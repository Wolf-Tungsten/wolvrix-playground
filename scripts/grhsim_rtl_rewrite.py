#!/usr/bin/env python3
"""Hotspot-gated Slang AST rewrites and finite cycle-trace differential checks.

Only proven local source forms are proposed. A passing differential check is
finite-stimulus evidence, not a formal equivalence proof or a speedup claim.
"""
from __future__ import annotations
import argparse
import difflib
import json
from pathlib import Path
import shlex
import subprocess

from grhsim_source_map import ROOT, identity, save


def overlaps(candidate,span):
    if Path(candidate['file']).resolve()!=Path(span['resolved_file']).resolve(): return False
    start=(candidate['line'],candidate['column']);end=(candidate['end_line'],candidate['end_column'])
    point=(span['line'],span['column'])
    if span.get('end_line') and span.get('end_column'):
        return start < (span['end_line'],span['end_column']) and point < end
    return start<=point<end


def materialize(candidate,rule,filelist,output,source_record):
    source=Path(candidate['file']).resolve(strict=True)
    if identity(source)!=source_record:
        raise ValueError('RTL has changed since the critical-path report')
    data=source.read_bytes();begin,end=candidate['begin'],candidate['end']
    if not 0<=begin<end<=len(data) or data[begin:end]!=candidate['before'].encode():
        raise ValueError('AST source offsets do not match the RTL snapshot')
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    original=output/'original'/source.name;rewritten=output/'rewritten'/source.name
    original.parent.mkdir();rewritten.parent.mkdir()
    original.write_bytes(data)
    revised=data[:begin]+candidate['after'].encode()+data[end:]
    rewritten.write_bytes(revised)
    files=[Path(line.strip()).resolve() for line in Path(filelist).read_text().splitlines()
           if line.strip() and not line.strip().startswith('//')]
    if files.count(source)!=1:
        raise ValueError('rewritten source must occur exactly once in the plain source filelist')
    source_files=[identity(f) for f in files]
    for name,path in [('baseline',original),('candidate',rewritten)]:
        (output/(name+'.f')).write_text(''.join(str(path if f==source else f)+'\n' for f in files))
    diff=''.join(difflib.unified_diff(data.decode().splitlines(True),revised.decode().splitlines(True),
                                    fromfile=str(source),tofile=str(rewritten)))
    (output/'change.patch').write_text(diff)
    manifest=dict(schema_version=1,status='candidate',engine='slang-elaborated-ast',rule=rule,
        equivalence_goal='strict-cycle',verification='not-run',performance='not-measured',
        candidate=candidate,original=identity(original),rewritten=identity(rewritten),
        baseline_filelist=identity(output/'baseline.f'),candidate_filelist=identity(output/'candidate.f'),
        source_snapshot=source_record,
        source_files=source_files,include_directory=str(source.parent),
        structural_diff=dict(edits=1,removed='full-width range select',preserved='assignment process, width, signedness and four-state type'),
        semantics='unsigned full-width static slice on a named packed value; identical width/signedness/four-state type; continuous RHS only',
        configuration_scope='all elaborated occurrences in the supplied top/filelist/options; not every possible parameter configuration')
    save(output/'manifest.json',manifest)
    return manifest


def propose(args):
    mapping=json.loads(args.source_map.read_text());report=json.loads(args.report.read_text())
    if report.get('status')!='pass': raise ValueError('critical-path report is incomplete')
    output=args.output.resolve()
    if output.exists(): raise ValueError('candidate output already exists')
    work=output.with_name(output.name+'-discovery');work.mkdir(parents=True,exist_ok=False)
    read_args=shlex.split(args.read_args.read_text()) if args.read_args else []
    command=[str(args.native_tool.resolve()),str(work/'ast.json'),args.top,'-f',str(args.filelist.resolve()),*read_args]
    with (work/'ast.log').open('w') as log:
        subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    ast=json.loads((work/'ast.json').read_text())
    hot=report.get('source_associations',[])
    eligible=[]
    for candidate in ast['candidates']:
        spans=[s for s in hot if s.get('associated_batch_ns',0)>0 and overlaps(candidate,s)]
        if spans:
            candidate['source_span_ids']=sorted({s['source_span_id'] for s in spans})
            eligible.append((max(s['associated_batch_ns'] for s in spans),candidate))
    if not eligible:
        output.mkdir()
        save(output/'manifest.json',dict(schema_version=1,status='no-candidate',rule=ast['rule'],
            ast_candidates=len(ast['candidates']),reason='no supported AST rewrite intersects a measured RTL hotspot',
            discovery_command=command,report=identity(args.report)))
        return
    _,candidate=sorted(eligible,key=lambda x:(-x[0],x[1]['file'],x[1]['begin']))[0]
    records=[r for r in mapping['source_files'].values() if Path(r['path']).resolve()==Path(candidate['file']).resolve()]
    if len(records)!=1: raise ValueError('candidate source lacks a unique report snapshot')
    result=materialize(candidate,ast['rule'],args.filelist,output,records[0])
    result.update(discovery_command=command,report=identity(args.report),native_tool=identity(args.native_tool))
    save(output/'manifest.json',result)


def json_line(stream,label):
    line=stream.readline()
    if not line: raise ValueError(f'missing {label} record')
    return json.loads(line,parse_constant=lambda s:(_ for _ in ()).throw(ValueError('non-finite JSON value')))


def compare_traces(baseline,candidate,stimulus,cycles):
    with Path(stimulus).open() as inputs,Path(baseline).open() as a,Path(candidate).open() as b:
        ah,bh=json_line(a,'baseline header'),json_line(b,'candidate header')
        digest=identity(stimulus)['sha256']
        if ah!=bh or ah.get('schema_version')!=1 or ah.get('stimulus_sha256')!=digest:
            raise ValueError('trace headers or fixed stimuli differ')
        if not ah.get('observables') or not isinstance(ah['observables'],list):
            raise ValueError('no declared observables in cycle trace')
        if any(not isinstance(path,str) or path.split('.')[0] not in ('outputs','state','commits') for path in ah['observables']):
            raise ValueError('invalid observable declaration')
        for cycle in range(cycles):
            expected=json_line(inputs,'stimulus')
            left,right=json_line(a,'baseline'),json_line(b,'candidate')
            if set(left)!=set(right) or not {'cycle','inputs','outputs','state','commits'}<=set(left):
                raise ValueError('incomplete cycle observation')
            if type(left['cycle']) is not int or type(right['cycle']) is not int or left['cycle']!=cycle or right['cycle']!=cycle:
                raise ValueError(f'missing/reordered cycle {cycle}')
            if expected.get('cycle')!=cycle or expected.get('inputs')!=left['inputs'] or left['inputs']!=right['inputs']:
                raise ValueError(f'input trajectory mismatch at cycle {cycle}')
            if not isinstance(left['outputs'],dict) or not left['outputs'] or not isinstance(left['state'],dict) or not isinstance(left['commits'],list):
                raise ValueError('invalid observable payload')
            for path in ah['observables']:
                value=left
                for key in path.split('.'):
                    if not isinstance(value,dict) or key not in value:raise ValueError('declared observable is absent: '+path)
                    value=value[key]
            if left!=right:
                raise ValueError(f'cycle mismatch at {cycle}')
        if inputs.read().strip() or a.read().strip() or b.read().strip():
            raise ValueError('unexpected extra stimulus/trace cycles')
    return dict(status='pass',cycles=cycles,stimulus_sha256=digest,observables=ah['observables'])


def verify(args):
    manifest=json.loads(args.manifest.read_text())
    if manifest.get('status')!='candidate': raise ValueError('no rewrite candidate')
    commands=json.loads(args.commands.read_text())
    if commands.get('baseline')!=commands.get('candidate'):
        raise ValueError('baseline and candidate must use the same command template and compile options')
    for key in ('original','rewritten','baseline_filelist','candidate_filelist'):
        if identity(manifest[key]['path'])!=manifest[key]: raise ValueError('candidate input changed')
    for record in manifest.get('source_files',[]):
        if identity(record['path'])!=record:raise ValueError('RTL filelist dependency changed')
    if len(args.stimulus)<2 or len({identity(p)['sha256'] for p in args.stimulus})!=len(args.stimulus):
        raise ValueError('provide at least two distinct fixed input trajectories')
    args.output.mkdir(parents=True,exist_ok=False)
    records=[];status='pass'
    try:
        for index,stimulus in enumerate(args.stimulus):
            paths={}
            for variant,rtl_key,file_key in [('baseline','original','baseline_filelist'),('candidate','rewritten','candidate_filelist')]:
                template=commands[variant]
                if not isinstance(template,list) or not all(isinstance(x,str) for x in template): raise ValueError('command must be an argv array')
                joined=' '.join(template)
                if '{trace}' not in joined or '{stimulus}' not in joined or not ('{rtl}' in joined or '{filelist}' in joined):
                    raise ValueError('command must consume the RTL, fixed stimulus and trace destination')
                trace=args.output/f'{index}-{variant}.jsonl';paths[variant]=trace
                values=dict(rtl=manifest[rtl_key]['path'],filelist=manifest[file_key]['path'],
                    trace=str(trace.resolve()),stimulus=str(stimulus.resolve()),cycles=str(args.cycles),window=str(index),variant=variant,
                    include_directory=manifest['include_directory'])
                command=[token.format_map(values) for token in template]
                with (args.output/f'{index}-{variant}.log').open('w') as log:
                    subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=args.timeout,check=True)
                records.append(dict(variant=variant,window=index,command=command,trace=identity(trace)))
            check=compare_traces(paths['baseline'],paths['candidate'],stimulus,args.cycles)
            records.append(dict(window=index,**check))
        for key in ('original','rewritten','baseline_filelist','candidate_filelist'):
            if identity(manifest[key]['path'])!=manifest[key]:raise ValueError('verification changed a candidate input')
        for record in manifest.get('source_files',[]):
            if identity(record['path'])!=record:raise ValueError('verification changed an RTL dependency')
    except (ValueError,OSError,subprocess.SubprocessError) as error:
        status='fail';records.append(dict(error=str(error)))
    save(args.output/'verification.json',dict(schema_version=1,status=status,mode='strict-cycle-differential',
        scope='finite fixed input trajectories; not formal equivalence',cycles_per_window=args.cycles,records=records))
    manifest['verification']=identity(args.output/'verification.json')
    manifest['verification_status']=status
    save(args.manifest,manifest)
    if status!='pass': raise SystemExit(1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest='action',required=True)
    p=subs.add_parser('propose');p.set_defaults(function=propose)
    p.add_argument('--report',type=Path,required=True);p.add_argument('--source-map',type=Path,required=True)
    p.add_argument('--filelist',type=Path,required=True);p.add_argument('--top',required=True)
    p.add_argument('--read-args',type=Path);p.add_argument('--native-tool',type=Path,default=ROOT/'build/grhsim32-tools/bin/grhsim32_rtl_rewrite')
    p.add_argument('--output',type=Path,required=True)
    p=subs.add_parser('verify');p.set_defaults(function=verify)
    p.add_argument('--manifest',type=Path,required=True);p.add_argument('--commands',type=Path,required=True)
    p.add_argument('--stimulus',type=Path,action='append',required=True)
    p.add_argument('--cycles',type=int,default=100000);p.add_argument('--timeout',type=float,default=3600)
    p.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if getattr(args,'cycles',1)<=0: parser.error('cycles must be positive')
    args.function(args)


if __name__=='__main__':main()
