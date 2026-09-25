#!/usr/bin/env python3
"""Unit tests for scripts/grhsim_demonitor_census.py (synthetic views/models)."""

from collections import defaultdict
import unittest

import grhsim_demonitor_census as dc

SUPER = 3
NODE = 4
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
    }


def base_view():
    """v10 = and(20, 30c) in unit 1, consumed in unit 2; 20 monitored -> 2."""
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
    view["fanout_activate"] = {10: {2}, 20: {2}}
    view["fanout_arm"] = {10: set(), 20: set()}
    return view


def eligible_of(view):
    eligible, partial, rejections, port_arm, state_cover, pre = dc.census(view)
    return eligible, partial, rejections


class TestCensus(unittest.TestCase):
    def test_covered_is_eligible(self):
        eligible, _, rejections = eligible_of(base_view())
        self.assertEqual([e["v"] for e in eligible], [10])
        self.assertEqual(rejections.get("no_producer", 0), 1)  # v20 has no producer

    def test_uncovered_operand_rejected(self):
        view = base_view()
        view["fanout_activate"][20] = {3}  # 20 no longer activates unit 2
        eligible, _, rejections = eligible_of(view)
        self.assertEqual(eligible, [])
        self.assertEqual(rejections["operand_not_covering"], 1)

    def test_side_effect_unit_rejected(self):
        view = base_view()
        view["op_name"][201] = "core.system.task"
        view["unit_ops"][2].append(201)
        eligible, _, rejections = eligible_of(view)
        self.assertEqual(eligible, [])
        self.assertEqual(rejections["side_effect_unit"], 1)

    def test_port_arm_rejected(self):
        view = base_view()
        view["port_arm_values"] = {10}
        eligible, _, rejections = eligible_of(view)
        self.assertEqual(eligible, [])
        self.assertEqual(rejections["port_arm"], 1)

    def test_arm_list_rejected(self):
        view = base_view()
        view["fanout_arm"][10] = {9}
        eligible, _, rejections = eligible_of(view)
        self.assertEqual(eligible, [])
        self.assertEqual(rejections["arm_non_empty"], 1)

    def test_cascade_fixpoint(self):
        """Chain 30 -> 20 -> 10, all covered: 20 stays, 10 drops (operand removed)."""
        view = make_view()
        view["is_boundary"] = {10, 20, 30}
        view["width"] = {10: 1, 20: 1, 30: 1}
        view["op_name"] = {100: "core.compute.not", 101: "core.compute.not",
                           200: "core.compute.and"}
        view["op_operands"] = {100: [20], 101: [30], 200: [10, 20]}
        view["op_results"] = {100: [10], 101: [20], 200: [40]}
        view["op_has_refs"] = {100: False, 101: False, 200: False}
        view["producer_of"] = {10: 100, 20: 101, 30: 103, 40: 200}
        view["op_name"][103] = "core.input.read"
        view["op_results"][103] = [30]
        view["unit_of_op"] = {100: 1, 101: 1, 103: 1, 200: 2}
        view["unit_ops"] = defaultdict(list, {1: [100, 101, 103], 2: [200]})
        view["fanout_activate"] = {10: {2}, 20: {2}, 30: {2}}
        view["fanout_arm"] = {10: set(), 20: set(), 30: set()}
        eligible, _, _ = eligible_of(view)
        # 30 is rejected (producer_kind: input.read), 20 survives, 10 cascades out.
        self.assertEqual([e["v"] for e in eligible], [20])

    def test_constant_producer_eligible(self):
        view = make_view()
        view["is_boundary"] = {10}
        view["width"] = {10: 32}
        view["op_name"] = {100: "core.compute.constant", 200: "core.compute.and"}
        view["op_operands"] = {100: [], 200: [10]}
        view["op_results"] = {100: [10], 200: [40]}
        view["op_has_refs"] = {100: False, 200: False}
        view["producer_of"] = {10: 100, 40: 200}
        view["unit_of_op"] = {100: 1, 200: 2}
        view["unit_ops"] = defaultdict(list, {1: [100], 2: [200]})
        view["fanout_activate"] = {10: {2}}
        view["fanout_arm"] = {10: set()}
        eligible, _, _ = eligible_of(view)
        self.assertEqual([e["v"] for e in eligible], [10])


def make_model(compute_fanout):
    partitions = [
        [1, 0, 0, 0, [2, 3], [], []],
        [2, 1, SUPER, 1, [4], [], []],
        [3, 1, SUPER, 1, [5], [], []],
        [4, 2, NODE, 1, [], [100, 101], []],
        [5, 3, NODE, 1, [], [200], []],
    ]
    layout = [8, [], [], [[0, BOUNDARY, 2, 0], [0, BOUNDARY, 2, 8], [0, BOUNDARY, 2, 16],
                          [0, BOUNDARY, 2, 24]], [], [], 0, 32, 0]
    schedule = [[], [], compute_fanout, [], [], [], 0, 0, []]
    payload = [4, 1, partitions, layout, schedule]
    return {
        "strings": ["core.compute.and", "core.compute.constant"],
        "types": [[1, 0, "logic", 1]],
        "values": [[1, 1], [2, 1], [3, 1], [4, 1]],
        "operations": [
            [100, 1, 0, 0, [2, 3], [1], [], 0],
            [101, 2, 0, 0, [], [3], [], 0],
            [200, 1, 0, 0, [1, 2], [4], [], 0],
        ],
        "states": [],
        "mappings": [["cpu", 0, payload]],
    }


class TestViewFromModel(unittest.TestCase):
    def test_mini_model_end_to_end(self):
        model = make_model([[1, [3], []], [2, [3], []]])
        view = dc.view_from_model(model)
        eligible, _, rejections = eligible_of(view)
        self.assertEqual([e["v"] for e in eligible], [1])
        self.assertEqual(rejections.get("no_producer", 0), 1)


if __name__ == "__main__":
    unittest.main()
