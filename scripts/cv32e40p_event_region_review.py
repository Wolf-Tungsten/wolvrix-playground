#!/usr/bin/env python3
"""Attribute residual activity boundaries in the frozen event-region model."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re

from cv32e40p_compare import ROOT, identity, save
from cv32e40p_structure import generated_comparisons, terminal_reachability, user_boundaries


def read(path):
    return json.loads(path.read_text())


def verify(entry):
    if identity(entry['path']) != entry:
        raise ValueError('frozen input changed: ' + entry['path'])


def summarize(rows):
    return dict(values=len(rows), check_sites=sum(len(r['check_lines']) for r in rows),
                comparisons=sum(r['comparisons'] for r in rows), changes=sum(r['changes'] for r in rows))


def analyze(source, counts, mapping, out, backend='grhsim_event_regions'):
    if out.exists():
        raise FileExistsError('use a new report path')
    manifest = read(source / 'build.json')
    for entry in manifest['binaries'].values():
        verify(entry)
    structure = read(source / 'structure.json')
    for entry in structure['emitted_sources']:
        verify(entry)
    observed_inputs = read(counts / 'inputs.json')
    if observed_inputs['model'] != manifest['binaries'][backend]:
        raise ValueError('counts describe another production binary')
    for entry in observed_inputs['counter_sources']:
        verify(entry)
    observed = read(counts / 'counts.json')['coremark']
    reference = read(source / 'verification.json')['workloads']['coremark']['verilator']
    if observed['cycles'] != reference['cycles'] or observed['trace']['sha256'] != reference['trace']['sha256']:
        raise ValueError('counter workload differs from verified CoreMark')
    model = source / backend
    graph = read(model / 'normalized.json')['graphs'][0]
    values = {v['sym']: v for v in graph['vals']}
    ops = {o['sym']: o for o in graph['ops']}
    with mapping.open() as stream:
        schedule = {row['op_symbol']: row for row in csv.DictReader(stream)}
    mapped_values, groups = {}, defaultdict(list)
    for symbol, row in schedule.items():
        op = ops[symbol]
        if op['kind'] != row['op_kind'] or op['out'] != list(filter(None, row['value_symbols'].split(';'))):
            raise ValueError('mapping disagrees with graph: ' + symbol)
        for index, name in zip(row['value_ids'].split(';'), row['value_symbols'].split(';')):
            if index:
                mapped_values[index] = name
        groups[int(row['group'])].append(row)
    code = generated_comparisons(sorted(model.glob('*_sched_*.cpp')))
    if set(code) != {k[4:] for k in observed['counts'] if k.startswith('cmp:')}:
        raise ValueError('per-value counter set differs from generated comparison sites')
    events = set()
    for op in ops.values():
        edges = op.get('attrs', {}).get('eventEdge', {}).get('vs', [])
        if edges:
            events.update(op['in'][-len(edges):])
    terminals = terminal_reachability(values, ops, schedule,
        {p['val']: p['name'] for p in graph['ports']['out']})
    cycles = observed['cycles']
    rates = {k: sum(v) / cycles for k, v in observed['counts'].items()}
    rows = []
    for index, check in code.items():
        value = values[mapped_values[index]]
        op = ops[value['def']]
        where = schedule[op['sym']]
        if int(where['group']) != check['group']:
            raise ValueError('mapping disagrees with generated group: ' + index)
        row = dict(id=index, value=value['sym'], width=value['w'], kind=op['kind'], **check,
                   comparisons=rates['cmp:' + index], changes=rates['chg:' + index],
                   source=op.get('loc'), terminals=sorted(terminals(value['sym'])),
                   **user_boundaries(value, check['group'], schedule, events))
        if op['kind'] == 'kSliceStatic':
            producer = ops.get(values[op['in'][0]].get('def'), {})
            if producer.get('kind') == 'kRegisterReadPort':
                row['state_source'] = producer['attrs']['regSymbol']['v']
        rows.append(row)
    for name, aggregate in [('comparisons', 'scalar_comparisons'), ('changes', 'scalar_changes')]:
        if abs(sum(r[name] for r in rows) - rates[aggregate]) > 1e-8:
            raise ValueError('per-value rates do not sum to the aggregate')
    categories = {}
    for key in ('kind', 'width', 'state_source'):
        categories[key] = {str(v): summarize([r for r in rows if r.get(key) == v])
                           for v in sorted({r[key] for r in rows if key in r})}
    endpoints = defaultdict(list)
    for row in rows:
        endpoints[tuple(row['terminals'])].append(row)
    group_summary = []
    for group, operations in sorted(groups.items()):
        group_summary.append(dict(group=group, phase=operations[0]['phase'], batch=int(operations[0]['batch']),
            operations=len(operations), kinds=dict(Counter(o['op_kind'] for o in operations)),
            executions_by_phase=[n / cycles for n in observed['counts']['group:' + str(group)]],
            **summarize([r for r in rows if r['group'] == group])))
    # Logical equalities that became local no longer appear in change-check
    # counters. Keep their source stability and region frequency visible.
    families = defaultdict(list)
    by_value = {r['value']: r for r in rows}
    for symbol, where in schedule.items():
        op = ops[symbol]
        if op['kind'] != 'kEq' or len(op['in']) != 2:
            continue
        constants = [v for v in op['in'] if ops.get(values[v].get('def'), {}).get('kind') == 'kConstant']
        if len(constants) != 1:
            continue
        variable = next(v for v in op['in'] if v != constants[0])
        if op['out'][0] not in by_value:
            families[(variable, int(where['group']))].append(op['sym'])
    decoder_families = []
    for (variable, group), members in families.items():
        if len(members) < 16:
            continue
        tracked = by_value.get(variable)
        decoder_families.append(dict(source=variable, width=values[variable]['w'], group=group,
            predicates=len(members), operations=members,
            region_executions=rates['group:' + str(group)],
            source_changes=tracked['changes'] if tracked else None,
            source_value_id=tracked['id'] if tracked else None,
            logical_equality_work_proxy=len(members) * rates['group:' + str(group)],
            scope='IR operations times measured group executions; not a retired instruction count'))
    report = dict(scope='Current event-region model versus the same normalized-RTL Verilator; diagnostic counts, not timing',
        cycles=cycles, phases=observed_inputs['phases'],
        rounds=[n / cycles for n in observed['counts']['round']],
        total=summarize(rows), categories=categories,
        compute_boundary_only=summarize([r for r in rows if r['compute_boundary_only']]),
        terminal_sets=sorted([dict(terminals=t, **summarize(r)) for t, r in endpoints.items()],
                             key=lambda r: -r['comparisons']),
        local_decoder_families=decoder_families, groups=group_summary, values=rows,
        inputs=[identity(p) for p in [source / 'build.json', source / 'structure.json',
            model / 'normalized.json', counts / 'inputs.json', counts / 'counts.json', mapping,
            ROOT / 'testcase/cv32e40p-bench/map.cpp', ROOT / 'build/cv32e40p/tools/cv32e40p_map',
            ROOT / 'build/cv32e40p/tools/grhsim32/wolvrix/libwolvrix-lib.so', Path(__file__).resolve()]])
    save(out, report)
    print(json.dumps({k: report[k] for k in ('total', 'categories', 'compute_boundary_only', 'terminal_sets')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--counts', type=Path, required=True)
    parser.add_argument('--mapping', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--backend', default='grhsim_event_regions')
    args = parser.parse_args()
    analyze(args.source.resolve(), args.counts.resolve(), args.mapping.resolve(), args.output.resolve(), args.backend)
