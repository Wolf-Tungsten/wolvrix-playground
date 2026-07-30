"""Searcher skeleton (docs/04 Phase 0 task 4, parameters D7).

Given a sampled region, search over permutations of its internal nodes and
score each permutation with the segment DP; keep the best. Phase 0 ships the
skeleton: correct DP + a working simulated-annealing loop. Phase 1 completes
it (move-set tuning, iteration counts 10k-100k, and a C++ kernel for the hot
DP loop — the pure-Python DP here is correctness-first).

Segment DP: direct port of the production continuous-segment DP
(wolvrix/lib/grhsim/am/activity_schedule.cpp:535-615) with the new Phase-1
cost formula (docs/04 task 2): each segment pays, for every distinct value
it consumes that is not defined inside the segment, ``max(1, ceil(w/64))``
copies; no per-segment penalty. Values defined outside the permutable set
(halo producers, state targets, interface inputs) are permanent boundaries:
they pay in every consuming segment and are never subtracted back. Capacity
is 128 instructions per segment. Uses by commit-kind (state_write) nodes are
free and excluded from the problem, mirroring the production scoreboard.

Move legality: an order is valid iff every internal edge (def_use + order)
points forward. A relocate/swap is checked against the node's direct
predecessors/successors, which is exact for linear extensions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .graph import KIND_DEF_USE, KIND_EXTERNAL_READ, KIND_ORDER
from .sampler import Region

#: Capacity of one segment (production maxInstructionsPerBlock).
SEGMENT_CAPACITY = 128


def segment_dp(
    uses: list[list[int]],
    defs: list[list[int]],
    weight: np.ndarray,
    capacity: int = SEGMENT_CAPACITY,
    segment_penalty: float = 0.0,
) -> tuple[float, list[int]]:
    """Min-cost segmentation of a fixed order.

    ``uses``/``defs``: per-position variable ids (deduped per position).
    ``weight``: copies per variable. ``segment_penalty``: per-segment extra
    cost inside the DP objective (the production DP used 1.0; the harness
    cost formula itself is penalty-free). Returns (cost, cut-starts) where
    cut-starts are the segment start positions in increasing order; the
    returned cost includes the penalties.
    """
    n = len(uses)
    src_pos = np.full(weight.size, -1, dtype=np.int64)
    for pos in range(n):
        for var in defs[pos]:
            src_pos[var] = pos
    inf = math.inf
    dp = [inf] * (n + 1)
    dp[0] = 0.0
    prev = [0] * (n + 1)
    seen = [0] * weight.size
    counted = [0] * weight.size
    weight_list = weight.tolist()
    for end in range(1, n + 1):
        stamp = end
        cost = 0.0
        best = inf
        best_start = end - 1
        start = end - 1
        while start >= 0 and end - start <= capacity:
            for var in uses[start]:
                if seen[var] != stamp:
                    seen[var] = stamp
                    if src_pos[var] < start:  # -1 = permanent boundary
                        counted[var] = stamp
                        cost += weight_list[var]
            for var in defs[start]:
                if counted[var] == stamp:
                    counted[var] = 0
                    cost -= weight_list[var]
            candidate = dp[start] + cost + segment_penalty
            if candidate < best - 1e-12 or (
                abs(candidate - best) <= 1e-12 and (end - start) > (end - best_start)
            ):
                best = candidate
                best_start = start
            start -= 1
        dp[end] = best
        prev[end] = best_start
    cuts = []
    end = n
    while end > 0:
        cuts.append(prev[end])
        end = prev[end]
    cuts.reverse()
    return dp[n], cuts


@dataclass
class RegionProblem:
    """Searchable form of a region: only non-commit internal nodes permute."""

    node_local: np.ndarray  # (n,) uint32 region-local ids of permutable nodes
    uses: list[list[int]]  # per permutable node: dense var ids consumed
    defs: list[list[int]]  # per permutable node: dense var ids produced
    weight: np.ndarray  # (V,) int64 copies per dense var
    preds: list[list[int]]  # per permutable node: permutable predecessors
    succs: list[list[int]]
    initial_order: list[int]  # permutable indices in canonical topo order
    definer: np.ndarray = None  # (V,) int32: permutable index producing var, -1 = boundary
    capacity: int = SEGMENT_CAPACITY
    _kernel: object = None  # lazy KernelDP | False when unavailable
    _kernel_tried: bool = False

    def evaluator(self):
        """cost(order:int32 ndarray) -> float; C kernel when available."""
        if not self._kernel_tried:
            self._kernel_tried = True
            try:
                from .kernel import KernelDP

                self._kernel = KernelDP(self.uses, self.defs, self.weight, self.capacity)
            except Exception:
                self._kernel = False
        if self._kernel:
            return self._kernel.cost
        return self._python_cost

    def _python_cost(self, order) -> float:
        uses = [self.uses[int(node)] for node in order]
        defs = [self.defs[int(node)] for node in order]
        cost, _ = segment_dp(uses, defs, self.weight, capacity=self.capacity)
        return cost

    def order_cost(self, order) -> float:
        order = np.ascontiguousarray(order, dtype=np.int32)
        return self.evaluator()(order)

    def kernel_backed(self) -> bool:
        return self.evaluator() is not self._python_cost


def build_problem(region: Region) -> RegionProblem:
    """Extract the permutation problem from a sampled region.

    Commit-kind (state_write) internal nodes are excluded: their reads are
    free (production scoreboard) and they produce no values. comb-loop-atom
    members would have to stay atomic; the full XiangShan graph has none, so
    the skeleton refuses them loudly instead of handling them wrong.
    """
    internal = region.internal_count
    node_id = region.node_id[:internal]
    state_write = region.state_write[:internal]
    if region.comb_loop_atom[:internal].any():
        raise NotImplementedError(
            "region contains comb-loop-atom members; atomic grouping is Phase 1 work"
        )
    permutable = np.flatnonzero(~state_write)
    index_of = np.full(internal, -1, dtype=np.int64)
    index_of[permutable] = np.arange(permutable.size)

    # Dense per-problem variable ids with their copy weights.
    var_dense: dict[int, int] = {}
    weights: list[int] = []

    def dense_var(var: int, width: int) -> int:
        dense = var_dense.get(var)
        if dense is None:
            dense = len(weights)
            var_dense[var] = dense
            weights.append(max(1, (width + 63) // 64))
        return dense

    uses: list[list[int]] = [[] for _ in range(permutable.size)]
    defs: list[list[int]] = [[] for _ in range(permutable.size)]
    preds: list[list[int]] = [[] for _ in range(permutable.size)]
    succs: list[list[int]] = [[] for _ in range(permutable.size)]
    use_seen: list[set[int]] = [set() for _ in range(permutable.size)]
    dense_definer: dict[int, int] = {}  # dense var -> permutable producer index
    for src, dst, kind, var, width in zip(
        region.edge_src, region.edge_dst, region.edge_kind,
        region.edge_var, region.edge_width,
    ):
        src, dst, kind = int(src), int(dst), int(kind)
        if kind == KIND_EXTERNAL_READ:
            consumer = index_of[dst]
            if consumer >= 0:
                dense = dense_var(int(var), int(width))
                if dense not in use_seen[consumer]:
                    use_seen[consumer].add(dense)
                    uses[consumer].append(dense)
            continue
        src_internal = src < internal
        dst_permutable = index_of[dst] if dst < internal else -1
        if kind == KIND_DEF_USE:
            if src_internal and not state_write[src]:
                producer = index_of[src]
                dense = dense_var(int(var), int(width))
                if dense not in defs[producer]:
                    defs[producer].append(dense)
                    dense_definer[dense] = producer
            if dst_permutable >= 0:
                dense = dense_var(int(var), int(width))
                if dense not in use_seen[dst_permutable]:
                    use_seen[dst_permutable].add(dense)
                    uses[dst_permutable].append(dense)
        # Legality edges (def_use and order) between permutable nodes.
        if src_internal and dst_permutable >= 0 and not state_write[src]:
            producer = index_of[src]
            if dst_permutable not in succs[producer]:
                succs[producer].append(dst_permutable)
                preds[dst_permutable].append(producer)
    # Canonical order: permutable nodes sorted by topo position.
    order = sorted(range(permutable.size), key=lambda i: int(region.topo_pos[permutable[i]]))
    definer = np.full(len(weights), -1, dtype=np.int32)
    for dense, producer in dense_definer.items():
        definer[dense] = producer
    return RegionProblem(
        node_local=node_id[permutable].astype(np.uint32),
        uses=uses,
        defs=defs,
        weight=np.array(weights, dtype=np.int64),
        preds=preds,
        succs=succs,
        initial_order=order,
        definer=definer,
    )


def region_assignment_cost(problem: RegionProblem, blocks: np.ndarray) -> float:
    """Cost of an externally given assignment of the permutable nodes.

    ``blocks``: (n,) block id per permutable node. Charges, per deduped
    (var, block) pair where the var's producer is a boundary var or sits in
    a different block, the var's copy weight — the same semantics as the
    segment DP, so externally produced partitions (e.g. the production
    baseline restricted to the region) compare apples-to-apples with the
    search result.
    """
    blocks = np.ascontiguousarray(blocks, dtype=np.int64)
    if blocks.size != len(problem.uses):
        raise ValueError("blocks length != permutable node count")
    use_off, use_var = np.zeros(len(problem.uses) + 1, dtype=np.int64), None
    counts = np.array([len(entry) for entry in problem.uses], dtype=np.int64)
    np.cumsum(counts, out=use_off[1:])
    use_var = np.array([v for entry in problem.uses for v in entry], dtype=np.int64)
    consumer = np.repeat(np.arange(len(problem.uses), dtype=np.int64), counts)
    producer = problem.definer[use_var].astype(np.int64)
    same_block = (producer >= 0) & (blocks[producer] == blocks[consumer])
    keys = (use_var[~same_block] << 32) | blocks[consumer[~same_block]]
    unique, first = np.unique(keys, return_index=True)
    return float(problem.weight[use_var[~same_block][first]].sum())


@dataclass
class SearchResult:
    initial_cost: float
    best_cost: float
    best_order: list[int]
    iterations: int
    accepted: int
    history: list[float] = field(default_factory=list)


def calibrate_temperatures(
    problem: RegionProblem,
    samples: int = 2000,
    seed: int = 0,
) -> tuple[float, float]:
    """Pick (t0, t1) from the move-delta distribution of the initial order.

    Samples legal relocate/swap candidates once and returns t0 = 2x the mean
    positive delta (initial accept-worse probability ~60%) and t1 = t0/100
    (near-greedy by the end). Falls back to (1.0, 0.01) when no worsening
    move shows up.
    """
    rng = np.random.default_rng(seed)
    n = len(problem.initial_order)
    order = np.array(problem.initial_order, dtype=np.int32)
    pos = np.empty(n, dtype=np.int32)
    pos[order] = np.arange(n, dtype=np.int32)
    cost_of = problem.evaluator()
    current = cost_of(order)
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
        delta = cost_of(new_order) - current
        if delta > 0:
            deltas.append(float(delta))
    if not deltas:
        return 1.0, 0.01
    t0 = 2.0 * float(np.mean(deltas))
    return t0, t0 / 100.0


def anneal(
    problem: RegionProblem,
    iterations: int = 1000,
    t0: float = 10.0,
    t1: float = 0.1,
    swap_frac: float = 0.2,
    seed: int = 0,
    log_every: int = 0,
) -> SearchResult:
    """Simulated annealing over relocate/swap moves (D7).

    The order is a numpy int32 array mutated in place (reverted on reject);
    every candidate is rescored exactly by the segment DP — the C kernel when
    available (exp/harness/kernel.py), the pure-Python DP otherwise.
    """
    rng = np.random.default_rng(seed)
    n = len(problem.initial_order)
    order = np.array(problem.initial_order, dtype=np.int32)
    pos = np.empty(n, dtype=np.int32)
    pos[order] = np.arange(n, dtype=np.int32)
    cost_of = problem.evaluator()
    current = cost_of(order)
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
            # D7: relocate within the legal range — after every predecessor,
            # before every successor (shrunk-list coordinates, exact).
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
                continue  # pinned by its neighbours
            target = int(rng.integers(lo, hi + 1))
            if target == node_pos:
                continue  # no-op relocation (insert back where it was)
            if target < node_pos:
                order[target + 1 : node_pos + 1] = order[target:node_pos]
                order[target] = node
            else:
                order[node_pos:target] = order[node_pos + 1 : target + 1]
                order[target] = node
            undo = ("move", node, node_pos, target)
        candidate = cost_of(order)
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
                # Undo relocate of node x from y to z: shift the affected
                # elements back toward z, then restore x at y.
                if z < y:  # left move
                    order[z:y] = order[z + 1 : y + 1]
                else:  # right move
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
