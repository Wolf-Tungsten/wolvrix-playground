"""Offline register-read lowering inventory keyed by stable state symbol."""
import argparse
from pathlib import Path
from grhsim_single_baseline import identity
import re,json,sys
from collections import defaultdict,Counter
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source',type=Path,required=True)
parser.add_argument('--variant',required=True)
args=parser.parse_args();r=args.source.resolve();v=args.variant;records={};stats=Counter()
for p in sorted((r/v/'model').glob('*_sched_*.cpp')):
 current=None;group=None;phase=None
 for n,line in enumerate(p.open(),1):
  m=re.search(r'void GrhSIM_SimTop::eval_(compute|commit)_batch_',line)
  if m:phase=m[1]
  if phase!='compute':continue
  m=re.search(r'// Supernode (\d+):',line)
  if m:group=int(m[1]);current=None
  m=re.search(r'// op .* \[(k\w+)\](?: reg=(.*))?',line)
  if m:
   current=None
   if m[1]=='kRegisterReadPort':
    current=dict(file=p.name,line=n,group=group,state=m[2].strip());stats['read_comments']+=1
   continue
  if current is None:continue
  status=None
  if '// direct single-writer state read:' in line:status='direct'
  elif re.search(r'value_[a-z0-9_]+\[\d+\] = state_logic_storage_',line):status='copy'
  elif re.search(r'next_value = state_logic_storage_',line):status='copy_next'
  if status:
   d=records.setdefault(current['state'],dict(counts=Counter(),examples={}))
   d['counts'][status]+=1;stats[status]+=1
   d['examples'].setdefault(status,dict(**current,status_line=n,text=line.strip()))
   current=None
out=dict(variant=v,totals=dict(stats),states=records,inputs=[identity(__file__),identity(r/v/'model-sources.json')],limits='Inventory only for direct read comments and explicit direct copies attached to read ops. Ordinary inlined expression state reads are not included. Counts are static.')
(r/'empty-followup').mkdir(exist_ok=True)
(r/'empty-followup'/f'{v}-state-reads.json').write_text(json.dumps(out,indent=2)+'\n');print(v,dict(stats))
