"""Paired timing of the verified sparse prototype and the published default on node030 CPU96."""
import argparse
import platform
import resource
import time
from diagnostics import *
from armor_xs_current_gap import BINS, Baseline, LOCK, measurement_lock, run_one
from xiangshan_cv32_ablation_measure import read

def main():
    assert platform.node().split(".")[0]=="node030"
    out=OUT/"pair030"
    out.mkdir(exist_ok=True)
    with measurement_lock(LOCK,wait=True):
        root=out/str(time.time_ns());root.mkdir()
        output=out/"rounds.json"
        rows=read(output) if output.exists() else {wl:[] for wl in IMAGES}
        prepared={}
        for idx,group in enumerate((1,2,1,2),1):
            for wl in (list(IMAGES) if idx%2 else list(reversed(IMAGES))):
                if len(rows[wl])>=idx:continue
                order=["gr_pgo","sparse"]
                if (idx in (1,4))==(wl=="microbench"):order.reverse()
                for n in order:
                    if (wl,n) in prepared: continue
                    opts=argparse.Namespace(output=root/wl/n,binary=BINS["gr_pgo"] if n=="gr_pgo" else OUT/"sparse/build/emu",
                         simulator="grhsim",compiler=LLVM/"clang++",cpu=96,cycles=WINDOW,jobs=1,repeats=4,
                         tools_dir=None,sim_primitives="none",image=IMAGES[wl],nemu=NEMU,skip_idle_check=False)
                    p=Baseline(opts).prepare_measurement()
                    prepared[wl,n]=p
                    for attempt in range(100):
                        try:
                            run_one(p,wl,n,1,p["directory"]/f"warm-{attempt}")
                            break
                        except RuntimeError as err:
                            if "SMT busy" not in str(err) and "multiplexed" not in str(err):raise
                    else:raise RuntimeError("warmup exhausted")
                for attempt in range(100):
                    row=dict(round=idx,cpu=96,order=order,group=group)
                    try:
                        for n in order:
                            p=prepared[wl,n]
                            before=resource.getrusage(resource.RUSAGE_CHILDREN)
                            row[n]=run_one(p,wl,n,group,p["directory"]/f"r{idx}-{attempt}")
                            after=resource.getrusage(resource.RUSAGE_CHILDREN)
                            ratio=(after.ru_utime-before.ru_utime+after.ru_stime-before.ru_stime)/row[n]["external_wall_s"]
                            row[n]["cpu_fraction"]=ratio
                            if ratio<.97: raise RuntimeError("competing process")
                    except RuntimeError as err:
                        if all(s not in str(err) for s in ("SMT busy","multiplexed","competing process")):raise
                        print("retry",wl,idx,err,flush=True)
                        continue
                    rows[wl].append(row);save(output,rows)
                    print("paired",wl,idx,100*(row["sparse"]["external_wall_s"]/row["gr_pgo"]["external_wall_s"]-1),flush=True)
                    break
                else: raise RuntimeError("paired block retries exhausted")
if __name__=="__main__":
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    main()
