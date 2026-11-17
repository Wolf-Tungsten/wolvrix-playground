#!/usr/bin/env python3
"""One serial PMU diagnostic per frozen ablation binary, after formal timing."""
import argparse
import csv
import json
import os
from pathlib import Path
import platform
import resource
import signal
import subprocess
import time

from grhsim_single_baseline import Baseline, ROOT, cpus, identity, save
from xiangshan_cv32_ablation_measure import (VARIANTS, CYCLES, ROUNDS, read, verify,
    signature, measurement_lock, freeze, check_frozen)

EVENTS = ('cycles:u', 'instructions:u', 'branches:u', 'branch-misses:u')


def parse_counts(path, guest_cycles):
    records = {}
    for cells in csv.reader(Path(path).read_text().splitlines()):
        if not cells or cells[0].startswith('#'):
            continue
        if len(cells) < 3 or cells[2] not in EVENTS:
            continue
        event = cells[2]
        if event in records or len(cells) < 5 or not cells[0].strip().isdigit():
            raise ValueError('invalid/duplicate PMU event: ' + str(cells))
        value, runtime, fraction = int(cells[0]), float(cells[3]), float(cells[4])
        if runtime <= 0 or fraction < 99 or fraction > 100:
            raise ValueError('PMU event missing or multiplexed below 99%: ' + str(cells))
        records[event] = dict(value=value, running_ns=runtime, running_percent=fraction)
    if set(records) != set(EVENTS) or guest_cycles <= 0:
        raise ValueError('incomplete PMU event set or invalid guest cycles')
    if any(records[event]['value'] <= 0 for event in EVENTS[:3]):
        raise ValueError('zero PMU cycle/instruction/branch count')
    return dict(events=records, guest_cycles=guest_cycles,
        per_guest_cycle={event: row['value']/guest_cycles for event, row in records.items()},
        ipc=records['instructions:u']['value']/records['cycles:u']['value'],
        branch_miss_fraction=records['branch-misses:u']['value']/records['branches:u']['value'])


class Observer:
    def __init__(self, directory):
        self.directory = directory
        self.process = None
        self.stream = None
        self.result = {}

    def start(self, pid, started):
        self.result = dict(pid=pid, attach_request_delay_s=time.monotonic()-started,
            command=['perf', 'stat', '-p', str(pid), '-x', ',', '--no-big-num', '--no-scale',
                     '-e', ','.join(EVENTS), '-o', str(self.directory/'stat.csv')],
            scope='Attach after process launch; excludes unknown short attach latency. Includes remaining initialization, model, harness and NEMU. Not pure eval, not a timed sample.')
        self.stream = (self.directory/'perf.log').open('w')
        self.process = subprocess.Popen(self.result['command'], stdout=self.stream,
                                        stderr=subprocess.STDOUT)

    def finish(self):
        if self.process is None:
            if self.stream is not None and not self.stream.closed:
                self.stream.close()
            return
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
        try:
            self.result['returncode'] = self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill(); self.result['returncode'] = self.process.wait()
            self.result['stop_timeout'] = True
        self.stream.close(); self.process = None
        save(self.directory/'observer.json', self.result)


def diagnose(source, measured, out):
    if not platform.node().startswith('node030'):
        raise ValueError('diagnose on node030')
    source, measured, out = (Path(p).resolve() for p in (source, measured, out))
    with measurement_lock():
        previous = read(measured/'manifest.json'); check_frozen(previous)
        performance = read(measured/'summary.json')
        if performance['status'] != 'pass' or len(performance['rounds']) != ROUNDS:
            raise ValueError('all eight formal rounds must finish before PMU diagnostics')
        if performance['manifest'] != identity(measured/'manifest.json'):
            raise ValueError('formal summary manifest identity changed')
        image, nemu = (Path(previous[key]['path']) for key in ('image', 'nemu'))
        manifest = freeze(source, image, nemu)
        if manifest['models'] != previous['models']:
            raise ValueError('diagnostic models differ from formally measured binaries')
        out.mkdir(parents=True, exist_ok=False)
        manifest.update(measurement=identity(measured/'summary.json'),
            formal_manifest=identity(measured/'manifest.json'), driver=identity(__file__),
            events=EVENTS, order=VARIANTS, runs_per_variant=1,
            policy='Post-timing diagnosis only; no generation feedback or additional candidate selection.')
        save(out/'manifest.json', manifest)
        try:
            os.sched_setaffinity(0, cpus(Path('/sys/devices/system/cpu/online').read_text()))
            resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
            save(out/'perf-environment.json',dict(
                version=subprocess.check_output(['perf','--version'],text=True),
                paranoid=Path('/proc/sys/kernel/perf_event_paranoid').read_text().strip()))
            results = {}
            for name in VARIANTS:
                model=manifest['models'][name]; settings=model['configuration']
                args=argparse.Namespace(output=out/name,binary=Path(model['binary']['path']),image=image,nemu=nemu,
                    compiler='/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++',tools_dir=None,
                    sim_primitives=settings.get('sim_primitives','none'),sim_models=settings.get('sim_models','hardware'),
                    behavior_state_lowering=settings.get('behavior_state_lowering','ordinary'),
                    behavior_compute_lowering=settings.get('behavior_compute_lowering','ordinary'),
                    rtl_difftest='on',model_difftest='on',compile_difftest='on',runtime_difftest='on',
                    simulator='grhsim',xs_config=settings.get('config','DefaultConfig'),
                    skip_idle_check=True,cpu=96,jobs=1,cycles=CYCLES,repeats=1)
                runner=Baseline(args); prepared=runner.prepare_measurement()
                old_plan=read(measured/name/'runs/runtime_plan.json')
                originals=lambda p:sorted((x['role'],json.dumps(x['source'],sort_keys=True)) for x in p['files'])
                if originals(old_plan)!=originals(prepared['plan']):
                    raise ValueError(name+': runtime dependencies differ from trace-verified run')
                observer=Observer(out/name)
                try:
                    row=runner.run_sample(prepared,'pmu',CYCLES,seed=0,process_observer=observer)
                finally:
                    observer.finish()
                if signature(row)!=performance['functional_signature']:
                    raise ValueError(name+': PMU functional signature differs')
                if observer.result.get('stop_timeout') or observer.result.get('returncode') not in (0,-signal.SIGINT,128+signal.SIGINT):
                    raise ValueError(name+': perf collection failed; see perf.log')
                row['diagnostic']=True
                save(prepared['directory']/'pmu.json',row)
                results[name]=dict(run=row,counts=parse_counts(out/name/'stat.csv',row['guest_cycles']),
                    observer=identity(out/name/'observer.json'),raw=identity(out/name/'stat.csv'))
                save(out/'results.json',results)
            check_frozen(previous); check_frozen(manifest)
            result=dict(status='pass',models=results,manifest=identity(out/'manifest.json'),
                limits='One attached PMU run per binary. No confidence interval; not timing samples. Attach excludes a short unmeasured launch interval.')
            save(out/'summary.json',result)
            print(json.dumps({k:v['counts'] for k,v in results.items()},indent=2))
            return result
        except Exception as error:
            save(out/'failure.json',dict(error=str(error),type=type(error).__name__,time=time.time()))
            raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--measurement',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();diagnose(args.source,args.measurement,args.output)
