#!/usr/bin/env python3
"""Check the real commit/RAT adapter against its original Preprocess reference."""
import argparse
import json
from pathlib import Path

from behavior_difftest_study import XS, FIRTOOL, run_cwd, adapter_stimulus
from behavior_state_group_validate import pipeline, build_check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    rtl = out / 'rtl'
    rtl.mkdir(exist_ok=True)
    if not (rtl / 'simulation_models.json').exists():
        run_cwd(['mill', '-i', 'difftest.test.runMain', 'difftest.BehaviorDifftestStudyMain',
                 rtl, FIRTOOL, 'grouped'], out / 'elaborate.log', XS)
    manifest = json.loads((rtl / 'simulation_models.json').read_text())
    groups = [m for m in manifest['models'] if m['lowering'] == 'grouped']
    assert len(groups) == 1 and len(groups[0]['binding']['updates']) == 16
    assert [a['rows'] for a in groups[0]['binding']['arrays']] == [32, 32, 32, 1]
    assert manifest['observer_domains']
    code = r'''
#include "grhsim_BehaviorDifftestStudy.hpp"
#include <cstdio>
#include <random>
int main(){
 for(unsigned seed:{1U,42U,20261105U}){
  GrhSIM_BehaviorDifftestStudy m;m.init();std::mt19937_64 rng(seed);
  auto equal=[&](int cycle,int edge){
   if(m.io_archEqual&&m.io_ratEqual&&m.io_commitEqual&&m.io_vectorEqual)return true;
   fprintf(stderr,"seed=%u cycle=%d edge=%d arch=%d rat=%d commit=%d vector=%d\n",seed,cycle,edge,
    int(m.io_archEqual),int(m.io_ratEqual),int(m.io_commitEqual),int(m.io_vectorEqual));return false;
  };
  for(int cycle=0;cycle<10000;++cycle){
   const bool flush=cycle%17==0;const bool collision=cycle%3==0;
   m.reset=cycle<4||(cycle>=5000&&cycle<5004);
''' + adapter_stimulus() + r'''
   m.clock=false;m.eval();if(cycle>=4&&!equal(cycle,0))return 1;
   m.clock=true;m.eval();if(cycle>=4&&!equal(cycle,1))return 2;
   m.eval();if(cycle>=4&&!equal(cycle,2))return 3;
  }
 }
 puts("PASS: original Preprocess reference, 3 x 10000 cycles; reset/flush/skip/RAT/FP/vector/delays/repeated eval");
}
'''
    results = []
    for variant in ('O', 'G'):
        dest = out / variant
        if not (dest / 'model/grhsim_BehaviorDifftestStudy.hpp').exists():
            pipeline([rtl / 'BehaviorDifftestStudy.sv'], 'BehaviorDifftestStudy', dest,
                     rtl / 'simulation_models.json', grouped=variant == 'G')
        build_check(dest, code, 'BehaviorDifftestStudy')
        results.append(dict(variant=variant, cycles=30000, pass_=True))
    (out / 'summary.json').write_text(json.dumps(results, indent=2))
    print('PASS O/G real adapter against hardware reference')


if __name__ == '__main__':
    main()
