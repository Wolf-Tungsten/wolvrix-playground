#!/usr/bin/env python3

"""Phase-1 label pipeline (docs/04 Phase 1 task 2 + task 4 anchors).

For every sampled region: score the two baselines (production assignment
restricted to the region; canonical topo order + segment DP), calibrate the
annealing temperatures from the move-delta distribution, run the full
simulated-annealing search (D7), and write the best permutation + scores to
<out_dir>/label_XXXX.npz. The manifest aggregates the M1 comparison.

Usage:

    run_label_pipeline.py <regions_dir> <block_assignment.jsonl> <out_dir>
        [--iterations N] [--workers W] [--limit K] [--seed S]
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import time
from pathlib import Path

import numpy as np

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.sampler import Region  # noqa: E402
from harness.scorer import load_assignment  # noqa: E402
from harness.searcher import (  # noqa: E402
    anneal,
    build_problem,
    calibrate_temperatures,
    region_assignment_cost,
)

# Fork-inherited shared state (loaded once in the parent, see main()).
_MANIFEST = None
_REGION_DIR = None
_INSTR_BLOCK = None


def _label_one(index: int, iterations: int, seed: int) -> dict:
    region = Region.load(_REGION_DIR / _MANIFEST["files"][index])
    started = time.time()
    problem = build_problem(region)
    blocks = _INSTR_BLOCK[problem.node_local]
    production_cost = region_assignment_cost(problem, blocks)
    canonical_cost = problem.order_cost(np.array(problem.initial_order, dtype=np.int32))
    t0, t1 = calibrate_temperatures(problem, samples=2000, seed=seed)
    result = anneal(problem, iterations=iterations, t0=t0, t1=t1, seed=seed)
    elapsed = time.time() - started
    best_global = problem.node_local[np.array(result.best_order, dtype=np.int64)]
    out = {
        "index": index,
        "method": _MANIFEST["regions"][index]["method"],
        "permutable": len(problem.initial_order),
        "production_cost": production_cost,
        "canonical_cost": canonical_cost,
        "best_cost": result.best_cost,
        "iterations": iterations,
        "accepted": result.accepted,
        "t0": t0,
        "t1": t1,
        "seconds": elapsed,
    }
    np.savez(
        _OUT_DIR / f"label_{index:04d}.npz",
        index=np.array([index]),
        order_global=best_global.astype(np.uint32),
        production_cost=np.array([production_cost]),
        canonical_cost=np.array([canonical_cost]),
        best_cost=np.array([result.best_cost]),
    )
    return out


_OUT_DIR: Path = Path()


def main() -> int:
    global _OUT_DIR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("regions_dir")
    parser.add_argument("assignment")
    parser.add_argument("out_dir")
    parser.add_argument("--iterations", type=int, default=100_000)
    parser.add_argument("--workers", type=int, default=8,
                        help="shared machine: keep it to 8 unless told otherwise")
    parser.add_argument("--limit", type=int, default=0, help="only the first K regions")
    parser.add_argument("--seed", type=int, default=20260730)
    args = parser.parse_args()

    _OUT_DIR = Path(args.out_dir)
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Preload shared state in the parent; forked workers inherit it (COW),
    # so the 233 MB assignment is parsed exactly once.
    global _MANIFEST, _REGION_DIR, _INSTR_BLOCK
    _REGION_DIR = Path(args.regions_dir)
    _MANIFEST = json.loads((_REGION_DIR / "manifest.json").read_text())
    _INSTR_BLOCK = load_assignment(args.assignment).instr_block
    total = len(_MANIFEST["files"])
    count = min(args.limit, total) if args.limit else total
    # Resume support: skip regions whose label file already exists (e.g.
    # after a worker-count change restart).
    pending = [
        index
        for index in range(count)
        if not (_OUT_DIR / f"label_{index:04d}.npz").exists()
    ]
    started = time.time()
    print(f"[label] {len(pending)} regions pending ({count - len(pending)} done), "
          f"{args.iterations} iterations, {args.workers} workers")
    ctx = mp.get_context("fork")
    with ctx.Pool(args.workers) as pool:
        results = pool.starmap(
            _label_one,
            [(index, args.iterations, args.seed + index) for index in pending],
            chunksize=1,
        )
    # Rebuild result rows for previously completed regions from their npz.
    done_results = []
    for index in range(count):
        if index in pending:
            continue
        data = np.load(_OUT_DIR / f"label_{index:04d}.npz")
        done_results.append(
            {
                "index": index,
                "method": _MANIFEST["regions"][index]["method"],
                "permutable": int(data["order_global"].size),
                "production_cost": float(data["production_cost"][0]),
                "canonical_cost": float(data["canonical_cost"][0]),
                "best_cost": float(data["best_cost"][0]),
                "iterations": None,
                "accepted": None,
                "t0": None,
                "t1": None,
                "seconds": None,
            }
        )
    results = sorted(results + done_results, key=lambda r: r["index"])
    prod = np.array([r["production_cost"] for r in results])
    canon = np.array([r["canonical_cost"] for r in results])
    best = np.array([r["best_cost"] for r in results])
    valid = prod > 0
    improv_prod = (prod[valid] - best[valid]) / prod[valid]
    improv_canon = (canon[valid] - best[valid]) / canon[valid]
    summary = {
        "regions": len(results),
        "iterations": args.iterations,
        "seed": args.seed,
        "wall_seconds": time.time() - started,
        "improvement_vs_production": {
            "median": float(np.median(improv_prod)),
            "mean": float(improv_prod.mean()),
            "p25": float(np.percentile(improv_prod, 25)),
            "p75": float(np.percentile(improv_prod, 75)),
            "min": float(improv_prod.min()),
            "frac_improved": float((best[valid] < prod[valid]).mean()),
        },
        "improvement_vs_canonical": {
            "median": float(np.median(improv_canon)),
            "mean": float(improv_canon.mean()),
            "p25": float(np.percentile(improv_canon, 25)),
            "p75": float(np.percentile(improv_canon, 75)),
            "min": float(improv_canon.min()),
            "frac_improved": float((best[valid] < canon[valid]).mean()),
        },
        "results": results,
    }
    with open(_OUT_DIR / "manifest.json", "w") as stream:
        json.dump(summary, stream, indent=1)
    print(f"[label] done in {summary['wall_seconds']:.0f}s")
    print(f"[label] vs production: median {summary['improvement_vs_production']['median']:.1%} "
          f"(p25 {summary['improvement_vs_production']['p25']:.1%}, "
          f"p75 {summary['improvement_vs_production']['p75']:.1%})")
    print(f"[label] vs canonical:  median {summary['improvement_vs_canonical']['median']:.1%} "
          f"(p25 {summary['improvement_vs_canonical']['p25']:.1%}, "
          f"p75 {summary['improvement_vs_canonical']['p75']:.1%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
