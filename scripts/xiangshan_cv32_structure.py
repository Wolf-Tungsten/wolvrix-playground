#!/usr/bin/env python3
"""Offline C++/ELF structural audit of the frozen XiangShan comparison."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess

from grhsim_single_baseline import identity, save

FUNCTION = re.compile(r'void GrhSIM_SimTop::(eval_(compute|commit)_batch_\d+)\(')
GROUP = re.compile(r'// Supernode (\d+):')
OP = re.compile(r'// op .*\[(k\w+)\]')
INSN = re.compile(r'^\s*([0-9a-f]+):\s+([a-zA-Z][a-zA-Z0-9.]*)\s*(.*)$')
LABEL = re.compile(r'^([0-9a-f]+) <(.+)>:$')


def cpp(folder):
    counts=Counter();by_phase={};hist=Counter();small=[];groups=[]
    for path in sorted(folder.glob('*_sched_*.cpp')):
        phase=None;group=None;ops=Counter();start=0
        def finish():
            if group is None:return
            work=sum(v for k,v in ops.items() if k not in ('kRegisterReadPort','kConstant','kAssign'))
            bucket='0' if not work else '1-4' if work<=4 else '5-16' if work<=16 else '17-108' if work<=108 else '>108'
            if phase=='compute':hist[bucket]+=1
            record=dict(group=group,phase=phase,file=path.name,line=start,ops=sum(ops.values()),
                        non_read_const_assign_ops=work,kinds=dict(ops))
            groups.append(record)
            if phase=='compute' and work<=4 and len(small)<24:small.append(record)
        with path.open() as stream:
            for line_no,line in enumerate(stream,1):
                match=FUNCTION.search(line)
                if match:
                    finish();group=None;ops=Counter();phase=match[2]
                match=GROUP.search(line)
                if match:
                    finish();group=int(match[1]);ops=Counter();start=line_no
                match=OP.search(line)
                if match and group is not None:ops[match[1]]+=1
                if phase is None:continue
                count=by_phase.setdefault(phase,Counter())
                for key,token in (
                    ('activity_word_guards','if (unlikely(activeWordFlags != UINT8_C(0)))'),
                    ('group_guards','if (unlikely(activeWordFlags & UINT8_C('),
                    ('persistent_activation_updates','supernode_active_'),
                    ('local_change_accumulators','bool grhsim_any_changed_'),
                    ('local_change_or_updates','grhsim_any_changed_'),
                    ('scalar_old_value_reads','const auto grhsim_old_'),
                    ('scalar_change_checks','const bool grhsim_changed_'),
                    ('packed_change_groups','grhsim_changed_packed_'),
                    ('conditional_cones','// Conditional mux cone:'),
                    ('input_caches','// Conditional mux input cache:'),
                    ('covered_views','// Covered state view:'),
                    ('composed_expressions','// Composed state expression:')):
                    if token in line:
                        if key=='persistent_activation_updates' and '|=' not in line:continue
                        if key=='local_change_or_updates' and '|=' not in line:continue
                        count[key]+=1
        finish()
    return dict(counts={k:dict(v) for k,v in by_phase.items()},compute_group_op_histogram=dict(hist),
                small_group_examples=small,groups=groups,
                limits='Group operation counts use emitted operation comments; exclude read/constant/assign for the work histogram. Static, not executed counts.')


def machine(binary):
    by_function={};current=None;phase=None
    command=['objdump','-d','-w','-C','--no-show-raw-insn',str(binary)]
    process=subprocess.Popen(command,stdout=subprocess.PIPE,text=True)
    for line in process.stdout:
        m=LABEL.match(line.rstrip())
        if m:
            name=m[2]
            if name.startswith('GrhSIM_SimTop::'):
                phase='compute' if 'eval_compute_batch_' in name else 'commit' if 'eval_commit_batch_' in name else 'eval' if name=='GrhSIM_SimTop::eval()' else 'other'
                current=by_function.setdefault(name,dict(address=int(m[1],16),phase=phase,counts=Counter(),
                    first_instructions=[],entry_stack_subtractions=[]))
            else:current=None
            continue
        if current is None:continue
        m=INSN.match(line)
        if not m:continue
        mnemonic,operand=m[2].lower(),m[3];count=current['counts'];count['instructions']+=1
        # Objdump prints prefixes before the actual mnemonic. Classify a
        # multi-prefix alignment NOP as NOP, not an apparent memory operation.
        while mnemonic in ('data16','addr32','rep','repz','repnz','repe','repne',
                           'lock','bnd','notrack','cs','ds','es','fs','gs','ss','rex.w','rex'):
            parts=operand.split(None,1)
            if not parts:break
            mnemonic=parts[0].lower();operand=parts[1] if len(parts)>1 else ''
        if len(current['first_instructions'])<24:current['first_instructions'].append(line.strip())
        if count['instructions']<=100:
            sub=re.match(r'\$(0x[0-9a-f]+|[0-9]+),%rsp',operand)
            if mnemonic.startswith('sub') and sub:current['entry_stack_subtractions'].append(int(sub[1],0))
        if mnemonic.startswith('j'):
            count['branches']+=1
            if mnemonic not in ('jmp','jmpq'):count['conditional_branches']+=1
        if mnemonic.startswith(('cmp','test')):count['compare_test']+=1
        if mnemonic.startswith(('set','cmov')):count['setcc_cmov']+=1
        if mnemonic.startswith('call'):count['calls']+=1
        if mnemonic.startswith('ret'):count['returns']+=1
        if mnemonic.startswith(('v','k')) or re.search(r'%(?:xmm|ymm|zmm|k)[0-9]+',operand):count['vector_or_mask']+=1
        # Parentheses in demangled branch targets, e.g. eval(), are not memory.
        if re.search(r'\([^)]*%[a-z]',operand.split('#',1)[0]) and not mnemonic.startswith(('lea','nop')):
            count['memory_operands_excluding_lea_nop']+=1
            if re.search(r'\([^)]*%rsp',operand):count['rsp_memory_operands']+=1
            if re.search(r'\([^)]*%rbp',operand):count['rbp_memory_operands']+=1
    if process.wait():raise RuntimeError('objdump failed')
    totals={}
    for value in by_function.values():totals.setdefault(value['phase'],Counter()).update(value['counts'])
    return dict(binary=identity(binary),command=command,totals={k:dict(v) for k,v in totals.items()},functions=by_function,
        limits='Static disassembly counts, not retired instructions, execution frequency or branch misses. RBP may be an ordinary pointer. Stack subtractions list entry instructions, not always full frame size. No DWARF line map in these release ELFs.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--variant',choices=['before','after'],required=True)
    args=parser.parse_args();out=args.source.resolve();model=out/args.variant
    dest=out/'offline-structure';dest.mkdir(exist_ok=True)
    result=dict(cpp=cpp(model/'model'),inputs=[identity(model/'binary.json'),identity(model/'model-sources.json'),identity(Path(__file__))])
    save(dest/(args.variant+'-cpp.json'),result)
    print(args.variant+' C++ complete',flush=True)
    result['machine']=machine(model/'emu/grhsim-compile/emu')
    save(dest/(args.variant+'.json'),result)
    print(args.variant+' ELF complete',flush=True)
