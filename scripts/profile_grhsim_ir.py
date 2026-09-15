"""Sample an existing 100k model through the project Make target."""

import argparse
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import time

from benchmark_grhsim_ir import FAILURE, digest, endpoint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flow", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-seconds", type=float, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if (output.exists() or not output.is_relative_to(root / "ptmp") or
            not math.isfinite(args.baseline_seconds) or args.baseline_seconds <= 0):
        parser.error("output must be new under ptmp; baseline must be positive and finite")
    output.mkdir(parents=True)
    flow = args.flow.resolve()
    binary = flow / "emu/emu"
    profile = output / "cpu.prof"
    cutoff = args.baseline_seconds * 1.5
    prefix = shlex.join(["timeout", "--signal=KILL", f"{cutoff:.6f}s", "/usr/bin/time", "-f",
                         "wall=%e,exit=%x", "-o", str(output / "emu.time"), "taskset", "-c", "2",
                         "env", "LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libprofiler.so",
                         f"CPUPROFILE={profile}", "CPUPROFILE_FREQUENCY=200", "EMU_RUNTIME_PROFILE=1",
                         "EMU_PHASE_TIMING=1", "stdbuf", "-oL", "-eL"])
    command = ["make", "--no-print-directory", "run_xs_wolf_grhsim_ir_emu", f"XS_GRHSIM_IR_BUILD={flow}",
               f"XS_LOG_DIR={output / 'logs'}", f"RUN_ID={output.parent.name}_{output.name}",
               "XS_NUM_CORES=1", "XS_EMU_THREADS=1", "EMU_THREADS=1", "XS_EMU_CPU=2",
               "XS_SIM_MAX_CYCLE=100000", "XS_WAVEFORM=0", "XS_WAVEFORM_PATH=", "XS_COMMIT_TRACE=0",
               "XS_RAM_TRACE=0", "XS_PROGRESS_EVERY_CYCLES=0", f"XS_EMU_PREFIX={prefix}"]
    registration = {"binary": str(binary), "sha256": digest(binary), "cutoff_s": cutoff,
                    "command": command, "kind": "diagnostic only", "frequency_hz": 200,
                    "inputs": {name: digest(root / "testcase/xiangshan/ready-to-run" / name)
                               for name in ("coremark-2-iteration.bin", "riscv64-nemu-interpreter-so")}}
    (output / "registration.json").write_text(json.dumps(registration, indent=2) + "\n")
    env = {k: v for k, v in os.environ.items() if k not in ("LD_PRELOAD", "CPUPROFILE", "CPUPROFILE_FREQUENCY")}
    env["WOLF_ENV_SOURCED"] = "1"
    log = output / "make.log"
    start = time.monotonic()
    killed = None
    with log.open("w") as stream:
        process = subprocess.Popen(command, cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        while process.poll() is None:
            if FAILURE.search(log.read_text(errors="replace")):
                killed = "INVALID"
            elif time.monotonic() - start > cutoff + 30:
                killed = "REGRESSION_KILLED"
            if killed:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                break
            time.sleep(0.5)
        status = process.wait()
    elapsed = time.monotonic() - start
    if status and not killed:
        killed = "REGRESSION_KILLED" if status in (137, -9) or elapsed >= cutoff else "INVALID"
    result = {"exit": status, "classification": killed, "make_wall_s": elapsed}
    (output / "status.json").write_text(json.dumps(result, indent=2) + "\n")
    if killed or status:
        raise RuntimeError(str(result))
    text = log.read_text()
    final = endpoint(text)
    if final[:4] != (240349, 99996, 100001, "0x80000c0c"):
        raise RuntimeError(f"INVALID endpoint {final}")
    timing = re.fullmatch(r"wall=([\d.]+),exit=0\n?", (output / "emu.time").read_text())
    if not timing:
        raise RuntimeError("INVALID emu exit/timing")
    samples = re.search(r"PROFILE: interrupts/evictions/bytes = (\d+)/", text)
    if not samples or digest(binary) != registration["sha256"]:
        raise RuntimeError("missing sample count or changed binary")
    profiles = [p for p in output.glob("cpu.prof*") if p.stat().st_size > 0]
    if len(profiles) != 1:
        raise RuntimeError("expected exactly one nonempty model profile")
    profile = profiles[0]
    result.update(endpoint=final, emu_wall_s=float(timing[1]), samples=int(samples[1]),
                  classification="VALID_DIAGNOSTIC")
    (output / "status.json").write_text(json.dumps(result, indent=2) + "\n")
    with (output / "analysis.txt").open("w") as analysis:
        subprocess.run(["make", "--no-print-directory", "analyze_grhsim_cpu_profile",
                        f"PYTHON={os.sys.executable}", f"GRHSIM_CPU_PROFILE={profile}",
                        f"GRHSIM_CPU_PROFILE_BINARY={binary}",
                        f"GRHSIM_CPU_PROFILE_MODEL={flow / 'model/grhsim_SimTop.cpp'}",
                        f"GRHSIM_CPU_PROFILE_SAMPLES={samples[1]}"], cwd=root, env=env, check=True,
                       stdout=analysis, stderr=subprocess.STDOUT)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
