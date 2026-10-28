#!/usr/bin/env python3
"""Extract backend-generated code shape per GrhSIM partition.

This is a pre-runtime diagnostic for partition experiments.  It reads the
package Makefile rather than a hand-written list of partitions, groups the
generated sources and object files by their ``Gpart_<n>`` owner, and reports
the code/layout envelope that a proposed assignment creates.  The result is
an input to candidate review; it does not alter the partition assignment or
pretend that source bytes are execution time.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable


PART_RE = re.compile(r"(?:^|_)Gpart_(\d+)(?:_|\.|$)")


def _part_of(name: str) -> int | None:
    match = PART_RE.search(name)
    return int(match.group(1)) if match else None


def _category(name: str) -> str:
    if "_model_eval" in name:
        return "eval"
    if "_model_state_init_" in name:
        return "state_init"
    if "_model_state" in name:
        return "state"
    if "_model_sched_" in name:
        return "sched"
    if re.search(r"(?:^|/)Gpart_\d+\.cpp$", name):
        return "part"
    return "other"


def _empty() -> dict[str, int]:
    result = {"files": 0, "bytes": 0}
    for category in ("eval", "state", "state_init", "sched", "part", "other"):
        result[f"{category}_files"] = 0
        result[f"{category}_bytes"] = 0
    return result


def _add(row: dict[str, int], category: str, size: int) -> None:
    row["files"] += 1
    row["bytes"] += size
    row[f"{category}_files"] += 1
    row[f"{category}_bytes"] += size


def _make_sources(package: Path) -> list[str]:
    makefile = package / "Makefile"
    if not makefile.is_file():
        raise ValueError(f"missing package Makefile: {makefile}")
    text = makefile.read_text()
    match = re.search(r"^SRCS\s*:=\s*(.*?)\n(?:OBJS|$)", text, re.MULTILINE | re.DOTALL)
    if not match:
        raise ValueError(f"cannot find SRCS in {makefile}")
    # The generated Makefile currently emits one very long line.  Supporting
    # continuation lines costs little and keeps this useful for future packs.
    source_text = match.group(1).replace("\\\n", " ")
    sources = source_text.split()
    if not sources:
        raise ValueError(f"empty SRCS in {makefile}")
    return sources


def _measure_files(
    package: Path,
    sources: Iterable[str],
    suffix: str,
    *,
    allow_missing: bool = False,
) -> tuple[dict[str, dict[str, int]], dict[str, int], int]:
    parts: dict[str, dict[str, int]] = defaultdict(_empty)
    totals = _empty()
    missing: list[str] = []
    for source in sources:
        path = package / source
        if suffix and path.suffix != suffix:
            continue
        if not path.is_file():
            missing.append(source)
            continue
        size = path.stat().st_size
        category = _category(path.name)
        part = _part_of(path.name)
        key = str(part) if part is not None else "common"
        _add(parts[key], category, size)
        _add(totals, category, size)
    if missing and not allow_missing:
        raise ValueError(f"{package}: missing generated files (first 5): {missing[:5]}")
    return dict(parts), totals, len(missing)


def _measure_objects(package: Path, sources: Iterable[str]) -> tuple[dict[str, dict[str, int]], dict[str, int], int]:
    object_sources = [source[:-4] + ".o" for source in sources if source.endswith(".cpp")]
    return _measure_files(package, object_sources, ".o", allow_missing=True)


def inspect_package(label: str, package_arg: Path) -> dict:
    package = package_arg.resolve()
    sources = _make_sources(package)
    source_parts, source_total, missing_sources = _measure_files(package, sources, ".cpp")
    object_root = package
    if not any(package.glob("*.o")) and (package.parent / "objects").is_dir():
        # The harness build commonly moves temporary objects out of the
        # package after archiving; retain the same source names when available.
        object_root = package.parent / "objects"
    object_parts, object_total, missing_objects = _measure_objects(object_root, sources)
    part_keys = sorted(
        {key for key in source_parts | object_parts if key != "common"},
        key=int,
    )
    parts = {}
    for key in part_keys:
        source = source_parts.get(key, _empty())
        objects = object_parts.get(key, _empty())
        parts[key] = {
            "source": source,
            "objects": objects,
            "object_to_source_bytes": (
                objects["bytes"] / source["bytes"] if source["bytes"] else None
            ),
        }
    return {
        "label": label,
        "package": str(package),
        "objects_root": str(object_root),
        "source_count": len(sources),
        "source": source_total,
        "objects": object_total,
        "missing_source_files": missing_sources,
        "missing_object_files": missing_objects,
        "parts": parts,
        "common_source": source_parts.get("common", _empty()),
        "common_objects": object_parts.get("common", _empty()),
    }


def _parse_package(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("package must be LABEL=PATH")
    label, path = value.split("=", 1)
    if not label or not path:
        raise argparse.ArgumentTypeError("package must be LABEL=PATH")
    return label, Path(path)


def _normalize_plan_part(value: str) -> str:
    """Normalize plan CSV owner names without depending on a fixed prefix."""
    match = re.search(r"(?:^|_)part_(\d+)(?:_|$)", value)
    if match:
        return str(int(match.group(1)))
    try:
        return str(int(value))
    except ValueError as exc:
        raise ValueError(f"cannot extract numeric partition from plan owner {value!r}") from exc


def _plan_part(parts: dict[str, dict[str, int]], raw: str) -> dict[str, int]:
    return parts.setdefault(_normalize_plan_part(raw), {})


def _read_plan_shape(plan: Path) -> dict:
    """Extract scheduler-shape counters available before C++ source emission.

    ``groups.csv`` is produced by the GrhSIM planner from the graph and the
    activity schedule.  Its operation and estimated-line counts are therefore
    usable as a generator-side cost signal, unlike runtime timing or a
    partition-number-specific rule.  The parser intentionally tolerates the
    two owner spellings used by the planner (``inst_part_N`` and
    ``Ginst_part_N_model``).
    """
    plan = plan.resolve()
    groups_path = plan / "groups.csv"
    batches_path = plan / "batch_groups.csv"
    summary_path = plan / "summary.csv"
    for path in (groups_path, batches_path, summary_path):
        if not path.is_file():
            raise ValueError(f"missing plan shape file: {path}")

    parts: dict[str, dict[str, int]] = {}
    phase_batches: dict[str, set[tuple[str, int]]] = defaultdict(set)
    phase_group_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    with summary_path.open(newline="") as stream:
        for row in csv.DictReader(stream):
            item = _plan_part(parts, row["part"])
            try:
                value = int(row["value"])
            except ValueError:
                continue
            item[f"summary_{row['feature']}"] = value

    with groups_path.open(newline="") as stream:
        for row in csv.DictReader(stream):
            part = _plan_part(parts, row["part"])
            phase = row.get("phase", "unknown")
            try:
                operations = int(row["operations"])
                estimated_lines = int(row["estimated_lines"])
            except (KeyError, ValueError) as exc:
                raise ValueError(f"invalid groups.csv row in {groups_path}: {row}") from exc
            part["group_count"] = part.get("group_count", 0) + 1
            part["group_operations"] = part.get("group_operations", 0) + operations
            part["group_estimated_lines"] = part.get("group_estimated_lines", 0) + estimated_lines
            part["group_max_operations"] = max(part.get("group_max_operations", 0), operations)
            part["group_max_estimated_lines"] = max(
                part.get("group_max_estimated_lines", 0), estimated_lines
            )
            phase_group_counts[_normalize_plan_part(row["part"])][phase] += 1
            phase_key = f"{phase}_"
            part[f"{phase_key}group_count"] = part.get(f"{phase_key}group_count", 0) + 1
            part[f"{phase_key}operations"] = part.get(f"{phase_key}operations", 0) + operations
            part[f"{phase_key}estimated_lines"] = (
                part.get(f"{phase_key}estimated_lines", 0) + estimated_lines
            )
            part[f"{phase_key}max_operations"] = max(
                part.get(f"{phase_key}max_operations", 0), operations
            )
            part[f"{phase_key}max_estimated_lines"] = max(
                part.get(f"{phase_key}max_estimated_lines", 0), estimated_lines
            )
            if phase == "commit":
                for limit in (4096, 8192):
                    if operations > limit:
                        key = f"commit_groups_over_{limit}_ops"
                        part[key] = part.get(key, 0) + 1
                        lines_key = f"commit_estimated_lines_over_{limit}_ops"
                        part[lines_key] = part.get(lines_key, 0) + estimated_lines

    with batches_path.open(newline="") as stream:
        for row in csv.DictReader(stream):
            part = _plan_part(parts, row["part"])
            phase = row.get("phase", "unknown")
            batch = int(row["batch"])
            phase_batches[_normalize_plan_part(row["part"])].add((phase, batch))
            part["batch_group_rows"] = part.get("batch_group_rows", 0) + 1
            part[f"{phase}_batch_group_rows"] = part.get(f"{phase}_batch_group_rows", 0) + 1
            helper_chunks = int(row.get("helper_chunks", 0) or 0)
            part["helper_chunk_count"] = part.get("helper_chunk_count", 0) + helper_chunks
            part["max_helper_chunks"] = max(part.get("max_helper_chunks", 0), helper_chunks)

    for key, item in parts.items():
        item["batch_count"] = len(phase_batches[key])
        item["compute_batch_count"] = sum(phase == "compute" for phase, _ in phase_batches[key])
        item["commit_batch_count"] = sum(phase == "commit" for phase, _ in phase_batches[key])
        for limit in (4096, 8192):
            item.setdefault(f"commit_groups_over_{limit}_ops", 0)
            item.setdefault(f"commit_estimated_lines_over_{limit}_ops", 0)
        item["scheduler_estimated_lines"] = item.get("group_estimated_lines", 0)
        item["scheduler_commit_estimated_lines"] = item.get("commit_estimated_lines", 0)
        item["scheduler_compute_estimated_lines"] = item.get("compute_estimated_lines", 0)

    totals: dict[str, int] = defaultdict(int)
    for item in parts.values():
        for key, value in item.items():
            if key.startswith("summary_") or key.endswith("max_operations") or key.endswith("max_estimated_lines"):
                continue
            totals[key] += value
    return {
        "plan": str(plan),
        "parts": {key: parts[key] for key in sorted(parts, key=int)},
        "totals": dict(sorted(totals.items())),
    }


def _safe_ratio(after: int, before: int) -> tuple[float, str]:
    """Return a structural ratio and state whether its denominator was known."""
    if before > 0:
        return after / before, "measured"
    if after == 0:
        return 1.0, "zero"
    # A new shape dimension has no defensible source-byte coefficient.  Keep
    # the byte envelope conservative and expose the unknown explicitly instead
    # of inventing a constant or a timing probability.
    return 1.0, "new_dimension"


def _plan_source_shape_envelope(
    package: dict, baseline_plan: Path, candidate_plan: Path
) -> dict:
    """Project generated source categories from a pre-emission plan shape.

    The projection is deliberately an envelope, not a time model.  Each
    generated category is scaled only by the corresponding structural ledger:
    scheduler bytes by all estimated lines, eval bytes by compute lines,
    state bytes by state-logic bytes, and wrapper bytes by input/boundary
    targets plus event-edge storage.  Categories with no baseline denominator
    stay unchanged and are reported as unknown.  This lets a candidate gate
    reject an obvious shape expansion before C++ emission without pretending
    to know compiler layout, cache behavior, or active-cycle frequency.
    """
    baseline = _read_plan_shape(baseline_plan)
    candidate = _read_plan_shape(candidate_plan)
    baseline_parts = set(baseline["parts"])
    candidate_parts = set(candidate["parts"])
    package_parts = set(package["parts"])
    if baseline_parts != candidate_parts or baseline_parts != package_parts:
        raise ValueError("package and plan shapes must have the same partition set")

    def plan_value(item: dict[str, int], name: str) -> int:
        return int(item.get(name, item.get(f"summary_{name}", 0)))

    def wrapper_shape(item: dict[str, int]) -> int:
        return sum(
            plan_value(item, name)
            for name in (
                "input_targets",
                "boundary_targets",
                "event_edge_bytes",
                "producer_dirty_target_words",
            )
        )

    category_dimensions = {
        "sched_bytes": lambda item: plan_value(item, "group_estimated_lines"),
        "eval_bytes": lambda item: plan_value(item, "compute_estimated_lines"),
        "state_bytes": lambda item: plan_value(item, "state_logic_bytes"),
        "state_init_bytes": lambda item: plan_value(item, "state_logic_bytes"),
        "part_bytes": wrapper_shape,
    }
    predicted_parts: dict[str, dict] = {}
    predicted_totals = {category: 0 for category in ("bytes", "eval_bytes", "state_bytes", "state_init_bytes", "sched_bytes", "part_bytes", "other_bytes")}
    unknown_dimensions: list[dict[str, str]] = []
    for part in sorted(package_parts, key=int):
        source = package["parts"][part]["source"]
        before_shape = baseline["parts"][part]
        after_shape = candidate["parts"][part]
        projection = {"source": {}, "ratios": {}, "dimensions": {}}
        for category, dimension in category_dimensions.items():
            before = dimension(before_shape)
            after = dimension(after_shape)
            ratio, status = _safe_ratio(after, before)
            projection["ratios"][category] = ratio
            projection["dimensions"][category] = {
                "baseline": before,
                "candidate": after,
                "status": status,
            }
            if status == "new_dimension":
                unknown_dimensions.append({"part": part, "category": category})
            value = int(source.get(category, 0)) * ratio
            projection["source"][category] = value
            predicted_totals[category] += value

        other = int(source.get("other_bytes", 0))
        projection["source"]["other_bytes"] = other
        predicted_totals["other_bytes"] += other
        projection["source"]["bytes"] = sum(projection["source"].values())
        predicted_totals["bytes"] += projection["source"]["bytes"]

        for name in (
            "compute_max_estimated_lines",
            "commit_max_estimated_lines",
            "batch_count",
            "input_targets",
            "boundary_targets",
            "helper_chunk_count",
        ):
            before = plan_value(before_shape, name)
            after = plan_value(after_shape, name)
            ratio, status = _safe_ratio(after, before)
            projection["ratios"][name] = ratio
            projection["dimensions"][name] = {
                "baseline": before,
                "candidate": after,
                "status": status,
            }
        predicted_parts[part] = projection

    baseline_source_bytes = int(package["source"]["bytes"])
    predicted_source_bytes = int(predicted_totals["bytes"])
    predicted_eval = {
        part: values["source"]["eval_bytes"]
        for part, values in predicted_parts.items()
    }
    predicted_sched = {
        part: values["source"]["sched_bytes"]
        for part, values in predicted_parts.items()
    }
    return {
        "baseline_plan": str(baseline_plan.resolve()),
        "candidate_plan": str(candidate_plan.resolve()),
        "baseline_source_bytes": baseline_source_bytes,
        "predicted_source_bytes": predicted_source_bytes,
        "predicted_source_delta_bytes": predicted_source_bytes - baseline_source_bytes,
        "predicted_source_delta_percent": (
            (predicted_source_bytes / baseline_source_bytes - 1.0) * 100.0
            if baseline_source_bytes
            else 0.0
        ),
        "predicted_max_eval_part": max(predicted_eval, key=predicted_eval.get),
        "predicted_max_eval_bytes": predicted_eval[max(predicted_eval, key=predicted_eval.get)],
        "predicted_max_sched_part": max(predicted_sched, key=predicted_sched.get),
        "predicted_max_sched_bytes": predicted_sched[max(predicted_sched, key=predicted_sched.get)],
        "unknown_dimensions": unknown_dimensions,
        "parts": predicted_parts,
    }


def _attach_plan_shape(report: dict, plan_shapes: list[tuple[str, Path]]) -> None:
    if not plan_shapes:
        return
    labels = [label for label, _ in plan_shapes]
    if len(labels) != len(set(labels)):
        raise ValueError("plan shape labels must be unique")
    report["plan_shapes"] = {
        label: _read_plan_shape(path) for label, path in plan_shapes
    }


def _read_plan_parts(path: Path) -> dict[str, dict[str, int]]:
    """Read the exact replay ledger used before C++ emission.

    The ledger is intentionally limited to generic counters.  In particular,
    this projection does not treat a partition number or an RTL name as a
    special case.
    """
    rows = {}
    with path.open(newline="") as stream:
        for row in csv.DictReader(stream):
            part = str(int(row["part"]))
            if part in rows:
                raise ValueError(f"duplicate part {part} in {path}")
            rows[part] = {
                key: int(row[key])
                for key in (
                    "grhsim_v1_closure_work",
                    "grhsim_v1_recurring_work",
                    "raw_operation_count",
                    "state_write_count",
                    "piece_copies",
                    "send_calls",
                    "send_bytes",
                    "receive_calls",
                    "receive_bytes",
                )
            }
    if not rows:
        raise ValueError(f"empty plan ledger: {path}")
    return rows


def _project_source_shape(package: dict, baseline_plan: Path, candidate_plan: Path) -> dict:
    baseline = _read_plan_parts(baseline_plan)
    candidate = _read_plan_parts(candidate_plan)
    if set(baseline) != set(candidate) or set(baseline) != set(package["parts"]):
        raise ValueError("package and plan ledgers must have the same partition set")
    predicted_parts = {}
    predicted_total = _empty()
    for part in sorted(baseline, key=int):
        before = baseline[part]["raw_operation_count"]
        after = candidate[part]["raw_operation_count"]
        ratio = after / before if before else 1.0
        source = package["parts"][part]["source"]
        prediction = {
            "raw_operation_ratio": ratio,
            "source": {},
        }
        for category in ("bytes", "eval_bytes", "state_bytes", "state_init_bytes", "sched_bytes", "part_bytes", "other_bytes"):
            key = category if category in source else category.removesuffix("_bytes") + "_bytes"
            # The source ledger uses <category>_bytes except for total bytes.
            if category == "bytes":
                value = source["bytes"] * ratio
            else:
                value = source.get(key, 0) * ratio
            prediction["source"][category] = value
            predicted_total["bytes"] += value if category == "bytes" else 0
        prediction["raw_operation_count"] = {
            "baseline": before,
            "candidate": after,
            "delta": after - before,
        }
        predicted_parts[part] = prediction
    return {
        "baseline_plan": str(baseline_plan.resolve()),
        "candidate_plan": str(candidate_plan.resolve()),
        "predicted_source_bytes": predicted_total["bytes"],
        "baseline_source_bytes": package["source"]["bytes"],
        "predicted_source_delta_bytes": predicted_total["bytes"] - package["source"]["bytes"],
        "predicted_source_delta_percent": (
            (predicted_total["bytes"] / package["source"]["bytes"] - 1) * 100
            if package["source"]["bytes"] else 0.0
        ),
        "parts": predicted_parts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package",
        action="append",
        required=True,
        metavar="LABEL=PATH",
        help="generated GrhSIM package, repeat for baseline/candidates",
    )
    parser.add_argument(
        "--plan-baseline",
        type=Path,
        help="exact replay baseline parts.csv for optional pre-emission projection",
    )
    parser.add_argument(
        "--plan-candidate",
        action="append",
        metavar="LABEL=PATH",
        help="exact replay candidate parts.csv; repeat to project several candidates",
    )
    parser.add_argument(
        "--plan-shape",
        action="append",
        metavar="LABEL=PATH",
        help="planner directory containing groups.csv/batch_groups.csv/summary.csv",
    )
    parser.add_argument(
        "--plan-shape-baseline",
        type=Path,
        help="baseline planner directory for a pre-emission source-shape envelope",
    )
    parser.add_argument(
        "--plan-shape-candidate",
        action="append",
        metavar="LABEL=PATH",
        help="candidate planner directory for a pre-emission source-shape envelope; repeatable",
    )
    parser.add_argument("--output", type=Path, help="write JSON report here")
    args = parser.parse_args()
    packages = [_parse_package(value) for value in args.package]
    labels = [label for label, _ in packages]
    if len(labels) != len(set(labels)):
        parser.error("package labels must be unique")
    report = {
        "schema_version": 2,
        "status": "pass",
        "packages": [inspect_package(label, path) for label, path in packages],
    }
    if args.plan_shape:
        try:
            _attach_plan_shape(report, [_parse_package(value) for value in args.plan_shape])
        except ValueError as exc:
            parser.error(str(exc))
    if bool(args.plan_shape_baseline) != bool(args.plan_shape_candidate):
        parser.error("--plan-shape-baseline and --plan-shape-candidate must be supplied together")
    if args.plan_shape_baseline:
        try:
            report["plan_shape_envelopes"] = {
                label: _plan_source_shape_envelope(
                    report["packages"][0], args.plan_shape_baseline, path
                )
                for label, path in (_parse_package(value) for value in args.plan_shape_candidate)
            }
        except ValueError as exc:
            parser.error(str(exc))
    if bool(args.plan_baseline) != bool(args.plan_candidate):
        parser.error("--plan-baseline and --plan-candidate must be supplied together")
    if args.plan_baseline:
        reference = report["packages"][0]
        report["plan_projections"] = {
            label: _project_source_shape(reference, args.plan_baseline, path)
            for label, path in (_parse_package(value) for value in args.plan_candidate)
        }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
