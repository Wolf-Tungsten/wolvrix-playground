import copy
import unittest
from cv32e40p_grouped_notify_analysis import compare_notifications

class GroupedNotifyTests(unittest.TestCase):
    def fixture(self):
        old=dict(cycles=10,trace=dict(sha256='same'),counts={
            'scalar_comparisons':[0,10,0,0],'scalar_changes':[0,2,0,0],
            'cmp:1':[0,10,0,0],'chg:1':[0,2,0,0],
            'mux_cache_misses:2':[0,2,0,0], 'mux_invalidate_visits:0':[0,20,0,0],
            'mux_invalidations:0':[0,4,0,0]})
        new=copy.deepcopy(old)
        new['counts'].update({'mux_invalidate_visits:0':[0,10,0,0],
            'mux_invalidations:0':[0,2,0,0],
            'mux_notify_accumulate_visits:3:0':[0,20,0,0],
            'mux_notify_accumulate_changes:3:0':[0,4,0,0]})
        return old,new
    def test_distinguishes_local_cost_from_persistent_writes(self):
        r=compare_notifications(*self.fixture())
        self.assertEqual(r['persistent_dirty_updates_per_cycle'],{'before':2,'after':1})
        self.assertEqual(r['local_accumulations_per_cycle'],2)
    def test_rejects_changed_cache_misses(self):
        old,new=self.fixture();new['counts']['mux_cache_misses:2']=[0,1,0,0]
        with self.assertRaisesRegex(ValueError,'consumer'):compare_notifications(old,new)

if __name__=='__main__':unittest.main()
