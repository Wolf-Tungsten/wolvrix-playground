#!/usr/bin/env python3
"""Run the existing 8-pair comparison only with CPU96-127 and the SMT sibling idle."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from grhsim_single_baseline import Baseline, cpu_counters, cpus, idle_percent, save
import grhsim_single_compare as compare


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--control',action='store_true',help='same-binary A/A noise control')
    p.add_argument('--verify-only',action='store_true',help='stop after functional gates')
    p.add_argument('--image',type=Path,help='override the CoreMark image for a directed workload')
    p.add_argument('--verification-from',type=Path,
                   help='reuse verified traces after comparator checks binary/input identities')
    args=p.parse_args(); study=args.study.resolve()
    if not (study/'build-complete.json').exists(): raise ValueError('matched build is incomplete')
    original=Baseline.run_sample
    region=set(range(96,128)) | cpus(Path('/sys/devices/system/cpu/cpu96/topology/thread_siblings_list').read_text())
    def checked(self, prepared, name, *a, **kw):
        # The monitor and its hash/JSON work must not count as load on CPUs
        # whose idleness gates the experiment. taskset still pins the emu to 96.
        monitor_cpus=cpus(Path('/sys/devices/system/cpu/online').read_text())-region
        os.sched_setaffinity(0,monitor_cpus)
        records=[]
        idle_windows=0
        while True:
            before=cpu_counters(region); time.sleep(5); idle=idle_percent(before,cpu_counters(region))
            records.append(dict(time=time.time(),idle=idle))
            save(prepared['directory']/(name+'.region-preflight.json'),records)
            idle_windows=idle_windows+1 if min(idle.values()) >= 98 else 0
            if idle_windows >= 3: break
            print('[region-wait] waiting for 15 idle seconds on CPU96-127 and CPU96 SMT sibling',flush=True)
        start=cpu_counters(region)
        result=original(self,prepared,name,*a,**kw)
        activity=idle_percent(start,cpu_counters(region))
        busy={c:v for c,v in activity.items() if c!=96 and v<98}
        save(prepared['directory']/(name+'.region-during.json'),dict(idle=activity,busy=busy))
        if busy and name.startswith('pair'):
            raise RuntimeError('region became busy; logs retained, comparison stopped: '+str(busy))
        if busy:
            print('[region-diagnostic] load during non-timed '+name+': '+str(busy),flush=True)
        return result
    Baseline.run_sample=checked
    sys.argv=['grhsim_single_compare.py','--baseline',str(study/'A'),
        '--candidate',str(study/('A' if args.control else 'B')),'--output',str(args.output.resolve()),
        '--runtime-difftest','on','--candidate-sim-primitives','none','--pairs','8','--cycles','100000']
    if args.verification_from:
        sys.argv+=['--verification-from',str(args.verification_from.resolve())]
    if args.image:
        sys.argv+=['--image',str(args.image.resolve())]
    if args.verify_only:
        sys.argv+=['--verify-only']
    compare.main()

if __name__=='__main__': main()
