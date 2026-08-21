#!/usr/bin/env python3
"""evaluate — TES 的评估器 V。给定一个 wolvrix 现场（worktree），执行完整评估流水线：

  wolvrix 构建（Release + ccache）→ ctest -R grhsim 回归门 → emit（固定 post-stats
  GRH 输入，wolvrix 自解析 XiangShan SV 的归一化产物）→ difftest emu 构建
  → 绑核并行计时 reps（每 rep 独立物理核，difftest 金标门 + CV 检查）

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


def load_frozen_eval_config() -> dict:
    """Use the active run snapshot so config edits cannot change a run in flight."""
    run_path = TASK_DIR / "state" / "run.json"
    if run_path.exists():
        run = json.loads(run_path.read_text(encoding="utf-8"))
        if run.get("status") == "active" and run.get("task") == TASK:
            return run["config"]["eval"]
    return CONFIG["eval"]


EVAL_CFG = load_frozen_eval_config()
DESIGN_JSON = next(i["path"] for i in CONFIG["inputs"] if i["name"] == "post_stats_json")
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
    # 日志为 append 式（重测同 eval-id 会叠加新段）：取最后一次匹配，
    # 保证重跑覆盖时读到的是最新一轮的计数/计时。
    hits = HOST_RE.findall(text)
    if hits:
        host_ms = int(hits[-1].replace(",", ""))
    hits = CNT_RE.findall(text)
    if hits:
        instr = int(hits[-1][0].replace(",", ""))
        cyc = int(hits[-1][1].replace(",", ""))
    return {"host_ms": host_ms, "instrCnt": instr, "cycleCnt": cyc}


def no_other_emu() -> bool:
    r = subprocess.run(["pgrep", "-x", "emu"], capture_output=True)
    return r.returncode != 0


def _median(values: list[int]) -> int | float:
    value = statistics.median(values)
    return int(value) if float(value).is_integer() else value


def _cv(values: list[int]) -> float:
    return statistics.stdev(values) / statistics.mean(values) if len(values) > 1 else 0.0


def _run_rep_batch(emu: Path, cwd: Path, run_dir: Path,
                   start_idx: int, count: int, cores: list[str]) -> list[dict]:
    """并行起跑 count 个 rep（各绑 rep_cores 中不同物理核），全部结束后按 rep 序返回。

    干扰守卫在批次起跑前检查一次（批内 emu 是本评估自己的并行 rep）。
    每 rep 独立 rep 超时（kill 进程组记 rc=124）。返回未经金标判定的原始结果。
    """
    import signal
    ev = EVAL_CFG
    timeout = ev["rep_timeout_sec"]
    if not no_other_emu():
        return [{"rep": start_idx, "rc": None, "interference": True,
                 "error": "检测到其他 emu 进程，计时前中止（干扰守卫）"}]
    load = loadavg()
    procs = []
    for j in range(count):
        i = start_idx + j
        core = cores[j % len(cores)]
        log = run_dir / f"rep{i}.log"
        cmd = ["taskset", "-c", str(core), str(emu),
               "-i", str(REPO / PATHS["coremark_bin"]),
               "--diff", str(REPO / PATHS["nemu_so"]),
               "-b", "0", "-e", "0", "-C", str(ev["cycles"])]
        lf = open(log, "ab")
        lf.write(f"\n===== [{now_iso()}] {' '.join(str(c) for c in cmd)} =====\n".encode())
        lf.flush()
        p = subprocess.Popen(cmd, cwd=cwd, env=dict(os.environ), stdout=lf,
                             stderr=subprocess.STDOUT, start_new_session=True)
        procs.append({"rep": i, "core": core, "popen": p, "log": log, "lf": lf,
                      "t0": time.monotonic(), "rc": None})
    pending = list(procs)
    while pending:
        for pr in list(pending):
            rc = pr["popen"].poll()
            if rc is None and time.monotonic() - pr["t0"] > timeout:
                os.killpg(pr["popen"].pid, signal.SIGKILL)
                pr["popen"].wait()
                pr["rc"] = 124
            elif rc is not None:
                pr["rc"] = rc
            if pr["rc"] is not None:
                pr["wall_s"] = round(time.monotonic() - pr["t0"], 1)
                pr["lf"].close()
                pending.remove(pr)
        if pending:
            time.sleep(1)
    out = []
    for pr in procs:
        parsed = parse_run_log(pr["log"])
        out.append({"rep": pr["rep"], "core": pr["core"], "rc": pr["rc"],
                    "wall_s": pr["wall_s"], "loadavg_before": load, **parsed})
    return out


def run_reps(emu: Path, run_dir: Path, run_cwd: Path | None = None) -> dict:
    """协议化计时固定 reps，返回状态、原始 reps 与 Host 时间中位。

    emu 可为绝对路径或 run_cwd 下的相对名（如 Path("emu") + run_cwd=emu 构建目录）。
    reps 批内并行：每 rep 绑 eval.rep_cores 中一个独立物理核（缺省退回 eval.core
    单核串行语义）；批次间串行。rep 数由 run manifest 冻结，不因 CV 自适应扩增。
    """
    ev = EVAL_CFG
    golden = ev["golden"]
    tol = ev.get("golden_tol", {"instrCnt": 0, "cycleCnt": 0})
    cores = [str(c) for c in (ev.get("rep_cores") or [ev["core"]])]
    reps: list[dict] = []
    status = "ok"
    target_reps = ev["reps"]
    cwd = run_cwd or run_dir
    if not emu.is_absolute():
        emu = (cwd / emu).resolve()  # execvp 不搜 cwd，相对名必须解析成绝对路径
    while len(reps) < target_reps:
        batch = _run_rep_batch(emu, cwd, run_dir, len(reps) + 1,
                               min(target_reps - len(reps), len(cores)), cores)
        reps.extend(batch)
        if any(r.get("interference") for r in batch):
            return {"status": "interference", "reps": reps,
                    "error": "检测到其他 emu 进程，计时前中止（干扰守卫）"}
        if any(r["rc"] == 124 for r in batch):
            status = "timeout"
            break
        for r in batch:
            instr, cyc = r["instrCnt"], r["cycleCnt"]
            r["difftest_ok"] = (
                r["rc"] == 0 and instr is not None and cyc is not None
                and abs(instr - golden["instrCnt"]) <= tol["instrCnt"]
                and abs(cyc - golden["cycleCnt"]) <= tol["cycleCnt"])
        if any(not r["difftest_ok"] for r in batch):
            status = "difftest_fail"
            break
        times = [r["host_ms"] for r in reps if r["host_ms"] is not None]
        if len(times) != len(reps):
            status = "parse_fail"
            break
    times = [r["host_ms"] for r in reps if r["host_ms"] is not None]
    out = {"status": status, "reps": reps}
    if times and all(r.get("difftest_ok") for r in reps):
        median = _median(times)
        cv = _cv(times)
        out.update({"host_ms": {"reps": times, "median": median, "cv": round(cv, 4)},
                    "noisy": cv > ev["cv_max"], "score": -median})
    return out


def build_env_extra() -> dict:
    dep = REPO / PATHS["dep_root"]
    return {
        "CPLUS_INCLUDE_PATH": f"{dep}/usr/include:{dep}/usr/include/x86_64-linux-gnu",
        "LIBRARY_PATH": f"{dep}/usr/lib/x86_64-linux-gnu",
        "CCACHE_DIR": str(BUILD_ROOT / "ccache"),  # 跨任务共享（同一代码库的编译缓存）
    }


def cmake_env_extra() -> dict:
    """Reuse pinned FetchContent clones without sharing candidate object files."""
    env = build_env_extra()
    target_build = REPO / CONFIG["repos"]["target"] / "build"
    local_clones = [
        ("https://github.com/fmtlib/fmt.git", target_build / "_deps/fmt-src"),
        ("https://github.com/microsoft/mimalloc.git", target_build / "_deps/mimalloc-src"),
        ("https://github.com/CLIUtils/CLI11.git", target_build / "_deps/cli11-src"),
        ("https://github.com/oneapi-src/oneTBB.git", target_build / "_deps/tbb-src"),
        ("https://github.com/kahypar/kahypar-shared-resources.git",
         target_build / "external/mt-kahypar/external_tools/kahypar-shared-resources"),
        ("https://github.com/larsgottesbueren/WHFC.git",
         target_build / "external/mt-kahypar/external_tools/WHFC"),
        ("https://github.com/cmuparlay/parlaylib.git",
         target_build / "external/mt-kahypar/external_tools/parlay"),
    ]
    available = [(remote, source.resolve()) for remote, source in local_clones
                 if (source / ".git").exists()]
    config_offset = int(os.environ.get("GIT_CONFIG_COUNT", "0"))
    env["GIT_CONFIG_COUNT"] = str(config_offset + len(available))
    for index, (remote, source) in enumerate(available, start=config_offset):
        env[f"GIT_CONFIG_KEY_{index}"] = f"url.{source.as_uri()}.insteadOf"
        env[f"GIT_CONFIG_VALUE_{index}"] = remote
    return env


def evaluate_candidate(worktree: Path, eval_id: str, emit_args_override: list[str] | None,
                       compile_budget_sec: int) -> dict:
    evdir = BUILD_TASK / "evals" / eval_id
    wbuild, emit_dir, emu_build, run_dir = (evdir / d for d in ("wbuild", "emit", "emu_build", "run"))
    for d in (wbuild, emit_dir, emu_build, run_dir):
        d.mkdir(parents=True, exist_ok=True)
    logs = {"dir": str(evdir.relative_to(REPO))}
    result: dict = {"eval_id": eval_id, "worktree": str(worktree), "started_at": now_iso(),
                    "status": "ok", "logs": logs,
                    "compile_budget_sec": compile_budget_sec}

    commit = subprocess.run(["git", "-C", str(worktree), "rev-parse", "HEAD"],
                            capture_output=True, text=True)
    result["commit"] = commit.stdout.strip() if commit.returncode == 0 else None

    # 编译流程总预算：从 cmake 到 emu 二进制就绪的累计墙钟，超预算即 compile_timeout。
    # 计时 reps 不计入预算（预算是对「代码生成 + 编译」成本的约束）。
    t0 = time.monotonic()
    outer = EVAL_CFG["build_timeout_sec"]  # 单阶段兜底超时（远大于预算，仅防挂死）

    def remaining() -> float:
        return compile_budget_sec - (time.monotonic() - t0)

    def phase_timeout() -> int:
        return max(1, int(min(outer, remaining())))

    def check_budget(phase: str, rc: int) -> bool:
        """返回 True = 因预算/超时应判 compile_timeout。"""
        if rc == 124 or remaining() <= 0:
            result.update(status="compile_timeout", phase=phase,
                          compile_s=round(time.monotonic() - t0, 1))
            return True
        result["compile_s"] = round(time.monotonic() - t0, 1)
        return False

    # 1. wolvrix 构建
    cmake_args = ["-S", str(worktree), "-B", str(wbuild),
                  "-DCMAKE_BUILD_TYPE=Release", "-G", "Unix Makefiles",
                  # 与顶层 Makefile 口径一致：固定 clang/clang++（经 PATH 解析），
                  # 不落入系统默认 gcc，保证候选间工具链可比。
                  "-DCMAKE_C_COMPILER=clang", "-DCMAKE_CXX_COMPILER=clang++"]
    if shutil.which("ccache"):
        cmake_args += ["-DCMAKE_CXX_COMPILER_LAUNCHER=ccache", "-DCMAKE_C_COMPILER_LAUNCHER=ccache"]
    rc, dur = sh(["cmake", *cmake_args], evdir / "cmake.log", timeout=phase_timeout(),
                 env_extra=cmake_env_extra())
    if rc != 0:
        if check_budget("cmake", rc):
            return result
        result.update(status="build_fail", phase="cmake")
        return result
    rc, dur = sh(["cmake", "--build", str(wbuild), "-j", str(os.cpu_count() or 8)],
                 evdir / "build.log", timeout=phase_timeout(), env_extra=build_env_extra())
    result.setdefault("timings", {})["wolvrix_build_s"] = round(dur, 1)
    if rc != 0:
        if check_budget("build", rc):
            return result
        result.update(status="build_fail", phase="build")
        return result

    # 2. ctest 回归门
    if EVAL_CFG["ctest_gate"]:
        rc, _ = sh(["ctest", "--test-dir", str(wbuild), "-R", EVAL_CFG["ctest_regex"],
                    "--output-on-failure"], evdir / "ctest.log", timeout=phase_timeout())
        result["gates"] = {"ctest": rc == 0}
        if rc != 0:
            if check_budget("ctest", rc):
                return result
            result.update(status="ctest_fail", phase="ctest")
            return result

    # 3. emit
    emit_args = emit_args_override if emit_args_override is not None else EVAL_CFG["emit_args"]
    rc, dur = sh([str(wbuild / "bin" / "grhsim-am-lower-json"),
                  str(REPO / DESIGN_JSON), "SimTop",
                  "--emit", str(emit_dir), *emit_args],
                 evdir / "emit.log", timeout=phase_timeout(),
                 env_extra={"WOLVRIX_GRHSIM_AM_BLOCK_ATOM_JSONL": str(evdir / "block_atom.jsonl")})
    result["timings"]["emit_s"] = round(dur, 1)
    result["emit_args"] = emit_args
    if rc != 0 or not (emit_dir / "Makefile").exists():
        if check_budget("emit", rc):
            return result
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
                 evdir / "emu_build.log", timeout=phase_timeout(),
                 env_extra=build_env_extra())
    result["timings"]["emu_build_s"] = round(dur, 1)
    emu_real = emu_build / "grhsim-compile" / "emu"
    if rc != 0 or not emu_real.exists():
        if check_budget("emu_build", rc):
            return result
        result.update(status="build_fail", phase="emu_build")
        return result
    result["compile_s"] = round(time.monotonic() - t0, 1)

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
    p.add_argument("--compile-budget-sec", type=int, default=None,
                   help="覆盖 config 的编译流程总预算（秒）；超预算判 compile_timeout")
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
            budget = args.compile_budget_sec or EVAL_CFG["compile_budget_sec"]
            result = evaluate_candidate(wt, args.eval_id, override, budget)
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
