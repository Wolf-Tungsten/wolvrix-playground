#!/usr/bin/env python3

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass


INF = 10**9


@dataclass(frozen=True)
class DpResult:
    cost: int
    cuts: tuple[tuple[int, int], ...]


def edge_cut_cost(begin: int, end: int, succs: list[list[int]], preds: list[list[int]]) -> int:
    cost = 0
    for node in range(begin, end):
        cost += len(succs[node])
        for pred in preds[node]:
            if begin <= pred < node:
                cost -= 1
    return cost


def run_gsim_dp(sizes: list[int], succs: list[list[int]], preds: list[list[int]], max_size: int) -> DpResult:
    count = len(sizes)
    best = [INF] * (count + 1)
    back = [-1] * (count + 1)
    best[0] = 0

    for begin in range(count):
        if best[begin] >= INF:
            continue
        accum = sizes[begin]
        next_bound = begin + 1
        while next_bound < count and accum + sizes[next_bound] <= max_size:
            accum += sizes[next_bound]
            next_bound += 1

        cut_cost = 0
        for end in range(begin + 1, next_bound + 1):
            node = end - 1
            cut_cost += len(succs[node])
            for pred in preds[node]:
                if pred >= begin:
                    cut_cost -= 1
            new_cost = best[begin] + cut_cost
            if new_cost < best[end]:
                best[end] = new_cost
                back[end] = begin

    return backtrace(best[count], back, count)


def run_grhsim_dp(
    sizes: list[int],
    succs: list[list[int]],
    preds: list[list[int]],
    max_size: int,
    fixed: set[int] | None = None,
    sink_only: set[int] | None = None,
) -> DpResult:
    fixed = fixed or set()
    sink_only = sink_only or set()
    count = len(sizes)
    best = [INF] * (count + 1)
    back = [-1] * (count + 1)
    best[0] = 0

    for begin in range(count):
        if best[begin] >= INF:
            continue
        accum = 0
        cut_cost = 0
        fixed_singleton = False
        segment_sink: bool | None = None
        for end in range(begin + 1, count + 1):
            node = end - 1
            node_sink = node in sink_only
            if segment_sink is None:
                segment_sink = node_sink
            elif segment_sink != node_sink:
                break
            if node in fixed:
                if node != begin:
                    break
                fixed_singleton = True
            elif fixed_singleton:
                break

            accum += sizes[node]
            oversized_singleton = False
            if accum > max_size:
                if node != begin:
                    break
                oversized_singleton = True

            cut_cost += len(succs[node])
            for pred in preds[node]:
                if begin <= pred < node:
                    cut_cost -= 1

            new_cost = best[begin] + cut_cost
            if new_cost < best[end] or (new_cost == best[end] and (back[end] < 0 or begin < back[end])):
                best[end] = new_cost
                back[end] = begin
            if oversized_singleton:
                break

    return backtrace(best[count], back, count)


def backtrace(cost: int, back: list[int], count: int) -> DpResult:
    if count == 0:
        return DpResult(0, ())
    if cost >= INF or back[count] < 0:
        return DpResult(INF, tuple((i, i + 1) for i in range(count)))
    cuts: list[tuple[int, int]] = []
    end = count
    while end > 0:
        begin = back[end]
        cuts.append((begin, end))
        end = begin
    cuts.reverse()
    return DpResult(cost, tuple(cuts))


def make_random_dag(rng: random.Random, count: int, max_forward: int, edge_prob: float) -> tuple[list[list[int]], list[list[int]]]:
    succs = [[] for _ in range(count)]
    preds = [[] for _ in range(count)]
    for src in range(count):
        for dst in range(src + 1, min(count, src + 1 + max_forward)):
            if rng.random() < edge_prob:
                succs[src].append(dst)
                preds[dst].append(src)
    return succs, preds


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    plain_mismatch = 0
    constraint_mismatch = 0
    examples: list[tuple[str, list[int], set[int], set[int], DpResult, DpResult]] = []

    for _ in range(args.cases):
        count = rng.randint(2, 18)
        sizes = [rng.randint(1, 5) for _ in range(count)]
        max_size = rng.randint(3, 12)
        succs, preds = make_random_dag(rng, count, rng.randint(1, 6), rng.uniform(0.05, 0.35))

        gsim = run_gsim_dp(sizes, succs, preds, max_size)
        grh_plain = run_grhsim_dp(sizes, succs, preds, max_size)
        if gsim != grh_plain:
            plain_mismatch += 1
            if len(examples) < 3:
                examples.append(("plain", sizes, set(), set(), gsim, grh_plain))

        fixed = {i for i in range(count) if rng.random() < 0.05}
        sink_only = {i for i in range(count) if rng.random() < 0.10}
        grh_constrained = run_grhsim_dp(sizes, succs, preds, max_size, fixed=fixed, sink_only=sink_only)
        if gsim != grh_constrained:
            constraint_mismatch += 1
            if len(examples) < 6:
                examples.append(("constrained", sizes, fixed, sink_only, gsim, grh_constrained))

    print(f"cases={args.cases} seed={args.seed}")
    print(f"plain_gsim_vs_grhsim_mismatch={plain_mismatch}")
    print(f"constrained_gsim_vs_grhsim_mismatch={constraint_mismatch}")
    for idx, (kind, sizes, fixed, sink_only, gsim, grh) in enumerate(examples, 1):
        print(f"example{idx}: kind={kind} sizes={sizes} fixed={sorted(fixed)} sink_only={sorted(sink_only)}")
        print(f"  gsim cost={gsim.cost} cuts={gsim.cuts}")
        print(f"  grh  cost={grh.cost} cuts={grh.cuts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
