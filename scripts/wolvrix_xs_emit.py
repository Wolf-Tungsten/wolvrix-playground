#!/usr/bin/env python3

import shlex
import sys
import time
from pathlib import Path
import wolvrix


def parse_tokens(value: str) -> list[str]:
    if not value:
        return []
    return shlex.split(value)


def log(message: str) -> None:
    sys.stderr.write(f"[wolvrix-xs] {message}\n")
    sys.stderr.flush()


if len(sys.argv) < 6:
    raise RuntimeError(
        "usage: wolvrix_xs_emit.py <filelist> <top> <sv_out> <json_out> <read_args_file> [log_level]"
    )

filelist = sys.argv[1]
top_name = sys.argv[2]
sv_out = sys.argv[3]
json_out = sys.argv[4]
read_args_file = sys.argv[5]
log_level = sys.argv[6] if len(sys.argv) > 6 else "info"

total_start = time.perf_counter()

read_args: list[str] = ["-f", filelist, "--top", top_name]

if read_args_file:
    path = Path(read_args_file)
    if not path.exists():
        raise RuntimeError(f"read args file not found: {read_args_file}")
    for line in path.read_text(encoding="utf-8").splitlines():
        token = line.strip()
        if token:
            read_args.extend(parse_tokens(token))

start = time.perf_counter()
log("read_sv start")
design, _read_diags = wolvrix.read_sv(
    None,
    slang_args=read_args,
    log_level=log_level,
    diagnostics="warn",
    print_diagnostics_level="warn",
    raise_diagnostics_level="error",
)
log(f"read_sv done {int((time.perf_counter() - start) * 1000)}ms")

pipeline = [
    "xmr-resolve",
    "multidriven-guard",
    "blackbox-guard",
    "latch-transparent-read",
    "hier-flatten",
    "comb-loop-elim",
    ("simplify", ["-semantics", "2state"]),
    "memory-init-check",
    "stats",
]
for pass_spec in pipeline:
    pass_name = pass_spec[0] if isinstance(pass_spec, (tuple, list)) else pass_spec
    start = time.perf_counter()
    log(f"pass {pass_name} start")
    design.run_pipeline(
        [pass_spec],
        diagnostics="warn",
        log_level=log_level,
        print_diagnostics_level="warn",
        raise_diagnostics_level="error",
    )
    log(f"pass {pass_name} done {int((time.perf_counter() - start) * 1000)}ms")

start = time.perf_counter()
log(f"write_json start {json_out}")
design.write_json(json_out)
log(f"write_json done {int((time.perf_counter() - start) * 1000)}ms")

start = time.perf_counter()
log("read_json start")
design = wolvrix.read_json(json_out)
log(f"read_json done {int((time.perf_counter() - start) * 1000)}ms")

start = time.perf_counter()
log(f"write_sv start {sv_out}")
design.write_sv(sv_out)
log(f"write_sv done {int((time.perf_counter() - start) * 1000)}ms")

log(f"total done {int((time.perf_counter() - total_start) * 1000)}ms")
