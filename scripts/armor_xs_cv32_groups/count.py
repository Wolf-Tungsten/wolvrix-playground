"""User-mode PMU counts for the same window. Run separately from timing on node029."""
from pathlib import Path
import csv
import os
import platform
import resource
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'build/armor-xs-cv32-groups-v1'
sys.path.insert(0, str(ROOT / 'scripts'))
from armor_dispatch_diag import pick_cpu
from grhsim_single_baseline import identity, parse_run, save
from xiangshan_cv32_ablation_measure import read, signature

resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
names = sys.argv[1:] or ['base','full','events','mux','views']
events = ['instructions:u','branches:u','branch-misses:u','ic_cache_fill_l2:u']
cpu, _ = pick_cpu()
for name in names:
    ref = OUT/'correctness'/name
    valid = read(ref/'result.json')
    dest = OUT/name/'pmu'
    dest.mkdir()
    rt = ref/'runtime'
    binary = rt/'bin/emu'
    if identity(binary)['sha256'] != valid['binary']['sha256']:
        raise ValueError('different executable for ' + name)
    argv = ['taskset', '-c',str(cpu),'numactl','--membind=1','setarch','x86_64','-R',
            'perf','stat','-x,','-e',','.join(events),'-o',str(dest/'stat.csv'),'--',
            str(binary),'-i',str(rt/'image/workload.bin'),'--diff',str(rt/'ref/nemu.so'),
            '-b','0','-e','0','-s','0','-C','100000']
    with (dest/'run.log').open('w') as log:
        subprocess.run(argv,cwd=rt/'bin',env=dict(os.environ,LC_ALL='C',LD_LIBRARY_PATH=str(rt/'lib')),
                       stdout=log,stderr=subprocess.STDOUT,check=True)
    row = parse_run((dest/'run.log').read_text(),100000)
    if signature(row) != valid['signature']:
        raise ValueError(name + ' PMU endpoint mismatch')
    metrics = {}
    with (dest/'stat.csv').open() as stream:
        for fields in csv.reader(stream):
            if len(fields)>4 and fields[2] in events:
                metrics[fields[2]] = {'count':int(fields[0]),'running_percent':float(fields[4]),
                                       'per_guest_cycle':int(fields[0])/row['guest_cycles']}
    if set(metrics) != set(events) or any(r['running_percent']<99 for r in metrics.values()):
        raise ValueError('missing or multiplexed PMU counters')
    save(dest/'result.json',dict(events=metrics, binary=valid['binary'], signature=signature(row),
                                 command=argv,cpu=cpu,host=platform.node()))
    print(name, round(metrics['instructions:u']['per_guest_cycle']),flush=True)
