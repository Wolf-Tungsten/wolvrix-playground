#!/usr/bin/env python3
"""CV32 controls for the users-span fix and two independent storage rules."""
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

BASE=ROOT/'build/cv32e40p/state-expressions-v1'
OLD='grhsim_state_expression_inline'
FIXED='grhsim_ownership_fixed'
LAYOUT='grhsim_packed_layout'
SCOPE='grhsim_packed_scope'


def build(out,tools):
    assert platform.node().startswith('node030')
    original=check(BASE);out.mkdir(parents=True,exist_ok=False)
    (out/'firmware').symlink_to(BASE/'firmware');(out/'verification.json').symlink_to(BASE/'verification.json')
    native=out/'native-frozen';native.mkdir()
    for p in (tools/'cv32e40p_emit',native_library(tools)):shutil.copy2(p,native/p.name)
    snap=out/'source-snapshot';snap.mkdir()
    for p in (ROOT/'wolvrix/lib/transform/activity_schedule.cpp',ROOT/'wolvrix/lib/emit/grhsim_cpp.cpp',
              ROOT/'testcase/cv32e40p-bench/emit.cpp',Path(__file__).resolve()):shutil.copy2(p,snap/p.name)
    (snap/'wolvrix.patch').write_bytes(subprocess.check_output(['git','-C',ROOT/'wolvrix','diff','--binary']))
    save(out/'hypothesis.json',dict(variants=[OLD,FIXED,LAYOUT,SCOPE,'verilator'],rounds=8,
        cpu=96,numa=1,aslr=False,threads=1,
        reason='Before measurement, dangling users-span repair changed off source. The fixed control isolates this correctness change from each independent rule.',
        rule='Identical static layout and scope rules; no runtime feedback or combined candidate.'))
    env=emit_environment(native)
    env.update(CV32_EVENT_REGIONS_SHARED='1',WOLVRIX_GRHSIM_SHARED_EQUALITY_FAMILIES='1',
        WOLVRIX_GRHSIM_CONDITIONAL_MUX_INPUT_CACHE='1',WOLVRIX_GRHSIM_COVERED_STATE_VIEW_NOTIFICATIONS='1',
        WOLVRIX_GRHSIM_COVERED_STATE_VIEW_INLINE='1',WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION='1',
        WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION_INLINE='1')
    for name in (FIXED,LAYOUT,SCOPE):
        env['WOLVRIX_GRHSIM_STATE_LAYOUT_PACKED_ACCESS']=str(int(name==LAYOUT))
        env['WOLVRIX_GRHSIM_PACKED_ARRAY_LOCAL_SCOPE']=str(int(name==SCOPE))
        run([native/'cv32e40p_emit',GRAPH,out/name,'off'],out/'logs'/f'{name}-emit.log',env=env)
        assert identity(out/name/'normalized.json')['sha256']==identity(BASE/OLD/'normalized.json')['sha256']
    inventories={name:source_inventory(out/name) for name in (FIXED,LAYOUT,SCOPE)}
    before=source_inventory(BASE/OLD)
    changed=[n for n in before if before[n]['sha256']!=inventories[FIXED][n]['sha256']]
    structure=dict(ownership_fix_changed_files=changed,models={n:shapes(out/n) for n in (FIXED,LAYOUT,SCOPE)},
        feature_sources_equal_fixed={n:same_sources(out/n,out/FIXED) for n in (LAYOUT,SCOPE)})
    save(out/'structure.json',structure)
    for name in (FIXED,LAYOUT,SCOPE):compile_model(out/name,out,name,12)
    for name in (OLD,'verilator'):
        (out/name).mkdir();shutil.copy2(original['binaries'][name]['path'],out/name/'emu')
    backends=[OLD,FIXED,LAYOUT,SCOPE,'verilator']
    save(out/'elf-sections.json',{n:sections(out/n/'emu') for n in backends[:4]})
    records=[r for inv in inventories.values() for r in inv.values()]
    save(out/'build.json',dict(backends=backends,candidate=SCOPE,comparisons=[OLD,FIXED,'verilator'],flags=CFLAGS,
        binaries={n:identity(out/n/'emu') for n in backends},
        frozen_inputs=[identity(p) for p in (BASE/'build.json',GRAPH,HARNESS,CXX,out/'hypothesis.json',out/'structure.json',
            out/'elf-sections.json',out/'verification.json',*native.iterdir(),*snap.iterdir())]+records))
    check(out);print(json.dumps(structure,indent=2),flush=True)


def measurement(out):
    measure(out)
    rows=json.loads((out/'pairs.json').read_text())
    comparisons={after+'_vs_'+before:summarize_named(rows,after,before)
        for before,after in ((OLD,FIXED),(FIXED,LAYOUT),(FIXED,SCOPE),(OLD,LAYOUT),(OLD,SCOPE),
                             ('verilator',FIXED),('verilator',LAYOUT),('verilator',SCOPE))}
    save(out/'all-comparisons.json',comparisons)
    print(json.dumps({k:v['wall_s'] for k,v in comparisons.items()},indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=('build','check','verify','measure'))
    p.add_argument('--output',type=Path,required=True);p.add_argument('--tools',type=Path,default=ROOT/'build/cv32e40p/tools')
    a=p.parse_args();out=a.output.resolve()
    if a.stage=='build':build(out,a.tools.resolve())
    else:{'check':check,'verify':verify,'measure':measurement}[a.stage](out)
