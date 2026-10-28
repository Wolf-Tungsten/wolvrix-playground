"""Evidence for the full-build and six-run protocol in grhsim-perf-opt/goal.md."""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import time

from grhsim_provenance import source_identity


ORDER = ("new", "old", "new", "old", "new", "old")
BUILD_LIMIT_S = 2400
INPUT_NAMES = ("coremark-2-iteration.bin", "riscv64-nemu-interpreter-so")
FAILURE = re.compile(r"mismatch|HIT BAD TRAP|Assertion .*failed|Assertion failed|ABORT|Segmentation fault", re.I)
PROFILING_FLAG = re.compile(
    r"-f(?:cs-|auto-|memory-)?profile|--coverage|-[fl]to-profile|"
    r"-f(?:test-coverage|coverage-mapping|branch-probabilities)\b|"
    r"(?:^|\s)-pgo-(?:kind|test-profile-file)=")
FIXED = {
    "XS_NUM_CORES": "1", "XS_EMU_THREADS": "0", "EMU_THREADS": "0",
    "WOLVRIX_GRHSIM_WAVEFORM": "0", "WOLVRIX_GRHSIM_PERF": "0",
    "WOLVRIX_GRHSIM_SN_TIMING": "0", "DIFFTEST_PERFCNT": "0",
    "PGO_CFLAGS": "", "PGO_LDFLAGS": "", "XS_WAVEFORM": "0",
    "XS_WAVEFORM_FULL": "0", "XS_WAVEFORM_PATH": "",
    "XS_COMMIT_TRACE": "0", "XS_RAM_TRACE": "0",
    "XS_PROGRESS_EVERY_CYCLES": "0", "XS_LOG_BEGIN": "0", "XS_LOG_END": "0",
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def positive_integer(value: str) -> int:
    try:
        result = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if result <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return result


def clean_environment() -> dict:
    env = {key: value for key, value in os.environ.items()
           if key not in ("CPUPROFILE", "CPUPROFILE_FREQUENCY", "LD_PRELOAD",
                          "LLVM_PROFILE_FILE", "GCOV_PREFIX", "MAKEFLAGS", "MFLAGS",
                          "MAKELEVEL", "MAKEOVERRIDES", "WOLVRIX_GRHSIM_SN_PROFILE")}
    for key, value in env.items():
        if PROFILING_FLAG.search(value):
            raise ValueError(f"inherited profiling flag in {key}; use a clean non-PGO environment")
    env.update(FIXED)
    env.update(WOLF_ENV_SOURCED="1", LC_ALL="C", EMU_RUNTIME_PROFILE="0",
               EMU_PHASE_TIMING="0", EMU_PROGRESS_EVERY_CYCLES="0")
    return env


def new_output(path: Path, root: Path) -> Path:
    path = path.resolve()
    if not path.is_relative_to(root / "ptmp") or path == root / "ptmp" or path.exists():
        raise ValueError("output must be a new directory under repository ptmp/")
    path.mkdir(parents=True)
    return path


def input_paths(root: Path, rtl: Path) -> dict[str, Path]:
    paths = {name: root / "testcase/xiangshan/ready-to-run" / name for name in INPUT_NAMES}
    # Hash source SV and include files, not generated checkpoints or compiled outputs.
    for directory in (rtl, root / "testcase/xiangshan/difftest/src/test/vsrc/common",
                      root / "testcase/xiangshan/build/generated-src"):
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix in (".sv", ".v", ".svh", ".vh"):
                paths[str(path.relative_to(root))] = path
    if not any(path.is_file() for path in rtl.rglob("*.sv")):
        raise ValueError(f"aggregate SV input is missing: {rtl}")
    return paths


def fingerprints(paths: dict[str, Path]) -> dict:
    return {name: {"path": str(path), "sha256": digest(path)} for name, path in paths.items()}


def benchmark_identity(root: Path, rtl: Path, fixed_paths: dict[str, Path]) -> dict:
    # Re-enumerate each time: additions to an RTL/include directory are changes too.
    paths = {**input_paths(root, rtl), **fixed_paths}
    runtime = root / "testcase/xiangshan/difftest"
    for directory in (runtime / "src", runtime / "config", root / "testcase/xiangshan/build/generated-src"):
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix in (".cpp", ".cc", ".c", ".hpp", ".h"):
                paths[str(path.relative_to(root))] = path
    for path in sorted(runtime.glob("*")):
        if path.is_file() and (path.suffix == ".mk" or path.name == "Makefile"):
            paths[str(path.relative_to(root))] = path
    identity = fingerprints(paths)
    identity["source_identity"] = source_identity(root)
    return identity


def parse_endpoint(text: str) -> dict:
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    if FAILURE.search(text) or "Difftest enabled" not in text:
        raise ValueError("difftest failed or was not enabled")
    counts = re.findall(r"Core-0 instrCnt = (\d+), cycleCnt = (\d+)", text)
    guest = re.findall(r"Seed=(\d+)\s+Guest cycle spent: (\d+)", text)
    pc = re.findall(r"EXCEEDING CYCLE/INSTR LIMIT at pc = (0x[0-9a-fA-F]+)", text)
    host = re.findall(r"Host time spent: (\d+)ms", text)
    limits = [tuple(map(int, entry)) for entry in
              re.findall(r"\[CYCLE_LIMIT\] cycles=(-?\d+) max_cycles=(-?\d+)", text)]
    if any(len(values) != 1 for values in (counts, guest, pc, host)):
        raise ValueError("missing or ambiguous complete 100k endpoint/Host ms")
    if guest[0][0] != "0" or not limits or limits[-1] != (100000, 100000):
        raise ValueError("seed is not zero or run did not reach the 100k cycle limit")
    if any(max_cycles != 100000 or not 0 <= cycles <= max_cycles for cycles, max_cycles in limits) or \
            any(previous[0] >= current[0] for previous, current in zip(limits, limits[1:])):
        raise ValueError("cycle-limit progress must increase within the fixed 100k limit")
    if int(host[0]) <= 0:
        raise ValueError("Host milliseconds must be positive")
    return {"endpoint": [int(counts[0][0]), int(counts[0][1]), int(guest[0][1]), pc[0].lower()],
            "host_ms": int(host[0]), "seed": 0, "max_cycles": 100000}


def summarize(results: list[dict], threshold: Decimal) -> dict:
    if [row["mode"] for row in results] != list(ORDER):
        raise ValueError("exactly six runs in new/old/new/old/new/old order are required")
    if not threshold.is_finite() or threshold <= 0:
        raise ValueError("threshold must be positive and finite")
    if any(type(row["host_ms"]) is not int or row["host_ms"] <= 0 for row in results):
        raise ValueError("all six original Host millisecond values must be positive integers")
    new = [row["host_ms"] for row in results[::2]]
    old = [row["host_ms"] for row in results[1::2]]
    speedup = (Decimal(sum(old)) / Decimal(sum(new)) - 1) * 100
    # Compare the integer ratio by cross multiplication, without rounding a displayed percent.
    passed = Decimal(sum(old)) * 100 >= Decimal(sum(new)) * (100 + threshold)
    return {"classification": "passed" if passed else "failed",
            "scope": "six-run performance; full-build evidence is checked separately",
            "primary_metric": "original emu Host time spent, integer milliseconds",
            "order": list(ORDER), "new_host_ms": new, "old_host_ms": old,
            "new_sum_ms": sum(new), "old_sum_ms": sum(old),
            "pair_speedup_percent": [str((Decimal(o) / Decimal(n) - 1) * 100) for n, o in zip(new, old)],
            "speedup_percent": str(speedup), "threshold_percent": str(threshold),
            "threshold_passed": passed}


def observe_emu(make_pid: int, binary: Path, cpu: int) -> list[dict]:
    """Read process control metadata only: no execution counters or samples."""
    pending, seen, observations = [make_pid], set(), []
    while pending:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        proc = Path("/proc") / str(pid)
        try:
            pending.extend(int(value) for value in (proc / f"task/{pid}/children").read_text().split())
            if (proc / "exe").resolve() != binary:
                continue
            status = (proc / "status").read_text()
            threads = int(re.search(r"^Threads:\s+(\d+)", status, re.M)[1])
            allowed = sorted(os.sched_getaffinity(pid))
            observations.append({"pid": pid, "threads": threads, "cpus_allowed": allowed})
        except (OSError, ProcessLookupError):
            continue
    for observation in observations:
        if observation["threads"] != 1 or observation["cpus_allowed"] != [cpu]:
            raise ValueError(f"emu is not single-threaded on CPU{cpu}: {observation}")
    return observations


def stop_process_group(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    # The group can retain descendants after Make itself exits.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_logged(command: list[str], root: Path, env: dict, directory: Path,
               timeout_s: float | None = None, observer=None) -> dict:
    (directory / "command.sh").write_text(shlex.join(command) + "\n")
    start = time.monotonic()
    observations, reason, last_observation = [], None, -math.inf
    interrupted = False
    with (directory / "make.log").open("w") as log:
        process = subprocess.Popen(command, cwd=root, env=env, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while process.poll() is None:
                elapsed = time.monotonic() - start
                if timeout_s is not None and elapsed >= timeout_s:
                    reason = "full build exceeded 2400 seconds"
                if observer is not None and elapsed - last_observation >= (10 if observations else 0.1):
                    try:
                        observations.extend({"elapsed_s": elapsed, **row} for row in observer(process.pid))
                    except ValueError as error:
                        reason = str(error)
                    last_observation = elapsed
                if reason:
                    stop_process_group(process)
                    break
                time.sleep(0.1)
        except KeyboardInterrupt:
            reason, interrupted = "interrupted by user", True
            stop_process_group(process)
        status = process.wait()
    result = {"returncode": status, "wall_s": time.monotonic() - start,
              "terminated_reason": reason, "process_observations": observations}
    save(directory / "process.json", result)
    if interrupted:
        raise KeyboardInterrupt
    return result


def assignments(values: list[str]) -> dict:
    result = {}
    protected = set(FIXED) | {"XS_GRHSIM_BUILD", "XS_GRHSIM_RESUME_FROM_FLAT_GRH_JSON",
                            "XS_GRHSIM_FILELIST", "XS_GRHSIM_FLAT_GRH_JSON",
                            "XS_GRHSIM_JSON", "XS_GRHSIM_ROUNDTRIP_JSON", "XS_GRHSIM_EMIT_CPP_DIR",
                            "XS_EMU_PREFIX", "XS_EMU_DIFF_ARGS", "XS_SIM_MAX_CYCLE",
                            "VM_BUILD_JOBS", "XS_VM_BUILD_JOBS"}
    for assignment in values:
        key, separator, value = assignment.partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError("--make-var requires NAME=VALUE")
        if key in protected or "PGO" in key or PROFILING_FLAG.search(value):
            raise ValueError(f"--make-var cannot override protocol configuration: {key}")
        result[key] = value
    return result


def compiler_information(settings: dict, env: dict, root: Path) -> dict:
    result = {}
    for variable, default in (("CC", "clang"), ("CXX", "clang++")):
        invocation = settings.get(variable, env.get(variable, default))
        command = shlex.split(invocation) + ["--version"]
        try:
            version = subprocess.run(command, cwd=root, env=env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, timeout=10)
            result[variable] = {"invocation": invocation, "command": command,
                                "returncode": version.returncode, "version": version.stdout}
        except (OSError, subprocess.SubprocessError) as error:
            result[variable] = {"invocation": invocation, "command": command, "error": str(error)}
    return result


def build(args, root: Path) -> int:
    extra = assignments(args.make_var)
    if args.jobs <= 0:
        raise ValueError("build jobs must be positive")
    env = clean_environment()
    paths = input_paths(root, args.rtl.resolve())
    output = new_output(args.output, root)
    identity = fingerprints(paths)
    settings = {**extra, **FIXED, "XS_GRHSIM_BUILD": str(output),
                "XS_RTL_BUILD": str(args.rtl.resolve().parent),
                "XS_GRHSIM_FILELIST": str(output / "xs_grhsim.f"),
                "XS_GRHSIM_FLAT_GRH_JSON": str(output / "xiangshan_flat_grh.json"),
                "XS_GRHSIM_JSON": str(output / "xiangshan_grhsim.json"),
                "XS_GRHSIM_ROUNDTRIP_JSON": str(output / "xiangshan_grhsim_roundtrip.json"),
                "XS_GRHSIM_EMIT_CPP_DIR": str(output / "model"),
                "XS_GRHSIM_RESUME_FROM_FLAT_GRH_JSON": "0",
                "XS_LOG_DIR": str(output / "logs"), "XS_VM_BUILD_JOBS": str(args.jobs),
                "VM_BUILD_JOBS": str(args.jobs)}
    command = ["make", "--no-print-directory", f"-j{args.jobs}", "xs_grhsim_emu"]
    command.extend(f"{key}={value}" for key, value in settings.items())
    compilers = compiler_information(settings, env, root)
    save(output / "build-preregister.json", {"target": "xs_grhsim_emu",
         "full_from_sv": True, "timeout_s": BUILD_LIMIT_S, "jobs": args.jobs,
         "settings": settings, "compilers": compilers,
         "inputs_before": identity, "timestamp": time.time()})
    result = run_logged(command, root, env, output, timeout_s=BUILD_LIMIT_S)
    result.update(inputs_before=identity, inputs_after=fingerprints(input_paths(root, args.rtl.resolve())), jobs=args.jobs,
                  target="xs_grhsim_emu", full_from_sv=True, timeout_s=BUILD_LIMIT_S,
                  settings=settings, compilers=compilers)
    result["generation_identities"] = fingerprints({str(path.relative_to(output)): path for path in (
        output / "xiangshan_grhsim.generation-identity.json", output / "model/generation-identity.json")
        if path.is_file()})
    binary = output / "emu/emu"
    valid = (result["returncode"] == 0 and not result["terminated_reason"] and
             result["wall_s"] <= BUILD_LIMIT_S and binary.is_file() and os.access(binary, os.X_OK) and
             result["inputs_before"] == result["inputs_after"])
    result["classification"] = "passed" if valid else "failed"
    if binary.is_file():
        result["binary"] = {"path": str(binary), "sha256": digest(binary)}
    save(output / "build.json", result)
    print(json.dumps(result, indent=2), flush=True)
    return 0 if valid else 1


def benchmark(args, root: Path) -> int:
    threshold = Decimal(args.threshold)
    if not threshold.is_finite() or threshold <= 0:
        raise ValueError("threshold must be positive and finite")
    if args.cpu not in os.sched_getaffinity(0):
        raise ValueError(f"CPU{args.cpu} is not available")
    env = clean_environment()
    flows = {mode: getattr(args, mode).resolve() for mode in ("new", "old")}
    # difftest exposes emu/emu as a symlink; /proc/<pid>/exe resolves its target.
    binaries = {mode: (flow / "emu/emu").resolve() for mode, flow in flows.items()}
    if any(not path.is_file() or not os.access(path, os.X_OK) for path in binaries.values()):
        raise ValueError("old/new emu executables must already exist")
    rtl = args.rtl.resolve()
    input_paths(root, rtl)
    # Hash invocation paths so changing a symlink target also invalidates the group.
    fixed_paths = {f"binary_{mode}": flow / "emu/emu" for mode, flow in flows.items()}
    fixed_paths["measurement_script"] = Path(__file__).resolve()
    fixed_paths["project_makefile"] = root / "Makefile"
    output = new_output(args.output, root)
    before = benchmark_identity(root, rtl, fixed_paths)
    registration = {"order": list(ORDER), "threshold_percent": str(threshold),
                    "cpu": args.cpu, "cycles": 100000, "seed": 0, "emu_threads": 0,
                    "primary_metric": "Host time spent: integer milliseconds",
                    "waveform": False, "trace": False, "progress": False,
                    "diagnostic_sampling": False, "extra_counters": False,
                    "process_metadata_poll_s": 10, "cache_eviction": False,
                    "fingerprints_before": before, "timestamp": time.time()}
    if args.max_new_host_ms is not None:
        registration.update(max_new_host_ms=args.max_new_host_ms,
                            max_new_host_ms_scope="early rejection reference only; not a measured old sample or formal speedup")
    save(output / "preregister.json", registration)
    results, expected, rejection = [], None, None
    try:
        for index, mode in enumerate(ORDER, 1):
            if benchmark_identity(root, rtl, fixed_paths) != before:
                raise ValueError("binary, input, source code, or measurement configuration changed between runs")
            directory = output / f"{index}_{mode}"
            directory.mkdir()
            settings = {**FIXED, "XS_GRHSIM_BUILD": str(flows[mode]),
                        "XS_RTL_BUILD": str(args.rtl.resolve().parent),
                        "XS_LOG_DIR": str(directory / "logs"),
                        "XS_WAVEFORM_DIR": str(directory / "logs"),
                        "RUN_ID": f"{output.name}_{index}_{mode}",
                        "XS_EMU_CPU": str(args.cpu), "XS_SIM_MAX_CYCLE": "100000",
                        "XS_EMU_PREFIX": shlex.join(["taskset", "-c", str(args.cpu), "stdbuf", "-oL", "-eL"]),
                        "XS_EMU_DIFF_ARGS": shlex.join(["--diff", before[INPUT_NAMES[1]]["path"], "-s", "0"])}
            command = ["make", "--no-print-directory", "run_xs_grhsim_emu"]
            command.extend(f"{key}={value}" for key, value in settings.items())
            print(f"START {index} {mode}", flush=True)
            process = run_logged(command, root, env, directory,
                                 observer=lambda pid: observe_emu(pid, binaries[mode], args.cpu))
            if process["returncode"] or process["terminated_reason"]:
                raise ValueError(f"run {index} {mode}: nonzero exit or invalid process metadata")
            if not process["process_observations"]:
                raise ValueError(f"run {index} {mode}: no runtime thread/affinity evidence")
            parsed = parse_endpoint((directory / "make.log").read_text(errors="replace"))
            if expected is None:
                expected = parsed["endpoint"]
            if parsed["endpoint"] != expected:
                raise ValueError(f"run {index} {mode}: endpoint differs: {parsed['endpoint']} != {expected}")
            result = {"ordinal": index, "mode": mode, **parsed, **process}
            results.append(result)
            save(directory / "result.json", result)
            save(output / "results.json", results)
            print(f"DONE {index} {mode}: Host={parsed['host_ms']}ms", flush=True)
            if mode == "new" and args.max_new_host_ms is not None and parsed["host_ms"] > args.max_new_host_ms:
                rejection = {"classification": "rejected",
                             "reason": f"run {index} new: Host {parsed['host_ms']}ms exceeds preregistered maximum {args.max_new_host_ms}ms",
                             "max_new_host_ms": args.max_new_host_ms,
                             "completed_runs": len(results), "samples": results,
                             "action": "Candidate rejected early; no six-run speedup is available."}
                break
        after = benchmark_identity(root, rtl, fixed_paths)
        save(output / "fingerprints-after.json", after)
        if after != before:
            raise ValueError("binary, input, source code, or measurement configuration changed during six-run group")
        result = rejection if rejection is not None else summarize(results, threshold)
        result.update(fingerprints_unchanged=True, endpoint=expected, runtime_thread_affinity_verified=True)
    except KeyboardInterrupt:
        result = {"classification": "aborted", "reason": "interrupted by user",
                  "completed_runs": len(results),
                  "action": "No six-run speedup is available. Record the stop reason before abandoning the candidate or repeating all six runs."}
        save(output / "summary.json", result)
        print(json.dumps(result, indent=2), flush=True)
        return 130
    except (OSError, ValueError) as error:
        try:
            save(output / "fingerprints-after.json", benchmark_identity(root, rtl, fixed_paths))
        except (OSError, ValueError) as identity_error:
            save(output / "fingerprints-after.json", {"error": str(identity_error)})
        result = {"classification": "invalid", "reason": str(error), "completed_runs": len(results),
                  "action": "Record the cause and repeat all six runs; do not retain selected samples."}
        save(output / "summary.json", result)
        print(json.dumps(result, indent=2), flush=True)
        return 2
    save(output / "summary.json", result)
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result.get("threshold_passed", False) else 1


def main(argv=None, root=None) -> int:
    root = Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    build_parser = commands.add_parser("build", help="fresh full SV -> emu with a 2400s wall limit")
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--jobs", type=int, default=32)
    build_parser.add_argument("--make-var", action="append", default=[])
    bench_parser = commands.add_parser("benchmark", help="exactly new/old/new/old/new/old on CoreMark100k")
    for name in ("old", "new", "output"):
        bench_parser.add_argument(f"--{name}", type=Path, required=True)
    bench_parser.add_argument("--threshold", required=True, help="user-required speedup percentage")
    bench_parser.add_argument("--max-new-host-ms", type=positive_integer,
                              help="preregistered early-rejection reference; stop after any complete new run exceeds it")
    bench_parser.add_argument("--cpu", type=int, default=2)
    for command in (build_parser, bench_parser):
        command.add_argument("--rtl", type=Path, default=root / "ptmp/xs/rtl/rtl")
    args = parser.parse_args(argv)
    try:
        return build(args, root) if args.action == "build" else benchmark(args, root)
    except (OSError, ValueError, InvalidOperation) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
