#!/usr/bin/env python3
"""Tie frozen generator diffs, static replays, emitted C++ and ELF evidence.

This only reads frozen inputs and writes analysis artifacts. The accompanying
C++ probes replay simplify/schedule, without emitting or executing simulators.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess

from cv32e40p_compare import ROOT
from grhsim_single_baseline import identity,save
from xiangshan_cv32_compare import HISTORICAL,verify_identity
from xiangshan_packed_storage_compare import check_model
from xiangshan_shared_layout_audit import cv32_contractions

TRANSFER=ROOT/'build/xs/cv32-transfer-20261116-v3'
ABLATION=ROOT/'build/xs/cv32-ablation-20261116-v2'
LATEST=ROOT/'build/xs/packed-demand-20261116-v1'


def read(path):return json.loads(Path(path).read_text())


def instruction_rows(path):
    return [(int(m[1],16),m[2].strip()) for m in re.finditer(r'(?m)^\s*([0-9a-f]+):\s+(.+)$',Path(path).read_text())]


def region(rows,start,end):
    a=next(i for i,x in enumerate(rows) if x[0]==start)
    b=next(i for i,x in enumerate(rows) if x[0]==end)
    assert a<b
    return rows[a:b]


def source_diff(out):
    repo=ROOT/'wolvrix';revisions=('74d80cf','8523dc1')
    diff=subprocess.check_output(['git','-C',repo,'diff',*revisions,'--','lib','include'])
    patch=out/'production-series.patch';patch.write_bytes(diff)
    stats=subprocess.check_output(['git','-C',repo,'diff','--numstat',*revisions,'--','lib','include'],text=True)
    files=[dict(path=p,added=int(a),deleted=int(b)) for a,b,p in (line.split('\t') for line in stats.splitlines())]
    old,new=[subprocess.check_output(['git','-C',repo,'show',r+':lib/emit/grhsim_cpp.cpp'],text=True) for r in revisions]
    option=re.compile(r'const bool (\w+)\s*=\s*parseBooleanEmitOption\(options,\s*"(\w+)",\s*"(\w+)"(?:,\s*(true|false))?\)')
    opts=[{m[2]:dict(variable=m[1],environment=m[3],default=m[4],line=s.count('\n',0,m.start())+1)
           for m in option.finditer(s)} for s in (old,new)]
    added={k:v for k,v in opts[1].items() if k not in opts[0]}
    assert {k for k,v in added.items() if v['default']=='true'}=={'packed_scalar_slices','indexed_concat_slice','shared_equality_decode'}
    return dict(revisions={r:subprocess.check_output(['git','-C',repo,'rev-parse',r],text=True).strip() for r in revisions},
                files=files,patch=identity(patch),new_emitter_options=added,
                unchanged_production_files=['lib/transform/simplify.cpp','lib/transform/reg_to_mem.cpp'],
                explicit_pipeline=read(TRANSFER/'policy.json'),
                note='predicate-set and slice-demand were added but are not invoked by the frozen replay driver. '
                     'Scalar concat reduction already existed and was enabled in 74d80cf.')


def simplify(out):
    a,b=[read(out/(n+'-simplified.json')) for n in ('before','after')]
    assert (out/'before-input.json').read_bytes()==(out/'after-input.json').read_bytes()
    x,y=[{v['value']:v for v in q['packed_concats']} for q in (a,b)]
    assert len(x)==len(y)==3955 and x.keys()==y.keys()
    changed=[k for k in x if (x[k]['operands'],x[k]['width_histogram'])!=(y[k]['operands'],y[k]['width_histogram'])]
    wide=[k for k in changed if x[k]['width']>64]
    assert len(changed)==39 and len(wide)==7
    assert all(x[k]['element_count']==x[k]['operands'] and y[k]['element_count']!=y[k]['operands'] for k in wide)
    return dict(before_ops=sum(a['op_counts'].values()),after_ops=sum(b['op_counts'].values()),
                op_kind_deltas={k:b['op_counts'].get(k,0)-a['op_counts'].get(k,0) for k in a['op_counts'].keys()|b['op_counts'].keys()
                                if a['op_counts'].get(k,0)!=b['op_counts'].get(k,0)},
                changed_packed_concats=len(changed),changed_wide_packed_concats=len(wide),
                affected_wide_slice_users=sum(x[k]['users'].get('kSliceArray',0) for k in wide),
                wide_cases=[dict(before=x[k],after=y[k]) for k in wide],
                inputs=[identity(out/(n+'-'+s+'.json')) for n in ('before','after') for s in ('input','simplified')],
                note='IDs are from the simplify checkpoint, not the final emitted graph. Symbol names identify the seven cases.')


def rules(folder):
    total=Counter();indexed=[];families=[]
    tokens={'packed_scalar':'// Packed scalar slices:','indexed_concat':'// Indexed concat:',
            'equality_decode':'// Shared equality decode:','equality_family':'// Shared equality family:',
            'cone':'// Conditional mux cone:','cache':'// Conditional mux input cache:',
            'view':'// Covered state view:','composed':'// Composed state expression:'}
    for p in sorted(folder.glob('*_sched_*.cpp')):
        text=p.read_text()
        for k,t in tokens.items():total[k]+=text.count(t)
        for m in re.finditer('// Indexed concat:',text):
            end=text.index('\n        };',m.start())+11;code=text[m.start():end]
            indexed.append(dict(file=p.name,line=text.count('\n',0,m.start())+1,
                cases=len(re.findall(r'case \d+u:',code)),captured_named_snapshots=len(set(re.findall(r'grhsim_v\d+_\d+',code)))))
        families.extend(int(n) for n in re.findall(r'Shared equality family: source=\d+ predicates=(\d+)',text))
    return dict(counts=dict(total),indexed_sites=indexed,family_predicates=sum(families))


def scheduling(out):
    rows=read(out/'shared-connectivity.json')['groups']
    assert rows==read(out/'schedule-connectivity.json')['groups'],'independent static schedule replays differ'
    lineage=read(out/'schedule-lineage.json');assert lineage['exact_edge_multiset_equal']
    assert lineage['matched_cpp_operation_comments']==2486315
    assert len(rows)==len(lineage['groups'])==97550
    # buildSharedEventRegions appends classes after all retained compute
    # fragments and before the unchanged commits. Cross-check the class sum
    # against its frozen scheduler log instead of inferring from group size.
    log=(out/'shared-audit.log').read_text()
    line=next(s for s in log.splitlines() if 'shared event-regions:' in s)
    stats={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)}
    start,end=97204-stats['regions'],97204;classes=rows[start:end]
    assert stats['regions']==6542 and sum(g['ops'] for g in classes)==stats['ops']==1078464
    assert all(lineage['groups'][g['group']]['original_groups']>=2 for g in classes)
    joined=[]
    for g in classes:
        l=lineage['groups'][g['group']];assert l['internal_edges']==g['internal_edges']
        joined.append(dict(**g,**{k:v for k,v in l.items() if k not in g}))
    zero=[g for g in joined if g['removed_boundary_edges']==0]
    report=dict(shared_classes=len(classes),disconnected_classes=sum(g['components']>1 for g in joined),
        no_work_classes=sum(g['work_vertices']==0 for g in joined),
        independent_operations_only_classes=sum(g['work_vertices']>1 and not g['internal_edges'] for g in joined),
        zero_work_boundary_elimination_classes=len(zero),zero_elimination_with_created_boundary=sum(
            bool(g['created_out_edges']+g['created_in_edges']) for g in zero),
        zero_elimination_created_out_edges=sum(g['created_out_edges'] for g in zero),
        zero_elimination_created_in_edges=sum(g['created_in_edges'] for g in zero),
        total_components=sum(g['components'] for g in joined),
        full_lineage_totals={k:v for k,v in lineage.items() if k not in ('groups',)},
        ftq=next(g for g in joined if g['group']==93956),rob=next(g for g in joined if g['group']==94733),
        classes=joined,range=[start,end],scheduler_summary=stats,
        limit='Exclude constant/register/latch-read producers and consumers. Operand occurrences, not unique values or activation edges. '
              'Zero removal here does not rule out state-read coalescing, cache gains or broader semantic opportunities; it is not a complete profitability gate.')
    assert report['disconnected_classes']==4647 and len(zero)==3090
    assert report['zero_elimination_with_created_boundary']==2087
    report['inputs']=[identity(out/n) for n in ('shared-connectivity.json','unshared-connectivity.json',
        'schedule-lineage.json','shared-members.tsv','unshared-members.tsv','shared-work-edges.tsv','unshared-work-edges.tsv')]
    save(out/'shared-class-benefits.json',report)
    return {k:v for k,v in report.items() if k not in ('classes','inputs')}


def bitmap_elf(out):
    offsets=read(out/'bitmapcache-evidence.json')
    for n,v in offsets.items():
        verify_identity(v['assembly']['file']);verify_identity(v['source']);verify_identity(v['assembly']['file'])
    a=instruction_rows(out/'before-bitmapcache-reader.s');b=instruction_rows(out/'after-bitmapcache-reader.s')
    before=region(a,0x1234281,0x12342a0)
    entry=region(b,0xd6f811,0xd6f84e);tail=region(b,0xdc15de,0xdc15f4)
    assert len(before)==5 and len(entry)==13 and len(tail)==4
    assert hex(offsets['before']['offsets']['value_u64_slots_']+8172*8)=='0x147a80'
    assert hex(offsets['after']['offsets']['value_words_2_slots_']+919*16)=='0x203958'
    assert hex(offsets['after']['offsets']['value_u8_slots_']+2885)=='0xe8a57'
    for n,r in [('before',before),('after-entry',entry),('after-tail',tail)]:
        (out/('bitmapcache-'+n+'-window.s')).write_text(''.join(f'{addr:x}:\t{op}\n' for addr,op in r))
    return dict(before_core_instructions=5,after_static_instructions=17,after_conditional_branches=2,
        narrow_width_bits=4,source_width_bits=128,index_range=[0,31],
        no_cross_word_proof=all((i*4)%64+4<=64 for i in range(32)),
        windows=[identity(out/('bitmapcache-'+n+'-window.s')) for n in ('before','after-entry','after-tail')],
        source_after=dict(file=str(TRANSFER/'after/model/grhsim_SimTop_sched_10.cpp'),line=102593),
        source_before=dict(file=str(TRANSFER/'before/model/grhsim_SimTop_sched_14.cpp'),line=29929),
        correspondence='Same frozen SliceArray op symbol _op_12496825 and result symbol _val_11840339; storage offsets independently compiled.',
        limit='Equivalent result extraction core, excluding producer array construction and neighbouring computation. '
              '17 counts both branch alternatives; it is not a dynamic count or net cost of the seven transformations.')


def closure(out):
    rows=instruction_rows(out/'indexed-word-caller20.s')
    window=region(rows,0x1892fff,0x1894d5c)
    stores=[]
    for addr,op in window:
        m=re.match(r'mov\s+(%r\w+),0x([0-9a-f]+)\(%rsp\)',op)
        if m and 0x6e0<=int(m[2],16)<0xee0:stores.append(dict(address=hex(addr),register=m[1],offset=int(m[2],16)))
    assert len(stores)==256 and {s['offset'] for s in stores}==set(range(0x6e0,0xee0,8))
    target=out/'indexed-word-closure-build.s';target.write_text(''.join(f'{addr:x}:\t{op}\n' for addr,op in window))
    helpers=read(TRANSFER/'offline-structure/after.json')['machine']['functions']
    named={n:r for n,r in helpers.items() if r['phase']=='compute' and 'operator()(unsigned long)' in n}
    assert len(named)==15
    function='GrhSIM_SimTop::eval_compute_batch_20()::$_0::operator()(unsigned long) const'
    return dict(outlined_word_readers=len(named),example_function=function,
        example_helper=named[function],named_snapshots=256,selected_result_width=1,word_width=64,
        closure_pointer_stores=len(stores),closure_pointer_storage_bytes=2048,
        source=dict(file=str(TRANSFER/'after/model/grhsim_SimTop_sched_20.cpp'),line=8585),
        witness=identity(target),pointer_store_witnesses=stores,helper_assembly=identity(out/'indexed-word-helper20.s'),
        limit='Window also contains snapshot calculations and unrelated work. Only 256 pointer stores are assigned to closure construction; '
              'helper 737 instructions are static across its cases. Runtime frequency and net versus eager lowering are unknown.')


def audit(out):
    models={n:TRANSFER/n for n in ('before','after')};models['no_shared']=ABLATION/'no_shared'
    for path in models.values():check_model(path)
    cv=read(out/'cv32-components.json')
    for record in cv['inputs']:verify_identity(record)
    result=dict(mode='offline_generator_cpp_elf_lineage',series=source_diff(out),simplify=simplify(out),
                rules={n:rules(p/'model') for n,p in models.items()},schedule=scheduling(out),
                bitmapcache=bitmap_elf(out),indexed_closure=closure(out),cv32_contractions=cv32_contractions(),
                cv32_components=dict(report=identity(out/'cv32-components.json'),**cv))
    machine_paths={n:TRANSFER/'offline-structure'/(n+'.json') for n in ('before','after')}
    machine_paths.update(no_shared=ABLATION/'offline-structure/no_shared.json',
        no_cones=ABLATION/'cone-analysis/no-cones-machine.json',
        corrected_full=LATEST/'machine-evidence/full-structure.json',combined=LATEST/'machine-evidence/combined-structure.json',
        corrected_no_shared=LATEST/'machine-evidence/no_shared-structure.json')
    machine_rows={}
    for n,p in machine_paths.items():
        d=read(p);m=d.get('machine',d);verify_identity(m['binary'])
        machine_rows[n]=dict(binary=m['binary'],totals=m['totals'],audit=identity(p))
        if 'cpp' in d:machine_rows[n]['cpp_counts']=d['cpp']['counts']
    result['machine']=machine_rows
    result['inputs']=[identity(HISTORICAL/'pre_reg_to_mem.json'),identity(TRANSFER/'policy.json')]
    for p in models.values():result['inputs'] += [identity(p/n) for n in ('model-sources.json','binary.json','configuration.json')]
    result['replay_tools']={n:read(out/(n+'-compile.json')) for n in ('before','after','schedule','shared','unshared')}
    for record in result['replay_tools'].values():
        verify_identity(record['binary']);verify_identity(record['library'])
        source=record.get('archived_source',record['source']);verify_identity(source)
        assert source['sha256']==record['source']['sha256']
    result['analysis_tools']=[identity(ROOT/'scripts'/n) for n in ('xiangshan_cv32_simplify_audit.cpp','xiangshan_schedule_lineage.cpp',Path(__file__).name)]
    result['status']='pass'
    result['limits']=['No simulator execution, new timings, PMU or production changes.',
        'Historical no_shared/no_cones times do not compare directly to pre-CV32 before in the same run.',
        'Rules proposed for future implementation must be static, not based on model names or observed activation frequency.']
    save(out/'report.json',result)
    print(json.dumps(dict(status='pass',changed_wide_views=result['simplify']['changed_wide_packed_concats'],
        zero_boundary_gain=result['schedule']['zero_work_boundary_elimination_classes'],
        closure_pointer_stores=result['indexed_closure']['closure_pointer_stores'])))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'build/xs/cv32-lineage-audit-v1')
    audit(p.parse_args().output.resolve())
