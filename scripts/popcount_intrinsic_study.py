#!/usr/bin/env python3
"""Emit a small Chisel PopCount packed/distributed intrinsic study."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from chisel_pattern_bench import mill_classpath, run, save

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "testcase/chisel-intrinsic/PopCountStudy.scala"
FIRTOOL = Path.home() / ".cache/llvm-firtool/1.135.0/bin/firtool"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=64)
    parser.add_argument("--layout", choices=["packed", "lanes"], default="packed")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    compiler = mill_classpath("scalaCompilerClasspath")
    runtime = mill_classpath("test/runClasspath")
    plugin = next(x for x in mill_classpath("scalacPluginClasspath") if "chisel-plugin" in x)
    utility = ROOT / "testcase/xiangshan/utility/src/main/scala/utility"
    sources = [utility / "Compatibility.scala", utility / "SimulationPrimitives.scala", FIXTURE]
    classes = out / "classes"
    classes.mkdir(exist_ok=True)
    run(
        [
            "java", "-Xmx4g", "-cp", ":".join(compiler), "scala.tools.nsc.Main",
            "-classpath", ":".join(runtime), "-Xplugin:" + plugin, "-d", classes,
            *sources,
        ],
        out / "scala.log",
    )
    run(
        [
            "java", "-Xmx4g", "-cp", str(classes) + ":" + ":".join(runtime),
            "study.intrinsics.PopCountStudyMain", str(args.width), args.layout, out, FIRTOOL,
        ],
        out / "emit.log",
    )
    calls = {}
    for variant in ("A", "B"):
        calls[variant] = json.loads((out / variant / "calls.json").read_text())
    packed_intrinsic = [x for x in calls["B"]["calls"] if x["layout"] == "packed" and x["intrinsic"]]
    distributed_intrinsic = [x for x in calls["B"]["calls"] if x["layout"] == "distributed" and x["intrinsic"]]
    if args.layout == "packed" and not packed_intrinsic:
        raise RuntimeError("packed PopCount did not select intrinsic")
    if args.layout == "lanes" and distributed_intrinsic:
        raise RuntimeError("distributed PopCount selected intrinsic")
    save(out / "summary.json", {
        "width": args.width,
        "layout": args.layout,
        "calls": calls,
        "packed_intrinsic": len(packed_intrinsic),
        "distributed_intrinsic": len(distributed_intrinsic),
        "verilog": {v: str(out / v / f"PopCount{v}.sv") for v in ("A", "B")},
    })


if __name__ == "__main__":
    main()
