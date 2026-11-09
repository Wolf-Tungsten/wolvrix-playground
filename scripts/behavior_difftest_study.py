#!/usr/bin/env python3
"""Elaborate, lower and compile the semantic DiffTest adapter fixture."""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import subprocess

from chisel_pattern_bench import run, save

ROOT = Path(__file__).resolve().parents[1]
XS = ROOT / "testcase/xiangshan"
FIRTOOL = Path.home() / ".cache/llvm-firtool/1.135.0/bin/firtool"
FRONTEND = ROOT / "build/grhsim32-tools/bin/grhsim32_frontend"
EMITTER = ROOT / "build/grhsim32-tools/bin/grhsim32_pattern_emit"


def run_cwd(cmd, log, cwd):
    cmd = [str(x) for x in cmd]
    Path(log).parent.mkdir(parents=True, exist_ok=True)
    with Path(log).open("w") as stream:
        result = subprocess.run(cmd, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {log}\n{Path(log).read_text()[-3500:]}")


def adapter_stimulus() -> str:
    """Identical deterministic input generation for equivalence and timing."""
    stimulus = []
    for bank, rows in enumerate((40, 40, 128, 22)):
        stimulus.append(f"const unsigned base{bank} = rng() % {rows};")
        for lane in range(4):
            prefix = f"m.io_physical_{bank}_"
            stimulus += [
                f"{prefix}enable_{lane} = (rng() % 4 != 0);",
                f"{prefix}address_{lane} = (base{bank} + {lane}) % {rows};",
            ]
            if bank < 2:
                stimulus.append(f"{prefix}data_{lane} = rng();")
            else:
                stimulus.append(f"{prefix}data_{lane}[0] = rng(); {prefix}data_{lane}[1] = rng();")
    for bank, rows in enumerate((40, 40, 128, 22)):
        for lane in range(4):
            prefix = f"m.io_rats_{bank}_"
            stimulus += [
                f"{prefix}enable_{lane} = !flush && (rng() % 3 != 0);",
                f"{prefix}data_{lane} = rng() % {rows};",
            ]
            if bank != 3:
                stimulus.append(f"{prefix}address_{lane} = collision ? 5 : rng() % 32;")
    for lane in range(4):
        prefix = f"m.io_commit_{lane}_"
        stimulus += [
            f"{prefix}valid = !flush && rng() % 3 != 0;",
            f"{prefix}rfwen = rng() & 1; {prefix}fpwen = rng() & 1;",
            f"{prefix}vecwen = rng() & 1; {prefix}v0wen = rng() & 1;",
            f"{prefix}skip = rng() & 1; {prefix}special = rng() & 1;",
            f"{prefix}wdest = collision ? 5 : rng() % 32; {prefix}wpdest = rng() % 40;",
            f"{prefix}index = {lane}; {prefix}coreid = 0;",
        ]
        for part in range(16):
            stimulus.append(f"{prefix}otherwpdest_{part} = rng() % 300;")
    return "\n".join(stimulus)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--firtool", type=Path, default=FIRTOOL)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)

    run_cwd([
        "mill", "-i", "difftest.test.runMain", "difftest.BehaviorDifftestStudyMain",
        out, args.firtool,
    ], out / "elaborate.log", XS)

    manifest = json.loads((out / "simulation_models.json").read_text())
    if manifest.get("mode") != "commit-rat" or len(manifest.get("models", [])) != 1:
        raise RuntimeError("semantic DiffTest fixture did not emit one commit-rat model")
    model = manifest["models"][0]
    expected_states = {
        "physical.int", "physical.fp", "physical.vf", "physical.v0",
        "rat.int", "rat.fp", "rat.vec", "arch.int", "arch.fp", "arch.vec",
    }
    state_names = {state["name"] for state in model["states"]}
    if state_names != expected_states:
        raise RuntimeError(f"unexpected adapter state set: {sorted(state_names)}")
    if len(model["updates"]) != 274:
        raise RuntimeError(f"unexpected adapter update count: {len(model['updates'])}")
    if "commit" not in model["capabilities"] or "physical-writeback" not in model["capabilities"]:
        raise RuntimeError("adapter capabilities are incomplete")

    sv = out / "BehaviorDifftestStudy.sv"
    if FRONTEND.is_file():
        graph = out / "graph.json"
        run([FRONTEND, graph, "BehaviorDifftestStudy", sv], out / "frontend.log")
        data = json.loads(graph.read_text())
        operations = [op for graph_data in data["graphs"] for op in graph_data["ops"]]
        kinds = dict(collections.Counter(op["kind"] for op in operations))
        if kinds.get("kRegister", 0) < 10:
            raise RuntimeError("adapter fixture did not preserve ordinary state")
        summary = {
            "fixture": str(XS / "difftest/src/test/scala/BehaviorDifftestStudy.scala"),
            "manifest": manifest,
            "operation_count": len(operations),
            "operation_kinds": kinds,
        }
        if EMITTER.is_file():
            model_dir = out / "model"
            run([EMITTER, graph, "BehaviorDifftestStudy", model_dir, "raw"], out / "emit.log")
            run([
                "make", "-C", model_dir, "-j4",
                "CXX=/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++",
                "CXXFLAGS=-std=c++20 -O2 -march=native",
            ], out / "compile.log")
            check = model_dir / "adapter_check.cpp"
            check.write_text(r'''
#include "grhsim_BehaviorDifftestStudy.hpp"
#include <cstdio>
#include <cstdint>
#include <random>
static bool equal(GrhSIM_BehaviorDifftestStudy& m, int cycle, int edge) {
  if (m.io_archEqual && m.io_ratEqual && m.io_commitEqual && m.io_vectorEqual) return true;
  fprintf(stderr, "cycle=%d edge=%d arch=%d rat=%d commit=%d vector=%d\n", cycle, edge,
    int(m.io_archEqual), int(m.io_ratEqual), int(m.io_commitEqual), int(m.io_vectorEqual));
  return false;
}
int main() {
  for (unsigned seed : {1U, 42U, 20261105U}) {
    GrhSIM_BehaviorDifftestStudy m; m.init(); std::mt19937_64 rng(seed);
    for (int cycle = 0; cycle < 10000; ++cycle) {
      const bool flush = cycle % 17 == 0;
      const bool collision = cycle % 3 == 0;
      m.reset = cycle < 4 || (cycle >= 5000 && cycle < 5004);
''' + adapter_stimulus() + r'''
      m.clock = false; m.eval();
      if (cycle >= 4 && !equal(m, cycle, 0)) return 1;
      m.clock = true; m.eval();
      if (cycle >= 4 && !equal(m, cycle, 1)) return 1;
    }
  }
  puts("PASS: 3 seeds x 10000 cycles, reset/no-commit/multiple writes/aliases/skip/vector/commit delay");
}
''')
            run_cwd([
                "/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++",
                "-std=c++20", "-O2", "-march=native", "-I.",
                "adapter_check.cpp", "-L.", "-lgrhsim_BehaviorDifftestStudy",
                "-o", "adapter_check",
            ], out / "adapter-check-compile.log", model_dir)
            run_cwd([model_dir / "adapter_check"], out / "adapter-check.log", model_dir)
            summary["compiled_model"] = True
            summary["random_equivalence_cycles"] = 30000
            summary["reference"] = "original Preprocess + independently maintained physical/RAT state"
        save(out / "summary.json", summary)


if __name__ == "__main__":
    main()
