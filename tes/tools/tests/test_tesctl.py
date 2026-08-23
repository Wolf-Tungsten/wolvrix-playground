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


class ReconGateTest(unittest.TestCase):
    def test_due_when_never(self):
        self.assertTrue(tesctl.recon_due({"steps_completed": 0}))

    def test_due_after_staleness(self):
        self.assertTrue(tesctl.recon_due({"steps_completed": 3, "last_recon_step": 1}))
        self.assertFalse(tesctl.recon_due({"steps_completed": 2, "last_recon_step": 1}))

    def _run_dict(self, t0_extra):
        t0 = {"id": "t0", "branch": "b", "steps_completed": 0,
              "tip": "x", "tip_eval_id": "e00001", "best": None}
        t0.update(t0_extra)
        return {"status": "active", "run_id": "r004",
                "config": {"search": {"C": 1, "L": 4, "K": 2}},
                "baseline_sides": ["am"], "baselines": {"am": {"eval_id": "e00001"}},
                "trajectories": [t0],
                "current_step": None, "round_summaries_done": []}

    def test_next_returns_recon_before_step(self):
        na = tesctl.compute_next_action(self._run_dict({}))
        self.assertEqual("recon", na["type"])
        self.assertEqual("t0", na["trajectory"])
        self.assertEqual("e00001", na["eval_id"])  # 无 winner 时回退 AM 基线 eval

    def test_step_after_recon(self):
        na = tesctl.compute_next_action(self._run_dict({"last_recon_step": 0}))
        self.assertEqual("step", na["type"])


class OutcomeClassifyTest(unittest.TestCase):
    def test_initial_when_no_parent(self):
        self.assertEqual("initial", tesctl.classify_outcome(-100.0, None, 0.03))

    def test_win_neutral_loss(self):
        self.assertEqual("win", tesctl.classify_outcome(-100.0, -110.0, 0.03))     # +9.1%
        self.assertEqual("neutral", tesctl.classify_outcome(-100.0, -101.0, 0.03)) # +1%
        self.assertEqual("loss", tesctl.classify_outcome(-110.0, -100.0, 0.03))


class MigrationSeatTest(unittest.TestCase):
    def test_round1_rejected(self):
        self.assertIsNotNone(tesctl.validate_migration(1, False))

    def test_round2_first_seat_ok(self):
        self.assertIsNone(tesctl.validate_migration(2, False))

    def test_second_seat_rejected(self):
        self.assertIsNotNone(tesctl.validate_migration(3, True))


if __name__ == "__main__":
    unittest.main()
