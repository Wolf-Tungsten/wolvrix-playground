"""Replay the frozen XS/CV32 designs with original, permuted and byte-read reduction inputs."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import platform
import shutil

from armor_lane_replay import emit_frozen_model, prepare
from cv32e40p_compare import CFLAGS, CXX, ROOT, run, save
from grhsim_elf_section_identity import sections
from grhsim_single_baseline import clean_environment, identity
from xiangshan_cv32_ablation_measure import read, verify

MODES = {'A': 0, 'P': 1, 'B': 2}
ARCHIVE = ROOT.parent/'wolvrix-playground-cv32e40p'
DEFAULT = ROOT/'build/armor-mask-read-v1/frozen'


def freeze(out):
    prepare(ARCHIVE, out, ROOT/'build/armor-lane-v1/tools')
    snap = out/'snapshot'
    snap.mkdir()
    source = ROOT/'wolvrix/lib/emit/grhsim_cpp.cpp'
    shutil.copy2(source, snap/source.name)
    save(out/'policy.json', dict(modes=MODES, target='existing stable shared reduction inputs only',
        baseline=read(out/'inputs.json')['xs_binary'], emitter=identity(snap/source.name),
        candidate='physical-slot order within each original 32-bit half only if complete eight-lane reads increase',
        native='x86-64 BMI2 PEXT, x86-64 canonical low-byte multiply fallback, otherwise scalar',
        decision='B versus A must reduce total affected compute instructions and bytes and reduce reads in the preselected region',
        witness=dict(batch=21,supernode=28016,slot=723607),
        timing='if gate passes, eight serial alternating pairs per design under the archive CPU96 lock; no timing for P'))


def emit(out, design, mode):
    target = out/design/mode/'model'
    same = emit_frozen_model(out, design, target, {
        'WOLVRIX_GRHSIM_BOOL_LANE_PACK_AUDIT': '0',
        'WOLVRIX_GRHSIM_BOOL_LANE_PACK': '0',
        'WOLVRIX_GRHSIM_REDUCTION_MASK_LAYOUT': str(MODES[mode])})
    if same != (design == 'cv' or mode == 'A'):
        raise ValueError(f'{design} {mode}: unexpected source identity')


def emit_all(out):
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(emit,out,d,m) for d in ('xs','cv') for m in MODES]
        for future in futures:
            future.result()


def compile_xs(out, mode):
    original = ARCHIVE/'build/xs/indexed-snapshot-20261117-v3/candidate'
    dst = out/'xs'/mode
    shutil.copytree(original/'chisel-home',dst/'chisel-home',dirs_exist_ok=True)
    env = clean_environment()
    env.update(NOOP_HOME=str(ARCHIVE/'testcase/xiangshan'),LC_ALL='C')
    command = [arg.replace(str(original),str(dst)) for arg in read(original/'logs/compile.command.json')['argv']]
    run(command,dst/'compile.log',env=env)
    save(dst/'binary.json',identity(dst/'emu/grhsim-compile/emu'))


def compile_cv(out):
    dst = out/'cv/B'
    model = dst/'model'
    run(['make','-C',model,'-j','8','CXX='+str(CXX),'CXXFLAGS='+' '.join(CFLAGS)],dst/'compile.log')
    run([CXX,*CFLAGS,'-DCV32_GRHSIM','-I',model,ARCHIVE/'build/cv32e40p/run2/inputs/fixture/harness.cpp',
         model/'libgrhsim_Cv32Bench.a','-o',model/'emu'],dst/'link.log')
    baseline=Path(read(out/'inputs.json')['cv_binary']['path'])
    report=dict(A=sections(baseline),B=sections(model/'emu'),binary=identity(model/'emu'))
    if report['A'] != report['B']:
        raise ValueError('CV32 code/data sections changed')
    save(dst/'sections.json',report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('freeze','emit','build'))
    parser.add_argument('--out',type=Path,default=DEFAULT)
    parser.add_argument('--design',choices=('xs','cv'))
    parser.add_argument('--mode',choices=MODES)
    args=parser.parse_args()
    out=args.out.resolve()
    if args.stage=='freeze':
        freeze(out)
    elif args.stage=='emit':
        if not args.design and not args.mode: emit_all(out)
        elif args.design and args.mode: emit(out,args.design,args.mode)
        else: parser.error('individual emit needs both design and mode')
    elif not platform.node().startswith('node030'):
        parser.error('native model compilation requires node030')
    elif args.design=='cv':
        compile_cv(out)
    elif args.design=='xs' and args.mode in ('P','B'):
        compile_xs(out,args.mode)
    else:
        parser.error('build needs cv or xs with mode P/B')
