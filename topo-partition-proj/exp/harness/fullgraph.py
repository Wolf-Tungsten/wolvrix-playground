"""Full-graph ordering search (docs/04 Phase 1, risk register R1).

Region-level evidence (docs/08) says the deterministic canonical order is
already near-optimal inside sampled regions — but region boundaries are
frozen there, so the experiment cannot see ordering's global value. This
module runs the same move set (legal-range relocate + swap, simulated
annealing) on a WHOLE design's instruction graph: no halo, nothing frozen.
The question it answers: how much cost headroom does ordering have beyond
``canonical Kahn order + segment DP`` when the search is free to move any
instruction anywhere?

Design notes:

- The segment DP runs at NODE level (capacity counts instructions, matching
  the production ``maxInstructionsPerBlock`` semantics). The annealer permutes
  comb-loop-atom GROUPS (an atom is indivisible, docs/03); a group order is
  expanded to a node order for scoring. On designs with no comb loops the
  expansion is a single gather (groups are singletons).
- Scoring reuses the C kernel (exp/harness/kernel.py); every proposed move
  is rescored exactly, same acceptance rule and temperature schedule as the
  region searcher (harness/searcher.py) — this is the full-graph port of
  ``anneal``/``calibrate_temperatures``.
- Commit-kind (state_write) instructions are excluded from the problem
  exactly as in tools/run_fullgraph_plaindp.py: their reads are free, they
  produce no values, and they keep their production commit blocks when the
  result is scored on the health-metric scoreboard.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .graph import InstructionGraph, build_csr
from .kernel import KernelDP
from .searcher import SEGMENT_CAPACITY, SearchResult


@dataclass
class FullGraphProblem:
    """Whole-design permutation problem: permute groups, score node orders."""

    kernel: KernelDP  # node-level segment DP (CSR keyed by global node id)
    node_ids: np.ndarray  # (n,) uint32 global ids of permutable (compute) nodes
    group_of_node: np.ndarray  # (N,) uint32 group id per graph node
    member_off: np.ndarray  # (G+1,) int64 group -> members slice (by group id)
    member_flat: np.ndarray  # (M,) uint32 member node ids concatenated
    initial_order: list[int]  # group ids in canonical topo order
    preds: list[list[int]]  # per group: predecessor groups (deduped)
    succs: list[list[int]]
    n_groups: int

    def node_order(self, group_order: np.ndarray) -> np.ndarray:
        """Expand a group permutation to the node order the DP scores."""
        group_order = np.ascontiguousarray(group_order, dtype=np.int64)
        lengths = self.member_off[group_order + 1] - self.member_off[group_order]
        total = int(lengths.sum())
        out_starts = np.zeros(group_order.size, dtype=np.int64)
        np.cumsum(lengths[:-1], out=out_starts[1:])
        group_of_pos = np.repeat(np.arange(group_order.size), lengths)
        within = np.arange(total, dtype=np.int64) - out_starts[group_of_pos]
        member_index = self.member_off[group_order[group_of_pos]] + within
        return self.member_flat[member_index].astype(np.int32)

    def cost(self, group_order: np.ndarray) -> float:
        return self.kernel.cost(self.node_order(group_order))


def build_fullgraph_problem(
    graph: InstructionGraph,
    capacity: int = SEGMENT_CAPACITY,
    penalty: float = 0.0,
) -> FullGraphProblem:
    """Build the whole-design problem; mirrors run_fullgraph_plaindp setup.

    uses = def_use + external_read edges whose consumer is a non-commit
    instruction (commit reads are free); defs = every def_use source defines
    its var. Legality edges = def_use + order edges between permutable
    groups (comb-loop-atom contraction, self-loops dropped).
    """
    n_graph = graph.instructions
    compute = ~graph.state_write
    group_of_node, _ = graph.comb_groups()
    n_groups_all = int(group_of_node.max()) + 1
    # A group is permutable iff all its members are compute instructions.
    group_has_commit = np.zeros(n_groups_all, dtype=bool)
    np.logical_or.at(group_has_commit, group_of_node, ~compute)
    permutable_group = ~group_has_commit

    # Node-level CSR for the DP (keyed by global node id; commit rows empty).
    du_keep = compute[graph.du_dst]
    er_keep = compute[graph.er_dst]
    use_key = np.concatenate([graph.du_dst[du_keep], graph.er_dst[er_keep]])
    use_val = np.concatenate([graph.du_var[du_keep], graph.er_var[er_keep]])
    use_off, use_var = build_csr(use_key, use_val, n_graph)
    def_off, def_var = build_csr(graph.du_src, graph.du_var, n_graph)
    weight = np.zeros(graph.variables, dtype=np.int64)
    all_key = np.concatenate([graph.du_var, graph.er_var])
    all_width = np.concatenate([graph.du_width, graph.er_width])
    weight[all_key] = np.maximum(1, (all_width + 63) // 64)

    node_ids = graph.topo_order[compute[graph.topo_order]].astype(np.uint32)
    kernel = KernelDP.from_csr(
        use_off, use_var, def_off, def_var, weight, capacity, n=node_ids.size
    )
    kernel.penalty = penalty

    # Group members concatenated by group id (stable sort keeps members in
    # node-id order within a group, matching kahn_order's expansion).
    order_by_group = np.argsort(group_of_node, kind="stable")
    sorted_groups = group_of_node[order_by_group]
    raw_off = np.zeros(n_groups_all + 1, dtype=np.int64)
    np.add.at(raw_off, sorted_groups.astype(np.int64) + 1, 1)
    np.cumsum(raw_off, out=raw_off)
    raw_flat = order_by_group.astype(np.uint32)
    # Condense to dense permutable-group ids (0..G-1) for the annealer.
    perm_group_ids = np.flatnonzero(permutable_group)
    n_groups = int(perm_group_ids.size)
    sizes = raw_off[perm_group_ids + 1] - raw_off[perm_group_ids]
    member_off = np.zeros(n_groups + 1, dtype=np.int64)
    np.cumsum(sizes, out=member_off[1:])
    gather = (
        np.arange(member_off[-1], dtype=np.int64)
        - np.repeat(member_off[:-1], sizes)
        + np.repeat(raw_off[perm_group_ids], sizes)
    )
    member_flat = raw_flat[gather]

    # Canonical group order: groups in first-appearance order along the
    # node-level canonical topo order (groups are contiguous in it).
    permutable_nodes = graph.topo_order[
        permutable_group[group_of_node[graph.topo_order]]
    ]
    groups_in_topo = group_of_node[permutable_nodes]
    first_seen = np.ones(n_groups_all, dtype=bool)
    initial: list[int] = []
    append = initial.append
    for g in groups_in_topo.tolist():
        if first_seen[g]:
            first_seen[g] = False
            append(int(g))
    # Dense remap of permutable group ids to 0..G-1 for the annealer.
    remap = np.full(n_groups_all, -1, dtype=np.int64)
    remap[perm_group_ids] = np.arange(n_groups)
    initial_order = [int(remap[g]) for g in initial]

    # Legality adjacency between permutable groups (def_use + order edges).
    src, dst = graph.dependency_edges()
    gs = remap[group_of_node[src]]
    gd = remap[group_of_node[dst]]
    keep = (gs >= 0) & (gd >= 0) & (gs != gd)
    gs, gd = gs[keep], gd[keep]
    edge_key = gs * n_groups + gd
    edge_key = np.unique(edge_key)
    gs, gd = edge_key // n_groups, edge_key % n_groups
    preds: list[list[int]] = [[] for _ in range(n_groups)]
    succs: list[list[int]] = [[] for _ in range(n_groups)]
    for s, d in zip(gs.tolist(), gd.tolist()):
        succs[int(s)].append(int(d))
        preds[int(d)].append(int(s))

    return FullGraphProblem(
        kernel=kernel,
        node_ids=node_ids,
        group_of_node=group_of_node,
        member_off=member_off,
        member_flat=member_flat,
        initial_order=initial_order,
        preds=preds,
        succs=succs,
        n_groups=n_groups,
    )


def verify_linear_extension(problem: FullGraphProblem, group_order: np.ndarray) -> int:
    """Count dependency edges pointing backward in the order (0 = valid)."""
    pos = np.empty(problem.n_groups, dtype=np.int64)
    pos[np.ascontiguousarray(group_order, dtype=np.int64)] = np.arange(problem.n_groups)
    bad = 0
    for g in range(problem.n_groups):
        for succ in problem.succs[g]:
            if pos[succ] <= pos[g]:
                bad += 1
    return bad


def random_group_orders(
    problem: FullGraphProblem, count: int, seed: int
) -> list[np.ndarray]:
    """Random linear extensions: Kahn with uniform-random ready pick.

    Null-hypothesis probe for the headroom question: if even random valid
    orders score within a few percent of canonical, the cost function is
    structurally insensitive to ordering at full-graph scale.
    """
    rng = np.random.default_rng(seed)
    indegree = np.array([len(p) for p in problem.preds], dtype=np.int64)
    orders: list[np.ndarray] = []
    for _ in range(count):
        deg = indegree.copy()
        ready = [g for g in range(problem.n_groups) if deg[g] == 0]
        out = np.empty(problem.n_groups, dtype=np.int32)
        for placed in range(problem.n_groups):
            pick = int(rng.integers(0, len(ready)))
            g = ready[pick]
            ready[pick] = ready[-1]
            ready.pop()
            out[placed] = g
            for succ in problem.succs[g]:
                deg[succ] -= 1
                if deg[succ] == 0:
                    ready.append(succ)
        orders.append(out)
    return orders


def calibrate_temperatures(
    problem: FullGraphProblem,
    samples: int = 200,
    seed: int = 0,
    start_order: np.ndarray | None = None,
) -> tuple[float, float]:
    """t0 = 2x mean positive move delta, t1 = t0/100 (searcher.py semantics).

    Every sample is a full-graph DP call, so ``samples`` stays small; the
    estimate only needs the scale of the delta distribution. Calibrated on
    ``start_order`` when given (random-start probes need their own scale).
    """
    rng = np.random.default_rng(seed)
    n = problem.n_groups
    order = np.array(
        problem.initial_order if start_order is None else start_order, dtype=np.int32
    )
    pos = np.empty(n, dtype=np.int32)
    pos[order] = np.arange(n, dtype=np.int32)
    current = problem.cost(order)
    deltas: list[float] = []
    for _ in range(samples):
        node = int(rng.integers(0, n))
        node_pos = int(pos[node])
        lo, hi = 0, n - 1
        for pred in problem.preds[node]:
            pred_pos = pos[pred] - (1 if pos[pred] > node_pos else 0)
            if pred_pos + 1 > lo:
                lo = int(pred_pos) + 1
        for succ in problem.succs[node]:
            succ_pos = pos[succ] - (1 if pos[succ] > node_pos else 0)
            if succ_pos < hi:
                hi = int(succ_pos)
        if lo > hi:
            continue
        target = int(rng.integers(lo, hi + 1))
        if target == node_pos:
            continue
        new_order = order.copy()
        if target < node_pos:
            new_order[target + 1 : node_pos + 1] = new_order[target:node_pos]
            new_order[target] = node
        else:
            new_order[node_pos:target] = new_order[node_pos + 1 : target + 1]
            new_order[target] = node
        delta = problem.cost(new_order) - current
        if delta > 0:
            deltas.append(float(delta))
    if not deltas:
        return 1.0, 0.01
    t0 = 2.0 * float(np.mean(deltas))
    return t0, t0 / 100.0


def anneal_fullgraph(
    problem: FullGraphProblem,
    iterations: int = 1000,
    t0: float = 10.0,
    t1: float = 0.1,
    swap_frac: float = 0.2,
    seed: int = 0,
    log_every: int = 0,
    start_order: np.ndarray | None = None,
) -> SearchResult:
    """Simulated annealing over group orders (full-graph port of anneal).

    Identical move set, legality rules, acceptance rule, and temperature
    schedule to harness/searcher.py's ``anneal``; the only differences are
    that positions index groups and scoring expands to node orders.
    ``start_order`` overrides the canonical starting point (e.g. a random
    linear extension, for basin-structure probes).
    """
    rng = np.random.default_rng(seed)
    n = problem.n_groups
    order = np.array(
        problem.initial_order if start_order is None else start_order, dtype=np.int32
    )
    pos = np.empty(n, dtype=np.int32)
    pos[order] = np.arange(n, dtype=np.int32)
    current = problem.cost(order)
    initial = current
    best = current
    best_order = order.copy()
    accepted = 0
    history: list[float] = []

    def legal_swap(a: int, b: int) -> bool:
        ia, ib = pos[a], pos[b]
        if ia > ib:
            a, b, ia, ib = b, a, ib, ia
        for succ in problem.succs[a]:
            if succ == b:
                return False
            if pos[succ] <= ib:
                return False
        for pred in problem.preds[b]:
            if pred == a:
                return False
            if pos[pred] >= ia:
                return False
        for pred in problem.preds[a]:
            if pos[pred] >= ib and pred != b:
                return False
        for succ in problem.succs[b]:
            if pos[succ] <= ia and succ != a:
                return False
        return True

    for iteration in range(iterations):
        temperature = t0 * (t1 / t0) ** (iteration / max(1, iterations - 1))
        if n >= 2 and rng.random() < swap_frac:
            a, b = int(rng.integers(0, n)), int(rng.integers(0, n))
            if a == b or not legal_swap(a, b):
                continue
            ia, ib = pos[a], pos[b]
            order[ia], order[ib] = order[ib], order[ia]
            undo = ("swap", ia, ib, 0)
        else:
            node = int(rng.integers(0, n))
            node_pos = int(pos[node])
            # Legal range in shrunk-list coordinates (exact, see searcher.py).
            lo = 0
            hi = n - 1
            for pred in problem.preds[node]:
                pred_pos = pos[pred] - (1 if pos[pred] > node_pos else 0)
                if pred_pos + 1 > lo:
                    lo = int(pred_pos) + 1
            for succ in problem.succs[node]:
                succ_pos = pos[succ] - (1 if pos[succ] > node_pos else 0)
                if succ_pos < hi:
                    hi = int(succ_pos)
            if lo > hi:
                continue
            target = int(rng.integers(lo, hi + 1))
            if target == node_pos:
                continue
            if target < node_pos:
                order[target + 1 : node_pos + 1] = order[target:node_pos]
                order[target] = node
            else:
                order[node_pos:target] = order[node_pos + 1 : target + 1]
                order[target] = node
            undo = ("move", node, node_pos, target)
        candidate = problem.cost(order)
        if candidate <= current or rng.random() < math.exp(
            min(0.0, (current - candidate) / max(temperature, 1e-9))
        ):
            kind, x, y, z = undo
            if kind == "swap":
                pos[order[x]] = x
                pos[order[y]] = y
            else:
                lo, hi = min(y, z), max(y, z)
                pos[order[lo : hi + 1]] = np.arange(lo, hi + 1, dtype=np.int32)
            current = candidate
            accepted += 1
            if current < best:
                best = current
                best_order = order.copy()
        else:
            kind, x, y, z = undo
            if kind == "swap":
                order[x], order[y] = order[y], order[x]
            else:
                if z < y:
                    order[z:y] = order[z + 1 : y + 1]
                else:
                    order[y + 1 : z + 1] = order[y:z]
                order[y] = x
        if log_every and iteration % log_every == 0:
            history.append(current)
    return SearchResult(
        initial_cost=initial,
        best_cost=best,
        best_order=best_order.tolist(),
        iterations=iterations,
        accepted=accepted,
        history=history,
    )
