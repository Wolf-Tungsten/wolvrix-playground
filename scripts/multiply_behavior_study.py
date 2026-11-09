#!/usr/bin/env python3
"""Frozen local hardware/behavior multiply models using the production pipeline."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from chisel_pattern_bench import mill_classpath, run, save, identity
from grhsim_single_baseline import clean_environment

ROOT = Path(__file__).resolve().parents[1]
XS = ROOT / 'testcase/xiangshan'
CXX = Path('/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++')
FIRTOOL = Path.home() / '.cache/llvm-firtool/1.135.0/bin/firtool'
KINDS = ('int-mul', 'vec-int-mul', 'vec-int-mac-lane', 'vec-int-mac-whole', 'fp-mul', 'vec-fp-mul')


def sources():
    ys = XS / 'yunsuan/src/main/scala/yunsuan'
    return [XS/'utility/src/main/scala/utility/BehaviorModels.scala',
        *[ys/n for n in ('util/MultiplyBehavior.scala', 'scalar/Mul.scala',
            'vector/vectorIMAC/VIMacBehavior.scala', 'vector/vectorIMAC/VIMac64b.scala',
            'fpu/FloatFMA.scala', 'vector/VectorFloatFMA.scala')],
        ROOT/'testcase/chisel-intrinsic/MultiplyBehaviorStudy.scala']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--kinds', nargs='+', choices=KINDS, default=list(KINDS))
    p.add_argument('--rtl-only', action='store_true')
    p.add_argument('--compute-lowering', choices=('ordinary', 'grouped'), default='ordinary')
    args = p.parse_args(); out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    compiler = mill_classpath('scalaCompilerClasspath'); runtime = mill_classpath('test/runClasspath')
    plugin = next(x for x in mill_classpath('scalacPluginClasspath') if 'chisel-plugin' in x)
    signature = [identity(p) for p in sources()]
    stamp = out/'scala-sources.json'; classes = out/'classes'; classes.mkdir(exist_ok=True)
    if not stamp.exists() or json.loads(stamp.read_text()) != signature:
        if any(out.glob('*/A/rtl/MultiplyFixture.sv')):
            raise ValueError('sources changed after RTL generation; use a new output directory')
        run(['java','-Xmx8g','-cp',':'.join(compiler),'scala.tools.nsc.Main',
            '-classpath',':'.join(runtime),'-Xplugin:'+plugin,'-language:reflectiveCalls',
            '-d',classes,*sources()],out/'scala.log')
        save(stamp,signature)
    save(out/'classpath.json',[str(classes)]+runtime)
    for path in sources():
        dest=out/'source-copy'/path.relative_to(ROOT); dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,dest)
    frozen=out/'tools-frozen'
    if not frozen.exists():
        shutil.copytree(ROOT/'build/grhsim32-tools/python',frozen/'python',
                        ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copy2(ROOT/'build/grhsim32-tools/wolvrix/libwolvrix-lib.so',frozen/'libwolvrix-lib.so')
        save(frozen/'identity.json',[identity(p) for p in sorted(frozen.rglob('*')) if p.is_file()])
    for record in json.loads((frozen/'identity.json').read_text()):
        if identity(record['path']) != record: raise ValueError('frozen compiler changed')
    env=dict(clean_environment(),PYTHONPATH=str(frozen/'python'),LD_LIBRARY_PATH=str(frozen),
             PYTHONDONTWRITEBYTECODE='1')
    link=subprocess.check_output(['ldd',str(frozen/'python/wolvrix/_wolvrix.so')],env=env,text=True)
    (out/'frozen-linkage.log').write_text(link)
    assert str(frozen/'libwolvrix-lib.so') in link
    for kind in args.kinds:
        for label,mode in (('A','hardware'),('B','behavior')):
            dest=out/kind/label; rtl=dest/'rtl'; rtl.mkdir(parents=True,exist_ok=True)
            if not (rtl/'MultiplyFixture.sv').exists():
                study_args = [rtl,FIRTOOL,kind,mode]
                if args.compute_lowering == 'grouped' and mode == 'behavior':
                    study_args.append('grouped')
                run(['java','-Xmx12g','-cp',str(classes)+':'+':'.join(runtime),
                    'study.multiply.MultiplyBehaviorStudyMain',*map(str, study_args)],dest/'elaborate.log')
            manifest=json.loads((rtl/'simulation_models.json').read_text())
            if label=='A': assert manifest['mode']=='hardware' and not manifest['models']
            else:
                assert manifest['mode']==kind and len(manifest['models'])==1
                assert manifest['models'][0]['observer_only'] is False
                assert manifest['compute_lowering'] == args.compute_lowering
                assert manifest['models'][0]['lowering'] == (
                    'compute-grouped' if args.compute_lowering == 'grouped' else 'ordinary')
            print('RTL',kind,label,flush=True)
            if args.rtl_only: continue
            model=dest/'model'
            if not (model/'grhsim_MultiplyFixture.hpp').exists():
                (dest/'input.f').write_text(str(rtl/'MultiplyFixture.sv')+'\n')
                (dest/'read_args.txt').write_text('')
                emit_env=dict(env,WOLVRIX_SIMULATION_MODELS_MANIFEST=str(rtl/'simulation_models.json'),
                    WOLVRIX_XS_GRHSIM_PRE_REG_TO_MEM_JSON=str(dest/'pre.json'),
                    WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON='0',WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON='0')
                run([sys.executable,ROOT/'scripts/wolvrix_xs_grhsim.py',dest/'input.f','MultiplyFixture',
                    model,dest/'graph.json',dest/'read_args.txt','info','--waveform','off','--perf','off',
                    '--behavior-state-lowering','ordinary','--behavior-compute-lowering',
                    args.compute_lowering if label == 'B' else 'ordinary'],dest/'emit.log',emit_env)
            run(['make','-C',model,'-j8','CXX='+str(CXX),'CXXFLAGS=-std=c++20 -O3 -march=native'],dest/'compile.log',env)
            save(dest/'model-manifest.json',[identity(p) for p in sorted(model.glob('*')) if p.is_file()])
            print('BUILT',kind,label,flush=True)
    save(out/'build-complete.json',dict(kinds=args.kinds,rtl_only=args.rtl_only,
        compute_lowering=args.compute_lowering,
        source_manifest=identity(stamp),tools=identity(frozen/'identity.json'),driver=identity(__file__)))


if __name__ == '__main__': main()
