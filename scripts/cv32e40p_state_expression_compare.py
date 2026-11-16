#!/usr/bin/env python3
"""Fixed comparison of composable register-expression proofs, without feedback."""
import argparse
import csv
import json
from pathlib import Path
import platform
import re
import shutil

from cv32e40p_compare import ROOT,CXX,CFLAGS,identity,run,save,sample,signature,summarize_named
from cv32e40p_event_regions_compare import check,shapes,source_inventory
from cv32e40p_equality_family_compare import family_sites
from cv32e40p_mux_input_cache_compare import cache_sites
from cv32e40p_repair_compare import GRAPH,HARNESS,emit_environment,same_sources,compile_model,cone_sites,verify,diagnose,native_library
from cv32e40p_covered_state_views_compare import sites
from cv32e40p_covered_state_views_analysis import compare_counts
from cv32e40p_post_view_structure import StateClosures
from cv32e40p_conditional_mux_analysis import perf_counts

BASE=ROOT/'build/cv32e40p/covered-state-views-v1'
BASELINE='grhsim_covered_view_inline'
NOTIFY='grhsim_state_expression_notify'
INLINE='grhsim_state_expression_inline'
PARENT='WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION'
CHILD='WOLVRIX_GRHSIM_COVERED_STATE_VIEW_COMPOSITION_INLINE'

def read(p):return json.loads(p.read_text())
def composed(folder):
    return sorted([dict(value=int(v),ops=int(n),mode=mode,file=p.name)
        for p in folder.glob('*_sched_*.cpp') for v,n,mode in re.findall(
            r'Composed state expression: value=(\d+) ops=(\d+) mode=(inline|notify)',p.read_text())],key=lambda r:r['value'])
def summaries(rows):
    return {NOTIFY:{b:summarize_named(rows,NOTIFY,b) for b in (BASELINE,'verilator')},
            INLINE:{b:summarize_named(rows,INLINE,b) for b in (NOTIFY,BASELINE,'verilator')}}

def build(out,tools,jobs):
    if not platform.node().startswith('node030'):raise ValueError('build on node030')
    if out.exists():raise FileExistsError(out)
    original=check(BASE);out.mkdir(parents=True)
    (out/'firmware').symlink_to(BASE/'firmware');(out/'verification.json').symlink_to(BASE/'verification.json')
    native=out/'native-frozen';native.mkdir();snap=out/'source-snapshot';snap.mkdir()
    for p in (tools/'cv32e40p_emit',tools/'cv32e40p_map',native_library(tools)):shutil.copy2(p,native/p.name)
    for p in (ROOT/'wolvrix/lib/emit/grhsim_cpp.cpp',ROOT/'wolvrix/tests/emit/test_emit_grhsim_covered_state_views.cpp',
              ROOT/'wolvrix/CMakeLists.txt',Path(__file__).resolve()):shutil.copy2(p,snap/p.name)
    save(out/'hypothesis.json',dict(rule='Compose local scalar DAGs back to one single-writer register snapshot; preserve independent reader frontier and all cache ownership.',
        bounds=dict(proof_operations=32,depth=16,inline_expanded_tree_ops=4,inline_tree_ops_times_uses=16,inline_text_bytes=4096),
        stages={NOTIFY:'Keep old 21 views inline; remove redundant notifications on additional proven expressions.',
                INLINE:'Use the same proof set; additionally inline expressions passing the predeclared static budget.'},
        protocol='One fixed eight-round four-backend comparison; counts are functional gates, never generator inputs.',
        next_independent_experiment='Compute-entry guard will be compared separately against the same TNO0030 baseline, without composing candidates based on these results.'))
    env=emit_environment(native)
    env.update(CV32_EVENT_REGIONS_SHARED='1',WOLVRIX_GRHSIM_SHARED_EQUALITY_FAMILIES='1',
        WOLVRIX_GRHSIM_CONDITIONAL_MUX_INPUT_CACHE='1',WOLVRIX_GRHSIM_COVERED_STATE_VIEW_NOTIFICATIONS='1',
        WOLVRIX_GRHSIM_COVERED_STATE_VIEW_INLINE='1',**{PARENT:'0',CHILD:'0'})
    run([native/'cv32e40p_emit',GRAPH,out/'off-source','off'],out/'logs/off-emit.log',env=env)
    if not same_sources(out/'off-source',BASE/BASELINE):raise ValueError('feature-off source drift')
    shutil.copy2(BASE/'sources.csv',out/'sources.csv')
    mapping=list(csv.DictReader((out/'sources.csv').open()));ids={}
    for r in mapping:
        ids.update({int(i):s for i,s in zip(r['value_ids'].split(';'),r['value_symbols'].split(';')) if i})
    graph=read(BASE/BASELINE/'normalized.json')['graphs'][0];proof=StateClosures(graph,mapping)
    base_shape=shapes(BASE/BASELINE);old_views=sites(BASE/BASELINE);models={};records=[]
    for name,inline in ((NOTIFY,'0'),(INLINE,'1')):
        env.update({PARENT:'1',CHILD:inline})
        run([native/'cv32e40p_emit',GRAPH,out/name,'off'],out/'logs'/f'{name}-emit.log',env=env)
        if identity(out/name/'normalized.json')['sha256']!=identity(BASE/BASELINE/'normalized.json')['sha256']:raise ValueError('graph changed')
        added=composed(out/name);all_views=sites(out/name);added_ids={r['value'] for r in added}
        if not added:raise ValueError('no composed proof')
        if [s for s in all_views if s['value'] not in added_ids]!=old_views:raise ValueError('old view proof drift')
        shape=shapes(out/name)
        if shape['supernodes']!=base_shape['supernodes'] or base_shape['checked_values']-shape['checked_values']!=len(added):raise ValueError('boundary shape drift')
        removed=sum(r['mode']=='inline' for r in added)
        if sum(base_shape['value_slots'].values())-sum(shape['value_slots'].values())!=removed:raise ValueError('storage accounting')
        if family_sites(out/name)!=family_sites(BASE/BASELINE) or cache_sites(out/name)!=cache_sites(BASE/BASELINE) or cone_sites(out/name)!=cone_sites(BASE/BASELINE):raise ValueError('existing lowering drift')
        verified=[]
        for site in all_views:
            if site['value'] not in added_ids:continue
            cone=proof.closure(ids[site['value']],site['producer'])
            if cone is None or len(cone[0])!=1:raise ValueError('state source proof mismatch')
            state=next(iter(cone[0]));root=next(r for r in added if r['value']==site['value'])
            if len(cone[1])!=root['ops']:raise ValueError('operation proof mismatch')
            consumers={int(proof.mapping[u['op']]['group']) for u in proof.values[ids[site['value']]]['users'] if u['op'] in proof.mapping}
            if not (consumers|{site['producer']}).issubset(proof.readers[state]):raise ValueError('missing independent state reader')
            verified.append(dict(**root,state=state,producer=site['producer'],consumers=sorted(consumers),depth=cone[2]))
        models[name]=dict(shape=shape,sites=added,proof=verified);records.extend(source_inventory(out/name).values())
    strip=lambda a:[{k:v for k,v in r.items() if k!='mode'} for r in a]
    if strip(models[NOTIFY]['sites'])!=strip(models[INLINE]['sites']):raise ValueError('proof set differs by stage')
    save(out/'structure.json',dict(baseline=base_shape,models=models,off_sources_equal=True,graph_equal=True,same_selected_values=True))
    for name in (NOTIFY,INLINE):compile_model(out/name,out,name,jobs)
    for name in (BASELINE,'verilator'):
        (out/name).mkdir();shutil.copy2(original['binaries'][name]['path'],out/name/'emu')
    backends=[BASELINE,NOTIFY,INLINE,'verilator']
    save(out/'build.json',dict(feature='composed_state_expressions',backends=backends,flags=CFLAGS,
        binaries={b:identity(out/b/'emu') for b in backends},frozen_inputs=[identity(p) for p in (
            BASE/'build.json',GRAPH,HARNESS,CXX,out/'hypothesis.json',out/'structure.json',out/'sources.csv',out/'verification.json',
            ROOT/'scripts/cv32e40p_post_view_structure.py',*native.iterdir(),*snap.iterdir())]+records))
    print(json.dumps({b:dict(proved=len(m['sites']),inlined=sum(s['mode']=='inline' for s in m['sites']),shape=m['shape']) for b,m in models.items()},indent=2))

def counts(out,notify_counts,inline_counts):
    manifest=check(out);functional=read(out/'functional.json');structure=read(out/'structure.json')
    if functional['status']!='pass' or functional['build']!=identity(out/'build.json'):raise ValueError('functional gate mismatch')
    dirs={BASELINE:ROOT/'build/cv32e40p/covered-view-inline-counts-v1',NOTIFY:notify_counts,INLINE:inline_counts}
    observed={};inputs=[]
    for b,d in dirs.items():
        if read(d/'inputs.json')['model']['sha256']!=manifest['binaries'][b]['sha256']:raise ValueError('counter ELF mismatch')
        observed[b]=read(d/'counts.json')['coremark'];inputs.extend(identity(d/f) for f in ('inputs.json','counts.json'))
    gate={b:compare_counts(observed[BASELINE],observed[b],[s['value'] for s in structure['models'][b]['sites']]) for b in (NOTIFY,INLINE)}
    if observed[NOTIFY]['counts']!=observed[INLINE]['counts']:raise ValueError('stage behavior differs')
    save(out/'count-gate.json',dict(build=identity(out/'build.json'),stage_counts_equal=True,counters=gate,inputs=inputs))
    print(json.dumps({b:{k:v for k,v in g.items() if k not in ('group_executions','notification_probes')} for b,g in gate.items()},indent=2))

def analyze(out):
    manifest=check(out);d=read(out/'diagnostics.json');f=read(out/'functional.json')
    if d['build']!=identity(out/'build.json'):raise ValueError('PMU identity mismatch')
    ref=f['workloads']['coremark']['verilator']
    for row in d['runs'].values():
        if signature(row)!=signature(ref):raise ValueError('diagnostic workload mismatch')
    pmu={b:perf_counts(out/(b+'-stat.csv'),ref['cycles']) for b in manifest['backends']}
    save(out/'analysis.json',dict(pmu=pmu,machine=d['models'],counts=read(out/'count-gate.json'),summaries=read(out/'summary.json'),
        baseline_relative_to_verilator=summarize_named(read(out/'pairs.json'),BASELINE,'verilator'),
        limits='One PMU sample per backend; not a time attribution. No runtime measurements feed generation.',
        inputs=[identity(out/p) for p in ('build.json','functional.json','diagnostics.json','count-gate.json','summary.json','pairs.json')]))

def measure(out):
    manifest=check(out);backends=manifest['backends']
    if (out/'pairs.json').exists():raise FileExistsError('measurement already started')
    functional=json.loads((out/'functional.json').read_text())
    if functional['status']!='pass' or functional['build']!=identity(out/'build.json'):raise ValueError('functional gate mismatch')
    gate=json.loads((out/'count-gate.json').read_text())
    if not gate['stage_counts_equal'] or gate['build']!=identity(out/'build.json'):raise ValueError('count gate mismatch')
    for record in gate['inputs']:
        if identity(Path(record['path']))!=record:raise ValueError('count gate input drift')
    save(out/'measurement-policy.json',dict(rounds=8,repetitions=1,cpu=96,numa=1,aslr=False,
        order='forward/reverse alternating',backends=backends,max_pair_attempts=2,bootstrap_seed=20261114,
        count_gate=identity(out/'count-gate.json'),driver=identity(Path(__file__).resolve()),
        policy='Two statically frozen stages; no generation decisions based on results.'))
    warmups={b:sample(out,b,'coremark','warmup') for b in backends}
    for b,row in warmups.items():
        if signature(row)!=signature(functional['workloads']['coremark'][b]):raise ValueError('warmup signature drift')
    save(out/'warmups.json',warmups);rows=[]
    for index in range(8):
        order=backends if index%2==0 else backends[::-1]
        for attempt in range(2):
            row=dict(pair=index,attempt=attempt,order=order)
            try:
                for b in order:
                    row[b]=sample(out,b,'coremark',f'pair{index:02d}-attempt{attempt}')
                    if signature(row[b])!=signature(functional['workloads']['coremark'][b]):raise ValueError('functional drift: '+b)
                break
            except ValueError as error:
                if 'placement rejected:' not in str(error) or attempt:raise
        rows.append(row);save(out/'pairs.json',rows);print(f'round {index+1}/8 complete',flush=True)
    summary=summaries(rows);save(out/'summary.json',summary)
    with (out/'pairs.csv').open('w') as stream:
        writer=csv.writer(stream);writer.writerow(['pair','order',*[f'{b}_{m}' for b in backends for m in ('wall_s','sim_s','init_s')]])
        for row in rows:writer.writerow([row['pair'],'>'.join(row['order']),*[row[b][m] for b in backends for m in ('wall_s','sim_s','init_s')]])
    save(out/'report.json',dict(build=manifest,summaries=summary,structure=json.loads((out/'structure.json').read_text()),
        functional=identity(out/'functional.json'),policy=identity(out/'measurement-policy.json')))
    print(json.dumps({c:{b:s['wall_s'] for b,s in v.items()} for c,v in summary.items()},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('build','verify','counts','measure','diagnose','analyze'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--tools',type=Path,default=ROOT/'build/cv32e40p/tools')
    parser.add_argument('--jobs',type=int,default=12)
    parser.add_argument('--notify-counts',type=Path)
    parser.add_argument('--inline-counts',type=Path)
    args=parser.parse_args();out=args.output.resolve()
    if args.stage=='build':build(out,args.tools.resolve(),args.jobs)
    elif args.stage=='counts':counts(out,args.notify_counts.resolve(),args.inline_counts.resolve())
    else:{'verify':verify,'measure':measure,'diagnose':diagnose,'analyze':analyze}[args.stage](out)
