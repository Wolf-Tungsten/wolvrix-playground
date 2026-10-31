"""Mixed-language ingestion transactions through public Python entry points."""

import json
import os
import unittest
from pathlib import Path

import wolvrix

ROOT = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("INGEST_MIXED_TEST_WORK", ROOT / "ptmp/firrtl-ingest/F07/python"))
FIRRTL = """FIRRTL version 6.0.0
circuit top :
  extmodule External :
    input a : UInt<8>
    output y : UInt<8>
    defname = implementation
    parameter N = 3
  public module top :
    input a : UInt<8>
    output y : UInt<8>
    inst child of External
    connect child.a, a
    connect y, child.y
"""
SV = """module implementation #(parameter int N=1)(input logic [7:0] a, output logic [7:0] y);
assign y = a + N;
endmodule
"""


class MixedIngestTest(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)
        self.fir = WORK / "top.fir"
        self.sv = WORK / "implementation.sv"
        self.fir.write_text(FIRRTL)
        self.sv.write_text(SV)
        self.session = wolvrix.Session()
        self.addCleanup(self.session.close)
        self.session.diagnostics_raise_min_level = "none"
        self.session.diagnostics_print_min_level = "none"
        self.session.log_level = "off"

    def snapshot(self, key="design.main"):
        path = WORK / "snapshot.json"
        self.session.store_json(design=key, output=str(path))
        return json.loads(path.read_text())

    def good(self, *, replace=False):
        diagnostics = self.session.read_firrtl(str(self.fir), sv_sources=[str(self.sv)], replace=replace)
        self.assertFalse(any(d["kind"] == "error" for d in diagnostics), diagnostics)

    def test_entrypoints_clone_and_repeated_read(self):
        self.good()
        self.session.clone_design(design="design.main", out_design="design.clone")
        before = self.snapshot("design.clone")
        self.good(replace=True)
        self.session.delete("design.main")
        self.assertEqual(self.snapshot("design.clone"), before)
        diagnostics = self.session.read_sources([
            {"language": "firrtl", "path": str(self.fir)},
            {"language": "sv", "path": str(self.sv)},
        ], tops=["top"])
        self.assertFalse(any(d["kind"] == "error" for d in diagnostics), diagnostics)
        self.assertFalse(any(d["kind"] == "error" for d in self.session.run_pass(
            "hier-flatten", design="design.main")))

    def test_failed_link_preserves_existing_design(self):
        self.good()
        before = self.snapshot()
        self.sv.write_text(SV.replace("[7:0] y", "[6:0] y"))
        diagnostics = self.session.read_firrtl(str(self.fir), sv_sources=[str(self.sv)], replace=True)
        self.assertTrue(any(d["kind"] == "error" for d in diagnostics), diagnostics)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(any(d["kind"] == "error" for d in self.session.read_firrtl(str(self.fir), replace=True)))
        self.assertEqual(self.snapshot(), before)

    def test_negative_transactions_preserve_existing_design(self):
        self.good()
        before = self.snapshot()
        failures = [
            SV.replace("[7:0] y", "[6:0] y"),
            SV.replace("output logic [7:0] y", "input logic [7:0] y").replace("assign y = a + N;", ""),
            SV + "\nmodule top; endmodule\n",
            SV.replace("assign y = a + N;", "top again(.a(a), .y(y));"),
            SV.replace("output logic [7:0] y", "output logic [7:0] wrong").replace("assign y =", "assign wrong ="),
        ]
        for source in failures:
            with self.subTest(source=source):
                self.sv.write_text(source)
                diagnostics = self.session.read_firrtl(str(self.fir), sv_sources=[str(self.sv)], replace=True)
                self.assertTrue(any(d["kind"] == "error" for d in diagnostics), diagnostics)
                self.assertEqual(self.snapshot(), before)
        self.sv.write_text(SV)
        binding = {"module": "External", "implementation": {"name": "implementation"}}
        diagnostics = self.session.read_firrtl(str(self.fir), sv_sources=[str(self.sv)], replace=True,
                                               external_bindings=[binding, binding])
        self.assertTrue(any(d["kind"] == "error" for d in diagnostics), diagnostics)
        self.assertEqual(self.snapshot(), before)

    def test_diagnostics_survive_replacement(self):
        self.good()
        self.sv.write_text(SV.replace("assign y = a + N;", "always begin while(a) y = a; end"))
        diagnostics = self.session.read_firrtl(str(self.fir), sv_sources=[str(self.sv)], replace=True)
        errors = [d for d in diagnostics if d["kind"] == "error" and d.get("file", "").endswith("implementation.sv")]
        self.assertTrue(errors, diagnostics)
        self.sv.write_text(SV)
        self.good(replace=True)
        self.assertGreater(errors[0]["line"], 0)
        self.assertIn("^", errors[0]["text"])

    def test_explicit_binding_typed_parameters_and_validation(self):
        self.sv.write_text(SV.replace("implementation", "renamed").replace(" a,", " data,").replace("a + N", "data + N"))
        diagnostics = self.session.read_firrtl(str(self.fir), sv_sources=[str(self.sv)], external_bindings=[{
            "module": "External",
            "implementation": {"name": "renamed", "parameters": {
                "N": {"kind": "integer", "width": 8, "signed": False, "bits": "00001001"},
            }},
            "ports": {"a": "data"},
        }])
        self.assertFalse(any(d["kind"] == "error" for d in diagnostics), diagnostics)
        with self.assertRaises(ValueError):
            self.session.read_firrtl(str(self.fir), firrtl_options={"unknown": True}, out_design="bad")
        self.assertNotIn("bad", self.session)


if __name__ == "__main__":
    unittest.main()
