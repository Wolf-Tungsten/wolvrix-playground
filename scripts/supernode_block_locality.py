#!/usr/bin/env python3
"""Per-block locality comparison: gsim supernodes vs grhsim AM compute blocks.

Answers, for each side:
  1. per-block import count (distinct vars used in block but defined outside,
     non-state-write consumers only) bucketed by block size;
  2. cut profile over the block-id sequence (blocks are contiguous ranges of
     the partition DP sequence): def_use value edges crossing (<=k, >k);
  3. per crossing value: number of distinct consumer blocks.

Usage: supernode_block_locality.py GRAPH ASSIGN [GRAPH ASSIGN ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "topo-partition-proj" / "exp"))

import numpy as np

from harness.graph import load_graph
from harness.scorer import load_assignment

SIZE_BUCKETS = [(1, 5), (6, 15), (16, 35), (36, 64), (65, 128), (129, 256),
                (257, 512), (513, 10**9)]


def analyze(name: str, graph_path: str, assign_path: str) -> None:
    graph = load_graph(Path(graph_path), use_cache=True, verbose=False)
    assignment = load_assignment(Path(assign_path))
    instr_block = assignment.instr_block.astype(np.int64)
    commit_mask = assignment.commit_mask
    n_blocks = instr_block.max() + 1

    du_src = graph.du_src.astype(np.int64)
    du_dst = graph.du_dst.astype(np.int64)
    du_var = graph.du_var.astype(np.int64)
    state_write_consumer = graph.state_write[du_dst]

    # distinct def vars per block (compute-network vars only need def_use)
    var_def_block = np.full(graph.variables, -1, dtype=np.int64)
    # a var's def block = producer block of any def_use edge carrying it
    producer_block = instr_block[du_src]
    consumer_block = instr_block[du_dst]
    # def block: producer of the var (all producers of a var share one block
    # in these single-def exports)
    mask_def = var_def_block[du_var] == -1
    var_def_block[du_var[mask_def]] = producer_block[mask_def]

    # per-block imports: distinct (block, var) with consumer in block, def
    # outside block, consumer not state-write
    net = ~state_write_consumer
    cross_mask = (producer_block != consumer_block) & net
    cb = consumer_block[cross_mask]
    vv = du_var[cross_mask]
    pair = (cb.astype(np.uint64) << 32) | vv.astype(np.uint64)
    uniq_pair = np.unique(pair)
    import_block = (uniq_pair >> 32).astype(np.int64)
    imports_per_block = np.bincount(import_block, minlength=n_blocks)

    # block sizes in node units (atoms when available)
    if assignment.instr_atom is not None:
        pair_ba = (instr_block.astype(np.uint64) << 32) | assignment.instr_atom.astype(np.uint64)
        sizes = np.bincount((np.unique(pair_ba) >> 32).astype(np.int64), minlength=n_blocks)
    else:
        sizes = np.bincount(instr_block, minlength=n_blocks)
    compute_block = ~commit_mask

    print(f"== {name}")
    print(f"blocks={int(compute_block.sum())} (compute)  total_imports={int(imports_per_block[compute_block].sum())}")
    print("size_bucket        blocks  imports/blk  import_mass%")
    for lo, hi in SIZE_BUCKETS:
        sel = compute_block & (sizes >= lo) & (sizes <= hi)
        cnt = int(sel.sum())
        if cnt == 0:
            continue
        imp = imports_per_block[sel]
        print(f"  {lo:>4}-{hi if hi < 10**9 else 'inf':>4} {cnt:>9}  "
              f"{float(imp.mean()):>10.2f}  {100.0 * float(imp.sum()) / max(1, int(imports_per_block[compute_block].sum())):>10.1f}")

    # cut profile between consecutive block ids (sequence locality)
    # boundary after block k: def_use edges with producer <= k < consumer
    # (block ids follow the DP sequence on both sides)
    order = np.argsort(consumer_block, kind="stable")
    cb_sorted = consumer_block[order]
    # for each boundary k, edges with consumer_block > k and producer_block <= k
    # computed via counting: total edges with consumer > k minus edges with
    # producer > k and consumer > k ... do it directly per boundary instead:
    boundaries = np.arange(1, n_blocks)
    cross_counts = np.zeros(n_blocks - 1, dtype=np.int64)
    pb = producer_block
    cbs = consumer_block
    # edge crosses boundary k iff pb <= k < cb or cb <= k < pb
    lo = np.minimum(pb, cbs)
    hi = np.maximum(pb, cbs)
    # count per boundary via histogram of [lo, hi) intervals
    diff = np.zeros(n_blocks + 1, dtype=np.int64)
    same = lo == hi
    np.add.at(diff, lo[~same], 1)
    np.add.at(diff, hi[~same], -1)
    active = np.cumsum(diff)[: n_blocks - 1]
    cross_counts = active
    print("cut profile (def_use edges crossing block boundary k..k+1):")
    qs = np.percentile(cross_counts, [10, 25, 50, 75, 90, 99])
    print(f"  p10={qs[0]:.0f} p25={qs[1]:.0f} p50={qs[2]:.0f} p75={qs[3]:.0f} "
          f"p90={qs[4]:.0f} p99={qs[5]:.0f} mean={cross_counts.mean():.1f}")
    free = int((cross_counts <= 2).sum())
    print(f"  boundaries with cut<=2: {free} / {cross_counts.size} ({100.0*free/max(1,cross_counts.size):.1f}%)")

    # per crossing value: number of distinct consumer blocks
    if vv.size:
        cons = np.unique(pair)  # (block,var) pairs already unique
        var_of_pair = cons & np.uint64(0xFFFFFFFF)
        _, counts = np.unique(var_of_pair, return_counts=True)
        print(f"crossing values={counts.size}  consumer-blocks/value: "
              f"mean={counts.mean():.2f} p50={np.percentile(counts,50):.0f} "
              f"p90={np.percentile(counts,90):.0f} p99={np.percentile(counts,99):.0f}")


def main() -> None:
    args = sys.argv[1:]
    for i in range(0, len(args), 3):
        analyze(args[i], args[i + 1], args[i + 2])


if __name__ == "__main__":
    main()
