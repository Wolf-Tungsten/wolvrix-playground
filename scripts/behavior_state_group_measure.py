#!/usr/bin/env python3
"""Paired local H/O/G timings after functional checks and all builds finish."""
import argparse,csv,json,os,platform,subprocess,sys,time
from pathlib import Path
from grhsim_single_baseline import cpu_counters,cpus,idle_percent,identity,save
from grhsim_single_compare import summarize
from grhsim_numa import runtime_plan
ROOT=Path(__file__).resolve().parents[1]

def main():
 p=argparse.ArgumentParser();p.add_argument('--fixture',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--rat',action='store_true');a=p.parse_args()
 if not platform.node().startswith('node030'):raise ValueError('timings require node030')
 fixture=a.fixture.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 checks=json.loads((fixture/'check-summary.json').read_text())
 if len(checks)!=9 or not all(x['pass_'] for x in checks):raise ValueError('functional checks incomplete')
 region=set(range(96,128))|cpus(Path('/sys/devices/system/cpu/cpu96/topology/thread_siblings_list').read_text())
 os.sched_setaffinity(0,cpus(Path('/sys/devices/system/cpu/online').read_text())-region)
 scenarios=['sparse','dense','idle'] if a.rat else ['active','idle']
 def idle_gate(label):
  records=[];successive=0
  for attempt in range(24):
   before=cpu_counters(region);time.sleep(5);idle=idle_percent(before,cpu_counters(region))
   records.append(dict(time=time.time(),idle=idle));save(out/(label+'-preflight.json'),records)
   successive=successive+1 if min(idle.values())>=98 else 0
   if successive>=3:return
   print('[region-wait]',label,'window',attempt+1,flush=True)
  raise RuntimeError('CPU96-127 not continuously idle; no dependent timings started')
 # Each private executable/library copy is faulted on CPU96/NUMA1 before timing.
 prepared={};manifest=dict(host=platform.node(),cpu=96,node=1,aslr='off',cycles=10000,seed=42,
     scopes=scenarios,pairs=8,driver=identity(__file__),checks=identity(fixture/'check-summary.json'),variants={})
 idle_gate('prepare')
 for v in 'HOG':
  (out/v).mkdir()
  binary=fixture/v/'model/check';env=dict(os.environ)
  plan=runtime_plan(binary,None,None,out/v/'runtime',96,1,env);save(out/(v+'-runtime-plan.json'),plan)
  result=subprocess.run(['taskset','-c','96','numactl','--membind=1',sys.executable,ROOT/'scripts/grhsim_numa.py',out/(v+'-runtime-plan.json')],text=True,capture_output=True)
  (out/(v+'-prepare.log')).write_text(result.stdout+result.stderr)
  result.check_returncode()
  runtime=out/v/'runtime';env['LD_LIBRARY_PATH']=str(runtime/'lib')
  frozen=identity(runtime/'bin/emu');manifest['variants'][v]=dict(original=identity(binary),frozen=frozen,runtime=json.loads((runtime/'manifest.json').read_text()))
  prepared[v]=(runtime/'bin/emu',env)
 save(out/'manifest.json',manifest);all_rows=[];summaries={}
 for scenario in scenarios:
  idle_gate(scenario)
  def run(v,pair):
   binary,env=prepared[v];cmd=['taskset','-c','96','numactl','--membind=1','setarch',platform.machine(),'-R',binary,'--bench','42',scenario]
   start=time.monotonic();result=subprocess.run([str(x) for x in cmd],text=True,capture_output=True,env=env,check=True)
   row=json.loads(result.stdout);row.update(variant=v,scenario=scenario,pair=pair,warmup=pair<0,external_s=time.monotonic()-start)
   (out/f'{scenario}-{pair}-{v}.log').write_text(result.stdout+result.stderr)
   all_rows.append(row);save(out/'runs.json',all_rows);return row
  for v in 'HOG':run(v,-1)
  before=cpu_counters(region)
  for pair in range(8):
   for v in ('HOG' if pair%2==0 else 'GOH'):run(v,pair)
   print('[paired]',scenario,pair,flush=True)
  idle=idle_percent(before,cpu_counters(region));bad={c:v for c,v in idle.items() if c!=96 and v<98}
  save(out/(scenario+'-during.json'),dict(idle=idle,busy=bad))
  if bad:raise RuntimeError('region became busy; raw records retained and no performance conclusion: '+str(bad))
  rows=[r for r in all_rows if r['scenario']==scenario]
  if len({r['hash'] for r in rows})!=1:raise ValueError('H/O/G output hash mismatch')
  comparisons={}
  for baseline,candidate in [('O','G'),('H','G'),('H','O')]:
   pairs=[{label:dict(host_ms=next(r['ns']/1e6 for r in rows if r['pair']==i and r['variant']==v)) for label,v in [('A',baseline),('B',candidate)]} for i in range(8)]
   comparisons[candidate+'_vs_'+baseline]=summarize(pairs)
  summaries[scenario]=comparisons;save(out/'summary.json',summaries)
  with (out/(scenario+'-pairs.csv')).open('w') as f:
   w=csv.writer(f);w.writerow(['pair','order','H_ns','O_ns','G_ns','G_vs_O_percent','G_vs_H_percent'])
   for pair in range(8):
    values={v:next(r['ns'] for r in rows if r['pair']==pair and r['variant']==v) for v in 'HOG'}
    w.writerow([pair,'HOG' if pair%2==0 else 'GOH',*[values[v] for v in 'HOG'],100*(values['G']/values['O']-1),100*(values['G']/values['H']-1)])
 for v in 'HOG':
  if identity(prepared[v][0])!=manifest['variants'][v]['frozen']:raise ValueError('runtime binary changed')
 save(out/'complete.json',dict(pass_=True,scope='10000 local cycles including input generation and output hashing; no SoC timing'))
 print(json.dumps(summaries),flush=True)
if __name__=='__main__':main()
