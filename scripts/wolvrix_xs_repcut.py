#!/usr/bin/env python3

import sys
import time
from pathlib import Path

import wolvrix


def log(message: str) -> None:
    sys.stderr.write(f"[wolvrix-xs-repcut] {message}\n")
    sys.stderr.flush()


def _build_repcut_kwargs(
    work_dir: Path,
) -> dict:
    kwargs = {
        "path": REPCUT_PATH,
        "partition_count": REPCUT_PARTITION_COUNT,
        "imbalance_factor": REPCUT_IMBALANCE_FACTOR,
        "work_dir": str(work_dir),
        "partitioner": REPCUT_PARTITIONER,
        "mtkahypar_preset": REPCUT_MTKAHYPAR_PRESET,
        "mtkahypar_threads": REPCUT_MTKAHYPAR_THREADS,
    }
    if REPCUT_KEEP_INTERMEDIATE_FILES:
        kwargs["keep_intermediate_files"] = True
    return kwargs

# pass targets (edit here if top symbol changes)
TOP_MODULE_PATH = "SimTop"
REPCUT_PATH = TOP_MODULE_PATH

# repcut parameters (edit here)
REPCUT_PARTITION_COUNT = "32"
REPCUT_IMBALANCE_FACTOR = "0.015"
REPCUT_PARTITIONER = "mt-kahypar"
REPCUT_MTKAHYPAR_PRESET = "quality"
REPCUT_MTKAHYPAR_THREADS = "0"
REPCUT_KEEP_INTERMEDIATE_FILES = True

if len(sys.argv) < 4:
    raise RuntimeError(
        "usage: wolvrix_xs_repcut.py <json_in> <json_out> <work_dir> [log_level] [package_out_dir]"
    )

json_in = Path(sys.argv[1])
json_out = Path(sys.argv[2])
repcut_work_dir = Path(sys.argv[3])
log_level = sys.argv[4] if len(sys.argv) > 4 else "info"
package_out_dir = Path(sys.argv[5]) if len(sys.argv) > 5 else None

if not json_in.exists():
    raise RuntimeError(f"input json not found: {json_in}")

total_start = time.perf_counter()

with wolvrix.Session() as sess:
    sess.log_level = log_level

    start = time.perf_counter()
    log(f"read_json start {json_in}")
    sess.read_json_file(str(json_in), out_design="design.main")
    log(f"read_json done {int((time.perf_counter() - start) * 1000)}ms")

    start = time.perf_counter()
    log(f"pass repcut start path={REPCUT_PATH}")
    repcut_work_dir.mkdir(parents=True, exist_ok=True)
    repcut_kwargs = _build_repcut_kwargs(repcut_work_dir)
    sess.run_pass("repcut", design="design.main", **repcut_kwargs)
    log(f"pass repcut args argc={len(repcut_kwargs)}")
    log(f"pass repcut done {int((time.perf_counter() - start) * 1000)}ms")

    start = time.perf_counter()
    log(f"write_json start {json_out}")
    json_out.parent.mkdir(parents=True, exist_ok=True)
    sess.store_json(design="design.main", output=str(json_out))
    log(f"write_json done {int((time.perf_counter() - start) * 1000)}ms")

    start = time.perf_counter()
    log("read_json start (roundtrip)")
    sess.read_json_file(str(json_out), out_design="design.main", replace=True)
    log(f"read_json done (roundtrip) {int((time.perf_counter() - start) * 1000)}ms")

    start = time.perf_counter()
    sv_out_arg = json_out.with_suffix(".sv")
    sv_out_dir = sv_out_arg.with_suffix("") if sv_out_arg.suffix == ".sv" else sv_out_arg
    log(f"write_sv start {sv_out_dir}")
    sess.emit_sv(design="design.main", output=str(sv_out_dir), top=[TOP_MODULE_PATH], split_modules=True)
    log(f"write_sv done {int((time.perf_counter() - start) * 1000)}ms")

    if package_out_dir is not None:
        start = time.perf_counter()
        log(f"write_verilator_repcut_package start {package_out_dir}")
        package_out_dir.mkdir(parents=True, exist_ok=True)
        sess.emit_verilator_repcut_package(
            design="design.main",
            output=str(package_out_dir),
            top=[TOP_MODULE_PATH],
        )
        log(f"write_verilator_repcut_package done {int((time.perf_counter() - start) * 1000)}ms")

    log(f"total done {int((time.perf_counter() - total_start) * 1000)}ms")
