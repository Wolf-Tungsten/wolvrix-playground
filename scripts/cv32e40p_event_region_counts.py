#!/usr/bin/env python3
"""Count region executions by clock level and fixed-point round; never timing."""
import argparse
import json
from pathlib import Path
import re
import shutil

from cv32e40p_compare import ROOT, CXX, CFLAGS, identity, run, sample, save
from cv32e40p_code_shapes import Probes


class RegionProbes(Probes):
    def instrument(self, name, source):
        text = super().instrument(name, source)
        return re.sub(r'(const bool grhsim_changed_(\d+) = [^\n]+;)',
            lambda m: m[1] + '\n' + self.hit('cmp:' + m[2]) +
                self.hit('chg:' + m[2], 'grhsim_changed_' + m[2]), text)


def instrument_region_source(probes, name, source):
    text = probes.instrument('grhsim', source)
    # Each emitted cone has flat branches: its private scalar statements contain
    # no nested statement blocks. Count selected arms, not the eager IR budget.
    cone_pattern = (r'(// Conditional mux cone: root=(\d+) true_ops=\d+ false_ops=\d+\n)'
                    r'(\s*if \([^\n]+\) \{\n)(.*?)'
                    r'(\n\s*} else \{\n)')
    def cone_hits(match):
        root = match[2]
        return (match[1] + probes.hit('mux_root:' + root) + '\n' + match[3] +
                probes.hit('mux_true:' + root) + '\n' + match[4] + match[5] +
                probes.hit('mux_false:' + root) + '\n')
    text, cones = re.subn(cone_pattern, cone_hits, text, flags=re.S)
    if cones != source.count('// Conditional mux cone:'):
        raise ValueError('conditional mux instrumentation did not match every root')
    change_cache_pattern = (
        r'(// Conditional mux change-trigger cache: root=(\d+) sources=\d+\n)'
        r'(\s*if \(conditional_mux_change_dirty_\[(\d+)u\]\) \{\n)')
    def change_cache_hits(match):
        root = match[2]
        return (match[1] + probes.hit('mux_cache_visits:' + root) + '\n' + match[3] +
                probes.hit('mux_cache_misses:' + root) + '\n')
    text, change_caches = re.subn(change_cache_pattern, change_cache_hits, text)
    if change_caches != source.count('// Conditional mux change-trigger cache:'):
        raise ValueError('change-trigger cache instrumentation did not match every root')
    def notification_reduction(match):
        lhs, region, bucket, rhs = match[2], match[3], match[4], match[5]
        kind = 'joint' if lhs.startswith('grhsim_joint_') else 'deferred'
        return probes.hit('notify_reduction_' + kind + ':' + region + ':' + bucket) + '\n' + match[0]
    text, reductions = re.subn(
        r'((grhsim_(?:joint_notify|any_changed)_(\d+)_(\d+)) = static_cast<bool>\(\2 \| ([^\n]+)\);)',
        notification_reduction, text)
    if reductions != len(re.findall(r'grhsim_(?:joint_notify|any_changed)_\d+_\d+ = static_cast', source)):
        raise ValueError('joint/deferred reduction probe coverage mismatch')
    def local_notify_accumulation(match):
        group = match[2] + ':' + match[3]
        return (probes.hit('mux_notify_accumulate_visits:' + group) + '\n' +
                'if (' + match[4] + ') { ' + probes.hit('mux_notify_accumulate_changes:' + group) + ' }\n' + match[0])
    text, accumulated = re.subn(
        r'(grhsim_mux_notify_group_(\d+)_(\d+) = static_cast<bool>\(grhsim_mux_notify_group_\2_\3 \| \(([^\n]+)\)\);)',
        local_notify_accumulation, text)
    if accumulated != len(re.findall(r'grhsim_mux_notify_group_\d+_\d+ = static_cast', source)):
        raise ValueError('grouped notify accumulation probe coverage mismatch')
    # Count the extra work at producers as well as avoided work at consumers.
    # Conditions contain only emitter-generated pure change predicates.
    def dirty_mark(match):
        index, condition = match[2], match[3]
        return (probes.hit('mux_invalidate_visits:' + index) + '\n' +
                'if (' + condition + ') { ' + probes.hit('mux_invalidations:' + index) + ' }\n' + match[0])
    text, dirty_marks = re.subn(
        r'(conditional_mux_change_dirty_\[(\d+)u\] = static_cast<bool>\(conditional_mux_change_dirty_\[\2u\] \| \(([^\n]+)\)\);)',
        dirty_mark, text)
    def unconditional_mark(match):
        index = match[2]
        return (probes.hit('mux_invalidate_visits:' + index) + '\n' +
                probes.hit('mux_invalidations:' + index) + '\n' + match[0])
    text, unconditional_marks = re.subn(r'(conditional_mux_change_dirty_\[(\d+)u\] = true;)', unconditional_mark, text)
    expected_marks = len(re.findall(r'conditional_mux_change_dirty_\[\d+u\] = (?:static_cast|true)', source))
    if dirty_marks + unconditional_marks != expected_marks:
        raise ValueError('change-trigger invalidation probe coverage mismatch')
    text, input_caches = re.subn(r'(if \(grhsim_mux_cache_miss_(\d+)\) \{)',
        lambda m: probes.hit('mux_cache_visits:' + m[2]) + '\n' + m[1] + '\n' +
            probes.hit('mux_cache_misses:' + m[2]), text)
    if input_caches != source.count('// Conditional mux input cache:'):
        raise ValueError('conditional mux cache instrumentation did not match every root')
    text = re.sub(r'(if \(grhsim_local_eq_address_\d+ != local_equality_previous_(\d+)_\) \{)',
        lambda m: probes.hit('local_decode_checks:' + m[2]) + '\n' + m[1] + '\n' +
            probes.hit('local_decode_updates:' + m[2]), text)
    # Count the source check separately from sparse predicate updates. Both the
    # contiguous decoder and semantic families use this same guard sequence.
    text, cache_visits = re.subn(r'(if \(!grhsim_eq_cache_(\d+)\.valid\) \{)',
        lambda m: probes.hit('decode_visits:' + m[2]) + '\n' + m[1] + '\n' +
            probes.hit('decode_initializations:' + m[2]), text)
    text, cache_changes = re.subn(r'(\} else if \(grhsim_eq_address_(\d+) != grhsim_eq_cache_\2\.previous\) \{)',
        lambda m: m[1] + '\n' + probes.hit('decode_address_changes:' + m[2]), text)
    if cache_visits != source.count('// Shared equality decode:') or cache_changes != cache_visits:
        raise ValueError('shared equality instrumentation did not match every cache')
    if name.endswith('_eval.cpp'):
        marker = 'while (pending_eval_round) {'
        if text.count(marker) != 1:
            raise ValueError('expected one fixed-point loop')
        # The shared instrumentation counts the round immediately after this
        # brace, before ++fixed_point_round_count. Label the upcoming round
        # before that counter as well as before the group/function counters.
        text = text.replace(marker, marker + '\ncv32_shape::phase = clk_i ? '
            'static_cast<unsigned>(fixed_point_round_count >= 2 ? 3 : fixed_point_round_count + 1) : 0;')
    return text


def main(source, out, jobs, detailed=False, backend='grhsim_event_regions'):
    if out.exists(): raise FileExistsError('use a new diagnostic directory')
    manifest = json.loads((source / 'build.json').read_text())
    original = source / backend
    assert identity(original / 'emu') == manifest['binaries'][backend]
    out.mkdir(parents=True)
    (out / 'firmware').symlink_to(source / 'firmware')
    (out / 'verification.json').symlink_to(source / 'verification.json')
    dest = out / 'grhsim-counts'; dest.mkdir()
    for p in original.iterdir():
        if p.is_file() and (p.suffix in ('.cpp', '.hpp', '.o', '.a') or p.name == 'Makefile'):
            shutil.copy2(p, dest / p.name)
    probes = RegionProbes() if detailed else Probes()
    for p in sorted(dest.glob('*.cpp')):
        if '_sched_' in p.name or p.name.endswith(('_eval.cpp', '_state.cpp')):
            p.write_text(instrument_region_source(probes, p.name, p.read_text()))
    n = len(probes.entries)
    (dest / 'shape_counters.hpp').write_text('''#pragma once
#include <array>
#include <bit>
#include <cstdint>
#include <iostream>
namespace cv32_shape {
inline unsigned phase=0;
inline std::array<std::array<std::uint64_t,4>,''' + str(n) + '''> counts{};
inline void reset(){for(auto &v:counts)v={0,0,0,0};}
inline void dump(){std::cout<<"CV32_SHAPE {\\"counts\\":[";
for(unsigned i=0;i<counts.size();++i){if(i)std::cout<<',';
std::cout<<'['<<counts[i][0]<<','<<counts[i][1]<<','<<counts[i][2]<<','<<counts[i][3]<<']';}
std::cout<<"]}\\n";}
}
''')
    harness = (ROOT / 'build/cv32e40p/run2/inputs/fixture/harness.cpp').read_text()
    harness = '#include "shape_counters.hpp"\n' + harness
    harness = harness.replace('m.eval();', 'cv32_shape::phase=static_cast<unsigned>(m.clk_i); m.eval();')
    assert harness.count('        started = Clock::now();') == 1
    harness = harness.replace('        started = Clock::now();', '        cv32_shape::reset();\n        started = Clock::now();')
    harness = harness.replace('        sim_s += seconds(started);', '        sim_s += seconds(started);\n        cv32_shape::dump();')
    (dest / 'harness.cpp').write_text(harness)
    run(['make', '-C', dest, '-j', jobs, 'CXX=' + str(CXX), 'CXXFLAGS=' + ' '.join(CFLAGS)], out / 'compile.log')
    run([CXX, *CFLAGS, '-DCV32_GRHSIM', '-I', dest, dest / 'harness.cpp',
         dest / 'libgrhsim_Cv32Bench.a', '-o', dest / 'emu'], out / 'link.log')
    rows = {}
    for workload in ('smoke', 'coremark'):
        row = sample(out, 'grhsim-counts', workload, workload, trace=True)
        expected = json.loads((out / 'verification.json').read_text())['workloads'][workload]['verilator']
        assert row['trace']['sha256'] == expected['trace']['sha256']
        log = (out / 'runs' / workload / 'grhsim-counts/run.log').read_text()
        counts = json.loads(re.search(r'^CV32_SHAPE (.+)$', log, re.M)[1])['counts']
        assert len(counts) == len(probes.entries)
        counters = dict(zip(probes.entries, counts))
        for name, values in counters.items():
            if name.startswith('mux_root:'):
                root = name.split(':')[1]
                assert values == [a + b for a, b in zip(counters['mux_true:' + root], counters['mux_false:' + root])]
        if detailed:
            for prefix, aggregate in [('cmp:', 'scalar_comparisons'), ('chg:', 'scalar_changes')]:
                assert [sum(v[p] for k, v in counters.items() if k.startswith(prefix))
                        for p in range(4)] == counters[aggregate]
        rows[workload] = dict(cycles=row['cycles'], trace=row['trace'], counts=counters)
    save(out / 'counts.json', rows)
    save(out / 'inputs.json', dict(model=manifest['binaries'][backend], binary=identity(dest / 'emu'),
        source_manifest=identity(source / 'build.json'), driver=identity(Path(__file__).resolve()),
        detailed=detailed,
        counter_sources=[identity(p) for p in sorted(dest.glob('*.cpp'))],
        phases=['clock low', 'clock high round 1', 'clock high round 2', 'clock high round 3+'],
        scope='diagnostic execution counts; no timing conclusion'))
    c = rows['coremark']; cycles=c['cycles']
    print(json.dumps({k:[x/cycles for x in v] for k,v in c['counts'].items()
                      if k.startswith(('group:', 'scalar_'))}, indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=12)
    parser.add_argument('--detailed', action='store_true', help='also count each scalar value, checking aggregate sums')
    parser.add_argument('--backend', default='grhsim_event_regions')
    args=parser.parse_args()
    main(args.source.resolve(), args.output.resolve(), args.jobs, args.detailed, args.backend)
