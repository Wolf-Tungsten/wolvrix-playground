#!/usr/bin/env python3
"""Compare pre-schedule GRH by exact named dataflow, never raw OperationId."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from grhsim_single_baseline import ROOT, identity, save


def operations(path):
    with path.open('rb') as f:
        while True:
            offset=f.tell();line=f.readline()
            if not line:break
            if b'"kind": "k' not in line:continue
            row=json.loads(line.strip().rstrip(b','))
            if 'sym' in row and 'kind' in row:yield offset,row


def semantic(row):
    return {k:v for k,v in row.items() if k not in ('sym','loc')}


def digest(row):
    return hashlib.sha256(json.dumps(semantic(row),sort_keys=True,separators=(',',':')).encode()).digest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    paths=dict(E=ROOT/'build/xs/decode_table_csr_only_20261104_v1/E/pre_reg_to_mem.json',
               C=ROOT/'build/xs/decode_table_tuned_20261103_v1/C/pre_reg_to_mem.json')
    a.output.mkdir(parents=True,exist_ok=True)
    counts=Counter();positions={};kinds={};total={};added=[]
    for name,path in paths.items():
        kinds[name]=Counter();total[name]=0
        for offset,row in operations(path):
            key=digest(row);total[name]+=1;kinds[name][row['kind']]+=1
            if name=='E':counts[key]+=1;positions.setdefault(key,offset)
            elif counts[key]:counts[key]-=1
            else:added.append(dict(offset=offset,operation=row))
            if total[name]%1000000==0:print(name,total[name],flush=True)
    removed=[]
    with paths['E'].open('rb') as f:
        for key,count in counts.items():
            if count:
                f.seek(positions[key]);row=json.loads(f.readline().strip().rstrip(b','))
                removed.append(dict(count=count,offset=positions[key],operation=row))
    result=dict(inputs={n:identity(p) for n,p in paths.items()},counts=total,kinds=kinds,
                removed_from_E=removed,added_in_C=added,
                matching='SHA256 of exact kind, named operands/results, attributes; symbols and source locations excluded. Equal fingerprints are a multiset match, not an individual occurrence assignment.')
    save(a.output/'pre_graph_diff.json',result)
    print(json.dumps(dict(counts=total,removed=len(removed),added=len(added))),flush=True)

if __name__=='__main__':main()
