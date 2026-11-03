"""Compare complete FIRRTL prefix evidence or summarize uncontaminated repeat timings."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from statistics import median

from compare_xs_firrtl_ingest import compare, diagnostics_identity, read
from wolvrix_xs_grhsim import GRH_PIPELINE


def configuration(work: Path, report: dict) -> dict:
    """Recognize only the old benchmark's explicit un-serialized prefix scope."""
    result = dict(report["configuration"])
    if "measurement_mode" not in result:
        identity_files = ("graph-identity.json", "roundtrip-identity.json",
                          "flatten-graph-identity.json", "prefix-identity.json")
        if (report.get("measurement_scope") == "original sources through full production hier-flatten prefix" and
                "through_flatten_wall_s" in report and
                not any((work / name).exists() for name in identity_files) and
                "graph_identity" not in report and "roundtrip" not in report):
            result["measurement_mode"] = "through-flatten"
    result.setdefault("profile_timestamps", (work / "profile-stages.json").is_file())
    return result


def prefix_stages(report: dict) -> list[dict]:
    stages = report["post_ingest_stages"]
    end = next(index for index, (name, _) in enumerate(GRH_PIPELINE) if name == "hier-flatten")
    expected = [{"pass": name, "options": options, "keep_declared_symbols": True}
                for name, options in GRH_PIPELINE[:end + 1]]
    actual = [{key: row.get(key, True if key == "keep_declared_symbols" else None)
               for key in ("pass", "options", "keep_declared_symbols")} for row in stages]
    if actual != expected:
        raise ValueError("evidence does not cover the full production prefix through hier-flatten")
    return stages


def measurements(report: dict) -> dict:
    stages = prefix_stages(report)
    return {
        "ingest": {"wall_s": report["ingest_s"], "cpu_s": report["ingest_cpu_s"],
                   "maxrss_kib": report["maxrss_kib"]},
        "pre_flatten": {"wall_s": sum(row["wall_s"] for row in stages[:-1]),
                        "cpu_s": sum(row["cpu_s"] for row in stages[:-1]),
                        "maxrss_kib": max(row["maxrss_kib"] for row in stages[:-1])},
        "flatten": {key: stages[-1][key] for key in ("wall_s", "cpu_s", "maxrss_kib")},
        "prefix": {"wall_s": report.get("through_flatten_wall_s"),
                   "cpu_s": report["ingest_cpu_s"] + sum(row["cpu_s"] for row in stages),
                   "maxrss_kib": report["through_flatten_maxrss_kib"]},
    }


def validate_fingerprint(value: dict, context: str) -> None:
    if (not isinstance(value, dict) or type(value.get("bytes")) is not int or value["bytes"] <= 0 or
            not isinstance(value.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"])):
        raise ValueError(f"{context} requires a positive byte count and complete SHA256")


def validate_native_libraries(entries: list) -> None:
    if not isinstance(entries, list) or not entries:
        raise ValueError("native library identity is missing")
    paths = set()
    for entry in entries:
        if (not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or
                not Path(entry["path"]).is_absolute() or entry["path"] in paths or
                not isinstance(entry.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
            raise ValueError("native library identities require unique absolute paths and complete SHA256")
        paths.add(entry["path"])


def validate_allocator_configuration(value: dict | None) -> None:
    if value is None:
        return
    if (not isinstance(value, dict) or set(value) != {"mimalloc", "project_defaults", "generic_collect"} or
            type(value["mimalloc"]) is not bool or type(value["project_defaults"]) is not bool or
            (value["generic_collect"] is not None and
             (type(value["generic_collect"]) is not int or value["generic_collect"] < 1))):
        raise ValueError("effective allocator configuration requires two booleans and a positive interval or null")


def validate_prefix_identity(identity: dict, report: dict) -> None:
    if identity.get("schema") != "wolvrix.firrtl-prefix-identity.v1":
        raise ValueError("unsupported prefix identity schema")
    if set(identity.get("stages", {})) != {"ingest", "flatten"}:
        raise ValueError("both ingest and flatten complete graph identities are required")
    if report["configuration"].get("measurement_mode") != "prefix-identity":
        raise ValueError("complete prefix identity requires its dedicated correctness report")
    if not isinstance(report.get("manifest_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", report["manifest_sha256"]):
        raise ValueError("manifest identity requires a complete SHA256")
    expected_run = {key: report[key] for key in (
        "manifest_sha256", "native_libraries", "configuration", "allocator_environment", "cpu_affinity")}
    if "allocator_configuration" in report:
        expected_run["allocator_configuration"] = report["allocator_configuration"]
    if identity.get("run_identity") != expected_run:
        raise ValueError("prefix identity does not belong to the reported native/configuration/manifest")
    sources = report["source_bytes"]
    fingerprints = identity.get("source_fingerprints", {})
    if not sources or set(fingerprints) != set(sources):
        raise ValueError("source fingerprints must cover every reported input source")
    for name, value in fingerprints.items():
        validate_fingerprint(value, f"source {name}")
        if type(sources[name]) is not int or value["bytes"] != sources[name]:
            raise ValueError(f"source fingerprint byte count disagrees with input source: {name}")
    stages = prefix_stages(report)
    expected_pipeline = [{key: row[key] for key in ("pass", "options", "keep_declared_symbols")}
                         for row in stages]
    if identity.get("pipeline") != expected_pipeline:
        raise ValueError("prefix identity pipeline disagrees with the timed production passes")
    for stage in ("ingest", "flatten"):
        evidence = identity["stages"][stage]
        validate_fingerprint(evidence.get("graph"), stage + " graph")
        metadata = evidence.get("metadata")
        if (not isinstance(metadata, dict) or not isinstance(metadata.get("symbol"), str) or
                not metadata["symbol"] or not isinstance(metadata.get("metadata"), dict)):
            raise ValueError(f"{stage} graph metadata is incomplete")
        diagnostics = (report["diagnostics"] if stage == "ingest" else
                       [row["diagnostics"] for row in stages])
        if evidence.get("diagnostics") != diagnostics:
            raise ValueError(f"{stage} identity diagnostics disagree with the execution report")
    metadata = identity["stages"]["ingest"]["metadata"]["metadata"]
    if (sorted(metadata) != report["metadata_keys"] or
            metadata.get("ingest.dependencies", []) != report["dependencies"]):
        raise ValueError("ingest identity metadata disagrees with the execution report")


def compare_prefix(baseline: Path, candidate: Path, *, timing_only: bool = False) -> dict:
    before, after = (read(work, "timing.json") for work in (baseline, candidate))
    for report in (before, after):
        validate_native_libraries(report["native_libraries"])
        validate_allocator_configuration(report.get("allocator_configuration"))
    stages = [prefix_stages(report) for report in (before, after)]
    result = compare(baseline, candidate, timing_only=True)
    result["graph_checked"] = not timing_only
    result["checks"].update({
        "success": before["success"] is True and after["success"] is True,
        "configuration": configuration(baseline, before) == configuration(candidate, after),
        "source_bytes": before["source_bytes"] == after["source_bytes"],
        "prefix_diagnostics": diagnostics_identity([row["diagnostics"] for row in stages[0]]) ==
                              diagnostics_identity([row["diagnostics"] for row in stages[1]]),
    })
    if not timing_only:
        identities = [read(work, "prefix-identity.json") for work in (baseline, candidate)]
        for identity, report in zip(identities, (before, after)):
            validate_prefix_identity(identity, report)
        result["checks"]["source_fingerprints"] = (bool(identities[0]["source_fingerprints"]) and
            identities[0]["source_fingerprints"] == identities[1]["source_fingerprints"])
        result["checks"]["pipeline"] = identities[0]["pipeline"] == identities[1]["pipeline"]
        for stage in ("ingest", "flatten"):
            left, right = (identity["stages"][stage] for identity in identities)
            result["checks"][stage + "_graph"] = left["graph"] == right["graph"]
            result["checks"][stage + "_metadata"] = left["metadata"] == right["metadata"]
            result["checks"][stage + "_diagnostics"] = (diagnostics_identity(left["diagnostics"]) ==
                                                         diagnostics_identity(right["diagnostics"]))
        result["prefix_identity"] = identities
    result["measurements"] = [measurements(report) for report in (before, after)]
    result["allocator_environment"] = [report.get("allocator_environment", {}) for report in (before, after)]
    result["allocator_configuration"] = [report.get("allocator_configuration") for report in (before, after)]
    result["note"] = ("Correctness runs serialize both endpoints; only dedicated --through-flatten runs "
                      "provide continuous prefix wall time. Native libraries and allocator settings are "
                      "reported as experimental variables and are not required to match.")
    result["equal"] = all(result["checks"].values())
    return result


def summarize(runs: list[Path]) -> dict:
    if not runs:
        raise ValueError("at least one timing run is required")
    if len({work.resolve() for work in runs}) != len(runs):
        raise ValueError("repeat timing runs require distinct output directories")
    reports = [read(work, "timing.json") for work in runs]
    for work, report in zip(runs, reports):
        config = configuration(work, report)
        if config.get("measurement_mode") != "through-flatten":
            raise ValueError("repeat timing summaries require dedicated --through-flatten runs")
        if (any((work / name).exists() for name in ("graph-identity.json", "roundtrip-identity.json",
                "flatten-graph-identity.json", "prefix-identity.json")) or
                "graph_identity" in report or "roundtrip" in report):
            raise ValueError("serialized correctness evidence cannot enter repeat timing summaries")
        if config.get("profile") or config["profile_timestamps"] or (work / "profile-stages.json").exists():
            raise ValueError("profile/perf diagnostic runs cannot enter repeat timing summaries")
        if "through_flatten_wall_s" not in report:
            raise ValueError("continuous prefix wall time is missing")
    comparisons = [compare_prefix(runs[0], work, timing_only=True) for work in runs]
    checks = {"repeated_configuration_and_diagnostics": all(item["equal"] for item in comparisons),
              "native_libraries": all(sorted(item["sha256"] for item in report["native_libraries"]) ==
                                      sorted(item["sha256"] for item in reports[0]["native_libraries"])
                                      for report in reports),
              "allocator_environment": all(report.get("allocator_environment", {}) ==
                                           reports[0].get("allocator_environment", {}) for report in reports),
              "allocator_configuration": all(report.get("allocator_configuration") ==
                                             reports[0].get("allocator_configuration") for report in reports)}
    values = [measurements(report) for report in reports]
    summary = {}
    for phase, metrics in values[0].items():
        summary[phase] = {}
        for metric in metrics:
            samples = [row[phase][metric] for row in values]
            summary[phase][metric] = {"samples": samples, "median": median(samples),
                                      "min": min(samples), "max": max(samples)}
    return {"runs": [str(work.resolve()) for work in runs], "run_count": len(runs),
            "checks": checks, "equal": all(checks.values()), "summary": summary,
            "native_libraries": reports[0]["native_libraries"],
            "allocator_environment": reports[0].get("allocator_environment", {}),
            "allocator_configuration": reports[0].get("allocator_configuration")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    comparison = commands.add_parser("compare")
    comparison.add_argument("--baseline", required=True, type=Path)
    comparison.add_argument("--candidate", required=True, type=Path)
    comparison.add_argument("--timing-only", action="store_true")
    comparison.add_argument("--output", required=True, type=Path)
    summary = commands.add_parser("summarize")
    summary.add_argument("--runs", nargs="+", required=True, type=Path)
    summary.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = (compare_prefix(args.baseline, args.candidate, timing_only=args.timing_only)
              if args.command == "compare" else summarize(args.runs))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("equal", "checks")}, sort_keys=True))
    if not result["equal"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
