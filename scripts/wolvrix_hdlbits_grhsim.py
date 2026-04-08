#!/usr/bin/env python3

import sys
from pathlib import Path

import wolvrix


TOP_NAME = "top_module"
REPO_ROOT = Path(__file__).resolve().parent.parent


def log(message: str) -> None:
    sys.stderr.write(f"[wolvrix-hdlbits-grhsim] {message}\n")
    sys.stderr.flush()


def run_pipeline(dut_path: Path, out_dir: Path) -> None:
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
        sess.run_pass("comb-loop-elim", design="design.main")
        sess.run_pass("simplify", design="design.main", semantics="2state")
        sess.run_pass("memory-init-check", design="design.main")
        sess.run_pass("stats", design="design.main")
        sess.run_pass(
            "activity-schedule",
            design="design.main",
            args=["-path", TOP_NAME, "-enable-replication", "true"],
        )
        sess.store_json(design="design.main", output=str(json_out), top=[TOP_NAME])
        sess.emit_grhsim_cpp(design="design.main", output=str(out_dir), top=[TOP_NAME])


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: wolvrix_hdlbits_grhsim.py <dut> <out-dir>")

    dut_id = sys.argv[1]
    out_dir = Path(sys.argv[2]).resolve()

    dut_path = REPO_ROOT / "testcase" / "hdlbits" / "dut" / f"dut_{dut_id}.v"
    if not dut_path.exists():
        raise FileNotFoundError(f"DUT not found: {dut_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"emit {dut_path} -> {out_dir}")
    run_pipeline(dut_path, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
