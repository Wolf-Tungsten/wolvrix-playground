#!/usr/bin/env python3
"""Generate and audit the integer/bit behavior-model fixture matrix.

This driver deliberately keeps fixture generation separate from XiangShan
elaboration.  It records ordinary and grouped artifacts under one directory,
checks that grouped graphs contain authenticated kBehaviorComputeGroup nodes,
and refuses to treat an unimplemented whole-unit wrapper as a production mode.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MATRIX = {
    "int-alu": (ROOT / "scripts/integer_behavior_study.py", "int-alu"),
    "int-bku": (ROOT / "scripts/integer_behavior_study.py", "int-bku"),
    "vec-int-alu-lane": (ROOT / "scripts/vector_int_behavior_study.py", "vec-int-alu-lane"),
    "vec-int-pu-lane": (ROOT / "scripts/vector_pu_behavior_study.py", "vec-int-pu-lane"),
}


def run(cmd: list[object], log: Path) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as stream:
        result = subprocess.run([str(x) for x in cmd], cwd=ROOT,
                                stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(map(str, cmd))}\n"
                           + log.read_text(errors="replace")[-6000:])


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text())


def audit_variant(path: Path, model: str, lowering: str, mode: str = "behavior") -> dict:
    manifest = load_json(path / "simulation_models.json")
    records = manifest.get("models", [])
    if mode == "hardware":
        if manifest.get("mode") != "hardware" or records:
            raise ValueError(f"{path}: unexpected hardware model manifest")
    else:
        if len(records) != 1 or records[0].get("name") != model:
            raise ValueError(f"{path}: unexpected simulation model manifest")
        record = records[0]
        expected_lowering = "compute-grouped" if lowering == "grouped" else "ordinary"
        if record.get("lowering") != expected_lowering:
            raise ValueError(f"{path}: lowering mismatch: {record.get('lowering')}")

    groups = []
    ops = []
    if lowering == "grouped":
        graph = load_json(path / "model" / "behavior_imported.json")
        ops = [op for g in graph.get("graphs", []) for op in g.get("ops", [])]
        groups = [op for op in ops if op.get("kind") == "kBehaviorComputeGroup"]
        if not groups:
            raise ValueError(f"{path}: grouped fixture has no kBehaviorComputeGroup")
    stats = load_json(path / "model" / "activity_schedule_supernode_stats.json")
    return {
        "path": str(path),
        "model": model,
        "mode": mode,
        "lowering": lowering,
        "manifest_version": manifest.get("version"),
        "graph_ops": stats.get("graph_ops", len(ops)),
        "behavior_compute_groups": len(groups),
        "carrier_modules": sorted({
            op.get("attrs", {}).get("moduleName", {}).get("v")
            for op in ops if op.get("kind") == "kInstance"
            and op.get("attrs", {}).get("moduleName", {}).get("v", "").startswith(
                "WolvrixBehaviorComputeGroup_v1_")
        }),
        "cpp_bytes": sum(p.stat().st_size for p in (path / "model").glob("*.cpp")),
        "binary_bytes": next((p.stat().st_size for p in (path / "model").glob("libgrhsim_*.a")), 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--models", nargs="+", choices=sorted(MATRIX),
                        default=sorted(MATRIX))
    parser.add_argument("--lowerings", nargs="+", choices=("ordinary", "grouped"),
                        default=("ordinary", "grouped"))
    parser.add_argument("--force", action="store_true",
                        help="remove only this matrix output directory before generation")
    args = parser.parse_args()
    out = args.output.resolve()
    if args.force and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    results = []
    for model in args.models:
        script, script_model = MATRIX[model]
        if model in {"int-alu", "int-bku", "vec-int-alu-lane"}:
            hardware_root = out / model / "hardware-run"
            hardware_dest = hardware_root / "ordinary"
            if not (hardware_dest / "simulation_models.json").is_file():
                run([sys.executable, script, "--output", hardware_root,
                     "--model", script_model, "--mode", "hardware",
                     "--compute-lowering", "ordinary"],
                    hardware_root / "hardware-matrix-generate.log")
            results.append(audit_variant(hardware_dest, model, "ordinary", "hardware"))
        for lowering in args.lowerings:
            root = out / model
            dest = root / lowering
            if dest.exists() and (dest / "graph.json").is_file():
                results.append(audit_variant(dest, model, lowering))
                continue
            cmd = [sys.executable, script, "--output", root,
                   "--model", script_model, "--compute-lowering", lowering]
            run(cmd, root / f"{lowering}-matrix-generate.log")
            results.append(audit_variant(dest, model, lowering))

    report = {
        "version": 1,
        "scope": "scalar and vector integer behavior carrier fixture matrix",
        "default_production_mode": "hardware",
        "whole_unit": "rejected by XiangShan wrappers until complete merge semantics exist",
        "variants": results,
    }
    (out / "matrix.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
