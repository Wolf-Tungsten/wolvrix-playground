"""Profile native UsedBits after the full F32 raw prefix, without graph exports."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import resource
import sys
import time

from benchmark_f29_pass_trace import SplitProfile, native_identity, sha256, write_json_atomic
from benchmark_f30_pipeline import (verified_dependencies, verified_input_request,
                                    verify_loaded_native, verify_package_identity)
from benchmark_f31_dce import process_tree_sample
from benchmark_f32_passes import PREFIX, normalized_environment, timers
from benchmark_xs_firrtl_ingest import checked
from f30_resource_guard import GuardLimits, run_guarded

ROOT = Path(__file__).resolve().parents[1]


def run_sample(args):
    normalized_environment()
    request, sources = verified_input_request(args.firrtl, args.manifest)
    package = args.package.resolve()
    identity = verify_package_identity(package, package / 'identity.json')
    dependencies = verified_dependencies(package, package / 'dependencies.json', identity)
    sys.meta_path[:] = [finder for finder in sys.meta_path
                        if not type(finder).__module__.startswith('_wolvrix_editable')]
    sys.path.insert(0, str(package))
    import wolvrix
    native = native_identity(wolvrix)
    verify_loaded_native(package, identity, native)
    summary = args.output / 'summary.json'
    report = {'schema': 'wolvrix.f32.used-bits-profile.v1', 'status': 'running',
              'diagnostic_only': True, 'formal_performance_sample': False,
              'source': 'raw-firrtl', 'window_semantics': '2state',
              'stop_after_stage': 'second-dce' if args.finish_window else 'post-used-bits',
              'input': str(args.firrtl),
              'input_sha256': sha256(args.firrtl), 'sources': sources,
              'package_identity': identity, 'dependencies': dependencies, 'native': native,
              'cpu_affinity': sorted(os.sched_getaffinity(0)), 'stages': [],
              'started_at_ns': time.time_ns()}
    write_json_atomic(summary, report)
    timing_dir = args.output / 'timings'
    timing_dir.mkdir()
    started = time.monotonic()
    before = resource.getrusage(resource.RUSAGE_SELF)

    def stage(name, function):
        report['active_stage'] = {'name': name, 'finished': False,
                                  'started_monotonic_s': time.monotonic()}
        write_json_atomic(summary, report)
        print(json.dumps({'event': 'stage-started', 'stage': name}), flush=True)
        entered = time.monotonic()
        value = function()
        report['stages'].append({'stage': name, 'wall_s': time.monotonic() - entered})
        report['active_stage'] = {'name': name, 'finished': True}
        write_json_atomic(summary, report)
        return value

    try:
        with wolvrix.Session() as session:
            session.log_level = 'error'
            session.diagnostics_raise_min_level = 'none'
            stage('ingest', lambda: checked(session.read_sources(
                **request, out_design='design.main', pipeline='ingest'), 'ingest'))
            for name in (*PREFIX, 'expr-opt'):
                path = timing_dir / (name + '.jsonl')
                stage(name, lambda name=name, path=path: checked(session.run_pass(
                    name, design='design.main',
                    keep_declared_symbols=name in PREFIX[:3], timing_output=str(path),
                    **({'semantics': '2state'} if name == 'expr-opt' else {})), name))
            profile_dir = args.output / 'profile'
            profile = stage('profile-setup', lambda: SplitProfile(profile_dir))
            timing = timing_dir / 'used-bits.jsonl'
            try:
                stage('used-bits', lambda: checked(session.run_pass(
                    'used-bits', design='design.main', keep_declared_symbols=False,
                    timing_output=str(timing), semantics='2state'), 'used-bits'))
            finally:
                stage('profile-finish', profile.finish)
            rows, indexed = timers(timing, 'grh')
            native_timer = indexed.get('pass', {}).get('used-bits#0')
            if native_timer is None:
                raise ValueError('missing exact UsedBits native timer')
            report.update(native_timer=native_timer, timing_file=str(timing),
                          timing_sha256=sha256(timing), native_timers=rows,
                          profile={'directory': str(profile_dir), 'symbols': profile.symbols,
                                   'frequency_hz': 99, 'call_graph': 'dwarf,8192',
                                   'scope': 'UsedBits call including mandatory validation/maintenance'})
            if args.finish_window:
                report['remaining_window_timers'] = []
                for name, logical in (('split-nodes', 'split-nodes#0'),
                                      ('dead-code-elim', 'dead-code-elim#1')):
                    path = timing_dir / (logical.replace('#', '-') + '.jsonl')
                    stage(logical, lambda name=name, path=path: checked(session.run_pass(
                        name, design='design.main', keep_declared_symbols=False,
                        timing_output=str(path),
                        **({'semantics': '2state'} if name == 'split-nodes' else {})), name))
                    _, indexed = timers(path, 'grh')
                    timer = indexed.get('pass', {}).get(name + '#0')
                    if timer is None:
                        raise ValueError('missing exact native timer for ' + logical)
                    report['remaining_window_timers'].append({
                        'logical_instance': logical, 'native_timer': timer,
                        'timing_file': str(path), 'timing_sha256': sha256(path)})
        after = resource.getrusage(resource.RUSAGE_SELF)
        report.update(status='completed', returncode=0, wall_s=time.monotonic() - started,
                      user_s=after.ru_utime - before.ru_utime,
                      system_s=after.ru_stime - before.ru_stime, maxrss_kib=after.ru_maxrss,
                      finished_at_ns=time.time_ns(),
                      active_stage={'name': 'complete', 'finished': True})
    except BaseException as error:
        report.update(status='failed', error=repr(error), failed_at_ns=time.time_ns())
        write_json_atomic(summary, report)
        raise
    write_json_atomic(summary, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firrtl', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cpus', type=int, nargs='+', default=[2])
    parser.add_argument('--finish-window', action='store_true',
                        help='continue unprofiled through SplitNodes and second DCE, then stop')
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    for field in ('firrtl', 'manifest', 'package', 'output'):
        setattr(args, field, getattr(args, field).resolve())
    if not args.output.is_relative_to(ROOT / 'ptmp'):
        parser.error('output must be under repository ptmp/')
    if args.child:
        run_sample(args)
        return
    if args.output.exists():
        parser.error('profile output must be a new directory')
    args.output.mkdir(parents=True)
    os.sched_setaffinity(0, args.cpus)
    command = [sys.executable, str(Path(__file__).resolve()), '--firrtl', str(args.firrtl),
               '--manifest', str(args.manifest), '--package', str(args.package),
               '--output', str(args.output), '--child']
    if args.finish_window:
        command.append('--finish-window')
    raise SystemExit(run_guarded(command, args.output, GuardLimits(), sampler=process_tree_sample,
                                phase_timeouts={'split-nodes#0': 180} if args.finish_window else None))


if __name__ == '__main__':
    main()
