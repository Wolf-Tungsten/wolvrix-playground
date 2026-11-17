#!/usr/bin/env python3
"""Independent fixed CV32 comparisons of packed state layout and array scope."""
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

BASE=ROOT/'build/cv32e40p/state-expressions-v1'
BASELINE='grhsim_state_expression_inline'
FEATURES={'layout':('state_layout_packed_access','WOLVRIX_GRHSIM_STATE_LAYOUT_PACKED_ACCESS'),
          'scope':('packed_array_local_scope','WOLVRIX_GRHSIM_PACKED_ARRAY_LOCAL_SCOPE')}

def build(out,tools,jobs,feature):
    CANDIDATE='grhsim_packed_'+feature
    if not platform.node().startswith('node030'):raise ValueError('build on node030')
    original=check(BASE)
    out.mkdir(parents=True,exist_ok=False)
    (out/'firmware').symlink_to(BASE/'firmware')
    (out/'verification.json').symlink_to(BASE/'verification.json')
    native=out/'native-frozen';native.mkdir()
    snap=out/'source-snapshot';snap.mkdir()
    for p in (tools/'cv32e40p_emit',native_library(tools)):shutil.copy2(p,native/p.name)
    for p in (ROOT/'wolvrix/lib/transform/activity_schedule.cpp',ROOT/'wolvrix/include/transform/activity_schedule.hpp',
              ROOT/'wolvrix/lib/emit/grhsim_cpp.cpp',ROOT/'wolvrix/lib/transform/activity_shared_refinement.hpp',ROOT/'testcase/cv32e40p-bench/emit.cpp',Path(__file__).resolve()):shutil.copy2(p,snap/p.name)
    (snap/'wolvrix.patch').write_bytes(subprocess.check_output(['git','-C',ROOT/'wolvrix','diff','--binary']))
    save(out/'hypothesis.json',dict(feature=feature, rule='One fixed emitter rule: same-signature/demand packed state bundles, or private single-select array scopes with stable early index. Schedule, cache and covered-state proofs stay unchanged.',
        scope='One fixed static rule, independent of design names, traces and measurements; preserve all other TNO0032 options.',
        protocol='Eight forward/reverse paired rounds on node030 CPU96 NUMA1 ASLR off; current optimized baseline, guarded candidate and normalized RTL Verilator. No post-measurement rule changes.'))
    env=emit_environment(native)
    env.update(CV32_EVENT_REGIONS_SHARED='1',WOLVRIX_GRHSIM_SHARED_EQUALITY_FAMILIES='1',
        WOLVRIX_GRHSIM_CONDITIONAL_MUX_INPUT_CACHE='1',WOLVRIX_GRHSIM_COVERED_STATE_VIEW_NOTIFICATIONS='1',
        WOLVRIX_GRHSIM_COVERED_STATE_VIEW_INLINE='1',WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION='1',
        WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION_INLINE='1')
    for name,guard in ((BASELINE,'0'),(CANDIDATE,'1')):
        env[FEATURES[feature][1]]=guard
        run([native/'cv32e40p_emit',GRAPH,out/name,'off'],out/'logs'/f'{name}-emit.log',env=env)
        if identity(out/name/'normalized.json')['sha256']!=identity(BASE/BASELINE/'normalized.json')['sha256']:raise ValueError('graph changed')
    if not same_sources(out/BASELINE,BASE/BASELINE):raise ValueError('guard-off source drift')
    old, new = source_inventory(out/BASELINE), source_inventory(out/CANDIDATE)
    changed = sorted(name for name in old if old[name]['sha256'] != new[name]['sha256'])
    if feature == 'layout' and any(name.endswith('.cpp') for name in changed):
        raise ValueError('layout changed generated computation source: '+str(changed))
    if feature == 'scope' and any(name.endswith('.hpp') for name in changed):
        raise ValueError('scope changed generated header/storage')
    if feature == 'layout':
        lines=[l for l in (out/'logs'/f'{CANDIDATE}-emit.log').read_text().splitlines()
               if '[GRHSIM_PACKED_STATE_LAYOUT]' in l]
        if not lines:raise ValueError('missing layout decision')
        decision=dict(re.findall(r'(\w+)=(\d+)',lines[-1]))
    else:
        decision=dict(scope_sites=sum(p.read_text().count('// Scoped packed array:')
            for p in (out/CANDIDATE).glob('*_sched_*.cpp')))
    save(out/'structure.json',dict(feature=feature,decision=decision,off_sources_equal=True,
        changed_files=changed,baseline=shapes(out/BASELINE),candidate=shapes(out/CANDIDATE)))
    for name in (BASELINE,CANDIDATE):compile_model(out/name,out,name,jobs)
    (out/'verilator').mkdir();shutil.copy2(original['binaries']['verilator']['path'],out/'verilator/emu')
    backends=[BASELINE,CANDIDATE,'verilator']
    records=[record for name in backends[:2] for record in source_inventory(out/name).values()]
    save(out/'build.json',dict(feature=FEATURES[feature][0],backends=backends,candidate=CANDIDATE,
        comparisons=[BASELINE,'verilator'],flags=CFLAGS,binaries={b:identity(out/b/'emu') for b in backends},
        frozen_inputs=[identity(p) for p in (BASE/'build.json',GRAPH,HARNESS,CXX,out/'hypothesis.json',out/'structure.json',out/'verification.json',*native.iterdir(),*snap.iterdir())]+records))
    print(json.dumps(json.loads((out/'structure.json').read_text()),indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['build','verify','measure','diagnose','check'])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--feature',choices=FEATURES,default='layout')
    parser.add_argument('--tools',type=Path,default=ROOT/'build/cv32e40p/tools')
    parser.add_argument('--jobs',type=int,default=12)
    args=parser.parse_args();out=args.output.resolve()
    if args.stage=='build':build(out,args.tools.resolve(),args.jobs,args.feature)
    else:dict(verify=verify,measure=measure,diagnose=diagnose,check=check)[args.stage](out)
