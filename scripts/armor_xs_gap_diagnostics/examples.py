"""Extract short actual ELF disassembly windows around source-identified hot sites."""
from collections import Counter, defaultdict, deque
import json
from pathlib import Path
import re
import subprocess
from machine import *
from armor_dispatch_ibs import BASE, read_rows, symbolize

def examine(label):
    elf=Elf(BINS[label]); sym=Elf(next((OUT/"lines"/label/"work").glob("*-compile/emu")))
    folder=OUT/"machine"/label/"examples"
    folder.mkdir(exist_ok=True)
    raw=read_rows(OUT/"ibs-isolated"/label/"coremark",6)
    freq={}
    for ip,(row,dso,_) in raw.items():
        a=ip-BASE
        if dso.endswith("/emu") and sym.function(a) and phase(sym.function(a)) in ("compute","subStep","commit"):
            freq[a]=row
    pmc={}
    for line in (OUT/"machine"/label/"coremark/model-ips.tsv").read_text().splitlines():
        a,n,_,_=line.split();pmc[int(a,16)]=int(n)
    wanted=set(pmc)|{a for a,row in freq.items() if row[3]}
    loc=symbolize(sym.path,sorted(wanted),folder)
    sites=defaultdict(list); misses=Counter();rows=Counter();extra=Counter()
    for a,frames in loc.items():
        name,ln=Path(frames[0]).name,frames[1]
        if not ln: continue
        if not (name.startswith("SimTop") or name.startswith("grhsim_SimTop")):continue
        key=(name,ln)
        sites[key].append(a)
        misses[key]+=freq.get(a,[0,0,0,0])[3]
        rows[key]+=pmc.get(a,0)
        if name.startswith("grhsim_SimTop"):
            if phase(sym.function(a) or "")=="commit": extra["commit"]+=pmc.get(a,0)
    return elf,sites,misses,rows

def excerpt(elf,site,pcs,tag,label,center=None):
    pc=center or pcs[0]
    name=elf.function(pc); start=elf.funcs[name][0]
    until=pc+80
    text=subprocess.check_output([LLVM/"llvm-objdump","-d","--no-show-raw-insn","--demangle",
            f"--start-address={start}",f"--stop-address={until}",elf.path],text=True,errors="replace")
    match=re.compile(r"^\s*([0-9a-f]+):\s+(.*)")
    prev=deque(maxlen=7); after=[]
    for line in text.splitlines():
        m=match.match(line)
        if not m:continue
        addr=int(m[1],16)
        if addr<pc:prev.append(line)
        elif len(after)<10:after.append(line)
    dest=OUT/"machine"/label/"examples"/(tag+".asm")
    dest.write_text(f"{elf.path.name} {name}\n{site[0]}:{site[1]}  sample=0x{pc:x}\n"+"\n".join([*prev,*after])+"\n")
    return str(dest.relative_to(OUT))

def main():
    gr,gs,pg=(examine(l) for l in ("gr_pgo","gs_off","gs_pgo"))
    rows={}
    for name,ln in [("grhsim_SimTop_sched_73.cpp",65),("grhsim_SimTop_sched_59.cpp",40458)]:
        key=name,ln
        if key in gr[1]:
            tags="bank" if ln==65 else "notify"
            rows[tags]=dict(location=key,cycles=gr[3][key],excerpt=excerpt(gr[0],key,gr[1][key],tags,"gr_pgo"))
    choices=[]
    for key,n in gs[2].most_common(1000):
        if n<2 or key not in pg[1]:continue
        choices.append((key,n))
    files=defaultdict(set)
    for (fn,ln),n in choices:files[fn].add(ln)
    source={}
    for fn,lines in files.items():
        for ln,t in enumerate((MATCHED/"model"/fn).open(),1):
            if ln in lines:source[fn,ln]=t.strip()
    mc=Disassembler()
    examples=[]
    for key,n in choices:
        t=source[key]
        if not t.startswith("if (") or "$old$" in t or "activeFlags" in t:continue
        d1={a:mc.get(gs[0].code(a,16),a) for a in gs[1][key]}
        d2={a:mc.get(pg[0].code(a,16),a) for a in pg[1][key]}
        j1=[a for a,ins in d1.items() if asmclass(ins)=="jcc"]
        # Prefer a line whose PGO conditional becomes a branchless selection.
        special=[a for a,ins in d2.items() if asmclass(ins)=="cmov" or ins.startswith(("vpblend","kortest","vptest","kand"))]
        examples.append((bool(special),n,key,t,j1[0] if j1 else next(iter(d1)),special[0] if special else next(iter(d2))))
    for i,(_,n,key,t,a,b) in enumerate(sorted(examples,reverse=True)[:4],1):
        tag=f"when{i}"
        rows[tag]=dict(location=key,miss_off=n,miss_pgo=pg[2][key],source=t[:380],
             off=excerpt(gs[0],key,gs[1][key],tag,"gs_off",a),pgo=excerpt(pg[0],key,pg[1][key],tag,"gs_pgo",b))
    save(OUT/"machine/examples.json",rows)

if __name__=="__main__":
    main()
