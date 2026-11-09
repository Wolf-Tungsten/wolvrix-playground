#!/usr/bin/env python3
"""Summarize ordinary/grouped multiply fixture structure and paired timings."""
import argparse
import json
from pathlib import Path

KINDS = ('int-mul', 'vec-int-mul', 'fp-mul', 'vec-fp-mul')
SCENARIOS = ('active', 'sparse', 'idle')


def load_summary(path, kind, scenario):
    p = Path(path) / kind / (scenario + '-pairs.json')
    if not p.is_file():
        return None
    rows = json.loads(p.read_text())
    deltas = [100 * (r['B']['host_ms'] / r['A']['host_ms'] - 1) for r in rows]
    # Keep the same fixed seed/bootstrap convention as grhsim_single_compare.
    import random
    import statistics
    rng = random.Random(20261102)
    boot = sorted(statistics.mean(rng.choices(deltas, k=len(deltas))) for _ in range(10000))
    return {
        'pairs': len(rows),
        'mean_percent': statistics.mean(deltas),
        'median_percent': statistics.median(deltas),
        'ci95_percent': [boot[249], boot[9749]],
        'candidate_faster_pairs': sum(x < 0 for x in deltas),
        'baseline_s_mean': statistics.mean(r['A']['host_ms'] for r in rows) / 1000,
        'candidate_s_mean': statistics.mean(r['B']['host_ms'] for r in rows) / 1000,
        'pairs_file': str(p),
    }


def structure(study, kind, label):
    dest = Path(study) / kind / label
    model = dest / 'model'
    sched = json.loads((model / 'activity_schedule_supernode_stats.json').read_text())
    manifest = json.loads((dest / 'model-manifest.json').read_text())
    return {
        'binary': {'path': str(model / 'check'), 'bytes': (model / 'check').stat().st_size},
        'cpp_bytes': sum(p.stat().st_size for p in model.glob('*.cpp')),
        'cpp_files': len(list(model.glob('*.cpp'))),
        'graph_ops': sched.get('graph_ops'),
        'supernodes': sched.get('supernodes'),
        'compute_supernodes': sched.get('compute_supernodes'),
        'state_read_activation_edges': sched.get('state_read_activation_edges'),
        'manifest_records': len(manifest),
        'simulation_manifest': str(model / 'simulation_model_manifest.json'),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--ordinary', type=Path, required=True)
    p.add_argument('--grouped', type=Path, required=True)
    p.add_argument('--measure-ordinary', type=Path, required=True)
    p.add_argument('--measure-grouped', type=Path, required=True)
    p.add_argument('--measure-direct', type=Path, required=True)
    p.add_argument('--direct-extra', type=Path, action='append', default=[])
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    report = {
        'version': 1,
        'scope': 'multiply fixture; hardware vs ordinary/grouped and ordinary vs grouped',
        'variants': {}, 'hardware_comparison': {}, 'direct_comparison': {},
        'artifacts': {
            'ordinary_study': str(args.ordinary), 'grouped_study': str(args.grouped),
            'measure_ordinary': str(args.measure_ordinary),
            'measure_grouped': str(args.measure_grouped),
            'measure_direct': str(args.measure_direct),
            'direct_extra': [str(x) for x in args.direct_extra],
        },
    }
    for name, study in [('ordinary', args.ordinary), ('grouped', args.grouped)]:
        report['variants'][name] = {kind: {label: structure(study, kind, label)
                                           for label in ('A', 'B')} for kind in KINDS}
    for kind in KINDS:
        report['hardware_comparison'][kind] = {}
        for scenario in SCENARIOS:
            o = load_summary(args.measure_ordinary, kind, scenario)
            g = load_summary(args.measure_grouped, kind, scenario)
            if o is not None: report['hardware_comparison'][kind].setdefault('ordinary', {})[scenario] = o
            if g is not None: report['hardware_comparison'][kind].setdefault('grouped', {})[scenario] = g
        report['direct_comparison'][kind] = {}
        for scenario in SCENARIOS:
            found = None
            for path in [args.measure_direct, *args.direct_extra]:
                candidate = load_summary(path, kind, scenario)
                if candidate is not None:
                    found = candidate; break
            if found is not None:
                report['direct_comparison'][kind][scenario] = found
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(args.output)


if __name__ == '__main__':
    main()
