#!/usr/bin/env python3
"""Run the formal proved-zero backend comparison with verified THP code pages.

The common comparison driver owns scheduling, Difftest checks, timing parsing,
and AB/BA aggregation.  This wrapper only injects the existing process-local
code-page preload into each simulation command and audits complete huge-page
coverage after the run.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import repcut_cost_model_compare as common


PRELOAD = (common.REPO /
           "build/repcut_grhsim_20260925/active_dispatch_20261003/"
           "formal_zero_backend_perf_20261010/codepage_probe_once/"
           "codepage.so")


def command_for(run: dict, binaries: dict[str, Path], output: Path) -> list[str]:
    command = common._unwrapped_command_for(run, binaries, output)
    binary = str(binaries[run["variant"]])
    index = command.index(binary)
    command[index:index] = [
        "/usr/bin/env",
        f"LD_PRELOAD={PRELOAD}",
        "REPCUT_CODEPAGE_MODE=thp",
    ]
    return command


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
    if not PRELOAD.is_file():
        raise SystemExit(f"THP preload not found: {PRELOAD}")
    common._unwrapped_command_for = common.command_for
    common.command_for = command_for
    common.main()
    if "--dry-run" in sys.argv:
        return
    # common.main() obtains the output path from argv.  Locate it from the
    # required --output argument after the common driver has completed.
    args = sys.argv[1:]
    output = Path(args[args.index("--output") + 1]).resolve()
    audit_thp(output)


if __name__ == "__main__":
    main()
