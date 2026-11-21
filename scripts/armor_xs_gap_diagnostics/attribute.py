import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys

from machine import BINS, Disassembler, Elf, LLVM, OUT, ROOT, phase, source_dir, save
from source_categories import GsimClassifier, bucket, classify_grhsim, read_lcov
from armor_dispatch_ibs import BASE, read_rows, symbolize


def gr_kind(t, ph):
    if ph == "commit" and "std::memcmp(" in t:
        return "enable block compare" if "disabled_commit_guards" in t else "data block compare"
    if t.startswith("if (grhsim_changed_"):
        return "change compare"
    if t.startswith("if (") and "conditional_mux" in t:
        return "mux control"
    return classify_grhsim(t, ph)


def gs_kind(t, g):
    if t.startswith("if (") and "$old$" in t and t.endswith(") {"):
        return g.subject(t) + ": change branch"
    return g(t)


def cover(label,wl,registers):
    gs = label.startswith("gs")
    folder = OUT / "coverage"/label/wl
    result = folder / "sites-mix.json"
    if result.exists() or not (folder/"model.lcov").exists(): return
    counts,sites = Counter(), Counter()
    cycles = json.loads((folder/"endpoint.json").read_text())["guest_cycles"]
    for src, lines, _ in read_lcov(folder/"model.lcov"):
        path = Path(src)
        if not re.fullmatch(r"SimTop\d+\.cpp" if gs else r"grhsim_SimTop_sched_\d+\.cpp",path.name):
            continue
        g = GsimClassifier(registers)
        ph = None
        with path.open() as stream:
            for no,line in enumerate(stream,1):
                if line.startswith("void "):
                    ph = "commit" if "::eval_commit_batch_" in line else "compute" if "::eval_compute_batch_" in line or "::subStep" in line else None
                if not ph or no not in lines:
                    continue
                t=line.strip()
                if not t or t.startswith(("//","#")): continue
                cat = gs_kind(t,g) if gs else ph+"|"+gr_kind(t,ph)
                counts[cat] += lines[no]; sites[cat]+=1
    save(result,dict(sites=sites,executions=counts,per_guest={k:n/cycles for k,n in counts.items()}))


def classify_files(model,gs,wanted,registers):
    info={}
    for name,numbers in wanted.items():
        ph=None; g=GsimClassifier(registers)
        with (model/name).open() as stream:
            for i,line in enumerate(stream,1):
                if line.startswith("void "):
                    ph="commit" if "::eval_commit_batch_" in line else "compute" if "::eval_compute_batch_" in line or "::subStep" in line else None
                # Identify the subject even when the preceding old/cond line had no samples.
                if gs and (("$old$" in line and " = " in line) or "bool cond_" in line):
                    g.subject(line.strip())
                if i in numbers and ph:
                    t = line.strip()
                    cat = gs_kind(t,g) if gs else ph+"|"+gr_kind(t,ph)
                    b = bucket("gsim" if gs else "grhsim",cat)
                    info[name,i] = (b,cat)
    return info


def attribute(label,wl,registers):
    folder=OUT/"machine"/label/wl
    ibs=OUT/"ibs-isolated"/label/wl
    if not (folder/"model-ips.tsv").exists() or not (ibs/"meta.json").exists(): return
    if (folder/"attribution.json").exists(): return
    elf=Elf(BINS[label]); debug=Elf(next((OUT/"lines"/label/"work").glob("*-compile/emu")))
    a=elf.sec[".text"]; b=debug.sec[".text"]
    exact=elf.data[a[1]:a[1]+a[2]]==debug.data[b[1]:b[1]+b[2]]
    mc=Disassembler()
    events=("cycles","instructions","branch-misses","ibs-ops","ibs-misses")
    by_addr=defaultdict(Counter)
    totals=Counter(); unverified=Counter()
    sizes_match={}
    for line in (folder/"model-ips.tsv").read_text().splitlines():
        addr, *counts = line.split()
        p=int(addr,16); sym=elf.function(p)
        if sym not in debug.funcs or debug.funcs[sym][1] != elf.funcs[sym][1]:
            for ev,n in zip(events,counts): unverified[ev]+=int(n)
            continue
        q=debug.funcs[sym][0]+p-elf.funcs[sym][0]
        if not exact:
            dat=elf.code(p,16)
            length=mc.lib.LLVMDisasmInstruction(mc.ctx,dat,len(dat),p,mc.buf,len(mc.buf))
            if not length or dat[:length]!=debug.code(q,length):
                for ev,n in zip(events,counts): unverified[ev]+=int(n)
                continue
        for ev,n in zip(events,counts): by_addr[q][ev]+=int(n)
    sm=json.loads((folder/"summary.json").read_text())
    for ev, phases in sm["phase"].items(): totals[ev]=sum(phases.values())
    for ip,(row,dso,sym) in read_rows(ibs,6).items():
        totals["ibs-ops"]+=row[0]; totals["ibs-misses"]+=row[3]
        if dso.endswith("/emu") and BASE <= ip < BASE+debug.sec[".text"][0]+debug.sec[".text"][2]:
            p=ip-BASE
            if phase(debug.function(p) or "") in ("compute","commit","subStep","model-other"):
                by_addr[p]["ibs-ops"]+=row[0];by_addr[p]["ibs-misses"]+=row[3]
    located=symbolize(debug.path,sorted(by_addr),folder)
    model=source_dir(label); gs=label.startswith("gs")
    wanted=defaultdict(set)
    for fn,ln,*_ in located.values():
        nm=Path(fn).name
        if ln>0 and re.fullmatch(r"SimTop\d+\.cpp" if gs else r"grhsim_SimTop_sched_\d+\.cpp",nm):
            wanted[nm].add(ln)
    info=classify_files(model,gs,wanted,registers)
    buckets,details = defaultdict(Counter),defaultdict(Counter)
    top=defaultdict(Counter)
    for addr,v in by_addr.items():
        fn,ln,fun,inner=located.get(addr,("",0,"",""))
        ph=phase(debug.function(addr) or "")
        item=info.get((Path(fn).name,ln))
        if item: categ,detail=item
        elif ph=="commit": categ,detail="register update","commit|no line"
        else: categ,detail="model, no statement line","model, no statement line"
        key=Path(fn).name+":"+str(ln)
        for ev,n in v.items():
            if not n: continue
            buckets[ev][categ]+=n;details[ev][detail]+=n
            if item: top[categ][key]+=n if ev=="cycles" else 0
    for ev in events:
        if unverified[ev]: buckets[ev]["machine code differs"]=unverified[ev]
        buckets[ev]["outside model"]=totals[ev]-sum(buckets[ev].values())
    save(folder/"attribution.json",dict(total=totals,buckets=buckets,details=details,whole_text_exact=exact,
         top_lines={k:v.most_common(12) for k,v in top.items()},unverified=unverified))
    print(label,wl,buckets["cycles"],flush=True)


if __name__=="__main__":
    cmd,label=sys.argv[1:3]
    regs=set((OUT/"gs-registers.txt").read_text().splitlines())
    for wl in sys.argv[3:] or ("coremark","microbench"):
        (attribute if cmd=="profile" else cover)(label,wl,regs)
