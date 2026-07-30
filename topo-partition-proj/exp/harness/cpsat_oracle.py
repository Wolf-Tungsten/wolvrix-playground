"""Exact optimum for small regions via CP-SAT (docs/04 Phase 1 task 3).

Quantifies how far the annealed search result is from the mathematical
optimum. Model: ``seg[v]`` in [0, K) assigns every permutable node a block;
precedence edges force seg[u] <= seg[v], so the quotient is acyclic and —
by the docs/02 §4 theorem (every acyclic partition is a contiguous
segmentation of some topological order, and the segment DP finds the best
segmentation for that order) — minimizing the partition cost over monotone
seg assignments is exactly the search problem's optimum.

Cost terms mirror the segment DP: for each (var, segment), pay the copy
weight when the var is consumed in the segment but not defined there
(permanent-boundary vars have no producer and pay in every consuming
segment). Merging adjacent segments never increases this cost (dedup), so
the optimum uses the capacity-forced minimum K = ceil(n / capacity)
segments. Meaningful only when n > capacity (otherwise one segment is
forced and every order scores identically); regions are sampled at 160-220
internal nodes so permutable n lands in (128, 200].

Requires ortools (pip install ortools).
"""

from __future__ import annotations

import math

from .searcher import SEGMENT_CAPACITY, RegionProblem


def solve_optimal(
    problem: RegionProblem,
    capacity: int = SEGMENT_CAPACITY,
    time_limit_s: float = 300.0,
    workers: int = 8,
) -> tuple[float, str]:
    """Return (optimal_cost, solver_status). Exact objective = segment-DP cost."""
    from ortools.sat.python import cp_model

    n = len(problem.uses)
    k = max(2, math.ceil(n / capacity))
    model = cp_model.CpModel()
    seg = [model.new_int_var(0, k - 1, f"seg_{v}") for v in range(n)]
    for v in range(n):
        for pred in problem.preds[v]:
            model.add(seg[pred] <= seg[v])
    # Boolean seg[v] == s helpers, shared across cost terms.
    eq = {}
    for v in range(n):
        for s in range(k):
            flag = model.new_bool_var(f"eq_{v}_{s}")
            model.add(seg[v] == s).only_enforce_if(flag)
            model.add(seg[v] != s).only_enforce_if(flag.Not())
            eq[(v, s)] = flag
    for s in range(k):
        model.add(cp_model.LinearExpr.sum([eq[(v, s)] for v in range(n)]) <= capacity)
    objective_terms = []
    for var in range(problem.weight.size):
        producer = int(problem.definer[var])
        consumers = [v for v in range(n) if var in problem.uses[v]]
        if not consumers:
            continue
        weight = int(problem.weight[var])
        for s in range(k):
            used = model.new_bool_var(f"used_{var}_{s}")
            model.add_max_equality(used, [eq[(v, s)] for v in consumers])
            if producer >= 0:
                defined = eq[(producer, s)]
                pay = model.new_bool_var(f"pay_{var}_{s}")
                model.add_bool_and([used, defined.Not()]).only_enforce_if(pay)
                model.add_bool_or([used.Not(), defined]).only_enforce_if(pay.Not())
            else:  # permanent boundary: pays in every consuming segment
                pay = used
            objective_terms.append(weight * pay)
    model.minimize(cp_model.LinearExpr.sum(objective_terms) if objective_terms else 0)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_workers = workers
    status = solver.solve(model)
    status_name = solver.status_name(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return math.inf, status_name
    return float(solver.objective_value), status_name
