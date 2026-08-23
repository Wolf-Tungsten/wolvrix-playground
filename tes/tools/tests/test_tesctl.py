#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

TESCTL = Path(__file__).resolve().parents[1] / "tesctl.py"
SPEC = importlib.util.spec_from_file_location("tesctl", TESCTL)
assert SPEC is not None and SPEC.loader is not None
tesctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tesctl)

FROZEN = ["--branchy-mux", "--scan-branch-hints"]


class AuditPhenotypeTest(unittest.TestCase):
    def test_exact_frozen_passes(self):
        self.assertIsNone(tesctl.audit_phenotype({}, FROZEN, list(FROZEN)))

    def test_declared_add_passes(self):
        self.assertIsNone(tesctl.audit_phenotype(
            {"emit_args_add": ["--my-knob"]}, FROZEN, FROZEN + ["--my-knob"]))

    def test_undeclared_knob_rejected(self):
        err = tesctl.audit_phenotype({}, FROZEN, FROZEN + ["--my-knob"])
        self.assertIsNotNone(err)

    def test_declared_but_not_passed_rejected(self):
        # r003 corr-e00073/74/75/76 的漏传场景
        err = tesctl.audit_phenotype({"emit_args_add": ["--my-knob"]}, FROZEN, list(FROZEN))
        self.assertIsNotNone(err)

    def test_remove_respected(self):
        self.assertIsNone(tesctl.audit_phenotype(
            {"emit_args_remove": ["--scan-branch-hints"]}, FROZEN, ["--branchy-mux"]))

    def test_missing_file_rejected(self):
        self.assertIsNotNone(tesctl.audit_phenotype(None, FROZEN, list(FROZEN)))


if __name__ == "__main__":
    unittest.main()
