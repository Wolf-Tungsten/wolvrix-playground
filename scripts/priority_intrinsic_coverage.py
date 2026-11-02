#!/usr/bin/env python3
"""Inventory PriorityEncoder calls and classify utility coverage without guessing."""
from __future__ import annotations
import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def scan(root: Path):
    rows=[]
    for path in sorted(root.rglob('*.scala')):
        if any(part in {'out','target','build','.git'} for part in path.parts):
            continue
        text=path.read_text(errors='ignore')
        matches=list(re.finditer(r'\bPriorityEncoder\s*\(',text))
        if not matches: continue
        imports=bool(re.search(r'(?m)^\s*import\s+utility\.PriorityEncoder\b',text))
        direct=bool(re.search(r'\bchisel3\.util\.PriorityEncoder\b',text))
        rel=str(path.relative_to(root))
        if imports: kind='xiangshan-utility-covered'
        elif rel.startswith(('rocket-chip/','yunsuan/','openLLC/','difftest/','ChiselIOPMP/')):
            kind='third-party-kept-out-of-utility'
        elif direct: kind='fully-qualified-standard-call'
        else: kind='unclassified-call-site'
        for match in matches:
            line=text.count('\n',0,match.start())+1
            rows.append(dict(file=rel,line=line,kind=kind,utility_import=imports,
                             fully_qualified_standard=direct))
    return rows

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=ROOT/'testcase/xiangshan')
    p.add_argument('--calls',type=Path,help='simulation_primitives.json from a Chisel generation')
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    rows=scan(a.root)
    calls=json.loads(a.calls.read_text()) if a.calls else None
    widths=sorted({x['width'] for x in calls['calls']}) if calls else []
    layout_counts=Counter(x.get('layout', 'unknown') for x in calls['calls']) if calls else Counter()
    decision_counts=Counter(x.get('decision', 'unknown') for x in calls['calls']) if calls else Counter()
    report=dict(version=1,source_root=str(a.root.resolve()),calls=rows,
        summary={k:sum(r['kind']==k for r in rows) for k in sorted({r['kind'] for r in rows})},
        total_call_sites=len(rows),actual_generation=calls,
        actual_widths=widths,
        actual_layout_counts=dict(sorted(layout_counts.items())),
        actual_decision_counts=dict(sorted(decision_counts.items())),
        notes={'covered':'Explicit utility.PriorityEncoder import in XiangShan sources',
               'third_party':'Kept unchanged to avoid adding a reverse utility dependency',
               'semantic_internal':'Fully qualified calls inside utility implementation are intentional'})
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    with a.output.with_suffix('.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['file','line','kind','utility_import','fully_qualified_standard']);w.writeheader();w.writerows(rows)
    print(json.dumps({'total_call_sites':len(rows),'summary':report['summary'],'actual_widths':widths,
                      'actual_layout_counts':report['actual_layout_counts'],
                      'actual_decision_counts':report['actual_decision_counts']},ensure_ascii=False))
if __name__=='__main__': main()
