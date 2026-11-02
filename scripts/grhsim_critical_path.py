#!/usr/bin/env python3
"""Opt-in XiangShan/GrhSIM RTL critical-path analysis of a completed clean build."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

import grhsim32
from grhsim_path_instrument import instrument_wrapper, instrument_eval
from grhsim_source_map import build_source_map, identity, save, verify_package, add_asc_map, add_communication, rows, part_number
from grhsim_path_report import summarize_timeline, reference_labels, summarize_batches, assemble_report, write_html
from repcut_cycle_trace import archive_hashes
from repcut_formal_zero_thp_compare import audit_compute_alignment

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'scripts'


def context(args):
    base=args.build.resolve(strict=True)
    result=json.loads((base/'result.json').read_text())
    configuration=json.loads((base/'configuration.json').read_text())
    if result.get('status')!='pass': raise ValueError('clean build did not finish successfully')
    stage=base/result['retained']
    if not stage.is_relative_to(base) or not (stage/'partitioned.json').is_file():
        raise ValueError('invalid retained stage')
    out=args.output.resolve() if args.output else base/'critical-path'
    if out==base or out==stage or stage.is_relative_to(out):
        raise ValueError('diagnostic output must be separate from production outputs')
    out.mkdir(parents=True,exist_ok=True)
    config_file=out/'configuration.json'
    if config_file.exists() and json.loads(config_file.read_text())!=configuration['config']:
        raise ValueError('existing diagnostic configuration differs; choose a new output directory')
    save(config_file,configuration['config'])
    selected_cpus=args.runtime_cpus
    if not selected_cpus:
        selected_cpus=','.join(map(str,grhsim32.runtime_cpus(sorted(os.sched_getaffinity(0)))))
    ns=SimpleNamespace(config=config_file,output=out,jobs=args.jobs,runtime_cpus=selected_cpus,
        codepages=args.codepages,image=args.image,nemu=args.nemu)
    pipeline=grhsim32.Pipeline(ns)
    pipeline.cxx=configuration['compiler']
    if not Path(pipeline.cxx).is_file():
        raise ValueError('original model compiler is unavailable: '+pipeline.cxx)
    compiler_dir=Path(pipeline.cxx).parent
    pipeline.cc=str(compiler_dir/('clang' if 'clang' in Path(pipeline.cxx).name else 'gcc'))
    for attr,name in (('ar','llvm-ar'),('objcopy','llvm-objcopy')):
        if (compiler_dir/name).is_file(): setattr(pipeline,attr,str(compiler_dir/name))
    pipeline.generated=args.generated.resolve() if args.generated else base/'rtl/generated-src'
    if not (pipeline.generated/'DifftestMacros.svh').is_file():
        pipeline.generated=ROOT/'testcase/xiangshan/build/generated-src'
    if not (pipeline.generated/'DifftestMacros.svh').is_file():
        raise ValueError('generated Difftest interface is missing; supply --generated')
    pipeline.env.update(WOLVI_REPCUT_HOST_SPIN_US='infinite',WOLVI_REPCUT_WORKER_SPIN_US='infinite')
    pipeline.configure_runtime()
    return base,stage,out,configuration,pipeline


def native_tools(pipeline,out):
    pipeline.run_command(['cmake','-S',ROOT/'tools/grhsim32','-B',pipeline.build,
        '-DCMAKE_BUILD_TYPE=Release',f'-DCMAKE_C_COMPILER={pipeline.host_cc}',f'-DCMAKE_CXX_COMPILER={pipeline.host_cxx}'],out/'logs/configure.log')
    pipeline.run_command(['cmake','--build',pipeline.build,'--target','grhsim32_execution_plan','grhsim32_source_asc',
        'grhsim32_codepage','grhsim32_collapse_retry','-j',pipeline.jobs],out/'logs/native-build.log')


def static(args,ctx):
    base,stage,out,configuration,pipeline=ctx
    native=args.native_dir.resolve() if args.native_dir else out/'native'
    if not args.native_dir:
        native_tools(pipeline,out)
        if native.exists(): raise ValueError('native diagnostic output exists; use --native-dir to reuse explicitly')
        native.mkdir()
        env=dict(pipeline.env,GRHSIM_SOURCE_MAP='1')
        pipeline.run_command([pipeline.bin/'grhsim32_execution_plan',stage/'partitioned.json',native,'clock'],native/'run.log',env)
    proof=verify_package(native,stage/'package',min(pipeline.jobs,8))
    save(out/'plan_package_match.json',proof)
    mapping=build_source_map(native,out/'mapping',base/'rtl/rtl')
    add_communication(mapping,native,stage/'package')
    save(out/'mapping/source_map.json',mapping)
    save(out/'mapping/mapping_summary.json',dict(schema_version=1,**mapping['summary'],parts=mapping['parts']))
    save(out/'static_inputs.json',dict(schema_version=1,configuration=configuration,
        partitioned=identity(stage/'partitioned.json'),filelist=identity(base/'input.f'),
        native_tool=identity(pipeline.bin/'grhsim32_execution_plan'),native_directory=str(native),package_match=proof,
        note='--native-dir explicitly reuses an export; batch membership is checked against the retained package'))
    print(json.dumps(dict(stage='static',**mapping['summary'])),flush=True)
    return mapping


def build_probe(stage,dest,pipeline,parts_to_probe):
    if dest.exists():
        record=json.loads((dest/'build.json').read_text())
        if (record['parts']!=parts_to_probe or
            record['source_archive']!=identity(stage/'package/libgrhsim_SimTop.a') or
            record['binary']!=identity(dest/'harness/grhsim-compile/emu') or
            record.get('instrumenter')!=identity(SCRIPTS/'grhsim_path_instrument.py') or
            record.get('trace_header')!=identity(SCRIPTS/'grhsim_path_trace.hpp')):
            raise ValueError('diagnostic build provenance changed; choose a new output directory')
        return record
    package=dest/'package'; package.mkdir(parents=True)
    source=stage/'package'; name='libgrhsim_SimTop.a'
    for path in source.iterdir():
        if path.name!=name: (package/path.name).symlink_to(path)
    target=package/name
    shutil.copy2(source/name,target)
    sources=dest/'sources';sources.mkdir()
    shutil.copy2(SCRIPTS/'grhsim_path_trace.hpp',sources/'grhsim_path_trace.hpp')
    (sources/'grhsim_cp_config.hpp').write_text('#pragma once\nnamespace grhsim_path_trace { inline constexpr unsigned partition_count=32; }\n')
    replacements=[]; sites=[]
    for suffix in ('common','load_0','eval_0','update_0'):
        file=f'wolvi_repcut_grhsim_sim_{suffix}.cpp'
        (sources/file).write_text(instrument_wrapper((source/file).read_text(),suffix))
        replacements.append(file)
    for part in parts_to_probe:
        file=f'grhsim_Gpart_{part}_model_eval.cpp'
        cpp,entries=instrument_eval((source/file).read_text(),source,part)
        (sources/file).write_text(cpp); replacements.append(file);sites.extend(entries)
    def compile_one(file):
        obj=dest/Path(file).with_suffix('.o')
        pipeline.run_command([pipeline.cxx,'-std=c++20','-O3','-march=native','-pthread',
            '-I',source,'-I',sources,'-c',sources/file,'-o',obj],obj.with_suffix('.log'))
        grhsim32.align_object(obj,pipeline.objcopy)
        return obj
    with ThreadPoolExecutor(max_workers=min(pipeline.jobs,len(replacements))) as pool:
        objects=list(pool.map(compile_one,replacements))
    pipeline.run_command([pipeline.ar,'r',target,*objects],dest/'archive.log')
    before,after=archive_hashes(source/name),archive_hashes(target)
    changed=[key for key in before if before[key]!=after.get(key)]
    if list(before)!=list(after) or set(changed)!={obj.name for obj in objects}:
        raise ValueError('unexpected archive member/order change')
    binary=pipeline.harness(dest)
    alignment=audit_compute_alignment(binary,64)
    record=dict(status='pass',diagnostic_only=True,parts=parts_to_probe,sites=sites,
        source_archive=identity(source/name),source_binary=identity(stage/'harness/grhsim-compile/emu'),
        binary=identity(binary),compiler=pipeline.cxx,compiler_flags=['-std=c++20','-O3','-march=native','-pthread'],
        instrumenter=identity(SCRIPTS/'grhsim_path_instrument.py'),trace_header=identity(SCRIPTS/'grhsim_path_trace.hpp'),
        archive_order_preserved=True,unchanged_members=len(before)-len(changed),changed_members=changed,alignment=alignment)
    save(dest/'build.json',record)
    return record


def discover(args,ctx):
    base,stage,out,configuration,pipeline=ctx
    discovery=out/'discovery'; build_probe(stage,discovery,pipeline,[])
    reports=[]; run_records=[]
    request=dict(binary=identity(discovery/'harness/grhsim-compile/emu'),image=identity(args.image),nemu=identity(args.nemu),
        warmup=args.warmup,cycles=args.cycles,repeats=args.repeats,runtime_cpus=pipeline.runtime,
        requested_codepages=args.codepages)
    if args.reuse_discovery:
        if json.loads((out/'discovery_request.json').read_text())!=request:
            raise ValueError('discovery inputs or settings differ')
        run_records=json.loads((out/'discovery_runs.json').read_text())
        if len(run_records)!=args.repeats: raise ValueError('discovery repeat count differs')
        for record in run_records:
            path=Path(record['trace']['path'])
            if identity(path)!=record['trace'] or record['run']['functional']!='pass':
                raise ValueError('discovery trace identity or functional check differs')
            if record['run']['runtime']['worker_cpus']!=pipeline.runtime:
                raise ValueError('discovery CPU configuration differs')
            report=summarize_timeline(path)
            if (report['header']['warmup'],report['header']['cycles'])!=(args.warmup,args.cycles):
                raise ValueError('discovery sampling window differs')
            reports.append(report)
        modes={page_kind(record['run']) for record in run_records}
        if len(modes)!=1:raise ValueError('discovery effective page sizes differ')
        pipeline.args.codepages=modes.pop()
        return reports,run_records
    save(out/'discovery_request.json',request)
    pipeline.env.update(GRHSIM_CP_WARMUP=str(args.warmup),GRHSIM_CP_CYCLES=str(args.cycles),GRHSIM_CP_STRIDE='0')
    for run in range(args.repeats):
        path=discovery/f'run{run}.bin';pipeline.env['GRHSIM_CP_TRACE']=str(path)
        record=pipeline.simulate(discovery,discovery/'runs',f'run{run}',cycles=args.warmup+args.cycles+128)
        effective=page_kind(record)
        if run_records and effective!=page_kind(run_records[0]['run']):
            raise ValueError('discovery effective page sizes changed')
        # Freeze the first run's actual policy for all remaining diagnostics.
        pipeline.args.codepages=effective
        report=summarize_timeline(path);reports.append(report)
        save(discovery/f'run{run}.summary.json',dict(header=report['header'],parts=report['parts']))
        run_records.append(dict(kind='discovery',trace=identity(path),run=record))
    save(out/'discovery_runs.json',run_records)
    return reports,run_records


def page_kind(record):
    page=record.get('codepages')
    if not page or not page['bytes']:raise ValueError('missing code-page audit')
    if page['mode']=='file':return 'file'
    if page['huge_bytes']==page['bytes']:return 'thp'
    if page['huge_bytes']==0:return 'small'
    raise ValueError('partial code huge-page coverage')


def collect(args,ctx,mapping):
    base,stage,out,configuration,pipeline=ctx
    reports,run_records=discover(args,ctx)
    labels=reference_labels(reports)
    weights=default_weights(reports)
    available=sorted({batch['part'] for batch in mapping['batches'].values()})
    selected=sorted(available,key=lambda part:(-weights.get(part,0),part))[:args.part_limit]
    if not selected: raise ValueError('no eval lanes in discovery')
    fine=out/'batch-probe';build_probe(stage,fine,pipeline,selected)
    probes=[]
    pipeline.env.update(GRHSIM_CP_WARMUP=str(args.warmup),GRHSIM_CP_CYCLES=str(args.cycles),GRHSIM_CP_STRIDE=str(args.sample_stride))
    for part in selected:
        pipeline.env['GRHSIM_CP_PART']=str(part)
        for repeat in range(args.repeats):
            name=f'p{part}-r{repeat}';path=fine/f'{name}.bin'
            pipeline.env['GRHSIM_CP_TRACE']=str(path)
            record=pipeline.simulate(fine,fine/'runs',name,cycles=args.warmup+args.cycles+128)
            if page_kind(record)!=page_kind(run_records[0]['run']):
                raise ValueError('batch probe effective page size differs from discovery')
            probe=summarize_batches(path,mapping,labels)
            with (fine/f'{name}.intervals.jsonl').open('w') as stream:
                for interval in probe.pop('intervals'): stream.write(json.dumps(interval)+'\n')
            probes.append(probe)
            save(fine/f'{name}.summary.json',probe)
            run_records.append(dict(kind='batch',trace=identity(path),run=record))
            save(out/'collection_progress.json',dict(status='running',selected_parts=selected,
                completed_probe_runs=len(probes),planned_probe_runs=len(selected)*args.repeats,
                last_completed=name,runs=run_records))
    save(out/'runs.json',dict(status='pass',diagnostic_only=True,selected_parts=selected,
        warmup_cycles=args.warmup,window_cycles=args.cycles,batch_cycle_stride=args.sample_stride,
        repeats=args.repeats,runtime_cpus=pipeline.runtime,aslr_disabled=pipeline.aslr_off,
        numa_node=pipeline.numa,runs=run_records))
    save(out/'collection_progress.json',dict(status='pass',selected_parts=selected,
        completed_probe_runs=len(probes),planned_probe_runs=len(selected)*args.repeats,
        last_completed=name,runs=run_records))
    return reports,probes


def default_weights(reports):
    result={}
    for report in reports:
        for row in report['parts']:
            if row['phase']=='eval': result[row['part']]=result.get(row['part'],0)+row['exclusive_tail_ns']
    return result


def attribute(args,ctx,mapping):
    base,stage,out,_,pipeline=ctx
    runs=json.loads((out/'runs.json').read_text())
    selected=runs['selected_parts']
    source=json.loads((out/'static_inputs.json').read_text())
    native=Path(source.get('native_directory',out/'static' if (out/'static').is_dir() else out/'native'))
    directory=out/'asc';directory.mkdir(exist_ok=True)
    query=directory/'queries.txt'
    with query.open('w') as stream:
        for path in sorted(native.glob('*.sources.csv')):
            part=part_number(path.name.split('.')[0])
            if part not in selected:continue
            for row in rows(path):
                if '\t' in row['op_symbol'] or '\n' in row['op_symbol']:raise ValueError('unsupported operation symbol')
                stream.write(f"{part}\t{row['op_symbol']}\n")
    native_tools(pipeline,out)
    request=dict(raw=identity(base/'memory.json'),assignment=identity(stage/'assignment.txt'),
        query=identity(query),tool=identity(pipeline.bin/'grhsim32_source_asc'))
    csv=directory/'raw_asc.csv';manifest=directory/'inputs.json'
    if manifest.is_file():
        previous=json.loads(manifest.read_text())
        if previous['request']!=request or previous['result']!=identity(csv):
            raise ValueError('ASC attribution inputs changed; choose a new output directory')
    else:
        pipeline.run_command([pipeline.bin/'grhsim32_source_asc',base/'memory.json',stage/'assignment.txt',query,csv],directory/'run.log')
        save(manifest,dict(request=request,result=identity(csv)))
    add_asc_map(mapping,csv,out/'mapping',selected)
    if 'communication' not in mapping:add_communication(mapping,native,stage/'package')
    save(out/'mapping/source_map.json',mapping)
    save(out/'mapping/mapping_summary.json',dict(schema_version=1,**mapping['summary'],parts=mapping['parts']))


def render(ctx,mapping,discoveries=None,probes=None):
    _,_,out,_,_=ctx
    if discoveries is None:
        discoveries=[summarize_timeline(p) for p in sorted((out/'discovery').glob('run*.bin'))]
    if probes is None:
        labels=reference_labels(discoveries)
        probes=[]
        for path in sorted((out/'batch-probe').glob('p*-r*.bin')):
            probe=summarize_batches(path,mapping,labels)
            probe.pop('intervals')
            probes.append(probe)
    result=assemble_report(mapping,discoveries,probes)
    if (out/'runs.json').is_file():
        runs=json.loads((out/'runs.json').read_text())
        modes={page_kind(row['run']) for row in runs['runs']}
        if len(modes)!=1:raise ValueError('cannot report mixed effective page sizes')
        result['runtime']=dict(cpus=runs['runtime_cpus'],codepages=modes.pop(),warmup_cycles=runs['warmup_cycles'],
            window_cycles=runs['window_cycles'],batch_cycle_stride=runs['batch_cycle_stride'],repeats=runs['repeats'])
    save(out/'report.json',result)
    write_html(result,mapping,out/'report.html')
    with (out/'critical_steps.jsonl').open('w') as stream:
        for repeat,report in enumerate(discoveries):
            for row in report['steps']: stream.write(json.dumps(dict(repeat=repeat,**row))+'\n')
    print(json.dumps(dict(status='pass',report=str(out/'report.html'),mapping=result['mapping'],
                         top_parts=result['part_ranking'][:6]),indent=2),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('run','static','profile','report','discover','attribute'),nargs='?',default='run')
    parser.add_argument('--build',type=Path,default=ROOT/'build/xs/grhsim32')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--native-dir',type=Path,help='explicitly reuse a native static export; check batch membership')
    parser.add_argument('--jobs',type=int,default=min(32,os.cpu_count() or 1))
    parser.add_argument('--runtime-cpus')
    parser.add_argument('--generated',type=Path)
    parser.add_argument('--codepages',choices=('auto','thp','small','file'),default='auto')
    parser.add_argument('--image',type=Path,default=ROOT/'testcase/xiangshan/ready-to-run/coremark-2-iteration.bin')
    parser.add_argument('--nemu',type=Path,default=ROOT/'testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so')
    parser.add_argument('--warmup',type=int,default=1000)
    parser.add_argument('--cycles',type=int,default=10000)
    parser.add_argument('--repeats',type=int,default=2)
    parser.add_argument('--part-limit',type=int,default=3)
    parser.add_argument('--sample-stride',type=int,default=64,help='batch sampling every N cycles; phase trace covers every step')
    parser.add_argument('--reuse-discovery',action='store_true',help='explicitly reuse verified discovery traces in this output directory')
    args=parser.parse_args()
    if args.warmup<0 or args.cycles<=0 or args.repeats<2 or not 1<=args.part_limit<=32 or args.sample_stride<=0 or args.jobs<=0:
        parser.error('invalid diagnostic sampling limits')
    grhsim32.enable_generation_cpus()
    ctx=context(args)
    if args.action=='discover':
        discover(args,ctx)
        return
    if args.action in ('run','static'):
        mapping=static(args,ctx)
    else:
        mapping=json.loads((ctx[2]/'mapping/source_map.json').read_text())
        proof=json.loads((ctx[2]/'static_inputs.json').read_text())
        if identity(ctx[1]/'partitioned.json')!=proof['partitioned']:
            raise ValueError('source graph changed since mapping')
    if args.action in ('run','profile'):
        discoveries,probes=collect(args,ctx,mapping)
        attribute(args,ctx,mapping)
        render(ctx,mapping,discoveries,probes)
    elif args.action=='attribute':
        attribute(args,ctx,mapping)
        render(ctx,mapping)
    elif args.action=='report': render(ctx,mapping)


if __name__=='__main__': main()
