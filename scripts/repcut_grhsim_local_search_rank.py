#!/usr/bin/env python3
"""Rank whole-piece GrhSIM moves without hard-coded partition names.

The assignment evaluator supplies exact structural deltas.  This script uses
the current baseline per-part timings only to estimate the critical eval path;
it does not claim to predict walltime or update time.  The default estimate is
the envelope of backend recurring work and raw operation count; it is not a
runtime upper bound. Communication calls and bytes remain separate objectives.
Optional explicit structural budgets screen every lane before Pareto ranking.
A full execution-plan gate and fresh AB/BA remain mandatory.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import median

from repcut_grhsim_critical_profile import project_eval
from repcut_grhsim_plan_gate import evaluate_budget, identity


WORK_METRIC = "grhsim_v1_recurring_work"
DEFAULT_WORK_METRICS = ("grhsim_v1_recurring_work", "raw_operation_count")
COMMUNICATION_METRICS = ("send_calls", "send_bytes", "receive_calls", "receive_bytes")
ACTIVITY_MODELS = ("lane-scale", "source-envelope")


def _scale(base: float, candidate: float, allow_new_work: bool = False) -> float:
    if any(not math.isfinite(v) or v < 0 for v in (base, candidate)):
        raise ValueError('work counts must be finite and nonnegative')
    if base:
        return candidate / base
    if candidate and not allow_new_work:
        raise ValueError('cannot scale new work from zero baseline; use a source activity estimate')
    return 1.0


def structural_budget(record: dict, rules: list[dict]) -> dict:
    """Use the same explicit budget schema as the backend execution-plan gate."""
    global_metrics = {name: {"peak": value["peak"], "sum": value["total"]}
                      for name, value in record.items()
                      if isinstance(value, dict) and "peak" in value and "total" in value}
    return evaluate_budget({"global": global_metrics, "parts": record.get("parts", {})}, rules)


def select_migration(ranking: dict) -> dict | None:
    candidates = ranking['improving_frontier']
    if not candidates:
        return None
    return min(candidates, key=lambda row: (
        row['predicted_mean_step_max_eval_us'], row['candidate_non_endpoint_impact_count'],
        row['candidate_send_bytes_max_part_increase'], row['candidate_receive_bytes_max_part_increase'], row['name']))


def load_eval_times(path: Path, variant: str = "baseline") -> dict[int, dict[str, float]]:
    """Return per-part medians for an explicitly selected measurement arm.

    An accepted candidate becomes the next search baseline. Its timings must
    come from the candidate arm of the previous comparison, not that run's
    baseline arm.
    """
    grouped: dict[int, dict[str, list[float]]] = {}
    with path.open(newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("record_type") != "part_timing" or row.get("variant") != variant:
                continue
            part_name = row.get("part_name", "")
            if not part_name.startswith("part_"):
                continue
            part = int(part_name.removeprefix("part_"))
            grouped.setdefault(part, {"eval": [], "update": []})["eval"].append(
                float(row["eval_avg_us"])
            )
            grouped[part]["update"].append(float(row["update_push_avg_us"]))
    if not grouped:
        raise ValueError(f"no {variant} part_timing rows in {path}")
    return {
        part: {metric: median(values) for metric, values in metrics.items()}
        for part, metrics in grouped.items()
    }


def _metric(container: dict, scope: str, variant: str) -> float:
    return float(container[scope][variant])


def _pareto_frontier(rows: list[dict], objectives: tuple[str, ...]) -> list[dict]:
    frontier = []
    for row in rows:
        values = tuple(float(row[key]) for key in objectives)
        dominated = False
        for other in rows:
            if other is row:
                continue
            other_values = tuple(float(other[key]) for key in objectives)
            no_worse = all(a <= b for a, b in zip(other_values, values))
            strictly_better = any(a < b for a, b in zip(other_values, values))
            if no_worse and strictly_better:
                dominated = True
                break
        if not dominated:
            frontier.append(row)
    return sorted(frontier, key=lambda row: (
        float(row.get("predicted_mean_step_max_eval_us", row["predicted_max_eval_us"])),
        float(row["predicted_sum_eval_us"]),
        float(row["candidate_send_bytes_total"]),
        row["name"],
    ))


def rank(report: dict, timings: dict[int, dict[str, float]],
         work_metrics: tuple[str, ...] = DEFAULT_WORK_METRICS,
         budget_rules: list[dict] | None = None,
         critical_traces: list[Path] | None = None,
         activity_model: str = "lane-scale") -> dict:
    candidates = report.get("candidates", [])
    if not candidates:
        raise ValueError("candidate report is empty")
    if not work_metrics or len(set(work_metrics)) != len(work_metrics):
        raise ValueError("work metric list must be nonempty and unique")
    if activity_model not in ACTIVITY_MODELS:
        raise ValueError('unknown activity model')
    if activity_model == 'source-envelope' and not critical_traces:
        raise ValueError('source-envelope requires per-step critical traces')
    partitions = sorted(timings)
    baseline_eval = {part: timings[part]["eval"] for part in partitions}
    baseline_update = {part: timings[part]["update"] for part in partitions}
    baseline_max_eval = max(baseline_eval.values())
    baseline_sum_eval = sum(baseline_eval.values())
    output = []
    for record in candidates:
        source = int(record["source"])
        raw_destinations = record["destinations"] if "destinations" in record else [record["destination"]]
        destinations = [int(value) for value in raw_destinations]
        if source not in timings or any(destination not in timings for destination in destinations):
            raise ValueError(f"candidate {record['name']} references unknown partition")
        if not destinations or source in destinations or len(set(destinations)) != len(destinations):
            raise ValueError(f"candidate {record['name']} has invalid destinations")
        work = record[WORK_METRIC]
        scales: dict[str, dict[str, float]] = {}
        added_source_factors = {str(p): 0.0 for p in destinations}
        for metric in work_metrics:
            metric_work = record.get(metric)
            if not metric_work:
                raise ValueError(f"candidate {record['name']} has no {metric}")
            source_base = float(metric_work["source"]["baseline"])
            source_candidate = float(metric_work["source"]["candidate"])
            if "destinations" in metric_work:
                destination_work = metric_work["destinations"]
                destination_scales = {}
                for destination in destinations:
                    item = destination_work[str(destination)]
                    base = float(item["baseline"])
                    candidate = float(item["candidate"])
                    destination_scales[str(destination)] = _scale(base, candidate, activity_model == 'source-envelope')
            elif all(key in metric_work for key in ("destination_a", "destination_b")):
                if len(destinations) != 2:
                    raise ValueError(f"candidate {record['name']} has incomplete destination work")
                destination_scales = {}
                for destination, key in zip(destinations, ("destination_a", "destination_b")):
                    item = metric_work[key]
                    base = float(item["baseline"])
                    candidate = float(item["candidate"])
                    destination_scales[str(destination)] = _scale(base, candidate, activity_model == 'source-envelope')
            else:
                if len(destinations) != 1 or "destination" not in metric_work:
                    raise ValueError(f"candidate {record['name']} has incomplete destination work")
                item = metric_work["destination"]
                base = float(item["baseline"])
                candidate = float(item["candidate"])
                destination_scales = {str(destinations[0]): _scale(base, candidate, activity_model == 'source-envelope')}
            if activity_model == 'source-envelope':
                for index, destination in enumerate(destinations):
                    if 'destinations' in metric_work:
                        item = metric_work['destinations'][str(destination)]
                    elif 'destination_a' in metric_work:
                        item = metric_work[('destination_a', 'destination_b')[index]]
                    else:
                        item = metric_work['destination']
                    added = max(0.0, float(item['candidate']) - float(item['baseline']))
                    if added and not source_base:
                        raise ValueError('cannot price added work from an empty source')
                    added_source_factors[str(destination)] = max(
                        added_source_factors[str(destination)], added / source_base if source_base else 0.0)
            scales[metric] = {
                "source": _scale(source_base, source_candidate),
                "destinations": destination_scales,
            }
        source_scale = max(scale["source"] for scale in scales.values())
        destination_scale = max(
            scale["destinations"][str(destination)]
            for scale in scales.values() for destination in destinations)
        predicted = dict(baseline_eval)
        predicted[source] = baseline_eval[source] * source_scale
        for metric in work_metrics:
            for destination in destinations:
                scale = scales[metric]["destinations"][str(destination)]
                predicted[destination] = max(
                    predicted[destination], baseline_eval[destination] * scale)
        if activity_model == 'source-envelope':
            for destination in destinations:
                predicted[destination] = max(predicted[destination], baseline_eval[destination] +
                    baseline_eval[source] * added_source_factors[str(destination)])
        row = {
            "name": record["name"],
            "source": source,
            "destinations": destinations,
            "destination": destinations[0] if len(destinations) == 1 else None,
            "moved_atoms": int(record["moved_atoms"]),
            "shape_score": int(record["shape_score"]),
            "predicted_source_eval_us": predicted[source],
            "predicted_destination_eval_us": max(predicted[p] for p in destinations),
            "predicted_destination_eval_by_part_us": {str(p): predicted[p] for p in destinations},
            "source_work_scale": source_scale,
            "destination_work_scale": destination_scale,
            "work_scale_metrics": scales,
            "added_source_activity_factors": added_source_factors if activity_model == 'source-envelope' else None,
            "predicted_max_eval_us": max(predicted.values()),
            "predicted_sum_eval_us": sum(predicted.values()),
            "baseline_max_eval_us": baseline_max_eval,
            "baseline_sum_eval_us": baseline_sum_eval,
            "baseline_max_update_us": max(baseline_update.values()),
            "baseline_sum_update_us": sum(baseline_update.values()),
            "candidate_recurring_work_peak": _metric(work, "peak", "candidate"),
            "candidate_recurring_work_total": _metric(work, "total", "candidate"),
            "candidate_send_bytes_peak": _metric(record["send_bytes"], "peak", "candidate"),
            "candidate_send_bytes_total": _metric(record["send_bytes"], "total", "candidate"),
            "candidate_piece_copies_peak": _metric(record["piece_copies"], "peak", "candidate"),
            "candidate_piece_copies_total": _metric(record["piece_copies"], "total", "candidate"),
            "critical_eval_improves": max(predicted.values()) < baseline_max_eval,
            "unmodeled_transfer_impact_parts": record.get('non_endpoint_impact_parts'),
            "transfer_layout_impact_available": 'direct_impact_parts' in record,
        }
        impact_parts = record.get('non_endpoint_impact_parts')
        direct_parts = record.get('direct_impact_parts')
        # An exact transfer-layout audit is a generic risk signal: every
        # non-endpoint reader can receive a different activation/packet shape.
        # Unknown scope is conservatively ranked as larger than the whole
        # partition set instead of being silently treated as zero.
        row["candidate_non_endpoint_impact_count"] = (
            len(impact_parts) if impact_parts is not None else len(partitions) + 1
        )
        row["candidate_direct_impact_count"] = (
            len(direct_parts) if direct_parts is not None else len(partitions) + 1
        )
        row["candidate_non_endpoint_impact_ratio"] = (
            row["candidate_non_endpoint_impact_count"] / len(partitions)
            if partitions else 0.0
        )
        for metric in COMMUNICATION_METRICS:
            if metric not in record:
                raise ValueError(f"candidate {record['name']} has no {metric}")
            for scope in ("peak", "total"):
                row[f"candidate_{metric}_{scope}"] = _metric(record[metric], scope, "candidate")
        if "parts" in record:
            row["communication_changes_by_part"] = {
                part: {metric: values[metric] for metric in COMMUNICATION_METRICS
                       if values[metric]["candidate"] != values[metric]["baseline"]}
                for part, values in record["parts"].items()
                if any(values[metric]["candidate"] != values[metric]["baseline"]
                       for metric in COMMUNICATION_METRICS)
            }
            for metric in COMMUNICATION_METRICS:
                row[f"candidate_{metric}_max_part_increase"] = max(
                    [0] + [values[metric]["candidate"] - values[metric]["baseline"]
                           for values in record["parts"].values()])
        if budget_rules is not None:
            row["budget"] = structural_budget(record, budget_rules)
        output.append(row)
    objectives = (
        "predicted_max_eval_us",
        "predicted_sum_eval_us",
        "candidate_send_bytes_peak",
        "candidate_send_bytes_total",
        "candidate_send_calls_peak",
        "candidate_send_calls_total",
        "candidate_receive_calls_peak",
        "candidate_receive_calls_total",
        "candidate_receive_bytes_peak",
        "candidate_piece_copies_peak",
        "candidate_piece_copies_total",
        "candidate_non_endpoint_impact_count",
        "candidate_direct_impact_count",
        "destination_work_scale",
    )
    trace_prediction = None
    if critical_traces:
        if partitions != list(range(len(partitions))):
            raise ValueError('cycle trace requires contiguous partition indices')
        trace_prediction = project_eval(critical_traces, {
            row['name']: {row['source']: row['source_work_scale'],
                          **{p: max(1.0, *(s['destinations'][str(p)] for s in row['work_scale_metrics'].values()))
                             for p in row['destinations']}}
            for row in output}, len(partitions),
            additions={row['name']: {p: {row['source']: row['added_source_activity_factors'][str(p)]}
                                    for p in row['destinations']} for row in output}
            if activity_model == 'source-envelope' else None)
        for row in output:
            projection = trace_prediction['candidates'][row['name']]
            row['baseline_mean_step_max_eval_us'] = trace_prediction['baseline_mean_step_max_us']
            row['predicted_mean_step_max_eval_us'] = projection['mean_step_max_us']
            row['predicted_clock_level_mean_step_max_eval_us'] = projection['clock_levels']
            row['predicted_clock_level_delta_us'] = {
                phase: value - trace_prediction['baseline_clock_levels'][phase]
                for phase, value in projection['clock_levels'].items()}
            row['critical_eval_improves'] = projection['mean_step_max_us'] < trace_prediction['baseline_mean_step_max_us']
        objectives = ('predicted_mean_step_max_eval_us', *objectives[1:])
    if all("parts" in record for record in candidates):
        objectives += tuple(f"candidate_{metric}_max_part_increase" for metric in COMMUNICATION_METRICS)
    eligible = [row for row in output if row.get("budget", {}).get("within_budget", True)]
    frontier = _pareto_frontier(eligible, objectives)
    improving = [row for row in frontier if row["critical_eval_improves"]]
    return {
        "schema_version": 3,
        "status": "pass",
        "method": "baseline_eval_scaled_by_conservative_work_and_transfer_scope_envelope",
        "activity_model": activity_model,
        "piece_activity_observed": False,
        "source_activity_assumption": ("added work follows the source lane at the same step; "
                                       "destination activity remains an independent risk estimate")
                                      if activity_model == 'source-envelope' else None,
        "work_metrics": list(work_metrics),
        "timing_is_estimate": True,
        "timing_is_upper_bound": False,
        "max_partition_mean_is_not_mean_step_maximum": True,
        "critical_path_statistic": "mean_of_per_step_maxima" if critical_traces else "max_of_partition_means",
        "trace_projection_assumes_other_lane_times_unchanged": bool(critical_traces),
        "trace_baseline_mean_step_max_eval_us": trace_prediction['baseline_mean_step_max_us'] if trace_prediction else None,
        "trace_baseline_clock_levels": trace_prediction['baseline_clock_levels'] if trace_prediction else None,
        "update_time_predicted": False,
        "objectives": list(objectives),
        "baseline": {
            "part_count": len(partitions),
            "max_eval_us": baseline_max_eval,
            "sum_eval_us": baseline_sum_eval,
            "max_update_us": max(baseline_update.values()),
            "sum_update_us": sum(baseline_update.values()),
        },
        "candidate_count": len(output),
        "eligible_count": len(eligible),
        "budget_rules": budget_rules,
        "outside_budget": [row for row in output if row not in eligible],
        "frontier_count": len(frontier),
        "improving_frontier_count": len(improving),
        "frontier": frontier,
        "improving_frontier": improving,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--parts", type=Path, required=True)
    parser.add_argument(
        "--profile-variant", choices=("baseline", "candidate"), default="baseline",
        help="measurement arm matching the assignment being used as the search baseline",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument('--no-input-checks', action='store_true',
                        help='rank fresh build outputs without hashing or identity comparisons')
    parser.add_argument('--critical-trace', type=Path, action='append',
                        help='optional current-assignment traces to rank mean per-step maxima; repeatable')
    parser.add_argument('--activity-model', choices=ACTIVITY_MODELS, default='lane-scale',
                        help='source-envelope also transports source activity to each destination; requires traces')
    parser.add_argument("--budget", type=Path,
                        help="JSON rules using structural feature and scope=peak|sum|part; no fitted time limits")
    parser.add_argument(
        "--work-metric", action="append", dest="work_metrics",
        help="exact evaluator metric used in the conservative work envelope; repeatable",
    )
    args = parser.parse_args()
    record_input = (lambda path: {'path': str(path.resolve())}) if args.no_input_checks else identity
    trace_inputs = [record_input(p) for p in args.critical_trace] if args.critical_trace else None
    report = json.loads(args.report.read_text())
    result = rank(
        report,
        load_eval_times(args.parts, args.profile_variant),
        tuple(args.work_metrics) if args.work_metrics else DEFAULT_WORK_METRICS,
        json.loads(args.budget.read_text())["rules"] if args.budget else None,
        args.critical_trace,
        args.activity_model,
    )
    result["inputs"] = {"report": record_input(args.report), "parts": record_input(args.parts)}
    result["profile_variant"] = args.profile_variant
    if args.budget:
        result["inputs"]["budget"] = record_input(args.budget)
    if args.critical_trace:
        if not args.no_input_checks and trace_inputs != [identity(p) for p in args.critical_trace]:
            raise ValueError('critical trace changed during ranking')
        result['inputs']['critical_traces'] = trace_inputs
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({
        "candidates": result["candidate_count"],
        "eligible": result["eligible_count"],
        "frontier": result["frontier_count"],
        "improving_frontier": result["improving_frontier_count"],
        "output": str(args.output),
    }))


if __name__ == "__main__":
    main()
