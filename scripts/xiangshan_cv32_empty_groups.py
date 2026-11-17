#!/usr/bin/env python3
"""Inspect bodies of simple groups in an existing offline C++ audit."""
import argparse
from pathlib import Path
import json

from grhsim_single_baseline import identity, save


def inspect(source):
    records={}
    for variant in ('before','after'):
        input_file=source/'offline-structure'/f'{variant}-cpp.json'
        audit=json.loads(input_file.read_text())['cpp'];targets={}
        for group in audit['groups']:
            if group['phase']=='compute' and group['non_read_const_assign_ops']==0:
                targets.setdefault(group['file'],{})[group['line']]=group
        empty=[];classified=0
        for name,byline in targets.items():
            group=None;depth=0;active=False;code=[]
            with (source/variant/'model'/name).open() as stream:
                for line_no,line in enumerate(stream,1):
                    if line_no in byline:
                        group=byline[line_no];depth=0;active=False;code=[];continue
                    if group is None:continue
                    text=line.strip()
                    if not active:
                        if text=='{':active=True;depth=1
                        continue
                    if text.startswith('//') or not text:continue
                    depth+=text.count('{')-text.count('}')
                    if depth==0:
                        classified+=1
                        if not code:empty.append(group)
                        group=None;continue
                    if text not in ('{','}'):code.append(text)
        candidates=sum(map(len,targets.values()))
        if classified!=candidates:raise ValueError('unrecognized group body syntax')
        records[variant]=dict(candidates=candidates,classified=classified,
            empty_inner_bodies=len(empty),examples=empty[:32],input=identity(input_file))
    return dict(models=records,script=identity(__file__),
        method='Inspect first standalone inner block of groups listing only read/assign/constant. Empty means no executable statements remain there; flag guard/clear and surrounding activity-word code are outside this block. Assign can perform a lowered memory read; simple does not mean free.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    args=parser.parse_args();source=args.source.resolve()
    result=inspect(source);save(source/'offline-structure/empty-groups.json',result)
    print({v:r['empty_inner_bodies'] for v,r in result['models'].items()})
