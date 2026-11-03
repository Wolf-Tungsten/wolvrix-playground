#!/usr/bin/env python3
"""Emit the packed Gray-to-binary hardware and intrinsic variants."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from chisel_pattern_bench import mill_classpath, run, save

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "testcase/chisel-intrinsic/GrayDecodeStudy.scala"
FIRTOOL = Path.home() / ".cache/llvm-firtool/1.135.0/bin/firtool"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=32)
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
    run([
        "java", "-Xmx4g", "-cp", ":".join(compiler), "scala.tools.nsc.Main",
        "-classpath", ":".join(runtime), "-Xplugin:" + plugin, "-d", classes, *sources,
    ], out / "scala.log")
    run([
        "java", "-Xmx4g", "-cp", str(classes) + ":" + ":".join(runtime),
        "study.intrinsics.GrayDecodeStudyMain", str(args.width), out, FIRTOOL,
    ], out / "emit.log")
    calls = {
        variant: json.loads((out / variant / "calls.json").read_text())
        for variant in ("A", "B")
    }
    intrinsic = [row for row in calls["B"]["calls"] if row["intrinsic"]]
    if not intrinsic or {row["api"] for row in intrinsic} != {"GrayToBinary.Bits"}:
        raise RuntimeError("Gray-to-binary intrinsic was not selected")
    normal = (out / "A" / "GrayDecodeA.sv").read_text()
    candidate = (out / "B" / "GrayDecodeB.sv").read_text()
    if 'import "DPI-C"' in normal or 'import "DPI-C"' not in candidate:
        raise RuntimeError("unexpected Verilog intrinsic route")
    save(out / "summary.json", {
        "scope": "Chisel elaboration and SystemVerilog emission only",
        "width": args.width,
        "calls": calls,
        "hardware_verilog": str(out / "A" / "GrayDecodeA.sv"),
        "intrinsic_verilog": str(out / "B" / "GrayDecodeB.sv"),
        "function_name": f"wolvrix_gray_decode_v1_w{args.width}",
        "intrinsic_calls": len(intrinsic),
        "intrinsic_function": intrinsic[0]["source"],
    })


if __name__ == "__main__":
    main()
