"""Capture F33 Q0/Q1/Q2 or collect three guarded GSIM reference runs."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import stat
import sys
import time
import uuid

from benchmark_f29_pass_trace import native_identity, sha256, write_json_atomic
from benchmark_f30_gsim import freeze_native
from benchmark_f30_pipeline import (verified_dependencies, verified_input_request,
                                    verify_loaded_native, verify_package_identity,
                                    verify_source_provenance)
from benchmark_f31_dce import environment, process_tree_sample
from capture_f32_pipeline import (PREFIX as RAW_PREFIX, WINDOW as F32_WINDOW,
                                  action, native_rows, progress,
                                  structure_artifact, table_artifact)
from f30_resource_guard import GuardLimits
from f33_guard import (GSIM_TIMERS, PASSES, SupervisorLimits,
                       build_reference, canonical, run_guarded, validate_identity,
                       validate_reference)


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'ptmp/firrtl-ingest/F33'
SCHEMA = 'wolvrix.f33.pipeline-capture.v1'
GRH_STAGES = ('post-second-dead-code-elim', 'post-constant-analysis', 'post-third-dead-code-elim')
GSIM_STAGES = ('RemoveDeadNodes1', 'ConstantAnalysis', 'RemoveDeadNodes2')
WINDOW = ('constant-analysis', 'dead-code-elim')


def release_files(paths, *, sync=False, minimum_bytes=8 * 1024**2):
    """Advise only closed regular F33 files; preserve F32's path contract."""
    result = {'operation': 'POSIX_FADV_DONTNEED', 'sync': sync, 'files': [], 'bytes': 0, 'errors': []}
    for value in paths:
        path = Path(value).absolute()
        if not path.is_relative_to(WORK) or path.resolve() != path:
            raise ValueError('cache advice requires nonsymlink F33 artifact paths')
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size < minimum_bytes:
            continue
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                actual = os.fstat(descriptor)
                if (not stat.S_ISREG(actual.st_mode) or actual.st_dev != info.st_dev or
                        actual.st_ino != info.st_ino):
                    raise ValueError('F33 artifact changed during cache advice')
                if sync:
                    os.fdatasync(descriptor)
                os.posix_fadvise(descriptor, 0, 0, os.POSIX_FADV_DONTNEED)
            finally:
                os.close(descriptor)
            result['files'].append({'path': str(path), 'bytes': actual.st_size})
            result['bytes'] += actual.st_size
        except OSError as error:
            result['errors'].append({'path': str(path), 'error': str(error)})
    return result


def release_snapshot_cache(args, report, paths, point, *, sync):
    if not getattr(args, 'release_snapshot_cache', True):
        return
    started = time.monotonic()
    result = release_files(paths, sync=sync)
    record = {'point': point, 'sync': sync, 'minimum_bytes': 8 * 1024**2,
              'wall_s': time.monotonic() - started, **result}
    report.setdefault('snapshot_cache_release', []).append(record)
    print(json.dumps({'event': 'snapshot-cache-release', **record}), flush=True)


def digest_json(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def prepare(args):
    """Bind both implementations before starting any matched functional worker."""
    package = verify_package_identity(args.package, args.package / 'identity.json')
    dependencies = verified_dependencies(args.package, args.package / 'dependencies.json', package)
    request, sources = verified_input_request(args.firrtl, args.manifest)
    native, native_path = freeze_native(args.binary, args.source_root, args.output)
    verify_source_provenance(native)
    identity = {'input': {'sha256': sha256(args.firrtl), 'bytes': args.firrtl.stat().st_size,
                          'manifest_sha256': sha256(args.manifest), 'sources': sources},
                'configuration': {**environment(), 'top': args.top, 'node_maintenance': 'production',
                                  'window': list(PASSES), 'capture_structure': args.dump_structure,
                                  'serialization_id_map': args.serialization_id_map,
                                  'release_snapshot_cache': args.release_snapshot_cache,
                                  'fresh_graph_batch': args.batch_count},
                'semantics': '2state', 'batch_count': args.batch_count,
                'grh': {'source_sha256': digest_json({'source': package['source']['content_sha256'],
                                                      'dependencies': dependencies['content_sha256']}),
                        'binary_sha256': digest_json(package['libraries']), 'build': package['build']},
                'gsim': {'source_sha256': native['source']['content_sha256'],
                         'binary_sha256': native['sha256'],
                         'build': {'configuration_files': native['build_configuration_files'],
                                   'libraries': native['libraries'],
                                   'source_binding': native['source_binding']}}}
    validate_identity(identity)
    prepared = {'schema': 'wolvrix.f33.prepared.v1', 'identity': identity,
                'package_identity_sha256': sha256(args.package / 'identity.json'),
                'native_identity': str(native_path), 'native_identity_sha256': sha256(native_path),
                'native': native, 'request': request, 'created_at_ns': time.time_ns()}
    path = args.output / 'prepared.json'
    write_json_atomic(path, prepared)
    return prepared, path


def verify_prepared(args):
    prepared = json.loads(args.prepared.read_text())
    if prepared.get('schema') != 'wolvrix.f33.prepared.v1':
        raise ValueError('invalid prepared F33 identity')
    validate_identity(prepared['identity'])
    actual = prepared['identity']
    if (sha256(args.firrtl) != actual['input']['sha256'] or
            sha256(args.manifest) != actual['input']['manifest_sha256'] or
            sha256(args.package / 'identity.json') != prepared['package_identity_sha256'] or
            sha256(Path(prepared['native']['binary'])) != actual['gsim']['binary_sha256'] or
            sha256(Path(prepared['native_identity'])) != prepared['native_identity_sha256']):
        raise ValueError('prepared F33 input/package/native identity changed')
    expected = dict(actual['configuration'])
    options = {'top': args.top, 'capture_structure': args.dump_structure,
               'serialization_id_map': args.serialization_id_map,
               'release_snapshot_cache': args.release_snapshot_cache,
               'fresh_graph_batch': args.batch_count}
    if any(expected.get(key) != value for key, value in options.items()) or actual['batch_count'] != args.batch_count:
        raise ValueError('actual CLI top/dump/cache/batch options differ from frozen reference configuration')
    for name, value in environment().items():
        if expected.get(name) != value:
            raise ValueError('runtime configuration changed: ' + name)
    for source in actual['input']['sources']:
        if sha256(Path(source['path'])) != source['sha256']:
            raise ValueError('prepared source changed: ' + source['path'])
    return prepared


def grh_session(session, args, report, summary, request, *, batch_runner):
    """Keep the native sequence injectable for stop/boundary contract tests."""
    return grh_sessions([session], args, report, summary, request, batch_runner=batch_runner)


def grh_sessions(sessions, args, report, summary, request, *, batch_runner):
    """Preconstruct independent Q0 graphs, then time only the two pass loops."""
    batch_count = getattr(args, 'batch_count', 1)
    if len(sessions) != batch_count or len({id(session) for session in sessions}) != batch_count:
        raise ValueError('calibration requires exactly batch_count distinct fresh sessions')
    for session in sessions:
        session.log_level = 'error'
        session.diagnostics_raise_min_level = 'none'
    session = sessions[0]
    timings = args.output / 'timings'
    timings.mkdir()
    report['pass_calls'] = []

    def run_pass(name, logical, prefix, selected=None, graph_index=None):
        targets = sessions if selected is None else [selected]
        paths = [timings / (logical.replace('#', '-') +
                 (('-graph-' + str(graph_index)) if prefix and batch_count > 1 else '') + '.jsonl')]
        options = {}
        if name in ('expr-opt', 'used-bits', 'split-nodes', 'constant-analysis'):
            options['semantics'] = '2state'
            if args.top:
                options['top'] = args.top
        if logical == 'dead-code-elim#2':
            options['drop_disabled_firrtl_assertions'] = True
        report['active_stage'] = {'name': logical, 'finished': False, 'prefix': prefix}
        write_json_atomic(summary, report)
        started = time.monotonic()
        keep = name not in ('split-static-array', 'dead-code-elim', *F32_WINDOW, *WINDOW)
        if prefix:
            results = [targets[0].run_pass(name, design='design.main', timing_output=str(paths[0]),
                                           keep_declared_symbols=keep, **options)]
        else:
            # Validation, option compilation and result serialization belong
            # outside the native event interval, including for a single graph.
            results = batch_runner(targets, name, design='design.main', timing_output=str(paths[0]),
                                   stage_events=str(args.output / 'stage-events.jsonl'),
                                   run_id=args.run_id, logical_instance=logical,
                                   keep_declared_symbols=keep, **options)
        returned = time.monotonic()
        if prefix:
            action(results[0], logical)
        else:
            action(results, logical)
        rows, native = [], []
        for path in paths:
            records = native_rows(path, 'grh')
            passes = [row for row in records if row.get('scope') == 'pass']
            if len(passes) != 1 or passes[0].get('stage') != name:
                raise ValueError('ambiguous GRH native timer identity: ' + logical)
            rows.extend(records)
            native.extend(passes)
        duration = sum(row['wall_s'] for row in native)
        native_sum = duration
        if not prefix:
            row = native[0]
            members = row.get('native_member_times_s')
            native_sum = row.get('native_sum_s')
            if (len(rows) != 1 or row.get('pass_instance') != name + '#0' or
                    row.get('batch_count') != batch_count or not isinstance(members, list) or
                    len(members) != batch_count or
                    any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
                        for value in members) or type(native_sum) not in (int, float) or
                    not math.isfinite(native_sum) or native_sum < 0 or
                    not math.isclose(sum(members), native_sum, rel_tol=1e-9, abs_tol=1e-12) or
                    native_sum > duration or duration > returned - started):
                raise ValueError('invalid aggregate GRH calibration timer: ' + logical)
            report.setdefault('pass_times_s', {})[logical] = duration
        report['pass_calls'].append({'pass': name, 'logical_instance': logical, 'prefix': prefix,
                                     'native_timers': rows, 'python_call_wall_s': returned - started,
                                     'native_pass_sum_s': native_sum,
                                     'batch_count': len(targets), 'graph_index': graph_index,
                                     'parameters': options, 'timing_file': str(paths[0]),
                                     'timing_files': [str(path) for path in paths]})
        report['active_stage'] = {'name': logical, 'finished': True}
        write_json_atomic(summary, report)

    def snapshot(index):
        point = 'Q' + str(index)
        directory = args.output / point
        validation, _ = progress(report, summary, point + '-semantic-validation',
                                  lambda: session.semantic_validate(design='design.main'))
        if validation.get('valid') is not True:
            raise ValueError('invalid SemanticTree at ' + point + ': ' + str(validation))
        options = {'top': args.top} if args.top else {}
        if args.serialization_id_map:
            options['emit_serialization_id_map'] = True
        result, _ = progress(report, summary, point + '-snapshot', lambda: session.semantic_snapshot(
            design='design.main', output=str(directory), stage=GRH_STAGES[index], **options))
        action(result, point + ' snapshot')
        if args.dump_structure:
            result, _ = progress(report, summary, point + '-structure', lambda: session.store_json(
                design='design.main', output=str(directory / 'design.json'), mode='pretty-compact',
                top=[args.top] if args.top else [], emit_def_users=False, emit_source_locations=False))
            action(result, point + ' store_json')
        release_snapshot_cache(args, report, list(directory.iterdir()), point + '-closed', sync=True)
        report.setdefault('snapshots', {})[point] = {'directory': str(directory), 'stage': GRH_STAGES[index],
                                                    'semantic_validation': validation,
                                                    'batch_count': batch_count,
                                                    'calibration_representative': batch_count > 1,
                                                    'structure': str(directory / 'design.json') if args.dump_structure else None}
        write_json_atomic(summary, report)

    for graph_index, current in enumerate(sessions):
        result, _ = progress(report, summary, 'ingest-graph-' + str(graph_index), lambda: current.read_sources(
            **request, out_design='design.main', pipeline='ingest'))
        action(result, 'ingest')
        for name in RAW_PREFIX:
            run_pass(name, name + '#0', True, current, graph_index)
        for name in F32_WINDOW:
            run_pass(name, name + ('#1' if name == 'dead-code-elim' else '#0'), True, current, graph_index)
    snapshot(0)
    for index, (name, logical) in enumerate(zip(WINDOW, PASSES), 1):
        run_pass(name, logical, False)
        snapshot(index)
    report['stop_boundary'] = 'Q2'


def grh(args, prepared, report, summary):
    identity = verify_package_identity(args.package, args.package / 'identity.json')
    dependencies = verified_dependencies(args.package, args.package / 'dependencies.json', identity)
    request, sources = verified_input_request(args.firrtl, args.manifest)
    if sources != prepared['identity']['input']['sources']:
        raise ValueError('actual manifest sources do not match prepared reference')
    sys.meta_path[:] = [finder for finder in sys.meta_path
                        if not type(finder).__module__.startswith('_wolvrix_editable')]
    sys.path.insert(0, str(args.package))
    import wolvrix
    native = native_identity(wolvrix)
    verify_loaded_native(args.package, identity, native)
    report.update(native=native, package_identity=identity, dependencies=dependencies)
    with ExitStack() as stack:
        sessions = [stack.enter_context(wolvrix.Session()) for _ in range(args.batch_count)]
        grh_sessions(sessions, args, report, summary, request, batch_runner=wolvrix._run_pass_batch)
    verify_package_identity(args.package, args.package / 'identity.json')


def gsim_command(args, native, timing):
    command = [native['binary'], '--dir=' + str(args.output / 'model'),
               '--semantic-node-exchange=' + str(args.output), '--semantic-node-exchange-mode=snapshot',
               '--semantic-node-exchange-stage=F33', '--stop-after-stage=RemoveDeadNodes2',
               '--stage-events=' + str(args.output / 'stage-events.jsonl'), '--run-id=' + args.run_id,
               '--timing-output=' + str(timing), '--trace-input-sha256=' + sha256(args.firrtl)]
    if args.batch_count > 1:
        command.append('--f33-batch=' + str(args.batch_count))
    if args.dump_structure:
        command += ['--dump-json', '--dump-assign-tree', '--dump-stages=' + ','.join(GSIM_STAGES)]
    return [*command, str(args.firrtl)]


def gsim(args, prepared, report, summary):
    timing = args.output / 'native-timing.jsonl'
    native = prepared['native']
    command = gsim_command(args, native, timing)
    (args.output / 'model').mkdir()
    report.update(command=command, native=native)
    write_json_atomic(summary, report)
    with (args.output / 'gsim.log').open('x') as log:
        result = subprocess.run(command, cwd=args.source_root, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError('GSIM F33 pipeline failed: ' + str(result.returncode))
    rows = native_rows(timing, 'gsim')
    passes = [row for row in rows if row.get('scope') == 'pass']
    prefix_valid = (sum(row.get('stage') == 'RemoveDeadNodes1' for row in passes) == 1
                    if args.batch_count == 1 else
                    len(passes) == 2 and len(rows) == 3 and
                    sum(row.get('stage') == 'F33BatchPrefix' and row.get('scope') == 'prefix'
                        for row in rows) == 1)
    if ([row.get('stage') for row in passes[-2:]] != list(GSIM_STAGES[1:]) or
            [row.get('pass_instance') for row in passes[-2:]] != [GSIM_TIMERS[key] for key in PASSES] or
            not prefix_valid or
            any(row.get('stage') in ('AliasAnalysis', 'PatternDetect', 'CommonExpr') for row in rows)):
        raise ValueError('GSIM did not stop at the unique intended third-DCE boundary')
    report.update(native_timers=rows, timing_file=str(timing),
                  pass_times_s={key: row['wall_s'] for key, row in zip(PASSES, passes[-2:])},
                  stop_boundary='Q2', snapshots={})
    if any(row.get('batch_count', 1) != args.batch_count for row in passes[-2:]):
        raise ValueError('GSIM aggregate timer batch count differs from paired configuration')
    for index, stage in enumerate(GSIM_STAGES):
        structure = None
        if args.dump_structure:
            candidates = list((args.output / 'model').glob('*_' + str(index) + stage + '.json'))
            # GSIM's physical dump index includes prefix dumps when selected.
            if len(candidates) != 1:
                candidates = list((args.output / 'model').glob('*' + stage + '.json'))
            if len(candidates) != 1:
                raise ValueError('missing/ambiguous full GSIM structure: ' + stage)
            structure = str(candidates[0])
        report['snapshots']['Q' + str(index)] = {'directory': str(args.output / ('Q' + str(index))),
                                                'stage': stage, 'structure': structure,
                                                'batch_count': args.batch_count,
                                                'calibration_representative': args.batch_count > 1}


def membership_rows(path):
    """Stream native-ID ordered membership without constructing a full index."""
    header = None
    previous = -1
    with path.open() as stream:
        for line in stream:
            if line.startswith('#'):
                continue
            fields = line.rstrip('\n').split('\t')
            if header is None:
                header = fields
                continue
            if len(fields) != len(header):
                raise ValueError('invalid membership row shape')
            row = dict(zip(header, fields))
            node_id = int(row['node_id'])
            if node_id <= previous:
                raise ValueError('membership inventory native IDs are not unique and ordered')
            previous = node_id
            yield node_id, row


def validate_membership(directory, artifacts):
    membership = artifacts['execution-membership.tsv']
    nodes = artifacts['nodes.tsv']
    footer, meta = membership['footer'], nodes['metadata']
    counters = {'active_computation': 0, 'inline_constant_source': 0, 'source_catalog': 0}
    if (membership['metadata'].get('detail_schema') != 'gsim.f33.membership.v1' or
            membership['metadata'].get('table') != 'execution-membership' or
            any(membership['metadata'].get(key) != meta.get(key) for key in
                ('run_id', 'snapshot_id', 'stage', 'engine')) or
            footer.get('rowCount') != nodes['footer']['rowCount']):
        raise ValueError('invalid GSIM execution/inline-source/catalog membership identity')
    actual = iter(membership_rows(directory / 'execution-membership.tsv'))
    for node_id, _ in membership_rows(directory / 'nodes.tsv'):
        candidate = next(actual, None)
        if candidate is None or candidate[0] != node_id:
            raise ValueError('GSIM membership native IDs differ from Node inventory')
        row = candidate[1]
        kind = row['classification']
        if kind not in counters or any(row[key] not in ('0', '1') for key in
                                       ('execution_member', 'storage', 'external', 'input', 'output')):
            raise ValueError('invalid GSIM membership classification/flags')
        int(row['native_status'])
        executing = any(row[key] == '1' for key in ('execution_member', 'storage', 'external'))
        if executing != (kind == 'active_computation'):
            raise ValueError('GSIM membership active classification differs from native execution membership')
        counters[kind] += 1
    if next(actual, None) is not None:
        raise ValueError('extra GSIM membership IDs outside Node inventory')
    expected = dict(zip(('activeComputation', 'inlineConstantSource', 'sourceCatalog'), counters.values()))
    if any(type(footer.get(key)) is not int or footer[key] != value for key, value in expected.items()):
        raise ValueError('GSIM membership classification counts differ from footer')
    return expected


def finalize(args, report):
    runs, snapshots = set(), set()
    for index in range(3):
        point = 'Q' + str(index)
        record = report['snapshots'][point]
        directory = Path(record['directory'])
        names = ['nodes.tsv', 'connections.tsv', 'bit-slices.tsv',
                 'node-endpoints.tsv' if args.engine == 'grh' else 'node-details.tsv']
        if args.engine == 'gsim':
            names.append('execution-membership.tsv')
        if args.engine == 'grh' and args.serialization_id_map:
            names.append('serialization-id-map.tsv')
        artifacts = {name: table_artifact(directory / name) for name in names}
        meta = artifacts['nodes.tsv']['metadata']
        if (meta.get('engine') != args.engine or meta.get('stage') != record['stage'] or
                meta.get('input_identity', {}).get('sha256') not in (None, report['input_sha256'])):
            raise ValueError('snapshot identity mismatch: ' + point)
        for artifact in artifacts.values():
            if artifact['metadata'].get('snapshot_id') != meta.get('snapshot_id'):
                raise ValueError('mixed snapshot artifacts at ' + point)
        if args.engine == 'gsim':
            record['execution_membership'] = validate_membership(directory, artifacts)
        if args.serialization_id_map and args.engine == 'grh':
            mapping = artifacts['serialization-id-map.tsv']['metadata']
            if (mapping.get('schema') != 'grh.native-serialization-map.v1' or
                    any(mapping.get(key) != meta.get(key) for key in ('run_id', 'snapshot_id', 'stage', 'graph_id')) or
                    mapping.get('session_id') != meta.get('exchange_session_id')):
                raise ValueError('mixed native serialization identity at ' + point)
        if args.dump_structure:
            artifacts['structure'] = structure_artifact(Path(record['structure']), args.engine)
        record.update(artifacts=artifacts, node_count=artifacts['nodes.tsv']['footer']['rowCount'])
        runs.add(meta['run_id'])
        snapshots.add(meta['snapshot_id'])
        release_snapshot_cache(args, report, [Path(item['path']) for item in artifacts.values()],
                               point + '-verified', sync=False)
    if len(runs) != 1 or len(snapshots) != 3:
        raise ValueError('F33 boundaries must share one native run and three distinct snapshots')
    report['snapshot_run_id'] = next(iter(runs))


def capture(args):
    prepared = verify_prepared(args)
    summary = args.output / 'summary.json'
    if summary.exists() or any((args.output / ('Q' + str(i))).exists() for i in range(3)):
        raise ValueError('refusing to overwrite existing capture evidence')
    report = {'schema': SCHEMA, 'engine': args.engine, 'run_id': args.run_id, 'status': 'running',
              'source': 'raw-firrtl', 'window_semantics': '2state', 'trace_enabled': False,
              'formal_performance_sample': False, 'reference_identity': prepared['identity'],
              'fresh_graphs': args.batch_count, 'calibration_representative': args.batch_count > 1,
              'resource_interference': False, 'valid_checkpoint': False,
              'input': str(args.firrtl), 'input_sha256': sha256(args.firrtl), 'stages': [],
              'scope': 'Q0 second DCE input; ConstantAnalysis then third DCE; stop at Q2',
              'script_sha256': sha256(Path(__file__)), 'started_at_ns': time.time_ns()}
    started = time.monotonic()
    write_json_atomic(summary, report)
    try:
        (grh if args.engine == 'grh' else gsim)(args, prepared, report, summary)
        progress(report, summary, 'released-graph-artifact-verification', lambda: finalize(args, report))
        verify_prepared(args)
        report.update(status='completed', valid_checkpoint=True)
        evidence = [('stage-events', args.output / 'stage-events.jsonl')]
        evidence += ([('native-timing', args.output / 'native-timing.jsonl')] if args.engine == 'gsim' else
                     [('native-timing-' + row['logical_instance'] + '-graph-' + str(index), Path(path))
                      for row in report['pass_calls'] if not row['prefix']
                      for index, path in enumerate(row['timing_files'])])
        report['reference_evidence'] = [{'kind': kind, 'path': str(path), 'sha256': sha256(path)}
                                        for kind, path in evidence]
    except BaseException as error:
        report.update(status='failed', error=repr(error), valid_checkpoint=False)
        raise
    finally:
        report.update(finished_at_ns=time.time_ns(), wall_s=time.monotonic() - started)
        write_json_atomic(summary, report)
    return report


def launch(args, prepared_path, identity, output, engine, reference):
    output.mkdir(parents=True, exist_ok=True)
    run_id = 'f33-' + uuid.uuid4().hex
    command = [sys.executable, str(Path(__file__).resolve()), '--guard-child', '--mode=capture',
               '--engine=' + engine, '--firrtl=' + str(args.firrtl), '--manifest=' + str(args.manifest),
               '--package=' + str(args.package), '--binary=' + str(args.binary),
               '--source-root=' + str(args.source_root), '--output=' + str(output),
               '--prepared=' + str(prepared_path), '--run-id=' + run_id,
               '--batch-count=' + str(args.batch_count)]
    if args.top:
        command.append('--top=' + args.top)
    if args.dump_structure:
        command.append('--dump-structure')
    if args.serialization_id_map:
        command.append('--serialization-id-map')
    if not args.release_snapshot_cache:
        command.append('--no-release-snapshot-cache')
    limits = SupervisorLimits(resources=GuardLimits(rss_bytes=int(args.resource_guard_rss_gib * 1024**3)),
                              prefix_s=args.prefix_timeout_s, between_passes_s=args.export_timeout_s,
                              suffix_s=args.export_timeout_s, overall_s=args.overall_timeout_s)
    code = run_guarded(command, output, run_id=run_id, engine=engine, identity=identity,
                       reference=reference, limits=limits, sampler=process_tree_sample)
    if code:
        return code
    report = json.loads((output / 'summary.json').read_text())
    guard = json.loads((output / 'guard.json').read_text())
    if report.get('status') != 'completed' or guard.get('status') != 'completed':
        raise ValueError('capture lacks completed worker and guard evidence')
    if guard['pass_times_s'] != report['pass_times_s']:
        raise ValueError('native timers differ from guarded completion events')
    report['resource_interference'] = guard['resource_interference']
    report['reference_evidence'].append({'kind': 'guard', 'path': str(output / 'guard.json'),
                                         'sha256': sha256(output / 'guard.json')})
    write_json_atomic(output / 'summary.json', report)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('capture', 'reference'), default='capture')
    parser.add_argument('--engine', choices=('gsim', 'grh'), default='grh')
    for name in ('firrtl', 'manifest', 'package', 'binary', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT / 'reference/gsim')
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--batch-count', type=int, default=1,
                        help='independent fresh Q0 graphs per calibration batch; both engines must match')
    parser.add_argument('--top')
    parser.add_argument('--dump-structure', action='store_true')
    parser.add_argument('--serialization-id-map', action='store_true')
    parser.add_argument('--release-snapshot-cache', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--resource-guard-rss-gib', type=float, default=96)
    parser.add_argument('--prefix-timeout-s', type=float, default=1800)
    parser.add_argument('--export-timeout-s', type=float, default=1800)
    parser.add_argument('--overall-timeout-s', type=float, default=7200)
    parser.add_argument('--guard-child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--prepared', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--run-id', help=argparse.SUPPRESS)
    args = parser.parse_args()
    for name in ('firrtl', 'manifest', 'package', 'binary', 'output', 'source_root', 'reference', 'prepared'):
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, value.resolve())
    if not args.output.is_relative_to(WORK) or args.output == WORK:
        parser.error('output must be a fresh directory under ptmp/firrtl-ingest/F33/')
    if args.serialization_id_map and not args.dump_structure:
        parser.error('serialization identity map requires --dump-structure')
    if args.samples < 3:
        parser.error('reference collection requires at least three GSIM runs')
    if args.batch_count < 1 or args.batch_count > 256:
        parser.error('batch count must be an integer between 1 and 256')
    for name in ('WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC', 'WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC_NO_LIVENESS'):
        os.environ.pop(name, None)
    if args.guard_child:
        if not args.prepared or not args.run_id:
            parser.error('guard child requires prepared identity and run_id')
        capture(args)
        return 0
    if args.output.exists():
        parser.error('refusing to overwrite existing capture/reference/failure evidence')
    if args.mode == 'capture' and args.engine == 'grh' and args.reference is None:
        parser.error('paired GRH capture requires an identity-matched GSIM --reference')
    args.output.mkdir(parents=True)
    prepared, prepared_path = prepare(args)
    identity = prepared['identity']
    if args.mode == 'reference':
        samples = []
        for index in range(args.samples):
            output = args.output / ('sample-' + str(index + 1))
            code = launch(args, prepared_path, identity, output, 'gsim', None)
            if code:
                return code
            samples.append(json.loads((output / 'summary.json').read_text()))
        reference = build_reference(samples, identity)
        write_json_atomic(args.output / 'reference.json', reference)
        print(json.dumps({'status': 'completed', 'reference': str(args.output / 'reference.json'),
                          'passes': reference['passes']}), flush=True)
        return 0
    reference = json.loads(args.reference.read_text()) if args.reference else None
    if args.engine == 'grh':
        validate_reference(reference, identity)
    return launch(args, prepared_path, identity, args.output, args.engine, reference)


if __name__ == '__main__':
    raise SystemExit(main())
