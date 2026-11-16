#!/usr/bin/env python3
"""Offline direct-CFG and wide-view evidence, using an existing structure audit."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess

from cv32e40p_compare import identity, save
from cv32e40p_current_structure import SOURCES, COUNTERS, LLVM


def dwarf_file_checksums(dump):
    checksums = {}
    pattern = r'file_names\[\s*\d+\]:\s+name: "([^"]+)"\s+dir_index: \d+\s+md5_checksum: ([0-9a-f]{32})'
    for filename, digest in re.findall(pattern, dump):
        name = Path(filename).name
        checksums.setdefault(name, set()).add(digest)
    return checksums


def verify_embedded_sources(folder, required):
    dump = subprocess.check_output([LLVM/'llvm-dwarfdump', '--debug-line', folder/'emu'], text=True)
    embedded = dwarf_file_checksums(dump)
    result = []
    for filename in sorted(required):
        path = folder/filename
        digest = hashlib.md5(path.read_bytes()).hexdigest()
        if embedded.get(filename) != {digest}:
            raise ValueError('ELF embedded source checksum mismatch: ' + str(path))
        result.append(dict(**identity(path), dwarf_md5=digest))
    return result

def direct_cfg(rows):
    """Conservative CFG: reject indirect jumps instead of inventing targets."""
    ordered=sorted(rows,key=lambda r:r['address']);byaddr={r['address']:r for r in ordered}
    successors={}
    for i,r in enumerate(ordered):
        nxt=[ordered[i+1]['address']] if i+1<len(ordered) else []
        op=r['mnemonic'];targets=[]
        if op.startswith('j'):
            m=re.match(r'0x([0-9a-f]+)\b',r['operands'])
            if not m:raise ValueError('indirect jump prevents complete CFG proof')
            target=int(m[1],16);targets=[target] if target in byaddr else []
            if op not in ('jmp','jmpq'):targets+=nxt
        elif not op.startswith('ret'):targets=nxt
        successors[r['address']]=targets
    return ordered[0]['address'],successors


def reachable(entry,successors,skip_edge=None,skip_node=None):
    todo=[entry];seen=set()
    while todo:
        node=todo.pop()
        if node in seen or node==skip_node:continue
        seen.add(node);todo.extend(t for t in successors[node] if (node,t)!=skip_edge)
    return seen


def edge_dependence(rows,branch):
    """Instructions reachable only via each outgoing edge of a direct branch."""
    entry,successors=direct_cfg(rows)
    if len(successors[branch])!=2:raise ValueError('not a two-way local branch')
    baseline=reachable(entry,successors)
    return {target:baseline-reachable(entry,successors,skip_edge=(branch,target)) for target in successors[branch]}


def node_dominates(rows,node,target):
    entry,successors=direct_cfg(rows)
    return target in reachable(entry,successors) and target not in reachable(entry,successors,skip_node=node)


def state_view_signature(graph,symbol):
    values={v['sym']:v for v in graph['vals']};ops={o['sym']:o for o in graph['ops']}
    def signature(value):
        v=values[value];op=ops[v['def']];kind=op['kind']
        if kind=='kConstant':return [kind,v['w'],v['sgn'],op['attrs']['constValue']['v']]
        if kind=='kRegisterReadPort' and not op['in']:
            return [kind,v['w'],v['sgn'],op['attrs']['regSymbol']['v']]
        if kind=='kConcat':return [kind,v['w'],v['sgn'],*[signature(a) for a in op['in']]]
        raise ValueError('unsupported state view normalization: '+kind)
    return signature(symbol)


def analyze(folder):
    report=json.loads((folder/'report.json').read_text());result={'models':{}}
    for record in report['inputs']:
        if identity(Path(record['path']))!=record:raise ValueError('analysis input drift: '+record['path'])
    result['embedded_source_checksums']={}
    for label,source in SOURCES.items():
        rows=json.load(gzip.open(folder/f'{label}-instructions.json.gz','rt'))
        required={r['model_source']['file'] for r in rows if r['model_source']}
        result['embedded_source_checksums'][label]=verify_embedded_sources(source,required)
    for label in ('retained','joint'):
        source=SOURCES[label];cpp=report['models'][label]['cpp']
        rows=json.load(gzip.open(folder/f'{label}-instructions.json.gz','rt'))
        name='GrhSIM_Cv32Bench::eval_compute_batch_2()';function=[r for r in rows if r['function']==name]
        filename='grhsim_Cv32Bench_sched_2.cpp';lines=(source/filename).read_text().splitlines()
        root=4333;marker=next(i for i,s in enumerate(lines) if f'Conditional mux cone: root={root} ' in s);guard_line=marker+2
        branches=[r for r in function if r['model_source'] and r['model_source']['file']==filename and
                  r['model_source']['line']==guard_line and r['mnemonic'].startswith('j')]
        if len(branches)!=1 or branches[0]['mnemonic']!='je':raise ValueError('review required: CSR guard machine shape changed')
        branch=branches[0];index=function.index(branch)
        before=function[index-1]
        if before['mnemonic']!='testb' or not before['operands'].startswith('$0x1,'):raise ValueError('review required: CSR Boolean guard test changed')
        dep=edge_dependence(function,branch['address'])
        target=int(re.match(r'0x([0-9a-f]+)',branch['operands'])[1],16)
        fallthrough=function[index+1]['address'];true_only=dep[fallthrough];false_only=dep[target]
        counts=json.loads((COUNTERS[label]/'counts.json').read_text())['coremark']
        true_runs=sum(counts['counts']['mux_true:'+str(root)])
        false_runs=sum(counts['counts']['mux_false:'+str(root)])
        family=next(f for f in cpp['local_eq_families'] if f['source']=='_val_6162')
        locs={(p['file'],p['line']) for p in family['predicates']}
        family_rows=[r for r in function if r['model_source'] and
                     (r['model_source']['file'],r['model_source']['line']) in locs]
        cold=[r for r in function if r['address'] in true_only]
        graph=json.loads((source/'normalized.json').read_text())['graphs'][0]
        sigs=[state_view_signature(graph,sym) for sym in ('core$_13859_','core$_13860_')]
        if sigs[0]!=sigs[1]:raise ValueError('counter views no longer equivalent')
        view_groups={v['group'] for v in cpp['wide_locals'] if v['symbol'] in ('core$_13859_','core$_13860_')}
        if view_groups!={28}:raise ValueError('counter views no longer in the same compute group')
        ops={o['sym']:o for o in graph['ops']};values={v['sym']:v for v in graph['vals']}
        staging=cpp['commit_only_materialized_inputs']
        dynamic_staging=[r for r in staging if ops[values[r['symbol']]['def']]['kind']!='kConstant']
        true_end=next(i for i in range(marker+2,len(lines)) if lines[i].strip()=='} else {')
        arrays=[]
        for value in ('41659','41658'):
            decl=next(i for i,s in enumerate(lines) if f'std::array<std::uint64_t, 32> grhsim_v{value}_0' in s)
            construction=[r for r in function if r['model_source'] and r['model_source']['file']==filename and
                          r['model_source']['line']==decl+1]
            narrow={'41659':'42432','41658':'42428'}[value]
            narrow_uses=[i+1 for i,line in enumerate(lines) if 'grhsim_v'+narrow+'_0' in line]
            if len(narrow_uses)!=2 or not guard_line<narrow_uses[1]<=true_end:
                raise ValueError('wide-view result acquired another consumer')
            arrays.append(dict(value=value,line=decl+1,narrow_value=narrow,narrow_uses=narrow_uses,
                narrow_result_only_used_in_true_arm=True,construction_instructions=construction,
                vector_zero_stores=[r for r in construction if r['mnemonic']=='vmovdqu64' and '%rsp)' in r['operands']],
                stores_before_guard=[r['address'] for r in construction if r['address']<branch['address']],
                zero_stores_dominate_guard=[node_dominates(function,r['address'],branch['address']) for r in construction if r['mnemonic']=='vmovdqu64' and '%rsp)' in r['operands']]))
        result['models'][label]=dict(csr_guard=dict(root=root,source_line=guard_line,test=before,branch=branch,
                true_only_instructions=len(cold),true_only_stack_operands=sum(r['stack'] for r in cold),
                false_only_instructions=len(false_only),observed_true_runs=true_runs,observed_false_runs=false_runs,
                family_source_line_instructions=len(family_rows),
                family_instructions_dominated_by_true=sum(r['address'] in true_only for r in family_rows),
                limits='Direct CFG edge reachability plus reviewed testb/je mapping to the Boolean C++ guard. Counters are from the same frozen model; not a cycle-cost estimate.'),
            equivalent_counter_views=dict(symbols=['core$_13859_','core$_13860_'],signature=sigs[0],same_compute_group=28,
                note='Same register symbols/widths/sign and constants in one compute snapshot; SSA result IDs differ. This is a value-equivalence proof, not permission to merge across writes.'),
            array_construction=arrays,
            commit_staging=dict(materialized_values=len(staging),nonconstant_values=len(dynamic_staging),
                nonconstant_groups=dict(Counter(str(r['group']) for r in dynamic_staging)),
                kinds=dict(Counter(ops[values[r['symbol']]['def']]['kind'] for r in staging)),
                note='IR values with materialization comments and only direct commit consumers. Counts are not unique physical slots or dynamic machine stores.'))
        if label=='retained':
            excerpts=[]
            for name,first,last in [('grhsim_Cv32Bench_sched_1.cpp',414,428),
                                    ('grhsim_Cv32Bench_sched_4.cpp',1133,1143)]:
                cpp_lines=(source/name).read_text().splitlines()
                excerpts.append(dict(file=name,first=first,last=last,source='\n'.join(cpp_lines[first-1:last]),
                    instructions=[r for r in rows if r['model_source'] and r['model_source']['file']==name and
                                  first<=r['model_source']['line']<=last]))
            result['boundary_examples']=excerpts

    vcpp=(SOURCES['verilator']/'VCv32Bench___024root__0.cpp').read_text()
    result['verilator_counter_view_declarations']=re.findall(r'VlWide<(\d+)>/\*([^*]+)\*/ (Cv32Bench__DOT__core__DOT___1385[9]_|Cv32Bench__DOT__core__DOT___13860_);',vcpp)
    vrows=json.load(gzip.open(folder/'verilator-instructions.json.gz','rt'))
    vlines=vcpp.splitlines()
    vlocations={i+1 for i,line in enumerate(vlines) if 'Cv32Bench__DOT__core__DOT___13859_' in line}
    vzero=[r for r in vrows if r['model_source'] and
           r['model_source']['file']=='VCv32Bench___024root__0.cpp' and r['model_source']['line'] in vlocations and
           r['mnemonic']=='vmovdqu64' and '%rsp)' in r['operands']]
    result['verilator_counter_view_zero_stores']=vzero
    result['counter_view_limit']='Verilator also emits eight attributed vector-zero stores (initialization plus refill) for its single view. Two GrhSIM arrays are not proof of more dynamic zero-store instructions than Verilator; the evidence supports duplicate storage and missing demand placement, not a net store/time saving estimate.'
    result['inputs']=[identity(folder/'report.json'),identity(Path(__file__).resolve()),
        identity(LLVM/'llvm-dwarfdump'),
        *(identity(folder/f'{label}-instructions.json.gz') for label in ('retained','joint','verilator'))]
    save(folder/'path-evidence.json',result)
    for label,r in result['models'].items():
        g=r['csr_guard']
        print(label,'true arm runs',g['observed_true_runs'],'edge-dependent instructions',g['true_only_instructions'],
              'local Eq instructions on cold arm',g['family_instructions_dominated_by_true'],'/',g['family_source_line_instructions'])
        print('wide array zero stores',[(a['value'],len(a['vector_zero_stores'])) for a in r['array_construction']])

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True)
    args=parser.parse_args();analyze(args.source.resolve())
