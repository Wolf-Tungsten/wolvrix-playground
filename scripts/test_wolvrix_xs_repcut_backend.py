#!/usr/bin/env python3

import contextlib
import io
import os
from pathlib import Path
import runpy
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
        self.assertEqual(reg_to_mem["profitability_filter"], "none")

    def test_explicit_transform_choices_are_preserved(self):
        calls = self.run_flow(
            "grhsim", XS_REPCUT_COST_MODEL="verilator-v1",
            XS_REPCUT_REG_TO_MEM_PROFITABILITY_FILTER="verilator-v1",
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


if __name__ == "__main__":
    unittest.main()
