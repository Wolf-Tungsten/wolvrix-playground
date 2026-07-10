#!/usr/bin/env python3
"""Summarize GrhSIM optimization metrics from stats, emit dirs, build logs, and perf logs."""

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

CODE_SHAPE_PATTERNS = {
    "state_ref_alias_count": "auto &grhsim_state_",
    "state_scalar_ref_alias_count": "auto &grhsim_state_scalar",
    "value_ref_alias_count": "auto &grhsim_value_",
    "value_storage_ref_count": "grhsim_value_storage_ref",
    "state_storage_ref_count": "grhsim_state_storage_ref",
    "slice_u64_words_count": "grhsim_slice_u64_words",
    "assign_words_count": "grhsim_assign_words",
    "active_curr_count": "supernode_active_curr_",
    "active_next_count": "supernode_active_next_",
}

C2_ALIAS_OFF_GATE_LIMITS = {
    "compute_supernodes": 74430,
    "dag_edges": 485905,
    "boundary_values": 1151073,
    "boundary_activation_edges": 2216514,
    "sched_cpp_bytes": 1788406953,
    "storage_ref_alias_count": 0,
    "state_scalar_ref_alias_count": 0,
    "value_ref_alias_count": 0,
}

C2_ALIAS_OFF_GATE_TOLERANCE = {
    "compute_supernodes": 0,
    "dag_edges": 0,
    "boundary_values": 0,
    "boundary_activation_edges": 0,
    # Leave a small margin for harmless formatting drift, while still rejecting
    # the NO0172 alias-on body expansion by a wide margin.
    "sched_cpp_bytes": 100_000_000,
    "storage_ref_alias_count": 0,
    "state_scalar_ref_alias_count": 0,
    "value_ref_alias_count": 0,
}

COREMARK20K_FAST_GATE_LIMITS = {
    "emu_host_time_ms": 105000,
    "guest_cycle_spent": 20001,
    "guest_instr_cnt": 14121,
    "guest_cycle_cnt": 19996,
}

COREMARK50K_FAST_GATE_LIMITS = {
    "emu_host_time_ms": 355000,
    "guest_cycle_spent": 50001,
    "guest_instr_cnt": 73580,
    "guest_cycle_cnt": 49996,
}


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
    m = re.search(r"max cycles:\s*([0-9,]+)", text)
    if m:
        out["max_cycles"] = parse_int(m.group(1))
    else:
        m = re.search(r"(?:^|\s)-C\s+([0-9,]+)(?:\s|$)", text)
        if m:
            out["max_cycles"] = parse_int(m.group(1))
    m = re.search(r"Guest cycle spent:\s*([0-9,]+)", text)
    if m:
        out["guest_cycle_spent"] = parse_int(m.group(1))
    m = re.search(r"instrCnt\s*=\s*([0-9,]+),\s*cycleCnt\s*=\s*([0-9,]+),\s*IPC\s*=\s*([0-9.]+)", text)
    if m:
        out["guest_instr_cnt"] = parse_int(m.group(1))
        out["guest_cycle_cnt"] = parse_int(m.group(2))
        out["guest_ipc"] = parse_float(m.group(3))
    m = re.search(r"EXCEEDING CYCLE/INSTR LIMIT at pc = (0x[0-9a-fA-F]+)", text)
    if m:
        out["guest_pc"] = m.group(1)
    out["difftest_enabled"] = "Difftest enabled" in text or "--diff" in text
    out["cycle_limit_reached"] = "EXCEEDING CYCLE/INSTR LIMIT" in text
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
    if out.get("emu_host_time_ms") and out.get("guest_cycle_spent"):
        out["guest_cycles_per_s"] = out["guest_cycle_spent"] * 1000.0 / out["emu_host_time_ms"]
    return out


def count_text_occurrences(path: Path, patterns: dict[str, str]) -> tuple[int, dict[str, int]]:
    counts = {key: 0 for key in patterns}
    line_count = 0
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            line_count += 1
            for key, pattern in patterns.items():
                counts[key] += line.count(pattern)
    return line_count, counts


def read_emit_dir(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    out: dict[str, Any] = {}
    sched_files = sorted(path.glob("grhsim_*_sched_*.cpp"))
    state_init_files = sorted(path.glob("grhsim_*_state_init_*.cpp"))
    all_cpp_files = sorted(path.glob("*.cpp"))
    out["emit_dir"] = str(path)
    out["sched_cpp_files"] = len(sched_files)
    out["state_init_cpp_files"] = len(state_init_files)
    out["total_cpp_files"] = len(all_cpp_files)

    pattern_counts = {key: 0 for key in CODE_SHAPE_PATTERNS}
    sched_bytes = 0
    sched_lines = 0
    largest_sched_bytes = 0
    largest_sched_lines = 0
    largest_sched_file = ""
    for sched in sched_files:
        size = sched.stat().st_size
        line_count, file_pattern_counts = count_text_occurrences(sched, CODE_SHAPE_PATTERNS)
        sched_bytes += size
        sched_lines += line_count
        for key, value in file_pattern_counts.items():
            pattern_counts[key] += value
        if size > largest_sched_bytes:
            largest_sched_bytes = size
            largest_sched_lines = line_count
            largest_sched_file = sched.name

    out.update(pattern_counts)
    out["sched_cpp_bytes"] = sched_bytes
    out["sched_cpp_lines"] = sched_lines
    out["sched_cpp_largest_file"] = largest_sched_file
    out["sched_cpp_largest_bytes"] = largest_sched_bytes
    out["sched_cpp_largest_lines"] = largest_sched_lines
    if sched_files:
        out["sched_cpp_mean_bytes"] = sched_bytes / len(sched_files)
        out["sched_cpp_mean_lines"] = sched_lines / len(sched_files)
    out["storage_ref_alias_count"] = out["state_ref_alias_count"] + out["value_ref_alias_count"]
    return out


def merge_metrics(stats: dict[str, Any],
                  emit: dict[str, Any],
                  build: dict[str, Any],
                  perf: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    out.update(stats)
    out.update(emit)
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


def build_c2_alias_off_gate(out: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    passed = True
    for key, expected in C2_ALIAS_OFF_GATE_LIMITS.items():
        actual = out.get(key)
        tolerance = C2_ALIAS_OFF_GATE_TOLERANCE[key]
        if actual is None:
            ok = False
            delta = None
        else:
            delta = actual - expected
            ok = abs(delta) <= tolerance
        checks[key] = {
            "actual": actual,
            "expected": expected,
            "tolerance": tolerance,
            "delta": delta,
            "pass": ok,
        }
        passed = passed and ok
    return {
        "name": "c2-alias-off",
        "pass": passed,
        "checks": checks,
    }


def add_c2_alias_off_gate(out: dict[str, Any]) -> bool:
    gate = build_c2_alias_off_gate(out)
    out["gate"] = gate
    return bool(gate["pass"])


def build_coremark20k_fast_gate(out: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    passed = True

    def add_check(name: str, actual: Any, expected: Any, ok: bool, note: str = "") -> None:
        nonlocal passed
        checks[name] = {
            "actual": actual,
            "expected": expected,
            "pass": ok,
        }
        if note:
            checks[name]["note"] = note
        passed = passed and ok

    host_time = out.get("emu_host_time_ms")
    add_check(
        "emu_host_time_ms",
        host_time,
        f"<= {COREMARK20K_FAST_GATE_LIMITS['emu_host_time_ms']}",
        isinstance(host_time, (int, float)) and host_time <= COREMARK20K_FAST_GATE_LIMITS["emu_host_time_ms"],
        "fast 20k gate, calibrated from NO0151/NO0162 ~99-101s",
    )
    add_check("difftest_enabled", out.get("difftest_enabled"), True, out.get("difftest_enabled") is True)
    add_check("cycle_limit_reached", out.get("cycle_limit_reached"), True, out.get("cycle_limit_reached") is True)
    add_check("max_cycles", out.get("max_cycles"), 20000, out.get("max_cycles") == 20000)

    for key in ("guest_cycle_spent", "guest_instr_cnt", "guest_cycle_cnt"):
        expected = COREMARK20K_FAST_GATE_LIMITS[key]
        actual = out.get(key)
        add_check(key, actual, expected, actual == expected)

    return {
        "name": "coremark20k-fast",
        "pass": passed,
        "checks": checks,
    }


def add_coremark20k_fast_gate(out: dict[str, Any]) -> bool:
    gate = build_coremark20k_fast_gate(out)
    out["gate"] = gate
    return bool(gate["pass"])


def build_coremark50k_fast_gate(out: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    passed = True

    def add_check(name: str, actual: Any, expected: Any, ok: bool, note: str = "") -> None:
        nonlocal passed
        checks[name] = {
            "actual": actual,
            "expected": expected,
            "pass": ok,
        }
        if note:
            checks[name]["note"] = note
        passed = passed and ok

    host_time = out.get("emu_host_time_ms")
    add_check(
        "emu_host_time_ms",
        host_time,
        f"<= {COREMARK50K_FAST_GATE_LIMITS['emu_host_time_ms']}",
        isinstance(host_time, (int, float)) and host_time <= COREMARK50K_FAST_GATE_LIMITS["emu_host_time_ms"],
        "fast 50k gate, calibrated from NO0151/NO0162 ~348-350s",
    )
    add_check("difftest_enabled", out.get("difftest_enabled"), True, out.get("difftest_enabled") is True)
    add_check("cycle_limit_reached", out.get("cycle_limit_reached"), True, out.get("cycle_limit_reached") is True)
    add_check("max_cycles", out.get("max_cycles"), 50000, out.get("max_cycles") == 50000)

    for key in ("guest_cycle_spent", "guest_instr_cnt", "guest_cycle_cnt"):
        expected = COREMARK50K_FAST_GATE_LIMITS[key]
        actual = out.get(key)
        add_check(key, actual, expected, actual == expected)

    return {
        "name": "coremark50k-fast",
        "pass": passed,
        "checks": checks,
    }


def add_coremark50k_fast_gate(out: dict[str, Any]) -> bool:
    gate = build_coremark50k_fast_gate(out)
    out["gate"] = gate
    return bool(gate["pass"])


def add_latest_default_20k_gate(out: dict[str, Any]) -> bool:
    gates = {
        "c2-alias-off": build_c2_alias_off_gate(out),
        "coremark20k-fast": build_coremark20k_fast_gate(out),
    }
    passed = all(bool(gate["pass"]) for gate in gates.values())
    out["gate"] = {
        "name": "latest-default-20k",
        "pass": passed,
        "gates": gates,
    }
    return passed


def add_latest_default_50k_gate(out: dict[str, Any]) -> bool:
    gates = {
        "c2-alias-off": build_c2_alias_off_gate(out),
        "coremark50k-fast": build_coremark50k_fast_gate(out),
    }
    passed = all(bool(gate["pass"]) for gate in gates.values())
    out["gate"] = {
        "name": "latest-default-50k",
        "pass": passed,
        "gates": gates,
    }
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats", type=Path, help="activity_schedule_supernode_stats.json")
    parser.add_argument("--emit-dir", type=Path, help="grhsim_emit directory containing generated sched C++")
    parser.add_argument("--build-log", type=Path, help="xs_wolf_grhsim_build_*.log")
    parser.add_argument("--perf-log", type=Path, help="combined stdout/stderr perf stat log")
    parser.add_argument("--baseline", type=Path, help="baseline metrics JSON produced by this script")
    parser.add_argument(
        "--gate",
        choices=[
            "c2-alias-off",
            "coremark20k-fast",
            "coremark50k-fast",
            "latest-default-20k",
            "latest-default-50k",
        ],
        help="add a machine-checkable pass/fail gate to the metrics JSON and return non-zero on failure",
    )
    parser.add_argument("--out", type=Path, help="write JSON summary to this path")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    args = parser.parse_args()

    metrics = merge_metrics(
        read_stats(args.stats),
        read_emit_dir(args.emit_dir),
        read_build_log(args.build_log),
        read_perf_log(args.perf_log),
    )
    add_deltas(metrics, load_baseline(args.baseline))
    gate_passed = True
    if args.gate == "c2-alias-off":
        gate_passed = add_c2_alias_off_gate(metrics)
    elif args.gate == "coremark20k-fast":
        gate_passed = add_coremark20k_fast_gate(metrics)
    elif args.gate == "coremark50k-fast":
        gate_passed = add_coremark50k_fast_gate(metrics)
    elif args.gate == "latest-default-20k":
        gate_passed = add_latest_default_20k_gate(metrics)
    elif args.gate == "latest-default-50k":
        gate_passed = add_latest_default_50k_gate(metrics)

    text = json.dumps(metrics, indent=2 if args.pretty else None, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(text)
    return 0 if gate_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
