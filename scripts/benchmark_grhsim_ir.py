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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=2)
    parser.add_argument("--pairs", type=int, choices=(1, 3), default=3)
    parser.add_argument("--baseline-seconds", type=float, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if not output.is_relative_to(root / "ptmp") or output.exists():
        parser.error("output must be a new directory under ptmp")
    if args.cpu not in os.sched_getaffinity(0) or not math.isfinite(args.baseline_seconds) or args.baseline_seconds <= 0:
        parser.error("CPU must be available and baseline time positive")
    flows = {mode: getattr(args, mode).resolve() for mode in ("old", "new")}
    binaries = {mode: {"path": str(flow / "emu/emu"), "sha256": digest(flow / "emu/emu")}
                for mode, flow in flows.items()}
    order = [(mode, i) for i in range(1, args.pairs + 1) for mode in ("old", "new")]
    cutoff = args.baseline_seconds * 1.5
    output.mkdir(parents=True)
    registration = {"order": [f"{mode}{i}" for mode, i in order], "binaries": binaries,
                    "inputs": {name: digest(root / "testcase/xiangshan/ready-to-run" / name)
                               for name in ("coremark-2-iteration.bin", "riscv64-nemu-interpreter-so")},
                    "baseline_s": args.baseline_seconds, "cutoff_s": cutoff, "cpu": args.cpu,
                    "threads": 1, "cycles": 100000, "trace": False, "profile": False,
                    "primary": "Host time", "gate": "max(new) < min(old), 3+3 valid runs",
                    "expected_endpoint": [240349, 99996, 100001, "0x80000c0c"],
                    "timestamp": time.time()}
    (output / "preregister.json").write_text(json.dumps(registration, indent=2) + "\n")
    env = {key: value for key, value in os.environ.items()
           if key not in ("CPUPROFILE", "CPUPROFILE_FREQUENCY", "LD_PRELOAD")}
    env.update(WOLF_ENV_SOURCED="1", EMU_THREADS="1", EMU_RUNTIME_PROFILE="0", EMU_PHASE_TIMING="0")
    results = []
    for mode, repeat in order:
        label = f"{mode}{repeat}"
        directory = output / label
        directory.mkdir()
        timing = directory / "emu.time"
        prefix = shlex.join(["timeout", "--signal=KILL", f"{cutoff:.6f}s", "/usr/bin/time",
                             "-f", "wall=%e,exit=%x", "-o", str(timing), "taskset", "-c",
                             str(args.cpu), "stdbuf", "-oL", "-eL"])
        command = ["make", "--no-print-directory", "run_xs_wolf_grhsim_ir_emu",
                   f"XS_GRHSIM_IR_BUILD={flows[mode]}", f"XS_LOG_DIR={directory / 'logs'}",
                   f"RUN_ID={output.parent.name}_{output.name}_{label}", "XS_NUM_CORES=1", "XS_EMU_THREADS=1", "EMU_THREADS=1",
                   f"XS_EMU_CPU={args.cpu}", "XS_SIM_MAX_CYCLE=100000", "XS_WAVEFORM=0",
                   "XS_WAVEFORM_PATH=", "XS_COMMIT_TRACE=0", "XS_RAM_TRACE=0",
                   "XS_PROGRESS_EVERY_CYCLES=0", f"XS_EMU_PREFIX={prefix}"]
        (directory / "command.sh").write_text(shlex.join(command) + "\n")
        print(f"START {label}", flush=True)
        start = time.monotonic()
        log = directory / "make.log"
        killed = None
        with log.open("w") as stream:
            process = subprocess.Popen(command, cwd=root, env=env, stdout=stream,
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
        result = {"mode": mode, "repeat": repeat, "make_exit": status, "make_wall_s": time.monotonic() - start}
        (directory / "status.json").write_text(json.dumps(result, indent=2) + "\n")
        if status or killed:
            reason = killed or ("REGRESSION_KILLED" if status in (137, -9) or result["make_wall_s"] >= cutoff else "INVALID")
            result["classification"] = reason
            (directory / "status.json").write_text(json.dumps(result, indent=2) + "\n")
            raise RuntimeError(f"{label}: {reason}, Make exit={status}; see {log}")
        parsed = endpoint(log.read_text())
        if list(parsed[:4]) != registration["expected_endpoint"]:
            raise RuntimeError(f"{label}: INVALID endpoint {parsed[:4]}")
        wall = re.fullmatch(r"wall=([\d.]+),exit=0\n?", timing.read_text())
        if not wall:
            raise RuntimeError(f"{label}: INVALID emu exit/timing")
        result.update(host_s=parsed[4], emu_wall_s=float(wall[1]), emu_exit=0, endpoint=list(parsed[:4]))
        results.append(result)
        (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(f"DONE {label} Host={parsed[4]:.3f}s emu_wall={wall[1]}s", flush=True)
    stats = summary(results)
    (output / "summary.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2), flush=True)


if __name__ == "__main__":
    main()
