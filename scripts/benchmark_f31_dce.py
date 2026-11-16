"""Measure the first DCE from raw FIRRTL; never load a checkpoint."""
from __future__ import annotations

import argparse
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

from benchmark_f29_pass_trace import (native_identity, run_case, sha256,
                                     SplitWatchdog, WATCHDOG_SOURCE, write_json_atomic)
from benchmark_f30_gsim import freeze_native
from benchmark_f30_pipeline import (verified_input_request, verify_package_identity,
                                    verified_dependencies, verify_loaded_native)
from benchmark_xs_firrtl_ingest import checked

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'wolvrix.f31.dce-benchmark.v1'


def environment():
    return {'machine': list(platform.uname()),
            'cpu_model': next((line.partition(':')[2].strip() for line in
                               Path('/proc/cpuinfo').read_text().splitlines()
                               if line.startswith('model name')), platform.machine()),
            'thread_environment': {key: os.environ.get(key) for key in
                                   ('OMP_NUM_THREADS', 'OMP_PROC_BIND', 'TBB_NUM_THREADS', 'WOLVRIX_THREADS')},
            'loader_environment': {key: os.environ.get(key) for key in ('LD_LIBRARY_PATH', 'LD_PRELOAD')},
            'profiling_environment': {key: os.environ.get(key) for key in
                                      ('WOLVRIX_HIER_FLATTEN_PROFILE', 'WOLVRIX_SIMPLIFY_PHASE_TIMING', 'WOLVRIX_CLE_DEBUG')},
            'cpu_affinity': sorted(os.sched_getaffinity(0))}


def process_tree_sample(pid, group):
    # GSIM is a native grandchild; counting only its Python supervisor would
    # leave its graph allocations outside the RSS guard.
    from f30_resource_guard import process_memory, cgroup_memory
    total = process_memory(pid)
    pending = [pid]
    seen = {pid}
    while pending:
        parent = pending.pop()
        try:
            children = (Path('/proc') / str(parent) / 'task' / str(parent) / 'children').read_text().split()
        except (FileNotFoundError, ProcessLookupError):
            continue
        for item in children:
            child = int(item)
            if child in seen:
                continue
            seen.add(child)
            pending.append(child)
            try:
                memory = process_memory(child)
            except (FileNotFoundError, ProcessLookupError, ValueError):
                continue
            for key, amount in memory.items():
                total[key] = total.get(key, 0) + amount
    return {'process_bytes': total, 'cgroup': cgroup_memory(group), 'process_count': len(seen)}


def stage_timers(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    result = {}
    for row in rows:
        if (row.get('schema') != 'gsim-stage-timing.v1' or row.get('complete') is not True or
                row.get('clock') != 'steady_clock'):
            raise ValueError('invalid or incomplete native GSIM timing row')
        if row.get('scope') != 'pass':
            continue
        key = row['pass_instance']
        if key in result or not math.isfinite(row['wall_s']) or row['wall_s'] < 0:
            raise ValueError('duplicate or invalid GSIM timing')
        result[key] = row
    if 'RemoveDeadNodes#0' not in result:
        raise ValueError('missing first native DCE timer')
    if result['RemoveDeadNodes#0']['stage'] != 'RemoveDeadNodes':
        raise ValueError('first DCE timer has the wrong stage')
    return result


def reference(paths, input_sha, config):
    samples = []
    for path in paths:
        path = Path(path).resolve()
        value = json.loads(path.read_text())
        if (value.get('schema') != SCHEMA or value.get('engine') != 'gsim' or
                value.get('mode') != 'no-trace' or value.get('verify') is not False or
                value.get('status') != 'passed' or value.get('input_sha256') != input_sha or
                value.get('configuration') != config):
            raise ValueError('DCE reference must be a compatible, completed GSIM no-trace sample')
        if sha256(Path(value['native']['binary'])) != value['native']['sha256']:
            raise ValueError('GSIM reference binary changed')
        if sha256(Path(value['timing_file'])) != value['timing_sha256']:
            raise ValueError('GSIM native timing file changed')
        if stage_timers(value['timing_file']) != value['native_timers']:
            raise ValueError('GSIM native timing report mismatch')
        if value['dce']['pass_s'] != value['native_timers']['RemoveDeadNodes#0']['wall_s']:
            raise ValueError('GSIM DCE time is not bound to the native first-instance timer')
        if (sha256(Path(value['identity_file'])) != value['identity_sha256'] or
                json.loads(Path(value['identity_file']).read_text()) != value['native'] or
                sha256(Path(value['input'])) != input_sha):
            raise ValueError('GSIM reference identity/input mismatch')
        if value['finished_at_ns'] >= time.time_ns():
            raise ValueError('GSIM reference must finish before this run')
        samples.append({'path': str(path), 'sha256': sha256(path), 'sample': value})
    if len(samples) < 3 or len({entry['path'] for entry in samples}) != len(samples):
        raise ValueError('at least three distinct GSIM first-DCE samples are required')
    first = samples[0]['sample']
    for previous, current in zip(samples, samples[1:]):
        if current['sample']['started_at_ns'] < previous['sample']['finished_at_ns']:
            raise ValueError('GSIM reference samples must be sequential and chronological')
    if any(entry['sample']['native']['sha256'] != first['native']['sha256'] for entry in samples):
        raise ValueError('GSIM reference native versions differ')
    seconds = [entry['sample']['dce']['pass_s'] for entry in samples]
    baseline = statistics.median(seconds)
    split = statistics.median(next(row['wall_s'] for row in entry['sample']['native_timers'].values()
                                   if row['stage'] == 'SplitArray') for entry in samples)
    return {'median_s': baseline, 'limit_s': baseline + max(0.03 * baseline, 0.010),
            'dce_timeout_s': 2 * baseline, 'split_timeout_s': 2 * split,
            'samples': [{key: entry[key] for key in ('path', 'sha256')} for entry in samples]}


class DceWatchdog(SplitWatchdog):
    def __init__(self, payload):
        self.process = subprocess.Popen(
            [sys.executable, '-c', WATCHDOG_SOURCE.replace('split-static-array', 'dead-code-elim'),
             json.dumps(payload)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        if self.process.stdout.readline() != b'ready\n':
            raise RuntimeError('DCE watchdog did not start')


def gsim(args, report):
    native, identity = freeze_native(args.binary, args.source_root, args.output)
    report.update(native=native, identity_file=str(identity), identity_sha256=sha256(identity))
    timing = args.output / 'native-timing.jsonl'
    command = [native['binary'], '--dir', str(args.output / 'model'),
               '--stop-after-stage=RemoveDeadNodes0', '--timing-output=' + str(timing)]
    if args.mode == 'trace':
        command += ['--semantic-node-exchange=' + str(args.output / 'exchange'),
                    '--semantic-node-exchange-pass=pipeline', '--semantic-node-exchange-mode=trace',
                    '--trace-input-sha256=' + report['input_sha256']]
    command.append(str(args.firrtl))
    (args.output / 'model').mkdir()
    report['command'] = command
    report['started_at_ns'] = time.time_ns()
    started = time.monotonic()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    with (args.output / 'gsim.log').open('w') as log:
        process = subprocess.run(command, cwd=args.source_root, stdout=log, stderr=subprocess.STDOUT)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    report.update(returncode=process.returncode, wall_s=time.monotonic() - started,
                  user_s=after.ru_utime - usage.ru_utime, system_s=after.ru_stime - usage.ru_stime,
                  maxrss_kib=after.ru_maxrss, finished_at_ns=time.time_ns())
    if process.returncode:
        raise RuntimeError('GSIM first-DCE run failed: ' + str(process.returncode))
    timers = stage_timers(timing)
    report.update(timing_file=str(timing), timing_sha256=sha256(timing), native_timers=timers,
                  dce={'pass_s': timers['RemoveDeadNodes#0']['wall_s']})
    report['boundary_timers'] = [json.loads(line) for line in timing.read_text().splitlines()
                                 if json.loads(line).get('scope') == 'boundary']
    if sha256(Path(native['binary'])) != native['sha256'] or sha256(args.firrtl) != report['input_sha256']:
        raise ValueError('GSIM binary/input changed during sample')


def grh(args, report, summary):
    identity = verify_package_identity(args.package, args.package / 'identity.json')
    dependencies = verified_dependencies(args.package, args.package / 'dependencies.json', identity)
    sys.meta_path[:] = [finder for finder in sys.meta_path
                        if not type(finder).__module__.startswith('_wolvrix_editable')]
    sys.path.insert(0, str(args.package))
    import wolvrix
    native = native_identity(wolvrix)
    verify_loaded_native(args.package, identity, native)
    request, sources = verified_input_request(args.firrtl, args.manifest)
    baseline = reference(args.gsim_reference, report['input_sha256'], report['configuration'])
    report.update(native=native, package_identity=identity, dependencies=dependencies,
                  sources=sources, reference=baseline, prefix={'stages': []},
                  identity_file=str(args.package / 'identity.json'),
                  identity_sha256=sha256(args.package / 'identity.json'),
                  manifest=str(args.manifest.resolve()), manifest_sha256=sha256(args.manifest))
    report['started_at_ns'] = time.time_ns()
    started = time.monotonic()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    with wolvrix.Session() as session:
        session.log_level = 'error'
        session.diagnostics_raise_min_level = 'none'
        for name in ('ingest', 'xmr-resolve', 'hier-flatten'):
            report['active_stage'] = {'name': name, 'finished': False}
            write_json_atomic(summary, report)
            print(json.dumps({'event': 'stage-started', 'stage': name}), flush=True)
            before = time.monotonic()
            result = (session.read_sources(**request, out_design='design.main', pipeline='ingest')
                      if name == 'ingest' else session.run_pass(name, design='design.main', keep_declared_symbols=True))
            checked(result, name)
            row = {'stage': name, 'wall_s': time.monotonic() - before}
            report['prefix']['stages'].append(row)
            report['active_stage'] = {'name': name, 'finished': True}
            write_json_atomic(summary, report)
            print(json.dumps(row), flush=True)
        # The DCE trace toggle starts at G0; both runs share the same normal prefix.
        report['prefix']['comb_split'] = run_case(
            session, args.firrtl, args.output / 'prefix', False, 'design.main', 'SimTop', False,
            report['input_sha256'], baseline['split_timeout_s'], report, summary, run_started=started)
        row = report['dce'] = {}
        total = time.monotonic()
        if args.mode == 'trace':
            before = time.monotonic()
            session.semantic_exchange_start(design='design.main', output=str(args.output / 'dce'), top='SimTop',
                                            stage='post-split-static-array', pass_name='dead-code-elim',
                                            input_sha256=report['input_sha256'], validate_at_finish=args.verify,
                                            pass_instance='dead-code-elim#0',
                                            connection_evidence_at_finish=args.connection_evidence,
                                            diagnostic_operation_removal_only=args.diagnostic_stop_after_dce)
            row['snapshot_setup_s'] = time.monotonic() - before
        report['active_stage'] = {'name': 'dead-code-elim', 'finished': False}
        write_json_atomic(summary, report)
        watch_result = {'passes': []}
        watchdog = DceWatchdog({
            'timeout_s': baseline['dce_timeout_s'], 'parent_pid': os.getpid(), 'row': {'pass': 'dead-code-elim'},
            'result': watch_result, 'report': report, 'case_started': started, 'case_key': 'dce_failure',
            'timing_path': str(args.output / 'dce-timeout.json'), 'summary_path': str(summary),
            'marker_path': str(args.output / 'dce-timeout.marker'), 'run_started': started})
        before_usage = resource.getrusage(resource.RUSAGE_SELF)
        before = time.monotonic()
        watchdog.arm(before)
        finished = None
        try:
            result = session.run_pass('dead-code-elim', design='design.main', keep_declared_symbols=False,
                                      timing_output=str(args.output / 'native-dce-timing.jsonl'))
            finished = time.monotonic()
        finally:
            watchdog.finish(finished)
        after = resource.getrusage(resource.RUSAGE_SELF)
        row.update(pass_s=finished - before, user_s=after.ru_utime - before_usage.ru_utime,
                   system_s=after.ru_stime - before_usage.ru_stime, maxrss_kib=after.ru_maxrss)
        checked(result, 'dead-code-elim')
        timing = args.output / 'native-dce-timing.jsonl'
        native_rows = [json.loads(line) for line in timing.read_text().splitlines()]
        if (len(native_rows) != 1 or native_rows[0].get('pass_instance') != 'dead-code-elim#0' or
                native_rows[0].get('complete') is not True):
            raise ValueError('invalid native GRH first-DCE timing evidence')
        row['native_pass_s'] = native_rows[0]['wall_s']
        report.update(timing_file=str(timing), timing_sha256=sha256(timing), native_timers=native_rows)
        report['active_stage'] = {'name': 'dead-code-elim', 'finished': True}
        write_json_atomic(summary, report)
        print(json.dumps({'event': 'dce-returned', **row}), flush=True)
        if args.diagnostic_stop_after_dce:
            report.update(status='diagnostic_only', diagnostic_only=True,
                          diagnostic={'kind': 'dead-anchor-operation-removal',
                                      'probe_path': os.environ['WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC'],
                                      'liveness_provenance_disabled': True},
                          publication={'complete': False,
                                       'reason': 'stopped after native DCE before semantic exchange finish'},
                          active_stage={'name': 'diagnostic-stop-after-dce', 'finished': True},
                          finished_at_ns=time.time_ns(), wall_s=time.monotonic() - started,
                          user_s=after.ru_utime - usage.ru_utime,
                          system_s=after.ru_stime - usage.ru_stime,
                          maxrss_kib=after.ru_maxrss)
            write_json_atomic(summary, report)
            print(json.dumps({'event': 'diagnostic-stop-after-dce', 'publication_complete': False,
                              'probe_path': os.environ['WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC']}), flush=True)
            return True
        if args.mode == 'trace':
            report['active_stage'] = {'name': 'semantic-exchange-export', 'finished': False}
            write_json_atomic(summary, report)
            before = time.monotonic()
            session.semantic_exchange_finish(design='design.main', top='SimTop', stage='post-dead-code-elim')
            row['snapshot_export_s'] = time.monotonic() - before
        row['boundary_s'] = time.monotonic() - total
        write_json_atomic(summary, report)
        if args.verify:
            report['active_stage'] = {'name': 'dce-validation', 'finished': False}
            write_json_atomic(summary, report)
            before = time.monotonic()
            validation = session.semantic_validate(design='design.main')
            if not validation.get('valid'):
                raise RuntimeError('post-DCE semantic validation failed: ' + str(validation))
            checked(session.run_pass('grh.verify', design='design.main'), 'verify DCE')
            if args.actual_state:
                from compare_f31_dce_equivalence import capture_actual_state
                report['active_stage'] = {'name': 'actual-after-export', 'finished': False}
                write_json_atomic(summary, report)
                row['actual_after'] = capture_actual_state(
                    session, args.output / 'actual-after', 'post-dead-code-elim', top='SimTop')
            report['active_stage'] = {'name': 'repeated-dead-code-elim', 'finished': False}
            write_json_atomic(summary, report)
            repeated = session.run_pass('dead-code-elim', design='design.main', keep_declared_symbols=False)
            checked(repeated, 'DCE idempotence')
            repeated_history = session.history()[-1]
            if repeated_history.get('changed') is not False:
                raise RuntimeError('second DCE changed the post-DCE graph: ' + str(repeated_history))
            if args.actual_state:
                report['active_stage'] = {'name': 'actual-repeated-export', 'finished': False}
                write_json_atomic(summary, report)
                row['actual_repeated'] = capture_actual_state(
                    session, args.output / 'actual-repeated', 'second-dead-code-elim', top='SimTop')
                if row['actual_after']['signature'] != row['actual_repeated']['signature']:
                    raise RuntimeError('second DCE changed actual IR or public graph despite changed=false')
            row.update(validation_s=time.monotonic() - before, validation=validation,
                       repeated_dce=repeated, repeated_dce_history=repeated_history)
        report['active_stage'] = {'name': 'complete', 'finished': True}
        after = resource.getrusage(resource.RUSAGE_SELF)
        report.update(wall_s=time.monotonic() - started, finished_at_ns=time.time_ns(),
                      user_s=after.ru_utime - usage.ru_utime, system_s=after.ru_stime - usage.ru_stime,
                      maxrss_kib=after.ru_maxrss)
        write_json_atomic(summary, report)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=('grh', 'gsim'), required=True)
    parser.add_argument('--firrtl', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('no-trace', 'trace'), default='no-trace')
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--package', type=Path)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--source-root', type=Path, default=ROOT / 'reference/gsim')
    parser.add_argument('--gsim-reference', type=Path, nargs='+', default=[])
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--actual-state', action='store_true',
                        help='export actual IR/public graph before/after repeated DCE; implies --verify')
    parser.add_argument('--connection-evidence', action='store_true',
                        help='record sparse native use witnesses for newly added dependencies; implies --verify')
    parser.add_argument('--diagnostic-stop-after-dce', action='store_true',
                        help='stop after native DCE for a guarded GRH dead-anchor diagnostic')
    parser.add_argument('--resource-guard-rss-gib', type=float, default=96)
    parser.add_argument('--resource-guard-psi-percent', type=float, default=25)
    parser.add_argument('--resource-guard-psi-seconds', type=float, default=8)
    parser.add_argument('--resource-guard-interval-s', type=float, default=0.25)
    parser.add_argument('--guard-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.output, args.firrtl = args.output.resolve(), args.firrtl.resolve()
    if not args.output.is_relative_to(ROOT / 'ptmp'):
        parser.error('output must be under repository ptmp/')
    args.output.mkdir(parents=True, exist_ok=True)
    if args.diagnostic_stop_after_dce:
        if (args.engine != 'grh' or args.mode != 'trace' or args.verify or args.connection_evidence or
                args.actual_state):
            parser.error('--diagnostic-stop-after-dce requires GRH trace without verify or exports')
        diagnostic_value = os.environ.get('WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC', '')
        diagnostic_path = Path(diagnostic_value).resolve() if diagnostic_value else None
        ptmp_root = (ROOT / 'ptmp').resolve()
        if (diagnostic_path is None or diagnostic_path == ptmp_root or
                not diagnostic_path.is_relative_to(ptmp_root) or not diagnostic_path.parent.is_dir() or
                diagnostic_path.is_dir()):
            parser.error('diagnostic probe path must be a file under repository ptmp/ with an existing parent')
        if os.environ.get('WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC_NO_LIVENESS') != '1':
            parser.error('--diagnostic-stop-after-dce requires WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC_NO_LIVENESS=1')
    if not args.guard_child:
        from f30_resource_guard import GuardLimits, run_guarded
        if not math.isfinite(args.resource_guard_rss_gib) or args.resource_guard_rss_gib <= 0:
            parser.error('resource guard RSS GiB must be positive and finite')
        limits = GuardLimits(rss_bytes=int(args.resource_guard_rss_gib * 1024**3),
                             psi_percent=args.resource_guard_psi_percent,
                             psi_seconds=args.resource_guard_psi_seconds,
                             interval_s=args.resource_guard_interval_s)
        try:
            limits.validate()
        except ValueError as error:
            parser.error(str(error))
        raise SystemExit(run_guarded([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], '--guard-child'],
                                     args.output, limits,
                                     sampler=process_tree_sample if args.engine == 'gsim' else None))
    if args.engine == 'grh' and (not args.package or not args.manifest or not args.gsim_reference):
        parser.error('GRH requires --package, --manifest and three --gsim-reference samples')
    if args.connection_evidence and (args.engine != 'grh' or args.mode != 'trace'):
        parser.error('--connection-evidence requires GRH trace mode')
    if args.connection_evidence:
        args.verify = True
    if args.actual_state:
        if args.engine != 'grh':
            parser.error('--actual-state requires GRH')
        args.verify = True
    if args.engine == 'gsim' and not args.binary:
        parser.error('GSIM requires --binary')
    if args.package:
        args.package = args.package.resolve()
    summary = args.output / 'summary.json'
    if summary.exists():
        parser.error('refusing to overwrite an existing sample')
    report = {'schema': SCHEMA, 'engine': args.engine, 'mode': args.mode, 'verify': args.verify,
              'status': 'running', 'input': str(args.firrtl), 'input_sha256': sha256(args.firrtl),
              'configuration': environment(), 'source': 'raw-firrtl',
              'scope': 'native first-DCE including all required maintenance/commit; static snapshots/export separate'}
    if not args.verify and any(value is not None for value in report['configuration']['profiling_environment'].values()):
        raise ValueError('formal samples require profiling/debug/timing environments to be unset')
    write_json_atomic(summary, report)
    try:
        diagnostic_only = False
        if args.engine == 'gsim':
            gsim(args, report)
        else:
            diagnostic_only = grh(args, report, summary)
        if not diagnostic_only:
            report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error=repr(error))
        write_json_atomic(summary, report)
        raise
    write_json_atomic(summary, report)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
