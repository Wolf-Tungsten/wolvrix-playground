#!/usr/bin/env python3
"""Build profile-only A/B binaries and attribute runtime work by category.

The profile binaries are deliberately separate from formal walltime binaries:
they contain runtime counters and phase timing, while the frozen RTL and model
configuration are reused from the already verified integer-bit experiment.
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "scripts/grhsim_single_baseline.py"
TOOLS = ROOT / "build/grhsim32-tools"
SOURCE = ROOT / "build/xs/integer_bit_20261107_v1"
MODELS = "int-alu,int-bku,vec-int-alu-lane,vec-int-pu-lane"
COMPILER = "/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++"
NEMU = ROOT / "testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so"
COREMARK = ROOT / "testcase/xiangshan/ready-to-run/coremark-2-iteration.bin"
MICROBENCH = ROOT / "testcase/xiangshan/ready-to-run/microbench.bin"


def run(command: list[object], log: Path) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as stream:
        result = subprocess.run([str(x) for x in command], cwd=ROOT,
                                stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(map(str, command))}\n"
                           + log.read_text(errors="replace")[-8000:])


def baseline_args(output: Path, *, sim_models: str, lowering: str,
                  reuse_rtl: Path | None, image: Path, cycles: int,
                  repeats: int, runtime_profile_dir: Path | None,
                  binary: Path | None = None) -> list[object]:
    command = [sys.executable, BASELINE,
               "measure" if binary is not None else "all",
               "--output", output,
               "--compiler", COMPILER,
               "--tools-dir", TOOLS,
               "--jobs", "32",
               "--sim-models", sim_models,
               "--behavior-compute-lowering", lowering,
               "--rtl-difftest", "on",
               "--model-difftest", "on",
               "--compile-difftest", "on",
               "--runtime-difftest", "on",
               "--cpu", "96",
               "--cycles", str(cycles),
               "--repeats", str(repeats),
               "--image", image,
               "--nemu", NEMU,
               "--profile-perf",
               "--skip-idle-check"]
    if binary is None:
        command += ["--emit-runtime-profile", "--reuse-rtl-from", reuse_rtl]
    else:
        command += ["--binary", binary]
    if runtime_profile_dir is not None:
        command += ["--runtime-profile-dir", runtime_profile_dir]
    return command


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--tools-dir", type=Path, default=TOOLS)
    parser.add_argument("--cycles", type=int, default=100000)
    parser.add_argument("--include-microbench", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not platform.node().startswith("node030"):
        raise RuntimeError("profile experiment must run on node030")
    source = args.source.resolve()
    tools = args.tools_dir.resolve()
    output = args.output.resolve()
    if args.force and output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    if not (tools / "python/wolvrix/_wolvrix.so").is_file():
        raise FileNotFoundError(tools / "python/wolvrix/_wolvrix.so")
    for variant, mode, lowering in (
        ("A", "hardware", "ordinary"),
        ("B", MODELS, "grouped"),
    ):
        source_variant = source / variant
        if not (source_variant / "rtl").is_dir() or not (source_variant / "chisel-home").is_dir():
            raise FileNotFoundError(f"frozen RTL/chisel output missing for {variant}: {source_variant}")
        variant_out = output / variant
        command = baseline_args(variant_out, sim_models=mode, lowering=lowering,
                                reuse_rtl=source_variant, image=COREMARK,
                                cycles=args.cycles, repeats=1,
                                runtime_profile_dir=output / "profiles" / variant / "coremark")
        run(command, output / f"{variant}.coremark.profile.log")
        if args.include_microbench:
            binary = variant_out / "emu/grhsim-compile/emu"
            micro_out = output / f"{variant}-microbench"
            command = baseline_args(micro_out, sim_models=mode, lowering=lowering,
                                    reuse_rtl=None, image=MICROBENCH,
                                    cycles=args.cycles, repeats=1,
                                    runtime_profile_dir=output / "profiles" / variant / "microbench",
                                    binary=binary)
            run(command, output / f"{variant}.microbench.profile.log")
    config = {
        "version": 1,
        "source": str(source),
        "tools": str(tools),
        "variants": {"A": "hardware", "B": MODELS},
        "workloads": ["coremark"] + (["microbench"] if args.include_microbench else []),
        "cycles": args.cycles,
        "profile_only": True,
        "skip_idle_check": True,
    }
    (output / "profile-config.json").write_text(json.dumps(config, indent=2) + "\n")
    print(json.dumps(config, indent=2), flush=True)


if __name__ == "__main__":
    main()
