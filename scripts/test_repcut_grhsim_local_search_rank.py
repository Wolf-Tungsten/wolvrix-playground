#!/usr/bin/env python3
import csv
import copy
from pathlib import Path
import tempfile
import unittest

from repcut_grhsim_local_search_rank import load_eval_times, rank, structural_budget


class ProfileRankTest(unittest.TestCase):
    def test_accepted_arm_changes_the_critical_lane(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "parts.csv"
            with path.open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["record_type", "variant", "part_name", "eval_avg_us", "update_push_avg_us"])
                for arm, times in (("baseline", (40, 10)), ("candidate", (10, 30))):
                    for part, value in enumerate(times):
                        writer.writerow(["part_timing", arm, f"part_{part}", value, 2])
            old = load_eval_times(path)
            accepted = load_eval_times(path, "candidate")
            self.assertEqual(max(old, key=lambda p: old[p]["eval"]), 0)
            self.assertEqual(max(accepted, key=lambda p: accepted[p]["eval"]), 1)
            with self.assertRaisesRegex(ValueError, "no missing"):
                load_eval_times(path, "missing")

    def test_destination_summary_reports_the_slowest_destination(self):
        work = {
            "source": {"baseline": 10, "candidate": 5},
            "destinations": {"1": {"baseline": 10, "candidate": 20},
                             "2": {"baseline": 10, "candidate": 10}},
            "peak": {"baseline": 10, "candidate": 20},
            "total": {"baseline": 30, "candidate": 35},
        }
        candidate = {"name": "move", "source": 0, "destinations": [1, 2],
                     "moved_atoms": 2, "shape_score": 100,
                     **{metric: work for metric in ("grhsim_v1_recurring_work", "raw_operation_count",
                                                    "send_bytes", "send_calls", "receive_bytes",
                                                    "receive_calls", "piece_copies")}}
        timings = {0: {"eval": 20, "update": 2}, 1: {"eval": 8, "update": 1},
                   2: {"eval": 3, "update": 1}}
        row = rank({"candidates": [candidate]}, timings)["frontier"][0]
        self.assertEqual(row["predicted_destination_eval_us"], 16)
        self.assertEqual(row["predicted_max_eval_us"], 16)
        self.assertEqual(row["predicted_destination_eval_by_part_us"], {"1": 16, "2": 3})

    def test_smaller_payload_does_not_hide_more_calls(self):
        work = {"source": {"baseline": 10, "candidate": 5},
                "destination": {"baseline": 10, "candidate": 12},
                "peak": {"baseline": 10, "candidate": 12},
                "total": {"baseline": 20, "candidate": 17}}
        a = {"name": "fewer_bytes", "source": 0, "destination": 1,
             "moved_atoms": 1, "shape_score": 2,
             **{metric: copy.deepcopy(work) for metric in (
                 "grhsim_v1_recurring_work", "raw_operation_count", "piece_copies",
                 "send_bytes", "send_calls", "receive_bytes", "receive_calls")}}
        b = copy.deepcopy(a)
        b['name'] = 'fewer_calls'
        b['send_bytes']['total']['candidate'] = 18
        b['send_calls']['total']['candidate'] = 15
        t = {0: {'eval': 20, 'update': 1}, 1: {'eval': 1, 'update': 1}}
        r = rank({'candidates': [a, b]}, t)
        self.assertEqual({x['name'] for x in r['frontier']}, {'fewer_bytes', 'fewer_calls'})
        budget = [{'feature': 'send_calls', 'scope': 'sum', 'max_change_percent': -20}]
        guarded = rank({'candidates': [a, b]}, t, budget_rules=budget)
        self.assertEqual([x['name'] for x in guarded['frontier']], ['fewer_calls'])
        self.assertEqual([x['name'] for x in guarded['outside_budget']], ['fewer_bytes'])

    def test_guard_can_check_an_unmoved_sender(self):
        record = {'parts': {'7': {'send_calls': {'baseline': 100, 'candidate': 125}}}}
        result = structural_budget(record, [{'feature': 'send_calls', 'scope': 'part',
                                             'part': '7', 'max_change_percent': 0}])
        self.assertFalse(result['within_budget'])

    def test_transfer_layout_scope_is_a_generic_ranking_objective(self):
        work = {"source": {"baseline": 10, "candidate": 5},
                "destination": {"baseline": 10, "candidate": 8},
                "peak": {"baseline": 10, "candidate": 10},
                "total": {"baseline": 20, "candidate": 20}}
        common = {metric: copy.deepcopy(work) for metric in (
            "grhsim_v1_recurring_work", "raw_operation_count", "send_bytes",
            "send_calls", "receive_bytes", "receive_calls", "piece_copies")}
        narrow = {"name": "narrow", "source": 0, "destination": 1,
                  "moved_atoms": 1, "shape_score": 1,
                  "non_endpoint_impact_parts": [2], "direct_impact_parts": [0, 1, 2],
                  **copy.deepcopy(common)}
        broad = copy.deepcopy(narrow)
        broad["name"] = "broad"
        broad["non_endpoint_impact_parts"] = [2, 3]
        result = rank({"candidates": [narrow, broad]},
                      {0: {"eval": 20, "update": 1}, 1: {"eval": 1, "update": 1},
                       2: {"eval": 2, "update": 1}, 3: {"eval": 3, "update": 1}})
        self.assertEqual(result["frontier"][0]["name"], "narrow")
        self.assertEqual(result["frontier"][0]["candidate_non_endpoint_impact_count"], 1)


if __name__ == "__main__":
    unittest.main()
