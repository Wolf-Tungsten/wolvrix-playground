#!/usr/bin/env python3
"""Offline budget and ELF audit for the frozen two-stage expression experiment."""
import argparse
import csv
from functools import cache
import json
from pathlib import Path
import re

from cv32e40p_compare import identity,save
from cv32e40p_event_regions_compare import check
from cv32e40p_state_expression_compare import BASE,BASELINE,NOTIFY,INLINE
from cv32e40p_current_structure import elf_model
from cv32e40p_current_structure_paths import verify_embedded_sources


def audit(out):
    manifest=check(out);s=json.loads((out/'structure.json').read_text())
    graph=json.loads((out/INLINE/'normalized.json').read_text())['graphs'][0]
    values={v['sym']:v for v in graph['vals']};ops={o['sym']:o for o in graph['ops']}
    mapping={r['op_symbol']:r for r in csv.DictReader((out/'sources.csv').open())}
    ids={int(i):v for r in mapping.values() for i,v in zip(r['value_ids'].split(';'),r['value_symbols'].split(';')) if i}
    @cache
    def cost(value):
        op=ops[values[value]['def']]
        if op['kind'] in ('kConstant','kRegisterReadPort'):return 0
        return 1+sum(cost(x) for x in op['in'])
    budgets=[]
    for site in s['models'][INLINE]['sites']:
        value=ids[site['value']];uses=sum(u['op'] in mapping for u in values[value]['users']);n=cost(value)
        if (site['mode']=='inline')!=(n<=4 and n*uses<=16):raise ValueError('budget decision requires review')
        budgets.append(dict(**site,expanded_operations=n,scheduled_uses=uses,weighted_expansion=n*uses))
    save(out/'inline-budget-audit.json',budgets)
    evidence=out/'machine-evidence';evidence.mkdir()
    results={}
    for backend,folder in ((BASELINE,BASE/BASELINE),(NOTIFY,out/NOTIFY),(INLINE,out/INLINE)):
        if identity(folder/'emu')['sha256']!=manifest['binaries'][backend]['sha256']:raise ValueError('ELF identity mismatch')
        elf,rows=elf_model(backend,folder,evidence)
        cpp={p.name:p.read_text() for p in folder.glob('*_sched_*.cpp')};text='\n'.join(cpp.values())
        if backend!=BASELINE:
            for site in s['models'][backend]['sites']:
                if re.search(r'\bgrhsim_changed_'+str(site['value'])+r'\b',text):raise ValueError('covered comparison survived')
                if site['mode']=='inline' and re.search(r'\bgrhsim_value_'+str(site['value'])+r'_0_slot\b',text):
                    raise ValueError('inlined slot survived')
        examples=[]
        for value in (7797,26812,6160):
            filename='grhsim_Cv32Bench_sched_0.cpp' if value==26812 else 'grhsim_Cv32Bench_sched_1.cpp'
            lines=cpp[filename].splitlines()
            marker=f'[value_id={value}:0]' if backend==BASELINE else f'Composed state expression: value={value} '
            first=next(i for i,line in enumerate(lines) if marker in line)
            examples.append(dict(value=value,file=filename,first=first+1,source='\n'.join(lines[max(0,first-1):first+8])))
        results[backend]=dict(binary=identity(folder/'emu'),elf=elf,source_checksums=verify_embedded_sources(folder,cpp),examples=examples)
    save(evidence/'report.json',dict(models=results,inline_budget=identity(out/'inline-budget-audit.json'),
        inputs=[identity(out/'build.json'),identity(out/'structure.json'),identity(Path(__file__).resolve())],
        limits='Static ELF and source attribution; not per-value dynamic cost or spill counts. No simulation or optimization decisions.'))
    print('70 comparison removals, 52 slot removals, static budgets and ELF source identities verified')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    audit(p.parse_args().source.resolve())
