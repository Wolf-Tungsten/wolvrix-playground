#!/usr/bin/env python3
"""Size two follow-up fanout-shaping opportunities on the split exports:

S5 update-mux -> cond-form write (representation change):
  mux nodes with (a) exactly one operand produced by a snapshot assign
  (assign whose single operand is a state external var) and (b) zero
  compute-side consumers are Chisel when-lowering update muxes; moving them
  into the commit write as a cond removes them from the compute graph and
  drops one data edge from their select guard.
  State var ids come from the commit export's side-less external_read vars.

S6 slice_static chain fusion:
  slice_static whose producer is also slice_static can fuse into one slice
  (lsb adds); report site count and ge2 distribution.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

BASE = Path("build/xs/am-split-export")
COMPUTE = BASE / "named.compute.jsonl"
COMMIT = BASE / "named.commit.jsonl"


def load(path: Path):
    gids, ops, widths = [], [], []
    es, ed = [], []
    rd, rv, rside = [], [], []
    with open(path) as f:
        for line in f:
            line = line.replace('\\"', '"')
            if '"record":"node"' in line:
                r = json.loads(line)
                gids.append(r["id"])
                ops.append(r["opcode"])
                widths.append(r["width"])
            elif '"kind":"def_use"' in line:
                r = json.loads(line)
                es.append(r["src"])
                ed.append(r["dst"])
            elif '"kind":"external_read"' in line:
                r = json.loads(line)
                rd.append(r["dst"])
                rv.append(r["var"])
                rside.append(r.get("src_side"))
    gid = np.array(gids, dtype=np.int64)
    lut = np.full(int(gid.max()) + 1, -1, dtype=np.int64)
    lut[gid] = np.arange(gid.size, dtype=np.int64)
    es = np.array(es, dtype=np.int64)
    ed = np.array(ed, dtype=np.int64)
    keep = (lut[es] >= 0) & (lut[ed] >= 0)
    rd = np.array(rd, dtype=np.int64)
    rv = np.array(rv, dtype=np.int64)
    m = (rd < lut.size)
    rd, rv = rd[m], rv[m]
    rside = np.array(rside, dtype=object)[m]
    m = lut[rd] >= 0
    return (np.array(ops, dtype=object), np.array(widths, dtype=np.int64),
            lut[es[keep]], lut[ed[keep]], lut[rd[m]], rv[m], rside[m])


def main() -> int:
    # ---- state var ids from the commit export (side-less external reads) --
    c_op, c_w, c_es, c_ed, c_rd, c_rv, c_side = load(COMMIT)
    state_vars = set(c_rv[c_side != "compute"].tolist())
    print(f"commit nodes={c_op.size} state vars (side-less reads)={len(state_vars)}",
          flush=True)

    op, width, es, ed, rd, rv, rside = load(COMPUTE)
    n = op.size
    key = np.unique((es << 32) | ed)
    us, ud = key >> 32, (key & 0xFFFFFFFF).astype(np.int64)
    outdeg = np.bincount(us, minlength=n)
    # producers / consumers
    rorder = np.argsort(ud, kind="stable")
    rsrc, rdst = us[rorder], ud[rorder]
    roff = np.searchsorted(rdst, np.arange(n + 1))

    def producers(node):
        return rsrc[roff[node]:roff[node + 1]]

    # external (unproduced) operand vars per node
    ext_ops: dict[int, list[int]] = {}
    for d, v in zip(rd.tolist(), rv.tolist()):
        ext_ops.setdefault(d, []).append(v)

    is_assign = op == "assign"
    is_mux = op == "mux"
    is_slice = op == "slice_static"

    # snapshot assign: assign whose only operand is a state external var
    snapshot = np.zeros(n, dtype=bool)
    assign_nodes = np.nonzero(is_assign)[0]
    for node in assign_nodes.tolist():
        if producers(node).size != 0:
            continue
        vars_ = ext_ops.get(node, [])
        if len(vars_) == 1 and vars_[0] in state_vars:
            snapshot[node] = True
    print(f"snapshot assigns={int(snapshot.sum())}", flush=True)

    # ---- S5: update muxes ------------------------------------------------
    mux_nodes = np.nonzero(is_mux)[0]
    update_mux = []
    for node in mux_nodes.tolist():
        prods = producers(node)
        snap_ops = sum(1 for p in prods.tolist() if snapshot[p])
        ext_ops_count = sum(1 for v in ext_ops.get(node, []) if v in state_vars)
        if snap_ops + ext_ops_count != 1:
            continue
        if outdeg[node] != 0:
            continue
        update_mux.append(node)
    um = np.array(update_mux, dtype=np.int64)
    print(f"\n[S5] update muxes (one state-old operand, od0): {um.size}")
    # guard outdeg drop: select producer loses one edge per removed mux.
    # identify select as the 1-bit operand producer (heuristic: width 1 and
    # not the snapshot); count ge2 guards that drop below 2.
    guard_drop = Counter()
    guard_hit = Counter()
    for node in um.tolist():
        prods = producers(node)
        for p in prods.tolist():
            if snapshot[p]:
                continue
            if width[p] == 1:
                guard_hit[int(outdeg[p])] += 1
    drops_below2 = guard_hit.get(2, 0)
    print(f"  guard current-outdeg hist (top): "
          f"{dict(sorted(guard_hit.items())[:8])}")
    print(f"  guards dropping ge2->od1: {drops_below2}")
    # mux ge2 removed: update muxes have od0 -> none. node removal:
    print(f"  compute nodes removed: {um.size} "
          f"({100.0 * um.size / n:.1f}% of {n})")

    # ---- S6: slice chains --------------------------------------------------
    slice_nodes = np.nonzero(is_slice)[0]
    chain = 0
    chain_ge2_parent = 0
    for node in slice_nodes.tolist():
        prods = producers(node)
        if prods.size == 1 and is_slice[prods[0]]:
            chain += 1
            if outdeg[prods[0]] >= 2:
                chain_ge2_parent += 1
    print(f"\n[S6] slice_static(slice_static) chain links: {chain} "
          f"(parent ge2: {chain_ge2_parent})")

    # slice of concat (any operand produced by concat)
    is_concat = op == "concat"
    soc = 0
    for node in slice_nodes.tolist():
        if any(is_concat[p] for p in producers(node).tolist()):
            soc += 1
    print(f"[S6] slice_static(concat) sites: {soc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
