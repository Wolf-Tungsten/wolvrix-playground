import unittest

from repcut_memory_choose import choose


class MemorySelectionTests(unittest.TestCase):
    def fixture(self):
        audit = {'refinement_candidates': [
            {'candidate_id': 'a', 'cut_memories': ['ordinary']},
            {'candidate_id': 'b', 'cut_memories': ['another', 'third']}]}
        metrics = [dict(name='a', baseline_work=100, max_work=70, total_work=102),
                   dict(name='b', baseline_work=100, max_work=60, total_work=110)]
        return audit, metrics

    def test_replication_budget_excludes_better_peak(self):
        audit, metrics = self.fixture()
        self.assertEqual(choose(audit, metrics, 0.05)['selected_memories'], ['ordinary'])

    def test_renaming_memories_does_not_change_selected_cut(self):
        audit, metrics = self.fixture()
        before = choose(audit, metrics, 0.2)['selected']['name']
        audit['refinement_candidates'][0]['cut_memories'] = ['z']
        audit['refinement_candidates'][1]['cut_memories'] = ['a', 'b']
        self.assertEqual(choose(audit, metrics, 0.2)['selected']['name'], before)

    def test_no_improvement_keeps_input(self):
        audit, metrics = self.fixture()
        for row in metrics:
            row['max_work'] = row['baseline_work']
        self.assertEqual(choose(audit, metrics, 0.2)['selected_memories'], [])

    def test_missing_candidate_metrics_rejected(self):
        audit, metrics = self.fixture()
        with self.assertRaises(ValueError):
            choose(audit, metrics[:1], 0.05)


if __name__ == '__main__':
    unittest.main()
