#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

PHI = Path(__file__).resolve().parents[1] / "phi.py"
SPEC = importlib.util.spec_from_file_location("phi", PHI)
assert SPEC is not None and SPEC.loader is not None
phi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(phi)


def entry(eval_id, step, score, parents=None):
    return {"kind": "candidate", "run": "r004", "trajectory": "t0", "step": step,
            "candidate": 1, "eval_id": eval_id, "status": "ok", "score": score,
            "committed": True, "proposal_nodes": parents or []}


class NeutralDownweightTest(unittest.TestCase):
    def test_neutral_uses_parent_score_in_norm(self):
        with tempfile.TemporaryDirectory() as td:
            task = Path(td)
            (task / "state").mkdir()
            lines = [
                {"kind": "baseline-am", "run": "r004", "eval_id": "e00001", "score": -364.0},
                entry("e00002", 1, -229.0),
                {"kind": "commit-marker", "run": "r004", "trajectory": "t0", "step": 1,
                 "eval_id": "e00002", "committed": True, "outcome": "win"},
                # e00003 名义分略高于父（噪声漂移），outcome=neutral
                entry("e00003", 2, -226.0, parents=["e00002"]),
                {"kind": "commit-marker", "run": "r004", "trajectory": "t0", "step": 2,
                 "eval_id": "e00003", "committed": True, "outcome": "neutral"},
                entry("e00004", 3, -220.0, parents=["e00003"]),
                {"kind": "commit-marker", "run": "r004", "trajectory": "t0", "step": 3,
                 "eval_id": "e00004", "committed": True, "outcome": "win"},
            ]
            (task / "state" / "ledger.jsonl").write_text(
                "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
            phi.TASK_DIR = task
            S, _rej, _fail, outcomes = phi.trajectory_nodes("r004", "t0")
            self.assertEqual({"e00002": "win", "e00003": "neutral", "e00004": "win"}, outcomes)
            eff = phi.effective_scores(S, outcomes)
            # e00003 的归一化输入 = 前驱 e00002 的 -229，而非名义 -226
            self.assertEqual(-229.0, eff["e00003"])
            self.assertEqual(-220.0, eff["e00004"])


if __name__ == "__main__":
    unittest.main()
