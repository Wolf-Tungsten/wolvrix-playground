#!/usr/bin/env python3
"""Measure ordinary/grouped integer behavior fixtures on a fixed local runner.

The benchmark includes input preparation, the complete GrhSIM eval boundary and
output hashing.  It deliberately does not perform a CPU-idle admission check;
the caller controls the measurement environment.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CXX = Path("/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++")

CONFIG = {
    "int-alu": {
        "header": "grhsim_IntegerBehaviorFixture.hpp",
        "class": "GrhSIM_IntegerBehaviorFixture",
        "library": "libgrhsim_IntegerBehaviorFixture.a",
        "hardware": True,
        "array_output": False,
    },
    "int-bku": {
        "header": "grhsim_IntegerBehaviorFixture.hpp",
        "class": "GrhSIM_IntegerBehaviorFixture",
        "library": "libgrhsim_IntegerBehaviorFixture.a",
        "hardware": True,
        "array_output": False,
    },
    "vec-int-alu-lane": {
        "header": "grhsim_VectorIntBehaviorFixture.hpp",
        "class": "GrhSIM_VectorIntBehaviorFixture",
        "library": "libgrhsim_VectorIntBehaviorFixture.a",
        "hardware": True,
        "array_output": True,
    },
    "vec-int-pu-lane": {
        "header": "grhsim_VectorPuBehaviorFixture.hpp",
        "class": "GrhSIM_VectorPuBehaviorFixture",
        "library": "libgrhsim_VectorPuBehaviorFixture.a",
        "hardware": False,
        "array_output": True,
    },
}


def setup_code(model: str) -> str:
    if model == "int-alu":
        return r'''
      static constexpr unsigned kOps[] = {
        0, 1, 2, 3, 4, 5, 6, 7, 9, 11,
        16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 28, 29,
        32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 47,
        48, 49, 50, 52, 53, 54, 55,
        64, 65, 66, 67, 68, 69, 70, 72, 73, 74, 75,
        80, 81, 82, 83, 88, 89, 90, 91,
        96, 97, 98, 99, 100, 101, 102, 103,
        116, 118, 120, 121, 122, 127
      };
      m.io_in[2] = (m.io_in[2] & ~UINT64_C(0x1ff)) |
                   kOps[cycle % (sizeof(kOps) / sizeof(kOps[0]))];
'''
    if model == "int-bku":
        return r'''
      static constexpr unsigned kOps[] = {0, 1, 2, 4, 5, 8, 9, 10, 11, 12, 13};
      m.io_in[2] = (m.io_in[2] & ~UINT64_C(0x3f)) |
                   kOps[cycle % (sizeof(kOps) / sizeof(kOps[0]))];
'''
    if model == "vec-int-alu-lane":
        return r'''
      auto set_bits = [&](unsigned start, unsigned width, std::uint64_t value) {
        for (unsigned bit = 0; bit < width; ++bit) {
          const unsigned pos = start + bit;
          m.io_in[pos / 64] = (m.io_in[pos / 64] & ~(UINT64_C(1) << (pos % 64))) |
                               (((value >> bit) & 1u) << (pos % 64));
        }
      };
      set_bits(0, 138, 0);
      set_bits(266, 12, 0);
      set_bits(277, 5, 0);
      static constexpr unsigned kOps[] = {0, 16, 32, 33, 34, 35, 36, 37, 38, 39};
      const unsigned op = kOps[cycle % (sizeof(kOps) / sizeof(kOps[0]))];
      set_bits(282, 6, op);
      set_bits(276, 1, 1);
      set_bits(277, 1, 1);
      set_bits(278, 4, 1u << (cycle % 4));
      set_bits(267, 1, op >= 32 ? 1 : 0);
'''
    if model == "vec-int-pu-lane":
        return r'''
      auto set_bits = [&](unsigned start, unsigned width, std::uint64_t value) {
        for (unsigned bit = 0; bit < width; ++bit) {
          const unsigned pos = start + bit;
          m.io_in[pos / 64] = (m.io_in[pos / 64] & ~(UINT64_C(1) << (pos % 64))) |
                               (((value >> bit) & 1u) << (pos % 64));
        }
      };
      static constexpr unsigned kOps[] = {0x27, 0x28, 0x29, 0x2a, 0x2b, 0x2c, 0x2d, 0x2f};
      set_bits(553, 6, kOps[cycle % (sizeof(kOps) / sizeof(kOps[0]))]);
      set_bits(512, 2, cycle % 4);
      set_bits(526, 6, 0);
      set_bits(539, 8, 128);
      set_bits(552, 1, 1);
'''
    raise ValueError(model)


def source_code(model: str, config: dict) -> str:
    output = (
        "for (auto word : m.io_out) digest = (digest * UINT64_C(0x9e3779b97f4a7c15)) ^ word;"
        if config["array_output"] else
        "digest = (digest * UINT64_C(0x9e3779b97f4a7c15)) ^ m.io_out;"
    )
    setup = setup_code(model).replace("cycle %", "op_cycle %")
    return f'''#include "{config["header"]}"
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <random>
#include <string>
int main(int argc, char** argv) {{
  const std::string scenario = argc > 1 ? argv[1] : "active";
  const std::uint64_t seed = argc > 2 ? std::strtoull(argv[2], nullptr, 10) : 42;
  const unsigned cycles = argc > 3 ? std::strtoul(argv[3], nullptr, 10) : 10000;
  {config["class"]} m;
  m.init();
  std::mt19937_64 rng(seed);
  std::array<std::uint64_t, {4 if model == "int-alu" else 3 if model == "int-bku" else 5 if model == "vec-int-alu-lane" else 9}> last{{}};
  std::uint64_t digest = 0;
  const auto begin = std::chrono::steady_clock::now();
  for (unsigned cycle = 0; cycle < cycles; ++cycle) {{
    m.reset = cycle < 4 || (cycle >= cycles / 2 && cycle < cycles / 2 + 4);
    const bool refresh = scenario == "active" ||
      (scenario == "sparse" && (cycle % 17 == 0));
    if (refresh || cycle == 0) {{
      for (auto& word : last) word = rng();
    }}
    m.io_in = last;
    const unsigned op_cycle = scenario == "idle" ? 0u : cycle;
{setup}
    m.clock = false;
    m.eval();
    m.clock = true;
    m.eval();
    {output}
  }}
  const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::steady_clock::now() - begin).count();
  std::cout << "{{\\"cycles\\":" << cycles << ",\\"ns\\":" << ns
            << ",\\"hash\\":\\"" << std::hex << digest << "\\"}}\\n";
}}
'''


def run(cmd: list[object], cwd: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(x) for x in cmd], cwd=cwd, text=True,
                          capture_output=capture, check=True)


def bootstrap(deltas: list[float]) -> list[float]:
    rng = random.Random(20261107)
    return sorted(statistics.mean(rng.choices(deltas, k=len(deltas))) for _ in range(10000))


def summarize(pairs: list[dict], candidate: str, baseline: str) -> dict:
    deltas = [100.0 * (p[candidate]["ns"] / p[baseline]["ns"] - 1.0) for p in pairs]
    boot = bootstrap(deltas)
    return {
        "pairs": len(pairs),
        "mean_percent": statistics.mean(deltas),
        "median_percent": statistics.median(deltas),
        "ci95_percent": [boot[249], boot[9749]],
        "candidate_faster_pairs": sum(x < 0 for x in deltas),
        "deltas_percent": deltas,
        "candidate": candidate,
        "baseline": baseline,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--models", nargs="+", choices=sorted(CONFIG), default=sorted(CONFIG))
    parser.add_argument("--pairs", type=int, default=8)
    parser.add_argument("--cycles", type=int, default=10000)
    parser.add_argument("--cpu", type=int, default=96)
    args = parser.parse_args()
    matrix = args.matrix.resolve()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    prepared: dict[tuple[str, str], Path] = {}
    manifest = {
        "host": platform.node(), "cpu": args.cpu, "pairs": args.pairs,
        "cycles": args.cycles, "scenarios": ["active", "sparse", "idle"],
        "models": args.models, "variants": {}, "driver": str(Path(__file__).resolve()),
    }
    for model in args.models:
        config = CONFIG[model]
        variants = ["ordinary", "grouped"]
        if config["hardware"]:
            variants.insert(0, "hardware")
        for variant in variants:
            source_dir = matrix / model / ("hardware-run/ordinary" if variant == "hardware" else variant) / "model"
            source = out / model / variant / "bench.cpp"
            binary = out / model / variant / "bench"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(source_code(model, config))
            run([CXX, "-std=c++20", "-O3", "-march=native", "-I", source_dir,
                 source, source_dir / config["library"], "-o", binary], source.parent)
            prepared[(model, variant)] = binary
            manifest["variants"][f"{model}:{variant}"] = {
                "binary": str(binary), "source": str(source),
                "library": str(source_dir / config["library"]),
            }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    all_rows = []
    summaries: dict[str, dict] = {}
    for model in args.models:
        config = CONFIG[model]
        variants = ["ordinary", "grouped"]
        if config["hardware"]:
            variants.insert(0, "hardware")
        summaries[model] = {}
        for scenario in ("active", "sparse", "idle"):
            for variant in variants:
                result = run([prepared[(model, variant)], scenario, 42, args.cycles], out, capture=True)
                row = json.loads(result.stdout)
                row.update(model=model, variant=variant, scenario=scenario, pair=-1)
                all_rows.append(row)
            pairs = []
            for pair in range(args.pairs):
                order = variants if pair % 2 == 0 else list(reversed(variants))
                rows = {}
                for variant in order:
                    result = run([prepared[(model, variant)], scenario, 42 + pair, args.cycles], out, capture=True)
                    row = json.loads(result.stdout)
                    row.update(model=model, variant=variant, scenario=scenario, pair=pair)
                    rows[variant] = row
                    all_rows.append(row)
                pair_row = {variant: rows[variant] for variant in variants}
                pairs.append(pair_row)
            primary = summarize(pairs, "grouped", "ordinary")
            summaries[model][scenario] = {"grouped_vs_ordinary": primary}
            if config["hardware"]:
                summaries[model][scenario]["ordinary_vs_hardware"] = summarize(pairs, "ordinary", "hardware")
            model_dir = out / model
            (model_dir / f"{scenario}-pairs.json").write_text(json.dumps(pairs, indent=2) + "\n")
            with (model_dir / f"{scenario}-pairs.csv").open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["pair", "order", "hardware_ns", "ordinary_ns", "grouped_ns",
                                 "grouped_vs_ordinary_percent", "ordinary_vs_hardware_percent"])
                for pair, row in enumerate(pairs):
                    writer.writerow([
                        pair, "".join(variants if pair % 2 == 0 else list(reversed(variants))),
                        row.get("hardware", {}).get("ns", ""), row["ordinary"]["ns"], row["grouped"]["ns"],
                        100.0 * (row["grouped"]["ns"] / row["ordinary"]["ns"] - 1.0),
                        100.0 * (row["ordinary"]["ns"] / row["hardware"]["ns"] - 1.0)
                        if config["hardware"] else "",
                    ])
            print(model, scenario, json.dumps(summaries[model][scenario]), flush=True)
    (out / "runs.json").write_text(json.dumps(all_rows, indent=2) + "\n")
    (out / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")


if __name__ == "__main__":
    main()
