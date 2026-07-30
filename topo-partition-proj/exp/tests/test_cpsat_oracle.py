"""Unit tests for harness.cpsat_oracle."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

cp_sat = pytest.importorskip("ortools.sat.python.cp_model")

from harness.cpsat_oracle import solve_optimal  # noqa: E402
from harness.searcher import RegionProblem, anneal  # noqa: E402
from tests.test_searcher import random_problem  # noqa: E402


def handcrafted() -> RegionProblem:
    """Two chains 0->1, 2->3 plus cross var def@0 used@3; capacity 3.

    Optimum 1: seg{0,1} + seg{2,3} makes chain vars free, cross var pays 1.
    """
    n, nvar = 4, 3
    uses = [[], [0], [], [1, 2]]
    defs = [[0, 2], [], [1], []]
    preds = [[], [0], [], [2]]
    succs = [[1], [], [3], []]
    return RegionProblem(
        node_local=np.arange(n, dtype=np.uint32),
        uses=uses,
        defs=defs,
        weight=np.ones(nvar, dtype=np.int64),
        preds=preds,
        succs=succs,
        initial_order=[0, 1, 2, 3],
        definer=np.array([0, 2, 0], dtype=np.int32),
        capacity=3,
    )


def test_handcrafted_optimum():
    cost, status = solve_optimal(handcrafted(), capacity=3, time_limit_s=30)
    assert status == "OPTIMAL"
    assert cost == 1.0


def test_oracle_bounds_on_random_problem():
    problem = random_problem(seed=9, n=30, nvar=20, capacity=8)
    cost, status = solve_optimal(problem, capacity=8, time_limit_s=60)
    assert status in ("OPTIMAL", "FEASIBLE")
    # Upper bound: the annealed search can only be >= the optimum.
    result = anneal(problem, iterations=200, t0=2.0, t1=0.02, seed=1)
    assert cost <= result.best_cost + 1e-9
    # Lower bound: every boundary var used internally pays at least once.
    boundary = sum(
        int(problem.weight[var])
        for var in range(problem.weight.size)
        if problem.definer[var] < 0
        and any(var in use for use in problem.uses)
    )
    assert cost >= boundary - 1e-9
