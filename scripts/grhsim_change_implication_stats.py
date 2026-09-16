"""Audit bijective change-sharing candidates: boundary results whose change is implied by a same-group peer."""

import argparse
from collections import Counter
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    model = json.loads(args.model.read_bytes())
    ops, values, strings = model["operations"], model["values"], model["strings"]
    payload = model["mappings"][0][-1]
    partitions = payload[2]
    value_slots = payload[3][3]
    schedule = payload[4]

    fanout = {}
    for source, activates, arms in schedule[2]:
        fanout[source] = (tuple(sorted(activates)), tuple(sorted(arms)))

    by_id = {part[0]: part for part in partitions}
    parent = {part[0]: part[1] for part in partitions}
    owner = {}
    for part in partitions:
        if not part[5]:
            continue
        root = part[0]
        while parent.get(root) and by_id[parent[root]][2] != 3:
            root = parent[root]
        if parent.get(root) and by_id[parent[root]][2] == 3:
            root = parent[root]
        for op_id in part[5]:
            owner[op_id] = root
    producer = {}
    for op in ops:
        for value in op[5]:
            producer[value] = op[0]

    def is_boundary(value):
        return value_slots[value - 1][1] == 2

    def is_const(value):
        op = ops[producer[value] - 1]
        return strings[op[1] - 1] == "core.compute.constant"

    stats = Counter()
    examples = []
    for op in ops:
        name = strings[op[1] - 1]
        if name not in ("core.compute.not", "core.compute.xor", "core.compute.add", "core.compute.sub"):
            continue
        if len(op[5]) != 1:
            continue
        result = op[5][0]
        if not is_boundary(result):
            continue
        operands = op[4]
        if name == "core.compute.not":
            if len(operands) != 1:
                continue
            source = operands[0]
        else:
            if len(operands) != 2:
                continue
            if is_const(operands[0]):
                source = operands[1]
            elif is_const(operands[1]):
                source = operands[0]
            else:
                continue
        if not is_boundary(source):
            stats["source_not_boundary"] += 1
            continue
        src_op = producer[source]
        if owner.get(src_op) is None or owner.get(src_op) != owner.get(op[0]):
            stats["different_supernode"] += 1
            continue
        if fanout.get(source, ()) != fanout.get(result, ()):
            stats["different_fanout"] += 1
            continue
        stats[f"candidate_{name}"] += 1
        if len(examples) < 5:
            examples.append((op[0], name, source, result))
    total = sum(count for key, count in stats.items() if key.startswith("candidate_"))
    print(f"bijective change-sharing candidates: {total}")
    for key, count in stats.most_common():
        print(f"{count:>10} {key}")
    print("examples (op, kind, source, result):", examples)


if __name__ == "__main__":
    main()
