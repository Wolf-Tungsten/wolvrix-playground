#!/usr/bin/env python3
"""Local array-group study using the production XiangShan lowering pipeline."""
import argparse,json,os,subprocess,sys,shutil,hashlib
from pathlib import Path
from chisel_pattern_bench import mill_classpath,run,save
ROOT=Path(__file__).resolve().parents[1]
FIRTOOL=Path.home()/'.cache/llvm-firtool/1.135.0/bin/firtool'
CXX=Path('/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++')

def command(args,log,env=None,cwd=None):
    with log.open('w') as f:r=subprocess.run([str(x) for x in args],cwd=cwd or ROOT,env=env,stdout=f,stderr=subprocess.STDOUT)
    if r.returncode:raise RuntimeError(f'{log}: command failed {r.returncode}\n'+log.read_text()[-3500:])

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--fixture',choices=['simple','rat'],default='simple');p.add_argument('--rtl-from',type=Path);a=p.parse_args()
 out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
 frozen=out/'tools-frozen'
 if not frozen.exists():
  shutil.copytree(ROOT/'build/grhsim32-tools/python',frozen/'python')
  shutil.copy2(ROOT/'build/grhsim32-tools/wolvrix/libwolvrix-lib.so',frozen/'libwolvrix-lib.so')
  save(frozen/'identity.json',[dict(path=str(x.relative_to(frozen)),sha256=hashlib.sha256(x.read_bytes()).hexdigest()) for x in sorted(frozen.rglob('*')) if x.is_file()])
 if not (frozen/'libwolvrix-lib.so').is_file():raise ValueError('legacy snapshot lacks native compiler library; use a new output')
 for record in json.loads((frozen/'identity.json').read_text()):
  if hashlib.sha256((frozen/record['path']).read_bytes()).hexdigest()!=record['sha256']:raise ValueError('frozen tool changed')
 if a.rtl_from:
  for mode in ('hardware','model'):
   if not (out/mode).exists():shutil.copytree(a.rtl_from.resolve()/mode,out/mode)
 else:
  classes=out/'classes';classes.mkdir(exist_ok=True)
  runtime=mill_classpath('test/runClasspath');compiler=mill_classpath('scalaCompilerClasspath');plugin=next(x for x in mill_classpath('scalacPluginClasspath') if 'chisel-plugin' in x)
  command(['java','-Xmx4g','-cp',':'.join(compiler),'scala.tools.nsc.Main','-classpath',':'.join(runtime),'-Xplugin:'+plugin,
     '-d',classes,ROOT/'testcase/chisel-intrinsic/BehaviorStateGroupStudy.scala'],out/'scala.log')
  for mode in ('hardware','model'):
   dest=out/mode;dest.mkdir(exist_ok=True)
   if not (dest/'simulation_models.json').exists():
    command(['java','-Xmx8g','-cp',str(classes)+':'+':'.join(runtime),'study.groups.BehaviorStateGroupStudyMain',dest,FIRTOOL,a.fixture,mode],dest/'elaborate.log',cwd=dest)
 for label,mode,lowering in [('H','hardware','ordinary'),('O','model','ordinary'),('G','model','grouped')]:
  dest=out/label;dest.mkdir(exist_ok=True);source=out/mode
  files=sorted(source.glob('*.sv'));(dest/'input.f').write_text('\n'.join(str(f) for f in files)+'\n');(dest/'read_args.txt').write_text('')
  env=dict(os.environ,PYTHONPATH=str(frozen/'python'),LD_LIBRARY_PATH=str(frozen),
      WOLVRIX_SIMULATION_MODELS_MANIFEST=str(source/'simulation_models.json'),
      WOLVRIX_XS_GRHSIM_PRE_REG_TO_MEM_JSON=str(dest/'pre_reg_to_mem.json'),WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON='0',WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON='0')
  save(dest/'environment.json',{k:v for k,v in env.items() if k.startswith(('WOLVRIX','PYTHONPATH','LD_LIBRARY_PATH'))})
  if not (dest/'model/grhsim_BehaviorGroupFixture.hpp').exists():
   command([sys.executable,ROOT/'scripts/wolvrix_xs_grhsim.py',dest/'input.f','BehaviorGroupFixture',dest/'model',dest/'graph.json',dest/'read_args.txt','info',
     '--waveform','off','--perf','off','--behavior-state-lowering',lowering],dest/'emit.log',env)
  command(['make','-C',dest/'model','-j8','CXX='+str(CXX),'CXXFLAGS=-std=c++20 -O3 -march=native'],dest/'compile.log')
 save(out/'build-summary.json',dict(fixture=a.fixture,variants=['H','O','G'],production_driver=str(ROOT/'scripts/wolvrix_xs_grhsim.py')))
if __name__=='__main__':main()
