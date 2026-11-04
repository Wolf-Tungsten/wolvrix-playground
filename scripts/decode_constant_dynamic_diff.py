#!/usr/bin/env python3
"""Align dynamic counters by final supernode membership fingerprints."""
import argparse,csv,json
from collections import Counter,defaultdict
from pathlib import Path
from grhsim_single_baseline import save

def main():
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();r=a.root
 final=json.loads((r/'stage-comparison/final_group_keys.json').read_text())['groups']
 counts={}
 for n in ('C','E'):
  rows={}
  with (r/f'count-runs/{n}/runs/runtime/bin/seed0.counts.tsv').open() as f:
   for row in csv.DictReader(f,delimiter='\t'):
    if row['kind']=='group':rows[int(row['id'])]={k:int(row[k]) for k in ('fires','checks','changes','active_writes','active_nonzero','active_new_bits','dirty_writes')}
  counts[n]=rows
 by_hash={}
 for n in ('C','E'):
  for gid,h in final[n].items():by_hash.setdefault(h,{})[n]=counts[n].get(int(gid),{})
 common=[];only=[]
 for h,v in by_hash.items():
  if 'C' in v and 'E' in v:
   common.append((h,v['C'],v['E']))
  else:only.append((h,v))
 fields=('fires','checks','changes','active_writes','active_nonzero','active_new_bits','dirty_writes')
 totals={k:{n:sum((c if n=='C' else e).get(k,0) for _,c,e in common) for n in ('C','E')} for k in fields}
 # The unmatched set includes groups changed by scheduling; its totals are
 # still useful as a boundary, never assigned to a particular RTL source.
 unmatched={n:{k:sum(v.get(n,{}).get(k,0) for h,v in only) for k in fields} for n in ('C','E')}
 ranked=sorted(common,key=lambda x:x[1].get('fires',0)-x[2].get('fires',0),reverse=True)
 result=dict(common_groups=len(common),unmatched_group_hashes=len(only),common_totals=totals,unmatched_totals=unmatched,
  top_common_fire_excess=[dict(hash=h,C=c,E=e,fire_excess=c.get('fires',0)-e.get('fires',0),active_excess=c.get('active_writes',0)-e.get('active_writes',0)) for h,c,e in ranked[:100]],
  scope='Supernode membership hash aligns only identical semantic operation sets. Unmatched groups are not force-assigned; raw C/E totals remain authoritative.')
 save(r/'dynamic-group-diff.json',result);print(json.dumps(result,indent=2)[:4000])
if __name__=='__main__':main()
