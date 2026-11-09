#!/usr/bin/env python3
"""Independent array scoreboard and identical whole-fixture timing harness."""
import argparse,json
from pathlib import Path
from behavior_state_group_study import command,CXX

def harness(rat):
 lanes=520 if rat else 3;rows=[32,32,32,1] if rat else [32,32];widths=[8]*4 if rat else [64,9]
 s=r'''#include "grhsim_BehaviorGroupFixture.hpp"
#include <array>
#include <random>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <chrono>
#include <string>
int main(int argc,char**argv){
const bool timing=argc>1 && std::string(argv[1])=="--bench";
const std::string scenario=argc>3?argv[3]:"sparse";
const unsigned seed=argc>2?std::strtoul(argv[2],nullptr,10):42;
GrhSIM_BehaviorGroupFixture m;m.init();std::mt19937_64 rng(seed);
std::array<std::array<uint64_t,32>,4> expected{};
uint64_t hash=0;
auto check=[&](unsigned cycle,const char* phase){
'''
 for b,n in enumerate(rows):
  for i in range(n):s+=f'if(m.io_snapshot_{b}_{i}!=expected[{b}][{i}]){{fprintf(stderr,"cycle=%u phase=%s bank={b} row={i} got=%llu expected=%llu\\n",cycle,phase,(unsigned long long)m.io_snapshot_{b}_{i},(unsigned long long)expected[{b}][{i}]);return false;}}\n'
 s+='if(m.io_selected!=expected[0][m.io_readIndex])return false;\n'
 if rat:
  for i in range(64):
   row=i//2;s+=f'if(m.io_vectorMapping_{i}!=2*'+('expected[3][0]' if row==0 else f'(expected[2][{row}]+22)')+f'+{i%2})return false;\n'
 s+='return true;};\nauto start=std::chrono::steady_clock::now();\nfor(unsigned cycle=0;cycle<10000;++cycle){\n'
 s+=f'std::array<bool,{lanes}> valid;std::array<unsigned,{lanes}> index,kind;std::array<uint64_t,{lanes}> data;\n'
 s+=f'''for(unsigned lane=0;lane<{lanes};++lane){{
valid[lane]=cycle%17!=0 && rng()%5==0;
index[lane]=cycle%3==0?5:rng()%64; kind[lane]=1u<<(rng()%{len(rows)});
data[lane]=rng();
'''
 if rat:s+='data[lane]%=kind[lane]==8?22:kind[lane]==4?128:kind[lane]==1?224:256;\n'
 s+='}\n'
 if rat:s+=f'''if(timing && scenario=="sparse"){{const unsigned n=rng()%17;for(unsigned lane=0;lane<{lanes};++lane)valid[lane]=cycle%17!=0 && lane<n;}}\n'''
 s+='if(timing && scenario=="idle"){valid.fill(false);index.fill(0);kind.fill(0);data.fill(0); }\n'
 s+=f'''if(cycle%11==0 && !(timing && scenario=="idle")){{
valid.fill(false);valid[0]=true;valid[{lanes-1}]=true;index[0]=index[{lanes-1}]=5;
kind[0]=kind[{lanes-1}]=1;data[0]=expected[0][5]^1;data[{lanes-1}]=expected[0][5];
}}
m.reset=cycle<3 || (cycle>=5000 && cycle<5003);m.io_readIndex=timing && scenario=="idle"?0:rng()%32;
'''
 for i in range(lanes):s+=f'm.io_valid_{i}=valid[{i}];m.io_index_{i}=index[{i}];m.io_kind_{i}=kind[{i}];m.io_data_{i}=data[{i}];\n'
 s+='m.clock=false;m.eval();if(!timing && cycle>0 && !check(cycle,"pre"))return 1;\n'
 s+=f'const uint64_t old_arch0=expected[0][0];if(!timing)for(unsigned lane=0;lane<{lanes};++lane)if(valid[lane]){{\n'
 for b,n in enumerate(rows):
  cond=f'(kind[lane] & {1<<b})'
  if rat and b in (1,2):cond+=' && index[lane]<32'+(' && index[lane]!=0' if b==2 else '')
  mask='UINT64_MAX' if widths[b]==64 else str((1<<widths[b])-1)+'ULL'
  value='(data[lane] ^ (lane==2 ? old_arch0 : 0))' if not rat and b==1 else 'data[lane]'
  s+=f'if({cond})expected[{b}][{("0" if n==1 else "index[lane]&31")} ]={value}&{mask};\n'
 s+='}\nif(!timing && m.reset){\n'
 for b,n in enumerate(rows):s+=f'for(unsigned row=0;row<{n};++row)expected[{b}][row]='+('0' if b==0 else 'row')+';\n'
 s+='}\nm.clock=true;m.eval();if(!timing && !check(cycle,"post"))return 2;\n'
 s+='if(!timing){m.eval();if(!check(cycle,"repeated"))return 3;m.io_data_0^=1;m.eval();if(!check(cycle,"same-edge-input-change"))return 4;}\n'
 for b,n in enumerate(rows):
  for i in range(n):s+=f'hash=(hash*UINT64_C(1099511628211)) ^ m.io_snapshot_{b}_{i};\n'
 if rat:
  for i in range(64):s+=f'hash=(hash*UINT64_C(1099511628211)) ^ m.io_vectorMapping_{i};\n'
 s+='hash=(hash*UINT64_C(1099511628211)) ^ m.io_selected;\n}\n'
 s+=r'''auto ns=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count();
if(timing)printf("{\"cycles\":10000,\"ns\":%lld,\"hash\":%llu}\n",(long long)ns,(unsigned long long)hash);
else printf("PASS seed=%u 10000 cycles: pre-edge/reset/ordered writes/revert/snapshot/repeated eval; hash=%llu\n",seed,(unsigned long long)hash);
#if WOLVRIX_GRHSIM_PERF
const auto c=m.perf_counters();printf("counters commits=%llu updates=%llu touched_rows=%llu changed_rows=%llu compute_batches=%llu memory_reads=%llu\n",(unsigned long long)c.behaviorGroupCommits,(unsigned long long)c.behaviorEnabledUpdates,(unsigned long long)c.behaviorTouchedRows,(unsigned long long)c.touchedWriteCount,(unsigned long long)c.computeBatchExecCount,(unsigned long long)c.scheduledMemoryReads);
#endif
}
'''
 return s

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--fixture',choices=['simple','rat'],default='simple');a=p.parse_args();out=a.output.resolve();records=[]
 for v in 'HOG':
  dest=out/v;model=dest/'model';(model/'check.cpp').write_text(harness(a.fixture=='rat'))
  command([CXX,'-std=c++20','-O3','-march=native','-I'+str(model),model/'check.cpp',model/'libgrhsim_BehaviorGroupFixture.a','-o',model/'check'],dest/'check-compile.log')
  for seed in (1,42,20261105):
   command([model/'check','--check',str(seed)],dest/f'check-{seed}.log')
   records.append(dict(variant=v,seed=seed,pass_=True,cycles=10000))
 (out/'check-summary.json').write_text(json.dumps(records,indent=2))
 print('PASS: H/O/G, 3 seeds x 10000 cycles each')
if __name__=='__main__':main()
