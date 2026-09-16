"""Audit bitwise lane fusion: per-bit ops whose operands are aligned slices of common sources."""

import argparse
from array import array
from collections import Counter, defaultdict
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    model = json.loads(args.model.read_bytes())
    ops, values, types, strings = model["operations"], model["values"], model["types"], model["strings"]
    width = {t[0]: (t[3] if t[2] == "logic" else None) for t in types}
    bit_types = {t[0] for t in types if t[2] == "logic" and t[3] == 1 and not t[4] and t[5] == "2-state"}

    producer = array("I", [0]) * (len(values) + 1)
    uses = array("I", [0]) * (len(values) + 1)
    for op in ops:
        for value in op[5]:
            producer[value] = op[0]
        for value in op[4]:
            uses[value] += 1

    def name_of(op_id):
        return strings[ops[op_id - 1][1] - 1]

    def int_params(op_id):
        result = {}
        for entry in ops[op_id - 1][7]:
            if len(entry) == 3 and entry[1] == "int":
                result[strings[entry[0] - 1]] = entry[2]
        return result

    # value -> (source value, bit position) for 1-bit slices
    slice_of = {}
    for op in ops:
        if strings[op[1] - 1] != "core.compute.sliceStatic" or len(op[4]) != 1 or len(op[5]) != 1:
            continue
        result = op[5][0]
        if values[result - 1][1] not in bit_types:
            continue
        params = int_params(op[0])
        start, end = params.get("sliceStart"), params.get("sliceEnd")
        if start is None or end != start:
            continue
        slice_of[result] = (op[4][0], start)

    stats = Counter()
    # group 1-bit and/or/xor ops by (kind, source0, source1, pos) pattern
    lane_groups = defaultdict(list)
    for op in ops:
        name = strings[op[1] - 1]
        if name not in ("core.compute.and", "core.compute.or", "core.compute.xor"):
            continue
        if len(op[4]) != 2 or len(op[5]) != 1:
            continue
        if values[op[5][0] - 1][1] not in bit_types:
            continue
        stats["bit_binary_ops"] += 1
        s0 = slice_of.get(op[4][0])
        s1 = slice_of.get(op[4][1])
        if not s0 or not s1 or s0[1] != s1[1]:
            continue
        stats["aligned_slice_operands"] += 1
        lane_groups[(name, s0[0], s1[0])].append((s0[1], op[0]))
    fusible_ops = 0
    fusible_groups = 0
    for key, lanes in lane_groups.items():
        positions = sorted(lanes)
        run = 1
        for i in range(1, len(positions)):
            if positions[i][0] == positions[i - 1][0] + 1:
                run += 1
                continue
            if run >= 2:
                fusible_groups += 1
                fusible_ops += run
            run = 1
        if run >= 2:
            fusible_groups += 1
            fusible_ops += run
    # fix trailing run
    stats["fusible_lane_groups"] = fusible_groups
    stats["fusible_lane_ops"] = fusible_ops
    for key, count in stats.most_common():
        print(f"{count:>10} {key}")


if __name__ == "__main__":
    main()
