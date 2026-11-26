import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest

from f35_pass_guard import (EVENT_FD, EVENT_SCHEMA, F36_PASSES, GSIM_TIMER_ORDER, PASSES, Passes,
                            reference_budgets, run_guarded)


CHILD = '''
import json, os, subprocess, sys, time

fd, run_id, schema, mode, *passes = sys.argv[1:]
fd = int(os.environ[fd])
for key in passes:
    row = dict(schema=schema, run_id=run_id, logical_instance=key,
               input_boundary='complete-before-' + key, event='start', monotonic_s=time.monotonic())
    if mode == 'stuck':
        helper = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        print(helper.pid, flush=True)
    os.write(fd, (json.dumps(row) + '\\n').encode())
    if mode == 'stuck':
        time.sleep(30)
    if mode == 'invalid':
        row['run_id'] = 'different-run'
    row.update(event='end', monotonic_s=time.monotonic(), wall_s=1e-8)
    os.write(fd, (json.dumps(row) + '\\n').encode())
'''


NATIVE_CHILD = '''
import sys

import wolvrix
from capture_f34_pipeline import production_calls
from f35_pass_guard import stage_event_options
from wolvrix_xs_grhsim import firrtl_canonical_pipeline

with wolvrix.Session() as session:
    session.log_level = 'error'
    session.read_sources(sources=[{'path': sys.argv[1], 'language': 'firrtl'}], tops=['PassTrace'],
                         out_design='design.main', pipeline='ingest',
                         firrtl_options={'node_annotations': True})
    boundary = 'ingest'
    prefix, window = production_calls(firrtl_canonical_pipeline(remove_singleton_state_axis=False))
    for name, instance, keep, options in prefix + window:
        session.run_pass(name, design='design.main', keep_declared_symbols=keep, timing_output=sys.argv[2],
                         **stage_event_options('native', instance, boundary), **options)
        boundary = instance
'''


class F35PassGuardTests(unittest.TestCase):
    def test_native_reference_uses_only_pass_scope_and_exact_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / 'native-timing.jsonl'
            rows = [{'schema': 'gsim-stage-timing.v1', 'stage': stage, 'pass_instance': instance,
                     'scope': 'pass', 'clock': 'steady_clock', 'wall_s': index / 10,
                     'complete': True, 'batch_count': 1}
                    for index, (stage, instance) in enumerate(GSIM_TIMER_ORDER, start=1)]
            boundary = {**rows[-1], 'scope': 'boundary', 'wall_s': 100}
            reference.write_text(''.join(json.dumps(row) + '\n' for row in [*rows, boundary]))
            budgets = reference_budgets(reference, xmr_limit_s=21, flatten_limit_s=93)
            self.assertEqual(tuple(budgets), PASSES)
            self.assertEqual(budgets['xmr-resolve#0'], 21)
            self.assertEqual(budgets['hier-flatten#0'], 93)
            self.assertEqual(budgets['comb-loop-elim#0'], 1)
            self.assertEqual(budgets['split-static-array#0'], 0.8)
            self.assertEqual(budgets['dead-code-elim#0'], 1.6)
            self.assertEqual(budgets['dead-code-elim#3'], 3.6)
            for bad in (rows[:-1], rows + [rows[-1]], [*rows[:-1], {**rows[-1], 'wall_s': 0}],
                        [*rows[:-1], {**rows[-1], 'stage': 'RemoveDeadNodes4'}]):
                with self.subTest(bad=bad[-1]):
                    reference.write_text(''.join(json.dumps(row) + '\n' for row in bad))
                    with self.assertRaises(ValueError):
                        reference_budgets(reference, xmr_limit_s=21, flatten_limit_s=93)

    def test_native_completion_equal_to_budget_is_valid(self):
        for duration, kind in ((0.01, None), (0.011, 'completed-pass-over-budget')):
            with self.subTest(duration=duration):
                tracker = Passes('test', dict.fromkeys(PASSES, 0.01))
                base = {'schema': EVENT_SCHEMA, 'run_id': 'test', 'logical_instance': PASSES[0],
                        'input_boundary': 'ingest'}
                tracker.consume({**base, 'event': 'start', 'monotonic_s': 10}, 10)
                tracker.consume({**base, 'event': 'end', 'monotonic_s': 10 + duration,
                                 'wall_s': duration}, 10.03)
                if kind is None:
                    self.assertIsNone(tracker.trigger)
                    self.assertEqual(tracker.completed, {PASSES[0]: duration})
                else:
                    self.assertEqual(tracker.trigger['kind'], kind)
                    self.assertEqual(tracker.trigger['native_wall_s'], duration)

    def run_child(self, directory, mode, passes=PASSES):
        command = [sys.executable, '-c', CHILD, EVENT_FD, 'test', EVENT_SCHEMA, mode, *passes]
        code = run_guarded(command, directory, run_id='test', budgets=dict.fromkeys(passes, 0.2), passes=passes)
        return code, json.loads((directory / 'guard.json').read_text())

    def test_all_production_events_and_native_times_are_recorded(self):
        for passes in (PASSES, F36_PASSES):
            with self.subTest(passes=passes), tempfile.TemporaryDirectory() as directory:
                work = Path(directory)
                code, report = self.run_child(work, 'normal', passes=passes)
                self.assertEqual(code, 0)
                self.assertEqual(report['status'], 'completed')
                self.assertEqual(tuple(report['pass_times_s']), passes)
                events = (work / 'stage-events.jsonl').read_text().splitlines()
                self.assertEqual(len(events), 2 * len(passes))

    def test_live_deadline_kills_private_group(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            code, report = self.run_child(work, 'stuck')
            self.assertEqual(code, 2)
            self.assertEqual(report['status'], 'performance-blocked')
            self.assertEqual(report['returncode'], -signal.SIGKILL)
            trigger = json.loads((work / 'guard-trigger.json').read_text())
            self.assertEqual(trigger['kind'], 'running-pass-at-budget')
            self.assertEqual(trigger['logical_instance'], PASSES[0])
            self.assertEqual(trigger['last_complete_boundary'], 'complete-before-' + PASSES[0])
            self.assertGreaterEqual(trigger['elapsed_s'], 0.2)
            self.assertLess(trigger['elapsed_s'], 0.5)
            helper = int((work / 'grh.log').read_text().strip())
            try:
                stat = Path(f'/proc/{helper}/stat').read_text()
            except FileNotFoundError:
                return  # The killed helper has already been reaped.
            self.assertEqual(stat.rsplit(')', 1)[1].split()[0], 'Z')

    def test_malformed_events_stop_the_run(self):
        with tempfile.TemporaryDirectory() as directory:
            code, report = self.run_child(Path(directory), 'invalid')
            self.assertEqual(code, 2)
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['trigger']['kind'], 'invalid-pass-events')

    def test_disk_floor_stops_capture_and_preserves_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            command = [sys.executable, '-c', 'import time; time.sleep(30)']
            code = run_guarded(command, work, run_id='disk-test',
                               budgets=dict.fromkeys(PASSES, 100.0), min_free_bytes=1 << 60)
            self.assertEqual(code, 2)
            report = json.loads((work / 'guard.json').read_text())
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['returncode'], -signal.SIGKILL)
            trigger = json.loads((work / 'guard-trigger.json').read_text())
            self.assertEqual(trigger['kind'], 'capture-disk-space')
            self.assertLess(trigger['free_bytes'], trigger['min_free_bytes'])

    def test_native_events_match_pass_manager_timers(self):
        from importlib.util import find_spec

        spec = find_spec('wolvrix')
        if spec is None or spec.origin is None:
            self.skipTest('compiled Wolvrix Python package is not installed')
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            fixture = work / 'PassTrace.fir'
            fixture.write_text('FIRRTL version 6.0.0\ncircuit PassTrace :\n  module PassTrace :\n'
                               '    output out : UInt<1>\n    connect out, UInt<1>(0)\n')
            timing = work / 'native-timing.jsonl'
            command = [sys.executable, '-c', NATIVE_CHILD, str(fixture), str(timing)]
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent))
            code = run_guarded(command, work, run_id='native', budgets=dict.fromkeys(PASSES, 100.0), env=env)
            report = json.loads((work / 'guard.json').read_text())
            self.assertEqual(code, 0, (work / 'grh.log').read_text())
            self.assertEqual(report['status'], 'completed')
            self.assertEqual(report['returncode'], 0, (work / 'grh.log').read_text())
            events = [json.loads(line) for line in (work / 'stage-events.jsonl').read_text().splitlines()]
            native = [json.loads(line) for line in timing.read_text().splitlines()]
            self.assertEqual([row['event'] for row in events], ['start', 'end'] * len(PASSES))
            self.assertEqual([row['logical_instance'] for row in events[1::2]], list(PASSES))
            self.assertEqual([row['stage'] for row in native], [logical.split('#')[0] for logical in PASSES])
            self.assertEqual([row['wall_s'] for row in events[1::2]], [row['wall_s'] for row in native])

    def test_guarded_capture_replays_all_passes(self):
        from importlib.util import find_spec

        from capture_f35_pipeline import validate_stages
        from types import SimpleNamespace

        spec = find_spec('wolvrix')
        if spec is None or spec.origin is None:
            self.skipTest('compiled Wolvrix Python package is not installed')
        scripts = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            source = work / 'PassTrace.fir'
            source.write_text('FIRRTL version 6.0.0\ncircuit PassTrace :\n'
                              '  module PassTrace :\n    input a : UInt<1>\n'
                              '    output out : UInt<1>\n    node n = not(a)\n    connect out, n\n')
            manifest = work / 'manifest.json'
            manifest.write_text(json.dumps({'schema': 'wolvrix.xs.firrtl-inputs.v1',
                                            'sources': [{'path': str(source), 'language': 'firrtl'}],
                                            'tops': ['PassTrace'],
                                            'firrtl_options': {'node_annotations': True}}))
            # Main requires scratch paths below F35. Make sets TMPDIR there.
            command = [sys.executable, str(scripts / 'capture_f35_pipeline.py'), 'grh',
                       '--firrtl', str(source), '--manifest', str(manifest), '--output', str(work),
                       '--child-run-id', 'fixture-capture']
            code = run_guarded(command, work, run_id='fixture-capture', budgets=dict.fromkeys(PASSES, 100.0))
            self.assertEqual(code, 0, (work / 'grh.log').read_text())
            report = json.loads((work / 'capture.json').read_text())
            self.assertEqual([stage['pass'] for stage in report['passes']], list(PASSES))
            self.assertEqual(report['ingest_origins'][0]['node_count'], 3)
            self.assertTrue((work / 'R4/node-endpoints.tsv').is_file())
            validate_stages(SimpleNamespace(verify_replay=True, output=work), report['passes'])


if __name__ == '__main__':
    unittest.main()
