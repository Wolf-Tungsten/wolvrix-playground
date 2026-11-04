#!/usr/bin/env python3
"""Match final schedule memberships and storage independently of numeric IDs."""
from collections import Counter,defaultdict
import argparse,csv,hashlib,json,pickle
from pathlib import Path
from decode_constant_stage_diff import groups
from grhsim_single_baseline import save
csv.field_size_limit(16*1024*1024)

def main():
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();root=a.root
 with (root/'stage-comparison/aligned_after_clone.pkl').open('rb') as f:aligned=pickle.load(f)
 memberships={};groupkeys={};group_unique={};batchkeys={}
 for n in ('C','E'):
  stages=root/f'stage-{n}/stages';keys=aligned[n+'_keys'];counts=Counter(keys.values());unique={k for k,c in counts.items() if c==1};groupkeys[n]={};memberships[n]=Counter();group_unique[n]={}
  for gid,ops in groups(stages/'final-supernodes.groups.bin'):
   sig=tuple(sorted(keys[x] for x in ops));h=hashlib.sha256(b''.join(sig)).hexdigest();groupkeys[n][gid]=h;memberships[n][h]+=1
   if all(keys[x] in unique for x in ops):group_unique[n][gid]=h
  batches=defaultdict(list)
  with (stages/'batches.tsv').open() as f:
   for r in csv.DictReader(f,delimiter='	'):batches[(r['phase'],int(r['batch']))].append(groupkeys[n][int(r['group'])])
  batchkeys[n]={str(k):hashlib.sha256(''.join(sorted(v)).encode()).hexdigest() for k,v in batches.items()}
 print('final membership signatures complete',flush=True)
 common=memberships['C']&memberships['E'];summary=dict(final_groups={n:sum(c.values()) for n,c in memberships.items()},unchanged_group_membership=sum(common.values()),
  changed_group_membership={n:sum((c-common).values()) for n,c in memberships.items()},
  exact_common_batches=len(set(batchkeys['C'].values())&set(batchkeys['E'].values())))
 save(root/'stage-comparison/final_group_keys.json',dict(groups=groupkeys,batches=batchkeys,unique_groups=group_unique))
 def read_storage(n,file,key):
  result={};duplicates=set()
  with (root/f'stage-{n}/stages'/file).open() as f:
   for r in csv.DictReader(f,delimiter='	'):
    k=r[key]
    if k in result:duplicates.add(k)
    result[k]=r
  for k in duplicates:del result[k]
  return result,duplicates
 for file,key in [('storage-states.tsv','name'),('storage-values.tsv','name')]:
  c,ca=read_storage('C',file,key);e,ea=read_storage('E',file,key);common=set(c)&set(e);different=[]
  for k in common:
   if c[k]['cpp_ref']!=e[k]['cpp_ref']:different.append(dict(name=k,C=c[k],E=e[k]))
  summary[file]=dict(common_unique=len(common),ambiguous_C=len(ca),ambiguous_E=len(ea),changed_reference=len(different),C_only=len(set(c)-set(e)),E_only=len(set(e)-set(c)))
  save(root/'stage-comparison'/file.replace('.tsv','-diff.json'),dict(summary=summary[file],changed=different))
  print(file,summary[file],flush=True)
 save(root/'stage-comparison/final_diff.json',summary);print(summary,flush=True)

if __name__=='__main__':main()
