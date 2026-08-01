#!/usr/bin/env python3

"""P0 array inventory (docs/27): cluster kRegister symbols of a GRH graph by
naming pattern (`base_<digits>[_field]`, instance-path keyed), then match
clusters against the reg-to-mem group report to separate:

- discovered & rejected (still exploded, outcome known from the report),
- discovered & merged (gone from E1, only relevant for the pre graph),
- never-discovered arrays (clusters that match no report group),
- scalars (clusters smaller than --min-size).

Cluster key: (instance path, name pattern with every `_<digits>` run replaced
by `_#`, width). Multi-dim arrays (`usefulCtrs_0_0_value`) collapse into one
cluster; matching to report groups uses width + divisibility
(group.element_count divides cluster size), which is approximate — flagged.

Usage:

    p0_array_clusters.py --e1 /tmp/grh_e1_index.pkl [--pre /tmp/grh_pre_index.pkl] \
        --report /tmp/r2m_report_r1.json --ledger /tmp/p0_ledger.json \
        --min-size 4 --json /tmp/p0_clusters.json
"""

from __future__ import annotations

import argparse
import json
import pickle
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

IDX_RUN = re.compile(r"_\d+")


def load_index(path: str):
    with open(path, "rb") as fh:
        return pickle.load(fh)


def cluster_registers(ops, meta, min_size: int):
    """Return clusters: key -> {members, width, locfiles, path, pattern}."""
    clusters: dict[tuple, dict] = {}
    n_reg = 0
    for sym, m in meta.items():
        if ops[sym][0] != "kRegister":
            continue
        n_reg += 1
        locfile, _target, width = m
        if "$" in sym:
            path, _, name = sym.rpartition("$")
        else:
            path, name = "", sym
        pattern = IDX_RUN.sub("_#", name)
        # Entry indices may live in the instance path (hierarchically
        # unrolled arrays, e.g. MSHR_64: `slices_0$ms_0$req_channel`) —
        # strip `_<digits>` runs from each path component as well.
        path_pattern = "$".join(IDX_RUN.sub("_#", comp) for comp in path.split("$"))
        key = (path_pattern, pattern, width)
        c = clusters.get(key)
        if c is None:
            c = clusters[key] = {
                "path": path_pattern,
                "pattern": pattern,
                "width": width,
                "members": [],
                "locfiles": Counter(),
            }
        c["members"].append(sym)
        c["locfiles"][locfile] += 1
    small = {k: c for k, c in clusters.items() if len(c["members"]) < min_size}
    big = {k: c for k, c in clusters.items() if len(c["members"]) >= min_size}
    return big, small, n_reg


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--e1", required=True)
    ap.add_argument("--pre", default=None)
    ap.add_argument("--report", required=True)
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--min-size", type=int, default=4)
    ap.add_argument("--json", required=True)
    args = ap.parse_args()

    started = time.time()
    report = json.loads(Path(args.report).read_text())
    groups = report["groups"]

    # Group stats by (width, count) for matching.
    group_keys = Counter((g["element_width"], g["element_count"]) for g in groups)
    rejected_keys = Counter(
        (g["element_width"], g["element_count"])
        for g in groups
        if g["outcome"] != "true_merged"
    )

    out = {"graphs": {}}

    for label, path in (("e1", args.e1), ("pre", args.pre)):
        if not path:
            continue
        ops, _defs, meta = load_index(path)
        big, small, n_reg = cluster_registers(ops, meta, args.min_size)
        rows = []
        matched_rejected = 0
        matched_any = 0
        undiscovered_regs = 0
        for (cpath, pattern, width), c in big.items():
            size = len(c["members"])
            # Match heuristic: exact (width,size) group, or a group whose
            # element_count divides the cluster size (2-D arrays split into
            # per-slice groups, e.g. tage usefulCtrs_<b>_<w>_value).
            exact = group_keys.get((width, size), 0)
            div_matches = 0
            if not exact:
                for (gw, gc), n in group_keys.items():
                    if gw == width and gc < size and size % gc == 0:
                        div_matches += n
            rej = rejected_keys.get((width, size), 0)
            discovered = exact > 0 or div_matches > 0
            top_loc = c["locfiles"].most_common(2)
            rows.append(
                {
                    "path_tail": "$".join([p for p in cpath.split("$") if p][-5:]),
                    "pattern": pattern,
                    "width": width,
                    "size": size,
                    "loc": top_loc,
                    "match": "exact" if exact else ("div" if div_matches else "none"),
                    "n_exact_groups": exact,
                    "n_rejected_groups_exact": rej,
                }
            )
            if discovered:
                matched_any += size
                if rej or any(
                    rejected_keys.get((width, gc))
                    for (gw, gc) in group_keys
                    if gw == width and size % gc == 0
                ):
                    matched_rejected += size
            else:
                undiscovered_regs += size
        rows.sort(key=lambda r: -r["size"])
        small_regs = sum(len(c["members"]) for c in small.values())
        out["graphs"][label] = {
            "registers": n_reg,
            "clusters>=min": len(big),
            "cluster_regs": sum(len(c["members"]) for c in big.values()),
            "small_cluster_regs": small_regs,
            "matched_any_regs": matched_any,
            "matched_rejected_regs": matched_rejected,
            "undiscovered_regs": undiscovered_regs,
            "top_clusters": rows,
        }
        print(
            f"[{label}] registers={n_reg} clusters>={args.min_size}: {len(big)} "
            f"covering {out['graphs'][label]['cluster_regs']} regs; "
            f"small: {len(small)} clusters / {small_regs} regs; "
            f"undiscovered(estimate): {undiscovered_regs} regs "
            f"({time.time()-started:.0f}s)",
            flush=True,
        )
        del ops, meta, big, small

    Path(args.json).write_text(json.dumps(out, ensure_ascii=False) + "\n")
    print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
