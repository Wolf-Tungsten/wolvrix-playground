import unittest
import copy

from cv32e40p_consumer_structure_compare import BASELINE, CANDIDATES, summaries
from cv32e40p_consumer_structure_analysis import counter_invariants


class IndependentComparisonTests(unittest.TestCase):
    def test_each_rule_has_named_baseline_and_verilator_ratios(self):
        candidates=list(CANDIDATES)
        times={BASELINE:4.0,'verilator':2.0,candidates[0]:3.0,candidates[1]:5.0}
        rows=[{b:{m:t*(i+1) for m in ('wall_s','sim_s','init_s')} for b,t in times.items()} for i in range(4)]
        report=summaries(rows)
        self.assertEqual(set(report),set(candidates))
        self.assertEqual(report[candidates[0]][BASELINE]['wall_s']['ratio_mean'],0.75)
        self.assertEqual(report[candidates[1]][BASELINE]['wall_s']['ratio_mean'],1.25)
        self.assertEqual(report[candidates[0]]['verilator']['wall_s']['ratio_ci95'],[1.5,1.5])
        self.assertEqual(report[candidates[1]]['verilator']['wall_s']['ratio_mean'],2.5)
        for candidate,comparisons in report.items():
            self.assertEqual(set(comparisons),{BASELINE,'verilator'})
            for baseline,result in comparisons.items():
                self.assertTrue(result['ratio_definition'].startswith(candidate+' / '+baseline))

    def test_changed_selector_counts_cannot_pass_interface_invariants(self):
        before=dict(cycles=10,trace={'sha256':'same'},counts={
            'cmp:1':[0,0,10,0],'chg:1':[0,0,2,0],
            'scalar_comparisons':[0,0,10,0],'scalar_changes':[0,0,2,0],
            'mux_true:4333':[0,0,0,0],'mux_false:4333':[0,0,10,0]})
        self.assertTrue(counter_invariants(before,copy.deepcopy(before))['all_equal'])
        extended=copy.deepcopy(before);extended['counts']['notify_reduction_deferred:1:0']=[0,0,10,0]
        self.assertEqual(len(counter_invariants(before,extended)['new_probe_counts']),1)
        missing=copy.deepcopy(before);del missing['counts']['mux_false:4333']
        with self.assertRaisesRegex(ValueError,'selector'):counter_invariants(before,missing)
        after=copy.deepcopy(before);after['counts']['mux_true:4333'][2]=1
        after['counts']['mux_false:4333'][2]-=1
        with self.assertRaisesRegex(ValueError,'selector'):counter_invariants(before,after)


if __name__=='__main__':unittest.main()
