"""Measure native ingest, optionally through the production GRH flatten prefix."""

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


def allocator_configuration() -> dict | None:
    """Read effective settings when the loaded native variant exposes them."""
    import wolvrix
    query = getattr(wolvrix._native, "allocator_configuration", None)
    return query() if query is not None else None


def graph_profile_stats() -> dict | None:
    """Read optional logical storage counters without enabling instrumentation."""
    import wolvrix
    query = getattr(wolvrix._native, "graph_profile_stats", None)
    return query() if query is not None else None


def allocator_statistics() -> dict | None:
    """Read actual native C++ allocations from a separate MI_STAT=1 build."""
    import wolvrix
    query = getattr(wolvrix._native, "allocator_statistics", None)
    return query() if query is not None else None


def allocation_delta(before: dict, after: dict) -> int:
    if not before["all_threads_merged"] or not after["all_threads_merged"]:
        raise RuntimeError("allocator counters omit live worker threads that have not merged their statistics")
    result = after["allocations"] - before["allocations"]
    if result < 0:
        raise RuntimeError("allocator counters decreased between stage snapshots")
    return result


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


def store_identity(session, output: Path, *, stage: str = "ingest", discard_json: bool = False) -> dict:
    started = time.perf_counter()
    original = output / f"{stage}.json"
    checked(session.store_json(design="design.main", output=str(original)), f"store {stage} JSON")
    report = {**json_identity(original), "store_and_hash_s": time.perf_counter() - started}
    identity_name = "graph-identity.json" if stage == "ingest" else f"{stage}-graph-identity.json"
    (output / identity_name).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if discard_json:
        original.unlink()
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
    parser.add_argument("--through-flatten", action="store_true",
                        help="run the full production GRH prefix through hier-flatten after ingest")
    parser.add_argument("--prefix-identity", action="store_true",
                        help="separate correctness run: store full ingest and flatten graph identities")
    parser.add_argument("--align-bare", action="store_true",
                        help="with --prefix-identity, run only hier-flatten after ingest")
    parser.add_argument("--fused-prefix", action="store_true",
                        help="use the explicit parallel grh-pre-flatten ingest endpoint")
    parser.add_argument("--discard-identity-json", action="store_true",
                        help="remove each prefix correctness graph JSON after storing its hash")
    parser.add_argument("--profile-timestamps", action="store_true",
                        help="record CLOCK_MONOTONIC stage intervals for perf --clockid mono")
    parser.add_argument("--allocator-stats", action="store_true",
                        help="diagnostic run with bundled mimalloc MI_STAT=1; excludes Python/libc allocations")
    args = parser.parse_args()
    if args.through_flatten and (args.verify_roundtrip or args.store_identity):
        parser.error("--through-flatten measures the in-memory prefix without JSON serialization")
    if args.prefix_identity and (args.through_flatten or args.verify_roundtrip or args.store_identity):
        parser.error("--prefix-identity is a separate correctness mode")
    if args.discard_identity_json and not args.prefix_identity:
        parser.error("--discard-identity-json requires --prefix-identity")
    if args.align_bare and (not args.prefix_identity or args.through_flatten or args.fused_prefix):
        parser.error("--align-bare requires --prefix-identity without --through-flatten or --fused-prefix")
    run_prefix = args.through_flatten or args.prefix_identity
    if args.fused_prefix and (not run_prefix or args.sv_filelist):
        parser.error("--fused-prefix requires a manifest and --through-flatten or --prefix-identity")
    if args.cpu is not None:
        if not hasattr(os, "sched_setaffinity"):
            parser.error("--cpu requires OS support for process CPU affinity")
        if args.cpu not in os.sched_getaffinity(0):
            parser.error("--cpu must name a CPU in the process affinity mask")
        os.sched_setaffinity(0, {args.cpu})
    # Pin before native imports can initialize a frontend worker pool.
    import wolvrix
    initial_allocator_stats = allocator_statistics()
    if args.allocator_stats and initial_allocator_stats is None:
        parser.error("--allocator-stats requires a WOLVRIX_MIMALLOC_STATS=ON native build")
    if initial_allocator_stats is not None and not args.allocator_stats:
        parser.error("MI_STAT=1 is a diagnostic build; use --allocator-stats or rebuild with WOLVRIX_MIMALLOC_STATS=OFF")
    output = args.output.resolve()
    manifest = (args.manifest or args.sv_filelist).resolve()
    if not manifest.is_relative_to(ROOT / "ptmp"):
        parser.error("manifest must be under repository ptmp/")
    if not output.is_relative_to(ROOT / "ptmp"):
        parser.error("output must be under repository ptmp/")
    output.mkdir(parents=True, exist_ok=True)
    profile_stages = []

    def record_profile_stage(name: str, start_ns: int, end_ns: int) -> None:
        if args.profile_timestamps:
            profile_stages.append({"name": name, "start_ns": start_ns, "end_ns": end_ns})
            (output / "profile-stages.json").write_text(json.dumps({
                "clock": "monotonic", "clock_implementation": time.get_clock_info("monotonic").implementation,
                "stages": profile_stages,
            }, indent=2) + "\n", encoding="utf-8")

    for name in ("graph-identity.json", "roundtrip-identity.json", "flatten-graph-identity.json", "prefix-identity.json"):
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
        "configuration": {"profile": False, "parse_cache": "on",
                          "fused_prefix": args.fused_prefix,
                          "profile_timestamps": args.profile_timestamps,
                          "measurement_mode": "prefix-identity" if args.prefix_identity else
                          "through-flatten" if args.through_flatten else "ingest"},
        "allocator_environment": {key: value for key, value in sorted(os.environ.items())
                                  if key.upper().startswith("MIMALLOC_") or
                                  key in {"MALLOC_ARENA_MAX", "MALLOC_TRIM_THRESHOLD_", "GLIBC_TUNABLES", "LD_PRELOAD"}},
        "allocator_configuration": allocator_configuration(),
        "source_bytes": source_bytes,
    }
    if args.allocator_stats:
        report["configuration"]["allocator_statistics"] = "bundled-mimalloc-MI_STAT=1"
        report["allocator_statistics_scope"] = "native C++ allocations; current and exited threads; Python/libc excluded"
    prefix_identity = None
    if args.prefix_identity:
        prefix_identity = {
            "schema": "wolvrix.firrtl-prefix-identity.v1",
            "run_identity": {key: report[key] for key in (
                "manifest_sha256", "native_libraries", "configuration", "allocator_environment",
                "allocator_configuration", "cpu_affinity")},
            "source_fingerprints": {path: json_identity(Path(path)) for path in source_bytes},
            "json_retained": not args.discard_identity_json,
            "stages": {},
        }
    (output / "native-identity.json").write_text(
        json.dumps(report["native_libraries"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with wolvrix.Session() as session:
        session.log_level = "info"
        session.diagnostics_raise_min_level = "none"
        allocation_before = allocator_statistics() if args.allocator_stats else None
        usage_before = resource.getrusage(resource.RUSAGE_SELF)
        started = time.perf_counter()
        profile_started_ns = time.monotonic_ns()
        if args.sv_filelist:
            diagnostics = session.read_sv(None, slang_args=request["slang_args"], out_design="design.main")
        else:
            diagnostics = session.read_sources(**request, out_design="design.main",
                pipeline="grh-pre-flatten" if args.fused_prefix and not args.prefix_identity else "ingest")
        profile_ended_ns = time.monotonic_ns()
        elapsed = time.perf_counter() - started
        record_profile_stage("ingest-pre-flatten" if args.fused_prefix and not args.prefix_identity else "ingest",
                             profile_started_ns, profile_ended_ns)
        usage_after = resource.getrusage(resource.RUSAGE_SELF)
        allocation_after = allocator_statistics() if args.allocator_stats else None
        user_s = usage_after.ru_utime - usage_before.ru_utime
        system_s = usage_after.ru_stime - usage_before.ru_stime
        report.update({"ingest_s": elapsed,
                       "ingest_user_s": user_s,
                       "ingest_system_s": system_s,
                       "ingest_cpu_s": user_s + system_s,
                       "graph_profile_stats": graph_profile_stats(),
                       "thread_affinity": thread_affinity(),
                       "maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                       "diagnostics": diagnostics,
                       "success": not any(str(entry.get("kind", "")).lower() == "error" for entry in diagnostics)})
        if args.align_bare or args.through_flatten:
            report["ingest_semantic_stats"] = session.semantic_stats(design="design.main")
        if args.allocator_stats:
            report["ingest_allocator_statistics"] = {
                "before": allocation_before, "after": allocation_after,
                "allocations": allocation_delta(allocation_before, allocation_after),
            }
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
        if args.prefix_identity:
            stored = store_identity(session, output, discard_json=args.discard_identity_json)
            prefix_identity["stages"]["ingest"] = {
                "graph": {key: stored[key] for key in ("bytes", "sha256")},
                "metadata": metadata, "diagnostics": diagnostics,
                "store_and_hash_s": stored["store_and_hash_s"],
            }
            (output / "prefix-identity.json").write_text(
                json.dumps(prefix_identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if run_prefix:
            from wolvrix_xs_grhsim import GRH_PIPELINE
            stages = []
            prefix_wall = 0.0
            if args.fused_prefix:
                if args.prefix_identity:
                    # The raw identity above belongs to an independent ingest.
                    # Restart from the sources for the fused endpoint identity.
                    session.delete("design.main")
                    fused_started = time.perf_counter()
                    fused_usage = resource.getrusage(resource.RUSAGE_SELF)
                    fused_diagnostics = session.read_sources(**request, out_design="design.main",
                        pipeline="grh-pre-flatten")
                    report["ingest_prefix_s"] = time.perf_counter() - fused_started
                    fused_after = resource.getrusage(resource.RUSAGE_SELF)
                    report["ingest_prefix_cpu_s"] = (fused_after.ru_utime - fused_usage.ru_utime +
                        fused_after.ru_stime - fused_usage.ru_stime)
                    checked(fused_diagnostics, "fused ingest prefix")
                else:
                    fused_diagnostics = diagnostics
                    report["ingest_prefix_s"] = elapsed
                    report["ingest_prefix_cpu_s"] = user_s + system_s
                    report["ingest_s"] = None
                    report["ingest_cpu_s"] = None
                    report["ingest_user_s"] = None
                    report["ingest_system_s"] = None
                prefix_report = session.get("design.main.prefix")
                prefix_wall = prefix_report["prefix_wall_s"]
                report["prefix_wall_s"] = prefix_wall
                stages.extend(dict(row, options=options, keep_declared_symbols=True)
                    for row, (name, options) in zip(prefix_report["stages"], GRH_PIPELINE)
                    if row["pass"] == name)
                if len(stages) != 8:
                    raise RuntimeError("fused ingest prefix did not report the eight production stages")
                diagnostics = fused_diagnostics[:prefix_report["ingest_diagnostic_count"]]
                if not args.prefix_identity:
                    report["diagnostics"] = diagnostics
            report["post_ingest_stages"] = stages
            report["measurement_scope"] = ("correctness run with ingest/flatten serialization; not formal prefix timing"
                                           if args.prefix_identity else
                                           "original sources through full production hier-flatten prefix")
            for name, options in GRH_PIPELINE:
                if (args.fused_prefix or args.align_bare) and name != "hier-flatten":
                    continue
                print(f"[benchmark] start GRH pass {name}", flush=True)
                stage_allocation_before = allocator_statistics() if args.allocator_stats else None
                stage_usage = resource.getrusage(resource.RUSAGE_SELF)
                stage_started = time.perf_counter()
                profile_started_ns = time.monotonic_ns()
                stage_diagnostics = session.run_pass(
                    name, design="design.main", keep_declared_symbols=True, **options)
                profile_ended_ns = time.monotonic_ns()
                stage_elapsed = time.perf_counter() - stage_started
                record_profile_stage(f"{len(stages):02d}-{name}", profile_started_ns, profile_ended_ns)
                stage_after = resource.getrusage(resource.RUSAGE_SELF)
                stage_allocation_after = allocator_statistics() if args.allocator_stats else None
                stages.append({"pass": name, "options": options, "wall_s": stage_elapsed,
                               "keep_declared_symbols": True,
                               "cpu_s": (stage_after.ru_utime - stage_usage.ru_utime +
                                         stage_after.ru_stime - stage_usage.ru_stime),
                               "maxrss_kib": stage_after.ru_maxrss,
                               "graph_profile_stats": graph_profile_stats(),
                               "diagnostics": stage_diagnostics})
                if args.allocator_stats:
                    stages[-1]["allocator_statistics"] = {
                        "before": stage_allocation_before, "after": stage_allocation_after,
                        "allocations": allocation_delta(stage_allocation_before, stage_allocation_after),
                    }
                report["success"] = report["success"] and not any(
                    str(entry.get("kind", "")).lower() == "error" for entry in stage_diagnostics)
                (output / "timing.json").write_text(
                    json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                checked(stage_diagnostics, name)
                print(f"[benchmark] done GRH pass {name}: {stage_elapsed:.3f} s", flush=True)
                if name == "hier-flatten":
                    report["hier_flatten_s"] = stage_elapsed
                    report["pre_flatten_passes_s"] = prefix_wall if args.fused_prefix else sum(row["wall_s"] for row in stages[:-1])
                    report["ingest_plus_hier_flatten_s"] = None if args.fused_prefix else elapsed + stage_elapsed
                    report["through_flatten_stage_sum_s"] = (report["ingest_prefix_s"] + stage_elapsed if args.fused_prefix
                        else elapsed + sum(row["wall_s"] for row in stages))
                    report["through_flatten_maxrss_kib"] = stage_after.ru_maxrss
                    if args.allocator_stats:
                        report["through_flatten_allocations"] = allocation_delta(allocation_before, stage_allocation_after)
                    if args.through_flatten:
                        report["through_flatten_wall_s"] = time.perf_counter() - started
                    else:
                        stored = store_identity(session, output, stage="flatten", discard_json=args.discard_identity_json)
                        prefix_identity["stages"]["flatten"] = {
                            "graph": {key: stored[key] for key in ("bytes", "sha256")},
                            "metadata": session.graph_metadata(design="design.main", top=top),
                            "diagnostics": [row["diagnostics"] for row in stages],
                            "store_and_hash_s": stored["store_and_hash_s"],
                        }
                        prefix_identity["pipeline"] = [
                            {key: row[key] for key in ("pass", "options", "keep_declared_symbols")}
                            for row in stages]
                        report["prefix_correctness_wall_s"] = time.perf_counter() - started
                        (output / "prefix-identity.json").write_text(
                            json.dumps(prefix_identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                    if args.align_bare or args.through_flatten:
                        report["flatten_semantic_stats"] = session.semantic_stats(design="design.main")
                    (output / "timing.json").write_text(
                        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                    break
            else:
                raise RuntimeError("production GRH pipeline has no hier-flatten stage")
    (output / "counts.json").write_text(json.dumps({
        "source_bytes": report["source_bytes"], "diagnostics": len(diagnostics),
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "rss.txt").write_text(f"maxrss_kib={report['maxrss_kib']}\n", encoding="utf-8")
    scope = "ingest plus production pre-flatten prefix" if args.fused_prefix and not args.prefix_identity else "ingest"
    summary = ["# Ingest benchmark", "", f"- {scope}: {elapsed:.3f} s",
               f"- max RSS: {report['maxrss_kib']} KiB",
               "- native allocator instrumentation: MI_STAT=1 diagnostic" if args.allocator_stats else
               "- native allocator instrumentation: disabled"]
    if args.through_flatten:
        summary += [f"- hier-flatten: {report['hier_flatten_s']:.3f} s",
                    f"- production prefix through flatten: {report['through_flatten_wall_s']:.3f} s"]
    elif args.prefix_identity:
        summary += ["- correctness run with both complete graph identities; not formal prefix timing",
                    f"- correctness run including serialization: {report['prefix_correctness_wall_s']:.3f} s"]
    (output / "baseline-summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    (output / "timing.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("ingest_s", "maxrss_kib", "manifest_sha256", "configuration")}, sort_keys=True))
    if args.through_flatten:
        print(json.dumps({key: report[key] for key in (
            "hier_flatten_s", "pre_flatten_passes_s", "ingest_plus_hier_flatten_s",
            "through_flatten_stage_sum_s", "through_flatten_wall_s",
            "through_flatten_maxrss_kib")}, sort_keys=True))


if __name__ == "__main__":
    main()
