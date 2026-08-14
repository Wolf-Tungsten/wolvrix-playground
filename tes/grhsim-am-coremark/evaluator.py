#!/usr/bin/env python3
"""evaluate — TES 的评估器 V。给定一个 wolvrix 现场（worktree），执行完整评估流水线：

  wolvrix 构建（Release + ccache）→ ctest -R grhsim 回归门 → emit（固定 exec-GRH 输入）
  → difftest emu 构建 → 绑核串行计时 reps（difftest 金标门 + CV 检查）

输出 build/tes/evals/<eval_id>/result.json，并把机器可读摘要打到 stdout。
整个过程持 flock(build/tes/LOCK) —— 任何时刻只允许一个评估在跑（串行纪律的硬保证）。

模式：
  run   --worktree <path> --eval-id eNNNNN   候选/AM 基线全流水线评估
  gsim  --eval-id eNNNNN                     gsim 基线：对现存 gsim emu 只做协议化计时 reps
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent          # tes/<task>/
TASK = TASK_DIR.name
REPO = TASK_DIR.parents[1]                           # playground 根
CONFIG = json.loads((TASK_DIR / "config.json").read_text(encoding="utf-8"))
PATHS = CONFIG["paths"]
EVAL_CFG = CONFIG["eval"]
BUILD_ROOT = REPO / "build" / "tes"                  # 全局：LOCK、ccache
BUILD_TASK = BUILD_ROOT / TASK                       # 本任务：evals/、src/

HOST_RE = re.compile(r"Host time spent:\s*([\d,]+)\s*ms")
CNT_RE = re.compile(r"instrCnt\s*=\s*([\d,]+),\s*cycleCnt\s*=\s*([\d,]+)")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def loadavg() -> str:
    with open("/proc/loadavg", encoding="ascii") as f:
        return " ".join(f.read().split()[:3])


def sh(cmd: list[str], log: Path, timeout: int, cwd: Path | None = None,
       env_extra: dict | None = None) -> tuple[int, float]:
    """跑命令，输出进 log，返回 (returncode, 耗时秒)。超时杀进程组返回 124。"""
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    t0 = time.monotonic()
    with open(log, "ab") as lf:
        lf.write(f"\n===== [{now_iso()}] {' '.join(str(c) for c in cmd)} =====\n".encode())
        lf.flush()
        try:
            p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=lf, stderr=subprocess.STDOUT,
                                 start_new_session=True)
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            import signal
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
            rc = 124
    return rc, time.monotonic() - t0


def parse_run_log(log: Path) -> dict:
    host_ms, instr, cyc = None, None, None
    with open(log, "rb") as f:
        text = f.read().decode("utf-8", errors="replace")
    m = HOST_RE.search(text)
    if m:
        host_ms = int(m.group(1).replace(",", ""))
    m = CNT_RE.search(text)
    if m:
        instr = int(m.group(1).replace(",", ""))
        cyc = int(m.group(2).replace(",", ""))
    return {"host_ms": host_ms, "instrCnt": instr, "cycleCnt": cyc}


def no_other_emu() -> bool:
    r = subprocess.run(["pgrep", "-x", "emu"], capture_output=True)
    return r.returncode != 0


def run_reps(emu: Path, run_dir: Path, run_cwd: Path | None = None) -> dict:
    """协议化计时 reps。返回 {status, reps:[...], median, cv, noisy}。

    emu 可为绝对路径或 run_cwd 下的相对名（如 Path("emu") + run_cwd=emu 构建目录）。
    """
    ev = EVAL_CFG
    golden = ev["golden"]
    reps: list[dict] = []
    status = "ok"
    target_reps = ev["reps"]
    cwd = run_cwd or run_dir
    while True:
        i = len(reps) + 1
        if not no_other_emu():
            return {"status": "interference", "reps": reps,
                    "error": "检测到其他 emu 进程，计时前中止（干扰守卫）"}
        load = loadavg()
        log = run_dir / f"rep{i}.log"
        rc, dur = sh(["taskset", "-c", str(ev["core"]), str(emu),
                      "-i", str(REPO / PATHS["coremark_bin"]),
                      "--diff", str(REPO / PATHS["nemu_so"]),
                      "-b", "0", "-e", "0", "-C", str(ev["cycles"])],
                     log, timeout=ev["rep_timeout_sec"], cwd=cwd)
        parsed = parse_run_log(log)
        rep = {"rep": i, "rc": rc, "wall_s": round(dur, 1), "loadavg_before": load,
               **parsed}
        rep["difftest_ok"] = (
            rc == 0 and parsed["instrCnt"] == golden["instrCnt"]
            and parsed["cycleCnt"] == golden["cycleCnt"])
        reps.append(rep)
        if rc == 124:
            status = "timeout"
            break
        if not rep["difftest_ok"]:
            status = "difftest_fail"
            break
        if len(reps) >= target_reps:
            times = [r["host_ms"] for r in reps if r["host_ms"] is not None]
            if len(times) != len(reps):
                status = "parse_fail"
                break
            cv = statistics.stdev(times) / statistics.mean(times) if len(times) > 1 else 0.0
            if cv <= ev["cv_max"] or len(reps) >= ev["max_reps"]:
                break
            target_reps = min(len(reps) + 1, ev["max_reps"])  # 超噪声带则加测
    times = [r["host_ms"] for r in reps if r["host_ms"] is not None]
    out = {"status": status, "reps": reps}
    if times and all(r["difftest_ok"] for r in reps):
        med = statistics.median(times)
        cv = statistics.stdev(times) / statistics.mean(times) if len(times) > 1 else 0.0
        out.update({"host_ms": {"reps": times, "median": med, "cv": round(cv, 4)},
                    "noisy": cv > ev["cv_max"], "score": -med})
    return out


def build_env_extra() -> dict:
    dep = REPO / PATHS["dep_root"]
    return {
        "CPLUS_INCLUDE_PATH": f"{dep}/usr/include:{dep}/usr/include/x86_64-linux-gnu",
        "LIBRARY_PATH": f"{dep}/usr/lib/x86_64-linux-gnu",
        "CCACHE_DIR": str(BUILD_ROOT / "ccache"),  # 跨任务共享（同一代码库的编译缓存）
    }


def evaluate_candidate(worktree: Path, eval_id: str, emit_args_override: list[str] | None) -> dict:
    evdir = BUILD_TASK / "evals" / eval_id
    wbuild, emit_dir, emu_build, run_dir = (evdir / d for d in ("wbuild", "emit", "emu_build", "run"))
    for d in (wbuild, emit_dir, emu_build, run_dir):
        d.mkdir(parents=True, exist_ok=True)
    logs = {"dir": str(evdir.relative_to(REPO))}
    result: dict = {"eval_id": eval_id, "worktree": str(worktree), "started_at": now_iso(),
                    "status": "ok", "logs": logs}

    commit = subprocess.run(["git", "-C", str(worktree), "rev-parse", "HEAD"],
                            capture_output=True, text=True)
    result["commit"] = commit.stdout.strip() if commit.returncode == 0 else None

    # 1. wolvrix 构建
    cmake_args = ["-S", str(worktree), "-B", str(wbuild),
                  "-DCMAKE_BUILD_TYPE=Release", "-G", "Unix Makefiles"]
    if shutil.which("ccache"):
        cmake_args += ["-DCMAKE_CXX_COMPILER_LAUNCHER=ccache", "-DCMAKE_C_COMPILER_LAUNCHER=ccache"]
    rc, dur = sh(["cmake", *cmake_args], evdir / "cmake.log", timeout=EVAL_CFG["build_timeout_sec"])
    if rc != 0:
        result.update(status="build_fail", phase="cmake")
        return result
    rc, dur = sh(["cmake", "--build", str(wbuild), "-j", str(os.cpu_count() or 8)],
                 evdir / "build.log", timeout=EVAL_CFG["build_timeout_sec"])
    result.setdefault("timings", {})["wolvrix_build_s"] = round(dur, 1)
    if rc != 0:
        result.update(status="build_fail", phase="build")
        return result

    # 2. ctest 回归门
    if EVAL_CFG["ctest_gate"]:
        rc, _ = sh(["ctest", "--test-dir", str(wbuild), "-R", EVAL_CFG["ctest_regex"],
                    "--output-on-failure"], evdir / "ctest.log", timeout=3600)
        result["gates"] = {"ctest": rc == 0}
        if rc != 0:
            result.update(status="ctest_fail", phase="ctest")
            return result

    # 3. emit
    emit_args = emit_args_override if emit_args_override is not None else EVAL_CFG["emit_args"]
    rc, dur = sh([str(wbuild / "bin" / "grhsim-am-lower-json"),
                  str(REPO / PATHS["exec_json"]), "SimTop", "--schedule",
                  "--emit", str(emit_dir), *emit_args],
                 evdir / "emit.log", timeout=EVAL_CFG["build_timeout_sec"],
                 env_extra={"WOLVRIX_GRHSIM_AM_BLOCK_ATOM_JSONL": str(evdir / "block_atom.jsonl")})
    result["timings"]["emit_s"] = round(dur, 1)
    result["emit_args"] = emit_args
    if rc != 0 or not (emit_dir / "Makefile").exists():
        result.update(status="emit_fail", phase="emit")
        return result

    # 4. emu 构建
    rc, dur = sh(["make", "-C", str(REPO / PATHS["difftest_dir"]), "emu",
                  f"BUILD_DIR={emu_build}",
                  f"GEN_CSRC_DIR={REPO / PATHS['gen_csrc_dir']}",
                  "SIM_TOP=SimTop", "NUM_CORES=1", "GRHSIM=1",
                  f"GRHSIM_MODEL_DIR={emit_dir}",
                  "WOLVRIX_GRHSIM_WAVEFORM=0",
                  f"VM_BUILD_JOBS={EVAL_CFG['vm_build_jobs']}",
                  "WITH_CHISELDB=0", "WITH_CONSTANTIN=0"],
                 evdir / "emu_build.log", timeout=EVAL_CFG["build_timeout_sec"],
                 env_extra=build_env_extra())
    result["timings"]["emu_build_s"] = round(dur, 1)
    emu_real = emu_build / "grhsim-compile" / "emu"
    if rc != 0 or not emu_real.exists():
        result.update(status="build_fail", phase="emu_build")
        return result

    # 5. 计时 reps（优先从 emu 构建目录用根符号链运行，与历史脚本一致）
    if (emu_build / "emu").exists():
        reps = run_reps(Path("emu"), run_dir, run_cwd=emu_build)
    else:
        reps = run_reps(emu_real, run_dir)
    result.update(reps)
    return result


def evaluate_gsim(eval_id: str) -> dict:
    evdir = BUILD_TASK / "evals" / eval_id
    run_dir = evdir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    emu = REPO / PATHS["gsim_emu"]
    result: dict = {"eval_id": eval_id, "mode": "gsim-baseline", "emu": str(emu.relative_to(REPO)),
                    "started_at": now_iso(), "logs": {"dir": str(evdir.relative_to(REPO))}}
    if not emu.exists():
        result.update(status="missing", error=f"gsim emu 不存在: {emu}")
        return result
    emu_real = emu.resolve()
    reps = run_reps(emu_real, run_dir, run_cwd=emu_real.parent)
    result.update(reps)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--worktree", required=True)
    p.add_argument("--eval-id", required=True)
    p.add_argument("--emit-args", default=None,
                   help="覆盖 config 的 emit_args（单个字符串，内部按空白切分）")
    p = sub.add_parser("gsim")
    p.add_argument("--eval-id", required=True)
    args = ap.parse_args()

    lock = BUILD_ROOT / "LOCK"  # 全局锁：测量干扰是机器级的，跨任务也只允许一个评估
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("[FAIL] 另一个 TES 评估正在运行（LOCK 持有中）。串行纪律：稍后再试。", file=sys.stderr)
            return 2

        if args.cmd == "run":
            wt = Path(args.worktree)
            if not wt.is_absolute():
                wt = REPO / wt
            override = args.emit_args.split() if args.emit_args else None
            result = evaluate_candidate(wt, args.eval_id, override)
        else:
            result = evaluate_gsim(args.eval_id)

    evdir = BUILD_TASK / "evals" / args.eval_id
    evdir.mkdir(parents=True, exist_ok=True)
    result["finished_at"] = now_iso()
    with open(evdir / "result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps({k: result.get(k) for k in
                      ("eval_id", "status", "score", "host_ms", "noisy", "timings")},
                     ensure_ascii=False))
    print(f"result: {evdir.relative_to(REPO)}/result.json")
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
