#!/usr/bin/env python3
"""Summarize actual per-step critical lanes from wrapper-only cycle traces.

The exclusive margin is max(eval) - max(eval without this lane), averaged over
steps. It bounds the removable eval-body time on this trace when other lanes
are fixed; it does not predict a changed assignment or global walltime.
"""
from __future__ import annotations

import argparse
from array import array
import json
from pathlib import Path
import struct
import sys

from repcut_grhsim_plan_gate import identity


def project_eval(paths: list[Path], candidates: dict[str, dict[int, float]], partitions: int,
                 additions: dict[str, dict[int, dict[int, float]]] | None = None) -> dict:
    """Apply structural scale proposals to per-step times, preserving phase overlap.

    Only listed lanes change in this estimate. Actual lowering and communication
    can affect other lanes, so runtime verification remains necessary.
    Optional additions carry donor activity into a destination at the same
    step. Take the maximum of that additive estimate and the lane-scaled one.
    Neither estimate observes individual piece activity or bounds real time.
    """
    if not paths or len({p.resolve() for p in paths}) != len(paths):
        raise ValueError('expected nonempty, distinct trace paths')
    if not candidates or any(not scales or any(p < 0 or p >= partitions for p in scales)
                             for scales in candidates.values()):
        raise ValueError('invalid candidate lane scales')
    import math
    if any(not math.isfinite(s) or s < 0 for scales in candidates.values() for s in scales.values()):
        raise ValueError('invalid candidate scale')
    additions = additions or {}
    if any(name not in candidates for name in additions):
        raise ValueError('unknown candidate in activity additions')
    for name, destinations in additions.items():
        for destination, donors in destinations.items():
            if destination not in candidates[name] or not donors:
                raise ValueError('activity destination must have a lane scale')
            if any(p < 0 or p >= partitions or not math.isfinite(weight) or weight < 0
                   for p, weight in donors.items()):
                raise ValueError('invalid activity donor or coefficient')
    totals = {name: 0.0 for name in candidates}
    phase_totals = {name: [0.0, 0.0] for name in candidates}
    baseline = 0
    baseline_phases = [0, 0]
    counts = [0, 0]
    # At least one of the first len(changed)+1 lanes is unchanged.
    depth = min(partitions, 1 + max(len(s) for s in candidates.values()))
    for path in paths:
        raw = path.read_bytes()
        if len(raw) < 24 or raw[:8] != b'GRHCYC01':
            raise ValueError('invalid cycle trace header')
        version, steps, parts, fields = struct.unpack_from('<4I', raw, 8)
        if version != 1 or parts != partitions or fields != 3 or len(raw) != 24 + steps * 4 * (4 + parts * fields):
            raise ValueError('invalid cycle trace shape')
        values = array('I')
        values.frombytes(raw[24:])
        if sys.byteorder != 'little':
            values.byteswap()
        if 0xffffffff in values or any(values[4 * i] > 3 for i in range(steps)):
            raise ValueError('invalid or missing cycle trace values')
        flags = values[:4 * steps:4]
        evals = [values[steps * (4 + p * fields) + 1:steps * (4 + (p + 1) * fields):fields]
                 for p in range(parts)]
        kept = [i for i, f in enumerate(flags) if not f & 2]
        top = [array('I') for _ in range(depth)]
        for i in kept:
            winners = sorted(range(parts), key=lambda p: evals[p][i], reverse=True)[:depth]
            for col, p in zip(top, winners):
                col.append(p)
            baseline += evals[winners[0]][i]
            baseline_phases[flags[i]] += evals[winners[0]][i]
            counts[flags[i]] += 1
        for name, scales in candidates.items():
            changed = [(p, scale, list(additions.get(name, {}).get(p, {}).items()))
                       for p, scale in scales.items()]
            acc = phase_totals[name]
            for j, i in enumerate(kept):
                peak = next((evals[col[j]][i] for col in top if col[j] not in scales), 0)
                for p, scale, donors in changed:
                    adjusted = evals[p][i] * scale
                    if donors:
                        transferred = evals[p][i] + sum(evals[donor][i] * weight
                                                       for donor, weight in donors)
                        adjusted = max(adjusted, transferred)
                    peak = max(peak, adjusted)
                acc[flags[i]] += peak
    steps = sum(counts)
    if not steps:
        raise ValueError('no non-reset steps')
    for name, acc in phase_totals.items():
        totals[name] = {'mean_step_max_us': sum(acc) / steps / 1000,
                        'clock_levels': {str(k): acc[k] / n / 1000 for k, n in enumerate(counts) if n}}
    return {'baseline_mean_step_max_us': baseline / steps / 1000,
            'baseline_clock_levels': {str(k): baseline_phases[k] / n / 1000
                                      for k, n in enumerate(counts) if n},
            'steps': steps, 'candidates': totals}


def summarize(paths: list[Path], check_inputs: bool = True) -> dict:
    if not paths or len({p.resolve() for p in paths}) != len(paths):
        raise ValueError('expected nonempty, distinct trace paths')
    inputs = [identity(p) if check_inputs else {'path': str(p.resolve())} for p in paths]
    phases = {}
    parts = None
    for path in paths:
        raw = path.read_bytes()
        if len(raw) < 24 or raw[:8] != b'GRHCYC01':
            raise ValueError(f'invalid cycle trace header: {path}')
        version, steps, count, fields = struct.unpack_from('<4I', raw, 8)
        if version != 1 or not steps or count < 2 or fields != 3:
            raise ValueError('unsupported cycle trace shape')
        if parts is not None and parts != count:
            raise ValueError('trace partition sets differ')
        parts = count
        if len(raw) != 24 + 4 * steps * (4 + count * fields):
            raise ValueError('truncated or extended cycle trace')
        values = array('I')
        values.frombytes(raw[24:])
        if sys.byteorder != 'little':
            values.byteswap()
        if 0xffffffff in values:
            raise ValueError('cycle trace contains missing/overflowed values')
        if any(values[4 * step] > 3 for step in range(steps)):
            raise ValueError('invalid clock/reset flags')
        offsets = [steps * (4 + p * fields) for p in range(parts)]
        for step in range(steps):
            flag = values[4 * step]
            if flag & 2:
                continue
            data = phases.setdefault(str(flag), {
                'steps': 0, 'eval': {'sum_ns': [0] * parts, 'winner_counts': [0] * parts,
                                   'winner_sum_ns': [0] * parts,
                                   'exclusive_margin_ns': [0] * parts, 'max_sum_ns': 0},
                'update': {'sum_ns': [0] * parts, 'winner_counts': [0] * parts,
                           'winner_sum_ns': [0] * parts,
                           'exclusive_margin_ns': [0] * parts, 'max_sum_ns': 0},
            })
            data['steps'] += 1
            for kind, field in (('eval', 1), ('update', 2)):
                acc = data[kind]
                first = second = -1
                winner = 0
                for p, offset in enumerate(offsets):
                    ns = values[offset + step * fields + field]
                    acc['sum_ns'][p] += ns
                    if ns > first:
                        second, first, winner = first, ns, p
                    elif ns > second:
                        second = ns
                acc['winner_counts'][winner] += 1
                acc['winner_sum_ns'][winner] += first
                acc['exclusive_margin_ns'][winner] += first - second
                acc['max_sum_ns'] += first
    if not phases:
        raise ValueError('no non-reset steps')
    aggregate = {'steps': sum(d['steps'] for d in phases.values())}
    for kind in ('eval', 'update'):
        aggregate[kind] = {key: [sum(d[kind][key][p] for d in phases.values()) for p in range(parts)]
                           for key in ('sum_ns', 'winner_counts', 'winner_sum_ns', 'exclusive_margin_ns')}
        aggregate[kind]['max_sum_ns'] = sum(d[kind]['max_sum_ns'] for d in phases.values())

    def finish(data):
        steps = data['steps']
        return {'steps': steps, **{kind: {
            'mean_step_max_us': data[kind]['max_sum_ns'] / steps / 1000,
            'max_partition_mean_us': max(data[kind]['sum_ns']) / steps / 1000,
            'parts': [{'part': p, 'mean_us': data[kind]['sum_ns'][p] / steps / 1000,
                       'bottleneck_count': data[kind]['winner_counts'][p],
                       'bottleneck_fraction': data[kind]['winner_counts'][p] / steps,
                       'bottleneck_mean_us': (data[kind]['winner_sum_ns'][p] /
                                              data[kind]['winner_counts'][p] / 1000
                                              if data[kind]['winner_counts'][p] else None),
                       'exclusive_margin_us': data[kind]['exclusive_margin_ns'][p] / steps / 1000}
                      for p in range(parts)]} for kind in ('eval', 'update')}}

    if check_inputs and inputs != [identity(p) for p in paths]:
        raise ValueError('trace changed during analysis')
    return {'schema_version': 1, 'status': 'pass', 'partition_count': parts, 'inputs': inputs,
            'reset_excluded': True, 'tie_policy': 'lowest lane wins the count; ties have zero margin',
            'scope': 'diagnostic body-time opportunity on a fixed trace; not assignment or walltime prediction',
            'all': finish(aggregate), 'clock_levels': {k: finish(d) for k, d in phases.items()}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--no-input-checks', action='store_true',
                        help='read freshly generated traces without hashing or identity comparisons')
    args = parser.parse_args()
    result = summarize(args.trace, check_inputs=not args.no_input_checks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'parts': result['partition_count'], 'steps': result['all']['steps'],
                      'eval_source_order': [x['part'] for x in sorted(result['all']['eval']['parts'],
                                          key=lambda x: (-x['exclusive_margin_us'], -x['bottleneck_count'], x['part']))]}))
