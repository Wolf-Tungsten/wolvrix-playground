"""Offline replica of gsim's production partitioner (mergeNodes.cpp + graphPartition.cpp).

Faithfully mirrors reference/gsim (supernode-align sandbox, NO0013):

- Two adjacency levels, matching topoProjExport.cpp's mapping:
    next/prev     := def_use edges (data dependence, (src,dst)-unique by export)
    depNext/depPrev := def_use ∪ order edges (order edges = node-level depPrev
                       from connectDep + memory reader->writer order; on the
                       flat dataset def_use ⊆ order holds empirically)
- mergeOut1 (mergeNodes.cpp:272): ONE reverse sweep over sortedSuper; a super
  with next.size()==1 merges into its unique successor when
  next.member.size() <= 7000 (pre-merge) and every depNext has order >=
  next.order (cycle safety). Live rewiring inside the sweep, so Out1 chains
  collapse in a single pass. removeEmptySuper at pass end.
- mergeIn1 (mergeNodes.cpp:324): ONE forward sweep, mirror image
  (prev.size()==1, prev.member.size() <= 7000, all depPrev orders <=
  prev.order, merge into the predecessor).
- mergeSublings (mergeNodes.cpp:382): exact (prev, depPrev) set-equality
  classes (prevHash + prevEq in gsim == exact classes); members merge into the
  first host with member.size() < 30, a full host is replaced by the current
  super. Members only move; adjacency is rebuilt afterwards (reconnectSuper
  equivalent: DSU over clusters + vectorized edge remap).
- resort (graphPartition.cpp:13): stack-based Kahn over the dep adjacency;
  sources pushed in current sortedSuper order, LIFO pop, a successor is pushed
  once all depPrev arrived; with ORDERED_TOPO_SORT (defined in production
  common.h:25) neighbors are visited in ascending id order. Caveat: gsim sorts
  by SuperNode::id (creation counter), which the export does not preserve; we
  sort by cluster id (= initial export node id). Tie-breaks may differ.
- graphInitPartition (graphPartition.cpp:63): DP over the resort'ed sequence.
  T[0]=0; for each i, jump targets j in (i, nextBound] where the cumulative
  member size stays <= SuperNodeMaxSize (a single oversized cluster becomes a
  singleton block); Cij accumulates sortedSuper[j-1].next.size() minus the
  in-edges whose prev.order >= i (data adjacency only); strict-< relaxation
  (ties keep the earlier cut); backtrack from T[N].

Not replicated (information absent from the flat export, documented in NO0013):
- mergeResetAll: reset supernodes (SUPER_UINT_RESET/SUPER_ASYNC_RESET) and the
  SUPER_ASYNC_RESET marking of reset-condition supernodes; those would be
  excluded from merging and force-cut in the DP. Our replica has only
  SUPER_VALID nodes.
- mergeWhenNodes: OP_WHEN condition grouping (condition identity not exported).
- reg_src data adjacency: the export emits register reads as external_read and
  skips reg_src's own expression refs, so reg_src nodes keep only their dep
  (order) out-edges here, while production gsim gave them full data adjacency.

Everything is explicit per-cluster Python sets for the live sweeps (conditions
must see intra-pass rewiring) and numpy for (re)builds. One full run on the
3M-node flat graph takes ~2-4 minutes.
"""

from __future__ import annotations

import time
from bisect import bisect_left
from dataclasses import dataclass, field

import numpy as np

MAX_NODES_PER_SUPER = 7000  # mergeNodes.cpp:8
MAX_SUBLINGS = 30  # mergeNodes.cpp:9


@dataclass
class GsimPartResult:
    block_of_node: np.ndarray  # (N,) int64, dense block ids in resort order
    blocks: int
    clusters_after_out1: int
    clusters_after_in1: int
    clusters_after_sublings: int
    merges: dict[str, int]
    oversized_blocks: int  # DP blocks whose single cluster exceeds max_size
    oversized_block_instructions: int
    block_sizes: np.ndarray = field(repr=False)
    seconds: float = 0.0


def _build_adjacency(
    du_src: np.ndarray,
    du_dst: np.ndarray,
    ord_src: np.ndarray,
    ord_dst: np.ndarray,
    n: int,
) -> tuple[list, list, list, list]:
    """Per-node sets: nexts/prevs from def_use, dnext/dprev = def_use ∪ order."""
    nexts: list[set] = [set() for _ in range(n)]
    prevs: list[set] = [set() for _ in range(n)]
    dnext: list[set] = [set() for _ in range(n)]
    dprev: list[set] = [set() for _ in range(n)]
    du_s = du_src.tolist()
    du_d = du_dst.tolist()
    for s, d in zip(du_s, du_d):
        nexts[s].add(d)
        prevs[d].add(s)
        dnext[s].add(d)
        dprev[d].add(s)
    od_s = ord_src.tolist()
    od_d = ord_dst.tolist()
    for s, d in zip(od_s, od_d):
        dnext[s].add(d)
        dprev[d].add(s)
    return nexts, prevs, dnext, dprev


def _find_roots(parent: np.ndarray) -> np.ndarray:
    """Vectorized DSU find for all nodes at once (pointer jumping)."""
    roots = np.arange(parent.size, dtype=np.int64)
    while True:
        p = parent[roots]
        done = p == roots
        if done.all():
            return roots
        roots = np.where(done, roots, parent[p])


def _reconnect(
    parent: np.ndarray,
    du_src: np.ndarray,
    du_dst: np.ndarray,
    ord_src: np.ndarray,
    ord_dst: np.ndarray,
    member: list,
) -> tuple[list, list, list, list, np.ndarray]:
    """reconnectSuper equivalent: rebuild cluster adjacency from node edges.

    Returns (nexts, prevs, dnext, dprev, roots) with sets only on live roots.
    """
    n = parent.size
    roots = _find_roots(parent)
    live = np.array([member[i] > 0 for i in range(n)], dtype=bool)
    live_root = live[roots]
    nexts: list[set] = [set() for _ in range(n)]
    prevs: list[set] = [set() for _ in range(n)]
    dnext: list[set] = [set() for _ in range(n)]
    dprev: list[set] = [set() for _ in range(n)]
    rs = roots[du_src.astype(np.int64)]
    rd = roots[du_dst.astype(np.int64)]
    keep = (rs != rd) & live_root[du_src.astype(np.int64)] & live_root[du_dst.astype(np.int64)]
    key = np.unique((rs[keep] << 32) | rd[keep])
    src_l = (key >> 32).tolist()
    dst_l = (key & 0xFFFFFFFF).tolist()
    for s, d in zip(src_l, dst_l):
        nexts[s].add(d)
        prevs[d].add(s)
        dnext[s].add(d)
        dprev[d].add(s)
    rs = roots[ord_src.astype(np.int64)]
    rd = roots[ord_dst.astype(np.int64)]
    keep = (rs != rd) & live_root[ord_src.astype(np.int64)] & live_root[ord_dst.astype(np.int64)]
    key = np.unique((rs[keep] << 32) | rd[keep])
    src_l = (key >> 32).tolist()
    dst_l = (key & 0xFFFFFFFF).tolist()
    for s, d in zip(src_l, dst_l):
        dnext[s].add(d)
        dprev[d].add(s)
    return nexts, prevs, dnext, dprev, roots


def partition(
    du_src: np.ndarray,
    du_dst: np.ndarray,
    ord_src: np.ndarray,
    ord_dst: np.ndarray,
    n_nodes: int,
    max_size: int,
    verbose: bool = False,
) -> GsimPartResult:
    """Run the full gsim pipeline replica: Out1 -> In1 -> Sublings -> resort -> DP."""
    started = time.time()
    merges = {"Out1": 0, "In1": 0, "Sibling": 0}
    member = [1] * n_nodes
    alive = [True] * n_nodes
    order = list(range(n_nodes))  # export id order is topological (verified)
    parent = np.arange(n_nodes, dtype=np.int64)

    nexts, prevs, dnext, dprev = _build_adjacency(du_src, du_dst, ord_src, ord_dst, n_nodes)
    if verbose:
        print(f"[gsimpart] adjacency built {time.time() - started:.1f}s", flush=True)

    # ---- mergeOut1: single reverse sweep, merge into unique successor ------
    t0 = time.time()
    for s in range(n_nodes - 1, -1, -1):
        ns = nexts[s]
        if len(ns) != 1:
            continue
        t = next(iter(ns))
        if member[t] > MAX_NODES_PER_SUPER:
            continue
        ot = order[t]
        ok = True
        for d in dnext[s]:
            if order[d] < ot:
                ok = False
                break
        if not ok:
            continue
        # merge s into t (mergeNodes.cpp:286-315)
        prevs[t].discard(s)
        dprev[t].discard(s)
        sp = prevs[s]
        for p in sp:
            prevs[t].add(p)
            dprev[t].add(p)
        for p in dprev[s]:
            np_ = nexts[p]
            dp_ = dnext[p]
            dp_.discard(s)
            dp_.add(t)
            if p in sp:
                np_.discard(s)
                np_.add(t)
            else:  # dep-only prev: nextSuper->addDepPrev(prev)
                dprev[t].add(p)
        for d in dnext[s]:
            if d != t:
                dprev[d].discard(s)
                dprev[d].add(t)
                dnext[t].add(d)
        member[t] += member[s]
        member[s] = 0
        alive[s] = False
        parent[s] = t
        ns.clear()
        sp.clear()
        dnext[s].clear()
        dprev[s].clear()
        merges["Out1"] += 1
    clusters_out1 = sum(1 for m in member if m > 0)
    if verbose:
        print(f"[gsimpart] mergeOut1 merges={merges['Out1']} clusters={clusters_out1} "
              f"{time.time() - t0:.1f}s", flush=True)

    # ---- mergeIn1: single forward sweep, merge into unique predecessor -----
    t0 = time.time()
    for s in range(n_nodes):
        if not alive[s]:
            continue
        sp = prevs[s]
        if len(sp) != 1:
            continue
        p = next(iter(sp))
        if member[p] > MAX_NODES_PER_SUPER:
            continue
        op = order[p]
        ok = True
        for q in dprev[s]:
            if order[q] > op:
                ok = False
                break
        if not ok:
            continue
        # merge s into p (mergeNodes.cpp:337-362; relation clears are
        # idempotent there, explicit here)
        nexts[p].discard(s)
        dnext[p].discard(s)
        sn = nexts[s]
        for d in sn:
            nexts[p].add(d)
            dnext[p].add(d)
        for d in dnext[s]:
            pd = prevs[d]
            dd = dprev[d]
            dd.discard(s)
            dd.add(p)
            dnext[p].add(d)
            if d in sn:
                pd.discard(s)
                pd.add(p)
                nexts[p].add(d)
        for q in dprev[s]:
            if q != p:
                dnext[q].discard(s)
                dnext[q].add(p)
                dprev[p].add(q)
        member[p] += member[s]
        member[s] = 0
        alive[s] = False
        parent[s] = p
        sn.clear()
        sp.clear()
        dnext[s].clear()
        dprev[s].clear()
        merges["In1"] += 1
    clusters_in1 = sum(1 for m in member if m > 0)
    if verbose:
        print(f"[gsimpart] mergeIn1 merges={merges['In1']} clusters={clusters_in1} "
              f"{time.time() - t0:.1f}s", flush=True)

    # ---- mergeSublings: exact (prev, depPrev) classes, host cap 30 ---------
    t0 = time.time()
    groups: dict = {}
    for s in range(n_nodes):
        if not alive[s] or not prevs[s]:
            continue
        key = (tuple(sorted(prevs[s])), tuple(sorted(dprev[s])))
        groups.setdefault(key, []).append(s)
    for members in groups.values():
        if len(members) < 2:
            continue
        host = -1
        for s in members:
            if host < 0:
                host = s
                continue
            if member[host] < MAX_SUBLINGS:
                member[host] += member[s]
                member[s] = 0
                alive[s] = False
                parent[s] = host
                merges["Sibling"] += 1
            else:
                host = s
    clusters_sib = sum(1 for m in member if m > 0)
    if verbose:
        print(f"[gsimpart] mergeSublings merges={merges['Sibling']} clusters={clusters_sib} "
              f"groups={len(groups)} {time.time() - t0:.1f}s", flush=True)

    # ---- reconnect + resort (stack Kahn over dep adjacency) -----------------
    t0 = time.time()
    nexts, prevs, dnext, dprev, roots = _reconnect(
        parent, du_src, du_dst, ord_src, ord_dst, member
    )
    times = [0] * n_nodes
    stack = [s for s in range(n_nodes) if member[s] > 0 and not dprev[s]]
    seq: list[int] = []
    append = seq.append
    while stack:
        top = stack.pop()
        append(top)
        for d in sorted(dnext[top]):
            times[d] += 1
            if times[d] == len(dprev[d]):
                stack.append(d)
    if len(seq) != clusters_sib:
        raise RuntimeError(f"resort visited {len(seq)} of {clusters_sib} clusters (cyclic?)")
    if verbose:
        print(f"[gsimpart] reconnect+resort {time.time() - t0:.1f}s", flush=True)

    # ---- graphInitPartition DP ---------------------------------------------
    t0 = time.time()
    count = len(seq)
    sz = [member[c] for c in seq]
    outn = [len(nexts[c]) for c in seq]
    pos = [0] * n_nodes
    for i, c in enumerate(seq):
        pos[c] = i
    prevlists = [sorted(pos[p] for p in prevs[c]) for c in seq]
    INF = 1 << 60
    T = [INF] * (count + 1)
    back = [-1] * (count + 1)
    T[0] = 0
    for i in range(count):
        ti = T[i]
        if ti == INF:
            continue
        nb = i + 1
        acc = sz[i]
        while nb < count and acc + sz[nb] <= max_size:
            acc += sz[nb]
            nb += 1
        cij = 0
        for j in range(i + 1, nb + 1):
            cij += outn[j - 1]
            pl = prevlists[j - 1]
            cij -= len(pl) - bisect_left(pl, i)
            newt = ti + cij
            if T[j] > newt:
                T[j] = newt
                back[j] = i
    cuts = [count]
    idx = count
    while back[idx] > 0:
        cuts.append(back[idx])
        idx = back[idx]
    cuts.reverse()  # backtrack yields descending cuts; segments need ascending
    block_of_cluster = [0] * n_nodes
    sizes = []
    beg = 0
    blk = 0
    for end in cuts:
        total = 0
        for p_ in range(beg, end):
            block_of_cluster[seq[p_]] = blk
            total += sz[p_]
        sizes.append(total)
        blk += 1
        beg = end
    sizes_arr = np.array(sizes, dtype=np.int64)
    if int(sizes_arr.sum()) != n_nodes:
        raise RuntimeError(
            f"segment sizes sum {int(sizes_arr.sum())} != node count {n_nodes} "
            "(cut points do not partition the sequence)"
        )
    oversized = sizes_arr > max_size
    block_of_node = np.array(block_of_cluster, dtype=np.int64)[roots]
    result = GsimPartResult(
        block_of_node=block_of_node,
        blocks=blk,
        clusters_after_out1=clusters_out1,
        clusters_after_in1=clusters_in1,
        clusters_after_sublings=clusters_sib,
        merges=merges,
        oversized_blocks=int(oversized.sum()),
        oversized_block_instructions=int(sizes_arr[oversized].sum()),
        block_sizes=sizes_arr,
        seconds=round(time.time() - started, 1),
    )
    if verbose:
        print(f"[gsimpart] DP blocks={blk} oversized={result.oversized_blocks} "
              f"{time.time() - t0:.1f}s total={result.seconds}s", flush=True)
    return result
