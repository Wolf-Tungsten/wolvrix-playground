#!/usr/bin/env python3
"""Offline raw-sample audit of a frozen three-pair XiangShan comparison."""
import hashlib
import json
from pathlib import Path
import re
import sys

import argparse
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);args=p.parse_args()
OUT=args.source.resolve()
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from grhsim_single_compare import summarize

def read(path):return json.loads(Path(path).read_text())
cache={}
def identity(path):
    path=Path(path).resolve()
    if path not in cache:
        digest=hashlib.sha256()
        with path.open('rb') as stream:
            for data in iter(lambda:stream.read(1024*1024),b''):digest.update(data)
        cache[path]=dict(path=str(path),bytes=path.stat().st_size,sha256=digest.hexdigest())
    return cache[path]
def verify(record):assert identity(record['path'])==record,record['path']
def signature(row):
    return {key:row[key] for key in ('pc','instr_count','cycle_count','guest_cycles',
        'stop_reason','runtime_difftest','workload_output')}

rows=read(OUT/'paired/pairs.json')
assert len(rows)==3,'Wait for the third complete pair; never summarize a partial pair.'
policy=read(OUT/'policy.json')
manifest=read(OUT/'paired/manifest.json')
assert policy['pairs']==manifest['pairs']==3
assert manifest['cpu']==96 and manifest['cycles']==100000
for key in ('driver','runner','numa'):verify(manifest[key])
correction=read(OUT/'runtime-driver/correction.json')
assert correction['runner']['sha256']==correction['original']['sha256']
verify(correction['runner']);verify(correction['original'])
for record in read(OUT/'inputs.json'):verify(record)
build=read(OUT/'build.json')
verify(build['inputs'])
for record in build['files']:verify(record)
for record in list(manifest['binaries'].values())+manifest['headers']+[manifest['image'],manifest['nemu']]:verify(record)
assert manifest['binaries']['B']==build['candidate']
assert manifest['binaries']['A']==build['baseline']

traces={}
for seed in (0,1):
    trace=read(OUT/f'paired/trace-s{seed}.json')
    assert trace['pass_'] and trace['records']==99999
    assert all(x['pass_'] for x in trace['coverage'])
    for chunk in trace['chunks']:
        verify(chunk['a']);verify(chunk['b'])
    traces[str(seed)]=dict(records=trace['records'],first_cycle=trace['first_cycle'],last_cycle=trace['last_cycle'])

samples=[]
for index,row in enumerate(rows):
    assert row['pair']==index
    assert row['order']==(['A','B'] if index%2==0 else ['B','A'])
    for side in row['order']:
        assert row[side]==read(OUT/f'paired/{side}/runs/pair{index:02d}.json')
        assert signature(row[side])==signature(rows[0]['A'])
        samples.append((side,f'pair{index:02d}',row[side]))
for side in ('A','B'):
    for label in ('smoke','verify-s0','verify-s1','warmup'):
        row=read(OUT/f'paired/{side}/runs/{label}.json')
        assert signature(row)==signature(read(OUT/f'paired/A/runs/{label}.json'))
        if label=='warmup':assert signature(row)==signature(rows[0]['A'])
        samples.append((side,label,row))

monitors=localities=0
staged_files=0
for side in ('A','B'):
    plan=read(OUT/f'paired/{side}/runs/runtime_plan.json')
    prepared=read(OUT/f'paired/{side}/runs/runtime/manifest.json')
    assert plan['cpu']==96 and plan['node']==1 and prepared['status']=='pass'
    for entry in prepared['files']:
        observed=identity(entry['destination'])
        assert observed['sha256']==entry['source']['sha256']
        assert observed['bytes']==entry['source']['bytes']
        assert observed==entry['copy']
        if entry['role']=='binary':assert observed['sha256']==manifest['binaries'][side]['sha256']
        staged_files+=1

for side,label,row in samples:
    folder=OUT/f'paired/{side}/runs'
    assert row['cpu']==96 and row['numa_node']==1 and row['max_threads']==1
    assert row['locality_pass'] and row['runtime_difftest']=='on'
    assert row['binary_sha256']==manifest['binaries'][side]['sha256']
    command=read(folder/(label+'.command.json'))
    assert command[:8]==['taskset','-c','96','numactl','--membind=1','setarch','x86_64','-R']
    assert int((folder/(label+'.personality')).read_text(),16)&0x40000
    monitoring=read(folder/(label+'.monitor.json'))
    assert monitoring
    for snap in monitoring:
        assert snap['threads']==len(snap['tasks'])==1
        assert all(task['processor']==96 and task['affinity']=='96' for task in snap['tasks'])
    monitors+=len(monitoring)
    records=read(folder/(label+'.locality.json'))
    assert len(records)==row['locality_samples'] and records
    plan=read(folder/'runtime_plan.json')
    owned={entry['destination']:entry['role'] for entry in plan['files']}
    for index,record in enumerate(records):
        assert not record['unknown_executable']
        assert all(node=='1' or count==0 for group in record['groups'].values()
                   for node,count in group['pages'].items())
        prefix=folder/(label+'.numa')/f'{index:04d}'
        mappings={}
        for line in prefix.with_suffix('.maps').read_text().splitlines():
            fields=line.split(maxsplit=5)
            mappings[int(fields[0].split('-')[0],16)]=(fields[1],fields[5] if len(fields)==6 else '')
        for line in prefix.with_suffix('.numa_maps').read_text().splitlines():
            address=int(line.split()[0],16)
            if address not in mappings:continue
            perms,path=mappings[address]
            if path in owned or not path or path in ('[heap]','[stack]') or path.startswith('[anon'):
                assert all(node=='1' or int(count)==0 for node,count in re.findall(r'\bN(\d+)=(\d+)',line)),line
            elif 'x' in perms and path.startswith('/'):
                assert path==plan['interpreter']['path'],path
        localities+=1

host=summarize(rows)
external=summarize([{side:dict(host_ms=row[side]['external_wall_s']*1000) for side in ('A','B')}
                    for row in rows])
extra=[]
for side in ('A','B'):
    for path in sorted((OUT/f'paired/{side}/runs').glob('pair*.command.json')):
        match=re.fullmatch(r'pair(\d+)\.command\.json',path.name)
        if match and int(match[1])>=3:
            label='pair'+match[1]
            extra.append(dict(side=side,label=label,command=identity(path),
                completed_result=(path.parent/(label+'.json')).exists(),
                treatment='Outside the user-requested three-pair limit; not a retained comparison or performance-based deletion.'))
assert not list((OUT/'paired').rglob('*.rejected.json'))
report=dict(status='pass',predeclared_pairs=3,completed_pairs=3,
    formal_samples=6,audited_runs=len(samples),thread_cpu_snapshots=monitors,
    raw_numa_snapshots=localities,staged_file_identities=staged_files,
    host_time=host,external_wall=external,traces=traces,
    formal_sibling_cpu288_idle_percent_range=[min(row[side]['sibling_idle']['288'] for row in rows for side in ('A','B')),
                                            max(row[side]['sibling_idle']['288'] for row in rows for side in ('A','B'))],
    beyond_limit_launches=extra,
    limits=['Three predeclared pairs; bootstrap intervals are descriptive small-sample intervals, not a guarantee across workloads or hosts. No sample deletion or runtime feedback.'],
    inputs=[identity(OUT/path) for path in ('policy.json','build.json','structure.json','runtime-driver/correction.json',
        'paired/manifest.json','paired/pairs.json','paired/trace-s0.json','paired/trace-s1.json')],script=identity(__file__))
(OUT/'independent-review').mkdir(exist_ok=True)
summary=read(OUT/'paired/summary.json')
assert summary['external_wall']==external
assert summary['delta_percent_mean']==host['delta_percent_mean']
(OUT/'independent-review/review.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({key:report[key] for key in ('status','formal_samples','audited_runs','thread_cpu_snapshots','raw_numa_snapshots','external_wall','beyond_limit_launches')},indent=2))
