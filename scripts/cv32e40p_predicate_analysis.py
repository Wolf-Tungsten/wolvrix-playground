#!/usr/bin/env python3
"""Offline accounting for predicate fusion; do not equate IR ops with instructions."""
import argparse
import csv
import json
from pathlib import Path

from cv32e40p_compare import ROOT, identity, save, summarize_named
from cv32e40p_event_regions_compare import check
from cv32e40p_structure import generated_comparisons


def analyze(out, counters):
    dest = out / 'attribution.json'
    if dest.exists(): raise FileExistsError(dest)
    manifest = check(out)
    model = out / 'grhsim_predicate_set'
    count_inputs = json.loads((counters / 'inputs.json').read_text())
    if count_inputs['model'] != manifest['binaries']['grhsim_predicate_set']:
        raise ValueError('different counter model')
    observed = json.loads((counters / 'counts.json').read_text())['coremark']
    reference = json.loads((out / 'functional.json').read_text())['workloads']['coremark']['verilator']
    if observed['cycles'] != reference['cycles'] or observed['trace']['sha256'] != reference['trace']['sha256']:
        raise ValueError('different counter workload')
    graph = json.loads((model / 'normalized.json').read_text())['graphs'][0]
    values = {v['sym']: v for v in graph['vals']}; ops = {o['sym']: o for o in graph['ops']}
    mapped = {}; groups = {}
    with (out / 'sources.csv').open() as stream:
        for row in csv.DictReader(stream):
            op = ops[row['op_symbol']]
            if op['kind'] != row['op_kind']: raise ValueError('mapping differs from graph')
            for index, name in zip(row['value_ids'].split(';'), row['value_symbols'].split(';')):
                if index: mapped[index] = name
            groups.setdefault(row['group'], dict(phase=row['phase'], batch=int(row['batch']), operations=[]))['operations'].append(row['op_symbol'])
    cycles = observed['cycles']; rates = {k: sum(v) / cycles for k, v in observed['counts'].items()}
    sites = generated_comparisons(sorted(model.glob('*_sched_*.cpp')))
    if set(sites) != {k[4:] for k in rates if k.startswith('cmp:')}:
        raise ValueError('counter/check-site mismatch')
    rows = []
    for index, site in sites.items():
        value = values[mapped[index]]; op = ops[value['def']]
        rows.append(dict(id=index, value=value['sym'], kind=op['kind'],
            new_interval_expression=op.get('loc', {}).get('pass') == 'predicate-set',
            comparisons=rates['cmp:' + index], changes=rates['chg:' + index], **site))
    for field, aggregate in [('comparisons', 'scalar_comparisons'), ('changes', 'scalar_changes')]:
        if abs(sum(r[field] for r in rows) - rates[aggregate]) > 1e-8:
            raise ValueError('per-value accounting mismatch')
    baseline_path = ROOT / 'build/cv32e40p/event-regions-review-v1/report.json'
    baseline = json.loads(baseline_path.read_text())
    old = {r['value']: r for r in baseline['values']}; new = {r['value']: r for r in rows}
    # Only names already present in the unscheduled input graph have stable
    # identity across scheduling. Fresh clone names must not be paired by ID.
    stable = {v['sym'] for v in json.loads((out / 'control.json').read_text())['graphs'][0]['vals']}
    common = old.keys() & new.keys() & stable
    removed = old.keys() - common; added = new.keys() - common
    delta = [dict(value=k, before=old[k]['comparisons'], after=new[k]['comparisons'],
        delta=new[k]['comparisons']-old[k]['comparisons'], old_group=old[k]['group'], new_group=new[k]['group'],
        old_kind=old[k]['kind'], new_kind=new[k]['kind']) for k in sorted(common)]
    removed_rate = sum(old[k]['comparisons'] for k in removed)
    added_rate = sum(new[k]['comparisons'] for k in added)
    retained_delta = sum(r['delta'] for r in delta)
    if abs(baseline['total']['comparisons'] - removed_rate + added_rate + retained_delta - rates['scalar_comparisons']) > 1e-8:
        raise ValueError('before/after accounting mismatch')
    pmu = {}
    for backend in manifest['binaries']:
        with (out / (backend + '-stat.csv')).open() as stream:
            pmu[backend] = {r[2]: int(r[0]) / cycles for r in csv.reader(stream) if len(r) > 2 and r[2].endswith(':u')}
        pmu[backend]['ipc'] = pmu[backend]['instructions:u'] / pmu[backend]['cycles:u']
    for group, data in groups.items(): data['executions_by_phase'] = [n / cycles for n in observed['counts']['group:' + group]]
    result = dict(scope='Diagnostic execution counts and independent PMU samples; unchanged input-value names are paired, not graph-local numeric IDs.',
        baseline_changes=baseline['total'], candidate_changes=dict(values=len(rows), comparisons=rates['scalar_comparisons'], changes=rates['scalar_changes']),
        new_interval_boundaries=dict(values=sum(r['new_interval_expression'] for r in rows),
            comparisons=sum(r['comparisons'] for r in rows if r['new_interval_expression']),
            changes=sum(r['changes'] for r in rows if r['new_interval_expression'])),
        comparison_accounting=dict(removed_or_unmatched_values=len(removed), added_or_unmatched_values=len(added),
            removed_previous_comparisons=removed_rate, added_new_comparisons=added_rate,
            retained_comparison_delta=retained_delta, retained=sorted(delta, key=lambda r: -r['delta'])),
        counters={k: [n / cycles for n in v] for k, v in observed['counts'].items()
            if k.startswith(('round', 'scalar_', 'direct_active_or_'))},
        groups=groups, pmu=pmu, values=rows,
        baseline_vs_verilator=summarize_named(json.loads((out / 'pairs.json').read_text()), 'grhsim_event_regions', 'verilator'),
        references=[identity(p) for p in (out / 'build.json', out / 'functional.json', out / 'sources.csv', model / 'normalized.json',
            out / 'pairs.json', counters / 'inputs.json', counters / 'counts.json', baseline_path, Path(__file__).resolve())])
    save(dest, result)
    print(json.dumps({k: result[k] for k in ('candidate_changes', 'new_interval_boundaries', 'pmu')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--counts', type=Path, required=True)
    args = parser.parse_args(); analyze(args.output.resolve(), args.counts.resolve())
