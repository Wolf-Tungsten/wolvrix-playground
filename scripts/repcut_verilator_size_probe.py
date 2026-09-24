#!/usr/bin/env python3
"""Measure Verilator-generated C++ source shape, not runtime or machine code.

The default probe emits six independent operations at six operand widths.
Only Verilator --cc is run; no compiler, executable, XiangShan input, or DPI
dependency is required. Outputs must go into a fresh directory.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time


OPERATIONS = ("identity", "add", "reduce_or", "static_slice", "dynamic_slice", "shift")
DEFAULT_WIDTHS = (32, 64, 65, 128, 256, 1024)
HELPER_RE = re.compile(r"\b(VL_[A-Z][A-Z0-9_]*)\s*(?:<[^;\n]*?>)?\s*\(")


def parse_cpus(value: str) -> set[int]:
    cpus = set()
    for entry in value.split(","):
        bounds = entry.split("-")
        if len(bounds) == 1:
            cpus.add(int(bounds[0]))
        elif len(bounds) == 2:
            low, high = map(int, bounds)
            if high < low:
                raise ValueError(f"reversed CPU range: {entry}")
            cpus.update(range(low, high + 1))
        else:
            raise ValueError(f"invalid CPU range: {entry}")
    if not cpus or min(cpus) < 0:
        raise ValueError("CPU list must be nonempty and nonnegative")
    return cpus


def fixture(operation: str, width: int) -> tuple[str, dict]:
    index_width = max(1, math.ceil(math.log2(2 * width)))
    output_width = 1 if operation == "reduce_or" else width
    offset = width // 2 + 1
    expressions = {
        "identity": "a",
        "add": "a + b",
        "reduce_or": "|a",
        "static_slice": f"source[{offset} +: {width}]",
        "dynamic_slice": f"source[index +: {width}]",
        "shift": "a << index",
    }
    expression = expressions[operation]
    sv = (
        "module Probe (\n"
        f"    input logic [{width - 1}:0] a,\n"
        f"    input logic [{width - 1}:0] b,\n"
        f"    input logic [{2 * width - 1}:0] source,\n"
        f"    input logic [{index_width - 1}:0] index,\n"
        f"    output logic [{output_width - 1}:0] y\n"
        ");\n"
        f"    assign y = {expression};\n"
        "endmodule\n"
    )
    description = {
        "operation": operation,
        "nominal_width_bits": width,
        "input_a_width_bits": width,
        "input_b_width_bits": width,
        "slice_source_width_bits": 2 * width,
        "index_width_bits": index_width,
        "output_width_bits": output_width,
        "expression": expression,
        "semantics": "combinational unsigned fixed-width SystemVerilog; output truncates add/shift",
    }
    if operation == "static_slice":
        description["slice_lsb"] = offset
    if operation == "dynamic_slice":
        description["index_note"] = "unrestricted input index; partial/out-of-range selections are possible"
    return sv, description


def run_command(command: list[str], directory: Path, name: str, timeout: float) -> dict:
    started = time.monotonic()
    stdout_path = directory / f"{name}.stdout.log"
    stderr_path = directory / f"{name}.stderr.log"
    with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
        try:
            result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=timeout, check=False)
            returncode, timed_out = result.returncode, False
        except subprocess.TimeoutExpired:
            returncode, timed_out = None, True
    return {
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "generation_wall_seconds": time.monotonic() - started,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }


def file_metrics(path: Path) -> dict:
    content = path.read_bytes()
    text = content.decode("utf-8", errors="replace")
    # Helpers here are textual call occurrences, not expanded helper bodies or
    # dynamic invocations. Ignore comment text before scanning.
    without_comments = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    helpers = Counter(HELPER_RE.findall(without_comments))
    return {
        "name": path.name,
        "bytes": len(content),
        "lines": len(text.splitlines()),
        "nonempty_lines": sum(bool(line.strip()) for line in text.splitlines()),
        "sha256": hashlib.sha256(content).hexdigest(),
        "helper_call_occurrences": dict(sorted(helpers.items())),
    }


def summarize_files(files: list[dict]) -> dict:
    helpers = Counter()
    for row in files:
        helpers.update(row["helper_call_occurrences"])
    return {
        "file_count": len(files),
        "bytes": sum(row["bytes"] for row in files),
        "lines": sum(row["lines"] for row in files),
        "nonempty_lines": sum(row["nonempty_lines"] for row in files),
        "helper_call_occurrences": dict(sorted(helpers.items())),
        "files": files,
    }


def collect_metrics(obj_dir: Path) -> dict:
    fast_paths = sorted(path for path in obj_dir.glob("*.cpp") if "__Slow" not in path.name)
    slow_paths = sorted(path for path in obj_dir.glob("*.cpp") if "__Slow" in path.name)
    fast = [file_metrics(path) for path in fast_paths]
    root_fast = [row for row in fast if row["name"].startswith("VProbe___024root__")]
    if not root_fast:
        raise RuntimeError(f"no fast root implementation C++ generated in {obj_dir}")
    return {
        "all_cpp_excluding_slow": summarize_files(fast),
        "root_cpp_excluding_slow": summarize_files(root_fast),
        "slow_cpp_excluded": [path.name for path in slow_paths],
        "headers_excluded": [path.name for path in sorted(obj_dir.glob("*.h"))],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=Path("build/repcut_cost_model_20260922/verilator_probe"),
                        help="fresh artifact directory (refuses an existing nonempty directory)")
    parser.add_argument("--verilator", type=Path, default=Path("/nfs/home/tanghaojin/verilator/bin/verilator"))
    parser.add_argument("--widths", type=int, nargs="+", default=list(DEFAULT_WIDTHS))
    parser.add_argument("--operations", nargs="+", choices=OPERATIONS, default=list(OPERATIONS))
    parser.add_argument("--require-host", default="node030", help="required short hostname; defaults to node030")
    parser.add_argument("--cpus", default="96-127", help="CPU affinity for this process and its Verilator children")
    parser.add_argument("--timeout", type=float, default=120, help="seconds allowed per Verilator invocation")
    args = parser.parse_args()
    host = socket.gethostname()
    if host.split(".", 1)[0] != args.require_host:
        parser.error(f"must run on {args.require_host}, current host is {host}")
    if any(width < 2 for width in args.widths) or len(args.widths) != len(set(args.widths)):
        parser.error("widths must be distinct integers >= 2")
    if len(args.operations) != len(set(args.operations)) or args.timeout <= 0:
        parser.error("operations must be distinct and timeout must be positive")
    try:
        cpus = parse_cpus(args.cpus)
        os.sched_setaffinity(0, cpus)
    except (ValueError, OSError) as error:
        parser.error(f"cannot set requested CPU affinity: {error}")
    if os.sched_getaffinity(0) != cpus:
        parser.error("the effective CPU affinity differs from the requested CPUs")
    verilator = args.verilator.resolve()
    if not verilator.is_file() or not os.access(verilator, os.X_OK):
        parser.error(f"Verilator is not executable: {verilator}")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error(f"output directory must be fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)
    version = run_command([str(verilator), "--version"], output, "version", args.timeout)
    version["text"] = Path(version["stdout_path"]).read_text().strip()
    summary = {
        "schema_version": 1,
        "measurement": "static generated C++ source size and textual helper calls; no machine-code size or runtime measurement",
        "status": "running",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "host": host,
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "argv": sys.argv,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "verilator": version,
        "common_flags": ["--cc", "--top-module", "Probe", "--prefix", "VProbe"],
        "notes": [
            "Each case is independently generated; no build or simulation is performed.",
            "Input operands are public ports, not constants; the identity case exposes fixed generated scaffolding.",
            "Fast C++ excludes filenames containing __Slow; headers and runtime helper definitions are not included.",
            "Root-fast metrics isolate generated root implementation files, excluding model facade and symbol-table C++.",
            "Helper counts are lexical call occurrences, not runtime calls, helper body size, or executed instruction counts.",
            "Widths describe a/b and output except reduction (one-bit output); slice source is twice the nominal width.",
            "Compiler inlining, backend optimization, scheduling and activity can change machine code and runtime independently.",
        ],
        "cases": [],
    }
    summary_path = output / "summary.json"

    def save_summary() -> None:
        summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    save_summary()
    if version["returncode"] != 0:
        summary["status"] = "failed"
        save_summary()
        return 1
    for width in args.widths:
        for operation in args.operations:
            directory = output / f"{operation}_w{width}"
            directory.mkdir()
            sv, case = fixture(operation, width)
            source = directory / "Probe.sv"
            source.write_text(sv)
            obj_dir = directory / "obj_dir"
            command = [str(verilator), *summary["common_flags"], "--Mdir", str(obj_dir), str(source)]
            case["source_path"] = str(source)
            case["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
            case["generation"] = run_command(command, directory, "verilator", args.timeout)
            case["status"] = "pass" if case["generation"]["returncode"] == 0 else "failed"
            if case["status"] == "pass":
                try:
                    case["metrics"] = collect_metrics(obj_dir)
                except RuntimeError as error:
                    case["status"] = "failed"
                    case["metrics_error"] = str(error)
            summary["cases"].append(case)
            save_summary()
            print(f"{operation:14s} width={width:4d} {case['status']}", flush=True)
    summary["status"] = "pass" if all(case["status"] == "pass" for case in summary["cases"]) else "failed"
    summary["finished_utc"] = datetime.now(timezone.utc).isoformat()
    save_summary()
    print(f"{summary['status']}: {summary_path}")
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
