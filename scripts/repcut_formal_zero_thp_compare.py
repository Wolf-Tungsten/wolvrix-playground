#!/usr/bin/env python3
"""Run a RepCut comparison with verified THP code pages.

The common comparison driver owns scheduling, Difftest checks, timing parsing,
and AB/BA aggregation.  This wrapper only injects the existing process-local
code-page preload into each simulation command and audits complete huge-page
coverage after the run. Optional wrapper flags: --numa-policy bind|preferred,
--collapse-retry PATH, and --require-compute-alignment BYTES. The last flag
checks actual GrhSIM function addresses before starting any simulation.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import repcut_cost_model_compare as common


PRELOAD = (common.REPO /
           "build/repcut_grhsim_20260925/active_dispatch_20261003/"
           "formal_zero_backend_perf_20261010/codepage_probe_once/"
           "codepage.so")


def with_codepage(command: list[str], binary: str, numa_policy: str = "bind",
                  collapse_retry: Path | None = None) -> list[str]:
    command = list(command)
    if numa_policy == "preferred":
        command[command.index("--membind=1")] = "--preferred=1"
    elif numa_policy != "bind":
        raise ValueError(f"unknown NUMA policy: {numa_policy}")
    preloads = [PRELOAD] if collapse_retry is None else [collapse_retry, PRELOAD]
    index = command.index(binary)
    command[index:index] = [
        "/usr/bin/env",
        "LD_PRELOAD=" + ":".join(str(path) for path in preloads),
        "REPCUT_CODEPAGE_MODE=thp",
        "WOLVI_GRHSIM_CODE_HUGEPAGE=0",
    ]
    return command


def command_for(run: dict, binaries: dict[str, Path], output: Path) -> list[str]:
    binary = str(binaries[run["variant"]])
    base = getattr(common, "_unwrapped_command_for", common.command_for)
    return with_codepage(base(run, binaries, output), binary)


def audit_compute_alignment(binary: Path, alignment: int) -> dict:
    if alignment <= 0 or alignment & (alignment - 1):
        raise ValueError("compute alignment must be a positive power of two")
    symbols = subprocess.check_output(["nm", "-n", str(binary)], text=True)
    functions = [(int(m[1], 16), m[2]) for m in re.finditer(
        r"^([0-9a-fA-F]+) [Tt] (\S+eval_compute_batch_\d+Ev)$", symbols, re.M)]
    if not functions:
        raise ValueError(f"no GrhSIM compute entries found: {binary}")
    misaligned = [(address, name) for address, name in functions if address % alignment]
    if misaligned:
        raise ValueError(f"{binary}: {len(misaligned)}/{len(functions)} compute entries "
                         f"are not aligned to {alignment} bytes")
    return {"binary": common.identity(binary), "alignment_bytes": alignment,
            "compute_entries": len(functions), "misaligned": 0}


def audit_thp(output: Path) -> None:
    rows = []
    for log in sorted(output.glob("*.log")):
        text = log.read_text()
        matches = re.findall(
            r"\[codepage\] PASS mode=(\w+) bytes=(\d+) anon_huge=(\d+) "
            r"regions=(\d+) setup_s=([0-9.]+) pid=(\d+)", text)
        if len(matches) != 1:
            raise RuntimeError(f"{log}: expected one complete THP report")
        mode, size, huge, regions, setup, pid = matches[0]
        if mode != "thp" or int(size) <= 0 or int(size) != int(huge):
            raise RuntimeError(f"{log}: incomplete THP coverage: {matches[0]}")
        rows.append({"log": log.name, "mode": mode, "bytes": int(size),
                     "huge_bytes": int(huge), "regions": int(regions),
                     "setup_s": float(setup), "pid": int(pid)})
    if not rows:
        raise RuntimeError(f"no simulation logs found in {output}")
    (output / "thp_verification.json").write_text(
        json.dumps({"status": "pass", "preload": str(PRELOAD.resolve()),
                    "runs": rows}, indent=2) + "\n")
    summary = output / "summary.json"
    if summary.is_file():
        data = json.loads(summary.read_text())
        data["codepage"] = {"mode": "thp", "preload": str(PRELOAD.resolve()),
                             "runs": len(rows),
                             "mapped_bytes": sorted({r["bytes"] for r in rows}),
                             "huge_bytes": sorted({r["huge_bytes"] for r in rows})}
        summary.write_text(json.dumps(data, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--numa-policy", choices=("bind", "preferred"), default="bind")
    parser.add_argument("--collapse-retry", type=Path,
                        help="optional process-local MADV_COLLAPSE retry preload")
    parser.add_argument("--require-compute-alignment", type=int)
    options, remaining = parser.parse_known_args()
    if not PRELOAD.is_file():
        raise SystemExit(f"THP preload not found: {PRELOAD}")
    if options.collapse_retry is not None:
        options.collapse_retry = options.collapse_retry.resolve(strict=True)
    alignment = {}
    if options.require_compute_alignment is not None and "--help" not in remaining:
        binary_parser = argparse.ArgumentParser(add_help=False)
        binary_parser.add_argument("--baseline-binary", required=True, type=Path)
        binary_parser.add_argument("--candidate-binary", required=True, type=Path)
        binaries, _ = binary_parser.parse_known_args(remaining)
        alignment = {name: audit_compute_alignment(getattr(binaries, name + "_binary"),
                                                 options.require_compute_alignment)
                     for name in common.VARIANTS}
    original_command = common.command_for
    original_argv = sys.argv

    def configured_command(run, binaries, output):
        return with_codepage(original_command(run, binaries, output),
                             str(binaries[run["variant"]]), options.numa_policy,
                             options.collapse_retry)

    common.command_for = configured_command
    sys.argv = [sys.argv[0], *remaining]
    try:
        common.main()
    finally:
        common.command_for = original_command
        sys.argv = original_argv
    if "--dry-run" in sys.argv:
        return
    # common.main() obtains the output path from argv.  Locate it from the
    # required --output argument after the common driver has completed.
    args = sys.argv[1:]
    output = Path(args[args.index("--output") + 1]).resolve()
    audit_thp(output)
    policy = {"numa_policy": options.numa_policy, "codepage_mode": "thp",
              "preload": common.identity(PRELOAD),
              "collapse_retry": common.identity(options.collapse_retry)
              if options.collapse_retry is not None else None,
              "compute_alignment": alignment}
    (output / "measurement_policy.json").write_text(json.dumps(policy, indent=2) + "\n")


if __name__ == "__main__":
    main()
