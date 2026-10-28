import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest

from repcut_grhsim_auto_flow import performance_pass, reference_memories, select_migration, save


class AutomaticChoiceTest(unittest.TestCase):
    def test_historical_memory_control_requires_successful_unique_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / 'run.json'
            names = ['hier$a$Memory', 'hier$b$Memory']
            save(record, dict(status='pass', target_memories=names))
            self.assertEqual(reference_memories(record), names)
            for status, targets in [('error', names), ('pass', []),
                                    ('pass', names + names), ('pass', ['a\nb'])]:
                save(record, dict(status=status, target_memories=targets))
                with self.assertRaises(ValueError):
                    reference_memories(record)

    def test_concurrent_stage_checkpoints_remain_complete_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.json'

            def update(index):
                save(path, dict(stage=index, payload=[index] * 500))
                current = json.loads(path.read_text())
                self.assertEqual(current['payload'], [current['stage']] * 500)

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(update, range(100)))
            self.assertEqual(list(Path(directory).glob('*.new')), [])

    def test_acceptance_uses_walltime_and_repeatable_wins(self):
        summary = {'metrics': {'elapsed_s': {'paired_delta_median_pct': -0.7,
                                             'candidate_wins': 7},
                               'host_s': {'paired_delta_median_pct': 0.2}}}
        self.assertTrue(performance_pass(summary))
        summary['metrics']['elapsed_s']['candidate_wins'] = 4
        self.assertFalse(performance_pass(summary))
        summary['metrics']['elapsed_s'].update(candidate_wins=8, paired_delta_median_pct=0.2)
        self.assertFalse(performance_pass(summary))

    def test_source_and_destination_labels_do_not_override_cost(self):
        def row(name, source, target, cost):
            return dict(name=name, source=source, destination=target,
                        predicted_mean_step_max_eval_us=cost,
                        candidate_non_endpoint_impact_count=2,
                        candidate_send_bytes_max_part_increase=128,
                        candidate_receive_bytes_max_part_increase=128)
        ranking = {'improving_frontier': [row('a', 1, 2, 30), row('b', 9, 5, 28)]}
        self.assertEqual(select_migration(ranking)['name'], 'b')
        renamed = copy.deepcopy(ranking)
        for candidate in renamed['improving_frontier']:
            candidate['source'] = 31 - candidate['source']
            candidate['destination'] = 31 - candidate['destination']
        self.assertEqual(select_migration(renamed)['name'], 'b')

    def test_no_improving_frontier_does_not_force_a_move(self):
        self.assertIsNone(select_migration({'improving_frontier': []}))


if __name__ == '__main__':
    unittest.main()
