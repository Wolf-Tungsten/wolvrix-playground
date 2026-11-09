#!/usr/bin/env python3
"""Eight paired timings per real multiply family, including full model eval."""
import argparse
import csv
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from grhsim_single_baseline import cpu_counters, cpus, idle_percent, identity, save
from grhsim_single_compare import summarize
from grhsim_numa import runtime_plan
from multiply_behavior_study import KINDS, ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--kinds',nargs='+',choices=KINDS,default=list(KINDS))
    p.add_argument('--scenarios',nargs='+',choices=('active','sparse','idle'),default=['active','sparse','idle'])
    p.add_argument('--completed-from',type=Path,help='reuse completed scenarios after checking binary/vector identity')
    args=p.parse_args();study=args.study.resolve();out=args.output.resolve()
    if not platform.node().startswith('node030'):raise ValueError('node030 required')
    checks=json.loads((study/'check-summary.json').read_text())
    assert len(checks)==8 and all(r['pass'] and r['cycles']==30000 for r in checks)
    out.mkdir(parents=True,exist_ok=False)
    region=set(range(96,128))|cpus(Path('/sys/devices/system/cpu/cpu96/topology/thread_siblings_list').read_text())
    os.sched_setaffinity(0,cpus(Path('/sys/devices/system/cpu/online').read_text())-region)
    def idle_gate(label):
        records=[];windows=0
        while windows<3:
            before=cpu_counters(region);time.sleep(5);idle=idle_percent(before,cpu_counters(region))
            records.append(dict(time=time.time(),idle=idle));save(out/(label+'-preflight.json'),records)
            windows=windows+1 if min(idle.values())>=98 else 0
            if windows==0:print('waiting for CPU96-127 and sibling',flush=True)
    idle_gate('prepare')
    manifest=dict(cpu=96,node=1,aslr='off',cycles=10000,pairs=8,host=platform.node(),
                  driver=identity(__file__),checks=identity(study/'check-summary.json'),variants={})
    previous={}
    if args.completed_from:
        old=args.completed_from.resolve(); prior=json.loads((old/'manifest.json').read_text())
        assert prior['checks']==manifest['checks']
        for kind in args.kinds:
            assert identity(study/kind/'vectors.bin')==prior['vectors'][kind]
            for label in 'AB':
                assert identity(study/kind/label/'model/check')==prior['variants'][kind+':'+label]['binary']
        previous=json.loads((old/'summary.json').read_text())
        manifest['completed_from']=dict(path=str(old),manifest=identity(old/'manifest.json'),summary=identity(old/'summary.json'))
    prepared={}
    kinds = tuple(args.kinds)
    for kind in kinds:
        for label in 'AB':
            dest=out/kind/label;dest.mkdir(parents=True)
            binary=study/kind/label/'model/check'
            env=dict(os.environ);plan=runtime_plan(binary,None,None,dest/'runtime',96,1,env)
            save(dest/'runtime-plan.json',plan)
            result=subprocess.run(['taskset','-c','96','numactl','--membind=1',sys.executable,
                str(ROOT/'scripts/grhsim_numa.py'),str(dest/'runtime-plan.json')],text=True,capture_output=True)
            (dest/'prepare.log').write_text(result.stdout+result.stderr);result.check_returncode()
            runtime=dest/'runtime';env['LD_LIBRARY_PATH']=str(runtime/'lib')
            prepared[kind,label]=(runtime/'bin/emu',env)
            manifest['variants'][kind+':'+label]=dict(binary=identity(binary),runtime=identity(runtime/'bin/emu'))
        manifest.setdefault('vectors',{})[kind]=identity(study/kind/'vectors.bin')
    save(out/'manifest.json',manifest);summaries={};runs=[]
    for kind in kinds:
        summaries[kind]={}
        for scenario in args.scenarios:
            if scenario in previous.get(kind,{}):
                summaries[kind][scenario]=previous[kind][scenario]
                save(out/'summary.json',summaries)
                continue
            idle_gate(kind+'-'+scenario)
            def sample(label,pair):
                binary,env=prepared[kind,label]
                command=['taskset','-c','96','numactl','--membind=1','setarch',platform.machine(),'-R',
                         str(binary),str(study/kind/'vectors.bin'),scenario]
                start=time.monotonic();r=subprocess.run(command,env=env,text=True,capture_output=True,check=True)
                row=json.loads(r.stdout);row.update(kind=kind,scenario=scenario,variant=label,pair=pair,
                    external_s=time.monotonic()-start)
                (out/kind/label/f'{scenario}-{pair}.log').write_text(r.stdout+r.stderr)
                runs.append(row);save(out/'runs.json',runs);return row
            for label in 'AB':sample(label,-1)
            start=cpu_counters(region);pairs=[]
            for i in range(8):
                order='AB' if i%2==0 else 'BA';rows={label:sample(label,i) for label in order}
                assert rows['A']['hash']==rows['B']['hash']
                assert rows['A']['transactions']==rows['B']['transactions']
                pairs.append(dict(pair=i,order=list(order),**{label:dict(host_ms=row['ns']/1e6) for label,row in rows.items()}))
            idle=idle_percent(start,cpu_counters(region));busy={c:v for c,v in idle.items() if c!=96 and v<98}
            save(out/f'{kind}-{scenario}-during.json',dict(idle=idle,busy=busy))
            if busy:raise RuntimeError('region became busy; retain raw samples without a speed conclusion')
            summary=summarize(pairs);summaries[kind][scenario]=summary
            save(out/kind/(scenario+'-pairs.json'),pairs);save(out/'summary.json',summaries)
            with (out/kind/(scenario+'-pairs.csv')).open('w') as f:
                w=csv.writer(f);w.writerow(['pair','order','A_ms','B_ms','delta_percent'])
                for r in pairs:w.writerow([r['pair'],''.join(r['order']),r['A']['host_ms'],r['B']['host_ms'],100*(r['B']['host_ms']/r['A']['host_ms']-1)])
            print(kind,scenario,json.dumps(summary),flush=True)
    passed=[]
    for kind,metrics in summaries.items():
        required_active = [s for s in ('active','sparse') if s in metrics]
        active = bool(required_active) and all(
            metrics[s]['delta_percent_mean'] <= -5 and metrics[s]['delta_percent_ci95'][1] < 0
            for s in required_active)
        idle = 'idle' in metrics and metrics['idle']['delta_percent_ci95'][0] <= 0
        if active and idle:passed.append(kind)
    save(out/'gate.json',dict(eligible=passed,criteria='active/sparse mean <= -5%, upper CI < 0; idle lower CI <= 0',
         all_samples_retained=True,scope='10000 full eval cycles including input loads/output hash; file loading excluded'))
    for key,(binary,_) in prepared.items():
        assert identity(binary)==manifest['variants'][':'.join(key)]['runtime']
    print('ELIGIBLE',','.join(passed),flush=True)


if __name__=='__main__':main()
