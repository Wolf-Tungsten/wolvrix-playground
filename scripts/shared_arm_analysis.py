#!/usr/bin/env python3
"""Offline source/ELF evidence for frozen same-arm shared-DAG expansion."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import re

from cv32e40p_compare import ROOT, identity, save
from cv32e40p_current_structure import elf_model
from cv32e40p_current_structure_paths import verify_embedded_sources
from cv32e40p_event_regions_compare import check as cv_check
from shared_arm_compare import XS_BASE, CV_BASE, BASE, CANDIDATE, check_xs
from xiangshan_cv32_structure import machine


def read(path):
    return json.loads(path.read_text())


def source_evidence(old, new, structure, dest):
    rows = []; files = Counter(); groups = Counter(); kinds = Counter()
    for path in sorted(new.glob('*_sched_*.cpp')):
        code = path.read_text().splitlines(); group = None
        oldlines = (old / path.name).read_text().splitlines()
        for index, line in enumerate(code):
            m = re.search(r'// Supernode (\d+):', line)
            if m: group = int(m[1])
            m = re.search(r'Conditional mux shared arm: root=(\d+) arm=(\d+)', line)
            if not m: continue
            root, arm = m[1], int(m[2]); row = structure['candidate']['arms'][root + ':' + str(arm)]
            if not row['added']: continue
            oldline = next(i+1 for i,s in enumerate(oldlines) if f'Conditional mux cone: root={root} ' in s)
            files[path.name] += row['added']; groups[group] += row['added']
            rows.append(dict(root=root, arm=arm, file=path.name, group=group, before_line=oldline,
                             after_line=index+1, **row))
    # All sites remain visible, with examples selected only by static added size.
    examples = []
    for row in sorted(rows, key=lambda r: (-r['added'], int(r['root']), r['arm']))[:6]:
        records = {}
        for label, folder, line in (('before', old, row['before_line']), ('candidate', new, row['after_line'])):
            path = folder / row['file']; lines = path.read_text().splitlines()
            target = dest / f"root-{row['root']}-arm-{row['arm']}-{label}.cpp.txt"
            target.write_text('\n'.join(f'{i+1}: {lines[i]}' for i in range(max(0,line-18),min(len(lines),line+45)))+'\n')
            records[label] = dict(source=identity(path), excerpt=identity(target), line=line)
        examples.append(dict(root=row['root'], arm=row['arm'], added=row['added'], records=records))
    return dict(sites=rows, examples=examples, added_by_file=dict(files), added_by_group=dict(groups),
                limits='Operation membership and source positions are static; excerpts may include neighbouring work.')


def deltas(old, new):
    return {key: dict(before=value, after=new.get(key,0), difference=new.get(key,0)-value,
                     percent=100*(new.get(key,0)/value-1) if value else None)
            for key,value in old.items() if isinstance(value,int)}


def xs(out):
    check_xs(out); dest = out / 'machine-evidence'; dest.mkdir(exist_ok=True)
    binary = out / 'candidate/emu/grhsim-compile/emu'; cached = dest / 'candidate.json'
    if cached.exists():
        current = read(cached); assert current['binary'] == identity(binary)
    else:
        current = machine(binary); save(cached,current)
    old = read(XS_BASE / 'offline-structure/candidate.json')['machine']
    assert old['binary'] == read(out / 'full/binary.json')
    totals = {phase:deltas(old['totals'][phase],current['totals'][phase]) for phase in ('compute','commit','eval')}
    functions = {name:dict(phase=row['phase'],counts=deltas(row['counts'], current['functions'][name]['counts']),
                         before_frame=row['entry_stack_subtractions'],after_frame=current['functions'][name]['entry_stack_subtractions'])
                 for name,row in old['functions'].items() if name in current['functions']}
    source = source_evidence(out/'full/model',out/'candidate/model',read(out/'structure.json'),dest)
    save(out/'machine-analysis.json',dict(status='pass',totals=totals,functions=functions,source=source,
        inputs=[identity(XS_BASE/'offline-structure/candidate.json'),identity(cached),identity(out/'structure.json'),identity(Path(__file__).resolve())],
        limits='Release XS ELF has no DWARF source map. Aggregate static counts are not executed instruction savings; use independent PMU only for total dynamic work.'))
    print('XS source/ELF analysis complete',flush=True)


def cv_counts(out):
    olddir=ROOT/'build/cv32e40p/shared-connected-candidate-counts-v1'
    newdir=ROOT/'build/cv32e40p/shared-arm-counts-v1'
    build=cv_check(out)
    assert read(olddir/'inputs.json')['model']['sha256']==build['binaries'][BASE]['sha256']
    assert read(newdir/'inputs.json')['model']==build['binaries'][CANDIDATE]
    arms=read(out/'structure.json')['candidate']['arms']; reports={}
    for workload in ('smoke','coremark'):
        old=read(olddir/'counts.json')[workload];new=read(newdir/'counts.json')[workload]
        assert old['counts']==new['counts'] and old['cycles']==new['cycles']
        assert old['trace']['sha256']==new['trace']['sha256']
        rows=[]
        for key,arm in arms.items():
            if not arm['added']:continue
            root,side=key.split(':');visits=sum(old['counts']['mux_root:'+root])
            hits=sum(old['counts'][('mux_true:' if side=='0' else 'mux_false:')+root])
            rows.append(dict(root=root,arm=int(side),added=arm['added'],visits=visits,hits=hits,
                             skipped_ir_operations=(visits-hits)*arm['added']))
        reports[workload]=dict(counters=len(old['counts']),cycles=old['cycles'],identical=True,arms=rows,
            avoided_ir_ops_per_cycle=sum(r['skipped_ir_operations'] for r in rows)/old['cycles'])
    save(out/'count-gate.json',dict(status='pass',workloads=reports,
        inputs=[identity(d/name) for d in (olddir,newdir) for name in ('counts.json','inputs.json')],
        script=identity(Path(__file__).resolve()),
        limits='IR upper-bound work from frozen branch counters, not retired machine instructions. Counts never feed generation.'))


def cv(out):
    cv_check(out); dest = out/'machine-evidence'; dest.mkdir(exist_ok=True)
    models = {}; mapped = {}
    for label, folder in (('baseline',CV_BASE/BASE),('candidate',out/CANDIDATE)):
        cached = dest/(label+'.json')
        if cached.exists():
            record = read(cached); assert record['binary']==identity(folder/'emu'); models[label]=record;continue
        result, rows = elf_model(label,folder,dest)
        required = {r['model_source']['file'] for r in rows if r['model_source']}
        record = dict(binary=identity(folder/'emu'),elf=result,source_checksums=verify_embedded_sources(folder,required))
        save(cached,record);models[label]=record
    shape = {}
    for label,record in models.items():
        phases = {}
        for f in record['elf']['functions']:
            phase = 'compute' if 'eval_compute_batch_' in f['symbol'] else 'commit' if 'eval_commit_batch_' in f['symbol'] else 'other'
            values = phases.setdefault(phase,Counter())
            values.update({k:v for k,v in f.items() if isinstance(v,int) and k not in ('address',)})
        shape[label]=phases
    totals = {phase:deltas(shape['baseline'][phase],shape['candidate'][phase]) for phase in shape['baseline']}
    source = source_evidence(CV_BASE/BASE,out/CANDIDATE,read(out/'structure.json'),dest)
    # The largest statically extended arm, chosen without timings or profiles.
    chosen=max(source['sites'],key=lambda r:r['added']); root=chosen['root']; side=chosen['arm']; filename=chosen['file']
    records={}
    for label,folder in (('baseline',CV_BASE/BASE),('candidate',out/CANDIDATE)):
        lines=(folder/filename).read_text().splitlines()
        marker=next(i for i,line in enumerate(lines) if f'Conditional mux cone: root={root} ' in line)
        middle=next(i for i in range(marker+2,len(lines)) if lines[i].strip()=='} else {')
        end=next(i for i in range(middle+1,len(lines)) if lines[i].strip()=='}')
        begin,stop=(marker+2,middle) if side==0 else (middle+1,end)
        declarations={m[1]:i+1 for i,line in enumerate(lines) if (m:=re.match(r'        const .+ (grhsim_v[0-9]+_0) = ',line))}
        inside={name:line for name,line in declarations.items() if begin<=line-1<stop}
        rows=json.load(gzip.open(dest/(label+'-instructions.json.gz'),'rt'))
        records[label]=dict(guard_line=marker+2,branch_lines=[begin+1,stop],declarations=declarations,inside=inside,rows=rows)
    moved=records['candidate']['inside'].keys()-records['baseline']['inside'].keys(); locals_evidence=[]
    for name in sorted(moved):
        if name not in records['baseline']['declarations']:continue
        item=dict(local=name)
        for label,record in records.items():
            line=record['declarations'][name]
            addresses=[r['address'] for r in record['rows'] if r['model_source'] and r['model_source']['file']==filename and r['model_source']['line']==line]
            item[label]=dict(line=line,mapped_instructions=len(addresses),addresses=[hex(a) for a in addresses])
        locals_evidence.append(item)
    guards={}
    for label,record in records.items():
        branches=[r for r in record['rows'] if r['model_source'] and r['model_source']['file']==filename and
                  r['model_source']['line']==record['guard_line'] and r['mnemonic'].startswith('j')]
        if len(branches)==1:
            branch=branches[0];target=re.match(r'0x([0-9a-f]+)',branch['operands'])
            if target and int(target[1],16)>branch['address']:
                lo,hi=branch['address'],int(target[1],16)
                mapped=[int(a,16) for item in locals_evidence for a in item[label]['addresses']]
                guards[label]=dict(branch=hex(lo),mnemonic=branch['mnemonic'],target=hex(hi),
                    mapped_local_instructions=len(mapped),inside_address_interval=sum(lo<a<hi for a in mapped))
    save(out/'local-movement-evidence.json',dict(root=root,arm=side,file=filename,locals=locals_evidence,
        address_intervals=guards,guard_lines={k:r['guard_line'] for k,r in records.items()},
        limits='DWARF attribution can combine operations or move code. Function contains indirect jumps; no complete CFG dominance or exact dynamic saving is claimed.'))
    save(out/'machine-analysis.json',dict(status='pass',models=models,totals=totals,source=source,
        inputs=[identity(out/'build.json'),identity(out/'structure.json'),identity(Path(__file__).resolve())],
        limits='CV32 DWARF checksum verified. Static instruction counts and source mappings do not determine dynamic savings; compiler can further move/simplify expressions.'))
    print('CV32 source/ELF analysis complete',flush=True)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('model',choices=('xs','cv','cv-counts'));p.add_argument('--source',type=Path,required=True)
    args=p.parse_args();{'xs':xs,'cv':cv,'cv-counts':cv_counts}[args.model](args.source.resolve())
