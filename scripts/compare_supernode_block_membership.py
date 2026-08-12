#!/usr/bin/env python3
"""Membership join: gsim supernode partition vs AM block partition (NO0009).

Joins the two membership exports on the shared gsim node-id space (both
artifacts must come from the SAME gsim run — node ids are process-local
allocation counters):

- gsim side: <name>_supernode_members.jsonl (one line per supernode:
  {"super", "cpp_id", "type", "member_count", "nodes": [node_id, ...]})
- AM side: block_atom jsonl (block lines {"block", "role", "atom_count",
  "instr_count"}; atom lines {"atom", "block", "kind", "gsim_node",
  "instr_count"})

Headline metrics:
  1. coverage: how many gsim member node ids exist in the AM node space
     (residual = post-PreCoarsen newcomers: mergeResetAll REG_RESET dups,
     replicationOpt copies — expected, itemized);
  2. per gsim supernode: across how many AM compute blocks do its member
     nodes land (1 == perfectly nested inside one AM block);
  3. per AM compute block: how many distinct gsim supernodes it touches
     (symmetric view);
  4. commit-side note: gsim nodes whose id appears only on AM commit atoms
     (register-write layer, not a scheduling difference).
"""

import argparse
import json
from collections import Counter


def load_gsim_members(path):
    supers = []  # (super_id, cpp_id, type, [node_ids])
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            supers.append(
                (
                    record["super"],
                    record.get("cpp_id", -1),
                    record.get("type", "?"),
                    record["nodes"],
                )
            )
    return supers


def load_am_members(path):
    block_role = {}
    block_atom_count = {}
    block_instr_count = {}
    atoms = []  # (atom, block, kind, gsim_node, instr_count)
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            if '"atom_count"' in line:
                record = json.loads(line)
                block = record["block"]
                block_role[block] = record["role"]
                block_atom_count[block] = record["atom_count"]
                block_instr_count[block] = record["instr_count"]
            else:
                record = json.loads(line)
                atoms.append(
                    (
                        record["atom"],
                        record["block"],
                        record.get("kind", "?"),
                        record["gsim_node"],
                        record.get("instr_count", 0),
                    )
                )
    return block_role, block_atom_count, block_instr_count, atoms


def histogram(values, buckets=(1, 2, 3, 4, 5, 8, 16, 64, 256, 1024)):
    """Bucketed histogram: {label: count}, plus mean."""
    counts = Counter()
    total = 0
    for value in values:
        total += value
        placed = False
        for bound in buckets:
            if value <= bound:
                counts[f"<={bound}"] += 1
                placed = True
                break
        if not placed:
            counts[">1024"] += 1
    ordered = {key: counts[key] for key in [f"<={b}" for b in buckets] + [">1024"] if counts[key]}
    mean = total / len(values) if values else 0.0
    return ordered, mean


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gsim-members", required=True, help="gsim *_supernode_members.jsonl")
    parser.add_argument("--am-members", required=True, help="AM block_atom jsonl")
    parser.add_argument("--out-json", default=None, help="optional machine-readable summary")
    parser.add_argument("--top", type=int, default=10, help="top-N outliers to list")
    args = parser.parse_args()

    supers = load_gsim_members(args.gsim_members)
    block_role, block_atom_count, block_instr_count, atoms = load_am_members(args.am_members)

    # node -> compute block / commit block maps (aligned mode: <=1 compute atom per node)
    node_compute_block = {}
    dup_compute_nodes = 0
    node_commit_block = {}
    am_node_space = set()
    atom_kind_count = Counter()
    for _atom, block, _kind, gsim_node, _instrs in atoms:
        atom_kind_count[_kind] += 1
        if gsim_node < 0:
            continue
        am_node_space.add(gsim_node)
        role = block_role.get(block, "?")
        if role == "compute":
            if gsim_node in node_compute_block:
                dup_compute_nodes += 1
            else:
                node_compute_block[gsim_node] = block
        elif role == "commit":
            node_commit_block.setdefault(gsim_node, block)

    compute_blocks = sorted(b for b, r in block_role.items() if r == "compute")
    commit_blocks = sorted(b for b, r in block_role.items() if r == "commit")

    # --- coverage ---
    member_nodes = set()
    for _sid, _cpp, _type, nodes in supers:
        member_nodes.update(nodes)
    covered_compute = member_nodes & set(node_compute_block)
    covered_any = member_nodes & am_node_space
    only_commit = (covered_any - covered_compute)
    unmapped = member_nodes - am_node_space

    print("== universes ==")
    print(f"gsim supernodes: {len(supers)}  member nodes: {len(member_nodes)}")
    print(f"AM blocks: compute={len(compute_blocks)} commit={len(commit_blocks)} "
          f"other={len(block_role) - len(compute_blocks) - len(commit_blocks)}  atoms={len(atoms)}")
    print(f"AM node-mapped atoms by kind: {dict(atom_kind_count)}")
    print(f"dup node->compute-atom mappings (expect 0 in aligned mode): {dup_compute_nodes}")
    print()
    print("== node-id coverage (gsim member nodes -> AM node space) ==")
    n = len(member_nodes)
    print(f"mapped to AM compute atom: {len(covered_compute)} ({100.0 * len(covered_compute) / n:.2f}%)")
    print(f"mapped only to AM commit atom: {len(only_commit)} ({100.0 * len(only_commit) / n:.2f}%)")
    print(f"unmapped (post-PreCoarsen newcomers: reset-dup / replication): "
          f"{len(unmapped)} ({100.0 * len(unmapped) / n:.2f}%)")
    print()

    # --- per supernode: how many AM compute blocks does it scatter into ---
    node_super = {}
    for sid, _cpp, _type, nodes in supers:
        for node in nodes:
            node_super[node] = sid
    super_block_spread = []
    super_records = []
    for sid, cpp_id, stype, nodes in supers:
        blocks = Counter()
        mapped = 0
        for node in nodes:
            block = node_compute_block.get(node)
            if block is not None:
                blocks[block] += 1
                mapped += 1
        spread = len(blocks)
        super_block_spread.append(spread)
        super_records.append(
            {
                "super": sid,
                "cpp_id": cpp_id,
                "type": stype,
                "members": len(nodes),
                "mapped": mapped,
                "am_blocks": spread,
                "dominant_block_share": (max(blocks.values()) / mapped) if mapped else 0.0,
            }
        )
    perfect = sum(1 for r in super_records if r["am_blocks"] == 1)
    print("== per gsim supernode: AM compute blocks touched ==")
    hist, mean = histogram(super_block_spread)
    print(f"histogram: {hist}  mean={mean:.3f}")
    print(f"perfectly nested in exactly 1 AM block: {perfect} / {len(super_records)} "
          f"({100.0 * perfect / len(super_records):.2f}%)")
    weighted = Counter()
    total_members = 0
    for r in super_records:
        weighted[r["am_blocks"]] += r["mapped"]
        total_members += r["mapped"]
    top_w = ", ".join(f"{k}blk:{v}" for k, v in sorted(weighted.items())[:8])
    print(f"member-weighted spread (blocks-touched -> mapped members): {top_w} ...")
    print()

    # --- per AM compute block: how many gsim supernodes does it touch ---
    # single pass: block -> Counter(super -> mapped atoms)
    block_supers = {block: Counter() for block in compute_blocks}
    for _atom, block, _kind, gsim_node, _instrs in atoms:
        if gsim_node < 0 or block not in block_supers:
            continue
        sid = node_super.get(gsim_node)
        if sid is not None:
            block_supers[block][sid] += 1
    block_super_spread = []
    block_records = []
    for block in compute_blocks:
        supers_touched = block_supers[block]
        spread = len(supers_touched)
        block_super_spread.append(spread)
        block_records.append(
            {
                "block": block,
                "atoms": block_atom_count[block],
                "instrs": block_instr_count[block],
                "gsim_supers": spread,
                "dominant_super_share": (
                    max(supers_touched.values()) / sum(supers_touched.values())
                    if supers_touched else 0.0
                ),
            }
        )
    single = sum(1 for r in block_records if r["gsim_supers"] == 1)
    print("== per AM compute block: gsim supernodes touched ==")
    hist, mean = histogram(block_super_spread)
    print(f"histogram: {hist}  mean={mean:.3f}")
    print(f"blocks touching exactly 1 gsim supernode: {single} / {len(block_records)} "
          f"({100.0 * single / max(1, len(block_records)):.2f}%)")
    print()

    # --- outliers ---
    print(f"== top {args.top} supernodes by AM-block spread ==")
    for r in sorted(super_records, key=lambda r: -r["am_blocks"])[: args.top]:
        print(f"super={r['super']} cpp_id={r['cpp_id']} type={r['type']} "
              f"members={r['members']} mapped={r['mapped']} am_blocks={r['am_blocks']} "
              f"dominant_share={r['dominant_block_share']:.2f}")
    print()
    print(f"== top {args.top} AM compute blocks by supernode spread ==")
    for r in sorted(block_records, key=lambda r: -r["gsim_supers"])[: args.top]:
        print(f"block={r['block']} atoms={r['atoms']} instrs={r['instrs']} "
              f"gsim_supers={r['gsim_supers']} dominant_share={r['dominant_super_share']:.2f}")

    if args.out_json:
        summary = {
            "gsim_supernodes": len(supers),
            "gsim_member_nodes": len(member_nodes),
            "am_compute_blocks": len(compute_blocks),
            "am_commit_blocks": len(commit_blocks),
            "am_atoms": len(atoms),
            "coverage": {
                "compute": len(covered_compute),
                "only_commit": len(only_commit),
                "unmapped": len(unmapped),
            },
            "dup_compute_node_mappings": dup_compute_nodes,
            "supernodes_perfect_nesting": perfect,
            "blocks_single_supernode": single,
            "super_records": super_records,
            "block_records": block_records,
        }
        with open(args.out_json, "w") as handle:
            json.dump(summary, handle, indent=1)
        print(f"\nwrote {args.out_json}")


if __name__ == "__main__":
    main()
