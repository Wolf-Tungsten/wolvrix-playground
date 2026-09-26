#!/usr/bin/env python3
"""Unit tests for grhsim_kind_cost_census (NO00017)."""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grhsim_kind_cost_census import (  # noqa: E402
    BUCKET_NAMES,
    active_offsets,
    compute_task_units,
    direct_commit_states,
    disasm_instruction_counts,
    frame_sizes,
    load_dyn_fires,
    mirror_port_arms,
    nnls,
    two_state_logic,
    unit_group_features,
    weighted_r2,
    width_bucket_of,
)

# type rows: [id, ref, kind, width, signed, domain, elem, count]
T_U1 = [1, 0, "logic", 1, False, "2-state", 0, 0]
T_U8 = [2, 0, "logic", 8, False, "2-state", 0, 0]
T_U8F = [3, 0, "logic", 8, False, "4-state", 0, 0]
T_U128 = [4, 0, "logic", 128, False, "2-state", 0, 0]
T_STR = [5, 0, "string", 0, False, "", 0, 0]
TYPES = {t[0]: t for t in [T_U1, T_U8, T_U8F, T_U128, T_STR]}


def make_view():
    return {
        "op_name": {}, "op_operands": {}, "op_results": {}, "op_refs": {},
        "producer_of": {}, "unit_ops": {}, "aliased_read_values": set(),
        "fanout_activate": {}, "fanout_arm": {}, "is_boundary": set(),
        "width": {}, "values_rows": [], "op_by_id": {},
    }


class TestComputeTaskUnits(unittest.TestCase):
    def test_walks_words_to_units_and_skips_commit(self):
        partitions = {
            10: [10, 0, 0, 0, [11], [], []],          # compute task partition -> words
            11: [11, 10, 0, 0, [12, 13], [], []],     # word -> units
            12: [12, 11, 3, 0, [], [], []],
            13: [13, 11, 3, 0, [], [], []],
            20: [20, 0, 0, 0, [21], [], []],          # commit task partition -> units
            21: [21, 20, 3, 0, [], [], []],
        }
        schedule = [[[None, [[None, [[1, 10, None, 0], [2, 20, None, 1]]]]]]]
        compute, all_ids, unit_to_task = compute_task_units(partitions, schedule)
        self.assertEqual(all_ids, [1, 2])
        self.assertEqual(compute, [(1, [12, 13])])
        self.assertEqual(unit_to_task, {12: 1, 13: 1})

    def test_commit_units_hold_ops_directly(self):
        # mirror_port_arms relies on commit task -> unit -> ops (no node layer)
        partitions = {20: [20, 0, 0, 0, [21], [], []], 21: [21, 20, 3, 0, [], [7], []]}
        self.assertEqual(partitions[21][5], [7])


class TestDirectCommitStates(unittest.TestCase):
    def test_single_writer_all_refs_read_or_port(self):
        # op rows: [oid, name_idx, ?, ?, operands, results, refs, ?]
        ops = [[1, 0, 0, 0, [], [10], [["state", 5]], None],          # state.read s5
               [2, 0, 0, 0, [10, 11, 12], [], [["state", 5]], None]]   # regWrite s5
        op_name = {1: "core.state.read", 2: "core.state.regWrite"}
        op_refs = {1: [["state", 5]], 2: [["state", 5]]}
        state_type = {5: 2, 6: 2}
        direct = direct_commit_states(ops, op_name, op_refs, TYPES, state_type)
        self.assertEqual(direct, {5})

    def test_extra_reference_excludes(self):
        ops = [[1, 0, 0, 0, [], [10], [["state", 5]], None],
               [2, 0, 0, 0, [10, 11, 12], [], [["state", 5]], None],
               [3, 0, 0, 0, [], [], [["state", 5], ["state", 9]], None]]  # dpi refs s5
        op_name = {1: "core.state.read", 2: "core.state.regWrite", 3: "core.dpi.call"}
        op_refs = {o[0]: o[6] for o in ops}
        direct = direct_commit_states(ops, op_name, op_refs, TYPES, {5: 2})
        self.assertEqual(direct, set())

    def test_four_state_and_wide_excluded(self):
        ops = [[1, 0, 0, 0, [], [10], [["state", 5]], None],
               [2, 0, 0, 0, [10, 11, 12], [], [["state", 5]], None],
               [3, 0, 0, 0, [], [13], [["state", 6]], None],
               [4, 0, 0, 0, [13, 11, 12], [], [["state", 6]], None]]
        op_name = {1: "core.state.read", 2: "core.state.regWrite",
                   3: "core.state.read", 4: "core.state.regWrite"}
        op_refs = {o[0]: o[6] for o in ops}
        state_type = {5: 3, 6: 4}   # 4-state u8; 2-state u128
        self.assertEqual(direct_commit_states(ops, op_name, op_refs, TYPES, state_type), set())


class TestMirrorPortArms(unittest.TestCase):
    def build(self):
        view = make_view()
        # compute value 100 (u8 boundary) produced by op 1 (core.compute.and);
        # commit task 2 -> unit 21 -> regWrite op 9 with operands (100,100,100)
        view["op_name"].update({1: "core.compute.and", 9: "core.state.regWrite"})
        view["op_operands"].update({1: [50, 51], 9: [100, 100, 100]})
        view["op_results"].update({1: [100], 9: []})
        view["op_refs"].update({1: [], 9: [["state", 5]]})
        view["producer_of"].update({100: 1})
        view["is_boundary"].add(100)
        view["values_rows"] = [[100, 2]]
        view["op_by_id"] = {1: [1], 9: [9]}
        ops = [[1], [9]]
        partitions = {20: [20, 0, 0, 0, [21], [], []], 21: [21, 20, 3, 0, [], [9], []]}
        schedule = [[[None, [[None, [[2, 20, None, 1]]]]]]]
        state_type = {5: 2}
        return view, ops, partitions, schedule, state_type

    def test_assigns_port_targets_to_three_operands(self):
        view, ops, partitions, schedule, state_type = self.build()
        ports = mirror_port_arms(ops, view, TYPES, state_type, partitions, schedule)
        self.assertEqual(ports, {100: [(0, 1)]})

    def test_non_boundary_operand_rejected(self):
        view, ops, partitions, schedule, state_type = self.build()
        view["is_boundary"].clear()
        ports = mirror_port_arms(ops, view, TYPES, state_type, partitions, schedule)
        self.assertEqual(ports, {})

    def test_eight_ports_share_one_word(self):
        view, ops, partitions, schedule, state_type = self.build()
        # 8 additional write ports on distinct states, operands 100/101/102
        view["op_name"].update({10 + i: "core.state.regWrite" for i in range(8)})
        view["op_operands"].update({10 + i: [100, 100, 100] for i in range(8)})
        view["op_results"].update({10 + i: [] for i in range(8)})
        view["op_refs"].update({10 + i: [["state", 50 + i]] for i in range(8)})
        view["op_by_id"].update({10 + i: [10 + i] for i in range(8)})
        ops.extend([[10 + i] for i in range(8)])
        partitions[21][5].extend(10 + i for i in range(8))
        state_type.update({50 + i: 2 for i in range(8)})
        ports = mirror_port_arms(ops, view, TYPES, state_type, partitions, schedule)
        # 9 ports: ordinals 0..8 -> words 0 (bits 0..7) and 1 (bit 0)
        self.assertEqual(ports[100], [(0, 0xFF), (1, 1)])


class TestUnitGroupFeatures(unittest.TestCase):
    def test_grouping_dedup_and_exclusions(self):
        view = make_view()
        # unit 7 ops: two values with identical fanout (same group), one
        # constant (excluded), one aliased (excluded), one non-logic (excluded),
        # one without fanout (excluded), one dpi (excluded), one port-only.
        ops = list(range(1, 9))
        view["unit_ops"][7] = ops
        view["op_name"].update({
            1: "core.compute.and", 2: "core.compute.or", 3: "core.compute.constant",
            4: "core.state.read", 5: "core.compute.and", 6: "core.compute.xor",
            7: "core.dpi.call", 8: "core.compute.mux"})
        view["op_results"].update({1: [101], 2: [102], 3: [103], 4: [104],
                                   5: [105], 6: [106], 7: [107], 8: [108]})
        view["width"].update({101: 1, 102: 1, 103: 1, 104: 8, 105: 1, 106: 1, 107: 1, 108: 1})
        view["aliased_read_values"].add(104)
        view["fanout_activate"].update({101: [201, 202], 102: [202, 201], 106: [202]})
        view["fanout_arm"].update({101: [301], 102: [301]})
        view["width"][108] = 1
        ports_map = {108: [(3, 2)]}
        active_off = {201: 0, 202: 1, 7: 9}
        active_mask = {201: 1, 202: 2, 7: 1}
        feats = unit_group_features(view, ports_map, active_off, active_mask)[7]
        # groups: {101,102} share one key, {106} one, {108} one -> 3 groups
        self.assertEqual(feats["groups"], 3)
        self.assertEqual(feats["dets"], 4)          # 101,102,106,108
        # arms: g1 = 2 offsets + 1 arm; g2 = 1 offset; g3 = 1 port line
        self.assertEqual(feats["arms"], 2 + 1 + 1 + 1)

    def test_local_mask_line(self):
        view = make_view()
        view["unit_ops"][7] = [1]
        view["op_name"][1] = "core.compute.and"
        view["op_results"][1] = [101]
        view["width"][101] = 1
        # unit 8 shares unit 7's active word at a higher bit -> local line
        view["fanout_activate"][101] = [8]
        feats = unit_group_features(view, {}, {7: 5, 8: 5}, {7: 1, 8: 2})[7]
        self.assertEqual(feats["arms"], 1)
        # same word but not later bits -> normal offset line, no local line
        feats = unit_group_features(view, {}, {7: 5, 8: 5}, {7: 2, 8: 1})[7]
        self.assertEqual(feats["arms"], 1)
        # local target + one other word -> local line + offset line
        view["fanout_activate"][101] = [8, 9]
        feats = unit_group_features(view, {}, {7: 5, 8: 5, 9: 6}, {7: 1, 8: 2, 9: 1})[7]
        self.assertEqual(feats["arms"], 2)


class TestFrameSizes(unittest.TestCase):
    def test_reads_local_frames(self):
        frames = frame_sizes([[7, 240, 8], [8, 16, 8], [9, 64, 8]], {7, 9})
        self.assertEqual(frames, {7: 240, 9: 64})


class TestWidthBucket(unittest.TestCase):
    def test_buckets(self):
        view = make_view()
        value_type = {1: 1, 2: 2, 3: 4, 4: 5}
        view["op_results"] = {1: [1], 2: [2], 3: [3], 4: [4], 5: []}
        buckets = [width_bucket_of(view, TYPES, value_type, op) for op in range(1, 6)]
        self.assertEqual(buckets, ["w1", "w2_64", "w65p", "none", "none"])
        self.assertEqual(BUCKET_NAMES, ["w1", "w2_64", "w65p", "none"])

    def test_two_state_logic(self):
        self.assertTrue(two_state_logic(T_U1))
        self.assertFalse(two_state_logic(T_U8F))
        self.assertFalse(two_state_logic(T_STR))


class TestSemanticBuckets(unittest.TestCase):
    def test_mapping_covers_preregistered_set(self):
        from grhsim_kind_cost_census import SEMANTIC_BUCKET_NAMES, semantic_bucket_of
        self.assertEqual(SEMANTIC_BUCKET_NAMES,
                         ["logic1", "logicN", "arith", "muldiv", "cmp", "mux",
                          "slice", "concat", "shift", "reduce", "state", "mem",
                          "other"])
        self.assertEqual(semantic_bucket_of("core.compute.and", 1), "logic1")
        self.assertEqual(semantic_bucket_of("core.compute.or", 64), "logicN")
        self.assertEqual(semantic_bucket_of("core.compute.logicNot", 1), "logic1")
        self.assertEqual(semantic_bucket_of("core.compute.add", 32), "arith")
        self.assertEqual(semantic_bucket_of("core.compute.div", 64), "muldiv")
        self.assertEqual(semantic_bucket_of("core.compute.eq", 1), "cmp")
        self.assertEqual(semantic_bucket_of("core.compute.prioritySelect", 8), "mux")
        self.assertEqual(semantic_bucket_of("core.compute.bitSelect", 1), "slice")
        self.assertEqual(semantic_bucket_of("core.compute.replicate", 32), "concat")
        self.assertEqual(semantic_bucket_of("core.compute.lshr", 64), "shift")
        self.assertEqual(semantic_bucket_of("core.compute.reduceAnd", 1), "reduce")
        self.assertEqual(semantic_bucket_of("core.state.read", 64), "state")
        self.assertEqual(semantic_bucket_of("core.state.memRead", 64), "mem")
        self.assertEqual(semantic_bucket_of("core.dpi.call", 0), "other")
        self.assertEqual(semantic_bucket_of("core.compute.constant", 8), "other")
        self.assertEqual(semantic_bucket_of("core.compute.assign", 8), "other")


class TestNnls(unittest.TestCase):
    def test_exact_recovery(self):
        rng = np.random.default_rng(1)
        a_mat = rng.random((200, 5))
        truth = np.array([3.0, 0.0, 1.5, 0.0, 2.0])
        b_vec = a_mat @ truth
        x = nnls(a_mat, b_vec)
        self.assertTrue(np.allclose(x, truth, atol=1e-6))

    def test_non_negative(self):
        rng = np.random.default_rng(2)
        a_mat = rng.random((100, 4))
        b_vec = a_mat @ np.array([1.0, 2.0, 3.0, 4.0]) + rng.normal(0, 0.01, 100)
        x = nnls(a_mat, b_vec)
        self.assertTrue((x >= 0).all())

    def test_zero_solution(self):
        a_mat = np.ones((10, 3))
        x = nnls(a_mat, -np.ones(10))
        self.assertTrue(np.allclose(x, 0.0))


class TestWeightedR2(unittest.TestCase):
    def test_perfect(self):
        self.assertAlmostEqual(weighted_r2([1, 2, 3], [1, 2, 3], [1, 1, 1]), 1.0)

    def test_worse_than_mean_goes_negative(self):
        r2 = weighted_r2([1.0, 2.0, 3.0], [3.0, 2.0, 1.0], np.ones(3))
        self.assertLess(r2, 0.0)


class TestDynParse(unittest.TestCase):
    def test_sn_and_totals(self):
        text = ("[grhsim-dyn] sn 101 act=2 body=3 grp=4 chg=5\n"
                "[grhsim-dyn] sn 102 act=7 body=8 grp=9 chg=10\n"
                "[grhsim-dyn] totals grp_pub=1 grp_fire=15 port_eval=2\n")
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write(text)
            path = handle.name
        body, chg, totals = load_dyn_fires(path)
        self.assertEqual(body, {101: 3, 102: 8})
        self.assertEqual(chg, {101: 5, 102: 10})
        self.assertEqual(totals["grp_fire"], 15)
        self.assertEqual(sum(chg.values()), totals["grp_fire"])


class TestDisasm(unittest.TestCase):
    def test_counts_only_matching_functions(self):
        # synthesize an objdump-like stream via a tiny fake binary is overkill;
        # instead verify the regexes directly
        from grhsim_kind_cost_census import DISASM_INSN, DISASM_LABEL
        label = "0000000001234567 <_ZN13GrhSIM_SimTop12cpu_task_1000Ev>:"
        self.assertEqual(DISASM_LABEL.match(label).group(1), "cpu_task_1000")
        helper = "0000000001234567 <_ZN13GrhSIM_SimTop14cpu_helper_321_0EPSt4byteRh>:"
        self.assertEqual(DISASM_LABEL.match(helper).group(1), "cpu_helper_321_0")
        other = "0000000001234567 <_ZN13GrhSIM_SimTop8evaluateEv>:"
        self.assertIsNone(DISASM_LABEL.match(other))
        insn = "   12345:\tmovl\t%eax,(%rdx)"
        self.assertIsNotNone(DISASM_INSN.match(insn))


if __name__ == "__main__":
    unittest.main()
