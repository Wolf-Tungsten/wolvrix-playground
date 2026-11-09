#!/usr/bin/env python3
"""Build a full XiangShan A/B for the locally qualified integer models.

A is hardware-only.  B enables only the selected scalar/vector lane models
with grouped compute lowering.  RTL generation is intentionally serialized to
avoid sharing Mill's incremental output directory; native emission/compile
can proceed independently after both RTL trees are complete.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import sys

from grhsim_single_baseline import Baseline, ROOT, identity, save
from simulation_model_modes import selected_models


DEFAULT_MODELS = (
    "int-alu",
    "int-bku",
    "vec-int-alu-lane",
    "vec-int-pu-lane",
)


def model_gate(root: Path, models: tuple[str, ...]) -> dict:
    gate_path = root / "wolvrix/build/artifacts/behavior-model/integer-bit-local-measure-20261107/gate.json"
    report_path = root / "wolvrix/build/artifacts/behavior-model/integer-bit-functional-20261107/report.json"
    gate = json.loads(gate_path.read_text())
    report = json.loads(report_path.read_text())
    for model in models:
        record = gate["models"].get(model)
        if not record or not record["active_sparse_gate"]:
            raise ValueError(f"{model}: local active/sparse gate is not satisfied")
        functional = report["models"].get(model)
        if not functional or not functional.get("match"):
            raise ValueError(f"{model}: ordinary/grouped functional gate is incomplete")
    return {
        "gate": identity(gate_path),
        "functional": identity(report_path),
        "selected": list(models),
    }


def make_config(output: Path, tools: Path, models: str, grouped: bool,
                jobs: int, cycles: int, repeats: int) -> argparse.Namespace:
    return argparse.Namespace(
        output=output,
        tools_dir=tools,
        compiler="/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++",
        jobs=jobs,
        cpu=96,
        cycles=cycles,
        repeats=repeats,
        sim_primitives="none",
        sim_models=models,
        behavior_state_lowering="ordinary",
        behavior_compute_lowering="grouped" if grouped else "ordinary",
        rtl_difftest="on",
        model_difftest="on",
        compile_difftest="on",
        runtime_difftest="on",
        skip_idle_check=True,
    )


def validate_manifest(path: Path, label: str, models: tuple[str, ...]) -> dict:
    manifest_path = path / "chisel-home/build/simulation_models.json"
    manifest = json.loads(manifest_path.read_text())
    if label == "A":
        if manifest.get("mode") != "hardware" or manifest.get("models"):
            raise ValueError("A did not generate hardware-only simulation manifest")
    else:
        names = {record["name"] for record in manifest.get("models", [])}
        if names != set(models):
            raise ValueError(f"B model set mismatch: expected {models}, got {sorted(names)}")
        for record in manifest["models"]:
            if record.get("observer_only") or record.get("lowering") != "compute-grouped":
                raise ValueError(f"B model contract mismatch: {record.get('name')}")
        if manifest.get("observer_domains"):
            raise ValueError("integer behavior B unexpectedly declares observer domains")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--tools-dir", type=Path,
                        default=ROOT / "build/grhsim32-tools")
    parser.add_argument("--jobs", type=int, default=16)
    parser.add_argument("--cycles", type=int, default=100000)
    parser.add_argument("--repeats", type=int, default=8)
    parser.add_argument("--rtl-from", type=Path,
                        help="reuse already verified A/B RTL trees with identical configuration")
    args = parser.parse_args()
    if not platform.node().startswith("node030"):
        raise RuntimeError("full XiangShan experiment must run on node030")
    models = tuple(x for x in args.models.split(",") if x)
    if len(models) != len(set(models)):
        raise ValueError("duplicate model selection")
    selected_models(",".join(models))
    gates = model_gate(ROOT, models)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))

    with (output / "build.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        tools = args.tools_dir.resolve()
        if not (tools / "python/wolvrix/_wolvrix.so").is_file():
            raise FileNotFoundError(f"missing shared Wolvrix tools: {tools}")
        mode = ",".join(models)
        works = {
            "A": Baseline(make_config(output / "A", tools, "hardware", False,
                                       args.jobs, args.cycles, args.repeats)),
            "B": Baseline(make_config(output / "B", tools, mode, True,
                                       args.jobs, args.cycles, args.repeats)),
        }
        for work in works.values():
            work.env["PYTHONDONTWRITEBYTECODE"] = "1"
        save(output / "local-gates.json", gates)
        save(output / "selection.json", {
            "models": list(models), "mode": mode,
            "lowering": "grouped", "rtl_difftest": "on",
            "runtime_difftest": "on", "cycles": args.cycles,
            "repeats": args.repeats,
        })

        for label in "AB":
            work = works[label]
            if not (work.out / "sources.json").exists():
                work.snapshot()
        if (output / "A/sources.json").read_bytes() != (output / "B/sources.json").read_bytes():
            raise ValueError("A/B source snapshots differ")

        # Build or refresh the shared binding once, then serialize Mill/RTL.
        works["A"].build_tools()
        for label in "AB":
            work = works[label]
            if args.rtl_from and not (work.out / "rtl_manifest.json").exists():
                raise ValueError("--rtl-from is not supported by this first full integer run")
            if not (work.out / "rtl_manifest.json").exists():
                work.rtl()
            manifest = validate_manifest(work.out, label, models)
            save(work.out / "model-selection-gate.json", manifest)

        generated_a = works["A"].generated / "generated-src/difftest-state.h"
        generated_b = works["B"].generated / "generated-src/difftest-state.h"
        if not generated_a.is_file() or not generated_b.is_file():
            # Older source layouts place the header directly under generated-src.
            generated_a = works["A"].generated / "difftest-state.h"
            generated_b = works["B"].generated / "difftest-state.h"
        if identity(generated_a)["sha256"] != identity(generated_b)["sha256"]:
            raise ValueError("A/B DiffTest schemas differ")
        save(output / "difftest-schema.json", {
            "A": identity(generated_a), "B": identity(generated_b),
        })

        def finish(label: str) -> None:
            work = works[label]
            if not (work.out / "model_manifest.json").exists():
                work.emit()
            if not (work.out / "binary.json").exists():
                work.compile()
            work.stage("integer behavior full S3 build complete " + label)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(finish, label) for label in "AB"]
            for future in futures:
                future.result()
        save(output / "build-complete.json", {
            "models": list(models),
            "A": identity(works["A"].out / "emu/grhsim-compile/emu"),
            "B": identity(works["B"].out / "emu/grhsim-compile/emu"),
            "sources": identity(output / "A/sources.json"),
            "tools": identity(tools / "python/wolvrix/_wolvrix.so"),
        })
        print(json.dumps(json.loads((output / "build-complete.json").read_text()), indent=2), flush=True)


if __name__ == "__main__":
    main()
