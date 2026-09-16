"""Audit task-level boundary read caching: values re-read across supernodes of one task."""

import argparse
from array import array
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys


SN_LINE = re.compile(r"^\[grhsim-dyn] sn (\d+) act=(\d+) body=(\d+) grp=(\d+) chg=(\d+)$")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--log", type=Path, help="optional [grhsim-dyn] dump for activation weighting")
    args = parser.parse_args()
    model = json.loads(args.model.read_bytes())
    ops, values, strings = model["operations"], model["values"], model["strings"]
    payload = model["mappings"][0][-1]
    partitions = payload[2]
    value_slots = payload[3][3]
    schedule = payload[4]

    activations = {}
    if args.log:
        for line in args.log.read_text(errors="replace").splitlines():
            if match := SN_LINE.match(line):
                activations[int(match[1])] = int(match[2])

    by_id = {part[0]: part for part in partitions}
    parent = {part[0]: part[1] for part in partitions}

    def supernode_of(part_id):
        root = part_id
        while parent.get(root) and by_id[root][2] != 3:
            root = parent[root]
        return root

    # op -> owning supernode, and supernode -> owning emit_function partition (kind 6)
    op_super = {}
    for part in partitions:
        if not part[5]:
            continue
        root = supernode_of(part[0])
        for op_id in part[5]:
            op_super[op_id] = root

    def function_of(super_id):
        root = super_id
        while parent.get(root) and by_id[root][2] != 6:
            root = parent[root]
        return root if by_id[root][2] == 6 else 0

    producer = array("I", [0]) * (len(values) + 1)
    for op in ops:
        for value in op[5]:
            producer[value] = op[0]

    # readers per boundary value, grouped by (value, task)
    readers = defaultdict(list)
    for op in ops:
        super_id = op_super.get(op[0])
        if super_id is None or not op[4]:
            continue
        name = strings[op[1] - 1]
        if name.startswith("core.state.") or name.startswith("core.dpi") or name.startswith("core.system"):
            continue
        for operand in set(op[4]):
            if value_slots[operand - 1][1] != 2:
                continue
            readers[operand].append(super_id)

    stats = Counter()
    dyn_saved = Counter()
    for value, supers in readers.items():
        by_task = defaultdict(set)
        for super_id in supers:
            by_task[function_of(super_id)].add(super_id)
        prod = producer[value]
        prod_task = function_of(op_super.get(prod, 0)) if prod else 0
        for task, reader_set in by_task.items():
            if len(reader_set) < 2:
                continue
            stats["value_task_pairs"] += 1
            stats["extra_reads"] += len(reader_set) - 1
            if prod_task != task:
                stats["external_pairs"] += 1
                stats["external_extra_reads"] += len(reader_set) - 1
                if activations:
                    dyn_saved[task] += sum(activations.get(sn, 0) for sn in sorted(reader_set)[1:])
    print(f"values with cross-supernode reads in one task: {stats['value_task_pairs']}")
    print(f"extra reads (beyond first supernode): {stats['extra_reads']}")
    print(f"external-producer pairs: {stats['external_pairs']}, extra reads: {stats['external_extra_reads']}")
    if activations:
        total = sum(dyn_saved.values())
        print(f"dynamic extra reads (activation-weighted): {total}")
        print(f"per eval: {total / 200102:.1f}")


if __name__ == "__main__":
    main()
