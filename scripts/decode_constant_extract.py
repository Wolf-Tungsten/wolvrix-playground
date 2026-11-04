#!/usr/bin/env python3
"""Extract real pre-clone ownership witnesses, retaining all source provenance."""
import argparse,json
from pathlib import Path
from collections import defaultdict
from grhsim_single_baseline import save

def main():
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();root=a.root
 decisions=json.loads((root/'stage-comparison/shared_decisions.json').read_text())['decisions'];selected=decisions[0]
 evidence={}
 for name in ('C','E'):
  stages=root/f'stage-{name}/stages';target=selected[name][2];consumer=selected[name][1];ops={};defs={};names={};users=defaultdict(list)
  # At most the first divergence and upstream cone are kept; scanning is linear.
  with (stages/'before-clone.ops.tsv').open() as f:
   next(f)
   for line in f:
    r=line.rstrip(chr(10)).split(chr(9));i=int(r[0]);ins=tuple(int(x) for x in r[7].split(',') if x);outs=tuple(int(x) for x in r[8].split(',') if x);ops[i]=(r,ins,outs)
    for v in outs:defs[v]=i
    for v in ins:users[v].append(i)
  todo=[target,consumer];keep=set()
  target_results=ops[target][2]
  for v in target_results:todo.extend(users[v])
  for i in list(todo):
   for v in ops[i][2]:todo.extend(users[v])
  frontier=list(todo)
  for depth in range(6):
   new=[]
   for i in frontier:
    if i in keep:continue
    keep.add(i)
    r,ins,outs=ops[i]
    if r[1] in ('kRegisterReadPort','kMemoryReadPort','kLatchReadPort','kConstant'):continue
    new.extend(defs[v] for v in ins if v in defs)
   frontier=new
  needed={v for i in keep for v in ops[i][1]+ops[i][2]}
  with (stages/'before-clone.values.tsv').open() as f:
   next(f)
   for line in f:
    r=line.rstrip(chr(10)).split(chr(9));i=int(r[0])
    if i in needed:names[i]=dict(name=json.loads(r[5]),width=int(r[2]),signed=bool(int(r[3])))
  rows=[]
  for i in sorted(keep):
   r,ins,outs=ops[i];rows.append(dict(id=i,kind=r[1],symbol=json.loads(r[2]),attrs=json.loads(r[3]),file=json.loads(r[4]),line=int(r[5]),inputs=list(ins),results=list(outs)))
  evidence[name]=dict(target=target,consumer=consumer,operations=rows,values=names,boundary=[v for v in needed if defs.get(v) not in keep],scope='real bounded cone, depth 6; not yet minimized or performance proof')
  print(name,len(keep),'ops',flush=True)
 save(root/'stage-comparison/first_owner_cone.json',evidence)

if __name__=='__main__':main()
