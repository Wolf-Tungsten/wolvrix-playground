#!/usr/bin/env python3
"""Attribute the frozen concat-slice model's remaining work; no production edits."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re
import shutil
import subprocess

from cv32e40p_compare import ROOT, CXX, CFLAGS, environment, identity, run, sample, save
from cv32e40p_regfile_compare import check_identity
from cv32e40p_code_shapes import Probes

CURRENT = ROOT / 'build/cv32e40p/concat-slices-v1'
ORIGINAL = ROOT / 'build/cv32e40p/run2'
PREVIOUS = ROOT / 'build/cv32e40p/code-shapes-v1'
MODEL = CURRENT / 'grhsim_concat_slices'
SOURCES = {'grhsim': MODEL, 'verilator': ORIGINAL / 'verilator',
           'verilator-original': ORIGINAL / 'verilator-original'}


def materializations(folder, graph):
    values = {v['sym']: v for v in graph['vals']}
    ops = {o['sym']: o for o in graph['ops']}
    records, groups = {}, {}
    for path in sorted(folder.glob('*_sched_*.cpp')):
        code = path.read_text()
        names = {i: symbol for symbol, i in re.findall(r'// value (.*?) -> .*?\[value_id=(\d+):0\]', code)}
        phase = 'commit' if '::eval_commit_batch_' in code else 'compute'
        group = None
        for number, line in enumerate(code.splitlines(), 1):
            m = re.search(r'// Supernode (\d+)', line)
            if m:
                group = int(m[1]); groups[str(group)] = dict(phase=phase, file=path.name)
            m = re.search(r'const bool grhsim_changed_(\d+) =', line)
            if not m: continue
            index = m[1]; v = values[names[index]]; op = ops[v['def']]
            entry = dict(value=v['sym'], width=v['w'], kind=op['kind'], group=group,
                         file=path.name, line=number, operands=op['in'])
            if op['kind'] in ('kEq', 'kNe') and len(op['in']) == 2:
                constants = [a for a in op['in'] if values[a].get('def') and ops[values[a]['def']]['kind'] == 'kConstant']
                if len(constants) == 1:
                    source = next(a for a in op['in'] if a != constants[0])
                    entry.update(compare_source=source, source_width=values[source]['w'],
                        constant=ops[values[constants[0]]['def']]['attrs']['constValue']['v'],
                        source_definition=ops.get(values[source].get('def')))
            if index in records: raise ValueError('multiple comparison sites for one value')
            records[index] = entry
    return records, groups


class DetailedProbes(Probes):
    def __init__(self, values):
        super().__init__(); self.values = values

    def instrument(self, name, text):
        result = super().instrument(name, text)
        if name != 'grhsim': return result
        def add(match):
            index = match[2]; entry = self.values[index]
            extra = self.hit('cmp:' + index) + self.hit('chg:' + index, 'grhsim_changed_' + index)
            if entry['width'] == 1: extra += self.hit('true:' + index, 'next_value')
            return match[1] + '\n' + extra
        return re.sub(r'(const bool grhsim_changed_(\d+) = [^\n]+;)', add, result)


def prepare(out):
    check_identity(CURRENT)
    out.mkdir(parents=True, exist_ok=False)
    (out / 'firmware').symlink_to(ORIGINAL / 'firmware')
    (out / 'verification.json').symlink_to(ORIGINAL / 'verification.json')
    graph = json.loads((MODEL / 'normalized.json').read_text())['graphs'][0]
    values, groups = materializations(MODEL, graph)
    models = {}
    for name, source in SOURCES.items():
        (out / name).mkdir(); shutil.copy2(source / 'emu', out / name / 'emu')
        symbols = []
        for line in subprocess.check_output(['nm', '-S', '--size-sort', '--defined-only', '--demangle', source / 'emu'], text=True).splitlines():
            m = re.match(r'([0-9a-f]+) ([0-9a-f]+) [TtWw] (.+)', line)
            if not m: continue
            s = m[3]
            selected = (s.startswith('GrhSIM_Cv32Bench::eval') if name == 'grhsim' else
                        s.startswith('VCv32Bench___024root___') and any(k in s for k in
                        ('___nba_', '___act_', '___eval_ico', '___eval_act', '___eval_nba', '___eval_body')))
            if selected: symbols.append(dict(symbol=s, bytes=int(m[2], 16)))
        sources = sorted(source.glob('*_sched_*.cpp')) if name == 'grhsim' else sorted(p for p in source.glob('*root__*.cpp') if 'Slow' not in p.name)
        header = source / ('grhsim_Cv32Bench.hpp' if name == 'grhsim' else 'VCv32Bench___024root.h')
        models[name] = dict(binary=identity(source / 'emu'), sources=[identity(p) for p in sources],
            header=identity(header), hot_model_text=sum(s['bytes'] for s in symbols), hot_symbols=symbols)
        if name != 'grhsim':
            models[name]['onehot_arrays'] = re.findall(r'VlUnpacked<CData/\*0:0\*/, (\d+)> (__VdfgBinToOneHot_Tab_\w+)', header.read_text())
            text = '\n'.join(p.read_text() for p in sources)
            models[name]['onehot_constant_read_sites'] = dict(Counter(re.findall(r'(__VdfgBinToOneHot_Tab_\w+)\[\d+U\]', text)))
    save(out / 'static.json', dict(reference=identity(CURRENT / 'report.json'), graph=identity(MODEL / 'normalized.json'),
        models=models, values=values, groups=groups,
        comparison_kinds=dict(Counter(x['kind'] for x in values.values()))))


def check(out):
    check_identity(CURRENT)
    d = json.loads((out / 'static.json').read_text())
    for entry in [d['reference'], d['graph']]:
        if identity(entry['path']) != entry: raise ValueError('frozen input changed')
    for model in d['models'].values():
        for entry in [model['binary'], model['header'], *model['sources']]:
            if identity(entry['path']) != entry: raise ValueError('frozen source changed')
    return d


def build(out, jobs):
    evidence = check(out); dest = out / 'grhsim-counts'; dest.mkdir(exist_ok=False)
    for p in MODEL.iterdir():
        if p.suffix in ('.cpp', '.h', '.hpp') or p.name == 'Makefile': shutil.copy2(p, dest / p.name)
    probes = DetailedProbes(evidence['values'])
    for p in sorted(dest.glob('*.cpp')):
        if p.name.endswith(('_eval.cpp', '_state.cpp')) or '_sched_' in p.name:
            p.write_text(probes.instrument('grhsim', p.read_text()))
    if len([n for n in probes.entries if n.startswith('group:')]) != len(evidence['groups']):
        raise ValueError('missing group probes')
    if len([n for n in probes.entries if n.startswith('cmp:')]) != len(evidence['values']):
        raise ValueError('missing comparison probes')
    (dest / 'shape_counters.hpp').write_text(probes.header())
    harness = '#include "shape_counters.hpp"\n' + (ORIGINAL / 'inputs/fixture/harness.cpp').read_text()
    harness = harness.replace('m.eval();', 'cv32_shape::phase=static_cast<unsigned>(m.clk_i); m.eval();')
    assert harness.count('        started = Clock::now();') == 1
    harness = harness.replace('        started = Clock::now();', '        cv32_shape::reset();\n        started = Clock::now();')
    harness = harness.replace('        sim_s += seconds(started);', '        sim_s += seconds(started);\n        cv32_shape::dump();')
    (dest / 'harness.cpp').write_text(harness)
    save(dest / 'probes.json', dict(entries=probes.entries, scope='source-level counters after image loading and reset; never performance data'))
    run(['make', '-C', dest, '-j', jobs, 'CXX=' + str(CXX), 'CXXFLAGS=' + ' '.join(CFLAGS)], out / 'logs/counts-build.log')
    run([CXX, *CFLAGS, '-DCV32_GRHSIM', '-I', dest, dest / 'harness.cpp', dest / 'libgrhsim_Cv32Bench.a', '-o', dest / 'emu'], out / 'logs/counts-link.log')
    save(out / 'count-build.json', dict(binary=identity(dest / 'emu'), probes=identity(dest / 'probes.json'),
        source_files=[identity(p) for p in sorted(dest.iterdir()) if p.suffix in ('.cpp', '.hpp')],
        analysis_driver=identity(__file__), shared_probes=identity(ROOT / 'scripts/cv32e40p_code_shapes.py')))


def count(out):
    check(out); built = json.loads((out / 'count-build.json').read_text())
    for entry in [built['binary'], built['probes'], *built['source_files']]:
        if identity(entry['path']) != entry: raise ValueError('counter build changed')
    expected = json.loads((out / 'verification.json').read_text())['workloads']; result = {}
    for workload in ('smoke', 'coremark'):
        row = sample(out, 'grhsim-counts', workload, 'count-' + workload, trace=True)
        if row['trace']['sha256'] != expected[workload]['verilator']['trace']['sha256']:
            raise ValueError('counter instrumentation changed bus trace')
        log = (out / 'runs' / ('count-' + workload) / 'grhsim-counts/run.log').read_text()
        raw = json.loads(re.search(r'^CV32_SHAPE (.+)$', log, re.M)[1])['counts']
        names = json.loads((out / 'grhsim-counts/probes.json').read_text())['entries']
        assert len(raw) == len(names)
        result[workload] = dict(cycles=row['cycles'], counts=dict(zip(names, raw)), trace=row['trace'])
    save(out / 'counts.json', result)


def pmu(out):
    check(out)
    for name in SOURCES:
        sample(out, name, 'coremark', 'pmu', perf=['stat', '-x,', '-o', out / f'{name}-stat.csv',
               '-e', 'cycles:u,instructions:u,branches:u,branch-misses:u'])
    # Reuse the existing production sample; this does not rerun or mutate it.
    run(['perf', 'report', '--stdio', '--no-children', '--call-graph', 'none', '--sort', 'symbol,srcline',
         '--percent-limit', '0', '-i', CURRENT / 'grhsim_concat_slices-perf.data'], out / 'grhsim-lines.txt')


def mapping(out):
    check(out)
    tool = ROOT / 'build/cv32e40p/tools/cv32e40p_map'
    env = environment(); env['LD_LIBRARY_PATH'] = str(CURRENT / 'native-emitter')
    run([tool, CURRENT / 'candidate.json', out / 'sources.csv'], out / 'logs/mapping.log', env=env)
    save(out / 'mapping-identity.json', dict(tool=identity(tool), graph=identity(CURRENT / 'candidate.json'),
        library=identity(CURRENT / 'native-emitter/libwolvrix-lib.so'), result=identity(out / 'sources.csv')))


def supplemental(out, static, totals):
    graph = json.loads((MODEL / 'normalized.json').read_text())['graphs'][0]
    ir_values = {v['sym']:v for v in graph['vals']}; ir_ops = {o['sym']:o for o in graph['ops']}
    mapped = {}
    for row in csv.DictReader((out / 'sources.csv').open()):
        for i, name in zip(row['value_ids'].split(';'), row['value_symbols'].split(';')):
            if i: mapped[i] = dict(row, value=name)
    for i, meta in static['values'].items():
        assert mapped[i]['value'] == meta['value'] and int(mapped[i]['group']) == meta['group']
    code = '\n'.join(p.read_text() for p in SOURCES['verilator'].glob('*root__*.cpp') if 'Slow' not in p.name)
    def constant(text):
        m = re.fullmatch(r"\d+'([bdh])([0-9a-fA-F]+)", text)
        if not m: raise ValueError('unexpected comparison literal: ' + text)
        return int(m[2], {'b': 2, 'd': 10, 'h': 16}[m[1]])
    onehot = {}
    # Exact attribution of the two generated Verilator tables, not a transform.
    for source, suffix in [('_val_6162', '0'), ('_val_134', '1')]:
        table = '__VdfgBinToOneHot_Tab_h39c821e2_0_' + suffix
        constants = set(map(int, re.findall(re.escape(table) + r'\[(\d+)U\]', code)))
        values = {i: v for i,v in static['values'].items() if v.get('compare_source') == source}
        compared = {constant(v['constant']) for v in values.values()}
        assert compared <= constants
        all_compared = set()
        for op in graph['ops']:
            if op['kind'] != 'kEq' or source not in op['in']: continue
            for operand in op['in']:
                definition = ir_ops.get(ir_values[operand].get('def'), {})
                if definition.get('kind') == 'kConstant':
                    all_compared.add(constant(definition['attrs']['constValue']['v']))
        assert all_compared == constants
        onehot[source] = dict(table=table, materialized_constants=sorted(compared),
            ir_constants=sorted(all_compared), verilator_read_constants=sorted(constants), groups={str(g): dict(
                sites=sum(v['group'] == g for v in values.values()), executions=totals['group:' + str(g)],
                comparisons=sum(totals['cmp:' + i] for i,v in values.items() if v['group'] == g),
                changes=sum(totals['chg:' + i] for i,v in values.items() if v['group'] == g))
                for g in sorted({v['group'] for v in values.values()})})
    values, ops = ir_values, ir_ops
    reductions = {}
    for name in ('_val_12607', '_val_6808'):
        op = ops[values[name]['def']]; by_source = defaultdict(list); other = []
        for field in op['in']:
            eq = ops[values[field]['def']]
            if eq['kind'] != 'kEq': other.append(field); continue
            literals = [a for a in eq['in'] if ops.get(values[a].get('def'), {}).get('kind') == 'kConstant']
            if len(literals) != 1: other.append(field); continue
            literal = literals[0]; source = next(a for a in eq['in'] if a != literal)
            by_source[source].append(constant(ops[values[literal]['def']]['attrs']['constValue']['v']))
        groups = {}
        for source, constants in by_source.items():
            ranges = []
            for number in sorted(set(constants)):
                if ranges and number == ranges[-1][1] + 1: ranges[-1][1] = number
                else: ranges.append([number, number])
            groups[source] = dict(constants=sorted(constants), ranges=ranges)
        reductions[name] = dict(operands=len(op['in']), other_fields=other, sources=groups)
    lines = []
    for line in (out / 'grhsim-lines.txt').read_text().splitlines():
        m = re.match(r'\s*([\d.]+)%\s+\[.\]\s+(.*?)\s+(grhsim_\S+:\d+)\s+', line)
        if m: lines.append(dict(percent=float(m[1]), symbol=m[2], location=m[3]))
    save(out / 'hot-lines.json', lines)
    result = dict(onehot=onehot, reductions=reductions, mapped_comparisons=len(static['values']),
        example_mapping={i: mapped[i] for i in ('43440', '42338', '42132', '42047', '41661', '43884', '42115')},
        sampling='Source-line attribution is approximate and rounded; not additive causal timing.')
    save(out / 'shape-evidence.json', result)
    return result


def report(out):
    static = check(out); count_data = json.loads((out / 'counts.json').read_text())['coremark']
    counts = count_data['counts']; cycles = count_data['cycles']
    totals = {k: sum(v) / cycles for k, v in counts.items()}
    per_kind, per_source, per_group = {}, {}, {}
    for index, entry in static['values'].items():
        for target, key in [(per_kind, entry['kind']), (per_group, str(entry['group'])),
                            (per_source, entry.get('compare_source', '(not constant comparison)'))]:
            item = target.setdefault(key, dict(sites=0, comparisons=0, changes=0, true_results=0))
            item['sites'] += 1
            item['comparisons'] += totals['cmp:' + index]
            item['changes'] += totals['chg:' + index]
            item['true_results'] += totals.get('true:' + index, 0)
    assert abs(sum(x['comparisons'] for x in per_kind.values()) - totals['scalar_comparisons']) < 1e-7
    assert abs(sum(x['changes'] for x in per_kind.values()) - totals['scalar_changes']) < 1e-7
    pmu_data = {}
    for name in SOURCES:
        counters = {r[2]: dict(count=float(r[0]), per_cycle=float(r[0])/cycles, running_percent=float(r[4]))
                    for r in csv.reader((out / f'{name}-stat.csv').open()) if len(r) >= 5}
        pmu_data[name] = dict(counters=counters, ipc=counters['instructions:u']['count']/counters['cycles:u']['count'])
    old = json.loads((PREVIOUS / 'report.json').read_text())
    for name in ('verilator', 'verilator-original'):
        if static['models'][name]['binary']['sha256'] != old['static']['models'][name]['binary']['sha256']:
            raise ValueError('cannot reuse Verilator dynamic counts from different binary')
    execution = {phase: [sum(v[i]/cycles for k,v in counts.items() if k.startswith('group:') and
                        static['groups'][k[6:]]['phase'] == phase) for i in (0, 1)] for phase in ('compute', 'commit')}
    samples = []
    for p in sorted((out / 'runs').glob('*/*/result.json')):
        row = json.loads(p.read_text()); backend = row['backend']
        expected = (json.loads((out / 'count-build.json').read_text())['binary'] if backend == 'grhsim-counts'
                    else static['models'][backend]['binary'])
        if row['placement_errors'] or row['binary']['sha256'] != expected['sha256']: raise ValueError('sample invalid')
        samples.append(dict(path=str(p), backend=backend, sibling_idle=row['cpu_idle_percent']['288']))
    assert len(samples) == 5
    extra = supplemental(out, static, totals)
    ratios = {}
    for name in ('verilator', 'verilator-original'):
        g, v = pmu_data['grhsim'], pmu_data[name]
        ratios[name] = dict(instructions=g['counters']['instructions:u']['count']/v['counters']['instructions:u']['count'],
            ipc_factor=v['ipc']/g['ipc'], cycles=g['counters']['cycles:u']['count']/v['counters']['cycles:u']['count'])
    save(out / 'report.json', dict(static=static, production_pmu=pmu_data, execution=execution,
        totals_per_cycle=totals, comparisons_by_kind=per_kind, comparisons_by_source=per_source, comparisons_by_group=per_group,
        reused_verilator_counts={k: old['counts'][k]['coremark'] for k in ('verilator', 'verilator-original')},
        previous_report=identity(PREVIOUS / 'report.json'), prior_production_sampling=identity(CURRENT / 'grhsim_concat_slices-perf.data'),
        samples=samples, code_shapes=extra, pmu_ratios=ratios, mapping=json.loads((out / 'mapping-identity.json').read_text()),
        analysis_driver=identity(__file__), comparison_scope='true_results counts one-bit results only; counters are source-level execution counts',
        scope='Five diagnostic samples, no new performance pairs or production code changes.'))
    print(json.dumps(dict(execution=execution, comparisons_by_kind=per_kind,
        top_sources=sorted(per_source.items(), key=lambda item: -item[1]['comparisons'])[:5]), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare', 'build', 'count', 'pmu', 'mapping', 'report'])
    parser.add_argument('--output', type=Path, default=ROOT / 'build/cv32e40p/remaining-gap-v1')
    parser.add_argument('--jobs', type=int, default=16)
    args = parser.parse_args(); out = args.output.resolve()
    if args.stage == 'build': build(out, args.jobs)
    else: globals()[args.stage](out)


if __name__ == '__main__': main()
