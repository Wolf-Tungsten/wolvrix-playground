"""F17 evidence must preserve observed fused CPU boundaries and the frozen budget."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import compare_f17_storage_perf as perf


class StoragePerfTests(unittest.TestCase):
    def stages(self, fused=False):
        names = (perf.JOINT, perf.FLATTEN) if fused else perf.STAGES
        return [{"name": name, "start_ns": 10 * i + 1, "end_ns": 10 * i + 9}
                for i, name in enumerate(names)]

    def test_windows_do_not_split_fused_endpoint(self):
        spans, selected, quality = perf.stage_layout(self.stages(True))
        self.assertEqual(set(spans), {perf.JOINT, perf.FLATTEN, "whole"})
        self.assertEqual(selected, (perf.JOINT, perf.FLATTEN))
        self.assertEqual(quality, (perf.JOINT, perf.FLATTEN, "whole"))
        self.assertNotIn("ingest", spans)
        self.assertNotIn("pre-flatten", spans)

    def test_partial_or_overlapping_pipeline_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "all ten"):
            perf.stage_layout(self.stages()[:-2] + [self.stages()[-1]])
        stages = self.stages(True)
        stages[1]["start_ns"] = stages[0]["end_ns"] - 1
        with self.assertRaisesRegex(RuntimeError, "Invalid stage"):
            perf.stage_layout(stages)

    def run_fixture(self, fused):
        spans, selected, quality = perf.stage_layout(self.stages(fused))
        names = [name[3:] for name in (*perf.PREPASSES, perf.FLATTEN)]
        options = [{}, {}, {"semantics": "2state"}, {"guarded_writes": "2state"}, {}, {}, {}, {}, {}]
        timing = {"configuration": {"profile": False, "fused_prefix": fused},
                  "diagnostics": [], "post_ingest_stages": [
                      {"pass": name, "options": opt, "keep_declared_symbols": True, "diagnostics": []}
                      for name, opt in zip(names, options)]}

        def report(cost):
            return {"period_ns": cost * 2, "family_period_ns": dict.fromkeys(perf.FAMILIES, cost // 6),
                    "six_family_period_ns": cost, "unresolved_leaf_period_ns": 0,
                    "top20_leaf_rows": []}

        reports = {name: report(6) for name in spans}
        if fused:
            reports[perf.JOINT] = report(24)
            reports[perf.FLATTEN] = report(12)
        else:
            reports["ingest"] = report(48)
            reports["pre-flatten"] = report(48)
            reports[perf.FLATTEN] = report(48)
        return {"timing": timing, "manifest": {}, "selected": selected,
                "reports": reports, "record": {}, "snapshots": [], "quality": {}, "spans": spans}

    def compare_fixture(self, candidate):
        baseline = self.run_fixture(False)
        with patch.object(perf, "inspect_run", side_effect=[baseline, candidate]):
            return perf.compare(SimpleNamespace(baseline=Path("baseline"), candidate=Path("candidate"), timing=None))

    def test_joint_budget_compares_f16_sum_and_retains_quarter_limit(self):
        report = self.compare_fixture(self.run_fixture(True))
        self.assertTrue(report["analysis_integrity_verified"])
        self.assertTrue(report["budget_pass"])
        self.assertEqual(report["budget_scopes"], (perf.JOINT, perf.FLATTEN, "selected-stage-sum"))
        row = report["comparisons"][perf.JOINT]
        self.assertEqual((row["f16_ns"], row["candidate_ns"]), (96, 24))
        self.assertNotIn("ingest", report["comparisons"])
        self.assertNotIn("pre-flatten", report["comparisons"])
        self.assertNotIn("eight-prepass-body-sum", report["comparisons"])
        self.assertIn("ingest-pre-flatten", perf.markdown(report))

        candidate = self.run_fixture(True)
        candidate["reports"][perf.JOINT]["family_period_ns"]["mi_new"] += 1
        candidate["reports"][perf.JOINT]["six_family_period_ns"] += 1
        self.assertFalse(self.compare_fixture(candidate)["budget_pass"])

    def test_legacy_run_keeps_individual_stage_budget(self):
        candidate = self.run_fixture(False)
        for row in candidate["reports"].values():
            row["family_period_ns"] = {key: value // 4 for key, value in row["family_period_ns"].items()}
            row["six_family_period_ns"] = sum(row["family_period_ns"].values())
        report = self.compare_fixture(candidate)
        self.assertEqual(report["budget_scopes"], (*perf.SELECTED, "selected-stage-sum"))
        self.assertIn("eight-prepass-body-sum", report["comparisons"])


if __name__ == "__main__":
    unittest.main()
