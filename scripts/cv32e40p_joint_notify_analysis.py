#!/usr/bin/env python3
"""Validate fixed joint factoring and count all local notification reductions."""
import argparse
import json
from pathlib import Path
from cv32e40p_compare import ROOT, identity, save
from cv32e40p_event_regions_compare import check
from cv32e40p_joint_notify_compare import BASE_BACKEND, CANDIDATE, RETAINED, joint_plans
from cv32e40p_repair_analysis import analyze as repair_analysis, counter_rates

def compare_reductions(old,new):
    if old['cycles'] != new['cycles'] or old['trace']['sha256'] != new['trace']['sha256']:
        raise ValueError('counter workload mismatch')
    counter_rates(old);counter_rates(new)
    a,b,n=old['counts'],new['counts'],old['cycles']
    # Persistent dirty writes, validity, consumers and scheduler must be exact.
    keys={k for k in a.keys()|b.keys() if not k.startswith(('notify_reduction_', 'mux_notify_accumulate'))}
    for k in keys:
        if a.get(k)!=b.get(k):raise ValueError('observable execution or invalidation changed: '+k)
    def totals(counts):
        aggregate=lambda prefix:sum(sum(v) for k,v in counts.items() if k.startswith(prefix))/n
        r=dict(deferred=aggregate('notify_reduction_deferred:'),joint=aggregate('notify_reduction_joint:'),
               cache_local=aggregate('mux_notify_accumulate_visits:'),
               persistent_dirty_updates=aggregate('mux_invalidate_visits:'))
        r['total_local_reductions']=r['deferred']+r['joint']+r['cache_local']
        return r
    return dict(invariants=len(keys),before=totals(a),after=totals(b),
                cache_executions_per_cycle={k:sum(v)/n for k,v in b.items() if k.startswith(('mux_cache_visits:','mux_cache_misses:'))})

def analyze(out,old_counts,new_counts):
    check(out)
    directories={RETAINED:ROOT/'build/cv32e40p/mux-input-cache-counts-v1',
                 BASE_BACKEND:old_counts,CANDIDATE:new_counts}
    data=lambda d:json.loads((d/'counts.json').read_text())['coremark']
    result=compare_reductions(data(old_counts),data(new_counts))
    result['plans']=joint_plans(out/CANDIDATE)
    result['inputs']=[identity(p) for p in (out/'build.json',out/'structure.json',
        *(d/'counts.json' for d in directories.values()),Path(__file__).resolve())]
    result['limits']='Counts are emitted OR contribution statements, including reconstruction, not machine instructions. Runtime counters only validate/evaluate the frozen candidate and do not feed any planner or selection.'
    repair_analysis(out,directories,retained_backend=RETAINED)
    save(out/'joint-attribution.json',result)
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--baseline-counts',type=Path,required=True)
    parser.add_argument('--counts',type=Path,required=True)
    args=parser.parse_args();analyze(args.source.resolve(),args.baseline_counts.resolve(),args.counts.resolve())
