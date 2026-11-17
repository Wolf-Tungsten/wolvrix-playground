"""Integrity failures that would invalidate a frozen conditional-arm comparison."""
from pathlib import Path
import tempfile
import unittest
from shared_arm_compare import census


class CensusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.before, self.audit, self.candidate = [Path(self.tmp.name) / n for n in ('before', 'audit', 'candidate')]
        self.filename = 'grhsim_top_sched_0.cpp'
        self.code = ('// Supernode 0: run\n'
            '            // Conditional mux cone: root=100 true_ops=20 false_ops=0\n')
        self.notes = ('        // Conditional mux shared arm: root=100 arm=0 original=20 reachable=5 outside=2 added=3 shared=1 cached=0 oversized=0 mode=audit ops=11,12,13,\n'
            '        // Conditional mux shared arm: root=100 arm=1 original=0 reachable=0 outside=0 added=0 shared=0 cached=0 oversized=0 mode=audit ops=\n')
        for p in (self.before, self.audit, self.candidate):
            p.mkdir(); (p / 'grhsim_top.hpp').write_text('unchanged header\n')
        (self.before / self.filename).write_text(self.code)
        (self.audit / self.filename).write_text(self.notes + self.code)
        (self.candidate / self.filename).write_text(self.notes.replace('mode=audit', 'mode=on') + self.code.replace('true_ops=20', 'true_ops=23'))

    def check(self):
        return census(self.before, self.audit, self.candidate)

    def change(self, folder, old, new, file=None):
        p = folder / (file or self.filename)
        p.write_text(p.read_text().replace(old, new))

    def test_valid_frozen_root(self):
        result = self.check()
        self.assertEqual(result['candidate']['summary']['added'], 3)

    def test_audit_may_not_change_code(self):
        self.change(self.audit, 'true_ops=20', 'true_ops=19')
        with self.assertRaises(AssertionError): self.check()

    def test_membership_must_match(self):
        self.change(self.candidate, '11,12,13,', '11,12,14,')
        with self.assertRaises(AssertionError): self.check()

    def test_duplicate_membership(self):
        self.change(self.candidate, '11,12,13,', '11,12,12,')
        with self.assertRaises(AssertionError): self.check()

    def test_no_new_roots(self):
        self.change(self.candidate, 'root=100', 'root=101')
        with self.assertRaises(AssertionError): self.check()

    def test_cache_may_not_expand(self):
        self.change(self.candidate, 'cached=0', 'cached=1')
        with self.assertRaises(AssertionError): self.check()

    def test_header_may_not_change(self):
        self.change(self.candidate, 'unchanged', 'changed', 'grhsim_top.hpp')
        with self.assertRaises(AssertionError): self.check()


if __name__ == '__main__': unittest.main()
