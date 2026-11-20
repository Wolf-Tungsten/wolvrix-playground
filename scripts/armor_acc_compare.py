"""Emit and compile XiangShan models from graphs regenerated with the accumulate-sink pass.

K is the regenerated control graph, D drops the recognized accumulator sinks and
the tasks that print them. Both use the frozen emitter of the previous round.
C and B use the current emitter: C replays the control graph and must reproduce
the sources of K, B rewrites the accumulator sinks into the accumulate bank.
G and BG add same-reader commit groups to C and B respectively.
"""
import argparse
from pathlib import Path
import platform
import resource
import shutil

from armor_followup_compare import ARCHIVE, BASE_XS
from cv32e40p_compare import ROOT, run, save
from grhsim_single_baseline import clean_environment, identity
from xiangshan_cv32_ablation_measure import read, verify
from xiangshan_packed_storage_compare import source_inventory, source_shape

OUT = ROOT / 'build/armor-acc-v1'
FROZEN = ROOT / 'build/armor-followup-v1/frozen'
GRAPHS = {'K': OUT / 'graphs/control.json', 'D': OUT / 'graphs/drop.json',
          'C': OUT / 'graphs/control.json', 'B': OUT / 'graphs/keep.json',
          'G': OUT / 'graphs/control.json', 'BG': OUT / 'graphs/keep.json'}
CURRENT = {'C': 'control', 'B': 'bank', 'G': 'control', 'BG': 'bank'}
GROUPED = {'G', 'BG'}


def emit(variant):
    resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    cfg = read(FROZEN / 'inputs.json')
    for record in cfg['native']:
        verify(record)
    env = clean_environment()
    env.update(LD_LIBRARY_PATH=str(FROZEN / 'native'), LC_ALL='C', NOOP_HOME=str(ARCHIVE / 'testcase/xiangshan'),
        WOLVRIX_GRHSIM_STORAGE_REF_ALIASES='0', WOLVRIX_GRHSIM_PACKED_ARRAY_LOCAL_SCOPE='0',
        WOLVRIX_GRHSIM_CONDITIONAL_MUX_SHARED_ARM='1', WOLVRIX_GRHSIM_BOOL_LANE_PACK='0',
        WOLVRIX_GRHSIM_REDUCTION_MASK_LAYOUT='0',
        WOLVRIX_GRHSIM_COMMIT_SCALAR_SAME_READER_GROUPS=str(int(variant in GROUPED)),
        WOLVRIX_GRHSIM_REDUCTION_COMMON_GUARD='0')
    target = OUT / variant / 'xs/model'
    target.parent.mkdir(parents=True, exist_ok=False)
    if variant in CURRENT:
        native = OUT / 'native-current'
        env.update(LD_LIBRARY_PATH=str(native))
        run([native / 'emit', CURRENT[variant], GRAPHS[variant], target, target.parent / 'accumulate.report.json'],
            target.parent / 'emit.log', env=env)
        reference = OUT / ('B' if variant == 'BG' else 'K') / 'xs/model'
    else:
        run([FROZEN / 'native/emit', GRAPHS[variant], target], target.parent / 'emit.log', env=env)
        reference = BASE_XS / 'model'
    actual, previous = source_inventory(target), source_inventory(reference)
    unchanged = source_shape(actual) == source_shape(previous)
    save(target.parent / 'sources.json', dict(unchanged=unchanged, count=len(actual), files=actual,
        graph=identity(GRAPHS[variant]), frozen_graph=cfg['xs'], reference=str(reference),
        native=[identity(p) for p in sorted((OUT / 'native-current').iterdir())] if variant in CURRENT else cfg['native']))
    print(variant, 'emitted; identical to', reference, ':', unchanged, flush=True)


def compile_model(variant):
    targets = read(ROOT / 'build/armor-followup-v1/native-target.json')['hosts']
    host = platform.node().split('.')[0]
    if host not in targets or targets[host] != targets['node030']:
        raise ValueError('native target differs from the measurement host')
    dst = OUT / variant / 'xs'
    shutil.copytree(BASE_XS / 'chisel-home', dst / 'chisel-home', dirs_exist_ok=True)
    env = clean_environment()
    env.update(NOOP_HOME=str(ARCHIVE / 'testcase/xiangshan'), LC_ALL='C')
    argv = read(BASE_XS / 'logs/compile.command.json')['argv']
    run([v.replace(str(BASE_XS), str(dst)) for v in argv], dst / 'compile.log', env=env)
    settings = read(BASE_XS / 'configuration.json')
    settings.update(accumulate_sink={'K': 'control', 'D': 'drop', 'C': 'control-current',
                                     'B': 'bank', 'G': 'control-current', 'BG': 'bank'}.get(variant, variant))
    if variant in GROUPED:
        settings.update(commit_scalar_same_reader_groups=True)
    save(dst / 'configuration.json', settings)
    save(dst / 'model-sources.json', read(dst / 'sources.json')['files'])
    save(dst / 'binary.json', identity(dst / 'emu/grhsim-compile/emu'))
    print(variant, 'compiled', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=('emit', 'build'))
    p.add_argument('variant', choices=tuple(GRAPHS))
    args = p.parse_args()
    (emit if args.stage == 'emit' else compile_model)(args.variant)
