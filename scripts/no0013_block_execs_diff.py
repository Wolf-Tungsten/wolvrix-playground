#!/usr/bin/env python3
"""NO0013 Phase C: per-block execs/cycles diff between two EMU_AM_BLOCK_EXECS dumps.

Input format per line: "<block> <w> <execs> <cycles>".

Usage: no0013_block_execs_diff.py <before.txt> <after.txt> [--top N]
Prints the blocks with the largest absolute cycle deltas (regressions first
and improvements first), plus totals; block ids are comparable across runs
only when both emus were built from the same program (same partition), which
holds for NO0013 (emitter-only changes).
"""
import sys
from collections import defaultdict


def load(path):
    cycles = defaultdict(int)
    execs = defaultdict(int)
    with open(path, 'r', encoding='utf-8') as fh:
        for line in fh:
            parts = line.split()
            if len(parts) >= 4 and parts[0].lstrip('-').isdigit():
                b = int(parts[0])
                execs[b] += int(parts[2])
                cycles[b] += int(parts[3])
    return execs, cycles


def main():
    before_path, after_path = sys.argv[1], sys.argv[2]
    top = 25
    if '--top' in sys.argv:
        top = int(sys.argv[sys.argv.index('--top') + 1])
    bexec, bcyc = load(before_path)
    aexec, acyc = load(after_path)
    blocks = set(bcyc) | set(acyc)
    rows = []
    for b in blocks:
        delta = acyc.get(b, 0) - bcyc.get(b, 0)
        rows.append((b, bcyc.get(b, 0), acyc.get(b, 0), delta,
                     bexec.get(b, 0), aexec.get(b, 0)))
    total_b = sum(bcyc.values())
    total_a = sum(acyc.values())
    print(f"total cycles: before={total_b / 1e9:.2f}G after={total_a / 1e9:.2f}G "
          f"delta={(total_a - total_b) / 1e9:+.2f}G")
    rows.sort(key=lambda r: -r[3])
    print("\n== regressions (after - before, descending) ==")
    for b, before, after, delta, be, ae in rows[:top]:
        if delta <= 0:
            break
        pf_b = before / max(be, 1) / 1e3
        pf_a = after / max(ae, 1) / 1e3
        print(f"b{b:<7d} {before / 1e9:8.2f}G -> {after / 1e9:8.2f}G "
              f"delta={delta / 1e9:+7.2f}G execs {be}->{ae} "
              f"perfire {pf_b:.1f}K->{pf_a:.1f}K")
    print("\n== improvements (delta ascending) ==")
    rows.sort(key=lambda r: r[3])
    for b, before, after, delta, be, ae in rows[:top]:
        if delta >= 0:
            break
        pf_b = before / max(be, 1) / 1e3
        pf_a = after / max(ae, 1) / 1e3
        print(f"b{b:<7d} {before / 1e9:8.2f}G -> {after / 1e9:8.2f}G "
              f"delta={delta / 1e9:+7.2f}G execs {be}->{ae} "
              f"perfire {pf_b:.1f}K->{pf_a:.1f}K")


if __name__ == '__main__':
    main()
