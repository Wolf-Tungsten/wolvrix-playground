#!/usr/bin/env python3
"""Compare actual changed-copy activity, including equal-size packet repacking.

Join each static packet by owner and complete reader set, not generated input
indices or process addresses. Optional assignment layouts audit this join and
identify exactly the packets that changed. Counts describe software payload
copies; they are not bus traffic, executed instructions, or a time model.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path

from repcut_grhsim_plan_gate import identity

COUNT_NAMES = ('calls', 'scalar', 'blocks', 'tails', 'bytes')
PHASES = {'all': (0, 1), 'clock0': (0,), 'clock1': (1,)}


def _add(left, right):
    for index, value in enumerate(right):
        left[index] += value


def _record(key, baseline, candidate):
    return dict(key=list(key), baseline=dict(zip(COUNT_NAMES, baseline)),
                candidate=dict(zip(COUNT_NAMES, candidate)),
                delta=dict(zip(COUNT_NAMES, (b - a for a, b in zip(baseline, candidate)))))


def _load_activity(diagnosis: Path, variant: str) -> dict:
    sites_path = diagnosis / variant / 'traffic/sites.json'
    sites = json.loads(sites_path.read_text())
    files = sorted((diagnosis / 'runs').glob(f'traffic-*-{variant}.edges.json'))
    if len(files) < 2:
        raise ValueError('need at least two independently collected traffic runs')
    first = None
    for path in files:
        record = json.loads(path.read_text())
        if record.get('status') != 'pass':
            raise ValueError('traffic run is not complete')
        steps = record['phase_steps']
        if (len(steps) != 4 or any(type(n) is not int or n < 0 for n in steps)
                or sum(steps) != record['steps'] or sum(steps[:2]) <= 0):
            raise ValueError('invalid traffic phase counts')
        if len(sites) != len(record['edges']):
            raise ValueError('site/edge count mismatch')
        for index, edge in enumerate(record['edges']):
            site = sites[index]
            if (edge['id'] != index or site['id'] != index
                    or any(edge[k] != site[k] for k in ('sender', 'receiver', 'tracked'))):
                raise ValueError('site/edge identity mismatch')
            counts = edge['counts']
            if (len(counts) != 4 or any(len(row) != len(COUNT_NAMES) or
                    any(type(n) is not int or n < 0 for n in row) for row in counts)):
                raise ValueError('invalid edge counters')
            size = edge['bytes']
            if size <= 0 or (site['words'] is not None and site['words'] * 8 != size):
                raise ValueError('site/edge byte size mismatch')
            for phase, (calls, scalar, blocks, tails, copied) in enumerate(counts):
                if calls > steps[phase]:
                    raise ValueError('changed calls exceed phase steps')
                if site['words'] is None:
                    valid = scalar == calls and blocks == tails == 0 and copied == calls * size
                else:
                    valid = (scalar == 0 and calls <= blocks + tails and tails <= calls
                             and blocks <= calls * (size // 64)
                             and (not tails or size % 64)
                             and copied == blocks * 64 + tails * (size % 64))
                if not valid:
                    raise ValueError('counter payload accounting mismatch')
        signature = [(e['id'], e['sender'], e['receiver'], e['bytes'], e['tracked'], e['counts'])
                     for e in record['edges']]
        if first is not None and (signature != first_signature or steps != first['phase_steps']):
            raise ValueError('traffic signature is not repeated')
        if first is None:
            first, first_signature = record, signature

    groups = {phase: {level: defaultdict(lambda: [0] * 5)
                      for level in ('pair', 'coarse', 'source')}
              for phase in PHASES}
    fanout = defaultdict(list)
    for site, edge in zip(sites, first['edges']):
        coarse = (edge['sender'], edge['receiver'], site['helper'], edge['bytes'])
        keys = {'pair': coarse[:2], 'coarse': coarse, 'source': (*coarse, site['src'])}
        for phase, indices in PHASES.items():
            counts = [sum(edge['counts'][p][i] for p in indices) for i in range(5)]
            for level, key in keys.items():
                _add(groups[phase][level][key], counts)
        fanout[edge['sender'], site['src']].append((site, edge))
    bundles = {}
    for (owner, src), rows in fanout.items():
        readers = tuple(sorted(e['receiver'] for _, e in rows))
        key = owner, readers
        if len(set(readers)) != len(readers) or key in bundles:
            raise ValueError('ambiguous owner/reader-set packet join')
        sizes = {e['bytes'] for _, e in rows}
        if len(sizes) != 1:
            raise ValueError('fanout payload sizes differ')
        bundles[key] = dict(src=src, bytes=sizes.pop(), receivers={
            str(e['receiver']): dict(helper=s['helper'], dst=s['dst'], tracked=s['tracked'],
                                    counts=e['counts']) for s, e in rows})
    totals = {phase: [sum(values[i] for values in groups[phase]['pair'].values())
                      for i in range(5)] for phase in PHASES}
    return dict(variant=variant, active_steps=sum(first['phase_steps'][:2]),
                phase_steps=first['phase_steps'], edge_count=len(sites),
                traffic_signature_repeated=True,
                inputs={'sites': identity(sites_path), 'runs': [identity(p) for p in files]},
                total=dict(zip(COUNT_NAMES, totals['all'])), totals=totals,
                groups=groups, bundles=bundles)


def _changes(left, right, limit):
    rows = []
    for key in left.keys() | right.keys():
        a, b = left.get(key, [0] * 5), right.get(key, [0] * 5)
        if a != b:
            rows.append(_record(key, a, b))
    rows.sort(key=lambda r: (-abs(r['delta']['bytes']), -abs(r['delta']['calls']), r['key']))
    return dict(changed_count=len(rows), truncated=len(rows) > limit, rows=rows[:limit])


def _audit_layout(activity, layout):
    if activity['bundles'].keys() != layout.keys():
        raise ValueError('assignment and generated packet sets differ')
    for key, (width, _) in layout.items():
        expected = (1 if width <= 8 else 2 if width <= 16 else 4 if width <= 32
                    else 8 if width <= 64 else ((width + 63) // 64) * 8)
        if activity['bundles'][key]['bytes'] != expected:
            raise ValueError('assignment and generated packet widths differ')


def compare(baseline_diagnosis: Path, candidate_diagnosis: Path, baseline_layout: Path | None,
            candidate_layout: Path | None, endpoints: list[int], limit: int,
            baseline_variant='baseline', candidate_variant='candidate') -> dict:
    baseline = _load_activity(baseline_diagnosis, baseline_variant)
    candidate = _load_activity(candidate_diagnosis, candidate_variant)
    if baseline['phase_steps'] != candidate['phase_steps']:
        raise ValueError('baseline/candidate phase-step counts differ')
    public = lambda a: {k: v for k, v in a.items() if k not in ('groups', 'bundles', 'totals')}
    report = dict(schema_version=2, status='pass', diagnostic_only=True,
                  scope='changed software payload copies; reset excluded; not PMU traffic or compute activity',
                  baseline=public(baseline), candidate=public(candidate),
                  totals=_record(('all',), baseline['totals']['all'], candidate['totals']['all']),
                  phases={phase: dict(
                      steps=sum(baseline['phase_steps'][p] for p in indices),
                      totals=_record((phase,), baseline['totals'][phase], candidate['totals'][phase]),
                      changes={level: _changes(baseline['groups'][phase][level],
                                               candidate['groups'][phase][level], limit)
                               for level in ('pair', 'coarse', 'source')})
                      for phase, indices in PHASES.items()},
                  source_key_caveat='generated output indices are variant-local; source keys are explanatory, not semantic identity')
    if bool(baseline_layout) != bool(candidate_layout):
        raise ValueError('both assignment layouts are required')
    if baseline_layout:
        from repcut_grhsim_piece_splits import load_transfer_layout, transfer_impact
        before, after = load_transfer_layout(baseline_layout), load_transfer_layout(candidate_layout)
        _audit_layout(baseline, before)
        _audit_layout(candidate, after)
        impact = transfer_impact(before, after, endpoints)
        rows = []
        for change in impact['changed_transfer_bundles']:
            key = change['owner'], tuple(change['readers'])
            a, b = baseline['bundles'].get(key), candidate['bundles'].get(key)
            rows.append({**change, 'baseline': a, 'candidate': b})
        report['layout_impact'] = {**impact, 'packet_join_audited': True,
                                  'changed_bundle_activity': rows,
                                  'inputs': {'baseline': identity(baseline_layout),
                                             'candidate': identity(candidate_layout)}}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline-diagnosis', 'candidate-diagnosis', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('baseline-layout', 'candidate-layout'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--baseline-variant', default='baseline')
    parser.add_argument('--candidate-variant', default='candidate')
    parser.add_argument('--endpoints', type=int, nargs='*', default=[])
    parser.add_argument('--limit', type=int, default=200)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit must be positive')
    result = compare(args.baseline_diagnosis, args.candidate_diagnosis,
                     args.baseline_layout, args.candidate_layout, args.endpoints,
                     args.limit, args.baseline_variant, args.candidate_variant)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': 'pass', 'totals': result['totals'],
                      'pair_changes': result['phases']['all']['changes']['pair']['changed_count']}))


if __name__ == '__main__':
    main()
