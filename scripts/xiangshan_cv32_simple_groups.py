"""Offline body and incoming-activation audit; never runs a simulator."""
import argparse,json,re,sys
from collections import Counter,defaultdict
from pathlib import Path
from grhsim_single_baseline import identity
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source',type=Path,required=True)
parser.add_argument('--variant',required=True)
args=parser.parse_args()
root=args.source.resolve()
variant=args.variant
folder=root/variant/'model'
audit=json.loads((root/'offline-structure'/f'{variant}-cpp.json').read_text())['cpp']
targets=defaultdict(dict)
for g in audit['groups']:
 if g['phase']=='compute' and g['non_read_const_assign_ops']==0:targets[g['file']][g['line']]=g
rows=[]
for name,byline in targets.items():
 current=None;word=None;bit=None;depth=0;active=False;code=[]
 for lineno,line in enumerate((folder/name).open(),1):
  m=re.search(r'activeWordFlags = static_cast<std::uint8_t>\(supernode_active_curr_\[(\d+)u\]',line)
  if m:word=int(m[1])
  if lineno in byline:current=byline[lineno];depth=0;active=False;code=[];bit=None;continue
  if current is None:continue
  s=line.strip()
  if not active:
   m=re.search(r'if \(unlikely\(activeWordFlags & UINT8_C\((\d+)\)',line)
   if m:bit=int(m[1])
   if s=='{':active=True;depth=1
   continue
  if not s or s.startswith('//'):continue
  depth+=s.count('{')-s.count('}')
  if depth==0:
   materialized_state_copies=sum(bool(re.search(r'(?:value_[a-z0-9_]+\[\d+\]|next_value) = (?:state_logic_storage_|state_(?:reg|memory))',x)) for x in code)
   declared=set();nontrivial=[]
   for x in code:
    m=re.fullmatch(r'bool (grhsim_any_changed_\d+_\d+) = false;',x)
    if m:declared.add(m[1]);continue
    if re.fullmatch(r'supernode_active_(?:curr|next)_\[\d+u\] \|= .*;',x):
     names=set(re.findall(r'grhsim_any_changed_\d+_\d+',x))
     if names and names<=declared and '-static_cast<std::uint8_t>' in x:continue
    nontrivial.append(x)
   rows.append(dict(**current,word=word,bit=bit,empty=not code,false_accumulator_only=bool(code) and not nontrivial,materialized_state_copies=materialized_state_copies,example_code=nontrivial[:2]))
   current=None;continue
  if s not in ('{','}'):code.append(s)
# Conservative static incoming union; include all runtime mask arrays and packed helpers.
# Include deferred word accumulation; exclude initial arrays and residual flag writeback.
runtime=defaultdict(int);initial=defaultdict(int);unknown=[];global_copies=Counter()
for p in folder.glob('*.cpp'):
 table=None
 for lineno,line in enumerate(p.open(),1):
  if '_sched_' in p.name:
   if re.search(r'value_[a-z0-9_]+\[\d+\] = state_logic_storage_',line):global_copies['direct_state_to_value_assignments']+=1
   if re.search(r'next_value = state_logic_storage_',line):global_copies['state_via_next_value_assignments']+=1
   if '// direct single-writer state read:' in line:global_copies['elided_direct_read_comments']+=1
  d=re.search(r'grhsim_deferred_active_word_(\d+) = .*\|.*UINT8_C\((\d+)\)',line)
  if d:runtime[int(d[1])]|=int(d[2])
  m=re.search(r'(?:kInitialComputeActiveMasks|kActivationMasks|kRowReaders)(?:\[\])?\s*\{?\s*=|kRowReaders\{\{',line)
  if 'kInitialComputeActiveMasks[] = {' in line:table='initial'
  elif 'kActivationMasks[] = {' in line or ' kRowReaders{{' in line:table='runtime'
  if table:
   target=initial if table=='initial' else runtime
   for word,mask in re.findall(r'\{(\d+)u, UINT8_C\((\d+)\)\}',line):target[int(word)]|=int(mask)
   if '};' in line or '}};' in line:table=None
  m=re.search(r'supernode_active_(?:curr|next)_\[(\d+)u\] \|= (.+);',line)
  if m:
   masks=re.findall(r'UINT8_C\((\d+)\)',m[2])
   if masks:runtime[int(m[1])]|=int(masks[-1])
   else:unknown.append((p.name,lineno,line.strip()))
  m=re.search(r'grhsim_or_active_u(16|32|64)\(supernode_active_(?:curr|next)_\.data\(\), (\d+)u, (.+);',line)
  if m:
   masks=re.findall(r'UINT(?:16|32|64)_C\((\d+)\)',m[3])
   if masks:
    mask=int(masks[-1]);word=int(m[2])
    for i in range(int(m[1])//8):runtime[word+i]|=(mask>>(8*i))&255
   else:unknown.append((p.name,lineno,line.strip()))
for row in rows:
 row['runtime_mask_union']=runtime[row['word']]
 row['has_recognized_runtime_writer']=bool(row['bit'] and runtime[row['word']]&row['bit'])
 row['initial_mask']=initial[row['word']]
summary=dict(simple_groups=len(rows),empty=sum(r['empty'] for r in rows),false_accumulator_only=sum(r['false_accumulator_only'] for r in rows),
 empty_runtime_writers=sum(r['empty'] and r['has_recognized_runtime_writer'] for r in rows),
 false_only_runtime_writers=sum(r['false_accumulator_only'] and r['has_recognized_runtime_writer'] for r in rows),
 simple_without_runtime_writers=sum(not r['has_recognized_runtime_writer'] for r in rows),unknown_literal_writes=len(unknown),simple_group_state_copy_assignments=sum(r['materialized_state_copies'] for r in rows),global_copies=dict(global_copies))
output=dict(variant=variant,summary=summary,rows=rows,unknown=unknown,
 inputs=[identity(__file__),identity(root/'offline-structure'/f'{variant}-cpp.json'),identity(root/variant/'model-sources.json')],
 limits='Static possible-writer union only, not execution frequency. Runtime masks include scalar, packed, deferred and table writes; residual flag writebacks do not create bits. Comment-bin membership does not imply all actual work is read/assign/constant. No model edits or simulations.')
(root/'empty-followup').mkdir(exist_ok=True)
(root/'empty-followup'/f'{variant}.json').write_text(json.dumps(output,indent=2)+'\n')
print(variant,summary,flush=True)
