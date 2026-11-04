#!/usr/bin/env python3
"""Regenerate the exact frozen RTL with read-only activity-stage exports."""
import argparse
import json
from pathlib import Path
import resource
import shutil

from decode_table_csr_only import configuration
from grhsim_single_baseline import Baseline, ROOT, identity, save


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--variant',choices=['C','E'],required=True)
    p.add_argument('--tools',type=Path,default=ROOT/'build/grhsim32-tools')
    p.add_argument('--source-order',type=Path)
    p.add_argument('--expect-identical',action='store_true')
    p.add_argument('--resume-pre',action='store_true',help='Research only; resume from pre-reg-to-mem JSON')
    p.add_argument('--capture-post-reg-to-mem',action='store_true',
                   help='Research only; run through reg-to-mem and save the legal post-pass design snapshot')
    p.add_argument('--resume-post-reg-to-mem',type=Path,
                   help='Research only; resume from a post-reg-to-mem design snapshot')
    p.add_argument('--capture-source-order',action='store_true',
                   help='Research only; stop after activity-schedule and retain source-order.keys.txt')
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    if a.capture_post_reg_to_mem and a.resume_post_reg_to_mem:
        raise ValueError('--capture-post-reg-to-mem cannot use --resume-post-reg-to-mem')
    if a.capture_source_order and not a.resume_post_reg_to_mem:
        raise ValueError('--capture-source-order requires --resume-post-reg-to-mem')
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    original=ROOT/'build/xs/decode_table_20261103_v3/B'
    reference=ROOT/('build/xs/decode_table_tuned_20261103_v1/C' if a.variant=='C' else 'build/xs/decode_table_csr_only_20261104_v1/E')
    for name in ('rtl_manifest.json','difftest_generated_manifest.json'):
        for row in json.loads((original/name).read_text()):
            if identity(row['path'])!=row:raise ValueError('frozen RTL/harness changed')
    tools=out/'tools-frozen'
    shutil.copytree(a.tools/'python',tools/'python')
    shutil.copy2(a.tools/'wolvrix/libwolvrix-lib.so',tools/'libwolvrix-lib.so')
    save(tools/'identity.json',[identity(f) for f in sorted(tools.rglob('*')) if f.is_file()])
    runner=Baseline(configuration(out,tools));runner.snapshot()
    (out/'rtl').symlink_to(original/'rtl',target_is_directory=True)
    (out/'chisel-home').mkdir()
    (out/'chisel-home/build').symlink_to(original/'chisel-home/build',target_is_directory=True)
    # Resume and capture both use the already frozen file list.  The snapshot
    # contains the elaborated design; input.f/read_args are still required by
    # the Python frontend's command contract even when read_sv is skipped.
    for name in ('input.f','read_args.txt'):
        shutil.copy2(reference/name,out/name)
    runner.env['WOLVRIX_ACTIVITY_STAGE_TRACE']=str(out/'stages')
    runner.env['WOLVRIX_FOLD_CONSTANT_DECODE']=str(int(a.variant=='C'))
    if a.source_order:
        runner.env['WOLVRIX_RESEARCH_SOURCE_ORDER']=str(a.source_order.resolve())
    runner.env['WOLVRIX_GRHSIM_STATE_READ_LOCALITY_STATS']='1'
    runner.env['WOLVRIX_GRHSIM_MATERIALIZED_SCALAR_READ_LOCALITY_STATS']='1'
    run_env=dict(runner.env,PYTHONPATH=str(tools/'python'),LD_LIBRARY_PATH=str(tools))
    if a.resume_pre:
        # The frozen pre-graph was independently reproduced from RTL. Resume
        # remains subject to the exact C++ identity gate for a self replay.
        (out/'pre_reg_to_mem.json').symlink_to(reference/'pre_reg_to_mem.json')
        run_env.update({
            'WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON':'1',
            'WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON':'0',
            'WOLVRIX_XS_GRHSIM_PRE_REG_TO_MEM_JSON':str(out/'pre_reg_to_mem.json'),
            'WOLVRIX_XS_GRHSIM_POST_STATS_JSON':str(out/'post_stats.json'),
        })
    if a.capture_post_reg_to_mem:
        # This is the legal replay boundary: stats is written immediately
        # after reg-to-mem, before activity-schedule can clone or group ops.
        # Do not combine capture with a source-order request.
        if a.source_order:
            raise ValueError('--capture-post-reg-to-mem cannot use --source-order')
        run_env.update({
            'WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON':'0',
            'WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON':'1' if a.resume_pre else '0',
            'WOLVRIX_XS_GRHSIM_ENABLE_STATS':'1',
            'WOLVRIX_XS_GRHSIM_STOP_AFTER_PRE_SCHED':'1',
            'WOLVRIX_XS_GRHSIM_POST_STATS_JSON':str(out/'post_reg_to_mem.json'),
        })
        import sys
        runner.run([sys.executable,ROOT/'scripts/wolvrix_xs_grhsim.py',out/'input.f','SimTop',
            out/'model',out/'graph.json',out/'read_args.txt','info','--waveform','off','--perf','off'],'capture-post',run_env)
        if not (out/'post_reg_to_mem.json').is_file():
            raise ValueError('post-reg-to-mem snapshot was not written')
        save(out/'capture_gate.json',dict(variant=a.variant, snapshot=identity(out/'post_reg_to_mem.json'),
                                          boundary='after-reg-to-mem-before-activity-schedule'))
        print('PASS captured legal post-reg-to-mem snapshot',flush=True)
        return
    if a.resume_post_reg_to_mem:
        snapshot=a.resume_post_reg_to_mem.resolve()
        if not snapshot.is_file():raise ValueError(f'post-reg-to-mem snapshot not found: {snapshot}')
        run_env.update({
            'WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON':'1',
            'WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON':'0',
            'WOLVRIX_XS_GRHSIM_POST_STATS_JSON':str(snapshot),
        })
        if a.capture_source_order:
            run_env['WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE']='1'
        import sys
        runner.run([sys.executable,ROOT/'scripts/wolvrix_xs_grhsim.py',out/'input.f','SimTop',
            out/'model',out/'graph.json',out/'read_args.txt','info','--waveform','off','--perf','off'],'emit-post',run_env)
    elif a.resume_pre:
        import sys
        runner.run([sys.executable,ROOT/'scripts/wolvrix_xs_grhsim.py',out/'input.f','SimTop',
            out/'model',out/'graph.json',out/'read_args.txt','info','--waveform','off','--perf','off'],'emit',run_env)
    else:
        runner.emit()
    if a.capture_source_order:
        keys=out/'stages/source-order.keys.txt'
        if not keys.is_file():
            raise ValueError('activity-schedule source order was not written')
        save(out/'source_order_gate.json',dict(snapshot=identity(a.resume_post_reg_to_mem),
                                              source_order=identity(keys),
                                              boundary='post-reg-to-mem-before-cpp-emission'))
        print('PASS captured source order at legal post-reg-to-mem boundary',flush=True)
        return
    if a.capture_post_reg_to_mem:
        return
    comparisons=[]
    reference_files={old.name:old for old in (reference/'model').iterdir() if old.suffix in ('.cpp','.hpp')}
    generated_files={new.name:new for new in (out/'model').iterdir() if new.suffix in ('.cpp','.hpp')}
    for name in sorted(reference_files.keys() & generated_files.keys()):
        old=reference_files[name];new=generated_files[name]
        left=identity(old);right=identity(new)
        comparisons.append(dict(name=name,reference=left,diagnostic=right,equal=left['sha256']==right['sha256']))
    missing_reference=sorted(reference_files.keys()-generated_files.keys())
    extra_generated=sorted(generated_files.keys()-reference_files.keys())
    graph=[identity(root/'pre_reg_to_mem.json') for root in (reference,out)] if a.resume_pre else None
    summary=dict(variant=a.variant,reference=str(reference),graph=graph,
                 graph_equal=(graph[0]['sha256']==graph[1]['sha256'] if graph else None),files=comparisons,
                 all_cpp_headers_identical=all(r['equal'] for r in comparisons) and not missing_reference and not extra_generated,
                 model_file_set_equal=not missing_reference and not extra_generated,
                 missing_reference=missing_reference,extra_generated=extra_generated,
                 compared_files=len(comparisons),
                 replay_snapshot=identity(a.resume_post_reg_to_mem) if a.resume_post_reg_to_mem else None)
    save(out/'export_gate.json',summary)
    if a.resume_pre and (not summary['graph_equal'] or ((not a.source_order or a.expect_identical) and not summary['all_cpp_headers_identical'])):
        raise ValueError('diagnostic generation differs from frozen reference; no causal replay allowed')
    if a.resume_post_reg_to_mem and (not a.source_order or a.expect_identical) and not summary['all_cpp_headers_identical']:
        raise ValueError('post-reg-to-mem replay differs from frozen reference; no causal replay allowed')
    if a.source_order:
        gate=out/'stages/source-order-replay.txt'
        if not gate.exists():raise ValueError('requested replay was not applied')
        save(out/'replay.json',dict(reference=identity(a.source_order),gate=gate.read_text(),self_replay=a.expect_identical))
    print('PASS generation identity and requested replay gates',flush=True)


if __name__=='__main__':main()
