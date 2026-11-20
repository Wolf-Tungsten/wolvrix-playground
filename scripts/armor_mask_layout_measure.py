"""Measure original versus the frozen byte-read candidate once the prospective ELF gate passes."""
import argparse
import platform
from pathlib import Path
import shutil

from armor_mask_layout_compare import ARCHIVE, DEFAULT
from cv32e40p_compare import identity, sample, save, signature, summarize_named
from cv32e40p_event_region_counts import main as region_counts
import xiangshan_cv32_ablation_measure as protocol
from xiangshan_cv32_ablation_measure import measurement_lock, read, verify

LOCK=ARCHIVE/'build/xs/xiangshan-cpu96-measure.lock'
FIRMWARE=ARCHIVE/'testcase/xiangshan/ready-to-run'


def check(out):
    machine=read(out/'machine.json')
    verify(machine['source'])
    if not machine['passed'] or not all(machine['gate'].values()):
        raise ValueError('machine-code gate did not pass')
    for model in machine['models'].values():verify(model['binary'])
    parts=read(out/'cv/B/sections.json')
    verify(parts['binary'])
    if parts['A']!=parts['B']:raise ValueError('zero-hit control changed code or data')


def xs(out, dest):
    source=dest/'xs-inputs'
    source.mkdir(parents=True,exist_ok=False)
    full=ARCHIVE/'build/xs/indexed-snapshot-20261117-v3/candidate'
    candidate=out/'xs/B'
    (source/'full').symlink_to(full,target_is_directory=True)
    (source/'candidate').symlink_to(candidate,target_is_directory=True)
    settings=read(full/'configuration.json')
    settings.update(reduction_mask_layout=2,emitter_snapshot=read(out/'policy.json')['emitter'])
    save(candidate/'configuration.json',settings)
    save(candidate/'model-sources.json',read(candidate/'sources.json')['files'])
    shutil.copy2(out/'policy.json',source/'policy.json')
    save(source/'inputs.json',[identity(out/f) for f in ('policy.json','inputs.json','source-audit.json','machine.json')])
    protocol.VARIANTS=('full','candidate')
    result=protocol.measure(source,dest/'xs',FIRMWARE/'coremark-2-iteration.bin',
        FIRMWARE/'riscv64-nemu-interpreter-so',lock_path=LOCK)
    reference=read(ARCHIVE/'build/xs/indexed-snapshot-20261117-v3/measurement/candidate/runs/round00.json')
    if result['functional_signature']!=protocol.signature(reference):
        raise ValueError('XS signature changed relative to the archived workload')


def cv(out, dest):
    orig=ARCHIVE/'build/cv32e40p/indexed-snapshot-v3'
    target=dest/'cv';target.mkdir(parents=True,exist_ok=False)
    (target/'firmware').symlink_to(orig/'firmware',target_is_directory=True)
    (target/'verification.json').symlink_to(orig/'verification.json')
    (target/'full').symlink_to(orig/'grhsim_indexed_snapshot',target_is_directory=True)
    (target/'candidate').symlink_to(out/'cv/B/model',target_is_directory=True)
    names=('full','candidate')
    binaries={m:identity(target/m/'emu') for m in names}
    if binaries['full']!=read(out/'inputs.json')['cv_binary'] or binaries['candidate']!=read(out/'cv/B/sections.json')['binary']:
        raise ValueError('CV32 binaries differ from the frozen build')
    save(target/'build.json',dict(binaries=binaries,gate=identity(out/'machine.json')))
    with measurement_lock(LOCK):
        policy=dict(variants=names,rounds=8,orders=[list(names if i%2==0 else names[::-1]) for i in range(8)],
                    warmups_per_variant=1,cpu=96,numa=1,aslr=False,threads=1,lock=str(LOCK))
        save(target/'measurement-policy.json',policy)
        traces={}
        for workload in ('smoke','coremark'):
            expected=read(target/'verification.json')['workloads'][workload]['verilator']
            rows={m:sample(target,m,workload,'verify-'+workload,trace=True) for m in names}
            for row in rows.values():
                if signature(row)!=signature(expected) or row['trace']['sha256']!=expected['trace']['sha256'] or row['trace']['bytes']!=row['cycles']*36:
                    raise ValueError('incomplete or different CV32 trace')
            traces[workload]=rows
        save(target/'functional.json',traces)
        harness=ARCHIVE/'build/cv32e40p/run2/inputs/fixture/harness.cpp'
        region_counts(target,target/'diagnostic',8,detailed=True,backend='candidate',harness_path=harness)
        before=ARCHIVE/'build/cv32e40p/indexed-snapshot-counts-v3'
        old_input=read(before/'inputs.json')
        if old_input['model']!=binaries['full']: raise ValueError('counter reference binary mismatch')
        baseline=read(before/'counts.json'); candidate=read(target/'diagnostic/counts.json')
        comparisons={}
        for w,v in candidate.items():
            old=baseline[w]
            if len(old['counts'])!=331 or old['counts']!=v['counts'] or old['cycles']!=v['cycles'] or old['trace']['sha256']!=v['trace']['sha256']:
                raise ValueError('CV32 detailed counters differ')
            comparisons[w]=dict(identical=True,count=len(old['counts']),cycles=old['cycles'])
        save(target/'counts-check.json',dict(workloads=comparisons,A=identity(before/'counts.json'),B=identity(target/'diagnostic/counts.json')))
        warm={m:sample(target,m,'coremark','warmup') for m in names}
        save(target/'warmups.json',warm)
        pairs=[]
        for i,order in enumerate(policy['orders']):
            row=dict(pair=i,order=order)
            for m in order:
                row[m]=sample(target,m,'coremark',f'round{i:02d}')
                if signature(row[m])!=signature(traces['coremark'][m]):raise ValueError('formal signature mismatch')
            pairs.append(row);save(target/'pairs.json',pairs)
            print(f'CV32 pair {i+1}/8',flush=True)
        for v in binaries.values():verify(v)
        save(target/'summary.json',summarize_named(pairs,'candidate','full'))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('design',choices=('xs','cv'));p.add_argument('--out',type=Path,default=DEFAULT)
    a=p.parse_args(); out=a.out.resolve()
    if not platform.node().startswith('node030'):p.error('runs require node030')
    check(out)
    (xs if a.design=='xs' else cv)(out,out.parent/'measurement')
