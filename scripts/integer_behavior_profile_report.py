#!/usr/bin/env python3
"""Summarize profile-only integer behavior attribution artifacts."""
from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path


def load_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    lines = path.read_text().splitlines()
    if not lines:
        return []
    fields = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        values = line.split("\t")
        if len(values) != len(fields):
            continue
        row = dict(zip(fields, values))
        for key in fields:
            if key not in {"model", "symbol", "phase"}:
                try:
                    row[key] = int(row[key])
                except ValueError:
                    pass
        rows.append(row)
    return rows


def phase_stats(log: Path) -> dict:
    result = {}
    if not log.is_file():
        return result
    text = re.sub(r"\x1b\[[0-9;]*m", "", log.read_text(errors="replace"))
    lines = text.splitlines()
    timing = [line for line in lines if line.startswith("[EMU_PHASE_TIMING] ")]
    for line in timing:
        if "model_step_count=" in line:
            for key, value in re.findall(r"([a-z0-9_]+)=([0-9]+)", line):
                result[key] = int(value)
        elif "tick_total_us=" in line:
            for key, value in re.findall(r"([a-z0-9_]+)=([0-9]+)", line):
                result[key] = int(value)
    return result


def summarize_variant(path: Path, run_root: Path) -> dict:
    root = path.parents[2]
    variant = path.parts[-2]
    behavior = load_rows(path / "grhsim_behavior_compute.tsv")
    supernodes = load_rows(path / "grhsim_supernode_fire.tsv")
    result = {
        "profile_dir": str(path),
        "behavior_rows": behavior,
        "behavior_totals": {
            key: sum(int(row.get(key, 0)) for row in behavior)
            for key in ("helper_calls", "input_active", "output_changed", "output_unchanged", "word_iterations")
        },
        "supernode_totals": {
            "compute_fire": sum(int(row.get("f", 0)) for row in supernodes if row.get("phase") == "compute"),
            "commit_fire": sum(int(row.get("f", 0)) for row in supernodes if row.get("phase") == "commit"),
            "rows": len(supernodes),
        },
        "phase_timing": phase_stats(run_root / "runs" / "run01.log"),
    }
    model = root / variant / "model"
    binary = root / variant / "binary.json"
    stats = model / "activity_schedule_supernode_stats.json"
    if stats.is_file():
        result["activity_schedule"] = json.loads(stats.read_text())
    if binary.is_file():
        result["binary"] = json.loads(binary.read_text())
    cpp = list(model.glob("*.cpp"))
    result["cpp_files"] = len(cpp)
    result["cpp_bytes"] = sum(p.stat().st_size for p in cpp)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.input.resolve()
    report = {
        "version": 1,
        "input": str(root),
        "variants": {},
    }
    for workload in ("coremark", "microbench"):
        report["variants"][workload] = {}
        for variant in ("A", "B"):
            profile = root / "profiles" / variant / workload
            run_root = root / variant if workload == "coremark" else root / f"{variant}-microbench"
            if not profile.is_dir():
                continue
            report["variants"][workload][variant] = summarize_variant(profile, run_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
