"""Check every emitted reduction bit and predicate against an independent source-level permutation."""
import argparse
from collections import Counter
import hashlib
from pathlib import Path
import re

from armor_mask_layout_compare import DEFAULT, MODES
from cv32e40p_compare import ROOT, save
from xiangshan_cv32_ablation_measure import read, verify
from xiangshan_packed_storage_compare import source_shape

NAME = r'grhsim_(?:short_)?reduction_inputs'
DECL = re.compile(r'const std::uint64_t ('+NAME+r') =\s*$')
FIELD = re.compile(r'\(static_cast<std::uint64_t>\(value_bool_slots_\[(\d+)\]\) << (\d+)u\)')
USE = re.compile(r'\(('+NAME+r') & UINT64_C\((\d+)\)\) != UINT64_C\((\d+)\)')
GROUP = re.compile(r'// Supernode (\d+):')


def block_starts(slots):
    starts = {}
    i = 0
    while i + 8 <= len(slots):
        if slots[i:i+8] == list(range(slots[i], slots[i]+8)):
            starts[i] = slots[i]
            i += 8
        else:
            i += 1
    return starts


def placement(slots):
    new_slots = sorted(slots[:32]) + sorted(slots[32:])
    starts = block_starts(new_slots)
    selected = len(starts) > len(block_starts(slots))
    return (new_slots, starts) if selected else (slots, {})


def parse_word(lines, start):
    slots = []
    i = start+1
    while i < len(lines):
        m = FIELD.search(lines[i])
        if not m or int(m[2]) != len(slots):
            raise ValueError('unexpected frozen bool field at line '+str(i+1))
        slots.append(int(m[1]))
        i += 1
        if lines[i-1].rstrip().endswith(';'):
            break
    if len(set(slots)) != len(slots):
        raise ValueError('repeated frozen slot')
    return slots, i


def prove_file(path, generated, helper):
    source = path.read_text().splitlines(keepends=True)
    sites = {}
    group = None
    for i,line in enumerate(source):
        if '// Supernode ' in line and (m:=GROUP.search(line)): group=int(m[1])
        if 'reduction_inputs =' in line and (m:=DECL.search(line)):
            slots,stop=parse_word(source,i)
            permuted,blocks=placement(slots)
            sites[i]=dict(group=group,name=m[1],stop=stop,slots=slots,permuted=permuted,blocks=blocks,
                          uses=0,wide=0)
    affected={s['group'] for s in sites.values() if s['blocks']}
    # Rebuild all candidate source bytes, including content outside masked predicates.
    totals={}
    for mode in ('P','B'):
        hashed=hashlib.sha256()
        active={}
        helper_needed=False
        i=0
        while i<len(source):
            line=source[i]
            if '// Supernode ' in line and (m:=GROUP.search(line)):
                active.clear()
                helper_needed=mode=='B' and int(m[1]) in affected
            if helper_needed and '// Shared stable Boolean inputs for masked concat reductions.' in line:
                hashed.update(helper.encode())
                helper_needed=False
            if i in sites:
                s=sites[i]
                active[s['name']]=s
                hashed.update(line.encode())
                bit=0
                while bit<len(s['permuted']):
                    slot=s['permuted'][bit]
                    block=mode=='B' and bit in s['blocks']
                    expr=('grhsim_read_reduction_mask8(&' if block else 'static_cast<std::uint64_t>(')
                    fragment=f'            ({expr}value_bool_slots_[{slot}]) << {bit}u)'
                    bit+=8 if block else 1
                    hashed.update((fragment+(';\n' if bit==len(s['slots']) else ' |\n')).encode())
                i=s['stop']
                continue
            if 'reduction_inputs &' in line:
                def remap(match):
                    word,mask,rhs=match.groups()
                    mask,rhs=int(mask),int(rhs)
                    s=active[word]
                    before=s['slots']
                    after=s['permuted']
                    if mask.bit_length()>len(before) or rhs not in (0,mask):
                        raise ValueError('invalid original mask or reduction family')
                    selected={v for j,v in enumerate(before) if mask & (1<<j)}
                    changed=sum(1<<j for j,v in enumerate(after) if v in selected)
                    if {v for j,v in enumerate(after) if changed & (1<<j)} != selected or (changed>>32!=0)!=(mask>>32!=0):
                        raise ValueError('permutation lost a leaf or changed 32-bit membership')
                    if mode=='B':
                        s['uses']+=1
                        s['wide']+=int(mask>0xffffffff)
                    return f'({word} & UINT64_C({changed})) != UINT64_C({changed if rhs else 0})'
                line,n=USE.subn(remap,line)
                if n==0: raise ValueError('unrecognized predicate: '+line)
            hashed.update(line.encode())
            i+=1
        actual=generated[mode][path.name][1]
        if hashed.hexdigest()!=actual:
            raise ValueError(f'{path.name} {mode}: source does not exactly reproduce independent reconstruction')
        totals[mode]=actual
    return list(sites.values())


def audit(out):
    snapshot=out/'snapshot/grhsim_cpp.cpp'
    verify(read(out/'policy.json')['emitter'])
    helper=snapshot.read_text().split('R"GRHSIM(        const auto grhsim_read_reduction_mask8 =',1)[1].split(')GRHSIM"',1)[0]
    helper='        const auto grhsim_read_reduction_mask8 ='+helper
    design={}
    for name in ('xs','cv'):
        records={m:read(out/name/m/'sources.json')['files'] for m in MODES}
        for rows in records.values():
            for row in rows: verify(row)
        shapes={m:source_shape(rows) for m,rows in records.items()}
        frozen=source_shape(read(ROOT/'build/armor-lane-v1/frozen'/(name+'-off')/'sources.json')['files'])
        if shapes['A']!=frozen or any(set(s)!=set(frozen) for s in shapes.values()):
            raise ValueError('baseline sources, outputs or schema drifted')
        changed=[n for n in frozen if any(s[n]!=frozen[n] for s in shapes.values())]
        if any(not re.fullmatch(r'grhsim_\w+_sched_\d+\.cpp',n) for n in changed):
            raise ValueError('unexpected changes outside compute batches')
        allsites=[]
        expected=read(ROOT/'build/armor-direction-v2/mask-layout.json')[name]['rows']
        scope_files=sorted({s['file'] for s in expected} | set(changed))
        for n in scope_files:
            sites=prove_file(out/name/'A/model'/n,shapes,helper)
            for s in sites:s['file']=n
            allsites.extend(sites)
        expected_keys={(s['file'],s['group'],s['name']):s for s in expected}
        if len(allsites)!=len(expected_keys):raise ValueError('lost or duplicated mask words')
        totals=Counter()
        for s in allsites:
            oracle=expected_keys[(s['file'],s['group'],s['name'])]
            if (s['slots']!=oracle['inputs'] or s['uses']!=oracle['predicates'] or
                bool(s['blocks'])!=(oracle['half8']>oracle['old8'])):
                raise ValueError('new inventory differs from the predeclared cohort')
            totals.update(words=1,predicates=s['uses'],selected=bool(s['blocks']),reads=len(s['blocks']),
                wide=s['wide'],selected_predicates=s['uses'] if s['blocks'] else 0)
        design[name]=dict(files=len(frozen),changed=changed,counts=dict(totals),sites=allsites)
        if len(changed)==0 and name=='xs':raise ValueError('missing XS changes')
    save(out/'source-audit.json',design)
    print({d:(len(t['changed']),t['counts']) for d,t in design.items()},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=DEFAULT)
    audit(p.parse_args().out.resolve())
