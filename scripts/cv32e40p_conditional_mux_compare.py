#!/usr/bin/env python3
"""Measure one frozen policy for private scalar mux-arm conditional evaluation."""
import argparse
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
BACKENDS = ('grhsim_event_regions', 'grhsim_conditional_mux', 'verilator')


def build(out, tools, jobs):
    if not platform.node().startswith('node030'):
        raise ValueError('build on node030 for -march=native')
    if out.exists(): raise FileExistsError('use a new output directory')
    original = check(BASE)
    model = BASE / BACKENDS[0]
    out.mkdir(parents=True)
    (out / 'firmware').symlink_to(BASE / 'firmware', target_is_directory=True)
    (out / 'verification.json').symlink_to(BASE / 'verification.json')
    frozen = out / 'native-frozen'; frozen.mkdir()
    for src in (tools / 'cv32e40p_emit', tools / 'cv32e40p_map', tools / 'grhsim32/wolvrix/libwolvrix-lib.so'):
        shutil.copy2(src, frozen / src.name)
    graph = ROOT / 'build/cv32e40p/concat-slices-v1/candidate.json'
    harness = ROOT / 'build/cv32e40p/run2/inputs/fixture/harness.cpp'
    env = environment(); env['LD_LIBRARY_PATH'] = str(frozen); env['CV32_EVENT_REGIONS'] = '1'
    env['WOLVRIX_GRHSIM_SHARED_EQUALITY_DECODE'] = '1'
    env['WOLVRIX_GRHSIM_CONDITIONAL_MUX_CONES'] = '0'
    save(out / 'hypothesis.json', dict(
        mechanism='Private mux-arm producers execute eagerly before the scalar mask-select helper.',
        change='Evaluate 16..256 pure scalar operations inside their sole consuming mux branch, in the same compute group.',
        expected='Skip unused arm computation and shorten local live ranges; preserve schedule and boundary values.',
        implementation_correction='Use direct if/else assignments. The initial lambda implementation outlined closures and added call/spill overhead; retain its complete results in conditional-mux-v3.',
        policy='One static policy, default off. No profile-guided selection, threshold search or stacking of rejected experiments.'))
    run([frozen / 'cv32e40p_emit', graph, out / 'off-source', 'off'], out / 'logs/off-emit.log', env=env)
    shape = lambda entries: {name: (r['bytes'], r['sha256']) for name, r in entries.items()}
    if shape(source_inventory(model)) != shape(source_inventory(out / 'off-source')):
        save(out / 'control-source-mismatch.json', dict(expected=source_inventory(model), actual=source_inventory(out / 'off-source')))
        raise ValueError('feature-off does not reproduce frozen baseline sources')
    candidate = out / BACKENDS[1]
    env['WOLVRIX_GRHSIM_CONDITIONAL_MUX_CONES'] = '1'
    run([frozen / 'cv32e40p_emit', graph, candidate, 'off'], out / 'logs/emit.log', env=env)
    if identity(candidate / 'normalized.json')['sha256'] != identity(model / 'normalized.json')['sha256']:
        raise ValueError('emitter experiment changed the graph')
    sites = []
    for src in sorted(candidate.glob('*_sched_*.cpp')):
        for line, text in enumerate(src.read_text().splitlines(), 1):
            match = re.search(r'Conditional mux cone: root=(\d+) true_ops=(\d+) false_ops=(\d+)', text)
            if match: sites.append(dict(file=src.name, line=line, root=int(match[1]), true_ops=int(match[2]), false_ops=int(match[3])))
    if not sites: raise ValueError('conditional mux cones did not trigger')
    run([frozen / 'cv32e40p_map', candidate / 'normalized.json', out / 'sources.csv', '--event-regions'], out / 'logs/map.log', env=env)
    run(['make', '-C', candidate, '-j', jobs, 'CXX=' + str(CXX), 'CXXFLAGS=' + ' '.join(CFLAGS)], out / 'logs/compile.log')
    run([CXX, *CFLAGS, '-DCV32_GRHSIM', '-I', candidate, harness,
         candidate / 'libgrhsim_Cv32Bench.a', '-o', candidate / 'emu'], out / 'logs/link.log')
    for backend in (BACKENDS[0], 'verilator'):
        (out / backend).mkdir(); shutil.copy2(original['binaries'][backend]['path'], out / backend / 'emu')
    snapshot = out / 'source-snapshot'; snapshot.mkdir()
    for src in (ROOT / 'wolvrix/lib/emit/grhsim_cpp.cpp', ROOT / 'testcase/cv32e40p-bench/emit.cpp',
                ROOT / 'wolvrix/lib/transform/activity_schedule.cpp', Path(__file__).resolve(),
                ROOT / 'scripts/cv32e40p_event_regions_compare.py'):
        shutil.copy2(src, snapshot / src.name)
    patch = out / 'wolvrix.patch'
    patch.write_bytes(subprocess.check_output(['git', '-C', ROOT / 'wolvrix', 'diff', '--binary']))
    save(out / 'structure.json', dict(baseline=shapes(model), candidate=shapes(candidate), sites=sites,
        off_source_identical=True, scheduled_graph_identical=True,
        emitted_sources=list(source_inventory(candidate).values())))
    save(out / 'build.json', dict(feature='conditional_mux_cones', backend_pair=BACKENDS[:2],
        frozen_inputs=[identity(p) for p in (BASE / 'build.json', graph, harness, CXX, patch,
            out / 'hypothesis.json', out / 'structure.json', out / 'verification.json', out / 'sources.csv',
            *sorted(frozen.iterdir()), *sorted(snapshot.iterdir()))],
        binaries={backend: identity(out / backend / 'emu') for backend in BACKENDS}, flags=CFLAGS,
        scope='same event-region schedule and normalized RTL; only private pure scalar mux cones'))
    print(json.dumps(dict(sites=sites, shape=shapes(candidate)), indent=2))


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
