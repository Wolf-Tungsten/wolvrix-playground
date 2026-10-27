"""Exercise retired-option rejection and retained simulation controls."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tarfile
import unittest
from unittest import mock

from grhsim_flow import RETIRED_OPTIONS, validate_environment
from check_remove_grhsim_ir import cpp_issues, python_issues
from compare_remove_grhsim_ir import approved_difference
from grhsim_declared_pack_census import declared_names
from grhsim_grh_reader import graph_snapshot
from remove_grhsim_ir_rob import runtime_sample
import remove_grhsim_ir_baseline as baseline_tools
import reemit_grhsim
import wolvrix_hdlbits_grhsim
import wolvrix_xs_grhsim


ROOT = Path(__file__).resolve().parents[1]


class ToolingTest(unittest.TestCase):
    def test_frozen_binding_checks_archive_headers_and_library(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "ptmp/remove-grhsim-ir") as temporary:
            base = Path(temporary); baseline = base / "baseline"; baseline.mkdir()
            archived = base / "archive"
            sources = {"wolvrix/include/core/grh.hpp": b"frozen header\n",
                       "wolvrix/app/pybind/wolvrix/__init__.py": b"frozen package\n",
                       "scripts/wolvrix_xs_grhsim_ir.py": b"frozen flow\n"}
            records = {".": {"files": {}}, "wolvrix": {"files": {}}}
            with tarfile.open(baseline / "source.tar.gz", "w:gz") as archive:
                for name, raw in sources.items():
                    path = archived / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
                    archive.add(path, arcname=name)
                    repo, key = ("wolvrix", name.removeprefix("wolvrix/")) if name.startswith("wolvrix/") else (".", name)
                    records[repo]["files"][key] = baseline_tools.digest(path)
            manifest = {"repositories": records}
            (baseline / "manifest.json").write_text(json.dumps(manifest))
            library = baseline / "frozen/wolvrix/build/libwolvrix-lib.so"
            library.parent.mkdir(parents=True); library.write_bytes(b"frozen library")
            (baseline / "inputs-supplement.json").write_text(json.dumps({"inputs": {
                "wolvrix/build/libwolvrix-lib.so": {"sha256": baseline_tools.digest(library)}}}))
            output = base / "binding"; baseline_tools.prepare_binding(baseline, output)
            self.assertEqual((output / "python/wolvrix/__init__.py").read_bytes(), sources["wolvrix/app/pybind/wolvrix/__init__.py"])
            self.assertEqual((output / "python/wolvrix/libwolvrix-lib.so").read_bytes(), library.read_bytes())
            self.assertEqual(len(json.loads((output / "source-identity.json").read_text())["source_sha256"]), 3)
            compiler_sources = {"wolvrix/CMakeLists.txt": b"set(WOLVRIX_LIB_SOURCES\n    lib/core/grh.cpp\n)\n",
                                "wolvrix/lib/core/grh.cpp": b"frozen implementation\n"}
            with tarfile.open(baseline / "source.tar.gz", "w:gz") as archive:
                for name, raw in {**sources, **compiler_sources}.items():
                    path = archived / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
                    archive.add(path, arcname=name)
                    repo, key = ("wolvrix", name.removeprefix("wolvrix/")) if name.startswith("wolvrix/") else (".", name)
                    records[repo]["files"][key] = baseline_tools.digest(path)
            records["wolvrix"]["submodules"] = "same dependencies\n"
            (baseline / "manifest.json").write_text(json.dumps(manifest))
            with mock.patch.object(baseline_tools, "command", return_value="same dependencies\n"):
                compiler = base / "compiler"
                baseline_tools.prepare_binding(baseline, compiler, rebuild_compiler=True)
                self.assertEqual((compiler / "compiler-sources.mk").read_text(), "FROZEN_COMPILER_SOURCES := lib/core/grh.cpp\n")
                self.assertFalse((compiler / "python/wolvrix/libwolvrix-lib.so").exists())
                identity = json.loads((compiler / "source-identity.json").read_text())
                self.assertEqual(identity["dependencies"], "same dependencies\n")
            with mock.patch.object(baseline_tools, "command", return_value="changed dependencies\n"):
                with self.assertRaisesRegex(RuntimeError, "dependency revisions changed"):
                    baseline_tools.prepare_binding(baseline, compiler, rebuild_compiler=True)
            with self.assertRaisesRegex(ValueError, "outside the baseline"):
                baseline_tools.prepare_binding(baseline, baseline / "binding")
            library.write_bytes(b"changed library")
            with self.assertRaisesRegex(RuntimeError, "Frozen shared library changed"):
                baseline_tools.prepare_binding(baseline, output)
            records["wolvrix"]["files"]["include/core/grh.hpp"] = "bad"
            (baseline / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError, "Frozen binding source changed"):
                baseline_tools.prepare_binding(baseline, output)
        makefile = (ROOT / "Makefile").read_text()
        smoke = next(line for line in makefile.splitlines() if "len(wolvrix.list_grhsim_passes())" in line)
        self.assertIn("$(PYTHON) -S -c", smoke)
        self.assertIn("pathlib.Path(wolvrix.__file__)", smoke)

    def test_frozen_xs_inputs_are_bound_and_remapped(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "ptmp/remove-grhsim-ir") as temporary:
            base = Path(temporary); baseline = base / "baseline"; frozen = baseline / "frozen"
            original = ROOT / "ptmp/test-frozen-xs"; relative = original.relative_to(ROOT)
            source = frozen / relative / "top.sv"; source.parent.mkdir(parents=True)
            source.write_text("module SimTop; endmodule\n")
            inputs = frozen / "ptmp/xs/grhsim-ir"; inputs.mkdir(parents=True)
            filelist = inputs / "xs_wolf.f"; filelist.write_text(str(original / "top.sv") + "\n")
            args = inputs / "wolvrix_read_args.txt"; args.write_text(f"-I\n{original}\n-D\nDIFFTEST\n")
            records = {str(path.relative_to(frozen)): {"sha256": baseline_tools.digest(path)} for path in (source, args)}
            (baseline / "inputs-supplement.json").write_text(json.dumps({"inputs": records}))
            (baseline / "manifest.json").write_text(json.dumps({"artifacts": {
                str(filelist.relative_to(baseline)): {"sha256": baseline_tools.digest(filelist)}}}))
            output = base / "candidate"
            baseline_tools.prepare_xs_inputs(baseline, output)
            self.assertEqual((output / "rtl.f").read_text(), str(source) + "\n")
            self.assertEqual((output / "read_args.txt").read_text(), f"-I\n{source.parent}\n-D\nDIFFTEST\n")
            with self.assertRaisesRegex(ValueError, "must not modify"):
                baseline_tools.prepare_xs_inputs(baseline, baseline / "candidate")
            source.write_text("changed")
            with self.assertRaisesRegex(RuntimeError, "Frozen XS input changed"):
                baseline_tools.prepare_xs_inputs(baseline, output)

    def test_runtime_probe_requires_exact_cycle_endpoint(self):
        row = "cycles=2000 checksum=123 init_seconds=0.1 run_seconds=1.2\n"
        self.assertEqual(runtime_sample(row, 2000)["checksum"], 123)
        for broken in (row.replace("cycles=2000", "cycles=1000"), row.replace("run_seconds=1.2", "run_seconds=1e999"),
                       row.replace("run_seconds=1.2", "run_seconds=-1.2"), row.replace("run_seconds=1.2", "run_seconds=0"),
                       "crashed\n" + row):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                runtime_sample(broken, 2000)

    def test_single_call_policy_only_approves_the_output_duplicate(self):
        effect = {"kind": "dpi", "function": "cpu_test_bit_abi", "values": [1, 3, 2]}
        difference = {"category": "effects", "old": [effect, effect], "new": [effect]}
        self.assertIsNotNone(approved_difference("dpi_bit_abi", difference, "single-original-call"))
        self.assertIsNone(approved_difference("dpi_bit_abi", difference, "strict"))
        self.assertIsNone(approved_difference("dpi_smoke", difference, "single-original-call"))
        self.assertIsNone(approved_difference("dpi_bit_abi", {**difference, "category": "outputs"}, "single-original-call"))
        self.assertIsNone(approved_difference("dpi_bit_abi", {**difference, "new": []}, "single-original-call"))
        changed = {**effect, "values": [1, 2, 2]}
        self.assertIsNone(approved_difference("dpi_bit_abi", {**difference, "new": [changed]}, "single-original-call"))

    def test_source_order_policy_only_approves_the_independent_call_swap(self):
        inc = {"kind": "dpi", "function": "cpu_test_inc", "values": [1, 2]}
        dbl = {"kind": "dpi", "function": "cpu_test_dbl", "values": [3, 6]}
        difference = {"category": "effects", "old": [dbl, inc], "new": [inc, dbl]}
        policy = "single-original-call-source-order"
        for name in ("dpi_smoke", "dpi_smoke_tu"):
            self.assertIsNotNone(approved_difference(name, difference, policy))
            self.assertIsNone(approved_difference(name, difference, "single-original-call"))
            self.assertIsNone(approved_difference(name, difference, "strict"))
        for changed in ({**difference, "category": "outputs"},
                        {**difference, "new": [inc]},
                        {**difference, "new": [inc, {**dbl, "values": [3, 7]}]},
                        {**difference, "old": [inc, dbl], "new": [dbl, inc]},
                        {**difference, "old": [dbl, inc, inc], "new": [inc, dbl, inc]},
                        {**difference, "old": [{**dbl, "kind": "task"}, inc]}):
            with self.subTest(changed=changed):
                self.assertIsNone(approved_difference("dpi_smoke", changed, policy))
        self.assertIsNone(approved_difference("random_function", difference, policy))
        bit = {"kind": "dpi", "function": "cpu_test_bit_abi", "values": [1, 3, 2]}
        self.assertIsNotNone(approved_difference("dpi_bit_abi", {"category": "effects", "old": [bit, bit], "new": [bit]}, policy))

    def test_graph_scoped_declared_symbols(self):
        first = {"symbol": "first", "ops": [], "vals": [], "declaredSymbols": ["q", "sub$x"]}
        second = {"symbol": "second", "ops": [], "vals": [], "declaredSymbols": ["q", "y"]}
        design = {"tops": ["first"], "graphs": [first, second], "declaredSymbols": []}
        self.assertEqual(declared_names(design), {"q", "sub$x"})
        self.assertEqual(declared_names(design, "second"), {"q", "y"})
        self.assertIs(graph_snapshot(design), first)
        self.assertEqual(declared_names(first), {"q", "sub$x"})
        self.assertEqual(declared_names({"strings": ["old"], "declaredSymbols": [1]}), {"old"})
        with self.assertRaisesRegex(ValueError, "explicit top"):
            declared_names({**design, "tops": ["first", "second"]})
        with self.assertRaisesRegex(ValueError, "exactly one GRH"):
            graph_snapshot(design, "missing")
        with self.assertRaisesRegex(ValueError, "textual"):
            declared_names({**first, "declaredSymbols": [1]})

    def test_production_audit_rejects_legacy_dependencies(self):
        for called in ("lower_grh_to_grhsim", "run_grhsim_pass", "emit_grhsim_cpu"):
            self.assertTrue(python_issues(f'session.{called}("old")', "entry.py"))
        self.assertFalse(python_issues('session.emit_grhsim_cpu_st_cpp(design="main")', "entry.py"))
        self.assertFalse(cpp_issues('// GrhSimModel is retired\n#include "core/grh.hpp"', "new.cpp"))
        self.assertTrue(cpp_issues('#include "grhsim/ir/model.hpp"', "old.cpp"))
        self.assertTrue(cpp_issues('GrhSimModel model;', "old.cpp"))
        for name in ("lower_grhsim", "run_grhsim_pipeline", "load_grhsim", "store_grhsim", "list_grhsim_passes"):
            self.assertTrue(python_issues(f"def {name}():\n    pass\n", "old_api.py"))
        self.assertTrue(cpp_issues("session.grhsimModels.clear();", "old.cpp"))
        self.assertTrue(cpp_issues("void py_session_lower_grhsim();", "old.cpp"))
        self.assertFalse(cpp_issues("transform::grhsim::GrhToGrhsimPass pass;", "new.cpp"))

    def test_retired_environment_including_empty_and_zero(self):
        validate_environment({})
        for name in RETIRED_OPTIONS:
            for value in ("", "0", "1"):
                with self.subTest(name=name, value=value):
                    with self.assertRaisesRegex(ValueError, name):
                        validate_environment({name: value})
        for entry in (wolvrix_xs_grhsim.parse_args, reemit_grhsim.parse_args,
                      wolvrix_hdlbits_grhsim.parse_args):
            with mock.patch.dict(os.environ, {"XS_WOLF_GRHSIM_IR_COMB_PACK": "0"}, clear=True):
                error = io.StringIO()
                with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as status:
                    entry(["--help"])
                self.assertEqual(status.exception.code, 2)
                self.assertIn("Retired GrhSIM options", error.getvalue())

    def test_make_rejects_all_retired_settings(self):
        env = {k: v for k, v in os.environ.items() if k not in RETIRED_OPTIONS and k != "MAKEFLAGS"}
        env["WOLF_ENV_SOURCED"] = "1"
        makefile = (ROOT / "Makefile").read_text()
        self.assertNotIn("XS_WOLF_GRHSIM_IR", makefile)
        self.assertNotIn("REMOVE_GRHSIM_IR_RETIRED_OPTIONS", makefile)
        for name in RETIRED_OPTIONS:
            for value in ("", "0"):
                with self.subTest(name=name, value=value):
                    result = subprocess.run(
                        ["make", "--no-print-directory", "-n", "check_remove_grhsim_ir_options", f"{name}={value}"],
                        cwd=ROOT, env=env, capture_output=True, text=True, check=False,
                    )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f"Retired GrhSIM option {name}", result.stderr)

    def test_make_rejects_retired_xs_wolf_namespace(self):
        env = {k: v for k, v in os.environ.items() if k != "MAKEFLAGS"}
        env["WOLF_ENV_SOURCED"] = "1"
        result = subprocess.run(
            ["make", "--no-print-directory", "-n", "check_remove_grhsim_ir_options",
             "XS_WOLF_FILELIST=old.f"],
            cwd=ROOT, env=env, capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Retired GrhSIM option XS_WOLF_FILELIST", result.stderr)

    def test_make_entry_guards(self):
        makefile = (ROOT / "Makefile").read_text()
        for entry in ("run_hdlbits_grhsim", "run_xs_bugcase_grhsim", "reemit_grhsim",
                      "xs_grhsim", "xs_grhsim_reemit", "generate_remove_grhsim_ir_rob"):
            with self.subTest(entry=entry):
                self.assertRegex(makefile, rf"(?m)^{entry}:.*\bcheck_remove_grhsim_ir_options\b")

    def test_make_reemit_forwards_explicit_controls(self):
        env = {k: v for k, v in os.environ.items()
               if k not in RETIRED_OPTIONS and k not in ("MAKEFLAGS", "MFLAGS")}
        env["WOLF_ENV_SOURCED"] = "1"
        for enabled in ("0", "1"):
            result = subprocess.run(
                ["make", "--no-print-directory", "-n", "reemit_grhsim", "SKIP_PY_INSTALL=1",
                 "GRHSIM_REEMIT_OVERWRITE=1", "GRHSIM_REEMIT_MEM_ENABLE_BITMAP=off",
                 "GRHSIM_REEMIT_MAX_OUTPUT_FILE_BYTES=34359738368",
                 "GRHSIM_REEMIT_MEM_WRITE_ACTIVATE=on-change",
                 f"GRHSIM_REEMIT_PACK_BIT_REGISTERS={enabled}", f"GRHSIM_REEMIT_MASKED_OR={enabled}"],
                cwd=ROOT, env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--mem-write-activate "on-change"', result.stdout)
            self.assertIn('--mem-enable-bitmap "off"', result.stdout)
            self.assertIn('--max-output-file-bytes "34359738368"', result.stdout)
            self.assertIn("--overwrite", result.stdout)
            for flag in ("pack-bit-registers", "recover-masked-or"):
                self.assertIn(f"--{'' if enabled == '1' else 'no-'}{flag}", result.stdout)
                self.assertNotIn(f"--{'no-' if enabled == '1' else ''}{flag}", result.stdout)

    def test_retained_controls(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            args = wolvrix_xs_grhsim.parse_args(
                ["rtl.f", "top", "flat.json", "graph.json", "roundtrip.json", "read_args.txt",
                 "--mem-enable-bitmap", "off", "--no-phase-simplify"])
        self.assertEqual(args.mem_enable_bitmap, "off")
        self.assertFalse(args.phase_simplify)
        with mock.patch.dict(os.environ, {
            "XS_GRHSIM_SEMANTIC_NODES": "1", "XS_GRHSIM_SEMANTIC_NODE_MAX_OP": "17",
            "XS_GRHSIM_COARSEN_MAX_OP": "53", "XS_GRHSIM_SEGMENT_PENALTY": "3",
            "XS_GRHSIM_SINK_GUARD_MIN": "6",
        }, clear=True):
            options = wolvrix_xs_grhsim.default_flow_options()
        self.assertEqual((options.semantic_nodes, options.max_node_work, options.max_supernode_work,
                          options.segment_penalty, options.enable_guard_min_size), (True, 17, 53, 3, 6))

    def test_retired_cli_controls(self):
        entries = (
            (wolvrix_xs_grhsim.parse_args,
             ["rtl.f", "top", "flat.json", "graph.json", "roundtrip.json", "read_args.txt"]),
            (reemit_grhsim.parse_args, ["--model", "graph.json", "--flow", str(ROOT / "ptmp/remove-grhsim-ir/options")]),
        )
        options = (
            ["--comb-pack"], ["--comb-pack-report", "old.json"], ["--select-state-stores"],
            ["--cpu-target-batch-count", "0"], ["--cpu-helper-max-estimated-lines", "128"],
            ["--cpu-chunk-max-estimated-lines", "128"], ["--cpu-unit-max-estimated-lines", "128"],
            ["--dump-post-lower-json", "old.json"], ["--remap"], ["--bitwise-muxes"],
            ["--mux-chain-fold"], ["--used-bits"], ["--canonicalize-compute"],
            ["--helper-max-estimated-lines", "128"],
        )
        with mock.patch.dict(os.environ, {}, clear=True):
            for parse, base in entries:
                for option in options:
                    with self.subTest(entry=parse.__module__, option=option[0]):
                        error = io.StringIO()
                        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as status:
                            parse(base + option)
                        self.assertEqual(status.exception.code, 2)
                        self.assertIn("unrecognized arguments", error.getvalue())

    def test_reemit_forwards_bitmap_as_boolean(self):
        work = ROOT / "ptmp/remove-grhsim-ir"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="tooling-", dir=work) as directory:
            for bitmap in ("off", "on"):
                argv = ["reemit", "--model", "unused.json", "--flow", directory, "--mem-enable-bitmap", bitmap]
                with mock.patch.dict(os.environ, {}, clear=True), mock.patch("sys.argv", argv), \
                     mock.patch.object(reemit_grhsim.wolvrix, "Session") as factory, \
                     mock.patch.object(reemit_grhsim, "finish_simulation_graph"), \
                     mock.patch.object(reemit_grhsim, "store_checkpoint"), \
                     mock.patch.object(reemit_grhsim, "capture_generation", return_value={}), \
                     mock.patch.object(reemit_grhsim, "emit_cpp") as emit, contextlib.redirect_stdout(io.StringIO()):
                    session = factory.return_value.__enter__.return_value
                    session.read_json_file.return_value = []
                    session.graph_metadata.return_value = {"symbol": "top", "metadata": {}}
                    self.assertEqual(reemit_grhsim.main(), 0)
                    self.assertIs(emit.call_args.kwargs["mem_enable_bitmap"], bitmap == "on")

    def test_reemit_skips_redundant_sink_checkpoint(self):
        work = ROOT / "ptmp/remove-grhsim-ir"
        work.mkdir(parents=True, exist_ok=True)
        metadata = {"grhsim.stage": "sink-partitioned", "grhsim.memMinBytes": "64"}
        with tempfile.TemporaryDirectory(prefix="tooling-", dir=work) as directory:
            for store in (False, True):
                argv = ["reemit", "--model", "unused.json", "--flow", directory]
                if store:
                    argv.append("--store-checkpoint")
                with mock.patch.dict(os.environ, {}, clear=True), mock.patch("sys.argv", argv), \
                     mock.patch.object(reemit_grhsim.wolvrix, "Session") as factory, \
                     mock.patch.object(reemit_grhsim, "finish_simulation_graph"), \
                     mock.patch.object(reemit_grhsim, "store_checkpoint") as checkpoint, \
                     mock.patch.object(reemit_grhsim, "capture_generation", return_value={}), \
                     mock.patch.object(reemit_grhsim, "emit_cpp"), contextlib.redirect_stdout(io.StringIO()):
                    session = factory.return_value.__enter__.return_value
                    session.read_json_file.return_value = []
                    session.graph_metadata.return_value = {"symbol": "top", "metadata": metadata}
                    self.assertEqual(reemit_grhsim.main(), 0)
                    self.assertEqual(checkpoint.called, store)


if __name__ == "__main__":
    unittest.main()
