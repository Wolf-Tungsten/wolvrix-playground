#!/usr/bin/env python3
"""Offline audit of the fixed CV32 packed-demand compatibility experiment."""
import argparse
import json
from pathlib import Path
import re

from cv32e40p_compare import identity,save,signature,summarize_named
from cv32e40p_event_regions_compare import check
from grhsim_elf_section_identity import sections


def read(path):
    return json.loads(Path(path).read_text())


def audit(out):
    manifest=check(out);names=manifest['backends'];rows=read(out/'pairs.json')
    assert len(rows)==8 and len(names)==5
    functional=read(out/'functional.json');assert functional['status']=='pass'
    policy=read(out/'measurement-policy.json')
    assert policy['rounds']==8 and policy['cpu']==96 and policy['numa']==1 and not policy['aslr']
    expected=signature(functional['workloads']['coremark'][names[0]])
    observations=0
    for i,row in enumerate(rows):
        assert row['pair']==i and row['order']==(names if i%2==0 else names[::-1])
        assert row['attempt']==0,'Any placement-rejected attempt needs an explicit separate audit.'
        for name in row['order']:
            value=row[name];folder=out/'runs'/f'pair{i:02d}-attempt0'/name
            assert value==read(folder/'result.json') and signature(value)==expected
            assert value['binary']==manifest['binaries'][name]
            assert not value['placement_errors']
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
                observations+=1
    comparisons=read(out/'all-comparisons.json')
    for key,reported in comparisons.items():
        after,before=key.split('_vs_');assert summarize_named(rows,after,before)==reported
    binaries={n:sections(manifest['binaries'][n]['path']) for n in names[:4]}
    assert set(binaries)=={'grhsim_ownership_fixed','grhsim_packed_no_init','grhsim_packed_select','grhsim_packed_combined'}
    assert all(v==binaries['grhsim_ownership_fixed'] for v in binaries.values())
    result=dict(status='pass',formal_samples=40,rounds=8,raw_placement_numa_snapshots=observations,
        attempts=[r['attempt'] for r in rows],equal_feature_code_sections=True,
        sibling_cpu288_idle_percent_range=[min(r[n]['cpu_idle_percent']['288'] for r in rows for n in names),
                                          max(r[n]['cpu_idle_percent']['288'] for r in rows for n in names)],
        comparisons=comparisons,inputs=[identity(out/n) for n in ('build.json','functional.json','pairs.json',
            'measurement-policy.json','all-comparisons.json')],script=identity(Path(__file__).resolve()))
    save(out/'independent-review.json',result)
    print(json.dumps({k:result[k] for k in ('status','formal_samples','raw_placement_numa_snapshots','equal_feature_code_sections','sibling_cpu288_idle_percent_range')},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    audit(p.parse_args().source.resolve())
