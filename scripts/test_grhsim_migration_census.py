#!/usr/bin/env python3
"""Unit tests for scripts/grhsim_migration_census.py (pure eligibility logic)."""

import unittest

from grhsim_migration_census import (K_DETECT, K_STORE, MigrationView,
                                     anchor_prefilter, build_cone, cone_census,
                                     profit_of, rescore)


def make_view():
    """Tiny two-unit model:

    unit 1 (A): op 10 core.compute.and   -> v100 (boundary, clean anchor)
                op 11 core.compute.or    -> v101 (boundary, consumed across units)
                op 12 core.compute.xor   -> v102 (boundary, A-local cone via op 29)
                op 13 core.compute.eq    -> v103 (boundary, operand v110 unseen)
                op 14 core.dpi.call-ish  -> v104 (boundary, non-compute kind)
                op 15 core.compute.mux   -> v105 (boundary, event-gate value)
                op 16 core.compute.add   -> v106 (boundary, wide 128b)
                op 17 core.compute.sub   -> v107 (boundary, operand v208 unseen)
                op 18 core.compute.expr  -> v108 (boundary, expr kind)
                op 19 core.compute.constant -> v112 (constant, A-local, free clone)
                op 29 core.compute.not   -> v109 (A-local, read by op 12 only)
                op 30 core.compute.xnor  -> v113 (A-local, shared: read by 12+31)
                op 31 core.compute.and   -> v114 (A-local, reads v113, stays)
                op 21 core.compute.or    -> v301 (in unit 1, consumes v101)
    unit 2 (B): op 20 core.compute.and (operands v100, v101, v200, v201)
                op 22 core.compute.mux (operand v105)
                op 23 core.compute.and (operand v107 -> v111 boundary, v303)
                op 24..28 consume v102/v103/v104/v106/v108
                op 32 core.compute.or  -> v115 (boundary, anchor w/ const cone)
    v110 produced outside units (unit 0), read only by op 13 (unseen by B).
    v111 produced by op 23 inside B (boundary, read by op 17 in A).
    op 32 (in B) consumes v115; v115 produced by op 33 (in A, operands v112
    constant + v202 already read by B via op 20).
    """
    view = MigrationView()
    ops = {
        10: ("core.compute.and", [200, 201], [100]),
        11: ("core.compute.or", [202], [101]),
        12: ("core.compute.xor", [109, 203], [102]),
        13: ("core.compute.eq", [110], [103]),
        14: ("core.dpi.call", [], [104]),
        15: ("core.compute.mux", [204, 205, 206], [105]),
        16: ("core.compute.add", [207], [106]),
        17: ("core.compute.sub", [111, 208], [107]),
        18: ("core.compute.expr", [209], [108]),
        19: ("core.compute.constant", [], [112]),
        29: ("core.compute.not", [210], [109]),
        30: ("core.compute.xnor", [211], [113]),
        31: ("core.compute.and", [113], [114]),
        33: ("core.compute.or", [112, 202], [115]),
        20: ("core.compute.and", [100, 101, 200, 201, 202, 203, 210], [300]),
        21: ("core.compute.or", [101], [301]),
        22: ("core.compute.mux", [105], [302]),
        23: ("core.compute.and", [107], [111, 303]),
        24: ("core.compute.xor", [102], [304]),
        25: ("core.compute.eq", [103], [305]),
        26: ("core.compute.add", [104], [306]),
        27: ("core.compute.sub", [106], [307]),
        28: ("core.compute.assign", [108], [308]),
        32: ("core.compute.or", [115], [309]),
    }
    for oid, (name, operands, results) in ops.items():
        view.op_name[oid] = name
        view.op_operands[oid] = operands
        view.op_results[oid] = results
        view.op_has_refs[oid] = (oid == 14)
        for v in results:
            view.producer_of[v] = oid
        for v in operands:
            view.consumers_of.setdefault(v, []).append(oid)
    for oid in (10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 29, 30, 31, 33, 21):
        view.unit_of_op[oid] = 1
    for oid in (20, 22, 23, 24, 25, 26, 27, 28, 32):
        view.unit_of_op[oid] = 2
    view.is_boundary = {100, 101, 102, 103, 104, 105, 106, 107, 108, 111, 115}
    view.event_gate_values = {105}
    for vid in (100, 101, 102, 103, 104, 105, 107, 108, 109, 110, 111, 112, 113,
                114, 115, 200, 201, 202, 203, 204, 205, 206, 207, 208, 209, 210,
                211):
        view.width[vid] = 1
    view.width[106] = 128
    inputs = {1: set(), 2: set()}
    for oid, unit in view.unit_of_op.items():
        for w in view.op_operands[oid]:
            if view.producer_unit(w) != unit:
                inputs[unit].add(w)
    view.unit_inputs = inputs
    return view


class CensusTest(unittest.TestCase):
    def test_anchor_prefilter(self):
        view = make_view()
        self.assertIsInstance(anchor_prefilter(view, 101), str)  # multi unit
        self.assertEqual(anchor_prefilter(view, 101), "multi_consumer_unit")
        self.assertEqual(anchor_prefilter(view, 104), "producer_kind")
        self.assertEqual(anchor_prefilter(view, 105), "event_gate")
        self.assertEqual(anchor_prefilter(view, 106), "width")
        self.assertEqual(anchor_prefilter(view, 108), "producer_kind")
        pre = anchor_prefilter(view, 100)
        self.assertEqual(pre[0], 10)
        self.assertEqual(pre[1], 1)
        self.assertEqual(pre[2], 2)

    def test_build_cone(self):
        view = make_view()
        # clean single-op anchor
        members, fail = build_cone(view, 10, 1, 2)
        self.assertEqual(members, {10})
        # cone through A-local v109 (op 29 co-migrates)
        members, fail = build_cone(view, 12, 1, 2)
        self.assertEqual(members, {12, 29})
        # constant operand cloned for free
        members, fail = build_cone(view, 33, 1, 2)
        self.assertEqual(members, {33})
        # unseen input operand
        _, fail = build_cone(view, 13, 1, 2)
        self.assertEqual(fail, "input_unseen")
        # v208 has no producer
        _, fail = build_cone(view, 17, 1, 2)
        self.assertEqual(fail, "input_unseen")

    def test_shared_intermediate_rejected(self):
        view = make_view()
        # op 12 reads v113 too: v113 is shared with op 31 which stays in A
        view.op_operands[12] = [109, 113, 203]
        view.consumers_of[113].append(12)
        _, fail = build_cone(view, 12, 1, 2)
        self.assertEqual(fail, "shared_intermediate")

    def test_cone_census(self):
        view = make_view()
        anchors, rejections = cone_census(view)
        got = {a["v"]: a["cone_size"] for a in anchors}
        self.assertEqual(got, {100: 1, 102: 2, 115: 1})
        self.assertEqual(rejections["multi_consumer_unit"], 1)
        self.assertEqual(rejections["producer_kind"], 2)
        self.assertEqual(rejections["event_gate"], 1)
        self.assertEqual(rejections["width"], 1)
        self.assertEqual(rejections["input_unseen"], 2)

    def test_profit(self):
        view = make_view()
        anchors, _ = cone_census(view)
        rows = rescore(anchors, {100: (10, 2), 102: (4, 1), 115: (3, 0)},
                       {2: 4})
        by_v = {r["v"]: r for r in rows}
        profit, reeval = profit_of(by_v[100], view)
        self.assertEqual(by_v[100]["save"], 10 * (K_DETECT + K_STORE))
        self.assertEqual(reeval, 4 * 2)  # K_EVAL(and)=2, cone size 1
        self.assertEqual(profit, 40 - 8)
        _, reeval = profit_of(by_v[102], view)
        self.assertEqual(reeval, 4 * (2 + 2))  # xor + not cone


if __name__ == "__main__":
    unittest.main()
