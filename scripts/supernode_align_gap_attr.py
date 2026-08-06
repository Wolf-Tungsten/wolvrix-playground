#!/usr/bin/env python3

"""Gap attribution on the NO0010 flat-graph baseline (supernode-align topic).

For each side (gsim flattened prod graph, AM irscale-final graph) report:

- value fan-out structure (def_use out-degree), split by crossing / not;
- cross_values decomposed by consumer kind (compute vs commit/state write);
- producer-op histogram of crossing values (overall and per consumer kind);
- crossing values whose producer has def_use out-degree 1 (absorbable chain
  links that the coarsen did not absorb) vs out-degree >= 2 (structural).

Usage:
    supernode_align_gap_attr.py <instruction_graph.jsonl> <block_assignment.jsonl> [label]

Run with the repo venv (needs numpy): .venv/bin/python.
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "topo-partition-proj" / "exp"))

import numpy as np  # noqa: E402

from harness.graph import load_graph  # noqa: E402
from harness.scorer import load_assignment  # noqa: E402


def op_hist(names: list[str], ops: np.ndarray, limit: int = 15) -> str:
    counts = Counter(ops.tolist())
    total = max(ops.size, 1)
    parts = [
        f"{names[op] if op < len(names) else op}={count}({100.0 * count / total:.1f}%)"
        for op, count in counts.most_common(limit)
    ]
    return " ".join(parts)


def main() -> int:
    if len(sys.argv) < 3:
        sys.stderr.write(__doc__ or "")
        return 2
    label = sys.argv[3] if len(sys.argv) > 3 else "side"
    started = time.time()
    graph = load_graph(sys.argv[1], use_cache=True, verbose=False)
    assignment = load_assignment(sys.argv[2])
    instr_block = assignment.instr_block.astype(np.int64)
    commit_mask = assignment.commit_mask
    names = graph.opcode_names

    # def_use out-degree per variable == per producer instruction (SSA).
    outdeg = np.bincount(graph.du_var, minlength=graph.variables)
    var_def = graph.var_def()

    producer_block = instr_block[graph.du_src.astype(np.int64)]
    consumer_block = instr_block[graph.du_dst.astype(np.int64)]
    cross = producer_block != consumer_block
    cross_var = np.unique(graph.du_var[cross])
    cross_outdeg = outdeg[cross_var]
    cross_producer = var_def[cross_var]
    cross_op = graph.op[cross_producer]
    print(f"[{label}] load+base {time.time() - started:.1f}s")

    # consumer-kind decomposition of crossing values
    dst_commit = commit_mask[consumer_block[cross]]
    cross_edge_var = graph.du_var[cross]
    var_commit = np.unique(cross_edge_var[dst_commit])
    var_compute = np.unique(cross_edge_var[~dst_commit])
    print(f"[{label}] instructions={graph.instructions} variables={graph.variables} "
          f"def_use={graph.du_src.size} blocks={assignment.blocks}")
    print(f"[{label}] commit_kind_instructions={int(graph.state_write.sum())} "
          f"commit_blocks={assignment.commit_blocks}")
    print(f"[{label}] cross_values={cross_var.size} compute_consumer={var_compute.size} "
          f"commit_consumer={var_commit.size}")

    # fan-out structure of ALL values (defined ones)
    defined = var_def >= 0
    deg = outdeg[defined]
    print(f"[{label}] all defined values: {defined.sum()} "
          f"fanout0={int((deg == 0).sum())} fanout1={int((deg == 1).sum())} "
          f"fanout2={int((deg == 2).sum())} fanout>=3={int((deg >= 3).sum())}")

    # crossing values by producer out-degree
    print(f"[{label}] crossing values by producer outdeg: "
          f"outdeg1={int((cross_outdeg == 1).sum())} "
          f"outdeg2={int((cross_outdeg == 2).sum())} "
          f"outdeg>=3={int((cross_outdeg >= 3).sum())}")

    # producer op histograms
    print(f"[{label}] crossing values producer ops: {op_hist(names, cross_op)}")
    if var_compute.size:
        comp_op = graph.op[var_def[var_compute]]
        print(f"[{label}] compute-consumer crossing producer ops: {op_hist(names, comp_op)}")
    if var_commit.size:
        com_op = graph.op[var_def[var_commit]]
        print(f"[{label}] commit-consumer crossing producer ops: {op_hist(names, com_op)}")
        # how many commit-consumer crossing values are ALSO consumed by compute?
        both = np.isin(var_commit, var_compute)
        print(f"[{label}] commit-consumer crossing values also consumed by compute: "
              f"{int(both.sum())} / {var_commit.size}")

    # outdeg-1 crossing values: why not absorbed? bucket by producer block size
    if (cross_outdeg == 1).any():
        solo = cross_var[cross_outdeg == 1]
        solo_producer_block = instr_block[var_def[solo].astype(np.int64)]
        sizes = np.bincount(instr_block[instr_block >= 0], minlength=assignment.blocks)
        solo_sizes = sizes[solo_producer_block]
        print(f"[{label}] outdeg1-crossing producer block size: "
              f"p50={int(np.percentile(solo_sizes, 50))} "
              f"p90={int(np.percentile(solo_sizes, 90))} "
              f"max={int(solo_sizes.max())} "
              f"share>=128={100.0 * float((solo_sizes >= 128).mean()):.1f}%")

    # fanout>=2 values that do NOT cross (absorbed): reference for absorb rate
    multi = defined & (outdeg >= 2)
    multi_var = np.nonzero(multi)[0]
    multi_cross = np.isin(multi_var, cross_var)
    print(f"[{label}] fanout>=2 values: {multi_var.size} "
          f"crossing={int(multi_cross.sum())} ({100.0 * float(multi_cross.mean()):.1f}%) "
          f"absorbed={int((~multi_cross).sum())}")
    print(f"[{label}] done {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
