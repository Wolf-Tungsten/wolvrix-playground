import unittest

from cv32e40p_conditional_mux_analysis import branch_work


class BranchWorkTests(unittest.TestCase):
    def test_one_sided_and_both_sided_costs(self):
        counts = {'mux_root:7': [0, 0, 100, 0], 'mux_true:7': [0, 0, 30, 0],
                  'mux_false:7': [0, 0, 70, 0]}
        work = branch_work(dict(root=7, true_ops=0, false_ops=20), counts, 100)
        self.assertEqual(work['selected_ir_per_cycle'], 14)
        self.assertEqual(work['skipped_ir_per_cycle'], 6)
        work = branch_work(dict(root=7, true_ops=10, false_ops=20), counts, 100)
        self.assertEqual(work['eager_ir_per_cycle'], 30)
        self.assertEqual(work['selected_ir_per_cycle'], 17)
        self.assertEqual(work['skipped_ir_per_cycle'], 13)
        counts['mux_false:7'][-1] = 1
        with self.assertRaisesRegex(ValueError, 'partition'):
            branch_work(dict(root=7, true_ops=10, false_ops=20), counts, 100)


if __name__ == '__main__':
    unittest.main()
