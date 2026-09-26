#!/usr/bin/env python3
"""Unit tests for scripts/grhsim_migrate_ec_census.py (synthetic views)."""

from collections import defaultdict
import unittest

import grhsim_migrate_ec_census as mc

SUPER = 3
NODE = 4


def base_view():
    """v10 = and(v20, v30c) in unit 1, consumed only in unit 2 (ops 200/201).
    v20 = and(v40c, v50c) in unit 1, also consumed in unit 3 (row {3}).
    v30 (constant) has an external reader (op 200), so no constant orphan."""
    view = {
        "op_name": {}, "op_operands": {}, "op_results": {}, "op_has_refs": {},
        "op_refs": {},
        "producer_of": {}, "consumers_of": defaultdict(list),
        "unit_of_op": {}, "unit_ops": defaultdict(list),
        "is_boundary": set(), "event_gate_values": set(), "width": {},
        "partitions": {
            1: [1, 0, SUPER, 0, [10], [], []],
            2: [2, 0, SUPER, 0, [20], [], []],
            3: [3, 0, SUPER, 0, [30], [], []],
            10: [10, 1, NODE, 0, [], [], []],
            20: [20, 2, NODE, 0, [], [], []],
            30: [30, 3, NODE, 0, [], [], []],
        },
        "fanout_activate": {}, "fanout_arm": {},
        "pinned": set(), "port_arm_values": set(),
        "commit_fanout": defaultdict(set),
        "aliased_read_values": set(), "dpi_produced": set(),
        "stored_ec_removed": set(),
    }
    view["is_boundary"] = {10, 20, 30}
    view["width"] = {10: 1, 20: 1, 30: 1}
    view["op_name"] = {100: "core.compute.and", 101: "core.compute.constant",
                       102: "core.compute.and", 103: "core.compute.constant",
                       104: "core.compute.constant",
                       200: "core.compute.and", 201: "core.compute.and",
                       203: "core.compute.constant",
                       300: "core.compute.and", 301: "core.compute.constant"}
    view["op_operands"] = {100: [20, 30], 102: [40, 50], 200: [10, 30],
                           201: [10, 70], 300: [20, 80]}
    view["op_results"] = {100: [10], 101: [30], 102: [20], 103: [40], 104: [50],
                          200: [60], 201: [61], 203: [70], 300: [62], 301: [80]}
    view["op_has_refs"] = {op: False for op in view["op_name"]}
    view["producer_of"] = {10: 100, 30: 101, 20: 102, 40: 103, 50: 104,
                           60: 200, 61: 201, 70: 203, 62: 300, 80: 301}
    view["unit_of_op"] = {100: 1, 101: 1, 102: 1, 103: 1, 104: 1,
                          200: 2, 201: 2, 203: 2, 300: 3, 301: 3}
    view["unit_ops"] = defaultdict(list, {1: [100, 101, 102, 103, 104],
                                          2: [200, 201, 203], 3: [300, 301]})
    for vid, ops in view["producer_of"].items():
        view["consumers_of"][vid] = []
    view["consumers_of"].update({20: [100, 300], 30: [100, 200], 40: [102],
                                 50: [102], 10: [200, 201], 70: [201], 80: [300]})
    view["fanout_activate"] = {10: {2}, 20: {3}, 30: {2}}
    view["fanout_arm"] = {10: set(), 20: set(), 30: set()}
    return view


def inputs(view):
    return mc.compute_unit_inputs(view)


class TestCandidates(unittest.TestCase):
    def test_new_edge_candidate(self):
        cands, rejections = mc.candidates(base_view(), inputs(base_view()))
        self.assertEqual(len(cands), 1)
        c = cands[0]
        self.assertEqual((c["v"], c["op"], c["unit_a"], c["unit_b"]), (10, 100, 1, 2))
        self.assertEqual(c["missing"], [20])
        self.assertEqual(rejections["multi_consumer_unit"], 1)  # v20: units 1+3
        self.assertEqual(rejections["producer_kind"], 1)        # v30: constant

    def test_zero_new_edge_remnant(self):
        view = base_view()
        # Op 204 in unit 2 already reads v20: the migration needs no new edge.
        view["op_name"][204] = "core.compute.and"
        view["op_operands"][204] = [20, 70]
        view["op_results"][204] = [63]
        view["op_has_refs"][204] = False
        view["producer_of"][63] = 204
        view["unit_of_op"][204] = 2
        view["unit_ops"][2].append(204)
        view["consumers_of"][20].append(204)
        cands, _ = mc.candidates(view, inputs(view))
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["missing"], [])

    def test_constant_orphan_rejected(self):
        view = base_view()
        # v30 loses its external reader: only X consumes it inside the donor.
        view["op_operands"][200] = [10, 70]
        view["consumers_of"][30] = [100]
        view["fanout_activate"].pop(30)
        view["fanout_arm"].pop(30)
        cands, rejections = mc.candidates(view, inputs(view))
        self.assertEqual(cands, [])
        self.assertEqual(rejections["constant_orphan"], 1)

    def test_edge_row_missing_rejected(self):
        view = base_view()
        del view["fanout_activate"][20]  # v20 monitored row gone
        cands, rejections = mc.candidates(view, inputs(view))
        self.assertEqual(cands, [])
        self.assertEqual(rejections["edge_row_missing"], 1)

    def test_edge_not_boundary_rejected(self):
        view = base_view()
        view["is_boundary"].discard(20)
        cands, rejections = mc.candidates(view, inputs(view))
        self.assertEqual(cands, [])
        self.assertEqual(rejections["edge_not_boundary"], 1)

    def test_edge_flag_rejections(self):
        for field, reason in (("pinned", "edge_pinned"),
                              ("event_gate_values", "edge_event_gate"),
                              ("aliased_read_values", "edge_aliased"),
                              ("dpi_produced", "edge_dpi_blind")):
            view = base_view()
            view[field].add(20)
            cands, rejections = mc.candidates(view, inputs(view))
            self.assertEqual(cands, [], reason)
            self.assertEqual(rejections[reason], 1, reason)

    def test_closure_rejections(self):
        cands, rejections = mc.candidates(base_view(), inputs(base_view()),
                                          closure={10})
        self.assertEqual(cands, [])
        self.assertEqual(rejections["closure_source"], 1)
        cands, rejections = mc.candidates(base_view(), inputs(base_view()),
                                          closure={20})
        self.assertEqual(cands, [])
        self.assertEqual(rejections["closure_edge"], 1)

    def test_side_effect_target_rejected(self):
        view = base_view()
        view["op_name"][205] = "core.system.task"
        view["op_has_refs"][205] = False
        view["unit_of_op"][205] = 2
        view["unit_ops"][2].append(205)
        cands, rejections = mc.candidates(view, inputs(view))
        self.assertEqual(cands, [])
        self.assertEqual(rejections["side_effect_unit"], 1)


class TestDemonitored(unittest.TestCase):
    def test_characterization(self):
        view = base_view()
        # v95: boundary, no stored row, consumer in compute super 2 -> removed.
        # v96: boundary, stored row present -> monitored. v97: produced and
        # consumed inside unit 1 (empty full row) -> not counted.
        view["is_boundary"] |= {95, 96, 97}
        view["width"].update({95: 1, 96: 1, 97: 1})
        view["op_name"].update({105: "core.compute.and", 107: "core.compute.and",
                                205: "core.compute.and", 206: "core.compute.and"})
        view["op_operands"].update({105: [40, 50], 107: [40, 50],
                                    205: [95, 96], 206: [97, 40]})
        view["op_results"].update({105: [95], 107: [97], 205: [63], 206: [64]})
        view["op_has_refs"].update({105: False, 107: False, 205: False, 206: False})
        view["producer_of"].update({95: 105, 97: 107, 63: 205, 64: 206})
        view["unit_of_op"].update({105: 1, 107: 1, 205: 2, 206: 1})
        view["unit_ops"][1].extend([105, 107, 206])
        view["unit_ops"][2].append(205)
        view["consumers_of"].update({95: [205], 96: [205], 97: [206]})
        view["fanout_activate"][96] = {2}
        view["fanout_arm"][96] = set()
        removed = mc.demonitored_values(view)
        self.assertIn(95, removed)
        self.assertNotIn(96, removed)
        self.assertNotIn(97, removed)


def cascade_view():
    """v10 = and(v20, v30c) in unit 1 consumed in unit 2 (edge source v20,
    row {1}); v20 = and(v40, v50c) in unit 6 consumed only in unit 1 (edge
    source v40, row {6}); v40 = and(v80c, v81c) in unit 3 consumed in unit 6
    but orphan-rejected. Both v10/v20 profitable -> v10 cascades out."""
    view = {
        "op_name": {}, "op_operands": {}, "op_results": {}, "op_has_refs": {},
        "op_refs": {},
        "producer_of": {}, "consumers_of": defaultdict(list),
        "unit_of_op": {}, "unit_ops": defaultdict(list),
        "is_boundary": set(), "event_gate_values": set(), "width": {},
        "partitions": {
            1: [1, 0, SUPER, 0, [10], [], []],
            2: [2, 0, SUPER, 0, [20], [], []],
            3: [3, 0, SUPER, 0, [30], [], []],
            6: [6, 0, SUPER, 0, [60], [], []],
            10: [10, 1, NODE, 0, [], [], []],
            20: [20, 2, NODE, 0, [], [], []],
            30: [30, 3, NODE, 0, [], [], []],
            60: [60, 6, NODE, 0, [], [], []],
        },
        "fanout_activate": {}, "fanout_arm": {},
        "pinned": set(), "port_arm_values": set(),
        "commit_fanout": defaultdict(set),
        "aliased_read_values": set(), "dpi_produced": set(),
        "stored_ec_removed": set(),
    }
    view["is_boundary"] = {10, 20, 30, 40, 50}
    view["width"] = {10: 1, 20: 1, 30: 1, 40: 1, 50: 1}
    view["op_name"] = {100: "core.compute.and", 101: "core.compute.constant",
                       105: "core.compute.and",
                       200: "core.compute.and",
                       300: "core.compute.and", 301: "core.compute.constant",
                       302: "core.compute.constant", 500: "core.compute.and",
                       600: "core.compute.and", 601: "core.compute.constant"}
    view["op_operands"] = {100: [20, 30], 105: [20, 30], 200: [10, 30],
                           300: [80, 81], 500: [50, 80], 600: [40, 50]}
    view["op_results"] = {100: [10], 101: [30], 105: [65], 200: [60],
                          300: [40], 301: [80], 302: [81], 500: [66],
                          600: [20], 601: [50]}
    view["op_has_refs"] = {op: False for op in view["op_name"]}
    view["producer_of"] = {10: 100, 30: 101, 65: 105, 60: 200, 40: 300,
                           80: 301, 81: 302, 66: 500, 20: 600, 50: 601}
    view["unit_of_op"] = {100: 1, 101: 1, 105: 1, 200: 2, 300: 3, 301: 3,
                          302: 3, 500: 3, 600: 6, 601: 6}
    view["unit_ops"] = defaultdict(list, {1: [100, 101, 105], 2: [200],
                                          3: [300, 301, 302, 500],
                                          6: [600, 601]})
    view["consumers_of"] = defaultdict(list, {20: [100, 105], 30: [100, 105, 200],
                                              10: [200], 80: [300, 500], 81: [300],
                                              40: [600], 50: [600, 500]})
    view["fanout_activate"] = {10: {2}, 20: {1}, 30: {2}, 40: {6}, 50: {3}}
    view["fanout_arm"] = {vid: set() for vid in view["fanout_activate"]}
    return view


class TestSelection(unittest.TestCase):
    VCHG = {10: (100, 5), 20: (50, 10)}

    def test_pricing_fields(self):
        view = base_view()
        sel = mc.select(view, inputs(view), self.VCHG, {2: 10})
        self.assertEqual([c["v"] for c in sel], [10])
        c = sel[0]
        # ops_B = 3 -> widen_x4 = ch20 * (4*13 + 4) = 10*56 = 560
        # reeval_x4 = body 10 * K_EVAL_X4(and)=8 -> 80; save_x4 = 100*16
        self.assertEqual(c["profit_x4"], 1600 - 560 - 80)
        self.assertAlmostEqual(c["widen"], 140.0)
        self.assertAlmostEqual(c["reeval"], 20.0)

    def test_profit_boundary_excluded(self):
        view = base_view()
        # profit_x4 = 1600 - 56*ch20 - 80: ch=27 -> +8 selected; ch=28 -> -48.
        sel = mc.select(view, inputs(view), {10: (100, 5), 20: (50, 27)}, {2: 10})
        self.assertEqual([c["v"] for c in sel], [10])
        sel = mc.select(view, inputs(view), {10: (100, 5), 20: (50, 28)}, {2: 10})
        self.assertEqual(sel, [])

    def test_cold_edge_free_widen(self):
        view = base_view()
        sel = mc.select(view, inputs(view), {10: (1, 1), 20: (0, 0)}, {2: 0})
        self.assertEqual([c["v"] for c in sel], [10])
        self.assertEqual(sel[0]["cold_edges"], 1)

    def test_fixpoint_cascade(self):
        view = cascade_view()
        both = {10: (100, 1), 20: (100, 1), 40: (0, 0), 50: (0, 0)}
        sel = mc.select(view, mc.compute_unit_inputs(view), both,
                        {2: 10, 1: 10, 6: 0})
        self.assertEqual([c["v"] for c in sel], [20])
        # v20 unprofitable (save 16 < reeval 80): v10's operand is no longer
        # selected, so v10 survives alone.
        cold = {10: (100, 1), 20: (1, 1), 40: (0, 0), 50: (0, 0)}
        sel = mc.select(view, mc.compute_unit_inputs(view), cold,
                        {2: 10, 1: 10, 6: 0})
        self.assertEqual([c["v"] for c in sel], [10])


if __name__ == "__main__":
    unittest.main()
