"""Capture all F35 GSIM and GRH pass traces for a module or the whole design."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from tempfile import mkdtemp

from benchmark_f29_pass_trace import write_json_atomic
from benchmark_xs_firrtl_ingest import request_from_manifest
from capture_f35_pipeline import WORK, capture_lock
from f35_module_extract import DEFAULT_MAX_BYTES, extract_module


def extract_inputs(args, output):
    request = request_from_manifest(args.manifest)
    firrtl_sources = [entry for entry in request["sources"] if entry["language"] == "firrtl"]
    if len(firrtl_sources) != 1 or Path(firrtl_sources[0]["path"]) != args.firrtl:
        raise ValueError("module capture requires the single FIRRTL input from the manifest")
    isolated = output / "isolated.fir"
    extraction = extract_module(args.firrtl, args.module, isolated, max_bytes=args.max_module_bytes,
                                reset_ports=args.reset_ports)
    write_json_atomic(output / "extraction.json", extraction)
    if unresolved := extraction["abstract_reset_ports"]:
        ports = ", ".join(unresolved)
        raise ValueError(f"{extraction['module']} has abstract Reset inputs: {ports}. "
                         "Use --reset-port NAME=AsyncReset or 'NAME=UInt<1>' to match the original instance.")
    firrtl_sources[0]["path"] = str(isolated)
    helpers = {Path(entry["path"]) for entry in request["sources"]}
    for helper in dict.fromkeys(args.sv):
        if helper not in helpers:
            request["sources"].append({"path": str(helper), "language": "sv", "unit": "helpers"})
    request["tops"] = [extraction["module"]]
    manifest = output / "ingest-request.json"
    write_json_atomic(manifest, {"schema": "wolvrix.xs.firrtl-inputs.v1", **request})
    return isolated, manifest


def capture(engine, common, output, extra):
    command = [sys.executable, str(Path(__file__).with_name("capture_f35_pipeline.py")),
               engine, *common, "--output", str(output), *extra]
    result = subprocess.run(command)
    if result.returncode:
        log = output / (engine + ".log")
        print(f"{engine.upper()} capture failed. See {log if log.exists() else output.parent}.",
              file=sys.stderr)
        raise SystemExit(result.returncode if result.returncode > 0 else 128 - result.returncode)


def run(args):
    work_root = args.work_root.resolve() if args.work_root else WORK
    if args.output:
        if not args.output.is_relative_to(work_root) or args.output == work_root:
            raise ValueError("output must be beneath " + str(work_root))
        args.output.mkdir(parents=True)
        output = args.output
    else:
        captures = work_root / "captures"
        captures.mkdir(parents=True, exist_ok=True)
        output = Path(mkdtemp(prefix="module-" if args.module else "full-", dir=captures))
    print(f"F35 capture output: {output}", flush=True)

    firrtl, manifest = extract_inputs(args, output) if args.module else (args.firrtl, args.manifest)
    common = ["--firrtl", str(firrtl), "--manifest", str(manifest), "--paired-capture",
              "--work-root", str(work_root)]
    if args.verify_replay:
        common.append("--verify-replay")
    gsim = args.reference or output / "gsim"
    grh = output / "grh"
    if args.reference is None:
        gsim_extra = ["--binary", str(args.binary)]
        if args.export_state_actions:
            gsim_extra.extend(["--export-state-actions"])
        capture("gsim", common, gsim, gsim_extra)
    extra = ["--reference", str(gsim), "--xmr-limit", str(args.xmr_limit),
             "--flatten-limit", str(args.flatten_limit)]
    if args.export_state_actions:
        extra.append("--binary=" + str(args.binary))
    if args.package:
        extra.extend(["--package", str(args.package)])
    if args.export_state_actions:
        extra.append("--export-state-actions")
    capture("grh", common, grh, extra)

    runs = {}
    for engine, directory in (("gsim", gsim), ("grh", grh)):
        summary_path = directory / "summary.json"
        summary = json.loads(summary_path.read_text())
        runs[engine] = {"summary": str(summary_path), "run_id": summary["run_id"], "passes": summary["passes"]}
    write_json_atomic(output / "summary.json", {
        "schema": "wolvrix.f35.paired-capture.v1", "complete": True,
        "scope": "module" if args.module else "full", "firrtl": str(firrtl), "manifest": str(manifest),
        "module_extraction": str(output / "extraction.json") if args.module else None,
        "reused_gsim_reference": args.reference is not None, **runs,
    })
    print(f"GSIM and GRH capture complete: {output / 'summary.json'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("firrtl", "manifest"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("binary", "output", "package"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--reference", type=Path, help="reuse a frozen GSIM reference for whole-design capture")
    parser.add_argument("--module", help="original FIRRTL module name")
    parser.add_argument("--work-root", type=Path, help="artifact root for an isolated paired capture")
    parser.add_argument("--export-state-actions", action="store_true",
                        help="include the GRH R4 state/action inventory")
    parser.add_argument("--sv", action="append", default=[], type=Path, help="additional module SV helper")
    parser.add_argument("--reset-port", action="append", default=[], metavar="NAME=TYPE",
                        help="bind a module's abstract Reset input to AsyncReset or UInt<1>")
    parser.add_argument("--max-module-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--xmr-limit", type=float, default=180)
    parser.add_argument("--flatten-limit", type=float, default=300)
    parser.add_argument("--verify-replay", action="store_true")
    args = parser.parse_args()
    for name in ("firrtl", "manifest", "binary", "output", "package", "reference"):
        if (path := getattr(args, name)) is not None:
            setattr(args, name, path.resolve())
    if args.module and args.reference:
        parser.error("--module requires a fresh GSIM capture from the extracted FIRRTL. "
                     "Use --reference only for whole-design capture.")
    if args.reference is None and (args.binary is None or not args.binary.is_file()):
        parser.error("a GSIM binary is required unless --reference is supplied")
    if args.sv and not args.module:
        parser.error("add whole-design SV sources to the input manifest")
    if args.reset_port and not args.module:
        parser.error("--reset-port applies to module capture")
    args.reset_ports = {}
    for binding in args.reset_port:
        name, _, kind = binding.partition("=")
        if not name or kind not in ("AsyncReset", "UInt<1>"):
            parser.error("--reset-port requires NAME=AsyncReset or 'NAME=UInt<1>'")
        name = name.strip("`")
        if name in args.reset_ports:
            parser.error("duplicate --reset-port for " + name)
        args.reset_ports[name] = kind
    try:
        args.sv = [path.resolve(strict=True) for path in args.sv]
        WORK.mkdir(parents=True, exist_ok=True)
        with capture_lock("paired"):
            run(args)
    except FileExistsError as error:
        parser.exit(1, f"F35 capture failed: output already exists: {error.filename}\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"F35 capture failed: {error}\n")


if __name__ == "__main__":
    main()
