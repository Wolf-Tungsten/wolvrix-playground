#!/usr/bin/env python3

import os
import sys
import time
from pathlib import Path

import wolvrix


def log(message: str) -> None:
    sys.stderr.write(f"[wolvrix-xs-repcut] {message}\n")
    sys.stderr.flush()


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name, "1" if default else "0").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean (0/1, true/false, yes/no, on/off)")


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
        "weight_mode": REPCUT_WEIGHT_MODE,
        "cost_model": REPCUT_COST_MODEL,
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
REPCUT_BACKEND = os.environ.get("XS_REPCUT_BACKEND", "verilator").strip().lower()
if REPCUT_BACKEND not in {"verilator", "grhsim"}:
    raise RuntimeError("XS_REPCUT_BACKEND must be one of: verilator, grhsim")
REPCUT_WEIGHT_MODE = os.environ.get("XS_REPCUT_WEIGHT_MODE", "closure-aware")
REPCUT_COST_MODEL = os.environ.get(
    "XS_REPCUT_COST_MODEL", "legacy" if REPCUT_BACKEND == "grhsim" else "verilator-v1"
)
REPCUT_KEEP_INTERMEDIATE_FILES = True
REPCUT_ENABLE_MEMORY_WRITE_COALESCE = _env_bool(
    "XS_REPCUT_MEMORY_WRITE_COALESCE", True
)
REPCUT_ENABLE_REG_TO_MEM = _env_bool("XS_REPCUT_REG_TO_MEM", True)
REPCUT_REG_TO_MEM_PROFITABILITY_FILTER = os.environ.get(
    "XS_REPCUT_REG_TO_MEM_PROFITABILITY_FILTER",
    "none" if REPCUT_BACKEND == "grhsim" else "verilator-v1",
).strip().lower()

if REPCUT_WEIGHT_MODE not in {"baseline", "closure-aware"}:
    raise RuntimeError(
        "XS_REPCUT_WEIGHT_MODE must be one of: baseline, closure-aware"
    )

if REPCUT_COST_MODEL not in {"legacy", "verilator-v1", "verilator-lowered-v1"}:
    raise RuntimeError(
        "XS_REPCUT_COST_MODEL must be one of: legacy, verilator-v1, verilator-lowered-v1"
    )

if REPCUT_REG_TO_MEM_PROFITABILITY_FILTER not in {"none", "verilator-v1"}:
    raise RuntimeError(
        "XS_REPCUT_REG_TO_MEM_PROFITABILITY_FILTER must be one of: none, verilator-v1"
    )

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
    log(
        f"pass repcut start path={REPCUT_PATH} "
        f"backend={REPCUT_BACKEND} weight_mode={REPCUT_WEIGHT_MODE} cost_model={REPCUT_COST_MODEL}"
    )
    repcut_work_dir.mkdir(parents=True, exist_ok=True)
    repcut_kwargs = _build_repcut_kwargs(repcut_work_dir)
    sess.run_pass("repcut", design="design.main", **repcut_kwargs)
    log(f"pass repcut args argc={len(repcut_kwargs)}")
    log(f"pass repcut done {int((time.perf_counter() - start) * 1000)}ms")

    # Keep these transforms after RepCut: the validation line operates on the
    # frozen partitioned graph, so every partition is handled uniformly.
    if REPCUT_ENABLE_MEMORY_WRITE_COALESCE:
        start = time.perf_counter()
        log("pass memory-write-coalesce start")
        sess.run_pass("memory-write-coalesce", design="design.main")
        log(
            "pass memory-write-coalesce done "
            f"{int((time.perf_counter() - start) * 1000)}ms"
        )

    if REPCUT_ENABLE_REG_TO_MEM:
        start = time.perf_counter()
        log(
            "pass reg-to-mem start intent=false "
            f"profitability_filter={REPCUT_REG_TO_MEM_PROFITABILITY_FILTER}"
        )
        sess.run_pass(
            "reg-to-mem",
            design="design.main",
            intent=False,
            profitability_filter=REPCUT_REG_TO_MEM_PROFITABILITY_FILTER,
        )
        log(f"pass reg-to-mem done {int((time.perf_counter() - start) * 1000)}ms")

    start = time.perf_counter()
    log(f"write_json start {json_out}")
    json_out.parent.mkdir(parents=True, exist_ok=True)
    sess.store_json(design="design.main", output=str(json_out))
    log(f"write_json done {int((time.perf_counter() - start) * 1000)}ms")

    start = time.perf_counter()
    log("read_json start (roundtrip)")
    sess.read_json_file(str(json_out), out_design="design.main", replace=True)
    log(f"read_json done (roundtrip) {int((time.perf_counter() - start) * 1000)}ms")

    if REPCUT_BACKEND == "verilator":
        start = time.perf_counter()
        sv_out_arg = json_out.with_suffix(".sv")
        sv_out_dir = sv_out_arg.with_suffix("") if sv_out_arg.suffix == ".sv" else sv_out_arg
        log(f"write_sv start {sv_out_dir}")
        sess.emit_sv(design="design.main", output=str(sv_out_dir), top=[TOP_MODULE_PATH], split_modules=True)
        log(f"write_sv done {int((time.perf_counter() - start) * 1000)}ms")

    if package_out_dir is not None:
        start = time.perf_counter()
        log(f"write_{REPCUT_BACKEND}_repcut_package start {package_out_dir}")
        package_out_dir.mkdir(parents=True, exist_ok=True)
        emit_package = (
            sess.emit_grhsim_repcut_package
            if REPCUT_BACKEND == "grhsim"
            else sess.emit_verilator_repcut_package
        )
        emit_package(
            design="design.main",
            output=str(package_out_dir),
            top=[TOP_MODULE_PATH],
        )
        log(f"write_{REPCUT_BACKEND}_repcut_package done {int((time.perf_counter() - start) * 1000)}ms")

    log(f"total done {int((time.perf_counter() - total_start) * 1000)}ms")
