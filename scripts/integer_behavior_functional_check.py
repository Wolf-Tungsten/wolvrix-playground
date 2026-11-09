#!/usr/bin/env python3
"""Cycle-oriented ordinary/grouped equivalence checks for integer fixtures."""
from __future__ import annotations

import argparse
import json
import random
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEEDS = (1, 42, 20261107)


def run(cmd, cwd, log):
    with log.open("w") as f:
        r = subprocess.run([str(x) for x in cmd], cwd=cwd, stdout=f, stderr=subprocess.STDOUT)
    if r.returncode:
        raise RuntimeError(log.read_text(errors="replace")[-5000:])


def source_code(header: str, cls: str, array_output: bool, model: str):
    output_digest = ("for (auto word : m.io_out) digest = (digest * 0x9e3779b97f4a7c15ULL) ^ word;"
                     if array_output else
                     "digest = (digest * 0x9e3779b97f4a7c15ULL) ^ m.io_out;")
    if model == "int-alu":
        setup = r'''
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
      m.io_in[2] = (m.io_in[2] & ~UINT64_C(0x1ff)) | kOps[cycle % (sizeof(kOps) / sizeof(kOps[0]))];
'''
    elif model == "int-bku":
        setup = r'''
      static constexpr unsigned kOps[] = {0, 1, 2, 4, 5, 8, 9, 10, 11, 12, 13};
      m.io_in[2] = (m.io_in[2] & ~UINT64_C(0x3f)) | kOps[cycle % (sizeof(kOps) / sizeof(kOps[0]))];
'''
    elif model == "vec-int-alu-lane":
        setup = r'''
      auto set_bits = [&](unsigned start, unsigned width, std::uint64_t value) {
        for (unsigned bit = 0; bit < width; ++bit) {
          const unsigned pos = start + bit;
          m.io_in[pos / 64] = (m.io_in[pos / 64] & ~(UINT64_C(1) << (pos % 64))) |
                               (((value >> bit) & 1u) << (pos % 64));
        }
      };
      set_bits(0, 138, 0);  // clear widen operands, mask and vxrm for the lane subset
      set_bits(266, 12, 0); // clear control bundle before selecting the supported lane subset
      set_bits(277, 5, 0);  // clear info bundle before selecting vm/SEW
      static constexpr unsigned kOps[] = {0, 16, 32, 33, 34, 35, 36, 37, 38, 39};
      const unsigned op = kOps[cycle % (sizeof(kOps) / sizeof(kOps[0]))];
      set_bits(282, 6, op);
      set_bits(276, 1, 1); // valid
      set_bits(277, 1, 1); // vm: all lanes active
      set_bits(278, 4, 1u << (cycle % 4)); // one SEW selector
      set_bits(267, 1, op >= 32 ? 1 : 0); // logic operations use VIAluMisc
'''
    elif model == "vec-int-pu-lane":
        setup = r'''
      auto set_bits = [&](unsigned start, unsigned width, std::uint64_t value) {
        for (unsigned bit = 0; bit < width; ++bit) {
          const unsigned pos = start + bit;
          m.io_in[pos / 64] = (m.io_in[pos / 64] & ~(UINT64_C(1) << (pos % 64))) |
                               (((value >> bit) & 1u) << (pos % 64));
        }
      };
      static constexpr unsigned kOps[] = {0x27, 0x28, 0x29, 0x2a, 0x2b, 0x2c, 0x2d, 0x2f};
      set_bits(553, 6, kOps[cycle % (sizeof(kOps) / sizeof(kOps[0]))]);
      set_bits(512, 2, cycle % 4); // SEW 8/16/32/64
      set_bits(526, 6, 0);         // first uop only
      set_bits(539, 8, 128);       // all VLEN bits active
      set_bits(552, 1, 1);         // unmasked operation
'''
    else:
        raise ValueError(model)
    return r'''
#include "HEADER"
#include <cstdint>
#include <iostream>
#include <random>
int main() {
  std::uint64_t digest = 0;
  for (std::uint64_t seed : {1ULL, 42ULL, 20261107ULL}) {
    CLASS m;
    m.init();
    std::mt19937_64 rng(seed);
    for (unsigned cycle = 0; cycle < 10000; ++cycle) {
      m.reset = cycle < 4 || (cycle >= 5000 && cycle < 5004);
      for (auto &word : m.io_in) word = rng();
      SETUP
      m.clock = false;
      m.eval();
      m.clock = true;
      m.eval();
      OUTPUT_DIGEST
    }
  }
  std::cout << std::hex << digest << "\n";
}
'''.replace("HEADER", header).replace("CLASS", cls).replace("OUTPUT_DIGEST", output_digest).replace("SETUP", setup)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--matrix", type=Path, required=True)
    p.add_argument("--models", nargs="+", default=("int-alu", "int-bku"))
    p.add_argument("--cxx", type=Path,
                   default=Path("/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++"))
    args = p.parse_args()
    matrix = args.matrix.resolve()
    report = {"version": 1, "seeds": SEEDS, "cycles_per_seed": 10000, "models": {}}
    for model in args.models:
        if model.startswith("int-"):
            header, cls = "grhsim_IntegerBehaviorFixture.hpp", "GrhSIM_IntegerBehaviorFixture"
            array_output = False
        elif model == "vec-int-alu-lane":
            header, cls = "grhsim_VectorIntBehaviorFixture.hpp", "GrhSIM_VectorIntBehaviorFixture"
            array_output = True
            library = "libgrhsim_VectorIntBehaviorFixture.a"
        elif model == "vec-int-pu-lane":
            header, cls = "grhsim_VectorPuBehaviorFixture.hpp", "GrhSIM_VectorPuBehaviorFixture"
            array_output = True
            library = "libgrhsim_VectorPuBehaviorFixture.a"
        else:
            raise ValueError(model)
        if model.startswith("int-"):
            library = "libgrhsim_IntegerBehaviorFixture.a"
        outputs = {}
        for lowering in ("ordinary", "grouped"):
            variant = matrix / model / lowering / "model"
            source = variant / "functional_check.cpp"
            binary = variant / "functional_check"
            source.write_text(source_code(header, cls, array_output, model))
            run([args.cxx, "-std=c++20", "-O3", "-march=native", "-I", variant,
                 source, variant / library, "-o", binary],
                variant, variant / "functional_compile.log")
            result = subprocess.check_output([str(binary)], cwd=variant, text=True).strip()
            outputs[lowering] = result
        if outputs["ordinary"] != outputs["grouped"]:
            raise AssertionError(f"{model}: ordinary/grouped digest mismatch: {outputs}")
        report["models"][model] = {"ordinary_digest": outputs["ordinary"],
                                   "grouped_digest": outputs["grouped"], "match": True}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
