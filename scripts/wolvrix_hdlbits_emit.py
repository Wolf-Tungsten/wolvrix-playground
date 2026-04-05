#!/usr/bin/env python3

import sys
from pathlib import Path
import wolvrix

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
    sess.read_sv(
        str(dut_path),
        target_design_key="design.main",
        slang_args=["--top", "top_module"],
    )
    sess.run_pass("xmr-resolve", design="design.main")
    sess.run_pass("multidriven-guard", design="design.main")
    sess.run_pass("latch-transparent-read", design="design.main")
    sess.run_pass("hier-flatten", design="design.main", sym_protect="hierarchy")
    sess.run_pass("comb-loop-elim", design="design.main")
    sess.run_pass("simplify", design="design.main")
    sess.run_pass("memory-init-check", design="design.main")
    sess.run_pass("stats", design="design.main")
    sess.store_json(design="design.main", output=str(json_out))
    sess.read_json_file(str(json_out), target_design_key="design.main", replace=True)
    sess.emit_sv(design="design.main", output=str(sv_out))
