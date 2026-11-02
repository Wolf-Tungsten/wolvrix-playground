"""Run the native FIRRTL/mixed ingest stage and record its fixed-input baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import time
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def native_identity() -> list[dict]:
    """Fingerprint the libraries actually mapped by this benchmark process."""
    import wolvrix
    paths = {Path(wolvrix._native.__file__).resolve()}
    maps = Path('/proc/self/maps')
    if maps.is_file():
        for line in maps.read_text().splitlines():
            fields = line.split(maxsplit=5)
            if len(fields) == 6 and fields[5].startswith('/'):
                path = Path(fields[5])
                if 'wolvrix' in path.name and '.so' in path.name and path.is_file():
                    paths.add(path.resolve())
    result = []
    for path in sorted(paths):
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        result.append({'path': str(path), 'sha256': digest.hexdigest(),
                       'mtime_ns': path.stat().st_mtime_ns})
    return result


def thread_affinity() -> dict[str, int]:
    """Record all live worker masks, including frontend worker threads."""
    if not hasattr(os, "sched_getaffinity") or not Path("/proc/self/task").is_dir():
        return {}
    masks = Counter()
    for entry in Path("/proc/self/task").iterdir():
        try:
            masks[",".join(map(str, sorted(os.sched_getaffinity(int(entry.name)))))] += 1
        except ProcessLookupError:
            continue
    return dict(sorted(masks.items()))


def checked(diagnostics: list[dict], action: str) -> None:
    errors = [entry for entry in diagnostics if str(entry.get("kind", "")).lower() == "error"]
    if errors:
        raise RuntimeError(f"{action}: {errors}")


def json_identity(path: Path) -> dict:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"bytes": path.stat().st_size, "sha256": digest}


def store_identity(session, output: Path) -> dict:
    started = time.perf_counter()
    original = output / "ingest.json"
    checked(session.store_json(design="design.main", output=str(original)), "store ingest JSON")
    report = {**json_identity(original), "store_and_hash_s": time.perf_counter() - started}
    (output / "graph-identity.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def verify_roundtrip(session, output: Path) -> dict:
    original = output / "ingest.json"
    restored = output / "roundtrip.json"
    started = time.perf_counter()
    stored = store_identity(session, output)
    before = {key: stored[key] for key in ("bytes", "sha256")}
    session.delete("design.main")
    checked(session.read_json_file(str(original), out_design="design.main"), "load ingest JSON")
    checked(session.store_json(design="design.main", output=str(restored)), "store roundtrip JSON")
    after = json_identity(restored)
    report = {"original": before, "roundtrip": after, "equal": before == after,
              "verification_s": time.perf_counter() - started}
    (output / "roundtrip-identity.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not report["equal"]:
        raise RuntimeError("ingest JSON roundtrip changed serialized graph identity")
    return report


def request_from_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.pop("schema", None) != "wolvrix.xs.firrtl-inputs.v1":
        raise ValueError("unsupported FIRRTL inputs manifest")
    allowed = {"sources", "tops", "input_root", "slang_args", "firrtl_options", "external_bindings"}
    if set(data) - allowed:
        raise ValueError(f"unexpected manifest fields: {sorted(set(data) - allowed)}")
    sources = data.get("sources")
    if not isinstance(sources, list) or not sources or not any(
            isinstance(source, dict) and source.get("language") == "firrtl" for source in sources):
        raise ValueError("manifest must contain a FIRRTL source")
    root = Path(data.get("input_root", path.parent))
    if not root.is_absolute():
        root = path.parent / root
    data["input_root"] = str(root.resolve())
    for source in sources:
        if not isinstance(source, dict) or source.get("language") not in {"firrtl", "sv"}:
            raise ValueError("invalid source entry")
        source_path = Path(source.get("path", ""))
        if not source_path.is_absolute():
            source_path = root / source_path
        source["path"] = str(source_path.resolve())
        if not source_path.is_file():
            raise ValueError(f"source not found: {source_path}")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--manifest", type=Path)
    inputs.add_argument("--sv-filelist", type=Path)
    parser.add_argument("--sv-read-args", type=Path)
    parser.add_argument("--top", default="SimTop")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cpu", type=int, help="pin this benchmark process to one allowed CPU")
    parser.add_argument("--verify-roundtrip", action="store_true",
                        help="verify full-design JSON roundtrip after ingest timing")
    parser.add_argument("--store-identity", action="store_true",
                        help="store full-design JSON and hash after ingest timing")
    args = parser.parse_args()
    if args.cpu is not None:
        if not hasattr(os, "sched_setaffinity"):
            parser.error("--cpu requires OS support for process CPU affinity")
        if args.cpu not in os.sched_getaffinity(0):
            parser.error("--cpu must name a CPU in the process affinity mask")
        os.sched_setaffinity(0, {args.cpu})
    # Pin before native imports can initialize a frontend worker pool.
    import wolvrix
    output = args.output.resolve()
    manifest = (args.manifest or args.sv_filelist).resolve()
    if not manifest.is_relative_to(ROOT / "ptmp"):
        parser.error("manifest must be under repository ptmp/")
    if not output.is_relative_to(ROOT / "ptmp"):
        parser.error("output must be under repository ptmp/")
    output.mkdir(parents=True, exist_ok=True)
    for name in ("graph-identity.json", "roundtrip-identity.json"):
        (output / name).unlink(missing_ok=True)
    if args.sv_filelist:
        route = "sv"
        if args.sv_read_args is None:
            parser.error("--sv-filelist requires --sv-read-args")
        from wolvrix_xs_grhsim import read_slang_args
        request = {"tops": [args.top], "slang_args": read_slang_args(manifest, args.top, args.sv_read_args.resolve())}
        # The frozen reference filelist contains one absolute source path per line.
        sources = [Path(line.strip()) for line in manifest.read_text().splitlines() if line.strip()]
        if any(not path.is_absolute() or not path.is_file() for path in sources):
            parser.error("SV reference filelist must contain one absolute source path per line")
        source_bytes = {str(path): path.stat().st_size for path in sources}
        control_identity = {"filelist": json_identity(manifest), "read_args": json_identity(args.sv_read_args),
                            "request": request}
        manifest_sha256 = hashlib.sha256(json.dumps(control_identity, sort_keys=True).encode()).hexdigest()
    else:
        request = request_from_manifest(manifest)
        route = "firrtl/mixed" if any(source["language"] == "sv" for source in request["sources"]) else "firrtl"
        source_bytes = {source["path"]: Path(source["path"]).stat().st_size for source in request["sources"]}
        manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
    (output / "manifest.json").write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = {
        "native_libraries": native_identity(),
        "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "manifest": str(manifest),
        "manifest_sha256": manifest_sha256,
        "route": route,
        "configuration": {"profile": False, "parse_cache": "on"},
        "source_bytes": source_bytes,
    }
    (output / "native-identity.json").write_text(
        json.dumps(report["native_libraries"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with wolvrix.Session() as session:
        session.log_level = "info"
        session.diagnostics_raise_min_level = "none"
        started = time.perf_counter()
        if args.sv_filelist:
            diagnostics = session.read_sv(None, slang_args=request["slang_args"], out_design="design.main")
        else:
            diagnostics = session.read_sources(**request, out_design="design.main")
        elapsed = time.perf_counter() - started
        report.update({"ingest_s": elapsed,
                       "thread_affinity": thread_affinity(),
                       "maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                       "diagnostics": diagnostics,
                       "success": not any(str(entry.get("kind", "")).lower() == "error" for entry in diagnostics)})
        (output / "timing.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        checked(diagnostics, "ingest " + report["route"] + " RTL")
        top = request.get("tops", [None])[0]
        metadata = session.graph_metadata(design="design.main", top=top)
        report.update({
            "ingest_s": elapsed,
            "maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "diagnostics": diagnostics,
            "metadata_keys": sorted(metadata.get("metadata", {}).keys()),
            "dependencies": metadata.get("metadata", {}).get("ingest.dependencies", []),
        })
        # Persist the stage measurement even if a later validation fails.
        (output / "timing.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if args.verify_roundtrip:
            report["roundtrip"] = verify_roundtrip(session, output)
        elif args.store_identity:
            report["graph_identity"] = store_identity(session, output)
    (output / "counts.json").write_text(json.dumps({
        "source_bytes": report["source_bytes"], "diagnostics": len(diagnostics),
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "rss.txt").write_text(f"maxrss_kib={report['maxrss_kib']}\n", encoding="utf-8")
    summary = ["# Ingest benchmark", "", f"- ingest: {elapsed:.3f} s",
               f"- max RSS: {report['maxrss_kib']} KiB", "- native performance instrumentation: removed"]
    (output / "baseline-summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    (output / "timing.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("ingest_s", "maxrss_kib", "manifest_sha256", "configuration")}, sort_keys=True))


if __name__ == "__main__":
    main()
