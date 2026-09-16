"""Measure scalar storage and verify stable helper input caches in a CPU mapping."""

import argparse
from array import array
from collections import Counter
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    model = json.loads(args.model.read_bytes())
    strings, operations = model["strings"], model["operations"]
    values, types = model["values"], model["types"]
    mapping = model["mappings"][0][4]
    partitions, layout = mapping[2], mapping[3]
    slots = layout[3]
    names = [strings[op[1] - 1] for op in operations]
    constants = {v for op, name in zip(operations, names) if name == "core.compute.constant" for v in op[5]}
    scalar = {t[0] for t in types if t[2] == "logic" and 0 < t[3] <= 64 and t[5] == "2-state"}
    if not scalar:
        raise ValueError("no scalar two-state types; check the input schema")
    candidates, duplicates, duplicate_storage = Counter(), Counter(), Counter()
    local, local_bytes = Counter(), Counter()
    helpers = 0
    read_caches = []
    cached_uses = 0
    op_helpers = array("I", [0]) * (len(operations) + 1)
    value_helpers = array("I", [0]) * (len(values) + 1)
    for partition in partitions:
        if partition[2] != 3 or not partition[4]:
            continue
        ids = [op for child in partition[4] for op in partitions[child - 1][5]]
        chunks = partition[7][2] if len(partition) > 7 else []
        for begin, count in chunks or [(0, len(ids))]:
            helpers += 1
            seen = {}
            group = ids[begin:begin + count]
            uses = Counter(v for op_id in group for v in operations[op_id - 1][4])
            produced = {v for op_id in group for v in operations[op_id - 1][5]}
            cached = [v for v, n in sorted(uses.items()) if n > 1 and v not in produced and
                      v not in constants and slots[v - 1][1] == 2 and values[v - 1][1] in scalar]
            if cached:
                read_caches.append([group[0], cached])
                cached_uses += sum(uses[v] for v in cached)
            for op_id in group:
                op = operations[op_id - 1]
                op_helpers[op_id] = helpers
                for value in op[5]:
                    value_helpers[value] = helpers
                name = names[op_id - 1]
                if not name.startswith("core.compute.") or len(op[5]) != 1:
                    continue
                value = op[5][0]
                type_id = values[value - 1][1]
                if type_id not in scalar:
                    continue
                slot = slots[value - 1]
                if slot[1] == 1:
                    local[name] += 1
                    # CPU type row: id, kind, width, element, count, size, alignment.
                    local_bytes[name] += layout[1][slot[0] - 1][5]
                if op[6] or op[7]:
                    continue
                key = (op[1], type_id, tuple(op[4]))
                candidates[name] += 1
                if key in seen:
                    duplicates[name] += 1
                    duplicate_storage[str(slot[1])] += 1
                else:
                    seen[key] = value
    if len(layout) > 10:
        raise ValueError("unexpected CPU layout extension")
    if len(layout) > 9 and layout[9] != read_caches:
        raise ValueError("serialized read cache plan differs from helper input reconstruction")
    escapes = bytearray(len(values) + 1)
    for op in operations:
        for operand in op[4]:
            if value_helpers[operand] != op_helpers[op[0]]:
                escapes[operand] = 1
    locals_plan = []
    for op, name in zip(operations, names):
        if (not name.startswith("core.compute.") or name == "core.compute.constant" or
                len(op[5]) != 1 or op[6]):
            continue
        value = op[5][0]
        if (value_helpers[value] and not escapes[value] and slots[value - 1][1] == 1 and
                values[value - 1][1] in scalar):
            locals_plan.append(value)
    result = {
        "operations": len(operations), "values": len(values), "helpers": helpers,
        "exact_candidates": candidates, "exact_reuses": duplicates,
        "exact_reuse_count": sum(duplicates.values()), "duplicate_storage": duplicate_storage,
        "scalar_partition_local": local, "scalar_partition_local_bytes": local_bytes,
        "helper_scalar_local_count": len(locals_plan),
        "read_cache_helpers": len(read_caches), "read_cache_values": sum(len(row[1]) for row in read_caches),
        "read_cache_operand_uses": cached_uses, "serialized_read_cache_plan_verified": len(layout) > 9,
        "note": "String IDs are one-based; keys include result type and ordered operands. "
                "No object references or parameters are eligible for exact reuse. "
                "Counts are static, not executed operations."
    }
    if args.reference:
        reference = json.loads(args.reference.read_bytes())
        if model.keys() != reference.keys() or len(model["mappings"]) != 1 or len(reference["mappings"]) != 1:
            raise ValueError("reference sections or mapping count differ")
        for key in model:
            if key != "mappings" and model[key] != reference[key]:
                raise ValueError(f"semantic section differs: {key}")
        before, after = reference["mappings"][0], model["mappings"][0]
        if before[:4] != after[:4] or before[4][:3] != after[4][:3] or before[4][4:] != after[4][4:]:
            raise ValueError("mapping metadata, partitions or schedule differ")
        if before[4][3][:9] != after[4][3][:9]:
            raise ValueError("storage layout changed")
        result["reference_comparison"] = "all semantic sections, partitions, storage and schedule identical; computation plans are the only extension"
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
