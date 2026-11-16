#!/usr/bin/env python3
"""Frozen, independent comparisons for repairs identified by the negative-result review."""
import argparse
import csv
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

from cv32e40p_compare import ROOT, CXX, CFLAGS, environment, identity, run, save, sample, signature, summarize_named
from cv32e40p_event_regions_compare import check, shapes, source_inventory
from cv32e40p_binary_shape import function_symbols, disassemble, instructions, instruction_shape

BASE = ROOT / 'build/cv32e40p/conditional-mux-v4'
BASE_BACKEND = 'grhsim_conditional_mux'
GRAPH = ROOT / 'build/cv32e40p/concat-slices-v1/candidate.json'
HARNESS = ROOT / 'build/cv32e40p/run2/inputs/fixture/harness.cpp'


def read(path): return json.loads(path.read_text())


def native_library(tools):
    """Accept either a build tree or an archived flat native-tool directory."""
    flat = tools / 'libwolvrix-lib.so'
    return flat if flat.is_file() else tools / 'grhsim32/wolvrix/libwolvrix-lib.so'


def snapshot_source(tools, source, name=None):
    # Replaying a withdrawn candidate must archive its original source, not
    # falsely label the current worktree as the source of the frozen tool.
    if (tools / 'libwolvrix-lib.so').is_file():
        return tools.parent / 'source-snapshot' / (name or source.name)
    return source


def emit_environment(native):
    env = {k: v for k, v in environment().items() if not k.startswith('CV32_')}
    env.update(LD_LIBRARY_PATH=str(native), CV32_EVENT_REGIONS='1', CV32_EVENT_REGIONS_SHARED='0',
               WOLVRIX_GRHSIM_CONDITIONAL_MUX_CONES='1', WOLVRIX_GRHSIM_LOCAL_EQUALITY_DECODE='0')
    return env


def same_sources(a, b):
    shape = lambda p: {n: (x['bytes'], x['sha256']) for n, x in source_inventory(p).items()}
    return shape(a) == shape(b)


def cone_sites(folder):
    return sorted(tuple(map(int, m)) for p in folder.glob('*_sched_*.cpp') for m in re.findall(
        r'Conditional mux cone: root=(\d+) true_ops=(\d+) false_ops=(\d+)', p.read_text()))


def normalize_bool_table(text):
    text = re.sub(r'std::array<std::uint8_t, (\d+)> (local_equality_table_\d+_)', r'std::array<bool, \1> \2', text)
    text = re.sub(r'(local_equality_table_\d+_\[[^\]\n]+\]) = UINT8_C\(0\)', r'\1 = false', text)
    text = re.sub(r'(local_equality_table_\d+_\[[^\]\n]+\]) = UINT8_C\(1\)', r'\1 = true', text)
    text = re.sub(r'(local_equality_table_\d+_)\.fill\(UINT8_C\(0\)\)', r'\1.fill(false)', text)
    text = re.sub(r'(local_equality_table_\d+_\[\d+u\]) != UINT8_C\(0\)', r'\1', text)
    # The ordinary scalar renderer strips redundant expression parentheses
    # differently for a comparison and a direct Boolean reference. This is a
    # comparison-only canonical string, never compiled as C++.
    while True:
        normalized = re.sub(r'\((local_equality_table_\d+_\[\d+u\])\)', r'\1', text)
        if normalized == text: break
        text = normalized
    return text


def compile_model(folder, out, name, jobs):
    run(['make', '-C', folder, '-j', jobs, 'CXX=' + str(CXX), 'CXXFLAGS=' + ' '.join(CFLAGS)], out / 'logs' / (name + '-compile.log'))
    run([CXX, *CFLAGS, '-DCV32_GRHSIM', '-I', folder, HARNESS, folder / 'libgrhsim_Cv32Bench.a', '-o', folder / 'emu'],
        out / 'logs' / (name + '-link.log'))


def build_bool(out, tools, jobs):
    if not platform.node().startswith('node030'): raise ValueError('build on node030 for -march=native')
    if out.exists(): raise FileExistsError(out)
    original = check(BASE); out.mkdir(parents=True)
    (out / 'firmware').symlink_to(BASE / 'firmware')
    (out / 'verification.json').symlink_to(BASE / 'verification.json')
    native = out / 'native-frozen'; native.mkdir()
    for src in (tools / 'cv32e40p_emit', tools / 'cv32e40p_map', native_library(tools)):
        shutil.copy2(src, native / src.name)
    previous = out / 'native-before'; previous.mkdir()
    for src in (BASE / 'native-frozen').iterdir(): shutil.copy2(src, previous / src.name)
    env = emit_environment(native)
    run([native / 'cv32e40p_emit', GRAPH, out / 'off-source', 'off'], out / 'logs/off-emit.log', env=env)
    if not same_sources(out / 'off-source', BASE / BASE_BACKEND): raise ValueError('default source drift')
    baseline, byte, candidate = BASE_BACKEND, 'grhsim_byte_decode', 'grhsim_bool_decode'
    backends = [baseline, byte, candidate, 'verilator']
    save(out / 'hypothesis.json', dict(
        change='Only local table representation changes from uint8_t with !=0 to native bool. Same cache families and update sites.',
        expected='Remove repeated Boolean normalization; measure separately from enabling a cache on the current retained model.',
        comparisons=[f'{candidate}/{byte}', f'{candidate}/{baseline}', f'{candidate}/verilator'],
        policy='Fixed selection and one eight-round ABCD/DCBA comparison; no threshold, group, or post-run candidate selection.'))
    for name, emitter in ((byte, previous), (candidate, native)):
        local_env = emit_environment(emitter); local_env['WOLVRIX_GRHSIM_LOCAL_EQUALITY_DECODE'] = '1'
        run([emitter / 'cv32e40p_emit', GRAPH, out / name, 'off'], out / 'logs' / (name + '-emit.log'), env=local_env)
        if identity(out / name / 'normalized.json')['sha256'] != identity(BASE / BASE_BACKEND / 'normalized.json')['sha256']:
            raise ValueError('graph changed')
    byte_files, bool_files = source_inventory(out / byte), source_inventory(out / candidate)
    if byte_files.keys() != bool_files.keys(): raise ValueError('generated file set changed')
    mismatches = []
    for filename in byte_files:
        before = normalize_bool_table((out / byte / filename).read_text())
        after = normalize_bool_table((out / candidate / filename).read_text())
        if before != after: mismatches.append(filename)
    save(out / 'representation-check.json', dict(normalized_source_equal=not mismatches, mismatches=mismatches,
        byte=byte_files, boolean=bool_files, cone_sites_equal=cone_sites(out / byte) == cone_sites(out / candidate)))
    if mismatches or cone_sites(out / byte) != cone_sites(out / candidate):
        raise ValueError('byte/bool changed more than the table representation: ' + str(mismatches))
    for name in (byte, candidate): compile_model(out / name, out, name, jobs)
    for name in (baseline, 'verilator'):
        (out / name).mkdir(); shutil.copy2(original['binaries'][name]['path'], out / name / 'emu')
    snapshot = out / 'source-snapshot'; snapshot.mkdir()
    for src in (ROOT / 'wolvrix/lib/emit/grhsim_cpp.cpp', ROOT / 'wolvrix/tests/emit/test_emit_grhsim_cpp.cpp',
                ROOT / 'scripts/cv32e40p_compare.py', Path(__file__).resolve()):
        archived = src if src.parent.name == 'scripts' else snapshot_source(tools, src)
        shutil.copy2(archived, snapshot / src.name)
    save(out / 'structure.json', dict(models={b: shapes(out / b) for b in (byte, candidate)},
        baseline=shapes(BASE / BASE_BACKEND), off_source_equal=True, graph_equal=True,
        representation_check=identity(out / 'representation-check.json')))
    save(out / 'build.json', dict(feature='local_equality_boolean_storage', backends=backends, candidate=candidate,
        comparisons=[byte, baseline, 'verilator'], flags=CFLAGS,
        frozen_inputs=[identity(p) for p in (BASE / 'build.json', GRAPH, HARNESS, CXX, out / 'hypothesis.json',
            out / 'structure.json', out / 'representation-check.json', out / 'verification.json',
            *native.iterdir(), *previous.iterdir(), *snapshot.iterdir())],
        binaries={b: identity(out / b / 'emu') for b in backends}))
    print('built byte/bool controls; only table representation differs')


def build_aligned(out, tools, jobs):
    if not platform.node().startswith('node030'): raise ValueError('build on node030 for -march=native')
    if out.exists(): raise FileExistsError(out)
    original = check(BASE); out.mkdir(parents=True)
    (out / 'firmware').symlink_to(BASE / 'firmware'); (out / 'verification.json').symlink_to(BASE / 'verification.json')
    emitter = out / 'native-emitter'; emitter.mkdir()
    for src in (BASE / 'native-frozen').iterdir(): shutil.copy2(src, emitter / src.name)
    before = out / 'native-transform-before'; before.mkdir()
    for src in (ROOT / 'build/cv32e40p/slice-demand-v1/native-transform').iterdir(): shutil.copy2(src, before / src.name)
    after = out / 'native-transform'; after.mkdir()
    for src in (tools / 'cv32e40p_slice_demand', native_library(tools)): shutil.copy2(src, after / src.name)
    env = emit_environment(emitter)
    baseline, generic, candidate = BASE_BACKEND, 'grhsim_generic_window', 'grhsim_aligned_window'
    backends = [baseline, generic, candidate, 'verilator']
    save(out / 'hypothesis.json', dict(
        change='Prove zero-padded aligned displacement and its bounded signed negation, replace a single-field window by index equality and payload slice.',
        expected='Remove generic shift/overshift/direction arithmetic left by the first slice-demand implementation.',
        controls='Old and repaired transforms use the same frozen conditional-mux scheduler/emitter. Local decode is off.',
        policy='One generic proof; no signal names, profiling, threshold search, or combination with the Boolean-table repair.'))
    for label, tool, mode in (('control', after, 'off'), ('generic', before, 'on'), ('candidate', after, 'on')):
        run([tool / 'cv32e40p_slice_demand', GRAPH, out / (label + '.json'), mode], out / 'logs' / (label + '-transform.log'),
            env=dict(env, LD_LIBRARY_PATH=str(tool)))
    run([emitter / 'cv32e40p_emit', out / 'control.json', out / 'off-source', 'off'], out / 'logs/off-emit.log', env=env)
    if not same_sources(out / 'off-source', BASE / BASE_BACKEND): raise ValueError('control source drift')
    for name, graph in ((generic, 'generic.json'), (candidate, 'candidate.json')):
        run([emitter / 'cv32e40p_emit', out / graph, out / name, 'off'], out / 'logs' / (name + '-emit.log'), env=env)
        run([emitter / 'cv32e40p_map', out / graph, out / (name + '-sources.csv'), '--event-regions'], out / 'logs' / (name + '-map.log'), env=env)
        compile_model(out / name, out, name, jobs)
    for name in (baseline, 'verilator'):
        (out / name).mkdir(); shutil.copy2(original['binaries'][name]['path'], out / name / 'emu')
    snapshot = out / 'source-snapshot'; snapshot.mkdir()
    for src in (ROOT / 'wolvrix/lib/transform/slice_demand.cpp', ROOT / 'wolvrix/tests/transform/test_slice_demand.cpp',
                ROOT / 'testcase/cv32e40p-bench/slice_demand.cpp', Path(__file__).resolve()):
        name = 'bench_slice_demand.cpp' if src.parent.name == 'cv32e40p-bench' else src.name
        archived = src if src.parent.name == 'scripts' else snapshot_source(tools, src, name)
        shutil.copy2(archived, snapshot / name)
    save(out / 'structure.json', dict(models={b: shapes(out / b) for b in (generic, candidate)},
        baseline=shapes(BASE / BASE_BACKEND), off_source_equal=True, frozen_emitter=True))
    save(out / 'build.json', dict(feature='aligned_slice_demand', backends=backends, candidate=candidate,
        comparisons=[generic, baseline, 'verilator'], flags=CFLAGS,
        frozen_inputs=[identity(p) for p in (BASE / 'build.json', GRAPH, HARNESS, CXX, out / 'hypothesis.json',
            out / 'structure.json', out / 'verification.json', out / 'control.json', out / 'generic.json', out / 'candidate.json',
            out / (generic + '-sources.csv'), out / (candidate + '-sources.csv'),
            *emitter.iterdir(), *before.iterdir(), *after.iterdir(), *snapshot.iterdir())],
        binaries={b: identity(out / b / 'emu') for b in backends}))
    print('built aligned-window repair with matched generic-window control')


def build_order(out, tools, jobs):
    if not platform.node().startswith('node030'): raise ValueError('build on node030 for -march=native')
    if out.exists(): raise FileExistsError(out)
    original = check(BASE); out.mkdir(parents=True)
    (out / 'firmware').symlink_to(BASE / 'firmware'); (out / 'verification.json').symlink_to(BASE / 'verification.json')
    before = out / 'native-before'; before.mkdir()
    for src in (BASE / 'native-frozen').iterdir(): shutil.copy2(src, before / src.name)
    after = out / 'native-frozen'; after.mkdir()
    for src in (tools / 'cv32e40p_emit', tools / 'cv32e40p_map', native_library(tools)): shutil.copy2(src, after / src.name)
    env = emit_environment(after)
    run([after / 'cv32e40p_emit', GRAPH, out / 'off-source', 'off'], out / 'logs/off-emit.log', env=env)
    if not same_sources(out / 'off-source', BASE / BASE_BACKEND): raise ValueError('single-terminal source drift')
    baseline, old, candidate = BASE_BACKEND, 'grhsim_shared_unguarded', 'grhsim_shared_order_guard'
    backends = [baseline, old, candidate, 'verilator']
    save(out / 'hypothesis.json', dict(
        change='Keep original region topological order when first-use DFS increases the existing local def-to-last-use sum.',
        expected='Avoid the proven static lifetime increase. This proxy does not predict physical spills or fix activation coarsening.',
        controls='Old/new shared-region membership, graph, and emitter options unchanged. Local decoder and slice transform disabled.',
        policy='One deterministic static comparison per region; no profile-based selection or threshold search.'))
    for name, native in ((old, before), (candidate, after)):
        env = emit_environment(native); env['CV32_EVENT_REGIONS_SHARED'] = '1'
        run([native / 'cv32e40p_emit', GRAPH, out / name, 'off'], out / 'logs' / (name + '-emit.log'), env=env)
        run([native / 'cv32e40p_map', GRAPH, out / (name + '-sources.csv'), '--shared-event-regions'], out / 'logs' / (name + '-map.log'), env=env)
        if identity(out / name / 'normalized.json')['sha256'] != identity(BASE / BASE_BACKEND / 'normalized.json')['sha256']:
            raise ValueError('graph changed')
    def groups(path):
        result = {}
        for row in csv.DictReader(path.open()): result.setdefault(row['group'], []).append(row['op_id'])
        return result
    a, b = groups(out / (old + '-sources.csv')), groups(out / (candidate + '-sources.csv'))
    if {k:sorted(v) for k,v in a.items()} != {k:sorted(v) for k,v in b.items()}: raise ValueError('region membership changed')
    logs = (out / 'logs' / (candidate + '-emit.log')).read_text()
    stats = []
    for line in logs.splitlines():
        if 'local_value_live_steps_before=' not in line: continue
        fields = {k:int(v) for k,v in re.findall(r'(\w+)=(\d+)', line)}
        if fields['local_value_live_steps_after'] > fields['local_value_live_steps_before']: raise ValueError('accepted worse order')
        stats.append(fields)
    if not stats or not any(s['use_order_rejected'] for s in stats): raise ValueError('no guarded order triggered')
    for name in (old, candidate): compile_model(out / name, out, name, jobs)
    for name in (baseline, 'verilator'):
        (out / name).mkdir(); shutil.copy2(original['binaries'][name]['path'], out / name / 'emu')
    snapshot = out / 'source-snapshot'; snapshot.mkdir()
    for src in (ROOT / 'wolvrix/lib/transform/activity_schedule.cpp', ROOT / 'wolvrix/lib/emit/grhsim_cpp.cpp',
                ROOT / 'wolvrix/tests/emit/test_emit_grhsim_event_regions.cpp', Path(__file__).resolve()):
        archived = src if src.parent.name == 'scripts' else snapshot_source(tools, src)
        shutil.copy2(archived, snapshot / src.name)
    save(out / 'structure.json', dict(models={n: shapes(out / n) for n in (old, candidate)},
        baseline=shapes(BASE / BASE_BACKEND), off_source_equal=True, graph_equal=True,
        membership_equal=True, changed_orders=[k for k in a if a[k] != b[k]], order_stats=stats))
    save(out / 'build.json', dict(feature='shared_region_order_guard', backends=backends, candidate=candidate,
        comparisons=[old, baseline, 'verilator'], flags=CFLAGS,
        frozen_inputs=[identity(p) for p in (BASE / 'build.json', GRAPH, HARNESS, CXX, out / 'hypothesis.json',
            out / 'structure.json', out / 'verification.json', out / (old + '-sources.csv'), out / (candidate + '-sources.csv'),
            *before.iterdir(), *after.iterdir(), *snapshot.iterdir())],
        binaries={n: identity(out / n / 'emu') for n in backends}))
    print('built order guard; same region membership, changes only local ordering')


def verify(out):
    manifest = check(out); rows = {}
    for workload in ('smoke', 'coremark'):
        rows[workload] = {b: sample(out, b, workload, 'verify-' + workload, trace=True) for b in manifest['backends']}
        reference = rows[workload]['verilator']
        for backend, row in rows[workload].items():
            if signature(row) != signature(reference) or row['trace']['sha256'] != reference['trace']['sha256'] or row['trace']['bytes'] != row['cycles'] * 36:
                raise ValueError('functional/trace mismatch: ' + backend)
    save(out / 'functional.json', dict(status='pass', build=identity(out / 'build.json'), workloads=rows))
    print('all backends passed smoke/CoreMark and complete bus trace')


def measure(out):
    manifest = check(out); backends = manifest['backends']; candidate = manifest['candidate']
    if (out / 'pairs.json').exists(): raise FileExistsError('measurement already started')
    functional = read(out / 'functional.json')
    if functional['status'] != 'pass' or functional['build'] != identity(out / 'build.json'): raise ValueError('functional gate mismatch')
    warmups = {b: sample(out, b, 'coremark', 'warmup') for b in backends}
    save(out / 'measurement-policy.json', dict(rounds=8, repetitions=1, cpu=96, numa=1, aslr=False,
        warmups=warmups, order='forward/reverse alternating: ' + ', '.join(backends), max_pair_attempts=2,
        bootstrap_seed=20261114, policy='frozen repair; no post-run selections'))
    rows = []
    for index in range(8):
        order = backends if index % 2 == 0 else backends[::-1]
        for attempt in range(2):
            row = dict(pair=index, attempt=attempt, order=order)
            try:
                for b in order:
                    row[b] = sample(out, b, 'coremark', f'pair{index:02d}-attempt{attempt}')
                    if signature(row[b]) != signature(functional['workloads']['coremark'][b]): raise ValueError('signature drift: ' + b)
                break
            except ValueError as error:
                if 'placement rejected:' not in str(error) or attempt: raise
        rows.append(row); save(out / 'pairs.json', rows)
        print(f'round {index+1}/8 ' + ', '.join(f'{candidate}/{b}={row[candidate]["wall_s"]/row[b]["wall_s"]:.5f}' for b in manifest['comparisons']), flush=True)
    summaries = {b: summarize_named(rows, candidate, b) for b in manifest['comparisons']}
    save(out / 'summary.json', summaries)
    with (out / 'pairs.csv').open('w') as stream:
        writer = csv.writer(stream); writer.writerow(['pair', 'order', *[f'{b}_{m}' for b in backends for m in ('wall_s', 'sim_s', 'init_s')]])
        for row in rows: writer.writerow([row['pair'], '>'.join(row['order']), *[row[b][m] for b in backends for m in ('wall_s', 'sim_s', 'init_s')]])
    save(out / 'report.json', dict(build=manifest, summaries=summaries, structure=read(out / 'structure.json'),
        functional=identity(out / 'functional.json'), policy=identity(out / 'measurement-policy.json')))
    print(json.dumps({b:s['wall_s'] for b,s in summaries.items()}, indent=2))


def diagnose(out):
    manifest = check(out); results = {}; models = {}
    if (out / 'diagnostics.json').exists(): raise FileExistsError('diagnostics already recorded')
    for backend in manifest['backends']:
        path = out / (backend + '-stat.csv')
        if path.exists(): raise FileExistsError(path)
        results[backend] = sample(out, backend, 'coremark', 'diagnostic-stat', perf=[
            'stat', '-x,', '-o', path, '-e', 'cycles:u,instructions:u,branches:u,branch-misses:u'])
        functions = []
        binary = Path(manifest['binaries'][backend]['path'])
        for symbol in function_symbols(binary):
            name = symbol['symbol']
            selected = name.startswith('GrhSIM_Cv32Bench::eval') if backend != 'verilator' else (
                name.startswith('VCv32Bench___024root___') and any(x in name for x in ('___nba_', '___act_', '___eval_ico', '___eval_act', '___eval_nba', '___eval_body')))
            if not selected: continue
            asm = disassemble(binary, symbol); functions.append(dict(**symbol, **instruction_shape(instructions(asm))))
            dest = out / 'assembly' / backend / f'function-{symbol["address"]:x}.s'; dest.parent.mkdir(parents=True, exist_ok=True); dest.write_text(asm)
        models[backend] = functions
    save(out / 'diagnostics.json', dict(scope='One independent PMU sample per backend. Static stack operands are not dynamic spills.',
        build=identity(out / 'build.json'), models=models, runs=results))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=('build', 'verify', 'measure', 'diagnose'))
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--tools', type=Path, default=ROOT / 'build/cv32e40p/tools')
    p.add_argument('--jobs', type=int, default=12)
    p.add_argument('--repair', choices=('bool', 'aligned', 'order'), default='bool')
    args = p.parse_args(); out = args.output.resolve()
    if args.stage == 'build': {'bool':build_bool, 'aligned':build_aligned, 'order':build_order}[args.repair](out, args.tools.resolve(), args.jobs)
    elif args.stage == 'verify': verify(out)
    elif args.stage == 'measure': measure(out)
    else: diagnose(out)
