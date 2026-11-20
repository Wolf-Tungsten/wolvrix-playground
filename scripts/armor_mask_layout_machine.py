"""Compare complete affected compute symbols and the frozen first predicate store in batch 21."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import subprocess

from armor_lane_machine import funcs
from armor_mask_layout_compare import DEFAULT
from cv32e40p_compare import identity, save
from grhsim_elf_section_identity import sections
from xiangshan_cv32_ablation_measure import read, verify

INSN = re.compile(r'^\s*([0-9a-f]+):\s+(\S+)\s*(.*)')
MEM_SOURCE = re.compile(r'\([^)]*%[^)]*\)(?:\{[^}]*\})*,')
SHIFT = re.compile(r'^(?:sh[lr]|sa[lr]|ro[lr]|shlx|shrx|sarx|v?ps[rl][la])')
REARRANGE = re.compile(r'^(?:v?p(?:insr|extr|shuf|erm|unpck|ack|blend)|v(?:shuf|perm|insert|extract|blend)|k(?:shift|unpck))')
BRANCH = re.compile(r'^(?:j\w+|ret\w*|call\w*)$')
METRICS=('code_bytes','instructions','conditional_branches','calls','memory_source_sites','byte_loads',
         'byte_inserts','scalar_vector_shifts','rearranges','pext','movabs_immediate','rip_relative_reads','rsp_sites')


def tally(lines, size):
    c=Counter(code_bytes=size)
    for line in lines:
        m=INSN.match(line)
        if not m: continue
        _,op,args=m.groups()
        c['instructions']+=1
        if op.startswith('j') and op not in ('jmp','jmpq'):c['conditional_branches']+=1
        if op.startswith('call'):c['calls']+=1
        if op.startswith(('lea','nop')):continue
        if '(' in args:
            source = bool(MEM_SOURCE.search(args))
            if source: c['memory_source_sites']+=1
            if source and op in ('movzbl','movzbq','movsbl','movsbq'):c['byte_loads']+=1
            if source and op in ('vpinsrb','pinsrb'):c['byte_inserts']+=1
            if '%rip)' in args and source:c['rip_relative_reads']+=1
            if re.search(r'\([^)]*%rsp',args):c['rsp_sites']+=1
        if SHIFT.match(op):c['scalar_vector_shifts']+=1
        if REARRANGE.match(op):c['rearranges']+=1
        if op.startswith('pext'):c['pext']+=1
        if op.startswith('movabs') and args.startswith('$'):c['movabs_immediate']+=1
    return {k:c[k] for k in METRICS}


def window(lines, site, offset, path):
    # Bind the same observable bool output. Use the model base register used at
    # that store and the incoming branch, allowing register allocation to vary.
    end_store=re.compile(r'\b(?:set\w+\s+|(?:v?mov\w*)\s+[^,]+,)'+hex(offset)+r'\((%r\w+)\)')
    stores=[(i,m[1]) for i,line in enumerate(lines) if (m:=end_store.search(line))]
    if len(stores)!=1: raise ValueError('ambiguous target store '+str(stores))
    end,base=stores[0]
    start=next(i+1 for i in range(end-1,-1,-1) if (m:=INSN.match(lines[i])) and BRANCH.fullmatch(m[2]))
    slot_offset=offset-723607
    addresses={slot_offset+s for s in site['slots']}
    mem=re.compile(r'\b(0x[\da-f]+)\('+base+r'\)')
    members=Counter()
    seen=[]
    for line in lines[start:end+1]:
        for match in mem.finditer(line):
            address=int(match[1],16)
            if address in addresses:
                op=INSN.match(line)[2]
                members[op]+=1
                seen.append(dict(slot=address-slot_offset,instruction=line.strip()))
    path.write_text('\n'.join(lines[start-1:end+1])+'\n')
    return dict(store=lines[end].strip(),base=base,first=lines[start].strip(),
        last=lines[end].strip(),matched=dict(members),input_sites=len(seen),
        input_byte_sites=sum(members[k] for k in ('movzbl','movzbq','movsbl','movsbq','vpinsrb','pinsrb')),
        classified=tally(lines[start:end+1],0),source_reads=seen,listing=identity(path))


def model(tag, elf, batches, site, offset, target):
    found=funcs(elf)
    functions={}
    totals=Counter()
    witness=None
    ranges={}
    for name,(address,length) in sorted(found.items(),key=lambda x:x[1][0]):
        batch=int(re.search(r'::eval_compute_batch_(\d+)',name)[1])
        if batch not in batches:continue
        if (address,length) in ranges:
            # A second label for identical code contributes no additional bytes.
            continue
        ranges[(address,length)]=name
        command=['objdump','-dw','--no-show-raw-insn','--start-address='+hex(address),
                 '--stop-address='+hex(address+length),elf]
        lines=subprocess.check_output(command,text=True).splitlines()
        metrics=tally(lines,length)
        functions[name]=metrics; totals.update(metrics)
        if name=='GrhSIM_SimTop::eval_compute_batch_21()':
            witness=window(lines,site,offset,target/(tag+'-28016.s'))
    ordered=sorted(ranges)
    if any(a[0]+a[1]>b[0] for a,b in zip(ordered,ordered[1:])):raise ValueError('overlapping function symbols')
    if not witness:raise ValueError('missing witness')
    return dict(binary=identity(elf),functions=functions,totals=dict(totals),sections=sections(elf),witness=witness)


def analyze(out):
    src=read(out/'source-audit.json')['xs']
    batches={int(n.split('_')[-1].split('.')[0]) for n in src['changed']}
    site=next(s for s in src['sites'] if s['group']==28016)
    if sorted(site['blocks'].values())==[]:raise ValueError('witness not transformed')
    inputs=read(out/'inputs.json')
    binaries={'A':inputs['xs_binary'], **{s:read(out/'xs'/s/'binary.json') for s in ('P','B')}}
    for r in binaries.values():verify(r)
    target=out/'machine';target.mkdir(exist_ok=True)
    previous=read(out.parents[1]/'armor-direction-v2/direction-summary.json')['A_witness']
    assert previous['first_output_slot']==723607
    offset=previous['model_bool_offset']+previous['first_output_slot']
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs={s:pool.submit(model,s,Path(r['path']),batches,site,offset,target) for s,r in binaries.items()}
        results={s:j.result() for s,j in jobs.items()}
    a=results['A']['witness']
    if a['matched']!=previous['input_slot_address_operands']:raise ValueError('original ELF anchor failed to reproduce')
    deltas={pair:{k:results[pair[0]]['totals'][k]-results[pair[1]]['totals'][k] for k in METRICS}
            for pair in ('PA','BP','BA')}
    local=results['B']['witness']
    gate={'fewer_instructions':deltas['BA']['instructions']<0,'fewer_bytes':deltas['BA']['code_bytes']<0,
          'fewer_witness_input_memory_sites':local['input_sites']<a['input_sites'],
          'fewer_witness_byte_load_or_insert_sites':local['input_byte_sites']<a['input_byte_sites']}
    save(out/'machine.json',dict(models=results,deltas=deltas,gate=gate,passed=all(gate.values()),
        batches=sorted(batches),source=identity(out/'source-audit.json'),
        metric_scope='Static instructions, explicit AT&T non-last memory operand for memory_source_sites (not dynamic loads); shifts and rearranges are mnemonic classes.'))
    print('BA delta',deltas['BA'],'gate',gate,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=DEFAULT)
    analyze(p.parse_args().out.resolve())
