#!/usr/bin/env python3
"""Audit execution/storage boundaries in frozen CV32E40P models; no model runs."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from functools import cache
import json
from pathlib import Path
import re

from cv32e40p_compare import ROOT, identity, save

ARTIFACTS = ROOT / 'build/cv32e40p'
CURRENT = ARTIFACTS / 'shared-equality-validated'
MODEL = CURRENT / 'grhsim_shared_equality'
COUNTS = ARTIFACTS / 'shared-equality-counts-v1'
MAPPING = ARTIFACTS / 'remaining-gap-v1'
ORIGINAL = ARTIFACTS / 'run2'


def read(path):
    return json.loads(Path(path).read_text())


def verify(entry):
    actual = identity(entry['path'])
    if actual != entry:
        raise ValueError('frozen artifact changed: ' + entry['path'])


def generated_comparisons(paths):
    """Only count named scalar change checks, not guards or commit comparisons."""
    result = {}
    for path in paths:
        group = None
        for line, text in enumerate(path.read_text().splitlines(), 1):
            marker = re.search(r'// Supernode (\d+):', text)
            if marker:
                group = int(marker[1])
            match = re.search(r'const bool grhsim_changed_(\d+) =', text)
            if match:
                if group is None:
                    raise ValueError('missing group for scalar check')
                if match[1] in result:
                    prior = result[match[1]]
                    if prior['group'] != group or prior['file'] != str(path):
                        raise ValueError('scalar value checked in multiple groups')
                    # Shared-decode init, clear and set paths check the same value.
                    prior['check_lines'].append(line)
                else:
                    result[match[1]] = dict(group=group, file=str(path), line=line, check_lines=[line])
    return result


def user_boundaries(value, producer, schedule, events):
    """Deduplicate target groups; ignore unscheduled IR users, and say how many."""
    targets, commit, unmapped = set(), set(), 0
    for user in value.get('users', []):
        target = schedule.get(user['op'])
        if target is None:
            unmapped += 1
        elif target['phase'] == 'commit':
            commit.add(int(target['group']))
        elif int(target['group']) != producer:
            targets.add(int(target['group']))
    output = bool(value.get('out') or value.get('inout'))
    event = value['sym'] in events
    return dict(compute_targets=sorted(targets), commit_targets=sorted(commit),
                public_output=output, event=event, unscheduled_uses=unmapped,
                compute_boundary_only=bool(targets) and not commit and not output and not event)


def totals(rows):
    return dict(values=len(rows), source_check_sites=sum(len(r['check_lines']) for r in rows),
                comparisons_per_cycle=sum(r['comparisons'] for r in rows),
                changes_per_cycle=sum(r['changes'] for r in rows))


def terminal_reachability(values, ops, schedule, outputs):
    """Follow scheduled def-use only; stop at commit, outputs or effects."""
    visiting = set()

    @cache
    def terminals(symbol):
        if symbol in visiting:
            raise ValueError('cycle in scheduled combinational def-use: ' + symbol)
        visiting.add(symbol)
        result = {'output:' + outputs[symbol]} if symbol in outputs else set()
        for user in values[symbol].get('users', []):
            where = schedule.get(user['op'])
            if where is None:
                continue
            op = ops[user['op']]
            if where['phase'] == 'commit':
                result.add('commit:' + str(where['group']))
            elif not op['out'] or op.get('attrs', {}).get('hasSideEffects', {}).get('v', False):
                result.add('effect:' + op['sym'])
            else:
                for target in op['out']:
                    result.update(terminals(target))
        visiting.remove(symbol)
        return frozenset(result)

    return terminals


def run(out):
    if out.exists():
        raise FileExistsError('use a new output directory')
    frozen = read(ARTIFACTS / 'binary-shape-v9/inputs.json')
    for entry in [*frozen['source_files'], frozen['current_manifest'], frozen['run2_manifest'],
                  frozen['normalized_rtl'], frozen['grhsim_graph']]:
        verify(entry)
    for record in frozen['binaries'].values():
        verify(record['binary'])
    count_build = read(COUNTS / 'build.json')
    for entry in [*count_build['inputs'], *count_build['outputs']]:
        verify(entry)
    count_report = read(COUNTS / 'report.json')
    for entry in count_report['references'].values():
        verify(entry)
    prior = read(MAPPING / 'static.json')
    normalized = MODEL / 'normalized.json'
    if identity(normalized)['sha256'] != prior['graph']['sha256']:
        raise ValueError('scheduled graph differs from the source mapping')
    graph = read(normalized)['graphs'][0]
    values = {v['sym']: v for v in graph['vals']}
    ops = {o['sym']: o for o in graph['ops']}
    with (MAPPING / 'sources.csv').open() as stream:
        schedule = {row['op_symbol']: row for row in csv.DictReader(stream)}
    # Mapping rows must refer to this exact graph and to the same result symbols.
    for symbol, row in schedule.items():
        op = ops[symbol]
        if op['kind'] != row['op_kind'] or op['out'] != list(filter(None, row['value_symbols'].split(';'))):
            raise ValueError('source map disagrees with graph: ' + symbol)
    observed = read(COUNTS / 'counts.json')['coremark']
    cycles = observed['cycles']
    rates = {k: sum(v) / cycles for k, v in observed['counts'].items()}
    reference = read(ORIGINAL / 'verification.json')['workloads']['coremark']['verilator']
    if cycles != reference['cycles'] or observed['trace']['sha256'] != reference['trace']['sha256']:
        raise ValueError('counter workload differs from verified CoreMark')
    events = set()
    outputs = {p['val']: p['name'] for p in graph['ports']['out']}
    terminals = terminal_reachability(values, ops, schedule, outputs)
    commits = defaultdict(list)
    for op in ops.values():
        edges = op.get('attrs', {}).get('eventEdge', {}).get('vs', [])
        if edges:
            events.update(op['in'][-len(edges):])
        if op['sym'] in schedule and schedule[op['sym']]['phase'] == 'commit':
            commits[int(schedule[op['sym']]['group'])].append(op)
    code_checks = generated_comparisons(sorted(MODEL.glob('*_sched_*.cpp')))
    if set(code_checks) != set(prior['values']):
        raise ValueError('generated comparison sites differ from counter metadata')
    rows = []
    state_slices = defaultdict(list)
    for index, meta in prior['values'].items():
        value = values[meta['value']]
        if code_checks[index]['group'] != meta['group']:
            raise ValueError('comparison group mismatch: ' + index)
        if value['w'] != meta['width'] or ops[value['def']]['kind'] != meta['kind']:
            raise ValueError('comparison definition mismatch: ' + index)
        row = dict(id=index, value=value['sym'], width=value['w'], kind=meta['kind'],
                   **code_checks[index], comparisons=rates['cmp:' + index], changes=rates['chg:' + index],
                   **user_boundaries(value, meta['group'], schedule, events))
        row['terminal_uses'] = sorted(terminals(value['sym']))
        if not row['terminal_uses']:
            raise ValueError('tracked value has no scheduled endpoint: ' + value['sym'])
        batch = int(schedule[value['def']]['batch'])
        target_batches = sorted({int(next(s['batch'] for s in schedule.values()
                                         if int(s['group']) == target)) for target in row['compute_targets']})
        row.update(batch=batch, target_batches=target_batches,
                   all_compute_targets_same_batch=bool(target_batches) and target_batches == [batch])
        if meta['kind'] == 'kSliceStatic':
            source = ops.get(values[meta['operands'][0]].get('def'), {})
            if source.get('kind') == 'kRegisterReadPort':
                row['state_source'] = source['attrs']['regSymbol']['v']
                state_slices[row['state_source']].append(row)
        rows.append(row)
    if abs(totals(rows)['comparisons_per_cycle'] - rates['scalar_comparisons']) > 1e-8:
        raise ValueError('per-value checks do not sum to the aggregate counter')
    groups = []
    for group, meta in prior['groups'].items():
        current = [r for r in rows if r['group'] == int(group)]
        groups.append(dict(group=int(group), phase=meta['phase'], file=meta['file'],
                           executions_per_cycle=rates['group:' + group], **totals(current)))
    commit_summary = []
    for group, group_ops in sorted(commits.items()):
        signatures = Counter()
        for op in group_ops:
            edges = op.get('attrs', {}).get('eventEdge', {}).get('vs', [])
            event = tuple(zip(edges, op['in'][-len(edges):])) if edges else (('level', 'latch guard'),)
            signatures[event] += 1
        commit_summary.append(dict(group=group, operations=len(group_ops),
            kinds=dict(Counter(o['kind'] for o in group_ops)),
            event_signatures=[dict(events=key, operations=n) for key, n in signatures.items()]))
    thresholds = []
    for threshold in (.99, .9, .75, .5):
        selected = {g['group'] for g in groups if g['phase'] == 'compute' and g['executions_per_cycle'] >= threshold}
        selected_rows = [r for r in rows if r['group'] in selected]
        thresholds.append(dict(threshold=threshold, groups=sorted(selected), **totals(selected_rows)))
    terminal_sets = defaultdict(list)
    for row in rows:
        terminal_sets[tuple(row['terminal_uses'])].append(row)
    terminal_summary = [dict(terminals=key, **totals(entries)) for key, entries in terminal_sets.items()]
    terminal_summary.sort(key=lambda x: -x['comparisons_per_cycle'])
    storage = {}
    header = (MODEL / 'grhsim_Cv32Bench.hpp').read_text()
    storage['grhsim'] = dict(value_slots={kind: int(n) for n, kind in re.findall(
        r'std::array<[^\n]+?, (\d+)> value_(\w+)_slots_', header)},
        scope='intermediate scalar slots only; excludes hardware state, RAM and helper/cache fields')
    vcounts = read(ARTIFACTS / 'code-shapes-v1/counts.json')
    for backend in ('verilator', 'verilator-original'):
        folder = ORIGINAL / backend
        h = (folder / 'VCv32Bench___024root.h').read_text()
        cpp = '\n'.join(p.read_text() for p in sorted(folder.glob('*root__*.cpp')) if 'Slow' not in p.name)
        scalars = re.findall(r'^\s*(CData|SData|IData|QData)/\*\d+:0\*/', h, re.M)
        local = re.findall(r'^    (?:CData|SData|IData|QData)/\*[^*]*\*/ (\w+);$', cpp, re.M)
        vc = vcounts[backend]['coremark']
        if vc['cycles'] != cycles or vc['trace']['sha256'] != reference['trace']['sha256']:
            raise ValueError('Verilator counter workload mismatch')
        storage[backend] = dict(root_scalar_fields=len(scalars), root_one_bit_fields=len(re.findall(
            r'^\s*CData/\*0:0\*/', h, re.M)), local_scalar_declarations=len(local),
            alu_local_declarations=len([name for name in local if 'alu_i' in name]),
            scope='root combines hardware state and intermediates; arrays excluded, including the two 4096-entry one-hot tables',
            existing_function_counts_per_cycle={k: [x / cycles for x in v] for k, v in vc['counts'].items()
                if any(tag in k for tag in ('nba_', 'act_comb', 'eval_body__nba'))})
    state_summary = []
    for reg, entries in state_slices.items():
        state_summary.append(dict(register=reg, producer_groups=sorted({r['group'] for r in entries}),
            target_groups=sorted({g for r in entries for g in r['compute_targets']}),
            value_ids=[r['id'] for r in entries], **totals(entries)))
    case_ids = [r['id'] for r in rows if r.get('state_source') == 'core$_11281_'] + ['42473']
    paths = [ARTIFACTS / 'binary-shape-v9/inputs.json', COUNTS / 'counts.json', COUNTS / 'build.json',
             COUNTS / 'report.json', MAPPING / 'static.json', MAPPING / 'sources.csv', normalized,
             ARTIFACTS / 'code-shapes-v1/counts.json', ORIGINAL / 'normalization.json',
             ROOT / 'wolvrix/include/transform/activity_schedule.hpp',
             ROOT / 'wolvrix/lib/transform/activity_schedule.cpp',
             ROOT / 'wolvrix/lib/emit/grhsim_cpp.cpp', Path(__file__).resolve()]
    out.mkdir(parents=True)
    save(out / 'inputs.json', dict(files=[identity(p) for p in paths], binaries=frozen['binaries'],
        note='Current implementation files explain the rules; generated source and counter identities are frozen separately. No new simulation or performance runs.'))
    save(out / 'comparisons.json', rows)
    save(out / 'groups.json', groups)
    save(out / 'alu-case.json', [r for r in rows if r['id'] in case_ids])
    compute_sizes = Counter(int(row['group']) for row in schedule.values() if row['phase'] == 'compute')
    summary = dict(cycles=cycles, trace_sha256=reference['trace']['sha256'], all_checks=totals(rows),
        compute_boundary_only=totals([r for r in rows if r['compute_boundary_only']]),
        all_compute_targets_same_batch=totals([r for r in rows if r['all_compute_targets_same_batch']]),
        one_bit_checks=totals([r for r in rows if r['width'] == 1]),
        by_kind={kind: totals([r for r in rows if r['kind'] == kind]) for kind in sorted({r['kind'] for r in rows})},
        compute_groups=sum(g['phase'] == 'compute' for g in groups),
        compute_executions_per_cycle=sum(g['executions_per_cycle'] for g in groups if g['phase'] == 'compute'),
        high_activity_groups=thresholds, commits=commit_summary, storage=storage,
        terminal_sets=terminal_summary,
        compute_group_ops=dict(total=sum(compute_sizes.values()), minimum=min(compute_sizes.values()),
                               maximum=max(compute_sizes.values()), at_128=sum(n == 128 for n in compute_sizes.values()),
                               groups=dict(sorted(compute_sizes.items()))),
        state_slices=sorted(state_summary, key=lambda x: -x['comparisons_per_cycle']),
        current_dynamic={k: rates[k] for k in ('scalar_comparisons', 'scalar_changes', 'direct_active_or_executions', 'round')},
        mapped_operations=len(schedule), graph_operations=len(ops),
        limits=['Counters are source-level executions, not retired host instructions or a time breakdown.',
                'High marginal group execution does not establish co-firing; no cycle correlation was recorded.',
                'IR consumer classification uses scheduled users only, not transitive sinks or dead/alias nodes.',
                'Internalizing a boundary requires a new schedule and preservation of event/state/effect barriers.',
                'The latest shared-deferred experiment is not promoted; this audit uses the frozen 9642e07f baseline.'])
    save(out / 'report.json', summary)
    print(json.dumps({key: summary[key] for key in ('all_checks', 'compute_boundary_only',
        'all_compute_targets_same_batch', 'one_bit_checks', 'compute_groups', 'compute_executions_per_cycle')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output.resolve())
