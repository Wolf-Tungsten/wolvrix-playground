#!/usr/bin/env python3
"""Run and compare frozen GrhSIM execution-plan probes before C++ emission.

The probe is supplied explicitly: its CLI is INPUT OUTPUT CLOCK and its CSV
schema is the research execution-plan/work-feature schema. Counts describe
structure, not nanoseconds; a valid comparison is not a performance prediction.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time


PREFIXES = ("WOLVRIX_", "GRHSIM_", "WOLVI_", "XS_REPCUT_", "EMU_", "REPCUT_")
TABLES = ("summary", "groups", "batch_groups", "input_masks", "work_inventory",
          "compute_lowering", "commit_bodies", "work_conditional", "backend_cost",
          "mechanism_cost")


def identity(path: Path) -> dict:
    path = path.resolve(strict=True)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def check_identity(record: dict) -> dict:
    actual = identity(Path(record["path"]))
    if actual["sha256"] != record["sha256"]:
        raise ValueError(f"input changed: {actual['path']}")
    return actual


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def canonical_part(name: str) -> str:
    return name[1:-6] if name.startswith("G") and name.endswith("_model") else name


def rows(folder: Path, name: str) -> list[dict]:
    with (folder / (name + ".csv")).open(newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or "part" not in reader.fieldnames:
            raise ValueError(f"missing CSV header: {name}")
        return list(reader)


def validate(folder: Path) -> dict:
    tables = {name: rows(folder, name) for name in TABLES}
    summaries: dict[str, dict[str, int]] = {}
    for row in tables["summary"]:
        if row["precision"] != "range":
            continue
        part = canonical_part(row["part"])
        features = summaries.setdefault(part, {})
        if row["feature"] in features:
            raise ValueError(f"duplicate summary feature: {part}/{row['feature']}")
        features[row["feature"]] = int(row["value"])
    if not summaries:
        raise ValueError("no range summaries")
    # An assignment replay may leave a genuinely empty partition.  The probe
    # emits a compact zero summary for it and omits empty group/mask/conditional
    # rows.  Normalize the dimensions used by the integrity checks here; an
    # empty lane must not be mistaken for truncated output from a nonempty one.
    for features in summaries.values():
        features.setdefault("groups", 0)
        features.setdefault("compute_groups", 0)
        features.setdefault("input_mask_words", 0)
        features.setdefault("batches", 0)
    parts = set(summaries)
    for name in ("groups", "work_inventory", "work_conditional"):
        found = {canonical_part(row["part"]) for row in tables[name]}
        nonempty = {part for part, features in summaries.items()
                    if features.get("groups", 0) or features.get("graph_ops", 0)}
        if not nonempty.issubset(found):
            raise ValueError(f"incomplete partition coverage: {name}")
    expected_masks = sum(f["input_mask_words"] for f in summaries.values())
    if len(tables["input_masks"]) != expected_masks:
        raise ValueError("input-mask rows disagree with execution-plan summaries")
    inventory: dict[str, dict[str, int]] = {part: {} for part in parts}
    for row in tables["work_inventory"]:
        part = canonical_part(row["part"])
        if row["feature"] in inventory[part]:
            raise ValueError(f"duplicate work feature: {part}/{row['feature']}")
        inventory[part][row["feature"]] = int(row["value"])
    lowering_parts = {canonical_part(row["part"]) for row in tables["compute_lowering"]}
    for part, features in summaries.items():
        if features["compute_groups"] and part not in lowering_parts:
            raise ValueError(f"missing compute lowering: {part}")
        if inventory[part].get("compute.groups", 0) != features["compute_groups"]:
            raise ValueError(f"compute group coverage mismatch: {part}")
    if not tables["mechanism_cost"] or not tables["backend_cost"]:
        raise ValueError("missing conditional backend costs")
    conditional: dict[str, dict[str, int]] = {part: {} for part in parts}
    for row in tables["mechanism_cost"]:
        if row["precision"] != "range":
            continue
        part = canonical_part(row["part"])
        mask, value = int(row["mask"]), int(row["value"])
        for phase, included in (("rise", mask & 1), ("fall", mask & 2),
                                ("other_context", mask & ~3), ("unreachable", mask == 0)):
            if included:
                name = phase + "." + row["unit"] + "." + row["feature"]
                conditional[part][name] = conditional[part].get(name, 0) + value
    # Reconstruct groups/batches independently, catching truncated CSVs even
    # when the probe's exit status or final log message looks successful.
    for part, features in summaries.items():
        groups = [r for r in tables["groups"] if canonical_part(r["part"]) == part]
        batches = {r["batch"] for r in tables["batch_groups"] if canonical_part(r["part"]) == part}
        if not features.get("groups", 0) and not features.get("graph_ops", 0):
            continue
        if len(groups) != features.get("groups", 0) or len(batches) != features.get("batches", 0):
            raise ValueError(f"incomplete group/batch membership: {part}")
        if len({r["group"] for r in groups}) != len(groups):
            raise ValueError(f"duplicate group: {part}")
        masks = sum(canonical_part(r["part"]) == part for r in tables["input_masks"])
        if masks != features["input_mask_words"]:
            raise ValueError(f"input-mask coverage mismatch: {part}")
    return {"parts": sorted(parts), "row_counts": {k: len(v) for k, v in tables.items()},
            "summary": summaries, "inventory": inventory, "conditional": conditional}


def analyze(args) -> None:
    emission = json.loads(args.emit_record.read_text())
    if emission["status"] != "pass" or not emission["options"]:
        raise ValueError("expected a successful emission record with explicit options")
    source = identity(args.partitioned) if args.partitioned else check_identity(emission["input"])
    library = check_identity(emission["library"])
    probe = identity(args.probe)
    # A new directory prevents accidentally accepting stale, partially written
    # tables from a previous invocation.
    args.output.mkdir(parents=True, exist_ok=False)
    env = {k: v for k, v in os.environ.items() if not k.startswith(PREFIXES)}
    env.update(emission["options"])
    env.update(LD_LIBRARY_PATH=str(Path(library["path"]).parent),
               WORK_FEATURES_OUT=str(args.output.resolve()))
    record = {"schema": "grhsim-plan-gate-v1", "status": "running", "input": source,
              "library": library, "probe": probe, "options": emission["options"],
              "clock": args.clock, "emission_record": identity(args.emit_record)}
    save(args.output / "identity.json", record)
    start = time.monotonic()
    command = [probe["path"], source["path"], str(args.output.resolve()), args.clock]
    try:
        with (args.output / "analysis.log").open("w") as log:
            with subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT) as process:
                loaded = set()
                # Observe the actual mapping, not just the requested search path.
                while process.poll() is None:
                    try:
                        maps = Path(f"/proc/{process.pid}/maps").read_text()
                        loaded = {line.rsplit(None, 1)[-1] for line in maps.splitlines()
                                  if line.endswith("/libwolvrix-lib.so")}
                    except FileNotFoundError:
                        pass
                    if loaded:
                        break
                    time.sleep(0.05)
                if loaded != {library["path"]}:
                    process.terminate()
                    process.wait()
                    raise ValueError(f"probe library mismatch: {loaded}")
                if process.wait() != 0:
                    raise ValueError("probe failed; inspect analysis.log")
        verified = validate(args.output)
        for item in (source, library, probe):
            check_identity(item)
        record.update(status="pass", elapsed_s=time.monotonic() - start,
                      parts=verified["parts"], row_counts=verified["row_counts"],
                      files={name: identity(args.output / (name + ".csv")) for name in TABLES})
    except Exception:
        record.update(status="failed", elapsed_s=time.monotonic() - start)
        save(args.output / "identity.json", record)
        raise
    save(args.output / "identity.json", record)
    print(json.dumps({"status": "pass", "output": str(args.output), "elapsed_s": record["elapsed_s"],
                      "parts": len(record["parts"])}), flush=True)


def load_verified(folder: Path) -> tuple[dict, dict]:
    record = json.loads((folder / "identity.json").read_text())
    if record.get("schema") != "grhsim-plan-gate-v1" or record["status"] != "pass":
        raise ValueError(f"unverified analysis: {folder}")
    if set(record["files"]) != set(TABLES):
        raise ValueError(f"incomplete analysis manifest: {folder}")
    for name, item in record["files"].items():
        if identity(folder / (name + ".csv"))["sha256"] != item["sha256"]:
            raise ValueError(f"analysis table changed: {name}")
    data = validate(folder)
    if data["parts"] != record["parts"]:
        raise ValueError("partition set changed")
    return record, data


def delta(a: int, b: int) -> dict:
    return {"baseline": a, "candidate": b, "delta": b - a,
            "percent": 100.0 * (b - a) / a if a else None}


def evaluate_budget(report: dict, rules: list[dict]) -> dict:
    """Apply caller-supplied structural budgets without fitting a time model."""
    if not rules:
        raise ValueError("a budget must contain at least one rule")
    checks = []
    for rule in rules:
        feature, scope = rule["feature"], rule["scope"]
        limit = float(rule["max_change_percent"])
        if not math.isfinite(limit) or limit < -100:
            raise ValueError("invalid structural budget limit")
        if scope in ("peak", "sum"):
            value = report["global"][feature][scope]
        elif scope == "part":
            value = report["parts"][rule["part"]][feature]
        else:
            raise ValueError(f"unknown budget scope: {scope}")
        # A zero baseline cannot absorb nonzero work under a relative budget.
        allowed = value["baseline"] * (1.0 + limit / 100.0)
        checks.append(dict(rule=rule, observed=value, within_budget=value["candidate"] <= allowed))
    return {"within_budget": all(check["within_budget"] for check in checks), "checks": checks,
            "scope": "explicit structural limits only; not a walltime acceptance test"}


def pareto_front(vectors: dict[str, list[int]]) -> dict[str, list[str]]:
    """Return each candidate's dominators; lower is preferable in every dimension."""
    if not vectors or len({len(v) for v in vectors.values()}) != 1 or not next(iter(vectors.values())):
        raise ValueError("expected nonempty, equally sized objective vectors")
    return {name: [other for other, ov in vectors.items() if other != name
                   and all(a <= b for a, b in zip(ov, vector))
                   and any(a < b for a, b in zip(ov, vector))]
            for name, vector in vectors.items()}


def rank(args) -> None:
    reports = {str(p.resolve()): json.loads(p.read_text()) for p in args.comparison}
    if not reports or any(r["status"] != "valid" for r in reports.values()):
        raise ValueError("expected valid comparisons")
    if len({r["baseline"]["sha256"] for r in reports.values()}) != 1:
        raise ValueError("candidate ranking requires exactly the same baseline analysis")
    metrics = [metric.rsplit(":", 1) for metric in args.metric]
    if any(aggregate not in ("peak", "sum") for _, aggregate in metrics):
        raise ValueError("rank metrics must be FEATURE:peak or FEATURE:sum")
    eligible = {name: report for name, report in reports.items()
                if report.get("budget", {}).get("within_budget", True)}
    vectors = {name: [r["global"][feature][aggregate]["candidate"] for feature, aggregate in metrics]
               for name, r in eligible.items()}
    dominators = pareto_front(vectors) if vectors else {}
    result = {"status": "pass", "scope": "structural Pareto screen; no fitted time coefficients",
              "metrics": args.metric, "vectors": vectors, "dominated_by": dominators,
              "front": [name for name, others in dominators.items() if not others],
              "outside_budget": sorted(set(reports) - set(eligible)),
              "comparisons": [identity(path) for path in args.comparison]}
    save(args.output, result)
    print(json.dumps({"status": "pass", "front": result["front"], "output": str(args.output)}))


def compare(args) -> None:
    left, a = load_verified(args.baseline)
    right, b = load_verified(args.candidate)
    for field in ("options", "clock", "parts"):
        if left[field] != right[field]:
            raise ValueError(f"incomparable analyses: different {field}")
    for field in ("library", "probe"):
        if left[field]["sha256"] != right[field]["sha256"]:
            raise ValueError(f"incomparable analyses: different {field}")
    result = {"schema": "grhsim-plan-comparison-v1", "status": "valid",
              "scope": "structural risk report; no time prediction or performance acceptance",
              "baseline": identity(args.baseline / "identity.json"),
              "candidate": identity(args.candidate / "identity.json"), "parts": {}, "global": {}}
    for family in ("summary", "inventory", "conditional"):
        features = set().union(*(set(v) for v in a[family].values()), *(set(v) for v in b[family].values()))
        for feature in sorted(features):
            name = family + "." + feature
            av = {p: a[family][p].get(feature, 0) for p in a["parts"]}
            bv = {p: b[family][p].get(feature, 0) for p in b["parts"]}
            result["global"][name] = {"peak": delta(max(av.values()), max(bv.values())),
                                      "sum": delta(sum(av.values()), sum(bv.values()))}
            for part in a["parts"]:
                result["parts"].setdefault(part, {})[name] = delta(av[part], bv[part])
    if getattr(args, "budget", None):
        result["budget"] = evaluate_budget(result, json.loads(args.budget.read_text())["rules"])
        result["budget_identity"] = identity(args.budget)
    if getattr(args, "phase_risk", False):
        from repcut_grhsim_phase_risk import compare_plans
        result["phase_risk"] = compare_plans(
            args.baseline, args.candidate,
            getattr(args, "source_part", None), getattr(args, "destination_part", None))
        result["phase_risk"]["rule"]["comparison_identity_checked"] = True
    save(args.output, result)
    print(json.dumps({"status": "valid", "output": str(args.output)}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    run = actions.add_parser("analyze")
    run.add_argument("--emit-record", type=Path, required=True)
    run.add_argument("--partitioned", type=Path,
                     help="Analyze a new assignment using the reference emission's frozen backend configuration")
    run.add_argument("--probe", type=Path, required=True)
    run.add_argument("--clock", required=True)
    run.add_argument("--output", type=Path, required=True)
    diff = actions.add_parser("compare")
    diff.add_argument("--baseline", type=Path, required=True)
    diff.add_argument("--candidate", type=Path, required=True)
    diff.add_argument("--output", type=Path, required=True)
    diff.add_argument("--budget", type=Path,
                      help="JSON rules with scope=peak|sum|part, feature, max_change_percent, and optional part")
    diff.add_argument("--phase-risk", action="store_true",
                      help="attach separate rise/fall and whole/range work ledgers; diagnostic only")
    diff.add_argument("--source-part", type=int, help="optional phase-risk focus")
    diff.add_argument("--destination-part", type=int, help="optional phase-risk focus")
    ranking = actions.add_parser("rank")
    ranking.add_argument("--comparison", type=Path, action="append", required=True)
    ranking.add_argument("--metric", action="append", required=True, help="FEATURE:peak or FEATURE:sum")
    ranking.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "compare":
        if (args.source_part is None) != (args.destination_part is None):
            parser.error("--source-part and --destination-part must be supplied together")
        if args.source_part is not None and not args.phase_risk:
            parser.error("phase-risk focus requires --phase-risk")
    {"analyze": analyze, "compare": compare, "rank": rank}[args.action](args)


if __name__ == "__main__":
    main()
