"""Audit residual algebraic reductions: self-inverse ops, complement pairs, absorption, double negation."""

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

    producer = array("I", [0]) * (len(values) + 1)
    uses = array("I", [0]) * (len(values) + 1)
    for op in ops:
        for value in op[5]:
            producer[value] = op[0]
        for value in op[4]:
            uses[value] += 1

    def name_of(op_id):
        return strings[ops[op_id - 1][1] - 1]

    stats = Counter()
    for op in ops:
        name = strings[op[1] - 1]
        operands = op[4]
        if len(op[5]) != 1 or not operands:
            continue
        if len(operands) == 2 and operands[0] == operands[1] and name in (
                "core.compute.xor", "core.compute.sub", "core.compute.ne", "core.compute.lt",
                "core.compute.gt", "core.compute.eq", "core.compute.le", "core.compute.ge",
                "core.compute.xnor"):
            stats["self_op:" + name] += 1
        if name == "core.compute.not" and producer[operands[0]]:
            inner = ops[producer[operands[0]] - 1]
            if name_of(inner[0]) == "core.compute.not" and len(inner[4]) == 1:
                stats["double_not"] += 1
        if name in ("core.compute.and", "core.compute.or", "core.compute.xor") and len(operands) == 2:
            for other in operands:
                src = producer[other]
                if not src:
                    continue
                inner = ops[src - 1]
                inner_name = name_of(inner[0])
                if name == "core.compute.xor" and inner_name == name:
                    shared = set(operands) & set(inner[4])
                    if shared and len(inner[4]) == 2:
                        stats["xor_self_cancel_chain"] += 1
                    continue
                if inner_name != name or len(inner[4]) != 2:
                    continue
                shared = set(operands) & set(inner[4])
                if shared:
                    stats["absorption:" + name] += 1
        if name in ("core.compute.and", "core.compute.or") and len(operands) == 2:
            kinds = {}
            for operand in operands:
                src = producer[operand]
                if src:
                    inner = ops[src - 1]
                    inner_name = name_of(inner[0])
                    if inner_name in ("core.compute.not", "core.compute.logicNot") and len(inner[4]) == 1:
                        kinds[inner[4][0]] = operand
            base = set(operands)
            for inner_src, outer_op in kinds.items():
                if inner_src in base:
                    stats["complement_pair:" + name] += 1
    total = sum(stats.values())
    print(f"total residual candidates: {total}")
    for key, count in stats.most_common():
        print(f"{count:>10} {key}")


if __name__ == "__main__":
    main()
