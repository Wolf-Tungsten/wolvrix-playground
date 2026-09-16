"""Summarize static op/value mix of a GrhSIM model, grouped by op kind and storage."""

import argparse
from collections import Counter
import json
from pathlib import Path


STORAGE_KINDS = ("object", "partition_local", "boundary")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True,
                        help="xiangshan_grhsim_ir.json with a complete cpu mapping")
    parser.add_argument("--top", type=int, default=40)
    args = parser.parse_args()
    model = json.loads(args.model.read_bytes())
    ops = model["operations"]
    values = model["values"]
    types = {t[0]: t for t in model["types"]}
    strings = model["strings"]

    mappings = model["mappings"]
    if len(mappings) != 1:
        raise ValueError(f"expected exactly one mapping, got {len(mappings)}")
    payload = mappings[0][-1]
    layout = payload[3]
    value_slots = layout[3]
    if len(value_slots) != len(values):
        raise ValueError("layout values do not densely cover model values")

    op_counts = Counter()
    width_by_op = {}
    result_storage = Counter()
    result_width = Counter()
    boundary_by_producer = Counter()
    for op in ops:
        name = strings[op[1] - 1]
        op_counts[name] += 1
        results = op[5]
        if not results:
            continue
        widths = width_by_op.setdefault(name, Counter())
        for value in results:
            value_type = values[value - 1][1]
            t = types[value_type]
            width = t[3] if t[2] == "logic" else 0
            widths[width] += 1
            slot = value_slots[value - 1]
            storage = STORAGE_KINDS[slot[1]] if slot[1] < len(STORAGE_KINDS) else str(slot[1])
            result_storage[(name, storage)] += 1
            if storage == "boundary":
                boundary_by_producer[name] += 1
                result_width[(name, width)] += 1

    total_ops = sum(op_counts.values())
    print(f"total_ops={total_ops} values={len(values)}")
    wide_total = sum(count for widths in width_by_op.values() for w, count in widths.items() if w > 64)
    narrow_total = sum(count for widths in width_by_op.values() for w, count in widths.items() if 0 < w <= 64)
    print(f"result widths: narrow(1..64)={narrow_total} wide(>64)={wide_total}")
    wide_detail = Counter()
    for name, widths in width_by_op.items():
        wide = sum(count for w, count in widths.items() if w > 64)
        if wide:
            wide_detail[name] = wide
    for name, count in wide_detail.most_common(15):
        print(f"{count:>10} wide {name}")
    print("\n== ops by kind (top %d) ==" % args.top)
    for name, count in op_counts.most_common(args.top):
        print(f"{count:>10} {100.0 * count / total_ops:7.3f}% {name}")
    print("\n== boundary results by producer kind (top %d) ==" % args.top)
    total_boundary = sum(boundary_by_producer.values())
    print(f"total_boundary_results={total_boundary}")
    for name, count in boundary_by_producer.most_common(args.top):
        print(f"{count:>10} {100.0 * count / max(total_boundary, 1):7.3f}% {name}")
    print("\n== result width histogram for selected ops ==")
    for name, _count in op_counts.most_common(args.top):
        widths = width_by_op.get(name)
        if not widths:
            continue
        common = ",".join(f"{w}:{c}" for w, c in sorted(widths.items())[:8])
        print(f"{name}: {common}")

    partitions = payload[2]
    frames = payload[3][4]
    if frames:
        frame_sizes = sorted(f[1] for f in frames)
        n = len(frame_sizes)
        print("\n== compute local frame bytes ==")
        print(f"n={n} min={frame_sizes[0]} p50={frame_sizes[n // 2]} "
              f"p90={frame_sizes[int(n * 0.9)]} max={frame_sizes[-1]} "
              f"mean={sum(frame_sizes) / n:.2f} total={sum(frame_sizes)}")
    KIND_SUPER = 3
    by_id = {part[0]: part for part in partitions}

    def subtree_results(root_id):
        results = 0
        ops_total = 0
        stack = [root_id]
        while stack:
            part = by_id[stack.pop()]
            ops_total += len(part[5])
            for op_id in part[5]:
                results += sum(1 for v in ops[op_id - 1][5] if value_slots[v - 1][1] == 2)
            stack.extend(part[4])
        return ops_total, results

    sizes, boundary_fanout = [], []
    for part in partitions:
        if part[2] != KIND_SUPER:
            continue
        ops_total, results = subtree_results(part[0])
        sizes.append(ops_total)
        boundary_fanout.append(results)
    if sizes:
        sizes.sort()
        boundary_fanout.sort()
        n = len(sizes)

        def quantiles(data):
            return (f"n={len(data)} min={data[0]} p50={data[n // 2]} "
                    f"p90={data[int(n * 0.9)]} p99={data[int(n * 0.99)]} max={data[-1]} "
                    f"mean={sum(data) / len(data):.2f}")

        print("\n== supernode op counts ==\n" + quantiles(sizes))
        print("== supernode boundary result counts ==\n" + quantiles(boundary_fanout))


if __name__ == "__main__":
    main()
