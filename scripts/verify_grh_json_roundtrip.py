"""Verify an existing GRH JSON file through an isolated native snapshot."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from benchmark_xs_firrtl_ingest import (
    ROOT, allocator_configuration, checked, json_identity, native_identity,
)


def file_signature(path: Path) -> tuple[int, ...]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="directory under repository ptmp/")
    parser.add_argument("--native-dir", required=True, type=Path, help="packaged native snapshot")
    args = parser.parse_args()
    original = args.input.resolve()
    output = args.output.resolve()
    native_dir = args.native_dir.resolve()
    restored = (output / "roundtrip.json").resolve()
    report_path = (output / "roundtrip-identity.json").resolve()
    for path in (output, restored, report_path):
        if not path.is_relative_to(ROOT / "ptmp"):
            parser.error("all outputs must be under repository ptmp/")
    if original in (restored, report_path):
        parser.error("input must differ from output artifacts")
    if not original.is_file():
        parser.error(f"input not found: {original}")
    if not sys.flags.no_site:
        parser.error("run with Python -S and the native snapshot environment")

    output.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "wolvrix.grh-json-roundtrip-identity.v1",
        "input": str(original),
        "output": str(restored),
        "native_directory": str(native_dir),
        "equal": False,
    }
    started = time.perf_counter()
    try:
        import wolvrix

        report["native_libraries"] = native_identity()
        report["allocator_configuration"] = allocator_configuration()
        mapped = {Path(entry["path"]) for entry in report["native_libraries"]}
        expected = {native_dir / "_wolvrix.so", native_dir / "libwolvrix-lib.so"}
        if (Path(wolvrix.__file__).resolve().parent != native_dir / "python" / "wolvrix" or
                not expected.issubset(mapped) or
                any(not path.is_relative_to(native_dir) for path in mapped)):
            raise RuntimeError("loaded native libraries do not match the requested isolated snapshot")

        signature = file_signature(original)
        report["original"] = {**json_identity(original), "mtime_ns": signature[3]}
        if file_signature(original) != signature:
            raise RuntimeError("input changed while computing its fingerprint")
        with wolvrix.Session() as session:
            session.log_level = "info"
            checked(session.read_json_file(str(original), out_design="design.main"), "load input JSON")
            checked(session.store_json(design="design.main", output=str(restored)), "store roundtrip JSON")
        report["roundtrip"] = json_identity(restored)
        if file_signature(original) != signature:
            raise RuntimeError("input changed during roundtrip verification")
        report["equal"] = all(
            report["original"][key] == report["roundtrip"][key] for key in ("bytes", "sha256")
        )
        if not report["equal"]:
            raise RuntimeError("JSON roundtrip changed full-file byte count or SHA-256")
    except Exception as error:
        report["error"] = str(error)
    report["verification_s"] = time.perf_counter() - started
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True), flush=True)
    return 0 if report["equal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
