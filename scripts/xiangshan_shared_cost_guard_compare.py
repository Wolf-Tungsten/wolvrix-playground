#!/usr/bin/env python3
"""Frozen static shared-region guard comparison, with serial CPU96 measurements."""
import argparse
import json
from pathlib import Path
import platform
import re
import resource
import shutil
import subprocess
import sys

from cv32e40p_compare import ROOT, CXX, run
from cv32e40p_repair_compare import native_library
from grhsim_single_baseline import clean_environment, identity, save
from xiangshan_cv32_compare import HISTORICAL, XS, verify_identity
from xiangshan_cv32_ablation_measure import measurement_lock

FULL = ROOT / 'build/xs/cv32-transfer-20261116-v3/after'
NO_SHARED = ROOT / 'build/xs/cv32-ablation-20261116-v2/no_shared'
SOURCE = ROOT / 'scripts/xiangshan_cv32_emit.cpp'
DIMENSIONS = ('compute_groups', 'boundary_values', 'boundary_activation_edges',
              'state_read_activation_edges')


def read(path):
    return json.loads(Path(path).read_text())


def source_inventory(folder):
    return [identity(p) for p in sorted(Path(folder).iterdir())
            if p.suffix in ('.cpp', '.hpp') or p.name == 'Makefile']


def source_shape(records):
    return {Path(record['path']).name: (record['bytes'], record['sha256'])
            for record in records}


def guard_decision(log):
    lines = [line for line in log.splitlines()
             if 'shared event-regions cost guard: accepted=' in line]
    if len(lines) != 1:
        raise ValueError('expected exactly one shared-region cost guard decision')
    fields = dict(re.findall(r'(\w+)=(\w+)', lines[0]))
    if fields.get('accepted') not in ('true', 'false'):
        raise ValueError('invalid guard decision')
    before = {name: int(fields[name + '_before']) for name in DIMENSIONS}
    after = {name: int(fields[name + '_after']) for name in DIMENSIONS}
    accepted = (all(after[name] <= before[name] for name in DIMENSIONS)
                and any(after[name] < before[name] for name in DIMENSIONS))
    if accepted != (fields['accepted'] == 'true'):
        raise ValueError('guard log violates frozen Pareto rule')
    return dict(accepted=accepted, before=before, after=after, log=lines[0])


def check_model(folder):
    verify_identity(read(folder / 'binary.json'))
    records = read(folder / 'model-sources.json')
    for record in records:
        verify_identity(record)
    if source_shape(records) != source_shape(source_inventory(folder / 'model')):
        raise ValueError('model source manifest does not cover source set: ' + str(folder))
    return records


def check_harness_source():
    repository = XS / 'difftest'
    expected = HISTORICAL / 'source_identity/difftest'
    head = subprocess.check_output(['git', '-C', repository, 'rev-parse', 'HEAD'])
    patch = subprocess.check_output(['git', '-C', repository, 'diff', '--binary', 'HEAD'])
    untracked = subprocess.check_output(
        ['git', '-C', repository, 'ls-files', '--others', '--exclude-standard'])
    if head != (expected / 'head.txt').read_bytes() or patch != (expected / 'diff.patch').read_bytes() or untracked:
        raise ValueError('DiffTest source differs from the frozen harness')


def prepare(out, tools, reuse_equivalent_binary=False):
    check_harness_source()
    full_sources = check_model(FULL)
    no_shared_sources = check_model(NO_SHARED)
    out.mkdir(parents=True, exist_ok=False)
    snap = out / 'snapshot'
    snap.mkdir()
    for path in (SOURCE, Path(__file__), ROOT / 'scripts/grhsim_single_compare.py',
                 ROOT / 'scripts/grhsim_single_baseline.py', ROOT / 'scripts/grhsim_numa.py',
                 ROOT / 'scripts/grhsim_difftrace.py', ROOT / 'scripts/xiangshan_cv32_ablation_measure.py',
                 ROOT / 'scripts/simulation_model_modes.py'):
        shutil.copy2(path, snap / path.name)
    # Headers and the shared library must be from the same new build: the options
    # struct changed ABI. Archive the worktree source independently of HEAD.
    candidate = out / 'candidate'
    candidate.mkdir()
    native = candidate / 'native'
    native.mkdir()
    shutil.copytree(ROOT / 'wolvrix/include', native / 'include')
    shutil.copy2(native_library(tools), native / 'libwolvrix-lib.so')
    shutil.copytree(ROOT / 'wolvrix/lib', snap / 'lib')
    (snap / 'wolvrix.patch').write_bytes(subprocess.check_output(
        ['git', '-C', ROOT / 'wolvrix', 'diff', '--binary', 'HEAD']))
    (snap / 'wolvrix-head.txt').write_bytes(subprocess.check_output(
        ['git', '-C', ROOT / 'wolvrix', 'rev-parse', 'HEAD']))
    shutil.copytree(FULL / 'chisel-home', candidate / 'chisel-home')
    (out / 'baseline').symlink_to(FULL, target_is_directory=True)
    config = read(FULL / 'configuration.json')
    config.update(variant='shared_cost_guard', event_regions_shared_cost_guard=True,
        source_driver=identity(snap / Path(__file__).name),
        wolvrix_source_patch=identity(snap / 'wolvrix.patch'),
        native_library=identity(native / 'libwolvrix-lib.so'),
        note='Same frozen graph and optimized pipeline; only static shared-region admission changes.')
    save(candidate / 'configuration.json', config)
    save(out / 'policy.json', dict(cpu=96, numa=1, aslr=False, threads=1,
        cycles=100000, smoke_cycles=10000, verification_seeds=[0, 1], pairs=8,
        order='AB/BA alternating', warmups_per_variant=1, runtime_difftest='on',
        baseline=str(FULL), candidate='same optimized pipeline with static shared-region cost guard',
        dimensions=list(DIMENSIONS),
        acceptance='Every candidate dimension <= pre-shared baseline and at least one strictly smaller.',
        generation='Graph structure only. No timing, profiles, model names, weights or tuned thresholds.',
        source_gate='Guard off must exactly reproduce full. Guard on must exactly reproduce full if accepted, or no_shared if rejected.',
        reuse_equivalent_binary=reuse_equivalent_binary,
        reuse_rule='If explicitly enabled before build, reuse the existing binary only after exact generated source and compile/configuration equality; no runtime-result input.',
        measurement='One serial invocation under the shared CPU96 file lock, full DiffTest, no runtime feedback or sample deletion.',
        idle_admission='Record CPU96/288 use; same skip-idle-check policy as prior XiangShan experiments. Placement and NUMA gates remain mandatory.'))
    inputs = [identity(HISTORICAL / 'pre_reg_to_mem.json'), identity(CXX), identity(Path(__file__)),
              identity(HISTORICAL / 'source_identity/difftest/head.txt'),
              identity(HISTORICAL / 'source_identity/difftest/diff.patch'),
              identity(XS / 'ready-to-run/coremark-2-iteration.bin'),
              identity(XS / 'ready-to-run/riscv64-nemu-interpreter-so'),
              identity(out / 'policy.json'), identity(candidate / 'configuration.json')]
    for model in (FULL, NO_SHARED):
        inputs.extend(identity(model / name) for name in
                      ('binary.json', 'model-sources.json', 'configuration.json',
                       'logs/compile.command.json', 'logs/native.command.json'))
        inputs.append(read(model / 'binary.json'))
    inputs += full_sources + no_shared_sources
    for directory in (snap, native, candidate / 'chisel-home'):
        inputs.extend(identity(p) for p in sorted(directory.rglob('*')) if p.is_file())
    # Measurement executes the common current runner; archive and freeze it.
    inputs.extend(identity(ROOT / 'scripts' / name) for name in
                  ('grhsim_single_compare.py', 'grhsim_single_baseline.py', 'grhsim_numa.py',
                   'grhsim_difftrace.py', 'xiangshan_cv32_ablation_measure.py', 'simulation_model_modes.py'))
    save(out / 'inputs.json', list({record['path']: record for record in inputs}.values()))
    print('prepared frozen guard experiment', flush=True)


def check_inputs(out):
    for record in read(out / 'inputs.json'):
        verify_identity(record)


def native_command(out, enabled):
    native = out / 'candidate/native'
    command = read(FULL / 'logs/native.command.json')['argv']
    command = [arg.replace(str(FULL / 'native'), str(native))
               .replace(str(FULL.parent / 'snapshot'), str(out / 'snapshot'))
               for arg in command]
    command.insert(1, '-DXS_SHARED_EVENT_REGIONS_COST_GUARD=' + str(int(enabled)))
    command[-1] = str(native / ('emit-guard' if enabled else 'emit-off'))
    return command


def compile_command(out):
    return [arg.replace(str(FULL), str(out / 'candidate'))
            for arg in read(FULL / 'logs/compile.command.json')['argv']]


def verify_reuse_settings(reference, candidate, command):
    expected = [arg.replace(str(reference), str(candidate))
                for arg in read(reference / 'logs/compile.command.json')['argv']]
    if command != expected:
        raise ValueError('equivalent binary reuse requires identical normalized build command')
    before, after = read(reference / 'configuration.json'), read(candidate / 'configuration.json')
    keys = ('config', 'guest_cores', 'sim_primitives', 'sim_models', 'behavior_state_lowering',
            'behavior_compute_lowering', 'model_flags', 'harness_flags', 'storage_ref_aliases',
            'rtl_difftest', 'model_difftest', 'compile_difftest', 'runtime_difftest', 'compiler')
    if any(before.get(key) != after.get(key) for key in keys):
        raise ValueError('equivalent binary reuse requires identical simulation build settings')
    def generated(folder):
        path = folder / 'chisel-home/build/generated-src'
        return {str(p.relative_to(path)): (p.stat().st_size, identity(p)['sha256'])
                for p in path.rglob('*') if p.is_file()}
    if generated(reference) != generated(candidate):
        raise ValueError('equivalent binary reuse requires identical generated harness inputs')


def build(out):
    if not platform.node().startswith('node030'):
        raise ValueError('build on node030 for march=native')
    resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    check_inputs(out)
    check_harness_source()
    dest, native = out / 'candidate', out / 'candidate/native'
    if (dest / 'binary.json').exists():
        raise FileExistsError('candidate already built')
    env = clean_environment()
    env.update(NOOP_HOME=str(XS), LC_ALL='C', WOLVRIX_GRHSIM_STORAGE_REF_ALIASES='0')
    save(dest / 'environment.json', {key: value for key, value in env.items()
         if key in ('PATH', 'LC_ALL', 'NOOP_HOME') or key.startswith('WOLVRIX_')})
    emitted = {}
    for enabled, label, folder in ((False, 'off', out / 'off-source'),
                                    (True, 'guard', dest / 'model')):
        command = native_command(out, enabled)
        run(command, dest / 'logs' / (label + '-native.log'), env=env)
        run([command[-1], HISTORICAL / 'pre_reg_to_mem.json', folder],
            dest / 'logs' / (label + '-emit.log'), env=env)
        emitted[label] = source_inventory(folder)
    if source_shape(emitted['off']) != source_shape(read(FULL / 'model-sources.json')):
        raise ValueError('guard-off generated source differs from frozen optimized full')
    decision = guard_decision((dest / 'logs/guard-emit.log').read_text())
    reference = FULL if decision['accepted'] else NO_SHARED
    if source_shape(emitted['guard']) != source_shape(read(reference / 'model-sources.json')):
        raise ValueError('guarded output differs from its exact static reference')
    save(dest / 'model-sources.json', emitted['guard'])
    save(out / 'structure.json', dict(guard=decision, guard_off_equal_full=True,
        exact_source_reference=str(reference), exact_source_equality=True,
        off_sources=emitted['off'], candidate_sources=emitted['guard']))
    command = compile_command(out)
    if read(out / 'policy.json')['reuse_equivalent_binary']:
        verify_reuse_settings(reference, dest, command)
        binary = dest / 'emu/grhsim-compile/emu'
        binary.parent.mkdir(parents=True)
        shutil.copy2(reference / 'emu/grhsim-compile/emu', binary)
        save(dest / 'binary-reuse.json', dict(reference=read(reference / 'binary.json'),
            generated_sources_equal=True, build_command_equal=True, configuration_equal=True,
            structure=identity(out / 'structure.json'), planned_compile_command=command))
    else:
        run(command, dest / 'logs/compile.log', env=env)
    save(dest / 'binary.json', identity(dest / 'emu/grhsim-compile/emu'))
    records = [identity(out / 'structure.json'), identity(dest / 'model-sources.json'),
               identity(dest / 'binary.json'), read(dest / 'binary.json')]
    records += emitted['off'] + emitted['guard']
    records += [identity(p) for p in sorted((dest / 'logs').iterdir()) if p.is_file()]
    records += [identity(native / name) for name in ('emit-off', 'emit-guard')]
    if (dest / 'binary-reuse.json').exists():
        records.append(identity(dest / 'binary-reuse.json'))
    save(out / 'build.json', dict(inputs=identity(out / 'inputs.json'), files=records,
        baseline=read(FULL / 'binary.json'), candidate=read(dest / 'binary.json')))
    check(out)
    print(json.dumps(dict(status='built', guard=decision,
        binary_reused=read(out / 'policy.json')['reuse_equivalent_binary'])), flush=True)


def check(out):
    check_inputs(out)
    manifest = read(out / 'build.json')
    verify_identity(manifest['inputs'])
    for record in manifest['files']:
        verify_identity(record)
    check_model(FULL)
    check_model(out / 'candidate')


def measure(out):
    if not platform.node().startswith('node030'):
        raise ValueError('measure on node030 CPU96')
    with measurement_lock():
        check(out)
        command = [sys.executable, ROOT / 'scripts/grhsim_single_compare.py',
            '--baseline', out / 'baseline', '--candidate', out / 'candidate',
            '--output', out / 'paired', '--cycles', '100000', '--pairs', '8',
            '--runtime-difftest', 'on', '--image', XS / 'ready-to-run/coremark-2-iteration.bin',
            '--nemu', XS / 'ready-to-run/riscv64-nemu-interpreter-so', '--skip-idle-check']
        run(command, out / 'measurement.log')
        check(out)
        summary = read(out / 'paired/summary.json')
        save(out / 'report.json', dict(build=identity(out / 'build.json'),
            policy=identity(out / 'policy.json'), structure=read(out / 'structure.json'),
            paired_summary=identity(out / 'paired/summary.json'),
            host_time={key: value for key, value in summary.items()
                       if key.startswith(('delta_', 'candidate_', 'baseline_'))},
            external_wall=summary['external_wall'], trace_checks=summary['trace_checks']))
        print(json.dumps(summary['external_wall'], indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'build', 'check', 'measure'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tools', type=Path, default=ROOT / 'build/cv32e40p/tools')
    parser.add_argument('--reuse-equivalent-binary', action='store_true',
        help='prepare only: predeclare reuse of an exactly equivalent frozen generated model')
    args = parser.parse_args()
    out = args.output.resolve()
    if args.stage == 'prepare':
        prepare(out, args.tools.resolve(), args.reuse_equivalent_binary)
    else:
        if args.reuse_equivalent_binary:
            parser.error('--reuse-equivalent-binary must be frozen during prepare')
        {'build': build, 'check': check, 'measure': measure}[args.stage](out)
