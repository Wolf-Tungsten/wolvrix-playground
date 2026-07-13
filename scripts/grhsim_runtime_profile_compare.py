#!/usr/bin/env python3

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


PHASES = ("compute", "commit")
WEIGHT_COLUMNS = ("n_comp", "n_src", "n_sink", "n_const", "a_succ")
SUMMARY_COLUMNS = (
    "rows",
    "nonzero_rows",
    "fire",
    "work_comp",
    "work_src",
    "work_sink",
    "work_const",
    "work_total",
    "a_succ_work",
)


@dataclass(frozen=True, order=True)
class SupernodeKey:
    supernode_id: int
    phase: str


@dataclass(frozen=True)
class StaticRow:
    key: SupernodeKey
    n_comp: int
    n_src: int
    n_sink: int
    n_const: int
    a_succ: int


@dataclass(frozen=True)
class JoinedRow:
    static: StaticRow
    fire: int

    @property
    def work_comp(self) -> int:
        return self.fire * self.static.n_comp

    @property
    def work_src(self) -> int:
        return self.fire * self.static.n_src

    @property
    def work_sink(self) -> int:
        return self.fire * self.static.n_sink

    @property
    def work_const(self) -> int:
        return self.fire * self.static.n_const

    @property
    def work_total(self) -> int:
        return self.work_comp + self.work_src + self.work_sink + self.work_const

    @property
    def a_succ_work(self) -> int:
        return self.fire * self.static.a_succ


def parse_nonnegative_int(value: str, path: Path, line: int, column: str) -> int:
    try:
        parsed = int(value)
    except ValueError as ex:
        raise ValueError(f"{path}:{line}: invalid integer in {column}: {value!r}") from ex
    if parsed < 0:
        raise ValueError(f"{path}:{line}: negative integer in {column}: {parsed}")
    return parsed


def validate_columns(path: Path, actual: list[str] | None, required: set[str]) -> None:
    if actual is None:
        raise ValueError(f"{path}: missing TSV header")
    missing = sorted(required - set(actual))
    if missing:
        raise ValueError(f"{path}: missing required columns: {', '.join(missing)}")


def parse_key(row: dict[str, str], path: Path, line: int) -> SupernodeKey:
    phase = row["phase"]
    if phase not in PHASES:
        raise ValueError(f"{path}:{line}: invalid phase: {phase!r}")
    return SupernodeKey(
        supernode_id=parse_nonnegative_int(row["supernode_id"], path, line, "supernode_id"),
        phase=phase,
    )


def read_static(path: Path) -> dict[SupernodeKey, StaticRow]:
    rows: dict[SupernodeKey, StaticRow] = {}
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, delimiter="\t")
        validate_columns(path, reader.fieldnames, {"supernode_id", "phase", *WEIGHT_COLUMNS})
        for line, raw in enumerate(reader, start=2):
            key = parse_key(raw, path, line)
            if key in rows:
                raise ValueError(f"{path}:{line}: duplicate key: {key}")
            values = {
                column: parse_nonnegative_int(raw[column], path, line, column)
                for column in WEIGHT_COLUMNS
            }
            rows[key] = StaticRow(key=key, **values)
    if not rows:
        raise ValueError(f"{path}: no static data rows")
    return rows


def read_fire(path: Path) -> dict[SupernodeKey, int]:
    rows: dict[SupernodeKey, int] = {}
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, delimiter="\t")
        validate_columns(path, reader.fieldnames, {"supernode_id", "phase", "f"})
        for line, raw in enumerate(reader, start=2):
            key = parse_key(raw, path, line)
            if key in rows:
                raise ValueError(f"{path}:{line}: duplicate key: {key}")
            rows[key] = parse_nonnegative_int(raw["f"], path, line, "f")
    if not rows:
        raise ValueError(f"{path}: no fire data rows")
    return rows


def join_rows(static_path: Path, fire_path: Path) -> list[JoinedRow]:
    static = read_static(static_path)
    fire = read_fire(fire_path)
    static_keys = set(static)
    fire_keys = set(fire)
    if static_keys != fire_keys:
        missing_fire = sorted(static_keys - fire_keys)[:10]
        missing_static = sorted(fire_keys - static_keys)[:10]
        raise ValueError(
            f"profile key mismatch: missing_fire={missing_fire} missing_static={missing_static} "
            f"static_rows={len(static)} fire_rows={len(fire)}"
        )
    return [JoinedRow(static=static[key], fire=fire[key]) for key in sorted(static)]


def empty_summary() -> dict[str, int]:
    return {column: 0 for column in SUMMARY_COLUMNS}


def summarize_rows(rows: list[JoinedRow]) -> dict[str, int]:
    result = empty_summary()
    for row in rows:
        result["rows"] += 1
        result["nonzero_rows"] += int(row.fire != 0)
        result["fire"] += row.fire
        result["work_comp"] += row.work_comp
        result["work_src"] += row.work_src
        result["work_sink"] += row.work_sink
        result["work_const"] += row.work_const
        result["work_total"] += row.work_total
        result["a_succ_work"] += row.a_succ_work
    return result


def row_json(row: JoinedRow) -> dict[str, int | str]:
    return {
        "supernode_id": row.static.key.supernode_id,
        "phase": row.static.key.phase,
        "fire": row.fire,
        "n_comp": row.static.n_comp,
        "n_src": row.static.n_src,
        "n_sink": row.static.n_sink,
        "n_const": row.static.n_const,
        "a_succ": row.static.a_succ,
        "work_total": row.work_total,
        "a_succ_work": row.a_succ_work,
    }


def summarize_variant(name: str, static_path: Path, fire_path: Path, top: int) -> dict:
    rows = join_rows(static_path, fire_path)
    phases = {
        phase: summarize_rows([row for row in rows if row.static.key.phase == phase])
        for phase in PHASES
    }
    return {
        "name": name,
        "static_tsv": str(static_path),
        "fire_tsv": str(fire_path),
        "phases": phases,
        "total": summarize_rows(rows),
        "top_by_fire": [
            row_json(row)
            for row in sorted(
                rows,
                key=lambda row: (-row.fire, row.static.key.phase, row.static.key.supernode_id),
            )[:top]
        ],
        "top_by_work": [
            row_json(row)
            for row in sorted(
                rows,
                key=lambda row: (-row.work_total, row.static.key.phase, row.static.key.supernode_id),
            )[:top]
        ],
    }


def comparison_json(baseline: dict, candidate: dict) -> dict:
    metrics = {}
    for metric in SUMMARY_COLUMNS:
        old = baseline["total"][metric]
        new = candidate["total"][metric]
        metrics[metric] = {
            "baseline": old,
            "candidate": new,
            "delta": new - old,
            "delta_percent": 100.0 * (new - old) / old if old else None,
        }
    return {
        "baseline": baseline["name"],
        "candidate": candidate["name"],
        "metrics": metrics,
    }


def print_summary(summary: dict[str, int], out: TextIO) -> None:
    print(
        " ".join(f"{column}={summary[column]}" for column in SUMMARY_COLUMNS),
        file=out,
    )


def print_top(title: str, rows: list[dict], out: TextIO) -> None:
    print(title, file=out)
    print("rank supernode phase fire n_comp n_src n_sink n_const a_succ work_total a_succ_work", file=out)
    for rank, row in enumerate(rows, start=1):
        print(
            f"{rank} {row['supernode_id']} {row['phase']} {row['fire']} "
            f"{row['n_comp']} {row['n_src']} {row['n_sink']} {row['n_const']} "
            f"{row['a_succ']} {row['work_total']} {row['a_succ_work']}",
            file=out,
        )


def print_report(variants: list[dict], comparisons: list[dict], out: TextIO) -> None:
    for variant in variants:
        print(f"variant={variant['name']}", file=out)
        print(f"static_tsv={variant['static_tsv']}", file=out)
        print(f"fire_tsv={variant['fire_tsv']}", file=out)
        for phase in PHASES:
            print(f"phase={phase}", file=out)
            print_summary(variant["phases"][phase], out)
        print("phase=total", file=out)
        print_summary(variant["total"], out)
        print_top("top_by_fire", variant["top_by_fire"], out)
        print_top("top_by_work", variant["top_by_work"], out)

    for comparison in comparisons:
        print(
            f"comparison={comparison['candidate']}_vs_{comparison['baseline']}",
            file=out,
        )
        print("metric baseline candidate delta delta_percent", file=out)
        for metric in SUMMARY_COLUMNS:
            values = comparison["metrics"][metric]
            delta_percent = values["delta_percent"]
            percent_text = "n/a" if delta_percent is None else f"{delta_percent:.6f}%"
            print(
                f"{metric} {values['baseline']} {values['candidate']} "
                f"{values['delta']} {percent_text}",
                file=out,
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Join and compare GrhSIM static and runtime supernode profile TSVs."
    )
    parser.add_argument(
        "--variant",
        action="append",
        nargs=3,
        metavar=("NAME", "STATIC_TSV", "FIRE_TSV"),
        required=True,
        help="add a named profile; the first profile is the comparison baseline",
    )
    parser.add_argument("--top", type=int, default=10, help="number of top rows to report")
    parser.add_argument("--output", type=Path, help="write the text report to this path")
    parser.add_argument("--json", type=Path, help="write the full machine-readable summary to this path")
    args = parser.parse_args()
    if args.top < 0:
        parser.error("--top must be non-negative")

    variants = [
        summarize_variant(name, Path(static_path), Path(fire_path), args.top)
        for name, static_path, fire_path in args.variant
    ]
    comparisons = [comparison_json(variants[0], candidate) for candidate in variants[1:]]
    payload = {"variants": variants, "comparisons": comparisons}

    if args.output is None:
        print_report(variants, comparisons, sys.stdout)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as out:
            print_report(variants, comparisons, out)

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
