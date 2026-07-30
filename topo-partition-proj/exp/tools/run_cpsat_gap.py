#!/usr/bin/env python3

"""CP-SAT gap measurement (docs/04 Phase 1 task 3, M1 gate: gap <= 5% ideal).

Samples small regions (160-220 internal nodes so permutable count lands in
(128, 200] — smaller is trivial: one segment fits all), runs the annealed
search, the exact CP-SAT oracle, and both anchors, then reports the gap.

Usage:

    run_cpsat_gap.py <instruction_graph.jsonl> <block_assignment.jsonl> <out.json>
        [--count K] [--iterations N] [--time-limit S] [--seed S]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.cpsat_oracle import solve_optimal  # noqa: E402
from harness.graph import load_graph  # noqa: E402
from harness.sampler import Sampler, SamplerConfig  # noqa: E402
from harness.scorer import load_assignment  # noqa: E402
from harness.searcher import (  # noqa: E402
    SEGMENT_CAPACITY,
    anneal,
    build_problem,
    calibrate_temperatures,
    region_assignment_cost,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph")
    parser.add_argument("assignment")
    parser.add_argument("out_json")
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--iterations", type=int, default=50_000)
    parser.add_argument("--time-limit", type=float, default=300.0)
    parser.add_argument("--seed", type=int, default=777)
    args = parser.parse_args()

    graph = load_graph(args.graph)
    assignment = load_assignment(args.assignment)
    config = SamplerConfig(min_internal=160, max_internal=220, seed=args.seed)
    sampler = Sampler(graph, config)
    # Oversample: regions with permutable <= capacity are trivially optimal.
    regions, _ = sampler.sample_round(args.count * 2, seed=args.seed)
    rows = []
    for region in regions:
        if len(rows) >= args.count:
            break
        problem = build_problem(region)
        n = len(problem.initial_order)
        if n <= SEGMENT_CAPACITY:
            continue
        blocks = assignment.instr_block[problem.node_local]
        production_cost = region_assignment_cost(problem, blocks)
        canonical_cost = problem.order_cost(np.array(problem.initial_order, dtype=np.int32))
        t0, t1 = calibrate_temperatures(problem, samples=1000, seed=args.seed)
        started = time.time()
        result = anneal(problem, iterations=args.iterations, t0=t0, t1=t1,
                        seed=args.seed + region.meta["index"])
        sa_seconds = time.time() - started
        started = time.time()
        optimal, status = solve_optimal(problem, time_limit_s=args.time_limit)
        cpsat_seconds = time.time() - started
        rows.append(
            {
                "method": region.meta["method"],
                "permutable": n,
                "production_cost": production_cost,
                "canonical_cost": canonical_cost,
                "sa_cost": result.best_cost,
                "cpsat_cost": optimal,
                "cpsat_status": status,
                "sa_gap": (result.best_cost - optimal) / optimal if optimal else None,
                "sa_seconds": sa_seconds,
                "cpsat_seconds": cpsat_seconds,
            }
        )
        print(
            f"[gap] {region.meta['method']:4s} n={n}: prod={production_cost:.0f} "
            f"canon={canonical_cost:.0f} sa={result.best_cost:.0f} "
            f"opt={optimal:.0f} ({status}, sa {sa_seconds:.0f}s / cp {cpsat_seconds:.0f}s)"
        )
    gaps = np.array([r["sa_gap"] for r in rows if r["sa_gap"] is not None])
    report = {
        "config": {
            "count": args.count,
            "iterations": args.iterations,
            "time_limit": args.time_limit,
            "seed": args.seed,
        },
        "rows": rows,
        "summary": {
            "solved": int(gaps.size),
            "gap_median": float(np.median(gaps)) if gaps.size else None,
            "gap_max": float(gaps.max()) if gaps.size else None,
            "gap_mean": float(gaps.mean()) if gaps.size else None,
            "exact_optimal_frac": float((gaps == 0).mean()) if gaps.size else None,
        },
    }
    Path(args.out_json).write_text(json.dumps(report, indent=1))
    if gaps.size:
        print(f"[gap] solved {gaps.size}: median gap {np.median(gaps):.2%}, "
              f"max {gaps.max():.2%}, optimal-hit {(gaps == 0).mean():.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
