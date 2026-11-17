#!/usr/bin/env python3
"""Fixed CV32 comparison of the cross-region state expression proofs."""
import argparse
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

from cv32e40p_compare import ROOT,CXX,CFLAGS,identity,run,save
from cv32e40p_event_regions_compare import check,shapes,source_inventory
from cv32e40p_repair_compare import GRAPH,HARNESS,emit_environment,same_sources,compile_model,native_library,verify,measure,diagnose

BASE=ROOT/'build/cv32e40p/shared-cost-guard-v1'
FULL=ROOT/'build/cv32e40p/state-expressions-v1'
REFERENCE='grhsim_shared_cost_guard'
BASELINE='grhsim_unshared'
CANDIDATE='grhsim_cross_region_views'

def build(out,tools,jobs):
    if not platform.node().startswith('node030'):raise ValueError('build on node030')
    original=check(BASE)
    out.mkdir(parents=True,exist_ok=False)
    (out/'firmware').symlink_to(BASE/'firmware')
    (out/'verification.json').symlink_to(BASE/'verification.json')
    native=out/'native-frozen';native.mkdir()
    snap=out/'source-snapshot';snap.mkdir()
    for p in (tools/'cv32e40p_emit',native_library(tools)):shutil.copy2(p,native/p.name)
    for p in (ROOT/'wolvrix/lib/transform/activity_schedule.cpp',ROOT/'wolvrix/include/transform/activity_schedule.hpp',
              ROOT/'wolvrix/lib/emit/grhsim_cpp.cpp',ROOT/'testcase/cv32e40p-bench/emit.cpp',Path(__file__).resolve()):shutil.copy2(p,snap/p.name)
    (snap/'wolvrix.patch').write_bytes(subprocess.check_output(['git','-C',ROOT/'wolvrix','diff','--binary']))
    save(out/'hypothesis.json',dict(rule='Extend existing single-register pure expression proofs across earlier compute groups; preserve independent original state heads, cache/event ownership, exact widths and fixed inline budget. Shared regions remain disabled in both tested variants.',
        scope='One fixed static rule, independent of design names, traces and measurements; preserve all other TNO0032 options.',
        protocol='Eight forward/reverse paired rounds on node030 CPU96 NUMA1 ASLR off; unshared baseline, cross-region candidate, full shared anchor and normalized RTL Verilator. No post-measurement rule changes.'))
    env=emit_environment(native)
    env.update(CV32_EVENT_REGIONS_SHARED='0',WOLVRIX_GRHSIM_SHARED_EQUALITY_FAMILIES='1',
        WOLVRIX_GRHSIM_CONDITIONAL_MUX_INPUT_CACHE='1',WOLVRIX_GRHSIM_COVERED_STATE_VIEW_NOTIFICATIONS='1',
        WOLVRIX_GRHSIM_COVERED_STATE_VIEW_INLINE='1',WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION='1',
        WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION_INLINE='1')
    for name,guard in ((BASELINE,'0'),(CANDIDATE,'1')):
        env['WOLVRIX_GRHSIM_COVERED_STATE_VIEW_CROSS_REGION']=guard
        run([native/'cv32e40p_emit',GRAPH,out/name,'off'],out/'logs'/f'{name}-emit.log',env=env)
        if identity(out/name/'normalized.json')['sha256']!=identity(BASE/REFERENCE/'normalized.json')['sha256']:raise ValueError('graph changed')
    if not same_sources(out/BASELINE,BASE/REFERENCE):raise ValueError('guard-off source drift')
    code='\n'.join(p.read_text() for p in (out/CANDIDATE).glob('*_sched_*.cpp'))
    added=[dict(value=int(v),ops=int(n),mode=mode) for v,n,mode in re.findall(r'Cross-region state expression: value=(\d+) ops=(\d+) mode=(inline|notify)',code)]
    save(out/'structure.json',dict(cross_region=added,off_sources_equal=True,graph_equal=True,
        baseline=shapes(out/BASELINE),candidate=shapes(out/CANDIDATE)))
    for name in (BASELINE,CANDIDATE):compile_model(out/name,out,name,jobs)
    (out/'verilator').mkdir();shutil.copy2(original['binaries']['verilator']['path'],out/'verilator/emu')
    anchor='grhsim_state_expression_inline'
    full=check(FULL);(out/anchor).mkdir();shutil.copy2(full['binaries'][anchor]['path'],out/anchor/'emu')
    backends=[BASELINE,CANDIDATE,anchor,'verilator']
    records=[record for name in backends[:2] for record in source_inventory(out/name).values()]
    save(out/'build.json',dict(feature='cross_region_state_expressions',backends=backends,candidate=CANDIDATE,
        comparisons=[BASELINE,anchor,'verilator'],flags=CFLAGS,binaries={b:identity(out/b/'emu') for b in backends},
        frozen_inputs=[identity(p) for p in (BASE/'build.json',FULL/'build.json',GRAPH,HARNESS,CXX,out/'hypothesis.json',out/'structure.json',out/'verification.json',*native.iterdir(),*snap.iterdir())]+records))
    print(json.dumps(json.loads((out/'structure.json').read_text()),indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['build','verify','measure','diagnose','check'])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--tools',type=Path,default=ROOT/'build/cv32e40p/tools')
    parser.add_argument('--jobs',type=int,default=12)
    args=parser.parse_args();out=args.output.resolve()
    if args.stage=='build':build(out,args.tools.resolve(),args.jobs)
    else:dict(verify=verify,measure=measure,diagnose=diagnose,check=check)[args.stage](out)
