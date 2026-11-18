"""Contract tests for F33 references, latched events, and external termination."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from benchmark_f29_pass_trace import sha256
from f30_resource_guard import GuardLimits
from f33_guard import (BOUNDARIES, GSIM_TIMERS, PASSES, PassDeadline, SupervisorLimits,
                       _messages, _PipeReader, _send, _start_worker, _stop_worker,
                       build_reference, run_guarded, validate_reference)


ROOT = Path(__file__).resolve().parents[1]


def fixed_sample(pid, group):
    return {'process_bytes': {'VmRSS': 1024}, 'cgroup': {'available': False}}


def stalled_sample(pid, group):
    time.sleep(10)
    return fixed_sample(pid, group)


def blocked_pipe_writer(channel):
    os.setsid()
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    # A single frame exceeds typical pipe capacity; no parent drain is needed
    # to prove private-worker cleanup remains bounded under backpressure.
    while True:
        _send(channel, 'large-diagnostic', 'x' * 59000)


class PipeTransportTests(unittest.TestCase):
    def channel(self):
        receive, send = os.pipe()
        os.set_blocking(receive, False)
        reader = _PipeReader(receive)
        self.addCleanup(reader.close)
        return reader, send

    def test_partial_pipe_frames_are_buffered_without_blocking(self):
        reader, send = self.channel()
        data = json.dumps({'kind': 'event', 'value': {'event': 'start'}}).encode() + b'\n'
        os.write(send, data[:9])
        self.assertEqual(list(_messages(reader)), [])
        self.assertEqual(reader.pending, data[:9])
        os.write(send, data[9:])
        os.close(send)
        self.assertEqual(list(_messages(reader)), [{'kind': 'event', 'value': {'event': 'start'}}])
        self.assertEqual(list(_messages(reader)), [])

    def test_coalesced_pipe_frames_preserve_order_and_yield_after_bound(self):
        reader, send = self.channel()
        data = b''.join(json.dumps({'kind': 'test', 'value': index}).encode() + b'\n' for index in range(70))
        os.write(send, data)
        os.close(send)
        first, second = list(_messages(reader)), list(_messages(reader))
        self.assertEqual(len(first), 64)
        self.assertEqual([row['value'] for row in first + second], list(range(70)))

    def test_eof_with_unterminated_frame_fails_closed(self):
        reader, send = self.channel()
        os.write(send, b'{"kind":"event"')
        os.close(send)
        self.assertEqual(list(_messages(reader)), [])
        with self.assertRaisesRegex(ValueError, 'truncated'):
            list(_messages(reader))

    def test_oversized_and_corrupt_frames_fail_closed(self):
        reader, send = self.channel()
        os.close(send)
        reader.pending = b'x' * 60001 + b'\n'
        with self.assertRaisesRegex(ValueError, 'exceeds bound'):
            list(_messages(reader))
        reader.pending = b'{broken json}\n'
        with self.assertRaises(ValueError):
            list(_messages(reader))

    def test_sender_handles_short_writes_without_dropping_frame_bytes(self):
        chunks = []
        def short_write(descriptor, data):
            chunk = bytes(data[:3])
            chunks.append(chunk)
            return len(chunk)
        with patch('f33_guard.os.write', side_effect=short_write):
            _send(123, 'test', 'payload')
        self.assertEqual(json.loads(b''.join(chunks)), {'kind': 'test', 'value': 'payload'})

    def test_backpressured_monitor_worker_is_cleaned_without_parent_read(self):
        worker, channel = _start_worker(blocked_pipe_writer, ())
        started = time.monotonic()
        time.sleep(0.02)
        _stop_worker(worker, channel, 0.05)
        self.assertFalse(worker.is_alive())
        self.assertLess(time.monotonic() - started, 0.5)
        with self.assertRaises(ProcessLookupError):
            os.kill(worker.pid, 0)


class GuardTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'ptmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='f33-guard-test-', dir=ROOT / 'ptmp')
        self.root = Path(self.temp.name)
        self.artifact = self.root / 'native-timer.jsonl'
        self.artifact.write_text('immutable native timing evidence\n')
        self.identity = {'input': {'sha256': 'a' * 64}, 'configuration': {'cpu': 'test'},
                         'semantics': '2state', 'batch_count': 1,
                         'grh': {'source_sha256': 'b' * 64, 'binary_sha256': 'c' * 64,
                                 'build': {'type': 'Release'}},
                         'gsim': {'source_sha256': 'd' * 64, 'binary_sha256': 'e' * 64,
                                  'build': {'type': 'Release'}}}

    def tearDown(self):
        self.temp.cleanup()

    def samples(self, duration=0.1):
        samples = []
        durations = duration if isinstance(duration, list) else [duration] * 3
        for index in range(3):
            duration = durations[index]
            directory = self.root / ('reference-' + str(index))
            directory.mkdir(exist_ok=True)
            run_id = 'sample-' + str(index)
            timers, events = [], []
            for offset, key in enumerate(PASSES):
                timers.append({'schema': 'gsim-stage-timing.v1', 'scope': 'pass',
                               'stage': 'ConstantAnalysis' if not offset else 'RemoveDeadNodes2',
                               'pass_instance': GSIM_TIMERS[key], 'clock': 'steady_clock',
                               'complete': True, 'wall_s': duration,
                               'batch_count': self.identity['batch_count']})
                for kind in ('start', 'end'):
                    row = {'run_id': run_id, 'engine': 'gsim', 'logical_instance': key,
                           'input_boundary': BOUNDARIES[key], 'event': kind,
                           'batch_count': self.identity['batch_count'],
                           'monotonic_s': 10 + 2 * offset + (1 if kind == 'end' else 0)}
                    if kind == 'end':
                        row['wall_s'] = duration
                    events.append(row)
            guard = {'schema': 'wolvrix.f33.guard.v1', 'status': 'completed', 'run_id': run_id,
                     'engine': 'gsim', 'resource_interference': False, 'reference_identity': self.identity,
                     'pass_times_s': {key: duration for key in PASSES}, 'event_errors': []}
            records = []
            for kind, data in (('native-timing', timers), ('stage-events', events), ('guard', guard)):
                path = directory / (kind + '.json')
                path.write_text(('\n'.join(json.dumps(row) for row in data) + '\n')
                                if isinstance(data, list) else json.dumps(data))
                records.append({'kind': kind, 'path': str(path), 'sha256': sha256(path)})
            samples.append({'status': 'completed', 'engine': 'gsim', 'run_id': run_id,
                            'reference_identity': self.identity, 'fresh_graphs': self.identity['batch_count'],
                            'resource_interference': False,
                            'reference_evidence': records, 'pass_times_s': {key: duration for key in PASSES}})
        return samples

    def reference(self, duration=0.1):
        return build_reference(self.samples(duration), self.identity)

    def limits(self, **kwargs):
        return SupervisorLimits(resources=GuardLimits(interval_s=0.01, terminate_grace_s=0.05),
                                poll_s=0.005, prefix_s=1.0, between_passes_s=1.0, suffix_s=1.0,
                                overall_s=3.0, sampler_stall_s=2.0, **kwargs)

    def child(self, body):
        output = self.root / 'run'
        code = '''import json, os, signal, subprocess, sys, time
from pathlib import Path
output = Path(sys.argv[1])
def emit(key, kind, duration=None):
    row = dict(run_id='run', engine='grh', logical_instance=key,
               input_boundary={'constant-analysis#0':'Q0','dead-code-elim#2':'Q1'}[key],
               event=kind, monotonic_s=time.monotonic())
    if duration is not None: row['wall_s'] = duration
    with (output/'stage-events.jsonl').open('a') as stream:
        stream.write(json.dumps(row)+'\\n')
        stream.flush()
'''
        return output, [sys.executable, '-c', code + '\n' + body, str(output)]

    def run_child(self, body, duration=0.1, sampler=fixed_sample):
        output, command = self.child(body)
        result = run_guarded(command, output, run_id='run', engine='grh', identity=self.identity,
                             reference=self.reference(duration), limits=self.limits(), sampler=sampler)
        return result, json.loads((output / 'guard.json').read_text()), output

    def test_reference_median_mapping_and_no_floor(self):
        samples = self.samples(0.00002)
        reference = build_reference(samples, self.identity)
        budgets = validate_reference(reference, self.identity)
        self.assertEqual(budgets[PASSES[0]], 0.00004)
        self.assertEqual(reference['passes'][PASSES[1]]['native_timer'], 'RemoveDeadNodes#1')
        self.assertEqual(reference['passes'][PASSES[1]]['input_boundary'], 'Q1')

    def test_reject_invalid_reference_or_configuration(self):
        for duration in (0, -1, float('inf'), float('nan')):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                self.reference(duration)
        with self.assertRaises(ValueError):
            build_reference(self.samples()[:2], self.identity)
        for field in ('input', 'configuration', 'semantics', 'grh', 'gsim', 'batch_count'):
            changed = copy.deepcopy(self.identity)
            changed[field] = 'different'
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_reference(self.reference(), changed)
        for change in ('interference', 'reused-graph', 'duplicate-run', 'timer-map', 'jitter'):
            samples = self.samples([0.1, 0.1, 0.3] if change == 'jitter' else 0.1)
            if change == 'interference':
                samples[0]['resource_interference'] = True
            elif change == 'reused-graph':
                samples[0]['fresh_graphs'] = 0
            elif change == 'duplicate-run':
                samples[0]['run_id'] = samples[1]['run_id']
            elif change == 'timer-map':
                samples[0]['pass_times_s']['dead-code-elim#1'] = samples[0]['pass_times_s'].pop(PASSES[1])
            with self.subTest(change=change), self.assertRaises(ValueError):
                build_reference(samples, self.identity)

    def test_reference_recomputed_values_cannot_replace_native_evidence(self):
        reference = self.reference()
        changed = copy.deepcopy(reference)
        for row in changed['samples']:
            row['pass_times_s'][PASSES[0]] = 1.0
        changed['passes'][PASSES[0]].update(samples_s=[1.0, 1.0, 1.0], median_s=1.0, budget_s=2.0)
        with self.assertRaises(ValueError):
            validate_reference(changed, self.identity)

    def test_independent_batch_identity_and_event_count_must_match(self):
        self.identity['batch_count'] = 4
        reference = self.reference()
        self.assertEqual(validate_reference(reference, self.identity)[PASSES[0]], 0.2)
        changed = copy.deepcopy(self.identity)
        changed['batch_count'] = 1
        with self.assertRaises(ValueError):
            validate_reference(reference, changed)
        tracker = PassDeadline('run', 'grh', {PASSES[0]: 0.1}, batch_count=4)
        event = self.event(PASSES[0], 'start', 10, batch_count=1)
        tracker.consume(event, 10)
        self.assertIsNone(tracker.active)
        self.assertTrue(tracker.errors)

    def test_missing_reference_refuses_spawn(self):
        output, command = self.child("(output/'spawned').touch()")
        with self.assertRaises(ValueError):
            run_guarded(command, output, run_id='run', engine='grh', identity=self.identity)
        self.assertFalse((output / 'spawned').exists())

    def event(self, key, kind, stamp, **kwargs):
        return {'run_id': 'run', 'engine': 'grh', 'logical_instance': key,
                'input_boundary': BOUNDARIES[key], 'event': kind, 'monotonic_s': stamp, **kwargs}

    def test_equal_completed_threshold_and_running_threshold(self):
        tracker = PassDeadline('run', 'grh', {PASSES[0]: 2.0})
        tracker.consume(self.event(PASSES[0], 'start', 10.0), 10.0)
        tracker.consume(self.event(PASSES[0], 'end', 12.0, wall_s=2.0), 12.1)
        self.assertIsNone(tracker.observe(30.0))
        tracker = PassDeadline('run', 'grh', {PASSES[0]: 2.0})
        tracker.consume(self.event(PASSES[0], 'start', 10.0), 10.0)
        self.assertIsNone(tracker.observe(11.999))
        self.assertEqual(tracker.observe(12.0)['kind'], 'running-pass-at-budget')

    def test_late_native_success_above_budget_is_blocked(self):
        result, guard, _ = self.run_child("""emit('constant-analysis#0', 'start')
emit('constant-analysis#0', 'end', 0.201)
emit('dead-code-elim#2', 'start')
emit('dead-code-elim#2', 'end', 0.01)
""")
        self.assertEqual(result, 2)
        self.assertEqual(guard['status'], 'performance-blocked')
        self.assertEqual(guard['trigger']['kind'], 'completed-pass-over-budget')
        self.assertEqual(guard['next_action'], 'optimize-pass')

    def test_native_like_blocked_child_terminated_and_evidence_first(self):
        result, guard, output = self.run_child("""def terminated(signum, frame):
    (output/'evidence-before-signal').write_text(str((output/'guard-trigger.json').exists()))
    sys.exit(7)
signal.signal(signal.SIGTERM, terminated)
emit('constant-analysis#0', 'start')
time.sleep(20)
""", duration=0.05)
        self.assertEqual(result, 2)
        self.assertEqual(guard['status'], 'performance-blocked')
        self.assertLess(guard['trigger']['observation_delay_s'], 0.250)
        self.assertLess(guard['wall_s'], 1.0)
        self.assertEqual((output / 'evidence-before-signal').read_text(), 'True')
        self.assertEqual(guard['completed_passes'], [])
        self.assertFalse(json.loads((output / 'summary.json').read_text())['valid_checkpoint'])

    def test_missing_corrupt_progress_after_start_cannot_clear_deadline(self):
        for damage in ('missing', 'invalid', 'truncated'):
            with self.subTest(damage=damage):
                if (self.root / 'run').exists():
                    import shutil
                    shutil.rmtree(self.root / 'run')
                operation = {"missing": "(output/'stage-events.jsonl').unlink()",
                             "invalid": "(output/'stage-events.jsonl').open('a').write('{bad json}\\n')",
                             "truncated": "(output/'stage-events.jsonl').write_text('bad\\n')"}[damage]
                result, guard, _ = self.run_child("emit('constant-analysis#0','start')\n"
                                                  "time.sleep(0.03)\n" + operation + "\ntime.sleep(20)", duration=0.06)
                self.assertEqual(result, 2)
                self.assertEqual(guard['status'], 'performance-blocked')
                self.assertTrue(guard['event_errors'])

    def test_slow_snapshot_not_charged_to_pass(self):
        result, guard, _ = self.run_child("""emit('constant-analysis#0','start')
emit('constant-analysis#0','end',0.02)
time.sleep(0.3)
emit('dead-code-elim#2','start')
emit('dead-code-elim#2','end',0.02)
time.sleep(0.3)
""", duration=0.05)
        self.assertEqual(result, 0)
        self.assertEqual(guard['status'], 'completed')
        self.assertGreater(guard['wall_s'], 0.6)

    def test_sampler_stall_does_not_block_deadline(self):
        result, guard, _ = self.run_child("emit('constant-analysis#0','start')\ntime.sleep(20)",
                                         duration=0.05, sampler=stalled_sample)
        self.assertEqual(result, 2)
        self.assertEqual(guard['status'], 'performance-blocked')
        self.assertLess(guard['trigger']['observation_delay_s'], 0.25)
        self.assertLess(guard['wall_s'], 1.0)
        for pid in guard['monitor_pids']:
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_failure_evidence_preserved_and_refuses_overwrite(self):
        _, guard, output = self.run_child("emit('constant-analysis#0','start')\ntime.sleep(20)", duration=0.04)
        original = (output / 'guard-trigger.json').read_bytes()
        with self.assertRaises(ValueError):
            run_guarded(['false'], output, run_id='run', engine='grh', identity=self.identity,
                        reference=self.reference(), limits=self.limits(), sampler=fixed_sample)
        self.assertEqual((output / 'guard-trigger.json').read_bytes(), original)

    def test_cleanup_ignoring_helper_in_private_process_group(self):
        result, guard, output = self.run_child("""helper = subprocess.Popen([sys.executable, '-c',
    'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(20)'])
(output/'helper.pid').write_text(str(helper.pid))
signal.signal(signal.SIGTERM, signal.SIG_IGN)
emit('constant-analysis#0','start')
time.sleep(20)
""", duration=0.05)
        self.assertEqual(result, 2)
        pid = int((output / 'helper.pid').read_text())
        status = Path('/proc') / str(pid) / 'status'
        # An orphan may remain as a zombie until the container init reaps it.
        if status.exists():
            self.assertIn('State:\tZ', status.read_text())

    def test_wrong_dce_occurrence_and_incomplete_child_never_pass(self):
        tracker = PassDeadline('run', 'grh', {key: 1 for key in PASSES})
        wrong = self.event(PASSES[0], 'start', 10)
        wrong.update(logical_instance='dead-code-elim#1', input_boundary='Q0')
        tracker.consume(wrong, 10)
        self.assertTrue(tracker.errors)
        self.assertIsNone(tracker.active)
        result, guard, _ = self.run_child("emit('constant-analysis#0','start')\n")
        self.assertEqual(result, 2)
        self.assertEqual(guard['trigger']['kind'], 'incomplete-pass-events')

    def test_changed_reference_artifact_rejected(self):
        reference = self.reference()
        Path(reference['samples'][0]['reference_evidence'][0]['path']).write_text('modified')
        with self.assertRaises(ValueError):
            validate_reference(reference, self.identity)


if __name__ == '__main__':
    unittest.main()
