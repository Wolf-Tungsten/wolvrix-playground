"""Simulate boolean chain canonicalization (flatten + dedup + sorted re-associate
+ global CSE) for 1-bit two-state and/or trees.

After normalizing every maximal and/or tree into a canonical right-deep chain of
sorted unique leaves, every op with the same sorted leaf suffix merges into one
shared op. This simulation counts, per op family (and/logicAnd/or/logicOr):

- old ops: current number of 1-bit two-state ops of the family;
- new ops: number of distinct (family, sorted leaf suffix) pairs needed;
- cross-supernode shared prefixes (would materialize as boundary values);
- current cross-supernode shared values among these trees (boundary today).

A positive net delta (old - new) is static op elimination; dynamic cost scales
with the boundary delta (each new cross-supernode shared value pays writeback +
fanout publication per producer activation).
"""

import argparse
from array import array
from collections import Counter
import json
from pathlib import Path

FAMILIES = {
    "core.compute.and": "and",
    "core.compute.logicAnd": "and",
    "core.compute.or": "or",
    "core.compute.logicOr": "or",
}
KINDS = {"and": {"core.compute.and", "core.compute.logicAnd"},
         "or": {"core.compute.or", "core.compute.logicOr"}}


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

    op_sn = array("i", [0]) * (len(ops) + 1)
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
        family = FAMILIES.get(name)
        if not family:
            continue
        for operand in op[4]:
            src = producer[operand]
            if src and FAMILIES.get(names[src - 1]) == family:
                interior.add(operand)

    stats = Counter()
    canonical_ops = set()      # (family, suffix tuple) — one op each after CSE
    prefix_sn_sets = {}
    old_cross_sn_values = 0
    old_ops_by_family = Counter()
    tree_count = 0

    for op in ops:
        family = FAMILIES.get(names[op[0] - 1])
        if not family or len(op[5]) != 1 or not is_1bit_2s(op[5][0]):
            continue
        old_ops_by_family[family] += 1
        root = op[5][0]
        if root in interior:
            continue
        # maximal tree root: flatten through same-family nodes
        kinds = KINDS[family]
        leaves = []
        stack = [root]
        ok = True
        while stack:
            value = stack.pop()
            if len(leaves) > 512:
                ok = False
                break
            op_id = producer[value]
            if op_id and names[op_id - 1] in kinds and len(ops[op_id - 1][4]) == 2:
                stack.append(ops[op_id - 1][4][0])
                stack.append(ops[op_id - 1][4][1])
            else:
                leaves.append(value)
        if not ok:
            stats["too_deep"] += 1
            continue
        uniq = sorted(set(leaves))
        if len(uniq) < 2:
            stats["degenerate"] += 1
            continue
        tree_count += 1
        stats["tree_leaves"] += len(uniq)
        # canonical right-deep chain: and(l0, and(l1, ...)) — ops keyed by suffix
        sn = op_sn[op[0]]
        for start in range(1, len(uniq)):
            suffix = tuple(uniq[start:])
            canonical_ops.add((family, suffix))
            bucket = prefix_sn_sets.setdefault((family, suffix), set())
            if sn > 0:
                bucket.add(sn)
        # current cross-supernode status of this root
        if op_sn[op[0]] > 0:
            stats["tree_roots_compute"] += 1

    old_total = sum(old_ops_by_family.values())
    new_total = len(canonical_ops)
    new_cross_sn = sum(1 for sn_set in prefix_sn_sets.values() if len(sn_set) > 1)

    print("== canonicalization simulation ==")
    print(f"trees={tree_count} leaves={stats['tree_leaves']} degenerate={stats['degenerate']} too_deep={stats['too_deep']}")
    for family in ("and", "or"):
        print(f"old_ops[{family}]={old_ops_by_family[family]}")
    print(f"old_total={old_total}")
    print(f"new_total(canonical distinct)={new_total}")
    print(f"net_static_delta={old_total - new_total}")
    print(f"new_cross_supernode_prefixes={new_cross_sn}")
    # distribution of chain lengths
    lengths = Counter(len(suffix) for _, suffix in canonical_ops)
    top_lengths = sorted(lengths.items())[:8]
    print(f"canonical chain length sample: {top_lengths}")


if __name__ == "__main__":
    main()
