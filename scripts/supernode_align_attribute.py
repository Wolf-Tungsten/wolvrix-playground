#!/usr/bin/env python3

"""Attribute cross-block values of a block assignment (supernode-align topic).

For one topo-proj export pair (instruction graph + block assignment, either
side — gsim or AM), break down the `cross_values` primary metric:

- width buckets of crossing values;
- fan-out: distinct consumer blocks per crossing value;
- topological block distance of crossing def_use edges (block ids are dense
  in topological order on both sides, so |dst_block - src_block| is a
  locality proxy);
- share of def_use edges that cross blocks.

Usage:
    supernode_align_attribute.py <instruction_graph.jsonl> <block_assignment.jsonl>

Run with the repo venv (needs numpy): .venv/bin/python.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "topo-partition-proj" / "exp"))

import numpy as np  # noqa: E402

from harness.graph import load_graph  # noqa: E402
from harness.scorer import load_assignment  # noqa: E402


def bucketize(values: np.ndarray, edges: list[int]) -> list[int]:
    counts = []
    for lo, hi in zip([0] + edges, edges + [None]):
        if hi is None:
            counts.append(int((values > lo).sum()) if lo else int((values == 0).sum()))
        elif lo == 0:
            counts.append(int((values <= hi).sum()))
        else:
            counts.append(int(((values > lo) & (values <= hi)).sum()))
    return counts


def main() -> int:
    if len(sys.argv) != 3:
        sys.stderr.write(__doc__ or "")
        return 2
    started = time.time()
    graph = load_graph(sys.argv[1], use_cache=True, verbose=False)
    assignment = load_assignment(sys.argv[2])
    instr_block = assignment.instr_block.astype(np.int64)

    producer_block = instr_block[graph.du_src.astype(np.int64)]
    consumer_block = instr_block[graph.du_dst.astype(np.int64)]
    cross = producer_block != consumer_block
    cross_var = graph.du_var[cross]
    cross_width = graph.du_width[cross]
    print(f"[load] {time.time() - started:.1f}s")

    unique_vars, first = np.unique(cross_var, return_index=True)
    unique_widths = cross_width[first]
    print(f"cross_values={unique_vars.size} cross_edges={cross.sum()} total_def_use={cross.size} "
          f"cross_share={100.0 * cross.sum() / max(cross.size, 1):.2f}%")

    width_edges = [1, 8, 32, 64]
    width_counts = bucketize(unique_widths, width_edges)
    print("crossing value widths: " + " ".join(
        f"{label}={count}" for label, count in zip(
            ["<=1", "2-8", "9-32", "33-64", ">64"], width_counts)))

    # fan-out: distinct consumer blocks per crossing value
    fan_keys = (cross_var.astype(np.int64) << 32) | consumer_block[cross]
    _, fan_counts = np.unique(cross_var, return_counts=True)
    pair_keys = np.unique(fan_keys)
    pair_var = (pair_keys >> 32).astype(np.int64)
    _, fanout = np.unique(pair_var, return_counts=True)
    fan_edges = [1, 2, 4, 16]
    fan_labels = ["1", "2", "3-4", "5-16", ">16"]
    fan_counts_b = [
        int((fanout == 1).sum()),
        int((fanout == 2).sum()),
        int(((fanout >= 3) & (fanout <= 4)).sum()),
        int(((fanout >= 5) & (fanout <= 16)).sum()),
        int((fanout > 16).sum()),
    ]
    print("crossing value consumer-block fan-out: " + " ".join(
        f"{label}={count}" for label, count in zip(fan_labels, fan_counts_b)))

    # topological block distance of crossing edges
    distance = consumer_block[cross] - producer_block[cross]
    backward = int((distance <= 0).sum())
    distance = distance[distance > 0]
    dist_edges = [1, 4, 16, 64, 256]
    dist_labels = ["1", "2-4", "5-16", "17-64", "65-256", ">256"]
    dist_counts = [
        int((distance == 1).sum()),
        int(((distance >= 2) & (distance <= 4)).sum()),
        int(((distance >= 5) & (distance <= 16)).sum()),
        int(((distance >= 17) & (distance <= 64)).sum()),
        int(((distance >= 65) & (distance <= 256)).sum()),
        int((distance > 256).sum()),
    ]
    print(f"crossing edges with non-forward block distance (<=0): {backward}")
    print("crossing edge block distance: " + " ".join(
        f"{label}={count}" for label, count in zip(dist_labels, dist_counts)))
    if distance.size:
        print(f"block distance p50={int(np.percentile(distance, 50))} "
              f"p90={int(np.percentile(distance, 90))} "
              f"p99={int(np.percentile(distance, 99))} max={int(distance.max())}")
    print(f"[done] {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
