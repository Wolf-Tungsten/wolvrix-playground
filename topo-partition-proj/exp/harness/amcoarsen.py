"""Offline replica of the AM coarsen + segment packing (supernode-align sandbox).

Faithfully mirrors wolvrix/lib/grhsim/am/activity_schedule.cpp:

- DSU with (weight, minInstruction, oversized, minLevel, maxLevel); unite roots
  at the smaller id.
- Cluster graph rebuilt from the DSU each round; cluster ids dense in atom
  order; edges are atom-level def_use + order pairs with commit atoms removed.
- Three merge passes (Out1 / In1 / Sibling) with per-round mergeMark (each
  cluster joins at most one merge per round) and coarsenBudget / oversized
  rejection in tryMerge.
- Scheduler modes:
  - "rotate": Out1 -> In1 -> Sibling -> ... until three consecutive idle
    passes (production behaviour);
  - "sequential": each pass runs to its own fixpoint in gsim order
    (Out1, then In1, then Sibling), optionally repeating the whole cycle
    (mode="sequential:N" with N cycles, N=0 meaning until stable).
- After coarsening: deterministic Kahn over the cluster DAG (ties on
  minInstruction, then dense id) and a greedy capacity packing of the cluster
  order into blocks of <= max_instructions (oversized cluster = singleton
  block). This approximates the production segment DP; validation numbers in
  pdocs/grh-notepad/supernode-align/NO0003 show the approximation error is
  small for the metrics we compare.

Everything is numpy-vectorized except the per-round candidate loop (mergeMark
semantics are order-dependent by construction).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class CoarsenResult:
    parent: np.ndarray  # DSU parent per atom
    rounds: int
    merges: dict[str, int]


def _build_cluster_graph(
    parent: np.ndarray, esrc: np.ndarray, edst: np.ndarray, active: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (root_of, cluster_of_atom, out_src, out_dst) with dense cluster ids."""
    n = parent.size

    def find(x: np.ndarray) -> np.ndarray:
        r = x.copy()
        while True:
            p = parent[r]
            done = p == r
            if done.all():
                return r
            r = np.where(done, r, parent[p])

    roots = np.empty(n, dtype=np.int64)
    roots[active] = find(np.nonzero(active)[0])
    uniq, inverse = np.unique(roots[active], return_inverse=True)
    cluster_of_atom = np.full(n, -1, dtype=np.int64)
    cluster_of_atom[active] = inverse
    cr = cluster_of_atom[esrc]
    ct = cluster_of_atom[edst]
    valid = (cr >= 0) & (ct >= 0) & (cr != ct)
    pairs = np.unique((cr[valid] << 32) | ct[valid])
    return uniq, cluster_of_atom, (pairs >> 32).astype(np.int64), (pairs & 0xFFFFFFFF).astype(np.int64)


def coarsen(
    esrc: np.ndarray,
    edst: np.ndarray,
    n_atoms: int,
    active: np.ndarray,
    budget: int,
    oversized_weight: np.ndarray | None = None,
    mode: str = "rotate",
    max_iters: int = 256,
    weights: np.ndarray | None = None,
    pass_order: tuple[str, ...] | None = None,
    mux_select: np.ndarray | None = None,
) -> CoarsenResult:
    """Run the merge passes. ``esrc/edst`` are atom-level edges (def_use + order).

    ``active`` marks atoms that participate (non-commit). ``weights`` defaults
    to 1 per atom. ``oversized_weight`` marks atoms that can never merge
    (production: atom weight > max_instructions_per_block). ``pass_order``
    selects and orders the passes (default Out1, In1, Sibling).
    """
    parent = np.arange(n_atoms, dtype=np.int64)
    weight = weights.astype(np.int64) if weights is not None else np.ones(n_atoms, dtype=np.int64)
    weight = weight.copy()
    oversized = np.zeros(n_atoms, dtype=bool)
    if oversized_weight is not None:
        oversized = oversized_weight.astype(bool).copy()

    merge_mark = np.zeros(n_atoms, dtype=np.int64)
    stamp = 0
    merges = {"Out1": 0, "In1": 0, "Sibling": 0, "PrevSibling": 0, "MuxCond": 0,
              "GOut1": 0, "GIn1": 0}

    def unite(a: int, b: int) -> None:
        ra, rb = a, b
        while parent[ra] != ra:
            ra = parent[ra]
        while parent[rb] != rb:
            rb = parent[rb]
        if rb < ra:
            ra, rb = rb, ra
        parent[rb] = ra
        weight[ra] += weight[rb]
        oversized[ra] |= oversized[rb]

    def try_merge(a: int, b: int) -> bool:
        ra, rb = a, b
        while parent[ra] != ra:
            ra = parent[ra]
        while parent[rb] != rb:
            rb = parent[rb]
        if ra == rb or merge_mark[ra] == stamp or merge_mark[rb] == stamp:
            return False
        if oversized[ra] or oversized[rb]:
            return False
        if weight[ra] + weight[rb] > budget:
            return False
        unite(ra, rb)
        root = ra if ra < rb else rb
        merge_mark[root] = stamp
        return True

    def find_root(a: int) -> int:
        while parent[a] != a:
            a = parent[a]
        return a

    def out1_pass() -> bool:
        root_of, cluster_of, osrc, odst = _build_cluster_graph(parent, esrc, edst, active)
        outdeg = np.bincount(osrc, minlength=root_of.size)
        changed = False
        sel = outdeg[osrc] == 1
        for c, t in zip(osrc[sel].tolist(), odst[sel].tolist()):
            if try_merge(int(root_of[c]), int(root_of[t])):
                changed = True
                merges["Out1"] += 1
        return changed

    def in1_pass() -> bool:
        root_of, cluster_of, osrc, odst = _build_cluster_graph(parent, esrc, edst, active)
        indeg = np.bincount(odst, minlength=root_of.size)
        changed = False
        sel = indeg[odst] == 1
        # production iterates target clusters in dense id order
        cand = np.nonzero(sel)[0]
        cand = cand[np.argsort(odst[cand], kind="stable")]
        for idx in cand.tolist():
            if try_merge(int(root_of[osrc[idx]]), int(root_of[odst[idx]])):
                changed = True
                merges["In1"] += 1
        return changed

    def sibling_pass() -> bool:
        root_of, cluster_of, osrc, odst = _build_cluster_graph(parent, esrc, edst, active)
        count = root_of.size
        # longest-path levels via Kahn
        indeg = np.bincount(odst, minlength=count).astype(np.int64)
        level = np.zeros(count, dtype=np.int64)
        queue = [int(c) for c in np.nonzero(indeg == 0)[0]]
        head = 0
        out_csr_off = np.zeros(count + 1, dtype=np.int64)
        np.add.at(out_csr_off, osrc + 1, 1)
        np.cumsum(out_csr_off, out=out_csr_off)
        out_csr_tgt = np.empty(osrc.size, dtype=np.int64)
        order = np.argsort(osrc, kind="stable")
        out_csr_tgt[:] = odst[order]
        while head < len(queue):
            s = queue[head]
            head += 1
            for off in range(out_csr_off[s], out_csr_off[s + 1]):
                t = int(out_csr_tgt[off])
                if level[s] + 1 > level[t]:
                    level[t] = level[s] + 1
                indeg[t] -= 1
                if indeg[t] == 0:
                    queue.append(t)
        if len(queue) != count:
            return False
        min_level = np.zeros(n_atoms, dtype=np.int64)
        max_level = np.zeros(n_atoms, dtype=np.int64)
        min_level[root_of] = level
        max_level[root_of] = level
        changed = False
        # per predecessor: chain-merge same-level successors
        pred_order = np.argsort(osrc, kind="stable")
        sorted_src = osrc[pred_order]
        sorted_dst = odst[pred_order]
        bounds = np.searchsorted(sorted_src, np.arange(count + 1))
        for c in range(count):
            pred_root = find_root(int(root_of[c]))
            buffer: list[tuple[int, int]] = []
            seen: set[int] = set()
            for off in range(bounds[c], bounds[c + 1]):
                r = find_root(int(root_of[sorted_dst[off]]))
                if r == pred_root or r in seen:
                    continue
                if min_level[r] != max_level[r]:
                    continue
                seen.add(r)
                buffer.append((int(min_level[r]), r))
            if len(buffer) < 2:
                continue
            buffer.sort()
            representative = -1
            previous_root = -1
            previous_level = -1
            for sib_level, root in buffer:
                if root == previous_root:
                    continue
                previous_root = root
                if sib_level != previous_level:
                    previous_level = sib_level
                    representative = -1
                if representative == -1:
                    representative = root
                    continue
                if try_merge(representative, root):
                    representative = find_root(representative)
                    changed = True
                    merges["Sibling"] += 1
                else:
                    representative = root
        return changed

    def prev_sibling_pass() -> bool:
        """gsim mergeSublings equivalent: merge clusters sharing an identical
        direct-predecessor set (safe in a DAG: identical predecessor sets
        cannot lie on a path between each other)."""
        root_of, cluster_of, osrc, odst = _build_cluster_graph(parent, esrc, edst, active)
        count = root_of.size
        if count == 0:
            return False
        # predecessor sets keyed by sorted unique predecessor clusters
        order = np.lexsort((osrc, odst))
        s_dst = odst[order]
        s_src = osrc[order]
        bounds = np.searchsorted(s_dst, np.arange(count + 1))
        changed = False
        groups: dict[tuple[int, ...], list[int]] = {}
        for c in range(count):
            preds = np.unique(s_src[bounds[c] : bounds[c + 1]])
            if preds.size == 0:
                continue
            groups.setdefault(tuple(preds.tolist()), []).append(c)
        for pred_set, members in groups.items():
            if len(members) < 2:
                continue
            representative = -1
            for c in members:
                if representative == -1:
                    representative = int(root_of[c])
                    continue
                if try_merge(representative, int(root_of[c])):
                    representative = find_root(representative)
                    changed = True
                    merges["PrevSibling"] += 1
                else:
                    representative = int(root_of[c])
        return changed

    def mux_cond_pass() -> bool:
        """mergeWhenNodes analogue: merge same-level mux clusters that share a
        select-condition producer (gsim merges when-bodies by condition)."""
        if mux_select is None:
            return False
        root_of, cluster_of, osrc, odst = _build_cluster_graph(parent, esrc, edst, active)
        count = root_of.size
        indeg = np.bincount(odst, minlength=count).astype(np.int64)
        level = np.zeros(count, dtype=np.int64)
        queue = [int(c) for c in np.nonzero(indeg == 0)[0]]
        head = 0
        out_csr_off = np.zeros(count + 1, dtype=np.int64)
        np.add.at(out_csr_off, osrc + 1, 1)
        np.cumsum(out_csr_off, out=out_csr_off)
        out_csr_tgt = np.empty(osrc.size, dtype=np.int64)
        out_csr_tgt[:] = odst[np.argsort(osrc, kind="stable")]
        while head < len(queue):
            s = queue[head]
            head += 1
            for off in range(out_csr_off[s], out_csr_off[s + 1]):
                t = int(out_csr_tgt[off])
                if level[s] + 1 > level[t]:
                    level[t] = level[s] + 1
                indeg[t] -= 1
                if indeg[t] == 0:
                    queue.append(t)
        if len(queue) != count:
            return False
        min_level = np.zeros(n_atoms, dtype=np.int64)
        max_level = np.zeros(n_atoms, dtype=np.int64)
        min_level[root_of] = level
        max_level[root_of] = level
        changed = False
        groups: dict[tuple[int, int], list[int]] = {}
        mux_atoms = np.nonzero((mux_select >= 0) & active)[0]
        for a in mux_atoms.tolist():
            c = int(cluster_of[a])
            if c < 0:
                continue
            r = find_root(int(root_of[c]))
            if min_level[r] != max_level[r]:
                continue
            sr = find_root(int(mux_select[a]))
            if sr == r:
                continue
            groups.setdefault((sr, int(min_level[r])), []).append(r)
        for (sr, _lev), roots in groups.items():
            if len(roots) < 2:
                continue
            representative = -1
            for r in sorted(set(roots)):
                if representative == -1:
                    representative = r
                    continue
                if try_merge(representative, r):
                    representative = find_root(representative)
                    changed = True
                    merges["MuxCond"] += 1
                else:
                    representative = r
        return changed

    def _levels(count: int, osrc: np.ndarray, odst: np.ndarray) -> np.ndarray | None:
        indeg = np.bincount(odst, minlength=count).astype(np.int64)
        level = np.zeros(count, dtype=np.int64)
        queue = [int(c) for c in np.nonzero(indeg == 0)[0]]
        head = 0
        out_csr_off = np.zeros(count + 1, dtype=np.int64)
        np.add.at(out_csr_off, osrc + 1, 1)
        np.cumsum(out_csr_off, out=out_csr_off)
        out_csr_tgt = np.empty(osrc.size, dtype=np.int64)
        out_csr_tgt[:] = odst[np.argsort(osrc, kind="stable")]
        while head < len(queue):
            s = queue[head]
            head += 1
            for off in range(out_csr_off[s], out_csr_off[s + 1]):
                t = int(out_csr_tgt[off])
                if level[s] + 1 > level[t]:
                    level[t] = level[s] + 1
                indeg[t] -= 1
                if indeg[t] == 0:
                    queue.append(t)
        if len(queue) != count:
            return None
        return level

    def gout1_pass() -> bool:
        """gsim mergeOut1 replica: single-sweep over out-degree-1 clusters in
        DESCENDING longest-path level order, no per-round merge mark (a cluster
        may absorb repeatedly), one-sided capacity (absorbing successor's
        weight must stay <= budget). Cycle-safe: paths strictly increase in
        level, so nothing at level > L can reach the level-L source."""
        root_of, cluster_of, osrc, odst = _build_cluster_graph(parent, esrc, edst, active)
        count = root_of.size
        if count == 0:
            return False
        level = _levels(count, osrc, odst)
        if level is None:
            return False
        outdeg = np.bincount(osrc, minlength=count)
        sel = outdeg[osrc] == 1
        cand_src = osrc[sel]
        cand_dst = odst[sel]
        order = np.argsort(-level[cand_src], kind="stable")
        changed = False
        for idx in order.tolist():
            c = int(cand_src[idx])
            r = find_root(int(root_of[c]))
            if oversized[r]:
                continue
            t_root = find_root(int(root_of[int(cand_dst[idx])]))
            if r == t_root or oversized[t_root]:
                continue
            # gsim: only the absorbing supernode's size is capped
            if weight[t_root] > budget:
                continue
            unite(r, t_root)
            changed = True
            merges["GOut1"] += 1
        return changed

    def gin1_pass() -> bool:
        """gsim mergeIn1 replica: single-sweep over in-degree-1 clusters in
        ASCENDING level order, merging into the unique predecessor with a
        one-sided capacity check on the predecessor."""
        root_of, cluster_of, osrc, odst = _build_cluster_graph(parent, esrc, edst, active)
        count = root_of.size
        if count == 0:
            return False
        level = _levels(count, osrc, odst)
        if level is None:
            return False
        indeg = np.bincount(odst, minlength=count)
        sel = indeg[odst] == 1
        cand_src = osrc[sel]
        cand_dst = odst[sel]
        order = np.argsort(level[cand_dst], kind="stable")
        changed = False
        for idx in order.tolist():
            c = int(cand_dst[idx])
            r = find_root(int(root_of[c]))
            if oversized[r]:
                continue
            p_root = find_root(int(root_of[int(cand_src[idx])]))
            if r == p_root or oversized[p_root]:
                continue
            if weight[p_root] > budget:
                continue
            unite(r, p_root)
            changed = True
            merges["GIn1"] += 1
        return changed

    passes = {"Out1": out1_pass, "In1": in1_pass, "Sibling": sibling_pass,
              "PrevSibling": prev_sibling_pass, "MuxCond": mux_cond_pass,
              "GOut1": gout1_pass, "GIn1": gin1_pass}
    order = tuple(pass_order) if pass_order else ("Out1", "In1", "Sibling")
    for name in order:
        if name not in passes:
            raise ValueError(f"unknown pass: {name}")
    rounds = 0
    if mode == "rotate":
        idle_mask = 0
        pass_idx = 0
        while rounds < max_iters and idle_mask != (1 << len(order)) - 1:
            stamp += 1
            changed = passes[order[pass_idx]]()
            if changed:
                idle_mask = 0
            else:
                idle_mask |= 1 << pass_idx
            pass_idx = (pass_idx + 1) % len(order)
            rounds += 1
    elif mode.startswith("sequential"):
        cycles = int(mode.split(":")[1]) if ":" in mode else 1
        it = 0
        while it < max_iters:
            any_cycle_changed = False
            for name in order:
                while rounds < max_iters:
                    stamp += 1
                    changed = passes[name]()
                    rounds += 1
                    if not changed:
                        break
                    any_cycle_changed = True
            it += 1
            if cycles > 0 and it >= cycles:
                break
            if not any_cycle_changed:
                break
    else:
        raise ValueError(f"unknown mode: {mode}")
    return CoarsenResult(parent=parent, rounds=rounds, merges=merges)


def cluster_blocks(
    parent: np.ndarray,
    esrc: np.ndarray,
    edst: np.ndarray,
    active: np.ndarray,
    weights: np.ndarray,
    max_instructions: int,
) -> np.ndarray:
    """Greedy capacity packing of the deterministic Kahn cluster order.

    Returns block id per atom (-1 for inactive/commit atoms), blocks dense in
    scan order. Approximates the production segment DP.
    """
    n = parent.size
    root_of, cluster_of, osrc, odst = _build_cluster_graph(parent, esrc, edst, active)
    count = root_of.size
    # cluster weights and min instruction
    cweight = np.zeros(count, dtype=np.int64)
    min_instr = np.full(count, np.iinfo(np.int64).max, dtype=np.int64)
    active_idx = np.nonzero(active)[0]

    def find(x: np.ndarray) -> np.ndarray:
        r = x.copy()
        while True:
            p = parent[r]
            done = p == r
            if done.all():
                return r
            r = np.where(done, r, parent[p])

    roots = find(active_idx)
    np.add.at(cweight, cluster_of[active_idx], weights[active_idx])
    np.minimum.at(min_instr, cluster_of[active_idx], active_idx)
    # Kahn with (min_instr, cluster) priority
    indeg = np.bincount(odst, minlength=count).astype(np.int64)
    out_off = np.zeros(count + 1, dtype=np.int64)
    np.add.at(out_off, osrc + 1, 1)
    np.cumsum(out_off, out=out_off)
    out_tgt = np.empty(osrc.size, dtype=np.int64)
    out_tgt[:] = odst[np.argsort(osrc, kind="stable")]
    import heapq

    heap = [(int(min_instr[c]), c) for c in range(count) if indeg[c] == 0]
    heapq.heapify(heap)
    order: list[int] = []
    while heap:
        _, c = heapq.heappop(heap)
        order.append(c)
        for off in range(out_off[c], out_off[c + 1]):
            t = int(out_tgt[off])
            indeg[t] -= 1
            if indeg[t] == 0:
                heapq.heappush(heap, (int(min_instr[t]), t))
    if len(order) != count:
        raise RuntimeError("cluster graph is cyclic")
    # greedy packing
    block_of_cluster = np.empty(count, dtype=np.int64)
    current_block = 0
    current_size = 0
    for c in order:
        w = int(cweight[c])
        if w > max_instructions:
            # oversized singleton: close the open block, take its own block
            if current_size > 0:
                current_block += 1
                current_size = 0
            block_of_cluster[c] = current_block
            current_block += 1
            continue
        if current_size + w > max_instructions and current_size > 0:
            current_block += 1
            current_size = 0
        block_of_cluster[c] = current_block
        current_size += w
    block_of_atom = np.full(n, -1, dtype=np.int64)
    block_of_atom[active_idx] = block_of_cluster[cluster_of[active_idx]]
    return block_of_atom
