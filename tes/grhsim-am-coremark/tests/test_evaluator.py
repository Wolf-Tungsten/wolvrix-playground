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


class FixedRepProtocolTest(unittest.TestCase):
    def test_run_reps_completes_exactly_three_reps(self) -> None:
        batches: list[int] = []

        def fake_batch(_emu: Path, _cwd: Path, _run_dir: Path,
                       start_idx: int, count: int, _cores: list[str]) -> list[dict]:
            batches.append(count)
            return [
                {
                    "rep": i,
                    "core": 12,
                    "rc": 0,
                    "host_ms": [250000, 300000, 390000][i - 1],
                    "instrCnt": 73584,
                    "cycleCnt": 49998,
                }
                for i in range(start_idx, start_idx + count)
            ]

        with mock.patch.object(evaluator, "_run_rep_batch", side_effect=fake_batch):
            result = evaluator.run_reps(Path("/fake/emu"), Path("/fake/run"))

        self.assertEqual(batches, [3])
        self.assertEqual(len(result["reps"]), 3)
        self.assertEqual(result["host_ms"]["median"], 300000)
        self.assertTrue(result["noisy"])


if __name__ == "__main__":
    unittest.main()
