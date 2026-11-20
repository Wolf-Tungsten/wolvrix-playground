"""Compile the frozen candidate and compare the actual changed compute functions."""
import argparse
from collections import Counter
import gzip
from pathlib import Path
import platform
import re
import shutil
import subprocess

from cv32e40p_compare import CFLAGS, CXX, ROOT, run, save
from grhsim_single_baseline import clean_environment, identity
from grhsim_elf_section_identity import sections
from xiangshan_cv32_ablation_measure import read, verify


def build(out, archive):
    if not platform.node().startswith('node030'):
        raise ValueError('native model flags require node030')
    src=archive/'build/xs/indexed-snapshot-20261117-v3/candidate'
    dst=out/'xs'
    original={Path(r['path']).name:r for r in read(src/'model-sources.json')}
    current=read(dst/'sources.json')['files']
    changed=[]
    for r in current:
        path=Path(r['path'])
        verify(r)
        verify(original[path.name])
        if r['sha256']!=original[path.name]['sha256']:
            changed.append(path.name)
    if any(not re.fullmatch(r'grhsim_SimTop_sched_\d+\.cpp',s) for s in changed):
        raise ValueError('unexpected changes beyond compute schedule C++: '+str(changed))
    shutil.copytree(src/'chisel-home',dst/'chisel-home')
    env=clean_environment()
    env.update(NOOP_HOME=str(archive/'testcase/xiangshan'),LC_ALL='C')
    command=[arg.replace(str(src),str(dst)) for arg in read(src/'logs/compile.command.json')['argv']]
    run(command,dst/'compile.log',env=env)
    save(dst/'binary.json',identity(dst/'emu/grhsim-compile/emu'))
    save(dst/'changed-sources.json',changed)
    gen=out/'cv/model'
    run(['make','-C',gen,'-j','12','CXX='+str(CXX),'CXXFLAGS='+' '.join(CFLAGS)],out/'cv/compile.log')
    run([CXX,*CFLAGS,'-DCV32_GRHSIM','-I',gen,archive/'build/cv32e40p/run2/inputs/fixture/harness.cpp',
         gen/'libgrhsim_Cv32Bench.a','-o',gen/'emu'],out/'cv/link.log')
    cvbase=archive/'build/cv32e40p/indexed-snapshot-v3/grhsim_indexed_snapshot/emu'
    cv={'baseline':sections(cvbase),'candidate':sections(gen/'emu')}
    if read(out/'cv/sources.json')['unchanged'] and cv['baseline']!=cv['candidate']:
        raise ValueError('same-source CV32 has different code/data sections')
    save(out/'cv/sections.json',cv)


def funcs(elf):
    text=subprocess.check_output(['nm','-S','-C','--defined-only',elf],text=True)
    found={}
    for l in text.splitlines():
        cols=l.split(maxsplit=3)
        if len(cols)==4 and cols[2] in ('t','T') and 'GrhSIM_SimTop::eval_compute_batch_' in cols[3]:
            found[cols[3]]=(int(cols[0],16),int(cols[1],16))
    return found


def analyze(out, archive):
    src=archive/'build/xs/indexed-snapshot-20261117-v3/candidate'
    dst=out/'xs'
    nums={s.split('_')[-1].split('.')[0] for s in read(dst/'changed-sources.json')}
    results={}
    evidence=out/'machine'
    evidence.mkdir(exist_ok=True)
    for name,elf in [('A',src/'emu/grhsim-compile/emu'),('B',dst/'emu/grhsim-compile/emu')]:
        functions={}
        for sym,(address,length) in funcs(elf).items():
            batch=re.search(r'::eval_compute_batch_(\d+)',sym)[1]
            if batch not in nums: continue
            cmd=['objdump','-d','-w','--no-show-raw-insn','--start-address='+hex(address),
                 '--stop-address='+hex(address+length),elf]
            listing=subprocess.check_output(cmd,text=True)
            with gzip.open(evidence/(name+'-'+str(address)+'.s.gz'),'wt') as f:f.write(listing)
            c=Counter(code_bytes=length)
            for line in listing.splitlines():
                m=re.match(r'\s*[0-9a-f]+:\s+(\S+)\s*(.*)',line)
                if not m:continue
                op,args=m.groups();c['instructions']+=1
                if op.startswith('j') and op not in ('jmp','jmpq'):c['conditional_branches']+=1
                if op.startswith('call'):c['calls']+=1
                if not op.startswith(('lea','nop')) and re.search(r'\([^)]*%rsp',args):c['rsp_operands']+=1
            functions[sym]=dict(c)
        totals=Counter()
        for row in functions.values():totals.update(row)
        results[name]=dict(binary=identity(elf),functions=functions,affected_totals=dict(totals),
            sections=sections(elf))
    delta={k:v-results['A']['affected_totals'].get(k,0) for k,v in results['B']['affected_totals'].items()}
    # Link a common result slot, not a source line inferred from addresses.
    # Both binaries have the same model header. Clang can use different base registers.
    batch=62
    srcfile=f'grhsim_SimTop_sched_{batch}.cpp'
    before,after=src/'model'/srcfile,dst/'model'/srcfile
    if srcfile in read(dst/'changed-sources.json'):
        for path in (before,after):
            if 'value_bool_slots_[192895]' not in path.read_text():
                raise ValueError('missing batch62 output anchor')
        probe=evidence/'slot-offset.cpp'
        probe.write_text('#include "'+str(dst/'model/grhsim_SimTop.hpp')+'"\n'+
            'extern "C" unsigned slot_offset() { return __builtin_offsetof(GrhSIM_SimTop,value_bool_slots_)+192895; }\n')
        asm=evidence/'slot-offset.s'
        subprocess.run([CXX,'-std=c++20','-O2','-S','-fno-access-control','-Wno-invalid-'+'offsetof',probe,'-o',asm],check=True)
        offset=int(re.search(r'movl\s+\$(\d+),',asm.read_text())[1])
        witness={}
        for name in ('A','B'):
            info=results[name]
            sym=f'GrhSIM_SimTop::eval_compute_batch_{batch}()'
            addr,_=funcs(Path(info['binary']['path']))[sym]
            with gzip.open(evidence/(name+'-'+str(addr)+'.s.gz'),'rt') as f:
                lines=f.read().splitlines()
            positions=[i for i,l in enumerate(lines) if re.search(r'vmovq\s+%xmm\d+,'+hex(offset)+r'\(',l)]
            if len(positions)!=1: raise ValueError('ambiguous slot witness')
            i=positions[0]
            excerpt=evidence/(name+'-batch62-store.s')
            excerpt.write_text('\n'.join(lines[i-22:i+5])+'\n')
            witness[name]=dict(slot_store=lines[i].strip(),window=identity(excerpt))
        save(evidence/'witness.json',dict(slot=192895,offset=hex(offset),batch=batch,
            proof='Identical header and named slot store; neighboring instructions form a window, not an exact per-pack dynamic cost.',
            sources=[identity(before),identity(after)],windows=witness))
    save(evidence/'report.json',dict(affected_batches=sorted(map(int,nums)),delta=delta,models=results))
    print('Affected compute functions, candidate minus baseline:',delta,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=('build','analyze'));p.add_argument('--output',required=True,type=Path)
    p.add_argument('--archive',type=Path,default=ROOT.parent/'wolvrix-playground-cv32e40p')
    a=p.parse_args()
    (build if a.stage=='build' else analyze)(a.output.resolve(),a.archive.resolve())
