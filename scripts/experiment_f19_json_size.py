"""Measure GRH JSON size reductions from omitting def/users and source locations."""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

from benchmark_xs_firrtl_ingest import (
    ROOT, allocator_configuration, checked, native_identity,
)
from verify_grh_json_roundtrip import semantic_stats


def size_entry(path: Path, baseline: int) -> dict:
    size = path.stat().st_size
    saved = baseline - size
    return {
        "bytes": size,
        "saved_bytes": saved,
        "saved_percent": saved * 100.0 / baseline if baseline else 0.0,
        "ratio": size / baseline if baseline else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--native-dir", required=True, type=Path)
    args = parser.parse_args()
    original = args.input.resolve()
    output = args.output.resolve()
    native_dir = args.native_dir.resolve()
    if not original.is_file():
        parser.error(f"input not found: {original}")
    if not output.is_relative_to(ROOT / "ptmp"):
        parser.error("output must be under repository ptmp/")
    if not sys.flags.no_site:
        parser.error("run with Python -S and the native snapshot environment")
    output.mkdir(parents=True, exist_ok=True)
    baseline = original.stat().st_size
    report_path = output / "summary.json"
    report = {
        "input": str(original),
        "baseline": {"bytes": baseline},
        "native_directory": str(native_dir),
        "variants": {},
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

        with wolvrix.Session() as session:
            session.log_level = "info"
            stage_started = time.perf_counter()
            checked(session.read_json_file(str(original), out_design="design.main"), "load baseline JSON")
            report["load_s"] = time.perf_counter() - stage_started
            report["original_semantics"] = semantic_stats(session, "design.main")
            variants = (
                ("no-def-users", False, True),
                ("no-loc", True, False),
                ("minimal", False, False),
            )
            for name, emit_def_users, emit_source_locations in variants:
                path = output / f"{name}.json"
                stage_started = time.perf_counter()
                checked(session.store_json(
                    design="design.main", output=str(path),
                    emit_def_users=emit_def_users,
                    emit_source_locations=emit_source_locations,
                ), f"store {name} JSON")
                report["variants"][name] = {
                    **size_entry(path, baseline),
                    "store_s": time.perf_counter() - stage_started,
                }
            session.delete("design.main")
            stage_started = time.perf_counter()
            checked(session.read_json_file(str(output / "minimal.json"), out_design="design.main"),
                    "load minimal JSON")
            report["minimal_load_s"] = time.perf_counter() - stage_started
            report["minimal_semantics"] = semantic_stats(session, "design.main")
        report["equal"] = report["original_semantics"] == report["minimal_semantics"]
        if not report["equal"]:
            raise RuntimeError("SemanticTree statistics changed after omitting def/users/loc")
    except Exception as error:
        report["error"] = str(error)
    report["maxrss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report["verification_s"] = time.perf_counter() - started
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True), flush=True)
    return 0 if report["equal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
