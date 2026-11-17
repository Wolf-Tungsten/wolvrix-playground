"""Structural invariants for the fixed indexed snapshot experiment."""
from pathlib import Path
import tempfile
import unittest
from indexed_snapshot_compare import check_structure, contract


class SnapshotStructureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.old=Path(self.tmp.name)/'old';self.new=Path(self.tmp.name)/'new'
        for p in (self.old,self.new):
            p.mkdir();(p/'grhsim_top.hpp').write_text('layout\n');(p/'grhsim_top_eval.cpp').write_text('same eval\n')
        self.file='grhsim_top_sched_0.cpp'
        self.common='// Supernode 7:\nconst bool grhsim_changed_11 = x;\n'
        (self.old/self.file).write_text(self.common+'// Indexed concat: assemble only the selected word(s).\n')
        (self.new/self.file).write_text(self.common+'// Indexed concat snapshot array: value=20 lane_width=32 lanes=8\n')

    def test_valid(self):
        result=check_structure(self.old,self.new)
        self.assertEqual(result['candidate']['snapshot_bytes'],32)
        self.assertEqual(result['candidate']['views'],1)

    def test_activation_drift(self):
        with (self.new/self.file).open('a') as f:f.write('supernode_active_curr_[0] |= 1;\n')
        with self.assertRaises(AssertionError):check_structure(self.old,self.new)

    def test_extra_view(self):
        with (self.new/self.file).open('a') as f:f.write('// Indexed concat: extra\n')
        with self.assertRaises(AssertionError):check_structure(self.old,self.new)

    def test_no_layout_change(self):
        (self.new/'grhsim_top.hpp').write_text('changed layout\n')
        with self.assertRaises(AssertionError):check_structure(self.old,self.new)

    def test_no_eval_change(self):
        (self.new/'grhsim_top_eval.cpp').write_text('changed eval\n')
        with self.assertRaises(AssertionError):check_structure(self.old,self.new)

    def test_no_site_is_not_coverage(self):
        (self.new/self.file).write_text((self.old/self.file).read_text())
        with self.assertRaises(AssertionError):check_structure(self.old,self.new)


if __name__=='__main__':unittest.main()
