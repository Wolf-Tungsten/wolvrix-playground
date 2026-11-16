import unittest

from cv32e40p_post_view_structure import StateClosures, empty_call_bounds, empty_entry_path


def fixture(second_state='q'):
    graph={'vals':[],'ops':[]};mapping=[]
    def op(name,kind,args,attrs=None,group=0):
        graph['ops'].append(dict(sym=name,kind=kind,**{'in':args},attrs=attrs or {}))
        graph['vals'].append(dict(sym=name+'_v',w=32,**{'def':name}))
        mapping.append(dict(op_symbol=name,group=str(group),phase='compute'))
        return name+'_v'
    a=op('ra','kRegisterReadPort',[],{'regSymbol':{'v':'q'}})
    b=op('rb','kRegisterReadPort',[],{'regSymbol':{'v':second_state}})
    c=op('bits','kSliceStatic',[a]);d=op('inverse','kNot',[c]);root=op('both','kAnd',[d,b])
    op('independent','kRegisterReadPort',[],{'regSymbol':{'v':'q'}},group=1)
    check=dict(id='7',symbol=root,kind='kAnd',group=0,compute_targets=[1],compute_boundary_only=True)
    return graph,mapping,check


class PostViewStructureTests(unittest.TestCase):
    def test_different_reads_of_same_state_form_one_closure(self):
        g,m,c=fixture();s=StateClosures(g,m);rows=s.screen([c],set())
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['state'],'q')
        self.assertEqual(rows[0]['size'],3);self.assertEqual(rows[0]['depth'],3)
        self.assertEqual(s.screen([dict(c,comparisons=0,changes=0)],set()),
                         s.screen([dict(c,comparisons=999,changes=999)],set()))

    def test_multiple_state_or_missing_independent_read_rejected(self):
        g,m,c=fixture('r');self.assertEqual(StateClosures(g,m).screen([c],set()),[])
        g,m,c=fixture();m.pop();self.assertEqual(StateClosures(g,m).screen([c],set()),[])

    def test_cache_dependency_is_transitive_not_just_root(self):
        g,m,c=fixture();rows=StateClosures(g,m).screen([c],{'bits'})
        self.assertEqual(rows[0]['cache_dependencies'],['bits'])

    def test_cross_region_input_and_conditional_read_stop_closure(self):
        g,m,c=fixture();m[0]['group']='2';self.assertIsNone(StateClosures(g,m).closure(c['symbol'],0))
        g,m,c=fixture();g['ops'][0]['in']=['external'];self.assertIsNone(StateClosures(g,m).closure(c['symbol'],0))

    def test_cyclic_graph_is_not_a_pure_state_cone(self):
        g,m,c=fixture();g['ops'][2]['in']=[c['symbol']]
        with self.assertRaisesRegex(ValueError,'cycle'):StateClosures(g,m).closure(c['symbol'],0)

    def test_empty_calls_use_bounds_without_assuming_overlap(self):
        self.assertEqual(empty_call_bounds(10,[1,1,1]),dict(minimum=7,maximum=9))
        self.assertEqual(empty_call_bounds(10,[0,0]),dict(minimum=10,maximum=10))
        self.assertEqual(empty_call_bounds(10,[10,10]),dict(minimum=0,maximum=0))
        with self.assertRaises(ValueError):empty_call_bounds(10,[11])

    def test_empty_machine_path_excludes_the_taken_body(self):
        rows=[dict(address=a,mnemonic=m,operands=o) for a,m,o in [
            (0,'pushq','%rbx'),(1,'movzbl','0x83(%rdi), %ebx'),(2,'testb','%bl, %bl'),
            (3,'jne','0x9 <model+9>'),(4,'popq','%rbx'),(5,'retq',''),(9,'movb','$0, 0x83(%rdi)')]]
        result=empty_entry_path(rows);self.assertEqual(result['count'],6);self.assertEqual(result['pushes'],1)
        rows[4]['mnemonic']='callq'
        with self.assertRaises(ValueError):empty_entry_path(rows)


if __name__=='__main__':unittest.main()
