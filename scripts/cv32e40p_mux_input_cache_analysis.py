#!/usr/bin/env python3
"""Attribute avoided conditional work without changing the comparison policy."""
import argparse
import csv
import json
from pathlib import Path

from cv32e40p_compare import ROOT, identity, save
from cv32e40p_event_regions_compare import check
from cv32e40p_mux_input_cache_compare import BASE_BACKEND, CANDIDATE, cache_sites
from cv32e40p_repair_compare import cone_sites
from cv32e40p_repair_analysis import analyze as repair_analysis, counter_rates


def read(path):
    return json.loads(path.read_text())


def compare_work(old, new, cones):
    if old['cycles'] != new['cycles'] or old['trace']['sha256'] != new['trace']['sha256']:
        raise ValueError('counter workload mismatch')
    # Validate the totals before attributing individual roots.
    counter_rates(old); counter_rates(new)
    a, b, cycles = old['counts'], new['counts'], old['cycles']
    affected = {f'mux_{arm}:{c["root"]}' for c in cones for arm in ('root', 'true', 'false')}
    results = {str(c['result']) for c in cones}
    invariant_keys = {k for k in a.keys() | b.keys()
                      if k.startswith(('group:', 'chg:', 'decode_', 'mux_root:', 'mux_true:', 'mux_false:'))
                      or k == 'round'} - affected
    invariant_keys |= {k for k in a.keys() | b.keys() if k.startswith('cmp:') and k[4:] not in results}
    if any(a.get(k) != b.get(k) for k in invariant_keys):
        raise ValueError('unexplained execution or notification change')
    rows = []
    for c in cones:
        root = str(c['root']); result = str(c['result'])
        visits, misses = b['mux_cache_visits:' + root], b['mux_cache_misses:' + root]
        if visits != a['mux_root:' + root] or misses != b['mux_root:' + root]:
            raise ValueError('cache visits/misses do not match root executions')
        for phase in range(4):
            if not 0 <= misses[phase] <= visits[phase]: raise ValueError('invalid cache hit count')
            for counts in (a, b):
                if counts['mux_root:' + root][phase] != counts['mux_true:' + root][phase] + counts['mux_false:' + root][phase]:
                    raise ValueError('arm coverage mismatch')
        old_arm_runs = {arm:sum(a['mux_' + arm + ':' + root]) for arm in ('true','false')}
        new_arm_runs = {arm:sum(b['mux_' + arm + ':' + root]) for arm in ('true','false')}
        ir = {name:sum(sum(counts['mux_' + arm + ':' + root]) * (1 + c[arm + '_ops'])
                      for arm in ('true', 'false')) / cycles
              for name, counts in (('before', a), ('after', b))}
        comparisons = {name:sum(counts.get('cmp:' + result, [0]*4)) / cycles
                       for name, counts in (('before', a), ('after', b))}
        rows.append(dict(**c, visits_per_cycle=sum(visits)/cycles, misses_per_cycle=sum(misses)/cycles,
            hits_per_cycle=(sum(visits)-sum(misses))/cycles,
            arm_executions=dict(before=old_arm_runs, after=new_arm_runs), ir_operations_per_cycle=ir,
            result_comparisons_per_cycle=comparisons))
    removed = (sum(a['scalar_comparisons']) - sum(b['scalar_comparisons'])) / cycles
    attributed = sum(r['result_comparisons_per_cycle']['before'] - r['result_comparisons_per_cycle']['after'] for r in rows)
    if abs(removed-attributed) > 1e-9: raise ValueError('unattributed scalar comparisons')
    return dict(cones=rows, invariant_count=len(invariant_keys), scalar_checks_saved_per_cycle=removed,
        scalar_checks_per_cycle={name:sum(counts['scalar_comparisons'])/cycles for name,counts in (('before',a),('after',b))},
        ir_operations_saved_per_cycle=sum(r['ir_operations_per_cycle']['before']-r['ir_operations_per_cycle']['after'] for r in rows),
        limits='IR operation counts describe selected private arms and their mux, not retired instructions. Exact source checks are additional work.')


def analyze(out, counts):
    check(out)
    directories = {BASE_BACKEND:ROOT / 'build/cv32e40p/equality-families-counts-v1', CANDIDATE:counts}
    repair_analysis(out, directories, retained_backend=BASE_BACKEND)
    for name in (BASE_BACKEND, CANDIDATE):
        if identity(out / name / 'normalized.json')['sha256'] != identity(out / BASE_BACKEND / 'normalized.json')['sha256']:
            raise ValueError('cannot pair different graph IDs')
    ops = {int(r['op_id']):r for r in csv.DictReader((out / 'sources.csv').open())}
    sizes = {root:(true, false) for root,true,false in cone_sites(out / CANDIDATE)}
    cones = []
    for site in cache_sites(out / CANDIDATE):
        op = ops[site['root']]; true, false = sizes[site['root']]
        cones.append(dict(**site, result=int(op['value_ids']), symbol=op['value_symbols'],
                          group=int(op['group']), true_ops=true, false_ops=false))
    if not cones: raise ValueError('no cache sites')
    old, new = [read(directories[b] / 'counts.json')['coremark'] for b in (BASE_BACKEND, CANDIDATE)]
    result = compare_work(old, new, cones)
    result['inputs'] = [identity(p) for p in (out / 'build.json', out / 'sources.csv',
        out / CANDIDATE / 'normalized.json', *(d / 'counts.json' for d in directories.values()), Path(__file__).resolve())]
    save(out / 'cache-attribution.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--counts', type=Path, required=True)
    args = parser.parse_args()
    analyze(args.source.resolve(), args.counts.resolve())
