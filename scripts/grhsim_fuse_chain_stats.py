#!/usr/bin/env python3
"""Single-use transparent-chain census for expression-tree (P4) coarsening.

On a mapped GrhSIM checkpoint, quantify how many compute-task op results could
be inlined into their single consumer when the emitter switches from
per-op statements to nested expression trees:

  eligibility(v): producer P is a pure core.compute op with a single result;
  v has exactly one consuming op C; v is not a boundary value; P and C live in
  the same leaf partition (supernode) of the CPU mapping.

Reports per-producer-kind breakdowns (2-state logic width buckets), chain-depth
structure (fusible value consumed by another fusible-value producer), sink
kinds (what the chains feed), and per-supernode coverage distribution.

The model JSON op layout is [id, opType, name, origin, operands, results,
objectRefs, parameters]; objectRefs are [kind, index] pairs.
mapping payload: partitions at payload[2] ([id, ?, ?, ?, children, ops, ...]),
value slots at payload[3][3] (slot[1]==2 -> boundary), schedule at payload[4].
"""

from __future__ import annotations

import argparse
from array import array
from collections import Counter, defaultdict
import json
import sys
import time


TRANSPARENT_DATA = {"add", "sub", "mul", "and", "or", "xor", "xnor", "not", "shl"}
NON_TRANSPARENT = {
    "div", "mod", "eq", "ne", "caseEq", "caseNe", "wildcardEq", "wildcardNe",
    "lt", "le", "gt", "ge", "logicAnd", "logicOr", "logicNot",
    "reduceAnd", "reduceOr", "reduceXor", "reduceNor", "reduceNand",
    "reduceXnor", "lshr", "ashr", "sliceDynamic", "sliceArray",
}
STRUCTURAL = {"mux", "bitSelect", "prioritySelect", "concat", "replicate",
              "sliceStatic", "assign", "constant"}


def bucket(width: int) -> str:
    if width <= 1:
        return "1"
    if width <= 8:
        return "2-8"
    if width <= 32:
        return "9-32"
    if width <= 64:
        return "33-64"
    return ">64"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="mapped xiangshan_grhsim_ir.json")
    args = parser.parse_args()

    t0 = time.time()
    with open(args.model, "rb") as fh:
        model = json.load(fh)
    log(f"[load] {time.time() - t0:.1f}s")

    strings = model["strings"]
    types = {t[0]: t for t in model["types"]}
    values = model["values"]
    ops = model["operations"]
    n_ops = len(ops)
    n_values = len(values)

    payload = model["mappings"][0][-1]
    partitions = {p[0]: p for p in payload[2]}
    value_slots = payload[3][3]
    schedule = payload[4]

    def text(string_id):
        return strings[string_id - 1] if string_id else "<none>"

    # type info: values[v] = [id, typeIndex, ...]; types entry layout per
    # grhsim_used_bits_stats: [id, ref, kind, width, isSigned, domain, elem, count]
    def logic_info(type_index: int):
        t = types[type_index]
        kind, width, domain = t[2], t[3], t[5]
        if kind != "logic":
            return (0, False)
        return (width, domain == "2-state")

    # ---- op arrays (1-based ordinals) ----
    kind_of = [""] * (n_ops + 1)
    operands_of = [None] * (n_ops + 1)
    results_of = [None] * (n_ops + 1)
    for index, op in enumerate(ops):
        ordinal = index + 1
        kind_of[ordinal] = text(op[1])
        operands_of[ordinal] = op[4]
        results_of[ordinal] = op[5]

    width_of = array("i", bytes(4 * (n_values + 1)))
    twostate_of = bytearray(n_values + 1)
    for index, value in enumerate(values):
        w, two = logic_info(value[1])
        width_of[index + 1] = w
        twostate_of[index + 1] = 1 if two else 0

    producer = array("i", bytes(4 * (n_values + 1)))
    for ordinal in range(1, n_ops + 1):
        for v in results_of[ordinal]:
            producer[v] = ordinal

    # consumer count + single consumer
    use_count = array("i", bytes(4 * (n_values + 1)))
    sole_consumer = array("i", bytes(4 * (n_values + 1)))
    for ordinal in range(1, n_ops + 1):
        for v in operands_of[ordinal]:
            use_count[v] += 1
            sole_consumer[v] = ordinal
    log(f"[arrays] {time.time() - t0:.1f}s")

    # ---- partition membership ----
    op_part = array("i", bytes(4 * (n_ops + 1)))
    part_children = {}
    for pid, part in partitions.items():
        part_children[pid] = part[4]
        for op_id in part[5]:
            op_part[op_id] = pid
    is_leaf = {pid: 1 if not part_children[pid] else 0 for pid in partitions}
    leaf_ops = sum(1 for o in range(1, n_ops + 1) if op_part[o] and is_leaf[op_part[o]])
    internal_ops = sum(1 for o in range(1, n_ops + 1) if op_part[o] and not is_leaf[op_part[o]])
    unmapped = n_ops - leaf_ops - internal_ops
    print(f"partitions={len(partitions)} leaves={sum(is_leaf.values())}")
    print(f"ops on leaf partitions={leaf_ops} internal={internal_ops} unmapped={unmapped}")

    # ---- task classification (compute/commit/system) ----
    tasks = []
    for numa in schedule[0]:
        for core in numa[1]:
            tasks.extend(core[1])
    op_task = array("i", bytes(4 * (n_ops + 1)))
    for task in tasks:
        stack = [task[1]]
        while stack:
            part = partitions[stack.pop()]
            for op_id in part[5]:
                op_task[op_id] = task[0]
            stack.extend(part[4])
    WRITE_OPS = {
        "core.state.regWrite", "core.state.latchWrite", "core.state.memWrite",
        "core.state.memWriteSeq", "core.state.memFill", "core.state.memAssign",
    }
    SIDE_EFFECT_OPS = {"core.dpi.call", "core.system.task", "core.system.function",
                       "core.output.write"}
    task_kind = {}
    for task in tasks:
        tid = task[0]
        kinds = set()
        stack = [task[1]]
        while stack:
            part = partitions[stack.pop()]
            for op_id in part[5]:
                kinds.add(kind_of[op_id])
            stack.extend(part[4])
        if kinds & SIDE_EFFECT_OPS:
            task_kind[tid] = "system"
        elif kinds & WRITE_OPS:
            task_kind[tid] = "commit"
        else:
            task_kind[tid] = "compute"
    log(f"[tasks] compute={sum(1 for k in task_kind.values() if k == 'compute')} "
        f"commit={sum(1 for k in task_kind.values() if k == 'commit')} "
        f"system={sum(1 for k in task_kind.values() if k == 'system')} ({time.time() - t0:.1f}s)")

    boundary_value = bytearray(n_values + 1)
    for i, slot in enumerate(value_slots):
        if slot[1] == 2:
            boundary_value[i + 1] = 1

    # ---- fusion census ----
    compute_ops = 0           # pure compute ops inside compute tasks
    fusible = 0               # values eligible for inlining into sole consumer
    fusible_chain = 0         # fusible and consumer's result is itself fusible
    kind_hist = Counter()     # producer kind of fusible values
    kind_width = Counter()    # (producer kind, width bucket)
    sink_hist = Counter()     # consumer kind (what fused chains feed)
    fourstate = 0
    wide = 0
    multi_use_same_part = 0   # used >1 but all uses inside same partition
    per_part_total = defaultdict(int)
    per_part_fusible = defaultdict(int)
    task_fusible = defaultdict(lambda: [0, 0])  # task -> [fusible, compute_ops]

    def short(kind: str) -> str:
        return kind[len("core.compute."):] if kind.startswith("core.compute.") else kind

    for ordinal in range(1, n_ops + 1):
        kind = kind_of[ordinal]
        if not kind.startswith("core.compute."):
            continue
        tid = op_task[ordinal]
        if not tid or task_kind.get(tid) != "compute":
            continue
        results = results_of[ordinal]
        if len(results) != 1:
            continue
        compute_ops += 1
        v = results[0]
        part = op_part[ordinal]
        if tid:
            task_fusible[tid][1] += 1
        if part and is_leaf[part]:
            per_part_total[part] += 1
        # eligibility
        if use_count[v] != 1 or boundary_value[v] or not part or not is_leaf[part]:
            continue
        consumer = sole_consumer[v]
        if op_part[consumer] != part:
            continue
        w = width_of[v]
        if not twostate_of[v]:
            fourstate += 1
            continue
        if w > 64:
            wide += 1
        fusible += 1
        k = short(kind)
        kind_hist[k] += 1
        kind_width[(k, bucket(w))] += 1
        sink_hist[short(kind_of[consumer])] += 1
        per_part_fusible[part] += 1
        if tid:
            task_fusible[tid][0] += 1
        # does the chain continue? consumer is itself a fusible compute op
        cresults = results_of[consumer]
        if (len(cresults) == 1 and kind_of[consumer].startswith("core.compute.")
                and use_count[cresults[0]] == 1 and not boundary_value[cresults[0]]
                and op_part[consumer]):
            fusible_chain += 1

    print(f"\n== P4 single-use chain census (compute tasks) ==")
    print(f"compute-task compute ops (single result): {compute_ops}")
    print(f"fusible (single-use, non-boundary, same-leaf-partition, 2-state): {fusible} "
          f"({100.0 * fusible / max(compute_ops, 1):.2f}%)")
    print(f"  of which >64 wide: {wide} ({100.0 * wide / max(fusible, 1):.2f}%)")
    print(f"  4-state excluded: {fourstate}")
    print(f"fusible whose consumer also fusible (chain interior): {fusible_chain} "
          f"({100.0 * fusible_chain / max(fusible, 1):.2f}% of fusible)")
    print(f"\nfusible by producer kind:")
    for kind, count in kind_hist.most_common(20):
        klass = ("transparent" if kind in TRANSPARENT_DATA else
                 "structural" if kind in STRUCTURAL else
                 "non-transparent" if kind in NON_TRANSPARENT else "other")
        print(f"  {kind:<18} {count:>9}  [{klass}]")
    trans_total = sum(kind_hist[k] for k in TRANSPARENT_DATA if k in kind_hist)
    struct_total = sum(kind_hist[k] for k in STRUCTURAL if k in kind_hist)
    print(f"  transparent-data total: {trans_total} ({100.0 * trans_total / max(fusible, 1):.2f}%)")
    print(f"  structural total:       {struct_total} ({100.0 * struct_total / max(fusible, 1):.2f}%)")
    print(f"\nfusible by (producer kind, width bucket) top-20:")
    for (kind, b), count in kind_width.most_common(20):
        print(f"  {kind:<18} {b:<6} {count:>9}")
    print(f"\nconsumer (sink) kinds of fusible values top-20:")
    for kind, count in sink_hist.most_common(20):
        print(f"  {kind:<18} {count:>9}")

    shares = sorted((per_part_fusible[p] / per_part_total[p]
                     for p in per_part_total if per_part_total[p] >= 8),
                    reverse=True)
    if shares:
        n = len(shares)
        print(f"\nper-supernode fusible share (n={n}, >=8 ops): "
              f"p50={shares[n // 2]:.3f} p90={shares[int(n * 0.9)]:.3f} "
              f"mean={sum(shares) / n:.3f}")

    top_tasks = sorted(task_fusible.items(), key=lambda kv: -kv[1][0])[:15]
    print(f"\ntop tasks by fusible count (task, fusible, compute_ops, share):")
    for tid, (f, c) in top_tasks:
        print(f"  task_{tid} fusible={f} ops={c} share={f / max(c, 1):.3f}")

    log(f"[done] total {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
