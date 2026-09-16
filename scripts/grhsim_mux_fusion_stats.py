"""Audit scalar mux opportunities and optionally verify bitSelect-only rewriting."""

import argparse
from array import array
from collections import Counter
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--reference", type=Path,
                        help="verify that only eligible bit mux opcodes differ from this baseline")
    args = parser.parse_args()
    model = json.loads(args.model.read_bytes())
    ops, values, types, strings = (model[k] for k in ("operations", "values", "types", "strings"))
    names = [strings[op[1] - 1] for op in ops]
    producer = array("I", [0]) * (len(values) + 1)
    uses = array("I", [0]) * (len(values) + 1)
    for op in ops:
        for value in op[5]:
            producer[value] = op[0]
        for value in op[4]:
            uses[value] += 1
    scalar = {t[0] for t in types if t[2] == "logic" and 0 < t[3] <= 64 and t[5] == "2-state"}
    width = {t[0]: t[3] for t in types if t[0] in scalar}

    def flatten(value, lanes, internals):
        op = ops[producer[value] - 1]
        if (names[op[0] - 1] == "core.compute.concat" and len(op[4]) >= 2 and uses[value] == 1 and
                len(op[5]) == 1 and not op[6] and not op[7] and
                values[value - 1][1] in scalar and
                all(values[v - 1][1] in scalar for v in op[4]) and
                sum(width[values[v - 1][1]] for v in op[4]) == width[values[value - 1][1]]):
            internals.append(op[0])
            for v in op[4]:
                flatten(v, lanes, internals)
        else:
            lanes.append(value)

    bit = {t[0] for t in types if t[0] in scalar and t[3] == 1 and not t[4]}
    mux_widths = Counter()
    bit_muxes = 0
    for op, name in zip(ops, names):
        if name != "core.compute.mux" or len(op[4]) != 3 or len(op[5]) != 1 or op[6] or op[7]:
            continue
        result_type = values[op[5][0] - 1][1]
        if result_type in scalar:
            mux_widths[str(width[result_type])] += 1
        if result_type in bit and all(values[v - 1][1] == result_type for v in op[4]):
            bit_muxes += 1
    counts, widths, examples = Counter(), Counter(), []
    covered = set()
    for op, name in zip(ops, names):
        if name != "core.compute.concat" or len(op[4]) < 2 or len(op[5]) != 1 or op[6] or op[7]:
            continue
        result = op[5][0]
        if values[result - 1][1] not in scalar:
            continue
        counts["scalar_concat"] += 1
        if (not all(values[v - 1][1] in scalar for v in op[4]) or
                sum(width[values[v - 1][1]] for v in op[4]) != width[values[result - 1][1]]):
            continue
        lanes, internals = [], []
        for v in op[4]:
            flatten(v, lanes, internals)
        selectors = []
        for value in lanes:
            child = ops[producer[value] - 1]
            valid = (names[child[0] - 1] == "core.compute.mux" and len(child[4]) == 3 and
                     len(child[5]) == 1 and not child[6] and not child[7] and
                     values[value - 1][1] in scalar and
                     all(values[v - 1][1] == values[value - 1][1] for v in child[4][1:]) and
                     values[child[4][0] - 1][1] in scalar)
            selectors.append(child[4][0] if valid and uses[value] == 1 else 0)
        if len(lanes) >= 2 and selectors[0] and len(set(selectors)) == 1:
            counts["full_same_selector_concats"] += 1
            counts["mux_lanes_with_nested_overlap"] += len(lanes)
            covered.update(producer[v] for v in lanes)
            widths[str(width[values[result - 1][1]])] += 1
            if len(examples) < 8:
                examples.append({"concat": op[0], "condition": selectors[0], "lanes": lanes,
                                 "width": width[values[result - 1][1]], "internal_concats": internals})
        run = 1
        for i in range(1, len(selectors)):
            if selectors[i] and selectors[i] == selectors[i - 1]:
                run += 1
            else:
                if run > 1:
                    counts["same_selector_runs"] += 1
                    counts["run_lanes_with_nested_overlap"] += run
                run = 1
        if run > 1:
            counts["same_selector_runs"] += 1
            counts["run_lanes_with_nested_overlap"] += run
    counts["unique_fully_fusible_muxes"] = len(covered)
    cpu = model["mappings"][0][4]
    schedule = cpu[4]
    tasks = [t for n in schedule[0] for c in n[1] for t in c[1]]
    comparison = None
    if args.reference:
        reference = json.loads(args.reference.read_bytes())
        if model.keys() != reference.keys():
            raise ValueError("reference sections differ")
        original_strings = reference["strings"]
        if strings != original_strings + ["core.compute.bitSelect"]:
            raise ValueError("expected only bitSelect appended to the original string table")
        for key in model:
            if key not in ("counts", "strings", "operations") and model[key] != reference[key]:
                raise ValueError(f"section changed: {key}")
        original_counts = dict(reference["counts"])
        original_counts["strings"] += 1
        if model["counts"] != original_counts:
            raise ValueError("unexpected table or pool count change")
        rewritten = 0
        for before, after in zip(reference["operations"], ops, strict=True):
            name = original_strings[before[1] - 1]
            result_type = values[before[5][0] - 1][1] if len(before[5]) == 1 else 0
            eligible = (name == "core.compute.mux" and len(before[4]) == 3 and
                        result_type in bit and not before[6] and not before[7] and
                        all(values[v - 1][1] == result_type for v in before[4]))
            if eligible:
                if (strings[after[1] - 1] != "core.compute.bitSelect" or
                        before[:1] != after[:1] or before[2:] != after[2:]):
                    raise ValueError(f"incorrect bit mux rewrite at op {before[0]}")
                rewritten += 1
            elif before != after:
                raise ValueError(f"unrelated operation changed at op {before[0]}")
        comparison = {"verified_bit_mux_rewrites": rewritten,
                      "unchanged": "all other semantic sections, op fields, pools, partitions, layout and schedule"}
    print(json.dumps({"counts": counts, "widths": widths, "examples": examples,
                      "scalar_mux_widths": mux_widths, "unsigned_bit_muxes": bit_muxes,
                      "task_execution_kinds": Counter(str(t[3]) for t in tasks),
                      "operations": len(ops), "operation_counts": Counter(names),
                      "states": len(model["states"]), "values": len(values),
                      "boundary_values": sum(slot[1] == 2 for slot in cpu[3][3]),
                      "object_bytes": cpu[3][6], "boundary_bytes": cpu[3][7],
                      "runtime_bytes": cpu[3][8],
                      "reference_comparison": comparison,
                      "note": "Static opportunities; nested roots overlap."}, indent=2))


if __name__ == "__main__":
    main()
