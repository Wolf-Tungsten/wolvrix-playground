#!/usr/bin/env python3

import sys
import time
from pathlib import Path

import wolvrix


def log(message: str) -> None:
    sys.stderr.write(f"[wolvrix-xs-repcut] {message}\n")
    sys.stderr.flush()

# pass targets (edit here if top symbol changes)
TOP_MODULE_PATH = "SimTop"
TOP_LOGIC_INSTANCE_PATH = "SimTop.logic_part"
REPCUT_PATH = TOP_LOGIC_INSTANCE_PATH
INSTANCE_INLINE_PATH = TOP_LOGIC_INSTANCE_PATH

# repcut parameters (edit here)
REPCUT_PARTITION_COUNT = "32"
REPCUT_IMBALANCE_FACTOR = "0.015"
REPCUT_PARTITIONER = "mt-kahypar"
REPCUT_MTKAHYPAR_PRESET = "quality"
REPCUT_MTKAHYPAR_THREADS = "0"
REPCUT_KEEP_INTERMEDIATE_FILES = True

if len(sys.argv) < 4:
    raise RuntimeError(
        "usage: wolvrix_xs_repcut.py <json_in> <json_out> <work_dir> [log_level]"
    )

json_in = Path(sys.argv[1])
json_out = Path(sys.argv[2])
repcut_work_dir = Path(sys.argv[3])
log_level = sys.argv[4] if len(sys.argv) > 4 else "info"

if not json_in.exists():
    raise RuntimeError(f"input json not found: {json_in}")

total_start = time.perf_counter()

start = time.perf_counter()
log(f"read_json start {json_in}")
design = wolvrix.read_json(str(json_in))
log(f"read_json done {int((time.perf_counter() - start) * 1000)}ms")

start = time.perf_counter()
log(f"pass strip-debug start path={TOP_MODULE_PATH}")
design.run_pass(
    "strip-debug",
    args=["-path", TOP_MODULE_PATH],
    diagnostics="info",
    log_level=log_level,
    print_diagnostics_level="info",
    raise_diagnostics_level="error",
)
log(f"pass strip-debug done {int((time.perf_counter() - start) * 1000)}ms")

start = time.perf_counter()
log(f"pass repcut start path={REPCUT_PATH}")
repcut_work_dir.mkdir(parents=True, exist_ok=True)
repcut_args = [
    "-path",
    REPCUT_PATH,
    "-partition-count",
    REPCUT_PARTITION_COUNT,
    "-imbalance-factor",
    REPCUT_IMBALANCE_FACTOR,
    "-work-dir",
    str(repcut_work_dir),
    "-partitioner",
    REPCUT_PARTITIONER,
    "-mtkahypar-preset",
    REPCUT_MTKAHYPAR_PRESET,
    "-mtkahypar-threads",
    REPCUT_MTKAHYPAR_THREADS,
]
if REPCUT_KEEP_INTERMEDIATE_FILES:
    repcut_args.append("-keep-intermediate-files")

design.run_pass(
    "repcut",
    args=repcut_args,
    diagnostics="info",
    log_level=log_level,
    print_diagnostics_level="info",
    raise_diagnostics_level="error",
)
log(f"pass repcut done {int((time.perf_counter() - start) * 1000)}ms")

start = time.perf_counter()
log(f"pass instance-inline start path={INSTANCE_INLINE_PATH}")
design.run_pass(
    "instance-inline",
    args=["-path", INSTANCE_INLINE_PATH],
    diagnostics="info",
    log_level=log_level,
    print_diagnostics_level="info",
    raise_diagnostics_level="error",
)
log(f"pass instance-inline done {int((time.perf_counter() - start) * 1000)}ms")

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
sv_out_arg = json_out.with_suffix(".sv")
sv_out_dir = sv_out_arg.with_suffix("") if sv_out_arg.suffix == ".sv" else sv_out_arg
log(f"write_sv start {sv_out_dir}")
design.write_sv(str(sv_out_dir), top=[TOP_MODULE_PATH], split_modules=True)
log(f"write_sv done {int((time.perf_counter() - start) * 1000)}ms")

log(f"total done {int((time.perf_counter() - total_start) * 1000)}ms")
