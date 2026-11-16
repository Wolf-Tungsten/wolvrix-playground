#!/usr/bin/env python3
"""Attribute one frozen shared-region result; keep diagnostics out of paired data."""
import argparse
import csv
import json
import math
from pathlib import Path

from cv32e40p_compare import ROOT, identity, run, sample, save, summarize_named
from cv32e40p_event_regions_compare import check
from cv32e40p_binary_shape import function_symbols, disassemble, instructions, instruction_shape


def decompose_reports(before, after):
    """Account for changed execution rates without treating lost checks as lost logic."""
    if before['cycles'] != after['cycles']:
        raise ValueError('different workload cycle counts')
    indexed = []
    for report in (before, after):
        rows = {row['id']: row for row in report['values']}
        if len(rows) != len(report['values']):
            raise ValueError('duplicate value ID')
        for name in ('comparisons', 'changes'):
            if not math.isclose(sum(r[name] for r in rows.values()), report['total'][name], abs_tol=1e-8):
                raise ValueError('per-value counts disagree with aggregate')
        indexed.append(rows)
    old, new = indexed
    removed = sorted(old.keys() - new.keys(), key=int)
    added = sorted(new.keys() - old.keys(), key=int)
    retained = []
    for key in sorted(old.keys() & new.keys(), key=int):
        a, b = old[key], new[key]
        if any(a[field] != b[field] for field in ('value', 'kind', 'width')):
            raise ValueError('value identity changed: ' + key)
        retained.append(dict(id=key, value=b['value'], kind=b['kind'],
            before=a['comparisons'], after=b['comparisons'], delta=b['comparisons'] - a['comparisons'],
            old_group=a['group'], new_group=b['group'],
            cache_lost=len(a['check_lines']) == 3 and len(b['check_lines']) == 1 and a['kind'] == 'kEq'))
    cached_removed = [key for key in removed if len(old[key]['check_lines']) == 3 and old[key]['kind'] == 'kEq']
    cache_lost = [row for row in retained if row['cache_lost']]
    removed_rate = sum(old[key]['comparisons'] for key in removed)
    added_rate = sum(new[key]['comparisons'] for key in added)
    retained_delta = sum(row['delta'] for row in retained)
    reconstructed = before['total']['comparisons'] - removed_rate + added_rate + retained_delta
    if not math.isclose(reconstructed, after['total']['comparisons'], abs_tol=1e-8):
        raise ValueError('comparison accounting does not balance')
    return dict(scope='Change checks per guest cycle, not all logical equalities or machine instructions. '
            'For these emitters three Eq check sites identify shared decoder init/clear/set paths.',
        before=before['total'], after=after['total'], cycles=before['cycles'],
        removed_values=len(removed), added_values=len(added),
        removed_previous_comparisons=removed_rate, added_new_comparisons=added_rate,
        retained_comparison_delta=retained_delta, reconstructed_after_comparisons=reconstructed,
        removed_cached_values=len(cached_removed),
        removed_cached_previous_comparisons=sum(old[key]['comparisons'] for key in cached_removed),
        retained_cache_lost_values=len(cache_lost),
        retained_cache_lost_delta=sum(row['delta'] for row in cache_lost),
        removed=[old[key] for key in removed], added=[new[key] for key in added],
        retained=sorted(retained, key=lambda row: (-row['delta'], int(row['id']))),
        local_decoder_families={name: [{k: v for k, v in family.items() if k != 'operations'}
            for family in report.get('local_decoder_families', [])]
            for name, report in [('before', before), ('after', after)]})


def decompose(before_path, after_path, output):
    if output.exists():
        raise FileExistsError('use a new report path')
    reports = [json.loads(path.read_text()) for path in (before_path, after_path)]
    graphs = []
    for report in reports:
        entries = [entry for entry in report['inputs'] if Path(entry['path']).name == 'normalized.json']
        if len(entries) != 1 or identity(entries[0]['path']) != entries[0]:
            raise ValueError('missing or changed frozen graph')
        graphs.append(entries[0])
    if graphs[0]['sha256'] != graphs[1]['sha256']:
        raise ValueError('value IDs belong to different graphs')
    result = decompose_reports(*reports)
    result['inputs'] = [identity(p) for p in (before_path, after_path, Path(__file__).resolve())] + graphs
    save(output, result)


def profile(out):
    manifest = check(out)
    if (out / 'diagnostic-runs.json').exists():
        raise FileExistsError('diagnostics already recorded')
    results = {}
    for backend in (*manifest['backend_pair'], 'verilator'):
        path = out / (backend + '-stat.csv')
        if path.exists(): raise FileExistsError(path)
        results[backend] = sample(out, backend, 'coremark', 'diagnostic-stat', perf=[
            'stat', '-x,', '-o', path, '-e', 'cycles:u,instructions:u,branches:u,branch-misses:u'])
    data = out / 'shared-perf.data'
    if data.exists(): raise FileExistsError(data)
    results['profile'] = sample(out, 'grhsim_shared_regions', 'coremark', 'diagnostic-record', perf=[
        'record', '-o', data, '-e', 'cycles:u', '-F', '499', '--call-graph', 'dwarf,8192'])
    for suffix, extra in [('perf', []), ('lines', ['--sort', 'symbol,srcline', '--percent-limit', '0'])]:
        run(['perf', 'report', '--stdio', '--no-children', '--call-graph', 'none', *extra, '-i', data],
            out / ('shared-' + suffix + '.txt'))
    save(out / 'diagnostic-runs.json', results)


def analyze(out, counters):
    if (out / 'diagnostics.json').exists(): raise FileExistsError('analysis already recorded')
    manifest = check(out)
    count_inputs = json.loads((counters / 'inputs.json').read_text())
    if count_inputs['model'] != manifest['binaries']['grhsim_shared_regions']:
        raise ValueError('counter model mismatch')
    observed = json.loads((counters / 'counts.json').read_text())['coremark']
    reference = json.loads((out / 'verification.json').read_text())['workloads']['coremark']['verilator']
    if observed['cycles'] != reference['cycles'] or observed['trace']['sha256'] != reference['trace']['sha256']:
        raise ValueError('counter workload mismatch')
    cycles = observed['cycles']
    models, pmu, files = {}, {}, []
    for backend, entry in manifest['binaries'].items():
        binary = Path(entry['path']); functions = []
        for symbol in function_symbols(binary):
            name = symbol['symbol']
            selected = (name.startswith('GrhSIM_Cv32Bench::eval') if backend != 'verilator' else
                name.startswith('VCv32Bench___024root___') and any(tag in name for tag in (
                    '___nba_', '___act_', '___eval_ico', '___eval_act', '___eval_nba', '___eval_body')))
            if not selected: continue
            asm = disassemble(binary, symbol)
            functions.append(dict(**symbol, **instruction_shape(instructions(asm))))
            path = out / 'assembly' / backend / f'function-{symbol["address"]:x}.s'
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text(asm); files.append(path)
        models[backend] = dict(binary=entry, functions=functions,
            totals={key: sum(f[key] for f in functions) for key in ('bytes', 'instructions',
                'memory_operand_instructions', 'stack_operand_instructions', 'compare_or_test', 'cmov_or_setcc')})
        path = out / (backend + '-stat.csv'); files.append(path)
        records = {}
        for row in csv.reader(path.read_text().splitlines()):
            if len(row) >= 3 and row[2].endswith(':u'):
                records[row[2]] = int(row[0]) / cycles
        if set(records) != {'cycles:u', 'instructions:u', 'branches:u', 'branch-misses:u'}:
            raise ValueError('missing PMU event')
        pmu[backend] = records | {'ipc': records['instructions:u'] / records['cycles:u']}
    with (out / 'sources.csv').open() as stream:
        mapping = list(csv.DictReader(stream))
    groups = {}
    for row in mapping:
        groups.setdefault(row['group'], dict(batch=int(row['batch']), phase=row['phase'], operations=[]))['operations'].append(row['op_symbol'])
    for group, data in groups.items():
        data['executions_by_phase'] = [n / cycles for n in observed['counts']['group:' + group]]
    measured = json.loads((out / 'pairs.json').read_text())
    report = dict(scope='Independent diagnostic runs. Static stack operands are not spill counts; sampled percentages do not apportion paired speed.',
        cycles=cycles, phases=count_inputs['phases'], pmu=pmu, models=models, groups=groups,
        baseline_vs_verilator=summarize_named(measured, 'grhsim_event_regions', 'verilator'),
        counters_per_cycle={k: [v / cycles for v in values] for k, values in observed['counts'].items()
            if k.startswith(('scalar_', 'round', 'direct_active_or_'))},
        references=[identity(p) for p in [out / 'build.json', out / 'summary.json', out / 'diagnostic-runs.json',
            out / 'sources.csv', out / 'shared-perf.data', out / 'shared-perf.txt', out / 'shared-lines.txt',
            counters / 'inputs.json', counters / 'counts.json', *files, Path(__file__).resolve()]])
    save(out / 'diagnostics.json', report)
    print(json.dumps({k: report[k] for k in ('counters_per_cycle', 'pmu')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('profile', 'analyze', 'decompose'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--counts', type=Path)
    parser.add_argument('--before', type=Path)
    parser.add_argument('--after', type=Path)
    args = parser.parse_args()
    if args.stage == 'profile': profile(args.output.resolve())
    elif args.stage == 'decompose':
        if args.before is None or args.after is None: parser.error('decompose requires --before and --after')
        decompose(args.before.resolve(), args.after.resolve(), args.output.resolve())
    else:
        if args.counts is None: parser.error('analyze requires --counts')
        analyze(args.output.resolve(), args.counts.resolve())
