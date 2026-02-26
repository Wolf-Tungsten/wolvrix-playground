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

design = wolvrix.read_sv(
    str(dut_path),
    slang_args=["--top", "top_module"],
    log_level="info",
)

for pass_name in [
    "xmr-resolve",
    "const-fold",
    "redundant-elim",
    "memory-init-check",
    "dead-code-elim",
    "stats",
]:
    design.run_pass(pass_name)

design.write_json(str(json_out))
design = wolvrix.read_json(str(json_out))
design.write_sv(str(sv_out))
