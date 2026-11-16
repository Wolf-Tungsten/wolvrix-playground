import copy
import unittest

from cv32e40p_covered_state_views_compare import BASELINE, NOTIFY, INLINE, summaries
from cv32e40p_covered_state_views_analysis import compare_counts


class CoveredStateViewsTests(unittest.TestCase):
    def test_stage_and_baseline_ratio_directions(self):
        times={BASELINE:4.0,NOTIFY:3.0,INLINE:2.0,'verilator':1.0}
        rows=[{b:{k:t*i for k in ('wall_s','sim_s','init_s')} for b,t in times.items()} for i in (1,2,3)]
        s=summaries(rows)
        self.assertEqual(s[NOTIFY][BASELINE]['wall_s']['ratio_mean'],0.75)
        self.assertAlmostEqual(s[INLINE][NOTIFY]['wall_s']['ratio_mean'],2/3)
        self.assertEqual(s[INLINE]['verilator']['wall_s']['ratio_ci95'],[2,2])

    def data(self):
        old=dict(cycles=10,trace={'sha256':'same'},counts={
            'cmp:1':[0,0,10,0],'chg:1':[0,0,2,0],'cmp:2':[0,0,8,0],'chg:2':[0,0,1,0],
            'scalar_comparisons':[0,0,18,0],'scalar_changes':[0,0,3,0],
            'group:1':[0,0,10,0],'round':[10,10,10,0],'function:eval':[10,10,0,0],
            'mux_cache_misses:3':[0,0,3,0]})
        new=copy.deepcopy(old)
        for key in ('cmp:1','chg:1'):del new['counts'][key]
        new['counts']['scalar_comparisons']=[0,0,8,0];new['counts']['scalar_changes']=[0,0,1,0]
        return old,new

    def test_only_selected_checks_and_notifications_may_disappear(self):
        old,new=self.data();result=compare_counts(old,new,{1})
        self.assertEqual(result['removed_checks'],1.0);self.assertTrue(result['all_equal'])
        new['counts']['group:1'][2]+=1
        with self.assertRaisesRegex(ValueError,'execution'):compare_counts(old,new,{1})

    def test_missing_live_value_or_changed_cache_is_rejected(self):
        for key in ('cmp:2','chg:2','mux_cache_misses:3','function:eval'):
            old,new=self.data();del new['counts'][key]
            with self.assertRaises(ValueError):compare_counts(old,new,{1})

    def test_savings_must_close_per_phase(self):
        old,new=self.data();new['counts']['cmp:2']=[0,1,7,0];new['counts']['scalar_comparisons']=[0,1,7,0]
        with self.assertRaises(ValueError):compare_counts(old,new,{1})


if __name__=='__main__':unittest.main()
