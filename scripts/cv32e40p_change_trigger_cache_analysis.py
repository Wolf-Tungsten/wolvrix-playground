#!/usr/bin/env python3
"""Attribute a fixed change-trigger cache experiment, including notifier work."""
import argparse
import csv
import json
from pathlib import Path
import re

from cv32e40p_compare import ROOT, identity, save
from cv32e40p_change_trigger_cache_compare import BASE_BACKEND, CANDIDATE, change_sites
from cv32e40p_event_regions_compare import check
from cv32e40p_mux_input_cache_analysis import compare_work
from cv32e40p_repair_analysis import analyze as repair_analysis
from cv32e40p_repair_compare import cone_sites


def analyze(out, counts):
    check(out)
    directories = {BASE_BACKEND: ROOT / 'build/cv32e40p/mux-input-cache-counts-v1', CANDIDATE: counts}
    if identity(out / CANDIDATE / 'normalized.json')['sha256'] != identity(out / BASE_BACKEND / 'normalized.json')['sha256']:
        raise ValueError('graph identity mismatch')
    with (out / 'sources.csv').open() as stream:
        ops = {int(row['op_id']): row for row in csv.DictReader(stream)}
    sizes = {root: (a, b) for root, a, b in cone_sites(out / CANDIDATE)}
    indexes = {}
    for path in (out / CANDIDATE).glob('*_sched_*.cpp'):
        for root, index in re.findall(r'Conditional mux change-trigger cache: root=(\d+) sources=\d+\s+if \(conditional_mux_change_dirty_\[(\d+)u\]\)', path.read_text()):
            indexes[int(root)] = index
    cones = []
    for site in change_sites(out / CANDIDATE):
        op = ops[site['root']]; a, b = sizes[site['root']]
        cones.append(dict(**site, result=int(op['value_ids']), symbol=op['value_symbols'],
                          group=int(op['group']), true_ops=a, false_ops=b))
    if not cones: raise ValueError('no change-trigger cache sites')
    old, new = [json.loads((directories[name] / 'counts.json').read_text())['coremark']
                for name in (BASE_BACKEND, CANDIDATE)]
    result = compare_work(old, new, cones)
    for key, value in old['counts'].items():
        if key.startswith(('mux_cache_visits:', 'mux_cache_misses:')) and value != new['counts'].get(key):
            raise ValueError('retained exact-key cache changed')
    for cone in result['cones']:
        index = indexes[cone['root']]
        visits = new['counts']['mux_invalidate_visits:' + index]
        changes = new['counts']['mux_invalidations:' + index]
        if any(not 0 <= b <= a for a, b in zip(visits, changes)):
            raise ValueError('invalid notifier accounting')
        cone['notification_sites_executed_per_cycle'] = sum(visits) / new['cycles']
        cone['changed_source_notifications_per_cycle'] = sum(changes) / new['cycles']
    result['limits'] = ('IR operations count private arm operations plus root mux, not retired instructions. '
                        'Notifier visits count generated dirty-mark sites, including writes of an unchanged dirty bit. '
                        'Actual notifications can coalesce before one cache miss; they are not additional region activations. '
                        'Diagnostic counts are excluded from performance samples.')
    result['inputs'] = [identity(path) for path in (out / 'build.json', out / 'sources.csv',
        *(directory / 'counts.json' for directory in directories.values()), Path(__file__).resolve())]
    repair_analysis(out, directories, retained_backend=BASE_BACKEND)
    save(out / 'cache-attribution.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--counts', type=Path, required=True)
    args = parser.parse_args()
    analyze(args.source.resolve(), args.counts.resolve())
