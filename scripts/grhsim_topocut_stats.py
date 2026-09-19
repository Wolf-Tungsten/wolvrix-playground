#!/usr/bin/env python3
"""Topological-cut census for single-pass (fixed-point-free) evaluation feasibility.

Answers four questions on a mapped GrhSIM checkpoint (xiangshan_grhsim_ir.json):

  Q1 acyclicity: is the value-dependence graph, cut at state elements, a DAG?
     Kahn peeling leaves a cyclic remainder; Tarjan SCCs decompose it.
  Q2 state depth: with write->read forwarding edges across the clock edge, how
     many commit crossings does the task graph need (the static round count)?
  Q3 wave eligibility: which tasks are reachable in wave 0 (seeds, pre-edge),
     wave 1 (commit-fanout closure, post-edge), or both (duplication cost)?
  Q4 escape hatches: mixed read/write memory arrays, side-effect ops,
     multi-event structure, four-state values.

The model JSON op layout is [id, opType, name, origin, operands, results,
objectRefs, parameters]; objectRefs are [kind, index] pairs.
"""

import argparse
from array import array
from collections import Counter, defaultdict, deque
import json
import sys
import time


STATE_READ = "core.state.read"
MEM_READ = "core.state.memRead"
WRITE_OPS = {
    "core.state.regWrite", "core.state.latchWrite", "core.state.memWrite",
    "core.state.memWriteSeq", "core.state.memFill", "core.state.memAssign",
}
SIDE_EFFECT_OPS = {
    "core.dpi.call", "core.system.task", "core.system.function", "core.output.write",
}
INPUT_READ = "core.input.read"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True, help="mapped xiangshan_grhsim_ir.json")
    ap.add_argument("--scc-limit", type=int, default=200000,
                    help="skip Tarjan when the cyclic remainder exceeds this size")
    args = ap.parse_args()

    t0 = time.time()
    with open(args.model, "rb") as fh:
        model = json.load(fh)
    log(f"[load] {time.time() - t0:.1f}s")

    strings = model["strings"]
    types = {t[0]: t for t in model["types"]}
    values = model["values"]
    states = model["states"]
    ops = model["operations"]
    n_ops = len(ops)
    n_values = len(values)

    payload = model["mappings"][0][-1]
    partitions = {p[0]: p for p in payload[2]}
    value_slots = payload[3][3]
    schedule = payload[4]

    name_of = [0] * (n_ops + 1)
    operands_of = [None] * (n_ops + 1)
    results_of = [None] * (n_ops + 1)
    objrefs_of = [None] * (n_ops + 1)
    for index, op in enumerate(ops):
        ordinal = index + 1
        name_of[ordinal] = op[1]
        operands_of[ordinal] = op[4]
        results_of[ordinal] = op[5]
        objrefs_of[ordinal] = op[6]

    def text(string_id):
        return strings[string_id - 1] if string_id else "<none>"

    # ---- schema probe: one sample per interesting kind ----
    seen_kinds = set()
    for index, op in enumerate(ops):
        kind = text(op[1])
        if kind in seen_kinds:
            continue
        if kind in (STATE_READ, MEM_READ) or kind in WRITE_OPS or kind in SIDE_EFFECT_OPS \
                or kind == INPUT_READ:
            log(f"[sample] {kind}: op={op}")
            seen_kinds.add(kind)
    for kind in (STATE_READ, MEM_READ, "core.state.regWrite", "core.state.memWrite",
                 "core.dpi.call", "core.output.write", INPUT_READ):
        if kind not in seen_kinds:
            log(f"[sample] MISSING kind {kind}")

    producer = array("i", bytes(4 * (n_values + 1)))
    for index in range(n_ops):
        for v in results_of[index + 1]:
            producer[v] = index + 1

    # ===================================================== Q1: op-level acyclicity
    t1 = time.time()
    indeg = array("i", bytes(4 * (n_ops + 1)))
    outdeg = array("i", bytes(4 * (n_ops + 1)))
    n_edges = 0
    for ordinal in range(1, n_ops + 1):
        for v in operands_of[ordinal]:
            p = producer[v]
            if p:
                indeg[ordinal] += 1
                outdeg[p] += 1
                n_edges += 1
    offsets = array("i", bytes(4 * (n_ops + 2)))
    acc = 0
    for ordinal in range(1, n_ops + 1):
        offsets[ordinal] = acc
        acc += outdeg[ordinal]
    offsets[n_ops + 1] = acc
    adj = array("i", bytes(4 * n_edges))
    cursor = array("i", offsets[:-1])
    for ordinal in range(1, n_ops + 1):
        for v in operands_of[ordinal]:
            p = producer[v]
            if p:
                adj[cursor[p]] = ordinal
                cursor[p] += 1
    log(f"[graph] ops={n_ops} edges={n_edges} build={time.time() - t1:.1f}s")

    t2 = time.time()
    remaining = array("i", indeg)
    queue = deque(ordinal for ordinal in range(1, n_ops + 1) if remaining[ordinal] == 0)
    processed = 0
    depth = array("i", bytes(4 * (n_ops + 1)))
    max_depth = 0
    while queue:
        node = queue.popleft()
        processed += 1
        d = depth[node] + 1
        for i in range(offsets[node], offsets[node + 1]):
            nxt = adj[i]
            if d > depth[nxt]:
                depth[nxt] = d
                if d > max_depth:
                    max_depth = d
            remaining[nxt] -= 1
            if remaining[nxt] == 0:
                queue.append(nxt)
    leftover = n_ops - processed
    print(f"\n== Q1 op-level acyclicity ==")
    print(f"ops={n_ops} value_edges={n_edges} kahn_processed={processed} "
          f"leftover={leftover} ({100.0 * leftover / n_ops:.4f}%) dag_max_depth={max_depth}")
    log(f"[kahn] {time.time() - t2:.1f}s")

    if 0 < leftover <= args.scc_limit:
        t3 = time.time()
        leftover_set = bytearray(n_ops + 1)
        for ordinal in range(1, n_ops + 1):
            if remaining[ordinal] > 0:
                leftover_set[ordinal] = 1
        # Iterative Tarjan on the leftover-induced subgraph.
        index_of = array("i", bytes(4 * (n_ops + 1)))
        lowlink = array("i", bytes(4 * (n_ops + 1)))
        on_stack = bytearray(n_ops + 1)
        counter = [0]
        stack = []
        sccs = []
        for root in range(1, n_ops + 1):
            if not leftover_set[root] or index_of[root]:
                continue
            work = [(root, offsets[root])]
            while work:
                node, ci = work[-1]
                if ci == offsets[node]:
                    counter[0] += 1
                    index_of[node] = lowlink[node] = counter[0]
                    stack.append(node)
                    on_stack[node] = 1
                recursed = False
                end = offsets[node + 1]
                while ci < end:
                    nxt = adj[ci]
                    ci += 1
                    if not leftover_set[nxt]:
                        continue
                    if not index_of[nxt]:
                        work[-1] = (node, ci)
                        work.append((nxt, offsets[nxt]))
                        recursed = True
                        break
                    if on_stack[nxt] and index_of[nxt] < lowlink[node]:
                        lowlink[node] = index_of[nxt]
                if recursed:
                    continue
                work.pop()
                if work and lowlink[node] < lowlink[work[-1][0]]:
                    lowlink[work[-1][0]] = lowlink[node]
                if lowlink[node] == index_of[node]:
                    scc = []
                    while True:
                        member = stack.pop()
                        on_stack[member] = 0
                        scc.append(member)
                        if member == node:
                            break
                    if len(scc) > 1:
                        sccs.append(scc)
        sccs.sort(key=len, reverse=True)
        size_hist = Counter()
        for scc in sccs:
            size_hist[min(len(scc), 10)] += 1
        print(f"cyclic remainder sccs(>1)={len(sccs)} size_hist(clipped@10)="
              f"{dict(sorted(size_hist.items()))}")
        for rank, scc in enumerate(sccs[:10]):
            kinds = Counter(text(name_of[m]) for m in scc)
            print(f"  scc#{rank} size={len(scc)} kinds={dict(kinds.most_common(8))}")
        log(f"[tarjan] {time.time() - t3:.1f}s")
    elif leftover:
        kinds = Counter()
        for ordinal in range(1, n_ops + 1):
            if remaining[ordinal] > 0:
                kinds[text(name_of[ordinal])] += 1
        print(f"cyclic remainder too large for Tarjan ({leftover} > {args.scc_limit}); "
              f"kinds={dict(kinds.most_common(15))}")

    # ===================================================== state structure (Q4a)
    state_readers = defaultdict(int)
    state_writers = defaultdict(Counter)
    state_memreaders = defaultdict(int)
    write_kind_totals = Counter()
    side_effect_totals = Counter()
    input_read_ops = []
    four_state_values = 0
    for value in values:
        t = types[value[1]]
        if t[5] != "2-state":
            four_state_values += 1
    for ordinal in range(1, n_ops + 1):
        kind = text(name_of[ordinal])
        if kind == STATE_READ:
            for ref in objrefs_of[ordinal]:
                if ref[0] == "state":
                    state_readers[ref[1]] += 1
        elif kind == MEM_READ:
            for ref in objrefs_of[ordinal]:
                if ref[0] == "state":
                    state_memreaders[ref[1]] += 1
        elif kind in WRITE_OPS:
            write_kind_totals[kind] += 1
            for ref in objrefs_of[ordinal]:
                if ref[0] == "state":
                    state_writers[ref[1]][kind] += 1
        elif kind in SIDE_EFFECT_OPS:
            side_effect_totals[kind] += 1
        elif kind == INPUT_READ:
            input_read_ops.append(ordinal)

    mixed_arrays = [sid for sid in state_memreaders if sid in state_writers]
    multi_writer_states = [sid for sid, kinds in state_writers.items()
                           if sum(kinds.values()) > 1]
    print(f"\n== state structure ==")
    print(f"states={len(states)} read_by_state_read={len(state_readers)} "
          f"written={len(state_writers)} memread={len(state_memreaders)}")
    print(f"write ops by kind: {dict(write_kind_totals.most_common())}")
    print(f"side-effect ops by kind: {dict(side_effect_totals.most_common())}")
    print(f"input.read ops={len(input_read_ops)} four_state_values={four_state_values} "
          f"({100.0 * four_state_values / max(n_values, 1):.2f}%)")
    print(f"mixed mem arrays (memRead + writer)={len(mixed_arrays)} "
          f"memRead ops on them={sum(state_memreaders[s] for s in mixed_arrays)}")
    print(f"states with >1 write op={len(multi_writer_states)}")

    # ---- write-op event structure: parameter name histogram ----
    param_names = Counter()
    event_values = Counter()
    for index, op in enumerate(ops):
        kind = text(op[1])
        if kind not in WRITE_OPS:
            continue
        for entry in op[7]:
            if len(entry) == 3:
                pname = text(entry[0])
                param_names[(kind.split(".")[-1], pname)] += 1
                if pname in ("event", "edge"):
                    event_values[entry[2]] += 1
    print(f"write-op parameter names: {dict(param_names.most_common(12))}")
    if event_values:
        print(f"distinct event parameter values={len(event_values)} "
              f"top={event_values.most_common(6)}")

    # ===================================================== task graph (Q2/Q3)
    t4 = time.time()
    tasks = []
    for numa in schedule[0]:
        for core in numa[1]:
            tasks.extend(core[1])
    task_ids = {task[0] for task in tasks}
    task_partition = {task[0]: task[1] for task in tasks}
    print(f"\n== task graph ==\ntasks={len(tasks)}")

    op_task = array("i", bytes(4 * (n_ops + 1)))
    part_task = {}              # partition id -> owning task (subtree containment)

    def subtree_ops(root):
        stack = [root]
        while stack:
            part = partitions[stack.pop()]
            for op_id in part[5]:
                yield op_id
            stack.extend(part[4])

    for task in tasks:
        stack = [task[1]]
        while stack:
            pid = stack.pop()
            part = partitions[pid]
            part_task[pid] = task[0]
            for op_id in part[5]:
                op_task[op_id] = task[0]
            stack.extend(part[4])
    unmapped_ops = n_ops - sum(1 for ordinal in range(1, n_ops + 1) if op_task[ordinal])
    print(f"ops not under any task subtree={unmapped_ops} "
          f"({100.0 * unmapped_ops / n_ops:.2f}% — helper/shared partitions)")

    boundary_value = bytearray(n_values + 1)
    for i, slot in enumerate(value_slots):
        if slot[1] == 2:
            boundary_value[i + 1] = 1

    task_edges = set()          # (src_task, dst_task) via value flow
    boundary_edges = set()      # subset where the crossing value is boundary
    for ordinal in range(1, n_ops + 1):
        dst = op_task[ordinal]
        if not dst:
            continue
        for v in operands_of[ordinal]:
            p = producer[v]
            if p:
                src = op_task[p]
                if src and src != dst:
                    task_edges.add((src, dst))
                    if boundary_value[v]:
                        boundary_edges.add((src, dst))

    # commit activation edges: state fanout -> activated tasks
    # rows are [state, [activate PartitionIds], [arm PartitionIds]]
    fanout = {}
    arm_rows = 0
    for row in schedule[3]:
        fanout[row[0]] = row[1]
        if len(row) > 2 and row[2]:
            arm_rows += 1
    sample_rows = list(fanout.items())[:2]
    log(f"[sample] fanout rows={sample_rows} arm_rows={arm_rows}")

    state_writer_tasks = defaultdict(set)
    for ordinal in range(1, n_ops + 1):
        if text(name_of[ordinal]) not in WRITE_OPS:
            continue
        task_id = op_task[ordinal]
        if not task_id:
            continue
        for ref in objrefs_of[ordinal]:
            if ref[0] == "state":
                state_writer_tasks[ref[1]].add(task_id)

    def as_task(ref):
        return part_task.get(ref)

    activation_edges = set()
    unresolved = 0
    for sid, activate in fanout.items():
        writers = state_writer_tasks.get(sid)
        if not writers:
            continue
        for entry in activate:
            target = entry[0] if isinstance(entry, list) else entry
            dst = as_task(target)
            if dst is None:
                unresolved += 1
                continue
            for src in writers:
                if src != dst:
                    activation_edges.add((src, dst))
    log(f"[taskgraph] value_edges={len(task_edges)} boundary_edges={len(boundary_edges)} "
        f"activation_edges={len(activation_edges)} unresolved_fanout={unresolved} "
        f"({time.time() - t4:.1f}s)")

    succ = defaultdict(set)
    for src, dst in task_edges:
        succ[src].add(dst)
    act_succ = defaultdict(set)
    for src, dst in activation_edges:
        act_succ[src].add(dst)

    # task classification
    task_has_write = defaultdict(bool)
    task_has_side = defaultdict(bool)
    task_has_input = defaultdict(bool)
    task_ops = Counter()
    for ordinal in range(1, n_ops + 1):
        task_id = op_task[ordinal]
        if not task_id:
            continue
        task_ops[task_id] += 1
        kind = text(name_of[ordinal])
        if kind in WRITE_OPS:
            task_has_write[task_id] = True
        elif kind in SIDE_EFFECT_OPS:
            task_has_side[task_id] = True
        elif kind == INPUT_READ:
            task_has_input[task_id] = True

    commit_tasks = {t for t in task_ids if task_has_write[t]}
    system_tasks = {t for t in task_ids if task_has_side[t]}
    seeds = {t for t in task_ids if task_has_input[t]} | commit_tasks | system_tasks

    def closure(start, extra_succ=None):
        seen = set(start)
        queue = deque(start)
        while queue:
            node = queue.popleft()
            for nxt in succ.get(node, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return seen

    # wave 0: seeds + value-flow closure (commit tasks included as wave-0 actors)
    wave0 = closure(seeds)
    # wave 1: commit-fanout targets + value-flow closure (single commit crossing)
    wave1_starts = set()
    for src, dst in activation_edges:
        wave1_starts.add(dst)
    wave1 = closure(wave1_starts)
    # wave >=2: needs a second commit crossing (commit task inside wave1 firing again)
    wave2_starts = set()
    for src, dst in activation_edges:
        if src in wave1:
            wave2_starts.add(dst)
    wave2 = closure(wave2_starts) - wave1 - wave0

    both = wave0 & wave1
    only0 = wave0 - wave1
    only1 = wave1 - wave0

    def op_share(task_set):
        return sum(task_ops[t] for t in task_set)

    compute_tasks = task_ids - commit_tasks - system_tasks
    total_compute_ops = op_share(compute_tasks)
    print(f"commit_tasks={len(commit_tasks)} system_tasks={len(system_tasks)} "
          f"compute_tasks={len(compute_tasks)} seed_tasks={len(seeds)}")
    print(f"wave0 tasks={len(wave0)} ops={op_share(wave0)}")
    print(f"wave1 tasks={len(wave1)} ops={op_share(wave1)}")
    print(f"wave>=2-only tasks={len(wave2)} ops={op_share(wave2)} "
          f"(structural round-2+ residue)")
    print(f"wave0-only={len(only0)} wave1-only={len(only1)} both={len(both)}")
    cb = op_share(both & compute_tasks)
    c0 = op_share(only0 & compute_tasks)
    c1 = op_share(only1 & compute_tasks)
    print(f"compute op shares: wave0-only={c0} ({100.0 * c0 / max(total_compute_ops, 1):.2f}%) "
          f"wave1-only={c1} ({100.0 * c1 / max(total_compute_ops, 1):.2f}%) "
          f"both={cb} ({100.0 * cb / max(total_compute_ops, 1):.2f}%); "
          f"unroll text multiplier={1.0 + cb / max(total_compute_ops, 1):.3f}x")

    # commit tasks whose inputs are wave-1 (fire in round 1 -> round-2 source)
    commit_in_wave1 = commit_tasks & wave1
    print(f"commit tasks inside wave1 closure={len(commit_in_wave1)} "
          f"(candidates for second register wave)")

    # escape hatches inside wave closures
    mixed_set = set(mixed_arrays)
    memread_wave = Counter()
    for ordinal in range(1, n_ops + 1):
        if text(name_of[ordinal]) != MEM_READ:
            continue
        sids = [ref[1] for ref in objrefs_of[ordinal] if ref[0] == "state"]
        if not any(s in mixed_set for s in sids):
            continue
        task_id = op_task[ordinal]
        bucket = ("both" if task_id in both else
                  "wave0" if task_id in only0 else
                  "wave1" if task_id in only1 else "none")
        memread_wave[bucket] += 1
    print(f"memRead ops on mixed arrays by wave: {dict(memread_wave.most_common())}")
    side_wave = Counter()
    for ordinal in range(1, n_ops + 1):
        if text(name_of[ordinal]) not in SIDE_EFFECT_OPS:
            continue
        task_id = op_task[ordinal]
        bucket = ("both" if task_id in both else
                  "wave0" if task_id in only0 else
                  "wave1" if task_id in only1 else "none")
        side_wave[bucket] += 1
    print(f"side-effect ops by wave: {dict(side_wave.most_common())}")

    # longest boundary-edge chain (proxy for intra-wave dataflow depth)
    print(f"\n[census done] total {time.time() - t0:.1f}s")


def log(msg):
    print(msg, file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
