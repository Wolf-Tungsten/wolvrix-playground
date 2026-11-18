"""Run fresh, interleaved formal F33 performance samples without exports."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
import uuid

from benchmark_f29_pass_trace import native_identity, sha256, write_json_atomic
from benchmark_f30_gsim import freeze_native
from benchmark_f30_pipeline import (verified_dependencies, verified_input_request,
                                    verify_loaded_native, verify_package_identity)
from benchmark_f31_dce import process_tree_sample
from benchmark_xs_firrtl_ingest import checked
from f30_resource_guard import GuardLimits
from f33_guard import (PASSES, SupervisorLimits, append_event, run_guarded,
                       build_reference, validate_identity)
from benchmark_f31_dce import environment
from capture_f32_pipeline import action, native_rows
import capture_f33_pipeline as f33_capture


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'wolvrix.f33.performance-sample.v1'
GROUP_SCHEMA = 'wolvrix.f33.performance-group.v1'
RESULT_SCHEMA = 'wolvrix.f33.performance-results.v1'
PREFIX = ('xmr-resolve', 'hier-flatten', 'comb-loop-elim', 'split-static-array',
          'dead-code-elim', 'expr-opt', 'used-bits', 'split-nodes', 'dead-code-elim')
GSIM_TIMERS = ('ConstantAnalysis#0', 'RemoveDeadNodes#1')
INSTRUMENTATION_ENV = ('WOLVRIX_HIER_FLATTEN_PROFILE', 'WOLVRIX_SIMPLIFY_PHASE_TIMING',
                       'WOLVRIX_CLE_DEBUG', 'WOLVRIX_GRHSIM_PERF',
                       'WOLVRIX_GRHSIM_SN_TIMING')


def environment():
    return {'machine': list(platform.uname()),
            'cpu_model': next((line.partition(':')[2].strip() for line in Path('/proc/cpuinfo').read_text().splitlines()
                               if line.startswith('model name')), platform.machine()),
            'thread_environment': {key: os.environ.get(key) for key in
                                   ('OMP_NUM_THREADS', 'OMP_PROC_BIND', 'TBB_NUM_THREADS', 'WOLVRIX_THREADS')},
            'loader_environment': {key: os.environ.get(key) for key in ('LD_LIBRARY_PATH', 'LD_PRELOAD')},
            'profiling_environment': {key: os.environ.get(key) for key in INSTRUMENTATION_ENV},
            'cpu_affinity': sorted(os.sched_getaffinity(0))}


def normalized_environment():
    os.environ.update(OMP_NUM_THREADS='1', OMP_PROC_BIND='FALSE',
                      TBB_NUM_THREADS='1', WOLVRIX_THREADS='1')
    for name in INSTRUMENTATION_ENV:
        os.environ.pop(name, None)


def timers(path, engine):
    rows = native_rows(path, engine)
    scopes = {}
    for row in rows:
        scope = scopes.setdefault(row.get('scope'), {})
        key = row.get('pass_instance')
        if not isinstance(key, str) or key in scope:
            raise ValueError('missing or duplicate native timer instance: ' + str(path))
        scope[key] = row
    return rows, scopes


def action_check(result, label):
    if isinstance(result, dict):
        if result.get('success') is not True:
            raise RuntimeError(label + ' failed: ' + str(result))
    else:
        checked(result, label)


def prefix_sample(session, request, directory, report, summary):
    timing_dir = directory / 'timings'
    timing_dir.mkdir()
    rows = []
    report['prefix'] = []
    session.log_level = 'error'
    session.diagnostics_raise_min_level = 'none'
    started = time.monotonic()
    report['active_stage'] = {'name': 'ingest', 'finished': False}
    write_json_atomic(summary, report)
    action_check(session.read_sources(**request, out_design='design.main', pipeline='ingest'), 'ingest')
    report['prefix'].append({'stage': 'ingest', 'wall_s': time.monotonic() - started})
    for index, name in enumerate(PREFIX):
        timing = timing_dir / (name + '-' + str(index) + '.jsonl')
        report['active_stage'] = {'name': name + '#0', 'finished': False}
        write_json_atomic(summary, report)
        options = {'semantics': '2state'} if name in ('expr-opt', 'used-bits', 'split-nodes') else {}
        if name == 'comb-loop-elim':
            options['fail_on_true_loop'] = True
        keep_declared = name in ('xmr-resolve', 'hier-flatten', 'comb-loop-elim')
        result = session.run_pass(name, design='design.main', keep_declared_symbols=keep_declared,
                                  timing_output=str(timing), **options)
        action_check(result, name)
        native, scopes = timers(timing, 'grh')
        stage = scopes.get('pass', {}).get(name + '#0')
        if stage is None or len(scopes['pass']) != 1:
            raise ValueError('ambiguous F33 prefix timer: ' + name)
        rows.append({'pass': name, 'native_timer': stage, 'timing_file': str(timing),
                     'timing_sha256': sha256(timing), 'all_native_timers': native})
    report['prefix_passes'] = rows
    report['active_stage'] = {'name': 'Q0-ready', 'finished': True}
    write_json_atomic(summary, report)
    return timing_dir


def grh_sample(args, group, summary):
    package = Path(group['package'])
    identity = verify_package_identity(package, package / 'identity.json')
    dependencies = verified_dependencies(package, package / 'dependencies.json', identity)
    if sha256(package / 'identity.json') != group['package_identity_sha256']:
        raise ValueError('frozen GRH package changed')
    request, sources = verified_input_request(group['input'], group['source_manifest'])
    if sources != group['sources']:
        raise ValueError('input source set differs from the frozen performance group')
    sys.meta_path[:] = [finder for finder in sys.meta_path
                        if not type(finder).__module__.startswith('_wolvrix_editable')]
    sys.path.insert(0, str(package))
    import wolvrix
    native = native_identity(wolvrix)
    verify_loaded_native(package, identity, native)
    report = {'schema': SCHEMA, 'status': 'running', 'engine': 'grh', 'run_id': args.run_id,
              'started_at_ns': time.time_ns(),
              'group_id': group['group_id'], 'input_sha256': group['input_sha256'],
              'configuration': group['configuration'], 'package_identity_sha256': group['package_identity_sha256'],
              'identity': group['identity'], 'resource_interference': False,
              'native': native, 'dependencies': dependencies, 'sources': sources,
              'instrumentation': {'trace': False, 'snapshots': False, 'export': False,
                                  'verify': False, 'profile': False}, 'active_stage': {'name': 'initialization'}}
    write_json_atomic(summary, report)
    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    with wolvrix.Session() as session:
        timing_dir = prefix_sample(session, request, args.output, report, summary)
        events = args.output / 'stage-events.jsonl'
        timings = []
        window_start = None
        window_end = None
        for name, logical, options in (
                ('constant-analysis', PASSES[0], {'semantics': '2state', 'top': args.top}),
                ('dead-code-elim', PASSES[1], {'drop_disabled_firrtl_assertions': True})):
            timing = timing_dir / (logical.replace('#', '-') + '.jsonl')
            append_event(events, run_id=args.run_id, engine='grh', logical_instance=logical,
                         event='start', batch_count=1)
            started = time.monotonic()
            report['active_stage'] = {'name': logical, 'finished': False,
                                      'started_monotonic_s': started}
            write_json_atomic(summary, report)
            started = time.monotonic()
            if window_start is None:
                window_start = started
            result = session.run_pass(name, design='design.main', keep_declared_symbols=False,
                                      timing_output=str(timing), **options)
            returned = time.monotonic()
            action_check(result, logical)
            if logical == PASSES[1]:
                window_end = returned
            native_rows_for_pass, scopes = timers(timing, 'grh')
            stage = scopes.get('pass', {}).get(name + '#0')
            if stage is None or len(scopes['pass']) != 1:
                raise ValueError('ambiguous F33 formal timer: ' + logical)
            wall = returned - started
            append_event(events, run_id=args.run_id, engine='grh', logical_instance=logical,
                         event='end', wall_s=wall, batch_count=1)
            timings.append({'logical_instance': logical, 'pass': name, 'wall_s': wall,
                            'native_timer': stage, 'timing_file': str(timing),
                            'timing_sha256': sha256(timing), 'all_native_timers': native_rows_for_pass})
            report['pass_times_s'] = {row['logical_instance']: row['native_timer']['wall_s'] for row in timings}
            report['active_stage'] = {'name': logical, 'finished': True}
            write_json_atomic(summary, report)
        validation = session.semantic_validate(design='design.main')
        if validation.get('valid') is not True:
            raise ValueError('F33 formal Q2 graph failed SemanticTree validation: ' + str(validation))
    usage_after = resource.getrusage(resource.RUSAGE_SELF)
    window = window_end - window_start
    native_sum = sum(row['native_timer']['wall_s'] for row in timings)
    report.update(status='passed', pass_times_s={row['logical_instance']: row['native_timer']['wall_s'] for row in timings},
                  guard_pass_times_s={row['logical_instance']: row['wall_s'] for row in timings},
                  passes=timings, window={'wall_s': window, 'native_pass_sum_s': native_sum,
                      'framework_overhead_s': window - native_sum,
                      'source': 'runner-monotonic', 'clock': 'steady_clock',
                      'start_after': 'ConstantAnalysis batch call begins at Q0',
                      'end_after': 'third DCE call returns at Q2'},
                  window_s=window,
                  metrics={**{row['logical_instance']: row['native_timer']['wall_s'] for row in timings}, 'window': window},
                  maxrss_kib=usage_after.ru_maxrss, user_s=usage_after.ru_utime - usage_before.ru_utime,
                  system_s=usage_after.ru_stime - usage_before.ru_stime,
                  event_file=str(events), event_sha256=sha256(events),
                  timing_files=[{'path': row['timing_file'], 'sha256': row['timing_sha256'],
                                 'rows': row['all_native_timers']} for row in timings],
                  semantic_validation=validation, active_stage={'name': 'complete', 'finished': True},
                  finished_at_ns=time.time_ns())
    write_json_atomic(summary, report)
    verify_package_identity(package, package / 'identity.json')


def gsim_sample(args, group, summary):
    native = json.loads(Path(group['gsim_identity']).read_text())
    if (sha256(Path(group['gsim_identity'])) != group['gsim_identity_sha256'] or
            sha256(Path(native['binary'])) != native['sha256']):
        raise ValueError('frozen GSIM identity or binary changed')
    for library in native.get('libraries', []):
        if sha256(Path(library['path'])) != library['sha256']:
            raise ValueError('frozen GSIM library changed: ' + library['path'])
    timing = args.output / 'native-timing.jsonl'
    model = args.output / 'model'
    model.mkdir()
    command = [native['binary'], '--dir=' + str(model), '--stop-after-stage=RemoveDeadNodes2',
               '--timing-output=' + str(timing), '--stage-events=' + str(args.output / 'stage-events.jsonl'),
               '--run-id=' + args.run_id, str(group['input'])]
    report = {'schema': SCHEMA, 'status': 'running', 'engine': 'gsim', 'run_id': args.run_id,
              'started_at_ns': time.time_ns(),
              'group_id': group['group_id'], 'input_sha256': group['input_sha256'],
              'configuration': group['configuration'], 'identity': group['identity'],
              'resource_interference': False, 'fresh_graphs': 1, 'command': command,
              'instrumentation': {'trace': False, 'snapshots': False, 'export': False,
                                  'verify': False, 'profile': False},
              'active_stage': {'name': 'raw-firrtl-prefix', 'finished': False}}
    write_json_atomic(summary, report)
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    with (args.output / 'gsim.log').open('x') as log:
        result = subprocess.run(command, cwd=group['gsim_source_root'], stdout=log,
                                stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError('GSIM F33 sample failed with status ' + str(result.returncode))
    rows, scopes = timers(timing, 'gsim')
    passes = scopes.get('pass', {})
    stages = ('ConstantAnalysis', 'RemoveDeadNodes2')
    if [row.get('stage') for row in (passes.get(GSIM_TIMERS[0]), passes.get(GSIM_TIMERS[1]))] != list(stages):
        raise ValueError('GSIM did not reach both F33 performance passes')
    window_row = scopes.get('window', {}).get('F33Window#0')
    if window_row is None or window_row.get('stage') != 'F33Window':
        raise ValueError('GSIM continuous F33 window timer is missing')
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    event_path = args.output / 'stage-events.jsonl'
    report.update(status='passed', native_timers=rows, timing_file=str(timing),
                  timing_sha256=sha256(timing), event_file=str(event_path), event_sha256=sha256(event_path),
                  timing_files=[{'path': str(timing), 'sha256': sha256(timing), 'rows': rows}],
                  pass_times_s={PASSES[0]: passes[GSIM_TIMERS[0]]['wall_s'],
                                PASSES[1]: passes[GSIM_TIMERS[1]]['wall_s']},
                  passes=[{'logical_instance': logical, 'native_timer': passes[timer]}
                          for logical, timer in zip(PASSES, GSIM_TIMERS)],
                  window={'wall_s': window_row['wall_s'], 'native_timer': window_row,
                          'source': 'native', 'clock': 'steady_clock'},
                  window_s=window_row['wall_s'],
                  metrics={PASSES[0]: passes[GSIM_TIMERS[0]]['wall_s'],
                           PASSES[1]: passes[GSIM_TIMERS[1]]['wall_s'], 'window': window_row['wall_s']},
                  wall_s=time.monotonic() - started,
                  user_s=after.ru_utime - before.ru_utime, system_s=after.ru_stime - before.ru_stime,
                  native_returncode=result.returncode, active_stage={'name': 'complete', 'finished': True},
                  finished_at_ns=time.time_ns())
    write_json_atomic(summary, report)


def sample(args):
    normalized_environment()
    group_path = args.group.resolve()
    group = json.loads(group_path.read_text())
    if group.get('schema') != GROUP_SCHEMA or group.get('status') != 'frozen':
        raise ValueError('invalid frozen F33 formal performance group')
    body = dict(group)
    digest = body.pop('manifest_sha256', None)
    if hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest() != digest:
        raise ValueError('F33 performance group digest mismatch')
    validate_identity(group['identity'])
    observed_configuration = environment()
    for key, value in observed_configuration.items():
        if group['configuration'].get(key) != value:
            raise ValueError('sample process environment differs from frozen configuration: ' + key)
    if (sha256(Path(group['input'])) != group['input_sha256'] or
            sha256(Path(group['source_manifest'])) != group['source_manifest_sha256']):
        raise ValueError('F33 performance input or source manifest changed')
    for source in group['sources']:
        if sha256(Path(source['path'])) != source['sha256']:
            raise ValueError('frozen source changed: ' + source['path'])
    args.output.mkdir(parents=True, exist_ok=True)
    summary = args.output / 'summary.json'
    if summary.exists():
        raise ValueError('refusing to overwrite existing F33 performance sample')
    if args.engine == 'grh':
        grh_sample(args, group, summary)
    else:
        gsim_sample(args, group, summary)
    if sha256(Path(group['input'])) != group['input_sha256']:
        raise ValueError('F33 performance input changed during sample')


def schedule(count):
    return ['grh' if index % 2 == 0 else 'gsim' for index in range(count * 2)]


def run_group(args):
    normalized_environment()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'ptmp') or output.exists():
        raise ValueError('F33 performance output must be a new directory under ptmp')
    if args.repeats < 3:
        raise ValueError('F33 formal performance requires at least three samples per engine')
    if not 0 < args.rss_gib <= 144:
        raise ValueError('F33 resource guard RSS must be in (0, 144] GiB')
    output.mkdir(parents=True)
    if args.cpus:
        selected = set(args.cpus)
        if not selected or not selected <= set(os.sched_getaffinity(0)):
            raise ValueError('requested CPUs must be allowed by the current process')
        os.sched_setaffinity(0, selected)
    input_path, manifest_path = args.firrtl.resolve(), args.manifest.resolve()
    package, binary, source_root = args.package.resolve(), args.binary.resolve(), args.source_root.resolve()
    request, sources = verified_input_request(input_path, manifest_path)
    package_identity = verify_package_identity(package, package / 'identity.json')
    dependencies = verified_dependencies(package, package / 'dependencies.json', package_identity)
    if package_identity.get('build', {}).get('CMAKE_BUILD_TYPE') != 'Release':
        raise ValueError('F33 formal performance requires a frozen Release GRH package')
    prepared_dir = output / 'prepared'
    prepared_dir.mkdir()
    prepare_args = argparse.Namespace(firrtl=input_path, manifest=manifest_path, package=package,
        binary=binary, source_root=source_root, output=prepared_dir, top=args.top, batch_count=1,
        dump_structure=False, serialization_id_map=False, release_snapshot_cache=False)
    prepared, _ = f33_capture.prepare(prepare_args)
    identity = prepared['identity']
    configuration = environment()
    if any(configuration['profiling_environment'].values()):
        raise ValueError('profiling instrumentation must be disabled for formal samples')
    configuration['thread_environment']['GSIM_PARSER_THREADS'] = '1'
    configuration['instrumentation'] = {'trace': False, 'snapshot': False, 'export': False,
                                        'verify': False, 'profile': False, 'statistics': False}
    group = {'schema': GROUP_SCHEMA, 'status': 'frozen', 'group_id': uuid.uuid4().hex,
             'created_at_ns': time.time_ns(), 'input': str(input_path),
             'input_sha256': sha256(input_path), 'input_bytes': input_path.stat().st_size,
             'source_manifest': str(manifest_path), 'source_manifest_sha256': sha256(manifest_path),
             'sources': sources, 'package': str(package),
             'package_identity_sha256': sha256(package / 'identity.json'),
             'package_content_sha256': package_identity['source']['content_sha256'],
             'dependencies_sha256': dependencies['content_sha256'],
             'gsim_identity': prepared['native_identity'],
             'gsim_identity_sha256': sha256(Path(prepared['native_identity'])),
             'gsim_binary_sha256': prepared['native']['sha256'],
             'gsim_source_revision': prepared['native']['source_revision'],
             'gsim_source_root': str(source_root), 'configuration': configuration,
             'identity': identity,
             'repeats_per_engine': args.repeats,
             'measurement': {'mode': 'no-trace', 'window_semantics': '2state',
                             'source': 'raw-firrtl', 'exports': False,
                             'verification': False, 'profile': False, 'build_type': 'Release'},
             'limits': {'rss_bytes': int(args.rss_gib * 1024**3), 'psi_percent': 25, 'psi_seconds': 8,
                        'per_pass_budget_multiplier': 2},
             'schedule': schedule(args.repeats)}
    group['manifest_sha256'] = hashlib.sha256(json.dumps(group, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    group_path = output / 'group.json'
    write_json_atomic(group_path, group)
    results = {'schema': RESULT_SCHEMA, 'status': 'running', 'group_id': group['group_id'],
               'group_manifest': str(group_path), 'group_manifest_sha256': sha256(group_path), 'samples': [],
               'reference_samples': [], 'started_at_ns': time.time_ns()}
    results_path = output / 'results.json'
    write_json_atomic(results_path, results)
    limits = SupervisorLimits(resources=GuardLimits(rss_bytes=int(args.rss_gib * 1024**3),
                                                   psi_percent=25, psi_seconds=8))

    def launch_sample(engine, directory, sequence, reference=None, reference_sample=False):
        directory.mkdir(parents=True)
        run_id = 'f33-perf-' + uuid.uuid4().hex
        command = [sys.executable, str(Path(__file__).resolve()), '--sample', '--engine', engine,
                   '--group', str(group_path), '--output', str(directory), '--run-id', run_id,
                   '--top', args.top]
        started = time.time_ns()
        system_before = {'loadavg': Path('/proc/loadavg').read_text().split()[:3],
                         'MemAvailable': next(line for line in Path('/proc/meminfo').read_text().splitlines()
                                              if line.startswith('MemAvailable'))}
        try:
            guarded = run_guarded(command, directory, run_id=run_id, engine=engine,
                                  identity=identity, reference=reference,
                                  limits=limits, sampler=process_tree_sample, require_passes=True)
            status = 'completed' if guarded == 0 else 'failed'
        except BaseException as error:
            status = 'failed'
            write_json_atomic(directory / 'orchestrator-error.json', {'error': repr(error)})
        summary = directory / 'summary.json'
        row = {'sequence': sequence, 'engine': engine, 'run_id': run_id,
               'status': 'passed' if status == 'completed' else 'failed',
               'reference_sample': reference_sample, 'directory': str(directory),
               'summary_file': str(summary), 'summary_sha256': sha256(summary) if summary.exists() else None,
               'guard_file': str(directory / 'guard.json'),
               'guard_sha256': sha256(directory / 'guard.json') if (directory / 'guard.json').exists() else None,
               'started_at_ns': started, 'finished_at_ns': time.time_ns(), 'system_before': system_before}
        if summary.exists():
            sample_summary = json.loads(summary.read_text())
            evidence = []
            for kind, field in (('native-timing', 'timing_file'), ('stage-events', 'event_file')):
                if sample_summary.get(field):
                    path = Path(sample_summary[field])
                    if path.is_file():
                        evidence.append({'kind': kind, 'path': str(path), 'sha256': sha256(path)})
            guard_path = directory / 'guard.json'
            if guard_path.is_file():
                evidence.append({'kind': 'guard', 'path': str(guard_path), 'sha256': sha256(guard_path)})
            sample_summary['reference_evidence'] = evidence
            if status == 'completed' and reference_sample:
                sample_summary.update(status='completed', reference_identity=identity, fresh_graphs=1)
            elif status == 'completed':
                sample_summary.update(status='passed', identity=identity,
                                      window_s=sample_summary['window']['wall_s'])
            write_json_atomic(summary, sample_summary)
            row['summary_sha256'] = sha256(summary)
            row['native_status'] = sample_summary.get('status')
            row['started_at_ns'] = sample_summary['started_at_ns']
            row['finished_at_ns'] = sample_summary['finished_at_ns']
        return row

    reference_rows = []
    for index in range(1, 4):
        directory = output / 'reference-samples' / f'{index:02d}-gsim'
        directory.parent.mkdir(exist_ok=True)
        row = launch_sample('gsim', directory, index, reference_sample=True)
        results['reference_samples'].append(row)
        write_json_atomic(results_path, results)
        if row['status'] != 'passed':
            raise RuntimeError('GSIM reference sample failed; evidence retained at ' + row['directory'])
        reference_rows.append(json.loads(Path(row['summary_file']).read_text()))
    reference = build_reference(reference_rows, identity)
    reference_path = output / 'reference.json'
    write_json_atomic(reference_path, reference)
    results['reference'] = str(reference_path)
    results['reference_sha256'] = sha256(reference_path)
    write_json_atomic(results_path, results)

    for sequence, engine in enumerate(group['schedule'], 1):
        directory = output / 'samples' / f'{sequence:02d}-{engine}'
        row = launch_sample(engine, directory, sequence, reference=reference if engine == 'grh' else None)
        results['samples'].append(row)
        write_json_atomic(results_path, results)
        print(json.dumps({'event': 'sample-finished', **row}), flush=True)
    results.update(status='completed' if all(row['status'] == 'passed' for row in results['samples'])
                   else 'completed-with-failures', finished_at_ns=time.time_ns())
    write_json_atomic(results_path, results)
    print(json.dumps({'status': results['status'], 'results': str(results_path)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firrtl', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--package', type=Path)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--source-root', type=Path, default=ROOT / 'reference/gsim')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--cpus', type=int, nargs='*')
    parser.add_argument('--rss-gib', type=float, default=144)
    parser.add_argument('--top', default='SimTop')
    parser.add_argument('--sample', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--engine', choices=('grh', 'gsim'), help=argparse.SUPPRESS)
    parser.add_argument('--group', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--run-id', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.sample:
        normalized_environment()
        group = json.loads(args.group.read_text())
        if args.run_id is None or args.engine is None:
            parser.error('sample child requires --run-id and --engine')
        args.output.mkdir(parents=True, exist_ok=True)
        summary = args.output / 'summary.json'
        try:
            if args.engine == 'grh':
                grh_sample(args, group, summary)
            else:
                gsim_sample(args, group, summary)
        except BaseException as error:
            existing = json.loads(summary.read_text()) if summary.exists() else {}
            existing.update(schema=SCHEMA, status='failed', engine=args.engine,
                            run_id=args.run_id, error=repr(error), finished_at_ns=time.time_ns())
            write_json_atomic(summary, existing)
            raise
    else:
        for name in ('firrtl', 'manifest', 'package', 'binary'):
            if getattr(args, name) is None:
                parser.error('--' + name + ' is required')
        run_group(args)


if __name__ == '__main__':
    main()
