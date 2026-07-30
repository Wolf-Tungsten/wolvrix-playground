#!/usr/bin/env python3

"""Full-graph no-coarsen baseline (docs/04 D5 second reference, Phase 1
decision input): deterministic Kahn canonical order restricted to non-commit
instructions + segment DP (new cost formula, capacity 128) on the whole
XiangShan instruction graph — no coarsen, exactly the deployable alternative
to the production schedule. Commit (state_write) instructions keep their
production commit blocks so the scoreboard compares apples-to-apples with
the plain baseline of docs/06 (cost 6,468,546).

Usage:

    run_fullgraph_plaindp.py <instruction_graph.jsonl> <block_assignment.jsonl>
        [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.graph import build_csr, load_graph  # noqa: E402
from harness.kernel import KernelDP  # noqa: E402
from harness.scorer import load_assignment, score_assignment  # noqa: E402
from harness.searcher import SEGMENT_CAPACITY  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph")
    parser.add_argument("assignment")
    parser.add_argument("--json", default=None)
    parser.add_argument("--penalty", type=float, default=0.0,
                        help="per-segment penalty inside the DP objective")
    args = parser.parse_args()

    started = time.time()
    graph = load_graph(args.graph)
    assignment = load_assignment(args.assignment)
    n_graph = graph.instructions
    compute = ~graph.state_write

    # Order: canonical Kahn order restricted to non-commit instructions.
    order = graph.topo_order[compute[graph.topo_order]].astype(np.int32)
    # uses CSR keyed by global node id: def_use + external_read edges whose
    # consumer is a non-commit instruction (commit reads are free).
    du_keep = compute[graph.du_dst]
    er_keep = compute[graph.er_dst]
    use_key = np.concatenate([graph.du_dst[du_keep], graph.er_dst[er_keep]])
    use_val = np.concatenate([graph.du_var[du_keep], graph.er_var[er_keep]])
    use_off, use_var = build_csr(use_key, use_val, n_graph)
    # defs CSR keyed by global node id: every def_use source defines its var.
    def_off, def_var = build_csr(graph.du_src, graph.du_var, n_graph)
    # weights per variable (consistent across edges).
    weight = np.zeros(graph.variables, dtype=np.int64)
    all_width_key = np.concatenate(
        [graph.du_var, graph.er_var]
    )
    all_width = np.concatenate([graph.du_width, graph.er_width])
    weight[all_width_key] = np.maximum(1, (all_width + 63) // 64)
    print(f"[plaindp] setup in {time.time() - started:.1f}s: "
          f"{order.size} compute instructions (of {n_graph})")

    started = time.time()
    kernel = KernelDP.from_csr(
        use_off, use_var, def_off, def_var, weight, SEGMENT_CAPACITY, n=order.size
    )
    kernel.penalty = args.penalty
    cost = kernel.cost_with_prev(order)
    cuts = kernel.cuts()
    print(f"[plaindp] segment DP in {time.time() - started:.1f}s: "
          f"cost={cost:.0f}, segments={len(cuts)}")

    # Build the mixed assignment: new compute segments + production commit blocks.
    segment_of = np.zeros(order.size, dtype=np.int64)
    for seg_index, (begin, end) in enumerate(zip(cuts, cuts[1:] + [order.size])):
        segment_of[begin:end] = seg_index
    compute_block = segment_of + 1  # block ids 1..K
    commit_offset = int(compute_block.max()) + 1
    # Dense remap of the production commit block ids used by state_writes.
    sw = graph.state_write
    prod_commit_ids = np.unique(assignment.instr_block[sw])
    commit_remap = np.zeros(int(prod_commit_ids.max()) + 1, dtype=np.int64)
    commit_remap[prod_commit_ids] = np.arange(prod_commit_ids.size)
    instr_block = np.zeros(n_graph, dtype=np.uint32)
    instr_block[order] = compute_block.astype(np.uint32)
    instr_block[sw] = commit_offset + commit_remap[assignment.instr_block[sw]]
    # slot 0 = padding; 1..K compute; K+1..K+497 commit (production's commits).
    commit_mask = np.zeros(commit_offset + prod_commit_ids.size, dtype=bool)
    commit_mask[commit_offset:] = True
    board = score_assignment(graph, instr_block, commit_mask)
    reference = {
        "cost": assignment.header["incoming_copy_cost"],
        "dag_edges": assignment.header["dag_edges"],
        "compute_compute_value_pairs": assignment.header["compute_compute_value_pairs"],
        "footprint": assignment.header["blocks"],
    }
    payload = {
        "penalty": args.penalty,
        "plaindp_nocoarsen": board.as_dict(),
        "production_plain": reference,
        "delta_pct": {
            key: (board.as_dict()[mapped] - reference[key]) / reference[key] * 100
            for key, mapped in [
                ("cost", "cost"),
                ("dag_edges", "dag_edges"),
                ("compute_compute_value_pairs", "compute_compute_value_pairs"),
                ("footprint", "footprint"),
            ]
        },
        "segments": len(cuts),
    }
    print(f"[plaindp] no-coarsen: {board.as_dict()}")
    print(f"[plaindp] production: {reference}")
    for key, delta in payload["delta_pct"].items():
        print(f"[plaindp]   {key}: {delta:+.1f}%")
    if args.json:
        Path(args.json).write_text(json.dumps(payload, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
