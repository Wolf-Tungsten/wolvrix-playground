#!/usr/bin/env python3
"""Unit tests for scripts/grhsim_migrate_ec_gates.py (synthetic checkpoints/logs)."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import grhsim_migrate_ec_gates as mg

SUPER = 3
NODE = 4
BOUNDARY = 2
LOCAL = 1


def make_model(compute_fanout, node5_ops, v1_kind, stored=None, v1_owner=2):
    """v1 = logicNot(v2) in supernode 2 (op 100), consumed only in supernode 3
    (ops 200/201). v2 = and(v4, v5c) in supernode 2, also consumed in
    supernode 6 (row {6}; v4 has no row, so the replay keeps v2's row).
    v6/v7 (produced in supernode 3) are consumed by op 302 in supernode 6
    (monitored outputs of the migration target). Migrating op 100 into
    supernode 3 adds the edge v2 -> 3 and drops the v1 row. Only v1/v2/v6/v7
    are Boundary. Supernode activeIds 10/20/30."""
    partitions = [
        [1, 0, 0, 0, [2, 3, 6], [], []],
        [2, 1, SUPER, 1, [4], [], [], [[10], [], []]],
        [3, 1, SUPER, 1, [5], [], [], [[20], [], []]],
        [6, 1, SUPER, 1, [7], [], [], [[30], [], []]],
        [4, 2, NODE, 1, [], [100, 101, 102, 103, 104, 105], []],
        [5, 3, NODE, 1, [], node5_ops, []],
        [7, 6, NODE, 1, [], [300, 302], []],
    ]
    kinds = {1: v1_kind, 2: BOUNDARY, 3: BOUNDARY, 4: BOUNDARY, 5: LOCAL,
             6: BOUNDARY, 7: BOUNDARY, 8: LOCAL, 9: LOCAL, 10: LOCAL}
    slots = [[0, kinds[i + 1], v1_owner if i == 0 else 2, i * 8] for i in range(10)]
    layout = [8, [], [], slots, [], [], 0, 80, 0]
    schedule = [[], [], compute_fanout, [], [], [], 0, 0, [], 1]
    if stored is not None:
        schedule.append(stored)
    payload = [4, 1, partitions, layout, schedule]
    return {
        "strings": ["core.compute.and", "core.compute.constant",
                    "core.compute.logicNot"],
        "types": [[1, 0, "logic", 1]],
        "values": [[i, 1] for i in range(1, 11)],
        "operations": [
            [100, 3, 0, 0, [2], [1], [], 0],
            [101, 2, 0, 0, [], [3], [], 0],
            [102, 1, 0, 0, [4, 5], [2], [], 0],
            [103, 3, 0, 0, [8], [4], [], 0],
            [104, 2, 0, 0, [], [5], [], 0],
            [105, 2, 0, 0, [], [8], [], 0],
            [200, 1, 0, 0, [1, 3], [6], [], 0],
            [201, 1, 0, 0, [1, 4], [7], [], 0],
            [300, 3, 0, 0, [2], [9], [], 0],
            [302, 1, 0, 0, [6, 7], [10], [], 0],
        ],
        "states": [],
        "mappings": [["cpu", 0, payload]],
    }


OLD_NODE5 = [200, 201]
NEW_NODE5 = [200, 201, 100]
OLD_FANOUT = [[1, [3], []], [2, [6], []], [6, [6], []], [7, [6], []]]
NEW_FANOUT = [[2, [3, 6], []], [6, [6], []], [7, [6], []]]
SELECTED = [{"v": 1, "op": 100, "kind": "core.compute.logicNot", "unit_a": 2,
             "unit_b": 3, "width": 1, "operands": [2], "missing": [2]}]


def old_new(stored_old=None, stored_new=None, new_fanout=None):
    old = make_model(OLD_FANOUT, OLD_NODE5, BOUNDARY, stored_old)
    new = make_model(OLD_FANOUT if new_fanout is None else new_fanout,
                     NEW_NODE5, LOCAL, stored_new, v1_owner=3)
    return old, new


def mapping(old, new):
    from grhsim_migration_gates import MappingInfo, analyze_migration
    return analyze_migration(MappingInfo(old), MappingInfo(new))


def make_stored_model(fanout, stored):
    """S=1 logicNot(P=2) in supernode 2, consumed in supernode 3 (row {3}).
    P = and(vc, vq) in supernode 2 with layout owner 9 ( != every consumer
    owner), consumed in units 2/6 (row {2,6}); vq has no row, so P survives
    the NO00014 replay; vc's row {3} is replay-removed (constant producer).
    The stored removal of S then revalidates and appends the completion edge
    P->3, leaving exactly [[2, [2,3,6], []]]."""
    partitions = [
        [1, 0, 0, 0, [2, 3, 6], [], []],
        [2, 1, SUPER, 1, [4], [], [], [[10], [], []]],
        [3, 1, SUPER, 1, [5], [], [], [[20], [], []]],
        [6, 1, SUPER, 1, [7], [], [], [[30], [], []]],
        [4, 2, NODE, 1, [], [100, 101, 102, 103, 105], []],
        [5, 3, NODE, 1, [], [200], []],
        [7, 6, NODE, 1, [], [300], []],
    ]
    owners = {1: 2, 2: 9, 3: 2, 4: 2, 5: 2, 6: 3, 7: 6}
    kinds = {1: BOUNDARY, 2: BOUNDARY, 3: BOUNDARY}
    slots = [[0, kinds.get(i + 1, LOCAL), owners[i + 1], i * 8] for i in range(7)]
    layout = [8, [], [], slots, [], [], 0, 56, 0]
    schedule = [[], [], fanout, [], [], [], 0, 0, [], 1, stored]
    payload = [4, 1, partitions, layout, schedule]
    return {
        "strings": ["core.compute.and", "core.compute.constant",
                    "core.compute.logicNot"],
        "types": [[1, 0, "logic", 1]],
        "values": [[i, 1] for i in range(1, 8)],
        "operations": [
            [100, 3, 0, 0, [2], [1], [], 0],
            [101, 2, 0, 0, [], [3], [], 0],
            [102, 2, 0, 0, [], [5], [], 0],
            [103, 3, 0, 0, [5], [4], [], 0],
            [105, 1, 0, 0, [3, 4], [2], [], 0],
            [200, 1, 0, 0, [1, 3], [6], [], 0],
            [300, 3, 0, 0, [2], [7], [], 0],
        ],
        "states": [],
        "mappings": [["cpu", 0, payload]],
    }


STORED_FANOUT = [[2, [2, 3, 6], []]]
UNSTORED_FANOUT = [[1, [3], []], [2, [2, 6], []]]


class TestFanoutEdgesGate(unittest.TestCase):
    def run_gate(self, new_fanout=None, stored_old=None, stored_new=None):
        old, new = old_new(stored_old, stored_new, new_fanout)
        _, _, _, old_to_new, _ = mapping(old, new)
        return mg.gate_fanout_edges(old, new, old_to_new, {1})

    def test_pass_on_exact_migration(self):
        g = self.run_gate(new_fanout=NEW_FANOUT)
        self.assertTrue(g.ok, g.detail)

    def test_pass_with_identical_stored_lists(self):
        stored = make_stored_model(STORED_FANOUT, [1])
        g = mg.gate_fanout_edges(stored, stored, {}, set())
        self.assertTrue(g.ok, g.detail)

    def test_fail_on_changed_stored_list(self):
        old = make_stored_model(STORED_FANOUT, [1])
        new = make_stored_model(UNSTORED_FANOUT, [])
        g = mg.gate_fanout_edges(old, new, {}, set())
        self.assertFalse(g.ok)
        self.assertTrue(any("stored removal list changed" in d for d in g.detail))

    def test_fail_on_missing_completion_edge(self):
        corrupt = make_stored_model([[2, [2, 6], []]], [1])
        g = mg.gate_fanout_edges(corrupt, corrupt, {}, set())
        self.assertFalse(g.ok)
        self.assertTrue(any("deviate from the tree mirror" in d for d in g.detail))

    def test_fail_on_invalid_stored_entry(self):
        corrupt = make_stored_model(UNSTORED_FANOUT, [7])
        g = mg.gate_fanout_edges(corrupt, corrupt, {}, set())
        self.assertFalse(g.ok)
        self.assertTrue(any("fails revalidation" in d for d in g.detail))

    def test_fail_on_missing_row_removal(self):
        g = self.run_gate(new_fanout=[[1, [3], []]] + NEW_FANOUT)
        self.assertFalse(g.ok)

    def test_fail_on_missing_edge(self):
        g = self.run_gate(new_fanout=[[2, [6], []], [6, [6], []], [7, [6], []]])
        self.assertFalse(g.ok)
        self.assertTrue(any("deviate from the tree mirror" in d for d in g.detail))

    def test_fail_on_bad_order(self):
        g = self.run_gate(new_fanout=[[2, [6, 3], []], [6, [6], []], [7, [6], []]])
        self.assertFalse(g.ok)
        self.assertTrue(any("activeId ordering" in d for d in g.detail))

    def test_fail_on_untouched_row_change(self):
        g = self.run_gate(new_fanout=[[2, [3, 6], []], [6, [3], []], [7, [6], []]])
        self.assertFalse(g.ok)
        self.assertTrue(any("deviate from the tree mirror" in d for d in g.detail))


def make_mirror_model():
    """full_fanout_rows fixture: op 100 in supernode 2 (edge only where the
    layout owner differs); op 200 owned directly by an EmitFunction partition
    (non-supernode target is kept); op 300 under an EventDomain (excluded);
    the event gate arms v5 but skips the input v7; the unlisted op 501 (null
    owner) opens a targetless row for v12."""
    partitions = [
        [1, 0, 0, 0, [2, 8, 9], [], []],
        [2, 1, SUPER, 1, [4], [], [], [[10], [], []]],
        [4, 2, NODE, 1, [], [100], []],
        [8, 1, 6, 1, [], [200], [], [[40], [], []]],
        [9, 1, 2, 1, [10], [], [0, [[5, 0], [7, 0]]]],
        [10, 9, 6, 1, [], [300], []],
    ]
    owners = {6: 9, 12: 9}
    slots = [[0, LOCAL, owners.get(i + 1, 2), i * 8] for i in range(12)]
    layout = [8, [], [], slots, [], [], 0, 96, 0]
    schedule = [[], [], [], [], [], [], 0, 0, [], 1]
    payload = [4, 1, partitions, layout, schedule]
    return {
        "strings": ["core.compute.and", "core.compute.constant",
                    "core.compute.logicNot", "core.input.read"],
        "types": [[1, 0, "logic", 1]],
        "values": [[i, 1] for i in range(1, 13)],
        "operations": [
            [100, 1, 0, 0, [5, 6], [1], [], 0],
            [200, 3, 0, 0, [5], [2], [], 0],
            [300, 3, 0, 0, [5], [3], [], 0],
            [400, 2, 0, 0, [], [5], [], 0],
            [401, 2, 0, 0, [], [6], [], 0],
            [402, 4, 0, 0, [], [7], [], 0],
            [501, 3, 0, 0, [12], [11], [], 0],
        ],
        "states": [],
        "mappings": [["cpu", 0, payload]],
    }


class TestFullFanoutMirror(unittest.TestCase):
    def test_layout_owner_domain_arm_and_null_owner_edges(self):
        import grhsim_demonitor_census as dc
        model = make_mirror_model()
        rows = mg.full_fanout_rows(model, dc.view_from_model(model))
        self.assertEqual(rows, {5: [[8], [9]], 6: [[2], []], 12: [[], []]})


class TestReconciliation(unittest.TestCase):
    def test_restore_projection_spares_last_flat_candidate(self):
        old, _ = old_new()
        partitions = {p[0]: p for p in old["mappings"][0][-1][2]}
        selected = [{"v": v, "op": op, "unit_a": 2, "unit_b": 3, "missing": []}
                    for v, op in ((1, 100), (3, 101), (2, 102), (4, 103),
                                  (5, 104), (8, 105))]
        projected, spared = mg.restore_projection(selected, partitions, {})
        self.assertEqual(spared, [8])  # op 105 is last in flat order
        self.assertEqual({c["v"] for c in projected}, {1, 2, 3, 4, 5})

    def test_restore_projection_keeps_partial_donor(self):
        old, _ = old_new()
        partitions = {p[0]: p for p in old["mappings"][0][-1][2]}
        projected, spared = mg.restore_projection(SELECTED, partitions, {})
        self.assertEqual(spared, [])
        self.assertEqual({c["v"] for c in projected}, {1})

    def test_reconciliation_gate(self):
        g = mg.gate_reconciliation(SELECTED, SELECTED, [], {1: LOCAL})
        self.assertTrue(g.ok, g.detail)
        g = mg.gate_reconciliation(SELECTED, SELECTED, [], {1: LOCAL, 2: LOCAL})
        self.assertFalse(g.ok)


def write_log(path, lines):
    Path(path).write_text("\n".join(lines) + "\n")


SN_BASE = ["[grhsim-dyn] sn 2 act=10 body=9 grp=8 chg=2",
           "[grhsim-dyn] sn 3 act=40 body=40 grp=30 chg=20",
           "[grhsim-dyn] sn 6 act=7 body=7 grp=7 chg=1"]


class TestDynamicGates(unittest.TestCase):
    def setUp(self):
        old, new = old_new()
        _, _, _, self.old_to_new, _ = mapping(old, new)
        self.view = mg.dc.view_from_model(old)
        self.unit_bound = mg.widen_bounds(SELECTED, {2: (50, 10)})
        self.migrated = {1}

    def test_widen_bounds(self):
        self.assertEqual(self.unit_bound, {3: 10})

    def test_sn_bounded(self):
        with TemporaryDirectory() as td:
            base, new = Path(td) / "b.log", Path(td) / "n.log"
            write_log(base, SN_BASE)
            # widened unit 3 may grow act/body/grp by W_B=10, chg never grows;
            # donor unit 2 shrinks; unit 6 stays.
            write_log(new, ["[grhsim-dyn] sn 2 act=9 body=8 grp=8 chg=2",
                            "[grhsim-dyn] sn 3 act=50 body=50 grp=40 chg=20",
                            "[grhsim-dyn] sn 6 act=7 body=7 grp=7 chg=1"])
            g = mg.gate_sn_bounded(base, new, self.old_to_new, self.unit_bound, {3}, {})
            self.assertTrue(g.ok, g.detail)
            write_log(new, ["[grhsim-dyn] sn 2 act=10 body=9 grp=8 chg=2",
                            "[grhsim-dyn] sn 3 act=51 body=50 grp=40 chg=20",
                            "[grhsim-dyn] sn 6 act=7 body=7 grp=7 chg=1"])
            g = mg.gate_sn_bounded(base, new, self.old_to_new, self.unit_bound, {3}, {})
            self.assertFalse(g.ok)
            write_log(new, ["[grhsim-dyn] sn 2 act=11 body=9 grp=8 chg=2",
                            "[grhsim-dyn] sn 3 act=40 body=40 grp=30 chg=20",
                            "[grhsim-dyn] sn 6 act=7 body=7 grp=7 chg=1"])
            g = mg.gate_sn_bounded(base, new, self.old_to_new, self.unit_bound, {3}, {})
            self.assertFalse(g.ok)
            write_log(new, ["[grhsim-dyn] sn 2 act=10 body=9 grp=8 chg=2",
                            "[grhsim-dyn] sn 3 act=40 body=40 grp=30 chg=21",
                            "[grhsim-dyn] sn 6 act=7 body=7 grp=7 chg=1"])
            g = mg.gate_sn_bounded(base, new, self.old_to_new, self.unit_bound, {3}, {})
            self.assertFalse(g.ok)

    def test_sn_bounded_remon_chg(self):
        with TemporaryDirectory() as td:
            base, new = Path(td) / "b.log", Path(td) / "n.log"
            write_log(base, SN_BASE)
            # chg +2 on unit 3 within the re-monitor allowance {3: 2}.
            write_log(new, ["[grhsim-dyn] sn 2 act=9 body=8 grp=8 chg=2",
                            "[grhsim-dyn] sn 3 act=40 body=40 grp=30 chg=22",
                            "[grhsim-dyn] sn 6 act=7 body=7 grp=7 chg=1"])
            g = mg.gate_sn_bounded(base, new, self.old_to_new, self.unit_bound,
                                   {3}, {3: 2})
            self.assertTrue(g.ok, g.detail)
            # +3 exceeds the allowance.
            write_log(new, ["[grhsim-dyn] sn 2 act=9 body=8 grp=8 chg=2",
                            "[grhsim-dyn] sn 3 act=40 body=40 grp=30 chg=23",
                            "[grhsim-dyn] sn 6 act=7 body=7 grp=7 chg=1"])
            g = mg.gate_sn_bounded(base, new, self.old_to_new, self.unit_bound,
                                   {3}, {3: 2})
            self.assertFalse(g.ok)
            # the same +2 without an allowance still fails.
            g = mg.gate_sn_bounded(base, new, self.old_to_new, self.unit_bound,
                                   {3}, {})
            self.assertFalse(g.ok)

    def test_kind_vchg_bounded_remonitored(self):
        with TemporaryDirectory() as td:
            base, new = Path(td) / "b.log", Path(td) / "n.log"
            vchg_base = ["[grhsim-vchg] v 1 wr=100 ch=5",
                         "[grhsim-vchg] v 2 wr=50 ch=10",
                         "[grhsim-vchg] v 6 wr=7 ch=3"]
            kinds_base = ["[grhsim-dyn] kind core.compute.and wr=157 ch=18 silent=0"]
            write_log(base, vchg_base + kinds_base)
            # v5 re-monitored: absent from the baseline log ((0,0) by
            # construction), any new counts are exempt from the growth bounds.
            write_log(new, ["[grhsim-vchg] v 2 wr=50 ch=10",
                            "[grhsim-vchg] v 5 wr=9 ch=4",
                            "[grhsim-vchg] v 6 wr=7 ch=3",
                            "[grhsim-dyn] kind core.compute.and wr=66 ch=14 silent=0"])
            g = mg.gate_kind_vchg_bounded(base, new, self.migrated,
                                          self.unit_bound, self.view, {5})
            self.assertTrue(g.ok, g.detail)
            # the same growth outside the exception set still fails.
            g = mg.gate_kind_vchg_bounded(base, new, self.migrated,
                                          self.unit_bound, self.view, set())
            self.assertFalse(g.ok)
            # a re-monitored value with a nonzero baseline violates.
            g = mg.gate_kind_vchg_bounded(base, new, self.migrated,
                                          self.unit_bound, self.view, {2})
            self.assertFalse(g.ok)

    def test_kind_vchg_bounded(self):
        with TemporaryDirectory() as td:
            base, new = Path(td) / "b.log", Path(td) / "n.log"
            vchg_base = ["[grhsim-vchg] v 1 wr=100 ch=5",
                         "[grhsim-vchg] v 2 wr=50 ch=10",
                         "[grhsim-vchg] v 6 wr=7 ch=3"]
            kinds_base = ["[grhsim-dyn] kind core.compute.and wr=157 ch=18 silent=0"]
            write_log(base, vchg_base + kinds_base)
            # v1 migrated -> gone; v6 produced in widened unit 3 -> +10 ok.
            write_log(new, ["[grhsim-vchg] v 2 wr=50 ch=10",
                            "[grhsim-vchg] v 6 wr=17 ch=3",
                            "[grhsim-dyn] kind core.compute.and wr=67 ch=13 silent=0"])
            g = mg.gate_kind_vchg_bounded(base, new, self.migrated,
                                          self.unit_bound, self.view, set())
            self.assertTrue(g.ok, g.detail)
            write_log(new, ["[grhsim-vchg] v 2 wr=50 ch=10",
                            "[grhsim-vchg] v 6 wr=18 ch=3",
                            "[grhsim-dyn] kind core.compute.and wr=68 ch=13 silent=0"])
            g = mg.gate_kind_vchg_bounded(base, new, self.migrated,
                                          self.unit_bound, self.view, set())
            self.assertFalse(g.ok)
            write_log(new, ["[grhsim-vchg] v 1 wr=1 ch=0",
                            "[grhsim-vchg] v 2 wr=50 ch=10",
                            "[grhsim-vchg] v 6 wr=7 ch=3",
                            "[grhsim-dyn] kind core.compute.and wr=58 ch=13 silent=0"])
            g = mg.gate_kind_vchg_bounded(base, new, self.migrated,
                                          self.unit_bound, self.view, set())
            self.assertFalse(g.ok)
            write_log(new, ["[grhsim-vchg] v 2 wr=50 ch=11",
                            "[grhsim-vchg] v 6 wr=7 ch=3",
                            "[grhsim-dyn] kind core.compute.and wr=57 ch=14 silent=0"])
            g = mg.gate_kind_vchg_bounded(base, new, self.migrated,
                                          self.unit_bound, self.view, set())
            self.assertFalse(g.ok)

    def test_mshrink_closure(self):
        with TemporaryDirectory() as td:
            base, new = Path(td) / "b.log", Path(td) / "n.log"
            write_log(base, ["[grhsim-vchg] v 1 wr=100 ch=5",
                             "[grhsim-vchg] v 2 wr=50 ch=10",
                             "[grhsim-vchg] v 6 wr=7 ch=3"])
            # removed 100; monitored outputs of unit 3: v6/v7 -> allowance
            # W_B * 2 = 20; added writes 8 within.
            write_log(new, ["[grhsim-vchg] v 2 wr=50 ch=10",
                            "[grhsim-vchg] v 6 wr=15 ch=3"])
            g = mg.gate_mshrink_closure(base, new, SELECTED, self.migrated,
                                        self.unit_bound, self.view, 100001)
            self.assertTrue(g.ok, g.detail)
            # +25 beyond the 20 allowance.
            write_log(new, ["[grhsim-vchg] v 2 wr=50 ch=10",
                            "[grhsim-vchg] v 6 wr=32 ch=3"])
            g = mg.gate_mshrink_closure(base, new, SELECTED, self.migrated,
                                        self.unit_bound, self.view, 100001)
            self.assertFalse(g.ok)
            # closed-form violation: v1 baseline wr != selected wr sum.
            g = mg.gate_mshrink_closure(base, new, [{"v": 9, "missing": []}],
                                        self.migrated, self.unit_bound,
                                        self.view, 100001)
            self.assertFalse(g.ok)


class TestEndToEndSelection(unittest.TestCase):
    def test_recompute_selection_on_synthetic_model(self):
        """The in-process selection recomputed from the old model + a baseline
        log must pick exactly v1 (the only edge-feasible profitable value)."""
        old, _ = old_new()
        with TemporaryDirectory() as td:
            log = Path(td) / "base.log"
            # wr1=100 -> save_x4 1600; widen = ch2*((2+1)*13+4)=43*10=430;
            # reeval = body(3)=10 * K_EVAL_X4(logicNot)=4 -> 40; profit > 0.
            write_log(log, ["[grhsim-vchg] v 1 wr=100 ch=5",
                            "[grhsim-vchg] v 2 wr=50 ch=10",
                            "[grhsim-dyn] sn 3 act=10 body=10 grp=10 chg=1"])
            view, vchg, selected = mg.recompute_selection(old, log)
            self.assertEqual([c["v"] for c in selected], [1])
            self.assertEqual(selected[0]["missing"], [2])


if __name__ == "__main__":
    unittest.main()
