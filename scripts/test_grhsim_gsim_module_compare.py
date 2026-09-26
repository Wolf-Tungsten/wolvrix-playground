#!/usr/bin/env python3
"""Unit tests for grhsim_gsim_module_compare (NO00020)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grhsim_gsim_module_compare import (  # noqa: E402
    ANON_MODULE, BUCKET_ORDER, DEAD_MODULE, GRHSIM_KIND_BUCKETS, MIXED_MODULE,
    MODULE_KIND_SEP, assemble_cone, assemble_kinddelta, assemble_opcount,
    bucket_of_grhsim_kind, bucket_of_gsim_op, check_grhsim_counts,
    diff_checkpoints, distribution, grhsim_cone_size, is_generated_value_name,
    match_anchor_sets, match_report, merge_owners, module_of_path,
    module_of_state_name, normalize_name, op_kind_counter, percentile,
    propagate_value_owners, strip_chunk_suffix, strip_mem_wrapper,
)
from compare_ir_shapes import GSIM_OP_BUCKETS  # noqa: E402


class TestNormalization(unittest.TestCase):
    def test_dot_and_dollar_collapse(self):
        self.assertEqual(
            normalize_name("endpoint__DOT__bundle_delayed_delayer_25__DOT__REG__DOT__data_63"),
            "endpoint_bundle_delayed_delayer_25_REG_data_63")
        self.assertEqual(
            normalize_name("endpoint$bundle_delayed_delayer_25$REG_data_63"),
            "endpoint_bundle_delayed_delayer_25_REG_data_63")
        self.assertEqual(normalize_name("a__DOT__b$c__DOT__d"), "a_b_c_d")

    def test_strip_chunk_suffix(self):
        self.assertEqual(strip_chunk_suffix("a_b_63"), "a_b")
        self.assertIsNone(strip_chunk_suffix("a_b"))
        self.assertIsNone(strip_chunk_suffix("63"))

    def test_module_of_path(self):
        self.assertEqual(module_of_path("a__DOT__b__DOT__c", "__DOT__"), "a_b")
        self.assertEqual(module_of_path("a$b$c", "$"), "a_b")
        self.assertEqual(module_of_path("clock", "$"), "(top)")

    def test_generated_value_names(self):
        self.assertTrue(is_generated_value_name(""))
        self.assertTrue(is_generated_value_name("_val_13"))
        self.assertTrue(is_generated_value_name("packed_bits_3601835"))
        self.assertTrue(is_generated_value_name("_op_13.local1.0"))
        self.assertFalse(is_generated_value_name("cpu$l_soc$foo"))
        self.assertFalse(is_generated_value_name("clock"))
        self.assertFalse(is_generated_value_name("_val_13x"))
        self.assertFalse(is_generated_value_name("_opx_1"))

    def test_strip_mem_wrapper(self):
        self.assertEqual(strip_mem_wrapper("cpu$ram_ext$Memory"), "cpu$ram")
        self.assertEqual(strip_mem_wrapper("a$b$array_0_ext$Memory"),
                         "a$b$array_0")
        self.assertEqual(strip_mem_wrapper("cpu$ram"), "cpu$ram")
        self.assertEqual(strip_mem_wrapper("cpu$Memory"), "cpu$Memory")

    def test_module_of_state_name(self):
        self.assertEqual(module_of_state_name("cpu$l_soc$foo"),
                         "cpu_l_soc")
        self.assertEqual(module_of_state_name("__event_12_0"), "(events)")
        self.assertEqual(module_of_state_name("packed_bits_215914"),
                         "(packed)")
        self.assertEqual(module_of_state_name("__reg_to_mem_250614"),
                         "(reg-to-mem)")
        self.assertEqual(module_of_state_name("packed_bits_x"), "(top)")
        self.assertEqual(module_of_state_name("clock"), "(top)")


class TestAnchorMatching(unittest.TestCase):
    def test_exact_and_chunk_strip(self):
        gsim = [("top__DOT__m__DOT__reg_a", 8),
                ("top__DOT__m__DOT__wide_0", 64),
                ("top__DOT__m__DOT__wide_1", 36),
                ("top__DOT__m__DOT__gone", 4)]
        grh = [("top$m$reg_a", 8),
               ("top$m$wide", 100),
               ("top$m$extra", 2)]
        groups, un_g, un_r = match_anchor_sets(gsim, grh)
        kinds = {g["key"]: g["kind"] for g in groups}
        self.assertEqual(kinds.get("top_m_reg_a"), "exact")
        self.assertEqual(kinds.get("top_m_wide"), "chunk_strip")
        wide = next(g for g in groups if g["key"] == "top_m_wide")
        self.assertEqual(len(wide["gsim"]), 2)
        self.assertEqual(len(wide["grhsim"]), 1)
        self.assertEqual([k for k in un_g], ["top_m_gone"])
        self.assertEqual([k for k in un_r], ["top_m_extra"])

    def test_chunk_strip_symmetric_grhsim_split(self):
        gsim = [("m__DOT__bar", 32)]
        grh = [("m$bar_0", 16), ("m$bar_1", 16)]
        groups, un_g, un_r = match_anchor_sets(gsim, grh)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["kind"], "chunk_strip")
        self.assertFalse(un_g)
        self.assertFalse(un_r)

    def test_match_report_bit_weighting(self):
        groups = [{"key": "a", "kind": "exact",
                   "gsim": [("a", 8)], "grhsim": [("a", 8)]},
                  {"key": "w", "kind": "chunk_strip",
                   "gsim": [("w_0", 64), ("w_1", 36)], "grhsim": [("w", 100)]}]
        report = match_report(groups, {"z": [("z", 4)]}, {"_RANDOM": [("_RANDOM", 1)]},
                              8 + 100 + 4, 8 + 100 + 1)
        self.assertEqual(report["matched"]["gsimBits"], 108)
        self.assertEqual(report["matched"]["grhsimBits"], 108)
        self.assertAlmostEqual(report["coverage"]["gsimBits"], 108 / 112)
        self.assertAlmostEqual(report["coverage"]["grhsimBits"], 108 / 109)
        self.assertIn("firtool_randomize_artifact", report["unmatched"]["grhsim"])


class TestBuckets(unittest.TestCase):
    def test_grhsim_mapping_targets_known_taxonomy(self):
        for kind, bucket in GRHSIM_KIND_BUCKETS.items():
            self.assertIn(bucket, BUCKET_ORDER, kind)

    def test_gsim_mapping_targets_known_taxonomy(self):
        for op, bucket in GSIM_OP_BUCKETS.items():
            self.assertIn(bucket, BUCKET_ORDER, op)
        self.assertEqual(bucket_of_gsim_op("OP_EMPTY"), "node_ref")
        self.assertEqual(bucket_of_gsim_op("OP_SOMETHING_NEW"), "other")

    def test_grhsim_kind_examples(self):
        self.assertEqual(bucket_of_grhsim_kind("core.compute.and"), "bitwise_logic")
        self.assertEqual(bucket_of_grhsim_kind("core.compute.mux"), "mux_control")
        self.assertEqual(bucket_of_grhsim_kind("core.compute.prioritySelect"), "mux_control")
        self.assertEqual(bucket_of_grhsim_kind("core.state.regWrite"), "state_reg_access")
        self.assertEqual(bucket_of_grhsim_kind("core.state.memWriteSeq"), "memory")
        self.assertEqual(bucket_of_grhsim_kind("core.input.read"), "io")
        self.assertEqual(bucket_of_grhsim_kind("core.unknown.op"), "other")


class TestCone(unittest.TestCase):
    def test_cone_counts_distinct_ops_and_truncates(self):
        # value ids: 1 named boundary; 2,3 unnamed; 4 const leaf
        producer_of = {2: 10, 3: 11, 4: 12}
        op_operands = [None] * 13
        op_operands[10] = [1, 3]
        op_operands[11] = [3, 4]   # shared subcone via 3's producer
        op_operands[12] = []
        boundary = lambda vid: vid == 1  # noqa: E731
        # cone of value 2: ops {10, 11} (12 shared under 11 counted once when
        # reached through both 10 and 11), boundary leaves 1, const op 12.
        cone, leaves = grhsim_cone_size(2, producer_of, op_operands, boundary)
        self.assertEqual(cone, 3)      # ops 10, 11, 12
        self.assertEqual(leaves, 1)    # the named boundary value 1
        # boundary start value itself: no ops, one leaf
        cone, leaves = grhsim_cone_size(1, producer_of, op_operands, boundary)
        self.assertEqual((cone, leaves), (0, 1))

    def test_distribution_percentiles(self):
        self.assertEqual(percentile([1, 2, 3, 4], 50), 2)
        self.assertEqual(percentile([1, 2, 3, 4], 90), 4)
        dist = distribution([2, 1, 3])
        self.assertEqual(dist["median"], 2)
        self.assertEqual(dist["min"], 1)
        self.assertEqual(dist["max"], 3)
        self.assertAlmostEqual(dist["mean"], 2.0)
        self.assertEqual(distribution([]), {"n": 0})


class TestOwnerPropagation(unittest.TestCase):
    def test_named_chain_mixed_dead(self):
        # values: 1 named (modA), 2 unnamed -> consumed by op1 producing 1
        #         3 unnamed -> consumed by op2 producing named 4 (modA) and
        #                       op3 producing named 5 (modB) -> mixed
        #         6 unnamed, no consumers -> dead
        n_values = 6
        named = {1: "modA", 4: "modA", 5: "modB"}
        consumers = {2: [1], 3: [2, 3]}
        results = {1: [1], 2: [4], 3: [5]}
        owner = propagate_value_owners(
            n_values,
            lambda vid: named.get(vid),
            lambda vid: consumers.get(vid, ()),
            lambda pos: results.get(pos, ()))
        self.assertEqual(owner[1], "modA")
        self.assertEqual(owner[2], "modA")
        self.assertEqual(owner[3], MIXED_MODULE)
        self.assertEqual(owner[6], DEAD_MODULE)

    def test_merge_owners(self):
        self.assertEqual(merge_owners("", "a"), "a")
        self.assertEqual(merge_owners("a", "a"), "a")
        self.assertEqual(merge_owners("a", "b"), MIXED_MODULE)
        self.assertEqual(merge_owners(DEAD_MODULE, "a"), "a")
        self.assertEqual(merge_owners("a", DEAD_MODULE), "a")
        self.assertEqual(merge_owners(DEAD_MODULE, DEAD_MODULE), DEAD_MODULE)

    def test_sink_owner_from_state_write(self):
        # value 2 unnamed -> consumed by op1 (no results, a regWrite sink in
        # modSink): 2 inherits the written state's module.
        # value 3 unnamed -> consumed by op2 (no results, printf-like sink
        # returning None): 3 stays dead.
        n_values = 3
        consumers = {2: [1], 3: [2]}
        sinks = {1: "modSink", 2: None}
        owner = propagate_value_owners(
            n_values,
            lambda vid: None,
            lambda vid: consumers.get(vid, ()),
            lambda pos: (),
            sink_module_of=lambda pos: sinks.get(pos))
        self.assertEqual(owner[2], "modSink")
        self.assertEqual(owner[3], DEAD_MODULE)

    def test_sink_owner_merges_with_result_consumers(self):
        # value 2 unnamed -> consumed by op1 producing named 1 (modA) and by
        # regWrite sink op2 in modB: merged owner is mixed.
        n_values = 2
        named = {1: "modA"}
        consumers = {2: [1, 2]}
        results = {1: [1]}
        sinks = {2: "modB"}
        owner = propagate_value_owners(
            n_values,
            lambda vid: named.get(vid),
            lambda vid: consumers.get(vid, ()),
            lambda pos: results.get(pos, ()),
            sink_module_of=lambda pos: sinks.get(pos))
        self.assertEqual(owner[2], MIXED_MODULE)


class TestGrhsimCountsGate(unittest.TestCase):
    def tiny_model(self):
        return {
            "counts": {"strings": 2, "dialects": 1, "types": 1, "origins": 1,
                       "inputs": 1, "outputs": 1, "states": 1, "functions": 0,
                       "interface_ports": 0, "values": 2, "operations": 2,
                       "operands": 3, "results": 2, "object_refs": 1,
                       "mappings": 0},
            "strings": ["a", "b"],
            "dialects": [[1, 2, 3]],
            "types": [[1, 1, "logic", 8, False, "2-state", 0, 0]],
            "origins": [[1, 1, 1, 0, 1, 1, 1, 0, 0, 0, 0]],
            "inputs": [[1, 1, 1, 1]],
            "outputs": [[1, 2, 1, 1]],
            "states": [[1, 1, 1, 1]],
            "functions": [],
            "interface": [],
            "values": [[1, 1, 1, 1], [2, 1, 2, 1]],
            "operations": [[1, 1, 1, 1, [1, 2], [1], [], []],
                           [2, 1, 1, 1, [1], [2], [["state", 1]], []]],
            "init": [],
            "mappings": [],
        }

    def test_counts_ok(self):
        ok, checks = check_grhsim_counts(self.tiny_model())
        self.assertTrue(ok, checks)

    def test_counts_mismatch_detected(self):
        model = self.tiny_model()
        model["counts"]["values"] = 5
        model["counts"]["operands"] = 99
        ok, checks = check_grhsim_counts(model)
        self.assertFalse(ok)
        self.assertFalse(checks["values"]["ok"])
        self.assertFalse(checks["operands"]["ok"])
        self.assertTrue(checks["operations"]["ok"])

    def test_op_kind_counter(self):
        model = self.tiny_model()
        counter = op_kind_counter(model)
        self.assertEqual(counter, {"a": 2})


class TestDiffCheckpoints(unittest.TestCase):
    def base(self):
        return {
            "counts": {"strings": 2},
            "strings": ["a", "b"],
            "types": [[1, 1, "logic", 8, False, "2-state", 0, 0]],
            "origins": [[1, 1, 1, 0, 1, 1, 1, 0, 0, 0, 0]],
            "inputs": [], "outputs": [],
            "states": [[1, 1, 1, 1]],
            "functions": [], "interface": [],
            "values": [[1, 1, 1, 1]],
            "operations": [[1, 1, 1, 1, [1], [1], [], []]],
            "init": [], "mappings": [],
        }

    def test_identical(self):
        report = diff_checkpoints(self.base(), self.base())
        self.assertEqual(report["classification"], "identical_payload")
        self.assertEqual(report["differingArrays"], [])

    def test_string_drift_classified(self):
        other = self.base()
        other["strings"] = ["a", "c"]
        other["values"] = [[1, 1, 2, 1]]   # name idx shift: unreliable downstream
        report = diff_checkpoints(self.base(), other)
        self.assertEqual(report["classification"], "string_table_content_drift")
        self.assertIn("strings", report["differingArrays"])

    def test_origin_only_drift_classified(self):
        other = self.base()
        other["origins"] = [[1, 1, 1, 0, 1, 9, 9, 0, 0, 0, 0]]
        other["operations"] = [[1, 1, 1, 7, [1], [1], [], []]]  # only origin id
        other["values"] = [[1, 1, 1, 7]]
        other["states"] = [[1, 1, 1, 7]]
        report = diff_checkpoints(self.base(), other)
        self.assertEqual(report["classification"], "origin_or_string_embedding_only")
        self.assertEqual(report["nonOriginDiffRows"]["operations"], 0)

    def test_structural_drift_classified(self):
        other = self.base()
        other["operations"] = [[1, 1, 1, 1, [1, 1], [1], [], []]]  # operand change
        report = diff_checkpoints(self.base(), other)
        self.assertEqual(report["classification"], "structural_payload_drift")
        self.assertEqual(report["nonOriginDiffRows"]["operations"], 1)


class TestAssembly(unittest.TestCase):
    def test_opcount_closure(self):
        gsim = {"moduleNodeCounts": {"m": 3}, "moduleEnodeCounts": {"m": 10},
                "nodeCount": 3, "totalEnodes": 10}
        grh = {"moduleOpCounts": {"m": 4}, "moduleValueCounts": {"m": 6},
               "totalOps": 4, "totalValues": 6}
        out = assemble_opcount(gsim, grh, 5)
        self.assertTrue(out["closureOk"])
        row = out["topByAbsDelta"][0]
        self.assertEqual(row["gsimEnodes"], 10)
        self.assertEqual(row["grhsimOps"], 4)
        self.assertEqual(row["opDelta"], -6)

    def test_kinddelta_excess_order(self):
        gsim = {"globalOpCounts": {"OP_ADD": 2, "OP_EMPTY": 5},
                "moduleOpCounts": {("m", "OP_ADD"): 2, ("m", "OP_EMPTY"): 5}}
        grh = {"globalKindCounts": {"core.compute.add": 3, "core.compute.and": 4},
               "moduleKindCounts": {"m" + MODULE_KIND_SEP + "core.compute.add": 3,
                                    "m" + MODULE_KIND_SEP + "core.compute.and": 4}}
        out = assemble_kinddelta(gsim, grh, 5)
        table = {row["bucket"]: row for row in out["global"]}
        self.assertEqual(table["arithmetic"]["grhsimMinusGsim"], 1)
        self.assertEqual(table["bitwise_logic"]["grhsimMinusGsim"], 4)
        self.assertEqual(table["node_ref"]["grhsimMinusGsim"], -5)
        self.assertEqual(out["excessOrder"][0]["bucket"], "bitwise_logic")
        self.assertEqual(out["topModules"][0]["module"], "m")

    def test_cone_assembly(self):
        groups = [{"key": "a", "kind": "exact",
                   "gsim": [("g_a", 8)], "grhsim": [("r_a", 8)]},
                  {"key": "b", "kind": "exact",
                   "gsim": [("g_b", 8)], "grhsim": [("r_b", 8)]}]
        gsim_cones = {"g_a": 10, "g_b": 4}
        grh_cones = {"r_a": (20, 3), "r_b": (2, 1)}
        out = assemble_cone(groups, gsim_cones, grh_cones, 5)
        self.assertEqual(out["pairs"], 2)
        self.assertEqual(out["gsimConeSize"]["max"], 10)
        self.assertEqual(out["outliers"][0]["key"], "a")
        self.assertEqual(out["outliers"][0]["grhsimCone"], 20)


if __name__ == "__main__":
    unittest.main()
