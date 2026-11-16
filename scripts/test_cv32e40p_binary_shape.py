import unittest

from cv32e40p_binary_shape import (annotation, instruction_shape, instructions,
    parse_addr2line, parse_perf_symbols, select_symbols)


class BinaryShapeParserTests(unittest.TestCase):
    def test_objdump_instruction_shape(self):
        text = '''
0000000000001000 <sample>:
   1000:\tpushq\t%rbp
   1001:\tmovq\t%rsp, %rbp
   1004:\tvmovdqu64\t%zmm0, 0x40(%rsp)
   100a:\tcmpb\t$0x0, (%rdi)
   100d:\tjne\t1010 <sample+0x10>
   100f:\tcallq\t1020 <helper>
   1014:\tcmovneq\t%rax, %rbx
   1018:\tretq
'''
        rows = instructions(text)
        self.assertEqual(len(rows), 8)
        shape = instruction_shape(rows)
        self.assertEqual(shape['branches'], 1)
        self.assertEqual(shape['conditional_branches'], 1)
        self.assertEqual(shape['calls'], 1)
        self.assertEqual(shape['returns'], 1)
        self.assertEqual(shape['memory_operand_instructions'], 2)
        self.assertEqual(shape['stack_operand_instructions'], 3)
        self.assertEqual(shape['vector_or_mask_instructions'], 1)
        self.assertEqual(shape['compare_or_test'], 1)
        self.assertEqual(shape['cmov_or_setcc'], 1)

    def test_perf_report_and_annotation_are_distinct_scopes(self):
        profile = parse_perf_symbols('''
    52.00% emu emu [.] VCv32Bench___024root___nba_sequent__TOP__0(...)
     0.25% emu emu [.] main
''')
        self.assertEqual(profile, [dict(percent=52.0,
            symbol='VCv32Bench___024root___nba_sequent__TOP__0(...)')])
        annotated = annotation('''
    40.00 : 1000: vmovdqu64 %zmm0, 0x40(%rsp)
     2.00 : 1004: jne 1010
''')
        self.assertEqual([row['function_percent'] for row in annotated], [40.0, 2.0])
        self.assertEqual([row['address'] for row in annotated], [0x1000, 0x1004])

    def test_grhsim_selects_scheduled_model_functions(self):
        symbols = [dict(symbol='GrhSIM_Cv32Bench::eval()', address=1, bytes=8),
                   dict(symbol='GrhSIM_Cv32Bench::eval_compute_batch_0()', address=2, bytes=10),
                   dict(symbol='GrhSIM_Cv32Bench::eval_commit_batch_9()', address=3, bytes=12),
                   dict(symbol='main', address=4, bytes=100)]
        chosen = select_symbols('grhsim', symbols, [])
        self.assertEqual([row['symbol'] for row in chosen], [
            'GrhSIM_Cv32Bench::eval()', 'GrhSIM_Cv32Bench::eval_commit_batch_9()',
            'GrhSIM_Cv32Bench::eval_compute_batch_0()'])

    def test_addr2line_pairs_function_and_source_location(self):
        self.assertEqual(parse_addr2line('helper\nsource.cpp:12\n??\n??:0\n', 2), [
            dict(function='helper', location='source.cpp:12'),
            dict(function='??', location='??:0')])


if __name__ == '__main__':
    unittest.main()
