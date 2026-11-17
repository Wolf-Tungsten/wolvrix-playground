#!/usr/bin/env python3
"""Source/ELF evidence for frozen packed-demand candidates, never runs models."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

from grhsim_single_baseline import identity,save
from xiangshan_cv32_compare import verify_identity
from xiangshan_cv32_structure import machine
from xiangshan_packed_storage_analysis import group_text,disassemble
from xiangshan_packed_demand_compare import PREVIOUS,check,VARIANTS


def read(path):return json.loads(Path(path).read_text())


def selected_mapping(before,after):
    """Independently reconstruct every original lane and emitted member table."""
    records=[]
    pattern=re.compile(r'// Selected packed state: value=(\d+) slice=(\d+) lanes=(\d+) table_lanes=(\d+)')
    for path in sorted(after.glob('*_sched_*.cpp')):
        code=path.read_text();old=(before/path.name).read_text()
        for match in pattern.finditer(code):
            value,result,count,table_count=map(int,match.groups())
            declaration=re.search(r'std::array<[^\n;]+> (packed_array_lanes_local_'+str(value)+r'_\d+)\{\};',old)
            assert declaration,(path.name,value)
            name=declaration[1]
            fills=re.findall(re.escape(name)+r'\[(\d+)\] = ([^\n]+);',old)
            fields={}
            for lane,expr in fills:
                found=re.findall(r'state_logic_storage_\.(\w+)',expr)
                assert len(found)==1,(path.name,value,lane,expr)
                lane=int(lane)
                if lane in fields:assert fields[lane]==found[0]
                fields[lane]=found[0]
            assert sorted(fields)==list(range(count))
            table=re.search(r'packed_state_members_'+str(value)+r'\[\] = \{\n(.*?)        \};',code[match.end():],re.S)
            members=re.findall(r'&state_logic_storage_t::(\w+)',table[1]);assert len(members)==table_count
            assert [members[i if i<table_count else 0] for i in range(count)]==[fields[i] for i in range(count)]
            new_index=re.search(r'packed_state_index_'+str(value)+r' = static_cast<std::size_t>\(([^\n]+)\);',code[match.end():])[1]
            old_index=re.search(r'packed_array_idx_'+str(result)+r' = static_cast<std::size_t>\(([^\n]+)\);',old)[1]
            assert new_index==old_index,(path.name,value,new_index,old_index)
            records.append(dict(file=path.name,value=value,result=result,lanes=count,table_lanes=table_count,
                                index=new_index,all_lane_members_equal=True))
    assert records
    return dict(sites=len(records),lane_mapping_checks=sum(r['lanes'] for r in records),rows=records,
                limit='Exact source member/index mapping; the emitter and functional regressions additionally prove snapshot and effect legality.')


def region(folder,batch,group,assembly,destination,active_offset):
    path,line,code=group_text(folder/'model',group)
    prefix='\n'.join(path.read_text().splitlines()[:line])
    word=int(re.findall(r'activeWordFlags = static_cast<std::uint8_t>\(supernode_active_curr_\[(\d+)u\]',prefix)[-1])
    bit=int(re.search(r'activeWordFlags & UINT8_C\((\d+)\)',code)[1])
    address=active_offset+word
    lines=assembly.read_text().splitlines()
    start=next(i for i,s in enumerate(lines) if re.search(r'movb\s+\$0x0,0x'+f'{address:x}'+r'\(%r(?!sp)\w+\)',s))
    test=next(i for i in range(start,start+40) if re.search(r'test\s+\$0x'+f'{bit:x}'+r',',lines[i]))
    assert re.search(r'test\s+\$0x'+f'{bit*2:x}'+r',',lines[test+2])
    begin=re.search(r'jne\s+([0-9a-f]+)',lines[test+1])[1]
    end=re.search(r'jne\s+([0-9a-f]+)',lines[test+3])[1]
    a=next(i for i,s in enumerate(lines) if s.strip().startswith(begin+':'))
    b=next(i for i,s in enumerate(lines) if s.strip().startswith(end+':'))
    assert a<b
    body=lines[a:b];destination.write_text('\n'.join(body)+'\n')
    counts=Counter(re.search(r':\s+(\w+)',s)[1] for s in body if re.search(r'^\s*[0-9a-f]+:',s))
    return dict(source=identity(path),line=line,group=group,activity_word=word,bit=bit,
        begin=begin,end_exclusive=end,window=identity(destination),static_instructions=sum(counts.values()),
        mnemonics=dict(counts),memset_calls=sum('call' in s and '<memset@plt>' in s for s in body),
        indexed_stack_loads=[s for s in body if re.search(r'\(%rsp,%r\w+,8\)',s)],
        lambda_calls=[s for s in body if re.search(r'\bcall\s+\w+ <_ZZN13GrhSIM_',s)],
        source_private_256_arrays=len(re.findall(r'std::array<std::uint64_t, 256> packed_array_lanes_local_\w+(?:\{\})?;',code)),
        selected_sites=code.count('// Selected packed state:'),no_init_sites=code.count('// Packed array full overwrite:'),
        source_selected_tables=[tuple(map(int,m)) for m in re.findall(r'Selected packed state: value=(\d+) slice=(\d+) lanes=(\d+) table_lanes=(\d+)',code)],
        limit='Static body bounded by neighbouring activity-bit targets, includes its exit test; not dynamic work.')


def audit(out):
    check(out);dest=out/'machine-evidence';dest.mkdir(exist_ok=True)
    offset=read(PREVIOUS/'scope-evidence/report.json')['models']['full']['rob']['call_evidence']['offset_probe']['offsets']['supernode_active_curr_']
    result=dict(mode='offline_no_simulator',models={},build=identity(out/'build.json'),active_offset=offset)
    for name in VARIANTS:
        model=out/name;elf=read(model/'binary.json');verify_identity(elf)
        target=dest/(name+'-structure.json')
        if target.exists():
            m=read(target);assert m['binary']==elf
        else:
            m=machine(Path(elf['path']));save(target,m)
        row=dict(binary=elf,totals=m['totals'],audit=identity(target),
            batch9_frame=m['functions']['GrhSIM_SimTop::eval_compute_batch_9()']['entry_stack_subtractions'])
        if name in ('select','combined'):
            row['selected_mapping']=selected_mapping(out/'full/model',model/'model')
        if name!='no_shared':
            # The source gate proves headers are either the frozen full or
            # layout header; their activity arrays have the same offset.
            for batch,group,label in ((5,93956,'ftq'),(9,94733,'rob')):
                assembly=dest/(name+f'-batch{batch}.s')
                d=disassemble(model,batch,assembly)
                row[label]=region(model,batch,group,assembly,dest/(name+'-'+label+'.s'),offset)
                row[label]['batch_disassembly']=d
            if name in ('select','combined'):
                assert row['rob']['selected_sites']==8 and row['rob']['source_private_256_arrays']==0
                assert not row['rob']['indexed_stack_loads'] and not row['rob']['lambda_calls']
            if name=='combined':assert row['ftq']['no_init_sites']==64
        result['models'][name]=row
        print(name,'ELF audited',flush=True)
    result['script']=identity(Path(__file__).resolve());result['status']='pass'
    save(dest/'report.json',result)
    print(json.dumps({n:{k:r.get(k) for k in ('batch9_frame',)} for n,r in result['models'].items()}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    audit(p.parse_args().source.resolve())
