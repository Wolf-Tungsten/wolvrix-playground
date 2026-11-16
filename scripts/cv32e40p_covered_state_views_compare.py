#!/usr/bin/env python3
"""Fixed two-stage comparison of statically covered register view boundaries."""
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
NOTIFY='grhsim_covered_view_notify'
INLINE='grhsim_covered_view_inline'
NOTIFY_OPTION='WOLVRIX_GRHSIM_COVERED_STATE_VIEW_NOTIFICATIONS'
INLINE_OPTION='WOLVRIX_GRHSIM_COVERED_STATE_VIEW_INLINE'


def sites(folder):
    found=[]
    for path in sorted(folder.glob('*_sched_*.cpp')):
        for value,source,producer,targets,mode in re.findall(
            r'Covered state view: value=(\d+) source=(\d+) producer=(\d+) targets=(\d+) mode=(inline|notify)',path.read_text()):
            found.append(dict(value=int(value),source=int(source),producer=int(producer),targets=int(targets),mode=mode,file=path.name))
    return sorted(found,key=lambda v:v['value'])


def summaries(rows):
    return {NOTIFY:{b:summarize_named(rows,NOTIFY,b) for b in (BASELINE,'verilator')},
            INLINE:{b:summarize_named(rows,INLINE,b) for b in (NOTIFY,BASELINE,'verilator')}}


def audit_sites(folder,mapping,selected):
    graph=json.loads((folder/'normalized.json').read_text())['graphs'][0]
    values={v['sym']:v for v in graph['vals']};ops={o['sym']:o for o in graph['ops']}
    rows=list(csv.DictReader(mapping.open()));byop={r['op_symbol']:r for r in rows};byid={}
    for row in rows:
        for i,n in zip(row['value_ids'].split(';'),row['value_symbols'].split(';')):
            if i:byid[int(i)]=n
    direct={}
    for row in rows:
        op=ops[row['op_symbol']]
        if op['kind']=='kRegisterReadPort' and not op['in']:
            direct.setdefault(op['attrs']['regSymbol']['v'],set()).add(int(row['group']))
    proof=[]
    for site in selected:
        value=byid[site['value']];source=byid[site['source']]
        op=ops[values[value]['def']];read=ops[values[source]['def']]
        if op['kind'] not in ('kSliceStatic','kNot','kLogicNot','kAssign') or op['in']!=[source]:
            raise ValueError('not a single scalar view')
        if read['kind']!='kRegisterReadPort' or read['in']:raise ValueError('not a direct register read')
        state=read['attrs']['regSymbol']['v'];producer=site['producer']
        if int(byop[read['sym']]['group'])!=producer or int(byop[op['sym']]['group'])!=producer:
            raise ValueError('source is not in producer snapshot')
        consumers=set()
        for user in graph['ops']:
            if value not in user['in'] or user['sym'] not in byop:continue
            row=byop[user['sym']]
            if row['phase']!='compute':raise ValueError('commit escape')
            consumers.add(int(row['group']))
        if len(consumers-{producer})!=site['targets']:raise ValueError('target count mismatch')
        if not (consumers|{producer}).issubset(direct[state]):raise ValueError('consumer lacks independent direct state read')
        proof.append(dict(**site,symbol=value,state=state,kind=op['kind'],width=values[value]['w'],
                          consumer_groups=sorted(consumers),existing_direct_read_groups=sorted(direct[state])))
    return proof


def build(out,tools,jobs):
    if not platform.node().startswith('node030'):raise ValueError('build on node030 for -march=native')
    if out.exists():raise FileExistsError(out)
    original=check(BASE);out.mkdir(parents=True)
    (out/'firmware').symlink_to(BASE/'firmware');(out/'verification.json').symlink_to(BASE/'verification.json')
    native=out/'native-frozen';native.mkdir()
    for src in (tools/'cv32e40p_emit',tools/'cv32e40p_map',native_library(tools)):shutil.copy2(src,native/src.name)
    snapshot=out/'source-snapshot';snapshot.mkdir()
    for src in (ROOT/'wolvrix/lib/emit/grhsim_cpp.cpp',ROOT/'wolvrix/tests/emit/test_emit_grhsim_covered_state_views.cpp',
                ROOT/'wolvrix/CMakeLists.txt',ROOT/'testcase/cv32e40p-bench/emit.cpp',
                ROOT/'scripts/cv32e40p_repair_compare.py',Path(__file__).resolve()):shutil.copy2(src,snapshot/src.name)
    save(out/'hypothesis.json',dict(
        rule='A single scalar slice/not/logical-not/assign of a local register read, with one commit writer. Producer and every pure compute consumer must already be direct state activation heads, with producer ordered before consumers. Preserve event/public/waveform/alias/cache uses.',
        stages={NOTIFY:'Remove only proven redundant value change detection and fanout; keep original slot/store.',
                INLINE:'Apply identical proof and additionally replace every selected value by a typed state view; remove its slot and producer assignment.'},
        scope='No Eq family change, expanded state frontier, new group fusion, graph rewrite or profile input.',
        protocol='One fixed eight-round forward/reverse four-backend measurement after all structural and functional checks. No post-run candidate, threshold, or combination selection.'))
    env=emit_environment(native)
    env.update(CV32_EVENT_REGIONS_SHARED='1',WOLVRIX_GRHSIM_SHARED_EQUALITY_FAMILIES='1',
               WOLVRIX_GRHSIM_CONDITIONAL_MUX_INPUT_CACHE='1',**{NOTIFY_OPTION:'0',INLINE_OPTION:'0'})
    run([native/'cv32e40p_emit',GRAPH,out/'off-source','off'],out/'logs/off-emit.log',env=env)
    if not same_sources(out/'off-source',BASE/BASELINE):raise ValueError('retained source drift')
    shutil.copy2(BASE/'sources.csv',out/'sources.csv')
    baseline=shapes(BASE/BASELINE);models={};records=[]
    for name,inline in ((NOTIFY,'0'),(INLINE,'1')):
        candidate_env=dict(env);candidate_env.update({NOTIFY_OPTION:'1',INLINE_OPTION:inline})
        run([native/'cv32e40p_emit',GRAPH,out/name,'off'],out/'logs'/f'{name}-emit.log',env=candidate_env)
        if identity(out/name/'normalized.json')['sha256']!=identity(BASE/BASELINE/'normalized.json')['sha256']:
            raise ValueError('IR changed')
        selected=sites(out/name)
        if not selected:raise ValueError('no statically covered views')
        shape=shapes(out/name)
        if shape['supernodes']!=baseline['supernodes']:raise ValueError('region count changed')
        if baseline['checked_values']-shape['checked_values']!=len(selected):raise ValueError('comparison count mismatch')
        if name==NOTIFY and shape['value_slots']!=baseline['value_slots']:raise ValueError('notify-only storage drift')
        if name==INLINE and sum(baseline['value_slots'].values())-sum(shape['value_slots'].values())!=len(selected):
            raise ValueError('inline storage reduction mismatch')
        if family_sites(out/name)!=family_sites(BASE/BASELINE):raise ValueError('sparse equality family drift')
        if cache_sites(out/name)!=cache_sites(BASE/BASELINE):raise ValueError('input-cache drift')
        if cone_sites(out/name)!=cone_sites(BASE/BASELINE):raise ValueError('conditional-cone drift')
        proof=audit_sites(out/name,out/'sources.csv',selected)
        models[name]=dict(shape=shape,sites=selected,proof=proof)
        records.extend(source_inventory(out/name).values())
    strip=lambda sites:[{k:v for k,v in s.items() if k!='mode'} for s in sites]
    if strip(models[NOTIFY]['sites'])!=strip(models[INLINE]['sites']):raise ValueError('two stages selected different values')
    save(out/'structure.json',dict(baseline=baseline,models=models,off_sources_equal=True,graph_equal=True,
        same_selected_values=True,region_membership_equal=True,cache_and_conditional_sites_equal=True,emitted_sources=records))
    for name in (NOTIFY,INLINE):compile_model(out/name,out,name,jobs)
    for name in (BASELINE,'verilator'):
        (out/name).mkdir();shutil.copy2(original['binaries'][name]['path'],out/name/'emu')
    backends=[BASELINE,NOTIFY,INLINE,'verilator']
    save(out/'build.json',dict(feature='covered_state_view_boundaries',backends=backends,flags=CFLAGS,
        binaries={b:identity(out/b/'emu') for b in backends},
        frozen_inputs=[identity(p) for p in (BASE/'build.json',GRAPH,HARNESS,CXX,out/'hypothesis.json',out/'structure.json',
                        out/'verification.json',out/'sources.csv',*native.iterdir(),*snapshot.iterdir())]+records))
    print(json.dumps({name:dict(sites=models[name]['sites'],shape=models[name]['shape']) for name in models},indent=2))


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
    parser.add_argument('stage',choices=('build','verify','measure','diagnose'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--tools',type=Path,default=ROOT/'build/cv32e40p/tools');parser.add_argument('--jobs',type=int,default=12)
    args=parser.parse_args();out=args.output.resolve()
    if args.stage=='build':build(out,args.tools.resolve(),args.jobs)
    else:{'verify':verify,'measure':measure,'diagnose':diagnose}[args.stage](out)
