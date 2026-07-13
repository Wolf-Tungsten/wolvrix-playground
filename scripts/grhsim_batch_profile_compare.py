#!/usr/bin/env python3

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import grhsim_runtime_profile_compare as runtime_profile


PHASES = runtime_profile.PHASES
BATCH_FUNCTION_RE = re.compile(rb"eval_(compute|commit)_batch_(\d+)\s*\(")
SUPERNODE_RE = re.compile(rb"// Supernode (\d+): run when its activity flag is set\.")
PERF_SYMBOL_RE = re.compile(
    r"^\s*[0-9]+(?:\.[0-9]+)?%\s+([0-9,]+)\s+([0-9,]+)\s+"
    r"\[[^]]+\]\s+GrhSIM_SimTop::eval_(compute|commit)_batch_(\d+)\(\)",
    re.MULTILINE,
)


@dataclass(frozen=True, order=True)
class BatchKey:
    phase: str
    batch_id: int


@dataclass(frozen=True)
class PerfSamples:
    samples: int
    period: int


def parse_nonnegative(value: str, path: Path, field: str) -> int:
    try:
        parsed = int(value.replace(",", ""))
    except ValueError as ex:
        raise ValueError(f"{path}: invalid {field}: {value!r}") from ex
    if parsed < 0:
        raise ValueError(f"{path}: negative {field}: {parsed}")
    return parsed


def read_generated_batches(source_dir: Path) -> dict[BatchKey, list[runtime_profile.SupernodeKey]]:
    batches: dict[BatchKey, list[runtime_profile.SupernodeKey]] = {}
    owners: dict[runtime_profile.SupernodeKey, BatchKey] = {}
    for path in sorted(source_dir.glob("*_sched_*.cpp")):
        data = path.read_bytes()
        functions = BATCH_FUNCTION_RE.findall(data)
        if not functions:
            continue
        if len(functions) != 1:
            raise ValueError(f"{path}: expected one batch function, found {len(functions)}")
        raw_phase, raw_batch = functions[0]
        phase = raw_phase.decode("ascii")
        key = BatchKey(phase=phase, batch_id=int(raw_batch))
        if key in batches:
            raise ValueError(f"{path}: duplicate generated batch: {key}")

        ids = [int(raw_id) for raw_id in SUPERNODE_RE.findall(data)]
        if not ids:
            raise ValueError(f"{path}: batch has no supernode markers: {key}")
        if len(ids) != len(set(ids)):
            raise ValueError(f"{path}: duplicate supernode marker in batch: {key}")

        supernodes = [
            runtime_profile.SupernodeKey(supernode_id=supernode_id, phase=phase)
            for supernode_id in ids
        ]
        for supernode in supernodes:
            prior = owners.get(supernode)
            if prior is not None:
                raise ValueError(
                    f"{path}: supernode {supernode} belongs to both {prior} and {key}"
                )
            owners[supernode] = key
        batches[key] = supernodes

    if not batches:
        raise ValueError(f"{source_dir}: no generated batch functions")
    phases = {key.phase for key in batches}
    if phases != set(PHASES):
        raise ValueError(f"{source_dir}: generated phases mismatch: {sorted(phases)}")
    return batches


def read_perf_samples(path: Path) -> dict[BatchKey, PerfSamples]:
    text = path.read_text(encoding="utf-8")
    rows: dict[BatchKey, PerfSamples] = {}
    for match in PERF_SYMBOL_RE.finditer(text):
        samples_text, period_text, phase, batch_text = match.groups()
        key = BatchKey(phase=phase, batch_id=int(batch_text))
        if key in rows:
            raise ValueError(f"{path}: duplicate perf symbol for batch: {key}")
        samples = parse_nonnegative(samples_text, path, "samples")
        period = parse_nonnegative(period_text, path, "period")
        if samples == 0 or period == 0:
            raise ValueError(f"{path}: non-positive sampled batch: {key}")
        rows[key] = PerfSamples(samples=samples, period=period)
    if not rows:
        raise ValueError(f"{path}: no exact GrhSIM batch symbols")
    return rows


def rate(numerator: int | float, denominator: int | float, scale: float = 1.0) -> float | None:
    return scale * numerator / denominator if denominator else None


def summarize_variant(
    name: str,
    source_dir: Path,
    static_path: Path,
    fire_path: Path,
    perf_path: Path,
) -> dict:
    batches = read_generated_batches(source_dir)
    perf = read_perf_samples(perf_path)
    joined = runtime_profile.join_rows(static_path, fire_path)
    joined_by_key = {row.static.key: row for row in joined}

    generated_supernodes = {
        supernode
        for supernodes in batches.values()
        for supernode in supernodes
    }
    profile_supernodes = set(joined_by_key)
    if generated_supernodes != profile_supernodes:
        missing_profile = sorted(generated_supernodes - profile_supernodes)[:10]
        missing_generated = sorted(profile_supernodes - generated_supernodes)[:10]
        raise ValueError(
            "generated/profile supernode mismatch: "
            f"missing_profile={missing_profile} missing_generated={missing_generated} "
            f"generated={len(generated_supernodes)} profile={len(profile_supernodes)}"
        )

    unknown_perf = sorted(set(perf) - set(batches))
    if unknown_perf:
        raise ValueError(f"{perf_path}: sampled unknown generated batches: {unknown_perf[:10]}")

    batch_rows = []
    for key in sorted(batches):
        rows = [joined_by_key[supernode] for supernode in batches[key]]
        runtime = runtime_profile.summarize_rows(rows)
        samples = perf.get(key, PerfSamples(samples=0, period=0))
        batch_rows.append(
            {
                "phase": key.phase,
                "batch_id": key.batch_id,
                "supernodes": len(rows),
                "samples": samples.samples,
                "period": samples.period,
                **runtime,
                "samples_per_billion_work": rate(
                    samples.samples, runtime["work_total"], 1_000_000_000.0
                ),
                "events_per_work": rate(samples.period, runtime["work_total"]),
            }
        )

    phase_rows = {}
    for phase in PHASES:
        rows = [row for row in batch_rows if row["phase"] == phase]
        runtime_rows = [
            joined_by_key[supernode]
            for key, supernodes in batches.items()
            if key.phase == phase
            for supernode in supernodes
        ]
        runtime = runtime_profile.summarize_rows(runtime_rows)
        samples = sum(row["samples"] for row in rows)
        period = sum(row["period"] for row in rows)
        phase_rows[phase] = {
            "batches": len(rows),
            "sampled_batches": sum(row["samples"] != 0 for row in rows),
            "samples": samples,
            "period": period,
            **runtime,
            "samples_per_billion_work": rate(samples, runtime["work_total"], 1_000_000_000.0),
            "events_per_work": rate(period, runtime["work_total"]),
        }

    return {
        "name": name,
        "source_dir": str(source_dir),
        "static_tsv": str(static_path),
        "fire_tsv": str(fire_path),
        "perf_report": str(perf_path),
        "perf_symbols": len(perf),
        "phases": phase_rows,
        "batches": batch_rows,
    }


def percent_delta(candidate: int | float | None, baseline: int | float | None) -> float | None:
    if candidate is None or baseline in (None, 0):
        return None
    return 100.0 * (candidate / baseline - 1.0)


def compare_variants(baseline: dict, candidate: dict) -> dict:
    metrics = ("samples", "period", "fire", "work_total", "samples_per_billion_work", "events_per_work")
    phases = {}
    for phase in PHASES:
        phases[phase] = {}
        for metric in metrics:
            old = baseline["phases"][phase][metric]
            new = candidate["phases"][phase][metric]
            phases[phase][metric] = {
                "baseline": old,
                "candidate": new,
                "delta_percent": percent_delta(new, old),
            }
    return {
        "baseline": baseline["name"],
        "candidate": candidate["name"],
        "phases": phases,
    }


def format_optional(value: float | None, precision: int = 6) -> str:
    return "n/a" if value is None else f"{value:.{precision}f}"


def print_batch_rows(title: str, rows: list[dict], out: TextIO) -> None:
    print(title, file=out)
    print(
        "rank phase batch supernodes samples period fire work_total "
        "samples_per_billion_work events_per_work",
        file=out,
    )
    for rank, row in enumerate(rows, start=1):
        print(
            f"{rank} {row['phase']} {row['batch_id']} {row['supernodes']} "
            f"{row['samples']} {row['period']} {row['fire']} {row['work_total']} "
            f"{format_optional(row['samples_per_billion_work'])} "
            f"{format_optional(row['events_per_work'])}",
            file=out,
        )


def print_report(
    variants: list[dict],
    comparisons: list[dict],
    top: int,
    min_samples: int,
    out: TextIO,
) -> None:
    for variant in variants:
        print(f"variant={variant['name']}", file=out)
        print(f"source_dir={variant['source_dir']}", file=out)
        print(f"static_tsv={variant['static_tsv']}", file=out)
        print(f"fire_tsv={variant['fire_tsv']}", file=out)
        print(f"perf_report={variant['perf_report']}", file=out)
        print(f"perf_symbols={variant['perf_symbols']}", file=out)
        for phase in PHASES:
            summary = variant["phases"][phase]
            print(
                f"phase={phase} batches={summary['batches']} "
                f"sampled_batches={summary['sampled_batches']} samples={summary['samples']} "
                f"period={summary['period']} fire={summary['fire']} "
                f"work_total={summary['work_total']} "
                f"samples_per_billion_work={format_optional(summary['samples_per_billion_work'])} "
                f"events_per_work={format_optional(summary['events_per_work'])}",
                file=out,
            )

        by_samples = sorted(
            variant["batches"],
            key=lambda row: (-row["samples"], row["phase"], row["batch_id"]),
        )[:top]
        print_batch_rows("top_by_samples", by_samples, out)
        for phase in PHASES:
            by_density = sorted(
                (
                    row
                    for row in variant["batches"]
                    if row["phase"] == phase
                    and row["samples"] >= min_samples
                    and row["work_total"]
                ),
                key=lambda row: (
                    -row["samples_per_billion_work"],
                    -row["samples"],
                    row["batch_id"],
                ),
            )[:top]
            print_batch_rows(
                f"top_by_sample_density phase={phase} min_samples={min_samples}",
                by_density,
                out,
            )
        print_batch_rows("all_batches", variant["batches"], out)

    for comparison in comparisons:
        print(
            f"comparison={comparison['candidate']}_vs_{comparison['baseline']}",
            file=out,
        )
        print("phase metric baseline candidate delta_percent", file=out)
        for phase in PHASES:
            for metric, values in comparison["phases"][phase].items():
                delta = values["delta_percent"]
                delta_text = "n/a" if delta is None else f"{delta:.6f}%"
                print(
                    f"{phase} {metric} {values['baseline']} {values['candidate']} {delta_text}",
                    file=out,
                )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Join generated GrhSIM batches, runtime work, and perf symbol samples."
    )
    parser.add_argument(
        "--variant",
        action="append",
        nargs=5,
        metavar=("NAME", "SOURCE_DIR", "STATIC_TSV", "FIRE_TSV", "PERF_REPORT"),
        required=True,
        help="add a named batch profile; the first profile is the comparison baseline",
    )
    parser.add_argument("--top", type=int, default=10, help="number of top batches to report")
    parser.add_argument(
        "--min-samples",
        type=int,
        default=20,
        help="minimum samples for sample-density ranking",
    )
    parser.add_argument("--output", type=Path, help="write the text report to this path")
    parser.add_argument("--json", type=Path, help="write the machine-readable report to this path")
    args = parser.parse_args()
    if args.top < 0:
        parser.error("--top must be non-negative")
    if args.min_samples < 0:
        parser.error("--min-samples must be non-negative")

    variants = [
        summarize_variant(
            name,
            Path(source_dir),
            Path(static_tsv),
            Path(fire_tsv),
            Path(perf_report),
        )
        for name, source_dir, static_tsv, fire_tsv, perf_report in args.variant
    ]
    comparisons = [compare_variants(variants[0], variant) for variant in variants[1:]]
    payload = {"variants": variants, "comparisons": comparisons}

    if args.output is None:
        print_report(variants, comparisons, args.top, args.min_samples, sys.stdout)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as out:
            print_report(variants, comparisons, args.top, args.min_samples, out)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
