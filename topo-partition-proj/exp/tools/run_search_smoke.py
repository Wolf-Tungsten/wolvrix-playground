#!/usr/bin/env python3

"""Searcher smoke run (docs/04 Phase 0 task 4, Phase-1 final form): load a
few sampled regions, score both anchors (production restriction / canonical
order), run the annealing search with calibrated temperatures, and report
cost before/after.

Usage:

    run_search_smoke.py <regions_dir> <block_assignment.jsonl>
        [--regions K] [--iterations N] [--seed S]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.sampler import Region  # noqa: E402
from harness.scorer import load_assignment  # noqa: E402
from harness.searcher import (  # noqa: E402
    anneal,
    build_problem,
    calibrate_temperatures,
    region_assignment_cost,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("regions_dir")
    parser.add_argument("assignment")
    parser.add_argument("--regions", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    region_dir = Path(args.regions_dir)
    manifest = json.loads((region_dir / "manifest.json").read_text())
    assignment = load_assignment(args.assignment)
    entries = sorted(manifest["regions"], key=lambda e: e["internal"])
    picked = entries[: args.regions]
    print(f"[search] smoke on {len(picked)} smallest regions "
          f"(internal sizes: {[e['internal'] for e in picked]})")
    totals = {"production": 0.0, "canonical": 0.0, "best": 0.0}
    for entry in picked:
        region = Region.load(region_dir / manifest["files"][entry["index"]])
        started = time.time()
        problem = build_problem(region)
        production = region_assignment_cost(
            problem, assignment.instr_block[problem.node_local]
        )
        canonical = problem.order_cost(np.array(problem.initial_order, dtype=np.int32))
        t0, t1 = calibrate_temperatures(problem, samples=2000, seed=args.seed)
        result = anneal(
            problem,
            iterations=args.iterations,
            t0=t0,
            t1=t1,
            seed=args.seed + entry["index"],
        )
        elapsed = time.time() - started
        totals["production"] += production
        totals["canonical"] += canonical
        totals["best"] += result.best_cost
        print(
            f"[search] region {entry['index']:4d} ({entry['method']:4s}, "
            f"permutable {len(problem.initial_order)}): production={production:.0f} "
            f"canonical={canonical:.0f} best={result.best_cost:.0f} "
            f"(vs production -{(production - result.best_cost) / production * 100:.1f}%, "
            f"vs canonical -{(canonical - result.best_cost) / canonical * 100:.2f}%) "
            f"accepted={result.accepted}/{args.iterations} T=({t0:.2f},{t1:.3f}) "
            f"in {elapsed:.1f}s"
        )
    print(
        f"[search] total: production={totals['production']:.0f} "
        f"canonical={totals['canonical']:.0f} best={totals['best']:.0f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
