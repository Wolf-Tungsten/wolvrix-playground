#!/usr/bin/env python3
"""Generate and lower the scalar integer/bit behavior carriers."""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XS = ROOT / 'testcase/xiangshan'
FIRTOOL = Path.home() / '.cache/llvm-firtool/1.135.0/bin/firtool'
CXX = Path('/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++')

def mill_cp(name):
    p = XS / 'out/xiangshan' / f'{name}.json'
    return [x.split(':', 3)[3] for x in json.loads(p.read_text())['value']]

def run(cmd, cwd, log, env=None):
    with Path(log).open('w') as f:
        r = subprocess.run([str(x) for x in cmd], cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT)
    if r.returncode:
        raise RuntimeError(Path(log).read_text()[-4000:])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--model', choices=['int-alu','int-bku'], required=True)
    ap.add_argument('--mode', choices=['hardware', 'behavior'], default='behavior')
    ap.add_argument('--compute-lowering', choices=['ordinary','grouped'], default='ordinary')
    ap.add_argument('--emit-runtime-profile', action='store_true')
    ap.add_argument('--profile-perf', action='store_true')
    args = ap.parse_args(); out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    if args.mode == 'hardware' and args.compute_lowering == 'grouped':
        raise ValueError('hardware fixture cannot use grouped compute lowering')
    compiler, runtime = mill_cp('scalaCompilerClasspath'), mill_cp('test/runClasspath')
    plugin = next(x for x in mill_cp('scalacPluginClasspath') if 'chisel-plugin' in x)
    classes = out/'classes'; classes.mkdir(exist_ok=True)
    sources = [XS/'utility/src/main/scala/utility/BehaviorModels.scala',
               XS/'src/main/scala/xiangshan/package.scala', XS/'src/main/scala/xiangshan/Parameters.scala',
               XS/'src/main/scala/xiangshan/XSCore.scala', XS/'src/main/scala/xiangshan/backend/fu/FuConfig.scala',
               XS/'src/main/scala/xiangshan/backend/fu/Alu.scala', XS/'src/main/scala/xiangshan/backend/fu/Bku.scala',
               ROOT/'testcase/chisel-intrinsic/IntegerBehaviorStudy.scala']
    run(['java','-Xmx8g','-cp',':'.join(compiler),'scala.tools.nsc.Main','-classpath',':'.join(runtime),
         '-Xplugin:'+plugin,'-language:reflectiveCalls','-d',classes,*sources], ROOT, out/'scala.log')
    for label, grouped in [('ordinary',False),('grouped',True)]:
        if label != args.compute_lowering: continue
        dest = out/label; dest.mkdir(exist_ok=True)
        run(['java','-Xmx8g','-cp',str(classes)+':'+':'.join(runtime),
             'study.integer.IntegerBehaviorStudyMain',dest,FIRTOOL,args.model,args.mode,label], ROOT, dest/'elaborate.log')
        manifest = json.loads((dest/'simulation_models.json').read_text())
        if args.mode == 'hardware':
            assert manifest['mode'] == 'hardware' and not manifest['models']
        else:
            assert manifest['models'][0]['name'] == args.model
            if grouped: assert manifest['models'][0]['lowering'] == 'compute-grouped'
        (dest/'input.f').write_text(str(dest/'IntegerBehavior.sv')+'\n')
        (dest/'read_args.txt').write_text('')
        model = dest/'model'; graph = dest/'graph.json'; model.mkdir(exist_ok=True)
        env = dict(os.environ, WOLVRIX_SIMULATION_MODELS_MANIFEST=str(dest/'simulation_models.json'),
                   WOLVRIX_XS_GRHSIM_PRE_REG_TO_MEM_JSON=str(dest/'pre.json'),
                   WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON='0',
                   WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON='0',
                   PYTHONPATH=str(ROOT/'build/grhsim32-tools/python'))
        if args.emit_runtime_profile:
            env['GRHSIM_EMIT_RUNTIME_PROFILE'] = '1'
        run([sys.executable, ROOT/'scripts/wolvrix_xs_grhsim.py',dest/'input.f','IntegerBehaviorFixture',model,graph,dest/'read_args.txt','info',
             '--waveform','off','--perf','eval' if args.profile_perf else 'off','--behavior-compute-lowering',label], ROOT, dest/'emit.log', env)
        run(['make','-C',model,'-j8','CXX='+str(CXX),'CXXFLAGS=-std=c++20 -O3 -march=native'], ROOT, dest/'compile.log', env)
        print(json.dumps({'model':args.model,'lowering':label,'output':str(dest)}))

if __name__ == '__main__': main()
