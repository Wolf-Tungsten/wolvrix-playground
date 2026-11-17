"""Small child processes exercise external monitoring and termination evidence."""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from benchmark_f30_pipeline import ROOT
from f30_resource_guard import (GuardLimits, PhaseDeadline, PressureDeadline, ProcessMemoryUnavailable,
                                cgroup_memory, current_phase,
                                find_cgroup, process_memory, run_guarded)
from benchmark_f29_pass_trace import write_json_atomic


class ResourceGuardTests(unittest.TestCase):
    def setUp(self):
        root = ROOT / 'ptmp/firrtl-ingest/F30/resource-guard-contract'
        root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=root)
        self.work = Path(self.temporary.name)
        self.limits = GuardLimits(rss_bytes=128 * 1024**2, psi_seconds=0.1,
                                  interval_s=0.02, terminate_grace_s=0.5)

    def tearDown(self):
        self.temporary.cleanup()

    def child(self, *, delay=0.2, allocation=0, block_gil=False):
        program = '''import json, os, signal, sys, time
from pathlib import Path
work = Path(sys.argv[1])
summary = {'status': 'running', 'mode': 'no-trace',
    'active_stage': {'kind': 'prefix', 'name': 'hier-flatten'},
    'prefix': {'stages': [{'stage': 'ingest', 'wall_s': 0.01}]},
    'no_trace': {'passes': []}}
(work / 'summary.json').write_text(json.dumps(summary))
def stopped(number, frame):
    guard = json.loads((work / 'guard.json').read_text())
    (work / 'signal-evidence.json').write_text(json.dumps({
        'guard_status_before_signal': guard['status'], 'guard_reason': guard['reason'],
        'pid': os.getpid(), 'pgid': os.getpgrp()}))
    sys.exit(0)
signal.signal(signal.SIGTERM, stopped)
allocation = bytearray(int(sys.argv[3]))
(work / 'child-ready').write_text(str(os.getpid()))
if sys.argv[4] == 'gil':
    import ctypes
    ctypes.PyDLL(None).sleep(int(float(sys.argv[2])))
else:
    time.sleep(float(sys.argv[2]))
summary['status'] = 'passed'
(work / 'summary.json').write_text(json.dumps(summary))
'''
        return [sys.executable, '-c', program, str(self.work), str(delay), str(allocation),
                'gil' if block_gil else 'sleep']

    def guard(self):
        return json.loads((self.work / 'guard.json').read_text())

    def samples(self):
        return [json.loads(line) for line in (self.work / 'resources.samples.jsonl').read_text().splitlines()]

    @staticmethod
    def pressure_sample(high=True):
        return {'process_bytes': {'VmRSS': 1024}, 'cgroup': {'available': True,
            'pressure': {name: {'avg10': 30.0 if high else 0.0} for name in ('some', 'full')}}}

    def test_process_rss_and_cgroup_charged_memory_are_distinct(self):
        proc = self.work / 'proc/123'
        proc.mkdir(parents=True)
        (proc / 'status').write_text('Name:\tfixture\nVmRSS:\t100 kB\nRssAnon:\t70 kB\n'
                                      'RssFile:\t30 kB\nVmSwap:\t2 kB\nVmHWM:\t110 kB\n')
        (proc / 'cgroup').write_text('0::/fixture.scope\n')
        cg = self.work / 'cgroup/fixture.scope'
        cg.mkdir(parents=True)
        (cg / 'memory.current').write_text('100000000\n')
        (cg / 'memory.stat').write_text('anon 71680\nfile 99000000\nkernel 100\n')
        (cg / 'memory.swap.current').write_text('2048\n')
        (cg / 'memory.pressure').write_text('some avg10=26.00 avg60=1.00 avg300=0.00 total=200\n'
                                           'full avg10=2.00 avg60=0.00 avg300=0.00 total=20\n')
        memory = process_memory(123, self.work / 'proc')
        self.assertEqual(memory['VmRSS'], 102400)
        self.assertEqual(memory['RssAnon'], 71680)
        group = find_cgroup(123, self.work / 'proc', self.work / 'cgroup')
        observed = cgroup_memory(group)
        self.assertEqual(observed['memory_current_bytes'], 100000000)
        self.assertEqual(observed['memory_stat']['file'], 99000000)
        self.assertEqual(observed['pressure']['some']['avg10'], 26)
        self.assertNotEqual(observed['memory_current_bytes'], memory['VmRSS'])

    def test_low_memory_child_completes_with_full_samples_and_diagnostic_marker(self):
        self.assertEqual(run_guarded(self.child(), self.work, self.limits), 0)
        guard = self.guard()
        self.assertEqual(guard['status'], 'completed')
        self.assertTrue(guard['diagnostic_only'])
        self.assertGreater(guard['sample_count'], 1)
        self.assertEqual(guard['sample_count'], len(self.samples()))
        summary = json.loads((self.work / 'summary.json').read_text())
        self.assertEqual(summary['status'], 'passed')
        self.assertTrue(summary['resource_guard']['diagnostic_only'])
        self.assertNotIn('termination', summary)

    def test_real_rss_limit_is_persisted_before_signal_and_keeps_completed_stages(self):
        limits = replace(self.limits, rss_bytes=20 * 1024**2)
        self.assertEqual(run_guarded(self.child(delay=5, allocation=32 * 1024**2), self.work, limits), 1)
        guard = self.guard()
        self.assertEqual(guard['reason'], 'rss_limit')
        self.assertGreaterEqual(guard['last_sample']['process_bytes']['VmRSS'], limits.rss_bytes)
        evidence = json.loads((self.work / 'signal-evidence.json').read_text())
        self.assertEqual(evidence['guard_status_before_signal'], 'failed')
        self.assertEqual(evidence['guard_reason'], 'rss_limit')
        self.assertEqual(evidence['pid'], evidence['pgid'])
        self.assertNotEqual(evidence['pgid'], os.getpgrp())
        summary = json.loads((self.work / 'summary.json').read_text())
        self.assertEqual(summary['status'], 'failed')
        self.assertEqual(summary['prefix']['stages'][0]['wall_s'], 0.01)
        self.assertEqual(summary['no_trace']['passes'], [])
        self.assertNotIn('finished_at_ns', summary)
        self.assertEqual(summary['termination']['reason'], 'rss_limit')
        self.assertEqual(guard['last_sample']['phase']['name'], 'hier-flatten')

    def test_sustained_pressure_terminates_child_without_rss_limit(self):
        self.assertEqual(run_guarded(self.child(delay=5, block_gil=True), self.work, self.limits,
                                    sampler=lambda pid, group: self.pressure_sample()), 1)
        self.assertEqual(self.guard()['reason'], 'cgroup_pressure')
        self.assertLess(self.guard()['last_sample']['process_bytes']['VmRSS'], self.limits.rss_bytes)

    def test_phase_deadline_uses_native_call_start_and_resets_on_finished_phase(self):
        deadline = PhaseDeadline({'split-nodes#0': 5})
        phase = {'name': 'split-nodes#0', 'finished': False, 'started_monotonic_s': 10}
        self.assertFalse(deadline.observe(phase, 14.9))
        self.assertTrue(deadline.observe(phase, 15))
        self.assertEqual(deadline.trigger['elapsed_s'], 5)
        self.assertFalse(deadline.observe({**phase, 'finished': True}, 20))
        self.assertFalse(deadline.observe({'name': 'P3-snapshot'}, 21))
        self.assertFalse(deadline.observe({'name': 'split-nodes#0'}, 25))
        self.assertTrue(deadline.observe({'name': 'split-nodes#0'}, 30))
        for limits in ({'phase': 0}, {'phase': float('nan')}, {'': 1}):
            with self.assertRaises(ValueError):
                PhaseDeadline(limits)

    def test_phase_timeout_stops_gil_blocked_child_and_preserves_trigger_before_signal(self):
        started = time.monotonic()
        self.assertEqual(run_guarded(self.child(delay=5, block_gil=True), self.work, self.limits,
            phase_timeouts={'hier-flatten': 0.1}), 1)
        self.assertLess(time.monotonic() - started, 2)
        guard = self.guard()
        self.assertEqual(guard['reason'], 'phase_timeout')
        self.assertEqual(guard['phase_timeouts_s'], {'hier-flatten': 0.1})
        self.assertEqual(guard['phase_timeout_trigger']['name'], 'hier-flatten')
        self.assertGreaterEqual(guard['phase_timeout_trigger']['elapsed_s'], 0.1)
        self.assertEqual(guard['phase']['name'], 'hier-flatten')
        summary = json.loads((self.work / 'summary.json').read_text())
        self.assertEqual(summary['status'], 'failed')
        self.assertEqual(summary['termination']['reason'], 'phase_timeout')
        self.assertEqual(summary['no_trace']['passes'], [])
        self.assertNotIn('finished_at_ns', summary)

    def test_user_service_pressure_is_independent_and_available_sources_survive_degradation(self):
        service = self.work / 'cgroup/user@1000.service'
        scope = service / 'benchmark.scope'
        scope.mkdir(parents=True)
        (scope / 'memory.current').write_text('123\n')
        (scope / 'memory.stat').write_text('anon 100\nfile 23\n')
        pressure = 'some avg10=30.00 avg60=1.00 avg300=0.00 total=200\nfull avg10=0.00 total=0\n'
        (scope / 'memory.pressure').write_text(pressure.replace('30.00', '0.00'))
        (service / 'memory.pressure').write_text(pressure)
        group = cgroup_memory(scope)
        self.assertEqual(group['memory_current_bytes'], 123)
        self.assertEqual(group['pressure']['some']['avg10'], 0)
        deadline = PressureDeadline(GuardLimits())
        self.assertFalse(deadline.observe({'cgroup': group}, 10))
        self.assertTrue(deadline.observe({'cgroup': group}, 18))
        self.assertEqual(deadline.trigger['path'], str(service))
        self.assertEqual(deadline.trigger['kind'], 'some')
        self.assertEqual(deadline.trigger['sustained_s'], 8)
        # A missing scope pressure file cannot disable a readable ancestor.
        (scope / 'memory.pressure').unlink()
        self.assertTrue(deadline.observe({'cgroup': cgroup_memory(scope)}, 19))
        # Conversely, a missing ancestor leaves the scope pressure guard active.
        (service / 'memory.pressure').unlink()
        (scope / 'memory.pressure').write_text(pressure)
        self.assertTrue(deadline.observe({'cgroup': cgroup_memory(scope)}, 20))
        self.assertEqual(deadline.trigger['path'], str(scope))

    def test_transient_pressure_does_not_trigger_and_defaults_require_eight_seconds(self):
        deadline = PressureDeadline(GuardLimits())
        self.assertFalse(deadline.observe(self.pressure_sample(), 10))
        self.assertFalse(deadline.observe(self.pressure_sample(), 17.99))
        self.assertTrue(deadline.observe(self.pressure_sample(), 18))
        self.assertFalse(deadline.observe(self.pressure_sample(False), 19))
        self.assertFalse(deadline.observe(self.pressure_sample(), 25))
        calls = []
        def sample(pid, group):
            calls.append(pid)
            return self.pressure_sample(len(calls) <= 2)
        self.assertEqual(run_guarded(self.child(), self.work, self.limits, sampler=sample), 0)

    def test_no_cgroup_degrades_to_explicit_rss_only_guard(self):
        with patch('f30_resource_guard.find_cgroup', return_value=None):
            self.assertEqual(run_guarded(self.child(), self.work, self.limits), 0)
        self.assertIsNone(self.guard()['cgroup_path'])
        self.assertTrue(all(not row['cgroup']['available'] for row in self.samples()))
        self.assertTrue(all('VmRSS' in row['process_bytes'] for row in self.samples()))

    def test_unreadable_rss_fails_closed_and_stops_private_child(self):
        with patch('f30_resource_guard.process_memory', side_effect=ValueError('missing VmRSS')):
            self.assertEqual(run_guarded(self.child(delay=5), self.work, self.limits), 1)
        self.assertEqual(self.guard()['reason'], 'monitor_error')
        self.assertIn('missing VmRSS', self.guard()['error'])

    def test_missing_rss_exit_race_requires_actual_success_or_nonzero_child_exit(self):
        for returncode in (0, 7):
            with self.subTest(returncode=returncode):
                output = self.work / ('exit-race-' + str(returncode))
                output.mkdir()
                (output / 'summary.json').write_text(json.dumps({'status': 'passed',
                    'active_stage': {'kind': 'complete', 'name': 'completed'}}))
                # Deterministically model exit_mm being visible before waitpid:
                # the second poll still says live, but the bounded wait reaps it.
                child = Mock(pid=999999, returncode=None)
                child.poll.return_value = None
                child.wait.return_value = returncode
                with patch('f30_resource_guard.subprocess.Popen', return_value=child), \
                        patch('f30_resource_guard.find_cgroup', return_value=None), \
                        patch('f30_resource_guard.process_memory',
                              side_effect=ProcessMemoryUnavailable('benchmark VmRSS is unavailable')), \
                        patch('f30_resource_guard.terminate_child', return_value=returncode) as cleanup:
                    self.assertEqual(run_guarded(['fixture'], output, self.limits),
                                     0 if returncode == 0 else 1)
                self.assertEqual(child.poll.call_count, 2)
                self.assertEqual(child.wait.call_args_list[0].kwargs, {'timeout': self.limits.terminate_grace_s})
                cleanup.assert_called_once_with(child, self.limits.terminate_grace_s)
                guard = json.loads((output / 'guard.json').read_text())
                self.assertEqual(guard['returncode'], returncode)
                self.assertEqual(guard['reason'], 'child_completed' if returncode == 0 else 'child_exit')
                self.assertEqual(guard['exit_observation']['returncode'], returncode)
                summary = json.loads((output / 'summary.json').read_text())
                self.assertEqual(summary['status'], 'passed' if returncode == 0 else 'failed')
                self.assertNotIn('error', guard)
                if returncode == 0:
                    self.assertNotIn('termination', summary)
                else:
                    self.assertEqual(summary['termination']['reason'], 'child_exit')

    def test_missing_rss_allows_real_exit_longer_than_one_hundred_milliseconds(self):
        limits = replace(self.limits, terminate_grace_s=GuardLimits().terminate_grace_s)
        self.assertEqual(limits.terminate_grace_s, 2)
        for returncode in (0, 7):
            with self.subTest(returncode=returncode):
                output = self.work / ('delayed-exit-' + str(returncode))
                output.mkdir()
                ready, release = output / 'ready', output / 'release'
                program = '''import json, sys, time
from pathlib import Path
work = Path(sys.argv[1])
(work / 'summary.json').write_text(json.dumps({'status': 'passed',
    'active_stage': {'kind': 'complete', 'name': 'completed'}}))
(work / 'ready').touch()
while not (work / 'release').exists():
    time.sleep(0.001)
time.sleep(0.25)
raise SystemExit(int(sys.argv[2]))
'''
                def unavailable(pid, group):
                    until = time.monotonic() + 2
                    while not ready.exists():
                        if time.monotonic() >= until:
                            self.fail('delayed-exit fixture did not become ready')
                        time.sleep(0.001)
                    release.touch()
                    if returncode:
                        raise FileNotFoundError('fixture process status disappeared during exit')
                    raise ProcessMemoryUnavailable('benchmark VmRSS is unavailable')
                self.assertEqual(run_guarded([sys.executable, '-c', program, str(output), str(returncode)],
                                             output, limits, sampler=unavailable),
                                 0 if returncode == 0 else 1)
                guard = json.loads((output / 'guard.json').read_text())
                self.assertEqual(guard['reason'], 'child_completed' if returncode == 0 else 'child_exit')
                self.assertEqual(guard['returncode'], returncode)
                self.assertGreaterEqual(guard['exit_observation']['waited_s'], 0.2)
                self.assertEqual(guard['exit_observation']['maximum_wait_s'], 2)
                self.assertNotIn('error', guard)

    def test_live_child_missing_rss_remains_failure_even_when_summary_says_complete(self):
        (self.work / 'summary.json').write_text(json.dumps({'status': 'passed',
            'active_stage': {'kind': 'complete', 'name': 'completed'}}))
        command = [sys.executable, '-c', 'import time; time.sleep(5)']
        limits = replace(self.limits, terminate_grace_s=GuardLimits().terminate_grace_s)
        started = time.monotonic()
        with patch('f30_resource_guard.process_memory',
                   side_effect=ProcessMemoryUnavailable('benchmark VmRSS is unavailable')):
            self.assertEqual(run_guarded(command, self.work, limits), 1)
        self.assertGreaterEqual(time.monotonic() - started, limits.terminate_grace_s)
        guard = self.guard()
        self.assertEqual(guard['reason'], 'monitor_error')
        self.assertNotIn('exit_observation', guard)
        self.assertIn('VmRSS is unavailable', guard['error'])
        self.assertNotEqual(guard['returncode'], 0)
        self.assertEqual(json.loads((self.work / 'summary.json').read_text())['status'], 'failed')

    def test_process_status_without_rss_identifies_exit_race_without_inventing_zero_rss(self):
        proc = self.work / 'proc/123'
        proc.mkdir(parents=True)
        (proc / 'status').write_text('Name:\tfixture\nState:\tZ (zombie)\n')
        with self.assertRaises(ProcessMemoryUnavailable):
            process_memory(123, self.work / 'proc')

    def test_phase_reports_incomplete_prefix_and_next_transform_without_fake_completion(self):
        summary = self.work / 'summary.json'
        summary.write_text(json.dumps({'active_stage': {'kind': 'prefix', 'name': 'hier-flatten'}}))
        self.assertEqual(current_phase(self.work)['name'], 'hier-flatten')
        summary.write_text(json.dumps({'mode': 'trace', 'active_stage': {'kind': 'transform'}}))
        (self.work / 'trace').mkdir()
        timing = self.work / 'trace/timing.json'
        timing.write_text(json.dumps({'passes': []}))
        self.assertEqual(current_phase(self.work)['name'], 'comb-loop-elim')
        timing.write_text(json.dumps({'passes': [{'pass': 'comb-loop-elim', 'status': 'passed'}]}))
        self.assertEqual(current_phase(self.work)['name'], 'split-static-array')

    def test_supervisor_sigterm_stops_child_and_keeps_signal_evidence(self):
        program = ('import sys; from pathlib import Path; '
                   'sys.path.insert(0, sys.argv[1]); '
                   'from f30_resource_guard import run_guarded, GuardLimits; '
                   'raise SystemExit(run_guarded(sys.argv[3:], Path(sys.argv[2]), '
                   'GuardLimits(interval_s=0.02, terminate_grace_s=0.5)))')
        supervisor = subprocess.Popen([sys.executable, '-c', program, str(ROOT / 'scripts'),
                                       str(self.work), *self.child(delay=5)])
        try:
            until = time.monotonic() + 3
            while not (self.work / 'child-ready').exists() and supervisor.poll() is None:
                if time.monotonic() >= until:
                    self.fail('guard child did not become ready')
                time.sleep(0.01)
            os.kill(supervisor.pid, signal.SIGTERM)
            self.assertEqual(supervisor.wait(timeout=3), 1)
            guard = self.guard()
            self.assertEqual(guard['reason'], 'supervisor_signal')
            self.assertEqual(guard['signal'], signal.SIGTERM)
            with self.assertRaises(ProcessLookupError):
                os.kill(guard['benchmark_pid'], 0)
            self.assertTrue((self.work / 'signal-evidence.json').is_file())
        finally:
            if supervisor.poll() is None:
                supervisor.terminate()
                supervisor.wait(timeout=3)

    def test_persistence_failure_cannot_leave_benchmark_alive_or_replace_original_error(self):
        spawned = []
        real_popen = subprocess.Popen
        def popen(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            spawned.append(child)
            return child
        def failing_write(path, value):
            if path.name == 'guard.json' and 'benchmark_pid' in value:
                raise OSError('fixture disk is full')
            return write_json_atomic(path, value)
        with patch('f30_resource_guard.subprocess.Popen', side_effect=popen), \
                patch('f30_resource_guard.write_json_atomic', side_effect=failing_write):
            with self.assertRaisesRegex(OSError, 'fixture disk is full'):
                run_guarded(self.child(delay=5), self.work, self.limits)
        self.assertEqual(len(spawned), 1)
        self.assertIsNotNone(spawned[0].poll())

    def test_normal_and_failed_child_exit_clean_up_private_helpers(self):
        for returncode in (0, 7):
            with self.subTest(returncode=returncode):
                output = self.work / str(returncode)
                output.mkdir()
                helper_pid = output / 'helper.pid'
                program = '''import json, os, signal, subprocess, sys, time
from pathlib import Path
work = Path(sys.argv[1])
helper = subprocess.Popen([sys.executable, '-c',
    'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(10)'])
(work / 'helper.pid').write_text(str(helper.pid))
(work / 'summary.json').write_text(json.dumps({'status': 'passed' if sys.argv[2] == '0' else 'failed'}))
time.sleep(0.05)
raise SystemExit(int(sys.argv[2]))
'''
                self.assertEqual(run_guarded([sys.executable, '-c', program, str(output), str(returncode)],
                                             output, self.limits), 0 if returncode == 0 else 1)
                pid = int(helper_pid.read_text())
                until = time.monotonic() + 1
                while True:
                    try:
                        state = (Path('/proc') / str(pid) / 'status').read_text()
                    except FileNotFoundError:
                        break
                    if '\nState:\tZ' in state:
                        break  # Reparented zombies are no longer running helpers.
                    if time.monotonic() >= until:
                        self.fail('private helper survived supervisor cleanup')
                    time.sleep(0.01)

    def test_existing_guard_evidence_and_invalid_limits_are_rejected(self):
        for limits in (replace(self.limits, rss_bytes=0), replace(self.limits, interval_s=2),
                       replace(self.limits, psi_percent=float('nan'))):
            with self.assertRaises(ValueError):
                run_guarded(self.child(), self.work, limits)
        (self.work / 'guard.json').write_text('retained evidence\n')
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            run_guarded(self.child(), self.work, self.limits)
        self.assertEqual((self.work / 'guard.json').read_text(), 'retained evidence\n')


if __name__ == '__main__':
    unittest.main()
