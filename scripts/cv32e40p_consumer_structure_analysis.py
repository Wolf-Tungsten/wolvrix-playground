#!/usr/bin/env python3
"""Explain two frozen emitter repairs; never feed measurements into generation."""
import argparse
import gzip
import json
from pathlib import Path
import re
import subprocess

from cv32e40p_compare import ROOT, identity, save, signature, summarize_named
from cv32e40p_event_regions_compare import check
from cv32e40p_consumer_structure_compare import BASE, BASELINE, CANDIDATES
from cv32e40p_conditional_mux_analysis import perf_counts
from cv32e40p_repair_analysis import counter_rates
from cv32e40p_binary_shape import function_symbols, instructions
from cv32e40p_current_structure import LLVM, model_frame, grhsim_source
from cv32e40p_current_structure_paths import direct_cfg, edge_dependence, node_dominates, verify_embedded_sources


def read(path):return json.loads(path.read_text())


def counter_invariants(a,b):
    if a['cycles']!=b['cycles'] or a['trace']['sha256']!=b['trace']['sha256']:
        raise ValueError('counter workload mismatch')
    counter_rates(a);counter_rates(b)
    # The retained counter archive predates deferred-OR probes. Preserve those
    # new measurements, but do not pretend that absent old probes were zero.
    keys=a['counts'].keys()
    extra=b['counts'].keys()-keys
    if any(not k.startswith('notify_reduction_deferred:') for k in extra):
        raise ValueError('unexpected counter schema extension')
    differences={k:dict(before=a['counts'].get(k),after=b['counts'].get(k)) for k in sorted(keys)
                 if a['counts'].get(k)!=b['counts'].get(k)}
    if differences:raise ValueError('unchanged interface/selector counts differ: '+str(differences)[:1200])
    return dict(compared=len(keys),all_equal=True,new_probe_counts={k:b['counts'][k] for k in sorted(extra)},
        csr_true_runs=sum(b['counts']['mux_true:4333']),csr_false_runs=sum(b['counts']['mux_false:4333']),
        scalar_checks_per_cycle=sum(b['counts']['scalar_comparisons'])/b['cycles'])


def wide_paths(folder,out,label):
    symbol=next(s for s in function_symbols(folder/'emu') if s['symbol']=='GrhSIM_Cv32Bench::eval_compute_batch_2()')
    asm=subprocess.check_output([LLVM/'llvm-objdump','-d','--demangle','--no-show-raw-insn',
        f'--start-address=0x{symbol["address"]:x}',f'--stop-address=0x{symbol["address"]+symbol["bytes"]:x}',folder/'emu'],text=True)
    (out/f'{label}-batch2.s').write_text(asm)
    rows=instructions(asm)
    output=subprocess.check_output([LLVM/'llvm-symbolizer','--obj='+str(folder/'emu'),'--output-style=JSON','--inlines'],
        input=''.join(f'0x{r["address"]:x}\n' for r in rows),text=True)
    frames=[json.loads(line) for line in output.splitlines() if line.strip()]
    if len(rows)!=len(frames):raise ValueError('symbolizer count mismatch')
    for row,entry in zip(rows,frames):
        if row['address']!=int(entry['Address'],16):raise ValueError('symbolizer address mismatch')
        row['source']=model_frame(entry['Symbol'],folder)
    file='grhsim_Cv32Bench_sched_2.cpp';lines=(folder/file).read_text().splitlines()
    marker=next(i for i,line in enumerate(lines) if 'Conditional mux cone: root=4333 ' in line)
    branches=[r for r in rows if r['source'] and r['source']['file']==file and
              r['source']['line']==marker+2 and r['mnemonic'] in ('je','jne')]
    result=dict(function=symbol,source_checksums=verify_embedded_sources(folder,{file}),
        stack_subtractions=[r['operands'] for r in rows if r['mnemonic']=='subq' and '%rsp' in r['operands']],
        guard_candidates=branches)
    def arrays(guard,true_only=None,true_entry=None):
        found=[]
        for value in ('41658','41659'):
            line=next(i+1 for i,s in enumerate(lines) if f'std::array<std::uint64_t, 32> grhsim_v{value}_0' in s)
            stores=[r for r in rows if r['source'] and r['source']['file']==file and r['source']['line']==line
                    and r['mnemonic']=='vmovdqu64' and '%rsp)' in r['operands']]
            found.append(dict(value=value,line=line,vector_stores=stores,
                only_via_true=[node_dominates(rows,true_entry,r['address']) if true_entry is not None else
                               r['address'] in true_only for r in stores],
                dominates_guard=[node_dominates(rows,r['address'],guard) for r in stores]))
        return found
    if len(branches)>1:
        # Clang may turn a Boolean OR guard into a chain of jumps to one arm.
        # Prove the entire incoming-edge set, not one arbitrarily chosen jump.
        targets={int(re.match(r'0x([0-9a-f]+)',b['operands'])[1],16) for b in branches}
        result['cfg_status']='Multiple guard branches require common-arm proof.'
        if len(targets)==1:
            target=targets.pop()
            try:
                _,successors=direct_cfg(rows)
                predecessors={a for a,following in successors.items() if target in following}
                mapped=next(r for r in rows if r['address']>=target and r['source'])
                end=next(i+1 for i in range(marker+2,len(lines)) if lines[i]=='            } else {')
                declarations=[next(i+1 for i,s in enumerate(lines) if f'std::array<std::uint64_t, 32> grhsim_v{v}_0' in s)
                              for v in ('41658','41659')]
                # A preceding scalar can be sunk into this block with its old
                # DWARF line. Validate the actual array definitions and CFG,
                # rather than treating the first mapped instruction as a boundary.
                if (predecessors=={b['address'] for b in branches} and
                    all(marker+2<line<end for line in declarations)):
                    result['cfg_status']='All incoming edges to the reviewed true arm are the Boolean guard chain; array stores dominated by that entry.'
                    result['true_entry']=target;result['true_entry_first_mapped']=mapped
                    result['arrays']=arrays(branches[0]['address'],true_entry=target)
            except (ValueError,StopIteration) as error:result['cfg_status']='Common-arm proof unavailable: '+str(error)
    elif len(branches)!=1:
        result['cfg_status']='No unique Boolean guard branch; no machine-path claim.'
    else:
        branch=branches[0];index=rows.index(branch);test=rows[index-1]
        result['test']=test
        if test['mnemonic'] not in ('testb','testl','testq'):
            result['cfg_status']='Guard test requires manual review; no machine-path claim.'
        else:
            target=int(re.match(r'0x([0-9a-f]+)',branch['operands'])[1],16)
            true=rows[index+1]['address'] if branch['mnemonic']=='je' else target
            try:
                true_only=edge_dependence(rows,branch['address'])[true]
                result['cfg_status']='Direct CFG edge dependence; reviewed Boolean zero-test guard.'
                result['arrays']=arrays(branch['address'],true_only=true_only)
            except ValueError as error:result['cfg_status']='CFG proof unavailable: '+str(error)
    with gzip.open(out/f'{label}-batch2-instructions.json.gz','wt') as stream:json.dump(rows,stream)
    return result


def analyze(out,counts):
    manifest=check(out);functional=read(out/'functional.json');diagnostic=read(out/'diagnostics.json')
    if functional['build']!=identity(out/'build.json') or diagnostic['build']!=identity(out/'build.json'):
        raise ValueError('build identity mismatch')
    ref=functional['workloads']['coremark']['verilator']
    for row in diagnostic['runs'].values():
        if signature(row)!=signature(ref):raise ValueError('PMU signature mismatch')
    pmu={b:perf_counts(out/(b+'-stat.csv'),ref['cycles']) for b in manifest['backends']}
    evidence=out/'machine-evidence';evidence.mkdir(exist_ok=True)
    paths={BASELINE:wide_paths(BASE/BASELINE,evidence,BASELINE),
           'grhsim_conditional_wide':wide_paths(out/'grhsim_conditional_wide',evidence,'grhsim_conditional_wide')}
    old_counts=ROOT/'build/cv32e40p/mux-input-cache-counts-v1'
    old_inputs=read(old_counts/'inputs.json')
    if old_inputs['model']['sha256']!=manifest['binaries'][BASELINE]['sha256']:raise ValueError('old counter ELF mismatch')
    old=read(old_counts/'counts.json')['coremark'];invariants={};inputs=[]
    local_families={}
    for backend,folder in [(BASELINE,BASE/BASELINE),*((b,out/b) for b in CANDIDATES)]:
        parsed=grhsim_source(backend,folder,old,[])
        local_families[backend]=[dict(source=f['source'],group=f['group'],predicates=f['standalone_local_eq'])
            for f in parsed['local_eq_families'] if f['source'] in ('_val_6162','_val_134')]
    for backend,folder in counts.items():
        origin=read(folder/'inputs.json');data=read(folder/'counts.json')['coremark']
        if origin['model']['sha256']!=manifest['binaries'][backend]['sha256']:raise ValueError('counter ELF mismatch')
        invariants[backend]=counter_invariants(old,data)
        inputs.extend(identity(folder/p) for p in ('inputs.json','counts.json'))
    machine=diagnostic['models']
    result=dict(pmu=pmu,machine=machine,wide_paths=paths,counter_invariants=invariants,local_eq_families=local_families,
        summaries=read(out/'summary.json'),baseline_relative_to_verilator=summarize_named(read(out/'pairs.json'),BASELINE,'verilator'),
        instruction_deltas={b:100*(pmu[b]['per_guest_cycle']['instructions:u']/pmu[BASELINE]['per_guest_cycle']['instructions:u']-1)
                            for b in CANDIDATES},
        build_wall_s={p.name:read(p)['wall_s'] for p in sorted((out/'logs').glob('*.result.json'))},
        inputs=[identity(out/p) for p in ('build.json','structure.json','functional.json','summary.json','pairs.json','diagnostics.json')]+
            [identity(old_counts/p) for p in ('inputs.json','counts.json')]+inputs+[identity(Path(__file__).resolve())],
        limits='One separate PMU execution per backend; exact diagnostic counters are not time percentages. '
               'Static stack accesses are not dynamic spills. No profile input, candidate selection, or post-measurement tuning.')
    save(out/'consumer-analysis.json',result)
    print(json.dumps(dict(instruction_deltas=result['instruction_deltas'],counter_invariants=invariants,
        wide_paths={k:{a:b for a,b in v.items() if a in ('stack_subtractions','cfg_status','arrays')} for k,v in paths.items()}),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--counts',action='append',default=[])
    args=parser.parse_args();analyze(args.source.resolve(),{b:Path(p).resolve() for b,p in (v.split('=',1) for v in args.counts)})
