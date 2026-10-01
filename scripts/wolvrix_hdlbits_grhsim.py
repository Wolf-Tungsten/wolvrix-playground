#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

import wolvrix

from wolvrix_xs_grhsim_ir import CPU_PIPELINE


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
    if any(out_dir.iterdir()):
        raise ValueError(f"CPU emit output directory must be empty: {out_dir}")

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
        sess.store_json(
            design="design.main", output=str(out_dir.parent / f"{dut_path.stem}_flat.grh.json"), top=[TOP_NAME],
        )
        sess.lower_grhsim(
            design="design.main", out_model="grhsim.main", top=TOP_NAME,
            logic_domain="2-state", keep_origins=True, keep_declared_symbols=True,
            consume=True,
        )
        sess.run_grhsim_pass("grhsim.verify", model="grhsim.main")
        for pass_name in CPU_PIPELINE:
            sess.run_grhsim_pass(pass_name, model="grhsim.main")
        emit_options = {"model": "grhsim.main", "output": str(out_dir)}
        if waveform_mode and waveform_mode != "off":
            emit_options["waveform"] = waveform_mode
        if perf_mode and perf_mode != "off":
            emit_options["perf"] = perf_mode
        sess.print_diagnostics(
            sess.run_grhsim_pass("cpu.st.emit-cpp", **emit_options),
            min_level="info",
        )
        sess.store_grhsim(model="grhsim.main", output=str(json_out))
        write_stable_header_alias(out_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dut")
    parser.add_argument("out_dir")
    parser.add_argument("--waveform", choices=["off", "declared-symbols"], default="off")
    parser.add_argument("--perf", choices=["off", "eval"], default="off")
    parser.add_argument("--backend", choices=["ir"], default="ir")
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
