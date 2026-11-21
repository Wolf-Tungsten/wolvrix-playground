"""Join individual scalar sites to the same scheduler's producer cluster, unique reader and capacity."""
import array
from collections import defaultdict, Counter
from pathlib import Path
import struct
import subprocess
import sys
import time
from diagnostics import *

def main():
    point=OUT/"sitewatch/gr_pgo"
    while not (point/"sites.bin").exists() or not (OUT/"audit/single-reader.tsv").exists():
        time.sleep(8)
    raw=point/"micro.bin"
    if not raw.exists():
        exe=Path(__import__("json").loads((point/"binary.json").read_text())["path"])
        cpu,_=pick_cpu()
        cmd=["taskset","-c",str(cpu),"numactl","--membind=1","setarch","x86_64","-R",exe,
             "-i",IMAGES["microbench"],"--diff",NEMU,"-b","0","-e","0","-s","0","-C",str(WINDOW)]
        execute(cmd,"micro",point,dict(clean_environment(),XS_SPARSE_OUT=str(raw)),point)
        assert signature(parse_run((point/"micro.log").read_text(),WINDOW))==expected("gr_pgo","microbench")
    src=(ROOT/"scripts/armor_single_reader_audit.cpp").read_text()
    before="        if (!ordinary[value] || source == missing || targets.size() != 1) continue;"
    assert src.count(before)==1
    dest=OUT/"audit"
    src=src.replace("    Dump fanout(", '    std::ofstream classification("value-classes.bin", std::ios::binary);\n    Dump fanout(')
    src=src.replace(before,'''        char code = 0;
        if (ordinary[value] && source != missing) {
            if (targets.size() > 1) code = 1;
            else if (targets.size() == 1) {
                const Id target = targets.front();
                if (groupOps.at(target) == 0) code = 2;
                else if (groupOps[target] + clusterOps[source] > 160) code = 3;
                else if (earliest[source] < rank[target]) code = 4;
                else code = 5;
            }
        }
        classification.write(&code, 1);
'''+before)
    (dest/"weighted.cpp").write_text(src)
    subprocess.run([LLVM/"clang++","-O2","-std=c++20",dest/"weighted.cpp","-o",dest/"weighted"],check=True)
    with (dest/"weighted-stat.tsv").open("w") as f:
        subprocess.run([dest/"weighted",dest/"stages","160"],cwd=dest,stdout=f,check=True)
    assert (dest/"weighted-stat.tsv").read_text()==(dest/"single-reader.tsv").read_text().split("192\t")[0]
    groups=(dest/"value-classes.bin").read_bytes()
    names=["other/source/internal","multiple external targets","only commit target","only compute, capacity",
           "only compute, order","only compute, fits and order"]
    static=[groups.count(i) for i in range(6)]
    assert sum(static[2:])==580240,static
    ids=[int(l.split()[3]) for l in (OUT/"sparse-sites.tsv").read_text().splitlines()]
    output={}
    for wl,stats in (("coremark",point/"sites.bin"),("microbench",raw)):
        rows=[Counter() for _ in range(6)]
        data=list(struct.iter_unpack("<QQ",stats.read_bytes()))
        assert len(data)==len(ids)
        for val,(n,c) in zip(ids,data):
            row=rows[groups[val-1]]
            row.update({"sites":1,"executions":n,"changes":c})
        output[wl]=dict(zip(names,rows))
    save(dest/"weighted.json",dict(static=dict(zip(names,static)),dynamic=output))
if __name__=="__main__":
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    main()
