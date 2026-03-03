#!/usr/bin/env python3

import sys
import time
from pathlib import Path

import wolvrix


def log(message: str) -> None:
    sys.stderr.write(f"[wolvrix-xs-repcut] {message}\n")
    sys.stderr.flush()


if len(sys.argv) < 3:
    raise RuntimeError(
        "usage: wolvrix_xs_repcut.py <json_in> <json_out> [log_level]"
    )

json_in = Path(sys.argv[1])
json_out = Path(sys.argv[2])
log_level = sys.argv[3] if len(sys.argv) > 3 else "info"

if not json_in.exists():
    raise RuntimeError(f"input json not found: {json_in}")

total_start = time.perf_counter()

start = time.perf_counter()
log(f"read_json start {json_in}")
design = wolvrix.read_json(str(json_in))
log(f"read_json done {int((time.perf_counter() - start) * 1000)}ms")

start = time.perf_counter()
log("pass strip-debug start")
design.run_pipeline(
    ["strip-debug"],
    diagnostics="info",
    log_level=log_level,
    print_diagnostics_level="info",
    raise_diagnostics_level="error",
)
log(f"pass strip-debug done {int((time.perf_counter() - start) * 1000)}ms")

start = time.perf_counter()
log(f"write_json start {json_out}")
json_out.parent.mkdir(parents=True, exist_ok=True)
design.write_json(str(json_out))
log(f"write_json done {int((time.perf_counter() - start) * 1000)}ms")

start = time.perf_counter()
log("read_json start (roundtrip)")
design = wolvrix.read_json(str(json_out))
log(f"read_json done (roundtrip) {int((time.perf_counter() - start) * 1000)}ms")

start = time.perf_counter()
sv_out = json_out.with_suffix(".sv")
log(f"write_sv start {sv_out}")
design.write_sv(str(sv_out))
log(f"write_sv done {int((time.perf_counter() - start) * 1000)}ms")

log(f"total done {int((time.perf_counter() - total_start) * 1000)}ms")
