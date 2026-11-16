from pathlib import Path
import unittest
from cv32e40p_current_structure import is_stack, model_frame, peak_source_spans
from cv32e40p_current_structure_paths import dwarf_file_checksums, edge_dependence, node_dominates, state_view_signature

class StructureEvidenceTests(unittest.TestCase):
    def test_source_span_is_not_declaration_count(self):
        self.assertEqual(peak_source_spans([(1,2),(2,3),(8,8)]),dict(peak=2,line=2))
        with self.assertRaises(ValueError):peak_source_spans([(4,3)])
    def test_inline_header_does_not_replace_outer_model_location(self):
        frames=[dict(FileName='/tmp/model/runtime.hpp',Line=50,FunctionName='helper'),
                dict(FileName='/tmp/model/model.cpp',Line=100,FunctionName='model')]
        self.assertEqual(model_frame(frames,Path('/tmp/model'))['line'],100)
        self.assertIsNone(model_frame(frames,Path('/another')))
    def test_stack_address_excludes_stack_pointer_arithmetic(self):
        self.assertTrue(is_stack('0x10(%rsp,%rax,8), %rsi'))
        self.assertFalse(is_stack('$0x998, %rsp'))
    def cfg(self):
        return [dict(address=a,mnemonic=m,operands=o) for a,m,o in [
            (0,'movl','%eax, %ebx'),(1,'je','0x5 <model+5>'),
            (2,'xorl','%eax, %eax'),(3,'jmp','0x6 <model+6>'),
            (5,'movl','%ecx, %eax'),(6,'retq','')]]
    def test_branch_dependence_excludes_reconverged_code(self):
        self.assertEqual(edge_dependence(self.cfg(),1),{5:{5},2:{2,3}})
        self.assertTrue(node_dominates(self.cfg(),0,6))
        self.assertFalse(node_dominates(self.cfg(),2,6))
    def test_unknown_indirect_jump_refuses_proof(self):
        rows=self.cfg();rows[3]['operands']='*%rax'
        with self.assertRaisesRegex(ValueError,'indirect'):edge_dependence(rows,1)
    def test_embedded_checksums_keep_conflicting_copies_visible(self):
        def entry(name,digest):
            return f'file_names[  0]:\n name: "{name}"\n dir_index: 0\n md5_checksum: {digest}\n'
        a='a'*32;b='b'*32
        parsed=dwarf_file_checksums(entry('model.cpp',a)+entry('model.cpp',a)+entry('/tmp/model.cpp',b))
        self.assertEqual(parsed,{'model.cpp':{a,b}})
    def test_state_view_equivalence_uses_state_not_ssa_id(self):
        graph=dict(vals=[dict(sym='a',w=32,sgn=False,def_='ra'),dict(sym='b',w=32,sgn=False,def_='rb')],
            ops=[dict(sym='ra',kind='kRegisterReadPort',**{'in':[]},attrs={'regSymbol':{'v':'q'}}),
                 dict(sym='rb',kind='kRegisterReadPort',**{'in':[]},attrs={'regSymbol':{'v':'q'}})])
        for v in graph['vals']:v['def']=v.pop('def_')
        self.assertEqual(state_view_signature(graph,'a'),state_view_signature(graph,'b'))
        graph['ops'][1]['attrs']['regSymbol']['v']='different'
        self.assertNotEqual(state_view_signature(graph,'a'),state_view_signature(graph,'b'))

if __name__=='__main__':unittest.main()
