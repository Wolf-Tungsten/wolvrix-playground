#!/usr/bin/env python3

"""Full-graph ordering-headroom experiment (docs/04 risk R1, docs/08 §7).

Runs the Phase-1 search on a WHOLE instruction graph (no region boundaries):
canonical Kahn order vs simulated-annealing chains vs random linear
extensions, all scored by the same segment DP (C kernel). The experiment
decides whether ordering has global headroom worth learning (GNN) or the
deterministic canonical order is already all there is.

Anchors printed/written:
- production: the exported production assignment (plain baseline) scored by
  the harness scoreboard;
- canonical: deterministic order + segment DP (the no-coarsen baseline);
- SA chains: best over N parallel annealing chains;
- random extensions: valid random topological orders (null hypothesis —
  if even these land close to canonical, the cost function is structurally
  insensitive to ordering).

Usage:
    run_fullgraph_search.py <instruction_graph.jsonl> <block_assignment.jsonl>
        <out_dir> [--chains N] [--iterations K] [--seed S] [--penalty L]
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.fullgraph import (  # noqa: E402
    FullGraphProblem,
    anneal_fullgraph,
    build_fullgraph_problem,
    calibrate_temperatures,
    random_group_orders,
    verify_linear_extension,
)
from harness.graph import load_graph  # noqa: E402
from harness.scorer import load_assignment, score_assignment  # noqa: E402

_PROBLEM: FullGraphProblem | None = None
_CONFIG: dict | None = None


def _chain(index: int) -> dict:
    assert _PROBLEM is not None and _CONFIG is not None
    seed = _CONFIG["seed"] + index
    start = None
    t0, t1 = _CONFIG["t0"], _CONFIG["t1"]
    start_cost = None
    if _CONFIG["start"] == "random":
        # Basin probe: each chain calibrates its own temperature scale on a
        # fresh random linear extension and anneals from there.
        start = random_group_orders(_PROBLEM, 1, seed=seed + 7919)[0]
        start_cost = _PROBLEM.cost(start)
        t0, t1 = calibrate_temperatures(
            _PROBLEM, samples=_CONFIG["calibration_samples"], seed=seed, start_order=start
        )
    result = anneal_fullgraph(
        _PROBLEM,
        iterations=_CONFIG["iterations"],
        t0=t0,
        t1=t1,
        swap_frac=_CONFIG["swap_frac"],
        seed=seed,
        log_every=max(1, _CONFIG["iterations"] // 10),
        start_order=start,
    )
    return {
        "chain": index,
        "initial_cost": result.initial_cost,
        "start_cost": start_cost,
        "t0": t0,
        "t1": t1,
        "best_cost": result.best_cost,
        "accepted": result.accepted,
        "history": result.history,
        "best_order": np.array(result.best_order, dtype=np.int32),
    }


def _scoreboard(graph, assignment, kernel, node_order):
    """Health metrics of a node order: DP segments for compute nodes plus the
    production commit blocks (same mixed-assignment semantics as
    tools/run_fullgraph_plaindp.py)."""
    cost = kernel.cost_with_prev(node_order.astype(np.int32))
    cuts = kernel.cuts()
    segment_of = np.zeros(node_order.size, dtype=np.int64)
    for seg_index, (begin, end) in enumerate(zip(cuts, cuts[1:] + [node_order.size])):
        segment_of[begin:end] = seg_index
    compute_block = segment_of + 1
    commit_offset = int(compute_block.max()) + 1
    sw = graph.state_write
    prod_commit_ids = np.unique(assignment.instr_block[sw])
    commit_remap = np.zeros(int(prod_commit_ids.max()) + 1, dtype=np.int64)
    commit_remap[prod_commit_ids] = np.arange(prod_commit_ids.size)
    instr_block = np.zeros(graph.instructions, dtype=np.uint32)
    instr_block[node_order] = compute_block.astype(np.uint32)
    instr_block[sw] = commit_offset + commit_remap[assignment.instr_block[sw]]
    commit_mask = np.zeros(commit_offset + prod_commit_ids.size, dtype=bool)
    commit_mask[commit_offset:] = True
    board = score_assignment(graph, instr_block, commit_mask)
    return cost, len(cuts), board.as_dict()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph")
    parser.add_argument("assignment")
    parser.add_argument("out_dir")
    parser.add_argument("--chains", type=int, default=32)
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--calibration-samples", type=int, default=200)
    parser.add_argument("--swap-frac", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=20260730)
    parser.add_argument("--penalty", type=float, default=0.0)
    parser.add_argument("--random-extensions", type=int, default=8)
    parser.add_argument("--capacity", type=int, default=128)
    parser.add_argument("--start", choices=["canonical", "random"], default="canonical",
                        help="chain starting point: canonical order, or per-chain random "
                             "linear extensions with per-chain temperature calibration")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()

    graph = load_graph(args.graph)
    assignment = load_assignment(args.assignment)
    problem = build_fullgraph_problem(graph, capacity=args.capacity, penalty=args.penalty)
    n_edges = sum(len(s) for s in problem.succs)
    print(
        f"[fg] {graph.instructions} instructions, {problem.node_ids.size} compute, "
        f"{problem.n_groups} groups, {n_edges} legality edges, "
        f"setup {time.time() - started:.1f}s",
        flush=True,
    )

    if args.start == "canonical":
        t0, t1 = calibrate_temperatures(problem, samples=args.calibration_samples, seed=args.seed)
        print(f"[fg] calibrated t0={t0:.4f} t1={t1:.6f} ({time.time() - started:.1f}s)", flush=True)
    else:
        t0 = t1 = None  # each random-start chain calibrates its own scale
        print(f"[fg] random-start mode: per-chain calibration ({time.time() - started:.1f}s)", flush=True)

    global _PROBLEM, _CONFIG
    _PROBLEM = problem
    _CONFIG = {
        "iterations": args.iterations,
        "t0": t0,
        "t1": t1,
        "swap_frac": args.swap_frac,
        "seed": args.seed,
        "start": args.start,
        "calibration_samples": args.calibration_samples,
    }
    chains: list[dict] = []
    ctx = mp.get_context("fork")
    with ctx.Pool(args.chains) as pool:
        for row in pool.imap_unordered(_chain, range(args.chains)):
            chains.append(row)
            extra = f" start={row['start_cost']:.0f}" if row.get("start_cost") else ""
            print(
                f"[fg] chain {row['chain']}: best={row['best_cost']:.0f} "
                f"accepted={row['accepted']}{extra} ({time.time() - started:.1f}s)",
                flush=True,
            )
    chains.sort(key=lambda r: r["best_cost"])

    random_costs: list[float] = []
    if args.random_extensions > 0:
        for order in random_group_orders(problem, args.random_extensions, args.seed + 999):
            random_costs.append(problem.cost(order))
        print(f"[fg] random extensions: {random_costs}", flush=True)

    canonical_groups = np.array(problem.initial_order, dtype=np.int32)
    canonical_cost = problem.cost(canonical_groups)
    best = chains[0]
    best_groups = best["best_order"]
    bad_edges = verify_linear_extension(problem, best_groups)
    print(
        f"[fg] canonical={canonical_cost:.0f} best={best['best_cost']:.0f} "
        f"(chain {best['chain']}), backward edges in best order: {bad_edges}",
        flush=True,
    )
    if bad_edges != 0:
        raise RuntimeError("SA produced an illegal order")

    # Health-metric scoreboard for canonical and best orders.
    canonical_nodes = problem.node_order(canonical_groups)
    best_nodes = problem.node_order(best_groups)
    can_cost, can_segments, can_board = _scoreboard(graph, assignment, problem.kernel, canonical_nodes)
    best_cost, best_segments, best_board = _scoreboard(graph, assignment, problem.kernel, best_nodes)
    reference = {
        "cost": assignment.header["incoming_copy_cost"],
        "dag_edges": assignment.header["dag_edges"],
        "compute_compute_value_pairs": assignment.header["compute_compute_value_pairs"],
        "footprint": assignment.header["blocks"],
    }

    summary = {
        "config": {
            "chains": args.chains,
            "iterations": args.iterations,
            "calibration_samples": args.calibration_samples,
            "swap_frac": args.swap_frac,
            "seed": args.seed,
            "penalty": args.penalty,
            "capacity": args.capacity,
            "start": args.start,
            "t0": t0,
            "t1": t1,
        },
        "graph": {
            "instructions": graph.instructions,
            "compute": int(problem.node_ids.size),
            "groups": problem.n_groups,
            "legality_edges": n_edges,
            "comb_loop_atoms": int(graph.comb_loop_atom.sum()),
        },
        "canonical": {"cost": canonical_cost, "segments": can_segments, "board": can_board},
        "best": {
            "cost": best["best_cost"],
            "chain": best["chain"],
            "accepted": best["accepted"],
            "segments": best_segments,
            "board": best_board,
        },
        "chains": [
            {k: v for k, v in row.items() if k != "best_order"} for row in chains
        ],
        "random_extensions": random_costs,
        "production": reference,
        "improvement_vs_canonical": (canonical_cost - best["best_cost"]) / canonical_cost,
        "improvement_vs_production": (reference["cost"] - best["best_cost"]) / reference["cost"],
        "wall_seconds": time.time() - started,
    }
    (out_dir / "fullgraph_search.json").write_text(json.dumps(summary, indent=1))
    np.savez(
        out_dir / "fullgraph_best.npz",
        group_order=best_groups,
        node_order=best_nodes,
        best_cost=np.array([best["best_cost"]]),
    )
    print(f"[fg] vs canonical: {summary['improvement_vs_canonical'] * 100:+.2f}%", flush=True)
    print(f"[fg] vs production: {summary['improvement_vs_production'] * 100:+.2f}%", flush=True)
    print(f"[fg] wrote {out_dir / 'fullgraph_search.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
