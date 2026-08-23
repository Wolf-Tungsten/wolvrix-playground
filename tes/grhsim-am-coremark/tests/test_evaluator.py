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


def fake_reps(start, count, times):
    # times 是本批次自己的列表（批内下标从零起）；start 是全局 rep 序号
    return [{"rep": i, "core": 12, "rc": 0, "host_ms": times[i - start],
             "instrCnt": 73584, "cycleCnt": 49998}
            for i in range(start, start + count)]


class ClusterRepsTest(unittest.TestCase):
    def test_bimodal_split(self):
        cl = evaluator.cluster_reps([295000, 389000, 296000], 1.15)
        self.assertEqual([[0, 2], [1]], cl)  # 按簇中位升序，快簇在前

    def test_unimodal_stays_one(self):
        self.assertEqual([[0, 1, 2]], evaluator.cluster_reps([295000, 297000, 296000], 1.15))

    def test_singleton_outlier_separate(self):
        # 簇按中位升序：singleton 离群簇 [0]（250s）排最前；adjudicate 会跳过它取 [1,2]
        self.assertEqual([[0], [1, 2]], evaluator.cluster_reps([250000, 295000, 296000], 1.15))


class AdjudicateRepsTest(unittest.TestCase):
    def test_fast_cluster_median(self):
        adj = evaluator.adjudicate_reps([295000, 389200, 295000, 390000], 1.15)
        self.assertEqual("bimodal", adj["state"])
        self.assertEqual([0, 2], adj["fast_cluster"])
        self.assertEqual(295000, adj["median"])
        self.assertAlmostEqual(342100, adj["median_all"], delta=1)

    def test_unimodal_plain_median(self):
        adj = evaluator.adjudicate_reps([295000, 296000, 297000], 1.15)
        self.assertEqual("unimodal", adj["state"])
        self.assertEqual(296000, adj["median"])

    def test_all_singletons_degraded(self):
        adj = evaluator.adjudicate_reps([250000, 300000, 390000], 1.15)
        self.assertEqual("degraded", adj["state"])
        self.assertEqual(250000, adj["median"])  # 取最快簇，保守


class AdaptiveRepProtocolTest(unittest.TestCase):
    def run_with(self, batches_times):
        calls = []

        def fake_batch(_emu, _cwd, _run_dir, start_idx, count, _cores):
            calls.append(count)
            return fake_reps(start_idx, count, batches_times[len(calls) - 1])

        with mock.patch.object(evaluator, "_run_rep_batch", side_effect=fake_batch):
            with mock.patch.dict(evaluator.EVAL_CFG, {}, clear=False):
                return evaluator.run_reps(Path("/fake/emu"), Path("/fake/run")), calls

    def test_unimodal_stops_at_three(self):
        result, calls = self.run_with([[250000, 251000, 252000]])
        self.assertEqual([3], calls)
        self.assertEqual("unimodal", result["host_ms"]["state"])
        self.assertEqual(251000, result["host_ms"]["median"])
        self.assertFalse(result["noisy"])

    def test_bimodal_extends_to_reps_max(self):
        # 双峰在加跑后不会消失（同一进程放置抽签），一路扩到缺省 reps_max=9
        result, calls = self.run_with([[295000, 389000, 295000]] * 4)
        self.assertEqual([3, 3, 3], calls)
        self.assertEqual(len(result["reps"]), 9)
        self.assertEqual("bimodal", result["host_ms"]["state"])
        self.assertEqual(295000, result["host_ms"]["median"])


if __name__ == "__main__":
    unittest.main()
