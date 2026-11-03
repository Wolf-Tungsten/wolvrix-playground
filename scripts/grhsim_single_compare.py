#!/usr/bin/env python3
"""Paired native GrhSIM emu runs with shared NUMA/affinity verification."""
import argparse
import csv
import json
import os
from pathlib import Path
import platform
import random
import resource
import statistics
from grhsim_single_baseline import Baseline, ROOT, XS, cpus, identity, save
from grhsim_difftrace import build_comparator, compare_traces

def resolve_binary(path):
    """Accept either a frozen emu or its Baseline output directory."""
    path=Path(path).resolve()
    candidate=path/'emu/grhsim-compile/emu' if path.is_dir() else path
    if not candidate.is_file():
        raise ValueError(f'not a native GrhSIM binary or output directory: {path}')
    return candidate


def pair_order(pairs):
    return [('A','B') if i%2==0 else ('B','A') for i in range(pairs)]


def summarize(pairs):
    deltas=[100*(r['B']['host_ms']/r['A']['host_ms']-1) for r in pairs]
    rng=random.Random(20261102)
    boot=sorted(statistics.mean(rng.choices(deltas,k=len(deltas))) for _ in range(10000))
    return dict(pairs=len(pairs),delta_percent_mean=statistics.mean(deltas),
        delta_percent_median=statistics.median(deltas),delta_percent_ci95=[boot[249],boot[9749]],
        candidate_faster_pairs=sum(d<0 for d in deltas),
        baseline_s_mean=statistics.mean(r['A']['host_ms']/1000 for r in pairs),
        candidate_s_mean=statistics.mean(r['B']['host_ms']/1000 for r in pairs),
        note='Negative means candidate faster; CI is a fixed-seed paired bootstrap, not proof of causality')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--historical',type=Path)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--pairs',type=int,default=8)
    p.add_argument('--cycles',type=int,default=100000)
    p.add_argument('--candidate-sim-primitives', choices=['none','priority-encode','popcount','popcount-ge4'], default='priority-encode')
    p.add_argument('--image',type=Path,default=XS/'ready-to-run/coremark-2-iteration.bin')
    p.add_argument('--nemu',type=Path,default=XS/'ready-to-run/riscv64-nemu-interpreter-so')
    p.add_argument('--baseline-header',type=Path);p.add_argument('--candidate-header',type=Path)
    args=p.parse_args()
    if not platform.node().startswith('node030'):raise ValueError('measurements require node030')
    if args.pairs<8 or args.cycles<100000:raise ValueError('requires >=8 pairs and >=100000 cycles')
    os.sched_setaffinity(0,cpus(Path('/sys/devices/system/cpu/online').read_text()))
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    names=dict(A=resolve_binary(args.baseline),B=resolve_binary(args.candidate))
    if args.historical:names['H']=resolve_binary(args.historical)
    aroot=Path(args.baseline).resolve() if Path(args.baseline).is_dir() else names['A'].parents[2]
    broot=Path(args.candidate).resolve() if Path(args.candidate).is_dir() else names['B'].parents[2]
    headers=[args.baseline_header or aroot/'chisel-home/build/generated-src/difftest-state.h',
             args.candidate_header or broot/'chisel-home/build/generated-src/difftest-state.h']
    if identity(headers[0])['sha256']!=identity(headers[1])['sha256']:raise ValueError('Difftest schemas differ')
    comparator=build_comparator(headers[0],out/'trace-comparator')
    save(out/'manifest.json',dict(binaries={k:identity(v) for k,v in names.items()},image=identity(args.image),
        nemu=identity(args.nemu),headers=[identity(x) for x in headers],pairs=args.pairs,cycles=args.cycles,
        driver=identity(__file__),runner=identity(ROOT/'scripts/grhsim_single_baseline.py'),
        numa=identity(ROOT/'scripts/grhsim_numa.py'),order=pair_order(args.pairs),cpu=96))
    runners={};prepared={}
    for name,binary in names.items():
        config=argparse.Namespace(output=out/name,binary=binary,image=args.image,nemu=args.nemu,
            compiler='/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++',tools_dir=None,
            sim_primitives='none' if name!='B' else args.candidate_sim_primitives,
            cpu=96,jobs=1,cycles=args.cycles,repeats=args.pairs)
        runners[name]=Baseline(config);prepared[name]=runners[name].prepare_measurement()
    def run(name,label,cycles=None,seed=0,extra=()):
        return runners[name].run_sample(prepared[name],label,cycles or args.cycles,seed,extra)
    for name in names:run(name,'smoke',10000)
    trace_checks=[]
    for seed in [0,1]:
        for name in ['A','B']:
            # Difftest currently has a fixed 32-byte trace-name buffer. A short
            # relative name also keeps its fixed filename buffer in bounds.
            run(name,f'verify-s{seed}',seed=seed,extra=['--dump-difftrace',f'./trace_s{seed}'])
        paths=[prepared[n]['binary'].parent/f'trace_s{seed}' for n in ['A','B']]
        trace_checks.append(compare_traces(comparator,*paths,out/f'trace-s{seed}.json'))
    for name in names:run(name,'warmup')
    anchors=[]
    if 'H' in names:anchors.append(run('H','anchor-before'))
    results=[];signature=None
    for i,order in enumerate(pair_order(args.pairs)):
        pair=dict(pair=i,order=order)
        for name in order:
            row=run(name,f'pair{i:02d}')
            current={k:row[k] for k in ['pc','instr_count','cycle_count','guest_cycles']}
            if signature is None:signature=current
            if current!=signature:raise ValueError('functional signatures differ across A/B')
            pair[name]=row
        results.append(pair);save(out/'pairs.json',results)
    if 'H' in names:anchors.append(run('H','anchor-after'))
    if 'H' in names and signature is not None:
        expected={k:signature[k] for k in ('pc','instr_count','cycle_count','guest_cycles')}
        for anchor in anchors:
            observed={k:anchor[k] for k in expected}
            if observed!=expected:
                raise ValueError(f'historical anchor functional signature differs: {observed} != {expected}')
    save(out/'summary.json',dict(**summarize(results),samples=results,historical=anchors,
        trace_checks=trace_checks,functional_signature=signature,scope='Native full SimTop; Host time includes harness'))
    with (out/'pairs.csv').open('w') as f:
        w=csv.writer(f);w.writerow(['pair','order','A_host_s','B_host_s','delta_percent','A_external_s','B_external_s'])
        for r in results:w.writerow([r['pair'],''.join(r['order']),r['A']['host_ms']/1000,r['B']['host_ms']/1000,
            100*(r['B']['host_ms']/r['A']['host_ms']-1),r['A']['external_wall_s'],r['B']['external_wall_s']])
    print(json.dumps(summarize(results)),flush=True)

if __name__=='__main__':main()
