#!/usr/bin/env python3
"""Independent frozen test of the existing static compute-call activity guard."""
import argparse
import copy
import json
from pathlib import Path
import platform
import shutil

from cv32e40p_compare import ROOT,CXX,CFLAGS,identity,run,save,signature
from cv32e40p_event_regions_compare import check,shapes,source_inventory
from cv32e40p_repair_compare import GRAPH,HARNESS,emit_environment,same_sources,compile_model,native_library,verify,measure as paired_measure,diagnose
from cv32e40p_state_expression_compare import BASE,BASELINE
from cv32e40p_covered_state_views_analysis import compare_counts
from cv32e40p_conditional_mux_analysis import perf_counts

CANDIDATE='grhsim_compute_entry_guard'
OPTION='WOLVRIX_GRHSIM_COMPUTE_BATCH_DISPATCH_GUARD'
def read(p):return json.loads(p.read_text())

def build(out,tools,jobs):
    if not platform.node().startswith('node030'):raise ValueError('build on node030')
    if out.exists():raise FileExistsError(out)
    original=check(BASE);out.mkdir(parents=True)
    (out/'firmware').symlink_to(BASE/'firmware');(out/'verification.json').symlink_to(BASE/'verification.json')
    native=out/'native-frozen';native.mkdir();snapshot=out/'source-snapshot';snapshot.mkdir()
    for p in (tools/'cv32e40p_emit',tools/'cv32e40p_map',native_library(tools)):shutil.copy2(p,native/p.name)
    for p in (ROOT/'wolvrix/lib/emit/grhsim_cpp.cpp',ROOT/'wolvrix/tests/emit/test_emit_grhsim_covered_state_views.cpp',
              ROOT/'wolvrix/CMakeLists.txt',Path(__file__).resolve()):shutil.copy2(p,snapshot/p.name)
    save(out/'hypothesis.json',dict(rule='Use existing compute_batch_dispatch_guard for every compute batch; load exact masks immediately before each call. Commit/event dispatch remains unchanged.',
        baseline='TNO0030 direct-view binary, fixed before the composition experiment; composition is disabled here.',
        expected='Skip empty calls without changing actual supernode execution, propagation or fixed-point counts.',
        protocol='One fixed candidate and eight forward/reverse three-backend rounds; no profile input, site selection or post-run combination.'))
    env=emit_environment(native);env.update(CV32_EVENT_REGIONS_SHARED='1',WOLVRIX_GRHSIM_SHARED_EQUALITY_FAMILIES='1',
        WOLVRIX_GRHSIM_CONDITIONAL_MUX_INPUT_CACHE='1',WOLVRIX_GRHSIM_COVERED_STATE_VIEW_NOTIFICATIONS='1',
        WOLVRIX_GRHSIM_COVERED_STATE_VIEW_INLINE='1',WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION='0',
        WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION_INLINE='0',**{OPTION:'0'})
    run([native/'cv32e40p_emit',GRAPH,out/'off-source','off'],out/'logs/off-emit.log',env=env)
    if not same_sources(out/'off-source',BASE/BASELINE):raise ValueError('feature-off source drift')
    env[OPTION]='1';run([native/'cv32e40p_emit',GRAPH,out/CANDIDATE,'off'],out/'logs/candidate-emit.log',env=env)
    before=source_inventory(BASE/BASELINE);after=source_inventory(out/CANDIDATE)
    if before.keys()!=after.keys():raise ValueError('source set drift')
    changed=[name for name in before if before[name]['sha256']!=after[name]['sha256']]
    if changed!=['grhsim_Cv32Bench_eval.cpp']:raise ValueError('change escaped caller: '+str(changed))
    if shapes(BASE/BASELINE)!=shapes(out/CANDIDATE):raise ValueError('model body/storage drift')
    if identity(BASE/BASELINE/'normalized.json')['sha256']!=identity(out/CANDIDATE/'normalized.json')['sha256']:raise ValueError('graph drift')
    save(out/'structure.json',dict(only_changed_source=changed,baseline=shapes(BASE/BASELINE),candidate=shapes(out/CANDIDATE),off_sources_equal=True))
    compile_model(out/CANDIDATE,out,CANDIDATE,jobs)
    for name in (BASELINE,'verilator'):
        (out/name).mkdir();shutil.copy2(original['binaries'][name]['path'],out/name/'emu')
    backends=[BASELINE,CANDIDATE,'verilator']
    save(out/'build.json',dict(feature='compute_call_activity_guard',backends=backends,candidate=CANDIDATE,comparisons=[BASELINE,'verilator'],flags=CFLAGS,
        binaries={b:identity(out/b/'emu') for b in backends},frozen_inputs=[identity(p) for p in (BASE/'build.json',GRAPH,HARNESS,CXX,
            out/'hypothesis.json',out/'structure.json',out/'verification.json',*native.iterdir(),*snapshot.iterdir())]+list(after.values())))
    print(json.dumps(read(out/'structure.json'),indent=2))

def compare_entry_counts(a,b):
    old=copy.deepcopy(a);new=copy.deepcopy(b);calls={}
    function_keys={k for k in old['counts']|new['counts'] if k.startswith('function:eval_compute_batch_')}
    for k in sorted(function_keys):
        x=old['counts'].pop(k);y=new['counts'].pop(k)
        if any(v>u for u,v in zip(x,y)):raise ValueError('compute function calls increased')
        calls[k]=dict(before=x,after=y,saved_per_cycle=(sum(x)-sum(y))/a['cycles'])
    invariant=compare_counts(old,new,[])
    return dict(invariant=invariant,function_calls=calls)

def counts(out,folder):
    manifest=check(out);f=read(out/'functional.json')
    if f['status']!='pass' or f['build']!=identity(out/'build.json'):raise ValueError('functional mismatch')
    original=ROOT/'build/cv32e40p/covered-view-inline-counts-v1'
    for backend,d in ((BASELINE,original),(CANDIDATE,folder)):
        if read(d/'inputs.json')['model']['sha256']!=manifest['binaries'][backend]['sha256']:raise ValueError('counter ELF mismatch')
    result=compare_entry_counts(read(original/'counts.json')['coremark'],read(folder/'counts.json')['coremark'])
    result.update(build=identity(out/'build.json'),inputs=[identity(d/p) for d in (original,folder) for p in ('inputs.json','counts.json')])
    save(out/'count-gate.json',result);print(json.dumps(result['function_calls'],indent=2))

def measure(out):
    gate=read(out/'count-gate.json')
    if gate['build']!=identity(out/'build.json') or not gate['invariant']['all_equal']:raise ValueError('count gate mismatch')
    for record in gate['inputs']:
        if identity(Path(record['path']))!=record:raise ValueError('count origin drift')
    paired_measure(out)

def analyze(out):
    manifest=check(out);d=read(out/'diagnostics.json');f=read(out/'functional.json');ref=f['workloads']['coremark']['verilator']
    if d['build']!=identity(out/'build.json'):raise ValueError('diagnostic identity drift')
    for row in d['runs'].values():
        if signature(row)!=signature(ref):raise ValueError('diagnostic workload mismatch')
    save(out/'analysis.json',dict(pmu={b:perf_counts(out/(b+'-stat.csv'),ref['cycles']) for b in manifest['backends']},
        machine=d['models'],counts=read(out/'count-gate.json'),summaries=read(out/'summary.json'),
        limits='Independent entry-guard experiment. One PMU sample; no composition based on earlier performance outcomes.'))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=('build','verify','counts','measure','diagnose','analyze'))
    p.add_argument('--output',type=Path,required=True);p.add_argument('--tools',type=Path,default=ROOT/'build/cv32e40p/tools')
    p.add_argument('--jobs',type=int,default=12);p.add_argument('--counts',type=Path)
    args=p.parse_args();out=args.output.resolve()
    if args.stage=='build':build(out,args.tools.resolve(),args.jobs)
    elif args.stage=='counts':counts(out,args.counts.resolve())
    else:{'verify':verify,'measure':measure,'diagnose':diagnose,'analyze':analyze}[args.stage](out)
