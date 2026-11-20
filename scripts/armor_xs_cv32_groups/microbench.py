"""Second workload, default versus all, on a separate host from the primary CoreMark run."""
from pathlib import Path
import os
import platform
import resource
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'build/armor-xs-cv32-groups-v1'
sys.path.insert(0, str(ROOT/'scripts'))
from armor_dispatch_diag import runtime, pick_cpu
from armor_mask_layout_measure import FIRMWARE
from grhsim_difftrace import compare_traces, validate_trace_coverage
from grhsim_single_baseline import cpu_counters, cpus, identity, idle_percent, parse_run, save
from grhsim_single_compare import summarize
from xiangshan_cv32_ablation_measure import read, signature, verify

names = ['base','full']
ref = ROOT/'build/armor-expression-default-v1/microbench-default'
firmware = FIRMWARE/'microbench.bin'
comp = ROOT/'build/armor-dispatch-v1/timing-v1/trace-comparator/compare'
dest = OUT/'microbench'
if len(sys.argv) == 1:
    cpu,_ = pick_cpu()
    # Stage each private runtime on the same NUMA node that will execute it.
    os.execvp('numactl',['numactl','--physcpubind='+str(cpu),'--membind=1',sys.executable,__file__,str(cpu)])
cpu = int(sys.argv[1])
resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
siblings = cpus(Path(f'/sys/devices/system/cpu/cpu{cpu}/topology/thread_siblings_list').read_text())
expected = signature(read(ref/'result.json'))
orders = [names, names[::-1], names, names[::-1]]
dest.mkdir()
save(dest/'policy.json',dict(host=platform.node(),cpu=cpu,siblings=sorted(siblings),numa=1,
     aslr=False,cycles=100000,orders=orders,firmware=identity(firmware)))
setups = {}
for n in names:
    binary = read(OUT/n/'binary.json')
    verify(binary)
    rt, env, emu = runtime(dest/n,Path(binary['path']))
    shutil.copy2(firmware,rt/'image/workload.bin')
    if identity(rt/'image/workload.bin')['sha256'] != identity(firmware)['sha256']:
        raise ValueError('staged firmware differs')
    setups[n]=(rt,env,['setarch','x86_64','-R',*emu,'-C','100000'])
def sample(n,label,extra=()):
    rt,env,cmd=setups[n]
    logpath = dest/n/(label+'.log')
    before=cpu_counters(siblings)
    with logpath.open('w') as log:
        start=time.monotonic()
        result=subprocess.run([*cmd,*extra],cwd=rt/'bin',env=env,stdout=log,stderr=subprocess.STDOUT)
        wall=time.monotonic()-start
    result.check_returncode()
    idle=idle_percent(before,cpu_counters(siblings))
    row=parse_run(logpath.read_text(),100000)
    if signature(row)!=expected:
        raise ValueError(n+' endpoint mismatch')
    row.update(external_wall_s=wall,cpu=cpu,sibling_idle=idle,command=[*cmd,*extra])
    save(dest/n/(label+'.json'),row)
    return row
for name in names:
    row=sample(name,'verify',('--dump-difftrace','./trace_s0'))
    path=dest/name/'trace.json'
    trace=compare_traces(comp,ref/'runtime/bin/trace_s0',setups[name][0]/'bin/trace_s0',path)
    trace['coverage']=validate_trace_coverage(trace,row)
    save(path,trace)
    print('verified',name,trace['records'],flush=True)
for n in names:
    sample(n,'warmup')
rows=[]
for i,order in enumerate(orders,1):
    row={'round':i,'order':order}
    for n in order:
        row[n]=sample(n,'round'+str(i))
    rows.append(row)
    save(dest/'rounds.json',rows)
    print(i, {n:round(row[n]['external_wall_s'],3) for n in names}, flush=True)
save(dest/'summary.json',summarize([{k:{'host_ms':1000*r[n]['external_wall_s']} for k,n in zip(('A','B'),names)} for r in rows]))
