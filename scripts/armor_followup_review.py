"""Recompute each experiment's two contrasts from the raw per-run records."""
import csv
import json
import math

from armor_followup_compare import OUT
from armor_followup_measure import ORDERS, VARIANT_KEYS
from armor_mask_layout_review import stats
from cv32e40p_compare import identity,save
from xiangshan_cv32_ablation_measure import read,verify


def agree(a,b):
    if not math.isclose(a,b,abs_tol=1e-8):raise ValueError(f'{a} != {b}')


def review():
    machine=read(OUT/'machine.json')
    xs=OUT/'measurement/xs';cv=OUT/'measurement/cv'
    binaries={'xs':machine['binaries'],'cv':read(cv/'build.json')['binaries']}
    structural=read(OUT/'source-audit.json')
    for cand in binaries.values():
        for v in cand.values():verify(v)
    assert read(OUT/'F/cv/sections.json')['baseline']==read(OUT/'F/cv/sections.json')['candidate']
    assert structural['cv-F']['changed']==[]
    observed=read(OUT/'factor-counters/verified.json')
    verify(observed['trace']);verify(observed['counts'])
    assert observed['per_group_agreement'] and observed['groups']==len(structural['xs-F']['guards'])
    assert read(OUT/'factor-counters/trace.json')['pass_']
    commit=read(OUT/'commit-counters/verified.json')
    verify(commit['trace']);verify(commit['counts'])
    assert read(OUT/'commit-counters/trace.json')['records']==99999
    ct=commit['totals']
    assert ct['groups']==ct['all_equal']+ct['changed_groups']
    assert ct['candidate_member_writes']==ct['changed_members']+ct['extra_member_writes']
    assert ct['changed_members']==ct['changed_groups']+ct['avoided_duplicate_reader_sets']
    traces=read(OUT/'functional-xs/verified.json')
    for name in VARIANT_KEYS:
        assert traces['current'][name]==binaries['xs'][name]
        for seed in (0,1):
            r=traces['runs'][f'verify-s{seed}-{name}']; assert r['run']['binary_sha256']==binaries['xs'][name]['sha256']
            verify(r['trace']);d=read(r['trace']['path']);assert d['pass_'] and d['records']==99999 and all(x['pass_'] for x in d['coverage'])
            for c in d['chunks']:verify(c['a']);verify(c['b'])
    counts=read(cv/'counts-check.json')
    assert counts['per_workload']==331
    verify(counts['baseline'])
    before=read(counts['baseline']['path'])
    for name,record in counts['variants'].items():
        verify(record)
        for workload,row in read(record['path']).items():
            fixed=dict(row['counts'])
            if name=='commit':
                measured=fixed.pop('commit_saved_direct_ors')
                direct=fixed['direct_active_or_executions']
                change=counts['direct_or_reconciliation'][workload]
                assert measured==change['avoided'] and direct==change['candidate']
                fixed['direct_active_or_executions']=[x+y for x,y in zip(direct,measured)]
            assert len(fixed)==331 and before[workload]['counts']==fixed
    for w,rows in read(cv/'functional.json').items():
        golden=read(cv/'verification.json')['workloads'][w]['verilator']['trace']
        for row in rows.values():
            verify(row['trace']);assert row['trace']['sha256']==golden['sha256'] and row['trace']['bytes']==36*row['cycles']
    paired=[];report={};data={}
    for design,folder in [('xs',xs),('cv',cv)]:
        rounds=read(folder/'rounds.json');assert [r['order'] for r in rounds]==ORDERS
        summary=read(folder/'summary.json')
        for idx,rec in enumerate(rounds):
            t={};idle={}
            for name in ORDERS[idx]:
                source=(folder/name/'runs'/f'round{idx:02d}.json' if design=='xs' else folder/'runs'/f'round{idx:02d}'/name/'result.json')
                raw=read(source);assert raw==rec[name] and rec['round']==idx
                if design=='xs':
                    assert raw['cpu']==96 and raw['max_threads']==1 and raw['locality_pass'] and raw['numa_node']==1
                    assert raw['binary_sha256']==binaries[design][name]['sha256'] and raw['reference_mapped'] and raw['guest_cycles']==100001
                    t[name]=raw['external_wall_s'];idle[name]=raw['sibling_idle']['288']
                else:
                    assert not raw['placement_errors'] and raw['binary']==binaries[design][name] and raw['cycles']==3376065
                    t[name]=raw['wall_s'];idle[name]=raw['cpu_idle_percent']['288']
            for name in VARIANT_KEYS:
                paired.append([design,idx+1,'>'.join(rec['order']),name,t['full'],t[name],100*(t[name]/t['full']-1),idle['full'],idle[name]])
                data.setdefault((design,name),[]).append((t['full'],t[name]))
        report[design]={}
        for name in VARIANT_KEYS:
            z=stats(data[design,name],20261102 if design=='xs' else 20261114)
            if design=='xs':
                old=summary['comparisons'][name]['external_wall_s'];vals=[old['delta_percent_mean'],*old['delta_percent_ci95']]
            else:
                old=summary[name]['wall_s'];vals=[100*(x-1) for x in (old['ratio_mean'],*old['ratio_ci95'])]
            for a,b in zip([z['mean_percent'],*z['ci95']],vals):agree(a,b)
            report[design][name]=z
    outfile=OUT/'paired-walltime.csv'
    with outfile.open('w') as out:
        wr=csv.writer(out);wr.writerow(['design','round','order','candidate','A_s','candidate_s','percent_change','A_CPU288_idle','candidate_CPU288_idle']);wr.writerows(paired)
    rows=read(OUT/'pmu/raw.json');assert [r['variant'] for r in rows]==['full','commit','factor','factor','commit','full']
    for r in rows:
        assert r['placement'] and r['binary']==binaries['xs'][r['variant']] and r['signature']['guest_cycles']==100001
        for z in r['events'].values():agree(z['raw']*z['enabled_ns']/z['running_ns']/100001,z['per_guest_cycle'])
    repl=read(OUT/'pmu/summary.json')['changes_percent']
    for n,i,j in [('commit',1,4),('factor',2,3)]:
        for e in repl[n]:
            for k,a,expected in ((i,0,repl[n][e][0]),(j,5,repl[n][e][1])):
                agree(100*(rows[k]['events'][e]['per_guest_cycle']/rows[a]['events'][e]['per_guest_cycle']-1),expected)
    save(OUT/'review.json',dict(status='pass',statistics=report,paired=identity(outfile),pmu=repl,
        inputs=[identity(OUT/p) for p in ('machine.json','source-audit.json','factor-counters/verified.json','commit-counters/verified.json','functional-xs/verified.json','measurement/cv/counts-check.json','machine/witnesses.json','pmu/raw.json','native-target.json','final-ctest.log')]))
    print(json.dumps(report,indent=2))


if __name__=='__main__':review()
