#!/usr/bin/env python3
"""Two independent, frozen emitter repairs; no runtime-feedback selection."""
import argparse
import csv
import json
from pathlib import Path
import platform
import re
import shutil

from cv32e40p_compare import ROOT, CXX, CFLAGS, identity, run, save, sample, signature, summarize_named
from cv32e40p_event_regions_compare import check, shapes, source_inventory
from cv32e40p_equality_family_compare import family_sites
from cv32e40p_mux_input_cache_compare import cache_sites
from cv32e40p_repair_compare import (GRAPH, HARNESS, emit_environment, same_sources, compile_model,
                                   cone_sites, verify, diagnose, native_library)

BASE=ROOT/'build/cv32e40p/mux-input-cache-v1'
BASELINE='grhsim_mux_input_cache'
CANDIDATES={'grhsim_conditional_wide':'WOLVRIX_GRHSIM_CONDITIONAL_MUX_WIDE',
            'grhsim_local_predicate_sets':'WOLVRIX_GRHSIM_LOCAL_PREDICATE_SETS'}


def sites(folder):
    text='\n'.join(p.read_text() for p in sorted(folder.glob('*_sched_*.cpp')))
    return dict(wide_operations=list(map(int,re.findall(r'Conditional wide operation: op=(\d+)',text))),
        predicate_sets=[dict(root=int(a),constants=int(b),intervals=int(c)) for a,b,c in
                        re.findall(r'Local predicate set: root=(\d+) constants=(\d+) intervals=(\d+)',text)])


def summaries(rows):
    return {candidate:{baseline:summarize_named(rows,candidate,baseline) for baseline in (BASELINE,'verilator')}
            for candidate in CANDIDATES}


def build(out,tools,jobs):
    if not platform.node().startswith('node030'):raise ValueError('build on node030 for -march=native')
    if out.exists():raise FileExistsError(out)
    original=check(BASE);out.mkdir(parents=True)
    (out/'firmware').symlink_to(BASE/'firmware');(out/'verification.json').symlink_to(BASE/'verification.json')
    native=out/'native-frozen';native.mkdir()
    for src in (tools/'cv32e40p_emit',tools/'cv32e40p_map',native_library(tools)):shutil.copy2(src,native/src.name)
    snapshot=out/'source-snapshot';snapshot.mkdir()
    for src in (ROOT/'wolvrix/lib/emit/grhsim_cpp.cpp',ROOT/'wolvrix/tests/emit/test_emit_grhsim_consumer_structure.cpp',
                ROOT/'wolvrix/CMakeLists.txt',ROOT/'testcase/cv32e40p-bench/emit.cpp',
                ROOT/'scripts/cv32e40p_repair_compare.py',Path(__file__).resolve()):shutil.copy2(src,snapshot/src.name)
    save(out/'hypothesis.json',dict(
        wide='Allow private concat/assign/static-slice/dynamic-slice word operations up to 4096 bits inside existing closed conditional cones. Reuse original word semantics; do not merge views or change activity interfaces.',
        predicates='Lower dense same-source local equality OR consumers to unsigned interval membership inside the emitter. Preserve original IR, schedule, boundary slots, sparse caches and conditional cone ownership.',
        bounds=dict(wide_bits=4096,cone_operations=[16,256],predicate_leaves=512,predicate_visits=2048,
                    predicate_min_constants=16,predicate_min_constants_per_interval=8),
        protocol='Both rules fixed before execution, tested independently against the same retained baseline and Verilator. One eight-round forward/reverse four-backend comparison. No combined candidate, post-run threshold adjustment, source-name selection or feedback into generation.'))
    env=emit_environment(native)
    env.update(CV32_EVENT_REGIONS_SHARED='1',WOLVRIX_GRHSIM_SHARED_EQUALITY_FAMILIES='1',
               WOLVRIX_GRHSIM_CONDITIONAL_MUX_INPUT_CACHE='1',**{key:'0' for key in CANDIDATES.values()})
    run([native/'cv32e40p_emit',GRAPH,out/'off-source','off'],out/'logs/off-emit.log',env=env)
    if not same_sources(out/'off-source',BASE/BASELINE):raise ValueError('retained source drift')
    baseline=shapes(BASE/BASELINE);models={};source_records=[]
    for name,option in CANDIDATES.items():
        candidate_env=dict(env);candidate_env[option]='1'
        run([native/'cv32e40p_emit',GRAPH,out/name,'off'],out/'logs'/f'{name}-emit.log',env=candidate_env)
        if identity(out/name/'normalized.json')['sha256']!=identity(BASE/BASELINE/'normalized.json')['sha256']:
            raise ValueError('IR changed: '+name)
        shape=shapes(out/name)
        for field in ('checked_values','supernodes','value_slots'):
            if shape[field]!=baseline[field]:raise ValueError('activity boundary changed: '+field)
        if family_sites(out/name)!=family_sites(BASE/BASELINE):raise ValueError('persistent equality families changed')
        if cache_sites(out/name)!=cache_sites(BASE/BASELINE):raise ValueError('exact input cache sites changed')
        found=sites(out/name)
        if name=='grhsim_conditional_wide':
            if not found['wide_operations'] or found['predicate_sets']:raise ValueError('wide rule coverage mismatch')
        else:
            if not found['predicate_sets'] or found['wide_operations']:raise ValueError('predicate rule coverage mismatch')
            if cone_sites(out/name)!=cone_sites(BASE/BASELINE):raise ValueError('scalar conditional cones changed')
        models[name]=dict(shape=shape,sites=found,options={k:candidate_env[k] for k in CANDIDATES.values()})
        source_records.extend(source_inventory(out/name).values())
    shutil.copy2(BASE/'sources.csv',out/'sources.csv')
    save(out/'structure.json',dict(baseline=baseline,models=models,off_sources_equal=True,graph_equal=True,
        region_membership_equal=True,boundary_slots_equal=True,cache_sites_equal=True,emitted_sources=source_records))
    # Structure and policy are frozen before compiling or running either candidate.
    for name in CANDIDATES:compile_model(out/name,out,name,jobs)
    for name in (BASELINE,'verilator'):
        (out/name).mkdir();shutil.copy2(original['binaries'][name]['path'],out/name/'emu')
    backends=[BASELINE,*CANDIDATES,'verilator']
    save(out/'build.json',dict(feature='independent_consumer_structure_repairs',backends=backends,candidates=list(CANDIDATES),
        flags=CFLAGS,binaries={b:identity(out/b/'emu') for b in backends},
        frozen_inputs=[identity(p) for p in (BASE/'build.json',GRAPH,HARNESS,CXX,out/'hypothesis.json',out/'structure.json',
                        out/'verification.json',out/'sources.csv',*native.iterdir(),*snapshot.iterdir())]+source_records))
    print(json.dumps({name:v['sites'] for name,v in models.items()},indent=2))


def measure(out):
    manifest=check(out);backends=manifest['backends']
    if (out/'pairs.json').exists():raise FileExistsError('measurement already started')
    functional=json.loads((out/'functional.json').read_text())
    if functional['status']!='pass' or functional['build']!=identity(out/'build.json'):raise ValueError('functional gate mismatch')
    save(out/'measurement-policy.json',dict(rounds=8,repetitions=1,cpu=96,numa=1,aslr=False,
        order='forward/reverse alternating',backends=backends,max_pair_attempts=2,bootstrap_seed=20261114,
        policy='Two independent statically frozen rules; no selection or regeneration from measurement results.'))
    warmups={b:sample(out,b,'coremark','warmup') for b in backends}
    for b,row in warmups.items():
        if signature(row)!=signature(functional['workloads']['coremark'][b]):raise ValueError('warmup signature drift')
    save(out/'warmups.json',warmups)
    rows=[]
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
        rows.append(row);save(out/'pairs.json',rows)
        print(f'round {index+1}/8 complete',flush=True)
    summary=summaries(rows);save(out/'summary.json',summary)
    with (out/'pairs.csv').open('w') as stream:
        writer=csv.writer(stream);writer.writerow(['pair','order',*[f'{b}_{m}' for b in backends for m in ('wall_s','sim_s','init_s')]])
        for row in rows:writer.writerow([row['pair'],'>'.join(row['order']),*[row[b][m] for b in backends for m in ('wall_s','sim_s','init_s')]])
    save(out/'report.json',dict(build=manifest,summaries=summary,structure=json.loads((out/'structure.json').read_text()),
        functional=identity(out/'functional.json'),policy=identity(out/'measurement-policy.json')))
    print(json.dumps({c:{b:s['wall_s'] for b,s in v.items()} for c,v in summary.items()},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('build','verify','measure','diagnose'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--tools',type=Path,default=ROOT/'build/cv32e40p/tools')
    parser.add_argument('--jobs',type=int,default=12)
    args=parser.parse_args();out=args.output.resolve()
    if args.stage=='build':build(out,args.tools.resolve(),args.jobs)
    else:{'verify':verify,'measure':measure,'diagnose':diagnose}[args.stage](out)
