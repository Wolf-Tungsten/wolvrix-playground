#!/usr/bin/env python3
"""Offline audit of the frozen covered-state-view model; never execute an ELF."""
import argparse
from collections import Counter, defaultdict
import csv
from functools import cache
import json
from pathlib import Path
import re

from cv32e40p_compare import ROOT, identity, save
from cv32e40p_event_regions_compare import check
from cv32e40p_current_structure import elf_model, grhsim_source, source_instruction_shape
from cv32e40p_current_structure import RUN as SOURCE_MAP_ORIGIN
from cv32e40p_current_structure_paths import verify_embedded_sources
from cv32e40p_consumer_structure_analysis import wide_paths
from cv32e40p_binary_shape import function_symbols, disassemble, instructions

RUN=ROOT/'build/cv32e40p/covered-state-views-v1'
CURRENT=RUN/'grhsim_covered_view_inline'
VERILATOR=ROOT/'build/cv32e40p/run2/verilator'
COUNTS=ROOT/'build/cv32e40p/covered-view-inline-counts-v1'
ALLOWED={'kSliceStatic','kNot','kLogicNot','kAssign','kEq','kReduceOr',
         'kAnd','kOr','kLogicAnd','kLogicOr','kConcat'}


def read(path):return json.loads(path.read_text())


class StateClosures:
    """Structural screening, not the emitter's full legality/profitability proof."""
    def __init__(self,graph,mapping):
        self.values={v['sym']:v for v in graph['vals']}
        self.ops={op['sym']:op for op in graph['ops']}
        self.mapping={r['op_symbol']:r for r in mapping}
        self.readers=defaultdict(set);self.visiting=set()
        for name,row in self.mapping.items():
            op=self.ops[name]
            if op['kind']=='kRegisterReadPort' and not op['in']:
                self.readers[op['attrs']['regSymbol']['v']].add(int(row['group']))

    @cache
    def closure(self,symbol,group):
        key=symbol,group
        if key in self.visiting:raise ValueError('cycle in state-expression cone')
        value=self.values.get(symbol)
        if not value or not value.get('def') or value['w']>64:return None
        op=self.ops[value['def']];kind=op['kind']
        if op.get('attrs',{}).get('hasSideEffects',{}).get('v',False):return None
        if kind=='kConstant':return frozenset(),frozenset(),0
        where=self.mapping.get(op['sym'])
        if where is None or where['phase']!='compute' or int(where['group'])!=group:return None
        if kind=='kRegisterReadPort' and not op['in']:
            return frozenset([op['attrs']['regSymbol']['v']]),frozenset(),0
        if kind not in ALLOWED:return None
        self.visiting.add(key)
        try:args=[self.closure(x,group) for x in op['in']]
        finally:self.visiting.remove(key)
        if any(x is None for x in args):return None
        return (frozenset().union(*(x[0] for x in args)),
                frozenset([op['sym']]).union(*(x[1] for x in args)),
                1+max((x[2] for x in args),default=0))

    def screen(self,checks,cache_ops):
        rows=[]
        for check in checks:
            if not check['compute_boundary_only']:continue
            cone=self.closure(check['symbol'],check['group'])
            if cone is None or len(cone[0])!=1:continue
            state=next(iter(cone[0]));targets={check['group'],*check['compute_targets']}
            if not targets.issubset(self.readers[state]):continue
            rows.append(dict(id=check['id'],symbol=check['symbol'],kind=check['kind'],
                state=state,producer=check['group'],consumers=check['compute_targets'],
                direct_read_groups=sorted(self.readers[state]),operations=sorted(cone[1]),
                size=len(cone[1]),depth=cone[2],cache_dependencies=sorted(cone[1]&cache_ops)))
        return sorted(rows,key=lambda row:int(row['id']))


def cached_predicates(folder):
    result=set()
    for file in folder.glob('*_sched_*.cpp'):
        text=file.read_text()
        for m in re.finditer(r'// Shared equality family: source=(\d+) predicates=(\d+)',text):
            start=text.index('{',m.end());depth=1;end=start+1
            while depth:
                depth+=(text[end]=='{')-(text[end]=='}');end+=1
            ids=set(re.findall(r'grhsim_changed_(\d+)',text[start:end]))
            if len(ids)!=int(m[2]):raise ValueError('cached predicate coverage mismatch')
            result.update(ids)
    return result


def empty_call_bounds(calls,group_counts):
    """Bounds using marginals; never assume that rare groups fire together."""
    if calls<0 or any(n<0 or n>calls for n in group_counts):raise ValueError('invalid call/group counts')
    return dict(minimum=max(0,calls-sum(group_counts)),maximum=calls-max(group_counts,default=0))


def empty_entry_path(rows):
    """Recognize a reviewed zero-byte-mask fallthrough, refusing other shapes."""
    first_branch=next(i for i,r in enumerate(rows) if r['mnemonic'].startswith('j'))
    branch=rows[first_branch];test=rows[first_branch-1]
    if branch['mnemonic']!='jne' or test['mnemonic']!='testb':raise ValueError('unreviewed entry branch')
    if len(set(test['operands'].split(', ')))!=1:raise ValueError('entry is not a zero test')
    target=int(re.match(r'0x([0-9a-f]+)\b',branch['operands'])[1],16)
    stop=next(i for i in range(first_branch+1,len(rows)) if rows[i]['mnemonic'].startswith('ret'))
    if rows[stop]['address']>=target or any(r['mnemonic'].startswith(('j','call')) for r in rows[first_branch+1:stop]):
        raise ValueError('empty path does not return directly')
    path=rows[:stop+1]
    return dict(branch=branch,instructions=path,count=len(path),
        pushes=sum(r['mnemonic']=='pushq' for r in path),pops=sum(r['mnemonic']=='popq' for r in path),
        stack_allocation=[r['operands'] for r in path if r['mnemonic']=='subq' and '%rsp' in r['operands']])


def excerpt(folder,filename,needle,before=1,after=12):
    lines=(folder/filename).read_text().splitlines()
    i=next(i for i,line in enumerate(lines) if needle in line)
    first=max(0,i-before);last=min(len(lines),i+after+1)
    return dict(file=filename,first=first+1,last=last,source='\n'.join(lines[first:last]))


def audit(out):
    if (out/'report.json').exists():raise FileExistsError(out/'report.json')
    out.mkdir(parents=True,exist_ok=True)
    manifest=check(RUN);functional=read(RUN/'functional.json');reference=functional['workloads']['coremark']['verilator']
    if functional['build']!=identity(RUN/'build.json'):raise ValueError('functional identity mismatch')
    for backend,folder in [('grhsim_covered_view_inline',CURRENT),('verilator',VERILATOR)]:
        if identity(folder/'emu')['sha256']!=manifest['binaries'][backend]['sha256']:raise ValueError('ELF mismatch')
    counts=read(COUNTS/'counts.json')['coremark'];origin=read(COUNTS/'inputs.json')
    if origin['model']!=manifest['binaries']['grhsim_covered_view_inline']:raise ValueError('counter model mismatch')
    if counts['cycles']!=reference['cycles'] or counts['trace']['sha256']!=reference['trace']['sha256']:
        raise ValueError('counter workload mismatch')
    old=ROOT/'build/cv32e40p/code-shapes-v1'
    previous=read(old/'static.json')['models']['verilator']
    for item in [previous['binary'],previous['header'],*previous['sources']]:
        if identity(Path(item['path']))!=item:raise ValueError('Verilator counter origin drift')
    vc=read(old/'counts.json')['verilator']['coremark']
    if vc['cycles']!=reference['cycles'] or vc['trace']['sha256']!=reference['trace']['sha256']:
        raise ValueError('Verilator workload mismatch')
    models={};asm={}
    for label,folder in [('current',CURRENT),('verilator',VERILATOR)]:
        elf,rows=elf_model(label,folder,out);asm[label]=rows
        required={r['model_source']['file'] for r in rows if r['model_source']}
        models[label]=dict(binary=identity(folder/'emu'),elf=elf,source_checksums=verify_embedded_sources(folder,required))
    cpp=grhsim_source('current',CURRENT,counts,asm['current']);save(out/'current-source.json',cpp)
    if identity(RUN/'sources.csv')['sha256']!=identity(SOURCE_MAP_ORIGIN/'sources.csv')['sha256']:
        raise ValueError('source-audit helper mapping differs')
    graph=read(CURRENT/'normalized.json')['graphs'][0];mapping=list(csv.DictReader((RUN/'sources.csv').open()))
    screening=StateClosures(graph,mapping);byid={r['id']:r for r in cpp['checks']}
    cached=cached_predicates(CURRENT)
    cache_ops={screening.values[byid[i]['symbol']]['def'] for i in cached}
    structural=screening.screen(cpp['checks'],cache_ops)
    # Attach existing execution counts only after structural screening has finished.
    for row in structural:
        row['comparisons_per_cycle']=byid[row['id']]['comparisons']
        row['changes_per_cycle']=byid[row['id']]['changes']
    independent=[r for r in structural if not r['cache_dependencies']]
    closures=dict(screened=len(structural),cache_owned_roots=len(cached),
        cache_dependent_roots=sum(bool(r['cache_dependencies']) for r in structural),
        independent_roots=len(independent),independent_checks=sum(r['comparisons_per_cycle'] for r in independent),
        sizes=dict(Counter(str(r['size']) for r in independent)),states=dict(Counter(r['state'] for r in independent)),rows=structural,
        limit='Structural screen only: scheduled local scalar cones, one register symbol, independently existing readers. Full snapshot/alias/event/ownership/guard/writer and code-duplication proofs remain. No list is fed to a generator.')
    file='grhsim_Cv32Bench_sched_2.cpp';text=(CURRENT/file).read_text()
    masks=[int(x) for x in re.findall(r'if \(unlikely\(activeWordFlags & UINT8_C\((\d+)\)\)\)',text)]
    if masks!=[1,2,4,8,16,32,64,128] or text.count('dispatchMask = UINT8_C(255)')!=1:
        raise ValueError('batch2 dispatch shape requires review')
    name='GrhSIM_Cv32Bench::eval_compute_batch_2()'
    entry=empty_entry_path([r for r in asm['current'] if r['function']==name])
    groups=[g['group'] for g in cpp['groups'] if g['batch']==2];counter=counts['counts']
    bounds=[empty_call_bounds(counter['function:eval_compute_batch_2'][phase],
             [counter['group:'+str(g)][phase] for g in groups]) for phase in range(4)]
    entry.update(groups=groups,calls_by_phase=counter['function:eval_compute_batch_2'],empty_calls_by_phase=bounds,
        empty_calls_per_cycle={key:sum(r[key] for r in bounds)/counts['cycles'] for key in ('minimum','maximum')},
        limit='Counts bound empty calls without assuming correlated group activations. The path excludes the caller call instruction. A new caller guard would have its own cost; this is not predicted net savings.')
    examples=[]
    for value in ('7797','26812','6160'):
        r=byid[value];filename=Path(r['file']).name
        e=excerpt(CURRENT,filename,f'[value_id={value}:0]',before=1,after=7)
        e.update(value=value,comparisons=r['comparisons'],changes=r['changes'],
                 machine=source_instruction_shape(asm['current'],{(filename,i) for i in range(e['first'],e['last']+1)}))
        examples.append(e)
    examples.append(excerpt(CURRENT,'grhsim_Cv32Bench_sched_4.cpp','[kRegisterWritePort] reg=core$_11272_'))
    examples.append(excerpt(VERILATOR,'VCv32Bench___024root__1.cpp','void VCv32Bench___024root___eval_body__nba(VCv32Bench___024root* vlSelf) {',before=0,after=8))
    vbody=next(s for s in function_symbols(VERILATOR/'emu') if s['symbol'].startswith('VCv32Bench___024root___eval_body__nba('))
    bodyasm=disassemble(VERILATOR/'emu',vbody);(out/'verilator-nba-caller.s').write_text(bodyasm)
    entry['verilator_main_calls_per_cycle']=sum(vc['counts']['function:VCv32Bench___024root___nba_sequent__TOP__0'])/vc['cycles']
    entry['verilator_nba_caller']=dict(**vbody,instructions=instructions(bodyasm))
    wide=wide_paths(CURRENT,out,'current')
    nonconstant=[x for x in cpp['commit_only_materialized_inputs'] if screening.ops[screening.values[x['symbol']]['def']]['kind']!='kConstant']
    commit=dict(nonconstant_values=len(nonconstant),groups=dict(Counter(str(r['group']) for r in nonconstant)),
        examples=[excerpt(CURRENT,'grhsim_Cv32Bench_sched_4.cpp','[kRegisterWritePort] reg=core$_11244_',after=10),
                  excerpt(VERILATOR,'VCv32Bench___024root__0.cpp','= vlSelfRef.__VdfgRegularize_h6e95ff9d_0_17;',before=4,after=1)],
        limit='Materialized IR values can alias slots. No dynamic per-register commit-comparison counts were collected; these are not machine-store counts.')
    inputs=[identity(p) for p in (RUN/'build.json',RUN/'functional.json',RUN/'summary.json',RUN/'boundary-analysis.json',
        RUN/'sources.csv',SOURCE_MAP_ORIGIN/'sources.csv',COUNTS/'inputs.json',COUNTS/'counts.json',CURRENT/'normalized.json',old/'counts.json',old/'static.json',
        ROOT/'scripts/cv32e40p_current_structure.py',ROOT/'scripts/cv32e40p_current_structure_paths.py',
        ROOT/'scripts/cv32e40p_consumer_structure_analysis.py',ROOT/'scripts/cv32e40p_binary_shape.py',Path(__file__).resolve())]
    report=dict(scope='Offline current C++/ELF/IR and existing counters only. No simulator runs, sampling, model generation or production changes.',
        reference=dict(cycles=reference['cycles'],trace=reference['trace']['sha256']),models=models,cpp=cpp,
        state_closures=closures,empty_entry=entry,examples=examples,wide=wide,commit=commit,inputs=inputs,
        measurements=read(RUN/'summary.json')['grhsim_covered_view_inline'],pmu=read(RUN/'boundary-analysis.json')['pmu'],
        limits='Current ELF has no matching sampled event profile. Exact counts are not time percentages; source-line attribution and static stack references are not dynamic spills. No partitioning of the remaining walltime gap is claimed.')
    save(out/'report.json',report)
    print(json.dumps(dict(boundaries=cpp['boundaries']['all'],compute_only=cpp['boundaries']['compute_only'],
        closures={k:v for k,v in closures.items() if k!='rows'},empty_entry={k:entry[k] for k in ('count','pushes','pops','stack_allocation','empty_calls_per_cycle')},
        commit={k:v for k,v in commit.items() if k!='examples'}),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    audit(parser.parse_args().output.resolve())
