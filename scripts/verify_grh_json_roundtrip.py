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


def semantic_stats(session, design: str) -> dict:
    stats = session.semantic_stats(design=design)
    if any(stats[key] == 0 for key in ("trees", "nodes", "semantic_ids")):
        raise RuntimeError("semantic verification requires non-empty trees, nodes and SemanticIds")
    return stats


def semantic_validation(session, design: str) -> dict:
    result = session.semantic_validate(design=design)
    if result["module_path_duplicates"] or result["register_symbol_mismatches"]:
        raise RuntimeError(f"SemanticTree validation failed: {json.dumps(result, sort_keys=True)}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="directory under repository ptmp/")
    parser.add_argument("--native-dir", required=True, type=Path, help="packaged native snapshot")
    parser.add_argument("--semantic", action="store_true",
                        help="require and compare non-empty SemanticTree/SemanticId statistics on native graphs")
    parser.add_argument("--f20", action="store_true",
                        help="also validate unique instance paths and hierarchical register symbols")
    parser.add_argument("--existing", action="store_true",
                        help="validate an existing roundtrip.json without storing it again")
    args = parser.parse_args()
    if args.f20:
        args.semantic = True
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
            if args.existing:
                if not restored.is_file():
                    raise RuntimeError(f"existing roundtrip not found: {restored}")
                stage_started = time.perf_counter()
                checked(session.read_json_file(str(restored), out_design="design.main"), "load existing roundtrip JSON")
                report["load_s"] = time.perf_counter() - stage_started
                if args.semantic:
                    stats = semantic_stats(session, "design.main")
                    report["original_semantics"] = stats
                    report["roundtrip_semantics"] = stats
                if args.f20:
                    report["original_validation"] = semantic_validation(session, "design.main")
                    report["roundtrip_validation"] = report["original_validation"]
                report["existing_roundtrip"] = True
            else:
                stage_started = time.perf_counter()
                checked(session.read_json_file(str(original), out_design="design.main"), "load input JSON")
                report["load_s"] = time.perf_counter() - stage_started
                if args.semantic:
                    report["original_semantics"] = semantic_stats(session, "design.main")
                if args.f20:
                    report["original_validation"] = semantic_validation(session, "design.main")
                stage_started = time.perf_counter()
                checked(session.store_json(design="design.main", output=str(restored)), "store roundtrip JSON")
                report["store_s"] = time.perf_counter() - stage_started
                if args.semantic:
                    session.delete("design.main")
                    stage_started = time.perf_counter()
                    checked(session.read_json_file(str(restored), out_design="design.main"), "load roundtrip JSON")
                    report["roundtrip_load_s"] = time.perf_counter() - stage_started
                    report["roundtrip_semantics"] = semantic_stats(session, "design.main")
                if args.f20:
                    report["roundtrip_validation"] = semantic_validation(session, "design.main")
        report["roundtrip"] = json_identity(restored)
        if file_signature(original) != signature:
            raise RuntimeError("input changed during roundtrip verification")
        if args.semantic:
            statistic_keys = ("trees", "nodes", "name_bytes", "value_rows", "operation_rows", "semantic_ids")
            if any(report["original_semantics"][key] != report["roundtrip_semantics"][key]
                   for key in statistic_keys):
                raise RuntimeError("SemanticTree statistics changed during JSON roundtrip")
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
