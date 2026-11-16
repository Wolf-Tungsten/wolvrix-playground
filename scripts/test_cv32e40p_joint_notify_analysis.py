import copy
import unittest
from cv32e40p_joint_notify_analysis import compare_reductions

class JointNotifyTests(unittest.TestCase):
    def fixture(self):
        old=dict(cycles=10,trace=dict(sha256='same'),counts={
            'scalar_comparisons':[0,10,0,0],'scalar_changes':[0,2,0,0],
            'cmp:1':[0,10,0,0],'chg:1':[0,2,0,0],
            'mux_cache_misses:2':[0,2,0,0],'mux_invalidate_visits:0':[0,10,0,0],
            'mux_invalidations:0':[0,2,0,0],
            'notify_reduction_deferred:3:0':[0,50,0,0],
            'mux_notify_accumulate_visits:3:0':[0,40,0,0]})
        new=copy.deepcopy(old)
        new['counts'].update({'notify_reduction_deferred:3:0':[0,20,0,0],
            'mux_notify_accumulate_visits:3:0':[0,10,0,0],
            'notify_reduction_joint:3:0':[0,50,0,0]})
        return old,new
    def test_counts_reconstruction_not_only_source_reductions(self):
        r=compare_reductions(*self.fixture())
        self.assertEqual(r['before']['total_local_reductions'],9)
        self.assertEqual(r['after']['total_local_reductions'],8)
    def test_rejects_lost_dirty_notification(self):
        a,b=self.fixture();b['counts']['mux_invalidations:0']=[0,1,0,0]
        with self.assertRaisesRegex(ValueError,'invalidation'):compare_reductions(a,b)
    def test_rejects_spurious_miss(self):
        a,b=self.fixture();b['counts']['mux_cache_misses:2']=[0,3,0,0]
        with self.assertRaisesRegex(ValueError,'invalidation'):compare_reductions(a,b)

if __name__=='__main__':unittest.main()
