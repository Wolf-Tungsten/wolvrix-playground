#!/usr/bin/env python3
"""Prepare frozen ROB sources and compare every output word, invoked through Make."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import time

from grhsim_provenance import file_identity, generated_identity


ROOT = Path(__file__).resolve().parents[1]
OLD_MODEL = Path("ptmp/xs-components-rob-array-create/candidate")
OLD_TRACE = Path("ptmp/xs-components-rob/trace/rob_trace.bin")
OLD_RTL = Path("testcase/xs-components/rob/rtl")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def frozen(args, relative):
    path = args.baseline / "frozen" / relative
    manifest = json.loads((args.baseline / "manifest.json").read_text())
    expected = manifest["artifacts"][str(Path("frozen") / relative)]
    if path.stat().st_size != expected["size"] or digest(path) != expected["sha256"]:
        raise RuntimeError("Frozen input changed: " + str(path))
    return path


def prepare(args):
    args.output.mkdir(parents=True, exist_ok=True)
    rtl = args.output / "rtl"
    rtl.mkdir(exist_ok=True)
    source_list = frozen(args, OLD_MODEL / "rtl.f")
    entries, hashes = [], {}
    for line in source_list.read_text().splitlines():
        relative = OLD_RTL / Path(line).name
        source = frozen(args, relative)
        destination = rtl / source.name
        if not destination.exists() or digest(destination) != digest(source):
            shutil.copy2(source, destination)
        entries.append(str(destination))
        hashes[str(relative)] = digest(source)
    (args.output / "rtl.f").write_text("\n".join(entries) + "\n")
    (args.output / "read_args.txt").write_text("-I\n" + str(rtl) + "\n-D\nDIFFTEST\n")
    bench = args.output / "bench"
    bench.mkdir(exist_ok=True)
    source = frozen(args, OLD_MODEL / "bench/rob_bench.cpp")
    shutil.copy2(source, bench / source.name)
    (args.output / "inputs.json").write_text(json.dumps({"source_sha256": hashes,
        "frozen_bench_sha256": digest(source), "trace": str(args.baseline / "frozen" / OLD_TRACE),
        "exclusions": 0}, indent=2) + "\n")


def comparison_identity(output):
    model = output / "model"
    sidecar = model / "generation-identity.json"
    identity = json.loads(sidecar.read_text()) if sidecar.exists() else None
    generated = generated_identity(model)
    if identity and identity.get("generated") != generated:
        raise RuntimeError("Generated ROB sources differ from their generation identity")
    sources = {"original-sv": "original SV generation", "checkpoint-reemit": "GRH checkpoint reemit",
               "flat-grh-resume": "flat GRH checkpoint resume", "api-emit": "direct API emit"}
    return {"source": sources.get(identity["kind"], "unclassified generation") if identity else
            "generation identity unavailable; original SV generation is not established",
            "generation_identity": file_identity(sidecar) if identity else None,
            "generated_sources": generated,
            "executable": file_identity(output / "dump_outputs"),
            "library": file_identity(model / "libgrhsim_Rob.a"),
            "bench": file_identity(output / "bench/rob_bench.cpp"),
            "inputs": file_identity(output / "inputs.json")}


def compare(args):
    trace = frozen(args, OLD_TRACE)
    golden = frozen(args, OLD_MODEL / "all_outputs.bin")
    actual = args.output / "all_outputs.bin"
    identity = comparison_identity(args.output)
    start = time.perf_counter()
    with (args.output / "dump.log").open("w") as log:
        subprocess.run([str(args.output / "dump_outputs"), str(trace), str(actual)],
                       cwd=args.output, stdout=log, stderr=subprocess.STDOUT, check=True)
    elapsed = time.perf_counter() - start
    with golden.open("rb") as old, actual.open("rb") as current:
        offset = 0
        while True:
            left, right = old.read(8 * 1024 * 1024), current.read(8 * 1024 * 1024)
            if left != right:
                index = next((i for i, (a, b) in enumerate(zip(left, right)) if a != b), min(len(left), len(right)))
                raise RuntimeError(f"ROB all-output difference at byte {offset + index}; exclusions=0")
            if not left:
                break
            offset += len(left)
    if comparison_identity(args.output) != identity:
        raise RuntimeError("ROB generation or executable changed during comparison")
    result = {"equal": True, "exclusions": 0, "observed_bytes": offset, "sha256": digest(actual),
              "elapsed_seconds": elapsed, "trace_sha256": digest(trace), **identity}
    (args.output / "comparison.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in (
        "equal", "exclusions", "observed_bytes", "sha256", "elapsed_seconds", "trace_sha256", "source")}), flush=True)


def compare_prefix(args):
    """Check already produced bytes without treating a partial run as passed."""
    golden = frozen(args, OLD_MODEL / "all_outputs.bin")
    actual = args.output / "all_outputs.bin"
    limit = min(golden.stat().st_size, actual.stat().st_size)
    if limit < 24:
        raise RuntimeError("ROB has not produced its output header")
    with golden.open("rb") as old, actual.open("rb") as current:
        offset = 0
        while offset < limit:
            count = min(8 * 1024 * 1024, limit - offset)
            left, right = old.read(count), current.read(count)
            if left != right:
                index = next((i for i, (a, b) in enumerate(zip(left, right)) if a != b), min(len(left), len(right)))
                raise RuntimeError(f"ROB prefix difference at byte {offset + index}; exclusions=0")
            offset += len(left)
    result = {"prefix_equal": True, "observed_bytes": limit, "exclusions": 0,
              "complete": False, "scope": "partial output diagnostic; full process/comparison still required"}
    (args.output / "prefix-comparison.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


def runtime_sample(text, cycles):
    match = re.fullmatch(r"cycles=(\d+) checksum=(\d+) init_seconds=([\d.eE+-]+) run_seconds=([\d.eE+-]+)\s*", text)
    if not match or int(match[1]) != cycles:
        raise ValueError("ROB runtime probe lacks the exact requested cycle endpoint")
    result = {"cycles": int(match[1]), "checksum": int(match[2]),
              "init_seconds": float(match[3]), "run_seconds": float(match[4])}
    if not all(math.isfinite(result[key]) and result[key] >= 0 for key in ("init_seconds", "run_seconds")):
        raise ValueError("ROB runtime probe has invalid timing")
    if result["run_seconds"] == 0:
        raise ValueError("ROB runtime probe requires positive run timing")
    return result


def runtime_screen(args):
    """Alternating diagnostic only; this is not the full R6 performance gate."""
    trace = frozen(args, OLD_TRACE)
    old_library = frozen(args, OLD_MODEL / "grhsim-model/libgrhsim_Rob.a")
    programs = {"old": args.old_runtime.resolve(), "new": args.output / "runtime_probe"}
    identity = {"candidate": comparison_identity(args.output), "trace": file_identity(trace),
                "old_library": file_identity(old_library),
                "programs": {name: file_identity(path) for name, path in programs.items()}}
    available = os.sched_getaffinity(0)
    cpu = args.cpu if args.cpu is not None else min(available)
    if cpu not in available or args.cycles <= 0:
        raise ValueError("runtime screening requires an available CPU and positive cycle count")
    directory = args.output / "runtime-screen"
    directory.mkdir(exist_ok=True)
    samples, expected = [], None
    for index in range(4):
        for name, program in programs.items():
            completed = subprocess.run(["taskset", "-c", str(cpu), str(program), str(trace), str(args.cycles)],
                                       cwd=directory, capture_output=True, text=True, check=True)
            (directory / f"{index}-{name}.stdout").write_text(completed.stdout)
            (directory / f"{index}-{name}.stderr").write_text(completed.stderr)
            sample = runtime_sample(completed.stdout, args.cycles)
            if expected is not None and sample["checksum"] != expected:
                raise RuntimeError("ROB old/new runtime checksum differs")
            expected = sample["checksum"]
            if index:
                samples.append({"mode": name, "pair": index, **sample})
            print(f"runtime-screen {name} {'warmup' if not index else index}: {sample}", flush=True)
    if comparison_identity(args.output) != identity["candidate"] or any(
            file_identity(programs[name]) != identity["programs"][name] for name in programs):
        raise RuntimeError("ROB runtime executable/generation changed during screening")
    medians = {name: statistics.median(sample["run_seconds"] for sample in samples if sample["mode"] == name)
               for name in programs}
    result = {"schema": "wolvrix.remove-grhsim-ir.runtime-screen.v1", "cpu": cpu,
              "scope": "bounded diagnostic; not the full generation/compile/RSS/100k R6 gate",
              "cycles": args.cycles, "checksum": expected, "samples": samples, "median_seconds": medians,
              "new_over_old": medians["new"] / medians["old"], "identity": identity}
    (directory / "comparison.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("scope", "cycles", "median_seconds", "new_over_old")}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "compare", "compare-prefix", "runtime-screen"))
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--old-runtime", type=Path, default=ROOT / "ptmp/remove-grhsim-ir/r6-rob-frozen-runtime/runtime_probe")
    parser.add_argument("--cycles", type=int, default=2000)
    parser.add_argument("--cpu", type=int)
    args = parser.parse_args()
    args.baseline, args.output = args.baseline.resolve(), args.output.resolve()
    if not args.output.is_relative_to(ROOT / "ptmp/remove-grhsim-ir") or args.output.is_relative_to(args.baseline):
        parser.error("output must be isolated under ptmp/remove-grhsim-ir")
    if args.mode == "prepare":
        prepare(args)
    elif args.mode == "compare-prefix":
        compare_prefix(args)
    elif args.mode == "runtime-screen":
        runtime_screen(args)
    else:
        compare(args)


if __name__ == "__main__":
    main()
