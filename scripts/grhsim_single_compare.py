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
        baseline_s_median=statistics.median(r['A']['host_ms']/1000 for r in pairs),
        candidate_s_mean=statistics.mean(r['B']['host_ms']/1000 for r in pairs),
        candidate_s_median=statistics.median(r['B']['host_ms']/1000 for r in pairs),
        note='Negative means candidate faster; CI is a fixed-seed paired bootstrap, not proof of causality')


def compare_footprints(paths, rows):
    records=[identity(path) for path in paths]
    if any(r['bytes']==0 or r['bytes']%8 for r in records):
        raise ValueError('empty or malformed memory footprints')
    if records[0]['sha256']!=records[1]['sha256']:
        raise ValueError('memory footprints differ across A/B')
    outputs=[row['workload_output'] for row in rows]
    if not outputs[0].strip() or outputs[0]!=outputs[1]:
        raise ValueError('missing or different workload/UART output across A/B')
    if rows[0]['guest_cycles']!=rows[1]['guest_cycles']:
        raise ValueError('footprint verification cycle counts differ')
    return dict(status='pass',footprints=records,workload_output=outputs[0],
                guest_cycles=rows[0]['guest_cycles'],
                scope='First-access memory values and workload/UART output; not architectural equivalence')


def runtime_modes(common, baseline=None, candidate=None):
    return dict(A=baseline or common,B=candidate or common)


def build_modes(settings, runtime):
    rtl=settings.get('rtl_difftest','on')
    model=settings.get('model_difftest',runtime)
    compile_mode=settings.get('compile_difftest',model)
    return dict(rtl=rtl,model=model,compile=compile_mode)


def run_signature(row, common_only=False):
    if common_only:
        return {key:row[key] for key in ('guest_cycles','stop_reason','workload_output')}
    fields=['pc','instr_count','cycle_count','guest_cycles']
    if row.get('runtime_difftest')=='off':fields+=['stop_reason','workload_output']
    return {key:row[key] for key in fields}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--historical',type=Path)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--pairs',type=int,default=8)
    p.add_argument('--cycles',type=int,default=100000)
    p.add_argument('--runtime-difftest',choices=['on','off'],default='on')
    p.add_argument('--baseline-runtime-difftest',choices=['on','off'])
    p.add_argument('--candidate-runtime-difftest',choices=['on','off'])
    p.add_argument('--candidate-sim-primitives', choices=['none','priority-encode','popcount','popcount-ge4','gray-decode','decode-table'], default='priority-encode')
    p.add_argument('--image',type=Path,default=XS/'ready-to-run/coremark-2-iteration.bin')
    p.add_argument('--nemu',type=Path,default=XS/'ready-to-run/riscv64-nemu-interpreter-so')
    p.add_argument('--baseline-header',type=Path);p.add_argument('--candidate-header',type=Path)
    p.add_argument('--verification-from',type=Path,
                   help='Reuse completed DiffTest traces after checking frozen binary/input identities')
    args=p.parse_args()
    modes=runtime_modes(args.runtime_difftest,args.baseline_runtime_difftest,args.candidate_runtime_difftest)
    mixed_modes=modes['A']!=modes['B']
    all_on=all(mode=='on' for mode in modes.values())
    if args.historical:modes['H']=modes['A']
    if not platform.node().startswith('node030'):raise ValueError('measurements require node030')
    if args.pairs<8 or args.cycles<100000:raise ValueError('requires >=8 pairs and >=100000 cycles')
    os.sched_setaffinity(0,cpus(Path('/sys/devices/system/cpu/online').read_text()))
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    names=dict(A=resolve_binary(args.baseline),B=resolve_binary(args.candidate))
    if args.historical:names['H']=resolve_binary(args.historical)
    aroot=Path(args.baseline).resolve() if Path(args.baseline).is_dir() else names['A'].parents[2]
    broot=Path(args.candidate).resolve() if Path(args.candidate).is_dir() else names['B'].parents[2]
    build_configs={};build_difftest_modes={}
    for name,binary in names.items():
        path=binary.parents[2]/'configuration.json'
        settings=json.loads(path.read_text()) if path.is_file() else {}
        if settings and settings.get('runtime_difftest','on')!=modes[name]:
            raise ValueError(f'{name}: runtime DiffTest mode differs from build')
        build_configs[name]=settings
        build_difftest_modes[name]=build_modes(settings,modes[name])
    headers=[];comparator=None
    if all_on:
        headers=[args.baseline_header or aroot/'chisel-home/build/generated-src/difftest-state.h',
                 args.candidate_header or broot/'chisel-home/build/generated-src/difftest-state.h']
        if identity(headers[0])['sha256']!=identity(headers[1])['sha256']:raise ValueError('Difftest schemas differ')
        comparator=build_comparator(headers[0],out/'trace-comparator')
    manifest=dict(binaries={k:identity(v) for k,v in names.items()},image=identity(args.image),
        nemu=identity(args.nemu) if 'on' in modes.values() else None,
        runtime_difftest='mixed' if mixed_modes else modes['A'],runtime_difftest_by_variant=modes,
        build_configurations=build_configs,
        headers=[identity(x) for x in headers],pairs=args.pairs,cycles=args.cycles,
        driver=identity(__file__),runner=identity(ROOT/'scripts/grhsim_single_baseline.py'),
        numa=identity(ROOT/'scripts/grhsim_numa.py'),order=pair_order(args.pairs),cpu=96,
        verification_from=str(args.verification_from.resolve()) if args.verification_from else None)
    if args.verification_from:
        if not all_on:raise ValueError('trace reuse requires DiffTest on in both variants')
        previous=json.loads((args.verification_from/'manifest.json').read_text())
        for key in ('binaries','image','nemu','headers','runtime_difftest_by_variant','cycles'):
            if manifest[key]!=previous[key]:raise ValueError('verification inputs changed: '+key)
        for seed in (0,1):
            check=json.loads((args.verification_from/f'trace-s{seed}.json').read_text())
            if not check['pass_'] or check['records']<args.cycles:
                raise ValueError('previous trace verification incomplete')
    save(out/'manifest.json',manifest)
    runners={};prepared={}
    for name,binary in names.items():
        config=argparse.Namespace(output=out/name,binary=binary,image=args.image,nemu=args.nemu,
            compiler='/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++',tools_dir=None,
            sim_primitives='none' if name!='B' else args.candidate_sim_primitives,
            rtl_difftest=build_difftest_modes[name]['rtl'],
            model_difftest=build_difftest_modes[name]['model'],
            compile_difftest=build_difftest_modes[name]['compile'],
            runtime_difftest=modes[name],
            cpu=96,jobs=1,cycles=args.cycles,repeats=args.pairs)
        runners[name]=Baseline(config);prepared[name]=runners[name].prepare_measurement()
    if args.verification_from:
        for name in ('A','B'):
            previous_plan=json.loads((args.verification_from/name/'runs/runtime_plan.json').read_text())
            before=[(entry['role'],entry['source']) for entry in previous_plan['files']]
            after=[(entry['role'],entry['source']) for entry in prepared[name]['plan']['files']]
            if before!=after:raise ValueError(f'{name}: verification runtime dependencies changed')
    def run(name,label,cycles=None,seed=0,extra=()):
        return runners[name].run_sample(prepared[name],label,cycles or args.cycles,seed,extra)
    for name in names:run(name,'smoke',10000)
    trace_checks=[];footprint_check=None
    if all_on:
        for seed in [0,1]:
            if args.verification_from:
                paths=[args.verification_from/n/'runs/runtime/bin'/f'trace_s{seed}' for n in ['A','B']]
            else:
                for name in ['A','B']:
                    # Difftest currently has a fixed 32-byte trace-name buffer.
                    run(name,f'verify-s{seed}',seed=seed,extra=['--dump-difftrace',f'./trace_s{seed}'])
                paths=[prepared[n]['binary'].parent/f'trace_s{seed}' for n in ['A','B']]
            trace_checks.append(compare_traces(comparator,*paths,out/f'trace-s{seed}.json'))
    else:
        # XiangShan's default 8 TiB RAM would reserve a 1 TiB footprint bitmap.
        # Bound only these diagnostic runs; smoke/warmup/timing use default RAM.
        rows=[run(name,'verify-footprints',extra=['--dump-footprints','./footprints.bin',
                                                '--ram-size','1GB']) for name in ['A','B']]
        paths=[prepared[n]['binary'].parent/'footprints.bin' for n in ['A','B']]
        footprint_check=compare_footprints(paths,rows)
        footprint_check['diagnostic_ram_size_bytes']=1024**3
        save(out/'footprint-check.json',footprint_check)
    for name in names:run(name,'warmup')
    anchors=[]
    if 'H' in names:anchors.append(run('H','anchor-before'))
    results=[];signature=None;variant_signatures={}
    for i,order in enumerate(pair_order(args.pairs)):
        pair=dict(pair=i,order=order)
        for name in order:
            row=run(name,f'pair{i:02d}')
            variant_current=run_signature(row)
            if name not in variant_signatures:variant_signatures[name]=variant_current
            if variant_current!=variant_signatures[name]:raise ValueError(f'{name}: functional signature changed')
            current=run_signature(row,common_only=mixed_modes)
            if signature is None:signature=current
            if current!=signature:raise ValueError('functional signatures differ across A/B')
            pair[name]=row
        if all(build_difftest_modes[n]['compile']=='on' for n in ('A','B')):
            for field in ('pc','instr_count','cycle_count'):
                if pair['A'][field]!=pair['B'][field]:
                    raise ValueError(f'{field} differs across A/B')
        results.append(pair);save(out/'pairs.json',results)
    if 'H' in names:anchors.append(run('H','anchor-after'))
    if 'H' in names and signature is not None:
        expected=signature
        for anchor in anchors:
            observed=run_signature(anchor,common_only=mixed_modes)
            if observed!=expected:
                raise ValueError(f'historical anchor functional signature differs: {observed} != {expected}')
    save(out/'summary.json',dict(**summarize(results),samples=results,historical=anchors,
        trace_checks=trace_checks,footprint_check=footprint_check,
        runtime_difftest='mixed' if mixed_modes else modes['A'],runtime_difftest_by_variant=modes,
        build_difftest_modes=build_difftest_modes,
        variant_functional_signatures=variant_signatures,
        functional_signature=signature,scope='Native full SimTop; Host time includes harness'))
    with (out/'pairs.csv').open('w') as f:
        w=csv.writer(f);w.writerow(['pair','order','A_host_s','B_host_s','delta_percent','A_external_s','B_external_s'])
        for r in results:w.writerow([r['pair'],''.join(r['order']),r['A']['host_ms']/1000,r['B']['host_ms']/1000,
            100*(r['B']['host_ms']/r['A']['host_ms']-1),r['A']['external_wall_s'],r['B']['external_wall_s']])
    print(json.dumps(summarize(results)),flush=True)

if __name__=='__main__':main()
