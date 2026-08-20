#!/usr/bin/env python3
"""recon-t0s02 分析：block_execs.txt 按触发频次地标分类，汇总 cycles 分布。

用法: python3 scripts/tes_recon_t0s02_analyze.py <recon_dir>
读 <recon_dir>/block_execs.txt (每行 "block kind execs cycles", kind: w=compute c=commit)
与 stderr 汇总（<recon_dir>/run.log 尾部 [am-profile] 段）。
"""
import sys
from collections import defaultdict
from pathlib import Path

def main() -> None:
    rec = Path(sys.argv[1])
    rows = []
    for line in (rec / "block_execs.txt").read_text().splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        b, kind, execs, cyc = int(parts[0]), parts[1], int(parts[2]), int(parts[3])
        rows.append((b, kind, execs, cyc))
    if not rows:
        print("empty block_execs")
        return
    total_cyc = sum(r[3] for r in rows)
    max_exec = max(r[2] for r in rows)
    print(f"blocks={len(rows)} total_cycles={total_cyc:,} max_execs={max_exec:,}")

    # 按 execs 地标分桶（eval=100,102 round=200,154 cycle=50,051 量级，允许 0.5% 容差）
    landmarks = [("~200k(每round)", 200154), ("~100k(每eval)", 100102), ("~50k(每周期)", 50051)]
    buckets = defaultdict(lambda: [0, 0])  # name -> [blocks, cycles]
    for b, kind, execs, cyc in rows:
        name = None
        for lname, lv in landmarks:
            if abs(execs - lv) <= lv * 0.005:
                name = lname
                break
        if name is None:
            name = "other"
        buckets[(name, kind)][0] += 1
        buckets[(name, kind)][1] += cyc
    print("\n== execs 地标分桶 (blocks / cycles / cyc%) ==")
    for (name, kind), (nb, cyc) in sorted(buckets.items()):
        print(f"{name:18s} {kind} blocks={nb:7d} cycles={cyc:>15,} ({100.0*cyc/total_cyc:5.1f}%)")

    print("\n== compute/commit 分解 ==")
    for kind in ("w", "c"):
        sub = [r for r in rows if r[1] == kind]
        cyc = sum(r[3] for r in sub)
        ex = sum(r[2] for r in sub)
        print(f"{kind} blocks={len(sub):7d} execs={ex:>13,} cycles={cyc:>15,} ({100.0*cyc/total_cyc:5.1f}%)")

    print("\n== top 30 blocks by cycles ==")
    rows.sort(key=lambda r: -r[3])
    for b, kind, execs, cyc in rows[:30]:
        print(f"block {b:7d} {kind} execs={execs:>10,} cycles={cyc:>15,} ({100.0*cyc/total_cyc:5.2f}%) cyc/exec={cyc//max(execs,1):,}")

    # 累积集中度
    acc, s = 0, 0
    print("\n== 集中度 ==")
    for i, r in enumerate(rows, 1):
        acc += r[3]
        for pct in (50, 80, 90, 99):
            if s < pct and 100.0 * acc / total_cyc >= pct:
                print(f"top-{i} blocks = {pct}% cycles")
                s = pct

if __name__ == "__main__":
    main()
