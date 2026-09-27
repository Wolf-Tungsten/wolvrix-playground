"""Small independent cone graphs and malformed-input coverage for NO00023."""

from collections import Counter
from pathlib import Path
import tempfile
import unittest

from grhsim_residual_write_cones import (
    analyze, checked_fires, cone, family_key, fingerprint, gsim_registers,
    inspect_gsim_references, match_register, source_fingerprints, tree_summary, unit_index,
)


def tree():
    # The final node is a serialized lvalue, not part of the RHS.
    return {"root": 0, "lvalue": 3, "nodes": [
        {"op": "OP_MUX", "children": [1, 2]},
        {"op": "OP_EMPTY", "node": "a", "children": []},
        {"op": "OP_INT", "children": []},
        {"op": "OP_EMPTY", "node": "q", "children": []},
    ]}


def model():
    strings = ["core.state.read", "core.compute.and", "core.state.regWrite",
               "dut$bank_0", "dut$bank_1", "core.input.read"]
    ops = [
        [1, 1, 0, 0, [], [1], [["state", 1]]],
        [2, 6, 0, 0, [], [2], [["input", 1]]],
        [3, 2, 0, 0, [1, 2], [3], []],  # row 0 private
        [4, 2, 0, 0, [2, 2], [4], []],  # row 1 private
        [5, 3, 0, 0, [2, 3], [], [["state", 1]]],
        [6, 3, 0, 0, [2, 4], [], [["state", 2]]],
    ]
    return {"strings": strings, "types": [[1, 0, "logic", 8]],
            "states": [[1, 4, 1], [2, 5, 1]],
            "values": [[i, 1, 0] for i in range(1, 5)], "operations": ops,
            "mappings": [[[0, 0, [[100, 0, 3, 0, [], [1, 2, 3, 4]],
                                   [200, 0, 3, 0, [], [5, 6]],
                                   [10, 0, 6, 0, [11], []],
                                   [11, 10, 5, 0, [100], []]], [],
                            [[[None, [[None, [[1, 10, None, 0], [2, 200, None, 1]]]]]]]]]],
            "inputs": [], "outputs": []}


def sources():
    return {f"dut_bank_{i}": [{"name": f"dut__DOT__bank_{i}", "width": 8,
                               "dst": f"q{i}", "tree": tree_summary([tree()])}]
            for i in range(2)}


class ResidualConesTest(unittest.TestCase):
    def test_family_uses_full_path_and_width(self):
        self.assertEqual(family_key("x$bank_12", 8), ("x$bank", 8))
        self.assertNotEqual(family_key("x$bank_12", 8), family_key("y$bank_12", 8))
        self.assertIsNone(family_key("x$bank", 8))

    def test_generated_states_are_excluded(self):
        for name in ("__event_10_0", "packed_bits_5", "__reg_to_mem_22"):
            self.assertIsNone(family_key(name, 8))

    def test_full_cone_deduplicates_dag(self):
        m = model()
        ops = {op[0]: op for op in m["operations"]}
        prod = {v: op[0] for op in ops.values() for v in op[5]}
        kinds = {oid: m["strings"][op[1] - 1] for oid, op in ops.items()}
        self.assertEqual(cone([4], prod, ops, kinds), ({2, 4}, 0))
        self.assertEqual(cone([4], prod, ops, kinds, {}), ({4}, 2))
        self.assertEqual(cone([4], prod, ops, kinds, {4: "named"}), (set(), 1))

    def test_memread_stops_before_address(self):
        ops = {1: [1, 0, 0, 0, [9], [1]], 2: [2, 0, 0, 0, [], [9]]}
        self.assertEqual(cone([1], {1: 1, 9: 2}, ops,
                              {1: "core.state.memRead", 2: "core.compute.constant"}), ({1}, 0))

    def test_missing_producer_fails(self):
        with self.assertRaisesRegex(ValueError, "no producer"):
            cone([1], {}, {}, {})

    def test_tree_excludes_lvalue_for_rhs_metric(self):
        result = tree_summary([tree()])
        self.assertEqual((result["stored_enodes"], result["rhs_enodes"],
                          result["nonleaf_enodes"]), (4, 3, 1))
        self.assertEqual(result["refs"], ["a"])

    def test_invalid_tree_reference_fails(self):
        t = tree()
        t["nodes"][0]["children"].append(99)
        with self.assertRaisesRegex(ValueError, "tree reference"):
            tree_summary([t])

    def test_register_dst_resolution(self):
        payload = {"nodes": [
            {"name": "dut__DOT__bank_0", "type": "NODE_REG_SRC", "width": 8,
             "assignTrees": [{"root": 0, "nodes": [{"node": "q0"}]}]},
            {"name": "q0", "type": "NODE_REG_DST", "assignTrees": [tree()]},
        ]}
        result = gsim_registers(payload)
        self.assertEqual(result["dut_bank_0"][0]["tree"]["rhs_enodes"], 3)

    def test_named_reference_expansion_and_missing_reference(self):
        payload = {"nodes": [
            {"name": "data", "type": "NODE_OTHERS", "width": 8,
             "assignTrees": [{"root": 0, "nodes": [{"op": "OP_EMPTY", "node": "input"}]}]},
            {"name": "input", "type": "NODE_INP", "width": 8, "assignTrees": []},
        ]}
        report = {"analysis": {"inflated_top5": [{"family": "f"}], "families": [
            {"family": "f", "samples": [{"name": "r", "gsim": {"tree": {"refs": ["data"]}}}]}]}}
        result = inspect_gsim_references(payload, report)
        self.assertEqual(result[0]["second_layer"][0]["name"], "input")
        payload["nodes"].pop()
        with self.assertRaisesRegex(ValueError, "missing gsim"):
            inspect_gsim_references(payload, report)

    def test_exact_matching_rejects_width_and_ambiguity(self):
        src = sources()
        counts = Counter({"dut_bank_0": 1})
        self.assertEqual(match_register("dut$bank_0", 8, src, counts)[1], "matched")
        self.assertEqual(match_register("dut$bank_0", 7, src, counts)[1], "width_mismatch")
        counts["dut_bank_0"] = 2
        self.assertEqual(match_register("dut$bank_0", 8, src, counts)[1], "ambiguous_name")
        counts["dut_bank_0"] = 1
        src["dut_bank_0"].append(src["dut_bank_0"][0])
        self.assertEqual(match_register("dut$bank_0", 8, src, counts)[1], "ambiguous_name")

    def test_matching_never_strips_row_suffix(self):
        self.assertEqual(match_register("dut$bank_9", 8, sources(),
                                       Counter({"dut_bank_9": 1}))[1], "no_exact_name")

    def test_missing_dst_rejected(self):
        src = sources()
        src["dut_bank_0"][0]["tree"] = None
        self.assertEqual(match_register("dut$bank_0", 8, src,
                                       Counter({"dut_bank_0": 1}))[1], "missing_update_tree")

    def test_family_accounting_and_matching(self):
        result = analyze(model(), sources(), {100: 10}, 5, min_rows=2)
        row = result["families"][0]
        self.assertEqual((row["full_ops"], row["private_ops"], row["shared_ops"]), (4, 3, 1))
        self.assertEqual((row["full_execs"], row["private_execs"], row["shared_execs"]), (40, 30, 10))
        self.assertEqual(result["coverage"]["matched_bits"], 16)
        self.assertEqual(row["matched_grhsim_local_size"], 6)
        self.assertEqual(row["local_ratio_stored"], 0.75)

    def test_unmatched_rows_still_priced(self):
        result = analyze(model(), {}, {100: 10}, 5, min_rows=2)
        self.assertEqual(result["union_execs"], 40)
        self.assertEqual(result["coverage"]["reason_no_exact_name"], 2)

    def test_event_history_is_not_write_destination(self):
        m = model()
        m["operations"][4][6].append(["state", 999])
        result = analyze(m, sources(), {100: 10}, 5, min_rows=2)
        self.assertEqual(result["families"][0]["writer_counts"], {"1": 2})

    def test_global_union_does_not_sum_overlapping_families(self):
        m = model()
        m["strings"] += ["dut$other_0", "dut$other_1"]
        m["states"] += [[3, 7, 1], [4, 8, 1]]
        m["operations"] += [[7, 3, 0, 0, [2, 3], [], [["state", 3]]],
                             [8, 3, 0, 0, [2, 4], [], [["state", 4]]]]
        result = analyze(m, sources(), {100: 10}, 5, min_rows=2)
        self.assertEqual(result["sum_family_execs_with_overlap"], 80)
        self.assertEqual(result["union_execs"], 40)

    def test_no_writer_is_reported(self):
        m = model()
        m["operations"].pop()
        result = analyze(m, sources(), {100: 10}, 5, min_rows=2)
        self.assertEqual(result["coverage"]["reason_no_grhsim_writer"], 1)

    def test_missing_or_orphan_counter_fails(self):
        for counts in ({}, {100: 10, 101: 0}):
            with self.assertRaisesRegex(ValueError, "coverage mismatch"):
                analyze(model(), sources(), counts, 5, min_rows=2)

    def test_invalid_normalization_fails(self):
        with self.assertRaisesRegex(ValueError, "cycles must"):
            analyze(model(), sources(), {100: 10}, 0, min_rows=2)

    def test_unmapped_cone_fails(self):
        m = model()
        m["mappings"][0][-1][2][0][5].remove(1)
        with self.assertRaisesRegex(ValueError, "lack body counters"):
            analyze(m, sources(), {100: 10}, 5, min_rows=2)

    def test_duplicate_owner_fails(self):
        m = model()
        m["mappings"][0][-1][2].append([101, 0, 3, 0, [], [1]])
        m["mappings"][0][-1][2][3][4].append(101)
        with self.assertRaisesRegex(ValueError, "multiple compute owners"):
            unit_index(m)

    def test_commit_supernodes_are_not_compute(self):
        units, owners = unit_index(model())
        self.assertEqual(units, {100})
        self.assertNotIn(5, owners)

    def test_fingerprint_checks_names(self):
        m, other = model(), model()
        other["strings"][3] = "different"
        self.assertNotEqual(fingerprint(m, "strings"), fingerprint(other, "strings"))

    def test_generated_source_identity_includes_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            with self.assertRaisesRegex(ValueError, "empty"):
                source_fingerprints(path)
            (path / "model.cpp").write_text("a")
            first = source_fingerprints(path)
            (path / "extra.h").write_text("b")
            self.assertNotEqual(first, source_fingerprints(path))

    def test_counter_duplicates_and_endpoint_validation(self):
        log = ("Difftest enabled\ninstrCnt = 240349, cycleCnt = 99996\n"
               "Guest cycle spent: 100001\nHost time spent: 50000ms\n"
               "EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80000c0c\n"
               "cycles=100000 max_cycles=100000\n"
               "[grhsim-dyn] sn 100 act=10 body=10 grp=0 chg=0\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.log"
            path.write_text(log)
            self.assertEqual(checked_fires(path), ({100: 10}, 100001))
            path.write_text(log.replace("240349", "240,349").replace("100001", "100,001"))
            self.assertEqual(checked_fires(path), ({100: 10}, 100001))
            path.write_text(log + "[grhsim-dyn] sn 100 act=10 body=10 grp=0 chg=0\n")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                checked_fires(path)
            path.write_text(log.replace("240349", "240350"))
            with self.assertRaisesRegex(ValueError, "endpoint"):
                checked_fires(path)


if __name__ == "__main__":
    unittest.main()
