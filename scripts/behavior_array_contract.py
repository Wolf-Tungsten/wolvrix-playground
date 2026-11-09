#!/usr/bin/env python3
"""Verify array ordering, reset, read-before-write and encapsulation in GrhSIM."""
import argparse
import json
from pathlib import Path
import subprocess
from chisel_pattern_bench import mill_classpath, run, save

ROOT=Path(__file__).resolve().parents[1]
CXX=Path('/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++')

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(); out=args.output.resolve(); out.mkdir(parents=True,exist_ok=False)
    compiler=mill_classpath('scalaCompilerClasspath'); runtime=mill_classpath('test/runClasspath')
    plugin=next(p for p in mill_classpath('scalacPluginClasspath') if 'chisel-plugin' in p)
    classes=out/'classes'; classes.mkdir()
    utility=ROOT/'testcase/xiangshan/utility/src/main/scala/utility'
    run(['java','-Xmx4g','-cp',':'.join(compiler),'scala.tools.nsc.Main','-classpath',':'.join(runtime),
         '-Xplugin:'+plugin,'-d',classes,utility/'Compatibility.scala',utility/'BehaviorModels.scala',
         ROOT/'testcase/chisel-intrinsic/BehaviorArrayContract.scala'],out/'scala.log')
    run(['java','-Xmx4g','-cp',str(classes)+':'+':'.join(runtime),'study.models.BehaviorArrayContractMain',
         out,Path.home()/'.cache/llvm-firtool/1.135.0/bin/firtool'],out/'elaborate.log')
    manifest=json.loads((out/'simulation_models.json').read_text()); updates=manifest['models'][0]['updates']
    assert [u['order'] for u in updates]==list(range(4))
    assert all(u['address'] and u['data'] for u in updates)
    tools=ROOT/'build/grhsim32-tools/bin'; model=out/'model'
    run([tools/'grhsim32_frontend',out/'graph.json','BehaviorArrayContract',out/'BehaviorArrayContract.sv'],out/'frontend.log')
    run([tools/'grhsim32_pattern_emit',out/'graph.json','BehaviorArrayContract',model,'raw'],out/'emit.log')
    run(['make','-C',model,'-j4','CXX='+str(CXX),'CXXFLAGS=-std=c++20 -O2 -march=native'],out/'compile.log')
    source=r'''
#include "grhsim_BehaviorArrayContract.hpp"
#include <array>
#include <cstdio>
#include <random>
#include <chrono>
int main(){
 GrhSIM_BehaviorArrayContract m; m.init(); std::mt19937_64 rng(20261105);
 std::array<uint64_t,32> expected{}; uint64_t prior=0;
 auto start=std::chrono::steady_clock::now();
 for(unsigned cycle=0;cycle<10000;++cycle){
   m.reset=cycle==0 || cycle==5000; m.io_readIndex=rng()%32;
   const unsigned same=rng()%32;
'''
    for lane in range(3):
        source+=f' m.io_valid_{lane}=rng()%2; m.io_index_{lane}=cycle%2?same:rng()%32; m.io_value_{lane}=rng();\n'
    source+=' m.clock=false; m.eval(); prior=expected[m.io_readIndex];\n'
    for lane in range(3):
        source+=f' if(m.io_valid_{lane})expected[m.io_index_{lane}]=m.io_value_{lane};\n'
    source+=''' if(m.reset){for(unsigned i=0;i<32;++i)expected[i]=i;prior=0;}
 m.clock=true; m.eval();
 if(m.io_priorRead!=prior || m.io_readValue!=expected[m.io_readIndex] || m.io_copied!=123) return 1;
'''
    for row in range(32): source+=f' if(m.io_state_{row}!=expected[{row}])return 2;\n'
    source+=''' }
 printf("PASS 10000 cycles: ordered writes/reset/pre-edge reads/snapshot isolation; elapsed_ns=%lld\\n",
 (long long)std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count());
}
'''
    (model/'check.cpp').write_text(source)
    run([CXX,'-std=c++20','-O2','-march=native','-I'+str(model),model/'check.cpp',
         model/'libgrhsim_BehaviorArrayContract.a','-o',model/'check'],out/'check-compile.log')
    run([model/'check'],out/'check.log')
    save(out/'summary.json',dict(pass_=True,cycles=10000,manifest=manifest,log=(out/'check.log').read_text()))

if __name__=='__main__': main()
