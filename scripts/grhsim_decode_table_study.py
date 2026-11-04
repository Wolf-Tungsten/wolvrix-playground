#!/usr/bin/env python3
"""Matched full XiangShan decode-table build and CPU96 single-model measurements."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
import fcntl
import json
import os
from pathlib import Path
import platform
import re
import resource
import shutil
import subprocess
import sys

from grhsim_single_baseline import Baseline, ROOT, XS, cpus, identity, save
from decode_table_study import parse


def coverage(out):
    manifests={name:json.loads((out/name/'chisel-home/build/simulation_primitives.json').read_text()) for name in ('A','B')}
    calls={name:[r for r in data['calls'] if r['api'] in ['ListLookup','DecodeLogic','decoder']]
           for name,data in manifests.items()}
    a=manifests['A']['decode_tables'];b=manifests['B']['decode_tables']
    if a!=b:raise ValueError('raw decode tables differ across A/B')
    if any(c['intrinsic'] for c in calls['A']):raise ValueError('baseline contains decode intrinsic')
    if not any(c['intrinsic'] for c in calls['B']):raise ValueError('no real decode primitive selected')
    tables=[];directory=out/'tables';directory.mkdir(exist_ok=True)
    for key,payload in b.items():
        t=parse(payload);(directory/(key+'.table')).write_text(payload+'\n')
        sites=[r for r in calls['B'] if r['table_id']==key]
        tables.append(dict(table_id=key,mode=t['mode'],input_width=t['n'],output_width=t['m'],fields=t['fields'],
            rows=len(t['rows']),instances=len(sites),selected=sum(r['intrinsic'] for r in sites),sites=sites))
    scan=[]
    pattern=re.compile(r'\b(ListLookup|DecodeLogic|decoder)\s*(?:\.\s*(?:qmc|espresso))?\s*\(')
    for path in sorted(XS.rglob('*.scala')):
        if any(p in ('out','target','build','.git') for p in path.relative_to(XS).parts):continue
        text=path.read_text(errors='replace')
        text=re.sub(r'/\*.*?\*/',lambda m:'\n'*m.group().count('\n'),text,flags=re.S)
        text=re.sub(r'"(?:\\.|[^"\\])*"',lambda m:''.join('\n' if c=='\n' else ' ' for c in m.group()),text)
        for line_no,line in enumerate(text.splitlines(),1):
            for match in pattern.finditer(line.split('//',1)[0]):
                relative=str(path.relative_to(XS))
                scan.append(dict(file=relative,line=line_no,api=match.group(1),
                    scope='xiangshan-source' if relative.startswith('src/main/scala/') else 'library-or-test-not-globally-replaced'))
    report=dict(calls=calls,tables=tables,source_scan=scan,
        decisions=dict(Counter(r['decision'] for r in calls['B'])),
        note='Source scan counts call syntax; elaboration calls count actual occurrences before firtool deduplication.')
    save(out/'coverage.json',report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['build','measure','coverage'])
    p.add_argument('--output',type=Path,required=True);p.add_argument('--jobs',type=int,default=32)
    p.add_argument('--tools-dir',type=Path,default=ROOT/'build/grhsim32-tools')
    p.add_argument('--compiler',default='/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++')
    p.add_argument('--comparison',default='comparison-v1')
    p.add_argument('--verification-from',type=Path)
    args=p.parse_args();out=args.output.resolve()
    if args.command=='coverage':coverage(out);return
    if not platform.node().startswith('node030'):raise ValueError('run this experiment on node030')
    os.sched_setaffinity(0,cpus(Path('/sys/devices/system/cpu/online').read_text()))
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    if args.command=='build':out.mkdir(parents=True,exist_ok=False)
    with (out/'study.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.command=='measure':
            command=[sys.executable,ROOT/'scripts/grhsim_single_compare.py',
                '--baseline',out/'A','--candidate',out/'B','--output',out/args.comparison,
                '--runtime-difftest','on','--candidate-sim-primitives','decode-table',
                '--pairs','8','--cycles','100000']
            if args.verification_from:command+=['--verification-from',args.verification_from.resolve()]
            subprocess.run(command,check=True,cwd=ROOT)
            return
        frozen=out/'tools-frozen';shutil.copytree(args.tools_dir.resolve()/'python',frozen/'python')
        # LD_LIBRARY_PATH in Baseline.emit must resolve the frozen library, too.
        shutil.copy2(args.tools_dir.resolve()/'wolvrix/libwolvrix-lib.so',frozen/'libwolvrix-lib.so')
        save(frozen/'identity.json',[identity(p) for p in sorted(frozen.rglob('*')) if p.is_file()])
        work={}
        for name,mode in [('A','none'),('B','decode-table')]:
            config=argparse.Namespace(output=out/name,tools_dir=frozen,compiler=args.compiler,
                jobs=args.jobs,cpu=96,cycles=100000,repeats=8,sim_primitives=mode,
                rtl_difftest='on',model_difftest='on',compile_difftest='on',runtime_difftest='on')
            work[name]=Baseline(config);work[name].snapshot()
        if (out/'A/sources.json').read_bytes()!=(out/'B/sources.json').read_bytes():
            raise ValueError('source identity changed between snapshots')
        save(out/'experiment.json',dict(driver=identity(__file__),tools=identity(frozen/'identity.json'),
            sources=identity(out/'A/sources.json'),cpu=96,cycles=100000,pairs=8))
        # Mill's incremental outputs are shared; elaborations are sequential.
        for name in ('A','B'):
            work[name].stage('fresh Chisel RTL '+name);work[name].rtl()
        coverage(out)
        def model(name):
            try:
                work[name].emit();work[name].compile();work[name].stage('build complete '+name)
            except Exception as error:
                work[name].stage('failed: '+str(error));raise
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks=[pool.submit(model,n) for n in ('A','B')]
            for task in tasks:task.result()


if __name__=='__main__':main()
