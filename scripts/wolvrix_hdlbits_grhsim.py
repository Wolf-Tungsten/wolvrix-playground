#!/usr/bin/env python3

import os
import subprocess
import sys
from pathlib import Path


def log(message: str) -> None:
    sys.stderr.write(f"[wolvrix-hdlbits-grhsim] {message}\n")
    sys.stderr.flush()


if len(sys.argv) != 3:
    raise SystemExit("usage: wolvrix_hdlbits_grhsim.py <dut> <out-dir>")

dut_id = sys.argv[1]
out_dir = Path(sys.argv[2]).resolve()

repo_root = Path(__file__).resolve().parent.parent
dut_path = repo_root / "testcase" / "hdlbits" / "dut" / f"dut_{dut_id}.v"
if not dut_path.exists():
    raise FileNotFoundError(f"DUT not found: {dut_path}")

driver_path = Path(
    os.environ.get(
        "WOLVRIX_HDLBITS_GRHSIM_DRIVER",
        repo_root / "wolvrix" / "build" / "bin" / "hdlbits-grhsim-driver",
    )
)
if not driver_path.exists():
    raise FileNotFoundError(f"GrhSIM driver not found: {driver_path}")

out_dir.mkdir(parents=True, exist_ok=True)
json_out = out_dir / f"dut_{dut_id}.json"

cmd = [str(driver_path), str(dut_path), "top_module", str(out_dir), str(json_out)]
log("exec " + " ".join(cmd))
subprocess.run(cmd, check=True)
