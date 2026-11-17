#!/usr/bin/env python3
"""Two fixed leave-one-mechanism-out XiangShan builds; no simulation feedback."""
import argparse
import json
import os
from pathlib import Path
import platform
import resource
import shutil
from cv32e40p_compare import ROOT,CXX,run
from grhsim_single_baseline import clean_environment,identity,save
from xiangshan_cv32_compare import HISTORICAL,XS,verify_identity

BASE=ROOT/'build/xs/cv32-transfer-20261116-v3'
VARIANTS=('no_shared','no_cones')
def read(p):return json.loads(Path(p).read_text())
def prepare(out):
    out.mkdir(parents=True,exist_ok=False)
    snap=out/'snapshot';snap.mkdir()
    for p in (ROOT/'scripts/xiangshan_cv32_emit.cpp',Path(__file__)):
        shutil.copy2(p,snap/p.name)
    (out/'full').symlink_to(BASE/'after',target_is_directory=True)
    inputs=[identity(HISTORICAL/'pre_reg_to_mem.json'),identity(BASE/'after/binary.json'),identity(BASE/'after/model-sources.json'),identity(CXX)]
    inputs += [identity(p) for p in snap.iterdir()]
    for variant in VARIANTS:
        dest=out/variant;dest.mkdir()
        shutil.copytree(BASE/'after/native',dest/'native',ignore=lambda directory,names: ['emit'] if Path(directory)==BASE/'after/native' else [])
        shutil.copytree(BASE/'after/chisel-home',dest/'chisel-home')
        config=read(BASE/'after/configuration.json')
        config.update(variant=variant,ablation='Disable only shared regions' if variant=='no_shared' else 'Disable conditional mux cones and dependent input caches',
                      event_regions=True,event_regions_shared=variant!='no_shared',split_oversize_compute_nodes=False,
                      conditional_mux_cones=variant!='no_cones',conditional_mux_input_cache=variant!='no_cones',source_driver=identity(Path(__file__)))
        save(dest/'configuration.json',config)
        inputs += [identity(dest/'configuration.json')]
        inputs += [identity(p) for p in sorted((dest/'native').rglob('*')) if p.is_file()]
        inputs += [identity(p) for p in sorted((dest/'chisel-home').rglob('*')) if p.is_file()]
    save(out/'policy.json',dict(variants=['full',*VARIANTS],rules='Two independent ablations, no combined candidate and no adaptive threshold selection.',
        no_shared='eventRegionsShared=false; eventRegions=true; splitting remains false',
        no_cones='conditional_mux_cones=false and conditional_mux_input_cache=false; unchanged shared scheduling',
        generation='Frozen 8523dc1 library; same graph, simplify, reg-to-mem, compile flags and harness as v3 after.',
        measure='All simulator invocations serial on node030 CPU96 NUMA1 ASLR off; 10k smoke, seeds0/1 100k trace; one warmup each; eight three-backend forward/reverse rounds.',
        comparisons='Each ablation divided by full in the same round; no sum of independent effects.',
        performance_feedback=False))
    inputs.append(identity(out/'policy.json'));save(out/'inputs.json',inputs)
def build(out,variant):
    if not platform.node().startswith('node030'):raise ValueError('build on node030')
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    for record in read(out/'inputs.json'):verify_identity(record)
    dest=out/variant;native=dest/'native';env=clean_environment()
    env.update(NOOP_HOME=str(XS),LC_ALL='C',WOLVRIX_GRHSIM_STORAGE_REF_ALIASES='0')
    command=read(BASE/'after/logs/native.command.json')['argv']
    command=[x.replace(str(BASE/'after/native'),str(native)).replace(str(BASE/'snapshot'),str(out/'snapshot')) for x in command]
    command[1:1]=[f'-DXS_ABLATE_SHARED={int(variant=="no_shared")}',f'-DXS_ABLATE_CONES={int(variant=="no_cones")}']
    run(command,dest/'logs/native.log',env=env)
    run([native/'emit',HISTORICAL/'pre_reg_to_mem.json',dest/'model'],dest/'logs/emit.log',env=env)
    save(dest/'model-sources.json',[identity(p) for p in sorted((dest/'model').iterdir()) if p.suffix in ('.cpp','.hpp') or p.name=='Makefile'])
    command=read(BASE/'after/logs/compile.command.json')['argv']
    command=[x.replace(str(BASE/'after'),str(dest)) for x in command]
    run(command,dest/'logs/compile.log',env=env)
    save(dest/'binary.json',identity(dest/'emu/grhsim-compile/emu'))
    print(variant+' build complete',flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=['prepare',*VARIANTS]);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();out=a.output.resolve()
    if a.stage=='prepare':prepare(out)
    else:build(out,a.stage)
