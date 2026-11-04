#!/usr/bin/env python3
"""Retest the same captured tables against the previous intrinsic implementation."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from decode_table_study import CXX, TOOLS, extract_kernel, run
from grhsim_single_baseline import identity, save


def rebuild(cases_file, output):
    cases_file,output=Path(cases_file).resolve(),Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    old=json.loads(cases_file.read_text());done=[]
    for c in old:
        source=Path(c['case']);dest=output/c['name'];dest.mkdir()
        shutil.copy2(source/'table.txt',dest/'table.txt')
        (dest/'A').mkdir();shutil.copy2(source/'B/bench',dest/'A/bench')
        (dest/'B').mkdir();shutil.copy2(source/'B/DecodeTableStudy.sv',dest/'B/DecodeTableStudy.sv')
        shutil.copy2(source/'B/harness.cpp',dest/'B/harness.cpp')
        model=dest/'B/model'
        run([TOOLS/'grhsim32_frontend',dest/'B/graph.json','DecodeTableStudy',dest/'B/DecodeTableStudy.sv'],dest/'B/frontend.log')
        run([TOOLS/'grhsim32_pattern_emit',dest/'B/graph.json','DecodeTableStudy',model],dest/'B/emit.log')
        extract_kernel(model)
        run([CXX,'-std=c++20','-O3','-march=native','-I',model,dest/'B/harness.cpp',*sorted(model.glob('*.cpp')),'-o',dest/'B/bench'],dest/'B/compile.log')
        checks=[]
        for seed in (20261103,20261104):
            vectors=source/f'vectors-{seed}.bin'
            for v in ('A','B'):
                run([dest/v/'bench','verify',vectors],dest/f'verify-{v}-{seed}.log')
                checks.append(dict(variant=v,seed=seed,vectors=identity(vectors),status='pass'))
        # Keep original Verilator/reference evidence and generated-code links.
        (dest/'verilator').symlink_to(source/'verilator',target_is_directory=True)
        run(['nm','-S','--size-sort',dest/'B/bench'],dest/'B/symbols.log')
        run(['objdump','-d','--demangle',dest/'B/bench'],dest/'B/assembly.log')
        save(dest/'identity.json',dict(prior_case=str(source),table=identity(dest/'table.txt'),
            variants=dict(A=identity(dest/'A/bench'),B=identity(dest/'B/bench')),
            tools=[identity(TOOLS/'grhsim32_frontend'),identity(TOOLS/'grhsim32_pattern_emit')],
            note='A=previous intrinsic, B=tuned intrinsic; same frozen B RTL and exact vectors'))
        save(dest/'verification.json',checks)
        graph=json.loads((dest/'B/graph.json').read_text())
        remaining=sum(op['kind']=='kDecodeTable' for g in graph['graphs'] for op in g['ops'])
        done.append(dict(name=c['name'],table_id=c['table_id'],case=str(dest),prior_case=str(source),remaining_decode_ops=remaining))
        save(output/'cases.json',done)
        print('PASS',c['name'],'decode_ops='+str(remaining),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cases',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();rebuild(args.cases,args.output)
