#!/usr/bin/env python3
"""Compare schedule stages using named dataflow and explicit clone provenance."""
from array import array
from collections import Counter, defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import pickle
import sys

from grhsim_single_baseline import save


def words(path):
    data=array('I')
    with path.open('rb') as f:data.frombytes(f.read())
    if sys.byteorder!='little':data.byteswap()
    return data


def order(path):
    a=words(path)
    if not a or a[0]!=len(a)-1:raise ValueError('truncated order: '+str(path))
    return a[1:]


def nodes(path):
    a=words(path);p=1
    for index in range(a[0]):
        flags=a[p];p+=1;n=a[p];p+=1;ops=a[p:p+n];p+=n;n=a[p];p+=1;boundary=a[p:p+n];p+=n
        yield index,flags,ops,boundary
    if p!=len(a):raise ValueError('trailing/truncated nodes: '+str(path))


def groups(path):
    a=words(path);p=1
    for index in range(a[0]):
        n=a[p];p+=1;members=a[p:p+n];p+=n
        yield index,members
    if p!=len(a):raise ValueError('trailing/truncated groups: '+str(path))


def fingerprint(fields):
    return hashlib.sha256(json.dumps(fields,separators=(',',':'),ensure_ascii=False).encode()).digest()


class Snapshot:
    def __init__(self,path,stage):
        self.path=path;self.stage=stage
        print('loading',path,stage,flush=True)
        self.names={};self.canonical={}
        with (path/(stage+'.values.tsv')).open() as f:
            next(f)
            for line in f:
                idx,canon,width,signed,definition,name=line.rstrip('\n').split('\t')
                self.names[int(idx)]=json.loads(name)
                if idx!=canon:self.canonical[int(idx)]=int(canon)
        self.keys={};self.metadata={};self.outputs={}
        clone_records={}
        if stage=='after-clone':
            a=words(path/'source-clones.bin')
            if len(a)%6:raise ValueError('truncated clone records')
            for i in range(0,len(a),6):clone_records[a[i+4]]=(a[i],a[i+2],a[i+3])
        with (path/(stage+'.ops.tsv')).open() as f:
            next(f)
            for line in f:
                idx,kind,sym,attrs,file,lineno,col,inputs,outputs=line.rstrip('\n').split('\t')
                idx=int(idx);ins=list(map(int,inputs.split(','))) if inputs else [];outs=list(map(int,outputs.split(','))) if outputs else []
                semantic=(kind,attrs,[self.names[self.canonical.get(v,v)] for v in ins],
                          [self.names[self.canonical.get(v,v)] for v in outs])
                self.keys[idx]=fingerprint(semantic)
                # Only compact metadata retained; the complete original TSV stays on disk.
                self.metadata[idx]=(kind,json.loads(sym),json.loads(file),int(lineno),tuple(self.names[v] for v in outs))
                self.outputs[idx]=tuple(self.names[self.canonical.get(v,v)] for v in outs)
        # Each source clone belongs to an explicit consumer operand. Use that
        # consumer's pre-clone dataflow signature, not its numeric ID/name suffix.
        base=dict(self.keys)
        for clone,(source,user,operand) in clone_records.items():
            self.keys[clone]=fingerprint(('clone',base[source].hex(),base[user].hex(),operand))
        self.topo=order(path/(stage+'.topo.bin'))
        print('loaded',len(self.keys),'ops',len(clone_records),'clones',flush=True)

    def describe(self,idx):
        kind,symbol,file,line,outputs=self.metadata[idx]
        return dict(local_id=idx,kind=kind,symbol=symbol,file=file,line=line,outputs=outputs)


def align(e,c):
    er=defaultdict(list);cr=defaultdict(list)
    for idx,key in e.keys.items():er[key].append(idx)
    for idx,key in c.keys.items():cr[key].append(idx)
    mapping={};ambiguous=0
    for key,ids in cr.items():
        left=er.get(key,[])
        if len(ids)==1 and len(left)==1:mapping[ids[0]]=left[0]
        elif left:ambiguous+=len(ids)
    return mapping,dict(exact_unique=len(mapping),ambiguous_c_ops=ambiguous,unmatched_c=len(c.keys)-len(mapping)-ambiguous)


def sequence_diff(e_order,c_order,mapping,e,c):
    common=set(mapping.values());left=[x for x in e_order if x in common]
    right=[mapping[x] for x in c_order if x in mapping]
    shared=set(left)&set(right);left=[x for x in left if x in shared];right=[x for x in right if x in shared]
    pos={v:i for i,v in enumerate(left)}
    changed=sum(a!=b for a,b in zip(left,right))
    witnesses=[]
    for i,(a,b) in enumerate(zip(left,right)):
        if a!=b:
            witnesses.append(dict(common_position=i,E=e.describe(a),C_matching_E=e.describe(b),displacement=pos[b]-i))
            if len(witnesses)==12:break
    return dict(common=len(left),changed_positions=changed,max_displacement=max((abs(pos[x]-i) for i,x in enumerate(right)),default=0),first=witnesses)


def compare_nodes(ep,cp,mapping,e,c):
    # Compare membership sets. Node IDs and creation order remain only evidence
    # for each individual version, not cross-version identities.
    shared=set(mapping.values());counter=Counter();emeta={};totals={}
    for name,path in [('E',ep),('C',cp)]:
        n=0;common=0;ops_n=0
        for idx,flags,ops,bounds in nodes(path):
            n+=1;common+=bool(flags&1);ops_n+=len(ops)
            normalized=tuple(sorted(x for x in ops if x in shared)) if name=='E' else tuple(sorted(mapping[x] for x in ops if x in mapping))
            if not normalized:continue
            key=(flags,normalized)
            if name=='E':counter[key]+=1;emeta.setdefault(key,idx)
            else:counter[key]-=1
        totals[name]=dict(nodes=n,common_nodes=common,ops=ops_n)
    remaining=[(k,v) for k,v in counter.items() if v]
    examples=[]
    for (flags,ops),count in remaining[:12]:
        examples.append(dict(side='E' if count>0 else 'C',count=abs(count),flags=flags,operations=[e.describe(x) for x in ops[:8]]))
    return dict(totals=totals,changed_membership_groups=sum(abs(v) for _,v in remaining),examples=examples)


def compare_shared(e,c,mapping):
    er={};duplicates=set()
    a=words(e.path/'shared-decisions.bin')
    if len(a)%6:raise ValueError('truncated shared decisions')
    for i in range(0,len(a),6):
        row=list(a[i:i+6]);key=(row[1],row[2])
        if key in er:duplicates.add(key)
        er[key]=(i//6,row)
    a=words(c.path/'shared-decisions.bin');changed=[];same=0;unmapped=0
    if len(a)%6:raise ValueError('truncated shared decisions')
    for i in range(0,len(a),6):
        row=list(a[i:i+6]);key=(mapping.get(row[1]),mapping.get(row[2]))
        if None in key or key not in er or key in duplicates:unmapped+=1;continue
        ei,old=er[key]
        if old[4:]!=row[4:]:
            changed.append(dict(E_ordinal=ei,C_ordinal=i//6,E=old,C=row,consumer=e.describe(key[0]),producer=e.describe(key[1])))
        else:same+=1
    return dict(equal=same,unmapped_or_ambiguous=unmapped,changed=len(changed),decisions=changed,
                reasons={'0':'absorbed','1':'capacity','2':'invalid node','3':'common owner cannot absorb','4':'not earliest semantic consumer','5':'other consumer reaches node'})


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--E',type=Path,required=True);p.add_argument('--C',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    summary={}
    for stage in ('before-clone','after-clone'):
        e=Snapshot(args.E,stage);c=Snapshot(args.C,stage);mapping,stats=align(e,c)
        summary[stage]=dict(alignment=stats,topology=sequence_diff(e.topo,c.topo,mapping,e,c))
        if stage=='before-clone':
            summary[stage]['source_iteration']=sequence_diff(order(e.path/'source-original-iteration.order.bin'),order(c.path/'source-original-iteration.order.bin'),mapping,e,c)
        else:
            save(args.output/'shared_decisions.json',compare_shared(e,c,mapping))
            summary[stage]['node_stages']={}
            for name in ['nodes-created','nodes-declared-split',*[f'nodes-cycle-split-{i}' for i in range(1,14)],'nodes-final']:
                ep=e.path/(name+'.nodes.bin');cp=c.path/(name+'.nodes.bin')
                if not ep.exists() or not cp.exists():continue
                summary[stage]['node_stages'][name]=compare_nodes(ep,cp,mapping,e,c)
                save(args.output/'stage_diff.json',summary)
            with (args.output/'aligned_after_clone.pkl').open('wb') as f:
                pickle.dump(dict(C_to_E=mapping,E_keys=e.keys,C_keys=c.keys,E_metadata=e.metadata,C_metadata=c.metadata),f,protocol=5)
        save(args.output/'stage_diff.json',summary)
        del e,c,mapping
    print('stage comparison complete',flush=True)

if __name__=='__main__':main()
