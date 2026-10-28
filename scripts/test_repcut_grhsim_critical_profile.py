#!/usr/bin/env python3
from array import array
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from repcut_grhsim_critical_profile import project_eval, summarize
from repcut_grhsim_local_search_rank import rank
from repcut_grhsim_piece_candidates import critical_sources


class CriticalProfileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'trace.bin'

    def trace(self, flags, evals):
        parts, steps = len(evals), len(flags)
        values = array('I', [value for flag in flags for value in (flag, 1, 20_000, 2_000)])
        values.extend(value for lane in evals for us in lane for value in (1, us * 1000, 1000))
        if sys.byteorder != 'little':
            values.byteswap()
        self.path.write_bytes(b'GRHCYC01' + struct.pack('<4I', 1, steps, parts, 3) + values.tobytes())

    def test_largest_mean_is_not_largest_critical_opportunity(self):
        # Lane 0 is always busy. Lanes 1/2 alternate larger peaks.
        self.trace([0, 1, 0, 1, 2], [[8, 8, 8, 8, 100], [12, 0, 12, 0, 0], [0, 12, 0, 12, 0]])
        result = summarize([self.path])
        ev = result['all']['eval']
        self.assertEqual(result['all']['steps'], 4)
        self.assertEqual(ev['max_partition_mean_us'], 8)
        self.assertEqual(ev['mean_step_max_us'], 12)
        self.assertEqual([r['bottleneck_mean_us'] for r in ev['parts']], [None, 12, 12])
        self.assertEqual(result['clock_levels']['0']['eval']['parts'][1]['bottleneck_mean_us'], 12)
        self.assertEqual([r['exclusive_margin_us'] for r in ev['parts']], [0, 2, 2])
        profile = self.path.with_suffix('.json')
        profile.write_text(json.dumps(result))
        self.assertEqual(critical_sources(profile, 3, 2)[0], [1, 2])
        estimates = project_eval([self.path], {'reduce_busy': {0: 0.5},
                                              'reduce_peak': {1: 0.5},
                                              'overload_destination': {1: 0.5, 0: 2}}, 3)
        self.assertEqual(estimates['baseline_mean_step_max_us'], 12)
        self.assertEqual(estimates['candidates']['reduce_busy']['mean_step_max_us'], 12)
        self.assertEqual(estimates['candidates']['reduce_peak']['mean_step_max_us'], 10)
        self.assertEqual(estimates['candidates']['overload_destination']['mean_step_max_us'], 16)

    def test_ties_have_no_exclusive_savings_and_bad_data_is_rejected(self):
        self.trace([0], [[8], [8]])
        result = summarize([self.path])
        self.assertEqual([r['exclusive_margin_us'] for r in result['all']['eval']['parts']], [0, 0])
        self.path.write_bytes(self.path.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, 'truncated'):
            summarize([self.path])

    def test_fresh_flow_needs_no_input_hash_or_identity_checks(self):
        self.trace([0, 1], [[12, 0], [0, 14], [1, 1]])
        with patch('repcut_grhsim_critical_profile.identity', side_effect=AssertionError('unexpected hash')):
            result = summarize([self.path], check_inputs=False)
        profile = self.path.with_suffix('.json')
        profile.write_text(json.dumps(result))
        with patch('repcut_grhsim_piece_candidates.check_identity', side_effect=AssertionError('unexpected check')):
            sources, _ = critical_sources(profile, 3, 2, check_inputs=False)
        self.assertEqual(sources, [1, 0])
        self.assertEqual(result['inputs'], [{'path': str(self.path.resolve())}])

    def test_transferred_work_keeps_donor_activity_and_destination_pressure(self):
        # The receiver is idle when the donor is busy. Multiplying only the
        # receiver's existing time makes the moved work almost disappear.
        self.trace([0, 1, 2], [[20, 0, 999], [5, 15, 999], [10, 10, 999]])
        scales = {'move': {0: 0.25, 1: 1.375}}
        old = project_eval([self.path], scales, 3)
        new = project_eval([self.path], scales, 3, {'move': {1: {0: 0.75}}})
        self.assertEqual(old['baseline_mean_step_max_us'], 17.5)
        self.assertEqual(old['candidates']['move']['mean_step_max_us'], 15.3125)
        self.assertEqual(new['candidates']['move']['mean_step_max_us'], 20.3125)
        self.assertEqual(new['candidates']['move']['clock_levels'], {'0': 20, '1': 20.625})
        self.assertEqual(new['baseline_clock_levels'], {'0': 20, '1': 15})

    def test_bad_activity_additions_are_rejected(self):
        self.trace([0], [[10], [1]])
        scales = {'move': {0: 0.5, 1: 1}}
        for additions in ({'absent': {1: {0: 1}}}, {'move': {2: {0: 1}}},
                          {'move': {1: {2: 1}}}, {'move': {1: {0: float('nan')}}}):
            with self.subTest(additions=additions), self.assertRaises(ValueError):
                project_eval([self.path], scales, 2, additions)

    def test_rank_rejects_false_improvement_from_destination_only_activity(self):
        self.trace([0, 1], [[20, 0], [5, 15], [10, 10]])
        work = {'source': {'baseline': 100, 'candidate': 25},
                'destination': {'baseline': 200, 'candidate': 275},
                'peak': {'baseline': 200, 'candidate': 275},
                'total': {'baseline': 400, 'candidate': 400}}
        move = {'name': 'move', 'source': 0, 'destination': 1,
                'moved_atoms': 1, 'shape_score': 1,
                **{key: work for key in ('grhsim_v1_recurring_work', 'raw_operation_count',
                                        'send_calls', 'send_bytes', 'receive_calls', 'receive_bytes', 'piece_copies')}}
        timings = {p: {'eval': 10, 'update': 1} for p in range(3)}
        old = rank({'candidates': [move]}, timings, critical_traces=[self.path])
        new = rank({'candidates': [move]}, timings, critical_traces=[self.path],
                   activity_model='source-envelope')
        self.assertEqual(old['improving_frontier_count'], 1)
        self.assertEqual(new['improving_frontier_count'], 0)
        row = new['frontier'][0]
        self.assertEqual(row['added_source_activity_factors'], {'1': 0.75})
        self.assertEqual(row['predicted_clock_level_delta_us'], {'0': 0, '1': 5.625})
        with self.assertRaisesRegex(ValueError, 'requires per-step'):
            rank({'candidates': [move]}, timings, activity_model='source-envelope')

    def test_new_work_on_empty_destination_is_not_silently_zero(self):
        self.trace([0], [[20], [0], [2]])
        work = {'source': {'baseline': 100, 'candidate': 50},
                'destination': {'baseline': 0, 'candidate': 50},
                'peak': {'baseline': 100, 'candidate': 50},
                'total': {'baseline': 100, 'candidate': 100}}
        move = {'name': 'move', 'source': 0, 'destination': 1,
                'moved_atoms': 1, 'shape_score': 1,
                **{key: work for key in ('grhsim_v1_recurring_work', 'raw_operation_count',
                                        'send_calls', 'send_bytes', 'receive_calls', 'receive_bytes', 'piece_copies')}}
        timings = {p: {'eval': x, 'update': 1} for p, x in enumerate((20, 0, 2))}
        with self.assertRaisesRegex(ValueError, 'zero baseline'):
            rank({'candidates': [move]}, timings, critical_traces=[self.path])
        new = rank({'candidates': [move]}, timings, critical_traces=[self.path],
                   activity_model='source-envelope')
        self.assertEqual(new['frontier'][0]['predicted_mean_step_max_eval_us'], 10)

    def test_rank_uses_step_maximum_instead_of_maximum_average(self):
        self.trace([0, 1], [[8, 8], [12, 0], [0, 12]])
        work = {'source': {'baseline': 10, 'candidate': 5},
                'destination': {'baseline': 10, 'candidate': 10},
                'peak': {'baseline': 10, 'candidate': 10},
                'total': {'baseline': 30, 'candidate': 25}}
        move = {'name': 'reduce_average_bottleneck', 'source': 0, 'destination': 1,
                'moved_atoms': 1, 'shape_score': 1,
                **{key: work for key in ('grhsim_v1_recurring_work', 'raw_operation_count',
                                        'send_calls', 'send_bytes', 'receive_calls', 'receive_bytes', 'piece_copies')}}
        times = {p: {'eval': value, 'update': 1} for p, value in enumerate((8, 6, 6))}
        old = rank({'candidates': [move]}, times)
        new = rank({'candidates': [move]}, times, critical_traces=[self.path])
        self.assertEqual(old['improving_frontier_count'], 1)
        self.assertEqual(new['improving_frontier_count'], 0)
        self.assertEqual(new['critical_path_statistic'], 'mean_of_per_step_maxima')
        self.assertEqual(new['frontier'][0]['predicted_mean_step_max_eval_us'], 12)


if __name__ == '__main__':
    unittest.main()
