#!/usr/bin/env python3
"""Five fixed variants isolate the ownership fix from two packed-storage rules."""
import argparse
import json
from pathlib import Path
import platform
import resource
import shutil
import subprocess

from cv32e40p_compare import ROOT, run
from grhsim_single_baseline import identity, save, clean_environment
from xiangshan_cv32_compare import HISTORICAL, XS, verify_identity
from xiangshan_packed_storage_compare import FULL, NO_SHARED, check_model, source_inventory, source_shape, check_harness_source

REPLAY = ROOT / 'build/xs/packed-array-scope-20261116-v2'
VARIANTS = ('full', 'fixed', 'layout', 'scope', 'no_shared')


def read(path):
    return json.loads(Path(path).read_text())


def prepare(out):
    check_harness_source()
    out.mkdir(parents=True, exist_ok=False)
    shutil.copytree(REPLAY/'snapshot', out/'snapshot')
    shutil.copy2(__file__, out/'snapshot'/Path(__file__).name)
    shutil.copytree(REPLAY/'candidate/native', out/'native')
    (out/'full').symlink_to(FULL, target_is_directory=True)
    (out/'no_shared').symlink_to(NO_SHARED, target_is_directory=True)
    for name in ('fixed', 'layout', 'scope'):
        model = out/name; model.mkdir()
        shutil.copytree(FULL/'chisel-home', model/'chisel-home')
        configuration = read(FULL/'configuration.json')
        configuration.update(variant=name, borrowed_span_ownership_fixed=True,
            state_layout_packed_access=name=='layout', packed_array_local_scope=name=='scope',
            native_library=identity(out/'native/libwolvrix-lib.so'),
            note='Same static algorithms; ownership-corrected control separates lifetime fix from each independent emitter rule.')
        save(model/'configuration.json', configuration)
    save(out/'policy.json', dict(variants=VARIANTS, pairs=3, cpu=96, numa=1, aslr=False,
        threads=1, cycles=100000, smoke_cycles=10000, verification_seeds=[0,1],
        order='full/fixed/layout/scope/no_shared, then reverse, three rounds',
        reason='Before any timing, a dangling users span caused non-reproducible off generation. Add an ownership-fixed control to isolate the correctness repair.',
        generation='Static graph rules frozen before measurement; no feedback, threshold tuning or combinations.',
        source_gate='Layout must preserve all fixed-control computation source; scope must preserve headers and per-group operation order; both are separate.',
        scope_replay=str(REPLAY), idle_admission='Same skip-external-idle policy as prior XS comparisons; affinity/thread/NUMA mandatory.'))
    inputs=[identity(Path(__file__).resolve()), identity(REPLAY/'inputs.json'), identity(out/'policy.json'),
            identity(HISTORICAL/'pre_reg_to_mem.json'), identity(XS/'ready-to-run/coremark-2-iteration.bin'),
            identity(XS/'ready-to-run/riscv64-nemu-interpreter-so')]
    for folder in (out/'snapshot', out/'native'):
        inputs += [identity(p) for p in sorted(folder.rglob('*')) if p.is_file()]
    for name in ('fixed', 'layout', 'scope'):
        inputs.append(identity(out/name/'configuration.json'))
    for model in (FULL, NO_SHARED):
        check_model(model)
        inputs += [identity(model/n) for n in ('binary.json','model-sources.json','configuration.json','logs/compile.command.json')]
        inputs += [read(model/'binary.json')] + read(model/'model-sources.json')
    for name in ('xiangshan_cv32_ablation_measure.py','grhsim_single_compare.py','grhsim_single_baseline.py',
                 'grhsim_numa.py','grhsim_difftrace.py','simulation_model_modes.py','xiangshan_packed_storage_compare.py'):
        inputs.append(identity(ROOT/'scripts'/name))
    save(out/'inputs.json', list({r['path']:r for r in inputs}.values()))
    print('prepared fixed five-variant comparison',flush=True)


def check_inputs(out):
    for record in read(out/'inputs.json'):
        verify_identity(record)


def emit_layout(out):
    assert platform.node().startswith('node030')
    check_inputs(out)
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    env=clean_environment();env.update(NOOP_HOME=str(XS),LC_ALL='C',LD_LIBRARY_PATH=str(out/'native'),
        WOLVRIX_GRHSIM_STORAGE_REF_ALIASES='0',WOLVRIX_GRHSIM_STATE_LAYOUT_PACKED_ACCESS='1',
        WOLVRIX_GRHSIM_PACKED_ARRAY_LOCAL_SCOPE='0')
    run([out/'native/emit-off',HISTORICAL/'pre_reg_to_mem.json',out/'layout/model'],out/'layout/logs/emit.log',env=env)
    check_inputs(out)


def operations(folder):
    import re
    return {p.name: re.findall(r'// (?:Supernode \d+:|op [^\n]+)',p.read_text())
            for p in folder.glob('*_sched_*.cpp')}


def build(out):
    assert platform.node().startswith('node030')
    check_inputs(out);check_harness_source()
    for label in ('off','guard'):
        assert '[replay] emit done' in (REPLAY/'candidate/logs'/f'{label}-emit.log').read_text()
    shutil.copytree(REPLAY/'off-source',out/'fixed/model')
    shutil.copytree(REPLAY/'candidate/model',out/'scope/model')
    fixed=source_shape(source_inventory(out/'fixed/model'))
    old=source_shape(read(FULL/'model-sources.json'))
    structure=dict(ownership_fix_changed_files=[n for n in old if old[n]!=fixed.get(n)],models={})
    for name in ('layout','scope'):
        current=source_shape(source_inventory(out/name/'model'))
        changed=[n for n in fixed if current.get(n)!=fixed[n]]
        assert set(current)==set(fixed)
        if name=='layout':
            assert not any(n.endswith('.cpp') for n in changed),changed
        else:
            assert not any(n.endswith('.hpp') for n in changed),changed
            assert operations(out/name/'model')==operations(out/'fixed/model'),'scope changed op/group order'
        structure['models'][name]=dict(changed_files=changed,
            scope_sites=sum(p.read_text().count('// Scoped packed array:') for p in (out/name/'model').glob('*_sched_*.cpp')))
    save(out/'structure.json',structure)
    records=[identity(out/'structure.json')]
    for name in ('fixed','layout','scope'):
        model=out/name
        sources=source_inventory(model/'model');save(model/'model-sources.json',sources)
        command=[arg.replace(str(FULL),str(model)) for arg in read(FULL/'logs/compile.command.json')['argv']]
        env=clean_environment();env.update(NOOP_HOME=str(XS),LC_ALL='C')
        run(command,model/'logs/compile.log',env=env)
        save(model/'binary.json',identity(model/'emu/grhsim-compile/emu'))
        records += sources+[identity(model/'model-sources.json'),identity(model/'binary.json'),read(model/'binary.json')]
        records += [identity(p) for p in sorted((model/'logs').glob('*')) if p.is_file()]
    records += [identity(REPLAY/'candidate/logs'/f'{label}-emit.log') for label in ('off','guard')]
    save(out/'build.json',dict(inputs=identity(out/'inputs.json'),files=records,
        binaries={n:read(out/n/'binary.json') for n in VARIANTS}))
    check(out);print('all three corrected models built',flush=True)


def check(out):
    check_inputs(out)
    manifest=read(out/'build.json');verify_identity(manifest['inputs'])
    for record in manifest['files']:verify_identity(record)
    for name in VARIANTS:check_model(out/name)


def measure(out):
    import xiangshan_cv32_ablation_measure as protocol
    from grhsim_single_compare import summarize
    check(out)
    protocol.VARIANTS=VARIANTS;protocol.ROUNDS=3
    result=protocol.measure(out,out/'measurement',XS/'ready-to-run/coremark-2-iteration.bin',
                            XS/'ready-to-run/riscv64-nemu-interpreter-so')
    comparisons=result['comparisons']
    for before,after in (('fixed','layout'),('fixed','scope'),('no_shared','layout'),('no_shared','scope')):
        key=after+'_vs_'+before;comparisons[key]={}
        for metric in ('host_ms','external_wall_s'):
            scale=1000 if metric=='external_wall_s' else 1
            rows=[{side:dict(host_ms=r[name][metric]*scale) for side,name in (('A',before),('B',after))}
                  for r in result['rounds']]
            comparisons[key][metric]=summarize(rows)
    check(out)
    save(out/'report.json',dict(comparisons=comparisons,build=identity(out/'build.json'),
        policy=identity(out/'policy.json'),summary=identity(out/'measurement/summary.json')))
    print(json.dumps(comparisons,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=('prepare','emit-layout','build','check','measure'))
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();{'prepare':prepare,'emit-layout':emit_layout,'build':build,'check':check,'measure':measure}[a.stage](a.output.resolve())
