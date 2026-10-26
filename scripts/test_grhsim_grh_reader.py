"""Native graph diagnostics: scope, type boundaries and fire-driven writes."""

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from grhsim_declared_pack_census import build_universe, native_family_report, read_pack_members
from grhsim_grh_reader import GraphReader, logical_type
from grhsim_paired_cone_diff import (GsimGraph, GsimSignatures, NativeGrhSignatures,
                                    Signatures, load_grhsim_final, native_paired_report)


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("compare_rob", ROOT / "testcase/xs-components/scripts/compare_rob.py")
ROB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ROB)


class Fixture:
    def __init__(self, top="top"):
        self.graph = {"symbol": top, "ops": [], "vals": [], "declaredSymbols": ["q", "memory"],
                      "ports": {"in": [], "out": [], "inout": []}}
        self.model = {"tops": [top], "graphs": [self.graph]}
        self.op("q", "kRegister", attrs={"width": 8, "domain": "2state"})
        self.op("memory", "kRegister", attrs={"width": 64, "shape": [2, 4], "domain": "2state"})
        self.input("fire", 1)
        self.input("enable", 1)
        self.input("address", 2)
        self.op("one", "kConstant", out="one_value", attrs={"constValue": "8'h1"})
        self.op("read", "kRegisterReadPort", out="current", attrs={"regSymbol": "q"})
        self.op("xor", "kXor", ["current", "one_value"], "next")
        self.op("write", "grhsim.writeMask", ["fire", "enable", "next", "one_value"],
                attrs={"regSymbol": "q"})

    def input(self, name, width):
        self.graph["vals"].append({"sym": name, "w": width, "type": "logic", "domain": "2state"})
        self.graph["ports"]["in"].append({"name": name, "val": name})

    def op(self, name, kind, args=(), out=None, attrs=None, width=8, shape=(), domain="2state", signed=False):
        typed = {}
        for key, value in (attrs or {}).items():
            typed[key] = {"vs" if isinstance(value, list) else "v": value}
        record = {"sym": name, "kind": kind, "in": list(args), "out": [out] if out else [], "attrs": typed}
        self.graph["ops"].append(record)
        if out:
            self.graph["vals"].append({"sym": out, "w": width, "sgn": signed, "type": "logic",
                                       "domain": domain, "shape": list(shape), "def": name})
        return record


def gsim_fixture():
    graph = GsimGraph()
    graph.op_names = {1: "OP_EMPTY", 2: "OP_INT", 3: "OP_XOR"}
    graph.nodes["q"] = ["NODE_REG_SRC", 8, None]
    graph.nodes["next"] = ["NODE_REG_DST", 8, ((2, (
        (1, 8, 0, (), "q", None, ()),
        (2, 8, 0, (), None, "1", ()),
        (3, 8, 0, (0, 1), None, None, ()),
    )),)]
    graph.reg_src = [("q", 8, "next")]
    return graph


class ReaderTests(unittest.TestCase):
    def directory(self):
        work = ROOT / "ptmp/remove-grhsim-ir"
        work.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(prefix="reader-", dir=work)
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def test_native_records_and_array_total_width(self):
        fixture = Fixture()
        reader = GraphReader(fixture.model)
        self.assertIs(reader.ops["xor"], fixture.graph["ops"][-2])
        summary, registers, arrays = reader.state_census()
        self.assertEqual(summary["states"], 2)
        self.assertEqual(summary["array_storage_bits"], 64)
        self.assertEqual(arrays["memory"]["element_width"], 8)
        self.assertEqual(arrays["memory"]["shape"], [2, 4])
        self.assertEqual(registers["q"]["width"], 8)
        self.assertEqual(reader.cone(["next"]), {"read", "one", "xor"})
        self.assertEqual(reader.writes["q"], ["write"])
        self.assertNotIn("fire", reader.ops)
        universe = build_universe(fixture.model)
        self.assertEqual(set(universe["members"]), {"q"})
        self.assertEqual(universe["member_bits"], 8)
        self.assertEqual(universe["declared_non_logic_states"], 1)

    def family_fixture(self):
        fixture = Fixture()
        for index in range(2):
            name = f"bank$cell_{index}"
            fixture.graph["declaredSymbols"].append(name)
            fixture.op(name, "kRegister", attrs={"width": 8, "domain": "2state"})
            fixture.op(f"read{index}", "kRegisterReadPort", out=f"current{index}", attrs={"regSymbol": name})
            fixture.op(f"xor{index}", "kXor", [f"current{index}", "one_value"], f"next{index}")
            fixture.op(f"write{index}", "grhsim.writeMask", ["fire", "enable", f"next{index}", "one_value"],
                       attrs={"regSymbol": name})
        return fixture

    def test_native_families_use_fire_enable_data_mask(self):
        fixture = self.family_fixture()
        report = native_family_report(fixture.model, final_model=fixture.model)
        self.assertEqual(report["schema"], "grh-declared-families.v1")
        self.assertEqual(report["universe"], {"states": 3, "bits": 24})
        family = report["families"][0]
        self.assertTrue(family["isomorphic"])
        self.assertEqual(family["control_subfamilies"], [["bank$cell_0", "bank$cell_1"]])
        self.assertEqual(family["forms"], {"standalone": 2})
        self.assertFalse(report["dynamic"]["available"])
        self.assertEqual(report["family_bits"] + report["singleton_bits"], 24)
        fixture.graph["ops"][-1]["in"][0] = "enable"
        changed = native_family_report(fixture.model)["families"][0]
        self.assertTrue(changed["isomorphic"])
        self.assertEqual(len(changed["control_subfamilies"]), 2)

    def test_native_families_do_not_equate_effects_or_missing_writers(self):
        fixture = self.family_fixture()
        fixture.op("call", "grhsim.dpi-call", ["fire", "enable"], "call_value")
        fixture.graph["ops"][-2]["in"][2] = "call_value"
        family = native_family_report(fixture.model)["families"][0]
        self.assertFalse(family["isomorphic"])
        self.assertEqual(family["unsigned_reasons"], {"effectful_or_unsupported_cone": 1})
        fixture.graph["ops"] = [op for op in fixture.graph["ops"] if op["sym"] != "write0"]
        family = native_family_report(fixture.model)["families"][0]
        self.assertEqual(family["unsigned_reasons"]["no_writer"], 1)

    def test_new_packing_tsv_header_and_native_alignment(self):
        fixture = self.family_fixture()
        path = self.directory() / "pack.tsv"
        path.write_text("packed_state\tbit\tmember\tinitial\npacked\t0\tbank$cell_0\t0\n"
                        "packed\t1\tbank$cell_1\t1\n")
        self.assertEqual(len(read_pack_members(path)["packed"]), 2)
        family = native_family_report(fixture.model, pack_members=path)
        self.assertTrue(family["packing_alignment"]["available"])
        self.assertEqual(family["families"][0]["forms"], {"packed": 2})

    def test_graph_scope_requires_one_top(self):
        fixture, second = Fixture(), Fixture("other")
        second.graph["declaredSymbols"] = []
        fixture.model["graphs"].append(second.graph)
        self.assertEqual(GraphReader(fixture.model).declared, {"q", "memory"})
        self.assertEqual(GraphReader(fixture.model, "other").declared, set())
        fixture.model["tops"].append("other")
        with self.assertRaisesRegex(ValueError, "explicit top"):
            GraphReader(fixture.model)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            GraphReader(fixture.model, "missing")

    def test_broken_symbols_are_rejected(self):
        original = Fixture().model
        for edit, message in (
            (lambda g: g["ops"].append(copy.deepcopy(g["ops"][0])), "operation symbol"),
            (lambda g: g["vals"].append(copy.deepcopy(g["vals"][0])), "value symbol"),
            (lambda g: g["ops"][-1]["in"].append("missing"), "missing value"),
            (lambda g: g["ops"][-1]["attrs"]["regSymbol"].update(v="foreign"), "missing state"),
            (lambda g: g["vals"][-1].update({"def": "foreign"}), "inconsistent producer"),
        ):
            model = copy.deepcopy(original)
            edit(model["graphs"][0])
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                GraphReader(model)

    def test_indexed_read_is_an_opaque_boundary(self):
        fixture = Fixture()
        fixture.op("read_mem", "kRegisterReadArrayPort", ["address"], "mem_value", attrs={"regSymbol": "memory"})
        reader, pool = GraphReader(fixture.model), Signatures()
        engine = NativeGrhSignatures(reader, {"memory": 0}, pool)
        self.assertEqual(reader.cone(["mem_value"]), {"read_mem"})
        self.assertEqual(pool.keys[engine.sig_value("mem_value")][0], "grh_mem")
        self.assertEqual(reader.ops["read_mem"]["in"], ["address"])

    def test_native_and_gsim_signature_match(self):
        reader, pool = GraphReader(Fixture().model), Signatures()
        native = NativeGrhSignatures(reader, {"q": 0}, pool)
        gsim = GsimSignatures(gsim_fixture(), {"q": 0}, pool)
        self.assertEqual(native.sig_value("next"), gsim.sig(gsim.root("next")))
        self.assertEqual(pool.keys[native.sig_value("enable")][0], "input")

    def test_native_pair_report_uses_only_data_root(self):
        fixture = Fixture()
        report = native_paired_report(GraphReader(fixture.model), gsim_fixture())
        self.assertEqual(report["schema"], "grh-paired-cones.v1")
        self.assertFalse(report["dynamic"]["available"])
        self.assertEqual(len(report["linked_pairs"]), 1)
        row = report["linked_pairs"][0]
        self.assertEqual(row["data_value"], "next")
        self.assertTrue(row["data_root_equal"])
        fixture.graph["ops"][-1]["in"][2] = "one_value"
        changed = native_paired_report(GraphReader(fixture.model), gsim_fixture())["linked_pairs"][0]
        self.assertFalse(changed["data_root_equal"])
        self.assertEqual(changed["grh_data_operations"], 1)

    def test_native_pair_report_rejects_multiple_writer_inference(self):
        fixture = Fixture()
        fixture.op("write2", "grhsim.write", ["fire", "enable", "next"], attrs={"regSymbol": "q"})
        report = native_paired_report(GraphReader(fixture.model), gsim_fixture())
        self.assertEqual(report["linked_pairs"], [])
        self.assertEqual(report["unlinked"], {"multiple_writers": 1})

    def test_assign_requires_full_type_identity(self):
        fixture = Fixture()
        fixture.op("identity", "kAssign", ["next"], "identity_value")
        fixture.op("reshaped", "kAssign", ["next"], "reshaped_value", shape=[2])
        fixture.op("signed", "kAssign", ["next"], "signed_value", signed=True)
        fixture.op("fourstate", "kAssign", ["next"], "fourstate_value", domain="4state")
        reader, pool = GraphReader(fixture.model), Signatures()
        engine = NativeGrhSignatures(reader, {"q": 0}, pool)
        original = engine.sig_value("next")
        self.assertEqual(engine.sig_value("identity_value"), original)
        for name in ("reshaped_value", "signed_value", "fourstate_value"):
            self.assertNotEqual(engine.sig_value(name), original)
        self.assertNotEqual(logical_type(reader.values["reshaped_value"]), logical_type(reader.values["next"]))

    def test_cycle_is_rejected_without_recursion(self):
        fixture = Fixture()
        fixture.op("a", "kNot", ["b_value"], "a_value")
        fixture.op("b", "kNot", ["a_value"], "b_value")
        engine = NativeGrhSignatures(GraphReader(fixture.model), {}, Signatures())
        with self.assertRaisesRegex(ValueError, "combinational cycle"):
            engine.sig_value("a_value")

    def test_invalid_array_shape_rejected(self):
        fixture = Fixture()
        fixture.graph["ops"][1]["attrs"]["shape"]["vs"] = [0]
        with self.assertRaisesRegex(ValueError, "total width/shape"):
            GraphReader(fixture.model).state_census()

    def test_unused_value_symbols_are_preserved(self):
        fixture = Fixture()
        fixture.graph["vals"].append({"sym": "unused_alias", "w": 8, "type": "logic", "domain": "2state"})
        reader = GraphReader(fixture.model)
        self.assertIn("unused_alias", reader.values)
        self.assertEqual(reader.cone(["next"]), {"read", "xor", "one"})
        with self.assertRaisesRegex(ValueError, "missing value producer"):
            reader.cone(["unused_alias"])
        with self.assertRaisesRegex(ValueError, "missing value producer"):
            NativeGrhSignatures(reader, {}, Signatures()).sig_value("unused_alias")

    def test_native_loader_summary_and_checkpoint_preference(self):
        work = self.directory()
        (work / "grhsim").mkdir()
        fixture = Fixture()
        path = work / "grhsim/post_conversion.json"
        path.write_text(json.dumps(fixture.model))
        self.assertIsInstance(load_grhsim_final(path), GraphReader)
        self.assertEqual(ROB.grhsim_summary(path)[0]["array_storage_bits"], 64)
        (work / "grhsim/post_lower.json").write_text("frozen legacy")
        self.assertEqual(ROB.conversion_checkpoint(work), path)

    def test_native_cone_comparison_uses_third_write_operand(self):
        work = self.directory()
        result = ROB.compare_grh_cones(GraphReader(Fixture().model), gsim_fixture(),
                                      [{"grhsim": "q", "gsim": "q", "width": 8}], work)
        self.assertEqual(result["totals"]["pairs"], 1)
        self.assertEqual(result["samples"][0]["grhsim_root"][0]["op"], "xor")
        detail = json.loads((work / "cone_q.json").read_text())
        self.assertEqual(detail["grhsim_writes"][0]["in"], ["fire", "enable", "next", "one_value"])
        self.assertEqual(detail["grhsim_writes"][0]["kind"], "grhsim.writeMask")
        self.assertEqual(result["grhsim_compute_distribution"]["median"], 1)
        self.assertEqual(ROB.compare_grh_cones(GraphReader(Fixture().model), gsim_fixture(), [], work)
                         ["totals"], {})


if __name__ == "__main__":
    unittest.main()
