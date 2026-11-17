#!/usr/bin/env python3
"""Offline source, ELF and already-recorded counter evidence; no simulator runs."""
import argparse
import json
from pathlib import Path
import re
from grhsim_single_baseline import identity,save
from xiangshan_cv32_structure import cpp,machine
from xiangshan_packed_storage_analysis import group_text
from xiangshan_packed_storage_compare import check_model
from cv32e40p_shared_cycle_refinement_analysis import prove_count_sources,dynamic_model,source_model

def read(p):return json.loads(Path(p).read_text())

def cv32(out):
    rows={};models={};proofs={};inputs=[identity(out/'build.json'),identity(Path(__file__).resolve())]
    for label,name in [('full','grhsim_ownership_fixed'),('candidate','grhsim_shared_connected')]:
        folder=out/name;counts=out.parent/('shared-connected-'+label+'-counts-v1')
        data,proof=prove_count_sources(folder,counts);proofs[label]=proof;models[label]=source_model(folder)
        rows[label]=dict(summary=dynamic_model(data['coremark'],models[label]['group_phases']),raw=data)
        inputs += [identity(counts/'counts.json'),identity(counts/'inputs.json')]
    a,b=[rows[k]['raw']['coremark'] for k in ('full','candidate')]
    assert a['cycles']==b['cycles'] and a['trace']['sha256']==b['trace']['sha256']
    compared=sorted(k for k in a['counts'].keys()&b['counts'].keys() if k.startswith(('cmp:','chg:','mux_root:','mux_true:','mux_false:','mux_cache_','decode_')))
    changed={k:dict(before=a['counts'][k],after=b['counts'][k]) for k in compared if a['counts'][k]!=b['counts'][k]}
    preserved={}
    for key,fields in [('views',('value','source','mode')),('composed',('value','ops','mode'))]:
        old=sorted(tuple(v[k] for k in fields) for v in models['full'][key])
        new=sorted(tuple(v[k] for k in fields) for v in models['candidate'][key])
        preserved[key]=dict(before=len(old),after=len(new),identical=old==new)
    save(out/'count-analysis.json',dict(provenance=proofs,models={k:v['summary'] for k,v in rows.items()},preserved=preserved,
        common_behavior_counters=len(compared),changed_behavior_counters=changed,inputs=inputs,
        note='Counts are diagnostics, not timing. Different group IDs are not directly comparable. No data is fed to generation.'))
    print('CV32 counter/source evidence complete',flush=True)

def xs_source(out):
    destination=out/'offline-structure';destination.mkdir(exist_ok=True)
    model=out/'candidate'
    result=dict(cpp=cpp(model/'model'),inputs=[identity(model/'model-sources.json'),identity(Path(__file__).resolve())])
    save(destination/'candidate-cpp.json',result);print('XS C++ complete',flush=True)
    bank_source,bank_line,bank=group_text(out/'full/model',93956)
    ops=set(re.findall(r'// op (\S+) \[kConcat\]',bank));assert len(ops)==64
    found={}
    for p in sorted((model/'model').glob('*_sched_*.cpp')):
        group=None
        with p.open() as stream:
            for line_no,line in enumerate(stream,1):
                m=re.search(r'// Supernode (\d+):',line)
                if m:group=int(m[1])
                m=re.search(r'// op (\S+) \[kConcat\]',line)
                if m and m[1] in ops:
                    assert m[1] not in found
                    found[m[1]]=dict(group=group,file=p.name,line=line_no)
    result['ftq']=dict(original_group=93956,operations=len(ops),matched=len(found),groups=sorted({v['group'] for v in found.values()}),
        rows=found,source=identity(bank_source),line=bank_line,
        note='Exact original concat op symbols. Group separation is structural, not a dynamic execution count.')
    save(destination/'candidate-cpp.json',result)
    return result

def xs(out):
    model=out/'candidate';check_model(model)
    destination=out/'offline-structure'
    path=destination/'candidate-cpp.json'
    if path.exists():
        result=read(path)
        assert all(identity(r['path'])==r for r in result['inputs'])
    else:result=xs_source(out)
    result['inputs'].append(identity(model/'binary.json'))
    result['machine']=machine(model/'emu/grhsim-compile/emu')
    save(destination/'candidate.json',result)
    print('XS ELF complete',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('model',choices=('cv32','xs','xs-source'));p.add_argument('--source',type=Path,required=True)
    a=p.parse_args();{'cv32':cv32,'xs':xs,'xs-source':xs_source}[a.model](a.source.resolve())
