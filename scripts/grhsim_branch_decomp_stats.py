"""Measure branch-decomposition coverage of compute supernode bodies.

For each compute supernode, propagate branch tags backward through the value
DAG: a value used as a prioritySelect/bitSelect arm at position i is tagged
(P,i); a value that escapes the supernode (boundary writeback) or feeds a
condition position or any non-chain consumer is tagged HOIST. An op whose every
consumer carries the same single tag (P,i) belongs to that arm's branch: in a
layered if-else emission it would be evaluated only when arm i is taken.

Reports the share of compute ops that are branch-sinkable (exactly one tag)
versus hoisted (zero or multiple tags), per supernode and in total — the
dynamic ceiling of the layered if-else execution form.
"""

import argparse
from array import array
from collections import Counter
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    model = json.loads(args.model.read_bytes())
    ops, values, strings = model["operations"], model["values"], model["strings"]
    names = [strings[op[1] - 1] for op in ops]
    payload = model["mappings"][0][-1]
    partitions = {part[0]: part for part in payload[2]}
    value_slots = payload[3][3]

    producer = array("I", [0]) * (len(values) + 1)
    for op in ops:
        if op[5]:
            producer[op[5][0]] = op[0]

    op_sn = array("i", [0]) * (len(ops) + 1)
    sn_ops = {}
    sn_task = {}
    def collect(pid, phase, sn, task):
        part = partitions[pid]
        here = sn
        here_task = task
        if part[2] == 6:
            here_task = pid
        if part[2] == 3:
            here = pid if phase == 1 else -1
            if here > 0:
                sn_task[here] = here_task
        for op_id in part[5]:
            if here > 0:
                op_sn[op_id] = here
                sn_ops.setdefault(here, []).append(op_id)
        for child in part[4]:
            collect(child, phase, here, here_task)
    root = [part for part in partitions.values() if part[2] == 0][0]
    for child in root[4]:
        collect(child, partitions[child][3], 0, 0)

    stats = Counter()
    HOIST = 0  # tag id 0 = always evaluated

    # map (psel op id, arm operand position) -> tag id
    for sn, member_ops in sn_ops.items():
        member_set = set(member_ops)
        tag_of_value = {}  # value -> frozenset of tags (ints); {0} = hoist
        tags = {}
        next_tag = [1]

        def tag_for(psel_id, arm_pos):
            key = (psel_id, arm_pos)
            if key not in tags:
                tags[key] = next_tag[0]
                next_tag[0] += 1
            return tags[key]

        # reverse topological order: iterate member ops reversed by id
        # (ops ids do not guarantee order; do fixpoint instead)
        order = sorted(member_ops, reverse=True)
        # first pass: seed consumers outside the supernode
        for op_id in order:
            op = ops[op_id - 1]
            if not op[5]:
                continue
            result = op[5][0]
            tag_of_value[result] = {HOIST} if value_slots[result - 1][1] == 2 else set()
        for _ in range(64):
            changed = False
            for op_id in order:
                op = ops[op_id - 1]
                name = names[op_id - 1]
                if not op[5]:
                    continue
                result = op[5][0]
                acc = set(tag_of_value.get(result, set()))
                is_chain = name in ("core.compute.prioritySelect", "core.compute.bitSelect",
                                    "core.compute.mux")
                if is_chain:
                    if name == "core.compute.prioritySelect":
                        n = (len(op[4]) - 1) // 2
                        arm_operands = op[4][n:]
                        cond_operands = op[4][:n]
                    else:
                        arm_operands = op[4][1:]
                        cond_operands = op[4][:1]
                    for value in cond_operands:
                        if producer[value] and op_sn[producer[value]] == sn:
                            prev = tag_of_value.get(value, set())
                            new = prev | {HOIST}
                            if new != prev:
                                tag_of_value[value] = new
                                changed = True
                    for pos, value in enumerate(arm_operands):
                        if producer[value] and op_sn[producer[value]] == sn:
                            tag = tag_for(op_id, pos)
                            prev = tag_of_value.get(value, set())
                            new = prev | {tag}
                            if new != prev:
                                tag_of_value[value] = new
                                changed = True
                else:
                    my_tags = set(tag_of_value.get(result, set()))
                    for value in op[4]:
                        src = producer[value]
                        if src and op_sn[src] == sn:
                            prev = tag_of_value.get(value, set())
                            new = prev | my_tags
                            if new != prev:
                                tag_of_value[value] = new
                                changed = True
            if not changed:
                break
        sn_sink = 0
        for op_id in order:
            op = ops[op_id - 1]
            if not op[5]:
                stats["ops_noresult"] += 1
                continue
            result = op[5][0]
            tagset = tag_of_value.get(result, {HOIST})
            stats["ops_total"] += 1
            if tagset == {HOIST} or not tagset:
                stats["ops_hoist"] += 1
            elif len(tagset) == 1:
                stats["ops_sinkable"] += 1
                sn_sink += 1
            else:
                stats["ops_multitag"] += 1
        if sn_sink:
            task = sn_task.get(sn, 0)
            stats[f"task_{task}_sinkable"] += sn_sink

    print("== branch decomposition census ==")
    for key in sorted(stats):
        print(f"{stats[key]:10d}  {key}")
    total = stats["ops_total"]
    if total:
        print(f"sinkable_share={100.0 * stats['ops_sinkable'] / total:.2f}%")
        print(f"multitag_share={100.0 * stats['ops_multitag'] / total:.2f}%")
    print("== top tasks by sinkable ops ==")
    task_counts = [(key, stats[key]) for key in stats if key.startswith("task_")]
    for key, count in sorted(task_counts, key=lambda kv: -kv[1])[:12]:
        print(f"{count:10d}  {key}")


if __name__ == "__main__":
    main()
