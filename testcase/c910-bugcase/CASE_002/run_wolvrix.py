#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import wolvrix

def log(message: str) -> None:
    sys.stderr.write(f"[c910-bugcase-002] {message}\n")
    sys.stderr.flush()


def main() -> int:
    case_dir = Path(__file__).resolve().parent
    repo_root = (case_dir / "../../..").resolve()
    filelist = case_dir / "filelist.f"

    out_dir = Path(os.environ.get("OUT_DIR", repo_root / "build" / "c910_bugcase" / "CASE_002"))
    out_dir.mkdir(parents=True, exist_ok=True)

    log_level = os.environ.get("WOLF_LOG", "info")
    top_name = os.environ.get("WOLF_TOP", "sim_top")
    emitted_sv = out_dir / f"{top_name}_wolf.sv"
    json_path = out_dir / f"{top_name}_wolf.json"

    log(f"filelist: {filelist}")
    log(f"top: {top_name}")
    log(f"out_dir: {out_dir}")
    log(f"output json: {json_path}")
    log(f"output sv: {emitted_sv}")

    start = time.perf_counter()
    log("read_sv start")
    design, _read_diags = wolvrix.read_sv(
        None,
        slang_args=["-f", str(filelist), "--top", top_name],
        log_level=log_level,
        diagnostics="info",
        print_diagnostics_level="info",
        raise_diagnostics_level="error",
    )
    log(f"read_sv done {int((time.perf_counter() - start) * 1000)}ms")

    pipeline = [
        "xmr-resolve",
        "multidriven-guard",
        "blackbox-guard",
        "latch-transparent-read",
        ("hier-flatten", ["-sym-protect", "hierarchy"]),
        "comb-loop-elim",
    ]

    start = time.perf_counter()
    log("pipeline start")
    design.run_pipeline(
        pipeline,
        diagnostics="info",
        log_level=log_level,
        print_diagnostics_level="info",
        raise_diagnostics_level="error",
    )
    log(f"pipeline done {int((time.perf_counter() - start) * 1000)}ms")

    start = time.perf_counter()
    log("write_json start")
    design.write_json(str(json_path))
    log(f"write_json done {int((time.perf_counter() - start) * 1000)}ms")

    start = time.perf_counter()
    log("write_sv start")
    design.write_sv(str(emitted_sv))
    log(f"write_sv done {int((time.perf_counter() - start) * 1000)}ms")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
