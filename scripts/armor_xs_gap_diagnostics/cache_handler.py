"""perf script callback for Linux AMD IBS Op MSRs, in the order emitted in the raw sample."""
from collections import defaultdict
import os
import struct
from pathlib import Path

rows=defaultdict(lambda: [0]*6)

def process_event(event):
    raw=event.get("raw_buf")
    if not raw or len(raw)<44: return
    ctl,ip,data1,data2,data3=struct.unpack_from("<5Q",raw,4)
    if (data1>>38)&1 or not (data3&3):return
    load,store,miss=data3&1,(data3>>1)&1,(data3>>7)&1
    acc=rows[(ip,event.get("dso",""))]
    for k,v in enumerate((load,store,miss,miss*load,miss*store,miss*load*((data3>>32)&65535))):
        acc[k]+=v

def trace_end():
    with Path(os.environ["COUNT_CACHE_OUT"]).open("w") as f:
        for (ip,dso),v in rows.items():
            f.write(f"{ip:x}\t{dso}\t"+"\t".join(map(str,v))+"\n")
