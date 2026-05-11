#!/usr/bin/env python3
"""Summarize GrhSIM optimization metrics from stats, build logs, and perf logs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


STAT_KEYS = [
    "supernodes",
    "compute_supernodes",
    "commit_supernodes",
    "dag_edges",
    "boundary_values",
    "boundary_activation_edges",
    "compute_compute_value_pairs",
    "compute_commit_value_pairs",
    "state_read_activation_edges",
    "constant_activation_edges",
    "other_compute_activation_edges",
    "other_compute_unique_supernode_pairs",
    "other_compute_duplicate_activation_edges",
]

PERF_KEYS = [
    "emu_host_time_ms",
    "perf_elapsed_s",
    "cycles",
    "instructions",
    "branches",
    "branch_misses",
    "cache_references",
    "cache_misses",
    "duration_time",
    "user_time",
    "system_time",
    "guest_instr_cnt",
    "guest_cycle_cnt",
    "guest_ipc",
    "guest_pc",
]


def parse_int(text: str) -> int:
    return int(text.replace(",", ""))


def parse_float(text: str) -> float:
    return float(text.replace(",", ""))


def read_stats(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    data = json.loads(path.read_text())
    out: dict[str, Any] = {key: data.get(key) for key in STAT_KEYS if key in data}
    ops = data.get("ops_per_supernode", {})
    out.update(
        {
            "ops_mean": ops.get("mean"),
            "ops_median": ops.get("median"),
            "ops_p90": ops.get("p90"),
            "ops_p99": ops.get("p99"),
            "ops_max": ops.get("max"),
        }
    )
    outdeg = data.get("out_degree_per_supernode", {})
    out.update(
        {
            "outdeg_mean": outdeg.get("mean"),
            "outdeg_median": outdeg.get("median"),
            "outdeg_p90": outdeg.get("p90"),
            "outdeg_p99": outdeg.get("p99"),
            "outdeg_max": outdeg.get("max"),
        }
    )
    add_derived_metrics(out)
    return out


def add_derived_metrics(out: dict[str, Any]) -> None:
    boundary = out.get("boundary_activation_edges")
    dag = out.get("dag_edges")
    other = out.get("other_compute_activation_edges")
    unique = out.get("other_compute_unique_supernode_pairs")
    duplicate = out.get("other_compute_duplicate_activation_edges")
    compute_pairs = out.get("compute_compute_value_pairs")
    compute_supernodes = out.get("compute_supernodes")

    if boundary and dag:
        out["activation_per_dag_edge"] = boundary / dag
    if other and unique:
        out["other_compute_activation_per_unique_pair"] = other / unique
    if duplicate is not None and other:
        out["other_compute_duplicate_ratio"] = duplicate / other
    if compute_pairs and compute_supernodes:
        out["compute_pairs_per_compute_supernode"] = compute_pairs / compute_supernodes

    # A deliberately simple structural guard metric. Lower is better. It penalizes
    # the factors that regressed in the activation-affinity experiment.
    if all(out.get(key) is not None for key in ("compute_supernodes", "dag_edges", "outdeg_p99", "boundary_activation_edges")):
        out["runtime_risk_score"] = (
            float(out["compute_supernodes"]) * 4.0
            + float(out["dag_edges"]) * 1.0
            + float(out["outdeg_p99"]) * 1000.0
            + float(out["boundary_activation_edges"]) * 0.1
        )


def parse_key_value_line(line: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in re.findall(r"([A-Za-z0-9_]+)=([^ \n]+)", line):
        if value in {"true", "false"}:
            result[key] = value == "true"
            continue
        try:
            if "." in value:
                result[key] = float(value)
            else:
                result[key] = int(value)
        except ValueError:
            result[key] = value
    return result


def read_build_log(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    out: dict[str, Any] = {}
    text = path.read_text(errors="replace")
    for line in text.splitlines():
        if "compute-node materialize timing(ms):" in line:
            for key, value in parse_key_value_line(line).items():
                out[f"mat_{key}_ms" if key not in {"segments"} else f"mat_{key}"] = value
        elif "compute-node coarsen detail:" in line:
            for key, value in parse_key_value_line(line).items():
                out[f"coarsen_{key}"] = value
        elif "activity-schedule supernode stats " in line:
            out.update(parse_key_value_line(line))
    add_derived_metrics(out)
    return out


def read_perf_log(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    text = path.read_text(errors="replace")
    out: dict[str, Any] = {}

    m = re.search(r"Host time spent:\s*([0-9,]+)ms", text)
    if m:
        out["emu_host_time_ms"] = parse_int(m.group(1))
    m = re.search(r"instrCnt\s*=\s*([0-9,]+),\s*cycleCnt\s*=\s*([0-9,]+),\s*IPC\s*=\s*([0-9.]+)", text)
    if m:
        out["guest_instr_cnt"] = parse_int(m.group(1))
        out["guest_cycle_cnt"] = parse_int(m.group(2))
        out["guest_ipc"] = parse_float(m.group(3))
    m = re.search(r"EXCEEDING CYCLE/INSTR LIMIT at pc = (0x[0-9a-fA-F]+)", text)
    if m:
        out["guest_pc"] = m.group(1)
    m = re.search(r"([0-9,.]+)\s+seconds time elapsed", text)
    if m:
        out["perf_elapsed_s"] = parse_float(m.group(1))

    metric_map = {
        "cycles": "cycles",
        "instructions": "instructions",
        "branches": "branches",
        "branch-misses": "branch_misses",
        "cache-references": "cache_references",
        "cache-misses": "cache_misses",
        "duration_time": "duration_time",
        "user_time": "user_time",
        "system_time": "system_time",
    }
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        metric = parts[1]
        if metric in metric_map and re.fullmatch(r"[0-9,]+", parts[0]):
            out[metric_map[metric]] = parse_int(parts[0])

    if out.get("branch_misses") is not None and out.get("branches"):
        out["branch_miss_rate"] = out["branch_misses"] / out["branches"]
    if out.get("cache_misses") is not None and out.get("cache_references"):
        out["cache_miss_rate"] = out["cache_misses"] / out["cache_references"]
    if out.get("instructions") is not None and out.get("cycles"):
        out["host_ipc"] = out["instructions"] / out["cycles"]
    return out


def merge_metrics(stats: dict[str, Any], build: dict[str, Any], perf: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    out.update(stats)
    for key, value in build.items():
        out.setdefault(key, value)
    out.update(perf)
    return out


def load_baseline(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return json.loads(path.read_text())


def add_deltas(out: dict[str, Any], baseline: dict[str, Any]) -> None:
    if not baseline:
        return
    deltas: dict[str, Any] = {}
    for key, value in out.items():
        base = baseline.get(key)
        if isinstance(value, (int, float)) and isinstance(base, (int, float)) and base != 0:
            deltas[key] = {
                "abs": value - base,
                "pct": (value - base) / base,
            }
    if deltas:
        out["delta_vs_baseline"] = deltas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats", type=Path, help="activity_schedule_supernode_stats.json")
    parser.add_argument("--build-log", type=Path, help="xs_wolf_grhsim_build_*.log")
    parser.add_argument("--perf-log", type=Path, help="combined stdout/stderr perf stat log")
    parser.add_argument("--baseline", type=Path, help="baseline metrics JSON produced by this script")
    parser.add_argument("--out", type=Path, help="write JSON summary to this path")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    args = parser.parse_args()

    metrics = merge_metrics(read_stats(args.stats), read_build_log(args.build_log), read_perf_log(args.perf_log))
    add_deltas(metrics, load_baseline(args.baseline))

    text = json.dumps(metrics, indent=2 if args.pretty else None, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
