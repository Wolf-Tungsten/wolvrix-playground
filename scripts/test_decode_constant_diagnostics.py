from pathlib import Path
import tempfile
import unittest
from decode_constant_instrument import instrument
from decode_constant_measure import parse_perf
from decode_constant_graph_diff import digest

class Diagnostics(unittest.TestCase):
    def test_perf_scope_and_multiplexing(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'perf.csv'
            p.write_text('12,,cycles:u,1000,99.90,,\n<not supported>,,branches:u,0,0,,\n')
            self.assertEqual(parse_perf(p),[dict(event='cycles:u',value=12,running_ns=1000,running_percent=99.9,elapsed_s=None)])
            p.write_text('1.000,52,,msr/aperf/,1000000,100.00,,\n')
            self.assertEqual(parse_perf(p,True)[0]['elapsed_s'],1)

    def test_no_raw_id_alignment(self):
        x=dict(sym='_op_99',kind='kAdd',out=['cpu$sum'],**{'in':['cpu$a','cpu$b']})
        self.assertEqual(digest(x),digest(dict(x,sym='_op_7',loc={'file':'x.sv'})))
        self.assertNotEqual(digest(x),digest(dict(x,**{'in':['cpu$a','cpu$c']})))

    def test_body_and_change_instrumentation(self):
        source='''void GrhSIM_SimTop::eval_compute_batch_3()
{
    // Supernode 7: run when its activity flag is set.
    if (unlikely(activeWordFlags & UINT8_C(1))) {
        const bool grhsim_changed_99 = (a != next_value);
        supernode_active_curr_[0] |= UINT8_C(1);
        if (grhsim_assign_words_full<2>(a, next_words)) {
            producer_dirty_words_[0] |= UINT64_C(1);
        }
    }
}
'''
        out,counts=instrument(source)
        self.assertEqual(counts['supernode_guards'],1)
        self.assertLess(out.index('if (unlikely'),out.index('decode_counts::fire(7)'))
        self.assertEqual(out.count('grhsim_assign_words_full<2>'),1)
        self.assertEqual(out.count('a != next_value'),1)
        self.assertIn('decode_counts::activate(supernode_active_curr_[0], UINT8_C(1));',out)
        self.assertEqual(counts['conditional_changes'],1)

if __name__=='__main__':unittest.main()
