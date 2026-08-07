#!/usr/bin/env python3
"""One-off motif mining on the split AM compute graph export, to ground
fanout-reduction pass design (compute-partition topic).

Parses build/xs/am-split-export/named.compute.jsonl (escaped JSONL) and
answers:
1. assign@ge2 survivors: what produces the operand (node op vs external_read)?
2. and/or/xor with a replicate operand producer: site count, replicate
   out-degree, guard (replicate operand) producer op/width.
3. not/logic_not consumer histogram; how many feed mux.
4. logic_and@2 exact consumer-pair histogram.
5. eq@2 consumer pairs (guard chain shape).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

PATH = Path(sys.argv[1] if len(sys.argv) > 1 else
            "build/xs/am-split-export/named.compute.jsonl")


def load(path: Path):
    gids: list[int] = []
    ops: list[str] = []
    widths: list[int] = []
    names: list[str] = []
    src: list[int] = []
    dst: list[int] = []
    with open(path) as stream:
        for line in stream:
            line = line.replace('\\"', '"')
            if '"record":"node"' in line:
                rec = json.loads(line)
                gids.append(rec["id"])
                ops.append(rec["opcode"])
                widths.append(rec["width"])
                names.append(rec.get("name", ""))
            elif '"kind":"def_use"' in line:
                rec = json.loads(line)
                src.append(rec["src"])
                dst.append(rec["dst"])
    # node ids are global (pre-split) instruction ids: remap to dense local
    gid = np.array(gids, dtype=np.int64)
    lut = np.full(int(gid.max()) + 1, -1, dtype=np.int64)
    lut[gid] = np.arange(gid.size, dtype=np.int64)
    es = np.array(src, dtype=np.int64)
    ed = np.array(dst, dtype=np.int64)
    keep = (lut[es] >= 0) & (lut[ed] >= 0)
    return (np.array(ops, dtype=object), np.array(widths, dtype=np.int64),
            np.array(names, dtype=object), lut[es[keep]], lut[ed[keep]])


def main() -> int:
    op, width, name, es, ed = load(PATH)
    n = op.size
    print(f"nodes={n} def_use={es.size}")

    # dedup (src,dst)
    key = np.unique((es << 32) | ed)
    us, ud = key >> 32, (key & 0xFFFFFFFF).astype(np.int64)
    outdeg = np.bincount(us, minlength=n)
    indeg = np.bincount(ud, minlength=n)
    # external_read dst uses a different index space; a node with no def_use
    # producer is treated as externally fed.

    # producer index: dst -> src (only well-defined for indeg-1; we keep vector)
    # CSR over consumers
    order = np.argsort(us, kind="stable")
    csc_src, csc_dst = us[order], ud[order]
    off = np.searchsorted(csc_src, np.arange(n + 1))

    def consumers(node: int):
        return csc_dst[off[node]:off[node + 1]]

    # producer(s) of a node: reverse lookup via sorted-by-dst
    rorder = np.argsort(ud, kind="stable")
    rsrc, rdst = us[rorder], ud[rorder]
    roff = np.searchsorted(rdst, np.arange(n + 1))

    def producers(node: int):
        return rsrc[roff[node]:roff[node + 1]]

    is_op = lambda target: np.nonzero(op == target)[0]

    # ---- 1. assign survivors --------------------------------------------
    assign = is_op("assign")
    assign_ge2 = assign[outdeg[assign] >= 2]
    prod_op_hist: Counter = Counter()
    for node in assign_ge2.tolist():
        prods = producers(node)
        if prods.size == 0:
            prod_op_hist["<external_read>"] += 1
        else:
            for p in prods.tolist():
                prod_op_hist[op[p]] += 1
    print(f"\n[assign] total={assign.size} ge2={assign_ge2.size}")
    print(f"  operand producer ops: {dict(prod_op_hist.most_common(10))}")

    # ---- 2. op(x, replicate(c)) sites ------------------------------------
    repl = is_op("replicate")
    repl_set = np.zeros(n, dtype=bool)
    repl_set[repl] = True
    for base in ("and", "or", "xor"):
        nodes = is_op(base)
        sites = 0
        repl_outdeg_hist: Counter = Counter()
        guard_width_hist: Counter = Counter()
        guard_op_hist: Counter = Counter()
        for node in nodes.tolist():
            prods = producers(node)
            r = [p for p in prods.tolist() if repl_set[p]]
            if not r:
                continue
            sites += 1
            for rp in r:
                repl_outdeg_hist[int(outdeg[rp])] += 1
                g = producers(rp)
                for gp in g.tolist():
                    guard_width_hist[int(width[gp])] += 1
                    guard_op_hist[op[gp]] += 1
                if g.size == 0:
                    guard_op_hist["<external_read>"] += 1
        print(f"\n[{base}(x, replicate(c))] sites={sites}")
        print(f"  replicate outdeg hist: {dict(sorted(repl_outdeg_hist.items())[:8])}")
        print(f"  guard width: {dict(sorted(guard_width_hist.items())[:6])}")
        print(f"  guard producer ops: {dict(guard_op_hist.most_common(8))}")

    # ---- 3. not/logic_not --------------------------------------------------
    for target in ("not", "logic_not"):
        nodes = is_op(target)
        ge2 = nodes[outdeg[nodes] >= 2]
        cons_hist: Counter = Counter()
        mux_sel_sites = 0
        for node in nodes.tolist():
            cons = consumers(node)
            for c in cons.tolist():
                cons_hist[op[c]] += 1
            if any(op[c] == "mux" for c in cons.tolist()):
                mux_sel_sites += 1
        print(f"\n[{target}] total={nodes.size} ge2={ge2.size} "
              f"feeding_mux={mux_sel_sites}")
        print(f"  consumer ops: {dict(cons_hist.most_common(10))}")

    # ---- 4. logic_and@2 consumer pairs -------------------------------------
    la = is_op("logic_and")
    la2 = la[outdeg[la] == 2]
    pair_hist: Counter = Counter()
    for node in la2.tolist():
        cons = sorted(op[c] for c in consumers(node).tolist())
        if len(cons) == 2:
            pair_hist[(cons[0], cons[1])] += 1
        else:
            pair_hist[("<dup-edge>",)] += 1
    print(f"\n[logic_and@2] nodes={la2.size} consumer pairs:")
    for pair, cnt in pair_hist.most_common(12):
        print(f"  {pair}: {cnt}")

    # ---- 5. and/logic_and operand-producer op pairs (chain shape) ----------
    for target in ("and", "logic_and"):
        nodes = is_op(target)
        ge2 = nodes[outdeg[nodes] >= 2]
        prod_pair: Counter = Counter()
        for node in ge2.tolist():
            prods = producers(node)
            ops_sorted = sorted(op[p] for p in prods.tolist())
            if prods.size < 2:
                ops_sorted.append("<ext>")
            prod_pair[tuple(ops_sorted[:2])] += 1
        print(f"\n[{target}@ge2] nodes={ge2.size} operand producer pairs:")
        for pair, cnt in prod_pair.most_common(10):
            print(f"  {pair}: {cnt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
