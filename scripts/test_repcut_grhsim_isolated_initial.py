import tempfile
from fractions import Fraction
from pathlib import Path
import unittest

from repcut_grhsim_isolated_initial import read_weights, reduce_graph, restore_labels, select_oversized


class IsolationTests(unittest.TestCase):
    def test_normalized_capacity_not_largest_inventory(self):
        weights = [(2, 2), (2, 2), (20, 2), (2, 12), (2, 12), (2, 12)]
        self.assertEqual(select_oversized(weights, 3, Fraction(5, 100)), [2])

    def test_balanced_graph_needs_no_fixed_node(self):
        self.assertEqual(select_oversized([(1, 1)] * 8, 4, Fraction(5, 100)), [])

    def test_reindex_edges_and_restore_original_asc_order(self):
        with tempfile.TemporaryDirectory() as temp:
            source, output = Path(temp) / 'source.hgr', Path(temp) / 'reduced.hgr'
            source.write_text('3 5 11 2\n3 1 3 5\n7 2 3\n9 1 2 4\n1 2\n3 4\n50 60\n5 6\n7 8\n')
            record = reduce_graph(source, output, [2])
            self.assertEqual(record['remaining_edges'], 2)
            self.assertEqual(read_weights(output)[1], [(1, 2), (3, 4), (5, 6), (7, 8)])
            self.assertEqual(output.read_text().splitlines()[1:3], ['3 1 4', '9 1 2 3'])
            self.assertEqual(restore_labels([0, 1, 1, 0], 5, [2], 3), [1, 2, 0, 2, 1])

    def test_incomplete_solver_assignment_rejected(self):
        with self.assertRaises(ValueError):
            restore_labels([0, 0, 0, 0], 5, [2], 3)

    def test_invalid_pin_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source, output = Path(temp) / 'source.hgr', Path(temp) / 'reduced.hgr'
            source.write_text('1 2 11 1\n1 1 3\n1\n2\n')
            with self.assertRaises(ValueError):
                reduce_graph(source, output, [])


if __name__ == '__main__':
    unittest.main()
