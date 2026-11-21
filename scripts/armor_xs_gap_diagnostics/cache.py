from collections import Counter,defaultdict
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from attribute import BASE, Elf, OUT, classify_files, phase, read_rows, source_dir, symbolize, save

def collect(label, wl,regs):
    dest=OUT/"ibs-isolated"/label/wl/"cache"
    dest.mkdir(exist_ok=True)
    stats=dest/"sites.tsv"
    if not stats.exists():
        subprocess.run(["perf","script","-i",dest.parent/"perf.data","-s",Path(__file__).resolve().with_name("cache_handler.py")],
                       check=True,env=dict(os.environ,COUNT_CACHE_OUT=str(stats)),stdout=subprocess.DEVNULL)
    debug=Elf(next((OUT/"lines"/label/"work").glob("*-compile/emu")))
    keys=["load", "store", "dc_miss", "dc_miss_load", "dc_miss_store", "dc_miss_load_latency_sum"]
    rows=defaultdict(Counter);phases=defaultdict(Counter);a=Counter()
    for t in stats.read_text().splitlines():
        ip,dso,*v=t.split("\t")
        v=dict(zip(keys,map(int,v)));a.update(v)
        addr=int(ip,16)-BASE
        if dso.endswith("/emu") and 0<=addr<sum(debug.sec[".text"][::2]):
            name=debug.function(addr) or ""
            p=phase(name)
            if p!="harness":rows[addr].update(v)
        else:p="other"
        phases[p].update(v)
    locations=symbolize(debug.path,sorted(rows),dest)
    wanted=defaultdict(set);gs=label.startswith("gs")
    for src,ln,*_ in locations.values():
        f=Path(src).name
        if ln>0 and re.fullmatch(r"SimTop\d+\.cpp" if gs else r"grhsim_SimTop_sched_\d+\.cpp",f):
            wanted[f].add(ln)
    c=classify_files(source_dir(label),gs,wanted,regs);b=defaultdict(Counter);details=defaultdict(Counter)
    for addr,v in rows.items():
        src,ln,_,_=locations.get(addr,("",0,"",""))
        ph=phase(debug.function(addr) or "")
        k,detail=c.get((Path(src).name,ln),("register update","commit|no line") if ph=="commit"
                                            else ("model, no statement line","model, no statement line"))
        b[k].update(v);details[detail].update(v)
    outside=a.copy()
    for v in b.values():outside.subtract(v)
    b["outside model"]=outside
    save(dest/"summary.json",dict(all=a,phases=phases,buckets=b,details=details))
    print(label,wl,a["dc_miss"],[(k,t["dc_miss"]) for k,t in b.items()],flush=True)
if __name__=="__main__":
    regs=set((OUT/"gs-registers.txt").read_text().splitlines())
    for wl in ("coremark","microbench"):collect(sys.argv[1],wl,regs)
