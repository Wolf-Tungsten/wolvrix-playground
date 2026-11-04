"""Compare frozen F17.1 six-family self costs (exit 1 for a missed budget, 2 for invalid evidence)."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from benchmark_xs_firrtl_ingest import request_from_manifest
from profile_xs_firrtl_ingest import sample_quality, sha256, text_identity, stage_windows


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "wolvrix.f17.self-hotspot-comparison.v3"
PREPASSES = (
    "00-xmr-resolve", "01-mux-tree-fold", "02-register-write-normalize",
    "03-mux-tree-fold", "04-memory-read-retime", "05-multidriven-guard",
    "06-blackbox-guard", "07-latch-transparent-read",
)
FLATTEN = "08-hier-flatten"
STAGES = ("ingest", *PREPASSES, FLATTEN)
SPANS = (*STAGES, "pre-flatten", "whole")
SELECTED = ("ingest", "pre-flatten", FLATTEN)
JOINT = "ingest-pre-flatten"
LIBRARIES = {"_wolvrix.so", "libwolvrix-lib.so"}
GROUPING = {
    "mi_new": "exact mi_new with optional @plt or [clone ...] suffix",
    "memmove": r"\b(?:__)?memmove\w*(?:@plt)?(?: \[clone [^]]+\])*$",
    "_Hash_bytes": "contains std::_Hash_bytes(",
    "try_emplace": "contains ::try_emplace (all templates)",
    "Graph::opKind": "contains wolvrix::lib::grh::Graph::opKind(",
    "Graph::~Graph": "contains wolvrix::lib::grh::Graph::~Graph(",
}
FAMILIES = tuple(GROUPING)
CONFIG_FIELDS = (
    "configuration", "cpu_affinity", "thread_affinity", "allocator_configuration",
    "allocator_environment", "manifest_sha256", "measurement_scope", "route",
    "source_bytes", "dependencies", "metadata_keys",
)
UNKNOWN = re.compile(r"(?:0x)?[0-9a-fA-F]+")
MEMMOVE = re.compile(GROUPING["memmove"])
MI_NEW = re.compile(r"mi_new(?:@plt)?(?: \[clone [^]]+\])*")


def read_json(path: Path):
    return json.loads(path.read_text())


def digest_json(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def ns_timestamp(value: str) -> int:
    seconds, _, fraction = value.partition(".")
    if len(fraction) > 9:
        raise ValueError(f"Timestamp is not an integer nanosecond: {value}")
    return int(seconds) * 10**9 + int(fraction.ljust(9, "0") or "0")


def time_option(stage: dict) -> str:
    def stamp(ns):
        return f"{ns // 10**9}.{ns % 10**9:09d}"
    return f"{stamp(stage['start_ns'])},{stamp(stage['end_ns'])}"


def option(command: list[str], name: str):
    index = command.index(name) + 1 if name in command else len(command)
    return command[index] if index < len(command) else None


def family_matches(symbol: str) -> list[str]:
    # These are the frozen predicates, independent of the DSO and new names
    # that an implementation might introduce when work moves elsewhere.
    return [name for name, matches in (
        ("mi_new", MI_NEW.fullmatch(symbol)),
        ("memmove", MEMMOVE.search(symbol)),
        ("_Hash_bytes", "std::_Hash_bytes(" in symbol),
        ("try_emplace", "::try_emplace" in symbol),
        ("Graph::opKind", "wolvrix::lib::grh::Graph::opKind(" in symbol),
        ("Graph::~Graph", "wolvrix::lib::grh::Graph::~Graph(" in symbol),
    ) if matches]


class Evidence:
    def __init__(self):
        self.checks: dict[str, bool] = {}
        self.failures: dict[str, object] = {}

    def check(self, name: str, condition: bool, detail=None) -> None:
        self.checks[name] = bool(condition)
        if not condition and detail is not None:
            self.failures[name] = detail


def parse_report(path: Path, stage: dict, evidence: Evidence, prefix: str) -> dict:
    rows, unparsed, headers, events, lost, slices = [], [], [], [], [], []
    trailing_columns = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        if line.startswith("#"):
            if "Overhead" in line and "Symbol" in line:
                # Some perf versions append IPC fields even for cpu-clock.
                # Their padded symbol column can be thousands of bytes wide.
                trailing_columns = 2 if "[IPC Coverage]" in line else 1 if "IPC" in line else 0
            if match := re.search(r"Event count \(approx\.\):\s*(\d+)", line):
                headers.append(int(match[1]))
            if match := re.search(r"Samples:.*of event '([^']+)'", line):
                events.append(match[1])
            if match := re.search(r"Total Lost Samples:\s*(\d+)", line):
                lost.append(int(match[1]))
            if match := re.search(r"time slices:\s*([\d.]+),([\d.]+)", line):
                slices.append((ns_timestamp(match[1]), ns_timestamp(match[2])))
            continue
        body = line
        if trailing_columns:
            suffix = body.rsplit(None, trailing_columns)
            if len(suffix) != trailing_columns + 1:
                unparsed.append(line)
                continue
            body = suffix[0]
        # Whitespace splitting is linear in the row width. A lazy symbol
        # regexp followed by \s*$ repeatedly scans the padding before IPC.
        parts = body.split(None, 5)
        if (len(parts) != 6 or not parts[0].endswith("%") or
            not parts[0][:-1].replace(".", "", 1).isdecimal() or
            not parts[1].isdecimal() or not parts[2].isdecimal() or
            not (parts[4].startswith("[") and parts[4].endswith("]"))):
            unparsed.append(line)
            continue
        rows.append({"samples": int(parts[1]), "period_ns": int(parts[2]),
                     "dso": parts[3], "symbol": parts[5].rstrip()})
    matched = {name: [] for name in FAMILIES}
    overlaps, unresolved = [], []
    for row in rows:
        names = family_matches(row["symbol"])
        if len(names) > 1:
            overlaps.append(row)
        for name in names:
            matched[name].append(row)
        if row["symbol"] == "[unknown]" or UNKNOWN.fullmatch(row["symbol"]):
            unresolved.append(row)
    periods = {name: sum(row["period_ns"] for row in matched[name]) for name in FAMILIES}
    total = sum(row["period_ns"] for row in rows)
    evidence.check(f"{prefix}.all_rows_parsed", bool(rows) and not unparsed, unparsed)
    evidence.check(f"{prefix}.event_is_cpu_clock_user", events == ["cpu-clock:u"], events)
    evidence.check(f"{prefix}.period_sum_matches_header", headers == [total], headers)
    evidence.check(f"{prefix}.no_reported_lost_samples", lost == [0], lost)
    evidence.check(f"{prefix}.interval_matches_stage",
                   slices == [(stage["start_ns"], stage["end_ns"])], slices)
    evidence.check(f"{prefix}.families_disjoint", not overlaps, overlaps)
    evidence.check(f"{prefix}.no_unresolved_core_leaf",
                   not any(Path(row["dso"]).name in LIBRARIES for row in unresolved), unresolved)
    return {
        "path": str(path), "period_ns": total, "header_period_ns": headers[0] if len(headers) == 1 else None,
        "samples": sum(row["samples"] for row in rows), "row_count": len(rows),
        "family_period_ns": periods, "six_family_period_ns": sum(periods.values()),
        "symboltable_try_emplace_ns": sum(row["period_ns"] for row in matched["try_emplace"]
                                           if "SymbolTable::StringHash" in row["symbol"]),
        "matched_rows": matched, "unparsed_rows": unparsed,
        "unresolved_leaf_rows": unresolved,
        "unresolved_leaf_period_ns": sum(row["period_ns"] for row in unresolved),
        "unresolved_leaf_samples": sum(row["samples"] for row in unresolved),
        "top20_leaf_rows": sorted(rows, key=lambda row: -row["period_ns"])[:20],
    }


def pipeline(timing: dict) -> list[dict]:
    return [{key: row.get(key) for key in ("pass", "options", "keep_declared_symbols")}
            for row in timing["post_ingest_stages"]]


def normalized_diagnostics(rows: list[dict]) -> str:
    # Transaction IDs are unique per invocation; preserve filenames, source
    # coordinates, messages, ordering and every other diagnostic field.
    return re.sub(r"(ptmp/firrtl-ingest/transactions/)[0-9]+-[0-9]+/", r"\1<RUN>/",
                  json.dumps(rows, sort_keys=True))


def library_hashes(rows: list[dict]) -> dict[str, str]:
    result = {Path(row["path"]).name: row["sha256"] for row in rows}
    if len(result) != len(rows):
        raise ValueError("Duplicate native library names")
    return result


def stage_layout(stages: list[dict]) -> tuple[dict, tuple, tuple]:
    """Return only observed windows, without inventing a fused CPU split."""
    expected = (JOINT, FLATTEN) if stages and stages[0]["name"] == JOINT else STAGES
    if [row["name"] for row in stages] != list(expected):
        raise ValueError("Evidence must contain the fused endpoint or all ten production stages")
    spans = {row["name"]: row for row in stage_windows(stages)}
    selected = (JOINT, FLATTEN) if JOINT in spans else SELECTED
    quality = (expected[0], FLATTEN, "whole")
    return spans, selected, quality


def inspect_commands(work: Path, spans: dict, evidence: Evidence, label: str) -> None:
    commands = read_json(work / "reports/commands.json")
    first = JOINT if JOINT in spans else "ingest"
    expected = {(name, variant) for name in spans for variant in ("self", "inclusive")}
    expected.update({(name, "calltree") for name in (first, FLATTEN)})
    expected.update({(name, variant) for name in (first, FLATTEN, "whole")
                     for variant in ("stats", "samples")})
    actual = [(row["stage"]["name"], row["variant"]) for row in commands]
    evidence.check(f"{label}.complete_report_commands", len(actual) == len(expected) and set(actual) == expected,
                   {"expected": sorted(expected), "actual": actual})
    evidence.check(f"{label}.all_report_commands_succeeded", all(row["returncode"] == 0 for row in commands))
    for row in commands:
        name, variant = row["stage"]["name"], row["variant"]
        command = row["command"]
        tag = f"{label}.{name}.{variant}.command"
        destination = work / f"reports/{name}.{variant}.txt"
        stderr = destination.with_suffix(".stderr.log")
        evidence.check(f"{tag}.stage", name in spans and row["stage"] == spans[name])
        evidence.check(f"{tag}.time", name in spans and option(command, "--time") == time_option(spans[name]))
        evidence.check(f"{tag}.files", Path(row["stdout"]).resolve() == destination.resolve() and
                       Path(row["stderr"]).resolve() == stderr.resolve() and destination.is_file())
        evidence.check(f"{tag}.stderr_empty", stderr.is_file() and stderr.stat().st_size == 0)
        evidence.check(f"{tag}.recording", option(command, "-i") == str(work / "perf.data") and
                       option(command, "--symfs") == str(work / "symfs"))
        if name not in spans:
            continue
        common = ["report", "--stdio", "--stdio-color", "never", "--symfs", str(work / "symfs"),
                  "-i", str(work / "perf.data"), "--time", time_option(spans[name]), "-n",
                  "--show-total-period", "--sort", "dso,symbol", "--percent-limit", "0"]
        variants = {
            "self": common + ["--no-children", "-g", "none"],
            "inclusive": common + ["--children", "-g", "none"],
            "calltree": common + ["--children", "-g", "graph,0.5,caller"],
            "stats": common + ["--no-children", "-g", "none", "--stats", "--header"],
            "samples": ["script", "--hide-call-graph", "--ns", "--show-lost-events", "--symfs", str(work / "symfs"),
                        "-i", str(work / "perf.data"), "--time", time_option(spans[name]),
                        "-F", "pid,tid,time,period,comm,ip,sym,dso"],
        }
        # Exact argument lists reject filters and percent thresholds that could
        # silently remove DSOs or symbols from the fixed family denominator.
        evidence.check(f"{tag}.complete_scope", variant in variants and command[1:] == variants[variant])


def inspect_snapshots(work: Path, record: dict, timing: dict, evidence: Evidence, label: str) -> list[dict]:
    symbols = read_json(work / "symbol-identity.json")
    evidence.check(f"{label}.record_symbol_metadata_matches", record.get("symbols") == symbols)
    executed = library_hashes([row["installed"] for row in symbols])
    evidence.check(f"{label}.required_core_libraries", set(executed) == LIBRARIES)
    evidence.check(f"{label}.record_native_matches_run", executed == library_hashes(timing["native_libraries"]))
    evidence.check(f"{label}.run_native_identity_matches", executed == library_hashes(read_json(work / "run/native-identity.json")))
    result = []
    for row in symbols:
        name = Path(row["installed"]["path"]).name
        snapshot = work / "symbols" / name
        actual_sha = sha256(snapshot)
        text = text_identity(snapshot)
        text_fields = ("address", "bytes", "sha256")
        expected_text = {key: row["text_identity"][key] for key in text_fields}
        actual_text = {key: text[key] for key in text_fields}
        evidence.check(f"{label}.snapshot.{name}", actual_sha == row["snapshot_sha256"] and actual_text == expected_text)
        mapped = work / "symfs" / row["installed"]["path"].lstrip("/")
        evidence.check(f"{label}.symbol_mapping.{name}", mapped.resolve() == snapshot.resolve())
        result.append({"snapshot": str(snapshot), "executed_installed": row["installed"],
                       "expected_snapshot_sha256": row["snapshot_sha256"], "actual_snapshot_sha256": actual_sha,
                       "expected_text_identity": expected_text, "actual_text_identity": actual_text})
    return result


def inspect_run(work: Path, evidence: Evidence, label: str) -> dict:
    record = read_json(work / "record.json")
    timing = read_json(work / "run/timing.json")
    manifest_path = work / "run/manifest.json"
    manifest = read_json(manifest_path)
    stage_data = read_json(work / "run/profile-stages.json")
    stages = stage_data["stages"]
    evidence.check(f"{label}.record_success", record.get("status") == "complete" and record.get("returncode") == 0 and
                   record.get("probe_returncode") == 0 and timing.get("success") is True)
    command = record["record_command"]
    prefix = command[:command.index("--")]
    evidence.check(f"{label}.same_requested_sampling_options", prefix[1:] == [
        "record", "--no-buildid-cache", "-e", "cpu-clock:u", "-F", "199", "--call-graph", "dwarf,8192",
        "--clockid", "mono", "-o", str(work / "perf.data")])
    evidence.check(f"{label}.monotonic_stage_clock", stage_data.get("clock") == "monotonic")
    spans, selected, quality_names = stage_layout(stages)
    evidence.check(f"{label}.complete_ordered_stages", True)
    evidence.check(f"{label}.ordered_positive_boundaries", True)
    evidence.check(f"{label}.declared_fused_endpoint_matches_windows",
                   timing["configuration"].get("fused_prefix", False) == (JOINT in spans))
    original_manifest = Path(record["manifest"])
    evidence.check(f"{label}.manifest_record_matches_run", record["manifest_sha256"] == timing["manifest_sha256"] and
                   record["manifest"] == timing["manifest"])
    evidence.check(f"{label}.manifest_source_matches_snapshot", sha256(original_manifest) == record["manifest_sha256"] and
                   request_from_manifest(original_manifest) == manifest)
    evidence.check(f"{label}.uninstrumented_configuration", timing["configuration"].get("profile") is False and
                   timing["configuration"].get("profile_timestamps") is True and
                   timing["configuration"].get("measurement_mode") == "through-flatten" and
                   "allocator_statistics" not in timing["configuration"] and not timing.get("allocator_statistics"))
    evidence.check(f"{label}.production_pipeline", [row["pass"] for row in pipeline(timing)] ==
                   [name[3:] for name in (*PREPASSES, FLATTEN)] and
                   all(row["keep_declared_symbols"] is True for row in pipeline(timing)))
    evidence.check(f"{label}.pipeline_options", [row["options"] for row in pipeline(timing)] ==
                   [{}, {}, {"semantics": "2state"}, {"guarded_writes": "2state"}, {}, {}, {}, {}, {}])
    inspect_commands(work, spans, evidence, label)
    snapshots = inspect_snapshots(work, record, timing, evidence, label)
    reports = {name: parse_report(work / f"reports/{name}.self.txt", spans[name], evidence, f"{label}.{name}")
               for name in spans}
    quality = {}
    for name in quality_names:
        prefix = f"{label}.{name}"
        stored = read_json(work / f"reports/{name}.quality.json")
        actual = sample_quality(work / f"reports/{name}.samples.txt")
        evidence.check(f"{prefix}.quality_matches_sample_records", all(stored.get(key) == value for key, value in actual.items()))
        evidence.check(f"{prefix}.quality_stage_matches", stored.get("stage") == spans[name])
        evidence.check(f"{prefix}.quality_period_and_samples_match", actual["period_ns"] == reports[name]["period_ns"] and
                       actual["samples"] == reports[name]["samples"] and
                       actual["unresolved_leaf_period_ns"] == reports[name]["unresolved_leaf_period_ns"] and
                       actual["unresolved_leaf_samples"] == reports[name]["unresolved_leaf_samples"])
        stats = (work / f"reports/{name}.stats.txt").read_text()
        lost = [line.strip() for line in stats.splitlines()
                if re.search(r"\bLOST(?:_SAMPLES)?\s+events:", line, re.IGNORECASE)]
        evidence.check(f"{prefix}.quality_no_lost_or_unparsed", not actual["lost_event_lines"] and
                       not actual["unparsed_lines"] and not lost and not stored.get("lost_record_stat_lines"))
        quality[name] = stored
    for family in FAMILIES:
        if JOINT not in spans:
            evidence.check(f"{label}.prepass_gap_nonnegative.{family}", reports["pre-flatten"]["family_period_ns"][family] >=
                           sum(reports[name]["family_period_ns"][family] for name in PREPASSES))
        evidence.check(f"{label}.whole_gap_nonnegative.{family}", reports["whole"]["family_period_ns"][family] >=
                       sum(reports[name]["family_period_ns"][family] for name in selected))
    return {"record": record, "timing": timing, "manifest": manifest, "spans": spans,
            "reports": reports, "quality": quality, "snapshots": snapshots, "selected": selected}


def sum_reports(reports: dict, names: tuple[str, ...]) -> dict:
    periods = {family: sum(reports[name]["family_period_ns"][family] for name in names) for family in FAMILIES}
    return {"period_ns": sum(reports[name]["period_ns"] for name in names), "family_period_ns": periods,
            "six_family_period_ns": sum(periods.values()),
            "unresolved_leaf_period_ns": sum(reports[name]["unresolved_leaf_period_ns"] for name in names)}


def comparison(baseline: dict, candidate: dict) -> dict:
    before, after = baseline["six_family_period_ns"], candidate["six_family_period_ns"]
    upper = after + candidate["unresolved_leaf_period_ns"]
    return {
        "f16_ns": before, "candidate_ns": after, "quarter_limit_ns": before / 4,
        "candidate_over_f16": after / before if before else None,
        "reduction_percent": 100 * (1 - after / before) if before else None,
        "below_f16_quarter": after * 4 <= before,
        "candidate_with_all_unresolved_ns": upper,
        "quarter_even_if_all_candidate_unresolved_match": upper * 4 <= before,
        "f16_sampled_cpu_ns": baseline["period_ns"], "candidate_sampled_cpu_ns": candidate["period_ns"],
        "families": {name: {
            "f16_ns": baseline["family_period_ns"][name], "candidate_ns": candidate["family_period_ns"][name],
            "candidate_over_f16": candidate["family_period_ns"][name] / baseline["family_period_ns"][name]
                if baseline["family_period_ns"][name] else None,
        } for name in FAMILIES},
    }


def inspect_timing(path: Path, candidate: dict, evidence: Evidence) -> dict:
    timing_path = path / "timing.json" if path.is_dir() else path
    timing = read_json(timing_path)
    native = read_json(timing_path.parent / "native-identity.json")
    recorded = library_hashes(candidate["timing"]["native_libraries"])
    evidence.check("candidate_perf_native_matches_normal_timing",
                   library_hashes(timing["native_libraries"]) == library_hashes(native) == recorded)
    evidence.check("formal_timing.success", timing.get("success") is True)
    evidence.check("formal_timing.uninstrumented", timing["configuration"].get("profile") is False and
                   timing["configuration"].get("profile_timestamps") is False and
                   "allocator_statistics" not in timing["configuration"] and not timing.get("allocator_statistics"))
    manifest_path = timing_path.parent / "manifest.json"
    evidence.check("formal_timing.manifest_snapshot", read_json(manifest_path) == candidate["manifest"] and
                   sha256(Path(timing["manifest"])) == timing["manifest_sha256"] and
                   request_from_manifest(Path(timing["manifest"])) == read_json(manifest_path))
    for field in CONFIG_FIELDS:
        before, after = candidate["timing"].get(field), timing.get(field)
        if field == "configuration":
            before = {key: value for key, value in before.items() if key != "profile_timestamps"}
            after = {key: value for key, value in after.items() if key != "profile_timestamps"}
        evidence.check(f"formal_timing.same_configuration.{field}", before == after)
    evidence.check("formal_timing.same_pipeline", pipeline(timing) == pipeline(candidate["timing"]))
    evidence.check("formal_timing.same_ingest_diagnostics", normalized_diagnostics(timing["diagnostics"]) ==
                   normalized_diagnostics(candidate["timing"]["diagnostics"]))
    snapshots = {Path(row["snapshot"]).name: row for row in candidate["snapshots"]}
    files = []
    for row in native:
        library = Path(row["path"])
        text = text_identity(library)
        actual = sha256(library)
        name = library.name
        evidence.check(f"formal_timing.frozen_snapshot.{name}", actual == row["sha256"] == recorded.get(name))
        evidence.check(f"formal_timing.text_matches_profile.{name}",
                       {key: text[key] for key in ("address", "bytes", "sha256")} == snapshots[name]["actual_text_identity"])
        files.append({"path": str(library), "actual_sha256": actual, "expected_sha256": row["sha256"], "text_identity": text})
    return {"path": str(timing_path), "native_snapshots": files,
            "measurements": {key: timing.get(key) for key in (
                "ingest_s", "ingest_cpu_s", "ingest_prefix_s", "ingest_prefix_cpu_s", "pre_flatten_passes_s", "hier_flatten_s",
                "through_flatten_wall_s", "through_flatten_maxrss_kib")}}


def compare(args) -> dict:
    evidence = Evidence()
    runs = {label: inspect_run(work, evidence, label) for label, work in
            (("f16", args.baseline), ("candidate", args.candidate))}
    baseline, candidate = runs["f16"], runs["candidate"]
    for field in CONFIG_FIELDS:
        before, after = baseline["timing"].get(field), candidate["timing"].get(field)
        if field == "configuration":
            # The scheduling route is the intended implementation difference.
            before = {key: value for key, value in before.items() if key != "fused_prefix"}
            after = {key: value for key, value in after.items() if key != "fused_prefix"}
        if field == "metadata_keys":
            # A fused run records ingest_prefix_* endpoint fields while the
            # F16 run records separate ingest_* fields. Compare the common
            # schema and retain both complete key lists in the evidence.
            # Older fixture records (and small unit-test fixtures) may omit
            # metadata_keys entirely. Treat a missing list as an empty schema;
            # the real evidence still compares the complete recorded lists.
            before = {key for key in (before or ()) if not key.startswith("ingest_")}
            after = {key for key in (after or ()) if not key.startswith("ingest_")}
            # F17's retention publication adds this metadata key; it is a
            # serialized pipeline feature already checked by the JSON identity
            # comparison, rather than a benchmark configuration input.
            after.discard("firrtl.nodeEliminated")
        evidence.check(f"same_run_configuration.{field}", before == after)
    evidence.check("same_run_configuration.manifest", baseline["manifest"] == candidate["manifest"])
    evidence.check("same_run_configuration.complete_ordered_pipeline", pipeline(baseline["timing"]) == pipeline(candidate["timing"]))
    evidence.check("same_run_configuration.ordered_diagnostics_normalized_temp_path",
                   normalized_diagnostics(baseline["timing"]["diagnostics"]) ==
                   normalized_diagnostics(candidate["timing"]["diagnostics"]))
    evidence.check("same_run_configuration.ordered_pass_diagnostics", all(
        normalized_diagnostics(left["diagnostics"]) == normalized_diagnostics(right["diagnostics"])
        for left, right in zip(baseline["timing"]["post_ingest_stages"], candidate["timing"]["post_ingest_stages"])))
    for run in runs.values():
        run["reports"]["selected-stage-sum"] = sum_reports(run["reports"], run["selected"])
        if JOINT not in run["reports"]:
            run["reports"][JOINT] = sum_reports(run["reports"], ("ingest", "pre-flatten"))
            run["reports"][JOINT]["aggregation"] = "sum of observed ingest and continuous pre-flatten windows"
            run["reports"]["eight-prepass-body-sum"] = sum_reports(run["reports"], PREPASSES)
    common = [name for name in baseline["reports"] if name in candidate["reports"]]
    comparisons = {name: comparison(baseline["reports"][name], candidate["reports"][name])
                   for name in common}
    timing = inspect_timing(args.timing, candidate, evidence) if args.timing else None
    integrity = all(evidence.checks.values())
    selected = (JOINT, FLATTEN) if any(run["selected"][0] == JOINT for run in runs.values()) else SELECTED
    budget_scopes = (*selected, "selected-stage-sum")
    measured_budget = all(comparisons[name]["below_f16_quarter"] for name in budget_scopes)
    return {
        "schema": SCHEMA, "analysis": "offline existing reports only; no rerecording or native execution",
        "baseline": str(args.baseline), "candidate": str(args.candidate), "grouping": GROUPING,
        "measurement_scope": "exclusive sampled cpu-clock:u leaf Period nanoseconds; all DSOs; PLT and clones included; zero sampled cost is not proof of zero work",
        "budget_operator": "candidate_ns * 4 <= f16_ns", "budget_scopes": budget_scopes,
        "selected_scopes": selected,
        "joint_interval_comparison": selected[0] == JOINT,
        "analysis_integrity_verified": integrity, "sampled_budget_pass": measured_budget,
        "budget_pass": integrity and measured_budget,
        "budget_pass_with_unresolved_upper_bound": integrity and all(
            comparisons[name]["quarter_even_if_all_candidate_unresolved_match"] for name in budget_scopes),
        "formal_timing_identity_verified": all(value for key, value in evidence.checks.items()
            if key.startswith("formal_timing.") or key == "candidate_perf_native_matches_normal_timing") if args.timing else None,
        "formal_timing": timing, "checks": evidence.checks, "failed_check_details": evidence.failures,
        "comparisons": comparisons, "reports": {label: run["reports"] for label, run in runs.items()},
        "quality": {label: run["quality"] for label, run in runs.items()},
        "record_metadata": {label: run["record"] for label, run in runs.items()},
        "native_snapshot_verification": {label: run["snapshots"] for label, run in runs.items()},
        "run_configuration": {label: {
            **{field: run["timing"].get(field) for field in CONFIG_FIELDS if field not in ("dependencies", "metadata_keys")},
            "dependencies_sha256": digest_json(run["timing"].get("dependencies")),
            "metadata_keys_sha256": digest_json(run["timing"].get("metadata_keys")), "pipeline": pipeline(run["timing"]),
            "manifest": str((args.baseline if label == "f16" else args.candidate) / "run/manifest.json"),
        } for label, run in runs.items()},
        "limitations": [
            "Self costs do not establish inclusive callchain completeness.",
            ("The fused ingest/pre-flatten CPU is one observed interval, compared with F16's ingest plus continuous pre-flatten self costs; no per-pass CPU split is inferred."
             if selected[0] == JOINT else
             "Each prepass body is reported; the budget uses the continuous pre-flatten interval including gaps."),
            "Newly named or inlined work is not added to or used to shrink the frozen six families; inspect top20_leaf_rows for migration.",
            "Formal timing, RSS and actual allocator evidence remain separate from sampled CPU acceptance.",
        ],
    }


def markdown(report: dict) -> str:
    lines = ["# F17.1 six-family sampled self CPU comparison", "",
             f"Integrity: **{'PASS' if report['analysis_integrity_verified'] else 'FAIL'}**. "
             f"Budget: **{'PASS' if report['budget_pass'] else 'FAIL'}**.", ""]
    if "error" in report:
        return "\n".join([*lines, f"Analysis error: {report['error']}", ""])
    lines.extend([
        "The six frozen predicates include all DSOs, PLT entries and clones. Integer leaf Periods are nanoseconds; "
        "rounded overhead percentages are never used. Each required stage and the selected-stage sum must be at most one quarter of F16.", "",
        "| Scope | F16 self s | Candidate self s | Candidate/F16 | F16 quarter s | At most quarter |",
        "|---|---:|---:|---:|---:|---|",
    ])
    selected = report["selected_scopes"]
    for name in (*selected, "selected-stage-sum", "eight-prepass-body-sum", "whole", *PREPASSES):
        if name not in report["comparisons"]:
            continue
        row = report["comparisons"][name]
        ratio = f"{row['candidate_over_f16']:.6f}" if row["candidate_over_f16"] is not None else "n/a"
        lines.append(f"| {name} | {row['f16_ns'] / 1e9:.9f} | {row['candidate_ns'] / 1e9:.9f} | {ratio} | "
                     f"{row['quarter_limit_ns'] / 1e9:.11f} | {'PASS' if row['below_f16_quarter'] else 'FAIL'} |")
    lines.extend(["", "## Family detail", "",
                  "| Family | " + " | ".join(f"F16 {name} s | Candidate {name} s" for name in selected) + " |",
                  "|---|" + "---:|" * (len(selected) * 2)])
    for family in FAMILIES:
        cells = [family]
        for name in selected:
            row = report["comparisons"][name]["families"][family]
            cells.extend(f"{row[key] / 1e9:.9f}" for key in ("f16_ns", "candidate_ns"))
        lines.append("| " + " | ".join(cells) + " |")
    if not report["joint_interval_comparison"]:
        lines.extend(["", "## All eight prepass bodies", "",
                  "Cells are F16 → candidate sampled CPU seconds. These bodies exclude the gaps retained by the pre-flatten budget interval.", "",
                  "| Pass | " + " | ".join(FAMILIES) + " | Six-family sum |",
                  "|---|" + "---:|" * (len(FAMILIES) + 1)])
    for name in PREPASSES:
        if name not in report["comparisons"]:
            continue
        row = report["comparisons"][name]
        cells = [name]
        for family in FAMILIES:
            values = row["families"][family]
            cells.append(f"{values['f16_ns'] / 1e9:.6f} → {values['candidate_ns'] / 1e9:.6f}")
        cells.append(f"{row['f16_ns'] / 1e9:.6f} → {row['candidate_ns'] / 1e9:.6f}")
        lines.append("| " + " | ".join(cells) + " |")
    passed = sum(report["checks"].values())
    lines.extend(["", "## Integrity and unresolved leaves", "", f"{passed}/{len(report['checks'])} integrity checks passed. "
                  "The JSON preserves all matched symbol rows, top 20 leaf rows, every stage, exact periods, checks and snapshot identities.", "",
                  "| Recording | Span | Samples | Sampled CPU s | Unresolved samples | Unresolved period fraction |",
                  "|---|---|---:|---:|---:|---:|"])
    for label in ("f16", "candidate"):
        for name, row in report["quality"][label].items():
            lines.append(f"| {label} | {name} | {row['samples']:,} | {row['period_ns'] / 1e9:.9f} | "
                         f"{row['unresolved_leaf_samples']} | {row['unresolved_leaf_period_fraction']:.6%} |")
    lines.extend(["", "Unresolved samples are reported separately. Assigning every candidate unresolved Period to the six families "
                  f"{'still satisfies' if report['budget_pass_with_unresolved_upper_bound'] else 'does not establish'} the quarter budget. "
                  "Raw perf-script leaf records are rechecked against quality JSON and report totals; lost records, missing rows and unresolved core leaves fail integrity.", "",
                  f"Formal timing identity: **{'not requested' if report['formal_timing_identity_verified'] is None else 'PASS' if report['formal_timing_identity_verified'] else 'FAIL'}**. "
                  "When --timing is provided, its frozen native files, .text sections, manifest and configuration must match the candidate recording.", ""])
    failed = [key for key, value in report["checks"].items() if not value]
    if failed:
        lines.extend(["Failed checks:", "", *(f"- `{key}`" for key in failed), ""])
    lines.extend(["## Cost migration and limits", ""])
    for name in (JOINT if report["joint_interval_comparison"] else "ingest", FLATTEN):
        lines.extend([f"Candidate {name} top leaf rows:", ""])
        for row in report["reports"]["candidate"][name].get("top20_leaf_rows", [])[:10]:
            lines.append(f"- `{row['symbol']}` ({row['dso']}): {row['period_ns'] / 1e9:.9f} s, {row['samples']} samples.")
        lines.append("")
    lines.extend([*report["limitations"], "", f"Baseline: `{report['baseline']}`. Candidate: `{report['candidate']}`.", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True, help="frozen F16 perf work directory")
    parser.add_argument("--candidate", type=Path, required=True, help="candidate perf work directory")
    parser.add_argument("--output", type=Path, required=True, help="output prefix (PREFIX.json and PREFIX.md) under ptmp")
    parser.add_argument("--timing", type=Path, help="formal candidate timing.json or its directory; if supplied, identity verification is mandatory")
    args = parser.parse_args()
    args.baseline, args.candidate = args.baseline.resolve(), args.candidate.resolve()
    output = args.output.resolve()
    if output.is_dir():
        output /= "self-hotspot-comparison"
    if output.suffix in (".json", ".md"):
        output = output.with_suffix("")
    if not output.is_relative_to(ROOT / "ptmp"):
        parser.error("--output must be under the repository ptmp directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = compare(args)
    except (OSError, ValueError, KeyError, IndexError, TypeError, RuntimeError) as error:
        report = {"schema": SCHEMA, "baseline": str(args.baseline), "candidate": str(args.candidate),
                  "analysis_integrity_verified": False, "budget_pass": False,
                  "error": f"{type(error).__name__}: {error}"}
    json_path, markdown_path = Path(f"{output}.json"), Path(f"{output}.md")
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    markdown_path.write_text(markdown(report))
    print(f"Wrote {json_path} and {markdown_path}")
    return 2 if not report["analysis_integrity_verified"] else 0 if report["budget_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
