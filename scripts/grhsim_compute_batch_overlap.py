#!/usr/bin/env python3

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import TextIO


COMPUTE_BATCH_RE = re.compile(rb"eval_compute_batch_(\d+)\s*\(")
OP_ID_RE = re.compile(rb"// op _op_(\d+) \[")


def compute_batch_files(source_dir: Path) -> list[tuple[int, Path]]:
    batches: dict[int, Path] = {}
    for path in source_dir.glob("*_sched_*.cpp"):
        data = path.read_bytes()
        match = COMPUTE_BATCH_RE.search(data)
        if match is None:
            continue
        batch = int(match.group(1))
        if batch in batches:
            raise ValueError(f"duplicate compute batch {batch}: {batches[batch]} and {path}")
        batches[batch] = path
    if not batches:
        raise ValueError(f"no compute batch sources found under {source_dir}")
    expected = set(range(max(batches) + 1))
    missing = sorted(expected - batches.keys())
    if missing:
        raise ValueError(f"missing compute batches under {source_dir}: {missing}")
    return sorted(batches.items())


def op_assignments(source_dir: Path) -> tuple[dict[int, int], list[int], int]:
    assignments: dict[int, int] = {}
    ambiguous: set[int] = set()
    batch_sizes: list[int] = []
    for batch, path in compute_batch_files(source_dir):
        op_ids = {int(match.group(1)) for match in OP_ID_RE.finditer(path.read_bytes())}
        batch_sizes.append(len(op_ids))
        for op_id in op_ids:
            prior = assignments.get(op_id)
            if prior is None:
                assignments[op_id] = batch
            elif prior != batch:
                ambiguous.add(op_id)
    for op_id in ambiguous:
        assignments.pop(op_id, None)
    return assignments, batch_sizes, len(ambiguous)


def weighted_quantile(values: list[tuple[float, int]], quantile: float) -> float:
    total = sum(weight for _, weight in values)
    if total == 0:
        return 0.0
    threshold = quantile * total
    cumulative = 0
    for value, weight in sorted(values):
        cumulative += weight
        if cumulative >= threshold:
            return value
    return max(value for value, _ in values)


def choose_two(value: int) -> int:
    return value * (value - 1) // 2


def percent(numerator: int | float, denominator: int | float) -> float:
    return 100.0 * numerator / denominator if denominator else 0.0


def load_profile_variant(path: Path, name: str, expected_batches: int) -> tuple[dict, dict[int, dict]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    matches = [variant for variant in payload.get("variants", []) if variant.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"{path}: expected one profile variant named {name!r}, found {len(matches)}")
    variant = matches[0]
    rows: dict[int, dict] = {}
    for row in variant.get("batches", []):
        if row.get("phase") != "compute":
            continue
        batch_id = row.get("batch_id")
        if not isinstance(batch_id, int) or batch_id < 0:
            raise ValueError(f"{path}: invalid compute batch id: {batch_id!r}")
        if batch_id in rows:
            raise ValueError(f"{path}: duplicate compute batch profile: {batch_id}")
        for field in ("samples", "work_total", "samples_per_billion_work"):
            value = row.get(field)
            if not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"{path}: invalid {field} for compute batch {batch_id}: {value!r}")
        rows[batch_id] = row
    expected = set(range(expected_batches))
    if set(rows) != expected:
        raise ValueError(
            f"{path}: compute batch profile mismatch for {name!r}: "
            f"missing={sorted(expected - set(rows))[:10]} extra={sorted(set(rows) - expected)[:10]}"
        )
    phase = variant.get("phases", {}).get("compute", {})
    global_density = phase.get("samples_per_billion_work")
    if not isinstance(global_density, (int, float)) or global_density <= 0:
        raise ValueError(f"{path}: invalid compute phase sample density for {name!r}")
    return variant, rows


def write_profile_origin_report(
    profile_path: Path,
    old_name: str,
    new_name: str,
    old_count: int,
    new_count: int,
    new_sizes: list[int],
    overlap: list[list[int]],
    new_common: list[int],
    min_samples: int,
    out: TextIO,
) -> None:
    old_variant, old_rows = load_profile_variant(profile_path, old_name, old_count)
    new_variant, new_rows = load_profile_variant(profile_path, new_name, new_count)
    old_global = old_variant["phases"]["compute"]["samples_per_billion_work"]
    new_global = new_variant["phases"]["compute"]["samples_per_billion_work"]
    global_ratio = new_global / old_global

    rows = []
    for new_batch, counts in enumerate(overlap):
        common = new_common[new_batch]
        if common == 0:
            continue
        origin_density = sum(
            count * old_rows[old_batch]["samples_per_billion_work"]
            for old_batch, count in enumerate(counts)
        ) / common
        new_row = new_rows[new_batch]
        new_density = new_row["samples_per_billion_work"]
        density_ratio = new_density / origin_density if origin_density else 0.0
        expected_samples = origin_density * new_row["work_total"] / 1_000_000_000.0
        rows.append(
            {
                "batch": new_batch,
                "samples": new_row["samples"],
                "work_total": new_row["work_total"],
                "new_density": new_density,
                "common_share": percent(common, new_sizes[new_batch]),
                "origin_density": origin_density,
                "density_ratio": density_ratio,
                "relative_to_global": density_ratio / global_ratio,
                "expected_samples": expected_samples,
                "excess_samples": new_row["samples"] - expected_samples,
            }
        )

    print(
        f"profile_origin_density profile={profile_path} old={old_name} new={new_name} "
        f"min_samples={min_samples} old_global={old_global:.6f} "
        f"new_global={new_global:.6f} global_ratio={global_ratio:.6f}",
        file=out,
    )

    def print_rows(title: str, ranked: list[dict]) -> None:
        print(title, file=out)
        print(
            "rank new_batch samples work_total new_density common_share "
            "op_weighted_origin_density density_ratio relative_to_global "
            "expected_samples excess_samples",
            file=out,
        )
        for rank, row in enumerate(ranked, start=1):
            print(
                f"{rank} {row['batch']:02d} {row['samples']} {row['work_total']} "
                f"{row['new_density']:.6f} {row['common_share']:.3f}% "
                f"{row['origin_density']:.6f} {row['density_ratio']:.6f} "
                f"{row['relative_to_global']:.6f} {row['expected_samples']:.3f} "
                f"{row['excess_samples']:+.3f}",
                file=out,
            )

    eligible = [row for row in rows if row["samples"] >= min_samples]
    print_rows(
        "top_profile_density_ratio",
        sorted(eligible, key=lambda row: (-row["density_ratio"], -row["samples"], row["batch"]))[:15],
    )
    print_rows(
        "top_profile_excess_samples",
        sorted(eligible, key=lambda row: (-row["excess_samples"], -row["samples"], row["batch"]))[:15],
    )


def write_report(
    old_dir: Path,
    new_dir: Path,
    out: TextIO,
    profile_path: Path | None = None,
    old_profile_name: str | None = None,
    new_profile_name: str | None = None,
    min_profile_samples: int = 100,
) -> None:
    old_assignment, old_sizes, old_ambiguous = op_assignments(old_dir)
    new_assignment, new_sizes, new_ambiguous = op_assignments(new_dir)
    old_count = len(old_sizes)
    new_count = len(new_sizes)

    overlap = [[0 for _ in range(old_count)] for _ in range(new_count)]
    for op_id, new_batch in new_assignment.items():
        old_batch = old_assignment.get(op_id)
        if old_batch is not None:
            overlap[new_batch][old_batch] += 1

    common = sum(sum(row) for row in overlap)
    old_common = [sum(overlap[new_batch][old_batch] for new_batch in range(new_count))
                  for old_batch in range(old_count)]
    new_common = [sum(row) for row in overlap]
    dominant_old = sum(max(row, default=0) for row in overlap)
    dominant_new = sum(
        max((overlap[new_batch][old_batch] for new_batch in range(new_count)), default=0)
        for old_batch in range(old_count)
    )

    displacement: list[tuple[float, int]] = []
    sum_x = 0.0
    sum_y = 0.0
    sum_xx = 0.0
    sum_yy = 0.0
    sum_xy = 0.0
    same_index = 0
    nearby_one = 0
    nearby_two = 0
    old_scale = max(old_count - 1, 1)
    new_scale = max(new_count - 1, 1)
    one_batch_distance = 1.0 / max(old_scale, new_scale)
    for new_batch, row in enumerate(overlap):
        y = new_batch / new_scale
        for old_batch, count in enumerate(row):
            if count == 0:
                continue
            x = old_batch / old_scale
            distance = abs(x - y)
            displacement.append((distance, count))
            sum_x += x * count
            sum_y += y * count
            sum_xx += x * x * count
            sum_yy += y * y * count
            sum_xy += x * y * count
            same_index += count if old_batch == new_batch else 0
            nearby_one += count if distance <= one_batch_distance else 0
            nearby_two += count if distance <= 2.0 * one_batch_distance else 0

    covariance = sum_xy - sum_x * sum_y / common if common else 0.0
    variance_x = sum_xx - sum_x * sum_x / common if common else 0.0
    variance_y = sum_yy - sum_y * sum_y / common if common else 0.0
    correlation = covariance / math.sqrt(variance_x * variance_y) if variance_x > 0 and variance_y > 0 else 0.0
    mean_displacement = (
        sum(value * weight for value, weight in displacement) / common if common else 0.0
    )

    old_pair_total = sum(choose_two(count) for count in old_common)
    new_pair_total = sum(choose_two(count) for count in new_common)
    colocated_pairs = sum(choose_two(count) for row in overlap for count in row)

    print(f"old_dir={old_dir}", file=out)
    print(f"new_dir={new_dir}", file=out)
    print(
        f"old_compute_batches={old_count} old_unique_ops={len(old_assignment)} "
        f"old_ambiguous_cross_batch_ops={old_ambiguous}",
        file=out,
    )
    print(
        f"new_compute_batches={new_count} new_unique_ops={len(new_assignment)} "
        f"new_ambiguous_cross_batch_ops={new_ambiguous}",
        file=out,
    )
    print(
        f"common_ops={common} old_coverage={percent(common, len(old_assignment)):.3f}% "
        f"new_coverage={percent(common, len(new_assignment)):.3f}%",
        file=out,
    )
    print(
        "aggregate "
        f"new_dominant_old_share={percent(dominant_old, common):.3f}% "
        f"old_dominant_new_share={percent(dominant_new, common):.3f}% "
        f"same_index_share={percent(same_index, common):.3f}% "
        f"batch_position_correlation={correlation:.6f}",
        file=out,
    )
    print(
        "displacement "
        f"mean={mean_displacement:.6f} "
        f"p50={weighted_quantile(displacement, 0.50):.6f} "
        f"p90={weighted_quantile(displacement, 0.90):.6f} "
        f"within_one_batch={percent(nearby_one, common):.3f}% "
        f"within_two_batches={percent(nearby_two, common):.3f}%",
        file=out,
    )
    print(
        "pair_locality "
        f"old_pairs_colocated={percent(colocated_pairs, old_pair_total):.3f}% "
        f"new_pairs_same_origin={percent(colocated_pairs, new_pair_total):.3f}%",
        file=out,
    )
    print("new_batch total_ops common_ops top_old_batch:count/share_total/share_common ...", file=out)
    for new_batch, row in enumerate(overlap):
        top = Counter({old_batch: count for old_batch, count in enumerate(row) if count}).most_common(5)
        entries = " ".join(
            f"{old_batch}:{count}/{percent(count, new_sizes[new_batch]):.2f}%/"
            f"{percent(count, new_common[new_batch]):.2f}%"
            for old_batch, count in top
        )
        print(
            f"{new_batch:02d} {new_sizes[new_batch]:7d} {new_common[new_batch]:7d} {entries}",
            file=out,
        )
    if profile_path is not None:
        assert old_profile_name is not None
        assert new_profile_name is not None
        write_profile_origin_report(
            profile_path,
            old_profile_name,
            new_profile_name,
            old_count,
            new_count,
            new_sizes,
            overlap,
            new_common,
            min_profile_samples,
            out,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare stable operation placement across two generated GrhSIM compute layouts."
    )
    parser.add_argument("old_dir", type=Path, help="old GrhSIM generated C++ directory")
    parser.add_argument("new_dir", type=Path, help="new GrhSIM generated C++ directory")
    parser.add_argument("--output", type=Path, help="write the report to this path instead of stdout")
    parser.add_argument(
        "--batch-profile-json",
        type=Path,
        help="optionally add op-weighted old-origin sample-density analysis",
    )
    parser.add_argument("--old-profile-name", help="baseline variant name in --batch-profile-json")
    parser.add_argument("--new-profile-name", help="candidate variant name in --batch-profile-json")
    parser.add_argument(
        "--min-profile-samples",
        type=int,
        default=100,
        help="minimum candidate samples for profile-origin rankings",
    )
    args = parser.parse_args()
    profile_names = (args.old_profile_name, args.new_profile_name)
    if args.batch_profile_json is None and any(name is not None for name in profile_names):
        parser.error("profile names require --batch-profile-json")
    if args.batch_profile_json is not None and any(name is None for name in profile_names):
        parser.error("--batch-profile-json requires --old-profile-name and --new-profile-name")
    if args.min_profile_samples < 0:
        parser.error("--min-profile-samples must be non-negative")

    if args.output is None:
        import sys

        write_report(
            args.old_dir,
            args.new_dir,
            sys.stdout,
            args.batch_profile_json,
            args.old_profile_name,
            args.new_profile_name,
            args.min_profile_samples,
        )
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as out:
            write_report(
                args.old_dir,
                args.new_dir,
                out,
                args.batch_profile_json,
                args.old_profile_name,
                args.new_profile_name,
                args.min_profile_samples,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
