#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]


DEFAULT_CASES = [
    "XsRobEnqMaskMedium",
    "XsRobExceptionScanMedium",
    "XsRobRedirectAgeMedium",
    "XsVecCompressLaneMedium",
    "XsVecMguMaskMedium",
    "XsVecDataSplitMedium",
    "XsVecTailMergeMedium",
]


HARNESS_TEMPLATE = r'''
#include "V{case}.h"
#include "grhsim_{case}.hpp"

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

struct Inputs {{
    std::uint64_t in0 = 0;
    std::uint64_t in1 = 0;
    std::uint64_t in2 = 0;
    std::uint64_t in3 = 0;
    std::uint64_t in4 = 0;
    std::uint64_t in5 = 0;
    std::uint64_t ctrl = 0;
}};

struct Outputs {{
    std::uint64_t out0 = 0;
    std::uint64_t out1 = 0;
    std::uint64_t out2 = 0;
    std::uint64_t out3 = 0;
    std::uint64_t flags = 0;
    std::uint64_t checksum = 0;
}};

static std::uint64_t splitmix64(std::uint64_t x)
{{
    x += 0x9e3779b97f4a7c15ULL;
    x = (x ^ (x >> 30U)) * 0xbf58476d1ce4e5b9ULL;
    x = (x ^ (x >> 27U)) * 0x94d049bb133111ebULL;
    return x ^ (x >> 31U);
}}

static std::string hex64(std::uint64_t value)
{{
    std::ostringstream os;
    os << "0x" << std::hex << std::setw(16) << std::setfill('0') << value;
    return os.str();
}}

static std::vector<Inputs> make_vectors(unsigned count)
{{
    std::vector<Inputs> vectors;
    vectors.reserve(count + 2);
    vectors.push_back({{}});
    vectors.push_back({{~0ULL, 0, 1, 2, 0xffff, 0, 0x1234}});
    for (unsigned i = 0; i < count; ++i) {{
        const std::uint64_t base = splitmix64(0x5853434f4d504f4eULL + i);
        Inputs in;
        in.in0 = splitmix64(base ^ 0x00);
        in.in1 = splitmix64(base ^ 0x11);
        in.in2 = splitmix64(base ^ 0x22);
        in.in3 = splitmix64(base ^ 0x33);
        in.in4 = splitmix64(base ^ 0x44);
        in.in5 = splitmix64(base ^ 0x55);
        in.ctrl = splitmix64(base ^ 0x66);
        if ((i % 17U) == 0U) {{
            in.in0 = i & 0xffU;
            in.in1 = (i + 23U) & 0xffU;
            in.in2 = 0xffffU >> (i & 7U);
            in.in4 = 0x00ffU << (i & 7U);
            in.ctrl = (in.ctrl & ~0x7fULL) | (i & 0x7fU);
        }}
        vectors.push_back(in);
    }}
    return vectors;
}}

static Outputs sample_verilator(const V{case} &dut)
{{
    return Outputs{{dut.io_out0, dut.io_out1, dut.io_out2, dut.io_out3, dut.io_flags, dut.io_checksum}};
}}

static Outputs sample_grhsim(const GrhSIM_{case} &dut)
{{
    return Outputs{{dut.io_out0, dut.io_out1, dut.io_out2, dut.io_out3, dut.io_flags, dut.io_checksum}};
}}

static void drive_verilator(V{case} &dut, const Inputs &in)
{{
    dut.reset = 0;
    dut.io_in0 = in.in0;
    dut.io_in1 = in.in1;
    dut.io_in2 = in.in2;
    dut.io_in3 = in.in3;
    dut.io_in4 = in.in4;
    dut.io_in5 = in.in5;
    dut.io_ctrl = in.ctrl;
}}

static void drive_grhsim(GrhSIM_{case} &dut, const Inputs &in)
{{
    dut.reset = false;
    dut.io_in0 = in.in0;
    dut.io_in1 = in.in1;
    dut.io_in2 = in.in2;
    dut.io_in3 = in.in3;
    dut.io_in4 = in.in4;
    dut.io_in5 = in.in5;
    dut.io_ctrl = in.ctrl;
}}

static Outputs eval_verilator(V{case} &dut, const Inputs &in)
{{
    drive_verilator(dut, in);
    dut.clock = 0;
    dut.eval();
    Outputs out = sample_verilator(dut);
    dut.clock = 1;
    dut.eval();
    return out;
}}

static Outputs eval_grhsim(GrhSIM_{case} &dut, const Inputs &in)
{{
    drive_grhsim(dut, in);
    dut.clock = false;
    dut.eval();
    Outputs out = sample_grhsim(dut);
    dut.clock = true;
    dut.eval();
    return out;
}}

static void reset_verilator(V{case} &dut)
{{
    dut.reset = 1;
    dut.clock = 0;
    dut.eval();
    dut.clock = 1;
    dut.eval();
    dut.reset = 0;
    dut.clock = 0;
    dut.eval();
}}

static void reset_grhsim(GrhSIM_{case} &dut)
{{
    dut.reset = true;
    dut.clock = false;
    dut.eval();
    dut.clock = true;
    dut.eval();
    dut.reset = false;
    dut.clock = false;
    dut.eval();
}}

static bool same(const Outputs &lhs, const Outputs &rhs)
{{
    return lhs.out0 == rhs.out0 && lhs.out1 == rhs.out1 && lhs.out2 == rhs.out2 && lhs.out3 == rhs.out3 &&
           lhs.flags == rhs.flags && lhs.checksum == rhs.checksum;
}}

int main(int argc, char **argv)
{{
    unsigned vectors = 100000;
    if (argc == 3 && std::string(argv[1]) == "--vectors") {{
        vectors = static_cast<unsigned>(std::strtoul(argv[2], nullptr, 0));
    }} else if (argc != 1) {{
        std::cerr << "usage: " << argv[0] << " [--vectors N]\n";
        return 2;
    }}

    V{case} verilator;
    GrhSIM_{case} grhsim;
    grhsim.init();
    reset_verilator(verilator);
    reset_grhsim(grhsim);

    const auto inputs = make_vectors(vectors);
    for (unsigned i = 0; i < inputs.size(); ++i) {{
        const Outputs verilator_out = eval_verilator(verilator, inputs[i]);
        const Outputs grhsim_out = eval_grhsim(grhsim, inputs[i]);
        if (!same(verilator_out, grhsim_out)) {{
            std::cerr << "[FAIL] top={case} vector=" << i << "\n"
                      << "  out0 verilator=" << hex64(verilator_out.out0) << " grhsim=" << hex64(grhsim_out.out0) << "\n"
                      << "  out1 verilator=" << hex64(verilator_out.out1) << " grhsim=" << hex64(grhsim_out.out1) << "\n"
                      << "  out2 verilator=" << hex64(verilator_out.out2) << " grhsim=" << hex64(grhsim_out.out2) << "\n"
                      << "  out3 verilator=" << hex64(verilator_out.out3) << " grhsim=" << hex64(grhsim_out.out3) << "\n"
                      << "  flags verilator=" << hex64(verilator_out.flags) << " grhsim=" << hex64(grhsim_out.flags) << "\n"
                      << "  checksum verilator=" << hex64(verilator_out.checksum) << " grhsim=" << hex64(grhsim_out.checksum) << "\n";
            return 1;
        }}
    }}
    std::cout << "[PASS] top={case} vectors=" << inputs.size() << "\n";
    return 0;
}}
'''


def run_case(case: str, build_dir: Path, out_root: Path, vectors: int) -> bool:
    case_build = build_dir / case
    sv = case_build / "chisel-sv" / f"{case}.sv"
    grhsim_dir = case_build / "grhsim" / "model"
    grhsim_lib = grhsim_dir / f"libgrhsim_{case}.a"
    if not sv.exists():
        raise FileNotFoundError(sv)
    if not grhsim_lib.exists():
        raise FileNotFoundError(grhsim_lib)

    out_dir = out_root / case
    out_dir.mkdir(parents=True, exist_ok=True)
    harness = out_dir / f"{case}_verilator_grhsim.cpp"
    harness.write_text(HARNESS_TEMPLATE.format(case=case), encoding="ascii")

    verilator_log = out_dir / "verilator_build.log"
    cmd = [
        "verilator",
        "--cc",
        str(sv.resolve()),
        "--top-module",
        case,
        "--exe",
        str(harness.resolve()),
        "--Mdir",
        str((out_dir / "obj_dir").resolve()),
        "--build",
        "-MAKEFLAGS",
        "OBJCACHE=",
        "-CFLAGS",
        f"-std=c++20 -O3 -I{grhsim_dir.resolve()}",
        "-LDFLAGS",
        str(grhsim_lib.resolve()),
    ]
    with verilator_log.open("w", encoding="ascii", errors="replace") as fp:
        fp.write("$ " + " ".join(cmd) + "\n")
        completed = subprocess.run(cmd, cwd=ROOT, text=True, stdout=fp, stderr=subprocess.STDOUT)
    if completed.returncode != 0:
        print(f"{case}: BUILD_FAIL log={verilator_log}")
        return False

    exe = out_dir / "obj_dir" / f"V{case}"
    run_log = out_dir / "run.log"
    with run_log.open("w", encoding="ascii", errors="replace") as fp:
        completed = subprocess.run(
            [str(exe), "--vectors", str(vectors)],
            cwd=ROOT,
            text=True,
            stdout=fp,
            stderr=subprocess.STDOUT,
        )
    status = "PASS" if completed.returncode == 0 else "FAIL"
    print(f"{case}: {status} log={run_log}")
    return completed.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", default="build/grhsim_verilator_compare")
    parser.add_argument("--out-dir", default="build/no0190_verilator_compare_20260613")
    parser.add_argument("--vectors", type=int, default=100000)
    parser.add_argument("--case", action="append", dest="cases")
    args = parser.parse_args()

    build_dir = Path(args.build_dir)
    out_dir = Path(args.out_dir)
    if not build_dir.is_absolute():
        build_dir = ROOT / build_dir
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir

    cases = args.cases or DEFAULT_CASES
    passed = 0
    for case in cases:
        if run_case(case, build_dir, out_dir, args.vectors):
            passed += 1
    summary = out_dir / "summary.txt"
    summary.write_text(f"passed={passed}\ntotal={len(cases)}\n", encoding="ascii")
    print(f"summary: passed={passed}/{len(cases)} path={summary}")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
