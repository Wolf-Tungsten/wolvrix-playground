#!/usr/bin/env python3
"""Fixed three-round CV32 control for the connected shared schedule."""
import argparse
import json
from pathlib import Path
import platform
import shutil
import subprocess
from cv32e40p_compare import ROOT,CXX,CFLAGS,identity,run,save,sample,signature,summarize_named
from cv32e40p_event_regions_compare import check,shapes,source_inventory
from cv32e40p_repair_compare import GRAPH,HARNESS,emit_environment,same_sources,compile_model,native_library,verify
from xiangshan_cv32_ablation_measure import measurement_lock
from cv32e40p_shared_cycle_refinement_analysis import source_model

BASE=ROOT/'build/cv32e40p/packed-storage-fixed-v1'
FIXED='grhsim_ownership_fixed';CANDIDATE='grhsim_shared_connected'

def read(p):return json.loads(Path(p).read_text())
def build(out,tools):
    assert platform.node().startswith('node030');original=check(BASE);out.mkdir(parents=True,exist_ok=False)
    for name in ('firmware','verification.json'):(out/name).symlink_to(BASE/name)
    native=out/'native-frozen';native.mkdir()
    for p in (tools/'cv32e40p_emit',native_library(tools)):shutil.copy2(p,native/p.name)
    snap=out/'source-snapshot';snap.mkdir()
    for p in (ROOT/'wolvrix/lib/transform/activity_schedule.cpp',ROOT/'wolvrix/lib/transform/activity_shared_components.hpp',
        ROOT/'wolvrix/lib/transform/activity_shared_refinement.hpp',ROOT/'wolvrix/lib/emit/grhsim_cpp.cpp',
        ROOT/'wolvrix/include/transform/activity_schedule.hpp',ROOT/'testcase/cv32e40p-bench/emit.cpp',Path(__file__).resolve()):shutil.copy2(p,snap/p.name)
    (snap/'wolvrix.patch').write_bytes(subprocess.check_output(['git','-C',ROOT/'wolvrix','diff','--binary']))
    names=[FIXED,CANDIDATE,'verilator']
    save(out/'hypothesis.json',dict(variants=names,rounds=3,cpu=96,numa=1,aslr=False,threads=1,
        rule='Same connected/equal-activation shared candidate formation as XS. Whole compute nodes, local SCC refinement, unchanged other options.',
        feedback=False,order='three forward/reverse rounds; no sample removal or tuning'))
    env=emit_environment(native)
    env.update(CV32_EVENT_REGIONS_SHARED='1',WOLVRIX_GRHSIM_SHARED_EQUALITY_FAMILIES='1',
        WOLVRIX_GRHSIM_CONDITIONAL_MUX_INPUT_CACHE='1',WOLVRIX_GRHSIM_COVERED_STATE_VIEW_NOTIFICATIONS='1',
        WOLVRIX_GRHSIM_COVERED_STATE_VIEW_INLINE='1',WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION='1',
        WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION_INLINE='1',WOLVRIX_GRHSIM_PACKED_ARRAY_LOCAL_SCOPE='0')
    inventories={}
    for name,flag in ((FIXED,'0'),(CANDIDATE,'1')):
        env['CV32_SHARED_EVENT_REGIONS_CONNECTED']=flag
        run([native/'cv32e40p_emit',GRAPH,out/name,'off'],out/'logs'/(name+'-emit.log'),env=env)
        assert identity(out/name/'normalized.json')['sha256']==identity(BASE/FIXED/'normalized.json')['sha256'],'graph drift'
        inventories[name]=source_inventory(out/name)
    assert same_sources(out/FIXED,BASE/FIXED),'off source drift'
    log=(out/'logs'/(CANDIDATE+'-emit.log')).read_text()
    save(out/'structure.json',dict(off_equal_corrected_full=True,models={n:source_model(out/n) for n in names[:-1]},
        decisions=[l for l in log.splitlines() if 'shared connected components:' in l or 'shared cycle refinement:' in l or 'shared event-regions:' in l]))
    compile_model(out/CANDIDATE,out,CANDIDATE,12)
    (out/'verilator').mkdir()
    for name in (FIXED,'verilator'):shutil.copy2(original['binaries'][name]['path'],out/name/'emu')
    save(out/'build.json',dict(backends=names,candidate=CANDIDATE,comparisons=[FIXED,'verilator'],flags=CFLAGS,
        binaries={n:identity(out/n/'emu') for n in names},
        frozen_inputs=[identity(p) for p in (BASE/'build.json',GRAPH,HARNESS,CXX,out/'hypothesis.json',out/'structure.json',
            out/'verification.json',*native.iterdir(),*snap.iterdir())]+[r for inv in inventories.values() for r in inv.values()]))
    check(out);print('CV32 candidate ready',flush=True)

def measure(out):
    with measurement_lock():
        manifest=check(out);functional=read(out/'functional.json')
        assert functional['status']=='pass' and functional['build']==identity(out/'build.json')
        if (out/'pairs.json').exists():raise FileExistsError('measurement already started')
        names=manifest['backends'];warmups={n:sample(out,n,'coremark','warmup') for n in names}
        save(out/'measurement-policy.json',dict(rounds=3,warmups=warmups,cpu=96,numa=1,aslr=False,order='forward/reverse alternating',retries=0,feedback=False))
        rows=[]
        for i in range(3):
            order=names if i%2==0 else names[::-1];row=dict(pair=i,order=order)
            for name in order:
                row[name]=sample(out,name,'coremark',f'pair{i:02d}')
                assert signature(row[name])==signature(functional['workloads']['coremark'][name])
            rows.append(row);save(out/'pairs.json',rows);print('round '+str(i+1)+'/3',flush=True)
        stats={n:summarize_named(rows,CANDIDATE,n) for n in (FIXED,'verilator')}
        save(out/'summary.json',stats);check(out)
        save(out/'report.json',dict(comparisons=stats,build=identity(out/'build.json'),functional=identity(out/'functional.json')))
        print(json.dumps({n:s['wall_s'] for n,s in stats.items()},indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=('build','check','verify','measure'))
    p.add_argument('--output',type=Path,required=True);p.add_argument('--tools',type=Path,default=ROOT/'build/cv32e40p/tools')
    a=p.parse_args();out=a.output.resolve()
    if a.stage=='build':build(out,a.tools.resolve())
    elif a.stage=='verify':
        with measurement_lock():verify(out)
    else:{'check':check,'measure':measure}[a.stage](out)
