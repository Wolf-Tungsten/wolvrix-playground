"""Run sequential, CPU-pinned CoreMark comparisons through project Make targets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enabled", type=Path, required=True)
    parser.add_argument("--disabled", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=2)
    parser.add_argument("--repetitions", type=int, default=2)
    args = parser.parse_args()
    if args.repetitions < 2:
        parser.error("at least two runs per version are needed for timing")
    if args.cpu not in os.sched_getaffinity(0):
        parser.error("chosen CPU is unavailable")
    args.output.mkdir(parents=True, exist_ok=True)
    binaries = {}
    for mode in ("enabled", "disabled"):
        binary = (getattr(args, mode) / "emu" / "emu").resolve(strict=True)
        digest = hashlib.sha256()
        with binary.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        binaries[mode] = {"path": str(binary), "sha256": digest.hexdigest()}
    results = []
    for repeat in range(args.repetitions):
        # Reverse order on alternate rounds to reduce drift bias.
        modes = ("disabled", "enabled") if repeat % 2 == 0 else ("enabled", "disabled")
        for mode in modes:
            run_id = f"{mode}_{repeat}"
            log = args.output / f"{run_id}.log"
            if log.exists():
                raise RuntimeError(f"refusing to overwrite a previous benchmark: {log}")
            command = ["make", "--no-print-directory", "run_xs_wolf_grhsim_ir_emu",
                       f"XS_GRHSIM_IR_BUILD={getattr(args, mode).resolve()}",
                       f"XS_LOG_DIR={args.output.resolve()}", "XS_SIM_MAX_CYCLE=50000",
                       "XS_PROGRESS_EVERY_CYCLES=1000", f"RUN_ID={run_id}",
                       f"XS_EMU_PREFIX=taskset -c {args.cpu} stdbuf -oL -eL"]
            print(f"START {run_id} cpu={args.cpu}", flush=True)
            start = time.monotonic()
            with log.open("x") as stream:
                completed = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                                           env={**os.environ, "WOLF_ENV_SOURCED": "1"})
            text = re.sub(r"\x1b\[[0-9;]*m", "", log.read_text())
            progress = re.findall(r"host_cycles=(\d+) model_cycles=(\d+) instr=(\d+) "
                                  r"commit_pc=(\S+) trap_pc=(\S+).*?host_ms=(\d+)", text)
            host = re.search(r"Host time spent: (\d+)ms", text)
            if (completed.returncode or not progress or
                    tuple(map(int, progress[-1][:2])) != (50000, 50000) or not host):
                raise RuntimeError(f"incomplete/failed 50k run {run_id}; inspect {log}")
            if "Difftest enabled" not in text or "cycles=50000 max_cycles=50000" not in text:
                raise RuntimeError(f"missing difftest/cycle-limit evidence in {log}")
            if re.search(r"mismatch|ABORT|HIT BAD TRAP", text, re.IGNORECASE):
                raise RuntimeError(f"difftest failure in {log}")
            first10k = next((row for row in progress if int(row[0]) == 10000), None)
            result = {"mode": mode, "repeat": repeat, "cpu": args.cpu,
                      "binary": binaries[mode], "command": command,
                      "returncode": completed.returncode,
                      "host_ms": int(host[1]), "wall_seconds": time.monotonic() - start,
                      "first_10k_ms": int(first10k[5]) if first10k else None,
                      "instructions": int(progress[-1][2]), "commit_pc": progress[-1][3],
                      "trap_pc": progress[-1][4], "log": str(log)}
            results.append(result)
            (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
            print(f"DONE {run_id} host_ms={result['host_ms']} instructions={result['instructions']}", flush=True)
    endpoints = {(r["instructions"], r["commit_pc"], r["trap_pc"]) for r in results}
    if len(endpoints) != 1:
        raise RuntimeError("enabled and disabled runs differ at the 50k endpoint")
    medians = {mode: statistics.median(r["host_ms"] for r in results if r["mode"] == mode)
               for mode in ("disabled", "enabled")}
    summary = {"median_host_ms": medians,
               "enabled_over_disabled": medians["enabled"] / medians["disabled"]}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
