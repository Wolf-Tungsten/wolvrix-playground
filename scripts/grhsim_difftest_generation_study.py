#!/usr/bin/env python3
"""Build matched native GrhSIM models with/without generated DiffTest hardware.

Both variants compile and run without DiffTest collection or reference checking.
Use a fresh output directory; build and measurement are separate stages.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import os
from pathlib import Path
import platform
import resource
import shutil
import subprocess
import sys

from grhsim_single_baseline import Baseline, ROOT, cpus, identity, save


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['build','measure'])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--tools-dir',type=Path,default=ROOT/'build/grhsim32-tools')
    parser.add_argument('--compiler',default='/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++')
    parser.add_argument('--jobs',type=int,default=32)
    args=parser.parse_args()
    if not platform.node().startswith('node030'):raise ValueError('this experiment requires node030')
    os.sched_setaffinity(0,cpus(Path('/sys/devices/system/cpu/online').read_text()))
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    out=args.output.resolve()
    if args.command=='build':out.mkdir(parents=True,exist_ok=False)
    with (out/'study.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.command=='measure':
            subprocess.run([sys.executable,ROOT/'scripts/grhsim_single_compare.py',
                '--baseline',out/'A','--candidate',out/'B','--output',out/'comparison-v1',
                '--runtime-difftest','off','--candidate-sim-primitives','none',
                '--pairs','8','--cycles','100000'],check=True,cwd=ROOT)
            return
        frozen=out/'tools-frozen'
        shutil.copytree(args.tools_dir.resolve()/'python',frozen/'python')
        save(frozen/'identity.json',[identity(p) for p in sorted(frozen.rglob('*')) if p.is_file()])
        work={}
        for name,mode in [('A','on'),('B','off')]:
            config=argparse.Namespace(output=out/name,tools_dir=frozen,compiler=args.compiler,
                jobs=args.jobs,cpu=96,cycles=100000,repeats=8,sim_primitives='none',
                rtl_difftest=mode,runtime_difftest='off')
            work[name]=Baseline(config)
            work[name].snapshot()
        if (out/'A/sources.json').read_bytes()!=(out/'B/sources.json').read_bytes():
            raise ValueError('source identity changed between A/B snapshots')
        save(out/'experiment.json',dict(driver=identity(__file__),
            variants={n:dict(rtl_difftest=w.rtl_difftest,runtime_difftest=w.runtime_difftest)
                      for n,w in work.items()},tools=identity(frozen/'identity.json'),
            sources=identity(out/'A/sources.json'),cpu=96,cycles=100000,pairs=8))
        # Mill shares its incremental outputs: never elaborate A and B together.
        for name in ('B','A'):
            work[name].stage('fresh RTL '+name)
            work[name].rtl()
        def model(name):
            try:
                work[name].emit()
                work[name].compile()
                work[name].stage('build complete '+name)
            except Exception as error:
                work[name].stage('failed: '+str(error))
                raise
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(model,name) for name in ('A','B')]
            for future in futures:future.result()


if __name__=='__main__':main()
