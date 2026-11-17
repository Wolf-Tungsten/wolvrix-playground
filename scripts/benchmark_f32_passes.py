"""Run fresh, no-export, interleaved F32 performance samples from raw FIRRTL."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import statistics
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
from f30_resource_guard import GuardLimits, run_guarded

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'wolvrix.f32.pass-benchmark.v1'
GROUP_SCHEMA = 'wolvrix.f32.pass-benchmark-group.v1'
RESULT_SCHEMA = 'wolvrix.f32.pass-benchmark-results.v1'
PREFIX = ('xmr-resolve', 'hier-flatten', 'comb-loop-elim', 'split-static-array', 'dead-code-elim')
WINDOW = ('expr-opt', 'used-bits', 'split-nodes', 'dead-code-elim')
GSIM_WINDOW = {
    'ExprOpt#0': 'expr-opt',
    '{g->usedBits()}#0': 'used-bits',
    '{g->splitNodes()}#0': 'split-nodes',
    'RemoveDeadNodes1#0': 'dead-code-elim',
}
INSTRUMENTATION_ENV = ('WOLVRIX_HIER_FLATTEN_PROFILE', 'WOLVRIX_SIMPLIFY_PHASE_TIMING',
                       'WOLVRIX_CLE_DEBUG', 'WOLVRIX_SPLIT_NODES_PROFILE',
                       'WOLVRIX_SPLIT_NODES_TIMING', 'WOLVRIX_GRHSIM_PERF')


def environment():
    return {'machine': list(platform.uname()),
            'cpu_model': next((line.partition(':')[2].strip() for line in
                               Path('/proc/cpuinfo').read_text().splitlines()
                               if line.startswith('model name')), platform.machine()),
            'thread_environment': {key: os.environ.get(key) for key in
                                   ('OMP_NUM_THREADS', 'OMP_PROC_BIND', 'TBB_NUM_THREADS', 'WOLVRIX_THREADS')},
            'loader_environment': {key: os.environ.get(key) for key in ('LD_LIBRARY_PATH', 'LD_PRELOAD')},
            'profiling_environment': {key: os.environ.get(key) for key in INSTRUMENTATION_ENV},
            'cpu_affinity': sorted(os.sched_getaffinity(0))}


def timers(path, engine):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    result = {}
    for row in rows:
        if (row.get('schema') != engine + '-stage-timing.v1' or
                row.get('clock') != 'steady_clock' or row.get('complete') is not True or
                type(row.get('wall_s')) not in (int, float) or not math.isfinite(row['wall_s']) or row['wall_s'] < 0):
            raise ValueError('invalid native timer row in ' + str(path))
        key = row.get('pass_instance')
        if not isinstance(key, str) or not key:
            raise ValueError('native timer lacks pass_instance')
        scope = result.setdefault(row.get('scope'), {})
        if key in scope:
            raise ValueError('duplicate native timer scope/instance')
        scope[key] = row
    return rows, result


def normalized_environment():
    # Both engines use a single worker. Keep the loader inherited from the
    # caller, but explicitly remove profiling switches from the sample.
    os.environ.update(OMP_NUM_THREADS='1', OMP_PROC_BIND='FALSE',
                      TBB_NUM_THREADS='1', WOLVRIX_THREADS='1')
    for name in INSTRUMENTATION_ENV:
        os.environ.pop(name, None)


def tool_source_identity():
    return {'schema': 'wolvrix.f32.benchmark-tools.v1',
            'files': [{'path': str(path.resolve()), 'sha256': sha256(path)} for path in
                      (ROOT / 'scripts/benchmark_f32_passes.py', ROOT / 'scripts/f30_resource_guard.py')]}


def verify_tool_sources(frozen):
    actual = tool_source_identity()
    if frozen != actual:
        raise ValueError('benchmark runner or resource guard changed after group freeze')
    return actual


def verify_child_environment(configuration):
    actual = environment()
    changed = [key for key, value in actual.items() if configuration.get(key) != value]
    if changed:
        raise ValueError('actual child environment differs from frozen group: ' + ', '.join(changed))
    return actual


def gsim_active_stage(completed, previous, now):
    # Native rows accumulate. Test later stages first so completed SplitNodes
    # immediately ends its watchdog phase while second DCE is still running.
    if 'RemoveDeadNodes1#0' in completed:
        return {'name': 'window-complete', 'finished': True}
    if '{g->splitNodes()}#0' in completed:
        return {'name': 'dead-code-elim#1', 'finished': False}
    if '{g->usedBits()}#0' in completed:
        started = (previous.get('started_monotonic_s', now)
                   if previous.get('name') == 'split-nodes#0' else now)
        return {'name': 'split-nodes#0', 'finished': False, 'started_monotonic_s': started}
    if 'ExprOpt#0' in completed:
        return {'name': 'used-bits#0', 'finished': False}
    if 'RemoveDeadNodes#0' in completed:
        return {'name': 'expr-opt#0', 'finished': False}
    return previous


def verify_sample_group(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema') != GROUP_SCHEMA:
        raise ValueError('unsupported frozen F32 benchmark group')
    digest_value = dict(manifest)
    expected_manifest_hash = digest_value.pop('manifest_sha256', None)
    actual_manifest_hash = hashlib.sha256(json.dumps(
        digest_value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if actual_manifest_hash != expected_manifest_hash:
        raise ValueError('benchmark group manifest hash mismatch')
    verify_tool_sources(manifest.get('tool_identity'))
    if sha256(Path(manifest['input'])) != manifest['input_sha256']:
        raise ValueError('original FIRRTL changed after group freeze')
    if sha256(Path(manifest['source_manifest'])) != manifest['source_manifest_sha256']:
        raise ValueError('input manifest changed after group freeze')
    package = Path(manifest['package'])
    identity = verify_package_identity(package, package / 'identity.json')
    if sha256(package / 'identity.json') != manifest['package_identity_sha256']:
        raise ValueError('frozen GRH package changed after group freeze')
    dependencies = verified_dependencies(package, package / 'dependencies.json', identity)
    native = json.loads(Path(manifest['gsim_identity']).read_text())
    if (sha256(Path(manifest['gsim_identity'])) != manifest['gsim_identity_sha256'] or
            sha256(Path(native['binary'])) != native['sha256']):
        raise ValueError('frozen GSIM identity or binary changed')
    for library in native.get('libraries', []):
        if sha256(Path(library['path'])) != library['sha256']:
            raise ValueError('frozen GSIM runtime library changed: ' + library['path'])
    return manifest, identity, dependencies, native


def system_snapshot():
    load = Path('/proc/loadavg').read_text().split()
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, _, value = line.partition(':')
        if key in ('MemAvailable', 'SwapFree'):
            memory[key] = int(value.split()[0]) * 1024
    return {'captured_at_ns': time.time_ns(), 'loadavg_1_5_15': [float(value) for value in load[:3]],
            'memory_bytes': memory, 'cpu_affinity': sorted(os.sched_getaffinity(0))}


def write_progress(path, report, name, finished=False, started=None):
    report['active_stage'] = {'name': name, 'finished': finished}
    if started is not None:
        report['active_stage']['started_monotonic_s'] = started
    write_json_atomic(path, report)
    print(json.dumps({'event': 'stage-' + ('finished' if finished else 'started'),
                      'stage': name}), flush=True)


def grh_sample(args, report, summary, manifest):
    request, sources = verified_input_request(manifest['input'], manifest['source_manifest'])
    if sources != manifest['sources']:
        raise ValueError('actual source list or content differs from frozen benchmark group')
    package = Path(manifest['package'])
    identity = verify_package_identity(package, package / 'identity.json')
    dependencies = verified_dependencies(package, package / 'dependencies.json', identity)
    sys.meta_path[:] = [finder for finder in sys.meta_path
                        if not type(finder).__module__.startswith('_wolvrix_editable')]
    sys.path.insert(0, str(package))
    import wolvrix
    native = native_identity(wolvrix)
    verify_loaded_native(package, identity, native)
    if sha256(Path(manifest['gsim_identity'])) != manifest['gsim_identity_sha256']:
        raise ValueError('GSIM freeze identity changed during GRH sample')
    report.update(native=native, package_identity=identity, dependencies=dependencies,
                  sources=sources, prefix=[], window_passes=[],
                  package_identity_sha256=sha256(package / 'identity.json'))
    total_started = time.monotonic()
    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    timing_dir = args.output / 'timings'
    timing_dir.mkdir()
    with wolvrix.Session() as session:
        session.log_level = 'error'
        session.diagnostics_raise_min_level = 'none'
        write_progress(summary, report, 'ingest')
        start = time.monotonic()
        checked(session.read_sources(**request, out_design='design.main', pipeline='ingest'), 'ingest')
        report['prefix'].append({'stage': 'ingest', 'wall_s': time.monotonic() - start})
        write_progress(summary, report, 'ingest', True)
        def run_pass(name, logical, keep_declared):
            timing = timing_dir / (logical.replace('#', '-') + '.jsonl')
            started = time.monotonic()
            write_progress(summary, report, logical, started=started)
            result = session.run_pass(name, design='design.main', keep_declared_symbols=keep_declared,
                                      timing_output=str(timing), **({'semantics': '2state'} if name in WINDOW[:3] else {}))
            pass_returned = time.monotonic()
            elapsed = pass_returned - started
            checked(result, logical)
            rows, scopes = timers(timing, 'grh')
            pass_rows = scopes.get('pass', {})
            if len(pass_rows) != 1 or next(iter(pass_rows.values())).get('stage') != name:
                raise ValueError('ambiguous native GRH timer for ' + logical)
            row = {'pass': name, 'logical_instance': logical, 'wall_s': elapsed,
                   'native_timer': next(iter(pass_rows.values())),
                   'timing_file': str(timing), 'timing_sha256': sha256(timing),
                   'all_native_timers': rows, 'return_monotonic_s': pass_returned}
            (report['prefix'] if logical in ('xmr-resolve#0', 'hier-flatten#0',
                                             'comb-loop-elim#0', 'split-static-array#0',
                                             'dead-code-elim#0') else report['window_passes']).append(row)
            write_progress(summary, report, logical, True)
            return row

        # The raw source prefix is run in production order to create an actual P0.
        prefix_names = ('xmr-resolve', 'hier-flatten', 'comb-loop-elim',
                        'split-static-array', 'dead-code-elim')
        for name in prefix_names:
            logical = name + '#0'
            if name in ('split-static-array', 'dead-code-elim'):
                run_pass(name, logical, False)
            else:
                run_pass(name, logical, True)
        report['p0_reached_at_monotonic_s'] = time.monotonic()
        report['window_started_at_ns'] = time.time_ns()
        returned = []
        progress_s = 0.0
        for name, logical in zip(WINDOW, ('expr-opt#0', 'used-bits#0', 'split-nodes#0', 'dead-code-elim#1')):
            timing = timing_dir / (logical.replace('#', '-') + '.jsonl')
            progress_started = time.monotonic()
            write_progress(summary, report, logical, started=progress_started)
            progress_s += time.monotonic() - progress_started
            pass_started = time.monotonic()
            if name == 'expr-opt':
                window_start = pass_started
            result = session.run_pass(name, design='design.main', keep_declared_symbols=False,
                                      timing_output=str(timing),
                                      **({'semantics': '2state'} if name in WINDOW[:3] else {}))
            pass_returned = time.monotonic()
            if name == 'dead-code-elim':
                window_end = pass_returned
            checked(result, logical)
            returned.append((name, logical, timing, pass_returned - pass_started))
        for name, logical, timing, call_s in returned:
            rows, scopes = timers(timing, 'grh')
            pass_rows = scopes.get('pass', {})
            if len(pass_rows) != 1 or next(iter(pass_rows.values())).get('stage') != name:
                raise ValueError('ambiguous native GRH timer for ' + logical)
            native_row = next(iter(pass_rows.values()))
            row = {'pass': name, 'logical_instance': logical,
                   'wall_s': call_s, 'native_timer': native_row,
                   'timing_file': str(timing), 'timing_sha256': sha256(timing),
                   'all_native_timers': rows}
            report['window_passes'].append(row)
        report['window'] = {'wall_s': window_end - window_start,
                            'native_pass_sum_s': sum(row['native_timer']['wall_s'] for row in report['window_passes']),
                            'framework_overhead_s': window_end - window_start -
                                sum(row['native_timer']['wall_s'] for row in report['window_passes']),
                            'progress_write_s': progress_s,
                            'clock': 'steady_clock', 'start_after': 'first window call at P0',
                            'end_after': 'second dead-code-elim call return at P4'}
        report['window_finished_at_ns'] = time.time_ns()
        report['logical_window'] = [{'logical_pass': row['pass'], 'logical_occurrence': index,
                                     'logical_instance': row['logical_instance'],
                                     'native_timer': row['native_timer'],
                                     'timing_file': row['timing_file']}
                                    for index, row in enumerate(report['window_passes'])]
        write_progress(summary, report, 'window-complete', True)
    usage_after = resource.getrusage(resource.RUSAGE_SELF)
    timing_files = []
    for row in (*report['prefix'], *report['window_passes']):
        if 'timing_file' not in row:
            continue
        timing_files.append({'path': row['timing_file'], 'sha256': row['timing_sha256'],
                             'rows': row['all_native_timers']})
    report.update(status='passed', active_stage={'name': 'complete', 'finished': True},
                  wall_s=time.monotonic() - total_started, finished_at_ns=time.time_ns(),
                  returncode=0,
                  user_s=usage_after.ru_utime - usage_before.ru_utime,
                  system_s=usage_after.ru_stime - usage_before.ru_stime,
                  maxrss_kib=usage_after.ru_maxrss,
                  metrics={row['pass']: row['native_timer']['wall_s'] for row in report['window_passes']} |
                          {'window': report['window']['wall_s']},
                  instrumentation={'trace': False, 'dump': False, 'verify': False,
                                    'profile': False, 'export': False},
                  timing_files=timing_files,
                  window={**report['window'], 'source': 'runner-monotonic', 'clock': 'steady_clock'})
    write_json_atomic(summary, report)


def gsim_sample(args, report, summary, manifest, native):
    timing = args.output / 'native-timing.jsonl'
    model = args.output / 'model'
    model.mkdir()
    report.update(native=native, prefix=[], window_passes=[],
                  instrumentation={'trace': False, 'dump': False, 'verify': False,
                                    'profile': False, 'export': False})
    started = time.monotonic()
    report['started_at_ns'] = time.time_ns()
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    command = [native['binary'], '--dir', str(model), '--stop-after-stage=RemoveDeadNodes1',
               '--timing-output=' + str(timing), str(manifest['input'])]
    report['command'] = command
    write_progress(summary, report, 'gsim-raw-firrtl-prefix')
    with (args.output / 'gsim.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=manifest['gsim_source_root'], stdout=log, stderr=subprocess.STDOUT)
        observed = set()
        while process.poll() is None:
            try:
                rows, scopes = timers(timing, 'gsim')
            except (FileNotFoundError, ValueError):
                rows, scopes = [], {}
            for key, logical in GSIM_WINDOW.items():
                if key in scopes.get('pass', {}) and key not in observed:
                    report['window_passes'].append({'pass': logical, 'logical_instance': key,
                                                    'native_timer': scopes['pass'][key]})
                    observed.add(key)
            phase = gsim_active_stage(set(scopes.get('pass', {})), report['active_stage'], time.monotonic())
            if phase != report['active_stage']:
                write_progress(summary, report, phase['name'], phase['finished'],
                               started=phase.get('started_monotonic_s'))
            time.sleep(0.25)
        returncode = process.wait()
    if returncode:
        raise RuntimeError('GSIM F32 benchmark returned ' + str(returncode))
    rows, scopes = timers(timing, 'gsim')
    passes = scopes.get('pass', {})
    if set(GSIM_WINDOW) - passes.keys():
        raise ValueError('GSIM native F32 timing rows are incomplete: ' + repr(sorted(set(GSIM_WINDOW) - passes.keys())))
    window_rows = scopes.get('window', {})
    if 'F32Window#0' not in window_rows:
        raise ValueError('GSIM native contiguous P0-P4 window timer is missing')
    report['window_passes'] = [{'pass': logical, 'logical_instance': key, 'native_timer': passes[key],
                                'timing_file': str(timing.resolve())}
                               for key, logical in GSIM_WINDOW.items()]
    report['native_timers'] = rows
    report['timing_file'] = str(timing)
    report['timing_sha256'] = sha256(timing)
    window_row = window_rows['F32Window#0']
    report['window'] = {'wall_s': window_row['wall_s'],
                        'native_pass_sum_s': sum(row['native_timer']['wall_s'] for row in report['window_passes']),
                        'framework_overhead_s': window_row['wall_s'] -
                            sum(row['native_timer']['wall_s'] for row in report['window_passes']),
                        'clock': 'steady_clock', 'native_timer': window_row,
                        'start_after': 'first DCE/P0 boundary', 'end_after': 'second DCE/P4 boundary'}
    report['logical_window'] = [{'logical_pass': row['pass'], 'logical_occurrence': index,
                                 'logical_instance': row['logical_instance'],
                                 'native_timer': row['native_timer'],
                                 'timing_file': row['timing_file']}
                                for index, row in enumerate(report['window_passes'])]
    report['prefix'] = [row for row in rows if row.get('scope') == 'pass' and
                        row.get('pass_instance') not in GSIM_WINDOW and row.get('stage') not in ('F32Window',)]
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    report.update(status='passed', active_stage={'name': 'complete', 'finished': True},
                  started_at_ns=report['started_at_ns'], finished_at_ns=time.time_ns(),
                  returncode=returncode,
                  wall_s=time.monotonic() - started,
                  user_s=after.ru_utime - usage_before.ru_utime,
                  system_s=after.ru_stime - usage_before.ru_stime,
                  maxrss_kib=after.ru_maxrss,
                  metrics={row['pass']: row['native_timer']['wall_s'] for row in report['window_passes']} |
                          {'window': report['window']['wall_s']},
                  native_log=str(args.output / 'gsim.log'), native_returncode=returncode,
                  timing_files=[{'path': str(timing.resolve()), 'sha256': sha256(timing), 'rows': rows}],
                  window={**report['window'], 'source': 'native', 'clock': 'steady_clock'})
    write_json_atomic(summary, report)


def sample(args):
    normalized_environment()
    manifest, _, _, native = verify_sample_group(args.group_manifest)
    args.engine = args.sample_engine
    if args.engine not in ('grh', 'gsim'):
        raise ValueError('invalid benchmark engine')
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'ptmp'):
        raise ValueError('sample output must be under ptmp/')
    guard_files = {'guard.json', 'resources.samples.jsonl'}
    if output.exists() and any(path.name not in guard_files for path in output.iterdir()):
        raise ValueError('sample output directory must contain only this supervisor guard files')
    output.mkdir(parents=True, exist_ok=True)
    summary = output / 'summary.json'
    report = {'schema': SCHEMA, 'status': 'running', 'engine': args.engine,
              'source': 'raw-firrtl', 'mode': 'no-trace', 'verify': False,
              'window_semantics': '2state', 'stop_after_stage': 'post-second-dead-code-elim',
              'group_id': manifest['group_id'], 'group_manifest': str(Path(args.group_manifest).resolve()),
              'group_manifest_sha256': sha256(Path(args.group_manifest)),
              'input': manifest['input'], 'input_sha256': manifest['input_sha256'],
              'configuration': manifest['configuration'],
              'cpu_affinity': manifest['configuration']['cpu_affinity'],
              'started_at_ns': time.time_ns(), 'started_monotonic_s': time.monotonic(),
              'active_stage': {'name': 'initialization', 'finished': False}}
    write_json_atomic(summary, report)
    try:
        observed_configuration = verify_child_environment(manifest['configuration'])
        report.update(observed_configuration=observed_configuration,
                      cpu_affinity=observed_configuration['cpu_affinity'],
                      tool_identity=verify_tool_sources(manifest['tool_identity']))
        write_json_atomic(summary, report)
        if args.engine == 'grh':
            grh_sample(args, report, summary, manifest)
        else:
            gsim_sample(args, report, summary, manifest, native)
        if (sha256(Path(manifest['input'])) != manifest['input_sha256'] or
                sha256(Path(manifest['gsim_identity'])) != manifest['gsim_identity_sha256'] or
                sha256(Path(native['binary'])) != native['sha256']):
            raise ValueError('input or frozen GSIM binary changed during sample')
        if args.engine == 'grh' and sha256(Path(manifest['package']) / 'identity.json') != manifest['package_identity_sha256']:
            raise ValueError('frozen GRH package changed during sample')
        verify_tool_sources(manifest['tool_identity'])
        report['observed_configuration_after'] = verify_child_environment(manifest['configuration'])
        write_json_atomic(summary, report)
    except BaseException as error:
        report.update(status='failed', error=repr(error), failed_at_ns=time.time_ns())
        write_json_atomic(summary, report)
        raise


def schedule(repeats):
    return ['grh' if index % 2 == 0 else 'gsim' for index in range(repeats * 2)]


def run_group(args):
    normalized_environment()
    frozen_tools = tool_source_identity()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'ptmp') or output.exists():
        raise ValueError('benchmark group output must be a new directory under repository ptmp/')
    if args.repeats < 3:
        raise ValueError('formal F32 performance requires at least three samples per engine')
    output.mkdir(parents=True)
    if args.cpus:
        cpus = set(args.cpus)
        allowed = os.sched_getaffinity(0)
        if not cpus or not cpus <= allowed:
            raise ValueError('requested CPUs must be a nonempty subset of the current affinity')
        os.sched_setaffinity(0, cpus)
    input_path = args.firrtl.resolve()
    manifest_path = args.manifest.resolve()
    package = args.package.resolve()
    source_root = args.source_root.resolve()
    request, sources = verified_input_request(input_path, manifest_path)
    if sha256(input_path) != args.expected_input_sha256:
        raise ValueError('original FIRRTL SHA does not match the F32 frozen input')
    if args.expected_input_sha256 != 'b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b':
        raise ValueError('formal F32 benchmark input is not the frozen SimTop FIRRTL')
    package_identity = verify_package_identity(package, package / 'identity.json')
    dependencies = verified_dependencies(package, package / 'dependencies.json', package_identity)
    if package_identity.get('build', {}).get('CMAKE_BUILD_TYPE') != 'Release':
        raise ValueError('F32 benchmark requires a frozen Release package')
    native_freeze = output / 'gsim-freeze'
    native_freeze.mkdir()
    identity, identity_path = freeze_native(args.binary.resolve(), source_root, native_freeze)
    configuration = environment()
    if any(configuration['profiling_environment'].values()):
        raise ValueError('profiling/instrumentation environment must be disabled for formal samples')
    configuration['instrumentation'] = {'trace': False, 'snapshot': False, 'export': False,
                                        'verify': False, 'profile': False, 'statistics': False}
    group = {'schema': GROUP_SCHEMA, 'status': 'frozen', 'group_id': uuid.uuid4().hex,
             'created_at_ns': time.time_ns(), 'input': str(input_path),
             'input_sha256': sha256(input_path), 'input_bytes': input_path.stat().st_size,
             'source_manifest': str(manifest_path), 'source_manifest_sha256': sha256(manifest_path),
             'sources': sources, 'package': str(package),
             'package_identity_sha256': sha256(package / 'identity.json'),
             'package_content_identity': package_identity.get('source', {}).get('content_sha256'),
             'dependencies_content_sha256': dependencies['content_sha256'],
             'gsim_identity': str(identity_path.resolve()),
             'gsim_identity_sha256': sha256(identity_path),
             'gsim_binary_sha256': identity['sha256'], 'gsim_source_revision': identity['source_revision'],
             'gsim_source_root': str(source_root), 'configuration': configuration,
             'tool_identity': frozen_tools,
             'limits': {'rss_bytes': args.rss_gib * 1024**3, 'psi_percent': args.psi_percent,
                        'psi_seconds': args.psi_seconds, 'sample_interval_s': 0.25,
                        'split_nodes_timeout_s': args.split_timeout},
             'measurement': {'repeats_per_engine': args.repeats, 'mode': 'no-trace',
                             'window_semantics': '2state', 'exports': False, 'verification': False,
                             'profile': False, 'build_type': 'Release', 'source': 'raw-firrtl'},
             'schedule': schedule(args.repeats)}
    group_path = output / 'group.json'
    group['manifest_sha256'] = hashlib.sha256(
        json.dumps(group, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    write_json_atomic(group_path, group)
    group_hash = sha256(group_path)
    results = {'schema': RESULT_SCHEMA, 'status': 'running', 'group_id': group['group_id'],
               'group_manifest': str(group_path.resolve()), 'group_manifest_sha256': group_hash,
               'samples': [], 'started_at_ns': time.time_ns()}
    result_path = output / 'results.json'
    write_json_atomic(result_path, results)
    limits = GuardLimits(rss_bytes=int(args.rss_gib * 1024**3), psi_percent=args.psi_percent,
                         psi_seconds=args.psi_seconds, interval_s=0.25)
    limits.validate()
    for index, engine in enumerate(group['schedule'], 1):
        sample_dir = output / 'samples' / f'{index:02d}-{engine}'
        sample_dir.parent.mkdir(exist_ok=True)
        sample_dir.mkdir()
        command = [sys.executable, str(Path(__file__).resolve()), '--sample-engine', engine,
                   '--group-manifest', str(group_path), '--output', str(sample_dir)]
        timeouts = {'split-nodes#0': args.split_timeout}
        started = time.time_ns()
        system_before = system_snapshot()
        try:
            verify_tool_sources(group['tool_identity'])
            guard_result = run_guarded(command, sample_dir, limits,
                                       sampler=process_tree_sample, phase_timeouts=timeouts)
            verify_tool_sources(group['tool_identity'])
            status = 'passed' if guard_result == 0 else 'failed'
        except BaseException as error:
            status = 'failed'
            (sample_dir / 'orchestrator-error.json').write_text(json.dumps({'error': repr(error)}, indent=2) + '\n')
        summary_path = sample_dir / 'summary.json'
        sample_row = {'sequence': index, 'engine': engine, 'directory': str(sample_dir.resolve()),
                      'summary_file': str(summary_path), 'status': status,
                      'started_at_ns': started, 'finished_at_ns': time.time_ns(),
                      'guard_file': str((sample_dir / 'guard.json').resolve()),
                      'system_before': system_before, 'system_after': system_snapshot()}
        if summary_path.is_file():
            sample_row['summary_sha256'] = sha256(summary_path)
            try:
                sample_row['native_status'] = json.loads(summary_path.read_text()).get('status')
            except (OSError, ValueError):
                sample_row['native_status'] = 'invalid-summary'
        if (sample_dir / 'guard.json').is_file():
            sample_row['guard_sha256'] = sha256(sample_dir / 'guard.json')
            try:
                sample_row['returncode'] = json.loads((sample_dir / 'guard.json').read_text()).get('returncode')
            except (OSError, ValueError):
                sample_row['returncode'] = None
        results['samples'].append(sample_row)
        write_json_atomic(result_path, results)
        print(json.dumps({'event': 'sample-finished', **sample_row}), flush=True)
    results.update(finished_at_ns=time.time_ns(), status=(
        'completed' if len([row for row in results['samples'] if row['status'] == 'passed']) == len(group['schedule'])
        else 'completed-with-failures'))
    write_json_atomic(result_path, results)
    print(json.dumps({'status': results['status'], 'results': str(result_path),
                      'group_manifest': str(group_path), 'samples': len(results['samples'])}), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firrtl', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--package', type=Path)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--source-root', type=Path, default=ROOT / 'reference/gsim')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expected-input-sha256', default='b313a3ecd154cbd9279b14403709806b95fb136cf44b475e9def46a926ecb26b')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--cpus', type=int, nargs='*')
    parser.add_argument('--rss-gib', type=float, default=96)
    parser.add_argument('--psi-percent', type=float, default=25)
    parser.add_argument('--psi-seconds', type=float, default=8)
    parser.add_argument('--split-timeout', type=float, default=180)
    parser.add_argument('--sample-engine', choices=('grh', 'gsim'), help=argparse.SUPPRESS)
    parser.add_argument('--group-manifest', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.sample_engine:
        try:
            sample(args)
        except BaseException as error:
            print(json.dumps({'status': 'failed', 'error': repr(error)}), flush=True)
            raise
        return
    for name in ('firrtl', 'manifest', 'package', 'binary'):
        if getattr(args, name) is None:
            parser.error('--' + name + ' is required')
    if not (0 < args.split_timeout <= 180):
        parser.error('formal F32 split timeout must be positive and at most 180 seconds')
    if not (0 < args.rss_gib <= 96):
        parser.error('formal F32 RSS guard must be positive and at most 96 GiB')
    try:
        run_group(args)
    except BaseException as error:
        print(json.dumps({'status': 'failed', 'error': repr(error)}), flush=True)
        raise


if __name__ == '__main__':
    main()
