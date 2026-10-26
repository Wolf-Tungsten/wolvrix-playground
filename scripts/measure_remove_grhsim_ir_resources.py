"""Measure a Make workflow's elapsed time and simultaneous process-tree RSS."""

import argparse
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import time

from grhsim_provenance import file_identity, generated_identity, write_identity


ROOT = Path(__file__).resolve().parents[1]


def python_command(executable, no_site):
    return shlex.join([executable] + (["-S"] if no_site else []))


def process_snapshot(proc=Path("/proc")):
    records = {}
    for entry in proc.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(") ", 1)[1].split()
            if fields[0] == "Z":
                continue
            records[int(entry.name)] = {"parent": int(fields[1]), "group": int(fields[2]),
                "start": int(fields[19]), "rss_kib": max(0, int(fields[21])) * os.sysconf("SC_PAGE_SIZE") // 1024}
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return records


def tree_sample(records, root, known):
    selected = {pid for pid, row in records.items()
                if pid == root or row["group"] == root or (pid, row["start"]) in known}
    while True:
        children = {pid for pid, row in records.items() if row["parent"] in selected}
        if children <= selected:
            break
        selected |= children
    known.update((pid, records[pid]["start"]) for pid in selected)
    return len(selected), sum(records[pid]["rss_kib"] for pid in selected)


def measure(target, flow, output, *, jobs=4, frozen_binding=None):
    if output.exists() or not output.is_relative_to(ROOT / "ptmp/remove-grhsim-ir"):
        raise ValueError("measurement output must be new under ptmp/remove-grhsim-ir")
    if not flow.is_relative_to(ROOT / "ptmp/remove-grhsim-ir"):
        raise ValueError("flow must be under ptmp/remove-grhsim-ir")
    generation = target != "xs_grhsim_build_emu"
    if generation and (flow / "model").exists():
        raise ValueError("generation measurement requires a fresh model directory")
    if not generation:
        model = flow / "model"
        if not (model / "Makefile").is_file() or (flow / "emu").exists() or any(model.glob("*.o")) or any(model.glob("*.a")) or any(model.glob("*.pch")):
            raise ValueError("build measurement requires generated sources without compiled artifacts")
    output.mkdir(parents=True)
    # Editable-install .pth hooks can override PYTHONPATH and load an old
    # binding against a candidate core library. Preserve an explicitly
    # isolated interpreter when Make launches the generation scripts.
    python = python_command(os.sys.executable, os.sys.flags.no_site)
    command = ["make", "--no-print-directory", target, f"PYTHON={python}", "SKIP_PY_INSTALL=1",
               f"REMOVE_GRHSIM_IR_XS_FRESH={flow}", f"XS_GRHSIM_BUILD={flow}", f"VM_BUILD_JOBS={jobs}"]
    if frozen_binding:
        command.append(f"REMOVE_GRHSIM_IR_FROZEN_COMPILER={frozen_binding}")
    env = dict(os.environ); env.update(WOLF_ENV_SOURCED="1", LC_ALL="C", PYTHONDONTWRITEBYTECODE="1")
    env.pop("MAKEFLAGS", None); env.pop("MFLAGS", None)
    toolchain = {tool: subprocess.check_output([tool, "--version"], text=True).splitlines()[0]
                 for tool in ("clang++", "make")}
    registration = {"schema": "wolvrix.remove-grhsim-ir.resources.v1", "command": command,
        "host": platform.node(), "kernel": platform.release(), "toolchain": toolchain,
        "sample_interval_s": 0.05, "jobs": jobs, "target": target, "flow": str(flow),
        "rss_definition": "maximum sampled simultaneous sum of resident pages in the Make process tree; shared pages counted per process",
        "limitation": "sampling may miss peaks shorter than 50ms; not maximum-child ru_maxrss",
        "driver": file_identity(__file__), "makefile": file_identity(ROOT / "Makefile"),
        "identity_inputs": {name: file_identity(flow / name) for name in ("inputs.json", "graph.generation-identity.json") if (flow / name).is_file()}}
    if not generation:
        registration["generated"] = generated_identity(flow / "model")
    if frozen_binding:
        registration["frozen_binding"] = file_identity(frozen_binding / "source-identity.json")
    write_identity(output / "registration.json", registration)
    known = set(); peak = 0; peak_processes = 0; samples = 0
    start = time.monotonic()
    with (output / "make.log").open("w") as log, (output / "rss.tsv").open("w") as trace:
        trace.write("elapsed_s\tprocesses\tsimultaneous_rss_kib\n")
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        while True:
            count, rss = tree_sample(process_snapshot(), process.pid, known)
            elapsed = time.monotonic() - start
            trace.write(f"{elapsed:.6f}\t{count}\t{rss}\n"); trace.flush(); samples += 1
            if rss > peak:
                peak, peak_processes = rss, count
            if process.poll() is not None and count == 0:
                break
            time.sleep(0.05)
        status = process.wait()
    result = {"exit": status, "wall_s": time.monotonic() - start, "peak_simultaneous_rss_kib": peak,
              "processes_at_peak": peak_processes, "samples": samples,
              "registration": file_identity(output / "registration.json"),
              "classification": "MEASURED" if status == 0 else "FAILED",
              "scope": "one observation; no automatic performance acceptance"}
    if target == "build_remove_grhsim_ir_xs_from_sv":
        executable = flow / "emu/emu"
        result["scope"] = "aggregate-all original SV through generated C++ to linked emu"
        result["budget_s"] = 2100
        result["binary"] = file_identity(executable) if executable.is_file() else None
        result["within_compile_budget"] = status == 0 and executable.is_file() and result["wall_s"] < 2100
    write_identity(output / "result.json", result)
    print(json.dumps(result, indent=2), flush=True)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("generate_remove_grhsim_ir_xs", "generate_remove_grhsim_ir_xs_frozen",
                        "build_remove_grhsim_ir_xs_from_sv", "xs_grhsim_build_emu"), required=True)
    parser.add_argument("--flow", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--frozen-binding", type=Path)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("jobs must be positive")
    return measure(args.target, args.flow.resolve(), args.output.resolve(), jobs=args.jobs,
                   frozen_binding=args.frozen_binding.resolve() if args.frozen_binding else None)


if __name__ == "__main__":
    raise SystemExit(main())
