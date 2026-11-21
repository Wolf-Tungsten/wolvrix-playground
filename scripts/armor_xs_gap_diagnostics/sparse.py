"""Test whether cold change paths of hot scalar materializations can avoid unconditional writes."""
from collections import Counter
import json
from pathlib import Path
import re
import resource
import sys

from diagnostics import *
from watch import GR

SOURCE=DEFAULT/"pgo/model"

def eligible(lines):
    """Match one scalar update with only masked reader updates, an optional boolean accumulator and a store."""
    i=0
    while i<len(lines):
        row=lines[i]
        m=GR.match(row) if b"const bool grhsim_changed_" in row else None
        if not m:
            yield row
            i+=1
            continue
        _, changed, expr=m.groups()
        slot=expr[1:].partition(b" != ")[0]
        body=[]
        for j in range(i+1,min(len(lines),i+15)):
            t=lines[j].strip()
            if t == slot+b" = next_value;":
                if body:
                    yield (int(changed.rsplit(b"_",1)[1]), i+1, row, lines[i+1:j+1])
                    i=j
                else:
                    yield row
                break
            if changed in t and t.endswith(b";") and (t.startswith(b"grhsim_any_changed_") or
                (t.startswith(b"supernode_active_curr_[") and b" |= " in t) or t.startswith(b"grhsim_or_active_u")):
                body.append(t)
            else:
                yield row
                break
        else:
            yield row
        i+=1

def record_source(directory, measure, chosen=None):
    directory.mkdir(parents=True,exist_ok=True)
    rows=[]; target=0
    for p in sorted(SOURCE.iterdir()):
        if p.suffix not in (".cpp",".hpp",".h") and p.name!="Makefile": continue
        dest=directory/p.name
        if "_sched_" not in p.name or b"::eval_compute_batch_" not in p.read_bytes()[:16000]:
            if not dest.exists(): dest.symlink_to(p)
            continue
        with dest.open("wb") as stream:
            if measure: stream.write(b'#include "xs_sparse.hpp"\n')
            for item in eligible(p.read_bytes().splitlines(keepends=True)):
                if isinstance(item,bytes):
                    stream.write(item)
                    continue
                value,line,decl,effects=item
                name=b"grhsim_changed_%d"%value
                stream.write(decl)
                key=len(rows)
                rows.append((key,p.name,line,value,len(effects)-1))
                if measure:
                    stream.write(b"            xs_sparse::hit(%du, %s);\n" % (key,name))
                    stream.writelines(effects)
                elif key in chosen:
                    stream.write(b"            if (unlikely("+name+b")) {\n")
                    for effect in effects:
                        stream.write(b"    "+effect.replace(name,b"true"))
                    stream.write(b"            }\n")
                    target+=1
                else:
                    stream.writelines(effects)
    if measure:
        header='''#pragma once
#include <cstdio>
#include <cstdlib>
namespace xs_sparse {
struct Row { unsigned long long calls, changes; };
inline Row counters[COUNT]{};
inline void hit(unsigned i,bool changed){ ++counters[i].calls; counters[i].changes+=changed; }
struct Dump { ~Dump(){ if(auto f=std::fopen(std::getenv("XS_SPARSE_OUT"),"wb")){
    std::fwrite(counters,sizeof(Row),COUNT,f);std::fclose(f); } } };
inline Dump dump;
}
'''.replace("COUNT",str(len(rows)))
        (directory/"xs_sparse.hpp").write_text(header)
        with (OUT/"sparse-sites.tsv").open("w") as f:
            for row in rows: f.write("\t".join(map(str,row))+"\n")
    return len(rows),target

def make_pgo(model,dest):
    xs=ROOT/"testcase/xiangshan"
    gateway=ROOT/"build/armor-expression-default-v1/default/chisel-home/build/generated-src"
    cmd=["make","--no-print-directory","-o","xs_wolf_grhsim_emit","xs_wolf_grhsim_emu","WOLF_ENV_SOURCED=1",
         f"PGO_WORKLOAD={IMAGES['coremark']}",f"XS_GRHSIM_BUILD={dest/'build'}",f"XS_WOLF_GRHSIM_EMIT_DIR={model}",
         f"XS_LOG_DIR={dest/'logs'}",f"XS_DIFFTEST_GEN_DIR={gateway}",f"XS_DIFFTEST_MACROS={gateway/'DifftestMacros.svh'}",
         f"CXX={LLVM/'clang++'}",f"CC={LLVM/'clang'}",f"AR={LLVM/'llvm-ar'}",f"LLVM_PROFDATA={LLVM/'llvm-profdata'}",
         "PYTHON=/usr/bin/python3","XS_VM_BUILD_JOBS=24","GRHSIM_MODEL_BUILD_JOBS=24","EMU_RANDOMIZE=0",
         "NUM_CORES=1","EMU_THREADS=0","NO_DIFF=0","EMU_TRACE=","PGO_BOLT=0","XS_WITH_CHISELDB=0","XS_WITH_CONSTANTIN=0"]
    execute(cmd,"pgo",dest,clean_environment(),ROOT)

def main():
    instrument=OUT/"sitewatch/gr_pgo"
    sites=OUT/"sparse-sites.tsv"
    if not sites.exists():
        print("eligible",record_source(instrument/"work/model",True),flush=True)
    _,binary=build("gr_pgo","sitewatch")
    raw=instrument/"sites.bin"
    if not raw.exists():
        cpu,_=pick_cpu()
        cmd=["taskset","-c",str(cpu),"numactl","--membind=1","setarch","x86_64","-R",binary,
             "-i",IMAGES["coremark"],"--diff",NEMU,"-b","0","-e","0","-s","0","-C",str(WINDOW)]
        execute(cmd,"train-sites",instrument,dict(clean_environment(),XS_SPARSE_OUT=str(raw)),instrument)
        assert signature(parse_run((instrument/"train-sites.log").read_text(),WINDOW))==expected("gr_pgo","coremark")
    import struct
    vals=list(struct.iter_unpack("<QQ",raw.read_bytes()))
    desc=[l.split() for l in sites.read_text().splitlines()]
    assert len(vals)==len(desc)
    chosen={i for i,(n,c) in enumerate(vals) if n>=WINDOW//4 and c*200<=n}
    assert chosen
    dest=OUT/"sparse"
    if not (dest/"selection.json").exists():
        size,n=record_source(dest/"model",False,chosen)
        assert len(vals)==size and len(chosen)==n
        save(dest/"selection.json",dict(sites=size,selected=n,visits=sum(vals[i][0] for i in chosen),
             changes=sum(vals[i][1] for i in chosen),guarded_effects=sum(vals[i][0]*int(desc[i][4]) for i in chosen),
             min_visits=WINDOW//4,max_change_fraction=.005))
    if not (dest/"build/emu").exists(): make_pgo(dest/"model",dest)
    print((dest/"selection.json").read_text(),flush=True)
if __name__=="__main__":
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    main()
