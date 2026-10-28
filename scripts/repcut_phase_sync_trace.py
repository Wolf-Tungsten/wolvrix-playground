#!/usr/bin/env python3
"""Build diagnostic GrhSIM wrappers with Host-side phase-window tracing.

Only the generated common wrapper object is replaced in each archive. Model
objects and source archives are left untouched. The resulting binaries are for
phase attribution, not ordinary walltime benchmarking.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
LLVM = Path("/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin")
DEFAULT_BASELINE = ROOT / (
    "build/repcut_grhsim_balance_20261013/redesign/indivisible_sweep_20261017/"
    "p8_p30_perf_20261018/return_piece_690482_n629/candidate")
DEFAULT_CANDIDATE = ROOT / (
    "build/repcut_grhsim_balance_20261013/redesign/indivisible_sweep_20261017/"
    "backend_hgr_from_scratch_20261020/stage3_p29_n12_to30_perf_20261020/candidate")


def identity(path: Path) -> dict:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path.resolve()), "size_bytes": path.stat().st_size,
            "sha256": digest.hexdigest()}


def instrument_common(text: str) -> str:
    text = '#include "repcut_phase_sync_trace.hpp"\n' + text
    needle = "  active_phase_fns_ = &phaseFns;\n"
    if text.count(needle) != 1:
        raise ValueError("phase activation anchor not unique")
    text = text.replace(needle,
        "  const unsigned phaseTraceIndex = [&]() {\n"
        "    if (&phaseFns == &load_step_fns_) return 0U;\n"
        "    if (&phaseFns == &early_eval_step_fns_) return 1U;\n"
        "    if (&phaseFns == &early_update_step_fns_) return 2U;\n"
        "    if (&phaseFns == &normal_eval_step_fns_) return 3U;\n"
        "    return 4U;\n"
        "  }();\n"
        "  const auto phaseTraceBegin = repcut_phase_sync_trace::now();\n"
        "  active_phase_fns_ = &phaseFns;\n")
    needle = "    std::exception_ptr hostError;\n"
    if text.count(needle) != 1:
        raise ValueError("host phase anchor not unique")
    text = text.replace(needle,
        "    const auto phaseTraceDispatchEnd = repcut_phase_sync_trace::now();\n"
        "    const auto phaseTraceHostBegin = phaseTraceDispatchEnd;\n"
        "    std::exception_ptr hostError;\n")
    needle = "    std::exception_ptr workerError;\n"
    if text.count(needle) != 1:
        raise ValueError("worker phase anchor not unique")
    text = text.replace(needle,
        "    const auto phaseTraceHostEnd = repcut_phase_sync_trace::now();\n"
        "    const auto phaseTraceWaitBegin = phaseTraceHostEnd;\n"
        "    std::exception_ptr workerError;\n")
    needle = "    active_phase_fns_ = nullptr;\n"
    if text.count(needle) != 2:
        raise ValueError("active phase cleanup anchor count changed")
    # The first cleanup is the normal path; the second is the exception path.
    replacement = (
        "    const auto phaseTraceWaitEnd = repcut_phase_sync_trace::now();\n"
        "    repcut_phase_sync_trace::record(\n"
        "        phaseTraceIndex,\n"
        "        repcut_phase_sync_trace::elapsed_ns(phaseTraceBegin, phaseTraceDispatchEnd),\n"
        "        repcut_phase_sync_trace::elapsed_ns(phaseTraceHostBegin, phaseTraceHostEnd),\n"
        "        repcut_phase_sync_trace::elapsed_ns(phaseTraceWaitBegin, phaseTraceWaitEnd),\n"
        "        repcut_phase_sync_trace::elapsed_ns(phaseTraceBegin, phaseTraceWaitEnd));\n"
        "    active_phase_fns_ = nullptr;\n")
    text = text.replace(needle, replacement, 1)
    return text


def link_harness(dest: Path, model_dir: Path, model_lib: Path) -> Path:
    harness = dest / "harness"
    command = [
        "make", "-j16", "-C", str(ROOT / "testcase/xiangshan/difftest"), "emu-grhsim",
        "CC=" + str(LLVM / "clang"), "CXX=" + str(LLVM / "clang++"),
        "BUILD_DIR=" + str(harness),
        "GEN_CSRC_DIR=" + str(ROOT / "build/asc_counter_print_20260915/candidate_v4/noop/build/generated-src"),
        "GEN_VSRC_DIR=" + str(ROOT / "build/asc_counter_print_20260915/candidate_v4/noop/build/generated-src"),
        "NUM_CORES=1", "WITH_CHISELDB=0", "WITH_CONSTANTIN=0", "EMU_THREADS=0", "GRHSIM=1",
        "GRHSIM_MODEL_DIR=" + str(model_dir), "GRHSIM_MODEL_LIB=" + str(model_lib),
        "GRHSIM_MODEL_BUILD_JOBS=24", "GRHSIM_MODEL_CXXFLAGS=-std=c++20 -O3 -march=native",
        "EMU_OPTIMIZE=-O3", "WOLVRIX_GRHSIM_WAVEFORM=0",
    ]
    with (dest / "harness.log").open("w") as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    return harness / "grhsim-compile/emu"


def build_variant(name: str, source_root: Path, output: Path) -> dict:
    source_package = source_root / "package"
    source_archive = source_package / "libgrhsim_SimTop.a"
    dest = output / name
    package = dest / "package"
    package.mkdir(parents=True, exist_ok=False)
    # The package is several GB with objects. Symlink every root member except
    # the archive, which is the only changed artifact.
    for item in source_package.iterdir():
        if item.name == source_archive.name:
            continue
        (package / item.name).symlink_to(item)
    dest_archive = package / source_archive.name
    shutil.copy2(source_archive, dest_archive)
    common_cpp = source_package / "wolvi_repcut_grhsim_sim_common.cpp"
    instrumented_cpp = dest / common_cpp.name
    instrumented_cpp.write_text(instrument_common(common_cpp.read_text()))
    common_obj = dest / "wolvi_repcut_grhsim_sim_common.o"
    command = [str(LLVM / "clang++"), "-std=c++20", "-O3", "-march=native", "-pthread",
               "-I", str(package), "-I", str(Path(__file__).resolve().parent),
               "-c", str(instrumented_cpp), "-o", str(common_obj)]
    with (dest / "common.log").open("w") as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    subprocess.run([str(LLVM / "llvm-ar"), "r", str(dest_archive), str(common_obj)],
                   cwd=ROOT, check=True)
    binary = link_harness(dest, package, dest_archive)
    return {"source": str(source_root), "package": str(package),
            "archive": identity(dest_archive), "binary": identity(binary),
            "diagnostic_only": True, "changed_member": common_obj.name}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    records = {
        "baseline": build_variant("baseline", args.baseline.resolve(), args.output.resolve()),
        "candidate": build_variant("candidate", args.candidate.resolve(), args.output.resolve()),
    }
    (args.output / "manifest.json").write_text(json.dumps(records, indent=2) + "\n")
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
