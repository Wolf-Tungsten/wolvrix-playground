#!/usr/bin/env python3
"""Unit tests for scripts/grhsim_edgecomplete_gates.py (synthetic checkpoints/logs)."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import grhsim_edgecomplete_gates as eg

SUPER = 3
NODE = 4
BOUNDARY = 2


def make_model(compute_fanout, removal_list=None):
    """v1 = and(v2, v3c) in supernode 2, consumed in supernode 3 (op 200);
    v2 = and(consts) in supernode 2 with row {2}. Supernode activeIds 10/20."""
    partitions = [
        [1, 0, 0, 0, [2, 3], [], []],
        [2, 1, SUPER, 1, [4], [], [], [[10], [], []]],
        [3, 1, SUPER, 1, [5], [], [], [[20], [], []]],
        [4, 2, NODE, 1, [], [100, 101, 102, 103, 104], []],
        [5, 3, NODE, 1, [], [200, 201], []],
    ]
    slots = [[0, BOUNDARY, 2, i * 8] for i in range(9)]
    layout = [8, [], [], slots, [], [], 0, 72, 0]
    schedule = [[], [], compute_fanout, [], [], [], 0, 0, [], 1]
    if removal_list is not None:
        schedule.append(removal_list)
    payload = [4, 1, partitions, layout, schedule]
    return {
        "strings": ["core.compute.and", "core.compute.constant"],
        "types": [[1, 0, "logic", 1]],
        "values": [[i, 1] for i in range(1, 10)],
        "operations": [
            [100, 1, 0, 0, [2, 3], [1], [], 0],
            [101, 2, 0, 0, [], [3], [], 0],
            [102, 1, 0, 0, [5, 6], [2], [], 0],
            [103, 2, 0, 0, [], [5], [], 0],
            [104, 2, 0, 0, [], [6], [], 0],
            [200, 1, 0, 0, [1, 4], [9], [], 0],
            [201, 2, 0, 0, [], [4], [], 0],
        ],
        "states": [],
        "mappings": [["cpu", 0, payload]],
    }


# save(1) = wr1 * 16 = 1600; widen = ch2 * (2 ops * 13 + 4) = 30 * ch2 = 300
VCHG = {1: (100, 5), 2: (10, 10)}
OLD_FANOUT = [[1, [3], []], [2, [2], []]]
NEW_FANOUT = [[2, [2, 3], []]]


class TestFanoutEdgesGate(unittest.TestCase):
    def run_gate(self, new_fanout, removal_list):
        old = make_model(OLD_FANOUT)
        new = make_model(new_fanout, removal_list)
        return eg.gate_fanout_edges(old, new, VCHG)

    def test_pass_on_exact_completion(self):
        g, selected, added = self.run_gate(NEW_FANOUT, [1])
        self.assertTrue(g.ok, g.detail)
        self.assertEqual([c["v"] for c in selected], [1])
        self.assertEqual(dict(added), {2: {3}})

    def test_fail_on_missing_removal(self):
        g, _, _ = self.run_gate([[1, [3], []], [2, [2, 3], []]], [])
        self.assertFalse(g.ok)

    def test_fail_on_extra_removal(self):
        g, _, _ = self.run_gate([], [1, 2])
        self.assertFalse(g.ok)

    def test_fail_on_missing_edge(self):
        g, _, _ = self.run_gate([[2, [2], []]], [1])
        self.assertFalse(g.ok)
        self.assertTrue(any("wrong edge sets" in d for d in g.detail))

    def test_fail_on_wrong_edge(self):
        g, _, _ = self.run_gate([[2, [3], []]], [1])
        self.assertFalse(g.ok)

    def test_fail_on_bad_order(self):
        g, _, _ = self.run_gate([[2, [3, 2], []]], [1])
        self.assertFalse(g.ok)
        self.assertTrue(any("activeId ordering" in d for d in g.detail))

    def test_fail_on_removal_list_mismatch(self):
        g, _, _ = self.run_gate(NEW_FANOUT, [2])
        self.assertFalse(g.ok)


def write_log(path, lines):
    Path(path).write_text("\n".join(lines) + "\n")


SN_BASE = ["[grhsim-dyn] sn 2 act=10 body=9 grp=8 chg=2",
           "[grhsim-dyn] sn 3 act=40 body=40 grp=30 chg=20"]


class TestDynamicGates(unittest.TestCase):
    def selected_and_bounds(self):
        old = make_model(OLD_FANOUT)
        view = eg.dc.view_from_model(old)
        selected = eg.ec.select(view, VCHG)
        return view, selected, eg.widen_bounds(selected, VCHG)

    def test_sn_bounded(self):
        view, selected, unit_bound = self.selected_and_bounds()
        self.assertEqual(unit_bound, {3: 10})
        with TemporaryDirectory() as td:
            base = Path(td) / "base.log"
            new = Path(td) / "new.log"
            write_log(base, SN_BASE)
            # widened unit 3 may grow by W_B=10; unit 2 must not grow
            write_log(new, ["[grhsim-dyn] sn 2 act=10 body=9 grp=8 chg=2",
                            "[grhsim-dyn] sn 3 act=50 body=50 grp=40 chg=30"])
            g = eg.gate_sn_bounded(base, new, unit_bound)
            self.assertTrue(g.ok, g.detail)
            write_log(new, ["[grhsim-dyn] sn 2 act=10 body=9 grp=8 chg=2",
                            "[grhsim-dyn] sn 3 act=51 body=50 grp=40 chg=30"])
            g = eg.gate_sn_bounded(base, new, unit_bound)
            self.assertFalse(g.ok)
            write_log(new, ["[grhsim-dyn] sn 2 act=11 body=9 grp=8 chg=2",
                            "[grhsim-dyn] sn 3 act=40 body=40 grp=30 chg=20"])
            g = eg.gate_sn_bounded(base, new, unit_bound)
            self.assertFalse(g.ok)

    def test_vchg_bounded(self):
        view, selected, unit_bound = self.selected_and_bounds()
        with TemporaryDirectory() as td:
            base = Path(td) / "base.log"
            new = Path(td) / "new.log"
            # baseline: removed v1 wr=100; v9 (produced in widened unit 3) wr=7
            write_log(base, ["[grhsim-vchg] v 1 wr=100 ch=5",
                             "[grhsim-vchg] v 2 wr=10 ch=10",
                             "[grhsim-vchg] v 9 wr=7 ch=3"])
            write_log(new, ["[grhsim-vchg] v 2 wr=10 ch=10",
                            "[grhsim-vchg] v 9 wr=17 ch=3"])  # +10 = W_B(3)
            g = eg.gate_vchg_bounded(base, new, selected, unit_bound, view)
            self.assertTrue(g.ok, g.detail)
            write_log(new, ["[grhsim-vchg] v 2 wr=10 ch=10",
                            "[grhsim-vchg] v 9 wr=18 ch=3"])
            g = eg.gate_vchg_bounded(base, new, selected, unit_bound, view)
            self.assertFalse(g.ok)
            write_log(new, ["[grhsim-vchg] v 1 wr=1 ch=0",
                            "[grhsim-vchg] v 2 wr=10 ch=10",
                            "[grhsim-vchg] v 9 wr=7 ch=3"])
            g = eg.gate_vchg_bounded(base, new, selected, unit_bound, view)
            self.assertFalse(g.ok)
            write_log(new, ["[grhsim-vchg] v 2 wr=10 ch=11",
                            "[grhsim-vchg] v 9 wr=7 ch=3"])
            g = eg.gate_vchg_bounded(base, new, selected, unit_bound, view)
            self.assertFalse(g.ok)

    def test_mshrink_closure(self):
        view, selected, unit_bound = self.selected_and_bounds()
        with TemporaryDirectory() as td:
            base = Path(td) / "base.log"
            new = Path(td) / "new.log"
            write_log(base, ["[grhsim-vchg] v 1 wr=100 ch=5",
                             "[grhsim-vchg] v 2 wr=10 ch=10",
                             "[grhsim-vchg] v 9 wr=7 ch=3"])
            # removed 100; added writes up to allowance (v2:0 + v9:10) = 10
            write_log(new, ["[grhsim-vchg] v 2 wr=10 ch=10",
                            "[grhsim-vchg] v 9 wr=15 ch=3"])
            g = eg.gate_mshrink_closure(base, new, selected, unit_bound, view, 100001)
            self.assertTrue(g.ok, g.detail)
            write_log(new, ["[grhsim-vchg] v 2 wr=10 ch=10",
                            "[grhsim-vchg] v 9 wr=19 ch=3"])  # +12 > allowance
            g = eg.gate_mshrink_closure(base, new, selected, unit_bound, view, 100001)
            self.assertFalse(g.ok)


if __name__ == "__main__":
    unittest.main()
