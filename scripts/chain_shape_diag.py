#!/usr/bin/env python3
"""Chain-shape diagnostics for supernode-align NO0015.

Measures the chain-coarsening capability gap between the gsim flattened graph
and the grhsim AM compute graph on export datasets (graph_cache.npz), without
running the C++ partition lab:

- P0 fingerprints: outdeg/indeg distribution and mean degree of the atom DAG,
  pre-coarsen and post-coarsen (single-pass out1/in1/sibling sweeps, exact
  DSU-based replica of partition_lab / production semantics, budget=7000,
  sibling cap=30; mergeWhen NOT modelled -- see NO0015 caveats).
- P1 supply: maximal strict chain histogram (outdeg==1 && indeg==1 links),
  relaxed out1 chains, sibling equivalence-class sizes.
- P1 rejection accounting: out1/in1 candidates rejected by the member budget,
  static vs dynamic (merge-created) degree-1 merges, sibling cap drops.
- State-boundary views: every metric is computed on the full export and on
  the subgraph with state atoms removed (AM: atoms containing state_write
  instructions; gsim: REG_UPDATE op 63 nodes), each with du-only and
  du+order edge sets.

Usage: chain_shape_diag.py DATASET_DIR [--json OUT]
"""

from __future__ import annotations

import argparse
import heapq
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

BUDGET = 7000
SIBCAP = 30
GSIM_REG_UPDATE_OP = 63

HIST_BINS = [1, 2, 3, 5, 9, 17, 33, 65, 129, 257, 1025, 1 << 62]
HIST_LABELS = ["1", "2", "3-4", "5-8", "9-16", "17-32", "33-64", "65-128",
               "129-256", "257-1024", ">1024"]


def hist_of(lengths: np.ndarray) -> dict:
    counts, _ = np.histogram(lengths, bins=HIST_BINS)
    out = {}
    for i, label in enumerate(HIST_LABELS):
        lo = HIST_BINS[i]
        hi = HIST_BINS[i + 1]
        mask = (lengths >= lo) & (lengths < hi)
        out[label] = {"chains": int(counts[i]),
                      "mass": int(lengths[mask].sum())}
    return {"bins": out, "total_mass": int(lengths.sum())}


def load_dataset(ds: Path) -> dict:
    c = np.load(ds / "graph_cache.npz")
    return {k: c[k] for k in c.files}


def state_atoms(d: dict) -> np.ndarray:
    """Boolean per atom: contains a state-write instruction (AM) or is a
    REG_UPDATE node (gsim)."""
    atom = d["atom"].astype(np.int64)
    n_atom = int(atom.max()) + 1
    op = d["op"].astype(np.int64)
    sw = d["state_write"].astype(bool)
    mark_instr = sw | (op == GSIM_REG_UPDATE_OP)
    out = np.zeros(n_atom, dtype=bool)
    np.logical_or.at(out, atom[mark_instr], True)
    return out


def build_edges(d: dict, use_order: bool, drop: np.ndarray):
    """Atom-level deduped edge list excluding dropped atoms and self-loops."""
    atom = d["atom"].astype(np.int64)
    srcs = [d["du_src"].astype(np.int64)]
    dsts = [d["du_dst"].astype(np.int64)]
    if use_order and "ord_src" in d:
        srcs.append(d["ord_src"].astype(np.int64))
        dsts.append(d["ord_dst"].astype(np.int64))
    s = atom[np.concatenate(srcs)]
    t = atom[np.concatenate(dsts)]
    keep = (s != t) & ~drop[s] & ~drop[t]
    s, t = s[keep], t[keep]
    pair = np.unique((s.astype(np.uint64) << 32) | t.astype(np.uint64))
    return (pair >> 32).astype(np.int64), (pair & np.uint64(0xFFFFFFFF)).astype(np.int64)


def csr(n: int, es: np.ndarray, et: np.ndarray):
    idx = np.argsort(es, kind="stable")
    ss, tt = es[idx], et[idx]
    off = np.zeros(n + 1, dtype=np.int64)
    np.add.at(off, ss + 1, 1)
    return ss, tt, np.cumsum(off)


def topo_sort(n: int, off: np.ndarray, tt: np.ndarray, indeg: np.ndarray,
              mode: str, min_key: np.ndarray, alive: np.ndarray) -> np.ndarray:
    indeg = indeg.copy()
    order: list[int] = []
    if mode == "lifo":
        stack = [int(i) for i in np.nonzero(alive & (indeg == 0))[0]]
        arrived = np.zeros(n, dtype=np.int64)
        while stack:
            top = stack.pop()
            order.append(top)
            for o in range(off[top], off[top + 1]):
                v = int(tt[o])
                arrived[v] += 1
                if arrived[v] == indeg[v]:
                    stack.append(v)
    else:  # mininstr heap
        ready = [(int(min_key[i]), int(i))
                 for i in np.nonzero(alive & (indeg == 0))[0]]
        heapq.heapify(ready)
        while ready:
            _, top = heapq.heappop(ready)
            order.append(top)
            for o in range(off[top], off[top + 1]):
                v = int(tt[o])
                indeg[v] -= 1
                if indeg[v] == 0:
                    heapq.heappush(ready, (int(min_key[v]), v))
    return np.asarray(order, dtype=np.int64)


def deg_dist(deg: np.ndarray, alive: np.ndarray) -> dict:
    d = deg[alive]
    return {
        "deg0": int((d == 0).sum()),
        "deg1": int((d == 1).sum()),
        "deg2p": int((d >= 2).sum()),
        "pct1": round(float((d == 1).mean()) * 100, 2),
    }


def chain_histograms(n: int, off: np.ndarray, tt: np.ndarray,
                     poff: np.ndarray, pt: np.ndarray,
                     topo: np.ndarray, alive: np.ndarray) -> dict:
    outdeg = np.diff(off)
    indeg = np.diff(poff)
    strict_len = np.ones(n, dtype=np.int64)
    out1_len = np.ones(n, dtype=np.int64)
    strict_link = np.zeros(n, dtype=bool)
    out1_link = np.zeros(n, dtype=bool)
    for s in topo[::-1]:
        if outdeg[s] != 1:
            continue
        t = int(tt[off[s]])
        out1_link[s] = True
        out1_len[s] = out1_len[t] + 1
        if indeg[t] == 1:
            strict_link[s] = True
            strict_len[s] = strict_len[t] + 1
    strict_head = alive.copy()
    ls = np.nonzero(strict_link)[0]
    if ls.size:
        strict_head[tt[off[ls]]] = False
    # relaxed out1 links form in-arborescences (shared suffixes), so mass over
    # heads double-counts; report the per-node collapse-depth distribution
    # among outdeg==1 nodes instead.
    depth = out1_len[alive & (outdeg == 1)]
    counts, _ = np.histogram(depth, bins=HIST_BINS)
    out1_depth = {label: int(counts[i]) for i, label in enumerate(HIST_LABELS)}
    return {
        "strict": hist_of(strict_len[np.nonzero(strict_head)[0]]),
        "out1_depth_dist": out1_depth,
        "out1_depth_max": int(depth.max()) if depth.size else 0,
        "outdeg1_nodes": int((outdeg[alive] == 1).sum()),
    }


def coarsen_sim(n: int, off: np.ndarray, tt: np.ndarray,
                poff: np.ndarray, ps: np.ndarray,
                topo: np.ndarray, alive: np.ndarray,
                budget: int = BUDGET, sibcap: int = SIBCAP) -> dict:
    """Exact single-pass replica of lab/production coarsen sweeps."""
    parent = np.arange(n, dtype=np.int64)
    member = np.ones(n, dtype=np.int64)
    member[~alive] = 0

    def find(x: int) -> int:
        r = x
        while parent[r] != r:
            r = int(parent[r])
        while parent[x] != r:
            parent[x], x = r, int(parent[x])
        return r

    outdeg_orig = np.diff(off)
    indeg_orig = np.diff(poff)
    out1 = in1 = sib = 0
    out1_budget_rej = in1_budget_rej = 0
    out1_static = out1_dynamic = in1_static = in1_dynamic = 0

    # mergeOut1: reverse topo sweep
    for s in topo[::-1]:
        s = int(s)
        if parent[s] != s:
            continue
        roots = set()
        for o in range(off[s], off[s + 1]):
            r = find(int(tt[o]))
            if r != s:
                roots.add(r)
        if len(roots) != 1:
            continue
        t = roots.pop()
        if member[t] > budget:
            out1_budget_rej += 1
            continue
        if outdeg_orig[s] == 1:
            out1_static += 1
        else:
            out1_dynamic += 1
        parent[s] = t
        member[t] += member[s]
        out1 += 1

    # mergeIn1: forward topo sweep
    for s in topo:
        s = int(s)
        if parent[s] != s:
            continue
        roots = set()
        for o in range(poff[s], poff[s + 1]):
            r = find(int(ps[o]))
            if r != s:
                roots.add(r)
        if len(roots) != 1:
            continue
        p = roots.pop()
        if member[p] > budget:
            in1_budget_rej += 1
            continue
        if indeg_orig[s] == 1:
            in1_static += 1
        else:
            in1_dynamic += 1
        parent[s] = p
        member[p] += member[s]
        in1 += 1

    # mergeSublings: exact effective-predecessor-set equality classes
    classes: dict[tuple, list[int]] = defaultdict(list)
    for s in np.nonzero(alive)[0]:
        s = int(s)
        if parent[s] != s:
            continue
        roots = set()
        for o in range(poff[s], poff[s + 1]):
            r = find(int(ps[o]))
            if r != s:
                roots.add(r)
        if roots:
            classes[tuple(sorted(roots))].append(s)
    sib_classes = 0
    sib_cap_drops = 0
    sib_class_sizes = []
    for key, members in classes.items():
        if len(members) < 2:
            continue
        sib_classes += 1
        sib_class_sizes.append(len(members))
        host = members[0]
        for s in members[1:]:
            if member[host] < sibcap:
                parent[s] = host
                member[host] += member[s]
                sib += 1
            else:
                sib_cap_drops += 1
                host = s

    # cluster DAG
    roots_map = np.empty(n, dtype=np.int64)
    for s in range(n):
        roots_map[s] = find(s)
    es_all = np.repeat(np.arange(n, dtype=np.int64), np.diff(off))
    cs, ct = roots_map[es_all], roots_map[tt]
    keep = cs != ct
    pair = np.unique((cs[keep].astype(np.uint64) << 32) | ct[keep].astype(np.uint64))
    live_mask = (parent == np.arange(n)) & alive
    n_cluster = int(live_mask.sum())
    cm = member[live_mask]
    outdeg_c = np.zeros(n, dtype=np.int64)
    indeg_c = np.zeros(n, dtype=np.int64)
    if pair.size:
        np.add.at(outdeg_c, (pair >> 32).astype(np.int64), 1)
        np.add.at(indeg_c, (pair & np.uint64(0xFFFFFFFF)).astype(np.int64), 1)
    outdeg_c = outdeg_c[live_mask]
    indeg_c = indeg_c[live_mask]
    total_mass = int(cm.sum())
    gt1024 = int(cm[cm > 1024].sum())
    return {
        "merges": {"out1": out1, "in1": in1, "sib": sib},
        "out1_static": out1_static, "out1_dynamic": out1_dynamic,
        "in1_static": in1_static, "in1_dynamic": in1_dynamic,
        "budget_rejects": {"out1": out1_budget_rej, "in1": in1_budget_rej},
        "sibling": {
            "classes_ge2": sib_classes,
            "class_size_mean": round(float(np.mean(sib_class_sizes)), 2) if sib_class_sizes else 0.0,
            "class_size_max": int(max(sib_class_sizes)) if sib_class_sizes else 0,
            "cap_drops": sib_cap_drops,
        },
        "clusters": n_cluster,
        "reduction_pct": round(100.0 * (1 - n_cluster / max(int(alive.sum()), 1)), 2),
        "cluster_member": {
            "mean": round(float(cm.mean()), 3),
            "max": int(cm.max()),
            "p50": int(np.percentile(cm, 50)),
            "p99": int(np.percentile(cm, 99)),
            "mass_gt1024": gt1024,
            "mass_gt1024_pct": round(100.0 * gt1024 / max(total_mass, 1), 2),
        },
        "cluster_dag": {
            "edges": int(pair.size),
            "mean_deg": round(float(pair.size) / max(n_cluster, 1), 3),
            "outdeg1_pct": round(float((outdeg_c == 1).mean()) * 100, 2),
            "indeg1_pct": round(float((indeg_c == 1).mean()) * 100, 2),
        },
    }


def run_views(name: str, d: dict) -> dict:
    atom = d["atom"].astype(np.int64)
    n_atom = int(atom.max()) + 1
    satom = state_atoms(d)
    min_instr = np.full(n_atom, int(d["instructions"][0]), dtype=np.int64)
    np.minimum.at(min_instr, atom, np.arange(atom.size, dtype=np.int64))
    order_mode = "mininstr" if "am" in name else "lifo"

    views = {}
    for view_name, drop in [("full", np.zeros(n_atom, dtype=bool)),
                            ("compute_only", satom)]:
        alive = ~drop
        for edge_name, use_order in [("du", False), ("du+order", True)]:
            es, et = build_edges(d, use_order, drop)
            ss, tt, off = csr(n_atom, es, et)
            ps, pt, poff = csr(n_atom, et, es)
            outdeg = np.diff(off)
            indeg = np.diff(poff)
            fp = {
                "nodes_alive": int(alive.sum()),
                "edges": int(es.size),
                "mean_deg": round(float(es.size) / max(int(alive.sum()), 1), 3),
                "out": deg_dist(outdeg, alive),
                "in": deg_dist(indeg, alive),
            }
            topo = topo_sort(n_atom, off, tt, indeg, order_mode, min_instr, alive)
            ch = chain_histograms(n_atom, off, tt, poff, pt, topo, alive)
            sim = coarsen_sim(n_atom, off, tt, poff, pt, topo, alive)
            views[f"{view_name}/{edge_name}"] = {
                "fingerprint": fp, "chains": ch, "coarsen": sim}
    return views


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    ds = Path(args.dataset)
    d = load_dataset(ds)
    result = {ds.name: run_views(ds.name, d)}
    text = json.dumps(result, indent=1, ensure_ascii=False)
    if args.json:
        Path(args.json).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
