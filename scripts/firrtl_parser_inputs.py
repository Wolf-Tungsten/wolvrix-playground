"""Freeze or verify the exact inputs and all-body results used to accept F03."""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path


SCHEMA = "wolvrix.firrtl-parser-inputs.v1"
SPEC_REVISION = "5ab37a032d822c8e3975fb9f7f36e52a019c34ec"
VOLATILE_METRICS = {"file", "unit", "index_ms", "body_ms"}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def identity(root, path):
    path = path.resolve(strict=True)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
            "sha256": digest.hexdigest()}


def snapshot(args):
    root = args.root.resolve(strict=True)
    filelist = args.sv_filelist.resolve(strict=True)
    rtl = filelist.parent
    listed = []
    for line in filelist.read_text().splitlines():
        if not line.strip():
            continue
        path = (rtl / line.strip()).resolve(strict=True)
        if path.suffix not in {".sv", ".v"}:
            raise ValueError(f"expected a source filename in {filelist}: {line}")
        listed.append(path)
    if not listed or len(listed) != len(set(listed)):
        raise ValueError("SV filelist must contain unique source filenames")
    sources = set(listed)
    sources.update(path.resolve() for path in rtl.rglob("*")
                   if path.is_file() and path.suffix in {".sv", ".v", ".svh", ".vh"})
    sv = [identity(root, path) for path in sorted(sources)]
    fixtures = sorted((root / "wolvrix/tests/ingest/data/firrtl").glob("*.fir"))
    if not fixtures:
        raise ValueError("the FIRRTL parser fixture corpus is missing")
    files = [identity(root, path) for path in
             [args.firrtl, filelist, args.generation_log, args.spec, *fixtures]]
    return {
        "schema": SCHEMA,
        "spec_revision": SPEC_REVISION,
        "files": files,
        "sv_inventory": {
            "root": rtl.relative_to(root).as_posix(),
            "listed_files": len(listed),
            "files": len(sv),
            "bytes": sum(item["bytes"] for item in sv),
            "sha256": hashlib.sha256(encoded(sv)).hexdigest(),
        },
    }, sv


def inspect(args):
    command = [str(args.inspector.resolve(strict=True)), "--expected-version", "6.0.0", str(args.firrtl)]
    start = time.monotonic()
    result = subprocess.run(command, text=True, capture_output=True)
    elapsed = time.monotonic() - start
    args.work_dir.mkdir(parents=True, exist_ok=True)
    (args.work_dir / "inspection.log").write_text(result.stdout + result.stderr)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode:
        raise ValueError(f"FIRRTL inspection failed with exit status {result.returncode}")
    metrics = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if not separator or key in metrics:
            raise ValueError(f"invalid inspection record: {line}")
        metrics[key] = int(value) if value.isdecimal() else value
    if metrics.get("status") != "passed" or metrics.get("validation") != "all-module-bodies":
        raise ValueError("acceptance requires successful validation of every module body")
    if not metrics.get("modules") or metrics.get("validated_modules") != metrics["modules"]:
        raise ValueError("inspection did not validate every indexed module")
    print(f"inspection_wall_seconds={elapsed:.6f}")
    return {key: value for key, value in metrics.items() if key not in VOLATILE_METRICS}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "verify"))
    for name in ("root", "firrtl", "sv-filelist", "generation-log", "spec", "inspector", "manifest", "work-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == "capture" and args.manifest.exists():
            raise ValueError("capture requires a new manifest path; existing frozen inputs are not overwritten")
        expected = json.loads(args.manifest.read_text()) if args.mode == "verify" else None
        actual, sv = snapshot(args)
        if expected is not None:
            if expected.get("schema") != SCHEMA:
                raise ValueError("unsupported input manifest schema")
            if {key: expected.get(key) for key in actual} != actual:
                raise ValueError("frozen input identity mismatch (FIRRTL, fixtures, SV, generation log or specification)")
        actual["parser"] = inspect(args)
        after, after_sv = snapshot(args)
        if after != {key: actual[key] for key in after} or after_sv != sv:
            raise ValueError("input contents changed during validation")
        if expected is not None and actual != expected:
            raise ValueError("all-body parser/interface results differ from the frozen acceptance results")
        args.work_dir.mkdir(parents=True, exist_ok=True)
        (args.work_dir / "sv-inventory.json").write_text(json.dumps(sv, indent=2) + "\n")
        (args.work_dir / "verified-inputs.json").write_text(json.dumps(actual, indent=2) + "\n")
        if args.mode == "capture":
            args.manifest.parent.mkdir(parents=True, exist_ok=True)
            args.manifest.write_text(json.dumps(actual, indent=2) + "\n")
        print(f"frozen_inputs={args.mode}-passed sv_files={len(sv)} manifest={args.manifest}")
        return 0
    except (OSError, ValueError) as error:
        print(f"[firrtl-inputs] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
