#!/usr/bin/env python3
"""Attribute conditional-mux work without treating IR operations as instructions."""
import argparse
import csv
import json
from pathlib import Path

from cv32e40p_compare import ROOT, identity, save, summarize_named
from cv32e40p_event_regions_compare import check


def read(path):
    return json.loads(path.read_text())


def branch_work(site, counters, cycles):
    root = str(site['root'])
    executions = sum(counters['mux_root:' + root])
    true = sum(counters['mux_true:' + root])
    false = sum(counters['mux_false:' + root])
    if true + false != executions or not cycles:
        raise ValueError('branch counts do not partition root executions')
    eager = executions * (site['true_ops'] + site['false_ops'])
    selected = true * site['true_ops'] + false * site['false_ops']
    return dict(root=site['root'], true_ops=site['true_ops'], false_ops=site['false_ops'],
        evaluations=executions, true_evaluations=true, false_evaluations=false,
        true_fraction=true / executions if executions else None,
        eager_ir_per_cycle=eager / cycles, selected_ir_per_cycle=selected / cycles,
        skipped_ir_per_cycle=(eager - selected) / cycles)


def perf_counts(path, guest_cycles):
    counts = {}
    for row in csv.reader(path.read_text().splitlines()):
        if not row or row[0].startswith('#'): continue
        if len(row) < 5 or row[2] not in ('cycles:u', 'instructions:u', 'branches:u', 'branch-misses:u'):
            continue
        if not row[0].strip().isdigit() or float(row[4]) < 99:
            raise ValueError('missing or multiplexed PMU event: ' + str(row))
        counts[row[2]] = int(row[0])
    if len(counts) != 4: raise ValueError('incomplete PMU counters')
    return dict(per_guest_cycle={k: v / guest_cycles for k, v in counts.items()},
                ipc=counts['instructions:u'] / counts['cycles:u'])


def analyze(source, diagnostic):
    manifest = check(source)
    baseline, candidate = manifest['backend_pair']
    counter_inputs = read(diagnostic / 'inputs.json')
    if counter_inputs['model'] != manifest['binaries'][candidate]:
        raise ValueError('counter model differs from measured model')
    counted = read(diagnostic / 'counts.json')['coremark']
    reference = read(source / 'functional.json')['workloads']['coremark'][candidate]
    if counted['trace']['sha256'] != reference['trace']['sha256'] or counted['cycles'] != reference['cycles']:
        raise ValueError('counter workload differs from functional gate')
    structure = read(source / 'structure.json')
    mapping = {int(x['op_id']): x for x in csv.DictReader((source / 'sources.csv').open())}
    sites = []
    for site in structure['sites']:
        work = branch_work(site, counted['counts'], counted['cycles'])
        ir = mapping[site['root']]
        work.update(group=int(ir['group']), op=ir['op_symbol'], result=ir['value_symbols'], rtl_file=ir['file'], rtl_line=int(ir['line']))
        sites.append(work)
    old_counts_path = ROOT / 'build/cv32e40p/event-regions-review-counts-v2/counts.json'
    old_inputs = read(old_counts_path.parent / 'inputs.json')
    if old_inputs['model']['sha256'] != manifest['binaries'][baseline]['sha256']:
        raise ValueError('baseline counters came from another binary')
    old = read(old_counts_path)['coremark']
    if old['trace']['sha256'] != counted['trace']['sha256']: raise ValueError('baseline counter workload drift')
    preserved = [k for k in old['counts'] if k.startswith(('group:', 'cmp:', 'chg:')) or k in ('round', 'scalar_comparisons', 'scalar_changes')]
    differences = {k: dict(baseline=old['counts'][k], candidate=counted['counts'].get(k))
                   for k in preserved if old['counts'][k] != counted['counts'].get(k)}
    pmu = {b: perf_counts(source / (b + '-stat.csv'), reference['cycles']) for b in (baseline, candidate, 'verilator')}
    baseline_instructions = pmu[baseline]['per_guest_cycle']['instructions:u']
    candidate_instructions = pmu[candidate]['per_guest_cycle']['instructions:u']
    measurements = read(source / 'pairs.json')
    result = dict(
        source=identity(source / 'build.json'), diagnostic=identity(diagnostic / 'inputs.json'),
        baseline_counts=identity(old_counts_path), driver=identity(Path(__file__).resolve()),
        inputs=[identity(p) for p in (source / 'structure.json', source / 'sources.csv',
            source / 'pairs.json', source / 'diagnostics.json', diagnostic / 'counts.json',
            *[source / (b + '-stat.csv') for b in (baseline, candidate, 'verilator')])],
        sites=sites,
        totals={k: sum(s[k] for s in sites) for k in ('eager_ir_per_cycle', 'selected_ir_per_cycle', 'skipped_ir_per_cycle')},
        counter_invariants=dict(checked=len(preserved), differences=differences),
        pmu=pmu, retired_instruction_change_percent=100 * (candidate_instructions / baseline_instructions - 1),
        baseline_relative_to_verilator=summarize_named(measurements, baseline, 'verilator'),
        limits='IR counts describe original private producers and include expressions optimized away by Clang. They are not retired instruction counts. PMU uses separate diagnostic executions, not the paired timing samples.')
    save(source / 'attribution.json', result)
    print(json.dumps(dict(totals=result['totals'], invariant_differences=differences, pmu=pmu, sites=sites), indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--counts', type=Path, required=True)
    args = p.parse_args()
    analyze(args.source.resolve(), args.counts.resolve())
