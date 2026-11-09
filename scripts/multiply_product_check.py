#!/usr/bin/env python3
"""Exact significand product equivalence at the original pipelined CSA boundary."""
import argparse
from chisel_pattern_bench import mill_classpath,run,save
from multiply_behavior_study import ROOT,FIRTOOL,CXX
from behavior_state_group_validate import pipeline,build_check
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    compiler=mill_classpath('scalaCompilerClasspath');runtime=mill_classpath('test/runClasspath')
    plugin=next(x for x in mill_classpath('scalacPluginClasspath') if 'chisel-plugin' in x)
    classes=out/'classes';classes.mkdir(exist_ok=True)
    run(['java','-Xmx8g','-cp',':'.join(compiler),'scala.tools.nsc.Main','-classpath',':'.join(runtime),
        '-Xplugin:'+plugin,'-language:reflectiveCalls','-d',classes,
        ROOT/'testcase/chisel-intrinsic/FloatProductStudy.scala'],out/'scala.log')
    run(['java','-Xmx12g','-cp',str(classes)+':'+':'.join(runtime),'study.multiply.FloatProductStudyMain',
        out,FIRTOOL],out/'elaborate.log')
    pipeline([out/'FloatProductFixture.sv'],'FloatProductFixture',out)
    code=r'''
#include "grhsim_FloatProductFixture.hpp"
#include <random>
#include <cstdio>
int main(){
 for(unsigned seed:{1U,42U,20261105U}){
  GrhSIM_FloatProductFixture m;m.init();std::mt19937_64 rng(seed);bool initialized=false;
  for(unsigned cycle=0;cycle<10000;++cycle){
   m.reset=cycle<4;m.io_a=rng()&((UINT64_C(1)<<53)-1);m.io_b=rng()&((UINT64_C(1)<<53)-1);
   m.io_format=cycle%3+1;m.io_fire=!m.reset&&(cycle%7!=0);
   m.clock=false;m.eval();m.clock=true;m.eval();initialized|=m.io_fire;
   if(initialized&&!m.io_equal){fprintf(stderr,"seed=%u cycle=%u\n",seed,cycle);return 1;}
   m.eval();if(initialized&&!m.io_equal)return 2;
  }
 }
 puts("PASS: scalar/vector significand products at original CSA boundary, 30000 cycles");
}
'''
    build_check(out,code,'FloatProductFixture');save(out/'summary.json',dict(pass_=True,cycles=30000))


if __name__=='__main__':main()
