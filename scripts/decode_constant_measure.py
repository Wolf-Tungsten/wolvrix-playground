#!/usr/bin/env python3
"""Frozen C/E research measurements; observer counters never rank ordinary runs."""
import argparse
import csv
import fcntl
import json
import os
from pathlib import Path
import platform
import resource
import signal
import subprocess
import threading
import time

from decode_table_csr_only import configuration
from grhsim_single_baseline import Baseline, ROOT, cpus, identity, save
from grhsim_single_compare import summarize, run_signature

EVENTS = {
    'core': 'cycles:u,instructions:u,branches:u,branch-misses:u',
    'cache': 'cycles:u,instructions:u,ic_tag_hit_miss.instruction_cache_miss:u,L1-dcache-load-misses:u',
    'tlb': 'cycles:u,instructions:u,dTLB-load-misses:u,iTLB-load-misses:u',
}


def parse_perf(path, interval=False):
    rows=[]
    for cells in csv.reader(path.read_text().splitlines()):
        if not cells or cells[0].startswith('#'):continue
        try:
            offset=1 if interval else 0
            value=float(cells[offset]);event=cells[offset+2]
            running=float(cells[offset+3]);percent=float(cells[offset+4])
        except (ValueError,IndexError):continue
        rows.append(dict(event=event,value=value,running_ns=running,running_percent=percent,
                         elapsed_s=float(cells[0]) if interval else None))
    return rows


class Observer:
    def __init__(self, directory, name, mode):
        self.prefix=directory/name;self.mode=mode;self.stop=threading.Event()
        self.processes=[];self.rows=[];self.errors=[];self.streams=[]

    def start(self,pid,start):
        self.pid=pid;self.started=start;self.attached=time.monotonic()-start
        commands=[('frequency',['perf','stat','-a','-C','96','-I','1000','-x',',','--no-big-num',
                               '-e','msr/aperf/,msr/mperf/','-o',str(self.prefix)+'.frequency.csv'])]
        if self.mode in EVENTS:
            commands.append(('pmu',['perf','stat','-p',str(pid),'-x',',','--no-big-num','--no-scale','-e',EVENTS[self.mode],
                                    '-o',str(self.prefix)+'.pmu.csv']))
        elif self.mode=='sample':
            commands.append(('sample',['perf','record','--no-buildid','-e','cycles:u','-F','499',
                                       '-p',str(pid),'-o',str(self.prefix)+'.perf.data']))
        self.commands=[]
        for label,command in commands:
            stream=open(str(self.prefix)+'.'+label+'.log','w');self.streams.append(stream)
            try:
                self.processes.append((label,subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT)))
                self.commands.append(dict(label=label,command=command,launch_s=time.monotonic()-start))
            except OSError as error:self.errors.append(str(error))
        self.thread=threading.Thread(target=self.observe);self.thread.start()

    def observe(self):
        while not self.stop.is_set():
            row=dict(time_s=time.monotonic()-self.started,unix_time=time.time(),loadavg=Path('/proc/loadavg').read_text().strip())
            for label,path in [('frequency_khz','/sys/devices/system/cpu/cpu96/cpufreq/scaling_cur_freq'),
                               ('cpu_pressure','/proc/pressure/cpu')]:
                try:row[label]=Path(path).read_text().strip()
                except OSError as error:row[label]=str(error)
            self.rows.append(row);self.stop.wait(1)

    def finish(self):
        self.stop.set();self.thread.join()
        codes={}
        for label,proc in self.processes:
            if proc.poll() is None:proc.send_signal(signal.SIGINT)
            try:codes[label]=proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill();codes[label]=proc.wait();self.errors.append(label+' observer stop timeout')
        for stream in self.streams:stream.close()
        self.result=dict(pid=self.pid,attach_delay_s=self.attached,commands=self.commands,
            exit_codes=codes,errors=self.errors,system=self.rows,
            scope='MSR counters are CPU96-wide; PMU/IP attach excludes launch latency and measures whole process, including initialization and NEMU')
        for name,interval in [('frequency',True),('pmu',False)]:
            p=Path(str(self.prefix)+'.'+name+'.csv')
            if p.exists():self.result[name]=parse_perf(p,interval)
        save(str(self.prefix)+'.observation.json',self.result)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mode',choices=['walltime',*EVENTS,'sample'],default='walltime')
    p.add_argument('--pairs',type=int)
    p.add_argument('--baseline',type=Path,default=ROOT/'build/xs/decode_table_tuned_20261103_v1/C')
    p.add_argument('--candidate',type=Path,default=ROOT/'build/xs/decode_table_csr_only_20261104_v1/E')
    args=p.parse_args()
    if not platform.node().startswith('node030'):raise ValueError('measurement requires node030')
    args.pairs=args.pairs or (8 if args.mode=='walltime' else 4)
    os.sched_setaffinity(0,cpus(Path('/sys/devices/system/cpu/online').read_text()))
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    lock=open('/tmp/wolvrix-cpu96-measure.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    builds=dict(C=args.baseline.resolve(),E=args.candidate.resolve())
    manifest=dict(mode=args.mode,pairs=args.pairs,cpu=96,numa_node=1,cycles=100000,builds={},
                  driver=identity(__file__),runner=identity(ROOT/'scripts/grhsim_single_baseline.py'))
    for name,root in builds.items():
        binary=root/'emu/grhsim-compile/emu';frozen=json.loads((root/'binary.json').read_text())
        if identity(binary)!=frozen:raise ValueError('frozen binary changed')
        manifest['builds'][name]=frozen
    # These exact frozen binaries already passed both 100k-cycle effective traces.
    verification=ROOT/'build/xs/decode_table_csr_only_20261104_v1/comparison'
    prior=json.loads((verification/'manifest.json').read_text())
    manifest['trace_checks']=[]
    for name in builds:
        if prior['variants'][name]!=manifest['builds'][name]:raise ValueError('trace binary identity differs')
        settings=json.loads((builds[name]/'configuration.json').read_text())
        for key in ('image','nemu'):
            if identity(settings[key]['path'])!=settings[key]:raise ValueError('input changed')
    for seed in (0,1):
        path=verification/f'trace-C-E-s{seed}.json';check=json.loads(path.read_text())
        if not check['pass_'] or check['records']!=100000:raise ValueError('prior effective trace gate failed')
        manifest['trace_checks'].append(identity(path))
    save(out/'manifest.json',manifest)
    (out/'driver-frozen').mkdir()
    for driver in (__file__,ROOT/'scripts/grhsim_single_baseline.py'):
        target=out/'driver-frozen'/Path(driver).name;target.write_bytes(Path(driver).read_bytes())
    runners={};prepared={}
    for name,root in builds.items():
        runners[name]=Baseline(configuration(out/name,binary=root/'emu/grhsim-compile/emu'))
        prepared[name]=runners[name].prepare_measurement()
        previous=json.loads((verification/name/'runs/runtime_plan.json').read_text())
        files=lambda plan:sorted((x['role'],json.dumps(x['source'],sort_keys=True)) for x in plan['files'])
        if files(prepared[name]['plan'])!=files(previous):raise ValueError('prior trace runtime files changed')
    def run(name,label,cycles=100000):
        observer=Observer(prepared[name]['directory'],label,args.mode)
        row=runners[name].run_sample(prepared[name],label,cycles,process_observer=observer)
        observation=observer.result
        if (observation['errors'] or {x['event'] for x in observation.get('frequency',[])} != {'msr/aperf/','msr/mperf/'}):
            raise ValueError('frequency observer unavailable; raw sample retained')
        if args.mode in EVENTS and (len(observation.get('pmu',[]))!=4 or any(x['running_percent']<99 for x in observation['pmu'])):
            raise ValueError('PMU missing or multiplexed below 99%; raw sample retained')
        if args.mode=='sample':
            sample_path=Path(str(observer.prefix)+'.perf.data')
            with Path(str(observer.prefix)+'.samples.txt').open('w') as stream:
                subprocess.run(['perf','script','-i',str(sample_path),'--no-demangle','-F','ip,sym,dso,period'],
                               stdout=stream,stderr=subprocess.PIPE,check=True)
            if Path(str(observer.prefix)+'.samples.txt').stat().st_size==0:raise ValueError('empty IP sampling')
        row['observation']=str(observer.prefix)+'.observation.json'
        row['diagnostic']=args.mode!='walltime'
        save(prepared[name]['directory']/(label+'.json'),row)
        return row
    for name in builds:run(name,'smoke',10000)
    for name in builds:run(name,'warmup')
    pairs=[];signature=None
    for index in range(args.pairs):
        order=['C','E'] if index%2==0 else ['E','C'];pair=dict(pair=index,order=order)
        for name in order:
            pair[name]=run(name,f'pair{index:02d}')
            current=run_signature(pair[name])
            if signature is None:signature=current
            if signature!=current:raise ValueError('functional signature differs')
        pairs.append(pair);save(out/'pairs.json',pairs)
    summary=dict(mode=args.mode,samples=pairs,functional_signature=signature)
    if args.mode=='walltime':summary['E_vs_C']=summarize([dict(A=r['C'],B=r['E']) for r in pairs])
    save(out/'summary.json',summary)
    with (out/'pairs.csv').open('w') as f:
        w=csv.writer(f);w.writerow(['pair','order','C_s','E_s','E_vs_C_percent'])
        for r in pairs:w.writerow([r['pair'],''.join(r['order']),r['C']['host_ms']/1000,r['E']['host_ms']/1000,100*(r['E']['host_ms']/r['C']['host_ms']-1)])
    print(json.dumps(summary.get('E_vs_C',dict(mode=args.mode,pairs=len(pairs)))),flush=True)


if __name__=='__main__':main()
