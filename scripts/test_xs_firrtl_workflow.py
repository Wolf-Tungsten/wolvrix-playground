"""Validate the explicit mixed input route and its dependency boundary."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from xs_firrtl_inputs import create_manifest
from wolvrix_xs_grhsim import (GRH_PIPELINE, firrtl_canonical_pipeline, firrtl_grh_pipeline,
                               grh_pipeline, read_source_manifest, resolve_flat_prefix,
                               timed, write_flat_prefix_identity)

ROOT = Path(__file__).resolve().parents[1]


class XsFirrtlWorkflowTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "ptmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="xs-firrtl-", dir=ROOT / "ptmp")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.firrtl = self.work / "SimTop.fir"
        self.firrtl.write_text("FIRRTL version 6.0.0\ncircuit SimTop :\n  public module SimTop :\n    skip\n")

    def capture_emitter_budgets(self, name, target, overrides, extra_environment):
        work = self.work / name
        xs = work / "xiangshan"
        generated = xs / "build/generated-src"
        generated.mkdir(parents=True)
        (generated / "DifftestMacros.svh").write_text("// mock macros\n")
        (generated / "difftest-state.h").write_text("// mock state\n")
        harness = xs / "difftest"
        harness.mkdir()
        (harness / "Makefile").write_text(".PHONY: emu\nemu:\n"
            "\t@test '$(GRHSIM)' = 1\n"
            "\t@test -f '$(GRHSIM_MODEL_DIR)/Makefile'\n")
        rtl = work / "sv-rtl"
        (rtl / "rtl").mkdir(parents=True)
        (rtl / "rtl/SimTop.sv").write_text("module SimTop; endmodule\n")
        (rtl / "time.log").write_text("firtool --preserve-aggregate=all\nExit status: 0\n")
        vsrc = work / "vsrc"
        vsrc.mkdir()
        captured = work / "generator-arguments.json"
        script = work / "mock_generation.py"
        script.write_text("import json, sys\nfrom pathlib import Path\n"
            f"Path({str(captured)!r}).write_text(json.dumps(sys.argv[1:]))\n"
            "model = Path(sys.argv[sys.argv.index('--emit-cpp-dir') + 1])\n"
            "model.mkdir(parents=True, exist_ok=True)\n"
            "(model / 'Makefile').write_text('# mock model\\n')\n")
        environment = {**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""}
        for key in ("XS_GRHSIM_MAX_TU_BYTES", "XS_GRHSIM_MAX_OUTPUT_FILE_BYTES",
                    "XS_FIRRTL_GRHSIM_MAX_TU_BYTES", "XS_FIRRTL_GRHSIM_MAX_OUTPUT_FILE_BYTES"):
            environment.pop(key, None)
        environment.update(extra_environment)
        result = subprocess.run(["make", "--no-print-directory", target,
            "SKIP_PY_INSTALL=1", f"PYTHON={sys.executable}", f"XS_ROOT={xs}",
            f"XS_GRHSIM_SCRIPT={script}", f"XS_FIRRTL_INPUT={self.firrtl}",
            f"XS_FIRRTL_BUILD={work / 'firrtl-flow'}", f"XS_RTL_BUILD={rtl}",
            f"XS_GRHSIM_BUILD={work / 'sv-flow'}", f"XS_VSRC_DIR={vsrc}",
            f"XS_DIFFTEST_GEN_DIR={generated}", f"XS_FIRRTL_HARNESS_SOURCE={generated}",
            "XS_FIRRTL_SV_SOURCES=", "XS_FIRRTL_INCLUDE_DIRS=", "XS_FIRRTL_RESOURCE_ROOTS=",
            "XS_FIRRTL_COMPILE_TIMEOUT=30s", f"XS_LOG_DIR={work / 'logs'}",
            *[f"{key}={value}" for key, value in overrides.items()]], cwd=ROOT,
            env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout)
        argv = json.loads(captured.read_text())
        def option(name, default):
            self.assertLessEqual(argv.count(name), 1, argv)
            return int(argv[argv.index(name) + 1]) if name in argv else default
        return (option("--max-tu-bytes", 1048576),
                option("--max-output-file-bytes", 4294967296))

    def test_firrtl_emitter_budgets_preserve_override_precedence_and_sv_defaults(self):
        native = (16777216, 34359738368)
        generic = (1048576, 4294967296)
        specific = {"XS_FIRRTL_GRHSIM_MAX_TU_BYTES": "2097152",
                    "XS_FIRRTL_GRHSIM_MAX_OUTPUT_FILE_BYTES": "8589934592"}
        shared = {"XS_GRHSIM_MAX_TU_BYTES": "4194304",
                  "XS_GRHSIM_MAX_OUTPUT_FILE_BYTES": "17179869184"}
        specific_values = (2097152, 8589934592)
        shared_values = (4194304, 17179869184)
        shared_generic = {"XS_GRHSIM_MAX_TU_BYTES": "1048576",
                          "XS_GRHSIM_MAX_OUTPUT_FILE_BYTES": "4294967296"}
        cases = (
            ("canonical-default", "xs-firrtl-grhsim", {}, {}, native),
            ("underscore-default", "xs_firrtl_grhsim", {}, {}, native),
            ("emu-default", "xs_firrtl_grhsim_emu", {}, {}, native),
            ("specific-cli", "xs-firrtl-grhsim", specific, {}, specific_values),
            ("specific-env", "xs-firrtl-grhsim", {}, specific, specific_values),
            ("shared-cli", "xs-firrtl-grhsim", shared, {}, shared_values),
            ("shared-env", "xs-firrtl-grhsim", {}, shared, shared_values),
            ("shared-cli-generic", "xs-firrtl-grhsim", shared_generic, {}, generic),
            ("shared-env-generic", "xs-firrtl-grhsim", {}, shared_generic, generic),
            ("specific-cli-over-shared-env", "xs-firrtl-grhsim", specific, shared, specific_values),
            ("specific-env-over-shared-env", "xs-firrtl-grhsim", {}, {**shared, **specific}, specific_values),
            ("shared-cli-over-specific-cli", "xs-firrtl-grhsim", {**shared, **specific}, {}, shared_values),
            ("shared-cli-over-specific-env", "xs-firrtl-grhsim", shared, specific, shared_values),
            ("tu-only", "xs-firrtl-grhsim", {"XS_FIRRTL_GRHSIM_MAX_TU_BYTES": "2097152"}, {},
                (2097152, native[1])),
            ("file-only", "xs-firrtl-grhsim", {"XS_FIRRTL_GRHSIM_MAX_OUTPUT_FILE_BYTES": "8589934592"}, {},
                (native[0], 8589934592)),
            ("sv-default", "xs_grhsim", {}, {}, generic),
            ("sv-shared-cli", "xs_grhsim", shared, {}, shared_values),
            ("sv-shared-env", "xs_grhsim", {}, shared, shared_values),
            ("sv-specific-cli-ignored", "xs_grhsim", specific, {}, generic),
            ("sv-specific-env-ignored", "xs_grhsim", {}, specific, generic),
        )
        for name, target, overrides, environment, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(self.capture_emitter_budgets(name, target, overrides, environment), expected)

    def test_grh_profile_defaults_to_full(self):
        with patch.dict(os.environ):
            os.environ.pop("XS_GRHSIM_PIPELINE_PROFILE", None)
            self.assertIs(grh_pipeline(), GRH_PIPELINE)
            self.assertEqual([name for name, _ in grh_pipeline()], [
                "xmr-resolve", "mux-tree-fold", "register-write-normalize",
                "mux-tree-fold", "memory-read-retime", "multidriven-guard",
                "blackbox-guard", "latch-transparent-read", "hier-flatten",
                "comb-loop-elim", "grh.verify", "simplify", "grh.verify",
                "memory-init-check"])
        with patch.dict(os.environ, {"XS_GRHSIM_PIPELINE_PROFILE": " FULL "}):
            self.assertIs(grh_pipeline(), GRH_PIPELINE)

    def test_bringup_profile_keeps_required_grh_stages(self):
        with patch.dict(os.environ, {"XS_GRHSIM_PIPELINE_PROFILE": " bringup "}):
            self.assertEqual(grh_pipeline(), [
                ("xmr-resolve", {}),
                ("multidriven-guard", {}),
                ("blackbox-guard", {}),
                ("latch-transparent-read", {}),
                ("hier-flatten", {}),
                ("comb-loop-elim", {"fail_on_true_loop": True}),
                ("memory-init-check", {}),
            ])
        # This profile controls only ordinary GRH cleanup. The shared simulation
        # pipeline still owns grh-to-grhsim and its internal full verification.
        self.assertEqual([name for name, _ in GRH_PIPELINE].count("grh.verify"), 2)
        self.assertIn(("simplify", {"semantics": "2state"}), GRH_PIPELINE)

    def test_firrtl_pipeline_inserts_static_array_split(self):
        for profile in ("full", "bringup"):
            with patch.dict(os.environ, {"XS_GRHSIM_PIPELINE_PROFILE": profile}):
                original = grh_pipeline()
                variant = firrtl_grh_pipeline(original)
                names = [name for name, _ in variant]
                self.assertEqual(names.count("split-static-array"), 1)
                self.assertNotIn("dead-code-elim", names)
                elim = names.index("comb-loop-elim")
                self.assertEqual(names[elim + 1], "split-static-array")
                self.assertNotIn("split-static-array", [name for name, _ in original])
        with self.assertRaisesRegex(ValueError, "no comb-loop-elim"):
            firrtl_grh_pipeline([("hier-flatten", {})])

    def test_f24_firrtl_pipeline_order_is_explicit(self):
        self.assertEqual([name for name, _ in firrtl_canonical_pipeline()], [
            "xmr-resolve", "hier-flatten", "comb-loop-elim", "split-static-array",
            "dead-code-elim", "expr-opt", "used-bits", "split-nodes",
            "dead-code-elim", "constant-analysis", "dead-code-elim",
            "alias-analysis", "pattern-detect", "comm-expr", "dead-code-elim",
        ])

    def test_timed_diagnostic_failure_records_failed(self):
        journal = self.work / "timed-failure.jsonl"
        with patch.dict(os.environ, {"XS_FIRRTL_STAGE_LOG": str(journal)}):
            with self.assertRaisesRegex(RuntimeError, "invalid input"):
                timed("ingest-firrtl", lambda: [{"kind": "error", "message": "invalid input"}],
                      check_diagnostics=True)
        rows = [json.loads(line) for line in journal.read_text().splitlines()]
        self.assertEqual([(row["scope"], row["stage"], row["event"]) for row in rows], [
            ("pipeline", "ingest-firrtl", "start"),
            ("pipeline", "ingest-firrtl", "failed"),
        ])
        self.assertIn("invalid input", rows[-1]["detail"])

    def test_invalid_firrtl_cli_records_ingest_failure(self):
        self.firrtl.write_text("FIRRTL version 6.0.0\ncircuit SimTop :\n"
                              "  public module SimTop :\n    broken syntax\n")
        manifest = self.work / "invalid-sources.json"
        manifest.write_text(json.dumps(create_manifest(self.firrtl, top="SimTop")))
        journal = self.work / "invalid-stages.jsonl"
        result = subprocess.run([
            sys.executable, str(ROOT / "scripts/wolvrix_xs_grhsim.py"), str(manifest), "SimTop",
            str(self.work / "flat.json"), str(self.work / "final.json"),
            str(self.work / "roundtrip.json"), str(manifest), "off",
            "--sources-manifest", str(manifest),
        ], cwd=ROOT, env={**os.environ, "XS_FIRRTL_STAGE_LOG": str(journal)},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        rows = [json.loads(line) for line in journal.read_text().splitlines()]
        self.assertEqual([(row["stage"], row["event"]) for row in rows], [
            ("ingest-firrtl", "start"), ("ingest-firrtl", "failed"),
        ])
        self.assertTrue(all(row["scope"] == "pipeline" for row in rows))

    def test_flat_prefix_identity_rejects_stale_or_contradictory_state(self):
        checkpoint = self.work / "flat.json"
        checkpoint.write_text('{"graphs": []}\n')
        write_flat_prefix_identity(checkpoint, top="SimTop", stage="post-opt")
        preprocessed, identity = resolve_flat_prefix(checkpoint, top="SimTop", requested="auto")
        self.assertTrue(preprocessed)
        self.assertEqual(identity["stage"], "post-opt")
        with self.assertRaisesRegex(ValueError, "contradicts"):
            resolve_flat_prefix(checkpoint, top="SimTop", requested="pre-opt")
        with self.assertRaisesRegex(ValueError, "Invalid flat GRH prefix identity"):
            resolve_flat_prefix(checkpoint, top="OtherTop", requested="auto")
        checkpoint.write_text('{"graphs": []}\n \n')
        for requested in ("auto", "post-opt"):
            with self.subTest(requested=requested), self.assertRaisesRegex(ValueError, "Stale"):
                resolve_flat_prefix(checkpoint, top="SimTop", requested=requested)

    def test_legacy_flat_prefix_requires_explicit_stage(self):
        checkpoint = self.work / "legacy-flat.json"
        checkpoint.write_text('{"graphs": []}\n')
        with self.assertRaisesRegex(ValueError, "lacks prefix identity"):
            resolve_flat_prefix(checkpoint, top="SimTop", requested="auto")
        self.assertFalse(resolve_flat_prefix(checkpoint, top="SimTop", requested="pre-opt")[0])
        self.assertTrue(resolve_flat_prefix(checkpoint, top="SimTop", requested="post-opt")[0])

    def test_unknown_grh_profile_is_rejected(self):
        with patch.dict(os.environ, {"XS_GRHSIM_PIPELINE_PROFILE": "quick"}):
            with self.assertRaisesRegex(ValueError, "must be 'full' or 'bringup'"):
                grh_pipeline()

    def test_explicit_sources_and_policies(self):
        sv = self.work / "Helper.sv"
        sv.write_text("module Helper; endmodule\n")
        manifest = create_manifest(self.firrtl, top="SimTop", sv_sources=[sv],
            include_dirs=[self.work], defines=["DIFFTEST"], init_policy="zero")
        path = self.work / "sources.json"
        path.write_text(json.dumps(manifest))
        request = read_source_manifest(path, "SimTop")
        self.assertEqual([s["language"] for s in request["sources"]], ["firrtl", "sv"])
        self.assertEqual(request["firrtl_options"]["init_policy"], "zero")
        self.assertTrue(request["firrtl_options"]["node_annotations"])
        self.assertEqual(request["slang_args"], ["-I", str(self.work), "-D", "DIFFTEST"])
        with self.assertRaisesRegex(ValueError, "top differs"):
            read_source_manifest(path, "Other")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            create_manifest(self.firrtl, top="SimTop", sv_sources=[sv, sv])

    def test_disabled_node_annotations_round_trip(self):
        manifest = create_manifest(self.firrtl, top="SimTop", node_annotations=False)
        path = self.work / "sources.json"
        path.write_text(json.dumps(manifest))
        request = read_source_manifest(path, "SimTop")
        self.assertIs(request["firrtl_options"]["node_annotations"], False)
        self.assertEqual(request["firrtl_options"]["init_policy"], "unknown")
        self.assertEqual(request["firrtl_options"]["invalid_policy"], "unknown")

    def test_lower_threads_is_published_in_manifest(self):
        manifest = create_manifest(self.firrtl, top="SimTop", lower_threads=4)
        self.assertEqual(manifest["firrtl_options"]["lower_threads"], 4)
        with self.assertRaisesRegex(ValueError, "positive integer"):
            create_manifest(self.firrtl, top="SimTop", lower_threads=0)
        with self.assertRaisesRegex(ValueError, "positive integer"):
            create_manifest(self.firrtl, top="SimTop", lower_threads=True)

    def test_prepared_ingest_request_reaches_canonical_native_pipeline(self):
        self.firrtl.write_text("""FIRRTL version 6.0.0
circuit SimTop :
  public module SimTop :
    output enabled : UInt<1>
    wire hold : UInt<1>
    invalidate hold
    node n = eq(hold, UInt<1>(0))
    connect enabled, n
""")
        request = self.work / "request.json"
        prepared = create_manifest(self.firrtl, top="SimTop", invalid_policy="zero",
                                   node_annotations=False, lower_threads=2)
        prepared["input_root"] = "."
        prepared["sources"][0]["path"] = "SimTop.fir"
        request.write_text(json.dumps(prepared))
        request_bytes = request.read_bytes()
        flow = self.work / "flow"
        unused = self.work / "must-not-generate"
        environment = {**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""}
        environment.pop("XS_FIRRTL_INPUT", None)
        result = subprocess.run(["make", "--no-print-directory", "xs-firrtl-grhsim",
            "SKIP_PY_INSTALL=1", f"PYTHON={sys.executable}",
            f"XS_FIRRTL_SOURCES_MANIFEST={request}", f"XS_FIRRTL_BUILD={flow}",
            f"XS_FIRRTL_RTL_BUILD={unused}", f"XS_LOG_DIR={self.work / 'logs'}",
            # Prepared options own ingestion, even if legacy options differ.
            "XS_FIRRTL_INVALID_POLICY=unknown", "XS_FIRRTL_INIT_POLICY=zero",
            "XS_FIRRTL_NODE_ANNOTATIONS=on", "XS_FIRRTL_LOWER_THREADS=7",
            "XS_FIRRTL_SV_SOURCES=/missing/ignored-helper.sv"], cwd=ROOT, env=environment,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse(unused.exists())
        self.assertEqual(request.read_bytes(), request_bytes)
        normalized = json.loads((flow / "sources.json").read_text())
        self.assertEqual(normalized["firrtl_options"], prepared["firrtl_options"])
        self.assertEqual(normalized["sources"][0]["path"], str(self.firrtl))
        self.assertEqual(normalized["input_root"], str(self.work))
        identity = json.loads((flow / "model/generation-identity.json").read_text())
        self.assertEqual(identity["kind"], "original-firrtl-mixed")
        self.assertEqual(identity["inputs"]["sources_manifest"]["path"], str(flow / "sources.json"))
        self.assertEqual(identity["inputs"]["sources_manifest"]["sha256"],
                         hashlib.sha256((flow / "sources.json").read_bytes()).hexdigest())
        stages = [json.loads(row) for row in next((self.work / "logs").glob("xs_firrtl_stage_*.jsonl"))
                  .read_text().splitlines()]
        self.assertEqual([row["stage"] for row in stages
                          if row["scope"] == "pipeline" and row["event"] == "done"],
                         ["ingest-firrtl", *[name for name, _ in firrtl_canonical_pipeline()],
                          "grhsim-dialect-translate", "split-event-and-output",
                          "split-nonsink-and-sink", "partition-nonsink", "partition-sink",
                          "emit-grhsim-cpp"])
        # eq(invalid, 0) must evaluate as eq(0, 0) before constant-analysis.
        # A manifest ignored until TwoState projection would produce zero.
        (flow / "driver.cpp").write_text("""#include "model/grhsim_SimTop.hpp"
#include <cassert>
int main(){GrhSIM_SimTop m;m.init();m.eval();assert(m.enabled==1);}
""")
        (flow / "run.mk").write_text(""".PHONY: run
run:
	$(MAKE) -C model CXXFLAGS='-std=c++20 -O1 -fno-strict-aliasing'
	$(CXX) -std=c++20 -O1 driver.cpp model/libgrhsim_SimTop.a -lz -o driver
	./driver
""")
        result = subprocess.run(["make", "--no-print-directory", "-f", "run.mk", "run"],
            cwd=flow, env=environment, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_prepared_ingest_request_rejects_mismatches_before_generation(self):
        other = self.work / "Other.fir"
        other.write_text(self.firrtl.read_text())
        marker = self.work / "generator-started"
        generator = self.work / "mock_generation.py"
        generator.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
        for name, changes, overrides, expected in (
            ("top", {"tops": ["Other"]}, [], "top differs"),
            ("input", {}, [f"XS_FIRRTL_INPUT={other}"], "source differs"),
            ("missing", {"sources": [{"language": "firrtl", "path": str(self.work / "missing.fir")}]},
             [], "mixed input not found"),
            ("policy", {"firrtl_options": {"invalid_policy": "other"}}, [],
             "invalid_policy must be unknown or zero"),
        ):
            with self.subTest(name=name):
                request = self.work / f"request-{name}.json"
                request.write_text(json.dumps({**create_manifest(self.firrtl, top="SimTop"), **changes}))
                flow = self.work / name
                flow.mkdir()
                stale = flow / "sources.json"
                stale.write_text("stale output must not permit generation\n")
                environment = {**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""}
                environment.pop("XS_FIRRTL_INPUT", None)
                result = subprocess.run(["make", "--no-print-directory", "xs-firrtl-grhsim",
                    "SKIP_PY_INSTALL=1", f"PYTHON={sys.executable}",
                    f"XS_FIRRTL_SOURCES_MANIFEST={request}", f"XS_FIRRTL_BUILD={flow}",
                    f"XS_GRHSIM_SCRIPT={generator}", *overrides], cwd=ROOT, env=environment,
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(expected, result.stdout)
                self.assertFalse(marker.exists())
                self.assertEqual(stale.read_text(), "stale output must not permit generation\n")

    def test_legacy_ingest_policy_defaults_and_override_remain_supported(self):
        for policy in (None, "zero"):
            with self.subTest(policy=policy):
                environment = {**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""}
                environment.pop("XS_FIRRTL_INVALID_POLICY", None)
                environment.pop("XS_FIRRTL_SOURCES_MANIFEST", None)
                if policy:
                    environment["XS_FIRRTL_INVALID_POLICY"] = policy
                output = self.work / (policy or "default") / "sources.json"
                result = subprocess.run(["make", "--no-print-directory", "xs_firrtl_inputs",
                    f"XS_FIRRTL_INPUT={self.firrtl}", f"XS_FIRRTL_MANIFEST={output}",
                    "XS_FIRRTL_SV_SOURCES=", f"PYTHON={sys.executable}"],
                    cwd=ROOT, env=environment, text=True, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertEqual(read_source_manifest(output, "SimTop")
                                 ["firrtl_options"]["invalid_policy"], policy or "unknown")

    def test_prepared_ingest_request_selects_harness_firrtl(self):
        request = self.work / "request.json"
        request.write_text(json.dumps(create_manifest(self.firrtl, top="SimTop",
                                                      invalid_policy="zero")))
        xs = self.work / "xiangshan"
        (xs / "difftest").mkdir(parents=True)
        (xs / "difftest/Makefile").write_text("# mock harness\n")
        generated = self.work / "generated-src"
        generated.mkdir()
        (generated / "difftest-state.h").write_text("// mock state\n")
        flow = self.work / "flow"
        environment = {**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""}
        environment.pop("XS_FIRRTL_INPUT", None)
        result = subprocess.run(["make", "--no-print-directory", "xs_firrtl_harness_inputs",
            f"PYTHON={sys.executable}", f"XS_ROOT={xs}", f"XS_FIRRTL_BUILD={flow}",
            f"XS_FIRRTL_SOURCES_MANIFEST={request}",
            f"XS_FIRRTL_RTL_BUILD={self.work / 'must-not-generate'}",
            f"XS_FIRRTL_HARNESS_SOURCE={generated}"], cwd=ROOT, env=environment,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout)
        identity = json.loads((flow / "harness-inputs/build-identity.json").read_text())
        self.assertEqual(identity["firrtl"]["path"], str(self.firrtl))
        self.assertEqual(identity["firrtl"]["identity"]["sha256"],
                         hashlib.sha256(self.firrtl.read_bytes()).hexdigest())
        self.assertFalse((self.work / "must-not-generate").exists())

    def test_prebuilt_firrtl_needs_no_generated_sv(self):
        unused = self.work / "unused-rtl"
        result = subprocess.run(["make", "--no-print-directory", "xs_firrtl_inputs",
            f"XS_FIRRTL_INPUT={self.firrtl}", f"XS_FIRRTL_BUILD={self.work / 'flow'}",
            f"XS_RTL_BUILD={unused}", f"PYTHON={sys.executable}"], cwd=ROOT,
            env={**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse(unused.exists())
        manifest = json.loads((self.work / "flow/sources.json").read_text())
        self.assertEqual(len(manifest["sources"]), 2)
        self.assertEqual(manifest["sources"][0]["path"], str(self.firrtl))
        self.assertEqual(manifest["sources"][1], {"language": "sv", "unit": "helpers",
            "path": str(ROOT / "testcase/xiangshan/difftest/src/test/vsrc/common/SimJTAG.v")})
        self.assertIs(manifest["firrtl_options"]["node_annotations"], True)
        self.assertEqual(manifest["firrtl_options"]["lower_threads"], 1)
        result = subprocess.run(["make", "--no-print-directory", "xs_firrtl_inputs",
            f"XS_FIRRTL_INPUT={self.firrtl}", f"XS_FIRRTL_BUILD={self.work / 'flow-off'}",
            f"XS_RTL_BUILD={unused}", "XS_FIRRTL_NODE_ANNOTATIONS=off",
            "XS_FIRRTL_LOWER_THREADS=4",
            f"PYTHON={sys.executable}"], cwd=ROOT,
            env={**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, 0, result.stdout)
        disabled = json.loads((self.work / "flow-off/sources.json").read_text())
        self.assertIs(disabled["firrtl_options"]["node_annotations"], False)
        self.assertEqual(disabled["firrtl_options"]["lower_threads"], 4)

    def test_chisel_generation_uses_firrtl_target(self):
        xs = self.work / "xiangshan"
        xs.mkdir()
        (xs / "Makefile").write_text(""".PHONY: sim-verilog
sim-verilog:
	test '$(CHISEL_TARGET)' = chirrtl
	test '$(RTL_SUFFIX)' = fir
	test -z '$(FIRTOOL)'
	test -z '$(PRESERVE_AGGREGATE)'
	mkdir -p '$(BUILD_DIR)/rtl'
	printf 'FIRRTL version 6.0.0\\ncircuit SimTop :\\n  public module SimTop :\\n    skip\\n' > '$(BUILD_DIR)/rtl/SimTop.fir'
""")
        generated = self.work / "chisel"
        command = ["make", "--no-print-directory", "xs_firrtl_inputs",
            f"XS_ROOT={xs}", f"XS_FIRRTL_RTL_BUILD={generated}",
            f"XS_FIRRTL_BUILD={self.work / 'flow'}", f"XS_LOG_DIR={self.work / 'logs'}",
            "XS_FIRRTL_SV_SOURCES=", f"PYTHON={sys.executable}"]
        result = subprocess.run(command, cwd=ROOT,
            env={**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue((generated / "rtl/SimTop.fir").is_file())
        self.assertFalse(list(generated.rglob("*.sv")))
        self.assertFalse(list(generated.rglob("*.v")))
        result = subprocess.run(command, cwd=ROOT,
            env={**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("test 'chirrtl' = chirrtl", result.stdout)

    def test_missing_default_helper_rejects_manifest(self):
        xs = self.work / "xiangshan"
        xs.mkdir()
        result = subprocess.run(["make", "--no-print-directory", "xs_firrtl_inputs",
            f"XS_ROOT={xs}", f"XS_FIRRTL_INPUT={self.firrtl}",
            f"XS_FIRRTL_BUILD={self.work / 'flow'}", f"PYTHON={sys.executable}"], cwd=ROOT,
            env={**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("SV resource not found:", result.stdout)
        self.assertIn("SimJTAG.v", result.stdout)
        self.assertFalse((self.work / "flow/sources.json").exists())

    def test_build_and_run_forward_independent_paths(self):
        xs = self.work / "xiangshan"
        harness = xs / "difftest"
        harness.mkdir(parents=True)
        generated = xs / "build/generated-src"
        generated.mkdir(parents=True)
        (generated / "difftest-state.h").write_text("// mock generated state\n")
        (harness / "Makefile").write_text(""".PHONY: emu
emu:
	test '$(GRHSIM)' = 1
	test -f '$(GRHSIM_MODEL_DIR)/Makefile'
	test -f '$(GEN_CSRC_DIR)/difftest-state.h'
	test '$(GEN_CSRC_DIR)' -ef '$(GRHSIM_MODEL_DIR)/../harness-inputs/generated-src'
	mkdir -p '$(BUILD_DIR)'
	printf '#!/bin/sh\\nprintf "%%s\\\\n" "$$@"\\n' > '$(BUILD_DIR)/emu'
	chmod +x '$(BUILD_DIR)/emu'
""")
        flow = self.work / "flow"
        (flow / "model").mkdir(parents=True)
        (flow / "model/Makefile").write_text("# generated model placeholder\n")
        result = subprocess.run(["make", "--no-print-directory",
            "xs_firrtl_grhsim_build_emu", "run_xs_firrtl_grhsim_emu",
            f"XS_ROOT={xs}", f"XS_FIRRTL_BUILD={flow}", f"XS_FIRRTL_INPUT={self.firrtl}",
            f"XS_LOG_DIR={self.work / 'logs'}", "XS_EMU_PREFIX=",
            "XS_SIM_MAX_CYCLE=100000", "XS_FIRRTL_COMPILE_TIMEOUT=30s"], cwd=ROOT,
            env={**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue((flow / "emu/emu").is_file())
        self.assertIn("--diff\n", result.stdout)
        self.assertIn("-C\n100000\n", result.stdout)
        self.assertFalse((xs / "build/rtl/SimTop.sv").exists())

    def test_select_internal_module(self):
        self.firrtl.write_text("FIRRTL version 6.0.0\ncircuit SimTop :\n"
            "  module Component :\n    input a : UInt<1>\n    output y : UInt<1>\n    connect y, a\n"
            "  public module SimTop :\n    skip\n")
        manifest = create_manifest(self.firrtl, top="Component")
        path = self.work / "sources.json"
        path.write_text(json.dumps(manifest))
        request = read_source_manifest(path, "Component")
        import wolvrix
        from grhsim_flow import checked
        with wolvrix.Session() as session:
            checked(session.read_sources(**request), "select original circuit component")
            self.assertEqual(session.graph_metadata(design="design.main", top="Component")["symbol"], "Component")

    def test_emu_refresh_pins_one_snapshot_during_generation(self):
        xs = self.work / "xiangshan"
        harness = xs / "difftest"
        harness.mkdir(parents=True)
        (harness / "Makefile").write_text(""".PHONY: emu
emu:
	rg -q '^first$$' '$(GEN_CSRC_DIR)/difftest-state.h'
	test -f '$(GRHSIM_MODEL_DIR)/Makefile'
""")
        generated = xs / "build/generated-src"
        generated.mkdir(parents=True)
        state = generated / "difftest-state.h"
        state.write_text("first\n")
        script = self.work / "mock_generation.py"
        script.write_text("import sys\nfrom pathlib import Path\n"
            "model = Path(sys.argv[sys.argv.index('--emit-cpp-dir') + 1])\n"
            "model.mkdir(parents=True, exist_ok=True)\n"
            "(model / 'Makefile').write_text('# mock model\\n')\n"
            f"Path({str(state)!r}).write_text('second\\n')\n")
        flow = self.work / "flow"
        result = subprocess.run(["make", "--no-print-directory", "xs_firrtl_grhsim_emu",
            f"XS_ROOT={xs}", f"XS_FIRRTL_BUILD={flow}", f"XS_FIRRTL_INPUT={self.firrtl}",
            f"XS_GRHSIM_SCRIPT={script}", "XS_FIRRTL_HARNESS_REFRESH=1", "SKIP_PY_INSTALL=1",
            "XS_FIRRTL_SV_SOURCES=", "XS_FIRRTL_COMPILE_TIMEOUT=30s",
            f"PYTHON={sys.executable}", f"XS_LOG_DIR={self.work / 'logs'}"], cwd=ROOT,
            env={**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(state.read_text(), "second\n")
        self.assertEqual((flow / "harness-inputs/generated-src/difftest-state.h").read_text(), "first\n")

    def test_reference_build_propagates_failure(self):
        xs = self.work / "xiangshan"
        harness = xs / "difftest"
        harness.mkdir(parents=True)
        (harness / "Makefile").write_text(".PHONY: emu\nemu:\n\t@echo mock-reference-build-failure\n\t@false\n")
        generated = xs / "build/generated-src"
        generated.mkdir(parents=True)
        (generated / "DifftestMacros.svh").write_text("// mock macros\n")
        rtl = self.work / "rtl"
        (rtl / "rtl").mkdir(parents=True)
        (rtl / "rtl/SimTop.sv").write_text("module SimTop; endmodule\n")
        (rtl / "time.log").write_text("firtool -O=release\nExit status: 0\n")
        result = subprocess.run(["make", "--no-print-directory", "xs_ref_emu",
            f"XS_ROOT={xs}", f"XS_REF_RTL_BUILD={rtl}", f"XS_REF_BUILD={self.work / 'ref'}",
            f"XS_LOG_DIR={self.work / 'logs'}"], cwd=ROOT,
            env={**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertIn("mock-reference-build-failure", result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_generation_hard_deadline_and_exit_status(self):
        real_timeout = shutil.which("timeout")
        self.assertIsNotNone(real_timeout)
        for mode, status in (("success", 0), ("failure", 7), ("blocked", 137),
                             ("ignore-term", 137), ("override-deadline", 137),
                             ("tee-failure", 23)):
            with self.subTest(mode=mode):
                work = self.work / mode
                harness = work / "xiangshan/difftest"
                harness.mkdir(parents=True)
                generated = work / "xiangshan/build/generated-src"
                generated.mkdir(parents=True)
                (generated / "difftest-state.h").write_text("// mock state\n")
                built = work / "emu-built"
                (harness / "Makefile").write_text(".PHONY: emu\nemu:\n"
                    f"\t@printf built > '{built}'\n")
                flow = work / "flow"
                (flow / "model").mkdir(parents=True)
                (flow / "model/Makefile").write_text("# stale model must not permit a failed generation to build\n")
                finished = work / "generation-finished"
                script = work / "mock_generation.py"
                script.write_text("import ctypes, signal, sys\nfrom pathlib import Path\n"
                    "print('mock-generation-started', flush=True)\n"
                    f"mode = {mode!r}\n"
                    "if mode in ('blocked', 'ignore-term', 'override-deadline'):\n"
                    "    if mode == 'ignore-term': signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                    "    signal.alarm(5)  # Independent cleanup if the Make deadline regresses.\n"
                    "    ctypes.CDLL(None).pause()\n"
                    "    raise SystemExit('native blocking call unexpectedly returned')\n"
                    "if mode == 'failure': raise SystemExit(7)\n"
                    f"Path({str(finished)!r}).write_text('finished\\n')\n")
                shim_dir = work / "bin"
                shim_dir.mkdir()
                invocations = work / "timeout-invocations.jsonl"
                shim = shim_dir / "timeout"
                deadline = "40m" if mode == "override-deadline" else "14m"
                shim.write_text(f"#!{sys.executable}\nimport json, os, sys\nfrom pathlib import Path\n"
                    "assert sys.argv[1] == '--signal=KILL', sys.argv\n"
                    f"assert sys.argv[2] in [{deadline!r}, '30s'], sys.argv\n"
                    f"if sys.argv[2] == {deadline!r}: assert sys.argv[3:5] == {[sys.executable, str(script)]!r}, sys.argv\n"
                    "else: assert '_xs_grhsim_build_emu' in sys.argv, sys.argv\n"
                    f"with Path({str(invocations)!r}).open('a') as log: log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                    f"os.execv({real_timeout!r}, [{real_timeout!r}, '--signal=KILL', '1s', *sys.argv[3:]])\n")
                shim.chmod(0o755)
                if mode == "tee-failure":
                    tee = shim_dir / "tee"
                    tee.write_text(f"#!{sys.executable}\nimport sys\nfrom pathlib import Path\n"
                        "data = sys.stdin.buffer.read()\n"
                        "Path(sys.argv[1]).write_bytes(data)\n"
                        "sys.stdout.buffer.write(data)\n"
                        "raise SystemExit(23)\n")
                    tee.chmod(0o755)
                logs = work / "logs"
                journal = work / "journal/events.jsonl"
                result = subprocess.run(["make", "--no-print-directory", "xs_firrtl_grhsim_emu",
                    f"XS_ROOT={work / 'xiangshan'}", f"XS_FIRRTL_BUILD={flow}",
                    f"XS_FIRRTL_INPUT={self.firrtl}", f"XS_GRHSIM_SCRIPT={script}",
                    "XS_FIRRTL_SV_SOURCES=", "SKIP_PY_INSTALL=1", "RUN_ID=deadline", "XS_FIRRTL_COMPILE_TIMEOUT=30s",
                    f"PYTHON={sys.executable}", f"XS_LOG_DIR={logs}", f"XS_FIRRTL_STAGE_LOG={journal}",
                    *(["XS_FIRRTL_GENERATION_TIMEOUT=40m"] if mode == "override-deadline" else [])], cwd=ROOT,
                    env={**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": "",
                        "PATH": str(shim_dir) + os.pathsep + os.environ["PATH"]},
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
                self.assertIn("mock-generation-started", result.stdout)
                calls = [json.loads(line) for line in invocations.read_text().splitlines()]
                self.assertEqual(len(calls), 2 if status == 0 else 1)
                self.assertIn("--sources-manifest", calls[0])
                self.assertIn("--emit-cpp-dir", calls[0])
                self.assertIn("mock-generation-started", (logs / "xs_firrtl_grhsim_deadline.log").read_text())
                self.assertEqual(result.returncode, 0 if status == 0 else 2, result.stdout)
                if status:
                    self.assertIn(f"Error {status}", result.stdout)
                rows = [json.loads(line) for line in journal.read_text().splitlines()]
                expected_run = [
                    ("run", "xs-firrtl-grhsim", "start"), ("run", "xs-firrtl-grhsim", "exit"),
                ]
                if status == 0:
                    expected_run += [("run", "compile-grhsim-cpp", "start"), ("run", "compile-grhsim-cpp", "exit")]
                self.assertEqual([(row["scope"], row["stage"], row["event"]) for row in rows], expected_run)
                self.assertEqual(rows[1]["exit_status"], status)
                self.assertEqual(rows[1]["command_exit_status"], 0 if mode == "tee-failure" else status)
                self.assertEqual(rows[1]["tee_exit_status"], 23 if mode == "tee-failure" else 0)
                self.assertEqual(rows[1]["termination_reason"], "timeout-or-sigkill" if status == 137 else "exit")
                self.assertGreaterEqual(rows[1]["elapsed_s"], 0.8 if status == 137 else 0)
                self.assertEqual(finished.exists(), status == 0 or mode == "tee-failure", result.stdout)
                self.assertEqual(built.exists(), status == 0, result.stdout)

    def test_compile_budget_is_explicit_and_positive(self):
        for budget in ("", "0", "0s", "-1s", "NaN", "1w"):
            with self.subTest(budget=budget):
                result = subprocess.run(["make", "--no-print-directory", "check_xs_firrtl_compile_budget",
                    f"XS_FIRRTL_COMPILE_TIMEOUT={budget}"], cwd=ROOT,
                    env={**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""},
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("same-input GSIM C++ compile baseline", result.stdout)
        result = subprocess.run(["make", "--no-print-directory", "check_xs_firrtl_compile_budget",
            "XS_FIRRTL_COMPILE_TIMEOUT=.25s"], cwd=ROOT,
            env={**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_compile_deadline_covers_recursive_make_and_records_exit(self):
        for mode, status in (("success", 0), ("failure", 2), ("blocked", 137)):
            with self.subTest(mode=mode):
                work = self.work / ("compile-" + mode)
                xs = work / "xiangshan"
                harness = xs / "difftest"
                harness.mkdir(parents=True)
                generated = xs / "build/generated-src"
                generated.mkdir(parents=True)
                (generated / "difftest-state.h").write_text("// mock state\n")
                (harness / "Makefile").write_text(""".PHONY: emu
emu:
	@test '$(EMU_THREADS)' = 0
	@test '$(EMU_OPTIMIZE)' = '-std=c++20 -O3 -march=native -fno-strict-aliasing'
	@test '$(origin GRHSIM_MODEL_MAKE_J)' = 'command line'
	@test -z '$(GRHSIM_MODEL_MAKE_J)'
	@$(MAKE) -C '$(GRHSIM_MODEL_DIR)' build
""")
                flow = work / "flow"
                model = flow / "model"
                model.mkdir(parents=True)
                (model / "Makefile").write_text(".PHONY: build\nbuild:\n\t@$(PYTHON) ../compile_action.py\n")
                finished = work / "compile-finished"
                descendant = work / "compile-child.pid"
                (flow / "compile_action.py").write_text(
                    "import signal, subprocess, sys\nfrom pathlib import Path\n"
                    "print('mock-compile-started', flush=True)\n"
                    f"mode = {mode!r}\n"
                    "if mode == 'blocked':\n"
                    "    child = subprocess.Popen([sys.executable, '-c', 'import signal; signal.pause()'])\n"
                    f"    Path({str(descendant)!r}).write_text(str(child.pid))\n"
                    "    signal.pause()\n"
                    "if mode == 'failure': raise SystemExit(7)\n"
                    f"Path({str(finished)!r}).write_text('finished\\n')\n")
                journal = work / "journal/events.jsonl"
                result = subprocess.run(["make", "--no-print-directory", "xs_firrtl_grhsim_build_emu",
                    f"XS_ROOT={xs}", f"XS_FIRRTL_BUILD={flow}", f"XS_FIRRTL_INPUT={self.firrtl}",
                    "XS_FIRRTL_COMPILE_TIMEOUT=1s", f"XS_FIRRTL_STAGE_LOG={journal}",
                    f"XS_LOG_DIR={work / 'logs'}", "XS_VM_BUILD_JOBS=2", "RUN_ID=compile-test",
                    f"PYTHON={sys.executable}"], cwd=ROOT,
                    env={**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""},
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
                self.assertEqual(result.returncode, 0 if status == 0 else 2, result.stdout)
                self.assertIn("mock-compile-started", result.stdout)
                rows = [json.loads(line) for line in journal.read_text().splitlines()]
                self.assertEqual([(row["scope"], row["stage"], row["event"]) for row in rows], [
                    ("run", "compile-grhsim-cpp", "start"), ("run", "compile-grhsim-cpp", "exit"),
                ])
                self.assertEqual(rows[-1]["exit_status"], status)
                self.assertEqual(rows[-1]["command_exit_status"], status)
                self.assertEqual(rows[-1]["tee_exit_status"], 0)
                self.assertEqual(rows[-1]["termination_reason"], "timeout-or-sigkill" if status == 137 else "exit")
                self.assertGreaterEqual(rows[-1]["elapsed_s"], 0.8 if status == 137 else 0)
                self.assertEqual(finished.exists(), status == 0)
                if mode == "blocked":
                    child_stat = Path("/proc") / descendant.read_text() / "stat"
                    # SIGKILL reaches the nested model action and its child;
                    # a zombie awaiting reaping is already terminated.
                    self.assertTrue(not child_stat.exists() or child_stat.read_text().split()[2] == "Z")

    def test_dependency_graph_excludes_sv_generation(self):
        result = subprocess.run(["make", "--no-print-directory", "-qp", "xs-firrtl-grhsim",
            "SKIP_PY_INSTALL=1", f"XS_FIRRTL_INPUT={self.firrtl}"], cwd=ROOT,
            env={**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertIn(result.returncode, (0, 1), result.stdout[-2000:])
        graph = {}
        for line in result.stdout.splitlines():
            if line and not line[0].isspace() and not line.startswith("#") and ":" in line:
                target, prerequisites = line.split(":", 1)
                if target in graph or "=" in prerequisites:
                    continue
                graph[target] = prerequisites.split()
        seen = set()
        def visit(target):
            if target in seen:
                return
            seen.add(target)
            for dep in graph.get(target, []):
                visit(dep)
        for target in ("xs_firrtl_inputs", "xs_firrtl_grhsim", "xs-firrtl-grhsim", "xs_firrtl_grhsim_emu",
                       "xs_firrtl_grhsim_build_emu", "run_xs_firrtl_grhsim_emu",
                       "_xs_grhsim_build_emu", "_run_xs_grhsim_emu"):
            visit(target)
        self.assertNotIn("check_xs_aggregate_rtl", seen)
        self.assertNotIn("xs_rtl", seen)
        self.assertFalse(any(dep.endswith("SimTop.sv") for dep in seen))

    def test_mixed_cli_emits_and_executes_model(self):
        self.check_mixed_cli_model(checkpoints=True)

    def test_bringup_cli_without_automatic_checkpoints_executes_model(self):
        self.check_mixed_cli_model(checkpoints=False)

    def check_mixed_cli_model(self, *, checkpoints):
        self.firrtl.write_text("""FIRRTL version 6.0.0
circuit SimTop :
  extmodule External :
    input a : UInt<8>
    output y : UInt<8>
    defname = Helper
  public module SimTop :
    input a : UInt<8>
    output y : UInt<8>
    inst e of External
    node n = xor(a, UInt<8>(165))
    connect e.a, n
    connect y, e.y
""")
        sv = self.work / "Helper.sv"
        sv.write_text("module Helper(input logic [7:0] a, output logic [7:0] y); assign y=a+8'd3; endmodule\n")
        manifest = self.work / "sources.json"
        manifest.write_text(json.dumps(create_manifest(self.firrtl, top="SimTop", sv_sources=[sv],
                                                       node_annotations=checkpoints)))
        final = self.work / "final.json"
        model = self.work / "model"
        journal = self.work / "stages.jsonl"
        command = [sys.executable, str(ROOT / "scripts/wolvrix_xs_grhsim.py"),
            str(manifest), "SimTop", str(self.work / "flat.json"), str(final),
            str(self.work / "roundtrip.json"), str(manifest), "off",
            "--sources-manifest", str(manifest), "--emit-cpp-dir", str(model),
            "--firrtl-nodes", "prefer" if checkpoints else "off", "--max-supernode-nodes", "1"]
        if not checkpoints:
            command += ["--no-store-grh-checkpoints", "--no-roundtrip-verify",
                "--no-clone-shared-compute",
                "--cost-model", "bytes", "--no-readable-names",
                "--no-readable-dump", "--no-source-comments",
                "--dump-post-conversion-json", str(self.work / "explicit-converted.json"),
                "--dump-pre-partition-json", str(self.work / "explicit-pre-partition.json")]
        result = subprocess.run(command, cwd=ROOT,
            env={**os.environ, "XS_GRHSIM_PIPELINE_PROFILE": "full" if checkpoints else "bringup",
                 "XS_FIRRTL_STAGE_LOG": str(journal)},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, 0, result.stdout)
        rows = [json.loads(line) for line in journal.read_text().splitlines()]
        production = [row for row in rows if row["scope"] == "pipeline"]
        expected = ["ingest-firrtl", *[name for name, _ in firrtl_canonical_pipeline()],
                    "grhsim-dialect-translate", "split-event-and-output", "split-nonsink-and-sink",
                    "partition-nonsink", "partition-sink", "emit-grhsim-cpp"]
        self.assertEqual([(row["stage"], row["event"]) for row in production],
                         [(stage, event) for stage in expected for event in ("start", "done")])
        verification = [row for row in rows if row["scope"] == "verification"]
        self.assertEqual([(row["stage"], row["event"]) for row in verification], [
            ("verify-roundtrip", "start"), ("partition-sink", "start"),
            ("partition-sink", "done"), ("verify-roundtrip", "done"),
        ] if checkpoints else [])
        if checkpoints:
            # Resume without the source manifest: checkpoint evidence, not the
            # currently selected ingest route, decides whether the prefix ran.
            resumed = self.work / "resumed.json"
            resume_journal = self.work / "resume-stages.jsonl"
            resume_command = [sys.executable, str(ROOT / "scripts/wolvrix_xs_grhsim.py"),
                str(manifest), "SimTop", str(self.work / "flat.json"), str(resumed),
                str(self.work / "resumed-roundtrip.json"), str(manifest), "off",
                "--resume-from-flat-grh", "--emit-cpp-dir", str(self.work / "resumed-model"),
                "--firrtl-nodes", "prefer", "--max-supernode-nodes", "1"]
            resume_result = subprocess.run(resume_command, cwd=ROOT,
                env={**os.environ, "XS_FIRRTL_STAGE_LOG": str(resume_journal)},
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(resume_result.returncode, 0, resume_result.stdout)
            resume_rows = [json.loads(line) for line in resume_journal.read_text().splitlines()]
            self.assertEqual([row["stage"] for row in resume_rows
                              if row["scope"] == "pipeline" and row["event"] == "done"], [
                "load flat GRH", "grhsim-dialect-translate", "split-event-and-output",
                "split-nonsink-and-sink", "partition-nonsink", "partition-sink", "emit-grhsim-cpp",
            ])
            self.assertTrue(resumed.is_file())
        for name in ("flat.json", "final.json", "roundtrip.json"):
            self.assertEqual((self.work / name).exists(), checkpoints)
        self.assertTrue((self.work / "final.generation-identity.json").is_file())
        if not checkpoints:
            self.assertFalse((model / "grhsim.txt").exists())
            explicit = json.loads((self.work / "explicit-converted.json").read_text())
            self.assertTrue(explicit["graphs"])
            self.assertEqual(explicit["graphs"][0]["metadata"]["grhsim.stage"]["v"], "converted")
            self.assertFalse(any("grhsim.partition" in op.get("attrs", {})
                                 for op in explicit["graphs"][0]["ops"]))
            self.assertEqual((self.work / "explicit-converted.json").read_bytes(),
                             (self.work / "explicit-pre-partition.json").read_bytes())
        identity = json.loads((model / "generation-identity.json").read_text())
        self.assertEqual(identity["kind"], "original-firrtl-mixed")
        self.assertTrue(identity["ingest_dependencies"])
        self.assertIn("source_0", identity["inputs"])
        self.assertIn("requested=" + ("prefer" if checkpoints else "off"),
                      identity["firrtl_node_policy"]["grhsim.nonsinkHintStats"])
        (self.work / "driver.cpp").write_text("""#include "model/grhsim_SimTop.hpp"
#include <cassert>
int main(){GrhSIM_SimTop m;m.init();for(unsigned a=0;a<256;++a){m.a=a;m.eval();assert(m.y==(((a^165)+3)&255));}}
""")
        (self.work / "run.mk").write_text(""".PHONY: run
run:
	$(MAKE) -C model CXXFLAGS='-std=c++20 -O1 -fno-strict-aliasing'
	$(CXX) -std=c++20 -O1 driver.cpp model/libgrhsim_SimTop.a -lz -o driver
	./driver
""")
        targets = ["run"]
        if checkpoints:
            # Flat load compacts temporary IDs before conversion, so compare
            # the resumed executable against the same exhaustive scoreboard.
            (self.work / "resumed-driver.cpp").write_text(
                (self.work / "driver.cpp").read_text().replace("model/grhsim_SimTop.hpp",
                                                              "resumed-model/grhsim_SimTop.hpp"))
            with (self.work / "run.mk").open("a") as stream:
                stream.write(""".PHONY: run-resumed
run-resumed:
	$(MAKE) -C resumed-model CXXFLAGS='-std=c++20 -O1 -fno-strict-aliasing'
	$(CXX) -std=c++20 -O1 resumed-driver.cpp resumed-model/libgrhsim_SimTop.a -lz -o resumed-driver
	./resumed-driver
""")
            targets.append("run-resumed")
        result = subprocess.run(["make", "--no-print-directory", "-f", "run.mk", *targets], cwd=self.work,
            env={**os.environ, "MAKEFLAGS": ""}, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
