#!/usr/bin/env python3
"""Unit tests for scripts/grhsim_edgecomplete_census.py (synthetic views)."""

from collections import defaultdict
import unittest

import grhsim_edgecomplete_census as ec

SUPER = 3
BOUNDARY = 2


def make_view():
    return {
        "op_name": {}, "op_operands": {}, "op_results": {}, "op_has_refs": {},
        "op_refs": {},
        "producer_of": {}, "consumers_of": defaultdict(list),
        "unit_of_op": {}, "unit_ops": defaultdict(list),
        "is_boundary": set(), "event_gate_values": set(), "width": {},
        "partitions": {1: [1, 0, SUPER], 2: [2, 0, SUPER], 3: [3, 0, SUPER]},
        "fanout_activate": {}, "fanout_arm": {},
        "pinned": set(), "port_arm_values": set(),
        "commit_fanout": defaultdict(set),
        "aliased_read_values": set(), "dpi_produced": set(),
    }


def base_view():
    """v10 = and(20, 30c) in unit 1, consumed in unit 2.
    20 monitored with row {1} (activates the producer, not the consumer)."""
    view = make_view()
    view["is_boundary"] = {10, 20}
    view["width"] = {10: 1, 20: 1}
    view["op_name"] = {100: "core.compute.and", 101: "core.compute.constant",
                       200: "core.compute.and"}
    view["op_operands"] = {100: [20, 30], 101: [], 200: [10, 20]}
    view["op_results"] = {100: [10], 101: [30], 200: [40]}
    view["op_has_refs"] = {100: False, 101: False, 200: False}
    view["producer_of"] = {10: 100, 30: 101, 40: 200}
    view["unit_of_op"] = {100: 1, 101: 1, 200: 2}
    view["unit_ops"] = defaultdict(list, {1: [100, 101], 2: [200]})
    view["fanout_activate"] = {10: {2}, 20: {1}}
    view["fanout_arm"] = {10: set(), 20: set()}
    return view


class TestCandidates(unittest.TestCase):
    def test_missing_edge_candidate(self):
        cands, rejections = ec.candidates(base_view())
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["v"], 10)
        self.assertEqual(cands[0]["missing"], {"2": [20]})
        self.assertEqual(cands[0]["operands"], [20])

    def test_full_cover_is_noop(self):
        view = base_view()
        view["fanout_activate"][20] = {1, 2}  # already activates the consumer
        cands, rejections = ec.candidates(view)
        self.assertEqual(cands, [])
        self.assertEqual(rejections["already_covered"], 1)

    def test_producer_not_activated_rejected(self):
        view = base_view()
        view["fanout_activate"][20] = {3}  # row exists but misses unit 1
        cands, rejections = ec.candidates(view)
        self.assertEqual(cands, [])
        self.assertEqual(rejections["producer_not_activated"], 1)

    def test_operand_row_missing_rejected(self):
        view = base_view()
        del view["fanout_activate"][20]
        cands, rejections = ec.candidates(view)
        self.assertEqual(cands, [])
        self.assertEqual(rejections["edge_row_missing"], 1)

    def test_operand_not_boundary_rejected(self):
        view = base_view()
        view["is_boundary"] = {10}
        cands, rejections = ec.candidates(view)
        self.assertEqual(cands, [])
        self.assertEqual(rejections["operand_not_boundary"], 1)

    def test_operand_pinned_rejected(self):
        view = base_view()
        view["pinned"] = {20}
        cands, rejections = ec.candidates(view)
        self.assertEqual(cands, [])
        self.assertEqual(rejections["edge_pinned"], 1)

    def test_side_effect_unit_rejected(self):
        view = base_view()
        view["op_name"][201] = "core.system.task"
        view["unit_ops"][2].append(201)
        cands, rejections = ec.candidates(view)
        self.assertEqual(cands, [])
        self.assertEqual(rejections["side_effect_unit"], 1)

    def test_port_arm_rejected(self):
        view = base_view()
        view["port_arm_values"] = {10}
        cands, rejections = ec.candidates(view)
        self.assertEqual(cands, [])
        self.assertEqual(rejections["port_arm"], 1)

    def test_aliased_missing_edge_rejected(self):
        # Completion source 20 is an emit-aliased state read: its schedule row
        # is dead code, so the added edge 20 -> unit 2 would never fire.
        view = base_view()
        view["aliased_read_values"] = {20}
        cands, rejections = ec.candidates(view)
        self.assertEqual(cands, [])
        self.assertEqual(rejections["operand_aliased"], 1)

    def test_aliased_covered_operand_ok(self):
        # Alias status only blocks *missing* edges: when the consumer unit is
        # already in activate(20), the runtime activation flows through the
        # state's publish (aliasConsumers) and the candidate stays valid.
        view = base_view()
        view["aliased_read_values"] = {20}
        view["fanout_activate"][20] = {1, 2}
        cands, rejections = ec.candidates(view)
        self.assertEqual(cands, [])
        self.assertEqual(rejections["already_covered"], 1)

    def test_dpi_blind_missing_edge_rejected(self):
        # Completion source 20 is a DPI call result: the vchg profile has no
        # counters at the DPI publish site, so its widen is unpriceable.
        view = base_view()
        view["dpi_produced"] = {20}
        cands, rejections = ec.candidates(view)
        self.assertEqual(cands, [])
        self.assertEqual(rejections["operand_dpi_blind"], 1)


class TestSelection(unittest.TestCase):
    def test_profit_selection(self):
        view = base_view()
        # save = wr10 * 16; widen_x4 = ch20 * (1 op * 13 + 4) = 17 * ch20
        sel = ec.select(view, {10: (100, 5), 20: (10, 10)})
        self.assertEqual([c["v"] for c in sel], [10])
        sel = ec.select(view, {10: (100, 5), 20: (1000, 100)})  # widen 1700 > save 1600
        self.assertEqual(sel, [])

    def test_profit_boundary_excluded(self):
        view = base_view()
        # wr10 * 16 == ch20 * 17 exactly -> profit == 0 -> not selected
        sel = ec.select(view, {10: (17, 0), 20: (160, 16)})
        self.assertEqual(sel, [])

    def test_fixpoint_over_selected_not_eligible(self):
        """Chain 30 -> 20 -> 10 across three units, both completable: if 20 is
        profitable it is removed and 10 cascades out; if 20 is unprofitable
        its row survives and 10 may be removed (the corrected selected-set
        fixpoint)."""
        view = make_view()
        view["partitions"][4] = [4, 0, SUPER]
        view["is_boundary"] = {10, 20, 30}
        view["width"] = {10: 1, 20: 1, 30: 1}
        view["op_name"] = {100: "core.compute.and", 101: "core.compute.and",
                           105: "core.compute.and", 200: "core.compute.and",
                           110: "core.compute.constant", 111: "core.compute.constant",
                           112: "core.compute.constant", 113: "core.compute.constant",
                           114: "core.compute.constant"}
        view["op_operands"] = {100: [20, 40], 101: [30, 50], 105: [92, 93],
                               200: [10, 70], 110: [], 111: [], 112: [], 113: [], 114: []}
        view["op_results"] = {100: [10], 101: [20], 105: [30], 200: [60],
                              110: [40], 111: [50], 112: [92], 113: [93], 114: [70]}
        view["op_has_refs"] = {op: False for op in view["op_name"]}
        view["producer_of"] = {10: 100, 20: 101, 30: 105, 40: 110, 50: 111,
                               92: 112, 93: 113, 70: 114, 60: 200}
        view["unit_of_op"] = {100: 1, 110: 1, 101: 3, 111: 3, 105: 4, 112: 4,
                              113: 4, 200: 2, 114: 2}
        view["unit_ops"] = defaultdict(list, {1: [100, 110], 2: [200, 114],
                                              3: [101, 111], 4: [105, 112, 113]})
        # 10 consumed in unit 2; 20 consumed in unit 1; 30 consumed in unit 3.
        view["fanout_activate"] = {10: {2}, 20: {1}, 30: {3}}
        view["fanout_arm"] = {10: set(), 20: set(), 30: set()}
        # cand(10): missing {2:[20]} (unit 2 has 2 ops); cand(20): missing
        # {1:[30]} (unit 1 has 2 ops); cand(30): already_covered.
        both_profitable = {10: (100, 1), 20: (100, 1), 30: (10, 1)}
        sel = ec.select(view, both_profitable)
        self.assertEqual([c["v"] for c in sel], [20])
        operand_unprofitable = {10: (100, 1), 20: (1, 1), 30: (100000, 100000)}
        sel = ec.select(view, operand_unprofitable)
        self.assertEqual([c["v"] for c in sel], [10])

    def test_cold_edge_free_widen(self):
        view = base_view()
        sel = ec.select(view, {10: (1, 1), 20: (0, 0)})  # ch20=0 -> widen 0
        self.assertEqual([c["v"] for c in sel], [10])
        self.assertEqual(sel[0]["cold_edges"], 1)


if __name__ == "__main__":
    unittest.main()
