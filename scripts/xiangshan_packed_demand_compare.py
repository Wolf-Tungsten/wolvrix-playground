#!/usr/bin/env python3
"""Predeclared independent packed-demand rules and one layout combination."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import platform
import re
import resource
import shutil
import subprocess

from cv32e40p_compare import ROOT, run
from cv32e40p_repair_compare import native_library
from grhsim_single_baseline import identity, save, clean_environment
from grhsim_single_compare import summarize
from xiangshan_cv32_compare import HISTORICAL, XS, verify_identity
from xiangshan_packed_storage_compare import FULL, check_harness_source, check_model, source_inventory, source_shape

PREVIOUS = ROOT / 'build/xs/packed-storage-fixed-20261116-v1'
VARIANTS = ('full', 'layout', 'no_init', 'select', 'combined', 'no_shared')
NEW = ('no_init', 'select', 'combined', 'no_shared')
OPTIONS = {
    'no_init': (0, 1, 0), 'select': (0, 0, 1), 'combined': (1, 1, 1), 'no_shared': (0, 0, 0),
    'off': (0, 0, 0),
}


def read(path):
    return json.loads(Path(path).read_text())


def contract(folder):
    digest = hashlib.sha256()
    counts = dict(no_init=0, select=0)
    for p in sorted(folder.glob('*_sched_*.cpp')):
        code = p.read_text()
        # Preserve group/op order, scalar change sites and conditional/cache
        # declarations. Array construction is the intended code difference.
        lines = re.findall(r'(?m)^.*(?:// (?:Supernode |op |Conditional mux)|const bool grhsim_changed_).*$|'
                           r'^.*supernode_active_(?:curr|next)_\[.*$', code)
        digest.update((p.name + '\n' + '\n'.join(lines)).encode())
        counts['no_init'] += code.count('// Packed array full overwrite:')
        counts['select'] += code.count('// Selected packed state:')
    return dict(schedule_change_notify_hash=digest.hexdigest(), **counts)


def prepare(out, tools):
    check_harness_source()
    out.mkdir(parents=True, exist_ok=False)
    snap, native = out/'snapshot', out/'native'
    snap.mkdir(); native.mkdir()
    shutil.copytree(ROOT/'wolvrix/lib', snap/'lib')
    shutil.copytree(ROOT/'wolvrix/include', native/'include')
    shutil.copy2(native_library(tools), native/'libwolvrix-lib.so')
    for p in (ROOT/'scripts/xiangshan_cv32_emit.cpp', Path(__file__).resolve()):
        shutil.copy2(p, snap/p.name)
    (snap/'wolvrix.patch').write_bytes(subprocess.check_output(['git','-C',ROOT/'wolvrix','diff','--binary']))
    for name, old in (('full','fixed'), ('layout','layout')):
        check_model(PREVIOUS/old)
        (out/name).symlink_to(PREVIOUS/old, target_is_directory=True)
    for name in NEW:
        dest=out/name;dest.mkdir()
        shutil.copytree(PREVIOUS/'fixed/chisel-home', dest/'chisel-home')
        config=read(PREVIOUS/'fixed/configuration.json')
        a,b,c=OPTIONS[name]
        config.update(variant=name, state_layout_packed_access=bool(a), packed_array_no_init=bool(b),
            packed_array_state_select=bool(c), packed_array_local_scope=False,
            event_regions_shared=name!='no_shared', native_library=identity(native/'libwolvrix-lib.so'),
            note='Corrected generator. Independent no-init/select and one predeclared layout+no-init+select combination.')
        save(dest/'configuration.json',config)
    save(out/'policy.json',dict(variants=VARIANTS, pairs=3, cpu=96, numa=1, aslr=False, threads=1,
        cycles=100000, smoke_cycles=10000, verification_seeds=[0,1], options=OPTIONS,
        order='forward/reverse alternating for three rounds',
        generation='Static direct-state/full-overwrite and immutable-index proofs only. No timing feedback or tuned thresholds.',
        comparisons=['no_init/full','select/full','combined/layout','combined/full','combined/no_shared'],
        combination='Layout + no-init + selected reads fixed before generation; scope disabled, no combination search.',
        no_shared='Regenerated with the same corrected native library; no new demand/layout rules.',
        idle_admission='Preserve prior XS skip-external-idle policy; CPU96/NUMA1/ASLR/thread gates mandatory.'))
    files=[identity(p) for p in sorted(snap.rglob('*')) if p.is_file()]
    files += [identity(p) for p in sorted(native.rglob('*')) if p.is_file()]
    files += [identity(out/n) for n in ('policy.json',)]
    files += [identity(out/n/'configuration.json') for n in NEW]
    files += [identity(HISTORICAL/'pre_reg_to_mem.json')]
    for p in ('xiangshan_cv32_ablation_measure.py','xiangshan_packed_storage_compare.py',
              'grhsim_single_baseline.py','grhsim_single_compare.py','grhsim_difftrace.py','grhsim_numa.py'):
        files.append(identity(ROOT/'scripts'/p))
    save(out/'inputs.json',files)
    print('prepared six variants before any measurement',flush=True)


def check_inputs(out):
    for record in read(out/'inputs.json'):verify_identity(record)


def build(out):
    assert platform.node().startswith('node030')
    check_inputs(out);check_harness_source()
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    native=out/'native';env=clean_environment()
    env.update(NOOP_HOME=str(XS),LC_ALL='C',WOLVRIX_GRHSIM_STORAGE_REF_ALIASES='0',
               WOLVRIX_GRHSIM_PACKED_ARRAY_LOCAL_SCOPE='0',LD_LIBRARY_PATH=str(native))
    original=read(FULL/'logs/native.command.json')['argv']
    for name in ('full','no_shared'):
        cmd=[a.replace(str(FULL/'native'),str(native)).replace(str(FULL.parent/'snapshot'),str(out/'snapshot')) for a in original]
        cmd[-1]=str(native/('emit-'+name))
        if name=='no_shared':cmd.insert(1,'-DXS_ABLATE_SHARED=1')
        run(cmd,out/'logs'/('native-'+name+'.log'),env=env)
    def emit_one(name):
        a,b,c=OPTIONS[name];local=env.copy()
        local.update(WOLVRIX_GRHSIM_STATE_LAYOUT_PACKED_ACCESS=str(a),WOLVRIX_GRHSIM_PACKED_ARRAY_NO_INIT=str(b),
                     WOLVRIX_GRHSIM_PACKED_ARRAY_STATE_SELECT=str(c))
        target=out/'off-source' if name=='off' else out/name/'model'
        run([native/('emit-no_shared' if name=='no_shared' else 'emit-full'),HISTORICAL/'pre_reg_to_mem.json',target],
            out/'logs'/(name+'-emit.log'),env=local)
    # Emission/build parallelism is independent of the strictly serial run protocol.
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(emit_one,('off',*NEW)))
    if source_shape(source_inventory(out/'off-source'))!=source_shape(source_inventory(out/'full/model')):
        raise ValueError('options-off source differs from corrected frozen full')
    expected=contract(out/'full/model');shapes={}
    for name in ('no_init','select','combined'):
        shapes[name]=contract(out/name/'model')
        assert shapes[name]['schedule_change_notify_hash']==expected['schedule_change_notify_hash'],name
        header_reference=out/('layout' if name=='combined' else 'full')/'model'
        for p in (out/name/'model').glob('*.hpp'):
            assert p.read_bytes()==(header_reference/p.name).read_bytes(),(name,p.name)
    assert shapes['no_init']['no_init'] and not shapes['no_init']['select']
    assert shapes['select']['select'] and not shapes['select']['no_init']
    assert shapes['combined']['select']==shapes['select']['select']
    save(out/'structure.json',dict(off_equal_corrected_full=True,full=expected,models=shapes))
    def compile_one(name):
        model=out/name;sources=source_inventory(model/'model');save(model/'model-sources.json',sources)
        cmd=[a.replace(str(FULL),str(model)).replace('GRHSIM_MODEL_BUILD_JOBS=32','GRHSIM_MODEL_BUILD_JOBS=16')
             .replace('VM_BUILD_JOBS=32','VM_BUILD_JOBS=16') for a in read(FULL/'logs/compile.command.json')['argv']]
        run(cmd,model/'logs/compile.log',env=env)
        save(model/'binary.json',identity(model/'emu/grhsim-compile/emu'))
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(compile_one,NEW))
    files=[identity(out/'structure.json')]+source_inventory(out/'off-source')
    for name in NEW:
        files+=read(out/name/'model-sources.json')+[identity(out/name/n) for n in ('binary.json','model-sources.json')]
        files+=[read(out/name/'binary.json')]
    files += [identity(p) for p in sorted((out/'logs').glob('*')) if p.is_file()]
    files += [identity(native/('emit-'+name)) for name in ('full','no_shared')]
    save(out/'build.json',dict(inputs=identity(out/'inputs.json'),files=files,
        binaries={n:read(out/n/'binary.json') for n in VARIANTS}))
    check(out);print('all six models ready',flush=True)


def check(out):
    check_inputs(out)
    for record in read(out/'build.json')['files']:verify_identity(record)
    for name in VARIANTS:check_model(out/name)


def measure(out):
    import xiangshan_cv32_ablation_measure as protocol
    check(out);protocol.VARIANTS=VARIANTS;protocol.ROUNDS=3
    result=protocol.measure(out,out/'measurement',XS/'ready-to-run/coremark-2-iteration.bin',
                            XS/'ready-to-run/riscv64-nemu-interpreter-so')
    comparisons={}
    for before,after in (('full','no_init'),('full','select'),('full','layout'),('layout','combined'),
                         ('full','combined'),('no_shared','combined'),('full','no_shared')):
        comparisons[after+'_vs_'+before]={}
        for metric in ('host_ms','external_wall_s'):
            scale=1000 if metric=='external_wall_s' else 1
            rows=[{side:dict(host_ms=r[n][metric]*scale) for side,n in (('A',before),('B',after))} for r in result['rounds']]
            comparisons[after+'_vs_'+before][metric]=summarize(rows)
    check(out);save(out/'report.json',dict(comparisons=comparisons,build=identity(out/'build.json'),policy=identity(out/'policy.json')))
    print(json.dumps(comparisons,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=('prepare','build','check','measure'))
    p.add_argument('--output',type=Path,required=True);p.add_argument('--tools',type=Path,default=ROOT/'build/cv32e40p/tools')
    a=p.parse_args();out=a.output.resolve()
    if a.stage=='prepare':prepare(out,a.tools.resolve())
    else:{'build':build,'check':check,'measure':measure}[a.stage](out)
