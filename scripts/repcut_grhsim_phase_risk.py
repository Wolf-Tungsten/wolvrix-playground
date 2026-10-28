#!/usr/bin/env python3
"""Compare the phase-selective work exposed by two generated GrhSIM plans.

The partition objective currently sees aggregate graph work.  A generated plan
also records whether a compute group may run on the rising phase, falling phase, or
both.  Moving a group can therefore reduce the source aggregate while making a
destination execute more work on one lane (or activating a second lane).  This
module turns that information into a replayable backend-plan ledger.

It is deliberately a *diagnostic* and review aid.  It does not assign a magic
time coefficient, select a hand-written RTL signal, or change the partitioner.
The same input format is used for every generated plan, so a future evaluator
can attach this ledger before compiling a candidate.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


UNKNOWN = 1 << 63
PHASE_BITS = (("rise", 1), ("fall", 2))


def _number(text: str) -> int:
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"expected integer, got {text!r}") from exc


def _part_number(name: str) -> int:
    token = name.rsplit("_", 1)[-1]
    return _number(token)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError(f"empty CSV: {path}")
    return rows


def _empty_work() -> dict[str, int]:
    return {
        "total": 0,
        "compute_total": 0,
        "noncompute": 0,
        "rise": 0,
        "fall": 0,
        "both": 0,
        "unknown": 0,
        "unknown_only": 0,
        "other_context": 0,
        "known_rise": 0,
        "known_fall": 0,
        "exclusive_rise": 0,
        "exclusive_fall": 0,
        "coactive": 0,
        "inactive": 0,
    }


def _work_ledger(groups: Iterable[dict[str, str]]) -> tuple[dict[int, dict], dict[int, Counter]]:
    parts: dict[int, dict[str, int]] = defaultdict(_empty_work)
    masks: dict[int, Counter] = defaultdict(Counter)
    seen = set()
    for row in groups:
        part = _part_number(row["part"])
        key = part, row["group"]
        if key in seen:
            raise ValueError(f"duplicate group: {key}")
        seen.add(key)
        work = _number(row["work"])
        mask = _number(row["group_mask"])
        if work < 0 or mask < 0:
            raise ValueError("work and activity masks must be non-negative")
        item = parts[part]
        low = mask & 3
        item["total"] += work
        if row.get("phase") != "compute":
            # Commit/event work is part of the plan's aggregate group work,
            # but has no rising/falling compute-lane activity bit.
            item["noncompute"] += work
            continue
        item["compute_total"] += work
        if low & 1:
            item["rise"] += work
        if low & 2:
            item["fall"] += work
        if low == 3:
            item["both"] += work
            item["coactive"] += work
        elif low == 1:
            item["exclusive_rise"] += work
        elif low == 2:
            item["exclusive_fall"] += work
        elif mask == 0:
            item["inactive"] += work
        if mask & UNKNOWN:
            item["unknown"] += work
            if low == 0:
                item["unknown_only"] += work
        else:
            for name, bit in PHASE_BITS:
                if mask & bit:
                    item["known_" + name] += work
        if mask & ~(UNKNOWN | 3):
            item["other_context"] += work
        masks[part][str(mask)] += work
    return dict(parts), dict(masks)


def _summary_ledger(path: Path) -> dict[int, dict[str, int]]:
    summary = defaultdict(dict)
    summary_path = path / "summary.csv"
    if not summary_path.exists():
        return {}
    for row in _read_rows(summary_path):
        precision = row.get("precision")
        if precision not in {"whole", "range"}:
            continue
        feature = row.get("feature")
        if feature in {
            "coactivation_extra_rise_work",
            "coactivation_extra_fall_work",
            "group_work_total",
            "group_work_rise",
            "group_work_fall",
            "group_work_both",
            "group_work_unknown",
            "group_count_total",
            "group_count_rise",
            "group_count_fall",
            "group_count_both",
            "group_count_unknown",
        }:
            values = summary[_part_number(row["part"])]
            key = f"summary_{precision}_{feature}"
            if key in values:
                raise ValueError(f"duplicate summary feature: {row['part']}/{key}")
            value = _number(row["value"])
            if value < 0:
                raise ValueError("summary work and counts must be non-negative")
            values[key] = value
    # Preserve both analyses: their unknown contexts can differ substantially.
    # The aliases follow the existing range-based gate, not a probability model.
    for values in summary.values():
        features = set()
        for key in values:
            for prefix in ("summary_range_", "summary_whole_"):
                if key.startswith(prefix):
                    features.add(key.removeprefix(prefix))
        for feature in features:
            values["summary_" + feature] = values.get(
                "summary_range_" + feature,
                values.get("summary_whole_" + feature, 0),
            )
    return dict(summary)


def load_plan(plan: Path) -> dict:
    """Load a generated plan and retain both mask and summary ledgers."""
    plan = plan.resolve()
    groups, masks = _work_ledger(_read_rows(plan / "groups.csv"))
    summary = _summary_ledger(plan)
    all_parts = sorted(set(groups) | set(summary))
    rows = {}
    for part in all_parts:
        values = dict(_empty_work())
        values.update(groups.get(part, {}))
        values.update(summary.get(part, {}))
        rows[str(part)] = values
    return {
        "plan": str(plan),
        "parts": rows,
        "mask_work": {str(part): dict(sorted(counter.items(), key=lambda item: int(item[0])))
                      for part, counter in masks.items()},
    }


def _delta(before: dict, after: dict, keys: Iterable[str]) -> dict[str, int]:
    return {key: after.get(key, 0) - before.get(key, 0) for key in keys}


def _positive(values: dict[str, int], keys: Iterable[str]) -> dict[str, int]:
    return {key: max(0, values.get(key, 0)) for key in keys}


def _negative_release(values: dict[str, int], keys: Iterable[str]) -> dict[str, int]:
    return {key: max(0, -values.get(key, 0)) for key in keys}


def _summary_consistency_one(values: dict) -> dict:
    mismatches = {}
    available = False
    for precision in ("range", "whole"):
        summary_key = f"summary_{precision}_group_work_total"
        if summary_key not in values:
            continue
        available = True
        expected, actual = values["total"], values[summary_key]
        if expected != actual:
            mismatches[summary_key] = {"computed": expected, "summary": actual}
    return {"available": available, "mismatches": mismatches}


def _summary_consistency(before: dict, after: dict) -> dict:
    return {"baseline": _summary_consistency_one(before),
            "candidate": _summary_consistency_one(after)}


def compare_plans(baseline_plan: Path, candidate_plan: Path,
                  source_part: int | None = None,
                  destination_part: int | None = None) -> dict:
    baseline = load_plan(baseline_plan)
    candidate = load_plan(candidate_plan)
    if set(baseline["parts"]) != set(candidate["parts"]):
        raise ValueError("baseline and candidate partition sets differ")
    if (source_part is None) != (destination_part is None):
        raise ValueError("source and destination must be supplied together")
    if source_part is not None:
        if source_part == destination_part:
            raise ValueError("source and destination must differ")
        if any(str(part) not in baseline["parts"] for part in (source_part, destination_part)):
            raise ValueError("source or destination is absent from the plan")
    parts = sorted(set(baseline["parts"]) | set(candidate["parts"]), key=int)
    work_keys = tuple(_empty_work())
    rows = {}
    for part_text in parts:
        old = baseline["parts"].get(part_text, _empty_work())
        new = candidate["parts"].get(part_text, _empty_work())
        delta = _delta(old, new, work_keys)
        summary_delta = _delta(
            old, new,
            ("summary_coactivation_extra_rise_work",
             "summary_coactivation_extra_fall_work"),
        )
        summary_range_delta = _delta(
            old, new,
            ("summary_range_group_work_total",
             "summary_range_group_work_rise",
             "summary_range_group_work_fall",
             "summary_range_group_work_both",
             "summary_range_group_work_unknown",
             "summary_range_coactivation_extra_rise_work",
             "summary_range_coactivation_extra_fall_work"),
        )
        summary_whole_delta = _delta(
            old, new,
            ("summary_whole_group_work_total",
             "summary_whole_group_work_rise",
             "summary_whole_group_work_fall",
             "summary_whole_group_work_both",
             "summary_whole_group_work_unknown",
             "summary_whole_coactivation_extra_rise_work",
             "summary_whole_coactivation_extra_fall_work"),
        )
        consistency = _summary_consistency(old, new)
        if any(check["mismatches"] for check in consistency.values()):
            raise ValueError(f"summary/group work mismatch for part {part_text}: {consistency}")
        rows[part_text] = {
            "baseline": {key: old.get(key, 0) for key in work_keys},
            "candidate": {key: new.get(key, 0) for key in work_keys},
            "delta": delta,
            "summary_baseline": {key: value for key, value in old.items()
                                 if key.startswith("summary_")},
            "summary_candidate": {key: value for key, value in new.items()
                                  if key.startswith("summary_")},
            "summary_delta": summary_delta,
            "summary_range_delta": summary_range_delta,
            "summary_whole_delta": summary_whole_delta,
            "positive_destination_exposure": _positive(
                delta, ("rise", "fall", "both", "coactive", "exclusive_rise",
                        "exclusive_fall")),
            "source_release": _negative_release(
                delta, ("rise", "fall", "both", "coactive", "exclusive_rise",
                        "exclusive_fall")),
            "source_known_release": _negative_release(delta, ("known_rise", "known_fall")),
            "destination_known_exposure": _positive(delta, ("known_rise", "known_fall")),
            "mask_work_delta": _mask_delta(
                baseline["mask_work"].get(part_text, {}),
                candidate["mask_work"].get(part_text, {})),
            "summary_consistency": consistency,
        }
    changed = [part for part in parts if any(rows[part]["delta"].values()) or
               any(rows[part]["summary_delta"].values()) or
               any(rows[part]["summary_range_delta"].values()) or
               any(rows[part]["summary_whole_delta"].values()) or
               rows[part]["mask_work_delta"]]
    if source_part is None and destination_part is None:
        focus = changed
    else:
        focus = [str(part) for part in (source_part, destination_part)
                 if part is not None]
    focus_rows = {part: rows[part] for part in focus if part in rows}
    source = rows.get(str(source_part)) if source_part is not None else None
    destination = rows.get(str(destination_part)) if destination_part is not None else None
    source_release = None
    destination_exposure = None
    if source is not None:
        source_release = source["source_release"]
    if destination is not None:
        destination_exposure = destination["positive_destination_exposure"]
    risk_flags = []
    if destination is not None:
        phase_delta = destination["summary_range_delta"]
        phase_rise = phase_delta.get("summary_range_group_work_rise", 0)
        phase_fall = phase_delta.get("summary_range_group_work_fall", 0)
        if not (phase_rise or phase_fall):
            phase_rise = destination["delta"].get("rise", 0)
            phase_fall = destination["delta"].get("fall", 0)
        if phase_rise > 0 or phase_fall > 0:
            risk_flags.append("destination_phase_work_increase")
        if (destination["delta"].get("exclusive_rise", 0) > 0 or
                destination["delta"].get("exclusive_fall", 0) > 0):
            risk_flags.append("destination_phase_selective_increase")
        range_coactivation = (
            destination["summary_range_delta"].get(
                "summary_range_coactivation_extra_rise_work", 0),
            destination["summary_range_delta"].get(
                "summary_range_coactivation_extra_fall_work", 0),
        )
        if any(value > 0 for value in range_coactivation) or any(
                value > 0 for value in destination["summary_delta"].values()):
            risk_flags.append("destination_coactivation_extra_increase")
        if any(value > 0 for value in destination["mask_work_delta"].values()
               if value is not None):
            risk_flags.append("destination_mask_class_increase")
    if source is not None and source["delta"]["total"] < 0:
        risk_flags.append("source_aggregate_work_release")
        if (source["delta"]["unknown"] < 0 and
                not any(source["source_known_release"].values())):
            risk_flags.append("source_release_has_no_resolved_phase_evidence")
    if source is not None and destination is not None:
        if (source["delta"]["total"] < 0 and destination["delta"]["total"] > 0):
            risk_flags.append("release_is_paired_with_destination_increase")
        if (source["delta"]["coactive"] < 0 and
                destination["delta"]["coactive"] > 0):
            risk_flags.append("coactive_work_moves_to_destination")
    return {
        "schema_version": 1,
        "status": "pass",
        "diagnostic_only": True,
        "rule": {
            "description": "Review source release and destination phase exposure before timing a candidate",
            "phase_bits": {name: bit for name, bit in PHASE_BITS},
            "unknown_bit": UNKNOWN,
            "no_time_coefficients": True,
            "scope": "static may-work inventory, not runtime execution frequency",
            "unknown_is_discounted": False,
            "known_phase_definition": "explicit rise/fall bit with no unknown bit; still may-work, not measured work",
            "comparison_identity_checked": False,
            "identity_note": "Use plan-gate compare --phase-risk to require frozen backend identities",
        },
        "baseline": {"plan": baseline["plan"]},
        "candidate": {"plan": candidate["plan"]},
        "source_part": source_part,
        "destination_part": destination_part,
        "changed_parts": changed,
        "focus": focus_rows,
        "parts": rows,
        "risk_flags": risk_flags,
        "source_release": source_release,
        "destination_exposure": destination_exposure,
    }


def _mask_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    keys = sorted(set(before) | set(after), key=int)
    return {key: after.get(key, 0) - before.get(key, 0) for key in keys
            if after.get(key, 0) != before.get(key, 0)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-plan", type=Path, required=True)
    parser.add_argument("--candidate-plan", type=Path, required=True)
    parser.add_argument("--source-part", type=int)
    parser.add_argument("--destination-part", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (args.source_part is None) != (args.destination_part is None):
        parser.error("--source-part and --destination-part must be supplied together")
    result = compare_plans(args.baseline_plan, args.candidate_plan,
                           args.source_part, args.destination_part)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "risk_flags": result["risk_flags"],
                      "changed_parts": result["changed_parts"]}))


if __name__ == "__main__":
    main()
