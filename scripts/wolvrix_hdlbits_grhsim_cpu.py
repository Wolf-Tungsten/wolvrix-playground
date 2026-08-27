#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

import wolvrix


TOP_NAME = "top_module"
REPO_ROOT = Path(__file__).resolve().parent.parent


def log(message: str) -> None:
    sys.stderr.write(f"[wolvrix-hdlbits-grhsim-cpu] {message}\n")
    sys.stderr.flush()


def write_stable_header_alias(out_dir: Path) -> None:
    stable_header = out_dir / "grhsim_top_module.hpp"
    header_candidates = sorted(
        path
        for path in out_dir.glob("grhsim_*.hpp")
        if path.name != stable_header.name and path.with_suffix(".cpp").is_file()
    )
    if len(header_candidates) != 1:
        return

    actual_header = header_candidates[0]
    actual_stem = actual_header.stem
    actual_class = actual_stem.replace("grhsim_", "GrhSIM_", 1)
    stable_header.write_text(
        "#pragma once\n\n"
        f'#include "{actual_header.name}"\n\n'
        f"using GrhSIM_top_module = {actual_class};\n",
        encoding="ascii",
    )


def run_pipeline(dut_path: Path, out_dir: Path) -> None:
    json_out = out_dir / f"{dut_path.stem}.json"

    with wolvrix.Session() as session:
        session.log_level = "info"
        session.read_sv(
            str(dut_path),
            out_design="design.main",
            slang_args=["--top", TOP_NAME],
        )
        session.run_pass("xmr-resolve", design="design.main")
        session.run_pass("multidriven-guard", design="design.main")
        session.run_pass("latch-transparent-read", design="design.main")
        session.run_pass("hier-flatten", design="design.main", sym_protect="hierarchy")
        session.run_pass("comb-lane-pack", design="design.main")
        session.run_pass("comb-loop-elim", design="design.main")
        session.run_pass("slice-index-const", design="design.main")
        session.run_pass("simplify", design="design.main", semantics="2state")
        session.run_pass("memory-init-check", design="design.main")
        session.run_pass("stats", design="design.main")
        session.store_json(design="design.main", output=str(json_out), top=[TOP_NAME])
        wolvrix.pipelines.cpu_single_thread(
            session,
            design="design.main",
            module="grhsim.main",
            top=TOP_NAME,
            output=str(out_dir),
        )
    write_stable_header_alias(out_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dut")
    parser.add_argument("out_dir")
    parser.add_argument("--waveform", choices=["off"], default="off")
    parser.add_argument("--perf", choices=["off"], default="off")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    dut_path = REPO_ROOT / "testcase" / "hdlbits" / "dut" / f"dut_{args.dut}.v"
    if not dut_path.exists():
        raise FileNotFoundError(f"DUT not found: {dut_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"emit {dut_path} -> {out_dir}")
    run_pipeline(dut_path, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
