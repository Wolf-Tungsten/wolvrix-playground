"""Audit the generated compile flags, collect frozen input identities and export the TNO0021 times."""
import argparse
import csv
import json
from pathlib import Path
import re
import shlex
import subprocess

from armor_xs_pgo_build import ENGINES, FIR, GENERATOR, GRHSIM, GSIM, LLVM, NEMU, OUT, ROOT, XS, header
from armor_xs_pgo_measure import IMAGES, paired
from grhsim_single_baseline import identity, save
from xiangshan_cv32_ablation_measure import read, signature, verify


def audit_builds():
    manifest = dict(compiler=identity(LLVM/'clang++'), generator=identity(GENERATOR),
        fir=identity(FIR), firmware={n:identity(p) for n,p in IMAGES.items()}, nemu=identity(NEMU),
        versions={k:subprocess.check_output(['git','-C',v,'rev-parse','HEAD'],text=True).strip()
                  for k,v in [('xiangshan',XS),('difftest',XS/'difftest'),('wolvrix',ROOT/'wolvrix'),
                              ('gsim',GENERATOR.parents[2])]},
        models={})
    for engine in ENGINES:
        src=GRHSIM/'model' if engine=='grhsim' else GSIM/'model'
        sources=[identity(p) for p in sorted(src.iterdir()) if p.suffix in ('.cpp','.hpp','.h') or p.name=='Makefile']
        save(OUT/engine/'source-manifest.json',sources)
        model_cpp={p.name for p in src.glob('*.cpp')}
        proof=read(OUT/engine/'verify/result.json')
        records={}
        for mode in ('off','generate','use'):
            dest=OUT/engine/mode
            verify(proof['binaries'][mode])
            prof=OUT/engine/'profile/merged.profdata'
            file_flags={}
            for line in (dest/'commands.log').read_text().splitlines():
                if not line.startswith(str(LLVM/'clang++')+' '):
                    continue
                flags=shlex.split(line)
                if '-c' not in flags:
                    continue
                cpp=[Path(v).name for v in flags if v.endswith('.cpp')]
                if len(cpp)!=1:
                    raise ValueError('unexpected C++ command in '+str(dest))
                if cpp[0] in file_flags:
                    raise ValueError('duplicate compile command for '+cpp[0])
                pgo=[f for f in flags if f.startswith(('-fprofile-use','-fprofile-generate'))]
                want={'off':[],'generate':['-fprofile-generate'],'use':['-fprofile-use='+str(prof)]}[mode]
                if pgo!=want or '-O3' not in flags or '-march=native' not in flags:
                    raise ValueError(f'{engine} {mode}: wrong flags for {cpp[0]}')
                if ('-fno-slp-vectorize' in flags)!=(mode=='generate'):
                    raise ValueError('unexpected SLP policy')
                file_flags[cpp[0]]=pgo
            missing=model_cpp-file_flags.keys()
            if missing or not (file_flags.keys()-model_cpp):
                raise ValueError(f'{engine} {mode}: missing model or harness compiles: {missing}')
            logs=(dest/'compile.log').read_text(errors='replace')
            warnings=[line for line in logs.splitlines() if re.search(r'warning:.*(?:profile|PGO)|LLVM Profile (?:Error|Warning)',line,re.I)]
            sections=subprocess.check_output(['readelf','-SW',dest/'emu'],text=True)
            instrumented='__llvm_prf_cnts' in sections
            if instrumented != (mode=='generate'):
                raise ValueError('unexpected instrumentation in '+str(dest))
            records[mode]=dict(binary=proof['binaries'][mode], model_cpp=len(model_cpp),
                harness_cpp=len(file_flags)-len(model_cpp), instrumented=instrumented,
                profile_warnings=warnings, compile_s=read(dest/'compile.result.json')['elapsed_s'])
        verify(proof['profile'])
        manifest['models'][engine]=dict(records=records, schema=identity(header(engine)),
            source_manifest=identity(OUT/engine/'source-manifest.json'), profile=proof['profile'],
            profile_training_s=read(OUT/engine/'generate/training/run.result.json')['elapsed_s'])
    save(OUT/'build-identity.json',manifest)
    prefix_tool = OUT/'compare-commit-prefix'
    subprocess.run([LLVM/'clang++','-O2','-std=c++20','-I',header('grhsim').parent,
                    ROOT/'scripts/armor_xs_pgo_commit_prefix.cpp','-o',prefix_tool],check=True)
    prefixes = {}
    for workload in IMAGES:
        traces = [OUT/e/'off'/('check-'+workload)/'trace' for e in ENGINES]
        if any(sorted(p.name for p in t.glob('*.bin')) != ['0.bin'] for t in traces):
            raise ValueError('expected one trace chunk per 100k window')
        prefixes[workload] = json.loads(subprocess.check_output(
            [prefix_tool, *(t/'0.bin' for t in traces)],text=True))
    save(OUT/'cross-engine-commit-prefix.json', prefixes)


def export():
    fields=['workload','round','position','engine','pgo','wall_s','host_ms','pc','instr_count',
            'cycle_count','guest_cycles','cpu','numa','sibling_idle_pct']
    table=[]
    aggregate={}
    for label,wl,engines in [('coremark','coremark',ENGINES),
                             ('microbench-grhsim','microbench',('grhsim',)),('microbench-gsim','microbench',('gsim',))]:
        dest=OUT/'timing'/label
        rows=read(dest/'rounds.json')
        summary=read(dest/'summary.json')
        policy=read(dest/'policy.json')
        if policy['workload']!=identity(IMAGES[wl]) or policy['nemu']!=identity(NEMU):
            raise ValueError('input mismatch')
        if len(rows)!=4 or [row['order'] for row in rows]!=policy['orders']:
            raise ValueError('incomplete measurement')
        for e in engines:
            if paired(rows,e+'-off',e+'-use')!=summary[e]:
                raise ValueError('summary differs')
        for row in rows:
            for i,name in enumerate(row['order'],1):
                e,mode=name.split('-')
                sample=row[name]
                proof=read(OUT/e/'verify/result.json')
                if (sample['binary_sha256']!=proof['binaries'][mode]['sha256']
                        or signature(sample)!=proof['workloads'][wl]['signature'] or not sample['locality_pass']
                        or sample['cpu']!=96 or sample['numa_node']!=1 or sample['max_threads']!=1
                        or sample['diagnostic']):
                    raise ValueError('invalid timed sample: '+name)
                table.append(dict(workload=wl,round=row['round'],position=i,engine=e,pgo=mode,
                    wall_s=f"{sample['external_wall_s']:.6f}",host_ms=sample['host_ms'],pc=sample['pc'],
                    instr_count=sample['instr_count'],cycle_count=sample['cycle_count'],guest_cycles=sample['guest_cycles'],
                    cpu=96,numa=1,sibling_idle_pct=f"{sample['sibling_idle']['288']:.3f}"))
        aggregate[label]=summary
    csv_path=ROOT/'pdocs/armor_grhsim/data/TNO0021_xiangshan_pgo_times.csv'
    with csv_path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n')
        writer.writeheader()
        writer.writerows(table)
    save(OUT/'summary.json',aggregate)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('audit','export'))
    mode=parser.parse_args().action
    (audit_builds if mode=='audit' else export)()
