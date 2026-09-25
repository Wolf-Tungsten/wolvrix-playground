#!/usr/bin/env python3
"""Unit tests for scripts/grhsim_demonitor_gates.py (synthetic checkpoints/logs)."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import grhsim_demonitor_gates as dg
from test_grhsim_demonitor_census import make_model


class TestFanoutRowsGate(unittest.TestCase):
    def test_pass_on_exact_removal(self):
        old = make_model([[1, [3], []], [2, [3], []]])
        new = make_model([[2, [3], []]])
        g = dg.gate_fanout_rows(old, new)
        self.assertTrue(g.ok, g.detail)
        self.assertIn("removed rows: 1", g.detail[-1])

    def test_fail_on_extra_removal(self):
        old = make_model([[1, [3], []], [2, [3], []]])
        new = make_model([])
        g = dg.gate_fanout_rows(old, new)
        self.assertFalse(g.ok)
        self.assertTrue(any("not eligible" in d for d in g.detail))

    def test_fail_on_missing_removal(self):
        old = make_model([[1, [3], []], [2, [3], []]])
        new = make_model([[1, [3], []], [2, [3], []]])
        g = dg.gate_fanout_rows(old, new)
        self.assertFalse(g.ok)
        self.assertTrue(any("NOT removed" in d for d in g.detail))

    def test_fail_on_row_growth(self):
        old = make_model([[1, [3], []], [2, [3], []]])
        new = make_model([[1, [3], []], [2, [3], []], [3, [3], []]])
        g = dg.gate_fanout_rows(old, new)
        self.assertFalse(g.ok)
        self.assertTrue(any("new fanout rows" in d for d in g.detail))

    def test_fail_on_changed_survivor(self):
        old = make_model([[1, [3], []], [2, [3], []]])
        new = make_model([[2, [2, 3], []]])
        g = dg.gate_fanout_rows(old, new)
        self.assertFalse(g.ok)
        self.assertTrue(any("surviving fanout rows changed" in d for d in g.detail))


def write_log(path, lines):
    Path(path).write_text("\n".join(lines) + "\n")


SN_BASE = ["[grhsim-dyn] sn 1 act=10 body=9 grp=8 chg=2",
           "[grhsim-dyn] sn 2 act=5 body=5 grp=4 chg=1"]
KIND_BASE = ["[grhsim-dyn] kind core.compute.and wr=1000 ch=50 silent=10",
             "[grhsim-dyn] kind core.compute.eq wr=500 ch=25 silent=5"]
ENDPOINT = ["EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80000c0c",
            "instrCnt = 240,349, cycleCnt = 99,996",
            "Guest cycle spent: 100,001"]


class TestDynamicGates(unittest.TestCase):
    def test_sn_dominated_shrink_ok(self):
        with TemporaryDirectory() as td:
            base = Path(td) / "base.log"
            new = Path(td) / "new.log"
            write_log(base, SN_BASE)
            write_log(new, ["[grhsim-dyn] sn 1 act=10 body=9 grp=7 chg=2",
                            "[grhsim-dyn] sn 2 act=5 body=5 grp=4 chg=1"])
            g = dg.gate_sn_dominated(base, new)
            self.assertTrue(g.ok, g.detail)
            self.assertIn("reduced counters", g.detail[-1])

    def test_sn_dominated_growth_fails(self):
        with TemporaryDirectory() as td:
            base = Path(td) / "base.log"
            new = Path(td) / "new.log"
            write_log(base, SN_BASE)
            write_log(new, ["[grhsim-dyn] sn 1 act=11 body=9 grp=8 chg=2",
                            "[grhsim-dyn] sn 2 act=5 body=5 grp=4 chg=1"])
            g = dg.gate_sn_dominated(base, new)
            self.assertFalse(g.ok)

    def test_kind_and_mshrink(self):
        with TemporaryDirectory() as td:
            base = Path(td) / "base.log"
            new = Path(td) / "new.log"
            write_log(base, KIND_BASE)
            write_log(new, ["[grhsim-dyn] kind core.compute.and wr=980 ch=50 silent=30",
                            "[grhsim-dyn] kind core.compute.eq wr=500 ch=25 silent=5"])
            g, base_kinds, new_kinds = dg.gate_kind_dominated(base, new)
            self.assertTrue(g.ok, g.detail)
            g = dg.gate_mshrink(base_kinds, new_kinds, 0.012, 100001)
            self.assertTrue(g.ok, g.detail)
            g = dg.gate_mshrink(base_kinds, new_kinds, 0.02, 100001)
            self.assertFalse(g.ok)

    def test_determinism_endpoint(self):
        with TemporaryDirectory() as td:
            run1 = Path(td) / "run1.log"
            run2 = Path(td) / "run2.log"
            stream = KIND_BASE + ["[grhsim-vchg] v 1 wr=3 ch=1"] + ENDPOINT
            write_log(run1, stream)
            write_log(run2, stream)
            g = dg.gate_determinism(run1, run2)
            self.assertTrue(g.ok, g.detail)
            write_log(run2, KIND_BASE + ["[grhsim-vchg] v 1 wr=4 ch=1"] + ENDPOINT)
            g = dg.gate_determinism(run1, run2)
            self.assertFalse(g.ok)


class TestModelNeutralGates(unittest.TestCase):
    def test_model_and_partition_neutral(self):
        old = make_model([[1, [3], []]])
        new = make_model([])
        self.assertTrue(dg.gate_model_neutral(old, new).ok)
        self.assertTrue(dg.gate_partition_layout_neutral(old, new).ok)
        changed = make_model([])
        changed["strings"] = ["x"]
        self.assertFalse(dg.gate_model_neutral(old, changed).ok)


if __name__ == "__main__":
    unittest.main()
