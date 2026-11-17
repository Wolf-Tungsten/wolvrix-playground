#!/usr/bin/env python3
"""Read frozen XiangShan build and paired-run artifacts; never generate a candidate."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess

from grhsim_single_baseline import identity, save
from xiangshan_cv32_compare import check, read


def model_shape(folder):
    totals=Counter(); values=set(); groups=set(); functions=set()
    sites=Counter(); composed=Counter(); largest=[]
    markers={'conditional_mux_cones':r'Conditional mux cone: root=',
             'conditional_mux_input_caches':r'Conditional mux input cache: root=',
             'shared_equality_families':r'Shared equality family: source=',
             'covered_state_views':r'Covered state view: value=',
             'composed_state_expressions':r'Composed state expression: value='}
    for p in sorted(folder.glob('*.cpp')):
        size=p.stat().st_size;totals['cpp_bytes']+=size;totals['cpp_files']+=1
        if '_sched_' not in p.name:continue
        code=p.read_text();totals['scheduler_bytes']+=size;totals['scheduler_files']+=1
        found=re.findall(r'const bool grhsim_changed_(\d+) =',code)
        values.update(found);totals['scalar_change_check_sites']+=len(found)
        groups.update(re.findall(r'// Supernode (\d+):',code))
        functions.update(re.findall(r'void [\w:]+::(eval_\w+_batch_\d+)\(',code))
        for key,pattern in markers.items():sites[key]+=len(re.findall(pattern,code))
        composed.update(re.findall(r'Composed state expression: value=\d+ ops=\d+ mode=(\w+)',code))
        largest.append((size,p.name))
    header=(folder/'grhsim_SimTop.hpp').read_text()
    slots={kind:int(n) for n,kind in re.findall(r'std::array<[^\n]+?, (\d+)> value_(\w+)_slots_',header)}
    return dict(**totals,checked_values=len(values),supernodes=len(groups),batch_functions=len(functions),
                sites=dict(sites),composed_modes=dict(composed),value_slots=slots,
                largest_scheduler_files=sorted(largest,reverse=True)[:5],
                limits='Static declarations and check sites, not dynamic operations or a time attribution.')


def report(out):
    check(out)
    models={}
    for variant in ('before','after'):
        dest=out/variant
        models[variant]=dict(source=model_shape(dest/'model'),binary=read(dest/'binary.json'),
            emit=read(dest/'logs/emit.result.json'),compile=read(dest/'logs/compile.result.json'),
            schedule_records=[line for line in (dest/'logs/emit.log').read_text().splitlines()
                if any(key in line for key in ('event-regions:', 'compute-node final split detail:',
                                              'activity-schedule: path='))],
            elf_sections=subprocess.check_output(['size',dest/'emu/grhsim-compile/emu'],text=True))
    result=dict(policy=read(out/'policy.json'),models=models,
        inputs=[identity(out/'inputs.json'),identity(out/'policy.json'),identity(Path(__file__))])
    paired=out/'paired'
    if (paired/'summary.json').exists():
        summary=read(paired/'summary.json')
        result['timing']={k:v for k,v in summary.items() if k not in ('samples','trace_checks','historical')}
        result['traces']={str(seed):read(paired/f'trace-s{seed}.json') for seed in (0,1)}
        result['placement']=dict(samples=sum(len(row['order']) for row in summary['samples']),
            all_cpu96_single_thread=all(s['cpu']==96 and s['max_threads']==1
                for row in summary['samples'] for s in (row['A'],row['B'])),
            all_locality_pass=all(s['locality_pass'] for row in summary['samples'] for s in (row['A'],row['B'])),
            sibling_idle=[s['sibling_idle'] for row in summary['samples'] for s in (row['A'],row['B'])])
        result['inputs'] += [identity(paired/n) for n in ('summary.json','pairs.json','manifest.json','trace-s0.json','trace-s1.json')]
    save(out/'report.json',result)
    print(json.dumps(result.get('timing',models),ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report(args.output.resolve())
