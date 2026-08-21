#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock


EVALUATOR = Path(__file__).resolve().parents[1] / "evaluator.py"
SPEC = importlib.util.spec_from_file_location("grhsim_am_coremark_evaluator", EVALUATOR)
assert SPEC is not None and SPEC.loader is not None
evaluator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluator)


class SummarizeHostTimesTest(unittest.TestCase):
    def summarize(self, times: list[int]) -> dict:
        return evaluator.summarize_host_times(times, gap_ratio=1.12, min_cluster_reps=2)

    def test_r002_bimodal_sample_selects_fast_cluster(self) -> None:
        summary = self.summarize([295042, 389234, 295038, 362299, 343664])

        self.assertTrue(summary["bimodal"])
        self.assertEqual(summary["selection"], "fast_cluster")
        self.assertEqual(summary["median"], 295040)
        self.assertEqual(summary["raw_median"], 343664)
        self.assertEqual(summary["clusters"][0]["reps"], [295038, 295042])
        self.assertEqual(summary["clusters"][1]["reps"], [343664, 362299, 389234])

    def test_unimodal_sample_uses_all_reps(self) -> None:
        summary = self.summarize([302000, 300000, 304000, 301000, 303000])

        self.assertFalse(summary["bimodal"])
        self.assertEqual(summary["selection"], "all_reps")
        self.assertEqual(summary["median"], 302000)
        self.assertEqual(summary["clusters"][0]["count"], 5)

    def test_singleton_fast_outlier_does_not_form_cluster(self) -> None:
        summary = self.summarize([250000, 300000, 301000, 302000, 303000])

        self.assertFalse(summary["bimodal"])
        self.assertEqual(summary["median"], 301000)

    def test_two_well_populated_modes_split_at_largest_gap(self) -> None:
        summary = self.summarize([391000, 301000, 390000, 302000, 300000])

        self.assertTrue(summary["bimodal"])
        self.assertEqual(summary["median"], 301000)
        self.assertEqual([c["count"] for c in summary["clusters"]], [3, 2])

    def test_invalid_policy_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            evaluator.summarize_host_times([1, 2, 3], gap_ratio=1.0, min_cluster_reps=1)
        with self.assertRaises(ValueError):
            evaluator.summarize_host_times([1, 2, 3], gap_ratio=1.12, min_cluster_reps=0)

    def test_run_reps_completes_five_reps_across_two_batches(self) -> None:
        batches: list[int] = []

        def fake_batch(_emu: Path, _cwd: Path, _run_dir: Path,
                       start_idx: int, count: int, _cores: list[str]) -> list[dict]:
            batches.append(count)
            return [
                {
                    "rep": i,
                    "core": 12,
                    "rc": 0,
                    "host_ms": 300000 + i,
                    "instrCnt": 73584,
                    "cycleCnt": 49998,
                }
                for i in range(start_idx, start_idx + count)
            ]

        with mock.patch.object(evaluator, "_run_rep_batch", side_effect=fake_batch):
            result = evaluator.run_reps(Path("/fake/emu"), Path("/fake/run"))

        self.assertEqual(batches, [3, 2])
        self.assertEqual(len(result["reps"]), 5)
        self.assertEqual(result["host_ms"]["selection"], "all_reps")


if __name__ == "__main__":
    unittest.main()
