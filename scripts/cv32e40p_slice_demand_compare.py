#!/usr/bin/env python3
"""One frozen narrow-window fusion experiment with the retained event-region emitter."""
import argparse
from collections import Counter
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

from cv32e40p_compare import ROOT, CXX, CFLAGS, environment, identity, run, save, sample
from cv32e40p_event_regions_compare import check, source_inventory, shapes, verify, measure
from cv32e40p_binary_shape import function_symbols, disassemble, instructions, instruction_shape

BASE = ROOT / 'build/cv32e40p/event-regions-v3'
EMITTER = ROOT / 'build/cv32e40p/shared-regions-v3/native-frozen'
BACKENDS = ('grhsim_event_regions', 'grhsim_slice_demand', 'verilator')


def graph_shape(path):
    graph = json.loads(path.read_text())['graphs'][0]
    return dict(operations=len(graph['ops']), values=len(graph['vals']),
        kinds=dict(Counter(op['kind'] for op in graph['ops'])),
        transformed=[dict(symbol=op['sym'], kind=op['kind'], inputs=op['in'], outputs=op['out'])
            for op in graph['ops'] if op.get('loc', {}).get('pass') == 'slice-demand'])


def build(out, tools, jobs):
    if not platform.node().startswith('node030'): raise ValueError('build on node030 for -march=native')
    if out.exists(): raise FileExistsError('use a new output directory')
    original = check(BASE)
    out.mkdir(parents=True)
    (out / 'firmware').symlink_to(BASE / 'firmware', target_is_directory=True)
    (out / 'verification.json').symlink_to(BASE / 'verification.json')
    emitter = out / 'native-frozen'; emitter.mkdir()
    for src in EMITTER.iterdir(): shutil.copy2(src, emitter / src.name)
    transform = out / 'native-transform'; transform.mkdir()
    for src in (tools / 'cv32e40p_slice_demand', tools / 'grhsim32/wolvrix/libwolvrix-lib.so'):
        shutil.copy2(src, transform / src.name)
    graph = ROOT / 'build/cv32e40p/concat-slices-v1/candidate.json'
    harness = ROOT / 'build/cv32e40p/run2/inputs/fixture/harness.cpp'
    env = environment(); env['LD_LIBRARY_PATH'] = str(emitter)
    env['CV32_EVENT_REGIONS'] = '1'; env['CV32_EVENT_REGIONS_SHARED'] = '0'
    env['WOLVRIX_GRHSIM_LOCAL_EQUALITY_DECODE'] = '0'
    transform_env = dict(env, LD_LIBRARY_PATH=str(transform))
    save(out / 'hypothesis.json', dict(
        mechanism='A narrow final slice still requires wide logical shifts, muxes and bitwise temporaries in the retained model.',
        change='Propagate a 2..64-bit static window through pure wide expressions and lower shifts of a <=64-bit sparse span to guarded scalar shifts.',
        bounds=dict(min_wide_width=128, max_wide_width=4096, max_depth=32, max_plan_expressions=256),
        semantics='Explicit two-state, logical shifts, original scalar SSA snapshots; guard huge shift amounts and preserve other users.',
        expected='Remove wide temporaries and word helpers from the requested windows without new decode caches or region policies.',
        risks='Scalar guard arithmetic and changed scheduling may offset saved wide work; remaining wide consumers stay intact.',
        policy='One bounded static lowering; no parameter scan or post-run subset selection.'))
    for label, mode in [('control', 'off'), ('candidate', 'on')]:
        run([transform / 'cv32e40p_slice_demand', graph, out / (label + '.json'), mode],
            out / ('logs/' + label + '-transform.log'), env=transform_env)
    run([emitter / 'cv32e40p_emit', out / 'control.json', out / 'off-source', 'off'],
        out / 'logs/off-emit.log', env=env)
    shape = lambda entries: {name: (v['bytes'], v['sha256']) for name, v in entries.items()}
    if shape(source_inventory(BASE / BACKENDS[0])) != shape(source_inventory(out / 'off-source')):
        save(out / 'control-source-mismatch.json', dict(expected=source_inventory(BASE / BACKENDS[0]), actual=source_inventory(out / 'off-source')))
        raise ValueError('control transform/emission does not reproduce retained sources')
    if not re.search(r'roots=[1-9]', (out / 'logs/candidate-transform.log').read_text()):
        raise ValueError('no narrow slice was transformed')
    candidate = out / BACKENDS[1]
    run([emitter / 'cv32e40p_emit', out / 'candidate.json', candidate, 'off'], out / 'logs/emit.log', env=env)
    run([emitter / 'cv32e40p_map', out / 'candidate.json', out / 'sources.csv', '--event-regions'],
        out / 'logs/mapping.log', env=env)
    run(['make', '-C', candidate, '-j', jobs, 'CXX=' + str(CXX), 'CXXFLAGS=' + ' '.join(CFLAGS)], out / 'logs/compile.log')
    run([CXX, *CFLAGS, '-DCV32_GRHSIM', '-I', candidate, harness,
        candidate / 'libgrhsim_Cv32Bench.a', '-o', candidate / 'emu'], out / 'logs/link.log')
    for backend in (BACKENDS[0], 'verilator'):
        (out / backend).mkdir(); shutil.copy2(original['binaries'][backend]['path'], out / backend / 'emu')
    snapshot = out / 'source-snapshot'; snapshot.mkdir()
    for src in (ROOT / 'wolvrix/lib/transform/slice_demand.cpp', ROOT / 'wolvrix/include/transform/slice_demand.hpp',
                ROOT / 'wolvrix/lib/core/transform.cpp', ROOT / 'testcase/cv32e40p-bench/slice_demand.cpp',
                ROOT / 'wolvrix/tests/transform/test_slice_demand.cpp', Path(__file__).resolve(),
                ROOT / 'scripts/cv32e40p_event_regions_compare.py'):
        name = 'bench_slice_demand.cpp' if src == ROOT / 'testcase/cv32e40p-bench/slice_demand.cpp' else src.name
        shutil.copy2(src, snapshot / name)
    patch = out / 'wolvrix.patch'; patch.write_bytes(subprocess.check_output(['git', '-C', ROOT / 'wolvrix', 'diff', '--binary']))
    save(out / 'structure.json', dict(baseline=shapes(BASE / BACKENDS[0]), candidate=shapes(candidate),
        off_source_identical=True, emitter_library_identical=True,
        graphs={name: graph_shape(out / (name + '.json')) for name in ('control', 'candidate')},
        emitted_sources=list(source_inventory(candidate).values())))
    save(out / 'build.json', dict(feature='slice_demand', backend_pair=BACKENDS[:2],
        frozen_inputs=[identity(p) for p in (BASE / 'build.json', graph, harness, CXX, patch, out / 'sources.csv',
            out / 'hypothesis.json', out / 'structure.json', out / 'verification.json', out / 'control.json', out / 'candidate.json',
            *sorted(emitter.iterdir()), *sorted(transform.iterdir()), *sorted(snapshot.iterdir()))],
        binaries={backend: identity(out / backend / 'emu') for backend in BACKENDS}, flags=CFLAGS,
        scope='same input graph, frozen scheduler/emitter and workload; one narrow-window graph transform'))
    print(json.dumps({k: shapes(candidate)[k] for k in ('checked_values', 'supernodes', 'scheduler_bytes')}, indent=2))


def diagnose(out):
    manifest = check(out)
    if (out / 'diagnostics.json').exists(): raise FileExistsError('diagnostics already recorded')
    models, results = {}, {}
    for backend in BACKENDS:
        path = out / (backend + '-stat.csv')
        if path.exists(): raise FileExistsError(path)
        results[backend] = sample(out, backend, 'coremark', 'diagnostic-stat', perf=[
            'stat', '-x,', '-o', path, '-e', 'cycles:u,instructions:u,branches:u,branch-misses:u'])
        functions = []
        for symbol in function_symbols(Path(manifest['binaries'][backend]['path'])):
            name = symbol['symbol']
            selected = name.startswith('GrhSIM_Cv32Bench::eval') if backend != 'verilator' else (
                name.startswith('VCv32Bench___024root___') and any(tag in name for tag in (
                    '___nba_', '___act_', '___eval_ico', '___eval_act', '___eval_nba', '___eval_body')))
            if not selected: continue
            asm = disassemble(Path(manifest['binaries'][backend]['path']), symbol)
            functions.append(dict(**symbol, **instruction_shape(instructions(asm))))
            dest = out / 'assembly' / backend / f'function-{symbol["address"]:x}.s'
            dest.parent.mkdir(parents=True, exist_ok=True); dest.write_text(asm)
        models[backend] = dict(functions=functions, totals={key: sum(f[key] for f in functions)
            for key in ('bytes', 'instructions', 'memory_operand_instructions', 'stack_operand_instructions', 'compare_or_test', 'cmov_or_setcc')})
    data = out / 'candidate-perf.data'
    results['profile'] = sample(out, BACKENDS[1], 'coremark', 'diagnostic-record', perf=[
        'record', '-o', data, '-e', 'cycles:u', '-F', '499', '--call-graph', 'dwarf,8192'])
    run(['perf', 'report', '--stdio', '--no-children', '--call-graph', 'none', '-i', data], out / 'candidate-perf.txt')
    save(out / 'diagnostics.json', dict(scope='Independent diagnostic samples; static stack operands are not dynamic spill counts.',
        build=identity(out / 'build.json'), models=models, runs=results, driver=identity(__file__)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('build', 'verify', 'measure', 'diagnose'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tools', type=Path, default=ROOT / 'build/cv32e40p/tools')
    parser.add_argument('--jobs', type=int, default=12)
    args = parser.parse_args(); out = args.output.resolve()
    if args.stage == 'build': build(out, args.tools.resolve(), args.jobs)
    elif args.stage == 'verify': verify(out)
    elif args.stage == 'measure': measure(out)
    else: diagnose(out)
