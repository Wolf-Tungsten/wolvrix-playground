#!/usr/bin/env python3
"""Offline source and ELF evidence for the frozen indexed snapshot experiment."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess

from cv32e40p_compare import ROOT, identity, save
from cv32e40p_current_structure import elf_model
from cv32e40p_current_structure_paths import dwarf_file_checksums, LLVM
from cv32e40p_event_regions_compare import check as cv_check
from indexed_snapshot_compare import XS_BASE,CV_BASE,BASE,CANDIDATE,check_xs
from xiangshan_cv32_structure import machine


def read(p):return json.loads(p.read_text())


def delta(old,new):
    return {key:dict(before=value,after=new.get(key,0),difference=new.get(key,0)-value,
                     percent=100*(new.get(key,0)/value-1) if value else None)
            for key,value in old.items() if isinstance(value,int)}


def source_sites(out,old,new):
    sites=read(out/'structure.json')['candidate']['sites'];dest=out/'machine-evidence';result=[]
    for site in sites:
        entry=dict(site);records={};name='grhsim_concat_word_'+str(site['value'])
        for label,folder in (('before',old),('candidate',new)):
            file=folder/site['file'];code=file.read_text();lines=code.splitlines()
            start=next(i for i,line in enumerate(lines) if name+' =' in line)
            end=next(i for i in range(start+1,len(lines)) if lines[i]=='        };')
            call=next(i for i in range(end+1,len(lines)) if name in lines[i] and 'grhsim_indexed_' in lines[i])
            excerpt=dest/f"view-{site['value']}-{label}.cpp.txt"
            excerpt.write_text('\n'.join(f'{i+1}: {lines[i]}' for i in range(start,call+1))+'\n')
            captures=set(re.findall(r'grhsim_v\d+_\d+', '\n'.join(lines[start:end+1])))
            records[label]=dict(source=identity(file),start_line=start+1,end_line=end+1,call_line=call+1,
                                unique_named_snapshots=len(captures),excerpt=identity(excerpt))
        entry['source']=records;result.append(entry)
    return result


def cv_counts(out):
    olddir=ROOT/'build/cv32e40p/shared-arm-counts-v1';newdir=ROOT/'build/cv32e40p/indexed-snapshot-counts-v3'
    build=cv_check(out);assert read(olddir/'inputs.json')['model']['sha256']==build['binaries'][BASE]['sha256']
    assert read(newdir/'inputs.json')['model']==build['binaries'][CANDIDATE]
    reports={}
    for workload in ('smoke','coremark'):
        old=read(olddir/'counts.json')[workload];new=read(newdir/'counts.json')[workload]
        assert old['counts']==new['counts'] and old['cycles']==new['cycles']
        assert old['trace']['sha256']==new['trace']['sha256']
        reports[workload]=dict(counters=len(old['counts']),cycles=old['cycles'],identical=True)
    save(out/'count-gate.json',dict(status='pass',workloads=reports,
        inputs=[identity(d/n) for d in (olddir,newdir) for n in ('counts.json','inputs.json')],
        script=identity(Path(__file__).resolve())))


def xs(out):
    check_xs(out);dest=out/'machine-evidence';dest.mkdir(exist_ok=True)
    binary=out/'candidate/emu/grhsim-compile/emu';cached=dest/'candidate.json'
    if cached.exists():current=read(cached);assert current['binary']==identity(binary)
    else:current=machine(binary);save(cached,current)
    old=read(XS_BASE/'machine-evidence/candidate.json');assert old['binary']==read(out/'full/binary.json')
    totals={phase:delta(old['totals'][phase],current['totals'][phase]) for phase in ('compute','commit','eval')}
    source=source_sites(out,out/'full/model',out/'candidate/model')
    helpers={}
    for record in source:
        batch=re.search(r'_sched_(\d+)\.cpp',record['file'])[1]
        prefix='GrhSIM_SimTop::eval_compute_batch_'+batch+'()'
        entry={}
        for label,model,data in (('before',out/'full',old),('candidate',out/'candidate',current)):
            selected={n:r for n,r in data['functions'].items() if n.startswith(prefix)}
            entry[label]=selected
            symbols={}
            text=subprocess.check_output(['nm','-S','-C','--defined-only',model/'emu/grhsim-compile/emu'],text=True)
            for line in text.splitlines():
                parts=line.split(maxsplit=3)
                if len(parts)==4 and parts[3] in selected:symbols[parts[3]]=(int(parts[0],16),int(parts[1],16))
            for index,(name,(address,size)) in enumerate(symbols.items()):
                command=['objdump','-d','-w','-C','--no-show-raw-insn',f'--start-address={address}',f'--stop-address={address+size}',str(model/'emu/grhsim-compile/emu')]
                path=dest/f'batch-{batch}-{label}-{index}.s';path.write_text(subprocess.check_output(command,text=True))
                selected[name]['assembly']=identity(path)
        helpers[batch]=entry
    save(out/'machine-analysis.json',dict(status='pass',totals=totals,source=source,site_functions=helpers,
        inputs=[identity(XS_BASE/'machine-evidence/candidate.json'),identity(cached),identity(out/'structure.json'),identity(Path(__file__).resolve())],
        limits='Release XS ELF has no DWARF line map. Static shape and disappearance of a closure do not establish dynamic cost or whole-model speedup.'))
    print('XS source/ELF complete',flush=True)


def source_checksums(folder, required):
    dump=subprocess.check_output([LLVM/'llvm-dwarfdump','--debug-line',folder/'emu'],text=True)
    embedded=dwarf_file_checksums(dump);rows=[]
    for filename in sorted(required):
        digest=hashlib.md5((folder/filename).read_bytes()).hexdigest()
        if filename in embedded:assert embedded[filename]=={digest},filename
        rows.append(dict(**identity(folder/filename),dwarf_md5=digest if filename in embedded else None,
            checksum_status='verified' if filename in embedded else 'absent; frozen compiler inputs only'))
    return rows


def witness(out):
    report=read(out/'machine-analysis.json');site=report['site_functions']['19'];dest=out/'machine-evidence'
    name='GrhSIM_SimTop::eval_compute_batch_19()'
    def rows(record):
        path=Path(record['assembly']['path']);assert identity(path)==record['assembly']
        return [(int(m[1],16),m[2]) for m in re.finditer(r'(?m)^\s*([0-9a-f]+):\s+(.+)$',path.read_text())]
    before=rows(site['before'][name]);after=rows(site['candidate'][name])
    helper=next(n for n in site['before'] if 'operator()' in n)
    assert not any('operator()' in n for n in site['candidate'])
    target=site['before'][helper]['address'];call=next(i for i,(_,op) in enumerate(before) if re.match(r'call\s+'+f'{target:x}'+r'\b',op))
    pointers=[]
    for addr,op in before[max(0,call-1600):call]:
        m=re.match(r'mov\s+(%r\w+),0x([0-9a-f]+)\(%rsp\)',op)
        if m and 0x16b0<=int(m[2],16)<0x1eb0:pointers.append(dict(address=hex(addr),offset=int(m[2],16),instruction=op))
    assert len(pointers)==256 and {p['offset'] for p in pointers}==set(range(0x16b0,0x1eb0,8))
    matches=[i for i,(_,op) in enumerate(after) if re.match(r'movzbl\s+0x15a0\(%rsp,%rax,1\),%eax',op)]
    assert len(matches)==1;index=matches[0];assert '0xe3e77(' in after[index-1][1]
    stores=[]
    for addr,op in after[index-600:index]:
        m=re.match(r'vmov\w*\s+%zmm\d+,0x([0-9a-f]+)\(%rsp\)',op)
        if m and 0x15a0<=int(m[1],16)<0x16a0:stores.append(dict(address=hex(addr),offset=int(m[1],16),instruction=op))
    assert len(stores)==4 and {p['offset'] for p in stores}=={0x15a0,0x15e0,0x1620,0x1660}
    paths=[]
    for label,items in (('pointer-capture',before[call-1600:call+1]),('array-read',after[index-60:index+3])):
        path=dest/(label+'.s');path.write_text(''.join(f'{a:x}:\t{o}\n' for a,o in items));paths.append(identity(path))
    save(out/'capture-evidence.json',dict(status='pass',value=1055061,before_pointer_bytes=2048,candidate_array_bytes=256,
        pointer_stores=pointers,array_stores=stores,read_instructions=[dict(address=hex(a),instruction=o) for a,o in after[index-1:index+2]],
        old_helper_instructions=site['before'][helper]['counts']['instructions'],helper_eliminated=True,
        inputs=[identity(out/'machine-analysis.json'),identity(Path(__file__).resolve()),*paths],
        limits='Frozen ELF witness: capture stores and direct byte read. Excludes scalar-producer work and does not imply execution frequency or a whole-model speedup.'))


def cv(out):
    cv_check(out);dest=out/'machine-evidence';dest.mkdir(exist_ok=True);models={}
    for label,folder in (('baseline',CV_BASE/BASE),('candidate',out/CANDIDATE)):
        cached=dest/(label+'.json')
        if cached.exists():record=read(cached);assert record['binary']==identity(folder/'emu')
        else:
            result,rows=elf_model(label,folder,dest);required={r['model_source']['file'] for r in rows if r['model_source']}
            record=dict(binary=identity(folder/'emu'),elf=result,source_checksums=source_checksums(folder,required));save(cached,record)
        models[label]=record
    shapes={}
    for label,record in models.items():
        phases={}
        for f in record['elf']['functions']:
            phase='compute' if 'eval_compute_batch_' in f['symbol'] else 'commit' if 'eval_commit_batch_' in f['symbol'] else 'other'
            phases.setdefault(phase,Counter()).update({k:v for k,v in f.items() if isinstance(v,int) and k!='address'})
        shapes[label]=phases
    totals={phase:delta(shapes['baseline'][phase],shapes['candidate'][phase]) for phase in shapes['baseline']}
    source=source_sites(out,CV_BASE/BASE,out/CANDIDATE)
    save(out/'machine-analysis.json',dict(status='pass',models=models,totals=totals,source=source,
        inputs=[identity(out/'build.json'),identity(out/'structure.json'),identity(Path(__file__).resolve())],
        limits='Available CV32 DWARF source checksums verified; missing entries marked individually and covered only by frozen compiler inputs. Static instructions and source mappings are not executed work.'))
    print('CV32 source/ELF complete',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('model',choices=('xs','cv','cv-counts','witness'));p.add_argument('--source',type=Path,required=True)
    args=p.parse_args();{'xs':xs,'cv':cv,'cv-counts':cv_counts,'witness':witness}[args.model](args.source.resolve())
