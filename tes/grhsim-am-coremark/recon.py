#!/usr/bin/env python3
"""recon — 对轨迹 tip 做非计时 profiling（正式协议 action，不占 eval 预算）。

用法:
  recon.py --eval-id e00057 --out build/tes/<task>/recon/r004-t0-s00 [--perf]

两种模式：
- 默认（块级 profiling）：生产 emu 编译期关闭了 runtimeProfile（emit 旋钮
  `--runtime-profile` default off），因此用 <eval-id> 的 wbuild 里同 commit 的
  grhsim-am-lower-json 以「生产 emit_args + --runtime-profile」重 emit 到
  <out>/emit，构建 recon emu 到 <out>/emu_build，再以 EMU_RUNTIME_PROFILE=1 +
  EMU_AM_BLOCK_EXECS=<out>/block_execs.txt 跑一遍负载，产出 report.md/report.json
  （[am-profile] 阶段分解 + 全量块 execs/cycles top-50）。difftest 金标校验照旧。
- --perf：不重构建，直接对 <eval-id> 既有生产 emu_build 做 perf record -F 99
  采样（r002「生产 emu perf」用法），产出 perf.txt。

全程持 build/tes/LOCK + 起跑前无其他 emu（同 evaluator 纪律）。本脚本不做正式
计时（规则：正式计时 reps 不开插桩；profiling 是独立的不计时分析 pass）。
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent
REPO = TASK_DIR.parents[1]
CONFIG = json.loads((TASK_DIR / "config.json").read_text(encoding="utf-8"))
PATHS = CONFIG["paths"]
BUILD_ROOT = REPO / "build" / "tes"
BUILD_TASK = BUILD_ROOT / TASK_DIR.name
DESIGN_JSON = next(i["path"] for i in CONFIG["inputs"] if i["name"] == "post_stats_json")

PHASE_RE = re.compile(r"\[am-profile\] time ms: eval ([\d.]+), compute ([\d.]+) \(([\d.]+)%\), "
                      r"commit ([\d.]+) \(([\d.]+)%\), other (-?[\d.]+)")
ACT_RE = re.compile(r"\[am-profile\] activations: forward (\d+), backward (\d+)")
MARKS_RE = re.compile(r"\[am-profile\] changed marks: (\d+), clears (\d+)")
CNT_RE = re.compile(r"instrCnt\s*=\s*([\d,]+),\s*cycleCnt\s*=\s*([\d,]+)")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def build_env_extra() -> dict:
    dep = REPO / PATHS["dep_root"]
    return {
        "CPLUS_INCLUDE_PATH": f"{dep}/usr/include:{dep}/usr/include/x86_64-linux-gnu",
        "LIBRARY_PATH": f"{dep}/usr/lib/x86_64-linux-gnu",
        "CCACHE_DIR": str(BUILD_ROOT / "ccache"),
    }


def sh(cmd: list[str], log: Path, timeout: int, cwd: Path | None = None,
       env_extra: dict | None = None) -> int:
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    with open(log, "ab") as lf:
        lf.write(f"\n===== [{now_iso()}] {' '.join(str(c) for c in cmd)} =====\n".encode())
        lf.flush()
        try:
            return subprocess.run(cmd, cwd=cwd, env=env, stdout=lf,
                                  stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            return 124


def check_golden(profile_log: Path) -> str | None:
    """recon 数据以 difftest 金标为前置；返回 None=通过，否则原因。"""
    text = profile_log.read_text(encoding="utf-8", errors="replace")
    hits = CNT_RE.findall(text)
    if not hits:
        return "profile.log 中无 instrCnt/cycleCnt"
    instr, cyc = int(hits[-1][0].replace(",", "")), int(hits[-1][1].replace(",", ""))
    golden = CONFIG["eval"]["golden"]
    tol = CONFIG["eval"].get("golden_tol", {"instrCnt": 0, "cycleCnt": 0})
    if abs(instr - golden["instrCnt"]) > tol["instrCnt"] or abs(cyc - golden["cycleCnt"]) > tol["cycleCnt"]:
        return f"金标不符: {instr}/{cyc} vs {golden}±{tol}"
    return None


def parse_profile(profile_log: Path, block_execs: Path) -> dict:
    text = profile_log.read_text(encoding="utf-8", errors="replace")
    report: dict = {}
    m = PHASE_RE.search(text)
    if m:
        report["phases"] = {"eval_ms": float(m.group(1)), "compute_ms": float(m.group(2)),
                            "compute_pct": float(m.group(3)), "commit_ms": float(m.group(4)),
                            "commit_pct": float(m.group(5)), "other_ms": float(m.group(6))}
    m = ACT_RE.search(text)
    if m:
        report["activations"] = {"forward": int(m.group(1)), "backward": int(m.group(2))}
    m = MARKS_RE.search(text)
    if m:
        report["changed"] = {"marks": int(m.group(1)), "clears": int(m.group(2))}
    blocks = []
    if block_execs.exists():
        for line in block_execs.read_text(encoding="utf-8").splitlines():
            p = line.split()
            if len(p) == 4:
                blocks.append({"block": int(p[0]), "kind": p[1],
                               "execs": int(p[2]), "cycles": int(p[3])})
    blocks.sort(key=lambda b: -b["cycles"])
    total_cycles = sum(b["cycles"] for b in blocks)
    for b in blocks:
        b["cycles_pct"] = round(100.0 * b["cycles"] / total_cycles, 3) if total_cycles else 0.0
    report["block_count"] = len(blocks)
    report["total_block_cycles"] = total_cycles
    report["top_blocks"] = blocks[:50]
    return report


def write_report(rep: dict, out: Path, eval_id: str, wall_s: float) -> None:
    (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")
    lines = [f"# recon 报告（eval {eval_id}，非计时 profiling）", ""]
    lines.append(f"- 生成于 {now_iso()}，profiling 墙钟 {wall_s:.1f}s（含插桩与 recon 构建，非正式计时）")
    ph = rep.get("phases")
    if ph:
        lines.append(f"- 阶段分解: eval {ph['eval_ms']:.0f}ms = compute {ph['compute_ms']:.0f}ms "
                     f"({ph['compute_pct']}%) + commit {ph['commit_ms']:.0f}ms ({ph['commit_pct']}%) "
                     f"+ other {ph['other_ms']:.0f}ms")
    if rep.get("activations"):
        a = rep["activations"]
        lines.append(f"- activations: forward {a['forward']:,}, backward {a['backward']:,}")
    lines.append(f"- 块总数 {rep.get('block_count')}，总块周期 {rep.get('total_block_cycles', 0):,}")
    lines += ["", "| rank | block | kind | execs | cycles | cycles% |", "|---|---|---|---|---|---|"]
    for i, b in enumerate(rep.get("top_blocks", []), 1):
        lines.append(f"| {i} | {b['block']} | {b['kind']} | {b['execs']:,} | "
                     f"{b['cycles']:,} | {b['cycles_pct']}% |")
    lines.append("")
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")


def find_production_emu(evdir: Path) -> tuple[Path, Path]:
    """返回 (emu 绝对路径, 运行 cwd)。复用 evaluator 的定位顺序。"""
    emu_build = evdir / "emu_build"
    if (emu_build / "emu").exists():
        return (emu_build / "emu").resolve(), emu_build
    real = emu_build / "grhsim-compile" / "emu"
    if real.exists():
        return real.resolve(), emu_build
    raise FileNotFoundError(f"{evdir.name} 无可复用 emu（未构建或已清理）: {emu_build}")


def emu_run_cmd(emu: Path, cycles: int) -> list[str]:
    return [str(emu), "-i", str(REPO / PATHS["coremark_bin"]),
            "--diff", str(REPO / PATHS["nemu_so"]),
            "-b", "0", "-e", "0", "-C", str(cycles)]


def recon_build(evdir: Path, out: Path, emit_args: list[str], ev: dict) -> tuple[Path, Path] | None:
    """用 eval 的 wbuild 里同 commit 的 lower-json，以生产 emit_args + --runtime-profile
    重 emit 并构建 recon emu；返回 (emu, cwd)，失败返回 None。"""
    lower = evdir / "wbuild" / "bin" / "grhsim-am-lower-json"
    if not lower.exists():
        print(f"[FAIL] {evdir.name} 无 wbuild/bin/grhsim-am-lower-json（构建已清理？）",
              file=sys.stderr)
        return None
    emit_dir, emu_build = out / "emit", out / "emu_build"
    for d in (emit_dir, emu_build):
        d.mkdir(parents=True, exist_ok=True)
    rc = sh([str(lower), str(REPO / DESIGN_JSON), "SimTop",
             "--emit", str(emit_dir), *emit_args, "--runtime-profile"],
            out / "recon_emit.log", timeout=ev["build_timeout_sec"])
    if rc != 0 or not (emit_dir / "Makefile").exists():
        print(f"[FAIL] recon emit 失败（rc={rc}，日志 {out}/recon_emit.log）", file=sys.stderr)
        return None
    rc = sh(["make", "-C", str(REPO / PATHS["difftest_dir"]), "emu",
             f"BUILD_DIR={emu_build}", f"GEN_CSRC_DIR={REPO / PATHS['gen_csrc_dir']}",
             "SIM_TOP=SimTop", "NUM_CORES=1", "GRHSIM=1", f"GRHSIM_MODEL_DIR={emit_dir}",
             "WOLVRIX_GRHSIM_WAVEFORM=0", f"VM_BUILD_JOBS={ev['vm_build_jobs']}",
             "WITH_CHISELDB=0", "WITH_CONSTANTIN=0"],
            out / "recon_emu_build.log", timeout=ev["build_timeout_sec"],
            env_extra=build_env_extra())
    emu = emu_build / "grhsim-compile" / "emu"
    if rc != 0 or not emu.exists():
        print(f"[FAIL] recon emu 构建失败（rc={rc}，日志 {out}/recon_emu_build.log）",
              file=sys.stderr)
        return None
    return emu, emu_build


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval-id", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--perf", action="store_true",
                    help="不重构建，对既有生产 emu 做 perf record -F 99 采样")
    args = ap.parse_args()

    evdir = BUILD_TASK / "evals" / args.eval_id
    out = Path(args.out) if Path(args.out).is_absolute() else REPO / args.out
    out.mkdir(parents=True, exist_ok=True)
    rj = evdir / "result.json"
    if not rj.exists():
        print(f"[FAIL] {rj} 不存在", file=sys.stderr)
        return 1
    emit_args = json.loads(rj.read_text(encoding="utf-8")).get("emit_args") or CONFIG["eval"]["emit_args"]
    ev = CONFIG["eval"]

    lock = BUILD_ROOT / "LOCK"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("[FAIL] LOCK 被占（有评估在跑）", file=sys.stderr)
            return 2
        if subprocess.run(["pgrep", "-x", "emu"], capture_output=True).returncode == 0:
            print("[FAIL] 检测到其他 emu 进程", file=sys.stderr)
            return 2

        t0 = time.monotonic()
        if args.perf:
            try:
                emu, cwd = find_production_emu(evdir)
            except FileNotFoundError as exc:
                print(f"[FAIL] {exc}", file=sys.stderr)
                return 1
        else:
            built = recon_build(evdir, out, list(emit_args), ev)
            if built is None:
                return 1
            emu, cwd = built

        cmd = emu_run_cmd(emu, ev["cycles"])
        if args.perf:
            cmd = ["perf", "record", "-F", "99", "-o", str(out / "perf.data"), *cmd]
        cmd = ["taskset", "-c", str(ev["core"]), *cmd]

        env = dict(os.environ)
        if not args.perf:
            env["EMU_RUNTIME_PROFILE"] = "1"
            env["EMU_AM_BLOCK_EXECS"] = str(out / "block_execs.txt")
        rc = sh(cmd, out / "profile.log", timeout=ev["rep_timeout_sec"], cwd=cwd, env_extra=env)
        wall_s = time.monotonic() - t0
        if rc != 0:
            print(f"[FAIL] recon emu 退出码 {rc}（日志 {out}/profile.log）", file=sys.stderr)
            return 1
        err = check_golden(out / "profile.log")
        if err:
            print(f"[FAIL] recon 金标门: {err}", file=sys.stderr)
            return 1

        if args.perf:
            with open(out / "perf.txt", "w") as pf:
                subprocess.run(["perf", "report", "--stdio", "-i", str(out / "perf.data")],
                               stdout=pf, stderr=subprocess.DEVNULL, check=False)
            print(f"[OK] recon(perf) 完成: {out}/perf.txt（eval {args.eval_id}，墙钟 {wall_s:.1f}s）")
            return 0

        rep = parse_profile(out / "profile.log", out / "block_execs.txt")
        rep["eval_id"] = args.eval_id
        rep["emit_args"] = emit_args
        rep["wall_s"] = round(wall_s, 1)
        write_report(rep, out, args.eval_id, wall_s)

    print(f"[OK] recon 完成: {out}/report.md（eval {args.eval_id}，墙钟 {wall_s:.1f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
