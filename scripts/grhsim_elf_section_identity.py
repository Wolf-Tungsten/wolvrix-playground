#!/usr/bin/env python3
"""Read-only ELF64 little-endian section hashes for frozen-model identity."""
import argparse,hashlib,json,struct
from pathlib import Path

def sections(path):
 data=Path(path).read_bytes()
 if data[:6]!=b'\x7fELF\x02\x01':raise ValueError('expected ELF64 little endian')
 base=struct.unpack_from('<Q',data,40)[0]
 stride,count,names_index=struct.unpack_from('<HHH',data,58)
 if stride!=64 or not 0<names_index<count:raise ValueError('unsupported section table')
 rows=[struct.unpack_from('<IIQQQQIIQQ',data,base+i*stride) for i in range(count)]
 names=data[rows[names_index][4]:rows[names_index][4]+rows[names_index][5]]
 result={}
 for r in rows:
  name=names[r[0]:].split(b'\0',1)[0].decode()
  if name in ('.text','.rodata','.data'):
   content=data[r[4]:r[4]+r[5]]
   if len(content)!=r[5]:raise ValueError('truncated section')
   result[name]=dict(bytes=len(content),sha256=hashlib.sha256(content).hexdigest())
 return result
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('binaries',nargs='+',type=Path);args=p.parse_args()
 print(json.dumps({str(b):sections(b) for b in args.binaries},indent=2))
