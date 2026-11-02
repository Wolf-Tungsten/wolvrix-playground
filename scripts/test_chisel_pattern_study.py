from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from chisel_pattern_bench import CASES, DISTRIBUTIONS, extract_compute
from chisel_pattern_catalog import catalog, STRUCTURAL_CASES
from chisel_pattern_findings import REVIEWS
from chisel_pattern_crc_control import summarize_control
from chisel_pattern_results import validate_samples, assembly_function
from chisel_pattern_study import scala_code


class StudyTests(unittest.TestCase):
    def test_scala_comments_and_nested_blocks_do_not_become_hardware_hits(self):
        text='// PopCount\nval x = "Reg(\\\"Mux\\\")"\n/* Wire /* IO */ Reg */\nval y = PopCount(x)\n'
        code=scala_code(text)
        self.assertEqual(code.count('PopCount'),1)
        self.assertNotIn('Reg',code)
        self.assertEqual(len(code),len(text));self.assertEqual(code.count('\n'),text.count('\n'))

    def test_triple_string_rtl_is_not_scala_hardware_evidence(self):
        text='val s = """\nReg Mux // test\n"""\nval x = Wire(UInt(8.W))'
        code=scala_code(text)
        self.assertNotIn('Reg',code);self.assertIn('Wire(UInt',code)
        self.assertEqual(code.count('\n'),text.count('\n'))

    def test_all_experiments_have_a_catalog_home_or_control_label(self):
        patterns=catalog();ids=[p['id'] for p in patterns]
        self.assertEqual(len(ids),len(set(ids)))
        names={n for p in patterns for n in p['benchmark_cases']}
        self.assertEqual(set(CASES)-names,{'wire64','native_add64'})
        self.assertFalse(names-set(CASES))
        self.assertIn('age8',STRUCTURAL_CASES)

    def test_every_pattern_has_an_explicit_scoped_review(self):
        patterns=catalog()
        self.assertEqual({p['id'] for p in patterns},set(REVIEWS))
        for pattern in patterns:
            for field in ['disposition','hardware_intent','reviewed_evidence','next_step','synthesis_qualification']:
                self.assertTrue(pattern[field],(pattern['id'],field))

    def samples(self):
        return dict(verified_vectors=1000000,samples=[dict(distribution=d,pair=i,
            order='AB' if i%2==0 else 'BA',generated_ns=2.,software_ns=1.,compute_slice_ns=1.5,slice_software_ns=1.)
            for d in DISTRIBUTIONS for i in range(8)])

    def test_pair_validation_rejects_missing_duplicate_wrong_order_and_nonfinite(self):
        valid=self.samples();validate_samples(valid)
        for mutation in ['missing','duplicate','order','nan','incomplete-functional']:
            x=deepcopy(valid)
            if mutation=='missing':x['samples'].pop()
            if mutation=='duplicate':x['samples'][-1]=deepcopy(x['samples'][0])
            if mutation=='order':x['samples'][0]['order']='BA'
            if mutation=='nan':x['samples'][0]['generated_ns']=float('nan')
            if mutation=='incomplete-functional':x['verified_vectors']=99
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):validate_samples(x)

    def test_extractor_rejects_unrecognized_dispatch(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            (p/'grhsim_Pattern_eval.cpp').write_text('void f(){eval_compute_batch_0();}')
            (p/'grhsim_Pattern_sched_0.cpp').write_text('// Supernode 0: unexpected format\n')
            result=extract_compute(p)
            self.assertFalse(result['available']);self.assertFalse((p/'research_compute.cpp').exists())

    def test_crc_control_requires_both_candidates_and_complete_pairs(self):
        data=dict(verified_vectors=1000000,samples=[dict(variant=v,distribution=d,pair=i,
            order='AB' if i%2==0 else 'BA',generated_ns=2.,candidate_ns=3.)
            for v in ['serial','lookup'] for d in DISTRIBUTIONS for i in range(8)])
        self.assertEqual(len(summarize_control(data)),10)
        bad=deepcopy(data);bad['samples'][0]['variant']='unknown'
        with self.assertRaises(ValueError):summarize_control(bad)
        bad=deepcopy(data);bad['samples'][0]['candidate_ns']=float('inf')
        with self.assertRaises(ValueError):summarize_control(bad)

    def test_assembly_counts_only_requested_function(self):
        text='00000100 <Software::step(Input const&)>:\n 100:\t48 01 c0\tadd %rax,%rax\n 103:\tc3\tret\n\n00000104 <other>:\n 104:\t90\tnop\n'
        r=assembly_function(text,r'^Software::step\(')
        self.assertEqual(r['instructions'],2);self.assertNotIn('nop',r['mnemonics'])
        self.assertIsNone(assembly_function(text,'absent'))


if __name__=='__main__':unittest.main()
