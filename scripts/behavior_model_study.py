#!/usr/bin/env python3
"""Generate the generic Chisel commit/RAT behavior-model fixture."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import collections
import subprocess

from chisel_pattern_bench import mill_classpath, run, save

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "testcase/chisel-intrinsic/BehaviorModelStudy.scala"
FIRTOOL = Path.home() / ".cache/llvm-firtool/1.135.0/bin/firtool"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--firtool", type=Path, default=FIRTOOL)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)

    compiler = mill_classpath("scalaCompilerClasspath")
    runtime = mill_classpath("test/runClasspath")
    plugin = next(x for x in mill_classpath("scalacPluginClasspath") if "chisel-plugin" in x)
    utility = ROOT / "testcase/xiangshan/utility/src/main/scala/utility"
    sources = [utility / "Compatibility.scala", utility / "BehaviorModels.scala", FIXTURE]
    classes = out / "classes"
    classes.mkdir()
    run([
        "java", "-Xmx4g", "-cp", ":".join(compiler), "scala.tools.nsc.Main",
        "-classpath", ":".join(runtime), "-Xplugin:" + plugin, "-d", classes, *sources,
    ], out / "scala.log")
    run([
        "java", "-Xmx4g", "-cp", str(classes) + ":" + ":".join(runtime),
        "study.models.BehaviorModelStudyMain", out, args.firtool,
    ], out / "emit.log")

    manifests = {}
    for variant in ("A", "B"):
        manifest = json.loads((out / variant / "simulation_models.json").read_text())
        manifests[variant] = manifest
    if manifests["A"]["mode"] != "hardware" or manifests["A"]["models"]:
        raise RuntimeError("hardware fixture unexpectedly emitted behavior models")
    if manifests["B"]["mode"] != "commit-rat" or len(manifests["B"]["models"]) != 1:
        raise RuntimeError("behavior fixture did not emit one commit-rat model")
    model = manifests["B"]["models"][0]
    if len(model["states"]) != 2 or len(model["inputs"]) != 6 or len(model["outputs"]) != 2:
        raise RuntimeError("unexpected behavior model manifest shape")
    if [(state["name"], state["kind"], state["rows"]) for state in model["states"]] != [
        ("arch", "array", 32), ("rat", "array", 32)
    ]:
        raise RuntimeError("behavior model did not preserve the high-level arrays")
    if model.get("capabilities") != ["commit", "rat", "architectural-state"]:
        raise RuntimeError("behavior model capabilities were not recorded")
    if [check["name"] for check in model.get("checks", [])] != ["arch.state", "rat.state"]:
        raise RuntimeError("behavior model check outputs were not recorded")
    if [(update["state"], update["kind"]) for update in model["updates"]] != [
        ("arch", "array"), ("rat", "array")
    ]:
        raise RuntimeError("unexpected behavior model update count")
    sv_a = (out / "A/CommitRatBehaviorA.sv").read_text()
    sv_b = (out / "B/CommitRatBehaviorB.sv").read_text()
    if "behavior_arch" not in sv_b or "behavior_rat" not in sv_b:
        raise RuntimeError("behavior array names are absent from generated RTL")
    summary = {
        "scope": "Chisel elaboration and SystemVerilog emission",
        "fixture": str(FIXTURE),
        "hardware_manifest": manifests["A"],
        "behavior_manifest": manifests["B"],
        "hardware_verilog_bytes": len(sv_a),
        "behavior_verilog_bytes": len(sv_b),
        "ordinary_state_lowering": True,
    }
    frontend = ROOT / "build/grhsim32-tools/bin/grhsim32_frontend"
    if frontend.is_file():
        grh = {}
        for variant in ("A", "B"):
            graph = out / variant / "frontend-graph.json"
            subprocess.run([
                frontend, graph, "CommitRatBehaviorStudy",
                out / variant / f"CommitRatBehavior{variant}.sv",
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            data = json.loads(graph.read_text())
            operations = [op for graph_data in data["graphs"] for op in graph_data["ops"]]
            grh[variant] = {
                "operation_count": len(operations),
                "operation_kinds": dict(collections.Counter(op["kind"] for op in operations)),
            }
        if grh["A"] != grh["B"]:
            raise RuntimeError("hardware and behavior fixture GRH operation shapes differ")
        if grh["B"]["operation_kinds"].get("kRegister", 0) != 64:
            raise RuntimeError("behavior fixture did not lower to the expected array state")
        summary["grh"] = grh
    save(out / "summary.json", summary)


if __name__ == "__main__":
    main()
