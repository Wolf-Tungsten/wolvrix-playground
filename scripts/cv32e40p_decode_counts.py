#!/usr/bin/env python3
"""Count the frozen shared decoder's work, independently of performance samples."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import platform
import re
import shutil

from cv32e40p_compare import ROOT, CXX, CFLAGS, identity, run, sample, save
from cv32e40p_code_shapes import Probes
from cv32e40p_regfile_compare import check_identity

CURRENT = ROOT / 'build/cv32e40p/shared-equality-validated'
MODEL = CURRENT / 'grhsim_shared_equality'
PREVIOUS = ROOT / 'build/cv32e40p/remaining-gap-v1'
ORIGINAL = ROOT / 'build/cv32e40p/run2'
VERILATOR_COUNTS = ROOT / 'build/cv32e40p/code-shapes-v1/counts.json'
CSR_SOURCES = ('_val_134', '_val_6162')


class DecodeProbes(Probes):
    def __init__(self, values, groups):
        super().__init__()
        self.values = values
        self.cache_by_value = {i: str(g['cache']) for g in groups for i in g['value_ids']}
        self.sites = Counter()
        self.cache_sites = Counter()

    def instrument(self, name, text):
        result = super().instrument(name, text)
        if name != 'grhsim':
            return result

        def predicate(match):
            index, expression = match[2], match[3]
            if index not in self.values:
                raise ValueError('unknown predicate: ' + index)
            extra = self.hit('cmp:' + index) + self.hit('chg:' + index, 'grhsim_changed_' + index)
            kind = 'ordinary'
            if index in self.cache_by_value:
                cache = self.cache_by_value[index]
                if expression.endswith(' != false)'):
                    kind = 'clear'
                elif expression.endswith(' != true)'):
                    kind = 'set'
                elif 'grhsim_eq_address_' + cache + ' ==' in expression:
                    kind = 'initial_predicate'
                else:
                    raise ValueError('unexpected shared predicate: ' + expression)
                extra += self.hit('decode:' + cache + ':' + kind)
            self.sites[index, kind] += 1
            return match[1] + '\n' + extra

        result = re.sub(r'(const bool grhsim_changed_(\d+) = ([^\n]+);)', predicate, result)

        def cache_probe(match, kind, before=False):
            cache = match[2]
            self.cache_sites[cache, kind] += 1
            hit = self.hit('decode:' + cache + ':' + kind)
            return hit + '\n' + match[1] if before else match[1] + '\n' + hit

        # Count visits outside the valid guard, and cold/changed entries inside it.
        # A previous-address comparison is evaluated on visits minus cold entries.
        result = re.sub(r'(if \(!grhsim_eq_cache_(\d+)\.valid\) \{)',
                        lambda m: cache_probe(m, 'visits', before=True), result)
        result = re.sub(r'(if \(!grhsim_eq_cache_(\d+)\.valid\) \{)',
                        lambda m: cache_probe(m, 'initializations'), result)
        result = re.sub(r'(\} else if \(grhsim_eq_address_(\d+) != grhsim_eq_cache_\2\.previous\) \{)',
                        lambda m: cache_probe(m, 'address_changes'), result)
        return result

    def validate(self, groups):
        expected = Counter()
        for index in self.values:
            for kind in (('initial_predicate', 'clear', 'set') if index in self.cache_by_value else ('ordinary',)):
                expected[index, kind] = 1
        if self.sites != expected:
            raise ValueError('missing or duplicate predicate sites')
        expected_caches = Counter({(str(g['cache']), kind): 1 for g in groups
                                  for kind in ('visits', 'initializations', 'address_changes')})
        if self.cache_sites != expected_caches:
            raise ValueError('missing or duplicate decoder guards')


def check(out):
    check_identity(CURRENT)
    built = json.loads((out / 'build.json').read_text())
    for entry in built['inputs'] + built['outputs']:
        if identity(entry['path']) != entry:
            raise ValueError('frozen counter input/output changed: ' + entry['path'])
    return built


def build(out, jobs):
    manifest = check_identity(CURRENT)
    previous = json.loads((PREVIOUS / 'static.json').read_text())
    graph = identity(MODEL / 'normalized.json')
    if graph['sha256'] != previous['graph']['sha256']:
        raise ValueError('value attribution requires the identical scheduled graph')
    coverage = json.loads((CURRENT / 'decode-coverage.json').read_text())
    groups = coverage['groups']
    inputs = [identity(p) for p in [CURRENT / 'build.json', CURRENT / 'decode-coverage.json',
        PREVIOUS / 'static.json', PREVIOUS / 'counts.json', VERILATOR_COUNTS,
        ORIGINAL / 'verification.json', Path(manifest['harness']['path']),
        Path(__file__), ROOT / 'scripts/cv32e40p_code_shapes.py', ROOT / 'scripts/cv32e40p_compare.py']]
    inputs += [graph, manifest['cxx'], manifest['binaries']['grhsim_shared_equality']]
    out.mkdir(parents=True, exist_ok=False)
    for name in ('firmware', 'verification.json'):
        (out / name).symlink_to(ORIGINAL / name)
    dest = out / 'grhsim-counts'
    dest.mkdir()
    probes = DecodeProbes(previous['values'], groups)
    for path in sorted(MODEL.iterdir()):
        if path.suffix not in ('.cpp', '.h', '.hpp') and path.name != 'Makefile':
            continue
        inputs.append(identity(path))
        target = dest / path.name
        shutil.copy2(path, target)
        if path.suffix == '.cpp' and (path.name.endswith(('_eval.cpp', '_state.cpp')) or '_sched_' in path.name):
            target.write_text(probes.instrument('grhsim', path.read_text()))
    probes.validate(groups)
    if len([n for n in probes.entries if n.startswith('group:')]) != len(previous['groups']):
        raise ValueError('missing supernode counters')
    (dest / 'shape_counters.hpp').write_text(probes.header())
    harness = '#include "shape_counters.hpp"\n' + Path(manifest['harness']['path']).read_text()
    harness = harness.replace('m.eval();', 'cv32_shape::phase=static_cast<unsigned>(m.clk_i); m.eval();')
    for text in ('        started = Clock::now();', '        sim_s += seconds(started);'):
        if harness.count(text) != 1:
            raise ValueError('unexpected harness timing boundary')
    harness = harness.replace('        started = Clock::now();', '        cv32_shape::reset();\n        started = Clock::now();')
    harness = harness.replace('        sim_s += seconds(started);', '        sim_s += seconds(started);\n        cv32_shape::dump();')
    (dest / 'harness.cpp').write_text(harness)
    save(dest / 'probes.json', dict(entries=probes.entries, groups=groups,
        scope='source old/new predicates and separate cache guards; after loading/reset; not Host instructions or timings'))
    run(['make', '-C', dest, '-j', jobs, 'CXX=' + str(CXX), 'CXXFLAGS=' + ' '.join(CFLAGS)], out / 'logs/build.log')
    run([CXX, *CFLAGS, '-DCV32_GRHSIM', '-I', dest, dest / 'harness.cpp',
         dest / 'libgrhsim_Cv32Bench.a', '-o', dest / 'emu'], out / 'logs/link.log')
    outputs = [identity(p) for p in sorted(dest.iterdir()) if p.suffix in ('.cpp', '.hpp', '.json') or p.name == 'emu']
    save(out / 'build.json', dict(inputs=inputs, outputs=outputs, groups=groups, baseline_graph=previous['graph']))


def count(out):
    check(out)
    expected = json.loads((out / 'verification.json').read_text())['workloads']
    names = json.loads((out / 'grhsim-counts/probes.json').read_text())['entries']
    result = {}
    for workload in ('smoke', 'coremark'):
        row = sample(out, 'grhsim-counts', workload, 'count-' + workload, trace=True)
        if row['trace']['sha256'] != expected[workload]['verilator']['trace']['sha256']:
            raise ValueError('instrumented model bus trace differs')
        log = (out / 'runs' / ('count-' + workload) / 'grhsim-counts/run.log').read_text()
        matches = re.findall(r'^CV32_SHAPE (.+)$', log, re.M)
        if len(matches) != 1:
            raise ValueError('missing/duplicate counter record')
        raw = json.loads(matches[0])['counts']
        if len(raw) != len(names):
            raise ValueError('counter schema mismatch')
        result[workload] = dict(cycles=row['cycles'], counts=dict(zip(names, raw)), trace=row['trace'])
    save(out / 'counts.json', result)


def report(out):
    built = check(out)
    old = json.loads((PREVIOUS / 'counts.json').read_text())['coremark']
    new = json.loads((out / 'counts.json').read_text())['coremark']
    values = json.loads((PREVIOUS / 'static.json').read_text())['values']
    if old['cycles'] != new['cycles'] or old['trace']['sha256'] != new['trace']['sha256']:
        raise ValueError('before/after workload differs')
    n = new['cycles']
    old_totals = {k: sum(v) for k, v in old['counts'].items()}
    totals = {k: sum(v) for k, v in new['counts'].items()}
    for i in values:
        if old['counts']['chg:' + i] != new['counts']['chg:' + i]:
            raise ValueError('per-value changes differ: ' + i)
    for k in old_totals:
        if k.startswith(('group:', 'function:')) or k == 'round':
            if old['counts'][k] != new['counts'][k]:
                raise ValueError('execution schedule changed: ' + k)
    def sum_values(prefix, ids, table=totals):
        return sum(table[prefix + i] for i in ids) / n
    rows = {}
    for source in CSR_SOURCES:
        ids = {i for i, v in values.items() if v.get('compare_source') == source}
        groups = [g for g in built['groups'] if set(g['value_ids']) <= ids]
        covered = {i for g in groups for i in g['value_ids']}
        def cache_sum(kind):
            return sum(totals['decode:' + str(g['cache']) + ':' + kind] for g in groups) / n
        before = sum_values('cmp:', ids, old_totals)
        after = sum_values('cmp:', ids)
        rows[source] = dict(predicates=len(ids), covered=len(covered), remaining=sorted(ids - covered, key=int),
            caches=[g['cache'] for g in groups], old_comparisons_per_cycle=before,
            comparisons_per_cycle=after, changes_per_cycle=sum_values('chg:', ids),
            sparse_comparisons_per_cycle=sum_values('cmp:', covered),
            ordinary_comparisons_per_cycle=sum_values('cmp:', ids - covered),
            valid_checks_per_cycle=cache_sum('visits'), initializations_per_cycle=cache_sum('initializations'),
            address_checks_per_cycle=cache_sum('visits') - cache_sum('initializations'),
            address_changes_per_cycle=cache_sum('address_changes'),
            switch_dispatches_per_cycle=2 * cache_sum('address_changes'),
            clear_cases_per_cycle=cache_sum('clear'), set_cases_per_cycle=cache_sum('set'),
            initial_predicates_per_cycle=cache_sum('initial_predicate'))
    combined = {k: sum(row[k] for row in rows.values()) for k in next(iter(rows.values()))
                if k not in ('remaining', 'caches')}
    combined['old_share_percent'] = 100 * combined['old_comparisons_per_cycle'] / (old_totals['scalar_comparisons'] / n)
    combined['share_percent'] = 100 * combined['comparisons_per_cycle'] / (totals['scalar_comparisons'] / n)
    combined['comparison_reduction_percent'] = 100 * (1 - combined['comparisons_per_cycle'] / combined['old_comparisons_per_cycle'])
    save(out / 'report.json', dict(cycles=n, by_source=rows, combined=combined,
        all_scalar_comparisons_per_cycle=dict(before=old_totals['scalar_comparisons'] / n, after=totals['scalar_comparisons'] / n),
        per_cycle={k: v / n for k, v in totals.items() if not k.startswith(('cmp:', 'chg:'))},
        per_value_changes_and_execution_schedule_unchanged=True,
        references=dict(before=identity(PREVIOUS / 'counts.json'), after=identity(out / 'counts.json'),
                        production=identity(CURRENT / 'report.json'), verilator_counts=identity(VERILATOR_COUNTS)),
        scope='old/new scalar comparisons; cache checks and switch dispatches reported separately; no instrumented timing claim'))
    print(json.dumps(dict(by_source=rows, combined=combined), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('build', 'count', 'report', 'all'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=16)
    args = parser.parse_args()
    if args.stage != 'report' and not platform.node().startswith('node030'):
        raise ValueError('build and count on node030')
    out = args.output.resolve()
    if args.stage in ('build', 'all'): build(out, args.jobs)
    if args.stage in ('count', 'all'): count(out)
    if args.stage in ('report', 'all'): report(out)


if __name__ == '__main__': main()
