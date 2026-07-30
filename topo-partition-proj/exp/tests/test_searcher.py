"""Unit tests for harness.searcher — segment DP against brute force, and the
annealing skeleton on synthetic problems."""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.graph import KIND_DEF_USE, KIND_EXTERNAL_READ, KIND_ORDER  # noqa: E402
from harness.sampler import EXTERNAL_SRC, Region  # noqa: E402
from harness.searcher import (  # noqa: E402
    RegionProblem,
    anneal,
    build_problem,
    segment_dp,
)


def brute_force_cost(
    uses: list[list[int]], defs: list[list[int]], weight: list[int], capacity: int
) -> float:
    """Enumerate all segmentations with segments <= capacity; min cost."""
    n = len(uses)
    src_pos = {}
    for pos in range(n):
        for var in defs[pos]:
            src_pos[var] = pos
    best = float("inf")
    # Compositions of n into parts <= capacity: choose cut points.
    for cuts in itertools.product([False, True], repeat=n - 1):
        segments = []
        start = 0
        for index, cut in enumerate(cuts):
            if cut:
                segments.append((start, index + 1))
                start = index + 1
        segments.append((start, n))
        if any(end - begin > capacity for begin, end in segments):
            continue
        cost = 0
        for begin, end in segments:
            seen_vars = set()
            for pos in range(begin, end):
                for var in uses[pos]:
                    if var in seen_vars:
                        continue
                    seen_vars.add(var)
                    if src_pos.get(var, -1) < begin:
                        cost += weight[var]
        best = min(best, cost)
    return best


def test_dp_matches_brute_force_small():
    rng = np.random.default_rng(42)
    for trial in range(30):
        n = int(rng.integers(1, 8))
        nvar = int(rng.integers(1, 6))
        uses = [
            sorted(rng.choice(nvar, size=min(rng.integers(0, 3), nvar), replace=False).tolist())
            for _ in range(n)
        ]
        # Each var defined at most once, before any use (keep it DAG-ish).
        defs: list[list[int]] = [[] for _ in range(n)]
        for var in range(nvar):
            if rng.random() < 0.5:  # boundary var: no definition
                continue
            pos = int(rng.integers(0, n))
            defs[pos].append(var)
            for earlier in range(pos + 1, n):  # uses must come after the def
                if var in uses[earlier]:
                    continue
        weight = (rng.integers(1, 4, size=nvar)).tolist()
        capacity = int(rng.integers(1, n + 1))
        dp_cost, dp_cuts = segment_dp(uses, defs, np.array(weight), capacity=capacity)
        bf_cost = brute_force_cost(uses, defs, weight, capacity)
        assert dp_cost == bf_cost, (trial, uses, defs, weight, capacity)
        # cuts respect capacity and reproduce the cost
        assert all(
            later - earlier <= capacity
            for earlier, later in zip(dp_cuts, dp_cuts[1:] + [n])
        )


def test_dp_hand_computed():
    # 0 defines v0(1 copy); 1,2 use v0; one segment is free, split costs 1.
    uses = [[], [0], [0]]
    defs = [[0], [], []]
    weight = np.array([1])
    cost, cuts = segment_dp(uses, defs, weight, capacity=3)
    assert cost == 0 and cuts == [0]
    cost, cuts = segment_dp(uses, defs, weight, capacity=2)
    assert cost == 1
    # Boundary var v1 (no def anywhere) pays in every consuming segment.
    uses = [[1], [1], [1]]
    defs = [[], [], []]
    weight = np.array([1, 2])  # v1 costs 2 copies
    cost, _ = segment_dp(uses, defs, weight, capacity=3)
    assert cost == 2
    cost, _ = segment_dp(uses, defs, weight, capacity=1)
    assert cost == 6  # three singleton segments, 2 copies each


def make_region() -> Region:
    """Internal nodes 0..3 (3 is state_write); halo node 4.

    Edges: 0->1 v10(w32), 1->2 v11(w128), ext->2 v20(w16), 2->3 v12(w8),
    halo 4->2 v13(w64), order 0->1.
    """
    return Region(
        node_id=np.array([0, 1, 2, 3, 4], dtype=np.uint32),
        internal_count=4,
        op=np.zeros(5, dtype=np.uint8),
        width=np.ones(5, dtype=np.int32),
        state_write=np.array([False, False, False, True, False]),
        comb_loop_atom=np.zeros(5, dtype=bool),
        topo_pos=np.arange(5, dtype=np.uint32),
        edge_src=np.array([0, 1, EXTERNAL_SRC, 2, 4, 0], dtype=np.uint32),
        edge_dst=np.array([1, 2, 2, 3, 2, 1], dtype=np.uint32),
        edge_kind=np.array(
            [KIND_DEF_USE, KIND_DEF_USE, KIND_EXTERNAL_READ, KIND_DEF_USE, KIND_DEF_USE, KIND_ORDER],
            dtype=np.uint8,
        ),
        edge_var=np.array([10, 11, 20, 12, 13, 0xFFFFFFFF], dtype=np.uint32),
        edge_width=np.array([32, 128, 16, 8, 64, 0], dtype=np.int32),
        meta={"method": "test"},
    )


def test_build_problem():
    problem = build_problem(make_region())
    # state_write node 3 excluded -> 3 permutable nodes.
    assert len(problem.initial_order) == 3
    assert problem.initial_order == [0, 1, 2]  # topo order
    by_var = {i: w for i, w in enumerate(problem.weight.tolist())}
    # uses: node0 [], node1 [v10], node2 [v11, v20, v13-from-halo]
    assert problem.uses[0] == []
    assert len(problem.uses[1]) == 1
    assert len(problem.uses[2]) == 3
    # defs: v10 by 0, v11 by 1, v12 by 2 (consumer is state_write, still a def)
    assert [len(d) for d in problem.defs] == [1, 1, 1]
    # weights: v11 is 128 bits -> 2 copies
    v11 = problem.defs[1][0]
    assert by_var[v11] == 2
    # legality edges 0->1 (def_use+order deduped), 1->2
    assert problem.succs[0] == [1]
    assert problem.preds[2] == [1]
    # cost of the canonical order: one segment; boundary v20/v13 pay 1 each.
    assert problem.order_cost(problem.initial_order) == 2


def random_problem(seed: int, n: int, nvar: int, capacity: int) -> RegionProblem:
    rng = np.random.default_rng(seed)
    preds: list[list[int]] = [[] for _ in range(n)]
    succs: list[list[int]] = [[] for _ in range(n)]
    uses: list[list[int]] = [[] for _ in range(n)]
    defs: list[list[int]] = [[] for _ in range(n)]
    for var in range(nvar):
        if rng.random() < 0.3:  # boundary var: no producer
            for _ in range(rng.integers(1, 3)):
                uses[int(rng.integers(0, n))].append(var)
            continue
        producer = int(rng.integers(0, n - 3))
        defs[producer].append(var)
        for _ in range(rng.integers(1, 4)):
            consumer = int(rng.integers(producer + 1, n))
            uses[consumer].append(var)
            if consumer not in succs[producer]:
                succs[producer].append(consumer)
                preds[consumer].append(producer)
    definer = np.full(nvar, -1, dtype=np.int32)
    for producer, produced in enumerate(defs):
        for var in produced:
            definer[var] = producer
    return RegionProblem(
        node_local=np.arange(n, dtype=np.uint32),
        uses=uses,
        defs=defs,
        weight=rng.integers(1, 4, size=nvar).astype(np.int64),
        preds=preds,
        succs=succs,
        initial_order=list(range(n)),
        definer=definer,
        capacity=capacity,
    )


def test_kernel_matches_python_dp():
    from harness.kernel import KernelDP, available

    if not available():
        import pytest

        pytest.skip("C compiler unavailable")
    rng = np.random.default_rng(11)
    for trial in range(20):
        problem = random_problem(
            seed=trial, n=int(rng.integers(4, 40)), nvar=int(rng.integers(1, 25)),
            capacity=int(rng.integers(1, 12)),
        )
        kernel = KernelDP(problem.uses, problem.defs, problem.weight, problem.capacity)
        for _ in range(5):
            order = rng.permutation(problem.initial_order).astype(np.int32)
            assert kernel.cost(order) == problem._python_cost(order)


def test_anneal_python_fallback_matches_legality():
    problem = random_problem(seed=5, n=30, nvar=20, capacity=8)
    problem._kernel_tried = True  # force the pure-Python path
    problem._kernel = False
    result = anneal(problem, iterations=200, t0=5.0, t1=0.05, seed=3)
    assert result.best_cost <= result.initial_cost
    pos = {node: index for index, node in enumerate(result.best_order)}
    for node, preds in enumerate(problem.preds):
        for pred in preds:
            assert pos[pred] < pos[node]


def test_anneal_never_worsens_and_keeps_legality():
    rng = np.random.default_rng(7)
    n, nvar = 30, 20
    # Random DAG: edges only i -> j with i < j.
    preds: list[list[int]] = [[] for _ in range(n)]
    succs: list[list[int]] = [[] for _ in range(n)]
    uses: list[list[int]] = [[] for _ in range(n)]
    defs: list[list[int]] = [[] for _ in range(n)]
    for var in range(nvar):
        producer = int(rng.integers(0, n - 5))
        defs[producer].append(var)
        for _ in range(rng.integers(1, 4)):
            consumer = int(rng.integers(producer + 1, n))
            uses[consumer].append(var)
            if consumer not in succs[producer]:
                succs[producer].append(consumer)
                preds[consumer].append(producer)
    problem = RegionProblem(
        node_local=np.arange(n, dtype=np.uint32),
        uses=uses,
        defs=defs,
        weight=rng.integers(1, 3, size=nvar).astype(np.int64),
        preds=preds,
        succs=succs,
        initial_order=list(range(n)),
        capacity=8,
    )
    result = anneal(problem, iterations=300, t0=5.0, t1=0.05, seed=3)
    assert result.best_cost <= result.initial_cost
    pos = {node: index for index, node in enumerate(result.best_order)}
    for node in range(n):
        for pred in preds[node]:
            assert pos[pred] < pos[node]
