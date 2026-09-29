#!/usr/bin/env python3
"""Build MANIFEST.json for the sim-model-refactor golden baseline.

For every golden trace `dut_<id>.trace` in the golden directory this records
the eval count, the traced port names, the output ports declared in the
corresponding GrhSIM IR JSON (found under the capture work directory), and a
sha256 of the trace.  The coverage gate from the M0 milestone requires every
output port of every DUT to appear in its trace; violations fail the command.
"""

import argparse
import glob
import hashlib
import json
import sys
from pathlib import Path


def trace_ports_and_evals(trace_path: Path) -> tuple[list[str], int]:
    evals = 0
    ports: list[str] = []
    with trace_path.open(encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            evals += 1
            if evals == 1:
                tokens = line.split()
                ports = [item.partition("=")[0] for item in tokens[2:]]
    return ports, evals


def ir_output_ports(ir_json: Path) -> list[dict]:
    data = json.loads(ir_json.read_text(encoding="utf-8"))
    strings = data["strings"]
    types = {row[0]: row for row in data["types"]}
    outputs = []
    for row in data["outputs"]:
        _id, name_idx, type_idx, _origin = row
        type_row = types.get(type_idx)
        width = type_row[3] if type_row is not None else None
        outputs.append({"name": strings[name_idx - 1], "width": width})
    return outputs


def find_ir_json(work_dir: Path, dut: str) -> Path | None:
    candidates = sorted(
        glob.glob(str(work_dir / f"grhtb_{dut}" / "grhsim_*" / f"dut_{dut}.json"))
    )
    return Path(candidates[0]) if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden-dir", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--failed-list", type=Path, default=None, help="optional file with whitespace-separated failed DUT ids")
    args = parser.parse_args()

    traces = sorted(args.golden_dir.glob("dut_*.trace"))
    if not traces:
        print(f"[manifest] no dut_*.trace under {args.golden_dir}", file=sys.stderr)
        return 1

    manifest = {"suite": "hdlbits", "format": "grhsim-ir-trace.v1", "duts": {}}
    if args.failed_list is not None and args.failed_list.is_file():
        manifest["failed_duts"] = args.failed_list.read_text(encoding="utf-8").split()
    failures: list[str] = []
    total_evals = 0
    for trace_path in traces:
        dut = trace_path.stem.removeprefix("dut_")
        ports, evals = trace_ports_and_evals(trace_path)
        digest = hashlib.sha256(trace_path.read_bytes()).hexdigest()
        entry = {
            "trace": trace_path.name,
            "evals": evals,
            "sha256": digest,
            "ports": ports,
            "outputs": [],
        }
        if evals == 0:
            failures.append(f"dut_{dut}: empty trace")
        ir_json = find_ir_json(args.work_dir, dut)
        if ir_json is None:
            failures.append(f"dut_{dut}: IR JSON not found under {args.work_dir}")
        else:
            outputs = ir_output_ports(ir_json)
            entry["outputs"] = outputs
            missing = [item["name"] for item in outputs if item["name"] not in ports]
            if missing:
                failures.append(f"dut_{dut}: outputs missing from trace: {missing}")
        manifest["duts"][dut] = entry
        total_evals += evals

    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        f"[manifest] {len(traces)} DUTs, {total_evals} evals total -> {args.output}"
    )
    if failures:
        for failure in failures:
            print(f"[manifest] COVERAGE FAIL: {failure}", file=sys.stderr)
        return 1
    print("[manifest] coverage OK: every output port traced for every DUT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
