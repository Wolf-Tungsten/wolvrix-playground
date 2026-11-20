"""Bind independent commit and reduction experiments to frozen generated code and ELF symbols."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import subprocess

from armor_followup_compare import BASE_XS, OLD, OUT, ROOT
from cv32e40p_compare import save
from grhsim_elf_section_identity import sections
from grhsim_single_baseline import identity
from xiangshan_cv32_ablation_measure import read, verify

OP_COMMENT = re.compile(r'// op (\S+) \[(k\w+)\]')
ADD = re.compile(r'^[ \t]*(?:// Common reduction guard:|const bool factor_blocked =|if \(!factor_blocked \|\||'
                 r'reduction_factor_blocked_\[|} // common reduction guard|std::array<bool, \d+> reduction_factor_blocked_|'
                 r'reduction_factor_blocked_\.fill\().*\n', re.M)
REGION_GUARD = re.compile(r'// Supernode (\d+):|// Common reduction guard: (\d+) stable inputs\.\n'
                          r'\s*const bool factor_blocked = (.+);\n\s*if \(!factor_blocked \|\| !reduction_factor_blocked_\[(\d+)u\]')
METHOD = re.compile(r'GrhSIM_SimTop::eval_(compute|commit)_batch_(\d+)\(')


def inventory(manifest):
    return {Path(r['path']).name:r for r in read(manifest)['files']}


def audit_sources():
    audits={}
    old_census=read(ROOT/'build/armor-post-mask-analysis-v1/instrumentation.json')['sites']
    mask_by_group={}
    for row in old_census:
        common=row['masks'][0][0]
        for mask,_ in row['masks']:common &= mask
        slots={slot for i,slot in enumerate(row['slots']) if common & (1<<i)}
        mask_by_group.setdefault(row['group'],[]).append(slots)
    for design in ('xs','cv'):
        before=inventory(OLD/design/'A/sources.json')
        default=inventory(OUT/'A'/design/'sources.json')
        assert before.keys()==default.keys() and all(before[k]['sha256']==default[k]['sha256'] for k in before)
        for tag in ('C','F'):
            current=inventory(OUT/tag/design/'sources.json')
            if current.keys()!=before.keys():raise ValueError('different generated file set')
            changed=[];groups=[];commit_files={}
            for name,a in before.items():
                b=current[name]; verify(b)
                if b['sha256']==a['sha256']:continue
                verify(a);changed.append(name)
                s=Path(b['path']).read_text();old=Path(a['path']).read_text()
                if tag=='C':
                    if '::eval_commit_batch_' not in s or not re.fullmatch(r'grhsim_\w+_sched_\d+\.cpp',name):
                        raise ValueError('commit option changed unrelated file '+name)
                    if OP_COMMENT.findall(s)!=OP_COMMENT.findall(old):
                        raise ValueError('commit operation sequence differs in '+name)
                    lens=list(map(int,re.findall(r'// Same-reader scalar commit group: (\d+) writes\.',s)))
                    if not lens:raise ValueError('changed schedule without a commit group')
                    commit_files[name]=dict(groups=len(lens),writes=sum(lens),lengths=Counter(lens))
                else:
                    if ADD.sub('',s)!=old:raise ValueError('guard removal does not restore '+name)
                    group=None
                    for m in REGION_GUARD.finditer(s):
                        if m[1] is not None:
                            group=int(m[1]);continue
                        slots=list(map(int,re.findall(r'value_bool_slots_\[(\d+)\]',m[3])))
                        if design=='xs' and (len(slots)!=int(m[2]) or mask_by_group.get(group)!=[set(slots)]):
                            raise ValueError(f'guard inputs differ from the original predicate intersection in {group}')
                        groups.append(dict(file=name,group=group,inputs=slots,index=int(m[4])))
            audits[f'{design}-{tag}']=dict(file_count=len(before),changed=sorted(changed),commit=commit_files,guards=groups)
    save(OUT/'source-audit.json',audits)


def model_methods(binary):
    symbols={}
    for line in subprocess.check_output(['nm','-S','-C','--defined-only',binary],text=True).splitlines():
        columns=line.split(maxsplit=3)
        if len(columns)==4 and columns[2] in ('T','t') and METHOD.search(columns[3]):
            symbols.setdefault((int(columns[0],16),int(columns[1],16)),columns[3])
    return symbols


def count_symbols(job):
    path,start,size,symbol,batch,tag=job
    listing=subprocess.check_output(['objdump','-dw','-Mintel','--no-show-raw-insn','--start-address='+hex(start),
                                     '--stop-address='+hex(start+size),path],text=True)
    rows=re.findall(r'^[ \t]*([\da-f]+):[ \t]+(\S+)[ \t]*([^\n]*)',listing,re.M)
    stat=Counter(bytes=size,instructions=len(rows))
    for _,op,operands in rows:
        if op.startswith('j') and not op.startswith('jmp'):stat['jcc']+=1
        if op.startswith('call'):stat['calls']+=1
        if not op.startswith(('nop','lea')) and '[rsp' in operands:stat['rsp_sites']+=1
    if batch in (21,90) and symbol.endswith(f'_batch_{batch}()'):
        (OUT/'machine'/f'{tag}-{batch}.s').write_text(listing)
    return symbol,dict(stat)


def disassemble():
    evidence=OUT/'machine';evidence.mkdir(exist_ok=True)
    audit=read(OUT/'source-audit.json')
    records={name:identity(path) for name,path in [('full',BASE_XS/'emu/grhsim-compile/emu'),('commit',OUT/'C/xs/emu/grhsim-compile/emu'),('factor',OUT/'F/xs/emu/grhsim-compile/emu')]}
    batches={n:{int(k.split('_')[-1].split('.')[0]) for k in audit['xs-'+t]['changed'] if '_sched_' in k}
             for n,t in [('commit','C'),('factor','F')]}
    jobs=[];ranges={}
    for name,rec in records.items():
        path=Path(rec['path']);ranges[name]=sections(path)
        nums=set.union(*batches.values()) if name=='full' else batches[name]
        for (a,z),sym in model_methods(path).items():
            batch=int(METHOD.search(sym)[2])
            if batch in nums:jobs.append((path,a,z,sym,batch,name))
    functions={n:{} for n in records}
    with ThreadPoolExecutor(5) as pool:
        for job,(sym,stats) in zip(jobs,pool.map(count_symbols,jobs)):functions[job[-1]][sym]=stats
    differences={}
    for name,nums in batches.items():
        totals={}
        for v in ('full',name):
            counts=Counter()
            for sym,x in functions[v].items():
                if int(METHOD.search(sym)[2]) in nums:counts.update(x)
            totals[v]=dict(counts)
        differences[name]=dict(batches=sorted(nums),totals=totals,
                               delta={k:totals[name].get(k,0)-old for k,old in totals['full'].items()})
    save(OUT/'machine.json',dict(binaries=records,sections=ranges,functions=functions,comparisons=differences,
                                 scope='All main/helper executable symbols in changed schedule batches; counts static.'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('source','machine'))
    (audit_sources if parser.parse_args().stage=='source' else disassemble)()
