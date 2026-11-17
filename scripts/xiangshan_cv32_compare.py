#!/usr/bin/env python3
"""Frozen pre/post-CV32 native XiangShan comparison, with no runtime feedback."""
import argparse
import io
import json
import os
from pathlib import Path
import platform
import re
import resource
import shutil
import subprocess
import sys
import tarfile

from cv32e40p_compare import ROOT, CXX, run
from grhsim_single_baseline import clean_environment, identity, save

HISTORICAL = ROOT.parent / 'wolvrix-playground-new-xiangshan/build/xs/parent-default-single-20261114-v1'
XS = ROOT / 'testcase/xiangshan'
REVISIONS = {'before': '74d80cf', 'after': '8523dc1'}
SOURCE = ROOT / 'scripts/xiangshan_cv32_emit.cpp'


def read(path):
    return json.loads(Path(path).read_text())


def verify_identity(record):
    if identity(record['path']) != record:
        raise ValueError('frozen input changed: ' + record['path'])


def prepare(out):
    out.mkdir(parents=True, exist_ok=False)
    # The historical library was built from the immediate parent plus the exact
    # default-on patch subsequently committed as 74d80cf. Check this explicitly.
    prior = HISTORICAL / 'source_identity/wolvrix'
    head = (prior / 'head.txt').read_text().strip()
    patch = subprocess.check_output(['git', '-C', ROOT/'wolvrix', 'diff', head, REVISIONS['before'], '--', 'lib', 'include'])
    if patch != (prior/'diff.patch').read_bytes():
        raise ValueError('historical library is not the pre-CV32 production source')
    if subprocess.check_output(['git', '-C', ROOT/'wolvrix', 'diff', '8523dc1', '--', 'lib', 'include']).strip():
        raise ValueError('current production source differs from checkpoint')
    if subprocess.check_output(['git', '-C', XS/'difftest', 'rev-parse', 'HEAD'], text=True).strip() != (HISTORICAL/'source_identity/difftest/head.txt').read_text().strip():
        raise ValueError('DiffTest revision differs from frozen baseline')
    snapshots = out/'snapshot'; snapshots.mkdir()
    for p in (SOURCE, Path(__file__), ROOT/'scripts/grhsim_single_compare.py',
              ROOT/'scripts/grhsim_single_baseline.py', ROOT/'scripts/grhsim_numa.py', ROOT/'scripts/grhsim_difftrace.py'):
        shutil.copy2(p, snapshots/p.name)
    for p in ('head.txt', 'diff.patch', 'status.txt'):
        shutil.copy2(prior/p, snapshots/('old-library-'+p))
    frozen = [identity(HISTORICAL/'pre_reg_to_mem.json'), identity(CXX),
              identity(XS/'ready-to-run/coremark-2-iteration.bin'),
              identity(XS/'ready-to-run/riscv64-nemu-interpreter-so')]
    frozen += [identity(p) for p in sorted(snapshots.iterdir())]
    for variant, revision in REVISIONS.items():
        dest=out/variant; dest.mkdir(); native=dest/'native'; native.mkdir()
        archive=subprocess.check_output(['git','-C',ROOT/'wolvrix','archive',revision,'include'])
        with tarfile.open(fileobj=io.BytesIO(archive)) as package:
            package.extractall(native, filter='data')
        library=(HISTORICAL/'tools/libwolvrix-lib.so' if variant=='before'
                 else ROOT/'build/cv32e40p/tools/grhsim32/wolvrix/libwolvrix-lib.so')
        shutil.copy2(library,native/'libwolvrix-lib.so')
        frozen.append(identity(native/'libwolvrix-lib.so'))
        generated=dest/'chisel-home/build/generated-src'; generated.parent.mkdir(parents=True)
        shutil.copytree(HISTORICAL/'chisel-home/build/generated-src',generated)
        frozen += [identity(p) for p in sorted(generated.rglob('*')) if p.is_file()]
        config=read(HISTORICAL/'configuration.json')
        for field in ('compile_cpus','source_driver','reuse_rtl_from'): config.pop(field,None)
        config.update(wolvrix_revision=subprocess.check_output(['git','-C',ROOT/'wolvrix','rev-parse',revision],text=True).strip(),
            variant=variant,source_driver=identity(Path(__file__)),jobs=32,
            shared_input=identity(HISTORICAL/'pre_reg_to_mem.json'),
            pipeline=['simplify(two-state, keep-declared=false)','reg-to-mem(ordered-writes=true)',
                      'activity-schedule(compute limits=108)','emit-grhsim-cpp'],
            split_oversize_compute_nodes=variant=='before',
            event_regions=variant=='after',event_regions_shared=variant=='after',
            storage_ref_aliases=False,
            retained_cv32_features=variant=='after',runtime_difftest='on',
            model_flags='-std=c++20 -O3 -march=native',harness_flags='-O3',
            note='Same frozen pre-reg-to-mem graph; both sides replay simplify. No measured input to generation.')
        save(dest/'configuration.json',config)
        frozen.append(identity(dest/'configuration.json'))
    save(out/'policy.json',dict(cpu=96,numa=1,aslr=False,threads=1,cycles=100000,smoke_cycles=10000,
        verification_seeds=[0,1],pairs=8,order='AB/BA alternating',warmups_per_variant=1,
        baseline='74d80cf before CV32 optimization series',candidate='8523dc1 with retained TNO0032 configuration',
        graph='same frozen after-merge DefaultConfig SimTop, hardware simulation models, full DiffTest',
        explicit_on=['event_regions','event_regions_shared','conditional_mux_cones','shared_equality_families',
                     'conditional_mux_input_cache','covered_state_view_notifications','covered_state_view_inline',
                     'covered_state_view_composition','covered_state_view_composition_inline'],
        defaults_on=['scalar_concat_reduction (both)','indexed_concat_slice (after)',
                     'packed_scalar_slices (after)','shared_equality_decode (after)'],
        experimental_options='Other default-off switches remain off, including wide demand, local predicate sets, notification factoring, and compute entry guard.',
        scheduler_prerequisite='Disable oversize compute-node splitting in the candidate: event regions require whole compute nodes. Original XiangShan baseline retains splitting.',
        storage_ref_aliases=False,
        idle_admission='Record CPU96/288 use; no external-idle admission, as in the existing XiangShan protocol. Placement and locality gates mandatory.',
        stop_rule='Reject functional failures; no performance-guided revisions, combinations, extra rounds, or sample deletion.'))
    frozen.append(identity(out/'policy.json'))
    save(out/'inputs.json',frozen)


def build(out, variant):
    if not platform.node().startswith('node030'): raise ValueError('build on node030 for march=native')
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    for record in read(out/'inputs.json'): verify_identity(record)
    dest=out/variant; native=dest/'native'
    env=clean_environment();env.update(NOOP_HOME=str(XS),LC_ALL='C',WOLVRIX_GRHSIM_STORAGE_REF_ALIASES='0')
    save(dest/'environment.json',{k:v for k,v in env.items() if k in ('PATH','LC_ALL','NOOP_HOME') or k.startswith('WOLVRIX_')})
    run(['/usr/bin/c++','-std=c++20','-O2',f'-DXS_CV32_OPTIMIZED={int(variant=="after")}',
         '-I',native/'include','-I',ROOT/'wolvrix/external/slang/include',
         '-I',ROOT/'wolvrix/external/slang/external',
         '-I',ROOT/'build/cv32e40p/tools/grhsim32/wolvrix/external/slang/source',
         '-I',ROOT/'build/cv32e40p/tools/_deps/fmt-src/include',
         '-DSLANG_STATIC_DEFINE','-DSLANG_USE_MIMALLOC','-DSLANG_USE_THREADS',
         out/'snapshot/xiangshan_cv32_emit.cpp','-L',native,
         '-lwolvrix-lib','-Wl,-rpath,'+str(native),'-o',native/'emit'],dest/'logs/native.log',env=env)
    run([native/'emit',HISTORICAL/'pre_reg_to_mem.json',dest/'model'],dest/'logs/emit.log',env=env)
    generated=dest/'chisel-home/build/generated-src'
    command=['make','-C',XS/'difftest','emu','-j','32',f'BUILD_DIR={dest/"emu"}',
        f'GEN_CSRC_DIR={generated}',f'GEN_VSRC_DIR={generated}',f'GRHSIM_MODEL_DIR={dest/"model"}',
        'GRHSIM=1','NUM_CORES=1','EMU_THREADS=0','EMU_RANDOMIZE=0','WITH_CHISELDB=0','WITH_CONSTANTIN=0',
        'NO_DIFF=0','WOLVRIX_GRHSIM_WAVEFORM=0','WOLVRIX_GRHSIM_PERF=0','EMU_OPTIMIZE=-O3','PGO_BOLT=0',
        'GRHSIM_MODEL_BUILD_JOBS=32','VM_BUILD_JOBS=32',f'CXX={CXX}',f'CC={CXX.with_name("clang")}',
        f'AR={CXX.with_name("llvm-ar")}','GRHSIM_MODEL_CXXFLAGS=-std=c++20 -O3 -march=native']
    save(dest/'model-sources.json',[identity(p) for p in sorted((dest/'model').iterdir())
        if p.suffix in ('.cpp','.hpp') or p.name=='Makefile'])
    run(command,dest/'logs/compile.log',env=env)
    save(dest/'binary.json',identity(dest/'emu/grhsim-compile/emu'))
    print(variant+' build complete',flush=True)


def check(out):
    for record in read(out/'inputs.json'): verify_identity(record)
    for variant in REVISIONS:
        verify_identity(read(out/variant/'binary.json'))
        for record in read(out/variant/'model-sources.json'): verify_identity(record)


def measure(out):
    check(out)
    command=[sys.executable,ROOT/'scripts/grhsim_single_compare.py','--baseline',out/'before',
             '--candidate',out/'after','--output',out/'paired','--cycles','100000','--pairs','8',
             '--runtime-difftest','on','--image',XS/'ready-to-run/coremark-2-iteration.bin',
             '--nemu',XS/'ready-to-run/riscv64-nemu-interpreter-so','--skip-idle-check']
    run(command,out/'measurement.log')
    check(out)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['prepare','build-before','build-after','measure','check'])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve()
    if args.stage=='prepare':prepare(out)
    elif args.stage.startswith('build-'):build(out,args.stage[6:])
    elif args.stage=='check':check(out)
    else:measure(out)
