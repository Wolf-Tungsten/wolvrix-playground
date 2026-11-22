"""Counterbalanced node-local runs. Each workload stays on its own physical core."""
import fcntl, json, os, platform, resource, subprocess, sys, time
from argparse import ArgumentParser
from pathlib import Path
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/"scripts"))
import armor_xs_current_gap as gap
from grhsim_numa import runtime_plan
from grhsim_single_baseline import clean_environment, identity, save
base=root/"build/armor-xs-site-pgo-v1"
bins={"baseline":gap.BINS["gr_pgo"],"gs_pgo":gap.BINS["gs_pgo"],"proto05":gap.OUT/"sparse/build/emu"}
def main():
    parser=ArgumentParser()
    parser.add_argument("group")
    parser.add_argument("wl")
    parser.add_argument("cpu",type=int)
    parser.add_argument("variants",nargs="+")
    parser.add_argument("--rounds",type=int,default=2)
    args=parser.parse_args()
    assert platform.node().startswith("node030")
    cache=Path(f"/sys/devices/system/cpu/cpu{args.cpu}/cache/index3/id").read_text().strip()
    cache_lock=(base/f"node030-l3-{cache}.lock").open("a")
    fcntl.flock(cache_lock,fcntl.LOCK_EX)
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    gap.OUT=base
    dest=base/"pairs"/args.group/args.wl
    dest.mkdir(exist_ok=True,parents=True)
    rowsfile=dest/"rounds.json"
    rows=json.loads(rowsfile.read_text()) if rowsfile.exists() else []
    session=dest/str(time.time_ns())
    session.mkdir()
    cpu=args.cpu
    pids={}
    for tag in args.variants:
        exe=bins.get(tag,base/tag/"build/emu")
        if not exe.is_file():raise RuntimeError(str(exe))
        folder=session/tag
        folder.mkdir()
        rt=folder/"runtime"
        env=dict(clean_environment(),LC_ALL="C",EMU_PROGRESS_EVERY_CYCLES="0")
        plan=runtime_plan(exe,gap.NEMU,gap.IMAGES[args.wl],rt,cpu,1,env)
        save(folder/"plan.json",plan)
        subprocess.run(["taskset","-c",str(cpu),"numactl","--membind=1",sys.executable,root/"scripts/grhsim_numa.py",folder/"plan.json"],check=True)
        staged=rt/"bin/emu"
        siblings=Path(f"/sys/devices/system/cpu/cpu{cpu}/topology/thread_siblings_list").read_text().strip()
        pids[tag]=dict(cpu=cpu,siblings=set(map(int,siblings.split(","))),directory=folder,binary=staged,original_binary=identity(exe),
                       plan=json.loads((rt/"manifest.json").read_text()),runtime=dict(env,LD_LIBRARY_PATH=str(rt/"lib")),
                       base=["taskset","-c",str(cpu),"numactl","--membind=1","setarch","x86_64","-R",str(staged),
                             "-i",str(rt/"image/workload.bin"),"--diff",str(rt/"ref/nemu.so"),"-b","0","-e","0","-s","0"])
    for i in range(len(rows),args.rounds):
        order=args.variants.copy()
        if (i%4 in (1,2)) != (args.wl=="microbench"):order.reverse()
        row={"order":order,"cpu":cpu}
        for tag in order:
            p=pids[tag]
            for attempt in range(12):
                try:
                    before=resource.getrusage(resource.RUSAGE_CHILDREN)
                    result=gap.run_one(p,args.wl,tag,1,p["directory"]/f"r{i+1}-{attempt}")
                    after=resource.getrusage(resource.RUSAGE_CHILDREN)
                    result["cpu_fraction"]=(after.ru_utime-before.ru_utime+after.ru_stime-before.ru_stime)/result["external_wall_s"]
                    if result["cpu_fraction"]<.97:raise RuntimeError("competing process")
                except RuntimeError as err:
                    if all(t not in str(err) for t in ("competing process","SMT busy","multiplexed")):raise
                    print("retry",tag,err,flush=True)
                else:break
            else:raise RuntimeError("exhausted")
            row[tag]=result
        rows.append(row)
        save(rowsfile,rows)
if __name__=="__main__":main()
