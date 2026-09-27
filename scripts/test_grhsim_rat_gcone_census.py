#!/usr/bin/env python3
"""Unit tests for grhsim_rat_gcone_census (NO00022)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grhsim_rat_gcone_census import (  # noqa: E402
    build_op_index,
    build_unit_of_op,
    collect_families,
    load_body_fires,
    main,
    measure_families,
    parse_state_family,
    price_ops,
    replacement_memories,
    row_write_cone,
    split_row_fanout,
)

STRINGS = [
    "core.compute.constant",          # 1
    "core.compute.and",               # 2
    "core.state.regWrite",            # 3
    "core.state.read",                # 4
    "core.compute.mux",               # 5
    "core.compute.eq",                # 6
    "dut$fpRat$arch_table_0",         # 7
    "dut$fpRat$arch_table_1",         # 8
    "dut$vecRat$difftest_table_0",    # 9
    "dut$fpRat$spec_table_0",         # 10
]

TARGETS = ["fpRat/arch_table", "vecRat/difftest_table"]


def make_model():
    return {
        "strings": STRINGS,
        "types": [[1, 0, "logic", 1, 0, "2-state", 0, 0]],
        "states": [
            [1, 7, 1],   # dut$fpRat$arch_table_0
            [2, 8, 1],   # dut$fpRat$arch_table_1
            [3, 9, 1],   # dut$vecRat$difftest_table_0
            [4, 10, 1],  # dut$fpRat$spec_table_0 (not a target family)
        ],
        "values": [[vid, 1, 0] for vid in range(1, 12)],
        "operations": [
            [1, 1, 0, 0, [], [1], []],                    # const -> v1
            [2, 2, 0, 0, [1, 1], [2], []],                # and(v1,v1) -> v2 (shared)
            [3, 2, 0, 0, [2, 1], [3], []],                # and(v2,v1) -> v3 (row0 private)
            [4, 2, 0, 0, [2, 1], [4], []],                # and(v2,v1) -> v4 (row1 private)
            [5, 3, 0, 0, [1, 3], [], [["state", 1]]],     # regWrite state1 data=v3
            [6, 3, 0, 0, [1, 4], [], [["state", 2]]],     # regWrite state2 data=v4
            [7, 1, 0, 0, [], [9], []],                    # const -> v9
            [8, 3, 0, 0, [1, 9], [], [["state", 3]]],     # regWrite state3 data=v9
            [9, 4, 0, 0, [], [5], [["state", 1]]],        # read state1 -> v5
            [10, 4, 0, 0, [], [6], [["state", 2]]],       # read state2 -> v6
            [11, 4, 0, 0, [], [7], [["state", 3]]],       # read state3 -> v7
            [12, 5, 0, 0, [5, 1, 1], [10], []],           # mux consumer of v5
            [13, 6, 0, 0, [6, 1], [11], []],              # eq consumer of v6
            [14, 3, 0, 0, [1, 1], [], [["state", 4]]],    # regWrite state4 (spec_table)
        ],
        "inputs": [],
        "outputs": [],
        "mappings": [[
            [0, 0,
             [  # partitions [id, ?, kind, ?, children, ops]
                 [100, 0, 3, 0, [], [1, 2, 3, 4]],
                 [101, 0, 3, 0, [110], []],
                 [110, 0, 0, 0, [], [7]],
                 [200, 0, 4, 0, [], [5, 6, 8]],  # commit-domain: not a compute unit
             ],
             [],
             []],
        ]],
    }


BODY = {100: 10, 101: 4}


class TestParseStateFamily(unittest.TestCase):
    def test_matches(self):
        self.assertEqual(parse_state_family("dut$fpRat$arch_table_3"),
                         ("fpRat", "arch_table", 3))
        self.assertEqual(parse_state_family("x$vecRat$difftest_table_30"),
                         ("vecRat", "difftest_table", 30))

    def test_rejects(self):
        self.assertIsNone(parse_state_family("dut$fpRat$arch_table"))
        self.assertIsNone(parse_state_family("__reg_to_mem_120118"))
        self.assertIsNone(parse_state_family("dut$fpRat$arch_table_1_extra"))


class TestConeAndFanout(unittest.TestCase):
    def setUp(self):
        self.aux = build_op_index(make_model())

    def test_row_write_cone_full_backward(self):
        cone = row_write_cone(3, self.aux["producer_of"], self.aux["op_operands"])
        self.assertEqual(cone, {1, 2, 3})

    def test_split_row_fanout(self):
        private, shared = split_row_fanout([{1, 2, 3}, {1, 2, 4}])
        self.assertEqual(private, {3, 4})
        self.assertEqual(shared, {1, 2})

    def test_price_ops(self):
        unit_of_op = build_unit_of_op(make_model())
        execs, unmapped = price_ops({3, 4, 7}, unit_of_op, BODY)
        self.assertEqual(execs, 10 + 10 + 4)
        self.assertEqual(unmapped, [])
        execs, unmapped = price_ops({5}, unit_of_op, BODY)
        self.assertEqual(execs, 0)
        self.assertEqual(unmapped, [5])
        self.assertEqual(price_ops({7}, unit_of_op, {100: 10}), (0, [7]))


class TestReplacementMemories(unittest.TestCase):
    def test_origin_identifies_renamed_array_and_prices_real_cone(self):
        model = make_model()
        model["strings"] = list(STRINGS) + ["__reg_to_mem_1", "core.state.memWriteSeq",
                                             "core.state.memRead"]
        model["types"].append([2, 0, "array", 0, 0, "2-state", 1, 2])
        model["origins"] = [[1, 0, 7, 0, 0, 0, 0, 0, 0, 0, 0]]
        model["states"] = [[5, 11, 2, 1]]
        model["operations"] = model["operations"][:4] + [
            [15, 12, 0, 0, [1, 1, 3, 1, 1, 4, 1], [], [["state", 5], ["state", 6]]],
            [16, 13, 0, 0, [1], [5], [["state", 5]]],
        ]
        aux = build_op_index(model)
        result, failures = replacement_memories(model, aux, build_unit_of_op(model), BODY,
                                                {"fpRat/arch_table": 2})
        self.assertEqual(failures, {})
        row = result["families"]["fpRat/arch_table"][0]
        self.assertEqual(row["name"], "__reg_to_mem_1")
        self.assertEqual(row["sequence_triples"], 2)
        self.assertEqual(row["mem_reads"], 1)
        self.assertEqual(result["whole_cone_execs"], 40)
        _, failures = replacement_memories(model, aux, build_unit_of_op(model), BODY,
                                          {"fpRat/arch_table": 3})
        self.assertIn("fpRat/arch_table", failures)

    def test_missing_replacement_fails_even_when_scalar_names_are_absent(self):
        model = make_model()
        result, failures = replacement_memories(model, build_op_index(model),
                                                build_unit_of_op(model), BODY,
                                                {"fpRat/arch_table": 2})
        self.assertEqual(result["whole_cone_ops"], 0)
        self.assertEqual(failures, {"fpRat/arch_table": []})


class TestMeasureFamilies(unittest.TestCase):
    def test_measure(self):
        model = make_model()
        aux = build_op_index(model)
        unit_of_op = build_unit_of_op(model)
        families = collect_families(aux, TARGETS)
        self.assertEqual(sorted(families), sorted(TARGETS))
        self.assertEqual(families["fpRat/arch_table"], {0: 1, 1: 2})
        self.assertEqual(families["vecRat/difftest_table"], {0: 3})

        measured = measure_families(families, aux, unit_of_op, BODY)
        arch = measured["per_family"]["fpRat/arch_table"]
        self.assertEqual(arch["rows"], 2)
        self.assertEqual(arch["row_indices"], [0, 1])
        self.assertEqual(arch["private_ops"], 2)       # ops 3, 4
        self.assertEqual(arch["private_execs"], 20)    # 2 x body(100)=10
        self.assertEqual(arch["shared_ops"], 2)        # ops 1, 2
        self.assertEqual(arch["shared_execs"], 20)
        self.assertEqual(arch["read_consumer_kinds"],
                         {"core.compute.eq": 1, "core.compute.mux": 1})
        diff = measured["per_family"]["vecRat/difftest_table"]
        self.assertEqual(diff["private_ops"], 1)       # op 7
        self.assertEqual(diff["private_execs"], 4)     # body(101)
        self.assertEqual(diff["read_consumer_kinds"], {})

        self.assertEqual(measured["target_private_ops"], 3)   # ops 3, 4, 7
        self.assertEqual(measured["target_private_execs"], 24)
        self.assertEqual(measured["target_shared_only_ops"], 2)
        self.assertEqual(measured["target_shared_only_execs"], 20)
        self.assertEqual(measured["unmapped_private_ops"], [])
        self.assertEqual(measured["multi_writer_rows"], [])


class TestMainEndToEnd(unittest.TestCase):
    def test_main_writes_summary_and_passes_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_path = root / "model.json"
            model_path.write_text(json.dumps(make_model()))
            run_path = root / "run.log"
            run_path.write_text(
                "[grhsim-dyn] sn 100 act=10 body=10 grp=2 chg=2\n"
                "[grhsim-dyn] sn 101 act=4 body=4 grp=1 chg=1\n")
            out1, out2 = root / "run1", root / "run2"
            argv = [
                "--model", str(model_path),
                "--run", str(run_path),
                "--cycles", "100",
                "--expect-families",
                json.dumps({"fpRat/arch_table": 2, "vecRat/difftest_table": 1}),
            ]
            self.assertEqual(main(argv + ["--output", str(out1)]), 0)
            self.assertEqual(main(argv + ["--output", str(out2)]), 0)
            self.assertEqual((out1 / "summary.json").read_bytes(),
                             (out2 / "summary.json").read_bytes())
            self.assertEqual((out1 / "summary.md").read_bytes(),
                             (out2 / "summary.md").read_bytes())
            summary = json.loads((out1 / "summary.json").read_text())
            metric = summary["metrics"]["M-gcone"]
            self.assertEqual(metric["private_ops"], 3)
            self.assertEqual(metric["private_execs"], 24)
            self.assertTrue(all(ok for ok, _ in summary["gates"].values()))

    def test_main_fails_on_wrong_expectation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_path = root / "model.json"
            model_path.write_text(json.dumps(make_model()))
            run_path = root / "run.log"
            run_path.write_text("[grhsim-dyn] sn 100 act=1 body=10 grp=1 chg=1\n")
            code = main([
                "--model", str(model_path),
                "--run", str(run_path),
                "--output", str(root / "out"),
                "--expect-families", json.dumps({"fpRat/arch_table": 5}),
            ])
            self.assertEqual(code, 1)


class TestLoadBodyFires(unittest.TestCase):
    def test_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.log"
            path.write_text(
                "noise\n"
                "[grhsim-dyn] sn 7 act=3 body=42 grp=1 chg=1\n"
                "[grhsim-dyn] commit 9 ent=2\n")
            self.assertEqual(load_body_fires(path), {7: 42})


if __name__ == "__main__":
    unittest.main()
