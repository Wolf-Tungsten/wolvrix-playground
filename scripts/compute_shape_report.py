#!/usr/bin/env python3
"""Shape report for a split AM compute graph export vs the gsim flattened
baseline (compute-partition topic).

Usage: .venv/bin/python scripts/compute_shape_report.py [compute.jsonl]
Default: build/xs/am-split-export-opt/named.compute.jsonl

Prints node count, ge2 node count, summed out-degree (def_use (src,dst)
deduped, same caliber as compute_partition_metrics.py section B), and the
per-op ge2 table next to the gsim reference numbers captured from
fanout_attr.json task1 (xs_gsim_flat_prod_20260804).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

PATH = Path(sys.argv[1] if len(sys.argv) > 1 else
            "build/xs/am-split-export-opt/named.compute.jsonl")

# gsim flattened baseline (state_write excluded), from
# build/xs/am-split-export/fanout_attr.json task1_opcode.
GSIM_GE2 = {
    "and": 67864, "or": 23642, "not": 829, "mux": 21314, "eq": 30363,
    "ne": 594, "xor": None, "slice": 3853, "concat": 23778, "when": 3464,
    "mem.read": 313, "ref": 2468, "const": 64,
}
GSIM_TOTAL_GE2 = 252832
GSIM_SUM_OUTDEG = None  # not tracked in NO0003


def main() -> int:
    gids, ops = [], []
    es, ed = [], []
    with open(PATH) as f:
        for line in f:
            line = line.replace('\\"', '"')
            if '"record":"node"' in line:
                r = json.loads(line)
                gids.append(r["id"])
                ops.append(r["opcode"])
            elif '"kind":"def_use"' in line:
                r = json.loads(line)
                es.append(r["src"])
                ed.append(r["dst"])
    gid = np.array(gids, dtype=np.int64)
    lut = np.full(int(gid.max()) + 1, -1, dtype=np.int64)
    lut[gid] = np.arange(gid.size, dtype=np.int64)
    es = np.array(es, dtype=np.int64)
    ed = np.array(ed, dtype=np.int64)
    keep = (lut[es] >= 0) & (lut[ed] >= 0)
    es, ed = lut[es[keep]], lut[ed[keep]]
    n = len(ops)
    key = np.unique((es << 32) | ed)
    us = (key >> 32).astype(np.int64)
    outdeg = np.bincount(us, minlength=n)
    ge2 = outdeg >= 2
    total_ge2 = int(ge2.sum())
    sum_outdeg = int(outdeg.sum())
    per_op: Counter = Counter()
    per_op_ge2: Counter = Counter()
    for o, g in zip(ops, ge2.tolist()):
        per_op[o] += 1
        if g:
            per_op_ge2[o] += 1
    print(f"nodes={n} ge2={total_ge2} sum_outdeg={sum_outdeg}")
    print(f"gsim ge2={GSIM_TOTAL_GE2}  ratio={total_ge2 / GSIM_TOTAL_GE2:.3f}x")
    print(f"\n{'op':16s} {'AM nodes':>9s} {'AM ge2':>8s} {'gsim ge2':>9s}")
    for op_name, cnt in per_op_ge2.most_common(20):
        g = GSIM_GE2.get(op_name)
        print(f"{op_name:16s} {per_op[op_name]:>9d} {cnt:>8d} "
              f"{g if g is not None else '-':>9}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
