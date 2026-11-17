#!/usr/bin/env python3
"""One fixed connected/equal-frontier shared schedule, no profile feedback."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import platform
import resource
import shutil
import subprocess
from cv32e40p_compare import ROOT,run
from cv32e40p_repair_compare import native_library
from grhsim_single_baseline import identity,save,clean_environment
from grhsim_single_compare import summarize
from xiangshan_cv32_compare import HISTORICAL,XS,verify_identity
from xiangshan_packed_storage_compare import FULL,check_model,check_harness_source,source_inventory,source_shape

PREVIOUS=ROOT/'build/xs/packed-demand-20261116-v1'
VARIANTS=('full','candidate','no_shared')
def read(p):return json.loads(Path(p).read_text())

def prepare(out,tools):
    check_harness_source();out.mkdir(parents=True,exist_ok=False)
    native=out/'native';snap=out/'snapshot';native.mkdir();snap.mkdir()
    shutil.copytree(ROOT/'wolvrix/include',native/'include')
    shutil.copytree(ROOT/'wolvrix/lib',snap/'lib')
    shutil.copy2(native_library(tools),native/'libwolvrix-lib.so')
    for p in (ROOT/'scripts/xiangshan_cv32_emit.cpp',Path(__file__).resolve()):shutil.copy2(p,snap/p.name)
    (snap/'wolvrix.patch').write_bytes(subprocess.check_output(['git','-C',ROOT/'wolvrix','diff','--binary']))
    for name in ('full','no_shared'):
        old=(PREVIOUS/name).resolve();check_model(old);(out/name).symlink_to(old,target_is_directory=True)
    dest=out/'candidate';dest.mkdir();shutil.copytree(out/'full/chisel-home',dest/'chisel-home')
    config=read(out/'full/configuration.json')
    config.update(variant='connected_shared',event_regions_shared=True,event_regions_shared_connected=True,
                  native_library=identity(native/'libwolvrix-lib.so'))
    save(dest/'configuration.json',config)
    save(out/'policy.json',dict(variants=VARIANTS,pairs=3,cpu=96,numa=1,aslr=False,threads=1,cycles=100000,
        smoke_cycles=10000,verification_seeds=[0,1],runtime_difftest='on',
        rule='Whole compute nodes; computational dependency components within equal endpoint sets. Coalesce disconnected components only with identical complete incoming value/state frontiers. Require a cross-owner computational contraction or equal-frontier merge. Preserve rejected original groups; refine only quotient cycles.',
        options='Only event_regions_shared_connected; includes local SCC refinement. Existing scalar proofs/caches remain on; cost guard, cross-region proof, packed-layout/scope/no-init/select remain off.',
        order='three forward/reverse rounds, no sample removal or post-measurement rule changes',
        feedback=False,idle_admission='Preserve existing XS skip-idle-check policy; CPU/NUMA/ASLR/thread gates mandatory.'))
    inputs=[identity(p) for folder in (native,snap) for p in sorted(folder.rglob('*')) if p.is_file()]
    inputs += [identity(p) for p in (out/'policy.json',dest/'configuration.json',HISTORICAL/'pre_reg_to_mem.json')]
    for name in ('xiangshan_shared_connected_compare.py','xiangshan_cv32_ablation_measure.py','grhsim_single_baseline.py',
                 'grhsim_single_compare.py','grhsim_difftrace.py','grhsim_numa.py','simulation_model_modes.py'):
        inputs.append(identity(ROOT/'scripts'/name))
    save(out/'inputs.json',inputs)

def check_inputs(out):
    for r in read(out/'inputs.json'):verify_identity(r)

def build(out):
    assert platform.node().startswith('node030');check_inputs(out);check_harness_source()
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    native=out/'native';dest=out/'candidate';env=clean_environment()
    env.update(NOOP_HOME=str(XS),LC_ALL='C',LD_LIBRARY_PATH=str(native),WOLVRIX_GRHSIM_STORAGE_REF_ALIASES='0',
        WOLVRIX_GRHSIM_PACKED_ARRAY_LOCAL_SCOPE='0')
    original=read(FULL/'logs/native.command.json')['argv']
    for name,enabled in (('off',0),('connected',1)):
        cmd=[a.replace(str(FULL/'native'),str(native)).replace(str(FULL.parent/'snapshot'),str(out/'snapshot')) for a in original]
        for i,a in enumerate(cmd):
            if a.endswith('/xiangshan_cv32_emit.cpp'):cmd[i]=str(out/'snapshot/xiangshan_cv32_emit.cpp')
        cmd.insert(1,'-DXS_SHARED_EVENT_REGIONS_CONNECTED='+str(enabled));cmd[-1]=str(native/('emit-'+name))
        run(cmd,out/'logs'/('native-'+name+'.log'),env=env)
    def emit(name):
        folder=out/'off-source' if name=='off' else dest/'model'
        run([native/('emit-'+name),HISTORICAL/'pre_reg_to_mem.json',folder],out/'logs'/(name+'-emit.log'),env=env)
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(emit,('off','connected')))
    assert source_shape(source_inventory(out/'off-source'))==source_shape(read(out/'full/model-sources.json')),'off source drift'
    sources=source_inventory(dest/'model');save(dest/'model-sources.json',sources)
    log=(out/'logs/connected-emit.log').read_text()
    save(out/'structure.json',dict(off_equal_corrected_full=True,decisions=[l for l in log.splitlines() if 'shared connected components:' in l or 'shared cycle refinement:' in l or 'shared event-regions:' in l]))
    cmd=[a.replace(str(FULL),str(dest)) for a in read(FULL/'logs/compile.command.json')['argv']]
    run(cmd,dest/'logs/compile.log',env=env)
    save(dest/'binary.json',identity(dest/'emu/grhsim-compile/emu'))
    files=sources+source_inventory(out/'off-source')+[identity(out/'structure.json'),identity(dest/'binary.json'),read(dest/'binary.json'),identity(dest/'model-sources.json')]
    files += [identity(p) for folder in (out/'logs',dest/'logs') for p in sorted(folder.iterdir()) if p.is_file()]
    files += [identity(native/('emit-'+n)) for n in ('off','connected')]
    save(out/'build.json',dict(files=files,inputs=identity(out/'inputs.json'),binaries={n:read(out/n/'binary.json') for n in VARIANTS}))
    check(out);print('connected candidate built',flush=True)

def check(out):
    check_inputs(out)
    for r in read(out/'build.json')['files']:verify_identity(r)
    for n in VARIANTS:check_model(out/n)

def measure(out):
    import xiangshan_cv32_ablation_measure as p
    check(out);p.VARIANTS=VARIANTS;p.ROUNDS=3
    result=p.measure(out,out/'measurement',XS/'ready-to-run/coremark-2-iteration.bin',XS/'ready-to-run/riscv64-nemu-interpreter-so')
    comparisons={}
    for before,after in (('full','candidate'),('no_shared','candidate'),('full','no_shared')):
        comparisons[after+'_vs_'+before]={metric:summarize([{side:dict(host_ms=r[n][metric]*(1000 if metric=='external_wall_s' else 1)) for side,n in (('A',before),('B',after))} for r in result['rounds']]) for metric in ('host_ms','external_wall_s')}
    check(out);save(out/'report.json',dict(comparisons=comparisons,build=identity(out/'build.json'),policy=identity(out/'policy.json')))
    print(json.dumps(comparisons,indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=('prepare','build','check','measure'))
    p.add_argument('--output',type=Path,required=True);p.add_argument('--tools',type=Path,default=ROOT/'build/cv32e40p/tools')
    a=p.parse_args();out=a.output.resolve()
    if a.stage=='prepare':prepare(out,a.tools.resolve())
    else:{'build':build,'check':check,'measure':measure}[a.stage](out)
