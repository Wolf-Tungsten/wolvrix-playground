#!/usr/bin/env python3
"""分析 emit 中 array_broadcast_words / array_mux_words 的分布与动态成本。

用法: python3 scripts/tes_recon_wide_mux_analyze.py <recon_dir>
联合 <recon_dir>/emit/grhsim_SimTop_blocks_*.cpp 与 block_execs.txt，
按块汇总 broadcast/mux 调用数、位宽、动态 tick，估算 broadcast→mux 链融合
（消除中间物化）可触达的池规模。
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

BLOCK_RE = re.compile(r"// ===== block (\d+) role=(\w+) atoms=(\d+) instrs=(\d+) =====")
BCAST_RE = re.compile(r"array_broadcast_words\(wideValues_\.data\(\) \+ (\d+), (\d+), (&?\w+[^,]*), (\d+)\)")
MUX_RE = re.compile(r"array_mux_words\(wideValues_\.data\(\) \+ (\d+), (\d+), wideValues_\.data\(\) \+ (\d+), wideValues_\.data\(\) \+ (\d+), wideValues_\.data\(\) \+ (\d+), (\d+)\)")


def main() -> None:
    rec = Path(sys.argv[1])
    emit = rec / "emit"
    ticks = {}
    for line in (rec / "block_execs.txt").read_text().splitlines():
        p = line.split()
        if len(p) == 4:
            ticks[int(p[0])] = (p[1], int(p[2]), int(p[3]))
    total_ticks = sum(v[2] for v in ticks.values())

    # per-block: list of (kind, packed_width, target_off, t_off, f_off, elem_width)
    blocks = defaultdict(list)
    cur = None
    for cpp in sorted(emit.glob("grhsim_SimTop_blocks_*.cpp")):
        for line in cpp.read_text().splitlines():
            m = BLOCK_RE.search(line)
            if m:
                cur = int(m.group(1))
                continue
            if cur is None:
                continue
            mb = BCAST_RE.search(line)
            if mb:
                blocks[cur].append(("bcast", int(mb.group(2)), int(mb.group(1)),
                                    mb.group(3), None, int(mb.group(4))))
                continue
            mm = MUX_RE.search(line)
            if mm:
                blocks[cur].append(("mux", int(mm.group(2)), int(mm.group(1)),
                                    int(mm.group(4)), int(mm.group(5)), int(mm.group(6))))

    # 判定链：mux 的 t 输入是某 bcast 的 target（同 offset），或 mux 的 f 输入是上一个 mux 的 target
    print(f"total_ticks={total_ticks:,}")
    hdr = f"{'block':>8} {'ticks(G)':>9} {'tick%':>6} {'execs':>8} {'bcast':>5} {'mux':>4} {'chain':>5} {'pw':>6}"
    print(hdr)
    rows = []
    for b, ops in blocks.items():
        bcasts = {o[2]: o for o in ops if o[0] == "bcast"}
        chain = 0
        for o in ops:
            if o[0] != "mux":
                continue
            t_off, f_off = o[3], o[4]
            t_is_bcast = t_off in bcasts
            f_is_mux = any(p[0] == "mux" and p[2] == f_off for p in ops)
            if t_is_bcast or f_is_mux:
                chain += 1
        kind, execs, cyc = ticks.get(b, ("?", 0, 0))
        nb = sum(1 for o in ops if o[0] == "bcast")
        nm = sum(1 for o in ops if o[0] == "mux")
        pws = sorted({o[1] for o in ops})
        rows.append((cyc, b, execs, nb, nm, chain, pws))
    rows.sort(reverse=True)
    cum_chain_ticks = 0
    for cyc, b, execs, nb, nm, chain, pws in rows:
        pct = 100.0 * cyc / total_ticks
        flag = ""
        if chain:
            cum_chain_ticks += cyc
            flag = "<= CHAIN"
        print(f"{b:>8} {cyc/1e9:>9.2f} {pct:>5.2f} {execs:>8} {nb:>5} {nm:>4} {chain:>5} {str(pws[:3]):>6} {flag}")
    print(f"\n含链块 tick 合计: {cum_chain_ticks/1e9:.2f}G = {100.0*cum_chain_ticks/total_ticks:.2f}%")


if __name__ == "__main__":
    main()
