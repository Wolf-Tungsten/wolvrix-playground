#!/usr/bin/env python3
"""evaluate — TES 的评估器 V。给定一个 wolvrix 现场（worktree），执行完整评估流水线：

  wolvrix 构建（Release + ccache）→ ctest -R grhsim 回归门 → emit（固定 post-stats
  GRH 输入，wolvrix 自解析 XiangShan SV 的归一化产物）→ difftest emu 构建
  → 绑核串行计时 reps（每 rep 独立物理核，difftest 金标门 + CV 检查）

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
import threading
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


def cluster_reps(times_ms: list[float], ratio: float) -> list[list[int]]:
    """一维倍率缝隙聚簇：排序后相邻比值 > ratio 处切分；返回按簇中位升序的簇。"""
    order = sorted(range(len(times_ms)), key=lambda i: times_ms[i])
    clusters: list[list[int]] = [[order[0]]]
    for prev, cur in zip(order, order[1:]):
        if times_ms[cur] > times_ms[prev] * ratio:
            clusters.append([])
        clusters[-1].append(cur)
    clusters.sort(key=lambda c: statistics.median(times_ms[i] for i in c))
    return [sorted(c) for c in clusters]  # 簇内按下标排序，result.json 可读性


def adjudicate_reps(times_ms: list[float], ratio: float) -> dict:
    """快簇（首个 ≥2 成员的簇）中位为裁决 median；全 singleton 退化取最快簇。

    state: unimodal（单簇）/ bimodal（多簇且有 ≥2 成员簇）/ degraded（全 singleton）。
    """
    clusters = cluster_reps(times_ms, ratio)
    fast = next((c for c in clusters if len(c) >= 2), None)
    if fast is None:
        state = "degraded"
        fast = clusters[0]
    elif len(clusters) == 1:
        state = "unimodal"
    else:
        state = "bimodal"
    return {"state": state, "clusters": clusters, "fast_cluster": fast,
            "median": statistics.median(times_ms[i] for i in fast),
            "median_all": statistics.median(times_ms)}


def _sample_proc_state(pid: int, stop: threading.Event, out: dict) -> None:
    """1Hz 只读采样 rep 进程的 THP/NUMA 协变量（与计时纪律兼容的先例：r002 监视模式）。"""
    huge_max = 0
    pages: dict[str, int] = {}
    samples = 0
    while not stop.is_set():
        try:
            rollup = Path(f"/proc/{pid}/smaps_rollup").read_text(encoding="utf-8")
            m = re.search(r"AnonHugePages:\s+(\d+)\s+kB", rollup)
            if m:
                huge_max = max(huge_max, int(m.group(1)))
            numa = Path(f"/proc/{pid}/numa_maps").read_text(encoding="utf-8")
            cur: dict[str, int] = {}
            for n, p in re.findall(r"\bN(\d+)=(\d+)", numa):
                cur[f"N{n}"] = cur.get(f"N{n}", 0) + int(p)
            pages = cur
            samples += 1
        except (OSError, ValueError):
            break  # 进程已退出
        stop.wait(1.0)
    out.update({"anon_hugepages_kb_max": huge_max, "numa_pages": pages, "samples": samples})


def _run_one_rep(emu: Path, cwd: Path, run_dir: Path,
                 rep_idx: int, core: str) -> dict:
    """起跑一个 rep，结束后返回原始结果。

    干扰守卫在每个 rep 起跑前检查；rep 超时时 kill 进程组并记 rc=124。
    """
    import signal
    ev = EVAL_CFG
    timeout = ev["rep_timeout_sec"]
    if not no_other_emu():
        return {"rep": rep_idx, "rc": None, "interference": True,
                "error": "检测到其他 emu 进程，计时前中止（干扰守卫）"}
    load = loadavg()
    log = run_dir / f"rep{rep_idx}.log"
    cmd = ["taskset", "-c", core, str(emu),
           "-i", str(REPO / PATHS["coremark_bin"]),
           "--diff", str(REPO / PATHS["nemu_so"]),
           "-b", "0", "-e", "0", "-C", str(ev["cycles"])]
    with open(log, "ab") as lf:
        lf.write(f"\n===== [{now_iso()}] {' '.join(str(c) for c in cmd)} =====\n".encode())
        lf.flush()
        process = subprocess.Popen(cmd, cwd=cwd, env=dict(os.environ), stdout=lf,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        proc_state: dict = {}
        sampler_stop = threading.Event()
        sampler = threading.Thread(target=_sample_proc_state,
                                   args=(process.pid, sampler_stop, proc_state), daemon=True)
        sampler.start()
        started = time.monotonic()
        rc = None
        while rc is None:
            rc = process.poll()
            if rc is None and time.monotonic() - started > timeout:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                rc = 124
            elif rc is None:
                time.sleep(1)
        sampler_stop.set()
        sampler.join(timeout=2)
        wall_s = round(time.monotonic() - started, 1)
    return {"rep": rep_idx, "core": core, "rc": rc, "wall_s": wall_s,
            "loadavg_before": load, "proc_state": proc_state, **parse_run_log(log)}


def run_reps(emu: Path, run_dir: Path, run_cwd: Path | None = None) -> dict:
    """协议化计时 reps，返回状态、原始 reps 与裁决后的 Host 时间中位。

    emu 可为绝对路径或 run_cwd 下的相对名（如 Path("emu") + run_cwd=emu 构建目录）。
    reps 逐次串行：每 rep 按序轮转绑定 eval.rep_cores 中的物理核
    （缺省退回 eval.core）。初始 rep 数由 run manifest 冻结（eval.reps）；
    r004 起为簇结构自适应：检出双峰（cluster_ratio 倍率缝隙）才加跑至 ≤ reps_max，
    不因 CV 扩增。score/median = 快簇中位（弃用跨簇 median）。
    """
    ev = EVAL_CFG
    golden = ev["golden"]
    tol = ev.get("golden_tol", {"instrCnt": 0, "cycleCnt": 0})
    cores = [str(c) for c in (ev.get("rep_cores") or [ev["core"]])]
    ratio = float(ev.get("cluster_ratio", 1.15))
    reps_max = int(ev.get("reps_max", 9))
    reps: list[dict] = []
    status = "ok"
    target_reps = ev["reps"]
    cwd = run_cwd or run_dir
    if not emu.is_absolute():
        emu = (cwd / emu).resolve()  # execvp 不搜 cwd，相对名必须解析成绝对路径
    while len(reps) < target_reps:
        core = cores[len(reps) % len(cores)]
        rep = _run_one_rep(emu, cwd, run_dir, len(reps) + 1, core)
        reps.append(rep)
        if rep.get("interference"):
            return {"status": "interference", "reps": reps,
                    "error": "检测到其他 emu 进程，计时前中止（干扰守卫）"}
        if rep["rc"] == 124:
            status = "timeout"
            break
        instr, cyc = rep["instrCnt"], rep["cycleCnt"]
        rep["difftest_ok"] = (
            rep["rc"] == 0 and instr is not None and cyc is not None
            and abs(instr - golden["instrCnt"]) <= tol["instrCnt"]
            and abs(cyc - golden["cycleCnt"]) <= tol["cycleCnt"])
        if not rep["difftest_ok"]:
            status = "difftest_fail"
            break
        times = [r["host_ms"] for r in reps if r["host_ms"] is not None]
        if len(times) != len(reps):
            status = "parse_fail"
            break
        # 完成当前目标次数后再裁决；检出分裂则串行追加一组。
        if (len(reps) == target_reps and len(cluster_reps(times, ratio)) > 1
                and len(reps) < reps_max):
            target_reps = min(target_reps + len(cores), reps_max)
    times = [r["host_ms"] for r in reps if r["host_ms"] is not None]
    out = {"status": status, "reps": reps}
    if times and all(r.get("difftest_ok") for r in reps):
        adj = adjudicate_reps(times, ratio)
        median = _median([times[i] for i in adj["fast_cluster"]])
        cv = _cv(times)
        out.update({"host_ms": {"reps": times, "median": median,
                                "median_all": _median(times), "cv": round(cv, 4),
                                "clusters": adj["clusters"],
                                "fast_cluster": adj["fast_cluster"],
                                "state": adj["state"]},
                    "noisy": cv > ev["cv_max"] or adj["state"] == "degraded",
                    "score": -median})
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
    # The requested phenotype is fixed before any build gate. Preserve it on
    # early build/ctest failures so record-eval can audit and register failed
    # candidates under the same declaration contract as timed candidates.
    emit_args = emit_args_override if emit_args_override is not None else EVAL_CFG["emit_args"]
    result["emit_args"] = emit_args

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
    rc, dur = sh([str(wbuild / "bin" / "grhsim-am-lower-json"),
                  str(REPO / DESIGN_JSON), "SimTop",
                  "--emit", str(emit_dir), *emit_args],
                 evdir / "emit.log", timeout=phase_timeout(),
                 env_extra={"WOLVRIX_GRHSIM_AM_BLOCK_ATOM_JSONL": str(evdir / "block_atom.jsonl")})
    result["timings"]["emit_s"] = round(dur, 1)
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


def retime_eval(eval_id: str) -> int:
    """复用既有 emu 只补计时（不重建、不占预算）：result.json 追加 retimes 段并刷新顶层裁决。

    整批慢态嫌疑（spec §1.3）或中段基线重锚（round-summary 协议动作）时使用；
    旧裁决保留在 host_ms_superseded / retimes 历史中，rep 日志 append 式叠加。
    """
    evdir = BUILD_TASK / "evals" / eval_id
    rj = evdir / "result.json"
    if not rj.exists():
        print(f"[FAIL] {rj} 不存在", file=sys.stderr)
        return 1
    result = json.loads(rj.read_text(encoding="utf-8"))
    emu_build = evdir / "emu_build"
    if result.get("mode") == "gsim-baseline":
        emu = (REPO / result["emu"]).resolve()
        reps = run_reps(emu, evdir / "run", run_cwd=emu.parent)
    elif (emu_build / "emu").exists():
        reps = run_reps(Path("emu"), evdir / "run", run_cwd=emu_build)
    elif (emu_build / "grhsim-compile" / "emu").exists():
        reps = run_reps(emu_build / "grhsim-compile" / "emu", evdir / "run")
    else:
        print(f"[FAIL] {eval_id} 无可复用 emu（未构建或已清理）", file=sys.stderr)
        return 1
    if reps.get("status") != "ok" or "host_ms" not in reps:
        print(f"[FAIL] retime 未得到有效计时: {reps.get('status')}", file=sys.stderr)
        return 1
    result.setdefault("retimes", []).append({"started_at": now_iso(),
                                             "host_ms": reps["host_ms"],
                                             "score": reps.get("score")})
    if "host_ms" in result:
        result["host_ms_superseded"] = result["host_ms"]
    result["host_ms"] = reps["host_ms"]
    result["score"] = reps.get("score")
    rj.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] {eval_id} retime: median {reps['host_ms']['median']} ms"
          f"（state={reps['host_ms']['state']}）")
    return 0


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
    p = sub.add_parser("retime", help="复用既有 emu 重跑计时协议（不重建、不占预算）")
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

        if args.cmd == "retime":
            return retime_eval(args.eval_id)  # 自写 result.json，不走下方公共写盘路径

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
