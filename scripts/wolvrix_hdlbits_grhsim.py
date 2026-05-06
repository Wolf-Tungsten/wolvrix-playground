#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

import wolvrix


TOP_NAME = "top_module"
REPO_ROOT = Path(__file__).resolve().parent.parent


def log(message: str) -> None:
    sys.stderr.write(f"[wolvrix-hdlbits-grhsim] {message}\n")
    sys.stderr.flush()


def write_stable_header_alias(out_dir: Path) -> None:
    stable_header = out_dir / "grhsim_top_module.hpp"
    header_candidates = sorted(
        path
        for path in out_dir.glob("grhsim_*.hpp")
        if path.name != stable_header.name and not path.name.endswith("_runtime.hpp")
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


def run_pipeline(dut_path: Path, out_dir: Path, waveform_mode: str | None, perf_mode: str | None) -> None:
    json_out = out_dir / f"{dut_path.stem}.json"

    with wolvrix.Session() as sess:
        sess.log_level = "info"
        sess.read_sv(
            str(dut_path),
            out_design="design.main",
            slang_args=["--top", TOP_NAME],
        )
        sess.run_pass("xmr-resolve", design="design.main")
        sess.run_pass("multidriven-guard", design="design.main")
        sess.run_pass("latch-transparent-read", design="design.main")
        sess.run_pass("hier-flatten", design="design.main", sym_protect="hierarchy")
        sess.run_pass("comb-lane-pack", design="design.main")
        sess.run_pass("comb-loop-elim", design="design.main")
        sess.run_pass("slice-index-const", design="design.main")
        # simplify already bundles const-fold + redundant-elim + dead-code-elim.
        sess.run_pass("simplify", design="design.main", semantics="2state")
        sess.run_pass("memory-init-check", design="design.main")
        sess.run_pass("stats", design="design.main")
        sess.run_pass(
            "activity-schedule",
            design="design.main",
            path=TOP_NAME,
        )
        sess.store_json(design="design.main", output=str(json_out), top=[TOP_NAME])
        emit_kwargs = {
            "design": "design.main",
            "output": str(out_dir),
            "top": [TOP_NAME],
            "perf": perf_mode or "off",
        }
        if waveform_mode and waveform_mode != "off":
            emit_kwargs["waveform"] = waveform_mode
            log(f"emit waveform mode: {waveform_mode}")
        if perf_mode and perf_mode != "off":
            log(f"emit perf mode: {perf_mode}")
        sess.emit_grhsim_cpp(**emit_kwargs)
    write_stable_header_alias(out_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dut")
    parser.add_argument("out_dir")
    parser.add_argument("--waveform", choices=["off", "declared-symbols"], default="off")
    parser.add_argument("--perf", choices=["off", "eval"], default="off")
    args = parser.parse_args()

    dut_id = args.dut
    out_dir = Path(args.out_dir).resolve()

    dut_path = REPO_ROOT / "testcase" / "hdlbits" / "dut" / f"dut_{dut_id}.v"
    if not dut_path.exists():
        raise FileNotFoundError(f"DUT not found: {dut_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"emit {dut_path} -> {out_dir}")
    run_pipeline(dut_path, out_dir, args.waveform, args.perf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
