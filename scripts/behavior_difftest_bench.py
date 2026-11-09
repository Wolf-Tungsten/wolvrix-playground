#!/usr/bin/env python3
"""Build/timestamp 10k-cycle hardware and ordinary-GRH behavior adapter fixtures."""
import argparse
import csv
import json
from pathlib import Path
import platform
import subprocess
from behavior_difftest_study import XS,FIRTOOL,FRONTEND,EMITTER,run_cwd,adapter_stimulus
from chisel_pattern_bench import run,save

CXX='/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++'

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
 p.add_argument('--build',action='store_true');p.add_argument('--measure',action='store_true');args=p.parse_args()
 out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
 if args.build:
  for variant in 'AB':
   dest=out/variant;dest.mkdir(exist_ok=False)
   run_cwd(['mill','-i','difftest.test.runMain','difftest.BehaviorDifftestBenchMain',dest,FIRTOOL,variant],dest/'elaborate.log',XS)
   run([FRONTEND,dest/'graph.json','BehaviorDifftestBench',dest/'BehaviorDifftestBench.sv'],dest/'frontend.log')
   model=dest/'model';run([EMITTER,dest/'graph.json','BehaviorDifftestBench',model,'raw'],dest/'emit.log')
   run(['make','-C',model,'-j8','CXX='+CXX,'CXXFLAGS=-std=c++20 -O3 -march=native'],dest/'compile.log')
   # Reuse the validated identical input stream; the timed loop includes stimulus
   # generation and hashes, so these times are fixture walltime, not pure eval.
   body=adapter_stimulus()
   code='''#include "grhsim_BehaviorDifftestBench.hpp"
#include <chrono>
#include <cstdio>
#include <random>
#include <cstdint>
int main(){ GrhSIM_BehaviorDifftestBench m; m.init(); std::mt19937_64 rng(42); uint64_t hash=0;
auto start=std::chrono::steady_clock::now();
for(int cycle=0;cycle<10000;++cycle){
const bool flush=cycle%17==0, collision=cycle%3==0;
m.reset=cycle<4 || (cycle>=5000 && cycle<5004);
'''+body+'''
m.clock=false;m.eval();m.clock=true;m.eval();
if(cycle>=4){
'''
   for bank,rows in [('xrf',32),('frf',32),('vrf',64)]:
    for row in range(rows):code+=f'hash=(hash*UINT64_C(1099511628211)) ^ m.io_{bank}_value_{row};\n'
   for lane in range(4):
    code+=f'if(m.io_commitData_{lane}_valid)hash=(hash*UINT64_C(1099511628211))^m.io_commitData_{lane}_data;\n'
   code+='''}}
auto ns=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count();
printf("{\\"cycles\\":10000,\\"ns\\":%lld,\\"hash\\":%llu}\\n",(long long)ns,(unsigned long long)hash);
}'''
   (model/'bench.cpp').write_text(code)
   run([CXX,'-std=c++20','-O3','-march=native','-I'+str(model),model/'bench.cpp',
        model/'libgrhsim_BehaviorDifftestBench.a','-o',model/'bench'],dest/'bench-compile.log')
 if args.measure:
  from grhsim_single_baseline import cpu_counters,idle_percent,cpus,identity
  from grhsim_single_compare import summarize
  import time
  if not platform.node().startswith('node030'):raise ValueError('fixture timings require node030')
  if (out/'timings.json').exists():raise ValueError('timing records already exist; use a separate output')
  region=set(range(96,128)) | cpus(Path('/sys/devices/system/cpu/cpu96/topology/thread_siblings_list').read_text())
  a=cpu_counters(region);time.sleep(5);idle=idle_percent(a,cpu_counters(region))
  if min(idle.values())<98:raise RuntimeError('CPU96-127 busy; no fixture timing started')
  save(out/'timing-manifest.json',dict(binaries={v:identity(out/v/'model/bench') for v in 'AB'},
      host=platform.node(),cpu=96,numa_node=1,aslr='off',preflight_idle=idle,seed=42,cycles=10000))
  start=cpu_counters(region)
  records=[]
  for i in range(9):
   for variant in ('AB' if i%2==0 else 'BA'):
    r=subprocess.run(['taskset','-c','96','numactl','--membind=1','setarch','x86_64','-R',out/variant/'model/bench'],text=True,capture_output=True,check=True)
    (out/f'run-{i:02d}-{variant}.log').write_text(r.stdout+r.stderr)
    d=json.loads(r.stdout);d.update(pair=i,variant=variant,warmup=i==0);records.append(d)
    save(out/'timings.json',records)
  assert len({r['hash'] for r in records})==1,'hardware/behavior state hash mismatch'
  activity=idle_percent(start,cpu_counters(region))
  save(out/'during-idle.json',activity)
  if any(v<98 for c,v in activity.items() if c!=96):raise RuntimeError('CPU region became busy; raw timings retained')
  pairs=[{v:{'host_ms':next(r['ns']/1e6 for r in records if r['pair']==i and r['variant']==v)}
      for v in 'AB'} for i in range(1,9)]
  save(out/'summary.json',dict(**summarize(pairs),records=records,
      scope='10000 fixture cycles including stimulus and state hashing; raw GRH without full-SoC reg-to-mem'))
  with (out/'pairs.csv').open('w') as stream:
   writer=csv.writer(stream);writer.writerow(['pair','order','A_seconds','B_seconds','delta_percent'])
   for i,pair in enumerate(pairs):
    a,b=pair['A']['host_ms']/1000,pair['B']['host_ms']/1000
    writer.writerow([i,'BA' if i%2==0 else 'AB',a,b,100*(b/a-1)])

if __name__=='__main__': main()
