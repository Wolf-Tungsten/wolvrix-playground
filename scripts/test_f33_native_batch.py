"""Installed F33 native batch API contracts using independent real designs."""
from __future__ import annotations

from contextlib import ExitStack
import json
import math
from pathlib import Path
import tempfile
import unittest

import wolvrix
from capture_f34_pipeline import production_calls
from f33_guard import F34
from grhsim_flow import checked
from wolvrix_xs_grhsim import firrtl_canonical_pipeline


ROOT = Path(__file__).resolve().parents[1]
PREFIX = ('xmr-resolve', 'hier-flatten', 'comb-loop-elim', 'split-static-array',
          'dead-code-elim', 'expr-opt', 'used-bits', 'split-nodes', 'dead-code-elim')
SOURCE = '''FIRRTL version 6.0.0
circuit top :
  module top :
    input a : UInt<8>
    input choose : UInt<1>
    output y : UInt<8>
    node masked = and(a, UInt<8>(0))
    node selected = mux(choose, masked, UInt<8>(0))
    connect y, selected
'''


class NativeBatchTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'ptmp').mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='f33-native-batch-', dir=ROOT / 'ptmp')
        self.work = Path(self.temporary.name)
        self.source = self.work / 'input.fir'
        self.source.write_text(SOURCE)
        self.stack = ExitStack()

    def tearDown(self):
        self.stack.close()
        self.temporary.cleanup()

    def session(self, *, prefix=True):
        member = self.stack.enter_context(wolvrix.Session())
        member.log_level = 'off'
        member.diagnostics_print_min_level = 'none'
        member.diagnostics_raise_min_level = 'none'
        member.read_sources(sources=[{'path': str(self.source), 'language': 'firrtl', 'unit': 'f33-native-api'}],
                            tops=['top'], firrtl_options={'node_annotations': True, 'init_policy': 'zero',
                                                         'invalid_policy': 'zero'},
                            out_design='design.main', pipeline='ingest')
        if prefix:
            for name in PREFIX:
                kwargs = {'semantics': '2state'} if name in {'expr-opt', 'used-bits'} else {}
                member.run_pass(name, design='design.main', keep_declared_symbols=False, **kwargs)
        self.assertTrue(member.semantic_validate(design='design.main')['valid'])
        return member

    def paths(self, stem='pass'):
        return self.work / (stem + '-timing.jsonl'), self.work / (stem + '-events.jsonl')

    def invoke(self, members, name='constant-analysis', logical='constant-analysis#0', **kwargs):
        timing, events = self.paths(kwargs.pop('stem', 'pass'))
        result = wolvrix._run_pass_batch(members, name, design=kwargs.pop('design', 'design.main'),
                                         timing_output=str(timing), stage_events=str(events),
                                         run_id='native-api-fixture', logical_instance=logical, **kwargs)
        return result, timing, events

    def assert_success_evidence(self, members, name, logical, result, timing, events):
        self.assertTrue(result[-1]['success'], result)
        self.assertEqual(result[-1]['action'], 'run_pass_batch')
        self.assertEqual(result[-1]['batch_count'], len(members))
        rows = [json.loads(line) for line in timing.read_text().splitlines()]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row['schema'], row['stage'], row['pass_instance'], row['scope'], row['clock']),
                         ('grh-stage-timing.v1', name, name + '#0', 'pass', 'steady_clock'))
        self.assertTrue(row['complete'])
        self.assertEqual(row['batch_count'], len(members))
        self.assertEqual(len(row['native_member_times_s']), len(members))
        self.assertTrue(all(math.isfinite(seconds) and seconds >= 0 for seconds in row['native_member_times_s']))
        self.assertGreater(row['wall_s'], 0)
        self.assertAlmostEqual(row['native_sum_s'], sum(row['native_member_times_s']), places=12)
        self.assertLessEqual(row['native_sum_s'], row['wall_s'] + 1e-9)
        observed = [json.loads(line) for line in events.read_text().splitlines()]
        self.assertEqual([event['event'] for event in observed], ['start', 'end'])
        for event in observed:
            self.assertEqual((event['engine'], event['run_id'], event['logical_instance'], event['batch_count']),
                             ('grh', 'native-api-fixture', logical, len(members)))
            boundary = F34.boundaries.get(logical, 'Q0' if name == 'constant-analysis' else 'Q1')
            self.assertEqual(event['input_boundary'], boundary)
            self.assertTrue(math.isfinite(event['monotonic_s']))
        self.assertAlmostEqual(observed[-1]['wall_s'], row['wall_s'], places=12)
        self.assertGreaterEqual(observed[-1]['monotonic_s'] - observed[0]['monotonic_s'] + 1e-8, row['wall_s'])
        for member in members:
            self.assertTrue(member.semantic_validate(design='design.main')['valid'])

    def test_single_and_multiple_fresh_graph_native_timers_and_history(self):
        for count in (1, 3):
            with self.subTest(batch_count=count):
                members = [self.session() for _ in range(count)]
                self.assertEqual(len({id(member._capsule) for member in members}), count)
                histories = [member.history() for member in members]
                result, timing, events = self.invoke(members, top='top', semantics='2state', stem=f'ca-{count}')
                self.assert_success_evidence(members, 'constant-analysis', 'constant-analysis#0', result, timing, events)
                self.assertEqual([member.history() for member in members], histories)
                result, timing, events = self.invoke(members, 'dead-code-elim', 'dead-code-elim#2', stem=f'dce-{count}')
                self.assert_success_evidence(members, 'dead-code-elim', 'dead-code-elim#2', result, timing, events)
                self.assertEqual([member.history() for member in members], histories)

    def test_f34_two_fresh_members_stop_after_fourth_dce(self):
        members = [self.session(prefix=False) for _ in range(2)]
        prefix, window = production_calls(firrtl_canonical_pipeline())
        for member in members:
            for name, _, keep, options in prefix:
                result = member.run_pass(name, design='design.main', keep_declared_symbols=keep, **options)
                checked(result, name)
        for name, logical, keep, options in window:
            result, timing, events = self.invoke(members, name, logical, stem=logical,
                                                  keep_declared_symbols=keep, **options)
            self.assert_success_evidence(members, logical.split('#')[0], logical, result, timing, events)
        for index, member in enumerate(members):
            before = self.work / f'r4-{index}-before.json'
            after = self.work / f'r4-{index}-after.json'
            checked(member.store_json(design='design.main', output=str(before)), 'save R4')
            diagnostic = member.run_pass('grhsim-dialect-translate', design='design.main', top='top',
                                         logic_domain='2state')
            with self.assertRaisesRegex(RuntimeError, 'fourth dead-code-elim'):
                checked(diagnostic, 'successor support gate')
            checked(member.store_json(design='design.main', output=str(after)), 'save after rejected successor')
            self.assertEqual(before.read_bytes(), after.read_bytes())

    def test_python_duplicate_session_and_capsule_reject_before_start(self):
        member = self.session()
        timing, events = self.paths()
        with self.assertRaisesRegex(ValueError, 'distinct'):
            self.invoke([member, member])
        self.assertFalse(events.exists())
        self.assertFalse(timing.exists())
        other = self.stack.enter_context(wolvrix.Session())
        capsule = other._capsule
        try:
            other._capsule = member._capsule
            with self.assertRaisesRegex(ValueError, 'native sessions.*distinct'):
                self.invoke([member, other])
        finally:
            other._capsule = capsule
        self.assertFalse(events.exists())

    def test_python_invalid_configuration_rejects_before_start(self):
        member = self.session()
        timing, events = self.paths()
        for kwargs, error in (({'semantics': 'not-a-mode'}, ValueError),
                              ({'dryrun': True}, TypeError),
                              ({'unknown': True}, TypeError),
                              ({'logical': 'dead-code-elim#2'}, ValueError)):
            with self.subTest(kwargs=kwargs), self.assertRaises(error):
                self.invoke([member], **kwargs)
            self.assertFalse(events.exists())
        with self.assertRaisesRegex(ValueError, '1..256'):
            self.invoke([])
        self.assertFalse(timing.exists())

    def test_assertion_option_compiles_only_when_enabled(self):
        self.assertEqual(wolvrix._compile_run_pass('dead-code-elim', [], {})[1], [])
        self.assertEqual(wolvrix._compile_run_pass(
            'dead-code-elim', [], {'drop_disabled_firrtl_assertions': True})[1],
            ['-drop-disabled-firrtl-assertions'])
        with self.assertRaisesRegex(TypeError, 'must be bool'):
            wolvrix._compile_run_pass('dead-code-elim', [], {'drop_disabled_firrtl_assertions': 1})

    def native(self, capsules, **kwargs):
        timing, events = self.paths()
        values = dict(name='constant-analysis', design='design.main', args=['-semantics=2state'],
                      keep_declared_symbols=False, log_level='off', timing_output=str(timing),
                      stage_events=str(events), run_id='native-api-fixture', logical_instance='constant-analysis#0')
        values.update(kwargs)
        return wolvrix._native.session_run_pass_batch(capsules, **values)

    def test_direct_native_duplicate_and_invalid_options_reject_before_start(self):
        member = self.session()
        timing, events = self.paths()
        for kwargs in ({'capsules': [member._capsule, member._capsule]},
                       {'args': ['-not-a-constant-analysis-option']},
                       {'log_level': 'not-a-level'},
                       {'logical_instance': 'dead-code-elim#2'},
                       {'name': 'alias-analysis'}):
            values = dict(kwargs)
            capsules = values.pop('capsules', [member._capsule])
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.native(capsules, **values)
            self.assertFalse(events.exists())
            self.assertFalse(timing.exists())

    def test_missing_design_is_rejected_for_all_members_before_start(self):
        loaded = self.session()
        empty = self.stack.enter_context(wolvrix.Session())
        empty.log_level = loaded.log_level
        timing, events = self.paths()
        with self.assertRaises(KeyError):
            self.invoke([loaded, empty])
        self.assertFalse(events.exists())
        self.assertFalse(timing.exists())
        with self.assertRaises(KeyError):
            self.native([loaded._capsule], design='missing')
        self.assertFalse(events.exists())

    def test_pass_failure_has_start_but_no_successful_end(self):
        member = self.session()
        result, timing, events = self.invoke([member], top='missing-top', semantics='2state')
        self.assertFalse(result[-1]['success'])
        self.assertTrue(any(diagnostic.get('kind') == 'error' for diagnostic in result[:-1]))
        records = [json.loads(line) for line in events.read_text().splitlines()]
        self.assertEqual([record['event'] for record in records], ['start'])
        row = json.loads(timing.read_text())
        self.assertFalse(row['complete'])
        self.assertEqual(row['batch_count'], 1)
        self.assertGreater(row['wall_s'], 0)


if __name__ == '__main__':
    unittest.main()
