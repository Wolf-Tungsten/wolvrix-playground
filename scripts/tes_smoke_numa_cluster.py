#!/usr/bin/env python3
"""spike: r004 协议修复冒烟——双态复现与 numactl membind 对照（spec tes/DESIGN-r004-overhaul.md §1.1）。

三组各 6 rep（每批 3 个并行，taskset 绑 12/13/14，cores 均在 NUMA node 0）：
  A_base              现状（不包装）
  B_membind_local     numactl --membind=0（同侧）
  C_membind_remote    numactl --membind=1（错位对照）
每 rep 在 +5s/+25s 采样 /proc/<pid>/smaps_rollup(AnonHugePages) 与 numa_maps 节点分布。
持 build/tes/LOCK + 起跑前无其他 emu（与 evaluator 同纪律）。不进 ledger，不占预算。

裁决判据：
  - B 单簇且水位 ≈ A 快簇 → NUMA 放置为根因，启用 config eval.numactl_membind=0；
  - 三组都仍双态 → numactl 无效，聚簇裁决为主修复；
  - C 一致慢、B 一致快 → 错位对照坐实根因（结论同第一支）。

产物：build/tes/grhsim-am-coremark/smoke-<ts>/smoke.json + stdout 汇总表。
"""
from __future__ import annotations

import argparse
import fcntl
import json
import re
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EMU = REPO / "build/xs/gsim/gsim-compile/emu"
EMU_ARGS = ["-i", str(REPO / "testcase/xiangshan/ready-to-run/coremark-2-iteration.bin"),
            "--diff", str(REPO / "testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so"),
            "-b", "0", "-e", "0", "-C", "50000"]
CORES = ["12", "13", "14"]
LOCAL, REMOTE = 0, 1  # cores 12/13/14 ∈ node 0（numactl --hardware 实测）
GROUPS = {"A_base": [],
          "B_membind_local": ["numactl", f"--membind={LOCAL}"],
          "C_membind_remote": ["numactl", f"--membind={REMOTE}"]}
REPS_PER_GROUP = 6
HOST_RE = re.compile(r"Host time spent:\s*([\d,]+)\s*ms")


def sample_proc(pid: int, stop: threading.Event, out: dict) -> None:
    """+5s/+25s 各采一次 THP/NUMA 协变量（只读）。"""
    for delay in (5.0, 20.0):
        if stop.wait(delay):
            return
        try:
            rollup = Path(f"/proc/{pid}/smaps_rollup").read_text(encoding="utf-8")
            m = re.search(r"AnonHugePages:\s+(\d+)\s+kB", rollup)
            if m:
                out["anon_hugepages_kb_max"] = max(out.get("anon_hugepages_kb_max", 0), int(m.group(1)))
            numa = Path(f"/proc/{pid}/numa_maps").read_text(encoding="utf-8")
            pages: dict[str, int] = {}
            for n, p in re.findall(r"\bN(\d+)=(\d+)", numa):
                pages[f"N{n}"] = pages.get(f"N{n}", 0) + int(p)
            out["numa_pages"] = pages
            out["samples"] = out.get("samples", 0) + 1
        except (OSError, ValueError):
            return


def run_rep(group: str, prefix: list[str], rep: int, core: str, outdir: Path, emu: Path) -> dict:
    log = outdir / f"{group}-rep{rep}.log"
    cmd = [*prefix, "taskset", "-c", core, str(emu), *EMU_ARGS]
    state: dict = {}
    stop = threading.Event()
    with open(log, "w") as lf:
        p = subprocess.Popen(cmd, cwd=emu.parent, stdout=lf, stderr=subprocess.STDOUT,
                             start_new_session=True)
        th = threading.Thread(target=sample_proc, args=(p.pid, stop, state), daemon=True)
        th.start()
        rc = p.wait(timeout=1800)
    stop.set()
    text = log.read_text(encoding="utf-8", errors="replace")
    hits = HOST_RE.findall(text)
    return {"group": group, "rep": rep, "core": core, "rc": rc,
            "host_ms": int(hits[-1].replace(",", "")) if hits else None,
            "proc_state": state}


def run_group(group: str, prefix: list[str], outdir: Path, emu: Path) -> list[dict]:
    reps: list[dict] = []
    for start in range(1, REPS_PER_GROUP + 1, len(CORES)):
        with concurrent_batch(group, prefix, start, min(len(CORES), REPS_PER_GROUP - start + 1), outdir, emu) as batch:
            reps.extend(batch)
    return reps


class concurrent_batch:
    """并行起跑 count 个 rep（各绑一个核），全部结束后返回。"""

    def __init__(self, group, prefix, start, count, outdir, emu):
        self.args = (group, prefix, start, count, outdir, emu)

    def __enter__(self):
        group, prefix, start, count, outdir, emu = self.args
        threads, results = [], [None] * count
        for j in range(count):
            def work(idx=j):
                results[idx] = run_rep(group, prefix, start + idx, CORES[idx % len(CORES)], outdir, emu)
            th = threading.Thread(target=work)
            th.start()
            threads.append(th)
        for th in threads:
            th.join()
        return results

    def __exit__(self, *exc):
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--emu", default=str(EMU), help="被测 emu（默认 gsim 基线 emu）")
    ap.add_argument("--groups", default=",".join(GROUPS),
                    help="逗号分隔的组名子集（A_base,B_membind_local,C_membind_remote）")
    args = ap.parse_args()
    emu = Path(args.emu).resolve()
    groups = {g: GROUPS[g] for g in args.groups.split(",")}

    outdir = REPO / "build/tes/grhsim-am-coremark" / f"smoke-{datetime.now():%Y%m%d-%H%M%S}"
    outdir.mkdir(parents=True, exist_ok=True)
    lock = REPO / "build/tes/LOCK"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("[FAIL] LOCK 被占（有评估在跑），稍后再试", file=sys.stderr)
            return 2
        if subprocess.run(["pgrep", "-x", "emu"], capture_output=True).returncode == 0:
            print("[FAIL] 检测到其他 emu 进程", file=sys.stderr)
            return 2

        all_reps: list[dict] = []
        for group, prefix in groups.items():
            print(f"[smoke] group {group} ...", flush=True)
            all_reps.extend(run_group(group, prefix, outdir, emu))

    (outdir / "smoke.json").write_text(json.dumps(all_reps, ensure_ascii=False, indent=2) + "\n")
    print(f"\n{'group':<18} {'reps(host_s)':<48} {'median':>8} {'min':>7} {'max':>7}")
    for group in groups:
        times = sorted(r["host_ms"] for r in all_reps if r["group"] == group and r["host_ms"])
        pretty = " ".join(f"{t/1000:.1f}" for t in times)
        print(f"{group:<18} {pretty:<48} {statistics.median(times)/1000:>7.1f}s "
              f"{times[0]/1000:>6.1f}s {times[-1]/1000:>6.1f}s")
    print(f"\n协变量（每 rep 最后一次采样的 numa_pages / AnonHugePages_max_kb）：")
    for r in all_reps:
        print(f"  {r['group']}-rep{r['rep']}: {r['proc_state']}")
    print(f"raw: {outdir}/smoke.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
