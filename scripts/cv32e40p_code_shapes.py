#!/usr/bin/env python3
"""Inspect frozen generated models and build separate execution-count diagnostics."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re
import shutil
import subprocess

from cv32e40p_compare import ROOT, CXX, CFLAGS, run, identity, save, sample
from cv32e40p_regfile_compare import check_identity

ORIGINAL = ROOT / 'build/cv32e40p/run2'
CURRENT = ROOT / 'build/cv32e40p/packed-slices-final'
SOURCES = {'grhsim': CURRENT / 'grhsim_packed_slices',
           'verilator': ORIGINAL / 'verilator',
           'verilator-original': ORIGINAL / 'verilator-original'}


def static_report(out):
    check_identity(CURRENT)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'firmware').symlink_to(ORIGINAL / 'firmware')
    (out / 'verification.json').symlink_to(ORIGINAL / 'verification.json')
    result = {'source_manifest': identity(CURRENT / 'build.json'), 'models': {}, 'ir': {}}
    for name, src in SOURCES.items():
        dest = out / name; dest.mkdir()
        shutil.copy2(src / 'emu', dest / 'emu')
        headers = list(src.glob('grhsim_Cv32Bench.hpp')) if name == 'grhsim' else [src / 'VCv32Bench___024root.h']
        header = headers[0].read_text()
        fast = sorted(src.glob('grhsim_Cv32Bench_sched_*.cpp')) if name == 'grhsim' else sorted(p for p in src.glob('VCv32Bench___024root__*.cpp') if 'Slow' not in p.name)
        code = '\n'.join(p.read_text() for p in fast)
        item = dict(binary=identity(src / 'emu'), header=identity(headers[0]), sources=[identity(p) for p in fast],
                    fast_cpp_bytes=sum(p.stat().st_size for p in fast), fast_cpp_lines=code.count('\n'))
        if name == 'grhsim':
            item['value_slots'] = {
                kind: int(count) for count, kind in re.findall(r'std::array<[^\n]+?, (\d+)> value_(\w+)_slots_', header)}
            item['state_scalar_fields'] = dict(Counter(re.findall(r'^\s*(bool|std::uint\d+_t) \w+_slots_\d+;', header, re.M)))
            item['scalar_comparison_sites'] = len(re.findall(r'const bool grhsim_changed_\d+ =', code))
            item['packed_comparison_sites'] = len(re.findall(r'const auto grhsim_slice_changes_\d+ =', code))
            item['direct_active_or_sites'] = len(re.findall(r'^\s*supernode_active_curr_\[.*?\] \|=', code, re.M))
            item['supernodes'] = len(re.findall(r'// Supernode \d+:', code))
        else:
            item['scalar_fields'] = dict(Counter(re.findall(r'^\s*(CData|SData|IData|QData)/\*\d+:\d+\*/', header, re.M)))
            item['one_bit_fields'] = len(re.findall(r'^\s*CData/\*0:0\*/', header, re.M))
            item['wide_fields'] = len(re.findall(r'^\s*VlWide<', header, re.M))
            item['table_lookup_sites'] = len(re.findall(r'VCv32Bench__ConstPool__TABLE_\w+\s*\[', code))
            tables = '\n'.join(p.read_text() for p in src.glob('*ConstPool*cpp'))
            sizes = [int(n) for n in re.findall(r'const VlUnpacked<[^;=\n]+, (\d+)> VCv32Bench__ConstPool__TABLE_', tables)]
            item['table_count'] = len(sizes); item['table_elements'] = sum(sizes)
        sections = subprocess.check_output(['size', '-A', str(src / 'emu')], text=True)
        item['elf_sections'] = {m[1]: int(m[2]) for m in re.finditer(r'^(\.\S+)\s+(\d+)\s+\d+', sections, re.M)}
        result['models'][name] = item
    for name, path in [('before_schedule', ORIGINAL / 'graph.json'), ('after_schedule', SOURCES['grhsim'] / 'normalized.json')]:
        g = json.loads(path.read_text())['graphs'][0]
        kinds = Counter(o['kind'] for o in g['ops'])
        result['ir'][name] = dict(file=identity(path), operations=len(g['ops']), values=len(g['vals']), kinds=dict(kinds))
    save(out / 'static.json', result)


def inspect_extras(out):
    compiled, tables = {}, {}
    for name, src in SOURCES.items():
        symbols = []
        for line in subprocess.check_output(['nm', '-S', '--size-sort', '--defined-only', '--demangle', str(src / 'emu')], text=True).splitlines():
            m = re.match(r'([0-9a-f]+) ([0-9a-f]+) ([TtWw]) (.+)', line)
            if not m: continue
            symbol = m[4]
            included = (('GrhSIM_Cv32Bench::eval_compute_batch_' in symbol or
                         'GrhSIM_Cv32Bench::eval_commit_batch_' in symbol or symbol == 'GrhSIM_Cv32Bench::eval()')
                if name == 'grhsim' else symbol.startswith('VCv32Bench___024root___') and
                any(x in symbol for x in ('___nba_', '___act_', '___eval_ico', '___eval_act', '___eval_nba', '___eval_body')))
            if included: symbols.append(dict(symbol=symbol, bytes=int(m[2], 16)))
        compiled[name] = dict(total=sum(x['bytes'] for x in symbols), symbols=symbols)
        if name == 'grhsim': continue
        code = '\n'.join(p.read_text() for p in src.glob('*root__*.cpp') if 'Slow' not in p.name)
        rows = []
        for p in src.glob('*ConstPool*cpp'):
            for m in re.finditer(r'const VlUnpacked<(\w+)/\*(\d+):0\*/, (\d+)> (VCv32Bench__ConstPool__TABLE_\w+) = \{\{(.*?)\}\};', p.read_text(), re.S):
                n = int(m[3]); values = [int(v, 0) for v in re.findall(r'(0x[0-9a-fA-F]+|\d+)(?:U|ULL|UL)?', m[5])]
                if len(values) != n: raise ValueError('unexpected table literal')
                category, bit = 'other', None
                if len(set(values)) == 1: category = 'constant'
                elif int(m[2]) == 0:
                    for b in range(n.bit_length() - 1):
                        if all(v == ((i >> b) & 1) for i, v in enumerate(values)):
                            category, bit = 'single_bit', b; break
                        if all(v == (((i >> b) & 1) ^ 1) for i, v in enumerate(values)):
                            category, bit = 'inverted_bit', b; break
                rows.append(dict(name=m[4], entries=n, output_width=int(m[2]) + 1, category=category, bit=bit,
                    lookup_sites=len(re.findall(re.escape(m[4]) + r'\s*\[', code))))
        tables[name] = dict(categories=dict(Counter(x['category'] for x in rows)),
            site_categories={k: sum(x['lookup_sites'] for x in rows if x['category'] == k) for k in sorted({x['category'] for x in rows})}, tables=rows)
    save(out / 'compiled-hot-functions.json', compiled)
    save(out / 'table-shapes.json', tables)

    graph = json.loads((ORIGINAL / 'graph.json').read_text())['graphs'][0]
    vals = {v['sym']: v for v in graph['vals']}; ops = {o['sym']: o for o in graph['ops']}
    candidates = []
    for op in graph['ops']:
        if op['kind'] != 'kConcat': continue
        groups = []; pending = []
        def finish():
            if len(pending) > 1:
                source = pending[0][1]
                groups.append(dict(source=source, fields=[x[0] for x in pending], high=pending[0][3], low=pending[-1][2],
                    complete_source=pending[-1][2] == 0 and pending[0][3] + 1 == vals[source]['w']))
        for operand in op['in']:
            definition = ops.get(vals[operand].get('def'))
            if not definition or definition['kind'] != 'kSliceStatic' or len(definition['in']) != 1:
                finish(); pending = []; continue
            attrs = definition.get('attrs', {}); low = attrs.get('sliceStart', {}).get('v'); high = attrs.get('sliceEnd', {}).get('v')
            if low is None or high is None or low < 0 or high < low or high - low + 1 != vals[operand]['w']:
                finish(); pending = []; continue
            source = definition['in'][0]
            if high >= vals[source]['w']: finish(); pending = []; continue
            if pending and (source != pending[-1][1] or high + 1 != pending[-1][2]): finish(); pending = []
            pending.append((operand, source, low, high))
        finish()
        if groups:
            reduction = sum(len(g['fields']) - 1 for g in groups)
            candidates.append(dict(op=op['sym'], output=op['out'], old_operands=len(op['in']),
                merged_operands=len(op['in']) - reduction, groups=groups, location=op.get('loc')))
    save(out / 'concat-slice-shapes.json', dict(scope='read-only structural potential, no transform or performance prediction',
        concats=len(candidates), groups=sum(len(c['groups']) for c in candidates),
        operand_reduction=sum(c['old_operands'] - c['merged_operands'] for c in candidates), candidates=candidates))


class Probes:
    def __init__(self):
        self.entries = []
        self.index = {}
    def hit(self, name, amount='1'):
        if name not in self.index:
            self.index[name] = len(self.entries); self.entries.append(name)
        return f'cv32_shape::counts[{self.index[name]}][cv32_shape::phase] += ({amount});'
    def instrument(self, name, text):
        # These probes only add counters. Fail on unexpected generated shapes;
        # never remove or replace a model computation or condition.
        text = '#include "shape_counters.hpp"\n' + text
        if name == 'grhsim':
            text = re.sub(r'(void GrhSIM_Cv32Bench::(\w+)\([^\n]*\)\s*\{)',
                lambda m: m[1] + '\n' + self.hit('function:' + m[2]), text)
            text = text.replace('while (pending_eval_round) {', 'while (pending_eval_round) {\n' + self.hit('round'))
            text = re.sub(r'(// Supernode (\d+):[^\n]*\n\s*if \([^\n]*\) \{)',
                lambda m: m[1] + '\n' + self.hit('group:' + m[2]), text)
            text = re.sub(r'(const bool (grhsim_changed_\d+) = [^\n]+;)',
                lambda m: m[1] + '\n' + self.hit('scalar_comparisons') + self.hit('scalar_changes', m[2]), text)
            text = re.sub(r'(\[\[maybe_unused\]\] const auto (grhsim_slice_changes_\d+) = [^\n]+;)',
                lambda m: m[1] + '\n' + self.hit('packed_comparisons') + self.hit('packed_changed_groups', m[2] + ' != 0') +
                    self.hit('packed_changed_bits', 'std::popcount(' + m[2] + ')'), text)
            text = re.sub(r'(^[ \t]*supernode_active_curr_\[[^\n]+?\] \|= [^\n]+;)',
                lambda m: m[1] + '\n' + self.hit('direct_active_or_executions'), text, flags=re.M)
        else:
            text = re.sub(r'((?:void|bool) (VCv32Bench___024root___\w+)\([^\n;]*\) \{)',
                lambda m: m[1] + '\n' + self.hit('function:' + m[2]), text)
            text = re.sub(r'(// Inlined CFunc: (\w+)\n)',
                lambda m: m[1] + self.hit('inline:' + m[2]) + '\n', text)
        return text
    def header(self):
        n = len(self.entries)
        return f'''#pragma once
#include <array>
#include <bit>
#include <cstdint>
#include <iostream>
namespace cv32_shape {{
inline unsigned phase = 0;
inline std::array<std::array<std::uint64_t,2>,{n}> counts{{}};
inline void reset() {{ for(auto &v:counts) v={{0,0}}; }}
inline void dump() {{ std::cout << "CV32_SHAPE {{\\\"counts\\\":[";
for(unsigned i=0;i<counts.size();++i) {{ if(i)std::cout<<',';std::cout<<'['<<counts[i][0]<<','<<counts[i][1]<<']'; }}
std::cout << "]}}\\n"; }}
}}
'''


def build_counts(out, jobs):
    check_identity(CURRENT)
    records = {}
    for name, src in SOURCES.items():
        dest = out / (name + '-counts'); dest.mkdir(exist_ok=False)
        for p in src.iterdir():
            if p.suffix in ('.cpp', '.h', '.hpp', '.mk') or p.name == 'Makefile': shutil.copy2(p, dest / p.name)
        probes = Probes(); files = []
        for p in sorted(dest.glob('*.cpp')):
            selected = (p.name.endswith(('_eval.cpp', '_state.cpp')) or '_sched_' in p.name) if name == 'grhsim' else ('___024root__' in p.name and 'Slow' not in p.name)
            if selected:
                p.write_text(probes.instrument(name, p.read_text())); files.append(p.name)
        if name == 'grhsim':
            assert 'round' in probes.index and 'group:0' in probes.index
            assert len([n for n in probes.entries if n.startswith('group:')]) == 183
        else:
            assert 'function:VCv32Bench___024root___eval_nba' in probes.index
        (dest / 'shape_counters.hpp').write_text(probes.header())
        harness = (ORIGINAL / 'inputs/fixture/harness.cpp').read_text()
        harness = '#include "shape_counters.hpp"\n' + harness
        harness = harness.replace('m.eval();', 'cv32_shape::phase=static_cast<unsigned>(m.clk_i); m.eval();')
        assert harness.count('        started = Clock::now();') == 1
        harness = harness.replace('        started = Clock::now();', '        cv32_shape::reset();\n        started = Clock::now();')
        harness = harness.replace('        sim_s += seconds(started);', '        sim_s += seconds(started);\n        cv32_shape::dump();')
        (dest / 'harness.cpp').write_text(harness)
        save(dest / 'probes.json', dict(entries=probes.entries, files=files, original=identity(src / 'emu'), scope='counters reset after image load/reset; not performance sample'))
        if name == 'grhsim':
            run(['make', '-C', dest, '-j', jobs, 'CXX=' + str(CXX), 'CXXFLAGS=' + ' '.join(CFLAGS)], out / 'logs/grhsim-counts-build.log')
            run([CXX, *CFLAGS, '-DCV32_GRHSIM', '-I', dest, dest / 'harness.cpp', dest / 'libgrhsim_Cv32Bench.a', '-o', dest / 'emu'], out / 'logs/grhsim-counts-link.log')
        else:
            makefile = dest / 'VCv32Bench.mk'
            text = makefile.read_text()
            text, n = re.subn(r'^harness\.o: [^\n]+', 'harness.o: ' + str(dest / 'harness.cpp'), text, flags=re.M)
            assert n == 1
            makefile.write_text(text)
            run(['make', '-C', dest, '-f', 'VCv32Bench.mk', '-j', jobs,
                 'CXX=' + str(CXX), 'LINK=' + str(CXX), 'OPT_FAST=-O3', 'OPT_SLOW=-O3'], out / f'logs/{name}-counts-build.log')
        records[name] = dict(binary=identity(dest / 'emu'), probes=identity(dest / 'probes.json'))
    save(out / 'count-builds.json', records)


def count(out):
    builds = json.loads((out / 'count-builds.json').read_text())
    results = {}
    expected = json.loads((out / 'verification.json').read_text())['workloads']
    for name in SOURCES:
        backend = name + '-counts'
        assert identity(out / backend / 'emu') == builds[name]['binary']
        rows = {}
        for workload in ('smoke', 'coremark'):
            row = sample(out, backend, workload, 'count-' + workload, trace=True)
            if row['trace']['sha256'] != expected[workload]['verilator']['trace']['sha256']:
                raise ValueError('counter instrumentation changed bus trace')
            text = (out / 'runs' / ('count-' + workload) / backend / 'run.log').read_text()
            raw = json.loads(re.search(r'^CV32_SHAPE (.+)$', text, re.M)[1])['counts']
            names = json.loads((out / backend / 'probes.json').read_text())['entries']
            assert len(names) == len(raw)
            rows[workload] = dict(cycles=row['cycles'], counts=dict(zip(names, raw)),
                per_cycle={n: [v / row['cycles'] for v in values] for n, values in zip(names, raw)}, trace=row['trace'])
        results[name] = rows
    save(out / 'counts.json', results)


def pmu(out):
    check_identity(CURRENT)
    for name in SOURCES:
        sample(out, name, 'coremark', 'pmu', perf=['stat', '-x,', '-o', out / (name + '-stat.csv'),
            '-e', 'cycles:u,instructions:u,branches:u,branch-misses:u'])
        sample(out, name, 'coremark', 'sample', perf=['record', '-o', out / (name + '-perf.data'),
            '-e', 'cycles:u', '-F', '499', '--call-graph', 'dwarf,8192'])
        run(['perf', 'report', '--stdio', '--no-children', '-i', out / (name + '-perf.data')], out / (name + '-perf.txt'))
        run(['perf', 'report', '--stdio', '--no-children', '--sort', 'symbol,srcline', '--percent-limit', '.2',
             '-i', out / (name + '-perf.data')], out / (name + '-lines.txt'))


def cache_pmu(out):
    check_identity(CURRENT)
    for name in SOURCES:
        sample(out, name, 'coremark', 'cache-pmu', perf=['stat', '-x,', '-o', out / (name + '-cache.csv'),
            '-e', 'instructions:u,L1-icache-loads:u,L1-icache-load-misses:u,L1-dcache-loads:u,L1-dcache-load-misses:u'])


def report(out):
    check_identity(CURRENT)
    counts = json.loads((out / 'counts.json').read_text())
    result = dict(static=json.loads((out / 'static.json').read_text()),
        counts=counts, performance_reference=identity(CURRENT / 'report.json'), diagnostics={})
    for model in result['static']['models'].values():
        for entry in [model['binary'], model['header'], *model['sources']]:
            if identity(entry['path']) != entry:
                raise ValueError('generated source or binary changed: ' + entry['path'])
    cycles = counts['grhsim']['coremark']['cycles']
    for name in SOURCES:
        pmu = {}
        for suffix in ('stat', 'cache'):
            items = {}
            for row in csv.reader((out / (name + '-' + suffix + '.csv')).open()):
                if len(row) >= 5:
                    items[row[2]] = dict(count=float(row[0]), running_percent=float(row[4]),
                        per_guest_cycle=float(row[0]) / cycles)
            pmu[suffix] = items
        pmu['ipc'] = pmu['stat']['instructions:u']['count'] / pmu['stat']['cycles:u']['count']
        text = (out / (name + '-perf.txt')).read_text()
        pmu['lost_samples'] = int(re.search(r'Total Lost Samples: (\d+)', text)[1])
        pmu['hotspots'] = [dict(percent=float(p), symbol=s) for p, s in re.findall(
            r'^\s*([\d.]+)%\s+\S+\s+\S+\s+\[.\] (.+)$', text, re.M)]
        result['diagnostics'][name] = pmu
    result['pmu_ratio_decomposition'] = {}
    g = result['diagnostics']['grhsim']
    for name in ('verilator', 'verilator-original'):
        v = result['diagnostics'][name]
        result['pmu_ratio_decomposition'][name] = dict(
            instruction_ratio=g['stat']['instructions:u']['count'] / v['stat']['instructions:u']['count'],
            ipc_factor=v['ipc'] / g['ipc'],
            cycle_ratio=g['stat']['cycles:u']['count'] / v['stat']['cycles:u']['count'])
    groups = {int(row['group']): row['phase'] for row in csv.DictReader((ORIGINAL / 'sources.csv').open())}
    data = counts['grhsim']['coremark']['counts']
    sums = {k: sum(v) for k, v in data.items()}
    result['grhsim_execution'] = dict(
        compute_groups_per_cycle=sum(sum(v) for k, v in data.items() if k.startswith('group:') and groups[int(k[6:])] == 'compute') / cycles,
        commit_groups_per_cycle=sum(sum(v) for k, v in data.items() if k.startswith('group:') and groups[int(k[6:])] == 'commit') / cycles,
        scalar_change_fraction=sums['scalar_changes'] / sums['scalar_comparisons'],
        packed_group_change_fraction=sums['packed_changed_groups'] / sums['packed_comparisons'],
        packed_bit_change_fraction=sums['packed_changed_bits'] / (8 * sums['packed_comparisons']),
        direct_flag_or_per_cycle=sums['direct_active_or_executions'] / cycles)
    for extra in ('compiled-hot-functions', 'table-shapes', 'concat-slice-shapes'):
        result[extra.replace('-', '_')] = json.loads((out / (extra + '.json')).read_text())
    samples = []
    for p in sorted((out / 'runs').glob('*/*/result.json')):
        row = json.loads(p.read_text())
        expected = (result['static']['models'][row['backend']]['binary'] if row['backend'] in SOURCES else
                    json.loads((out / 'count-builds.json').read_text())[row['backend'].removesuffix('-counts')]['binary'])
        if row['binary']['sha256'] != expected['sha256'] or row['placement_errors']:
            raise ValueError('diagnostic sample identity or placement mismatch')
        samples.append(dict(path=str(p), backend=row['backend'], cycles=row['cycles'],
                            sibling_idle=row['cpu_idle_percent']['288'], trace=row.get('trace')))
    result['samples'] = samples
    expected_samples = {(stage, name) for stage in ('pmu', 'sample', 'cache-pmu') for name in SOURCES}
    expected_samples.update((stage, name + '-counts') for stage in ('count-smoke', 'count-coremark') for name in SOURCES)
    actual_samples = {(Path(row['path']).parent.parent.name, row['backend']) for row in samples}
    if actual_samples != expected_samples:
        raise ValueError('diagnostic run set is incomplete or contains unexpected samples')
    result['analysis_driver'] = identity(__file__)
    result['scope'] = 'Frozen production binaries for PMU; counter binaries for execution counts only. Counter reset excludes initialization. No new paired performance or production change.'
    save(out / 'report.json', result)
    print(json.dumps(result['pmu_ratio_decomposition'], indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['static', 'extras', 'build-counts', 'count', 'pmu', 'cache-pmu', 'report'])
    parser.add_argument('--output', type=Path, default=ROOT / 'build/cv32e40p/code-shapes-v1')
    parser.add_argument('--jobs', type=int, default=16)
    args = parser.parse_args(); out = args.output.resolve()
    if args.stage == 'static': static_report(out)
    elif args.stage == 'extras': inspect_extras(out)
    elif args.stage == 'build-counts': build_counts(out, args.jobs)
    elif args.stage == 'count': count(out)
    elif args.stage == 'pmu': pmu(out)
    elif args.stage == 'cache-pmu': cache_pmu(out)
    elif args.stage == 'report': report(out)


if __name__ == '__main__': main()
