"""Replay and compile the independent same-reader commit and common-factor reduction candidates."""
import argparse
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor

from armor_lane_replay import emit_frozen_model, prepare
from armor_mask_layout_compare import ARCHIVE, DEFAULT as OLD
from cv32e40p_compare import CFLAGS, CXX, ROOT, run, save
from grhsim_elf_section_identity import sections
from grhsim_single_baseline import clean_environment, identity
from xiangshan_cv32_ablation_measure import read, verify

OUT = ROOT / 'build/armor-followup-v1'
BASE_XS = ARCHIVE / 'build/xs/indexed-snapshot-20261117-v3/candidate'
BASE_CV = ARCHIVE / 'build/cv32e40p/indexed-snapshot-v3/grhsim_indexed_snapshot'


def freeze():
    frozen = OUT / 'frozen'
    prepare(ARCHIVE, frozen, ROOT / 'build/armor-lane-v1/tools')
    snapshot = frozen / 'grhsim_cpp.cpp'
    shutil.copy2(ROOT / 'wolvrix/lib/emit/grhsim_cpp.cpp', snapshot)
    inputs = read(frozen / 'inputs.json')
    verify(inputs['emit_source'])
    save(OUT / 'policy.json', dict(
        baseline=dict(xs=inputs['xs_binary'], cv=inputs['cv_binary']),
        commit='only commit_scalar_same_reader_groups=1',
        factor='only the common-input reduction guard; use existing stored Boolean snapshots; no profile-based sites',
        controls='original stable mask order and lane pack off, shared arm and compact snapshots on, independent A/C and A/F',
        runs='frozen eight alternating AB/BA pairs for both designs on node030 CPU96 NUMA1, ASLR off, shared lock; released timing separate from PMU and trace'))
    probe = [str(CXX),'-std=c++20','-O3','-march=native','-###','-S','-x','c++','/dev/null','-o','/dev/null']
    hosts = {}
    for name in ('node029','node030'):
        cmd = probe if platform.node().split('.')[0] == name else ['ssh',name,shlex.join(probe)]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        hosts[name] = re.findall(r'"-target-(?:cpu|feature)"\s+"([^"]+)"',result.stderr)
    if not hosts['node030'] or hosts['node029'] != hosts['node030']:
        raise ValueError('Clang native targets differ')
    save(OUT / 'native-target.json', dict(compiler=str(CXX),hosts=hosts))


def emit(variant, design):
    frozen = OLD if variant == 'C' else OUT / 'frozen'
    switches = {
        'WOLVRIX_GRHSIM_BOOL_LANE_PACK': '0',
        'WOLVRIX_GRHSIM_REDUCTION_MASK_LAYOUT': '0',
        'WOLVRIX_GRHSIM_COMMIT_SCALAR_SAME_READER_GROUPS': str(int(variant == 'C')),
        'WOLVRIX_GRHSIM_REDUCTION_COMMON_GUARD': str(int(variant == 'F')),
    }
    target = OUT / variant / design / 'model'
    same = emit_frozen_model(frozen, design, target, switches)
    if variant == 'A' and not same:
        raise ValueError(f'{design} disabled options changed frozen output')
    return same


def compile_model(variant, design):
    host = platform.node().split('.')[0]
    targets = read(OUT / 'native-target.json')['hosts']
    if host not in targets or targets[host] != targets['node030']:
        raise ValueError('native target differs from the measurement host')
    dst = OUT / variant / design
    model = dst / 'model'
    if design == 'xs':
        shutil.copytree(BASE_XS / 'chisel-home', dst / 'chisel-home', dirs_exist_ok=True)
        env = clean_environment()
        env.update(NOOP_HOME=str(ARCHIVE / 'testcase/xiangshan'), LC_ALL='C')
        argv = read(BASE_XS / 'logs/compile.command.json')['argv']
        run([v.replace(str(BASE_XS), str(dst)) for v in argv], dst / 'compile.log', env=env)
        binary = dst / 'emu/grhsim-compile/emu'
        settings = read(BASE_XS / 'configuration.json')
        settings.update(commit_scalar_same_reader_groups=variant == 'C', reduction_common_guard=variant == 'F')
        save(dst / 'configuration.json', settings)
        save(dst / 'model-sources.json', read(dst / 'sources.json')['files'])
    else:
        run(['make', '-C', model, '-j8', 'CXX=' + str(CXX), 'CXXFLAGS=' + ' '.join(CFLAGS)], dst / 'compile.log')
        binary = model / 'emu'
        run([CXX, *CFLAGS, '-DCV32_GRHSIM', '-I', model, ARCHIVE / 'build/cv32e40p/run2/inputs/fixture/harness.cpp',
             model / 'libgrhsim_Cv32Bench.a', '-o', binary], dst / 'link.log')
        before, after = sections(BASE_CV / 'emu'), sections(binary)
        if read(dst / 'sources.json')['unchanged'] and before != after:
            raise ValueError('identical CV32 sources produced different code/data')
        save(dst / 'sections.json', dict(baseline=before, candidate=after))
    save(dst / 'binary.json', identity(binary))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=('freeze', 'emit', 'build'))
    p.add_argument('variant', nargs='?', choices=('A', 'C', 'F'))
    p.add_argument('design', nargs='?', choices=('xs', 'cv'))
    args = p.parse_args()
    if args.stage == 'freeze':
        freeze()
    elif args.stage == 'emit' and not args.variant and not args.design:
        with ThreadPoolExecutor(4) as pool:
            tasks = [pool.submit(emit, variant, design) for variant in ('A','F') for design in ('xs','cv')]
            for task in tasks: task.result()
    elif args.variant and args.design:
        (emit if args.stage == 'emit' else compile_model)(args.variant, args.design)
    else:
        p.error('provide variant and design')
