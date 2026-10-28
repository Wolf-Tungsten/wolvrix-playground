import csv
from pathlib import Path
import tempfile
import unittest

from repcut_grhsim_phase_risk import compare_plans, load_plan


def _write_plan(root: Path, rows, summary_rows=()):
    root.mkdir(parents=True)
    with (root / "groups.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=(
            "part", "group", "active_id", "phase", "operations",
            "estimated_lines", "work", "group_mask", "value_rise_work",
            "value_fall_work"))
        writer.writeheader()
        writer.writerows(rows)
    if summary_rows:
        with (root / "summary.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=("part", "precision", "feature", "value"))
            writer.writeheader()
            writer.writerows(summary_rows)


def _row(part, group, work, mask):
    return {"part": f"inst_part_{part}", "group": str(group), "active_id": str(group),
            "phase": "compute", "operations": "1", "estimated_lines": "1",
            "work": str(work), "group_mask": str(mask), "value_rise_work": str(work),
            "value_fall_work": str(work)}


class PhaseRiskTest(unittest.TestCase):
    def test_phase_ledger_detects_destination_selective_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            baseline = root / "baseline"
            candidate = root / "candidate"
            _write_plan(baseline, [_row(1, 0, 100, 1), _row(2, 0, 100, 2)])
            _write_plan(candidate, [_row(1, 0, 60, 1), _row(2, 0, 140, 2)])
            report = compare_plans(baseline, candidate, 1, 2)
            self.assertEqual(report["focus"]["1"]["delta"]["total"], -40)
            self.assertEqual(report["focus"]["2"]["delta"]["fall"], 40)
            self.assertIn("destination_phase_work_increase", report["risk_flags"])
            self.assertIn("release_is_paired_with_destination_increase", report["risk_flags"])

    def test_unknown_and_coactivation_summary_are_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            baseline = root / "baseline"
            candidate = root / "candidate"
            rows = [_row(0, 0, 5, 1), _row(4, 0, 10, (1 << 63) | 3)]
            summary = [{"part": "inst_part_4", "precision": "whole",
                        "feature": "coactivation_extra_rise_work", "value": "7"}]
            _write_plan(baseline, rows, summary)
            summary[0]["value"] = "13"
            _write_plan(candidate, rows, summary)
            report = compare_plans(baseline, candidate, 0, 4)
            self.assertEqual(report["parts"]["4"]["baseline"]["unknown"], 10)
            self.assertEqual(report["parts"]["4"]["summary_delta"][
                "summary_coactivation_extra_rise_work"], 6)
            self.assertIn("destination_coactivation_extra_increase", report["risk_flags"])

    def test_non_compute_rows_do_not_enter_work_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            plan = Path(folder) / "plan"
            _write_plan(plan, [_row(0, 0, 10, 1), {**_row(0, 1, 99, 1), "phase": "event"}])
            loaded = load_plan(plan)
            self.assertEqual(loaded["parts"]["0"]["total"], 109)
            self.assertEqual(loaded["parts"]["0"]["compute_total"], 10)
            self.assertEqual(loaded["parts"]["0"]["noncompute"], 99)

    def test_unchanged_totals_do_not_hide_whole_phase_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rows = [_row(0, 0, 20, 3)]
            summary = [{"part": "inst_part_0", "precision": "whole",
                        "feature": "group_work_rise", "value": "5"}]
            _write_plan(root / "a", rows, summary)
            _write_plan(root / "b", rows, [{**summary[0], "value": "15"}])
            report = compare_plans(root / "a", root / "b")
            self.assertEqual(report["changed_parts"], ["0"])
            self.assertEqual(report["parts"]["0"]["delta"]["total"], 0)
            self.assertEqual(report["parts"]["0"]["summary_whole_delta"][
                "summary_whole_group_work_rise"], 10)

    def test_each_summary_precision_must_match_total(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rows = [_row(0, 0, 10, 1)]
            _write_plan(root / "a", rows)
            _write_plan(root / "b", rows, [
                {"part": "inst_part_0", "precision": "range",
                 "feature": "group_work_total", "value": "10"},
                {"part": "inst_part_0", "precision": "whole",
                 "feature": "group_work_total", "value": "11"}])
            with self.assertRaisesRegex(ValueError, "summary/group work mismatch"):
                compare_plans(root / "a", root / "b")

    def test_missing_partition_or_focus_is_not_zero_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _write_plan(root / "a", [_row(0, 0, 10, 1)])
            _write_plan(root / "b", [_row(1, 0, 10, 1)])
            with self.assertRaisesRegex(ValueError, "partition sets differ"):
                compare_plans(root / "a", root / "b")
            with self.assertRaisesRegex(ValueError, "absent from the plan"):
                compare_plans(root / "a", root / "a", 0, 8)

    def test_duplicate_groups_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "plan"
            _write_plan(root, [_row(3, 0, 10, 1), _row(3, 0, 10, 1)])
            with self.assertRaisesRegex(ValueError, "duplicate group"):
                load_plan(root)

    def test_unknown_only_is_not_inactive_or_credited_to_both_phases(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _write_plan(root / "a", [_row(0, 0, 10, 1 << 63), _row(1, 0, 5, 3)])
            _write_plan(root / "b", [_row(0, 0, 2, 1 << 63), _row(1, 0, 13, 3)])
            report = compare_plans(root / "a", root / "b", 0, 1)
            source = report["parts"]["0"]
            self.assertEqual(source["baseline"]["inactive"], 0)
            self.assertEqual(source["baseline"]["unknown_only"], 10)
            self.assertFalse(any(source["source_known_release"].values()))
            self.assertIn("source_release_has_no_resolved_phase_evidence", report["risk_flags"])
            self.assertEqual(report["status"], "pass")
            self.assertTrue(report["diagnostic_only"])


if __name__ == "__main__":
    unittest.main()
