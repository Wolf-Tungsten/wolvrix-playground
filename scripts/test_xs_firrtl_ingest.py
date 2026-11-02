"""Tests for the F12 FIRRTL ingest benchmark manifest handling."""

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import wolvrix

from benchmark_xs_firrtl_ingest import ROOT, checked, native_identity, request_from_manifest, verify_roundtrip
from compare_xs_firrtl_ingest import compare, profile_report


class FirrtlIngestBenchmarkTest(unittest.TestCase):
    def test_order_inspection_preserves_raw_gate_and_detects_changed_notes(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "ptmp" / "firrtl-ingest") as temporary:
            work = Path(temporary)
            before, after = work / "before", work / "after"
            document = {"graphs": [{"symbol": "a", "vals": [{"loc": {"note": "original"}}]},
                                    {"symbol": "b", "vals": []}],
                        "aliases": {}, "declaredSymbols": ["a", "b"], "tops": ["a"]}
            timing = {"manifest_sha256": "manifest", "diagnostics": [{"message": "a"}, {"message": "b"}, {"message": "a"}],
                      "dependencies": [], "metadata_keys": [], "ingest_s": 1, "maxrss_kib": 2, "native_libraries": []}
            for directory in (before, after):
                directory.mkdir()
                if directory == after:
                    document["graphs"].reverse()
                    document["declaredSymbols"].reverse()
                    timing["diagnostics"].reverse()
                    timing["diagnostics"] = timing["diagnostics"][1:] + timing["diagnostics"][:1]
                payload = json.dumps(document, indent=2).encode()
                (directory / "ingest.json").write_bytes(payload)
                (directory / "graph-identity.json").write_text(json.dumps({"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}))
                (directory / "timing.json").write_text(json.dumps(timing))
            result = compare(before, after, inspect_ordering=True)
            self.assertFalse(result["equal"])
            self.assertTrue(result["order_analysis"]["graph_contents_equal"])
            self.assertTrue(result["order_analysis"]["diagnostic_inventory_equal"])
            document["graphs"][1]["vals"][0]["loc"]["note"] = "changed"
            (after / "ingest.json").write_text(json.dumps(document, indent=2))
            result = compare(before, after, inspect_ordering=True)
            self.assertEqual(result["order_analysis"]["changed_graphs"], ["a"])

    @unittest.skipUnless(hasattr(os, "sched_getaffinity"), "requires process CPU affinity")
    def test_sv_route_uses_make_and_preserves_full_design_roundtrip(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "ptmp" / "firrtl-ingest") as temporary:
            work = Path(temporary)
            source = work / "input.sv"
            source.write_text("module child(input [7:0] a, output [7:0] y); assign y=~a; endmodule\n"
                              "module top(input [7:0] a, output [7:0] y); child u(a,y); endmodule\n")
            filelist, arguments = work / "sources.f", work / "read-args.txt"
            filelist.write_text(str(source) + "\n")
            arguments.write_text("")
            cpu = min(os.sched_getaffinity(0))
            command = ["make", "--no-print-directory", "benchmark_xs_sv_ingest", "SKIP_PY_INSTALL=1",
                       f"PYTHON={sys.executable}", "XS_SIM_TOP=top",
                       f"SV_INGEST_BENCH_FILELIST={filelist}", f"SV_INGEST_BENCH_READ_ARGS={arguments}",
                       f"FIRRTL_INGEST_BENCH_WORK={work / 'run'}",
                       f"FIRRTL_INGEST_BENCH_ARGS=--verify-roundtrip --cpu {cpu}"]
            result = subprocess.run(command, cwd=ROOT, env={**os.environ, "WOLF_ENV_SOURCED": "1"},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            timing = json.loads((work / "run/timing.json").read_text())
            self.assertEqual(timing["route"], "sv")
            self.assertEqual(timing["cpu_affinity"], [cpu])
            self.assertTrue(timing["roundtrip"]["equal"])
            self.assertEqual(len(json.loads((work / "run/ingest.json").read_text())["graphs"]), 2)
            command[-1] = f"FIRRTL_INGEST_BENCH_ARGS=--cpu {cpu}"
            result = subprocess.run(command, cwd=ROOT, env={**os.environ, "WOLF_ENV_SOURCED": "1"},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((work / "run/graph-identity.json").exists())
            self.assertFalse((work / "run/roundtrip-identity.json").exists())
            source.write_text("module top(input ; endmodule\n")
            result = subprocess.run(command, cwd=ROOT, env={**os.environ, "WOLF_ENV_SOURCED": "1"},
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            failed = json.loads((work / "run/timing.json").read_text())
            self.assertFalse(failed["success"])
            self.assertTrue(failed["diagnostics"])

    def test_comparison_rejects_source_info_and_diagnostic_changes(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "ptmp" / "firrtl-ingest") as temporary:
            work = Path(temporary)
            before, after = work / "before", work / "after"
            timing = {"manifest_sha256": "manifest", "diagnostics": [
                {"location": "transactions/123-456/helper.sv", "message": "warning"}],
                "dependencies": ["firrtl:input"], "metadata_keys": ["node"],
                "ingest_s": 1, "maxrss_kib": 2, "native_libraries": []}
            for directory in (before, after):
                directory.mkdir()
                (directory / "timing.json").write_text(json.dumps(timing))
                (directory / "graph-identity.json").write_text(json.dumps({"bytes": 10, "sha256": "graph"}))
            timing["diagnostics"][0]["location"] = "transactions/789-123/helper.sv"
            (after / "timing.json").write_text(json.dumps(timing))
            self.assertTrue(compare(before, after)["equal"])
            (after / "graph-identity.json").write_text(json.dumps({"bytes": 10, "sha256": "changed-source-info"}))
            self.assertFalse(compare(before, after)["checks"]["graph"])
            timing["diagnostics"][0]["message"] = "different warning"
            (after / "timing.json").write_text(json.dumps(timing))
            self.assertFalse(compare(before, after)["checks"]["diagnostics"])
            (before / "graph-identity.json").unlink()
            (after / "graph-identity.json").unlink()
            report = compare(before, after, timing_only=True)
            self.assertFalse(report["graph_checked"])
            self.assertNotIn("graph", report["checks"])
            self.assertFalse(report["equal"])
            with self.assertRaises(FileNotFoundError):
                compare(before, after)

    def test_profile_accounting_excludes_nested_scopes(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "ptmp" / "firrtl-ingest") as temporary:
            work = Path(temporary)
            (work / "profile.jsonl").write_text(json.dumps({"total_us": 100,
                "stages": {"scan_interfaces_us": 10, "scan_index_us": 5,
                           "resolve_phase_us": 20, "ensure_phase_us": 50,
                           "lower_module_us": 45, "verify_linked_design_us": 17},
                "modules": [{"name": "parent", "resolve_us": 90, "resolve_self_us": 1},
                            {"name": "child", "resolve_us": 20, "resolve_self_us": 20}]}))
            report = profile_report(work)
            self.assertEqual(report["accounted_fraction"], 0.97)
            self.assertEqual(report["unattributed_us"], 3)
            self.assertEqual(report["top20_resolve_self"][0]["name"], "child")

    def test_full_design_roundtrip_preserves_hierarchy_and_node_attributes(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "ptmp" / "firrtl-ingest") as temporary:
            work = Path(temporary)
            source = work / "roundtrip.fir"
            source.write_text("""FIRRTL version 6.0.0
circuit top :
  module child :
    input a : UInt<8>
    output y : UInt<8>
    node n = not(a)
    connect y, n
  module top :
    input a : UInt<8>
    output y : UInt<8>
    inst u of child
    connect u.a, a
    connect y, u.y
""", encoding="utf-8")
            with wolvrix.Session() as session:
                checked(session.read_firrtl(str(source), firrtl_options={"node_annotations": True}), "fixture")
                report = verify_roundtrip(session, work)
            self.assertTrue(report["equal"])
            document = json.loads((work / "ingest.json").read_text())
            self.assertEqual(len(document["graphs"]), 2)
            self.assertIn("firrtl.node.members", (work / "ingest.json").read_text())

    def test_records_loaded_native_library_content(self):
        identity = native_identity()
        self.assertTrue(identity)
        for entry in identity:
            path = Path(entry['path'])
            self.assertTrue(path.is_absolute())
            self.assertEqual(entry['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(entry['mtime_ns'], path.stat().st_mtime_ns)

    def test_resolves_relative_sources_and_preserves_request_fields(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "ptmp" / "firrtl-ingest") as temporary:
            work = Path(temporary)
            source = work / "input.fir"
            source.write_text("FIRRTL version 6.0.0\ncircuit top :\n", encoding="utf-8")
            manifest = work / "sources.json"
            manifest.write_text(json.dumps({
                "schema": "wolvrix.xs.firrtl-inputs.v1",
                "input_root": ".",
                "tops": ["top"],
                "sources": [{"language": "firrtl", "path": source.name, "unit": "unit"}],
                "slang_args": [], "firrtl_options": {}, "external_bindings": [],
            }), encoding="utf-8")
            request = request_from_manifest(manifest)
            self.assertEqual(request["tops"], ["top"])
            self.assertEqual(Path(request["sources"][0]["path"]), source.resolve())

    def test_rejects_manifest_without_firrtl_source(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "ptmp" / "firrtl-ingest") as temporary:
            manifest = Path(temporary) / "sources.json"
            manifest.write_text(json.dumps({
                "schema": "wolvrix.xs.firrtl-inputs.v1",
                "sources": [{"language": "sv", "path": "missing.sv"}],
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                request_from_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
