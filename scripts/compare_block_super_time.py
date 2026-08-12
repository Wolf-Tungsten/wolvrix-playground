#!/usr/bin/env python3
"""NO0010: differential per-unit timing comparison (gsim supernode vs grhsim am
block) on the same coremark 50k window, aggregated to join clusters and ranked
by absolute cycle delta (the repair order).

Inputs
------
- gsim time TSV:    supernode_id <tab> f <tab> cycles   (GSIM_SUPERNODE_TIME_TSV)
                    Repeatable: pass several files -> per-unit median (fires must
                    be identical across reps; deviation is reported).
- gsim members:     SimTop_supernode_members.jsonl (cpp_id -> nodes, type)
- am block execs:   "block kind execs cycles" per line  (EMU_AM_BLOCK_EXECS,
                    4-column NO0010 format; 3-column legacy tolerated)
- am block/atom:    am_block_atom.jsonl (atom rows carry gsim_node)
- calibration json: {"gsim": {"tsc_hz", "rdtsc_overhead", "step_cycles"},
                     "am":   {"tsc_hz", "rdtsc_overhead", "compute_ns",
                              "commit_ns", "eval_ns"}}
                    (collected from the run logs by the run script)

Analyses
--------
A. totals + overhead-corrected cycles (cycles_corr = cycles - fires*t0 per unit)
B. closure: sum(unit cycles) vs engine total (gsim step_cycles; am eval ns
   converted via tsc_hz) -> the gap is the inter-block/scheduling overhead
C. repeatability: per-unit cycle CV across reps (hot units)
D. cluster ranking: |delta| = |cycles_a - cycles_g| per join cluster, Shapley
   decomposition into count effect vs per-fire cost effect, top-K coverage
E. commit/entry block time account (am-only)
"""
import argparse
import json
import math
from collections import defaultdict


def load_gsim_time_one(path):
    fire, cyc = {}, {}
    with open(path) as f:
        f.readline()  # header
        for line in f:
            line = line.strip()
            if not line:
                continue
            sid, cnt, cy = line.split("\t")[:3]
            fire[int(sid)] = int(cnt)
            cyc[int(sid)] = int(cy)
    return fire, cyc


def median(values):
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def merge_reps(one_loaders, paths):
    """Return (fire_median, cycles_median, fires_max_dev, per-unit (fires, cycles list))."""
    fires_all, cycles_all = [], []
    for p in paths:
        f, c = one_loaders(p)
        fires_all.append(f)
        cycles_all.append(c)
    ids = set()
    for f in fires_all:
        ids.update(f.keys())
    fire_med, cyc_med, max_dev = {}, {}, 0
    unit_reps = {}
    for i in ids:
        fs = [f.get(i, 0) for f in fires_all]
        cs = [c.get(i, 0) for c in cycles_all]
        if max(fs) - min(fs) > max_dev:
            max_dev = max(fs) - min(fs)
        fire_med[i] = int(median(fs))
        cyc_med[i] = median(cs)
        unit_reps[i] = (fire_med[i], cs)
    return fire_med, cyc_med, max_dev, unit_reps


def load_gsim_members(path):
    members, types = {}, {}
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            members[rec["cpp_id"]] = rec["nodes"]
            types[rec["cpp_id"]] = rec.get("type", "?")
    return members, types


def load_am_execs_one(path):
    """Returns (execs, cycles, kind)."""
    execs, cyc, kind = {}, {}, {}
    with open(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 3:
                continue
            b = int(parts[0])
            kind[b] = parts[1]
            execs[b] = int(parts[2])
            cyc[b] = int(parts[3]) if len(parts) > 3 else 0
    return execs, cyc, kind


def merge_am_reps(paths):
    execs_all, cycles_all, kind = [], [], {}
    for p in paths:
        e, c, k = load_am_execs_one(p)
        execs_all.append(e)
        cycles_all.append(c)
        kind.update(k)
    ids = set()
    for e in execs_all:
        ids.update(e.keys())
    ex_med, cy_med, max_dev = {}, {}, 0
    unit_reps = {}
    for i in ids:
        es = [e.get(i, 0) for e in execs_all]
        cs = [c.get(i, 0) for c in cycles_all]
        max_dev = max(max_dev, max(es) - min(es))
        ex_med[i] = int(median(es))
        cy_med[i] = median(cs)
        unit_reps[i] = (ex_med[i], cs)
    return ex_med, cy_med, kind, max_dev, unit_reps


def load_am_block_atom(path):
    atom_block, atom_node = {}, {}
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            if "atom" in rec:
                atom_block[rec["atom"]] = rec["block"]
                atom_node[rec["atom"]] = rec.get("gsim_node", -1)
    return atom_block, atom_node


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


def cv(values):
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    if m <= 0:
        return 0.0
    var = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var) / m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gsim-time", nargs="+", required=True)
    ap.add_argument("--gsim-members", required=True)
    ap.add_argument("--am-execs", nargs="+", required=True)
    ap.add_argument("--am-block-atom", required=True)
    ap.add_argument("--calib-json", required=True)
    ap.add_argument("--top-k", type=int, default=100)
    ap.add_argument("--out-json", default=None)
    args = ap.parse_args()

    with open(args.calib_json) as f:
        calib = json.load(f)
    g_t0 = calib["gsim"]["rdtsc_overhead"]
    a_t0 = calib["am"]["rdtsc_overhead"]

    g_fire, g_cyc_raw, g_fire_dev, g_reps = merge_reps(load_gsim_time_one, args.gsim_time)
    a_execs, a_cyc_raw, a_kind, a_fire_dev, a_reps = merge_am_reps(args.am_execs)
    members, super_types = load_gsim_members(args.gsim_members)
    atom_block, atom_node = load_am_block_atom(args.am_block_atom)

    # --- overhead correction (per unit, clamped at 0) ----------------------
    g_cyc = {s: max(0.0, g_cyc_raw[s] - g_fire.get(s, 0) * g_t0) for s in g_cyc_raw}
    a_cyc = {b: max(0.0, a_cyc_raw[b] - a_execs.get(b, 0) * a_t0) for b in a_cyc_raw}

    compute_blocks = {b for b in a_execs if a_kind.get(b) == "w"}
    commit_blocks = {b for b in a_execs if a_kind.get(b) == "c"}

    report = {"calibration": calib,
              "repeat_fires_max_dev": {"gsim": g_fire_dev, "am": a_fire_dev}}

    # --- A. totals ----------------------------------------------------------
    g_tot_cyc = sum(g_cyc.values())
    a_compute_cyc = sum(a_cyc.get(b, 0) for b in compute_blocks)
    a_commit_cyc = sum(a_cyc.get(b, 0) for b in commit_blocks)
    a_entry_cyc = sum(a_cyc.get(b, 0) for b in a_execs
                      if a_kind.get(b) not in ("w", "c"))
    report["totals"] = {
        "gsim": {"supers": len(g_fire), "fires": sum(g_fire.values()),
                 "cycles_corr": g_tot_cyc},
        "am_compute": {"blocks": len(compute_blocks),
                       "execs": sum(a_execs.get(b, 0) for b in compute_blocks),
                       "cycles_corr": a_compute_cyc},
        "am_commit": {"blocks": len(commit_blocks),
                      "execs": sum(a_execs.get(b, 0) for b in commit_blocks),
                      "cycles_corr": a_commit_cyc},
        "am_entry_cycles_corr": a_entry_cyc,
    }

    # --- B. closure ----------------------------------------------------------
    g_step = calib["gsim"]["step_cycles"]
    a_eval_ns = calib["am"]["compute_ns"] + calib["am"]["commit_ns"]
    a_eval_cyc = a_eval_ns * calib["am"]["tsc_hz"] / 1.0e9
    report["closure"] = {
        "gsim": {"unit_cycles": g_tot_cyc, "step_cycles": g_step,
                 "ratio": g_tot_cyc / g_step if g_step else None,
                 "inter_block_cycles": g_step - g_tot_cyc},
        "am": {"unit_cycles": a_compute_cyc + a_commit_cyc + a_entry_cyc,
               "eval_cycles_est": a_eval_cyc,
               "ratio": ((a_compute_cyc + a_commit_cyc + a_entry_cyc) / a_eval_cyc
                         if a_eval_cyc else None),
               "inter_block_cycles_est":
                   a_eval_cyc - (a_compute_cyc + a_commit_cyc + a_entry_cyc)},
    }

    # --- C. repeatability -----------------------------------------------------
    g_hot_fire = median(list(g_fire.values())) if g_fire else 0
    a_hot_fire = median(list(a_execs.values())) if a_execs else 0
    g_cvs = [cv(cs) for _, (f, cs) in g_reps.items() if f > g_hot_fire and sum(cs) > 0]
    a_cvs = [cv(cs) for _, (f, cs) in a_reps.items() if f > a_hot_fire and sum(cs) > 0]
    report["repeatability"] = {
        "gsim_hot_units": len(g_cvs),
        "gsim_cv_p50": median(g_cvs) if g_cvs else None,
        "gsim_cv_p90": sorted(g_cvs)[int(0.9 * (len(g_cvs) - 1))] if g_cvs else None,
        "am_hot_units": len(a_cvs),
        "am_cv_p50": median(a_cvs) if a_cvs else None,
        "am_cv_p90": sorted(a_cvs)[int(0.9 * (len(a_cvs) - 1))] if a_cvs else None,
    }

    # --- D. cluster ranking ---------------------------------------------------
    node_super = {}
    for sid, nodes in members.items():
        for n in nodes:
            node_super[n] = sid
    dsu = DSU()
    touched_b, touched_s = set(), set()
    for a, node in atom_node.items():
        if node < 0:
            continue
        sid = node_super.get(node)
        if sid is None:
            continue
        b = atom_block[a]
        if b not in compute_blocks:
            continue
        dsu.union(("b", b), ("s", sid))
        touched_b.add(b)
        touched_s.add(sid)
    clusters = defaultdict(lambda: {"blocks": set(), "supers": set()})
    for b in touched_b:
        clusters[dsu.find(("b", b))]["blocks"].add(b)
    for s in touched_s:
        clusters[dsu.find(("s", s))]["supers"].add(s)

    rows = []
    for root, cl in clusters.items():
        fg = sum(g_fire.get(s, 0) for s in cl["supers"])
        fa = sum(a_execs.get(b, 0) for b in cl["blocks"])
        cg = sum(g_cyc.get(s, 0) for s in cl["supers"])
        ca = sum(a_cyc.get(b, 0) for b in cl["blocks"])
        delta = ca - cg
        per_g = cg / fg if fg else 0.0
        per_a = ca / fa if fa else 0.0
        # Shapley split of delta into count effect and per-fire cost effect.
        count_eff = (fa - fg) * (per_g + per_a) / 2.0
        cost_eff = (per_a - per_g) * (fg + fa) / 2.0
        rows.append({
            "blocks": len(cl["blocks"]), "supers": len(cl["supers"]),
            "gsim_fires": fg, "am_fires": fa,
            "gsim_cycles": round(cg, 1), "am_cycles": round(ca, 1),
            "delta": round(delta, 1),
            "count_effect": round(count_eff, 1), "cost_effect": round(cost_eff, 1),
            "per_fire_gsim": round(per_g, 2), "per_fire_am": round(per_a, 2),
            "super_list": sorted(cl["supers"]), "block_list": sorted(cl["blocks"]),
        })
    rows.sort(key=lambda r: -r["delta"])
    total_pos_delta = sum(r["delta"] for r in rows if r["delta"] > 0)
    cum = 0.0
    top_rows = []
    for rank, r in enumerate(rows[: args.top_k], 1):
        cum += max(r["delta"], 0.0)
        entry = {k: v for k, v in r.items() if k not in ("super_list", "block_list")}
        entry["rank"] = rank
        entry["share_of_pos_delta"] = (r["delta"] / total_pos_delta
                                       if total_pos_delta else 0.0)
        entry["cum_share"] = cum / total_pos_delta if total_pos_delta else 0.0
        # drill-down anchors: gsim super ids of the cluster (cpp_id space) and
        # the dominant super types inside it
        entry["gsim_supers"] = r["super_list"][:16]
        entry["am_blocks"] = r["block_list"][:16]
        type_hist = defaultdict(int)
        for s in r["super_list"]:
            type_hist[super_types.get(s, "?")] += 1
        entry["super_types"] = dict(sorted(type_hist.items(), key=lambda kv: -kv[1]))
        top_rows.append(entry)
    coverage = {}
    cum = 0.0
    marks = {10, 50, 100, 500, 1000, len(rows)}
    for i, r in enumerate(rows, 1):
        cum += max(r["delta"], 0.0)
        if i in marks:
            coverage[f"top{i}"] = cum / total_pos_delta if total_pos_delta else 0.0
    report["ranking"] = {
        "clusters": len(rows),
        "total_pos_delta_cycles": round(total_pos_delta, 1),
        "total_neg_delta_cycles": round(sum(r["delta"] for r in rows if r["delta"] < 0), 1),
        "coverage_of_pos_delta": coverage,
        "top_k": top_rows,
        # full per-cluster rows without member lists (compact diff-friendly)
        "all_clusters_compact": [
            {k: v for k, v in r.items() if k not in ("super_list", "block_list")}
            for r in rows],
    }

    # type attribution: distribute cluster delta to its supers prop. to gsim cycles
    type_delta = defaultdict(float)
    for root, cl in clusters.items():
        fg = sum(g_fire.get(s, 0) for s in cl["supers"])
        cg = sum(g_cyc.get(s, 0) for s in cl["supers"])
        ca = sum(a_cyc.get(b, 0) for b in cl["blocks"])
        delta = ca - cg
        for s in cl["supers"]:
            w = (g_cyc.get(s, 0) / cg) if cg > 0 else 1.0 / max(1, len(cl["supers"]))
            type_delta[super_types.get(s, "?")] += delta * w
    report["delta_by_super_type"] = dict(
        sorted(((t, round(d, 1)) for t, d in type_delta.items()), key=lambda kv: -kv[1]))

    # --- E. commit / entry account -------------------------------------------
    report["commit_account"] = {
        "cycles_corr": a_commit_cyc,
        "share_of_am_unit_cycles": (a_commit_cyc / (a_compute_cyc + a_commit_cyc + a_entry_cyc)
                                    if (a_compute_cyc + a_commit_cyc + a_entry_cyc) else 0.0),
        "entry_cycles_corr": a_entry_cyc,
    }

    text = json.dumps(report, indent=1)
    if args.out_json:
        with open(args.out_json, "w") as f:
            f.write(text + "\n")
    # compact stdout summary
    print(json.dumps({k: report[k] for k in
                      ("totals", "closure", "repeatability", "repeat_fires_max_dev")},
                     indent=1))
    rk = report["ranking"]
    print(f"clusters={rk['clusters']} total_pos_delta={rk['total_pos_delta_cycles']:.3g} "
          f"coverage={json.dumps(rk['coverage_of_pos_delta'])}")
    print("top-10 by delta (am - gsim cycles):")
    for r in rk["top_k"][:10]:
        print(f"  #{r['rank']} d={r['delta']:.6g} (cost {r['cost_effect']:.6g} / "
              f"count {r['count_effect']:.6g}) blocks={r['blocks']} supers={r['supers']} "
              f"per_fire {r['per_fire_gsim']:.3g}->{r['per_fire_am']:.3g} "
              f"types={r['super_types']}")


if __name__ == "__main__":
    main()
