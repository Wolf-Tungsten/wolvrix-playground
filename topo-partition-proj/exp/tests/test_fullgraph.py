"""Unit tests for harness/fullgraph.py (full-graph ordering search, R1)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.fullgraph import (  # noqa: E402
    anneal_fullgraph,
    build_fullgraph_problem,
    calibrate_temperatures,
    random_group_orders,
    verify_linear_extension,
)
from harness.graph import InstructionGraph, kahn_order  # noqa: E402
from harness.searcher import segment_dp  # noqa: E402


def synthetic_graph() -> InstructionGraph:
    """7 nodes: node 6 is state_write; nodes 4<->5 form a comb-loop atom.

    def_use: 0->1(v0), 1->2(v1), 0->2(v2), 2->3(v3), 3->4(v6),
             4->5(v4), 5->4(v5)   [the last two close the comb loop]
    external_read: 2 reads v9 (200b), 5 reads v8 (1b)
    order edge: 3->6
    """
    n, nvar = 7, 10
    atom = np.arange(n, dtype=np.uint32)
    atom[4] = atom[5] = 10
    comb = np.zeros(n, dtype=bool)
    comb[4] = comb[5] = True
    state_write = np.zeros(n, dtype=bool)
    state_write[6] = True
    du_src = np.array([0, 1, 0, 2, 3, 4, 5], dtype=np.uint32)
    du_dst = np.array([1, 2, 2, 3, 4, 5, 4], dtype=np.uint32)
    du_var = np.array([0, 1, 2, 3, 6, 4, 5], dtype=np.uint32)
    du_width = np.array([32, 32, 64, 128, 32, 32, 32], dtype=np.int32)
    er_dst = np.array([2, 5], dtype=np.uint32)
    er_var = np.array([9, 8], dtype=np.uint32)
    er_width = np.array([200, 1], dtype=np.int32)
    ord_src = np.array([3], dtype=np.uint32)
    ord_dst = np.array([6], dtype=np.uint32)
    graph = InstructionGraph(
        instructions=n,
        variables=nvar,
        op=np.zeros(n, dtype=np.uint8),
        opcode_names=["op"],
        width=np.full(n, 32, dtype=np.int32),
        state_write=state_write,
        atom=atom,
        comb_loop_atom=comb,
        du_src=du_src,
        du_dst=du_dst,
        du_var=du_var,
        du_width=du_width,
        er_dst=er_dst,
        er_var=er_var,
        er_width=er_width,
        ord_src=ord_src,
        ord_dst=ord_dst,
        topo_order=np.empty(0, dtype=np.uint32),
        topo_pos=np.empty(0, dtype=np.uint32),
    )
    topo = kahn_order(graph)
    pos = np.empty(n, dtype=np.uint32)
    pos[topo] = np.arange(n, dtype=np.uint32)
    graph.topo_order = topo
    graph.topo_pos = pos
    return graph


def reference_cost(problem, group_order) -> float:
    """Independent Python reference: segment_dp on the expanded node order."""
    node_order = problem.node_order(np.asarray(group_order, dtype=np.int32))
    use_off = problem.kernel.use_off
    use_var = problem.kernel.use_var
    def_off = problem.kernel.def_off
    def_var = problem.kernel.def_var
    uses = [use_var[use_off[v] : use_off[v + 1]].tolist() for v in node_order]
    defs = [def_var[def_off[v] : def_off[v + 1]].tolist() for v in node_order]
    cost, _ = segment_dp(uses, defs, problem.kernel.weight)
    return cost


def test_build_problem_groups():
    problem = build_fullgraph_problem(synthetic_graph())
    # Groups: {4,5} plus singletons 0..3; state_write node 6 excluded.
    assert problem.n_groups == 5
    assert problem.node_ids.size == 6
    # Canonical expansion = compute nodes in topo order.
    expanded = problem.node_order(np.array(problem.initial_order, dtype=np.int32))
    assert expanded.tolist() == [0, 1, 2, 3, 4, 5]
    # Atom members travel together.
    sizes = problem.member_off[1:] - problem.member_off[:-1]
    assert sorted(sizes.tolist()) == [1, 1, 1, 1, 2]
    # Legality edges lifted to groups; the 3->6 order edge drops (6 excluded).
    n_edges = sum(len(s) for s in problem.succs)
    assert n_edges == 5  # 0->1,0->2,1->2,2->3,3->G(4,5); loop edges internal


def test_kernel_matches_python_reference():
    problem = build_fullgraph_problem(synthetic_graph())
    expected = reference_cost(problem, problem.initial_order)
    got = problem.cost(np.array(problem.initial_order, dtype=np.int32))
    assert got == expected


def test_anneal_never_worse_and_legal():
    problem = build_fullgraph_problem(synthetic_graph())
    t0, t1 = calibrate_temperatures(problem, samples=50, seed=1)
    result = anneal_fullgraph(problem, iterations=300, t0=t0, t1=t1, seed=1)
    assert result.best_cost <= result.initial_cost
    best = np.array(result.best_order, dtype=np.int32)
    assert verify_linear_extension(problem, best) == 0
    # Atom members stay adjacent after expansion.
    expanded = problem.node_order(best).tolist()
    assert abs(expanded.index(4) - expanded.index(5)) == 1


def test_random_extensions_are_valid_permutations():
    problem = build_fullgraph_problem(synthetic_graph())
    for order in random_group_orders(problem, 4, seed=7):
        assert sorted(order.tolist()) == list(range(problem.n_groups))
        assert verify_linear_extension(problem, order) == 0
