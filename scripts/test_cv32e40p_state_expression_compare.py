import tempfile
import copy
from pathlib import Path
import unittest
from cv32e40p_state_expression_compare import BASELINE,NOTIFY,INLINE,composed,summaries
from cv32e40p_compute_entry_compare import compare_entry_counts


class StateExpressionReportTests(unittest.TestCase):
    def test_named_backend_directions(self):
        times={BASELINE:4,NOTIFY:3,INLINE:2,'verilator':1}
        rows=[{b:{m:t*n for m in ('wall_s','sim_s','init_s')} for b,t in times.items()} for n in (1,2,3)]
        s=summaries(rows)
        self.assertEqual(s[NOTIFY][BASELINE]['wall_s']['ratio_mean'],0.75)
        self.assertAlmostEqual(s[INLINE][NOTIFY]['wall_s']['ratio_mean'],2/3)
        self.assertEqual(s[INLINE]['verilator']['wall_s']['ratio_ci95'],[2,2])

    def test_storage_stage_is_not_inferred_from_global_switch(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'model_sched_0.cpp').write_text(
                '// Covered state view: value=4 source=2 producer=0 targets=1 mode=inline\n'
                '// Composed state expression: value=8 ops=6 mode=notify\n'
                '// Composed state expression: value=5 ops=2 mode=inline\n')
            r=composed(p)
            self.assertEqual([(x['value'],x['mode']) for x in r],[(5,'inline'),(8,'notify')])

    def entry_data(self):
        a=dict(cycles=10,trace={'sha256':'same'},counts={
            'scalar_comparisons':[0,0,10,0],'scalar_changes':[0,0,2,0],
            'cmp:1':[0,0,10,0],'chg:1':[0,0,2,0],'group:1':[0,0,10,0],
            'function:eval_compute_batch_0':[10,10,10,0],'function:eval_commit_batch_4':[10,10,10,0]})
        b=copy.deepcopy(a);b['counts']['function:eval_compute_batch_0']=[0,0,10,0]
        return a,b

    def test_entry_guard_only_changes_compute_function_calls(self):
        a,b=self.entry_data();r=compare_entry_counts(a,b)
        self.assertEqual(r['function_calls']['function:eval_compute_batch_0']['saved_per_cycle'],2)
        for key in ('group:1','function:eval_commit_batch_4','cmp:1'):
            altered=copy.deepcopy(b);altered['counts'][key][2]+=1
            with self.assertRaises(ValueError):compare_entry_counts(a,altered)

    def test_entry_guard_cannot_add_calls_in_another_phase(self):
        a,b=self.entry_data();b['counts']['function:eval_compute_batch_0']=[0,11,0,0]
        with self.assertRaisesRegex(ValueError,'calls increased'):compare_entry_counts(a,b)


if __name__=='__main__':unittest.main()
