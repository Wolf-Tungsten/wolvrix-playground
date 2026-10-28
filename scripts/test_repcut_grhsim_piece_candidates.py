#!/usr/bin/env python3
import csv
from pathlib import Path
import tempfile
import unittest

from repcut_grhsim_piece_candidates import profile_sources, propose


class CandidateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.model = self.root / 'model.txtdata'
        # Duplicate shared pieces, deliberately with opposite member ordering.
        self.model.write_text('repcut-assignment-model-v2\nfixture\n4 1 3 0 0\nwork\n'
                              '2 0 2 9\n2 2 0 9\n2 1 3 2\n')
        self.features = self.root / 'features.csv'
        with self.features.open('w', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['atom', 'feature', 'count'])
            writer.writerows([[0, 'compute.wide.helper_word_iterations', 100],
                              [1, 'compute.wide.helper_word_iterations', 5]])

    def test_non_32_partitions_and_duplicate_moves(self):
        result = propose(self.model, self.features, [0, 0, 1, 2], [0], 3, 8, 2)
        self.assertEqual(len(result), 4)
        self.assertEqual(len({(r['members'], r['destination']) for r in result}), 4)
        self.assertEqual(result[0]['destination'], 1)
        self.assertEqual(result[0]['destination_piece_members'], 1)
        self.assertEqual(result[2]['destination'], 2)

    def test_only_source_members_move_and_existing_labels_survive(self):
        labels = [0, 0, 1, 2]
        for r in propose(self.model, self.features, labels, [0], 3, 2, 2):
            moved = labels.copy()
            for atom in r['members']:
                self.assertEqual(labels[atom], 0)
                moved[atom] = r['destination']
            self.assertEqual(moved[2:], [1, 2])

    def test_assignment_shape_mismatch(self):
        with self.assertRaisesRegex(ValueError, 'size mismatch'):
            propose(self.model, self.features, [0] * 5, [0], 3, 2, 2)

    def test_invalid_labels(self):
        with self.assertRaisesRegex(ValueError, 'invalid partition labels'):
            propose(self.model, self.features, [0, 0, 1, 3], [0], 3, 2, 2)

    def test_bound_is_enforced(self):
        result = propose(self.model, self.features, [0, 0, 1, 2], [0], 3, 1, 1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['shape_score'], 100)

    def test_profile_arm_selects_sources_for_non_32_partitions(self):
        path = self.root / 'parts.csv'
        with path.open('w', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['record_type', 'variant', 'part_name', 'eval_avg_us', 'update_push_avg_us'])
            for variant, times in [('baseline', [9, 2, 1]), ('candidate', [1, 8, 8])]:
                for part, value in enumerate(times):
                    writer.writerow(['part_timing', variant, f'part_{part}', value, 1])
        self.assertEqual(profile_sources(path, 'baseline', 3, 1)[0], [0])
        self.assertEqual(profile_sources(path, 'candidate', 3, 2)[0], [1, 2])
        self.assertEqual(profile_sources(path, 'candidate', 3, None)[0], [1, 2, 0])
        with self.assertRaisesRegex(ValueError, 'partition set'):
            profile_sources(path, 'candidate', 4, 1)
        with self.assertRaisesRegex(ValueError, 'must be positive'):
            profile_sources(path, 'candidate', 3, 0)


if __name__ == '__main__':
    unittest.main()
