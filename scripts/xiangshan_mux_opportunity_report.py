#!/usr/bin/env python3
"""Summarize whole-graph mux opportunities without adding nested cone sizes."""
import argparse
from collections import Counter
import csv
import hashlib
import heapq
import json
import math
from pathlib import Path
import statistics


def rows(path):
    with path.open() as stream:
        yield from csv.DictReader(stream, delimiter='\t')


def one(path):
    return {k: float(v) if any(x in v for x in ('.','e','E')) else int(v)
            for k,v in next(rows(path)).items()}


def size_bucket(n):
    if n==0:return '0'
    if n<4:return '1-3'
    if n<16:return '4-15'
    if n<64:return '16-63'
    if n<=256:return '64-256'
    return '257+'


def identity(path):
    return dict(path=str(path.resolve()),bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def summarize(out):
    inputs=json.loads((out/'input.json').read_text())
    inventory=one(out/'graph-stats.tsv')
    exclusive=one(out/'exclusive.tsv')
    strict=one(out/'single-use-scalar.tsv')
    bounded=one(out/'bounded-scalar.tsv')
    denominator=inventory['live_pure']
    for data in (exclusive,strict):
        data['coverage_percent']=100*data['unique_gated']/denominator
        data['expected_saving_percent']=100*data['expected_saved']/denominator
    bounded['coverage_percent']=100*bounded['unique_ops']/denominator
    bounded['expected_saving_percent']=100*bounded['expected_saved']/denominator
    histogram=Counter();top_hist=Counter();top_volume=Counter();private_hist=Counter();counts=Counter()
    large=[];all_top=[];total_repeated=0;outer_sum=0
    for raw in rows(out/'muxes.tsv'):
        r={k:int(v) for k,v in raw.items()}
        t,f=r['exclusive_true'],r['exclusive_false'];counts['all']+=1
        counts['any_nonempty']+=bool(t or f);counts['both_nonempty']+=bool(t and f)
        counts['exactly_one_nonempty']+=bool(t)^bool(f)
        counts['constant_selector']+=r['selector_truth']>=0
        counts['private_scalar_any_nonempty']+=bool(r['private_scalar_true'] or r['private_scalar_false'])
        total_repeated+=t+f
        for arm,n in (('true',t),('false',f)):
            histogram[size_bucket(n)]+=1
            private_hist[size_bucket(r['private_scalar_'+arm])]+=1
            if n and r[arm+'_gate_depth']==1:
                top_hist[size_bucket(n)]+=1;top_volume[size_bucket(n)]+=n;outer_sum+=n
                item=(n,r['op_index'],arm,r)
                heapq.heappush(large,item)
                if len(large)>30:heapq.heappop(large)
    assert outer_sum==exclusive['unique_gated'], (outer_sum,exclusive['unique_gated'])
    with Path(inputs['source']['path']).open('rb') as stream:
        for n,oid,arm,r in sorted(large,reverse=True):
            stream.seek(r['json_offset']);op=json.loads(stream.readline().strip().rstrip(b','))
            all_top.append(dict(op=op['sym'],arm=arm,exclusive_ops=n,selector=op['in'][0],
                                result=op['out'],loc=op.get('loc'),**r))
    samples=list(rows(out/'demand-batches.tsv'));sampling={}
    for key,base in (('expected_ops',denominator),('expected_substantive',exclusive['substantive_ops']),
                     ('expected_word_units',exclusive['word_units'])):
        values=[float(r[key]) for r in samples]
        mean=statistics.mean(values)
        # Student t(63), 64 independent block means; this is uncertainty of
        # synthetic sampling only, not uncertainty of real hardware activity.
        if len(values)!=64:raise ValueError('This report expects the fixed 64-batch experiment')
        half=1.998340542520741*statistics.stdev(values)/math.sqrt(len(values))
        sampling[key]=dict(baseline=base,mean=mean,saved=base-mean,
            saving_percent=100*(base-mean)/base,
            saving_percent_ci95=[100*(base-mean-half)/base,100*(base-mean+half)/base])
    perkind={int(r['kind_id']):r for r in rows(out/'exclusive-kinds.tsv')}
    categories=[]
    for r in rows(out/'demand-kinds.tsv'):
        kind=int(r['kind_id']);base=int(r['live_ops']);expected=float(r['expected_ops'])
        if not base:continue
        categories.append(dict(kind=inputs['kinds'][kind],live_ops=base,
            exclusive_saved=float(perkind[kind]['exclusive_expected_saved']),
            demand_saved=base-expected,demand_saving_percent=100*(base-expected)/base))
    categories.sort(key=lambda x:x['demand_saved'],reverse=True)
    summary=dict(input=inputs,inventory=inventory,muxes=counts,
        closed_single_arm=exclusive,private_scalar=strict,bounded_private_scalar=bounded,
        arm_histogram=histogram,private_scalar_arm_histogram=private_hist,
        outermost_disjoint_arm_histogram=top_hist,outermost_union_check=outer_sum,
        outermost_disjoint_arm_op_volume=top_volume,
        naive_sum_of_nested_arm_sizes=total_repeated,
        naive_half_sum=total_repeated/2,
        synthetic_demand=dict(assignments=4096,seed=20261115,
            assumption='Independent fair bits for distinct selector SSA values, reused consistently at every occurrence; literal constants fixed. Boolean relationships between different values are not modeled.',
            metrics=sampling),op_kinds=categories,largest_disjoint_regions=all_top)
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
    with (out/'largest-disjoint-regions.csv').open('w') as f:
        w=csv.writer(f);w.writerow(('op','arm','ops','width','selector','rtl_file','rtl_line'))
        for r in all_top:w.writerow((r['op'],r['arm'],r['exclusive_ops'],r['width'],r['selector'],r['loc']['file'],r['loc']['line']))
    with (out/'op-kinds.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(categories[0]));w.writeheader();w.writerows(categories)
    print(json.dumps({k:summary[k] for k in ('inventory','muxes','closed_single_arm','private_scalar',
          'bounded_private_scalar','arm_histogram','outermost_disjoint_arm_histogram','naive_half_sum','synthetic_demand')},indent=2))
    print('largest independent regions',[(r['exclusive_ops'],Path(r['loc']['file']).name,r['loc']['line']) for r in all_top[:12]])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    summarize(p.parse_args().output.resolve())
