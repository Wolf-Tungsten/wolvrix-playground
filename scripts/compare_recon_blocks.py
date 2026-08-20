#!/usr/bin/env python3
"""Compare two recon block_execs.txt dumps (id kind execs cycles).

Usage: compare_recon_blocks.py <old.txt> <new.txt> [topN]
Prints phase totals and the top-N blocks of <new> with old cycles alongside.
NOTE: recon-t0s02 ran WITHOUT wide-detect-fast-path; block ids are stable
across the two emits (same schedule), so per-block joins are meaningful.
"""
import sys
from collections import defaultdict


def load(path):
    rows = {}
    with open(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) != 4:
                continue
            bid, kind, execs, cyc = int(parts[0]), parts[1], int(parts[2]), int(parts[3])
            rows[bid] = (kind, execs, cyc)
    return rows


def main():
    old = load(sys.argv[1])
    new = load(sys.argv[2])
    topn = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    tot_old = sum(r[2] for r in old.values())
    tot_new = sum(r[2] for r in new.values())
    print(f"total ticks: old {tot_old/1e9:.1f}G  new {tot_new/1e9:.1f}G  "
          f"delta {(tot_new-tot_old)/1e9:+.1f}G ({100*(tot_new-tot_old)/tot_old:+.1f}%)")
    for kind, name in (("w", "compute"), ("c", "commit")):
        so = sum(r[2] for r in old.values() if r[0] == kind)
        sn = sum(r[2] for r in new.values() if r[0] == kind)
        print(f"{name}: old {so/1e9:.1f}G ({100*so/tot_old:.1f}%)  new {sn/1e9:.1f}G "
              f"({100*sn/tot_new:.1f}%)  delta {(sn-so)/1e9:+.1f}G")
    ranked = sorted(new.items(), key=lambda kv: -kv[1][2])
    print(f"\ntop {topn} blocks by new cycles:")
    cum = 0
    for bid, (kind, execs, cyc) in ranked[:topn]:
        oc = old.get(bid, (kind, 0, 0))[2]
        cum += cyc
        print(f"  b{bid} {kind} execs={execs:7d} new={cyc/1e9:6.2f}G old={oc/1e9:6.2f}G "
              f"delta={(cyc-oc)/1e9:+6.2f}G cyc/exec={cyc/max(execs,1):8.0f} "
              f"cum%={100*cum/tot_new:5.1f}")
    # aggregates for known pools
    guards = [90656, 90657]
    g_new = sum(new[b][2] for b in guards if b in new)
    print(f"\nguard pool (90656+90657): new {g_new/1e9:.2f}G = {100*g_new/tot_new:.2f}% of ticks")
    top50 = sum(c for _, (_, _, c) in ranked[:50])
    print(f"top-50 share of new ticks: {100*top50/tot_new:.1f}%")


if __name__ == "__main__":
    main()
