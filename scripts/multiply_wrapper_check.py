#!/usr/bin/env python3
"""Exercise real FU control, flush, mask/tail and status merging around A/B."""
import argparse
import json
from pathlib import Path
import sys
from chisel_pattern_bench import mill_classpath,run,save,identity
from multiply_behavior_study import ROOT,FIRTOOL,CXX,KINDS
from behavior_state_group_validate import pipeline


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    compiler=mill_classpath('scalaCompilerClasspath');runtime=mill_classpath('test/runClasspath')
    plugin=next(x for x in mill_classpath('scalacPluginClasspath') if 'chisel-plugin' in x)
    src=ROOT/'testcase/chisel-intrinsic/MultiplyWrapperStudy.scala';classes=out/'classes';classes.mkdir(exist_ok=True)
    run(['java','-Xmx8g','-cp',':'.join(compiler),'scala.tools.nsc.Main','-classpath',':'.join(runtime),
        '-Xplugin:'+plugin,'-language:reflectiveCalls','-d',classes,src],out/'scala.log')
    results=[]
    for kind in KINDS:
        dest=out/kind;rtl=dest/'rtl';rtl.mkdir(parents=True,exist_ok=True)
        if not (rtl/'MultiplyWrapperFixture.sv').exists():
            run(['java','-Xmx12g','-cp',str(classes)+':'+':'.join(runtime),'study.multiply.MultiplyWrapperStudyMain',
                rtl,FIRTOOL,kind],dest/'elaborate.log')
        if not (dest/'model/libgrhsim_MultiplyWrapperFixture.a').exists():
            pipeline([rtl/'MultiplyWrapperFixture.sv'],'MultiplyWrapperFixture',dest)
        count={'int-mul':6,'vec-int-mul':16,'fp-mul':5,'vec-fp-mul':11}[kind]
        code=r'''
#include "grhsim_MultiplyWrapperFixture.hpp"
#include <cstdio>
#include <random>
int main(){
 for(unsigned seed:{1U,42U,20261105U}){
  GrhSIM_MultiplyWrapperFixture m;m.init();std::mt19937_64 rng(seed);
  unsigned outputs=0,flushes=0,masked=0;
  for(unsigned cycle=0;cycle<10000;++cycle){
   m.reset=cycle<4||(cycle>=5000&&cycle<5004);
   m.io_valid=!m.reset&&(rng()%4!=0);m.io_ready=rng()%5!=0;
   m.io_flush=cycle%19==0;flushes+=m.io_flush;
   m.io_a={rng(),rng()};m.io_b={rng(),rng()};m.io_c={rng(),rng()};m.io_mask={rng(),rng()};
   m.io_op=cycle%OP_COUNT;m.io_format=FORMAT_EXPR;m.io_rm=(cycle/17)%5;
   m.io_vl=rng()%17;m.io_vstart=rng()%17;m.io_tag=cycle%128;m.io_uop=rng()%4;
   m.io_vm=rng()%2;m.io_ma=rng()%2;m.io_ta=rng()%2;masked+=!m.io_vm;
   // Widening beyond SEW32 is illegal; keep the test at the real interface contract.
   WIDEN_FIX
   m.clock=false;m.eval();if(cycle>=4&&!m.io_equal){fprintf(stderr,"low seed=%u cycle=%u\n",seed,cycle);return 1;}
   m.clock=true;m.eval();m.eval();if(!m.reset&&!m.io_equal){fprintf(stderr,"rise seed=%u cycle=%u\n",seed,cycle);return 2;}
   outputs+=m.io_outValid;
  }
  if(!outputs||!flushes||!masked)return 3;
 }
 puts("PASS: real FU wrapper, 3x10000 cycles, reset/flush/ready/mask/tail/vstart/status merge");
}
'''
        fmt='cycle%3+1' if 'fp' in kind else 'cycle%4'
        fix=''
        if kind=='vec-int-mul':
            fix='if(m.io_format==3 && (m.io_op==4||m.io_op==5||m.io_op==6||(m.io_op>=8&&m.io_op<=11)))m.io_format=2;'
        if kind=='vec-fp-mul':fix='if(m.io_op>=9 && m.io_format==3)m.io_format=2;'
        code=code.replace('OP_COUNT',str(count)).replace('FORMAT_EXPR',fmt).replace('WIDEN_FIX',fix)
        source=dest/'check.cpp';source.write_text(code);model=dest/'model'
        run([CXX,'-std=c++20','-O3','-march=native','-I'+str(model),source,
            model/'libgrhsim_MultiplyWrapperFixture.a','-o',dest/'check'],dest/'check-compile.log')
        run([dest/'check'],dest/'check.log');print('PASS',kind,flush=True)
        results.append(dict(kind=kind,pass_=True,cycles=30000));save(out/'summary.json',results)


if __name__=='__main__':main()
