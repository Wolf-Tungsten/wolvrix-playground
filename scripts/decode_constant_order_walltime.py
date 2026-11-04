#!/usr/bin/env python3
"""Small CPU96 probe for a source-order replay binary."""
from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path

from decode_table_csr_only import configuration
from grhsim_difftrace import build_comparator, compare_traces
from grhsim_single_baseline import Baseline, ROOT, cpus, identity, save
from grhsim_single_compare import run_signature, summarize


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=4)
    args = parser.parse_args()
    if not platform.node().startswith("node030"):
        raise ValueError("walltime probe must run on node030")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    baseline = args.baseline.resolve()
    candidate = args.candidate.resolve()
    runners = {}
    prepared = {}
    for name, root in (("E", baseline), ("X", candidate)):
        binary = root / "emu/grhsim-compile/emu"
        runners[name] = Baseline(configuration(out / name, binary=binary,
                                                constant_decode_fold=False))
        prepared[name] = runners[name].prepare_measurement()
    e_header = baseline / "chisel-home/build/generated-src/difftest-state.h"
    x_header = candidate / "chisel-home/build/generated-src/difftest-state.h"
    if identity(e_header)["sha256"] != identity(x_header)["sha256"]:
        raise ValueError("DiffTest schema differs")
    comparator = build_comparator(e_header, out / "trace-comparator")
    checks = []
    for seed in (0, 1):
        row = runners["X"].run_sample(
            prepared["X"], f"verify-s{seed}", 100000, seed,
            extra_args=("--dump-difftrace", f"./trace_s{seed}"))
        new = prepared["X"]["binary"].parent / f"trace_s{seed}"
        # The frozen E trace is kept in the original comparison runtime tree.
        old = baseline.parent / "comparison/E/runs/runtime/bin" / f"trace_s{seed}"
        checks.append(dict(seed=seed, **compare_traces(
            comparator, old, new, out / f"trace-E-X-s{seed}.json")))
    for name in ("E", "X"):
        runners[name].run_sample(prepared[name], "smoke", 10000)
        runners[name].run_sample(prepared[name], "warmup", 100000)
    rows = []
    signature = None
    for index in range(args.pairs):
        order = ("E", "X") if index % 2 == 0 else ("X", "E")
        row = {"pair": index, "order": list(order)}
        for name in order:
            sample = runners[name].run_sample(prepared[name], f"pair{index:02d}", 100000)
            current = run_signature(sample)
            if signature is None:
                signature = current
            if current != signature:
                raise ValueError("functional signature changed")
            row[name] = sample
        rows.append(row)
        save(out / "pairs.json", rows)
    summary = dict(
        baseline=identity(baseline / "emu/grhsim-compile/emu"),
        candidate=identity(candidate / "emu/grhsim-compile/emu"),
        cpu=96, cycles=100000, pairs=args.pairs, trace_checks=checks,
        samples=rows, functional_signature=signature,
        X_vs_E=summarize([dict(A=row["E"], B=row["X"]) for row in rows]),
    )
    save(out / "summary.json", summary)
    print(json.dumps(summary["X_vs_E"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
