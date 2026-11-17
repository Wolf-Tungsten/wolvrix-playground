#!/usr/bin/env python3
"""Offline source/ELF audit of the fixed XiangShan no-cones ablation."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

from grhsim_single_baseline import identity, save
from xiangshan_cv32_structure import cpp, machine


def sites(folder):
    result=dict(cones=[],caches=[],families=[],views=[],composed=[],groups=[])
    patterns={
        'cones':r'Conditional mux cone: root=(\d+) true_ops=(\d+) false_ops=(\d+)',
        'caches':r'Conditional mux input cache: root=(\d+) inputs=(\d+)',
        'families':r'Shared equality family: source=(\d+) predicates=(\d+)',
        'views':r'Covered state view: value=(\d+) source=(\d+) producer=(\d+) targets=(\d+) mode=(\w+)',
        'composed':r'Composed state expression: value=(\d+) ops=(\d+) mode=(\w+)',
        'groups':r'// Supernode (\d+):'}
    for path in sorted(folder.glob('*_sched_*.cpp')):
        with path.open() as stream:
            for line_no,line in enumerate(stream,1):
                if '// ' not in line:continue
                for key,pattern in patterns.items():
                    match=re.search(pattern,line)
                    if match:
                        result[key].append(dict(fields=list(match.groups()),file=path.name,line=line_no))
    return result


def normalized_sites(records):
    return sorted((tuple(record['fields']),record['file']) for record in records)


def analyze(root):
    baseline=root/'full';candidate=root/'no_cones';out=root/'cone-analysis';out.mkdir(exist_ok=True)
    if not (candidate/'binary.json').exists():raise ValueError('candidate build is not complete')
    before,after=sites(baseline/'model'),sites(candidate/'model')
    oldviews={x['fields'][0]:x for x in before['views']}
    newviews={x['fields'][0]:x for x in after['views']}
    oldcomp={x['fields'][0]:x for x in before['composed']}
    newcomp={x['fields'][0]:x for x in after['composed']}
    checks=dict(no_conditional_cones=not after['cones'],no_input_caches=not after['caches'],
        group_id_and_file_sequence_equal=normalized_sites(before['groups'])==normalized_sites(after['groups']),
        shared_equality_families_equal=normalized_sites(before['families'])==normalized_sites(after['families']))
    if not all(checks.values()):raise ValueError('ablation structural invariant failed: '+str(checks))
    census=dict(cones=len(before['cones']),one_arm=sum('0' in x['fields'][1:] for x in before['cones']),
        absorbed_ops=sum(int(x['fields'][1])+int(x['fields'][2]) for x in before['cones']),
        caches=len(before['caches']),cache_keys=sum(int(x['fields'][1]) for x in before['caches']))
    view_delta=dict(before=len(oldviews),after=len(newviews),
        added=[newviews[v] for v in sorted(newviews.keys()-oldviews.keys(),key=int)],
        removed=[oldviews[v] for v in sorted(oldviews.keys()-newviews.keys(),key=int)],
        changed=[dict(before=oldviews[v],after=newviews[v]) for v in oldviews.keys()&newviews.keys()
                 if oldviews[v]['fields']!=newviews[v]['fields']],
        composition_before=len(oldcomp),composition_after=len(newcomp),
        composition_added=[newcomp[v] for v in sorted(newcomp.keys()-oldcomp.keys(),key=int)],
        composition_removed=[oldcomp[v] for v in sorted(oldcomp.keys()-newcomp.keys(),key=int)])
    save(out/'sites.json',dict(full=before,no_cones=after,checks=checks,census=census,views=view_delta))
    print('source site audit complete',checks,view_delta['before'],view_delta['after'],flush=True)
    original=baseline.resolve().parent/'offline-structure/after.json'
    if original.exists():
        full=json.loads(original.read_text())
        if full['machine']['binary']['sha256']!=identity(baseline/'emu/grhsim-compile/emu')['sha256']:
            raise ValueError('existing full ELF audit does not match binary')
    else:full=dict(cpp=cpp(baseline/'model'),machine=machine(baseline/'emu/grhsim-compile/emu'))
    ablated=dict(cpp=cpp(candidate/'model'),machine=machine(candidate/'emu/grhsim-compile/emu'))
    save(out/'full-machine.json',full['machine']);save(out/'no-cones-machine.json',ablated['machine'])
    save(out/'no-cones-cpp.json',ablated['cpp'])
    differences={}
    for phase in ('compute','commit','eval','other'):
        a=full['machine']['totals'][phase];b=ablated['machine']['totals'][phase]
        differences[phase]={k:dict(full=a.get(k,0),no_cones=b.get(k,0),
            delta=b.get(k,0)-a.get(k,0),percent=100*(b.get(k,0)/a[k]-1) if a.get(k) else None)
            for k in sorted(a.keys()|b.keys())}
    function_deltas=[]
    oldfunctions=full['machine']['functions'];newfunctions=ablated['machine']['functions']
    for name in sorted(oldfunctions.keys()&newfunctions.keys()):
        if not re.fullmatch(r'GrhSIM_SimTop::eval_compute_batch_\d+\(\)',name):continue
        a=oldfunctions[name];b=newfunctions[name]
        function_deltas.append(dict(name=name,
            conditional_branches_delta=b['counts'].get('conditional_branches',0)-a['counts'].get('conditional_branches',0),
            instructions_delta=b['counts']['instructions']-a['counts']['instructions'],
            entry_stack_subtraction_full=sum(a['entry_stack_subtractions']),
            entry_stack_subtraction_no_cones=sum(b['entry_stack_subtractions'])))
    save(out/'report.json',dict(checks=checks,census=census,views=view_delta,
        cpp_counts=dict(full=full['cpp']['counts'],no_cones=ablated['cpp']['counts']),
        machine_deltas=differences,compute_function_deltas=function_deltas,
        inputs=[identity(baseline/'binary.json'),identity(candidate/'binary.json'),identity(out/'sites.json'),identity(__file__)],
        limits='Static counts only; no execution frequency or PMU input. Disabling input caches removes protected keys/results before covered-state-view planning, so any view-site change is an interaction of this fixed ablation. No profile data enters generation.'))
    print(json.dumps(differences['compute'],indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    args=parser.parse_args();analyze(args.source.resolve())
