import copy
import unittest

from cv32e40p_mux_input_cache_analysis import compare_work


class InputCacheAttributionTests(unittest.TestCase):
    def fixture(self):
        old = dict(cycles=10, trace=dict(sha256='same'), counts={
            'scalar_comparisons':[0,10,0,0], 'scalar_changes':[0,2,0,0],
            'cmp:7':[0,10,0,0], 'chg:7':[0,2,0,0], 'group:3':[0,10,0,0],
            'mux_root:9':[0,10,0,0], 'mux_true:9':[0,4,0,0], 'mux_false:9':[0,6,0,0]})
        new = copy.deepcopy(old)
        new['counts'].update({'scalar_comparisons':[0,2,0,0], 'cmp:7':[0,2,0,0],
            'mux_root:9':[0,2,0,0], 'mux_true:9':[0,1,0,0], 'mux_false:9':[0,1,0,0],
            'mux_cache_visits:9':[0,10,0,0], 'mux_cache_misses:9':[0,2,0,0]})
        return old, new, [dict(root=9, result=7, true_ops=16, false_ops=20)]

    def test_attributes_only_skipped_work_and_counts_new_guards(self):
        result = compare_work(*self.fixture())
        self.assertAlmostEqual(result['scalar_checks_saved_per_cycle'], .8)
        self.assertAlmostEqual(result['ir_operations_saved_per_cycle'], 15.6)
        self.assertEqual(result['cones'][0]['visits_per_cycle'], 1)
        self.assertEqual(result['cones'][0]['misses_per_cycle'], .2)

    def test_rejects_lost_notification(self):
        old, new, cones = self.fixture()
        new['counts']['chg:7'] = new['counts']['scalar_changes'] = [0,1,0,0]
        with self.assertRaisesRegex(ValueError, 'notification'): compare_work(old, new, cones)

    def test_rejects_unaccounted_visits(self):
        old, new, cones = self.fixture(); new['counts']['mux_cache_visits:9'] = [0,9,0,0]
        with self.assertRaisesRegex(ValueError, 'visits'): compare_work(old, new, cones)



if __name__ == '__main__':
    unittest.main()
