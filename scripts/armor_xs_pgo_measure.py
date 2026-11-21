"""Verify PGO equivalence and time the four XiangShan executables on node030 CPU96."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import platform
import resource

from armor_mask_layout_measure import FIRMWARE, LOCK
from armor_xs_pgo_build import ENGINES, GRHSIM, IMAGE, LLVM, NEMU, OUT, header, run_window
from grhsim_difftrace import build_comparator, compare_traces, validate_trace_coverage
from grhsim_single_baseline import Baseline, identity, save
from grhsim_single_compare import summarize
from xiangshan_cv32_ablation_measure import measurement_lock, read, signature, verify

IMAGES = {'coremark': IMAGE, 'microbench': FIRMWARE/'microbench.bin'}
WINDOW = 100_000


def verify_engine(engine):
    folder = OUT/engine/'verify'
    schema = header(engine)
    if schema.read_bytes() != header('grhsim').read_bytes():
        raise ValueError('DiffTest state layouts differ')
    comparator = build_comparator(schema, folder/'comparator')
    cases = [('off','coremark'),('use','coremark'),('generate','coremark'),
             ('off','microbench'),('use','microbench')]
    cpus = (100,116,132,148,164)
    with ThreadPoolExecutor(max_workers=len(cases)) as pool:
        futures = {(mode,wl):pool.submit(run_window,engine,mode,'check-'+wl,IMAGES[wl],cpu)
                   for (mode,wl),cpu in zip(cases,cpus)}
        runs = {key:f.result() for key,f in futures.items()}
    checks = {}
    for wl in IMAGES:
        ordinary = runs['off',wl]
        ref = OUT/engine/'off'/('check-'+wl)/'trace'
        verified = {}
        for mode in ('use','generate') if wl == 'coremark' else ('use',):
            row = runs[mode,wl]
            if signature(ordinary) != signature(row):
                raise ValueError(f'{engine} {wl}: {mode} endpoint differs from off')
            path = folder/(wl+'-'+mode+'-trace.json')
            actual = OUT/engine/mode/('check-'+wl)/'trace'
            check = compare_traces(comparator,ref,actual,path)
            verified[mode] = validate_trace_coverage(check,row)
        # The production GrhSIM model has independent archived 100k reference traces.
        if engine == 'grhsim':
            frozen = GRHSIM.parent/(wl+'-default')/'runtime/bin/trace_s0'
            check = compare_traces(comparator,frozen,ref,folder/(wl+'-reference-trace.json'))
            verified['reference'] = validate_trace_coverage(check,ordinary)
        checks[wl] = dict(signature=signature(ordinary),checks=verified)
    training = read(OUT/engine/'generate/training/endpoint.json')
    if training != checks['coremark']['signature']:
        raise ValueError(engine+' training diverged from the non-PGO control')
    save(folder/'result.json',dict(workloads=checks,training=training,
         binaries={m:read(OUT/engine/m/'binary.json') for m in ('off','generate','use')},
         schema=identity(schema),profile=read(OUT/engine/'profile/merged.json')))
    print('verified',engine,flush=True)


def paired(rows, a, b):
    result = summarize([{key:dict(host_ms=1000*row[name]['external_wall_s'])
                         for key,name in [('A',a),('B',b)]} for row in rows])
    result.update(metric='external_wall_s', denominator=a, numerator=b)
    return result


def measure(wl, engines):
    if platform.node().split('.')[0] != 'node030':
        raise ValueError('formal timings use node030')
    models = [(e,m) for e in engines for m in ('off','use')]
    names = [e+'-'+m for e,m in models]
    if len(names)==4:
        indices=[(0,1,2,3),(3,2,1,0),(1,0,3,2),(2,3,0,1)]
    else:
        indices=[(0,1),(1,0),(0,1),(1,0)]
    orders=[[names[i] for i in row] for row in indices]
    dest=OUT/'timing'/(wl+('-'+engines[0] if len(engines)==1 else ''))
    with measurement_lock(LOCK,wait=True):
        dest.mkdir(parents=True,exist_ok=False)
        setups={}
        expected={}
        for (engine,mode),name in zip(models,names):
            proof=read(OUT/engine/'verify/result.json')
            record=proof['binaries'][mode]
            verify(record)
            expected[name]=proof['workloads'][wl]['signature']
            settings=argparse.Namespace(output=dest/name,binary=Path(record['path']),simulator=engine,
                compiler=LLVM/'clang++',cpu=96,cycles=WINDOW,jobs=1,repeats=len(orders),tools_dir=None,
                sim_primitives='none',image=IMAGES[wl],nemu=NEMU,skip_idle_check=True)
            runner=Baseline(settings)
            setups[name]=(runner,runner.prepare_measurement())
        save(dest/'policy.json',dict(workload=identity(IMAGES[wl]),nemu=identity(NEMU),orders=orders,
             host=platform.node(),cpu=96,numa=1,seed=0,aslr=False,window=WINDOW,threads=1,
             warmups=1,training_workload='coremark',metric='external_wall_s',lock=str(LOCK)))
        def sample(name,label):
            runner,setup=setups[name]
            row=runner.run_sample(setup,label,WINDOW,0,[])
            if signature(row)!=expected[name]:
                raise ValueError(name+' timed endpoint differs')
            return row
        save(dest/'warmup.json',{n:sample(n,'warmup') for n in names})
        rows=[]
        for i,order in enumerate(orders,1):
            row={'round':i,'order':order}
            rows.append(row)
            for n in order:
                row[n]=sample(n,'round'+str(i))
                save(dest/'rounds.json',rows)
                print('timed',wl,i,n,round(row[n]['external_wall_s'],3),flush=True)
        summary={e:paired(rows,e+'-off',e+'-use') for e in engines}
        if len(engines)==2:
            for m in ('off','use'):
                summary['grhsim_vs_gsim_'+m]=paired(rows,'gsim-'+m,'grhsim-'+m)
        save(dest/'summary.json',summary)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='action',required=True)
    v=sub.add_parser('verify')
    v.add_argument('engine',choices=ENGINES)
    m=sub.add_parser('time')
    m.add_argument('workload',choices=IMAGES)
    m.add_argument('engine',choices=(*ENGINES,'both'))
    args=p.parse_args()
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    if args.action=='verify':
        verify_engine(args.engine)
    else:
        measure(args.workload, ENGINES if args.engine=='both' else (args.engine,))
