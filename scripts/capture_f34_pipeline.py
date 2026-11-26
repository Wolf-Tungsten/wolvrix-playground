"""Capture the FIRRTL production R0–R4 window and lock GSIM pass references."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import fcntl
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from benchmark_f29_pass_trace import native_identity, sha256, write_json_atomic
from benchmark_f30_gsim import freeze_native
from benchmark_f30_pipeline import (verified_dependencies, verified_input_request,
                                    verify_loaded_native, verify_package_identity,
                                    verify_source_provenance)
from benchmark_f31_dce import process_tree_sample
from benchmark_f33_performance import environment, normalized_environment
from capture_f32_pipeline import action, native_rows, table_artifact
from capture_f33_pipeline import digest_json, validate_membership
from f30_resource_guard import GuardLimits
from f33_guard import F34, SupervisorLimits, Window, build_reference, run_guarded, sample_times, validate_reference


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'ptmp/firrtl-ingest/F34'
GSIM_ROOT = ROOT / 'reference/gsim'
GRH_STAGES = ('post-third-dead-code-elim', 'post-alias-analysis',
              'post-pattern-detect', 'post-common-expr', 'post-fourth-dead-code-elim')
GSIM_STAGES = ('RemoveDeadNodes2', *(stage for _, _, stage in F34.calls))
GRH_NAMES = ('alias-analysis', 'pattern-detect', 'comm-expr', 'dead-code-elim')
GSIM_STOP = GSIM_STAGES[-1]
ALIAS_WINDOW = Window('f34-alias', 'R', F34.calls[:1])
BASELINE = {'repository': 'fbeeeb57bb4a05831d474af8c381946777d3d77d',
            'wolvrix': '690a394ce00baf5b5666a617525259c4183d4050',
            'gsim': '052ef2d9937b175de8cc19a20a8af80a0498e57a'}
INHERITED = {'grh_nodes': 4616189, 'grh_unique_name_candidates': 4596538,
             'gsim_nodes': 5775134, 'gsim_execution_members': 4877861,
             'gsim_inline_constants': 897273,
             'f33_constant_analysis_over_formal_limit_s': 0.956,
             'f33_node_attribution_pending': True,
             'f32_review_items': ['U1', 'U2', 'U4'], 'f32_four_state_item': 'U3'}


def file_record(path):
    return {'path': str(path), 'sha256': sha256(path)}


def package_identity(path):
    identity = verify_package_identity(path, path / 'identity.json')
    dependencies = verified_dependencies(path, path / 'dependencies.json', identity)
    return identity, {
        'source_sha256': digest_json({'source': identity['source']['content_sha256'],
                                      'dependencies': dependencies['content_sha256']}),
        'binary_sha256': digest_json(identity['libraries']),
        'build': identity['build'],
    }


def configuration(args):
    window = ALIAS_WINDOW if args.mode == 'alias-capture' else F34
    return {**environment(), 'top': args.top, 'window': [list(call) for call in window.calls],
            'gsim_stop': window.calls[-1][2], 'grh_stop': window.passes[-1], 'node_maintenance': 'production'}


def prepare(args):
    _, grh = package_identity(args.package)
    _, sources = verified_input_request(args.firrtl, args.manifest)
    native, native_path = freeze_native(args.binary, GSIM_ROOT, args.output)
    verify_source_provenance(native)
    actual_input = next(row for row in sources if row['path'] == str(args.firrtl) and row['language'] == 'firrtl')
    identity = {
        'input': {'sha256': actual_input['sha256'], 'bytes': actual_input['bytes'],
                  'manifest_sha256': sha256(args.manifest), 'sources': sources},
        'configuration': configuration(args), 'semantics': '2state', 'batch_count': args.batch_count,
        'grh': grh,
        'gsim': {'source_sha256': native['source']['content_sha256'], 'binary_sha256': native['sha256'],
                 'build': {key: native[key] for key in
                           ('build_configuration_files', 'libraries', 'source_binding')}},
    }
    prepared = {'schema': 'wolvrix.f34.prepared.v1', 'identity': identity, 'baseline': BASELINE,
                'package_identity': file_record(args.package / 'identity.json'),
                'native_identity': file_record(native_path)}
    write_json_atomic(args.output / 'prepared.json', prepared)
    return prepared


def checked_prepared(args, prepared):
    identity = prepared['identity']
    if (prepared.get('schema') != 'wolvrix.f34.prepared.v1' or
            identity['configuration'] != configuration(args) or identity['batch_count'] != args.batch_count):
        raise ValueError('prepared F34 window or runtime configuration changed')
    package, actual_grh = package_identity(args.package)
    if actual_grh != identity['grh'] or file_record(args.package / 'identity.json') != prepared['package_identity']:
        raise ValueError('prepared GRH package changed')
    request, sources = verified_input_request(args.firrtl, args.manifest)
    if sources != identity['input']['sources'] or sha256(args.manifest) != identity['input']['manifest_sha256']:
        raise ValueError('prepared FIRRTL input or manifest changed')
    native_path = Path(prepared['native_identity']['path'])
    if file_record(native_path) != prepared['native_identity']:
        raise ValueError('prepared GSIM identity changed')
    native = json.loads(native_path.read_text())
    verify_source_provenance(native)
    if (sha256(Path(native['binary'])) != identity['gsim']['binary_sha256'] or
            any(file_record(Path(record['path'])) != record for record in native['libraries'])):
        raise ValueError('prepared GSIM binary or dependency changed')
    return package, request, native


def production_calls(pipeline):
    expected_prefix = ('xmr-resolve', 'hier-flatten', 'comb-loop-elim', 'split-static-array',
                       'dead-code-elim', 'expr-opt', 'used-bits', 'split-nodes', 'dead-code-elim',
                       'constant-analysis', 'dead-code-elim')
    singleton = ('remove-singleton-state-axis',)
    names = tuple(name for name, _ in pipeline)
    if names[2:3] == singleton:
        expected_prefix = expected_prefix[:2] + singleton + expected_prefix[2:]
    if names != expected_prefix + GRH_NAMES:
        raise ValueError('F34 requires the production prefix and four calls through fourth DCE')
    if (pipeline[-5][1] != {'keep_declared_symbols': False, 'drop_disabled_firrtl_assertions': True} or
            pipeline[-1][1] != {'keep_declared_symbols': False} or
            pipeline[-6][1].get('semantics') != '2state'):
        raise ValueError('F34 requires the production third/fourth DCE and ConstantAnalysis options')
    seen = {}
    calls = []
    for name, params in pipeline:
        canonical = 'common-expr' if name == 'comm-expr' else name
        ordinal = seen.get(canonical, 0)
        seen[canonical] = ordinal + 1
        options = dict(params)
        keep = options.pop('keep_declared_symbols', name in (
            'xmr-resolve', 'hier-flatten', 'remove-singleton-state-axis', 'comb-loop-elim'))
        calls.append((name, f'{canonical}#{ordinal}', keep, options))
    if tuple(logical for _, logical, _, _ in calls[-4:]) != F34.passes:
        raise ValueError('F34 production logical occurrences changed')
    return calls[:-4], calls[-4:]


def grh_timer(path, name, batch_count=None):
    rows = native_rows(path, 'grh')
    passes = [row for row in rows if row.get('scope') == 'pass']
    if len(passes) != 1 or (passes[0].get('stage'), passes[0].get('pass_instance')) != (name, name + '#0'):
        raise ValueError('missing or ambiguous GRH native pass timer: ' + name)
    row = passes[0]
    if batch_count is not None:
        members = row.get('native_member_times_s')
        native_sum = row.get('native_sum_s')
        if (len(rows) != 1 or row.get('batch_count') != batch_count or not isinstance(members, list) or
                len(members) != batch_count or any(type(x) not in (int, float) or not math.isfinite(x) or x < 0
                                                  for x in members) or
                type(native_sum) not in (int, float) or not math.isfinite(native_sum) or
                not math.isclose(sum(members), native_sum, rel_tol=1e-9, abs_tol=1e-12) or
                native_sum > row['wall_s']):
            raise ValueError('invalid GRH fresh-graph member timings: ' + name)
    return row


def record_stage(summary, report, name):
    report['active_stage'] = name
    write_json_atomic(summary, report)


def snapshot_indices(args):
    if args.mode == 'baseline':
        return range(1)
    if args.mode == 'alias-capture' or args.alias_snapshots:
        return range(2)
    return range(len(GRH_STAGES)) if args.snapshots else range(0)


def grh_run(args, package, request, report, summary):
    sys.meta_path[:] = [finder for finder in sys.meta_path
                        if not type(finder).__module__.startswith('_wolvrix_editable')]
    sys.path.insert(0, str(args.package))
    import wolvrix
    from wolvrix_xs_grhsim import firrtl_canonical_pipeline

    verify_loaded_native(args.package, package, native_identity(wolvrix))
    prefix, window = production_calls(firrtl_canonical_pipeline(remove_singleton_state_axis=False))
    if args.mode == 'alias-capture':
        window = window[:1]
    snapshots = snapshot_indices(args)
    timing_dir = args.output / 'timings'
    timing_dir.mkdir()
    report['prefix'] = []
    with ExitStack() as stack:
        sessions = [stack.enter_context(wolvrix.Session()) for _ in range(args.batch_count)]
        for index, session in enumerate(sessions):
            session.log_level = 'error'
            session.diagnostics_raise_min_level = 'none'
            record_stage(summary, report, 'ingest')
            started = time.monotonic()
            action(session.read_sources(**request, out_design='design.main', pipeline='ingest'), 'ingest')
            report['prefix'].append({'stage': 'ingest', 'graph': index, 'wall_s': time.monotonic() - started})
            for name, logical, keep, options in prefix:
                path = timing_dir / f'{index}-{logical}.jsonl'
                record_stage(summary, report, logical)
                action(session.run_pass(name, design='design.main', timing_output=str(path),
                                        keep_declared_symbols=keep, **options), logical)
                report['prefix'].append({'stage': logical, 'graph': index, 'options': options,
                                         'keep_declared_symbols': keep, 'native': grh_timer(path, name)})
        if 0 in snapshots:
            grh_snapshot(args, sessions[0], 0, report, summary)
            if args.r0_rhs:
                record_stage(summary, report, 'R0-rhs-signature-export')
                action(sessions[0].semantic_snapshot(design='design.main', output=str(args.output / 'R0'),
                                                     stage='R0', rhs_only=True), 'R0 RHS signatures')
        if args.mode == 'baseline':
            report.update(stop_boundary='R0', successor_calls=0)
            return []
        evidence = []
        report['pass_times_s'] = {}
        for index, (name, logical, keep, options) in enumerate(window, 1):
            path = timing_dir / f'{logical}.jsonl'
            record_stage(summary, report, logical)
            pass_options = dict(options)
            if logical == 'alias-analysis#0':
                trace_path = args.output / 'alias-analysis-migrations.jsonl'
                pass_options.update(trace_alias_migrations=str(trace_path),
                                    trace_input_sha256=report['reference_identity']['input']['sha256'])
            action(wolvrix._run_pass_batch(sessions, name, design='design.main', timing_output=str(path),
                                           stage_events=str(args.output / 'stage-events.jsonl'), run_id=args.run_id,
                                           logical_instance=logical, keep_declared_symbols=keep, **pass_options), logical)
            row = grh_timer(path, logical.split('#')[0], args.batch_count)
            report['pass_times_s'][logical] = row['wall_s']
            evidence.append({'kind': 'native-timing-' + logical, **file_record(path)})
            if logical == 'alias-analysis#0':
                evidence.append({'kind': 'alias-analysis-migrations', **file_record(trace_path)})
            if index in snapshots:
                grh_snapshot(args, sessions[0], index, report, summary)
        if args.mode == 'alias-capture':
            report.update(stop_boundary='R1', successor_calls=0)
            return evidence
        record_stage(summary, report, 'R4-semantic-validation')
        validation = [session.semantic_validate(design='design.main') for session in sessions]
        if any(row.get('valid') is not True for row in validation):
            raise ValueError('invalid GRH R4 SemanticTree')
        report.update(stop_boundary='R4', successor_calls=0, r4_semantic_validation=validation)
        return evidence


def grh_snapshot(args, session, index, report, summary):
    point, stage = f'R{index}', GRH_STAGES[index]
    record_stage(summary, report, point + '-semantic-validation')
    validation = session.semantic_validate(design='design.main')
    if validation.get('valid') is not True:
        raise ValueError('invalid GRH SemanticTree at ' + point)
    record_stage(summary, report, point + '-snapshot')
    options = {'top': args.top} if args.top else {}
    if args.detail_node_ids_file:
        options['detail_node_ids'] = json.loads(args.detail_node_ids_file.read_text())
    action(session.semantic_snapshot(design='design.main', output=str(args.output / point), stage=stage,
                                     **options), point)
    report['snapshots'][point] = {'semantic_validation': validation}


def gsim_times(rows, *, baseline=False, alias_only=False, batch_count=1):
    passes = [(row.get('pass_instance'), row.get('stage')) for row in rows if row.get('scope') == 'pass']
    if baseline:
        if not passes or passes[-1] != ('RemoveDeadNodes#1', 'RemoveDeadNodes2'):
            raise ValueError('GSIM R0 must stop after native third DCE')
        expected = []
    else:
        calls = ALIAS_WINDOW.calls if alias_only else F34.calls
        expected = [(timer, stage) for _, timer, stage in calls]
        count = len(expected)
        if passes[-count:] != expected or any(passes.count(pair) != 1 for pair in expected):
            raise ValueError('GSIM did not run the requested F34 passes once in order')
        if batch_count == 1 and (len(passes) <= count or
                                 passes[-count - 1] != ('RemoveDeadNodes#1', 'RemoveDeadNodes2')):
            raise ValueError('GSIM did not reach R0 from native third DCE')
    if any(row.get('stage') in ('Partition', 'GraphPartition', 'graphPartition') for row in rows):
        raise ValueError('GSIM ran a successor of R4')
    timers = {row['pass_instance']: row for row in rows if row.get('scope') == 'pass'}
    times = {}
    for logical, timer, _ in F34.calls[:len(expected)]:
        row = timers[timer]
        if row.get('batch_count', 1) != batch_count:
            raise ValueError('GSIM timer batch changed: ' + logical)
        times[logical] = row['wall_s']
    return times


def gsim_run(args, native, report, summary):
    timing = args.output / 'native-timing.jsonl'
    baseline = args.mode == 'baseline'
    alias_only = args.mode == 'alias-capture'
    stop = GSIM_STAGES[0] if baseline else GSIM_STAGES[1] if alias_only else GSIM_STOP
    model = args.output / 'model'
    model.mkdir()
    command = [native['binary'], '--dir=' + str(model),
               '--stop-after-stage=' + stop,
               '--timing-output=' + str(timing), '--run-id=' + args.run_id]
    if not baseline:
        command.append('--stage-events=' + str(args.output / 'stage-events.jsonl'))
    if args.mode in ('capture', 'alias-capture'):
        command += ['--trace-alias-analysis=' + str(args.output / 'alias-analysis-migrations.jsonl'),
                    '--trace-input-sha256=' + report['reference_identity']['input']['sha256']]
    if args.batch_count > 1:
        command.append('--f34-batch=' + str(args.batch_count))
    if baseline or alias_only or args.snapshots:
        snapshot_stage = 'F34R0' if baseline else 'F34Alias' if alias_only else 'F34'
        command += ['--semantic-node-exchange=' + str(args.output), '--semantic-node-exchange-mode=snapshot',
                    '--semantic-node-exchange-stage=' + snapshot_stage,
                    '--trace-input-sha256=' + report['reference_identity']['input']['sha256']]
    command.append(str(args.firrtl))
    report['command'] = command
    record_stage(summary, report, 'gsim-pipeline')
    with (args.output / 'gsim.log').open('x') as log:
        subprocess.run(command, cwd=GSIM_ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    rows = native_rows(timing, 'gsim')
    report.update(native_timers=rows,
                  pass_times_s=gsim_times(rows, baseline=baseline, alias_only=alias_only,
                                          batch_count=args.batch_count),
                  stop_boundary='R0' if baseline else 'R1' if alias_only else 'R4', successor_calls=0)
    evidence = [{'kind': 'native-timing', **file_record(timing)}]
    if args.mode in ('capture', 'alias-capture'):
        evidence.append({'kind': 'alias-analysis-migrations',
                         **file_record(args.output / 'alias-analysis-migrations.jsonl')})
    return evidence


def snapshot_artifacts(args, report):
    stages = GRH_STAGES if args.engine == 'grh' else GSIM_STAGES
    native_run, snapshot_ids = set(), set()
    for index in snapshot_indices(args):
        stage = stages[index]
        point = f'R{index}'
        directory = args.output / point
        names = ['nodes.tsv', 'connections.tsv', 'bit-slices.tsv']
        names += ['node-endpoints.tsv'] if args.engine == 'grh' else ['node-details.tsv', 'execution-membership.tsv']
        artifacts = {name: table_artifact(directory / name) for name in names}
        meta = artifacts['nodes.tsv']['metadata']
        if (meta.get('engine') != args.engine or meta.get('stage') != stage or
                meta.get('input_identity', {}).get('sha256') not in (None, report['reference_identity']['input']['sha256']) or
                any(artifact['metadata']['snapshot_id'] != meta['snapshot_id'] for artifact in artifacts.values())):
            raise ValueError('mixed snapshot artifacts at ' + point)
        native_run.add(meta['run_id'])
        snapshot_ids.add(meta['snapshot_id'])
        record = report['snapshots'].setdefault(point, {})
        record.update(stage=stage, node_count=artifacts['nodes.tsv']['footer']['rowCount'], artifacts=artifacts)
        if index == 0 and args.r0_rhs:
            name = 'rhs-root-signatures.tsv'
            rhs = table_artifact(directory / name)
            rhs_meta = rhs['metadata']
            if (rhs_meta.get('schema') != 'rhs-root-signature.v2' or rhs_meta.get('stage') != point or
                    rhs_meta.get('scope') != 'all' or rhs_meta.get('engine') != args.engine or
                    any(rhs_meta.get(key) != meta[key] for key in ('run_id', 'graph_id')) or
                    rhs['footer']['rowCount'] != record['node_count']):
                raise ValueError('R0 RHS signatures do not match the full node inventory')
            artifacts[name] = rhs
        if args.engine == 'gsim':
            record['execution_membership'] = validate_membership(directory, artifacts)
    if len(native_run) != 1 or len(snapshot_ids) != len(report['snapshots']):
        raise ValueError('F34 boundaries must share one run and have distinct snapshot identities')


def worker(args, prepared):
    summary = args.output / 'summary.json'
    report = {'schema': 'wolvrix.f34.capture.v1', 'status': 'running', 'mode': args.mode,
              'engine': args.engine, 'run_id': args.run_id, 'reference_identity': prepared['identity'],
              'fresh_graphs': args.batch_count, 'resource_interference': False, 'snapshots': {},
              'inherited_f33': INHERITED, 'valid_checkpoint': False}
    record_stage(summary, report, 'identity-verification')
    try:
        package, request, native = checked_prepared(args, prepared)
        evidence = (grh_run(args, package, request, report, summary) if args.engine == 'grh'
                    else gsim_run(args, native, report, summary))
        if snapshot_indices(args):
            record_stage(summary, report, 'snapshot-verification')
            snapshot_artifacts(args, report)
        if args.mode != 'baseline':
            evidence.append({'kind': 'stage-events', **file_record(args.output / 'stage-events.jsonl')})
        report.update(status='completed', valid_checkpoint=True, reference_evidence=evidence)
    except BaseException as error:
        report.update(status='failed', error=repr(error))
        raise
    finally:
        write_json_atomic(summary, report)


def launch(args, prepared, output, engine, reference=None):
    run_id = 'f34-' + uuid.uuid4().hex
    prepared_path = args.output / 'prepared.json'
    command = [sys.executable, str(Path(__file__).resolve()), '--mode=' + args.mode, '--engine=' + engine,
               '--output=' + str(output), '--prepared=' + str(prepared_path), '--run-id=' + run_id]
    command.extend('--' + key.replace('_', '-') + '=' + str(getattr(args, key))
                   for key in ('firrtl', 'manifest', 'package', 'binary', 'batch_count'))
    if args.top:
        command.append('--top=' + args.top)
    if args.snapshots:
        command.append('--snapshots')
    if args.alias_snapshots:
        command.append('--alias-snapshots')
    if args.r0_rhs:
        command.append('--r0-rhs')
    if args.detail_node_ids_file:
        command.append('--detail-node-ids-file=' + str(args.detail_node_ids_file))
    limits = SupervisorLimits(resources=GuardLimits(rss_bytes=int(args.rss_gib * 1024**3)),
                              prefix_s=args.prefix_timeout_s, between_passes_s=args.export_timeout_s,
                              suffix_s=args.export_timeout_s, overall_s=args.overall_timeout_s)
    code = run_guarded(command, output, run_id=run_id, engine=engine, identity=prepared['identity'],
                       reference=reference, limits=limits, sampler=process_tree_sample,
                       require_passes=args.mode != 'baseline', require_reference=args.mode != 'alias-capture',
                       window=ALIAS_WINDOW if args.mode == 'alias-capture' else F34)
    if code:
        raise RuntimeError('F34 worker failed: ' + str(output / 'guard.json'))
    path = output / 'summary.json'
    report = json.loads(path.read_text())
    guard_path = output / 'guard.json'
    guard = json.loads(guard_path.read_text())
    if (report.get('status') != 'completed' or guard.get('status') != 'completed' or
            guard['pass_times_s'] != report.get('pass_times_s', {})):
        raise ValueError('F34 worker completion does not match supervisor evidence')
    report['reference_evidence'].append({'kind': 'guard', **file_record(guard_path)})
    write_json_atomic(path, report)
    return report


def run_group(args):
    args.output.mkdir(parents=True, exist_ok=False)
    prepared = prepare(args)
    if args.mode == 'reference':
        samples = [json.loads(path.read_text()) for path in args.reuse_sample]
        for sample in samples:
            sample_times(sample, prepared['identity'], F34)
        if len({sample['run_id'] for sample in samples}) != len(samples):
            raise ValueError('duplicate GSIM reference run')
        for index in range(len(samples) + 1, args.samples + 1):
            samples.append(launch(args, prepared, args.output / f'sample-{index}', 'gsim'))
        result = build_reference(samples, prepared['identity'], F34)
        write_json_atomic(args.output / 'reference.json', result)
        print(json.dumps(result['passes'], indent=2))
    else:
        reference = json.loads(args.reference.read_text()) if args.reference else None
        if args.mode == 'capture' and args.engine == 'grh':
            validate_reference(reference, prepared['identity'], F34)
        report = launch(args, prepared, args.output, args.engine, reference)
        print(json.dumps({'stop_boundary': report['stop_boundary'], 'pass_times_s': report.get('pass_times_s'),
                          'node_counts': {point: row['node_count'] for point, row in report['snapshots'].items()}},
                         indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('baseline', 'reference', 'capture', 'alias-capture'), required=True)
    parser.add_argument('--engine', choices=('grh', 'gsim'), required=True)
    for name in ('firrtl', 'manifest', 'package', 'binary', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--prepared', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--run-id', help=argparse.SUPPRESS)
    parser.add_argument('--top')
    snapshots = parser.add_mutually_exclusive_group()
    snapshots.add_argument('--snapshots', action='store_true')
    snapshots.add_argument('--alias-snapshots', action='store_true',
                           help='export only R0 and R1 in a guarded GRH capture through R4')
    parser.add_argument('--detail-node-ids-file', type=Path,
                        help='JSON list of GRH Node IDs for native snapshot details')
    parser.add_argument('--r0-rhs', action='store_true',
                        help='export full R0 RHS signatures during GRH alias-capture')
    parser.add_argument('--batch-count', type=int, default=1)
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--reuse-sample', type=Path, action='append', default=[],
                        help='reuse a completed GSIM summary with the same frozen identity and raw evidence')
    parser.add_argument('--rss-gib', type=float, default=120)
    parser.add_argument('--prefix-timeout-s', type=float, default=1800)
    parser.add_argument('--export-timeout-s', type=float, default=1800)
    parser.add_argument('--overall-timeout-s', type=float, default=7200)
    args = parser.parse_args()
    for name in ('firrtl', 'manifest', 'package', 'binary', 'output', 'reference', 'prepared',
                 'detail_node_ids_file'):
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, value.resolve())
    if not args.output.is_relative_to(WORK) or args.output == WORK:
        parser.error('F34 artifacts must be under ptmp/firrtl-ingest/F34/')
    if not 1 <= args.batch_count <= 256 or (args.mode == 'baseline' and args.batch_count != 1):
        parser.error('expected 1..256 fresh graphs per batch, or one for baseline')
    if args.mode == 'alias-capture' and (args.batch_count != 1 or args.reference):
        parser.error('alias-capture records one graph and runs without a performance reference')
    if args.alias_snapshots and (args.engine != 'grh' or args.mode != 'capture'):
        parser.error('--alias-snapshots requires --mode=capture --engine=grh')
    if args.detail_node_ids_file and (args.engine != 'grh' or not snapshot_indices(args)):
        parser.error('--detail-node-ids-file requires GRH snapshots')
    if args.r0_rhs and (args.engine != 'grh' or args.mode != 'alias-capture'):
        parser.error('--r0-rhs requires --mode=alias-capture --engine=grh')
    if args.mode == 'reference' and (args.engine != 'gsim' or args.snapshots or args.samples < 3):
        parser.error('reference needs at least three independent GSIM processes with snapshots disabled')
    if args.reuse_sample and (args.mode != 'reference' or len(args.reuse_sample) > args.samples):
        parser.error('--reuse-sample requires reference mode and at most --samples summaries')
    if args.mode == 'capture' and args.engine == 'grh' and not (args.reference or args.prepared):
        parser.error('guarded GRH capture requires an identity-matched GSIM reference')
    normalized_environment()
    for name in ('WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC', 'WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC_NO_LIVENESS'):
        os.environ.pop(name, None)
    if args.prepared:
        if not args.run_id:
            parser.error('worker requires explicit run identity')
        worker(args, json.loads(args.prepared.read_text()))
        return
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / 'capture.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        run_group(args)


if __name__ == '__main__':
    main()
