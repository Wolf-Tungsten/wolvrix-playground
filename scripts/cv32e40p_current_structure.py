#!/usr/bin/env python3
"""Offline C++/ELF audit of frozen CV32E40P models; never runs a simulator."""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
import json
from pathlib import Path
import re
import subprocess

from cv32e40p_compare import ROOT, identity, save
from cv32e40p_binary_shape import function_symbols, instructions, instruction_shape
from cv32e40p_structure import generated_comparisons, user_boundaries, terminal_reachability

LLVM=Path('/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin')
ART=ROOT/'build/cv32e40p'
RUN=ART/'joint-notify-cache-v1'
SOURCES={
    'retained':ART/'mux-input-cache-v1/grhsim_mux_input_cache',
    'joint':RUN/'grhsim_joint_notify_cache',
    'verilator':ART/'run2/verilator'}
BACKENDS={'retained':'grhsim_mux_input_cache','joint':'grhsim_joint_notify_cache','verilator':'verilator'}
COUNTERS={'retained':ART/'mux-input-cache-counts-v1','joint':ART/'joint-notify-counts-v1'}


def read(path):return json.loads(path.read_text())


def is_stack(operands):
    return bool(re.search(r'\(%(?:rsp|rbp)(?:,|\))',operands))


def peak_source_spans(spans):
    """Lexical lifetimes only; not compiler liveness or dynamic register usage."""
    events=Counter()
    for first,last in spans:
        if last<first:raise ValueError('reversed source span')
        events[first]+=1;events[last+1]-=1
    current=peak=where=0
    for line,delta in sorted(events.items()):
        current+=delta
        if current>peak:peak,where=current,line
    return dict(peak=peak,line=where)


def model_frame(frames,folder):
    for frame in frames:
        path=Path(frame.get('FileName',''))
        if path.parent==folder and path.suffix=='.cpp':
            return dict(file=path.name,line=frame['Line'],function=frame['FunctionName'])
    return None


def source_lines(folder):
    return {p.name:p.read_text().splitlines() for p in sorted(folder.glob('*.cpp'))}


def elf_model(label,folder,out):
    def chosen(name):
        if label!='verilator':
            return name.startswith('GrhSIM_Cv32Bench::eval') or name=='GrhSIM_Cv32Bench::refresh_outputs()'
        return (name.startswith('VCv32Bench___024root___') and
                any(k in name for k in ('___nba_', '___act_', '___ico_', '___eval(', '___eval_ico', '___eval_act', '___eval_nba')))
    symbols=[s for s in function_symbols(folder/'emu') if chosen(s['symbol'])]
    seen=set();selected=[]
    for s in symbols:
        if s['address'] not in seen:selected.append(s);seen.add(s['address'])
    directory=out/'assembly'/label;directory.mkdir(parents=True)
    all_rows=[];functions=[]
    for s in selected:
        asm=subprocess.check_output([LLVM/'llvm-objdump','-d','--demangle','--no-show-raw-insn',
            f'--start-address=0x{s["address"]:x}',f'--stop-address=0x{s["address"]+s["bytes"]:x}',folder/'emu'],text=True)
        (directory/f'{s["address"]:x}.s').write_text(asm)
        rows=instructions(asm)
        for r in rows:r.update(function=s['symbol'],stack=is_stack(r['operands']))
        functions.append(dict(**s,**instruction_shape(rows),
            stack_frame_subtractions=[r['operands'] for r in rows if r['mnemonic']=='subq' and '%rsp' in r['operands']]))
        all_rows+=rows
    output=subprocess.check_output([LLVM/'llvm-symbolizer','--obj='+str(folder/'emu'),'--output-style=JSON','--inlines'],
                                  input=''.join(f'0x{r["address"]:x}\n' for r in all_rows),text=True)
    frames=[json.loads(line) for line in output.splitlines() if line.strip()]
    if len(frames)!=len(all_rows):raise ValueError('symbolizer row count mismatch')
    for row,entry in zip(all_rows,frames):
        if int(entry['Address'],16)!=row['address']:raise ValueError('symbolizer address mismatch')
        row['model_source']=model_frame(entry['Symbol'],folder)
        row['leaf_source']=entry['Symbol'][0] if entry['Symbol'] else None
    with gzip.open(out/f'{label}-instructions.json.gz','wt') as stream:json.dump(all_rows,stream)
    sections=subprocess.check_output(['readelf','-SW',folder/'emu'],text=True)
    (out/f'{label}-sections.txt').write_text(sections)
    return dict(functions=functions,model_source_mapped=sum(r['model_source'] is not None for r in all_rows),
                selected_instructions=len(all_rows)),all_rows


def source_instruction_shape(rows,locations):
    selected=[r for r in rows if r['model_source'] and
              (r['model_source']['file'],r['model_source']['line']) in locations]
    return dict(instructions=len(selected),stack_operands=sum(r['stack'] for r in selected),
                mnemonics=dict(Counter(r['mnemonic'] for r in selected)),
                examples=selected[:10])


def grhsim_source(label,folder,counts,asmrows):
    graph=read(folder/'normalized.json')['graphs'][0]
    values={v['sym']:v for v in graph['vals']};ops={o['sym']:o for o in graph['ops']}
    mapping=list(csv.DictReader((RUN/'sources.csv').open()))
    schedule={r['op_symbol']:r for r in mapping};ids={}
    for r in mapping:
        op=ops[r['op_symbol']]
        if op['kind']!=r['op_kind'] or op['out']!=list(filter(None,r['value_symbols'].split(';'))):
            raise ValueError('IR/source mapping differs')
        for index,symbol in zip(r['value_ids'].split(';'),r['value_symbols'].split(';')):
            if index:ids[index]=dict(r,value=symbol)
    n=counts['cycles'];rates={k:sum(v)/n for k,v in counts['counts'].items()}
    checks=generated_comparisons(sorted(folder.glob('*_sched_*.cpp')))
    events=set()
    for op in graph['ops']:
        edges=op.get('attrs',{}).get('eventEdge',{}).get('vs',[])
        if edges:events.update(op['in'][-len(edges):])
    outputs={p['val']:p['name'] for p in graph['ports']['out']}
    terminals=terminal_reachability(values,ops,schedule,outputs)
    rows=[];kinds=defaultdict(lambda:dict(values=0,comparisons=0,changes=0))
    for index,code in checks.items():
        meta=ids[index];v=values[meta['value']]
        if int(meta['group'])!=code['group']:raise ValueError('comparison group mismatch')
        row=dict(id=index,symbol=v['sym'],width=v['w'],kind=ops[v['def']]['kind'],**code,
            comparisons=rates['cmp:'+index],changes=rates['chg:'+index],
            **user_boundaries(v,code['group'],schedule,events),
            terminal_uses=sorted(terminals(v['sym'])))
        rows.append(row);kind=kinds[row['kind']];kind['values']+=1;kind['comparisons']+=row['comparisons'];kind['changes']+=row['changes']
    if abs(sum(r['comparisons'] for r in rows)-rates['scalar_comparisons'])>1e-7:raise ValueError('comparison accounting')
    def total(subset):return dict(values=len(subset),comparisons=sum(r['comparisons'] for r in subset),changes=sum(r['changes'] for r in subset))
    boundaries=dict(all=total(rows),compute_only=total([r for r in rows if r['compute_boundary_only']]),
                    one_bit=total([r for r in rows if r['width']==1]),
                    terminal_sets=[dict(terminals=list(key),**total([r for r in rows if tuple(r['terminal_uses'])==key]))
                                   for key in sorted({tuple(r['terminal_uses']) for r in rows})])
    texts=source_lines(folder);families=defaultdict(list);materialized=set();wide=[];group_lines={}
    for filename,lines in texts.items():
        if '_sched_' not in filename:continue
        group=None;uses=defaultdict(list)
        for line,text in enumerate(lines,1):
            for token in set(re.findall(r'\bgrhsim_v\d+_0\b',text)):uses[token].append(line)
        for line,text in enumerate(lines,1):
            m=re.search(r'// Supernode (\d+):',text)
            if m:group=int(m[1])
            group_lines[filename,line]=group
            m=re.search(r'// value .* \[value_id=(\d+):0\]',text)
            if m:materialized.add(m[1])
            m=re.search(r'const bool grhsim_v(\d+)_0 = .+ == ',text)
            if m:
                index=m[1];v=values[ids[index]['value']];op=ops[v['def']]
                const=[x for x in op['in'] if values[x].get('def') and ops[values[x]['def']]['kind']=='kConstant']
                if op['kind']=='kEq' and len(const)==1:
                    source=next(x for x in op['in'] if x!=const[0]);token='grhsim_v'+index+'_0'
                    families[group,source].append(dict(value=index,file=filename,line=line,last_use=uses[token][-1],
                        constant=ops[values[const[0]]['def']]['attrs']['constValue']['v']))
            m=re.search(r'(?:const auto |std::array<[^;]+> )(grhsim_v(\d+)_0)(?:\{| =)',text)
            if m and m[2] in ids:
                v=values[ids[m[2]]['value']]
                if v['w']>64:wide.append(dict(value=m[2],symbol=v['sym'],width=v['w'],kind=ops[v['def']]['kind'],
                    file=filename,line=line,last_use=uses[m[1]][-1],group=group))
    family_rows=[]
    for (group,source),predicates in sorted(families.items(),key=lambda x:(-len(x[1]),x[0])):
        source_id=next((i for i,m in ids.items() if m['value']==source),None)
        locs={(p['file'],p['line']) for p in predicates}
        per_file={}
        for filename in sorted({p['file'] for p in predicates}):
            per_file[filename]=peak_source_spans([(p['line'],p['last_use']) for p in predicates if p['file']==filename])
        family_rows.append(dict(group=group,source=source,source_id=source_id,width=values[source]['w'],
            standalone_local_eq=len(predicates),source_checks=rates.get('cmp:'+str(source_id)),
            source_changes=rates.get('chg:'+str(source_id)),region_executions=rates['group:'+str(group)],
            lexical_spans=per_file,source_line_instructions=source_instruction_shape(asmrows,locs),predicates=predicates))
    group_shape=defaultdict(Counter)
    for row in asmrows:
        loc=row['model_source']
        if not loc:continue
        group=group_lines.get((loc['file'],loc['line']))
        if group is not None:
            group_shape[group]['instructions']+=1;group_shape[group]['stack_operands']+=row['stack']
    groups=[]
    for group in sorted({int(m['group']) for m in mapping}):
        entries=[m for m in mapping if int(m['group'])==group];phase=entries[0]['phase']
        groups.append(dict(group=group,phase=phase,batch=int(entries[0]['batch']),scheduled_ops=len(entries),
            kinds=dict(Counter(m['op_kind'] for m in entries)),executions_by_phase=[v/n for v in counts['counts'].get('group:'+str(group),[0]*4)],
            checks=total([r for r in rows if r['group']==group]),machine_source_attribution=dict(group_shape[group])))
    commit_inputs=[]
    for index in sorted(materialized,key=int):
        if index not in ids:continue
        meta=ids[index];v=values[meta['value']]
        boundary=user_boundaries(v,int(meta['group']),schedule,events)
        if boundary['commit_targets'] and not boundary['compute_targets'] and not boundary['public_output'] and not boundary['event']:
            commit_inputs.append(dict(id=index,symbol=v['sym'],width=v['w'],group=int(meta['group']),
                                      change_tracked=index in checks,commit_targets=boundary['commit_targets']))
    return dict(boundaries=boundaries,comparison_kinds=dict(kinds),checks=rows,groups=groups,
                local_eq_families=family_rows,wide_locals=wide,commit_only_materialized_inputs=commit_inputs,
                materialized_commented_values=len(materialized),
                scalar_slot_counts={kind:int(size) for size,kind in re.findall(r'std::array<[^\n]+?, (\d+)> value_(\w+)_slots_', (folder/'grhsim_Cv32Bench.hpp').read_text())},
                rounds=[v/n for v in counts['counts']['round']])


def run(out):
    if out.exists():raise FileExistsError(out)
    manifest=read(RUN/'build.json');functional=read(RUN/'functional.json')
    reference=functional['workloads']['coremark']['verilator'];inputs=[]
    if reference['cycles']!=3376065:raise ValueError('workload changed')
    for label,folder in SOURCES.items():
        actual=identity(folder/'emu');expected=manifest['binaries'][BACKENDS[label]]
        if any(actual[k]!=expected[k] for k in ('sha256','bytes')):raise ValueError('ELF identity mismatch')
        inputs.append(actual)
        inputs += [identity(p) for p in sorted(folder.glob('*')) if p.suffix in ('.cpp','.hpp','.h')]
    observed={}
    for label,path in COUNTERS.items():
        original=read(path/'inputs.json')['model'];elf=identity(SOURCES[label]/'emu')
        if any(original[k]!=elf[k] for k in ('sha256','bytes')):raise ValueError('counter ELF mismatch')
        data=read(path/'counts.json')['coremark']
        if data['cycles']!=reference['cycles'] or data['trace']['sha256']!=reference['trace']['sha256']:raise ValueError('counter workload mismatch')
        observed[label]=data;inputs += [identity(path/'inputs.json'),identity(path/'counts.json')]
    prior=read(ART/'code-shapes-v1/static.json')['models']['verilator']
    for record in [prior['binary'],prior['header'],*prior['sources']]:
        if identity(Path(record['path']))!=record:raise ValueError('Verilator source/counter origin mismatch')
    vc=read(ART/'code-shapes-v1/counts.json')['verilator']['coremark']
    if vc['cycles']!=reference['cycles'] or vc['trace']['sha256']!=reference['trace']['sha256']:raise ValueError('Verilator counter workload mismatch')
    out.mkdir(parents=True)
    models={}
    for label,folder in SOURCES.items():
        elf,rows=elf_model(label,folder,out);models[label]=dict(elf=elf,binary=identity(folder/'emu'))
        if label!='verilator':models[label]['cpp']=grhsim_source(label,folder,observed[label],rows)
        else:
            models[label]['function_counts']={k:[v/vc['cycles'] for v in a] for k,a in vc['counts'].items()}
            header=(folder/'VCv32Bench___024root.h').read_text()
            models[label]['onehot_tables']=re.findall(r'VlUnpacked<CData/\*0:0\*/, (\d+)> (__VdfgBinToOneHot_Tab_\w+)',header)
    inputs += [identity(p) for p in (RUN/'build.json',RUN/'functional.json',RUN/'sources.csv',RUN/'summary.json',RUN/'repair-analysis.json',
        ART/'code-shapes-v1/counts.json',ART/'code-shapes-v1/static.json',Path(__file__).resolve(),
        *(SOURCES[label]/'normalized.json' for label in ('retained','joint')))]
    report=dict(models=models,inputs=inputs,scope='Offline frozen C++/ELF/IR and existing counters. No simulator executions, perf sampling, tuning, candidate selection or production edits.',
        limits='DWARF mappings are approximate and can reflect folded/moved instructions. Static stack operands are not dynamic spills. Lexical source spans are not compiler liveness. Existing exact execution counts are not time percentages; no current-symbol sampled profile exists for these GrhSIM binaries.',
        reference=dict(cycles=reference['cycles'],trace=reference['trace']['sha256']),measurement=read(RUN/'summary.json'))
    save(out/'report.json',report)
    for label,d in models.items():
        print(label,'ELF instructions',d['elf']['selected_instructions'],'mapped',d['elf']['model_source_mapped'])
        if label!='verilator':
            c=d['cpp'];print('boundaries',c['boundaries']['all'],c['boundaries']['compute_only'])
            print('families',[(f['source'],f['standalone_local_eq'],f['source_line_instructions']['instructions'],f['source_line_instructions']['stack_operands']) for f in c['local_eq_families'][:2]])
            print('commit-only slots',len(c['commit_only_materialized_inputs']))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();run(args.output.resolve())
