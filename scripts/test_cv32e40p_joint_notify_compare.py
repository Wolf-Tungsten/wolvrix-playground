from pathlib import Path
import tempfile
import unittest
from cv32e40p_joint_notify_compare import check_partition

class JointPartitionTests(unittest.TestCase):
    def fixture(self,root,extra=False):
        old=root/'old';new=root/'new';old.mkdir();new.mkdir()
        filename='model_sched_0.cpp'
        text=''
        for kind,values in [('grhsim_any_changed',[1,2,3,4,5]),('grhsim_mux_notify_group',[1,2,3,4])]:
            for value in values:
                expr=kind+'_7_0';text+=f'{expr} = static_cast<bool>({expr} | (grhsim_changed_{value}));\n'
        (old/filename).write_text(text)
        (new/filename).write_text(
            '// Joint notify bucket: producer=7 bucket=0 sources=1,2,3,4, deferred=0, cache=0,\n'
            '// Joint notify bucket: producer=7 bucket=1 sources=5, deferred=0, cache='+('0,' if extra else '')+'\n')
        plan=dict(producer=7,buckets=2,sources=5,before=9,after=8,file=filename)
        return old,new,[plan]
    def test_exact_subset_reconstruction_and_cost(self):
        with tempfile.TemporaryDirectory() as directory:
            r=check_partition(*self.fixture(Path(directory)))[0]
            self.assertTrue(r['exact_target_sets_equal'])
            self.assertEqual((r['original'],r['factored']),(9,8))
    def test_rejects_using_superset_for_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'source set'):
                check_partition(*self.fixture(Path(directory),True))

if __name__=='__main__':unittest.main()
