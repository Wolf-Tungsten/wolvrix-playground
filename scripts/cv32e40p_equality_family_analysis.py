#!/usr/bin/env python3
"""Verify sparse-cache work and unchanged activation with matched graph IDs."""
import argparse
import csv
import json
from pathlib import Path
import re

from cv32e40p_compare import ROOT, identity, save
from cv32e40p_event_regions_compare import check
from cv32e40p_repair_analysis import analyze as repair_analysis, counter_rates
from cv32e40p_equality_family_compare import BASE_BACKEND, CONTROL_BACKEND, CANDIDATE


def read(path):
    return json.loads(path.read_text())


def parse_families(text):
    pattern = (r'// Shared equality family: source=(\d+) predicates=(\d+)\n'
               r'.*?auto &grhsim_eq_cache_(\d+) = shared_equality_cache_\[\3u\];'
               r'(.*?)grhsim_eq_cache_\3\.previous = grhsim_eq_address_\3;')
    result = []
    for source, count, cache, body in re.findall(pattern, text, re.S):
        ids = sorted(set(re.findall(r'const bool grhsim_changed_(\d+) =', body)), key=int)
        if len(ids) != int(count): raise ValueError('family predicate coverage mismatch')
        result.append(dict(source=source, cache=cache, ids=ids))
    if len(result) != text.count('// Shared equality family:'):
        raise ValueError('unparsed family')
    return result


def analyze(out, counts):
    manifest = check(out)
    directories = {CANDIDATE:counts,
        CONTROL_BACKEND:ROOT / 'build/cv32e40p/region-order-before-counts-v1',
        BASE_BACKEND:ROOT / 'build/cv32e40p/conditional-mux-counts-v4'}
    repair_analysis(out, directories)
    old, new = [read(directories[b] / 'counts.json')['coremark'] for b in (CONTROL_BACKEND, CANDIDATE)]
    old_rates, rates = counter_rates(old), counter_rates(new)
    if old['trace']['sha256'] != new['trace']['sha256']: raise ValueError('trace mismatch')
    old_graph = out / CONTROL_BACKEND / 'normalized.json'
    new_graph = out / CANDIDATE / 'normalized.json'
    if identity(old_graph)['sha256'] != identity(new_graph)['sha256']: raise ValueError('graph IDs not comparable')
    mapping = {}
    for row in csv.DictReader((out / 'sources.csv').open()):
        for value, symbol in zip(row['value_ids'].split(';'), row['value_symbols'].split(';')):
            if value: mapping[value] = dict(symbol=symbol, group=int(row['group']), kind=row['op_kind'])
    families = []
    for p in sorted((out / CANDIDATE).glob('*_sched_*.cpp')):
        text = p.read_text()
        for family in parse_families(text):
            cache = family['cache']
            family.update(mapping[family['source']])
            declaration = re.search(r'const std::uint\d+_t grhsim_v' + family['source'] + r'_0 =', text)
            family['source_temporary_declaration_line'] = text.count('\n', 0, declaration.start()) + 1 if declaration else None
            family['file'] = p.name
            for field, prefix in (('comparisons','cmp:'), ('changes','chg:')):
                family[field] = {b:sum(sum(c[prefix + i]) for i in family['ids'])
                                 for b,c in ((CONTROL_BACKEND,old_rates),(CANDIDATE,rates))}
            family['source_checks'] = sum(rates['decode_visits:' + cache])
            family['initializations'] = sum(rates['decode_initializations:' + cache])
            family['source_changes'] = sum(rates['decode_address_changes:' + cache])
            family['previous_address_comparisons'] = family['source_checks'] - family['initializations']
            families.append(family)
    if not families: raise ValueError('no families')
    family_ids = {v for f in families for v in f['ids']}
    keys = {k for k in old_rates | rates if k.startswith(('group:', 'chg:', 'mux_')) or k == 'round'}
    differences = {k:dict(before=old_rates.get(k), after=rates.get(k)) for k in keys if old_rates.get(k) != rates.get(k)}
    other_comparisons = {k:dict(before=old_rates.get(k), after=rates.get(k)) for k in old_rates | rates
        if k.startswith('cmp:') and k[4:] not in family_ids and old_rates.get(k) != rates.get(k)}
    removed = sum(f['comparisons'][CONTROL_BACKEND] - f['comparisons'][CANDIDATE] for f in families)
    total_removed = sum(old_rates['scalar_comparisons']) - sum(rates['scalar_comparisons'])
    if differences or other_comparisons or abs(total_removed - removed) > 1e-9:
        raise ValueError('sparse-cache attribution has unexplained execution differences')
    result = dict(families=families, checks_saved_per_cycle=removed,
        changes_and_execution_unchanged=dict(checked=len(keys), differences=differences),
        other_comparison_differences=other_comparisons,
        candidate_scalar_checks_per_cycle=sum(rates['scalar_comparisons']),
        control_scalar_checks_per_cycle=sum(old_rates['scalar_comparisons']),
        caveat='Includes boundary old/new comparisons only; source guards are counted separately. Not machine instructions.',
        inputs=[identity(p) for p in (out / 'build.json', out / 'sources.csv', new_graph, old_graph,
            directories[CANDIDATE] / 'inputs.json', directories[CANDIDATE] / 'counts.json',
            directories[CONTROL_BACKEND] / 'inputs.json', directories[CONTROL_BACKEND] / 'counts.json', Path(__file__).resolve())])
    save(out / 'family-attribution.json', result)
    print(json.dumps({k:result[k] for k in ('families', 'checks_saved_per_cycle', 'changes_and_execution_unchanged')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--counts', type=Path, required=True)
    args = parser.parse_args()
    analyze(args.source.resolve(), args.counts.resolve())
