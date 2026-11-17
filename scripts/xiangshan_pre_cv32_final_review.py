#!/usr/bin/env python3
"""Offline audit of all eight direct pre-CV32/latest pairs and functional runs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import statistics
from grhsim_single_compare import summarize
from grhsim_single_baseline import save


def read(path):return json.loads(Path(path).read_text())
def signature(row):
    return {k:row[k] for k in ('pc','instr_count','cycle_count','guest_cycles','stop_reason','runtime_difftest','workload_output')}

def audit(out):
    root=out/'paired';declared=read(out/'policy.json');manifest=read(root/'manifest.json')
    summary=read(root/'summary.json');pairs=read(root/'pairs.json');models=read(out/'models.json')
    assert len(pairs)==summary['pairs']==manifest['pairs']==declared['pairs']==8
    assert manifest['cycles']==declared['cycles']==100000 and manifest['cpu']==declared['cpu']==96
    assert declared['numa']==1 and not declared['aslr'] and declared['threads']==declared['max_sample_attempts']==1
    assert manifest['schema_equal'] and not manifest['allow_schema_change']
    assert manifest['runtime_difftest_by_variant']=={'A':'on','B':'on'}
    assert manifest['verification_from'] is None
    assert manifest['order']==[list(('A','B') if i%2==0 else ('B','A')) for i in range(8)]
    identities={}
    def identity(path):
        path=Path(path).resolve()
        if path not in identities:
            digest=hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
            identities[path]=dict(path=str(path),bytes=path.stat().st_size,sha256=digest.hexdigest())
        return identities[path]
    def verify(row):assert identity(row['path'])==row,row['path']
    for r in read(out/'inputs.json'):verify(r)
    for name,label in (('A','baseline'),('B','candidate')):
        assert manifest['binaries'][name]==models[label]['binary'];verify(manifest['binaries'][name])
        assert manifest['build_configurations'][name]==models[label]['configuration']
    for k in ('image','nemu','driver','runner','numa'):verify(manifest[k])
    for r in manifest['headers']:verify(r)
    expected=signature(pairs[0]['A']);samples=[]
    for i,pair in enumerate(pairs):
        assert pair['pair']==i and pair['order']==manifest['order'][i]
        for name in pair['order']:
            row=read(root/name/'runs'/f'pair{i:02d}.json')
            assert row==pair[name] and signature(row)==expected
            samples.append((name,f'pair{i:02d}',row))
    assert pairs==summary['samples']
    for name in ('A','B'):
        folder=root/name/'runs'
        assert len(list(folder.glob('pair*.command.json')))==8
        for label in ('smoke','verify-s0','verify-s1','warmup'):
            row=read(folder/(label+'.json'))
            assert signature(row)==signature(read(root/'A/runs'/(label+'.json')))
            if label!='smoke':assert signature(row)==expected
            samples.append((name,label,row))
    traces={}
    for seed in (0,1):
        trace=read(root/f'trace-s{seed}.json')
        assert trace['pass_'] and trace['records']==99999 and all(c['pass_'] for c in trace['coverage'])
        assert trace==summary['trace_checks'][seed]
        for chunk in trace['chunks']:verify(chunk['a']);verify(chunk['b'])
        traces[str(seed)]=trace['records']
    monitors=localities=staged=0
    for name in ('A','B'):
        folder=root/name/'runs';plan=read(folder/'runtime_plan.json');prepared=read(folder/'runtime/manifest.json')
        assert plan['cpu']==96 and plan['node']==1 and prepared['status']=='pass'
        for entry in prepared['files']:
            verify(entry['source']);observed=identity(entry['destination'])
            assert observed==entry['copy'] and observed['sha256']==entry['source']['sha256'];staged+=1
    for name,label,row in samples:
        folder=root/name/'runs'
        assert row['cpu']==96 and row['numa_node']==1 and row['max_threads']==1 and row['locality_pass']
        assert row['runtime_difftest']=='on' and row['binary_sha256']==manifest['binaries'][name]['sha256']
        command=read(folder/(label+'.command.json'))
        assert command[:8]==['taskset','-c','96','numactl','--membind=1','setarch','x86_64','-R']
        assert int((folder/(label+'.personality')).read_text(),16)&0x40000
        assert ('--dump-difftrace' in command)==label.startswith('verify-')
        monitoring=read(folder/(label+'.monitor.json'));assert monitoring
        for snap in monitoring:
            assert snap['threads']==len(snap['tasks'])==1
            assert all(t['processor']==96 and t['affinity']=='96' for t in snap['tasks'])
        monitors+=len(monitoring)
        plan=read(folder/'runtime_plan.json');owned={e['destination'] for e in plan['files']}
        records=read(folder/(label+'.locality.json'));assert len(records)==row['locality_samples'] and records
        for index,record in enumerate(records):
            assert not record['unknown_executable']
            assert all(n=='1' or c==0 for g in record['groups'].values() for n,c in g['pages'].items())
            prefix=folder/(label+'.numa')/f'{index:04d}';mappings={}
            for line in prefix.with_suffix('.maps').read_text().splitlines():
                fields=line.split(maxsplit=5);mappings[int(fields[0].split('-')[0],16)]=(fields[1],fields[5] if len(fields)==6 else '')
            for line in prefix.with_suffix('.numa_maps').read_text().splitlines():
                address=int(line.split()[0],16)
                if address not in mappings:continue
                permissions,path=mappings[address]
                if path in owned or not path or path in ('[heap]','[stack]') or path.startswith('[anon'):
                    assert all(n=='1' or int(c)==0 for n,c in re.findall(r'\bN(\d+)=(\d+)',line)),line
                elif 'x' in permissions and path.startswith('/'):assert path==plan['interpreter']['path'],path
            localities+=1
    host=summarize(pairs)
    wall=summarize([{n:dict(host_ms=p[n]['external_wall_s']*1000) for n in ('A','B')} for p in pairs])
    assert all(summary[k]==v for k,v in host.items()) and summary['external_wall']==wall
    report=read(out/'report.json');assert report['external_wall']==wall
    for k in ('models','policy','inputs','summary'):verify(report[k])
    run_window=read(out/'run-window.json');assert run_window['status']=='pass' and run_window['host'].startswith('node030')
    result=dict(status='pass',pairs=8,formal_samples=16,audited_runs=len(samples),traces=traces,
        thread_cpu_snapshots=monitors,raw_numa_snapshots=localities,staged_files=staged,
        no_retries_or_sample_removal=True,host_time=host,external_wall=wall,
        order_diagnostics={order:dict(pairs=[p['pair'] for p in pairs if ''.join(p['order'])==order],
            delta_percent_mean=statistics.mean(100*(p['B']['external_wall_s']/p['A']['external_wall_s']-1) for p in pairs if ''.join(p['order'])==order)) for order in ('AB','BA')},
        sibling_cpu288_idle_percent_range=[min(p[n]['sibling_idle']['288'] for p in pairs for n in ('A','B')),max(p[n]['sibling_idle']['288'] for p in pairs for n in ('A','B'))],
        script=identity(Path(__file__).resolve()),inputs=[identity(out/'report.json'),identity(out/'run-window.json')]+[identity(root/n) for n in ('manifest.json','summary.json','pairs.json','trace-s0.json','trace-s1.json')],
        limits='Direct eight-pair comparison for this fixed 100k-cycle window; not a claim for all workloads.')
    save(out/'independent-review.json',result)
    print(json.dumps({k:result[k] for k in ('status','pairs','formal_samples','audited_runs','thread_cpu_snapshots','raw_numa_snapshots','external_wall','order_diagnostics')},indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);a=p.parse_args();audit(a.source.resolve())
