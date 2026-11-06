"""Validate the explicit mixed input route and its dependency boundary."""

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
from wolvrix_xs_grhsim import GRH_PIPELINE, grh_pipeline, read_source_manifest

ROOT = Path(__file__).resolve().parents[1]


class XsFirrtlWorkflowTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "ptmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="xs-firrtl-", dir=ROOT / "ptmp")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.firrtl = self.work / "SimTop.fir"
        self.firrtl.write_text("FIRRTL version 6.0.0\ncircuit SimTop :\n  public module SimTop :\n    skip\n")

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

    def test_lower_threads_is_published_in_manifest(self):
        manifest = create_manifest(self.firrtl, top="SimTop", lower_threads=4)
        self.assertEqual(manifest["firrtl_options"]["lower_threads"], 4)
        with self.assertRaisesRegex(ValueError, "positive integer"):
            create_manifest(self.firrtl, top="SimTop", lower_threads=0)
        with self.assertRaisesRegex(ValueError, "positive integer"):
            create_manifest(self.firrtl, top="SimTop", lower_threads=True)

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
            "XS_SIM_MAX_CYCLE=100000"], cwd=ROOT,
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
            "XS_FIRRTL_SV_SOURCES=", f"PYTHON={sys.executable}", f"XS_LOG_DIR={self.work / 'logs'}"], cwd=ROOT,
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
        (rtl / "time.log").write_text("firtool --preserve-aggregate=all\nExit status: 0\n")
        result = subprocess.run(["make", "--no-print-directory", "xs_ref_emu",
            f"XS_ROOT={xs}", f"XS_RTL_BUILD={rtl}", f"XS_REF_BUILD={self.work / 'ref'}",
            f"XS_LOG_DIR={self.work / 'logs'}"], cwd=ROOT,
            env={**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": ""},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertIn("mock-reference-build-failure", result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_generation_hard_deadline_and_exit_status(self):
        real_timeout = shutil.which("timeout")
        self.assertIsNotNone(real_timeout)
        for mode, status in (("success", 0), ("failure", 7), ("blocked", 137),
                             ("ignore-term", 137), ("override-deadline", 137)):
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
                deadline = "40m" if mode == "override-deadline" else "20m"
                shim.write_text(f"#!{sys.executable}\nimport json, os, sys\nfrom pathlib import Path\n"
                    f"assert sys.argv[1:3] == ['--signal=KILL', {deadline!r}], sys.argv\n"
                    f"assert sys.argv[3:5] == {[sys.executable, str(script)]!r}, sys.argv\n"
                    f"with Path({str(invocations)!r}).open('a') as log: log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                    f"os.execv({real_timeout!r}, [{real_timeout!r}, '--signal=KILL', '1s', *sys.argv[3:]])\n")
                shim.chmod(0o755)
                logs = work / "logs"
                result = subprocess.run(["make", "--no-print-directory", "xs_firrtl_grhsim_emu",
                    f"XS_ROOT={work / 'xiangshan'}", f"XS_FIRRTL_BUILD={flow}",
                    f"XS_FIRRTL_INPUT={self.firrtl}", f"XS_GRHSIM_SCRIPT={script}",
                    "XS_FIRRTL_SV_SOURCES=", "SKIP_PY_INSTALL=1", "RUN_ID=deadline",
                    f"PYTHON={sys.executable}", f"XS_LOG_DIR={logs}",
                    *(["XS_FIRRTL_GENERATION_TIMEOUT=40m"] if mode == "override-deadline" else [])], cwd=ROOT,
                    env={**os.environ, "WOLF_ENV_SOURCED": "1", "MAKEFLAGS": "",
                        "PATH": str(shim_dir) + os.pathsep + os.environ["PATH"]},
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
                self.assertIn("mock-generation-started", result.stdout)
                calls = [json.loads(line) for line in invocations.read_text().splitlines()]
                self.assertEqual(len(calls), 1)
                self.assertIn("--sources-manifest", calls[0])
                self.assertIn("--emit-cpp-dir", calls[0])
                self.assertIn("mock-generation-started", (logs / "xs_firrtl_grhsim_deadline.log").read_text())
                self.assertEqual(result.returncode, 0 if status == 0 else 2, result.stdout)
                if status:
                    self.assertIn(f"Error {status}", result.stdout)
                self.assertEqual(finished.exists(), status == 0, result.stdout)
                self.assertEqual(built.exists(), status == 0, result.stdout)

    def test_dependency_graph_excludes_sv_generation(self):
        result = subprocess.run(["make", "--no-print-directory", "-qp", "xs_firrtl_grhsim",
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
        for target in ("xs_firrtl_inputs", "xs_firrtl_grhsim", "xs_firrtl_grhsim_emu",
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
        command = [sys.executable, str(ROOT / "scripts/wolvrix_xs_grhsim.py"),
            str(manifest), "SimTop", str(self.work / "flat.json"), str(final),
            str(self.work / "roundtrip.json"), str(manifest), "off",
            "--sources-manifest", str(manifest), "--emit-cpp-dir", str(model),
            "--firrtl-nodes", "prefer" if checkpoints else "off", "--max-supernode-nodes", "1"]
        if not checkpoints:
            command += ["--no-store-grh-checkpoints", "--no-roundtrip-verify",
                "--simplify", "--simplify-max-rounds", "1",
                "--no-pack-bit-registers", "--no-recover-masked-or", "--no-phase-simplify",
                "--no-clone-shared-compute", "--firrtl-node-cse", "off",
                "--cost-model", "bytes", "--no-readable-names",
                "--no-readable-dump", "--no-source-comments",
                "--dump-post-conversion-json", str(self.work / "explicit-converted.json")]
        result = subprocess.run(command, cwd=ROOT,
            env={**os.environ, "XS_GRHSIM_PIPELINE_PROFILE": "full" if checkpoints else "bringup"},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, 0, result.stdout)
        for name in ("flat.json", "final.json", "roundtrip.json"):
            self.assertEqual((self.work / name).exists(), checkpoints)
        self.assertTrue((self.work / "final.generation-identity.json").is_file())
        if not checkpoints:
            self.assertFalse((model / "grhsim.txt").exists())
            explicit = json.loads((self.work / "explicit-converted.json").read_text())
            self.assertTrue(explicit["graphs"])
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
        result = subprocess.run(["make", "--no-print-directory", "-f", "run.mk", "run"], cwd=self.work,
            env={**os.environ, "MAKEFLAGS": ""}, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
