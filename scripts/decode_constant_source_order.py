#!/usr/bin/env python3
"""Construct replay keys from verified read-only exports, including widths/types."""
import argparse
import json
from pathlib import Path
from decode_constant_stage_diff import order
from grhsim_single_baseline import identity,save

def main():
 p=argparse.ArgumentParser();p.add_argument('stages',type=Path);a=p.parse_args();root=a.stages
 ids=order(root/'source-original-iteration.order.bin');selected=set(ids);ops={};need=set()
 with (root/'before-clone.ops.tsv').open() as f:
  next(f)
  for line in f:
   fields=line.rstrip(chr(10)).split(chr(9));idx=int(fields[0])
   if idx not in selected:continue
   inputs=[int(x) for x in fields[7].split(',') if x];outputs=[int(x) for x in fields[8].split(',') if x]
   ops[idx]=(fields[1],json.loads(fields[3]),inputs,outputs);need.update(inputs);need.update(outputs)
 values={}
 with (root/'before-clone.values.tsv').open() as f:
  next(f)
  for line in f:
   fields=line.rstrip(chr(10)).split(chr(9));idx=int(fields[0])
   if idx in need:values[idx]=(fields[5],fields[2],fields[3])
 def val(v):
  name,width,signed=values[v];return name+':'+width+':'+signed
 def attr(v):
  if isinstance(v,bool):return str(int(v))
  if isinstance(v,str):return json.dumps(v,ensure_ascii=False,separators=(',',':'))
  if isinstance(v,list):return '['+','.join(attr(x) for x in v)+']'
  if isinstance(v,float):return format(v,'.17g')
  return str(v)
 keys=[]
 for idx in ids:
  kind,attrs,inputs,outputs=ops[idx]
  key=json.dumps(kind)+' '+ ' '.join(val(v) for v in inputs) if inputs else json.dumps(kind)
  key+=' ->'+''.join(' '+val(v) for v in outputs)+' attrs'
  key+=''.join(' '+json.dumps(k)+':'+str(t)+':'+attr(v) for k,t,v in attrs)
  keys.append(key)
 if len(set(keys))!=len(keys):raise ValueError('ambiguous source keys')
 path=root/'source-order.reference.txt';path.write_text(chr(10).join(keys)+chr(10))
 save(root/'source-order.reference.json',dict(count=len(keys),identity=identity(path),source=identity(root/'source-original-iteration.order.bin')))
 print(path,len(keys),flush=True)

if __name__=='__main__':main()
