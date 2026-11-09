#!/usr/bin/env python3
"""Build fresh full-S3 hardware and locally qualified multiply behavior variants."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import subprocess
from grhsim_single_baseline import Baseline, ROOT, identity, save
from simulation_model_modes import selected_models


def reuse_rtl(work, source):
    """Reuse immutable RTL only when all XiangShan generation inputs match."""
    prior=json.loads((source/'configuration.json').read_text())
    current=json.loads((work.out/'configuration.json').read_text())
    for key in ('config','guest_cores','sim_primitives','sim_models','behavior_state_lowering',
                'behavior_compute_lowering',
                'rtl_difftest','model_difftest','compile_difftest','runtime_difftest',
                'difftest_relax_intermediate_wires','difftest_config','difftest_packed_delay_regs'):
        if prior[key]!=current[key]:raise ValueError('incompatible reused RTL configuration: '+key)
    for record in json.loads((source/'sources.json').read_text()):
        path=Path(record['path'])
        if path.is_relative_to(ROOT/'testcase/xiangshan') and identity(path)!=record:
            raise ValueError('RTL generation source changed: '+str(path))
    for manifest in ('rtl_manifest.json','difftest_generated_manifest.json'):
        for record in json.loads((source/manifest).read_text()):
            if identity(record['path'])!=record:raise ValueError('reused RTL artifact changed')
    # Hard links are safe for these frozen inputs; later stages only read them.
    for directory in ('rtl/rtl','chisel-home/build'):
        shutil.copytree(source/directory,work.out/directory,copy_function=os.link)
    save(work.out/'rtl_manifest.json',[identity(p) for p in sorted((work.out/'rtl/rtl').glob('*'))
        if p.suffix in ('.sv','.v')])
    save(work.out/'difftest_generated_manifest.json',[identity(p) for p in sorted(work.generated.rglob('*')) if p.is_file()])
    save(work.out/'simulation_models_manifest.json',identity(work.out/'chisel-home/build/simulation_models.json'))
    save(work.out/'reused-rtl.json',dict(source=str(source),
        sources=identity(source/'sources.json'),rtl=identity(source/'rtl_manifest.json'),
        generated=identity(source/'difftest_generated_manifest.json')))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--local-study',type=Path,required=True)
    p.add_argument('--performance',type=Path,required=True)
    p.add_argument('--wrapper-checks',type=Path,required=True)
    p.add_argument('--product-checks',type=Path,required=True)
    p.add_argument('--rtl-from',type=Path,help='reuse verified RTL after a compiler-only correction')
    args=p.parse_args();out=args.output.resolve();local=args.local_study.resolve()
    if not platform.node().startswith('node030'):raise ValueError('node030 required')
    gate=json.loads((args.performance/'gate.json').read_text());selected=gate['eligible']
    if not selected:raise ValueError('no locally qualified model')
    checks=json.loads((args.wrapper_checks/'summary.json').read_text())
    assert {r['kind'] for r in checks if r['pass_']}==set(selected)
    assert json.loads((args.product_checks/'summary.json').read_text())['pass_']
    assert all(r['identical_except_comments_whitespace'] for r in json.loads((local/'original-hardware/summary.json').read_text()))
    mode=','.join(selected);assert 'commit-rat' not in selected_models(mode)
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    os.sched_setaffinity(0,set(range(96,128)));out.mkdir(parents=True,exist_ok=True)
    with (out/'build.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        frozen=out/'tools-frozen'
        if not frozen.exists():
            shutil.copytree(local/'tools-frozen',frozen)
            (frozen/'identity.json').unlink()
            save(frozen/'identity.json',[identity(x) for x in sorted(frozen.rglob('*')) if x.is_file()])
        for record in json.loads((frozen/'identity.json').read_text()):
            assert identity(record['path'])==record
        link=subprocess.check_output(['ldd',str(frozen/'python/wolvrix/_wolvrix.so')],
            env=dict(os.environ,LD_LIBRARY_PATH=str(frozen)),text=True)
        assert str(frozen/'libwolvrix-lib.so') in link
        (out/'frozen-linkage.log').write_text(link)
        save(out/'local-gates.json',dict(performance=identity(args.performance/'gate.json'),
            functional=identity(local/'check-summary.json'),wrapper=identity(args.wrapper_checks/'summary.json'),
            product_boundary=identity(args.product_checks/'summary.json'),
            hardware=identity(local/'original-hardware/summary.json'),selected=selected))
        works={}
        for label,models in [('A','hardware'),('B',mode)]:
            config=argparse.Namespace(output=out/label,tools_dir=frozen,
                compiler='/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++',jobs=16,cpu=96,
                cycles=100000,repeats=8,sim_primitives='none',sim_models=models,behavior_state_lowering='ordinary',
                behavior_compute_lowering='grouped' if label=='B' else 'ordinary',
                rtl_difftest='on',runtime_difftest='on')
            work=Baseline(config);work.env['PYTHONDONTWRITEBYTECODE']='1';works[label]=work
            if (work.out/'sources.json').exists():
                for item in json.loads((work.out/'sources.json').read_text()):
                    if identity(item['path'])!=item:raise ValueError('source changed; use new output: '+item['path'])
            else:work.snapshot()
        assert (out/'A/sources.json').read_bytes()==(out/'B/sources.json').read_bytes()
        for record in json.loads((out/'A/sources.json').read_text()):
            src=Path(record['path']);dest=out/'source-copy'/src.relative_to(ROOT)
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
        for label in 'AB':
            work=works[label]
            if args.rtl_from and not (work.out/'rtl_manifest.json').exists():
                reuse_rtl(work,args.rtl_from.resolve()/label)
            if not (work.out/'rtl_manifest.json').exists():work.rtl()
            report=json.loads((work.out/'chisel-home/build/simulation_models.json').read_text())
            if label=='A':assert report['mode']=='hardware' and not report['models']
            else:
                assert {m['name'] for m in report['models']}==set(selected)
                expected_lowering = 'compute-grouped' if work.behavior_compute_lowering == 'grouped' else 'ordinary'
                assert all(not m['observer_only'] and m['lowering'] == expected_lowering for m in report['models'])
                assert not report['observer_domains']
            save(work.out/'model-selection-gate.json',report)
        for name in ('difftest-state.h',):
            assert identity(works['A'].generated/name)['sha256']==identity(works['B'].generated/name)['sha256']
        def finish(label):
            work=works[label]
            if not (work.out/'model_manifest.json').exists():work.emit()
            if not (work.out/'binary.json').exists():work.compile()
            work.stage('multiply S3 build complete '+label)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=[pool.submit(finish,v) for v in 'AB']
            for r in results:r.result()
        save(out/'build-complete.json',dict(variants={v:identity(w.out/'emu/grhsim-compile/emu') for v,w in works.items()},
            sources=identity(out/'A/sources.json'),tools=identity(frozen/'identity.json'),models=selected))


if __name__=='__main__':main()
