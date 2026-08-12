#!/usr/bin/env python3
"""NO0019: compare per-block (grhsim am) vs per-supernode (gsim) runtime
activation distributions on the same coremark 50k window.

Inputs
------
- gsim fire TSV:    supernode_id <tab> f            (GSIM_SUPERNODE_TSV)
- gsim static TSV:  supernode_id, phase, n_comp, n_src, n_sink, n_const, a_succ
- gsim members:     SimTop_supernode_members.jsonl  (cpp_id -> nodes)
- am block execs:   "block kind execs" per line     (EMU_AM_BLOCK_EXECS)
- am block/atom:    am_block_atom.jsonl (block header rows carry instr_count;
                    atom rows carry gsim_node)

Analyses
--------
A. totals: sum fires (gsim) vs sum execs (am compute / commit split)
B. distribution shape: percentiles, top-N concentration, gini, log2 histogram
C. cluster-level fire comparison over the block<->super bipartite incidence
   (union-find clusters; per-cluster sum ratio distribution)
D. commit-block overhead account
"""
import argparse
import json
import math
import sys
from collections import defaultdict


def load_gsim_fire(path):
    fire = {}
    with open(path) as f:
        header = f.readline()
        for line in f:
            line = line.strip()
            if not line:
                continue
            sid, cnt = line.split("\t")[:2]
            fire[int(sid)] = int(cnt)
    return fire


def load_gsim_static(path):
    static = {}
    with open(path) as f:
        header = f.readline()
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 7:
                continue
            sid = int(parts[0])
            static[sid] = {
                "n_comp": int(parts[2]),
                "n_src": int(parts[3]),
                "n_sink": int(parts[4]),
                "n_const": int(parts[5]),
                "a_succ": int(parts[6]),
            }
    return static


def load_gsim_members(path):
    members = {}
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            members[rec["cpp_id"]] = rec["nodes"]
    return members


def load_am_execs(path):
    execs = {}
    kind = {}
    with open(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 3:
                continue
            b = int(parts[0])
            kind[b] = parts[1]
            execs[b] = int(parts[2])
    return execs, kind


def load_am_block_atom(path):
    block_instr = {}
    atom_block = {}
    atom_node = {}
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            if "role" in rec or ("block" in rec and "atom_count" in rec):
                block_instr[rec["block"]] = rec.get("instr_count", 0)
            elif "atom" in rec:
                atom_block[rec["atom"]] = rec["block"]
                atom_node[rec["atom"]] = rec.get("gsim_node", -1)
    return block_instr, atom_block, atom_node


def percentiles(values, ps=(50, 90, 99, 99.9)):
    if not values:
        return {}
    s = sorted(values)
    out = {}
    n = len(s)
    for p in ps:
        k = min(n - 1, max(0, int(math.ceil(p / 100.0 * n)) - 1))
        out[f"p{p}"] = s[k]
    out["max"] = s[-1]
    out["mean"] = sum(s) / n
    return out


def gini(values):
    s = sorted(v for v in values if v >= 0)
    n = len(s)
    if n == 0:
        return 0.0
    total = sum(s)
    if total == 0:
        return 0.0
    cum = 0.0
    for i, v in enumerate(s, 1):
        cum += i * v
    return (2.0 * cum) / (n * total) - (n + 1.0) / n


def top_share(values, frac):
    s = sorted(values, reverse=True)
    total = sum(s)
    if total == 0:
        return 0.0
    k = max(1, int(len(s) * frac))
    return sum(s[:k]) / total


def log2_hist(values, buckets=24):
    # bucket k (k>=1) holds [2^(k-1), 2^k); bucket 0 holds v<=0 or v<1 mapped
    # downward: use floor and clamp into [0, buckets] with an offset so that
    # ratios below 1 land in low buckets without python negative-index wrap.
    hist = [0] * (buckets + 1)
    for v in values:
        if v <= 0:
            hist[0] += 1
        else:
            b = int(math.floor(math.log2(v))) + 1
            hist[min(max(b, 0), buckets)] += 1
    return hist


class DSU:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        p = self.parent
        if x not in p:
            p[x] = x
            return x
        root = x
        while p[root] != root:
            root = p[root]
        while p[x] != root:
            p[x], x = root, p[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gsim-fire", required=True)
    ap.add_argument("--gsim-static", required=True)
    ap.add_argument("--gsim-members", required=True)
    ap.add_argument("--am-execs", required=True)
    ap.add_argument("--am-block-atom", required=True)
    ap.add_argument("--out-json", default=None)
    args = ap.parse_args()

    fire = load_gsim_fire(args.gsim_fire)
    static = load_gsim_static(args.gsim_static)
    members = load_gsim_members(args.gsim_members)
    am_execs, am_kind = load_am_execs(args.am_execs)
    block_instr, atom_block, atom_node = load_am_block_atom(args.am_block_atom)

    report = {}

    # --- A. totals -------------------------------------------------------
    gsim_total_fire = sum(fire.values())
    am_compute_execs = {b: e for b, e in am_execs.items() if am_kind.get(b) == "w"}
    am_commit_execs = {b: e for b, e in am_execs.items() if am_kind.get(b) == "c"}
    am_entry_execs = {b: e for b, e in am_execs.items() if am_kind.get(b) not in ("w", "c")}
    report["totals"] = {
        "gsim_supers": len(fire),
        "gsim_total_fire": gsim_total_fire,
        "am_compute_blocks": len(am_compute_execs),
        "am_compute_total_execs": sum(am_compute_execs.values()),
        "am_commit_blocks": len(am_commit_execs),
        "am_commit_total_execs": sum(am_commit_execs.values()),
        "am_other_blocks": len(am_entry_execs),
        "am_other_total_execs": sum(am_entry_execs.values()),
    }

    # --- B. distribution shape -------------------------------------------
    gsim_fires = list(fire.values())
    am_w = list(am_compute_execs.values())
    # dynamic work: fire x static size
    gsim_work = [
        fire[s] * (static.get(s, {}).get("n_comp", 0) + static.get(s, {}).get("n_src", 0)
                   + static.get(s, {}).get("n_sink", 0) + static.get(s, {}).get("n_const", 0))
        for s in fire
    ]
    am_work = [e * block_instr.get(b, 0) for b, e in am_compute_execs.items()]
    report["fire_distribution"] = {
        "gsim": {**percentiles(gsim_fires), "gini": gini(gsim_fires),
                 "top1pct_share": top_share(gsim_fires, 0.01),
                 "top10pct_share": top_share(gsim_fires, 0.10),
                 "zero_fire": sum(1 for v in gsim_fires if v == 0),
                 "hist_log2": log2_hist(gsim_fires)},
        "am_compute": {**percentiles(am_w), "gini": gini(am_w),
                       "top1pct_share": top_share(am_w, 0.01),
                       "top10pct_share": top_share(am_w, 0.10),
                       "zero_fire": sum(1 for v in am_w if v == 0),
                       "hist_log2": log2_hist(am_w)},
    }
    report["work_distribution"] = {
        "gsim_fire_x_enode_cost": {**percentiles(gsim_work), "total": sum(gsim_work)},
        "am_exec_x_instr": {**percentiles(am_work), "total": sum(am_work)},
    }

    # --- C. cluster-level fire comparison ---------------------------------
    # node -> super (gsim), atom -> block (am); bipartite incidence via
    # atom.gsim_node. Clusters over union of blocks and supers.
    node_super = {}
    for sid, nodes in members.items():
        for n in nodes:
            node_super[n] = sid
    dsu = DSU()
    touched_blocks = set()
    touched_supers = set()
    for a, node in atom_node.items():
        if node < 0:
            continue
        sid = node_super.get(node)
        if sid is None:
            continue
        b = atom_block[a]
        if am_kind.get(b) != "w":
            continue  # commit blocks stay out of the compute comparison
        dsu.union(("b", b), ("s", sid))
        touched_blocks.add(b)
        touched_supers.add(sid)
    clusters = defaultdict(lambda: {"blocks": set(), "supers": set()})
    for b in touched_blocks:
        clusters[dsu.find(("b", b))]["blocks"].add(b)
    for s in touched_supers:
        clusters[dsu.find(("s", s))]["supers"].add(s)

    ratios = []
    cluster_rows = []
    for root, cl in clusters.items():
        am_fire = sum(am_execs.get(b, 0) for b in cl["blocks"])
        g_fire = sum(fire.get(s, 0) for s in cl["supers"])
        cluster_rows.append({
            "blocks": len(cl["blocks"]), "supers": len(cl["supers"]),
            "am_fire": am_fire, "gsim_fire": g_fire,
        })
        if g_fire > 0 and am_fire > 0:
            ratios.append(am_fire / g_fire)
    ratio_bands = {"lt0.25": 0, "0.25_0.5": 0, "0.5_0.9": 0, "0.9_1.1": 0,
                   "1.1_2": 0, "2_4": 0, "ge4": 0}
    for v in ratios:
        if v < 0.25: ratio_bands["lt0.25"] += 1
        elif v < 0.5: ratio_bands["0.25_0.5"] += 1
        elif v < 0.9: ratio_bands["0.5_0.9"] += 1
        elif v <= 1.1: ratio_bands["0.9_1.1"] += 1
        elif v < 2: ratio_bands["1.1_2"] += 1
        elif v < 4: ratio_bands["2_4"] += 1
        else: ratio_bands["ge4"] += 1
    report["clusters"] = {
        "count": len(cluster_rows),
        "both_nonzero": len(ratios),
        "ratio_am_over_gsim": {**percentiles(ratios),
                               "bands": ratio_bands},
        "top_overshot": sorted([r for r in cluster_rows if r["gsim_fire"] > 0], key=lambda r: r["am_fire"] / r["gsim_fire"], reverse=True)[:10],
        "top_undershot": sorted([r for r in cluster_rows if r["am_fire"] > 0], key=lambda r: r["am_fire"] / r["gsim_fire"] if r["gsim_fire"] else float("inf"))[:10],
    }

    # --- D. commit account --------------------------------------------------
    commit_list = sorted(am_commit_execs.items(), key=lambda kv: kv[1], reverse=True)
    report["commit_account"] = {
        "total_execs": sum(am_commit_execs.values()),
        "share_of_all_block_execs": (sum(am_commit_execs.values())
                                     / max(1, sum(am_compute_execs.values()) + sum(am_commit_execs.values()))),
        "top10": commit_list[:10],
        "zero_exec_commit_blocks": sum(1 for _, e in commit_list if e == 0),
    }

    text = json.dumps(report, indent=1)
    if args.out_json:
        with open(args.out_json, "w") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
