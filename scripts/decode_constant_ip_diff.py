#!/usr/bin/env python3
import argparse,re,hashlib,json
from collections import Counter,defaultdict
from pathlib import Path
from grhsim_single_baseline import save

def functions(root, symbols):
 """Read only sampled schedule files; the complete model is about 1.4 GiB."""
 model = root/'model' if (root/'model').is_dir() else root
 out={}
 wanted={}
 for symbol in symbols:
  m=re.search(r'eval_(compute|commit)_batch_(\d+)', symbol)
  if m:wanted.setdefault(int(m.group(2)),[]).append((symbol,m.group(1)))
 for batch,entries in wanted.items():
  p=model/f'grhsim_SimTop_sched_{batch}.cpp'
  if not p.exists():continue
  s=p.read_text(errors='replace')
  for symbol,kind in entries:
   pat=rf'void (GrhSIM_SimTop::eval_{kind}_batch_{batch}\(\))\s*\{{'
   m=re.search(pat,s)
   if not m:continue
   i=m.end()-1;depth=0;j=i
   while j<len(s):
    if s[j]=='{':depth+=1
    elif s[j]=='}':
     depth-=1
     if depth==0:break
    j+=1
   body=s[i:j+1]
   key=hashlib.sha256(body.encode()).hexdigest()
   out[symbol]=dict(hash=key,bytes=len(body),file=p.name,batch=batch,kind=kind)
 return out

def samples(root):
 out=Counter();tot=0
 for p in (root/'runs').glob('pair*.samples.txt'):
  for line in p.open(errors='replace'):
   a=line.split()
   if len(a)<4:continue
   try:period=int(a[0])
   except ValueError:continue
   out[a[2]]+=period;tot+=period
 return out,tot

def main():
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();base=a.root.parent.parent
 info={};
 for n in ('C','E'):
  # The samples are from the frozen C/E binaries.  Keep their source model
  # trees separate from the research counter builds so function identities are
  # tied to the exact binary being sampled.
  frozen = (base/'decode_table_tuned_20261103_v1/C/model' if n=='C'
            else base/'decode_table_csr_only_20261104_v1/E/model')
  sm,_=samples(a.root/n)
  info[n]=functions(frozen,sm)
 rows={}
 for n in ('C','E'):
  sm,tot=samples(a.root/n);byhash=Counter()
  for fn,v in sm.items():
   f=info[n].get(fn)
   byhash[f['hash'] if f else 'unmapped:'+fn]+=v
  rows[n]=dict(total_period=tot,
              sampled_function_count=len(sm),
              mapped_function_count=len(info[n]),
              top_functions=[dict(function=fn,period=v,percent=100*v/tot,meta=info[n].get(fn)) for fn,v in sm.most_common(30)],
              top_body_hashes=[dict(hash=h,period=v,percent=100*v/tot,
                                    meta=next((x for x in info[n].values() if x['hash']==h),None))
                               for h,v in byhash.most_common(30)])
 save(a.root/'ip-sample-diff.json',rows);print(json.dumps(rows,indent=2)[:6000])
if __name__=='__main__':main()
