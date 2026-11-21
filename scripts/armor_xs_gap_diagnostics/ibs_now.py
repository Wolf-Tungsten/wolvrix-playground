"""Get IBS branch classifications on the line-table binaries; separate from timed runs."""
import os
import resource
import subprocess
import sys
import time
from diagnostics import *
from grhsim_single_baseline import cpu_counters, idle_percent

def run(label):
    d = OUT/"lines"/label
    binary = Path(__import__("json").loads((d/"binary.json").read_text())["path"])
    for wl, image in IMAGES.items():
        folder = OUT/"ibs-isolated"/label/wl
        folder.mkdir(parents=True,exist_ok=True)
        if (folder/"ip.tsv").exists():
            continue
        start_core = {"gr_off":96, "gr_pgo":120, "gs_off":144, "gs_pgo":168}[label]
        candidates=list(range(start_core,start_core+24))
        for _ in range(120):
            test_cores=set(candidates)|{c+192 for c in candidates}
            before=cpu_counters(test_cores);time.sleep(2)
            idle=idle_percent(before,cpu_counters(test_cores))
            available=[c for c in candidates if min(idle[c],idle[c+192])>=99]
            if available:
                cpu=available[0]
                break
        else: raise RuntimeError("no idle core in allocated range")
        data = folder/"perf.data"
        if not data.exists():
            command = ["taskset","-c",str(cpu),"numactl","--membind=1","setarch","x86_64","-R",
                       "perf","record","-q","--no-buildid","--raw-samples","-e","ibs_op/cnt_ctl=1/","-c","800000",
                       "-o",data,"--","sh","-c",'exec "$@" 2>&1',"sh",binary,"-i",image,"--diff",NEMU,
                       "-b","0","-e","0","-s","0","-C",str(WINDOW)]
            save(folder/"command.json",list(map(str,command)))
            start=time.monotonic()
            usage=resource.getrusage(resource.RUSAGE_CHILDREN)
            before=cpu_counters({cpu,cpu+192})
            with (folder/"run.log").open("w") as log, (folder/"perf.log").open("w") as err:
                subprocess.run(command,env=clean_environment(),cwd=folder,stdout=log,stderr=err,check=True)
            elapsed=time.monotonic()-start
            end=resource.getrusage(resource.RUSAGE_CHILDREN)
            occupied=(end.ru_utime-usage.ru_utime+end.ru_stime-usage.ru_stime)/elapsed
            save(folder/"occupancy.json",dict(cpu=cpu,elapsed=elapsed,cpu_fraction=occupied,
                 sibling_idle=idle_percent(before,cpu_counters({cpu,cpu+192}))[cpu+192]))
        sig = signature(parse_run((folder/"run.log").read_text(),WINDOW))
        assert sig == expected(label,wl)
        save(folder/"signature.json",sig)
        env = dict(os.environ,ARMOR_IBS_WHAT="op",ARMOR_IBS_OUT=str(folder))
        execute(["perf","script","-i",data,"-s",ROOT/"scripts/armor_dispatch_ibs_handler.py"],"decode",folder,env)
        print(label,wl,"decoded",flush=True)

if __name__=="__main__":
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    run(sys.argv[1])
