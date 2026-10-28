#!/usr/bin/env python3

import contextlib
import io
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("wolvrix_xs_repcut.py")


class RepCutBackendTest(unittest.TestCase):
    def run_flow(self, backend=None, **options):
        calls = []

        class FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def __getattr__(self, name):
                return lambda *args, **kwargs: calls.append((name, args, kwargs))

        env = {key: value for key, value in os.environ.items()
               if not key.startswith("XS_REPCUT_")}
        env.update(options)
        if backend is not None:
            env["XS_REPCUT_BACKEND"] = backend
        with tempfile.TemporaryDirectory(prefix="wolvrix-repcut-backend-") as tmp:
            output = Path(tmp)
            args = [str(SCRIPT), str(SCRIPT), str(output / "out.json"),
                    str(output / "work"), "info", str(output / "package")]
            with patch.dict(sys.modules, {"wolvrix": types.SimpleNamespace(Session=FakeSession)}), \
                    patch.dict(os.environ, env, clear=True), \
                    patch.object(sys, "argv", args), \
                    contextlib.redirect_stderr(io.StringIO()):
                runpy.run_path(str(SCRIPT), run_name="__main__")
        return calls

    def test_default_and_explicit_verilator_are_unchanged(self):
        for backend in (None, "verilator"):
            with self.subTest(backend=backend):
                calls = self.run_flow(backend)
                self.assertEqual(
                    [name for name, _, _ in calls if name.startswith("emit_")],
                    ["emit_sv", "emit_verilator_repcut_package"],
                )
                repcut = next(kwargs for name, args, kwargs in calls
                              if name == "run_pass" and args == ("repcut",))
                reg_to_mem = next(kwargs for name, args, kwargs in calls
                                  if name == "run_pass" and args == ("reg-to-mem",))
                self.assertEqual(repcut["cost_model"], "verilator-v1")
                self.assertNotIn("initial_assignment", repcut)
                self.assertEqual(reg_to_mem["profitability_filter"], "verilator-v1")

    def test_grhsim_is_homogeneous_and_uses_backend_neutral_defaults(self):
        calls = self.run_flow("grhsim")
        self.assertEqual(
            [name for name, _, _ in calls if name.startswith("emit_")],
            ["emit_grhsim_repcut_package"],
        )
        repcut = next(kwargs for name, args, kwargs in calls
                      if name == "run_pass" and args == ("repcut",))
        reg_to_mem = next(kwargs for name, args, kwargs in calls
                          if name == "run_pass" and args == ("reg-to-mem",))
        self.assertEqual(repcut["cost_model"], "legacy")
        self.assertNotIn("initial_assignment", repcut)
        self.assertEqual(reg_to_mem["profitability_filter"], "none")

    def test_explicit_transform_choices_are_preserved(self):
        calls = self.run_flow(
            "grhsim", XS_REPCUT_COST_MODEL="verilator-v1",
            XS_REPCUT_REG_TO_MEM_PROFITABILITY_FILTER="verilator-v1",
            XS_REPCUT_INITIAL_ASSIGNMENT="solver",
            XS_REPCUT_MEMORY_WRITE_COALESCE="0",
        )
        passes = [(args[0], kwargs) for name, args, kwargs in calls if name == "run_pass"]
        self.assertEqual([name for name, _ in passes], ["repcut", "reg-to-mem"])
        self.assertEqual(passes[0][1]["cost_model"], "verilator-v1")
        self.assertEqual(passes[1][1]["profitability_filter"], "verilator-v1")

    def test_mixed_and_unknown_backends_are_rejected(self):
        for backend in ("verilator,grhsim", "unknown"):
            with self.subTest(backend=backend):
                with self.assertRaisesRegex(RuntimeError, "XS_REPCUT_BACKEND"):
                    self.run_flow(backend)

    def test_grhsim_solver_fallback_remains_explicit(self):
        before = self.run_flow("grhsim", XS_REPCUT_INITIAL_ASSIGNMENT="solver", XS_REPCUT_COST_MODEL="legacy")
        after = self.run_flow("grhsim", XS_REPCUT_INITIAL_ASSIGNMENT="solver", XS_REPCUT_COST_MODEL="grhsim-v1")
        before_passes = [(args, kwargs) for name, args, kwargs in before if name == "run_pass"]
        after_passes = [(args, kwargs) for name, args, kwargs in after if name == "run_pass"]
        self.assertEqual(before_passes[0][1]["cost_model"], "legacy")
        self.assertEqual(after_passes[0][1]["cost_model"], "grhsim-v1")
        after_passes[0][1]["cost_model"] = "legacy"
        before_passes[0][1].pop("work_dir")
        after_passes[0][1].pop("work_dir")
        self.assertEqual(before_passes, after_passes)

    def test_initial_assignment_is_grhsim_only_and_preserves_postpasses(self):
        before = self.run_flow("grhsim", XS_REPCUT_COST_MODEL="grhsim-v1")
        after = self.run_flow("grhsim", XS_REPCUT_INITIAL_ASSIGNMENT="grhsim-terminal-v1")
        first = [(args, kwargs) for name, args, kwargs in before if name == "run_pass"]
        second = [(args, kwargs) for name, args, kwargs in after if name == "run_pass"]
        self.assertNotIn("initial_assignment", first[0][1])
        self.assertEqual(second[0][1].pop("initial_assignment"), "grhsim-terminal-v1")
        self.assertEqual(second[0][1].pop("initial_core_imbalance_factor"), "0.05")
        first[0][1].pop("work_dir")
        second[0][1].pop("work_dir")
        self.assertEqual(first, second)
        with self.assertRaisesRegex(RuntimeError, "XS_REPCUT_BACKEND=grhsim"):
            self.run_flow("verilator", XS_REPCUT_INITIAL_ASSIGNMENT="grhsim-terminal-v1")

    def test_make_defaults_and_exported_initial_options_match_script(self):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("XS_REPCUT_", "MAKE"))}
        probe = (
            ".PHONY: repcut-config-probe\n"
            "repcut-config-probe:\n"
            "\t@printf '%s\\n' '$(XS_REPCUT_COST_MODEL)' "
            '"$$XS_REPCUT_INITIAL_ASSIGNMENT" "$$XS_REPCUT_INITIAL_CORE_IMBALANCE_FACTOR"\n'
        )
        for backend, initial, expected in (
            ("verilator", None, ["verilator-v1", "solver", "0.05"]),
            ("grhsim", None, ["legacy", "solver", "0.05"]),
            ("grhsim", "grhsim-terminal-v1", ["grhsim-v1", "grhsim-terminal-v1", "0.05"]),
            ("grhsim", "grhsim-terminal-state-v1", ["grhsim-v1", "grhsim-terminal-state-v1", "0.05"]),
            ("grhsim", "solver", ["legacy", "solver", "0.05"]),
        ):
            with self.subTest(backend=backend, initial=initial):
                command = ["make", "-s", "--no-print-directory", "-f", "Makefile", "-f", "-",
                           "repcut-config-probe", "SKIP_WOLF_ENV_CHECK=1", f"XS_REPCUT_BACKEND={backend}"]
                if initial is not None:
                    command.append(f"XS_REPCUT_INITIAL_ASSIGNMENT={initial}")
                result = subprocess.run(command, cwd=SCRIPT.parent.parent, env=env, input=probe,
                                        text=True, capture_output=True, check=True)
                self.assertEqual(result.stdout.splitlines(), expected)


if __name__ == "__main__":
    unittest.main()
