#!/usr/bin/env python3
"""Join ordinary walltime, CPU-wide frequency and separate process counters."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import statistics
from grhsim_single_baseline import save
from grhsim_single_compare import summarize


def observation(path):
    d=json.loads(path.read_text());freq=defaultdict(float)
    for row in d['frequency']:freq[row['event']]+=row['value']
    counters={r['event']:r['value'] for r in d.get('pmu',[])}
    return dict(aperf=freq['msr/aperf/'],mperf=freq['msr/mperf/'],
                aperf_mperf=freq['msr/aperf/']/freq['msr/mperf/'],counters=counters,
                running_percent={r['event']:r['running_percent'] for r in d.get('pmu',[])},
                observer_launch_s=d['attach_delay_s'])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);a=p.parse_args()
    raw=json.loads((a.directory/'summary.json').read_text());pairs=raw['samples'];rows=[];metrics=defaultdict(list)
    for pair in pairs:
        row=dict(pair=pair['pair'],order=''.join(pair['order']))
        observations={}
        for name in ('C','E'):
            sample=pair[name];obs=observation(Path(sample['observation']));observations[name]=obs
            row[name+'_host_s']=sample['host_ms']/1000
            row[name+'_wall_s']=sample['external_wall_s']
            for key in ('aperf','mperf','aperf_mperf'):row[name+'_'+key]=obs[key]
            for key,value in obs['counters'].items():row[name+'_'+key]=value
            if 'instructions:u' in obs['counters']:
                row[name+'_CPI']=obs['counters']['cycles:u']/obs['counters']['instructions:u']
                row[name+'_branches_per_instruction']=obs['counters'].get('branches:u',0)/obs['counters']['instructions:u']
        row['E_vs_C_wall_percent']=100*(row['E_host_s']/row['C_host_s']-1)
        for key in ('aperf','mperf','aperf_mperf',*observations['C']['counters']):
            lhs=row['C_'+key];rhs=row['E_'+key]
            if lhs:metrics[key].append(100*(rhs/lhs-1))
        rows.append(row)
    output=dict(mode=raw['mode'],rows=rows,paired_delta_percent={k:dict(mean=statistics.mean(v),median=statistics.median(v),samples=v) for k,v in metrics.items()},
                scope='Host time is the ordinary primary metric only in walltime mode. APERF/MPERF are CPU-wide observations. Process PMU covers attached user execution including NEMU and startup; it is a separate diagnostic.')
    if raw['mode']=='walltime':output['walltime']=summarize([dict(A=r['C'],B=r['E']) for r in pairs])
    save(a.directory/'joined.json',output)
    columns=list(rows[0])
    with (a.directory/'joined.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows(rows)
    print(json.dumps(output.get('walltime',output['paired_delta_percent']),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
