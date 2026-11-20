"""Reconstruct paired walltime statistics and placement from archived per-run evidence."""
import argparse
import csv
import math
import random
import statistics
from pathlib import Path

from armor_mask_layout_compare import DEFAULT
from cv32e40p_compare import identity, save, signature as cv_signature
from grhsim_numa import locality_errors
from xiangshan_cv32_ablation_measure import read, signature as xs_signature, verify

NAMES=('full','candidate')
PREFIX=['taskset','-c','96','numactl','--membind=1','setarch','x86_64','-R']


def stats(values, seed):
    deltas=[100*(b/a-1) for a,b in values]
    rng=random.Random(seed)
    boot=sorted(statistics.mean(rng.choices(deltas,k=8)) for _ in range(10000))
    return dict(pairs=8,mean_percent=statistics.mean(deltas),ci95=[boot[249],boot[9749]],
        faster=sum(b<a for a,b in values),baseline_mean_s=statistics.mean(a for a,b in values),
        candidate_mean_s=statistics.mean(b for a,b in values),per_pair_percent=deltas,
        mean_by_order_percent=dict(AB=statistics.mean(deltas[::2]),BA=statistics.mean(deltas[1::2])))


def review(out):
    dest=out.parent/'measurement'
    xs=dest/'xs';cv=dest/'cv'
    machine=read(out/'machine.json')
    assert machine['passed'] and all(machine['gate'].values())
    for m in machine['models'].values():verify(m['binary'])
    verify(read(out/'policy.json')['emitter'])
    assert identity(Path(__file__).resolve().parents[1]/'wolvrix/lib/emit/grhsim_cpp.cpp')['sha256']==read(out/'policy.json')['emitter']['sha256']
    xs_manifest=read(xs/'manifest.json')
    for f in xs_manifest['files']:verify(f)
    xr=read(xs/'rounds.json'); cr=read(cv/'pairs.json')
    assert len(xr)==len(cr)==8
    values={'xs':[],'cv':[]}
    idle={d:{n:[] for n in NAMES} for d in values}
    for i in range(8):
        order=list(NAMES if i%2==0 else NAMES[::-1])
        assert xr[i]['order']==cr[i]['order']==order and xr[i]['round']==cr[i]['pair']==i
        for n,model in zip(NAMES,('A','B')):
            folder=xs/n/'runs';label=f'round{i:02d}'
            x=read(folder/(label+'.json'));c=read(cv/'runs'/label/n/'result.json')
            assert x==xr[i][n] and c==cr[i][n]
            assert (x['cpu'],x['numa_node'],x['max_threads'])==(96,1,1)
            assert x['reference_mapped'] and x['locality_pass'] and not x['diagnostic']
            assert x['binary_sha256']==machine['models'][model]['binary']['sha256']
            assert xs_signature(x)==xs_signature(read(xs/'full/runs/verify-s0.json'))
            command=read(folder/(label+'.command.json'))
            assert command[:8]==PREFIX and '--dump-difftrace' not in command
            assert int((folder/(label+'.personality')).read_text(),16)&0x40000
            local=read(folder/(label+'.locality.json'))
            assert local and not any(locality_errors(sample,1) for sample in local)
            assert cv_signature(c)==cv_signature(read(cv/'functional.json')['coremark'][n])
            for audit in c['audit'].values():
                assert audit['placement']==dict(threads=1,cpu=96,affinity_count=1,aslr_disabled=True)
                assert not locality_errors(audit['locality'],1)
            assert not c['placement_errors'] and c['binary']==read(cv/'build.json')['binaries'][n]
            idle['xs'][n].append(x['sibling_idle']['288'])
            idle['cv'][n].append(c['cpu_idle_percent']['288'])
        values['xs'].append(tuple(xr[i][n]['external_wall_s'] for n in NAMES))
        values['cv'].append(tuple(cr[i][n]['wall_s'] for n in NAMES))
    summarized={d:stats(v,20261102 if d=='xs' else 20261114) for d,v in values.items()}
    raw_x=read(xs/'summary.json')['comparisons']['candidate']['external_wall_s']
    raw_c=read(cv/'summary.json')['wall_s']
    def agree(actual,expected):
        assert all(math.isclose(a,b,abs_tol=1e-10) for a,b in zip(actual,expected))
    agree([summarized['xs']['mean_percent'],*summarized['xs']['ci95']],
          [raw_x['delta_percent_mean'],*raw_x['delta_percent_ci95']])
    agree([summarized['cv']['mean_percent'],*summarized['cv']['ci95']],
          [100*(r-1) for r in [raw_c['ratio_mean'],*raw_c['ratio_ci95']]])
    traces=[]
    for seed in (0,1):
        trace=read(xs/f'trace-candidate-s{seed}.json')
        assert trace['pass_'] and trace['records']==99999 and all(c['pass_'] for c in trace['coverage'])
        for chunk in trace['chunks']:verify(chunk['a']);verify(chunk['b'])
        traces.append(trace['records'])
    counters=read(cv/'counts-check.json')
    for part in ('A','B'):verify(counters[part])
    for w in ('smoke','coremark'):
        assert counters['workloads'][w]['count']==331 and counters['workloads'][w]['identical']
        samples=read(cv/'functional.json')[w]
        for row in samples.values(): verify(row['trace'])
        assert samples['full']['trace']['sha256']==samples['candidate']['trace']['sha256']
    with (dest/'paired-walltime.csv').open('w') as stream:
        writer=csv.writer(stream)
        writer.writerow(['design','pair','order','A_seconds','B_seconds','B/A_percent_change','A_sibling_idle_pct','B_sibling_idle_pct'])
        for d,rows in values.items():
            for i,(a,b) in enumerate(rows):
                writer.writerow([d,i,'AB' if i%2==0 else 'BA',a,b,100*(b/a-1),idle[d]['full'][i],idle[d]['candidate'][i]])
    save(dest/'review.json',dict(status='pass',statistics=summarized,cpu288_idle_percent=idle,traces=traces,
        cv_counts=counters['workloads'],machine=identity(out/'machine.json'),pairs=identity(dest/'paired-walltime.csv')))
    print(summarized,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=DEFAULT)
    review(p.parse_args().out.resolve())
