#!/usr/bin/env python3
"""Independent raw-sample and placement audit of the frozen connected experiment."""
import argparse
import json
from pathlib import Path
import re
from cv32e40p_compare import identity,save,signature,summarize_named
from cv32e40p_event_regions_compare import check


def read(p):return json.loads(Path(p).read_text())

def cv32(out):
    manifest=check(out);names=manifest['backends'];rows=read(out/'pairs.json');policy=read(out/'measurement-policy.json')
    assert len(rows)==len(names)==3 and policy['rounds']==3
    assert policy['cpu']==96 and policy['numa']==1 and not policy['aslr'] and policy['retries']==0
    functional=read(out/'functional.json');assert functional['status']=='pass'
    expected=signature(functional['workloads']['coremark'][names[0]])
    snapshots=0
    for i,row in enumerate(rows):
        assert row['pair']==i and row['order']==(names if i%2==0 else names[::-1])
        for name in row['order']:
            value=row[name];folder=out/'runs'/f'pair{i:02d}'/name
            assert value==read(folder/'result.json') and signature(value)==expected
            assert value['binary']==manifest['binaries'][name] and not value['placement_errors']
            assert read(folder/'run.command.json')['argv'][:8]==['taskset','-c','96','numactl','--membind=1','setarch','x86_64','-R']
            assert read(folder/'run.result.json')['returncode']==0
            for stage in ('start','end'):
                sample=value['audit'][stage]
                assert sample['placement']==read(folder/f'audit.{stage}.placement.json')
                assert sample['placement']==dict(threads=1,cpu=96,affinity_count=1,aslr_disabled=True)
                locality=sample['locality'];assert not locality['unknown_executable']
                assert all(n=='1' or c==0 for g in locality['groups'].values() for n,c in g['pages'].items())
                mappings={}
                for line in (folder/f'audit.{stage}.maps').read_text().splitlines():
                    fields=line.split(maxsplit=5);mappings[int(fields[0].split('-')[0],16)]=(fields[1],fields[5] if len(fields)==6 else '')
                for line in (folder/f'audit.{stage}.numa_maps').read_text().splitlines():
                    address=int(line.split()[0],16)
                    if address not in mappings:continue
                    permissions,path=mappings[address]
                    if '/runtime/' in path or not path or path in ('[heap]','[stack]') or path.startswith('[anon'):
                        assert all(n=='1' or int(c)==0 for n,c in re.findall(r'\bN(\d+)=(\d+)',line))
                    elif 'x' in permissions and path.startswith('/'):
                        assert path.endswith('/ld-linux-x86-64.so.2'),path
                snapshots+=1
    assert len(list((out/'runs').glob('pair*')))==3
    stats=read(out/'summary.json')
    for name,reported in stats.items():assert summarize_named(rows,manifest['candidate'],name)==reported
    result=dict(status='pass',rounds=3,formal_samples=9,raw_placement_numa_snapshots=snapshots,
        no_sample_removal=True,statistics_recomputed=True,comparisons=stats,
        inputs=[identity(out/n) for n in ('build.json','functional.json','pairs.json','summary.json','measurement-policy.json')],script=identity(Path(__file__).resolve()))
    save(out/'independent-review.json',result);print('CV32 independent sample review passed',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    a=p.parse_args();cv32(a.source.resolve())
