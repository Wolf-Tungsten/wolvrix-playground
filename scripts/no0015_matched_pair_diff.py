#!/usr/bin/env python3
"""NO0015: per-unit cost comparison restricted to EXACT 1:1 pairs between
gsim supernodes and grhsim am compute blocks (identical gsim-node member
set). On these pairs scheduling/partition is identical by construction, so
the per-fire cycle delta isolates emit-quality differences.

Inputs
------
- gsim members:  SimTop_supernode_members.jsonl (cpp_id -> nodes, type)
- gsim time TSV: supernode_id <tab> f <tab> cycles (multi-file -> median)
- am block/atom: am_block_atom.jsonl (block rows role; atom rows gsim_node)
- am execs:      "block kind execs cycles" (multi-file -> median)

Outputs
-------
- stdout summary + --out-json with pair table.
"""
import argparse
import json
from collections import defaultdict


def load_gsim_members(path):
    members, types = {}, {}
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            members[rec["cpp_id"]] = frozenset(rec["nodes"])
            types[rec["cpp_id"]] = rec.get("type", "?")
    return members, types


def load_gsim_time(paths):
    fire, cyc = defaultdict(list), defaultdict(list)
    for p in paths:
        with open(p) as f:
            f.readline()
            for line in f:
                line = line.strip()
                if not line:
                    continue
                sid, cnt, cy = line.split("\t")[:3]
                fire[int(sid)].append(int(cnt))
                cyc[int(sid)].append(int(cy))
    med = lambda vs: sorted(vs)[len(vs) // 2]
    return ({k: med(v) for k, v in fire.items()},
            {k: med(v) for k, v in cyc.items()})


def load_am_members(path):
    block_nodes = defaultdict(set)
    block_neg = defaultdict(int)
    block_atoms, block_instrs, role = {}, {}, {}
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            if "role" in rec:
                role[rec["block"]] = rec["role"]
                block_atoms[rec["block"]] = rec["atom_count"]
                block_instrs[rec["block"]] = rec["instr_count"]
            else:
                g = rec["gsim_node"]
                if g >= 0:
                    block_nodes[rec["block"]].add(g)
                else:
                    block_neg[rec["block"]] += 1
    return block_nodes, block_neg, block_atoms, block_instrs, role


def load_am_execs(paths):
    ex, cy, kind = defaultdict(list), defaultdict(list), {}
    for p in paths:
        with open(p) as f:
            for line in f:
                parts = line.split()
                if len(parts) < 4:
                    continue
                b = int(parts[0])
                kind[b] = parts[1]
                ex[b].append(int(parts[2]))
                cy[b].append(int(parts[3]))
    med = lambda vs: sorted(vs)[len(vs) // 2]
    return ({k: med(v) for k, v in ex.items()},
            {k: med(v) for k, v in cy.items()}, kind)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gsim-members", required=True)
    ap.add_argument("--gsim-time", nargs="+", required=True)
    ap.add_argument("--am-block-atom", required=True)
    ap.add_argument("--am-execs", nargs="+", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--topk", type=int, default=30)
    args = ap.parse_args()

    sup_nodes, sup_type = load_gsim_members(args.gsim_members)
    g_fire, g_cyc = load_gsim_time(args.gsim_time)
    blk_nodes, blk_neg, blk_atoms, blk_instrs, role = \
        load_am_members(args.am_block_atom)
    a_ex, a_cy, kind = load_am_execs(args.am_execs)

    compute_blocks = {b for b, r in role.items() if r == "compute"}

    # block nodeset -> block id (exact-set index)
    set2block = {}
    for b in compute_blocks:
        ns = blk_nodes.get(b)
        if not ns:
            continue
        set2block.setdefault(frozenset(ns), []).append(b)

    pairs = []          # (cpp_id, block)
    matched_supers, matched_blocks = set(), set()
    for cpp_id, ns in sup_nodes.items():
        bs = set2block.get(ns)
        if not bs:
            continue
        # a supernode's node set may in principle hit >1 identical blocks;
        # pair with each (they are duplicates doing identical work)
        for b in bs:
            pairs.append((cpp_id, b))
            matched_supers.add(cpp_id)
            matched_blocks.add(b)

    # per-pair timing join
    rows = []
    for cpp_id, b in pairs:
        fg, cg = g_fire.get(cpp_id, 0), g_cyc.get(cpp_id, 0)
        fa, ca = a_ex.get(b, 0), a_cy.get(b, 0)
        rows.append({
            "cpp_id": cpp_id, "block": b, "type": sup_type[cpp_id],
            "members": len(sup_nodes[cpp_id]),
            "atoms": blk_atoms.get(b, 0), "instrs": blk_instrs.get(b, 0),
            "neg_atoms": blk_neg.get(b, 0),
            "fires_g": fg, "fires_a": fa,
            "cycles_g": cg, "cycles_a": ca,
            "perfire_g": cg / fg if fg else 0.0,
            "perfire_a": ca / fa if fa else 0.0,
            "delta": ca - cg,
        })

    tot_g = sum(g_cyc.values())
    tot_a_compute = sum(c for b, c in a_cy.items() if kind.get(b) == "w")
    m_g = sum(r["cycles_g"] for r in rows)
    m_a = sum(r["cycles_a"] for r in rows)
    m_delta = m_a - m_g
    gap_total = tot_a_compute - tot_g

    hot = [r for r in rows if r["fires_g"] > 0 and r["fires_a"] > 0]
    ratios = sorted(r["perfire_a"] / r["perfire_g"] for r in hot
                    if r["perfire_g"] > 0)
    buckets = [("<=1.5x", 0, 1.5), ("1.5-3x", 1.5, 3), ("3-5x", 3, 5),
               ("5-10x", 5, 10), ("10-100x", 10, 100), (">100x", 100, 1e18)]
    bcnt = {name: 0 for name, _, _ in buckets}
    bcyc = {name: 0 for name, _, _ in buckets}
    for r in hot:
        if r["perfire_g"] <= 0:
            continue
        rt = r["perfire_a"] / r["perfire_g"]
        for name, lo, hi in buckets:
            if lo < rt <= hi:
                bcnt[name] += 1
                bcyc[name] += r["cycles_a"]
                break

    rows.sort(key=lambda r: -r["delta"])

    def pct(x, y):
        return 100.0 * x / y if y else 0.0

    print("== exact 1:1 pair match ==")
    print(f"gsim supernodes: {len(sup_nodes)}  matched: {len(matched_supers)}"
          f" ({pct(len(matched_supers), len(sup_nodes)):.1f}%)")
    print(f"am compute blocks: {len(compute_blocks)}  matched: {len(matched_blocks)}"
          f" ({pct(len(matched_blocks), len(compute_blocks)):.1f}%)")
    print(f"pairs: {len(rows)}  hot(both fired): {len(hot)}")
    print()
    print("== cycle share (coremark 50k window) ==")
    print(f"gsim total cycles:        {tot_g/1e9:8.2f}G")
    print(f"am compute total cycles:  {tot_a_compute/1e9:8.2f}G")
    print(f"matched-pair gsim cycles: {m_g/1e9:8.2f}G ({pct(m_g, tot_g):.1f}% of gsim)")
    print(f"matched-pair am cycles:   {m_a/1e9:8.2f}G ({pct(m_a, tot_a_compute):.1f}% of am compute)")
    print(f"matched-pair delta:       {m_delta/1e9:8.2f}G ({pct(m_delta, gap_total):.1f}% of compute gap {gap_total/1e9:.2f}G)")
    print()
    print("== per-fire ratio on hot matched pairs (am/gsim) ==")
    if ratios:
        n = len(ratios)
        q = lambda p: ratios[min(n - 1, int(p * n))]
        agg_g = sum(r["cycles_g"] for r in hot)
        agg_a = sum(r["cycles_a"] for r in hot)
        print(f"pairs with ratio: {n}  p10={q(.1):.2f} p50={q(.5):.2f} "
              f"p90={q(.9):.2f} p99={q(.99):.2f}")
        print(f"cycle-weighted aggregate ratio: {agg_a/agg_g:.2f}x"
              f" (am {agg_a/1e9:.2f}G vs gsim {agg_g/1e9:.2f}G on hot pairs)")
        print("bucket (per-fire ratio): pair-count / am-cycles-share")
        for name, _, _ in buckets:
            print(f"  {name:>8}: {bcnt[name]:6d} pairs  {bcyc[name]/1e9:8.2f}G")
    print()
    print(f"== top-{args.topk} matched pairs by delta ==")
    print(f"{'rank':>4} {'block':>7} {'cpp_id':>7} {'type':<14} {'memb':>5} "
          f"{'instrs':>7} {'fires_g':>9} {'fires_a':>9} {'pf_g':>10} "
          f"{'pf_a':>12} {'ratio':>8} {'delta(G)':>9}")
    for i, r in enumerate(rows[:args.topk]):
        rt = (r["perfire_a"] / r["perfire_g"]) if r["perfire_g"] > 0 else 0
        print(f"{i+1:>4} {r['block']:>7} {r['cpp_id']:>7} {r['type']:<14} "
              f"{r['members']:>5} {r['instrs']:>7} {r['fires_g']:>9} "
              f"{r['fires_a']:>9} {r['perfire_g']:>10.1f} "
              f"{r['perfire_a']:>12.1f} {rt:>8.2f} {r['delta']/1e9:>9.3f}")

    # fires parity sanity on hot pairs
    dev = [abs(r["fires_a"] - r["fires_g"]) / max(1, r["fires_g"]) for r in hot]
    dev.sort()
    if dev:
        print()
        print(f"fires parity |a-g|/g: p50={dev[len(dev)//2]:.4f} "
              f"p90={dev[int(.9*len(dev))]:.4f} max={dev[-1]:.4f}")

    with open(args.out_json, "w") as f:
        json.dump({
            "pairs": len(rows), "hot_pairs": len(hot),
            "matched_supers": len(matched_supers),
            "matched_blocks": len(matched_blocks),
            "totals": {"gsim": tot_g, "am_compute": tot_a_compute,
                       "matched_g": m_g, "matched_a": m_a,
                       "matched_delta": m_delta, "gap": gap_total},
            "rows": rows,
        }, f)


if __name__ == "__main__":
    main()
