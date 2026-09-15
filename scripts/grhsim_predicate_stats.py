"""Count logical predicates whose complete type makes them bitwise operations."""

import argparse
from collections import Counter
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    model = json.loads(args.model.read_bytes())
    strings, types, values = model["strings"], model["types"], model["values"]
    bits = {t[0] for t in types if t[2] == "logic" and t[3:6] == [1, False, "2-state"]}
    names = {"core.compute.logicAnd", "core.compute.logicOr", "core.compute.logicNot"}
    total, eligible, boundary = Counter(), Counter(), Counter()
    slots = model["mappings"][0][4][3][3]
    for op in model["operations"]:
        name = strings[op[1] - 1]
        if name not in names:
            continue
        total[name] += 1
        arity = 1 if name == "core.compute.logicNot" else 2
        if (not op[6] and not op[7] and len(op[4]) == arity and len(op[5]) == 1 and
                all(values[v - 1][1] in bits for v in op[4] + op[5])):
            eligible[name] += 1
            boundary[name] += slots[op[5][0] - 1][1] == 2
    result = {"total": total, "unsigned_one_bit": eligible, "boundary": boundary}
    if args.reference:
        reference = json.loads(args.reference.read_bytes())
        if model.keys() != reference.keys():
            raise ValueError("model sections differ")
        if len(reference["operations"]) != len(model["operations"]):
            raise ValueError("operation count differs")
        identical = []
        for key in model:
            if key == "operations":
                continue
            if model[key] != reference[key]:
                raise ValueError(f"unexpected difference in {key}")
            identical.append(key)
        changes = Counter()
        for old, new in zip(reference["operations"], model["operations"]):
            if old == new:
                continue
            before, after = strings[old[1] - 1], strings[new[1] - 1]
            if before not in ("core.compute.logicAnd", "core.compute.logicOr") or after != {
                    "core.compute.logicAnd": "core.compute.and", "core.compute.logicOr": "core.compute.or"}[before]:
                raise ValueError("unexpected operation change")
            if old[:1] + old[2:] != new[:1] + new[2:]:
                raise ValueError("operation changed more than opcode")
            if new[6] or new[7] or len(new[4]) != 2 or len(new[5]) != 1:
                raise ValueError("opcode changed on an ineligible operation")
            if any(values[v - 1][1] not in bits for v in new[4] + new[5]):
                raise ValueError("opcode changed on a non-Boolean value")
            changes[f"{before}->{after}"] += 1
        result.update(identical_sections=identical, opcode_changes=changes)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
