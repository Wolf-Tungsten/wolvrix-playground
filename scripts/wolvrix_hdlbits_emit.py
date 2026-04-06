#!/usr/bin/env python3

import sys
from pathlib import Path
import wolvrix


def report_diagnostics(diags: list[dict], *, min_level: str = "info") -> None:
    wolvrix.print_diagnostics(diags, min_level=min_level)

if len(sys.argv) != 3:
    raise SystemExit("usage: wolvrix_hdlbits_emit.py <dut> <out-dir>")

dut_id = sys.argv[1]
out_dir = Path(sys.argv[2])

repo_root = Path(__file__).resolve().parent.parent
dut_path = repo_root / "testcase" / "hdlbits" / "dut" / f"dut_{dut_id}.v"
if not dut_path.exists():
    raise FileNotFoundError(f"DUT not found: {dut_path}")

out_dir.mkdir(parents=True, exist_ok=True)
sv_out = out_dir / f"dut_{dut_id}.v"
json_out = out_dir / f"dut_{dut_id}.json"

with wolvrix.Session() as sess:
    sess.set_log_level("info")
    sess.set_diagnostics_policy("error")
    report_diagnostics(sess.read_sv(
        str(dut_path),
        out_design="design.main",
        slang_args=["--top", "top_module"],
    ))
    report_diagnostics(sess.run_pass("xmr-resolve", design="design.main"))
    report_diagnostics(sess.run_pass("multidriven-guard", design="design.main"))
    report_diagnostics(sess.run_pass("latch-transparent-read", design="design.main"))
    report_diagnostics(sess.run_pass("hier-flatten", design="design.main", sym_protect="hierarchy"))
    report_diagnostics(sess.run_pass("comb-loop-elim", design="design.main"))
    report_diagnostics(sess.run_pass("simplify", design="design.main"))
    report_diagnostics(sess.run_pass("memory-init-check", design="design.main"))
    report_diagnostics(sess.run_pass("stats", design="design.main"))
    report_diagnostics(sess.store_json(design="design.main", output=str(json_out)))
    report_diagnostics(sess.read_json_file(str(json_out), out_design="design.main", replace=True))
    report_diagnostics(sess.emit_sv(design="design.main", output=str(sv_out)))
