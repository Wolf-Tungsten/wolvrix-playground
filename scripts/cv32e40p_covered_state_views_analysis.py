#!/usr/bin/env python3
"""Account for a frozen boundary rewrite; no runtime input to the optimizer."""
import argparse
import json
from pathlib import Path
import re

from cv32e40p_compare import ROOT, identity, save, signature, summarize_named
from cv32e40p_event_regions_compare import check
from cv32e40p_covered_state_views_compare import BASE, BASELINE, NOTIFY, INLINE
from cv32e40p_repair_analysis import counter_rates
from cv32e40p_conditional_mux_analysis import perf_counts
from cv32e40p_current_structure import elf_model, source_instruction_shape
from cv32e40p_current_structure_paths import verify_embedded_sources


def read(p):return json.loads(p.read_text())


def boundary_evidence(out,structure):
    """Archive source/ELF correspondence, not inferred dynamic instruction costs."""
    evidence=out/'machine-evidence';report=evidence/'report.json'
    folders={BASELINE:BASE/BASELINE,NOTIFY:out/NOTIFY,INLINE:out/INLINE}
    if report.exists():
        previous=read(report)
        for backend,folder in folders.items():
            if previous[backend]['binary']!=identity(folder/'emu'):raise ValueError('evidence binary drift')
            for record in previous[backend]['embedded_source_checksums']:
                actual=identity(Path(record['path']))
                if any(actual[k]!=record[k] for k in actual):raise ValueError('evidence source drift')
        return identity(report)
    evidence.mkdir()
    selected=structure['models'][INLINE]['sites'];result={}
    for backend,folder in folders.items():
        machine,rows=elf_model(backend,folder,evidence)
        sources={p.name:p.read_text().splitlines() for p in folder.glob('*_sched_*.cpp')}
        checksums=verify_embedded_sources(folder,sources)
        all_text='\n'.join('\n'.join(lines) for lines in sources.values());examples=[]
        for site in selected:
            value=site['value'];filename=site['file'];lines=sources[filename]
            if backend!=BASELINE and re.search(r'\bgrhsim_changed_'+str(value)+r'\b',all_text):
                raise ValueError('removed comparison survives in generated source')
            if backend==INLINE:
                if re.search(r'\bgrhsim_value_'+str(value)+r'_0_slot\b',all_text):
                    raise ValueError('inlined value still has a slot reference')
                first=next(i for i,s in enumerate(lines) if f'Covered state view: value={value} ' in s)
                last=first
            else:
                first=next(i for i,s in enumerate(lines) if f'[value_id={value}:0]' in s)
                last=next(i for i in range(first+1,len(lines)) if lines[i].strip()=='}')
            locations={(filename,i+1) for i in range(first,last+1)}
            examples.append(dict(value=value,file=filename,first=first+1,last=last+1,
                source='\n'.join(lines[first:last+1]),machine=source_instruction_shape(rows,locations)))
        result[backend]=dict(binary=identity(folder/'emu'),elf=machine,embedded_source_checksums=checksums,boundaries=examples)
    result['limits']='DWARF attribution can move or combine operations. Source-line instruction counts are static, not exact dynamic savings or a time attribution. Inline comments have no executable definition; consumers may still execute shifts/masks.'
    save(report,result)
    return identity(report)


def compare_counts(old,new,removed):
    if old['cycles']!=new['cycles'] or old['trace']['sha256']!=new['trace']['sha256']:
        raise ValueError('counter workload mismatch')
    counter_rates(old);counter_rates(new)
    a,b=old['counts'],new['counts'];removed={str(v) for v in removed}
    for value in removed:
        if 'cmp:'+value not in a or 'chg:'+value not in a:raise ValueError('missing original value probe')
        if 'cmp:'+value in b or 'chg:'+value in b:raise ValueError('selected comparison still exists')
    # Exact notification OR counts may fall. All actual group, branch, cache,
    # remaining comparison and change counts must remain identical.
    stable={k for k in a.keys()|b.keys() if k not in ('scalar_comparisons','scalar_changes') and
            not k.startswith(('direct_active_or_','notify_reduction_'))}
    stable-={prefix+v for v in removed for prefix in ('cmp:','chg:')}
    differences={k:dict(before=a.get(k),after=b.get(k)) for k in sorted(stable) if a.get(k)!=b.get(k)}
    if differences:raise ValueError('execution/cache/remaining value counts changed: '+str(differences)[:1000])
    removed_comparisons=[sum(a['cmp:'+v][phase] for v in removed) for phase in range(4)]
    removed_changes=[sum(a['chg:'+v][phase] for v in removed) for phase in range(4)]
    if [a['scalar_comparisons'][i]-b['scalar_comparisons'][i] for i in range(4)]!=removed_comparisons:
        raise ValueError('comparison savings do not close')
    if [a['scalar_changes'][i]-b['scalar_changes'][i] for i in range(4)]!=removed_changes:
        raise ValueError('change savings do not close')
    n=old['cycles']
    return dict(invariant_keys=len(stable),all_equal=True,removed_values=len(removed),
        checks_before=sum(a['scalar_comparisons'])/n,checks_after=sum(b['scalar_comparisons'])/n,
        removed_checks=sum(removed_comparisons)/n,removed_changes=sum(removed_changes)/n,
        group_executions={k:sum(v)/n for k,v in b.items() if k.startswith('group:')},
        notification_probes={k:dict(before=a.get(k),after=b.get(k)) for k in sorted(a.keys()|b.keys())
                             if k.startswith(('direct_active_or_','notify_reduction_'))})


def count_gate(out,notify_counts,inline_counts):
    manifest=check(out);structure=read(out/'structure.json');functional=read(out/'functional.json')
    if functional['status']!='pass' or functional['build']!=identity(out/'build.json'):
        raise ValueError('functional/build identity mismatch')
    reference=functional['workloads']['coremark']['verilator']
    dirs={BASELINE:ROOT/'build/cv32e40p/mux-input-cache-counts-v1',NOTIFY:notify_counts,INLINE:inline_counts}
    observed={};inputs=[]
    for b,folder in dirs.items():
        origin=read(folder/'inputs.json');data=read(folder/'counts.json')['coremark']
        if origin['model']['sha256']!=manifest['binaries'][b]['sha256']:raise ValueError('counter ELF mismatch')
        if data['cycles']!=reference['cycles'] or data['trace']['sha256']!=reference['trace']['sha256']:
            raise ValueError('counter workload mismatch')
        observed[b]=data;inputs.extend(identity(folder/f) for f in ('inputs.json','counts.json'))
    counters={b:compare_counts(observed[BASELINE],observed[b],[x['value'] for x in structure['models'][b]['sites']])
              for b in (NOTIFY,INLINE)}
    if observed[NOTIFY]['counts']!=observed[INLINE]['counts']:raise ValueError('two-stage behavior counts differ')
    return dict(build=identity(out/'build.json'),counters=counters,stage_counts_equal=True,
                inputs=inputs+[identity(out/'functional.json'),identity(out/'structure.json')])


def analyze(out,notify_counts,inline_counts):
    manifest=check(out);structure=read(out/'structure.json');functional=read(out/'functional.json')
    diagnostic=read(out/'diagnostics.json');gate=count_gate(out,notify_counts,inline_counts)
    if diagnostic['build']!=identity(out/'build.json'):raise ValueError('diagnostic/build identity mismatch')
    reference=functional['workloads']['coremark']['verilator']
    for row in diagnostic['runs'].values():
        if signature(row)!=signature(reference):raise ValueError('PMU workload mismatch')
    pmu={b:perf_counts(out/(b+'-stat.csv'),reference['cycles']) for b in manifest['backends']}
    counters=gate['counters']
    result=dict(counters=counters,stage_counts_equal=True,pmu=pmu,machine=diagnostic['models'],
        source_and_elf_evidence=boundary_evidence(out,structure),
        summaries=read(out/'summary.json'),baseline_relative_to_verilator=summarize_named(read(out/'pairs.json'),BASELINE,'verilator'),
        instruction_delta_percent={b:100*(pmu[b]['per_guest_cycle']['instructions:u']/pmu[BASELINE]['per_guest_cycle']['instructions:u']-1)
                                   for b in (NOTIFY,INLINE)},
        build_wall_s={p.name:read(p)['wall_s'] for p in (out/'logs').glob('*.result.json')},
        inputs=[identity(out/f) for f in ('build.json','structure.json','functional.json','diagnostics.json','summary.json','pairs.json')]+
               gate['inputs']+[identity(Path(__file__).resolve())],
        limits='PMU is one independent sample including initialization, not a paired time measurement. '
               'Static instruction/stack counts are not dynamic spills. Exact diagnostic counts never feed generation or selection.')
    save(out/'boundary-analysis.json',result)
    print(json.dumps(dict(counters={b:{k:v for k,v in c.items() if k not in ('group_executions','notification_probes')} for b,c in counters.items()},
                         instruction_delta_percent=result['instruction_delta_percent']),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--notify-counts',type=Path,required=True);parser.add_argument('--inline-counts',type=Path,required=True)
    parser.add_argument('--counts-only',action='store_true',help='validate behavior counts before performance measurement')
    args=parser.parse_args();out=args.source.resolve()
    if args.counts_only:
        destination=out/'count-gate.json'
        if destination.exists():raise FileExistsError(destination)
        save(destination,count_gate(out,args.notify_counts.resolve(),args.inline_counts.resolve()))
        print('two stages preserve all remaining behavior counts')
    else:analyze(out,args.notify_counts.resolve(),args.inline_counts.resolve())
