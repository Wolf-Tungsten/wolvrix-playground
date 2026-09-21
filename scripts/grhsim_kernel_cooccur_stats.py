"""Census boolean kernel co-occurrence in 1-bit and/or trees within compute
supernodes (modulo association). CSE dedups identical ops; kernel extraction
targets common leaf PAIRS shared by multiple trees that never formed a shared
op (association variants). A pair (a,b) appearing in K trees of one supernode
could be factored into a shared and(a,b), saving K-1 and-evaluations per
supernode activation. Two passes: global pair frequencies as a filter, then
per-supernode counts for hot pairs. Pool = sum(max(0, K-1)) over (sn, pair).
"""

import argparse
from array import array
from collections import Counter
import json
from pathlib import Path

AND_NAMES = {"core.compute.and", "core.compute.logicAnd"}
OR_NAMES = {"core.compute.or", "core.compute.logicOr"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    model = json.loads(args.model.read_bytes())
    ops, values, strings = model["operations"], model["values"], model["strings"]
    types = {t[0]: t for t in model["types"]}
    names = [strings[op[1] - 1] for op in ops]
    payload = model["mappings"][0][-1]
    partitions = {part[0]: part for part in payload[2]}

    def is_1bit_2s(value):
        t = types[values[value - 1][1]]
        return t[2] == "logic" and t[3] == 1 and t[5] == "2-state"

    producer = array("I", [0]) * (len(values) + 1)
    for op in ops:
        if op[5]:
            producer[op[5][0]] = op[0]

    # supernode membership for ops (compute phase only: phase==1)
    op_sn = array("I", [0]) * (len(ops) + 1)
    def collect(pid, phase, sn):
        part = partitions[pid]
        here = sn
        if part[2] == 3:
            here = pid if phase == 1 else -1
        for op_id in part[5]:
            if here > 0:
                op_sn[op_id] = here
        for child in part[4]:
            collect(child, phase, here)
    roots = [part for part in partitions.values() if part[2] == 0]
    for child in roots[0][4]:
        collect(child, partitions[child][3], 0)

    interior = set()
    for op in ops:
        name = names[op[0] - 1]
        for operand in op[4]:
            src = producer[operand]
            if src and ((name in AND_NAMES and names[src - 1] in AND_NAMES) or
                        (name in OR_NAMES and names[src - 1] in OR_NAMES)):
                interior.add(operand)

    def leaves_of(root, kinds, limit=64):
        leaves = []
        stack = [root]
        while stack:
            value = stack.pop()
            if len(leaves) > limit:
                return None
            op_id = producer[value]
            if op_id and names[op_id - 1] in kinds and len(ops[op_id - 1][4]) == 2:
                stack.append(ops[op_id - 1][4][0])
                stack.append(ops[op_id - 1][4][1])
            else:
                leaves.append(value)
        return leaves

    global_pairs = Counter()
    tree_records = []
    stats = Counter()
    for op in ops:
        name = names[op[0] - 1]
        if name not in AND_NAMES and name not in OR_NAMES:
            continue
        if len(op[5]) != 1 or not is_1bit_2s(op[5][0]):
            continue
        sn = op_sn[op[0]]
        if sn <= 0:
            continue  # commit phase or unattached
        root = op[5][0]
        if root in interior:
            continue
        kinds = AND_NAMES if name in AND_NAMES else OR_NAMES
        leaves = leaves_of(root, kinds)
        if leaves is None or len(leaves) < 3:
            stats["small_or_deep"] += 1
            continue
        uniq = sorted(set(leaves))
        if not (3 <= len(uniq) <= 16):
            stats["small_or_deep"] += 1
            continue
        # direct operand pairs present as actual nodes in this tree
        direct = set()
        stack = [root]
        while stack:
            value = stack.pop()
            op_id = producer[value]
            if op_id and names[op_id - 1] in kinds and len(ops[op_id - 1][4]) == 2:
                a, b = ops[op_id - 1][4]
                direct.add((min(a, b), max(a, b)))
                stack.append(a)
                stack.append(b)
        stats["trees"] += 1
        tree_records.append((sn, root, uniq, direct))
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                global_pairs[(uniq[i], uniq[j])] += 1

    hot = {pair for pair, count in global_pairs.items() if count >= 4}
    stats["pairs_total"] = len(global_pairs)
    stats["pairs_hot_ge4"] = len(hot)

    per_sn = Counter()
    per_sn_variant = Counter()
    for sn, root, uniq, direct in tree_records:
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                pair = (uniq[i], uniq[j])
                if pair in hot:
                    per_sn[(sn, pair)] += 1
                    if pair not in direct:
                        per_sn_variant[(sn, pair)] += 1

    pool = 0
    pair_count = 0
    for (sn, pair), count in per_sn.items():
        if count >= 2:
            pool += count - 1
            pair_count += 1
    stats["hot_pairs_in_sn_ge2"] = pair_count
    stats["kernel_pool_upper"] = pool
    # refined: only trees lacking the direct node can profit from reassociation
    pool_v = 0
    pair_v = 0
    for (sn, pair), count in per_sn_variant.items():
        if count >= 1 and per_sn[(sn, pair)] >= 2:
            pool_v += count
            pair_v += 1
    stats["variant_pairs"] = pair_v
    stats["kernel_pool_variant"] = pool_v

    print("== kernel co-occurrence census ==")
    for key in sorted(stats):
        print(f"{stats[key]:10d}  {key}")
    print("== top global pairs ==")
    for pair, count in global_pairs.most_common(10):
        print(f"{count:10d}  {pair}")


if __name__ == "__main__":
    main()
