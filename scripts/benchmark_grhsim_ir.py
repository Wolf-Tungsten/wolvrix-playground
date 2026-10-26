"""Measure alternating single-threaded 100k CoreMark runs via project Make targets."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import statistics
import subprocess
import time


FAILURE = re.compile(r"mismatch|HIT BAD TRAP|Assertion .*failed|Assertion failed|ABORT|Segmentation fault", re.I)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def evict_page_cache(path: Path) -> bool:
    """Drop the file's page-cache pages so the next run reallocates its
    physical frames. Without eviction a freshly linked binary keeps its
    compile-time frame allocation, which behaves as a fixed per-file
    performance offset (measured up to ±6-9% on this workload) that an
    alternating old/new protocol cannot average out."""
    if not path.is_file():
        return False
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def endpoint(text: str) -> tuple[int, int, int, str, float]:
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    if FAILURE.search(text) or "Difftest enabled" not in text:
        raise ValueError("failed or missing difftest")
    counts = re.search(r"instrCnt = (\d+), cycleCnt = (\d+)", text)
    guest = re.search(r"Guest cycle spent: (\d+)", text)
    pc = re.search(r"EXCEEDING CYCLE/INSTR LIMIT at pc = (0x[0-9a-f]+)", text)
    host = re.search(r"Host time spent: (\d+)ms", text)
    if not all((counts, guest, pc, host)) or "cycles=100000 max_cycles=100000" not in text:
        raise ValueError("missing 100k endpoint")
    return int(counts[1]), int(counts[2]), int(guest[1]), pc[1], int(host[1]) / 1000


def summary(results: list[dict]) -> dict:
    groups = {mode: [r["host_s"] for r in results if r["mode"] == mode] for mode in ("old", "new")}
    old, new = groups["old"], groups["new"]
    means = {mode: statistics.mean(values) for mode, values in groups.items()}
    sd = {mode: statistics.stdev(values) if len(values) > 1 else None for mode, values in groups.items()}
    # Enumerate the one-sided permutation distribution, retaining ties.
    def u(a, b):
        return sum((x > y) + 0.5 * (x == y) for x in a for y in b)
    observed = u(new, old)
    pooled = new + old
    distribution = []
    for selected in itertools.combinations(range(len(pooled)), len(new)):
        indices = set(selected)
        distribution.append(u([pooled[i] for i in indices],
                              [pooled[i] for i in range(len(pooled)) if i not in indices]))
    pooled_sd = math.sqrt((sd["old"] ** 2 + sd["new"] ** 2) / 2) if sd["old"] is not None else 0
    return {"host_s": groups, "mean_s": means, "sample_sd_s": sd,
            "improvement_percent": 100 * (1 - means["new"] / means["old"]),
            "cohen_d_new_minus_old": (means["new"] - means["old"]) / pooled_sd if pooled_sd else None,
            "cliff_delta": 2 * observed / (len(new) * len(old)) - 1,
            "mann_whitney_u_new": observed,
            "one_sided_exact_p": sum(value <= observed for value in distribution) / len(distribution),
            "rank_gate_pass": len(new) >= 3 and len(old) >= 3 and max(new) < min(old)}


def native_work_summary(results: list[dict]) -> dict:
    groups = {}
    for mode in ("old", "new"):
        runs = [result for result in results if result["mode"] == mode]
        instructions = [run["counts"]["instructions:u"] for run in runs]
        per_cycle = [count / run["endpoint"][2] for count, run in zip(instructions, runs)]
        mean_instructions = statistics.mean(instructions)
        groups[mode] = {
            "instructions": instructions,
            "instructions_per_guest_cycle": per_cycle,
            "mean_instructions_per_guest_cycle": statistics.mean(per_cycle),
            "sample_sd_instructions_per_guest_cycle": statistics.stdev(per_cycle) if len(runs) > 1 else None,
            "instruction_spread_ratio": (max(instructions) - min(instructions)) / mean_instructions,
            "cpi": statistics.mean(run["counts"]["cycles:u"] for run in runs) / mean_instructions,
        }
    groups["instruction_reduction_percent"] = 100 * (1 -
        groups["new"]["mean_instructions_per_guest_cycle"] /
        groups["old"]["mean_instructions_per_guest_cycle"])
    return groups


def migration_runtime_summary(results: list[dict], runtime_limit=3.0, rss_limit=5.0) -> dict:
    """Use the migration budget, independently of the optimization rank gate."""
    groups = {}
    for mode in ("old", "new"):
        rows = [row for row in results if row["mode"] == mode and not row.get("warmup", False)]
        if len(rows) != 3:
            raise ValueError("migration runtime gate requires exactly three measured runs per mode")
        for row in rows:
            if any(not math.isfinite(row[key]) or row[key] <= 0 for key in ("host_s", "max_rss_kib")):
                raise ValueError("migration runtime gate requires positive finite Host and RSS observations")
        times = [row["host_s"] for row in rows]
        groups[mode] = {"host_s": times, "median_host_s": statistics.median(times),
                        "median_max_rss_kib": statistics.median(row["max_rss_kib"] for row in rows)}
        groups[mode]["host_spread_percent"] = 100 * (max(times) - min(times)) / groups[mode]["median_host_s"]
    runtime_ratio = groups["new"]["median_host_s"] / groups["old"]["median_host_s"]
    rss_ratio = groups["new"]["median_max_rss_kib"] / groups["old"]["median_max_rss_kib"]
    noise_ok = all(group["host_spread_percent"] <= 5.0 for group in groups.values())
    runtime_ok = runtime_ratio <= 1 + runtime_limit / 100
    rss_ok = rss_ratio <= 1 + rss_limit / 100
    return {"scope": "XS 100k runtime/RSS only; generation and compilation gates remain separate",
            "groups": groups, "new_over_old_host": runtime_ratio, "new_over_old_rss": rss_ratio,
            "runtime_limit_percent": runtime_limit, "rss_limit_percent": rss_limit,
            "noise_limit_percent": 5.0, "noise_ok": noise_ok,
            "runtime_ok": runtime_ok, "rss_ok": rss_ok,
            "classification": "NOISY" if not noise_ok else "PASS" if runtime_ok and rss_ok else "REGRESSION",
            "accepted": noise_ok and runtime_ok and rss_ok}


def main(argv=None, root=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=2)
    parser.add_argument("--pairs", type=int, choices=(1, 3), default=3)
    parser.add_argument("--baseline-seconds", type=float, required=True)
    parser.add_argument("--make-target", default="run_xs_grhsim_emu",
                        help="root Makefile run target used for every timed run")
    parser.add_argument("--build-var", default="XS_GRHSIM_BUILD",
                        help="root Makefile variable that selects the flow build directory")
    parser.add_argument("--emu-relpath", default="emu/emu",
                        help="emu binary path relative to the flow directory")
    parser.add_argument("--expected-endpoint", default="238535,99996,100001,0x80000cde",
                        help="instrCnt,cycleCnt,guestCycles,pc that every valid run must hit")
    parser.add_argument("--evict-page-cache", action=argparse.BooleanOptionalAction, default=True,
                        help="evict each flow binary's page cache before every run (default on)")
    parser.add_argument("--perf-stat", action="store_true",
                        help="collect native work counters; these runs are diagnostics, not Host baselines")
    parser.add_argument("--old-env", action="append", default=[], metavar="KEY=VALUE",
                        help="extra environment variable for old-mode runs only (repeatable); "
                             "enables same-binary A/B when old and new point at one flow")
    parser.add_argument("--migration-baseline", type=Path,
                        help="frozen removal baseline; enable one warmup each, 3+3, and its migration runtime/RSS budgets")
    args = parser.parse_args(argv)
    endpoint_fields = args.expected_endpoint.split(",")
    if len(endpoint_fields) != 4:
        parser.error("--expected-endpoint must be instrCnt,cycleCnt,guestCycles,pc")
    try:
        expected_endpoint = [int(endpoint_fields[0]), int(endpoint_fields[1]),
                             int(endpoint_fields[2]), endpoint_fields[3]]
    except ValueError:
        parser.error("--expected-endpoint counts must be integers")
    root = Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if not output.is_relative_to(root / "ptmp") or output.exists():
        parser.error("output must be a new directory under ptmp")
    if args.cpu not in os.sched_getaffinity(0) or not math.isfinite(args.baseline_seconds) or args.baseline_seconds <= 0:
        parser.error("CPU must be available and baseline time positive")
    if args.migration_baseline and (args.pairs != 3 or args.perf_stat or args.old_env or args.evict_page_cache):
        parser.error("migration timing requires three pairs, no perf/old-env, and --no-evict-page-cache after warmup")
    flows = {mode: getattr(args, mode).resolve() for mode in ("old", "new")}
    binaries = {mode: {"path": str(flow / args.emu_relpath), "sha256": digest(flow / args.emu_relpath)}
                for mode, flow in flows.items()}
    order = ([("old", 0), ("new", 0)] if args.migration_baseline else []) + [
        (mode, i) for i in range(1, args.pairs + 1) for mode in ("old", "new")]
    cutoff = args.baseline_seconds * 1.5
    output.mkdir(parents=True)
    old_env = {}
    for assignment in args.old_env:
        if "=" not in assignment:
            parser.error("--old-env must be KEY=VALUE")
        key, value = assignment.split("=", 1)
        old_env[key] = value
    registration = {"order": [f"{mode}{i}" for mode, i in order], "binaries": binaries,
                    "inputs": {name: digest(root / "testcase/xiangshan/ready-to-run" / name)
                               for name in ("coremark-2-iteration.bin", "riscv64-nemu-interpreter-so")},
                    "baseline_s": args.baseline_seconds, "cutoff_s": cutoff, "cpu": args.cpu,
                    "threads": 1, "cycles": 100000, "trace": False, "profile": False,
                    "evict_page_cache": args.evict_page_cache, "old_env": old_env,
                    "make_target": args.make_target, "build_var": args.build_var,
                    "emu_relpath": args.emu_relpath,
                    "primary": "Host time", "gate": "max(new) < min(old), 3+3 valid runs",
                    "expected_endpoint": expected_endpoint,
                    "timestamp": time.time()}
    registration["perf_stat"] = args.perf_stat
    if args.migration_baseline:
        baseline = args.migration_baseline.resolve()
        manifest = baseline / "manifest.json"
        frozen = json.loads(manifest.read_text())
        original = "frozen/ptmp/xs/grhsim-ir/emu/grhsim-compile/emu"
        if binaries["old"]["sha256"] != frozen["artifacts"][original]["sha256"]:
            raise ValueError("old runtime is not the frozen XS executable")
        if flows["old"].is_relative_to(baseline) or flows["new"].is_relative_to(baseline):
            raise ValueError("run isolated copies; benchmark must not write into the frozen baseline")
        supplement = baseline / "inputs-supplement.json"
        inputs = json.loads(supplement.read_text())["inputs"]
        for name, checksum in registration["inputs"].items():
            if checksum != inputs["testcase/xiangshan/ready-to-run/" + name]["sha256"]:
                raise ValueError("XS input differs from frozen input: " + name)
        registration.update(kind="migration runtime gate", warmup_runs=2, seed=0,
                            baseline_s=None, timeout_reference_s=args.baseline_seconds,
                            baseline_manifest_sha256=digest(manifest), baseline_inputs_sha256=digest(supplement),
                            policy=frozen["policy"], noise_limit_percent=5.0,
                            gate="Host median regression <= frozen runtime budget; RSS <= frozen memory budget; noise <= 5%")
        registration["candidate_artifacts"] = {
            str(path.relative_to(flows["new"])): digest(path)
            for path in (flows["new"] / "generation-identity.json", flows["new"] / "model/manifest.json",
                         flows["new"] / "model/generation-identity.json") if path.is_file()}
        if "model/generation-identity.json" not in registration["candidate_artifacts"]:
            raise ValueError("migration timing requires the candidate generation identity")
    if args.perf_stat:
        from grhsim_native_work_compare import MAIN_EVENTS, parse_perf_stat
        registration["primary"] = "instructions per guest cycle"
        registration["kind"] = "perf-stat diagnostic; Host times are not performance baselines"
        registration["events"] = list(MAIN_EVENTS)
    (output / "preregister.json").write_text(json.dumps(registration, indent=2) + "\n")
    env = {key: value for key, value in os.environ.items()
           if key not in ("CPUPROFILE", "CPUPROFILE_FREQUENCY", "LD_PRELOAD")}
    env.update(WOLF_ENV_SOURCED="1", EMU_THREADS="1", EMU_RUNTIME_PROFILE="0", EMU_PHASE_TIMING="0", LC_ALL="C")
    results = []
    evicted = set()
    for mode, repeat in order:
        label = f"{mode}{repeat}"
        directory = output / label
        directory.mkdir()
        cache_evicted = False
        if args.evict_page_cache:
            cache_evicted = evict_page_cache(flows[mode] / args.emu_relpath)
            if not cache_evicted:
                raise RuntimeError(f"{label}: cannot evict binary page cache")
            evicted.add(mode)
        timing = directory / "emu.time"
        time_format = "wall=%e,exit=%x" + (",rss_kib=%M" if args.migration_baseline else "")
        prefix_args = ["timeout", "--signal=KILL", f"{cutoff:.6f}s", "/usr/bin/time",
                       "-f", time_format, "-o", str(timing)]
        if args.perf_stat:
            prefix_args += ["perf", "stat", "-x,", "-e", ",".join(MAIN_EVENTS),
                            "-o", str(directory / "perf.stat")]
        prefix = shlex.join(prefix_args + ["taskset", "-c", str(args.cpu), "stdbuf", "-oL", "-eL"])
        command = ["make", "--no-print-directory", args.make_target,
                   f"{args.build_var}={flows[mode]}", f"XS_LOG_DIR={directory / 'logs'}",
                   f"RUN_ID={output.parent.name}_{output.name}_{label}", "XS_NUM_CORES=1", "XS_EMU_THREADS=1", "EMU_THREADS=1",
                   f"XS_EMU_CPU={args.cpu}", "XS_SIM_MAX_CYCLE=100000", "XS_WAVEFORM=0",
                   "XS_WAVEFORM_PATH=", "XS_COMMIT_TRACE=0", "XS_RAM_TRACE=0",
                   "XS_PROGRESS_EVERY_CYCLES=0", f"XS_EMU_PREFIX={prefix}"]
        if args.migration_baseline:
            command.append(f"XS_WAVEFORM_DIR={directory / 'waveforms'}")
        (directory / "command.sh").write_text(shlex.join(command) + "\n")
        print(f"START {label}", flush=True)
        start = time.monotonic()
        log = directory / "make.log"
        killed = None
        run_env = {**env, **old_env} if mode == "old" else env
        with log.open("w") as stream:
            process = subprocess.Popen(command, cwd=root, env=run_env, stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            while process.poll() is None:
                if FAILURE.search(log.read_text(errors="replace")):
                    killed = "INVALID"
                elif time.monotonic() - start > cutoff + 30:
                    killed = "REGRESSION_KILLED"
                if killed:
                    os.killpg(process.pid, signal.SIGKILL)
                    break
                time.sleep(0.5)
            status = process.wait()
        result = {"mode": mode, "repeat": repeat, "warmup": repeat == 0,
                  "make_exit": status, "make_wall_s": time.monotonic() - start}
        (directory / "status.json").write_text(json.dumps(result, indent=2) + "\n")
        if status or killed:
            reason = killed or ("REGRESSION_KILLED" if status in (137, -9) or result["make_wall_s"] >= cutoff else "INVALID")
            result["classification"] = reason
            (directory / "status.json").write_text(json.dumps(result, indent=2) + "\n")
            raise RuntimeError(f"{label}: {reason}, Make exit={status}; see {log}")
        parsed = endpoint(log.read_text())
        if list(parsed[:4]) != registration["expected_endpoint"]:
            raise RuntimeError(f"{label}: INVALID endpoint {parsed[:4]}")
        wall = re.fullmatch(r"wall=([\d.]+),exit=0" + (r",rss_kib=(\d+)" if args.migration_baseline else "") + r"\n?", timing.read_text())
        if not wall:
            raise RuntimeError(f"{label}: INVALID emu exit/timing")
        result.update(host_s=parsed[4], emu_wall_s=float(wall[1]), emu_exit=0, endpoint=list(parsed[:4]))
        if args.migration_baseline:
            if not re.search(r"Seed=0\s+Guest cycle", log.read_text()):
                raise RuntimeError(f"{label}: seed differs from frozen seed 0")
            result["max_rss_kib"] = int(wall[2])
        result["page_cache_evicted"] = cache_evicted
        if args.perf_stat:
            result["counts"] = parse_perf_stat((directory / "perf.stat").read_text(), MAIN_EVENTS)
        results.append(result)
        (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(f"DONE {label} Host={parsed[4]:.3f}s emu_wall={wall[1]}s", flush=True)
    for mode, binary in binaries.items():
        if digest(Path(binary["path"])) != binary["sha256"]:
            raise RuntimeError("XS binary changed during benchmark: " + mode)
    for name, checksum in registration["inputs"].items():
        if digest(root / "testcase/xiangshan/ready-to-run" / name) != checksum:
            raise RuntimeError("XS input changed during benchmark: " + name)
    measured = [result for result in results if not result["warmup"]]
    stats = summary(measured)
    stats["page_cache_evicted"] = sorted(evicted)
    if args.perf_stat:
        stats["kind"] = registration["kind"]
        stats["native_work"] = native_work_summary(measured)
    if args.migration_baseline:
        if (digest(baseline / "manifest.json") != registration["baseline_manifest_sha256"] or
                digest(baseline / "inputs-supplement.json") != registration["baseline_inputs_sha256"]):
            raise RuntimeError("frozen baseline identity changed during benchmark")
        for name, checksum in registration["candidate_artifacts"].items():
            if digest(flows["new"] / name) != checksum:
                raise RuntimeError("candidate generation changed during benchmark: " + name)
        stats["migration_runtime"] = migration_runtime_summary(
            measured, registration["policy"]["runtime_regression_percent"],
            registration["policy"]["generation_compile_rss_percent"])
    (output / "summary.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2), flush=True)
    if args.migration_baseline and not stats["migration_runtime"]["accepted"]:
        raise SystemExit("Migration runtime gate did not pass; see " + str(output / "summary.json"))


if __name__ == "__main__":
    main()
