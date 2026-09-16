"""Audit slice-chain reduction opportunities: slice-of-concat, nested slices, identity reassembly."""

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
    ops, values, types, strings = model["operations"], model["values"], model["types"], model["strings"]
    type_of = {t[0]: t for t in types}
    width = {t[0]: (t[3] if t[2] == "logic" else None) for t in types}

    producer = array("I", [0]) * (len(values) + 1)
    uses = array("I", [0]) * (len(values) + 1)
    for op in ops:
        for value in op[5]:
            producer[value] = op[0]
        for value in op[4]:
            uses[value] += 1

    def op_name(op_id):
        return strings[ops[op_id - 1][1] - 1]

    def params_of(op_id):
        result = {}
        for entry in ops[op_id - 1][7]:
            if len(entry) == 3 and entry[1] == "int":
                result[strings[entry[0] - 1]] = entry[2]
        return result

    stats = Counter()
    for op in ops:
        name = strings[op[1] - 1]
        if name != "core.compute.sliceStatic" or len(op[4]) != 1 or len(op[5]) != 1:
            continue
        stats["sliceStatic"] += 1
        params = params_of(op[0])
        start, end = params.get("sliceStart"), params.get("sliceEnd")
        if start is None or end is None:
            continue
        source = op[4][0]
        src_op = ops[producer[source] - 1]
        src_name = op_name(src_op[0])
        if src_name == "core.compute.sliceStatic" and len(src_op[4]) == 1:
            inner = params_of(src_op[0])
            if inner.get("sliceStart") is not None:
                stats["nested_slice"] += 1
        if src_name != "core.compute.concat" or len(src_op[5]) != 1:
            continue
        stats["slice_of_concat"] += 1
        lanes = src_op[4]
        offset = 0
        lane_ranges = []
        for lane in reversed(lanes):  # concat operands: first operand is the most significant
            lw = width[values[lane - 1][1]]
            lane_ranges.append((offset, offset + lw - 1, lane))
            offset += lw
        for lo, hi, lane in lane_ranges:
            if lo <= start and end <= hi and uses[source] == 1:
                lane_width = hi - lo + 1
                if start == lo and end == hi:
                    stats["slice_of_concat_exact_lane"] += 1
                else:
                    stats["slice_of_concat_sub_lane"] += 1
                break
    for key, count in stats.most_common():
        print(f"{count:>10} {key}")


if __name__ == "__main__":
    main()
