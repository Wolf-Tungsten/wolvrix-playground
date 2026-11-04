"""Tests for the F12 FIRRTL ingest benchmark manifest handling."""

import json
import hashlib
import copy
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import wolvrix

from benchmark_xs_firrtl_ingest import (
    ROOT, allocation_delta, allocator_configuration, allocator_statistics, checked,
    native_identity, request_from_manifest, verify_roundtrip,
)
from compare_xs_firrtl_ingest import compare, profile_report
from f16_firrtl_evidence import compare_prefix, summarize
from wolvrix_xs_grhsim import GRH_PIPELINE


class FirrtlIngestBenchmarkTest(unittest.TestCase):
    def test_effective_allocator_configuration_in_fresh_make_processes(self):
        environment = {key: value for key, value in os.environ.items()
                       if not key.upper().startswith("MIMALLOC_")}
        environment.update({"WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""})
        configurations = []
        for setting, expected_interval in (("", None), ("45000", 45000), ("0", 1), ("2000000", 1000000)):
            command = ["make", "--no-print-directory", "check_f16_allocator", f"PYTHON={sys.executable}",
                       "F16_NATIVE_DIR=", f"F16_GENERIC_COLLECT={setting}"]
            result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            config = json.loads(result.stdout)
            self.assertEqual(set(config), {"mimalloc", "project_defaults", "generic_collect"})
            self.assertIs(type(config["mimalloc"]), bool)
            self.assertIs(type(config["project_defaults"]), bool)
            if config["project_defaults"]:
                self.assertTrue(config["mimalloc"])
                self.assertIs(type(config["generic_collect"]), int)
                if expected_interval is None:
                    # The configured build default can be any supported interval.
                    self.assertGreaterEqual(config["generic_collect"], 1)
                    self.assertLessEqual(config["generic_collect"], 1000000)
                else:
                    self.assertEqual(config["generic_collect"], expected_interval)
            else:
                self.assertIsNone(config["generic_collect"])
            configurations.append(config)
        for config in configurations[1:]:
            self.assertEqual(configurations[0]["mimalloc"], config["mimalloc"])
            self.assertEqual(configurations[0]["project_defaults"], config["project_defaults"])

    def test_benchmark_supports_native_variants_without_allocator_diagnostics(self):
        with mock.patch.object(wolvrix, "_native", object()):
            self.assertIsNone(allocator_configuration())
            self.assertIsNone(allocator_statistics())

    def test_allocator_stage_delta_requires_all_worker_statistics(self):
        before = {"allocations": 100, "all_threads_merged": True}
        after = {"allocations": 160, "all_threads_merged": True}
        self.assertEqual(allocation_delta(before, after), 60)
        with self.assertRaisesRegex(RuntimeError, "live worker"):
            allocation_delta(before, {**after, "all_threads_merged": False})
        with self.assertRaisesRegex(RuntimeError, "decreased"):
            allocation_delta(after, before)

    def test_prefix_identity_checks_both_endpoints_separately_from_timing(self):
        work_root = ROOT / "ptmp" / "firrtl-ingest" / "F16"
        work_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work_root) as temporary:
            work = Path(temporary)
            source = work / "input.fir"
            source.write_text("""FIRRTL version 6.0.0
circuit top :
  module child :
    input a : UInt<8>
    output y : UInt<8>
    node n = not(a) @[child-source.fir 4:5]
    connect y, n
  public module top :
    input a : UInt<8>
    output y : UInt<8>
    inst u of child
    connect u.a, a
    connect y, u.y
""")
            manifest = work / "sources.json"
            manifest.write_text(json.dumps({"schema": "wolvrix.xs.firrtl-inputs.v1",
                "input_root": str(work), "tops": ["top"],
                "sources": [{"language": "firrtl", "path": str(source), "unit": "unit"}],
                "slang_args": [], "firrtl_options": {"node_annotations": True, "lower_threads": 2},
                "external_bindings": []}))
            for label, flags in (("before", "--prefix-identity"),
                                 ("after", "--prefix-identity --fused-prefix --discard-identity-json")):
                command = ["make", "--no-print-directory", "benchmark_f15_firrtl_ingest",
                    "SKIP_PY_INSTALL=1", f"PYTHON={sys.executable}",
                    f"F15_FIRRTL_MANIFEST={manifest}", f"F15_FIRRTL_BENCH_WORK={work / label}",
                    f"F15_FIRRTL_BENCH_ARGS={flags}"]
                result = subprocess.run(command, cwd=ROOT,
                    env={**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""},
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = compare_prefix(work / "before", work / "after")
            self.assertTrue(report["equal"], report["checks"])
            self.assertTrue(report["graph_checked"])
            self.assertIsNone(report["measurements"][0]["prefix"]["wall_s"])
            for stage in ("ingest", "flatten"):
                self.assertTrue((work / "before" / f"{stage}.json").is_file())
                self.assertFalse((work / "after" / f"{stage}.json").exists())
            text = (work / "before/flatten.json").read_text()
            self.assertIn("firrtl.node.members", text)
            self.assertIn("child-source.fir", text)
            with self.assertRaisesRegex(ValueError, "dedicated --through-flatten"):
                summarize([work / "before"])

    def prefix_report_fixture(self, work, *, seconds=1, correctness=False):
        work.mkdir()
        stages = []
        for name, options in GRH_PIPELINE:
            stages.append({"pass": name, "options": options, "keep_declared_symbols": True,
                           "diagnostics": [{"kind": "warning", "message": name}],
                           "wall_s": 1, "cpu_s": 1, "maxrss_kib": 2})
            if name == "hier-flatten":
                break
        digest = lambda text: hashlib.sha256(text.encode()).hexdigest()
        timing = {"manifest_sha256": digest("manifest"), "diagnostics": [], "success": True,
                  "dependencies": [], "metadata_keys": [], "source_bytes": {"source": 100},
                  "configuration": {"measurement_mode": "prefix-identity" if correctness else "through-flatten"},
                  "allocator_environment": {}, "cpu_affinity": [0],
                  "allocator_configuration": {"mimalloc": True, "project_defaults": True,
                                              "generic_collect": 1000000},
                  "ingest_s": seconds, "ingest_cpu_s": seconds, "maxrss_kib": 2,
                  "native_libraries": [{"path": str(ROOT / "ptmp/firrtl-ingest/F16/native.so"),
                                        "sha256": digest("native")}], "post_ingest_stages": stages,
                  "through_flatten_wall_s": seconds + len(stages), "through_flatten_maxrss_kib": 2}
        identity = {"schema": "wolvrix.firrtl-prefix-identity.v1",
                    "run_identity": {key: copy.deepcopy(timing[key]) for key in (
                        "manifest_sha256", "native_libraries", "configuration", "allocator_environment",
                        "allocator_configuration", "cpu_affinity")},
                    "source_fingerprints": {"source": {"bytes": 100, "sha256": digest("source")}},
                    "pipeline": [{key: row[key] for key in ("pass", "options", "keep_declared_symbols")}
                                 for row in stages], "stages": {}}
        for stage in ("ingest", "flatten"):
            identity["stages"][stage] = {"graph": {"bytes": 10, "sha256": digest(stage)},
                "metadata": {"symbol": "top", "metadata": {}},
                "diagnostics": [] if stage == "ingest" else [row["diagnostics"] for row in stages]}
        (work / "timing.json").write_text(json.dumps(timing))
        if correctness:
            (work / "prefix-identity.json").write_text(json.dumps(identity))
        return timing, identity

    def test_prefix_comparison_rejects_incomplete_or_changed_evidence(self):
        work_root = ROOT / "ptmp" / "firrtl-ingest" / "F16"
        work_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work_root) as temporary:
            work = Path(temporary)
            self.prefix_report_fixture(work / "before", correctness=True)
            timing, identity = self.prefix_report_fixture(work / "after", correctness=True)
            self.assertTrue(compare_prefix(work / "before", work / "after")["equal"])
            changed_timing, changed_identity = copy.deepcopy(timing), copy.deepcopy(identity)
            changed_timing["allocator_configuration"]["generic_collect"] = 45000
            changed_identity["run_identity"]["allocator_configuration"]["generic_collect"] = 45000
            (work / "after/timing.json").write_text(json.dumps(changed_timing))
            (work / "after/prefix-identity.json").write_text(json.dumps(changed_identity))
            comparison = compare_prefix(work / "before", work / "after")
            self.assertTrue(comparison["equal"])
            self.assertNotEqual(*comparison["allocator_configuration"])
            (work / "after/timing.json").write_text(json.dumps(timing))
            (work / "after/prefix-identity.json").write_text(json.dumps(identity))
            for stage, field in (("ingest", "graph"), ("flatten", "graph"), ("flatten", "metadata")):
                changed = copy.deepcopy(identity)
                if field == "graph":
                    changed["stages"][stage][field]["sha256"] = hashlib.sha256(b"changed").hexdigest()
                else:
                    changed["stages"][stage][field]["metadata"]["changed"] = True
                (work / "after/prefix-identity.json").write_text(json.dumps(changed))
                self.assertFalse(compare_prefix(work / "before", work / "after")["equal"], (stage, field))
            for field in ("graph", "diagnostics"):
                changed = copy.deepcopy(identity)
                changed["stages"]["flatten"][field] = {}
                (work / "after/prefix-identity.json").write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    compare_prefix(work / "before", work / "after")
            for field, value in (("source_fingerprints", {}), ("run_identity", {}), ("pipeline", [])):
                changed = copy.deepcopy(identity)
                changed[field] = value
                (work / "after/prefix-identity.json").write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    compare_prefix(work / "before", work / "after")
            for field in ("native_libraries", "manifest_sha256", "allocator_configuration"):
                changed = copy.deepcopy(identity)
                changed["run_identity"][field] = "stale provenance"
                (work / "after/prefix-identity.json").write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, "does not belong"):
                    compare_prefix(work / "before", work / "after")
            identity["stages"].pop("flatten")
            (work / "after/prefix-identity.json").write_text(json.dumps(identity))
            with self.assertRaisesRegex(ValueError, "both ingest and flatten"):
                compare_prefix(work / "before", work / "after")
            timing["post_ingest_stages"][-1]["diagnostics"].reverse()
            timing["post_ingest_stages"][-1]["diagnostics"].append({"message": "changed"})
            (work / "after/timing.json").write_text(json.dumps(timing))
            result = compare_prefix(work / "before", work / "after", timing_only=True)
            self.assertFalse(result["graph_checked"])
            self.assertFalse(result["checks"]["prefix_diagnostics"])

    def test_prefix_timing_summary_reports_repeats_and_rejects_mixed_libraries(self):
        work_root = ROOT / "ptmp" / "firrtl-ingest" / "F16"
        work_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work_root) as temporary:
            work = Path(temporary)
            runs = [work / str(index) for index in range(3)]
            for directory, seconds in zip(runs, (4, 2, 3)):
                self.prefix_report_fixture(directory, seconds=seconds)
            report = summarize(runs)
            self.assertTrue(report["equal"])
            self.assertEqual(report["run_count"], 3)
            self.assertEqual(report["summary"]["ingest"]["wall_s"]["median"], 3)
            with self.assertRaisesRegex(ValueError, "distinct output directories"):
                summarize([runs[0], runs[0], runs[0]])
            legacy = json.loads((runs[0] / "timing.json").read_text())
            legacy["configuration"].pop("measurement_mode")
            legacy["measurement_scope"] = "original sources through full production hier-flatten prefix"
            (runs[0] / "timing.json").write_text(json.dumps(legacy))
            self.assertTrue(summarize(runs)["equal"])
            (runs[0] / "graph-identity.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "dedicated --through-flatten"):
                summarize(runs)
            (runs[0] / "graph-identity.json").unlink()
            timing = json.loads((runs[-1] / "timing.json").read_text())
            timing["native_libraries"][0]["sha256"] = hashlib.sha256(b"different").hexdigest()
            (runs[-1] / "timing.json").write_text(json.dumps(timing))
            self.assertFalse(summarize(runs)["checks"]["native_libraries"])
            timing["native_libraries"][0]["sha256"] = hashlib.sha256(b"native").hexdigest()
            timing["allocator_environment"] = {"MIMALLOC_GENERIC_COLLECT": "1000000"}
            (runs[-1] / "timing.json").write_text(json.dumps(timing))
            self.assertFalse(summarize(runs)["checks"]["allocator_environment"])
            timing["allocator_environment"] = {}
            timing["allocator_configuration"]["generic_collect"] = 45000
            (runs[-1] / "timing.json").write_text(json.dumps(timing))
            self.assertFalse(summarize(runs)["checks"]["allocator_configuration"])
            timing["configuration"]["profile_timestamps"] = True
            (runs[-1] / "timing.json").write_text(json.dumps(timing))
            with self.assertRaisesRegex(ValueError, "profile/perf diagnostic"):
                summarize(runs)

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
