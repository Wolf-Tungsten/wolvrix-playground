#!/usr/bin/env python3
"""Propose bounded whole-ASC moves using source-model shared pieces.

The shape score only prioritizes proposals; its features have different units
and it is not an execution-time estimate. Exact closure/transfer evaluation and
same-option backend replay must follow. An optional profile selects source
partitions only; it does not score individual pieces. No module names enter
the proposal rules. Partition count is inferred unless explicitly supplied.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
import math
from pathlib import Path

from repcut_grhsim_local_search_rank import load_eval_times
from repcut_grhsim_plan_gate import check_identity, identity, save


FEATURES = frozenset({
    'compute.wide.operand_words', 'compute.wide.helper_operand_words',
    'compute.wide.helper_word_iterations', 'compute.wide.helper_output_words',
    'compute.wide.result.temporary', 'compute.wide.result.materialized',
    'compute.wide.result.untracked_store', 'compute.wide.concat_source_words',
    'compute.wide.concat_destination_words', 'compute.wide.helper_cross_word_merges',
    'compute.constant.wide_temporary',
})


def profile_sources(parts: Path, variant: str, partitions: int,
                    count: int | None) -> tuple[list[int], dict]:
    """Select expensive lanes from the timing arm matching the assignment."""
    timings = load_eval_times(parts, variant)
    if set(timings) != set(range(partitions)):
        raise ValueError('profile partition set does not match assignment')
    if count is not None and count < 1:
        raise ValueError('source-count must be positive')
    if any(not math.isfinite(t['eval']) or t['eval'] < 0 for t in timings.values()):
        raise ValueError('profile eval times must be finite and nonnegative')
    sources = sorted(timings, key=lambda p: (-timings[p]['eval'], p))
    return sources[:count], timings


def critical_sources(path: Path, partitions: int, count: int | None,
                     check_inputs: bool = True) -> tuple[list[int], dict]:
    """Prefer lanes that actually extend the per-step eval critical path."""
    profile = json.loads(path.read_text())
    if profile.get('status') != 'pass' or profile.get('partition_count') != partitions:
        raise ValueError('critical profile partition set does not match assignment')
    rows = profile['all']['eval']['parts']
    if len(rows) != partitions or {r['part'] for r in rows} != set(range(partitions)):
        raise ValueError('incomplete critical profile')
    if count is not None and count < 1:
        raise ValueError('source-count must be positive')
    if any(not math.isfinite(r['exclusive_margin_us']) or r['exclusive_margin_us'] < 0 for r in rows):
        raise ValueError('invalid critical margin')
    if check_inputs:
        for item in profile['inputs']:
            check_identity(item)
    ordered = sorted(rows, key=lambda r: (-r['exclusive_margin_us'], -r['bottleneck_count'], r['part']))
    return [r['part'] for r in ordered if r['exclusive_margin_us'] > 0][:count], profile


def propose(model: Path, features: Path, labels: list[int], sources: list[int],
            partitions: int, top: int, targets: int) -> list[dict]:
    if not labels or min(labels) < 0 or max(labels) >= partitions:
        raise ValueError('invalid partition labels')
    if not sources or any(s < 0 or s >= partitions for s in sources):
        raise ValueError('source partition out of range')
    if top < 1 or targets < 1:
        raise ValueError('top and targets must be positive')
    scores = [0] * len(labels)
    with features.open() as stream:
        for row in csv.DictReader(stream):
            atom, count = int(row['atom']), int(row['count'])
            if atom < 0 or atom >= len(labels) or count < 0:
                raise ValueError('invalid atom feature')
            if row['feature'] in FEATURES:
                scores[atom] += count
    selected: dict[int, dict[tuple[int, ...], dict]] = {s: {} for s in sources}
    floors = {s: 0 for s in sources}
    with model.open() as stream:
        if stream.readline().strip() != 'repcut-assignment-model-v2':
            raise ValueError('unsupported source model')
        stream.readline()  # adapter identity
        atoms, feature_count, piece_count, _, _ = map(int, stream.readline().split())
        if atoms != len(labels):
            raise ValueError('source model / assignment size mismatch')
        for _ in range(feature_count):
            stream.readline()
        for piece in range(piece_count):
            row = list(map(int, stream.readline().split()))
            if not row or len(row) != 1 + row[0] + feature_count:
                raise ValueError(f'invalid piece {piece}')
            members = row[1:1 + row[0]]
            if any(a < 0 or a >= atoms for a in members):
                raise ValueError('piece member out of range')
            by_source = {s: [] for s in sources}
            counts: Counter = Counter()
            for atom in members:
                label = labels[atom]
                counts[label] += 1
                if label in by_source:
                    by_source[label].append(atom)
            for source, local in by_source.items():
                score = sum(scores[a] for a in local)
                if not local or score == 0 or score < floors[source]:
                    continue
                key = tuple(sorted(local))
                # Identical moved sets yield identical assignments. Keep one
                # representative instead of spending replay/compile budget twice.
                if key in selected[source]:
                    continue
                record = dict(piece=piece, source=source, members=key, shape_score=score,
                              piece_partition_members=dict(counts))
                selected[source][key] = record
                if len(selected[source]) > top:
                    worst = min(selected[source], key=lambda k: (
                        selected[source][k]['shape_score'], len(k), -selected[source][k]['piece']))
                    del selected[source][worst]
                if len(selected[source]) == top:
                    floors[source] = min(r['shape_score'] for r in selected[source].values())
    result = []
    for source in sources:
        ranked = sorted(selected[source].values(), key=lambda r: (-r['shape_score'], -len(r['members']), r['piece']))
        for record in ranked:
            counts = record['piece_partition_members']
            # Prefer already sharing destinations. All destinations remain legal;
            # the next gate evaluates their actual added work/replication/traffic.
            destinations = sorted((p for p in range(partitions) if p != source),
                                  key=lambda p: (-counts.get(p, 0), p))[:targets]
            for destination in destinations:
                result.append(dict(record, destination=destination,
                                   destination_piece_members=counts.get(destination, 0)))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--features', type=Path, required=True)
    parser.add_argument('--assignment', type=Path, required=True)
    parser.add_argument(
        '--source', type=int, nargs='+',
        help='source partitions to inspect; omit to inspect every partition',
    )
    parser.add_argument(
        '--all-sources', action='store_true',
        help='explicitly request every partition (the default without a source profile or --source)',
    )
    parser.add_argument('--parts', type=Path,
                        help='select sources by current per-part eval medians')
    parser.add_argument('--critical-profile', type=Path,
                        help='select sources by per-step exclusive eval margin from current assignment traces')
    parser.add_argument('--profile-variant', choices=('baseline', 'candidate'),
                        default='baseline', help='timing arm matching --assignment')
    parser.add_argument('--source-count', type=int,
                        help='bound profile-selected sources; requires --parts or --critical-profile')
    parser.add_argument('--partitions', type=int)
    parser.add_argument('--top', type=int, default=8)
    parser.add_argument('--targets', type=int, default=2)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--no-input-checks', action='store_true',
                        help='use fresh build outputs without hashing or identity comparisons')
    args = parser.parse_args()
    if sum((args.source is not None, args.all_sources, args.parts is not None, args.critical_profile is not None)) > 1:
        parser.error('--source, --all-sources, --parts and --critical-profile are mutually exclusive')
    if args.source_count is not None and args.parts is None and args.critical_profile is None:
        parser.error('--source-count requires --parts or --critical-profile')
    labels = list(map(int, args.assignment.read_text().split()))
    partitions = args.partitions if args.partitions is not None else max(labels, default=-1) + 1
    sources = list(range(partitions)) if args.all_sources or args.source is None else list(dict.fromkeys(args.source))
    record_input = (lambda path: {'path': str(path.resolve())}) if args.no_input_checks else identity
    inputs = {name: record_input(getattr(args, name)) for name in ('model', 'features', 'assignment')}
    profile = {}
    if args.parts is not None:
        inputs['parts'] = record_input(args.parts)
        sources, timings = profile_sources(args.parts, args.profile_variant, partitions, args.source_count)
        profile = dict(profile_variant=args.profile_variant, source_count=args.source_count,
                       profile_eval_us={str(p): timings[p]['eval'] for p in timings})
    if args.critical_profile is not None:
        inputs['critical_profile'] = record_input(args.critical_profile)
        sources, critical = critical_sources(args.critical_profile, partitions, args.source_count,
                                            check_inputs=not args.no_input_checks)
        profile = dict(source_count=args.source_count, critical_profile=critical)
    records = (propose(args.model, args.features, labels, sources, partitions, args.top, args.targets)
               if sources or args.critical_profile is None else [])
    args.output.mkdir(parents=True, exist_ok=False)
    for record in records:
        name = f"piece_{record['piece']}_p{record['source']}_to_{record['destination']}"
        moved = labels.copy()
        for atom in record['members']:
            moved[atom] = record['destination']
        dest = args.output / (name + '.assignment')
        dest.write_text(''.join(f'{label}\n' for label in moved))
        record.update(name=name, moved_atoms=len(record['members']), assignment=record_input(dest))
        del record['members']
    if not args.no_input_checks:
        for name, before in inputs.items():
            if identity(getattr(args, name)) != before:
                raise ValueError(f'{name} changed during candidate construction')
    save(args.output / 'selection.json', dict(
        status='proposals_only', inputs=inputs, partitions=partitions,
        source_mode=('profile_critical_margin' if args.critical_profile is not None else
                     'profile_top_eval' if args.parts is not None else ('explicit' if args.source is not None else 'all')),
        source_partitions=sources,
        selected_features=sorted(FEATURES), candidates=records,
        timing_used='source selection only' if args.parts is not None or args.critical_profile is not None else False,
        needs_exact_assignment_and_backend_evaluation=True, **profile))
    print(json.dumps({'candidates': len(records), 'partitions': partitions, 'output': str(args.output)}))


if __name__ == '__main__':
    main()
