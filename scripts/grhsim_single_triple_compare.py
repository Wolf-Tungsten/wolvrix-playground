#!/usr/bin/env python3
"""Paired three-way native GrhSIM comparison for A/A'/B DiffTest modes."""
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


def resolve_binary(path):
    path=Path(path).resolve()
    candidate=path/'emu/grhsim-compile/emu' if path.is_dir() else path
    if not candidate.is_file():
        raise ValueError(f'not a native GrhSIM binary or output directory: {path}')
    return candidate


def bootstrap(deltas, seed):
    rng=random.Random(seed)
    samples=sorted(statistics.mean(rng.choices(deltas,k=len(deltas))) for _ in range(10000))
    return [samples[249],samples[9749]]


def pair_summary(rows, baseline, candidate, seed):
    deltas=[100*(row[candidate]['host_ms']/row[baseline]['host_ms']-1) for row in rows]
    return dict(baseline=baseline,candidate=candidate,pairs=len(rows),
        delta_percent_mean=statistics.mean(deltas),delta_percent_median=statistics.median(deltas),
        delta_percent_ci95=bootstrap(deltas,seed),candidate_faster_pairs=sum(x<0 for x in deltas),
        baseline_s_mean=statistics.mean(row[baseline]['host_ms']/1000 for row in rows),
        baseline_s_median=statistics.median(row[baseline]['host_ms']/1000 for row in rows),
        candidate_s_mean=statistics.mean(row[candidate]['host_ms']/1000 for row in rows),
        candidate_s_median=statistics.median(row[candidate]['host_ms']/1000 for row in rows),
        deltas=deltas)


def footprint_check(rows, paths):
    records=[identity(path) for path in paths]
    if any(record['bytes']==0 or record['bytes']%8 for record in records):
        raise ValueError('empty or malformed memory footprints')
    if len({record['sha256'] for record in records})!=1:
        raise ValueError('memory footprints differ across variants')
    outputs={row['workload_output'] for row in rows}
    cycles={row['guest_cycles'] for row in rows}
    if len(outputs)!=1 or not next(iter(outputs)).strip() or len(cycles)!=1:
        raise ValueError('workload output or guest cycles differ across variants')
    return dict(status='pass',footprints=records,workload_output=next(iter(outputs)),
                guest_cycles=next(iter(cycles)),diagnostic_ram_size_bytes=1024**3,
                scope='First-access memory values and workload/UART output; not architectural equivalence')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--a',type=Path,required=True)
    parser.add_argument('--aprime',type=Path,required=True)
    parser.add_argument('--b',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--pairs',type=int,default=8)
    parser.add_argument('--cycles',type=int,default=100000)
    parser.add_argument('--image',type=Path,default=XS/'ready-to-run/coremark-2-iteration.bin')
    parser.add_argument('--nemu',type=Path,default=XS/'ready-to-run/riscv64-nemu-interpreter-so')
    args=parser.parse_args()
    if not platform.node().startswith('node030'):raise ValueError('measurements require node030')
    if args.pairs<8 or args.cycles<100000:raise ValueError('requires >=8 pairs and >=100000 cycles')
    os.sched_setaffinity(0,cpus(Path('/sys/devices/system/cpu/online').read_text()))
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    paths=dict(A=resolve_binary(args.a),Aprime=resolve_binary(args.aprime),B=resolve_binary(args.b))
    variants={};configs={}
    for name,binary in paths.items():
        root=binary.parents[2]
        config=json.loads((root/'configuration.json').read_text()) if (root/'configuration.json').is_file() else {}
        configs[name]=config
        runtime=config.get('runtime_difftest','on')
        variants[name]=dict(binary=binary,rtl_difftest=config.get('rtl_difftest','on'),
            model_difftest=config.get('model_difftest',runtime),
            compile_difftest=config.get('compile_difftest',config.get('model_difftest',runtime)),
            runtime_difftest=runtime)
    save(out/'manifest.json',dict(variants={name:dict(binary=identity(v['binary']),
        rtl_difftest=v['rtl_difftest'],model_difftest=v['model_difftest'],
        compile_difftest=v['compile_difftest'],runtime_difftest=v['runtime_difftest'])
        for name,v in variants.items()},image=identity(args.image),nemu=identity(args.nemu),
        pairs=args.pairs,cycles=args.cycles,cpu=96,driver=identity(__file__),
        runner=identity(ROOT/'scripts/grhsim_single_baseline.py'),numa=identity(ROOT/'scripts/grhsim_numa.py')))
    runners={};prepared={}
    for name,v in variants.items():
        config=argparse.Namespace(output=out/name,binary=v['binary'],image=args.image,nemu=args.nemu,
            compiler='/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++',tools_dir=None,
            sim_primitives='none',rtl_difftest=v['rtl_difftest'],model_difftest=v['model_difftest'],
            compile_difftest=v['compile_difftest'],runtime_difftest=v['runtime_difftest'],
            cpu=96,jobs=1,cycles=args.cycles,repeats=args.pairs)
        runners[name]=Baseline(config);prepared[name]=runners[name].prepare_measurement()
    def run(name,label,cycles=None,extra=()):
        return runners[name].run_sample(prepared[name],label,cycles or args.cycles,0,extra)
    for name in variants:run(name,'smoke',10000)
    diagnostic=[]
    for name in variants:
        diagnostic.append(run(name,'verify-footprints',extra=['--dump-footprints','./footprints.bin','--ram-size','1GB']))
    footprint=footprint_check(diagnostic,[prepared[name]['binary'].parent/'footprints.bin' for name in variants])
    save(out/'footprint-check.json',footprint)
    for name in variants:run(name,'warmup')
    orders=[['A','Aprime','B'],['B','Aprime','A'],['Aprime','A','B'],['B','A','Aprime'],
            ['A','B','Aprime'],['Aprime','B','A'],['A','Aprime','B'],['B','Aprime','A']]
    orders=orders[:args.pairs]
    results=[];signatures={};common_signature=None
    for index,order in enumerate(orders):
        row=dict(pair=index,order=order)
        for name in order:
            result=run(name,f'pair{index:02d}')
            signature={key:result[key] for key in ('pc','instr_count','cycle_count','guest_cycles','stop_reason','workload_output')}
            if name not in signatures:signatures[name]=signature
            if signature!=signatures[name]:raise ValueError(f'{name}: functional signature changed')
            common={key:result[key] for key in ('guest_cycles','stop_reason','workload_output')}
            if common_signature is None:common_signature=common
            if common!=common_signature:raise ValueError('common workload signature differs')
            row[name]=result
        results.append(row);save(out/'triads.json',results)
    pairwise={
        'Aprime_vs_A':pair_summary(results,'A','Aprime',20261102),
        'B_vs_Aprime':pair_summary(results,'Aprime','B',20261103),
        'B_vs_A':pair_summary(results,'A','B',20261104),
    }
    summary=dict(pairs=len(results),orders=orders,runtime_difftest_by_variant={n:v['runtime_difftest'] for n,v in variants.items()},
        pairwise=pairwise,variant_functional_signatures=signatures,common_signature=common_signature,
        footprint_check=footprint,scope='Native full SimTop; Host time includes harness')
    save(out/'summary.json',summary)
    with (out/'triads.csv').open('w') as stream:
        fields=['pair','order','A_host_s','Aprime_host_s','B_host_s','Aprime_vs_A_percent','B_vs_Aprime_percent','B_vs_A_percent']
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for row in results:
            writer.writerow(dict(pair=row['pair'],order='>'.join(row['order']),
                A_host_s=row['A']['host_ms']/1000,Aprime_host_s=row['Aprime']['host_ms']/1000,
                B_host_s=row['B']['host_ms']/1000,
                Aprime_vs_A_percent=100*(row['Aprime']['host_ms']/row['A']['host_ms']-1),
                B_vs_Aprime_percent=100*(row['B']['host_ms']/row['Aprime']['host_ms']-1),
                B_vs_A_percent=100*(row['B']['host_ms']/row['A']['host_ms']-1)))
    print(json.dumps(pairwise),flush=True)


if __name__=='__main__':main()
