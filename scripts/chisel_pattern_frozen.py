#!/usr/bin/env python3
"""Extract the actual frozen MSHRCtl count cone, preserving scattered slot indices.

This version intentionally binds to the recorded source/batch/group. Structural
checks and exhaustive comparison fail if that location no longer has this cone.
"""
import argparse
import json
import platform
from pathlib import Path
import re
import subprocess
from chisel_pattern_bench import ROOT,identity,run,save


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',type=Path,default=ROOT/'build/xs/grhsim32_fresh_rtl_20261028')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cpu',type=int,default=96)
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    src=args.build/'initial/package/grhsim_Gpart_0_model_sched_116.cpp';text=src.read_text()
    start=text.index('// Supernode 928:');end=text.index('// Supernode 929:',start)
    group=text[start:end]
    declarations=re.findall(r'const std::uint8_t (grhsim_v\d+_\d+) = ([^;]+);',group)
    if len(declarations)!=3:raise ValueError('frozen count cone no longer has the expected three expressions')
    body='\n'.join(f'const std::uint8_t {name} = {expr};' for name,expr in declarations)
    slots=list(dict.fromkeys(map(int,re.findall(r'value_bool_slots_\[(\d+)\]',body))))
    if len(slots)!=18:raise ValueError('expected exactly 16 MSHR and 2 pipe status input slots')
    native_sum=' + '.join(f'value_bool_slots_[{s}]' for s in slots)
    gather=' | '.join(f'(uint32_t(value_bool_slots_[{s}])<<{i})' for i,s in enumerate(slots))
    header=f'''#include <array>
#include <bit>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <random>
#include <vector>
#include <string>
#include <cstdlib>
struct State {{std::array<bool,{max(slots)+1}> values{{}}; uint32_t packed=0;}};
constexpr std::array<unsigned,18> slots{{{','.join(map(str,slots))}}};
__attribute__((noinline)) uint8_t tree(const State& s) {{
 const auto* value_bool_slots_=s.values.data();
 {body}
 return {declarations[-1][0]};
}}
__attribute__((noinline)) uint8_t sum(const State& s) {{
 const auto* value_bool_slots_=s.values.data();return {native_sum};
}}
__attribute__((noinline)) uint8_t gather_popcount(const State& s) {{
 const auto* value_bool_slots_=s.values.data();return std::popcount({gather});
}}
__attribute__((noinline)) uint8_t packed_lower_bound(const State& s) {{return std::popcount(s.packed);}}
'''
    harness=r'''
void fill(State& s,uint32_t mask) {s.packed=mask&((1u<<18)-1);for(unsigned i=0;i<18;++i)s.values[slots[i]]=(mask>>i)&1;}
void check(State& s,uint32_t mask) {
 fill(s,mask);auto a=tree(s),b=sum(s),c=gather_popcount(s),d=packed_lower_bound(s);
 if(a!=b||b!=c||c!=d){std::cerr<<"mismatch mask="<<mask<<'\n';std::exit(1);}
}
using Fn=uint8_t(*)(const State&);
volatile uint64_t observed=0;
double measure(Fn fn,const std::vector<State>& v) {
 uint64_t sum=0;constexpr unsigned loops=8192;
 auto begin=std::chrono::steady_clock::now();
 for(unsigned k=0;k<loops;++k)for(const auto& s:v)sum+=fn(s);
 auto end=std::chrono::steady_clock::now();observed=sum;
 return double(std::chrono::duration_cast<std::chrono::nanoseconds>(end-begin).count())/(loops*v.size());
}
int main() {
 State s;
 for(unsigned i=0;i<(1u<<18);++i)check(s,i);
 for(uint64_t seed:{0x37c159,0x95d273}){std::mt19937_64 r(seed);for(unsigned i=0;i<100000;++i)check(s,r());}
 std::cout<<"{\"exhaustive_inputs\":262144,\"random_inputs\":200000,\"samples\":[";
 bool first=true;
 std::array<Fn,3> functions{sum,gather_popcount,packed_lower_bound};
 std::array<const char*,3> names{"direct_sum","gather_popcount","packed_lower_bound"};
 for(auto mode:{"random","sparse","dense"}){
  std::vector<State> pool(128);std::mt19937_64 random(0x37c159);
  for(auto& s:pool){uint32_t m=random();if(std::string(mode)=="sparse")m=1u<<(m%18);if(std::string(mode)=="dense")m=~(1u<<(m%18));fill(s,m);}
  for(unsigned variant=0;variant<3;++variant)for(unsigned pair=0;pair<8;++pair){
   measure(tree,pool);measure(functions[variant],pool);double a,b;
   if(pair%2){b=measure(functions[variant],pool);a=measure(tree,pool);}else{a=measure(tree,pool);b=measure(functions[variant],pool);}
   if(!first)std::cout<<',';first=false;
   std::cout<<"{\"distribution\":\""<<mode<<"\",\"variant\":\""<<names[variant]<<"\",\"pair\":"<<pair
            <<",\"order\":\""<<(pair%2?"BA":"AB")<<"\",\"tree_ns\":"<<a<<",\"candidate_ns\":"<<b<<'}';
  }
 }
 std::cout<<"],\"checksum\":"<<observed<<"}\n";
}
'''
    (out/'frozen_count.cpp').write_text(header+harness)
    compiler=json.loads((args.build/'configuration.json').read_text())['compiler']
    run([compiler,'-std=c++20','-O3','-march=native',out/'frozen_count.cpp','-o',out/'bench'],out/'compile.log')
    run(['nm','-S','--size-sort','--demangle',out/'bench'],out/'symbols.txt')
    run(['objdump','-d','--demangle',out/'bench'],out/'assembly.txt')
    run(['taskset','-c',str(args.cpu),out/'bench'],out/'measurement.json')
    save(out/'manifest.json',dict(schema_version=1,source=identity(src),group=928,batch='0:compute:116',
        lines=[text.count('\n',0,text.index('const std::uint8_t '+name,start))+1 for name,expr in declarations],
        inputs=slots,rtl=identity(args.build/'rtl/rtl/MSHRCtl.sv'),rtl_lines=[2071,2101],
        chisel=identity(ROOT/'testcase/xiangshan/coupledL2/src/main/scala/coupledL2/tl2tl/MSHRCtl.scala'),
        source_confidence='RTL/GRH/batch exact; Scala is a module/interface-based candidate, not exact elaboration SourceInfo',
        generated=identity(out/'frozen_count.cpp'),binary=identity(out/'bench'),measurement=identity(out/'measurement.json'),
        host=platform.node(),cpu=args.cpu,compiler=subprocess.check_output([compiler,'--version'],text=True),
        boundary='Only count subcone; excludes source slot production, output guards and downstream activation. packed_lower_bound excludes gather and is not a drop-in candidate.'))
    print(out/'measurement.json')


if __name__=='__main__':main()
