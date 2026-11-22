"""Regression checks for overlapping write groups, renumbered ops and shared predicates."""
import unittest
from collections import Counter

from rank_reg_to_mem import commit_lines, summarize


class WriteActivityTest(unittest.TestCase):
    def test_overlap_and_renumbering(self):
        groups = [
            dict(members=2, outcome="no_true_match", consolidated_reject="mux_chain",
                 writes=[[1, "a", "r0"], [3, "b", "r1"]]),
            dict(members=1, outcome="no_true_match", consolidated_reject="priority_guard",
                 writes=[[1, "a", "r0"]]),
        ]
        counts = {("a", "r0"): Counter(visits=12, changes=1)}
        coverage = {**counts, ("b", "r1"): Counter(visits=0, changes=0)}
        classes = summarize(groups, counts, {("a", "r0"): 3}, coverage)
        self.assertEqual(classes["mux_chain+priority_guard"]["renumbered_sites"], 1)
        self.assertEqual(classes["mux_chain"]["coverage_only_ports"], 1)
        self.assertEqual(sum(c["visits"] for c in classes.values()), 12)
        with self.assertRaisesRegex(ValueError, "line counts differ"):
            summarize(groups, counts, {("a", "r0"): 3}, {("a", "r0"): Counter(visits=13, changes=1)})

    def test_shared_and_wide_visit_lines(self):
        rows = [b"if (unlikely(state.a != next_value)) {",
                b"// op w1 [kRegisterWritePort] reg=b", b"state.b = next_value;"]
        self.assertEqual(commit_lines(rows, 1, 0), (1, 3, "lockstep"))
        self.assertIsNone(commit_lines(rows, 1, None))
        rows = [b"// op w1 [kRegisterWritePort] reg=b",
                b"if (unlikely(grhsim_assign_words_2<128>(dst, src))) {", b"dirty |= 1;"]
        self.assertEqual(commit_lines(rows, 0, None), (2, 3, "wide"))


if __name__ == "__main__":
    unittest.main()
