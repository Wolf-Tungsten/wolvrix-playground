"""Capture five native F32 boundaries from raw FIRRTL, without evolution trace."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

from benchmark_f29_pass_trace import SplitProfile, native_identity, sha256, write_json_atomic
from benchmark_f30_gsim import freeze_native
from benchmark_f30_pipeline import (verified_dependencies, verified_input_request,
                                    verify_loaded_native, verify_package_identity)
from benchmark_f31_dce import environment, process_tree_sample
from benchmark_xs_firrtl_ingest import checked
from f30_resource_guard import GuardLimits, run_guarded


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'wolvrix.f32.pipeline-capture.v1'
PREFIX = ('xmr-resolve', 'hier-flatten', 'comb-loop-elim', 'split-static-array', 'dead-code-elim')
WINDOW = ('expr-opt', 'used-bits', 'split-nodes', 'dead-code-elim')
GRH_STAGES = ('post-first-dead-code-elim', 'post-expr-opt', 'post-used-bits',
              'post-split-nodes', 'post-second-dead-code-elim')
GSIM_STAGES = ('RemoveDeadNodes0', 'ExprOpt', 'UsedBits', 'SplitNodes', 'RemoveDeadNodes1')
GSIM_PASS_KEYS = ('ExprOpt#0', '{g->usedBits()}#0', '{g->splitNodes()}#0', 'RemoveDeadNodes1#0')


def action(result, label):
    if isinstance(result, dict):
        if result.get('success') is not True:
            raise RuntimeError(label + ' failed: ' + str(result))
    else:
        checked(result, label)


def native_rows(path, engine):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    expected = engine + '-stage-timing.v1'
    for row in rows:
        seconds = row.get('wall_s')
        if (row.get('schema') != expected or row.get('complete') is not True or
                row.get('clock') != 'steady_clock' or type(seconds) not in (float, int) or
                not math.isfinite(seconds) or seconds < 0):
            raise ValueError('invalid native timing evidence: ' + str(path))
    return rows


def table_artifact(path):
    """Check and hash a large TSV in one bounded-memory read after graph release."""
    import hashlib
    digest = hashlib.sha256()
    first = last = None
    rows = -1  # the column header is not a data row
    total = 0
    with path.open('rb') as stream:
        for line in stream:
            digest.update(line)
            total += len(line)
            if first is None:
                first = line
            if line.startswith(b'#footer\t'):
                if last is not None:
                    raise ValueError('duplicate TSV footer: ' + str(path))
                last = line
            elif last is not None:
                raise ValueError('data after TSV footer: ' + str(path))
            elif not line.startswith(b'#'):
                rows += 1
    if not first or not first.startswith(b'#meta\t') or last is None:
        raise ValueError('missing native TSV metadata/footer: ' + str(path))
    meta, footer = json.loads(first[6:]), json.loads(last[8:])
    if footer.get('complete') is not True or footer.get('rowCount') != rows:
        raise ValueError('incomplete native TSV: ' + str(path))
    return {'path': str(path), 'bytes': total, 'sha256': digest.hexdigest(),
            'metadata': meta, 'footer': footer}


def progress(report, summary, name, function, **details):
    started = time.monotonic()
    report['active_stage'] = {'name': name, 'finished': False, 'started_monotonic_s': started}
    write_json_atomic(summary, report)
    print(json.dumps({'event': 'stage-started', 'stage': name}), flush=True)
    result = function()
    row = {'stage': name, 'wall_s': time.monotonic() - started, **details}
    report['stages'].append(row)
    report['active_stage'] = {'name': name, 'finished': True}
    write_json_atomic(summary, report)
    print(json.dumps({'event': 'stage-finished', **row}), flush=True)
    return result, row


def release_snapshot_cache(args, report, paths, point, *, sync):
    """Advise on closed capture artifacts outside native pass timers."""
    if not getattr(args, 'release_snapshot_cache', True):
        return
    from release_f32_cache import release_files
    started = time.monotonic()
    result = release_files(paths, sync=sync, minimum_bytes=8 * 1024**2)
    record = {'point': point, 'sync': sync, 'minimum_bytes': 8 * 1024**2,
              'wall_s': time.monotonic() - started, **result}
    report.setdefault('snapshot_cache_release', []).append(record)
    print(json.dumps({'event': 'snapshot-cache-release', **record}), flush=True)


def failed_pass_diagnostics(session, args, report, summary, name, logical_instance, pass_error):
    """Best-effort physical evidence from a failed, potentially mutated graph."""
    directory = args.output / 'failed-diagnostics' / logical_instance.replace('#', '-')
    structure = directory / 'design.json'
    record = {'pass': name, 'logical_instance': logical_instance, 'status': 'saving',
              'non_authoritative': True, 'mutated_failed_state': True,
              'structure': str(structure), 'pass_error': repr(pass_error),
              'started_at_ns': time.time_ns()}
    report.setdefault('failure_diagnostics', []).append(record)
    report.update(status='failed', error=repr(pass_error))

    def persist():
        try:
            write_json_atomic(summary, report)
        except Exception as error:
            record.setdefault('report_errors', []).append(repr(error))

    persist()
    try:
        directory.mkdir(parents=True)
        result = session.store_json(
            design='design.main', output=str(structure), mode='pretty-compact',
            top=[args.top] if args.top else [], emit_def_users=False, emit_source_locations=False)
        action(result, logical_instance + ' failed-state store_json')
        if not structure.is_file() or structure.stat().st_size == 0:
            raise RuntimeError('failed-state store_json did not write a nonempty file')
        record.update(status='saved', bytes=structure.stat().st_size)
    except Exception as error:
        record.update(status='save_failed', error=repr(error))
    finally:
        try:
            # A failed store may also leave a closed partial file. Its pages
            # need the same cache advice; it remains explicitly nonauthoritative.
            if structure.is_file():
                record['bytes'] = structure.stat().st_size
                release_snapshot_cache(args, report, [structure],
                                       logical_instance + '-closed-failed-diagnostics', sync=True)
        except Exception as error:
            record['cache_release_error'] = repr(error)
        record['finished_at_ns'] = time.time_ns()
        persist()


def grh_session(session, args, report, summary, request):
    """Native sequence kept separate so its stop/capture contract is testable."""
    session.log_level = 'error'
    session.diagnostics_raise_min_level = 'none'
    timings = args.output / 'timings'
    timings.mkdir()
    report['pass_calls'] = []

    def run_pass(name, logical_instance, prefix):
        timing = timings / (logical_instance.replace('#', '-') + '.jsonl')
        kwargs = {'top': args.top} if args.top and name in WINDOW[:3] else {}
        if name in WINDOW[:3]:
            kwargs['semantics'] = getattr(args, 'semantics', '2state')
        profile = None
        profile_record = None
        if name == 'split-nodes' and getattr(args, 'profile_split_nodes', False):
            profile_directory = args.output / 'split-nodes-profile'
            profile_record = {'directory': str(profile_directory), 'status': 'setting-up',
                              'call_graph': 'dwarf,8192', 'frequency': 99,
                              'scope': 'split-nodes native call; setup and finish outside pass timer'}
            report['split_nodes_profile'] = profile_record
            profile, _ = progress(report, summary, logical_instance + '-profile-setup',
                                  lambda: SplitProfile(profile_directory))
            profile_record.update(status='sampling', symbols=profile.symbols, pid=profile.process.pid)

        def invoke():
            result = session.run_pass(
                name, design='design.main', keep_declared_symbols=name not in
                ('split-static-array', 'dead-code-elim', *WINDOW), timing_output=str(timing), **kwargs)
            action(result, logical_instance)
            return result

        pass_error = None
        try:
            _, row = progress(report, summary, logical_instance, invoke,
                prefix=prefix, logical_instance=logical_instance, timing_file=str(timing))
        except Exception as error:
            pass_error = error
            raise
        finally:
            try:
                if profile is not None:
                    primary_error = sys.exc_info()[1]
                    try:
                        progress(report, summary, logical_instance + '-profile-finish', profile.finish)
                        profile_record['status'] = 'completed'
                    except Exception as error:
                        profile_record.update(status='failed', error=repr(error))
                        if primary_error is None:
                            raise
                    finally:
                        write_json_atomic(summary, report)
            finally:
                if pass_error is not None and args.dump_structure:
                    failed_pass_diagnostics(session, args, report, summary, name, logical_instance, pass_error)
        native = native_rows(timing, 'grh')
        passes = [entry for entry in native if entry.get('scope') == 'pass']
        if len(passes) != 1 or passes[0].get('stage') != name:
            raise ValueError('GRH pass call has ambiguous timing identity: ' + logical_instance)
        report['pass_calls'].append({**row, 'pass': name, 'parameters': kwargs, 'native_timers': native})

    def snapshot(index):
        directory = args.output / f'P{index}'
        kwargs = {'top': args.top} if args.top else {}
        validation, _ = progress(report, summary, f'P{index}-semantic-validation',
                                  lambda: session.semantic_validate(design='design.main'))
        if validation.get('valid') is not True:
            raise RuntimeError('invalid SemanticTree at P' + str(index) + ': ' + str(validation))
        result, _ = progress(report, summary, f'P{index}-snapshot', lambda: session.semantic_snapshot(
            design='design.main', output=str(directory), stage=GRH_STAGES[index],
            **({'emit_serialization_id_map': True} if getattr(args, 'serialization_id_map', False) else {}), **kwargs))
        action(result, f'P{index} snapshot')
        if args.dump_structure:
            result, _ = progress(report, summary, f'P{index}-structure', lambda: session.store_json(
                design='design.main', output=str(directory / 'design.json'), mode='pretty-compact',
                top=[args.top] if args.top else [], emit_def_users=False, emit_source_locations=False))
            action(result, f'P{index} store_json')
        release_snapshot_cache(args, report, list(directory.iterdir()), f'P{index}-closed-snapshot', sync=True)
        report.setdefault('snapshots', {})[f'P{index}'] = {
            'directory': str(directory), 'stage': GRH_STAGES[index],
            'semantic_validation': validation,
            'structure': str(directory / 'design.json') if args.dump_structure else None}
        write_json_atomic(summary, report)

    result, _ = progress(report, summary, 'ingest', lambda: session.read_sources(
        **request, out_design='design.main', pipeline='ingest'))
    action(result, 'ingest')
    for name in PREFIX:
        run_pass(name, name + '#0', True)
    snapshot(0)
    for index, name in enumerate(WINDOW, 1):
        run_pass(name, name + ('#1' if name == 'dead-code-elim' else '#0'), False)
        snapshot(index)


def grh(args, report, summary):
    identity_file = args.package / 'identity.json'
    identity = verify_package_identity(args.package, identity_file)
    dependencies = verified_dependencies(args.package, args.package / 'dependencies.json', identity)
    request, sources = verified_input_request(args.firrtl, args.manifest)
    sys.meta_path[:] = [finder for finder in sys.meta_path
                        if not type(finder).__module__.startswith('_wolvrix_editable')]
    sys.path.insert(0, str(args.package))
    import wolvrix
    native = native_identity(wolvrix)
    verify_loaded_native(args.package, identity, native)
    report.update(native=native, package_identity=identity, dependencies=dependencies, sources=sources,
                  identity_file=str(identity_file), identity_sha256=sha256(identity_file),
                  manifest=str(args.manifest), manifest_sha256=sha256(args.manifest))
    with wolvrix.Session() as session:
        grh_session(session, args, report, summary, request)
    # Package, manifest and all actual inputs must still match the recorded run.
    verify_package_identity(args.package, identity_file)
    if sha256(args.manifest) != report['manifest_sha256']:
        raise ValueError('ingest manifest changed during capture')
    for source in sources:
        if sha256(Path(source['path'])) != source['sha256']:
            raise ValueError('actual source changed during capture: ' + source['path'])


def gsim_command(args, native, timing):
    model = args.output / 'model'
    command = [native['binary'], '--dir=' + str(model), '--semantic-node-exchange=' + str(args.output),
               '--semantic-node-exchange-mode=snapshot', '--semantic-node-exchange-stage=F32',
               '--stop-after-stage=RemoveDeadNodes1', '--timing-output=' + str(timing),
               '--trace-input-sha256=' + sha256(args.firrtl)]
    if args.dump_structure:
        command += ['--dump-json', '--dump-assign-tree', '--dump-stages=' + ','.join(GSIM_STAGES)]
    return [*command, str(args.firrtl)]


def gsim(args, report, summary):
    native, identity_file = freeze_native(args.binary, args.source_root, args.output)
    report.update(native=native, identity_file=str(identity_file), identity_sha256=sha256(identity_file))
    timing = args.output / 'native-timing.jsonl'
    command = gsim_command(args, native, timing)
    (args.output / 'model').mkdir()
    report['command'] = command
    report['active_stage'] = {'name': 'gsim-native-F32-pipeline', 'finished': False}
    write_json_atomic(summary, report)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    with (args.output / 'gsim.log').open('w') as log:
        result = subprocess.run(command, cwd=args.source_root, stdout=log, stderr=subprocess.STDOUT)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    report.update(native_returncode=result.returncode, native_user_s=after.ru_utime - usage.ru_utime,
                  native_system_s=after.ru_stime - usage.ru_stime, native_maxrss_kib=after.ru_maxrss)
    if result.returncode:
        raise RuntimeError('GSIM F32 pipeline failed: ' + str(result.returncode))
    rows = native_rows(timing, 'gsim')
    passes = [row for row in rows if row.get('scope') == 'pass']
    keys = [row.get('pass_instance') for row in passes]
    if keys[-4:] != list(GSIM_PASS_KEYS) or keys.count('RemoveDeadNodes#0') != 1:
        raise ValueError('GSIM did not execute exactly the intended four-pass window')
    if any(row.get('stage') in ('ConstantAnalysis', 'AliasAnalysis', 'PatternDetect', 'CommonExpr') for row in rows):
        raise ValueError('GSIM executed an out-of-scope successor')
    report.update(timing_file=str(timing), timing_sha256=sha256(timing), native_timers=rows,
                  logical_window=[{'logical_pass': name, 'logical_occurrence': 1 if index == 3 else 0,
                                   'native_timer': row} for index, (name, row) in enumerate(zip(WINDOW, passes[-4:]))])
    report['snapshots'] = {}
    for index, stage in enumerate(GSIM_STAGES):
        directory = args.output / f'P{index}'
        structure = None
        if args.dump_structure:
            candidates = sorted((args.output / 'model').glob(f'*_{index}{stage}.json'))
            if len(candidates) != 1:
                raise ValueError('missing/ambiguous full GSIM structure at ' + stage)
            structure = str(candidates[0])
        report['snapshots'][f'P{index}'] = {'directory': str(directory), 'stage': stage, 'structure': structure}
    if sha256(Path(native['binary'])) != native['sha256']:
        raise ValueError('frozen GSIM binary changed during capture')


def structure_artifact(path, engine):
    result = {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha256(path)}
    if engine == 'gsim':
        with path.open(encoding='utf-8') as stream:
            prefix = stream.read(4096).split('"nodes"', 1)[0]
        # Validate the native header without loading the full multi-GiB graph.
        header = json.loads(prefix.rstrip().rstrip(',') + '}')
        if (header.get('nodeStructureSchema') != 'gsim.node-structure.v1' or
                header.get('nodeStructureComplete') is not True or
                header.get('assignmentOrder') != 'native-vector-order'):
            raise ValueError('GSIM structure lacks the complete native functional-field contract')
        result.update(schema=header['nodeStructureSchema'], functional_fields_complete=True,
                      assignment_order=header['assignmentOrder'])
    return result


def finalize_snapshots(args, report):
    runs, snapshot_ids = set(), set()
    for index in range(5):
        record = report['snapshots'][f'P{index}']
        directory = Path(record['directory'])
        required = ['nodes.tsv', 'connections.tsv', 'bit-slices.tsv',
                    'node-endpoints.tsv' if args.engine == 'grh' else 'node-details.tsv']
        if args.engine == 'grh' and getattr(args, 'serialization_id_map', False):
            required.append('serialization-id-map.tsv')
        artifacts = {name: table_artifact(directory / name) for name in required}
        node_meta = artifacts['nodes.tsv']['metadata']
        if node_meta.get('engine') != args.engine or node_meta.get('stage') != record['stage']:
            raise ValueError('snapshot does not match its declared engine/boundary')
        if node_meta.get('input_identity', {}).get('sha256') not in (None, report['input_sha256']):
            raise ValueError('snapshot input identity differs from original FIRRTL')
        runs.add(node_meta['run_id'])
        snapshot_ids.add(node_meta['snapshot_id'])
        for name, artifact in artifacts.items():
            if artifact['metadata'].get('snapshot_id') != node_meta['snapshot_id']:
                raise ValueError('mixed snapshot artifacts at ' + str(directory))
        if 'serialization-id-map.tsv' in artifacts:
            mapping = artifacts['serialization-id-map.tsv']['metadata']
            if (mapping.get('schema') != 'grh.native-serialization-map.v1' or mapping.get('engine') != 'grh' or
                    any(mapping.get(key) != node_meta.get(key) for key in ('run_id', 'snapshot_id', 'stage', 'graph_id')) or
                    mapping.get('session_id') != node_meta.get('exchange_session_id') or
                    type(mapping.get('graph_index')) is not int or mapping['graph_index'] <= 0 or
                    str(mapping['graph_index']) != mapping['graph_id'] or
                    type(mapping.get('graph_generation')) is not int or mapping['graph_generation'] < 0 or
                    not isinstance(mapping.get('graph_symbol'), str) or not mapping['graph_symbol']):
                raise ValueError('serialization identity map has mixed native graph/session identity')
        if args.dump_structure:
            structure = Path(record['structure'])
            if not structure.is_file() or structure.stat().st_size == 0:
                raise ValueError('missing full native structure: ' + str(structure))
            artifacts['structure'] = structure_artifact(structure, args.engine)
        record.update(artifacts=artifacts, node_count=artifacts['nodes.tsv']['footer']['rowCount'])
        release_snapshot_cache(args, report, [Path(item['path']) for item in artifacts.values()],
                               f'P{index}-verified-artifacts', sync=False)
    if len(runs) != 1 or len(snapshot_ids) != 5:
        raise ValueError('F32 snapshots must share a run and have five distinct native snapshot IDs')
    report['snapshot_run_id'] = next(iter(runs))


def capture(args):
    summary = args.output / 'summary.json'
    report = {'schema': SCHEMA, 'engine': args.engine, 'status': 'running', 'source': 'raw-firrtl',
              'trace_enabled': False, 'trace_validation': False, 'formal_performance_sample': False,
              'window_semantics': getattr(args, 'semantics', '2state'),
              'full_structure': args.dump_structure,
              'serialization_id_map': getattr(args, 'serialization_id_map', False),
              'profile_split_nodes': getattr(args, 'profile_split_nodes', False),
              'snapshot_cache_policy': {'enabled': args.release_snapshot_cache, 'minimum_bytes': 8 * 1024**2,
                                        'after_grh_snapshot': 'fdatasync-and-POSIX_FADV_DONTNEED',
                                        'after_failed_grh_dump': 'fdatasync-and-POSIX_FADV_DONTNEED',
                                        'after_verification': 'POSIX_FADV_DONTNEED'},
              'scope': 'post-first-DCE through second-DCE inclusive; prefix and exports separately recorded',
              'input': str(args.firrtl), 'input_sha256': sha256(args.firrtl),
              'input_bytes': args.firrtl.stat().st_size, 'configuration': environment(),
              'script_sha256': sha256(Path(__file__).resolve()), 'started_at_ns': time.time_ns(), 'stages': []}
    started = time.monotonic()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    write_json_atomic(summary, report)
    try:
        if args.engine == 'grh':
            grh(args, report, summary)
        else:
            gsim(args, report, summary)
        report['active_stage'] = {'name': 'released-graph-artifact-verification', 'finished': False}
        write_json_atomic(summary, report)
        finalize_snapshots(args, report)
        if sha256(args.firrtl) != report['input_sha256']:
            raise ValueError('original FIRRTL changed during capture')
        report.update(status='completed', active_stage={'name': 'complete', 'finished': True})
    except BaseException as error:
        report.update(status='failed', error=repr(error))
        raise
    finally:
        after = resource.getrusage(resource.RUSAGE_SELF)
        report.update(finished_at_ns=time.time_ns(), wall_s=time.monotonic() - started,
                      supervisor_user_s=after.ru_utime - usage.ru_utime,
                      supervisor_system_s=after.ru_stime - usage.ru_stime, supervisor_maxrss_kib=after.ru_maxrss)
        write_json_atomic(summary, report)
    print(json.dumps({'status': report['status'], 'summary': str(summary),
                      'node_counts': {key: row['node_count'] for key, row in report['snapshots'].items()}}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=('grh', 'gsim'), required=True)
    parser.add_argument('--firrtl', type=Path, required=True)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--package', type=Path)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--source-root', type=Path, default=ROOT / 'reference/gsim')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--top', default=None)
    parser.add_argument('--semantics', choices=('2state', '4state'), default='2state',
                        help='window arithmetic interpretation; F32 uses explicit two-state simulation')
    parser.add_argument('--dump-structure', action='store_true', help='also export full native physical structure at all five boundaries')
    parser.add_argument('--serialization-id-map', action='store_true',
                        help='export native GRH physical-to-StoreJson identity maps (requires --dump-structure)')
    parser.add_argument('--release-snapshot-cache', action=argparse.BooleanOptionalAction, default=True,
                        help='advise the kernel to release closed snapshots and verified artifact file cache (default: enabled)')
    parser.add_argument('--resource-guard-rss-gib', type=float, default=96)
    parser.add_argument('--resource-guard-psi-percent', type=float, default=25)
    parser.add_argument('--resource-guard-psi-seconds', type=float, default=8)
    parser.add_argument('--resource-guard-interval-s', type=float, default=0.25)
    parser.add_argument('--split-nodes-timeout-seconds', type=float, default=0,
                        help='external GRH SplitNodes wall budget; 0 disables the deadline')
    parser.add_argument('--profile-split-nodes', action='store_true',
                        help='sample GRH SplitNodes CPU stacks; setup/finish stay outside its timer')
    parser.add_argument('--guard-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    for name in ('firrtl', 'manifest', 'package', 'binary', 'source_root', 'output'):
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, value.resolve())
    if not args.output.is_relative_to((ROOT / 'ptmp').resolve()) or args.output == (ROOT / 'ptmp').resolve():
        parser.error('output must be a new directory under repository ptmp/')
    if args.engine == 'grh' and (args.package is None or args.manifest is None):
        parser.error('GRH capture requires --package and --manifest')
    if args.engine == 'gsim' and args.binary is None:
        parser.error('GSIM capture requires --binary')
    if args.engine == 'gsim' and args.semantics != '2state':
        parser.error('GSIM F32 capture supports only two-state simulation semantics')
    if args.serialization_id_map and (args.engine != 'grh' or not args.dump_structure):
        parser.error('serialization ID map requires GRH --dump-structure')
    if not math.isfinite(args.split_nodes_timeout_seconds) or args.split_nodes_timeout_seconds < 0:
        parser.error('SplitNodes timeout must be nonnegative and finite')
    if args.split_nodes_timeout_seconds and args.engine != 'grh':
        parser.error('SplitNodes phase timeout currently requires GRH')
    if args.profile_split_nodes and args.engine != 'grh':
        parser.error('SplitNodes profiling currently requires GRH')
    if not math.isfinite(args.resource_guard_rss_gib) or args.resource_guard_rss_gib <= 0:
        parser.error('RSS GiB limit must be positive and finite')
    limits = GuardLimits(rss_bytes=int(args.resource_guard_rss_gib * 1024**3),
                         psi_percent=args.resource_guard_psi_percent,
                         psi_seconds=args.resource_guard_psi_seconds, interval_s=args.resource_guard_interval_s)
    try:
        limits.validate()
    except ValueError as error:
        parser.error(str(error))
    for name in ('WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC', 'WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC_NO_LIVENESS'):
        os.environ.pop(name, None)
    if not args.guard_child:
        if args.output.exists():
            parser.error('refusing to overwrite an existing output directory')
        args.output.mkdir(parents=True)
        timeouts = {'split-nodes#0': args.split_nodes_timeout_seconds} if args.split_nodes_timeout_seconds else None
        return run_guarded([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], '--guard-child'],
                           args.output, limits, sampler=process_tree_sample, phase_timeouts=timeouts)
    if (args.output / 'summary.json').exists() or any((args.output / f'P{index}').exists() for index in range(5)):
        parser.error('refusing to overwrite existing capture artifacts')
    capture(args)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
