#!/usr/bin/env python3
"""Frozen packed-state-layout and array-scope comparisons on node030 CPU96."""
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
FEATURES = {
 'layout': ('state_layout_packed_access', 'WOLVRIX_GRHSIM_STATE_LAYOUT_PACKED_ACCESS'),
 'scope': ('packed_array_local_scope', 'WOLVRIX_GRHSIM_PACKED_ARRAY_LOCAL_SCOPE'),
}

def read(path):
    return json.loads(Path(path).read_text())


def source_inventory(folder):
    return [identity(p) for p in sorted(Path(folder).iterdir())
            if p.suffix in ('.cpp', '.hpp') or p.name == 'Makefile']


def source_shape(records):
    return {Path(record['path']).name: (record['bytes'], record['sha256'])
            for record in records}


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


def prepare(out, tools, feature):
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
    (out / 'full').symlink_to(FULL, target_is_directory=True)
    (out / 'no_shared').symlink_to(NO_SHARED, target_is_directory=True)
    config = read(FULL / 'configuration.json')
    config.update(variant='packed_' + feature, packed_feature=feature,
        source_driver=identity(snap / Path(__file__).name),
        wolvrix_source_patch=identity(snap / 'wolvrix.patch'),
        native_library=identity(native / 'libwolvrix-lib.so'),
        note='Same frozen full pipeline; one predeclared emitter option changes.')
    config[FEATURES[feature][0]] = True
    save(candidate / 'configuration.json', config)
    save(out / 'policy.json', dict(cpu=96, numa=1, aslr=False, threads=1,
        cycles=100000, smoke_cycles=10000, verification_seeds=[0, 1], pairs=3,
        order='full/candidate/no_shared then reverse, three rounds', warmups_per_variant=1, runtime_difftest='on',
        baseline=str(FULL), feature=feature, variants=['full','candidate','no_shared'],
        candidate='same full pipeline with only ' + FEATURES[feature][0],
        acceptance='Layout: disjoint same-signature/demand/type state bundles in graph order, packed lane order within bundle. Scope: private single scalar select and stable early index; original construction and notification points. No tuned cost thresholds.',
        generation='Graph structure only. No timing, profiles, model names, weights or tuned thresholds.',
        source_gate='Feature off must reproduce full; layout preserves all generated .cpp files; scope preserves generated headers and scheduler guards.',
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
    print('prepared frozen packed-storage experiment', flush=True)


def check_inputs(out):
    for record in read(out / 'inputs.json'):
        verify_identity(record)


def native_command(out, enabled):
    native = out / 'candidate/native'
    command = read(FULL / 'logs/native.command.json')['argv']
    command = [arg.replace(str(FULL / 'native'), str(native))
               .replace(str(FULL.parent / 'snapshot'), str(out / 'snapshot'))
               for arg in command]
    command[-1] = str(native / ('emit-guard' if enabled else 'emit-off'))
    return command


def compile_command(out):
    return [arg.replace(str(FULL), str(out / 'candidate'))
            for arg in read(FULL / 'logs/compile.command.json')['argv']]


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
    from concurrent.futures import ThreadPoolExecutor
    def emit_one(enabled, label, folder):
        command = native_command(out, enabled)
        local_env = env.copy()
        feature = read(out / 'policy.json')['feature']
        local_env[FEATURES[feature][1]] = str(int(enabled))
        run(command, dest / 'logs' / (label + '-native.log'), env=local_env)
        run([command[-1], HISTORICAL / 'pre_reg_to_mem.json', folder],
            dest / 'logs' / (label + '-emit.log'), env=local_env)
        return source_inventory(folder)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {label: pool.submit(emit_one, enabled, label, folder)
                   for enabled,label,folder in ((False,'off',out/'off-source'),(True,'guard',dest/'model'))}
        emitted = {label: future.result() for label,future in futures.items()}
    if source_shape(emitted['off']) != source_shape(read(FULL / 'model-sources.json')):
        raise ValueError('guard-off generated source differs from frozen optimized full')
    feature = read(out / 'policy.json')['feature']
    old, new = source_shape(emitted['off']), source_shape(emitted['guard'])
    changed = sorted(name for name in old if old[name] != new.get(name))
    if feature == 'layout' and any(name.endswith('.cpp') for name in changed):
        raise ValueError('state layout changed generated computation source: ' + str(changed))
    if feature == 'scope' and any(name.endswith('.hpp') for name in changed):
        raise ValueError('array scope changed generated header/storage')
    if feature == 'layout':
        lines = [line for line in (dest/'logs/guard-emit.log').read_text().splitlines()
                 if '[GRHSIM_PACKED_STATE_LAYOUT]' in line]
        if not lines: raise ValueError('missing layout diagnostics')
        decision = dict(re.findall(r'(\w+)=(\d+)', lines[-1]))
    else:
        decision = dict(scope_sites=sum(p.read_text().count('// Scoped packed array:')
            for p in (dest/'model').glob('*_sched_*.cpp')))
    save(dest / 'model-sources.json', emitted['guard'])
    save(out / 'structure.json', dict(feature=feature, decision=decision, changed_files=changed,
        feature_off_equal_full=True, off_sources=emitted['off'], candidate_sources=emitted['guard']))
    command = compile_command(out)
    run(command, dest / 'logs/compile.log', env=env)
    save(dest / 'binary.json', identity(dest / 'emu/grhsim-compile/emu'))
    records = [identity(out / 'structure.json'), identity(dest / 'model-sources.json'),
               identity(dest / 'binary.json'), read(dest / 'binary.json')]
    records += emitted['off'] + emitted['guard']
    records += [identity(p) for p in sorted((dest / 'logs').iterdir()) if p.is_file()]
    records += [identity(native / name) for name in ('emit-off', 'emit-guard')]
    save(out / 'build.json', dict(inputs=identity(out / 'inputs.json'), files=records,
        baseline=read(FULL / 'binary.json'), candidate=read(dest / 'binary.json')))
    check(out)
    print(json.dumps(dict(status='built', refinement=decision)), flush=True)


def check(out):
    check_inputs(out)
    manifest = read(out / 'build.json')
    verify_identity(manifest['inputs'])
    for record in manifest['files']:
        verify_identity(record)
    check_model(FULL)
    check_model(out / 'candidate')


def measure(out):
    import xiangshan_cv32_ablation_measure as protocol
    from grhsim_single_compare import summarize
    check(out)
    # Fixed before generation: three variants in three alternating rounds.
    # Import the ordinary repository module, never a sibling snapshot module.
    protocol.VARIANTS = ('full', 'candidate', 'no_shared')
    protocol.ROUNDS = 3
    result = protocol.measure(out, out/'measurement',
        XS/'ready-to-run/coremark-2-iteration.bin', XS/'ready-to-run/riscv64-nemu-interpreter-so')
    check(out)
    comparisons = result['comparisons']
    comparisons['candidate_vs_no_shared'] = {}
    for metric in ('host_ms', 'external_wall_s'):
        scale = 1000 if metric == 'external_wall_s' else 1
        rows = [{side:dict(host_ms=row[name][metric]*scale)
                 for side,name in (('A','no_shared'),('B','candidate'))} for row in result['rounds']]
        comparisons['candidate_vs_no_shared'][metric] = summarize(rows)
    save(out/'report.json',dict(build=identity(out/'build.json'),policy=identity(out/'policy.json'),
        structure=identity(out/'structure.json'),summary=identity(out/'measurement/summary.json'),
        comparisons=comparisons))
    print(json.dumps(comparisons,indent=2),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'build', 'check', 'measure'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--feature', choices=FEATURES)
    parser.add_argument('--tools', type=Path, default=ROOT / 'build/cv32e40p/tools')
    args = parser.parse_args()
    out = args.output.resolve()
    if args.stage == 'prepare':
        prepare(out, args.tools.resolve(), args.feature or 'layout')
    else:
        {'build': build, 'check': check, 'measure': measure}[args.stage](out)
