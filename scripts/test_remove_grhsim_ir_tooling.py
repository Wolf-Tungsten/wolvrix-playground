"""Exercise retired-option rejection and retained simulation controls."""

import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from grhsim_flow import RETIRED_OPTIONS, validate_environment
from check_remove_grhsim_ir import cpp_issues, python_issues
from grhsim_declared_pack_census import declared_names
from grhsim_grh_reader import graph_snapshot
import reemit_grhsim
import wolvrix_hdlbits_grhsim
import wolvrix_xs_grhsim


ROOT = Path(__file__).resolve().parents[1]


class ToolingTest(unittest.TestCase):
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
                      "xs_grhsim", "xs_grhsim_reemit", "xs_firrtl_grhsim"):
            with self.subTest(entry=entry):
                self.assertRegex(makefile, rf"(?m)^{entry}:.*\bcheck_remove_grhsim_ir_options\b")

    def test_make_reemit_forwards_explicit_controls(self):
        env = {k: v for k, v in os.environ.items()
               if k not in RETIRED_OPTIONS and k not in ("MAKEFLAGS", "MFLAGS")}
        env["WOLF_ENV_SOURCED"] = "1"
        result = subprocess.run(
            ["make", "--no-print-directory", "-n", "reemit_grhsim", "SKIP_PY_INSTALL=1",
             "GRHSIM_REEMIT_OVERWRITE=1", "GRHSIM_REEMIT_MEM_ENABLE_BITMAP=off",
             "GRHSIM_REEMIT_MAX_OUTPUT_FILE_BYTES=34359738368",
             "GRHSIM_REEMIT_MEM_WRITE_ACTIVATE=on-change"],
            cwd=ROOT, env=env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--mem-write-activate "on-change"', result.stdout)
        self.assertIn('--mem-enable-bitmap "off"', result.stdout)
        self.assertIn('--max-output-file-bytes "34359738368"', result.stdout)
        self.assertIn("--overwrite", result.stdout)

    def test_retained_controls(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            args = wolvrix_xs_grhsim.parse_args(
                ["rtl.f", "top", "flat.json", "graph.json", "roundtrip.json", "read_args.txt",
                 "--mem-enable-bitmap", "off"])
        self.assertEqual(args.mem_enable_bitmap, "off")
        with mock.patch.dict(os.environ, {
            "XS_GRHSIM_SEMANTIC_NODES": "1", "XS_GRHSIM_MAX_SUPERNODE_NODES": "17",
            "XS_GRHSIM_SEGMENT_PENALTY": "3",
            "XS_GRHSIM_SINK_GUARD_MIN": "6",
        }, clear=True):
            options = wolvrix_xs_grhsim.default_flow_options()
        self.assertEqual((options.semantic_nodes, options.max_supernode_nodes,
                          options.segment_penalty, options.enable_guard_min_size), (True, 17, 3, 6))

    def test_pre_simplify_dump_is_scoped_to_sv(self):
        base = ["rtl.f", "top", "flat.json", "graph.json", "roundtrip.json", "read_args.txt"]
        dump = ["--dump-pre-simplify-json", "before-simplify.json"]
        with mock.patch.dict(os.environ, {}, clear=True):
            args = wolvrix_xs_grhsim.parse_args(base + dump)
            self.assertEqual(args.dump_pre_simplify_json, Path("before-simplify.json"))
            self.assertIsNone(args.sources_manifest)
            error = io.StringIO()
            with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as status:
                wolvrix_xs_grhsim.parse_args(base + ["--sources-manifest", "sources.json"] + dump)
            self.assertEqual(status.exception.code, 2)
            self.assertIn("only supported by the SV route", error.getvalue())
            self.assertIn("canonical FIRRTL has no simplify stage", error.getvalue())

    def test_retired_cli_controls(self):
        entries = (
            (wolvrix_xs_grhsim.parse_args,
             ["rtl.f", "top", "flat.json", "graph.json", "roundtrip.json", "read_args.txt"]),
            (reemit_grhsim.parse_args, ["--model", "graph.json", "--flow", str(ROOT / "ptmp/remove-grhsim-ir/options")]),
        )
        options = (
            ["--max-node-work", "128"], ["--max-supernode-work", "128"],
            ["--max-op-in-compute-supernode", "128"], ["--fuse-leaves"],
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
