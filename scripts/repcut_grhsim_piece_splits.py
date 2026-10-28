#!/usr/bin/env python3
"""Generate and exactly evaluate generic multi-destination piece splits.

The generator starts from the current eval profile, chooses the most expensive
source lanes and the lanes with the most headroom, then splits a source-model
piece's *local* members between two destinations.  It contains no RTL names or
fixed partition numbers.  Shape features only choose the piece and balance the
two chunks; the exact assignment report, execution-plan gate, functional
signature, and ABBA timing remain acceptance gates.

The evaluator is intentionally small and uses the frozen assignment evaluator
already built for the experiment.  It writes the same structural fields used by
``repcut_grhsim_local_search_rank.py`` so split candidates can be screened by
the common conservative envelope.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import itertools
import json
from pathlib import Path
import subprocess
from typing import Iterable

from repcut_grhsim_local_search_rank import load_eval_times
from repcut_grhsim_piece_candidates import FEATURES
from repcut_grhsim_plan_gate import identity, save


def atom_scores(features: Path, atoms: int) -> list[int]:
    scores = [0] * atoms
    with features.open(newline="") as stream:
        for row in csv.DictReader(stream):
            atom = int(row["atom"])
            count = int(row["count"])
            if atom < 0 or atom >= atoms or count < 0:
                raise ValueError("invalid atom feature")
            if row["feature"] in FEATURES:
                scores[atom] += count
    return scores


def balanced_split(members: Iterable[int], scores: list[int], bins: int = 2) -> tuple[tuple[int, ...], ...]:
    """Split members by descending shape score with a deterministic k-bin fit.

    The greedy choice keeps both chunks close in the same pre-lowering shape
    metric while retaining every atom exactly once.  Ties use atom id, making
    generated assignments reproducible.
    """
    if bins < 2:
        raise ValueError("a split needs at least two bins")
    ordered = sorted(members, key=lambda atom: (-scores[atom], atom))
    if len(ordered) < bins:
        raise ValueError("a split needs at least one local member per bin")
    chunks: list[list[int]] = [[] for _ in range(bins)]
    loads = [0] * bins
    for atom in ordered:
        index = min(range(bins), key=lambda candidate: (loads[candidate],
                                                         len(chunks[candidate]), candidate))
        chunks[index].append(atom)
        loads[index] += scores[atom]
    if any(not chunk for chunk in chunks):
        raise ValueError("split produced an empty chunk")
    return tuple(tuple(sorted(chunk)) for chunk in chunks)


def _read_model_pieces(model: Path, labels: list[int], sources: set[int], scores: list[int]):
    with model.open() as stream:
        if stream.readline().strip() != "repcut-assignment-model-v2":
            raise ValueError("unsupported source model")
        stream.readline()
        atoms, feature_count, piece_count, _, _ = map(int, stream.readline().split())
        if atoms != len(labels) or atoms != len(scores):
            raise ValueError("model / assignment / feature size mismatch")
        for _ in range(feature_count):
            stream.readline()
        for piece in range(piece_count):
            row = list(map(int, stream.readline().split()))
            if not row or len(row) != 1 + row[0] + feature_count:
                raise ValueError(f"invalid piece {piece}")
            members = row[1:1 + row[0]]
            local: dict[int, list[int]] = {source: [] for source in sources}
            for atom in members:
                label = labels[atom]
                if label in local:
                    local[label].append(atom)
            for source, source_members in local.items():
                if len(source_members) < 2:
                    continue
                yield piece, source, tuple(sorted(source_members)), sum(scores[a] for a in source_members)


def generate(model: Path, features: Path, assignment: Path, parts: Path,
             source_count: int, target_count: int, top: int, split_degree: int,
             output: Path) -> dict:
    labels = list(map(int, assignment.read_text().split()))
    partitions = max(labels, default=-1) + 1
    timings = load_eval_times(parts)
    if set(timings) != set(range(partitions)):
        raise ValueError("profile partition set does not match assignment")
    if min(source_count, target_count, top) < 1 or split_degree < 2:
        raise ValueError("source-count, target-count, and top must be positive")
    sources = sorted(timings, key=lambda p: (-timings[p]["eval"], p))[:source_count]
    targets = [p for p in sorted(timings, key=lambda p: (timings[p]["eval"], p))
               if p not in sources][:target_count]
    if len(targets) < split_degree:
        raise ValueError("target-count is smaller than split-degree")
    scores = atom_scores(features, len(labels))
    selected: dict[int, list[tuple[int, int, tuple[int, ...]]]] = {source: [] for source in sources}
    for piece, source, members, shape_score in _read_model_pieces(
            model, labels, set(sources), scores):
        selected[source].append((shape_score, piece, members))
    for source in sources:
        selected[source].sort(key=lambda item: (-item[0], -len(item[2]), item[1]))
        selected[source] = selected[source][:top]

    output.mkdir(parents=True, exist_ok=False)
    candidates: list[dict] = []
    seen: set[tuple[int, ...]] = set()
    for source in sources:
        for shape_score, piece, members in selected[source]:
            try:
                chunks = balanced_split(members, scores, split_degree)
            except ValueError:
                continue
            for destinations in itertools.combinations(targets, split_degree):
                moved = labels.copy()
                for destination, chunk in zip(destinations, chunks):
                    for atom in chunk:
                        if labels[atom] != source:
                            raise ValueError("source member label changed")
                        moved[atom] = destination
                key = tuple(moved)
                if key in seen:
                    continue
                seen.add(key)
                name = f"split_p{source}_to_{'_'.join(map(str, destinations))}_piece_{piece}"
                path = output / (name + ".assignment")
                path.write_text("".join(f"{label}\n" for label in moved))
                candidates.append({
                    "name": name,
                    "source": source,
                    "destinations": list(destinations),
                    "source_piece": piece,
                    "split_method": f"shape_greedy_{split_degree}_bin",
                    "shape_score": shape_score,
                    "moved_atoms": sum(map(len, chunks)),
                    "split_atoms": [len(chunk) for chunk in chunks],
                    "split_shape_scores": [sum(scores[a] for a in chunk) for chunk in chunks],
                    "assignment": identity(path),
                })
    if not candidates:
        raise ValueError("no legal piece splits generated")
    inputs = {name: identity(path) for name, path in {
        "model": model, "features": features, "assignment": assignment, "parts": parts,
    }.items()}
    result = {
        "schema_version": 1,
        "status": "proposals_only",
        "inputs": inputs,
        "partitions": partitions,
        "source_mode": "profile_top_eval",
        "source_partitions": sources,
        "target_partitions": targets,
        "baseline_eval_us": {str(p): timings[p]["eval"] for p in timings},
        "selected_features": sorted(FEATURES),
        "timing_used": "only to choose source and headroom destination sets",
        "candidates": candidates,
        "needs_exact_assignment_and_backend_evaluation": True,
    }
    save(output / "selection.json", result)
    return result


METRICS = (
    "grhsim_v1_closure_work", "grhsim_v1_recurring_work", "raw_operation_count",
    "state_write_count", "piece_copies", "send_calls", "send_bytes",
    "receive_calls", "receive_bytes",
)


def _load_parts(path: Path) -> dict[int, dict[str, int]]:
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or "part" not in rows[0]:
        raise ValueError(f"bad assignment report: {path}")
    return {int(row["part"]): {metric: int(row[metric]) for metric in METRICS} for row in rows}


def _delta(base: int, candidate: int) -> dict:
    return {"baseline": base, "candidate": candidate, "delta": candidate - base,
            "percent": 100.0 * (candidate - base) / base if base else None}


def load_transfer_layout(path: Path) -> dict:
    """Keep exact member/offset layouts, including equal-size repacking."""
    csv.field_size_limit(max(csv.field_size_limit(), 1 << 24))
    result = {}
    with path.open(newline='') as stream:
        for row in csv.DictReader(stream):
            owner = int(row['owner'])
            readers = tuple(sorted(int(p) for p in row['readers'].split(';') if p))
            members = tuple(sorted(tuple(map(int, item.split(':')))
                                   for item in row['members'].split(';') if item))
            width = int(row['width'])
            if (owner < 0 or not readers or min(readers) < 0 or owner in readers or
                    len(set(readers)) != len(readers) or width < 1 or not members or
                    any(len(m) != 3 for m in members)):
                raise ValueError('invalid transfer layout')
            if (len({m[0] for m in members}) != len(members) or
                    any(key < 0 or size < 1 or offset < 0 or offset + size > width
                        for key, size, offset in members)):
                raise ValueError('invalid transfer members')
            key = owner, readers
            if key in result:
                raise ValueError('duplicate owner/reader-set bundle')
            result[key] = (width, members)
    return result


def transfer_impact(before: dict, after: dict, endpoints: Iterable[int]) -> dict:
    """Direct bundle impact only; downstream activity may propagate further."""
    endpoints = set(endpoints)
    impacted = set(endpoints)
    changes = []
    for owner, readers in sorted(before.keys() | after.keys()):
        key = owner, readers
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        impacted.update((owner, *readers))
        changes.append({'owner': owner, 'readers': list(readers),
                        'baseline_width_bits': old[0] if old else 0,
                        'candidate_width_bits': new[0] if new else 0,
                        'baseline_members': len(old[1]) if old else 0,
                        'candidate_members': len(new[1]) if new else 0,
                        'member_layout_changed': True})
    return {'direct_impact_parts': sorted(impacted),
            'non_endpoint_impact_parts': sorted(impacted - endpoints),
            'changed_transfer_bundles': changes,
            'impact_scope': 'exact owner/reader/member/width/offset changes; not full downstream activity closure'}


def evaluate(model: Path, baseline: Path, selection: Path, evaluator: Path,
             output: Path) -> dict:
    selection_data = json.loads(selection.read_text())
    candidates = selection_data.get("candidates", [])
    if not candidates:
        raise ValueError("selection contains no candidates")
    output.mkdir(parents=True, exist_ok=False)
    command = [str(evaluator), str(model), str(baseline), str(output / "baseline")]
    for record in candidates:
        command.extend([record["assignment"]["path"], str(output / record["name"])])
    log = output / "assignment.log"
    with log.open("w") as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
    baseline_parts = _load_parts(output / "baseline.parts.csv")
    baseline_transfers = load_transfer_layout(output / 'baseline.transfers.csv')
    if set(baseline_parts) != set(range(selection_data["partitions"])):
        raise ValueError("assignment evaluator returned an unexpected partition set")
    report_candidates = []
    for record in candidates:
        candidate_parts = _load_parts(output / (record["name"] + ".parts.csv"))
        if set(candidate_parts) != set(baseline_parts):
            raise ValueError(f"partition set changed for {record['name']}")
        destinations = record.get("destinations", [record.get("destination")])
        if not destinations or any(p is None for p in destinations):
            raise ValueError(f"missing destinations for {record['name']}")
        touched = [int(record["source"]), *map(int, destinations)]
        work: dict[str, dict] = {}
        for metric in METRICS:
            values = {"baseline": [baseline_parts[p][metric] for p in baseline_parts],
                      "candidate": [candidate_parts[p][metric] for p in candidate_parts]}
            work[metric] = {
                "peak": _delta(max(values["baseline"]), max(values["candidate"])),
                "total": _delta(sum(values["baseline"]), sum(values["candidate"])),
            }
            work[metric]["source"] = _delta(
                baseline_parts[touched[0]][metric], candidate_parts[touched[0]][metric])
            for index, part in enumerate(touched[1:]):
                work[metric][f"destination_{index}"] = _delta(
                    baseline_parts[part][metric], candidate_parts[part][metric])
            work[metric]["destinations"] = {
                str(part): _delta(baseline_parts[part][metric], candidate_parts[part][metric])
                for part in touched[1:]
            }
        # A move changes packing and reader sets outside its source/destinations.
        # Preserve every lane so communication guards also see those changes.
        parts = {str(part): {metric: _delta(baseline_parts[part][metric], candidate_parts[part][metric])
                            for metric in METRICS} for part in baseline_parts}
        changed = [part for part in baseline_parts if baseline_parts[part] != candidate_parts[part]]
        impact = transfer_impact(baseline_transfers,
                                 load_transfer_layout(output / (record['name'] + '.transfers.csv')),
                                 touched)
        if not set(impact['direct_impact_parts']).issubset(baseline_parts):
            raise ValueError('transfer layout references an unknown partition')
        report_candidates.append({**record, "destinations": list(map(int, destinations)),
                                  "touched": touched, "changed_parts": changed, "parts": parts,
                                  "metric_changed_parts": changed,
                                  **impact, **work})
    result = {
        "schema_version": 2,
        "status": "pass",
        "method": "exact_finite_assignment_all_partition_accounting",
        "baseline": {"parts": str(output / "baseline.parts.csv"),
                      "part_count": len(baseline_parts)},
        "candidates": report_candidates,
        "log": str(log),
    }
    save(output / "report.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    generate_parser = sub.add_parser("generate")
    for name in ("model", "features", "assignment", "parts", "output"):
        generate_parser.add_argument("--" + name, type=Path, required=True)
    generate_parser.add_argument("--source-count", type=int, default=4)
    generate_parser.add_argument("--target-count", type=int, default=6)
    generate_parser.add_argument("--top", type=int, default=1)
    generate_parser.add_argument("--split-degree", type=int, default=2)
    evaluate_parser = sub.add_parser("evaluate")
    for name in ("model", "baseline", "selection", "evaluator", "output"):
        evaluate_parser.add_argument("--" + name, type=Path, required=True)
    impact_parser = sub.add_parser('annotate-impact',
                                  help='add direct transfer-layout impact to an existing exact report')
    impact_parser.add_argument('--report', type=Path, required=True)
    impact_parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == "generate":
        result = generate(args.model, args.features, args.assignment, args.parts,
                          args.source_count, args.target_count, args.top,
                          args.split_degree, args.output)
        print(json.dumps({"candidates": len(result["candidates"]),
                          "sources": result["source_partitions"],
                          "targets": result["target_partitions"],
                          "output": str(args.output)}))
    elif args.command == 'evaluate':
        result = evaluate(args.model, args.baseline, args.selection, args.evaluator, args.output)
        print(json.dumps({"candidates": len(result["candidates"]), "output": str(args.output)}))
    else:
        result = json.loads(args.report.read_text())
        if result.get('status') != 'pass':
            raise ValueError('expected a successful exact assignment report')
        folder = args.report.parent
        before = load_transfer_layout(folder / 'baseline.transfers.csv')
        for candidate in result['candidates']:
            destinations = candidate.get('destinations', [candidate.get('destination')])
            touched = candidate.get('touched', [candidate['source'], *destinations])
            impact = transfer_impact(before, load_transfer_layout(
                folder / (candidate['name'] + '.transfers.csv')), touched)
            if not set(impact['direct_impact_parts']).issubset(range(result['baseline']['part_count'])):
                raise ValueError('transfer layout references an unknown partition')
            candidate.update(impact)
            if 'changed_parts' in candidate:
                candidate['metric_changed_parts'] = candidate['changed_parts']
        result['transfer_impact_source_report'] = identity(args.report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        save(args.output, result)
        print(json.dumps({'candidates': len(result['candidates']), 'output': str(args.output)}))


if __name__ == "__main__":
    main()
