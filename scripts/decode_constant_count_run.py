#!/usr/bin/env python3
"""Build isolated counters or verify repeated deterministic native trajectories."""
import argparse
import csv
import json
import os
from pathlib import Path
import platform
import resource
from collections import Counter

from decode_table_csr_only import configuration
from grhsim_single_baseline import Baseline, ROOT, cpus, identity, save
from grhsim_single_compare import run_signature
from grhsim_difftrace import build_comparator, compare_traces


def read_counts(path):
    result={};total=Counter()
    with path.open() as f:
        for row in csv.DictReader(f,delimiter='\t'):
            key=(row['kind'],int(row['id']))
            values={k:int(v) for k,v in row.items() if k not in ('kind','id')}
            if key in result:raise ValueError('duplicate counter row')
            result[key]=values
            if key[0]=='group':total.update(values)
    return result,dict(total)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['build','run'])
    p.add_argument('--root',type=Path,required=True);p.add_argument('--jobs',type=int,default=32)
    args=p.parse_args();root=args.root.resolve()
    if not platform.node().startswith('node030'):raise ValueError('use node030')
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    os.sched_setaffinity(0,cpus(Path('/sys/devices/system/cpu/online').read_text()))
    if args.command=='build':
        for n in ('C','E'):
            out=root/f'counts-{n}';runner=Baseline(configuration(out,jobs=args.jobs));runner.snapshot()
            cfg=json.loads((out/'configuration.json').read_text());cfg['diagnostic_instrumentation']=True;save(out/'configuration.json',cfg)
            runner.compile()
        return
    output=root/'count-runs';output.mkdir(exist_ok=False)
    runners={};prepared={}
    for n in ('C','E'):
        binary=root/f'counts-{n}/emu/grhsim-compile/emu'
        if identity(binary)!=json.loads((root/f'counts-{n}/binary.json').read_text()):raise ValueError('counter binary changed')
        runners[n]=Baseline(configuration(output/n,binary=binary));prepared[n]=runners[n].prepare_measurement()
    header=root/'counts-E/chisel-home/build/generated-src/difftest-state.h'
    comparator=build_comparator(header,output/'comparator')
    original=ROOT/'build/xs/decode_table_csr_only_20261104_v1/comparison'
    checks=[];samples=[];signature={};counts_by_name={}
    for label,seed,dump in [('seed0',0,True),('seed1',1,True),('repeat0',0,False)]:
        for n in ('C','E'):
            counts_path=prepared[n]['binary'].parent/(label+'.counts.tsv')
            prepared[n]['runtime']['WOLVRIX_CONSTANT_COUNTS']=str(counts_path)
            extra=['--dump-difftrace','./trace_s'+str(seed)] if dump else []
            row=runners[n].run_sample(prepared[n],label,100000,seed,extra)
            row['diagnostic']=True;row['counts']=identity(counts_path);row['variant']=n
            save(prepared[n]['directory']/(label+'.json'),row)
            sig=run_signature(row)
            if seed in signature and signature[seed]!=sig:raise ValueError('counter functional signature differs')
            signature[seed]=sig
            parsed,totals=read_counts(counts_path);row['counter_totals']=totals
            counts_by_name[(n,label)]=parsed;samples.append(row)
            if dump:
                old=original/n/'runs/runtime/bin'/('trace_s'+str(seed))
                if n=='C':old=ROOT/'build/xs/decode_table_tuned_20261103_v1/comparison/C/runs/runtime/bin'/('trace_s'+str(seed))
                new=prepared[n]['binary'].parent/('trace_s'+str(seed))
                checks.append(dict(variant=n,seed=seed,**compare_traces(comparator,old,new,output/f'trace-{n}-s{seed}.json')))
            save(output/'progress.json',dict(samples=samples,checks=checks))
    for n in ('C','E'):
        if counts_by_name[(n,'seed0')]!=counts_by_name[(n,'repeat0')]:raise ValueError('identical window counters are not stable')
    save(output/'summary.json',dict(samples=samples,checks=checks,repeated_counts_identical=True,
        note='Diagnostic walltime excluded. Each full trajectory includes initial/reset evaluations; equal seeds compared by every raw counter.'))

if __name__=='__main__':main()
