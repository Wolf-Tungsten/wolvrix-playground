#!/usr/bin/env python3
"""Rebuild decode lowering from frozen RTL and compare hardware/old/new models."""
import argparse
import csv
import fcntl
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import subprocess
import sys

from grhsim_single_baseline import Baseline, ROOT, XS, cpus, identity, save
from grhsim_single_compare import pair_order, run_signature, summarize
from grhsim_difftrace import build_comparator, compare_traces

CXX='/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++'


def configuration(output, tools=None, binary=None, mode='decode-table', jobs=32,
                  constant_decode_fold=None):
    return argparse.Namespace(output=output,tools_dir=tools,compiler=CXX,jobs=jobs,cpu=96,
        cycles=100000,repeats=8,sim_primitives=mode,rtl_difftest='on',model_difftest='on',
        compile_difftest='on',runtime_difftest='on',binary=binary,
        constant_decode_fold=constant_decode_fold,
        image=XS/'ready-to-run/coremark-2-iteration.bin',nemu=XS/'ready-to-run/riscv64-nemu-interpreter-so')


def build(source, out, tools, jobs):
    out.mkdir(parents=True,exist_ok=False)
    # There is no Chisel change in this follow-up. Verify the existing RTL,
    # frontend source tree and harness before reusing the recorded generation.
    records=json.loads((source/'B/sources.json').read_text())
    for record in records:
        if '/testcase/xiangshan/' in record['path'] and identity(record['path'])!=record:
            raise ValueError('XiangShan/harness source changed: '+record['path'])
    for name in ('rtl_manifest.json','difftest_generated_manifest.json'):
        for record in json.loads((source/'B'/name).read_text()):
            if identity(record['path'])!=record:raise ValueError('frozen input changed: '+record['path'])
    frozen=out/'tools-frozen';shutil.copytree(tools/'python',frozen/'python')
    shutil.copy2(tools/'wolvrix/libwolvrix-lib.so',frozen/'libwolvrix-lib.so')
    save(frozen/'identity.json',[identity(p) for p in sorted(frozen.rglob('*')) if p.is_file()])
    runner=Baseline(configuration(out/'C',frozen,jobs=jobs,constant_decode_fold=True));runner.snapshot()
    (out/'C/rtl').symlink_to(source/'B/rtl',target_is_directory=True)
    (out/'C/chisel-home').mkdir()
    (out/'C/chisel-home/build').symlink_to(source/'B/chisel-home/build',target_is_directory=True)
    save(out/'experiment.json',dict(source=str(source),mode='backend-only-from-verified-frozen-RTL',
        tools=identity(frozen/'identity.json'),new_sources=identity(out/'C/sources.json'),
        rtl_manifest=identity(source/'B/rtl_manifest.json'),driver=identity(__file__),
        variants=dict(A='hardware none',B='previous decode-table',C='constant fold + Boolean bitset scalar barrier')))
    runner.emit();runner.compile();runner.stage('tuned model build complete')


def measure(source, out):
    directory=out/'comparison';directory.mkdir(exist_ok=False)
    builds=dict(A=source/'A',B=source/'B',C=out/'C')
    for root in builds.values():
        if identity(root/'emu/grhsim-compile/emu')!=json.loads((root/'binary.json').read_text()):
            raise ValueError('frozen binary identity changed')
    headers={n:p/'chisel-home/build/generated-src/difftest-state.h' for n,p in builds.items()}
    if len({identity(p)['sha256'] for p in headers.values()})!=1:
        raise ValueError('DiffTest schema differs')
    comparator=build_comparator(headers['C'],directory/'trace-comparator')
    orders=[['A','B','C'],['C','B','A'],['B','A','C'],['C','A','B'],
            ['A','C','B'],['B','C','A'],['A','B','C'],['C','B','A']]
    runners={};prepared={}
    for name,root in builds.items():
        runners[name]=Baseline(configuration(directory/name,binary=root/'emu/grhsim-compile/emu',
            mode='none' if name=='A' else 'decode-table'))
        prepared[name]=runners[name].prepare_measurement()
    prior=json.loads((source/'comparison-v1/manifest.json').read_text())
    for name in ('A','B'):
        if identity(builds[name]/'emu/grhsim-compile/emu')!=prior['binaries'][name]:
            raise ValueError('prior trace binary changed')
    for name in builds:
        config=json.loads((builds[name]/'configuration.json').read_text())
        for key in ('image','nemu'):
            if config[key]!=prior[key] or identity(config[key]['path'])!=prior[key]:
                raise ValueError('prior trace workload/reference changed')
        previous=json.loads((source/'comparison-v1/A/runs/runtime_plan.json').read_text())
        libraries=lambda p:{x['source']['path']:x['source'] for x in p['files'] if x['role']=='library'}
        if libraries(prepared[name]['plan'])!=libraries(previous):
            raise ValueError('runtime libraries changed since trace verification')
    save(directory/'manifest.json',dict(variants={n:identity(p/'emu/grhsim-compile/emu') for n,p in builds.items()},
        orders=orders,cpu=96,cycles=100000,pairs=8,driver=identity(__file__),
        runner=identity(ROOT/'scripts/grhsim_single_baseline.py'),prior_trace_source=str(source/'comparison-v1'),
        note='A=hardware, B=previous intrinsic, C=tuned intrinsic; same RTL/harness and production flags'))
    def run(n,label,cycles=100000,seed=0,extra=()):
        return runners[n].run_sample(prepared[n],label,cycles,seed,extra)
    for name in builds:run(name,'smoke',10000)
    checks=[]
    for seed in (0,1):
        check=json.loads((source/f'comparison-v1/trace-s{seed}.json').read_text())
        if not check['pass_'] or check['records']!=100000:raise ValueError('previous trace gate incomplete')
        run('C',f'verify-s{seed}',seed=seed,extra=['--dump-difftrace',f'./trace_s{seed}'])
        for name in ('A','B'):
            old=source/f'comparison-v1/{name}/runs/runtime/bin'/f'trace_s{seed}'
            new=prepared['C']['binary'].parent/f'trace_s{seed}'
            checks.append(dict(baseline=name,seed=seed,**compare_traces(comparator,old,new,directory/f'trace-{name}-C-s{seed}.json')))
    for name in builds:run(name,'warmup')
    rows=[];signature=None
    for index,order in enumerate(orders):
        row=dict(pair=index,order=order)
        for name in order:
            sample=run(name,f'pair{index:02d}')
            current=run_signature(sample)
            if signature is None:signature=current
            if current!=signature:raise ValueError('functional signature changed')
            row[name]=sample
        rows.append(row);save(directory/'triads.json',rows)
    pairwise={}
    for a,b in [('A','B'),('A','C'),('B','C')]:
        pairs=[dict(A=r[a],B=r[b]) for r in rows]
        pairwise[b+'_vs_'+a]=dict(baseline=a,candidate=b,**summarize(pairs))
    save(directory/'summary.json',dict(pairwise=pairwise,samples=rows,trace_checks=checks,
        functional_signature=signature,cpu=96,cycles=100000))
    with (directory/'triads.csv').open('w') as f:
        w=csv.writer(f);w.writerow(['pair','order','A_s','B_s','C_s','B_vs_A_percent','C_vs_A_percent','C_vs_B_percent'])
        for r in rows:
            w.writerow([r['pair'],''.join(r['order']),*[r[n]['host_ms']/1000 for n in 'ABC'],
                *[100*(r[b]['host_ms']/r[a]['host_ms']-1) for a,b in [('A','B'),('A','C'),('B','C')]]])
    print(json.dumps(pairwise),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['build','measure']);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--jobs',type=int,default=32)
    p.add_argument('--tools',type=Path,default=ROOT/'build/grhsim32-tools')
    args=p.parse_args();out=args.output.resolve();source=args.source.resolve()
    if not platform.node().startswith('node030'):raise ValueError('run on node030')
    os.sched_setaffinity(0,cpus(Path('/sys/devices/system/cpu/online').read_text()))
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    if args.command=='build':build(source,out,args.tools.resolve(),args.jobs)
    else:
        with (out/'measure.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);measure(source,out)


if __name__=='__main__':main()
