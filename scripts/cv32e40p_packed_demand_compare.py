#!/usr/bin/env python3
"""Fixed CV32 compatibility and timing control for packed-demand lowering."""
import argparse
import json
from pathlib import Path
import platform
import shutil
import subprocess

from cv32e40p_compare import ROOT,CXX,CFLAGS,identity,run,save,summarize_named
from cv32e40p_event_regions_compare import check,shapes,source_inventory
from cv32e40p_repair_compare import GRAPH,HARNESS,emit_environment,same_sources,compile_model,native_library,verify,measure
from grhsim_elf_section_identity import sections
from xiangshan_cv32_ablation_measure import measurement_lock

BASE=ROOT/'build/cv32e40p/packed-storage-fixed-v1'
FIXED='grhsim_ownership_fixed'
FEATURES={'grhsim_packed_no_init':(0,1,0),'grhsim_packed_select':(0,0,1),'grhsim_packed_combined':(1,1,1)}


def build(out,tools):
    assert platform.node().startswith('node030')
    original=check(BASE);out.mkdir(parents=True,exist_ok=False)
    for name in ('firmware','verification.json'):(out/name).symlink_to(BASE/name)
    native=out/'native-frozen';native.mkdir()
    for p in (tools/'cv32e40p_emit',native_library(tools)):shutil.copy2(p,native/p.name)
    snap=out/'source-snapshot';snap.mkdir()
    for p in (ROOT/'wolvrix/lib/transform/activity_schedule.cpp',ROOT/'wolvrix/lib/emit/grhsim_cpp.cpp',
              ROOT/'testcase/cv32e40p-bench/emit.cpp',Path(__file__).resolve()):shutil.copy2(p,snap/p.name)
    (snap/'wolvrix.patch').write_bytes(subprocess.check_output(['git','-C',ROOT/'wolvrix','diff','--binary']))
    names=[FIXED,*FEATURES,'verilator']
    save(out/'hypothesis.json',dict(variants=names,options=FEATURES,rounds=8,cpu=96,numa=1,aslr=False,threads=1,
        rule='Direct-state complete overwrites and private selected state reads; independent rules and one predeclared layout combination.',
        expected='The frozen CV32 has no packed-lane representation; source/code identity gate precedes timing.',
        feedback=False))
    env=emit_environment(native)
    env.update(CV32_EVENT_REGIONS_SHARED='1',WOLVRIX_GRHSIM_SHARED_EQUALITY_FAMILIES='1',
        WOLVRIX_GRHSIM_CONDITIONAL_MUX_INPUT_CACHE='1',WOLVRIX_GRHSIM_COVERED_STATE_VIEW_NOTIFICATIONS='1',
        WOLVRIX_GRHSIM_COVERED_STATE_VIEW_INLINE='1',WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION='1',
        WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION_INLINE='1',WOLVRIX_GRHSIM_PACKED_ARRAY_LOCAL_SCOPE='0')
    inventories={};structure={}
    for name,(a,b,c) in {'off-source':(0,0,0),**FEATURES}.items():
        env.update(WOLVRIX_GRHSIM_STATE_LAYOUT_PACKED_ACCESS=str(a),WOLVRIX_GRHSIM_PACKED_ARRAY_NO_INIT=str(b),
                   WOLVRIX_GRHSIM_PACKED_ARRAY_STATE_SELECT=str(c))
        run([native/'cv32e40p_emit',GRAPH,out/name,'off'],out/'logs'/(name+'-emit.log'),env=env)
        assert identity(out/name/'normalized.json')['sha256']==identity(BASE/FIXED/'normalized.json')['sha256']
        if not same_sources(out/name,BASE/FIXED):raise ValueError('CV32 zero-hit source drift: '+name)
        inventories[name]=source_inventory(out/name);structure[name]=shapes(out/name)
    save(out/'structure.json',dict(all_sources_equal_fixed=True,models=structure))
    for name in FEATURES:compile_model(out/name,out,name,12)
    for name in (FIXED,'verilator'):
        (out/name).mkdir();shutil.copy2(original['binaries'][name]['path'],out/name/'emu')
    code={n:sections(out/n/'emu') for n in names[:-1]}
    assert all(s==code[FIXED] for s in code.values()),'zero-hit ELF section drift'
    save(out/'elf-sections.json',code)
    save(out/'build.json',dict(backends=names,candidate='grhsim_packed_combined',comparisons=[FIXED,'verilator'],flags=CFLAGS,
        binaries={n:identity(out/n/'emu') for n in names},
        frozen_inputs=[identity(p) for p in (BASE/'build.json',GRAPH,HARNESS,CXX,out/'hypothesis.json',out/'structure.json',
            out/'elf-sections.json',out/'verification.json',*native.iterdir(),*snap.iterdir())]+
            [r for inventory in inventories.values() for r in inventory.values()]))
    check(out);print('CV32 sources and code sections identical; five backends ready',flush=True)


def measurement(out):
    with measurement_lock():measure(out)
    rows=json.loads((out/'pairs.json').read_text())
    comparisons={after+'_vs_'+before:summarize_named(rows,after,before)
        for before,after in [(FIXED,n) for n in FEATURES]+[('verilator',FIXED),('verilator','grhsim_packed_combined')]}
    save(out/'all-comparisons.json',comparisons)
    print(json.dumps({k:v['wall_s'] for k,v in comparisons.items()},indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=('build','check','verify','measure'))
    p.add_argument('--output',type=Path,required=True);p.add_argument('--tools',type=Path,default=ROOT/'build/cv32e40p/tools')
    a=p.parse_args();out=a.output.resolve()
    if a.stage=='build':build(out,a.tools.resolve())
    elif a.stage=='verify':
        with measurement_lock():verify(out)
    else:{'check':check,'measure':measurement}[a.stage](out)
