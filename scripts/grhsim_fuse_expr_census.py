"""Census: dynamic weight of fusible single-use scalar compute chains (NO00011).

Unit = kind-3 supernode partition; flat op order = concatenation of its
node-children op lists (emit order); helperChunks = ranges over that order.

Fusible producer op = core.compute.* eligible kind, single result, result
2-state logic 1..64 bits, all operands 2-state logic <=64 bits, result
non-boundary, exactly one consuming op, consumer also eligible compute op,
producer and consumer in the same supernode AND same helperChunk.

Joins fusible ops with [grhsim-dyn] sn body counts for dynamic executions.
Used to size the grhsim.fuse-expr-chains pass (core.compute.expr) before
implementation; see pdocs/NO00011-grhsim-ir-expr-tree-fusion-20260925.md.

Parsing conventions follow scripts/grhsim_op_mix_stats.py (op[1]=name sid,
op[4]=operands, op[5]=results; type[2]=kind, type[3]=width, type[5]=domain).
"""

from __future__ import annotations

import argparse
from array import array
from collections import Counter
import json
import re
import sys
import time

ELIGIBLE = {
    "add", "sub", "mul", "and", "or", "xor", "xnor", "not",
    "shl", "lshr", "ashr", "div", "mod",
    "eq", "ne", "caseEq", "caseNe", "wildcardEq", "wildcardNe",
    "lt", "le", "gt", "ge", "logicAnd", "logicOr", "logicNot",
    "reduceAnd", "reduceNand", "reduceOr", "reduceNor", "reduceXor", "reduceXnor",
    "mux", "bitSelect", "prioritySelect", "concat", "replicate",
    "sliceStatic", "sliceDynamic", "sliceArray", "assign",
}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--dyn-log", required=True)
    args = parser.parse_args()

    t0 = time.time()
    with open(args.model, "rb") as fh:
        model = json.load(fh)
    log(f"[load] {time.time() - t0:.1f}s")

    strings = model["strings"]
    types = {t[0]: t for t in model["types"]}
    values = model["values"]
    ops = model["operations"]
    n_ops = len(ops)
    n_values = len(values)

    payload = model["mappings"][0][-1]
    partitions = {p[0]: p for p in payload[2]}
    value_slots = payload[3][3]

    def text(sid):
        return strings[sid - 1] if sid else "<none>"

    kind_of = [""] * (n_ops + 1)
    operands_of = [None] * (n_ops + 1)
    results_of = [None] * (n_ops + 1)
    for index, op in enumerate(ops):
        kind_of[index + 1] = text(op[1])
        operands_of[index + 1] = op[4]
        results_of[index + 1] = op[5]

    oktype_of = bytearray(n_values + 1)
    width_of = array("i", bytes(4 * (n_values + 1)))
    for index, value in enumerate(values):
        t = types[value[1]]
        if t[2] == "logic" and t[5] == "2-state" and 0 < t[3] <= 64:
            oktype_of[index + 1] = 1
            width_of[index + 1] = t[3]

    producer = array("i", bytes(4 * (n_values + 1)))
    for ordinal in range(1, n_ops + 1):
        for v in results_of[ordinal]:
            producer[v] = ordinal

    use_count = array("i", bytes(4 * (n_values + 1)))
    sole_consumer = array("i", bytes(4 * (n_values + 1)))
    for ordinal in range(1, n_ops + 1):
        for v in operands_of[ordinal]:
            use_count[v] += 1
            sole_consumer[v] = ordinal

    def is_boundary(v):
        return value_slots[v - 1][1] == 2

    # direct owner partition per op; climb to kind-3 supernode ancestor
    direct_owner = array("i", bytes(4 * (n_ops + 1)))
    for pid, part in partitions.items():
        for opid in part[5]:
            direct_owner[opid] = pid
    parent = {pid: p[1] for pid, p in partitions.items()}
    kind_of_part = {pid: p[2] for pid, p in partitions.items()}

    super_cache = {}

    def supernode_of(opid):
        pid = direct_owner[opid]
        if pid in super_cache:
            return super_cache[pid]
        root = pid
        while root and kind_of_part.get(root) != 3:
            root = parent.get(root, 0)
        super_cache[pid] = root
        return root

    # flattened op order per supernode + chunk id per flat position
    # node partition children order = partition.children (kind-4 nodes)
    super_flat = {}
    super_chunk_of_pos = {}
    for pid, part in partitions.items():
        if part[2] != 3:
            continue
        flat = []
        for child in part[4]:
            flat.extend(partitions[child][5])
        if part[5]:
            flat.extend(part[5])
        if not flat:
            continue
        super_flat[pid] = flat
        chunks = part[7][2] if len(part) > 7 else []
        cmap = array("i", bytes(4 * len(flat)))
        for pos in range(len(flat)):
            cid = 0
            for ci, (off, cnt) in enumerate(chunks):
                if off <= pos < off + cnt:
                    cid = ci + 1
                    break
            cmap[pos] = cid
        super_chunk_of_pos[pid] = cmap
    # op -> (supernode, flatpos)
    op_pos = {}
    for pid, flat in super_flat.items():
        for pos, opid in enumerate(flat):
            op_pos[opid] = (pid, pos)
    log(f"[index] {time.time() - t0:.1f}s supers={len(super_flat)}")

    def eligible_op(ord_: int) -> bool:
        kind = kind_of[ord_]
        return kind.startswith("core.compute.") and kind[13:] in ELIGIBLE

    def fusible_producer(ord_: int) -> bool:
        if not eligible_op(ord_):
            return False
        res = results_of[ord_]
        if len(res) != 1:
            return False
        v = res[0]
        if not oktype_of[v] or is_boundary(v) or use_count[v] != 1:
            return False
        for o in operands_of[ord_]:
            if not oktype_of[o]:
                return False
        cons = sole_consumer[v]
        if not cons or not eligible_op(cons):
            return False
        pp = op_pos.get(ord_)
        pc = op_pos.get(cons)
        if not pp or not pc or pp[0] != pc[0]:
            return False
        return super_chunk_of_pos[pp[0]][pp[1]] == super_chunk_of_pos[pc[0]][pc[1]]

    fusible_ops = [o for o in range(1, n_ops + 1) if fusible_producer(o)]
    fusible_set = set(fusible_ops)
    log(f"[fusible] {time.time() - t0:.1f}s count={len(fusible_ops)}")

    trees = 0
    for o in fusible_ops:
        cons = sole_consumer[results_of[o][0]]
        if cons not in fusible_set:
            trees += 1

    body_of = {}
    sn_re = re.compile(r"^\[grhsim-dyn\] sn (\d+) act=(\d+) body=(\d+)")
    with open(args.dyn_log) as fh:
        for line in fh:
            m = sn_re.match(line)
            if m:
                body_of[int(m.group(1))] = int(m.group(3))
    guest_cycles = 100001
    dyn_fusible = 0
    missing = 0
    hist = Counter()
    for o in fusible_ops:
        pid = op_pos[o][0]
        body = body_of.get(pid)
        if body is None:
            missing += 1
            continue
        dyn_fusible += body
    for o in fusible_ops:
        hist[kind_of[o][13:]] += 1
    print(f"static fusible ops (supernode+chunk aware, scalar-only): {len(fusible_ops)}")
    print(f"trees (roots): {trees}  mean fused ops/tree={len(fusible_ops)/max(trees,1):.2f}")
    print(f"dynamic fusible op executions: {dyn_fusible} "
          f"({dyn_fusible/guest_cycles:.1f}/guest-cycle)")
    print(f"fusible share of dynamic compute ops (dynOps 994789.4/cycle): "
          f"{100*dyn_fusible/99479933605:.2f}%")
    print(f"fusible ops in units missing from dyn log: {missing}")
    print("top fusible kinds:", dict(hist.most_common(12)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
