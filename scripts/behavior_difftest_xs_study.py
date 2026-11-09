#!/usr/bin/env python3
"""Build a resumable, source-matched hardware/behavior DiffTest experiment.

Measurement is deliberately a separate command after functional verification.
All modes retain DIFFTEST, NO_DIFF=0, NEMU, and the canonical checker events.
"""
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
import sys

from grhsim_single_baseline import Baseline, ROOT, identity, save


def validate_profile(path, behavior, grouped=False):
    profile = json.loads((path / 'chisel-home/build/generated-src/difftest_profile.json').read_text())
    classes = [b['className'].split('.')[-1] for b in profile['bundles']]
    raw = [n for n in classes if n.startswith(('DiffPhy', 'DiffArchIntRename', 'DiffArchFpRename', 'DiffArchVecRename'))]
    if behavior:
        if raw or any(n not in classes for n in ('DiffArchIntRegState', 'DiffArchFpRegState', 'DiffArchVecRegState', 'DiffCommitData')):
            raise ValueError('behavior profile lacks canonical registers or retains raw observations')
    elif len(raw) != 6:
        raise ValueError('hardware profile must have all six physical/RAT observations')
    manifest = json.loads((path / 'chisel-home/build/simulation_models.json').read_text())
    if behavior:
        if manifest['mode'] != 'commit-rat' or len(manifest['models']) != (2 if grouped else 1):
            raise ValueError('behavior manifest missing')
        if grouped:
            groups=[m for m in manifest['models'] if m.get('lowering')=='grouped']
            if len(groups)!=1 or len(groups[0]['binding']['updates'])!=2080:
                raise ValueError('grouped RAT must retain 520 ordered updates for each of four banks')
            if [a['rows'] for a in groups[0]['binding']['arrays']]!=[32,32,32,1]:
                raise ValueError('unexpected grouped RAT state layout')
            if len(manifest.get('observer_domains',[]))!=2:
                raise ValueError('adapter/Gateway observer domains missing')
    elif manifest['mode'] != 'hardware' or manifest['models']:
        raise ValueError('hardware mode unexpectedly generated behavior state')
    return dict(classes=classes, raw=raw, manifest=manifest)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--tools-dir', type=Path, default=ROOT / 'build/grhsim32-tools')
    p.add_argument('--jobs', type=int, default=16)
    p.add_argument('--behavior-state-lowering', choices=['ordinary','grouped'], default='ordinary')
    args = p.parse_args()
    if not platform.node().startswith('node030'):
        raise ValueError('this experiment builds and measures on node030')
    resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    os.sched_setaffinity(0, set(range(96, 128)))
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    with (out / 'build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        frozen = out / 'tools-frozen'
        if not (frozen / 'identity.json').exists():
            shutil.copytree(args.tools_dir.resolve() / 'python', frozen / 'python', dirs_exist_ok=True)
            # _wolvrix.so dynamically links the native compiler. Freeze both,
            # and put the native library on LD_LIBRARY_PATH before import.
            shutil.copy2(args.tools_dir.resolve()/'wolvrix/libwolvrix-lib.so', frozen/'libwolvrix-lib.so')
            save(frozen / 'identity.json', [identity(x) for x in sorted(frozen.rglob('*')) if x.is_file()])
        if not (frozen/'libwolvrix-lib.so').is_file():
            raise ValueError('old tool snapshot omitted the native library; use a new output')
        for item in json.loads((frozen / 'identity.json').read_text()):
            if identity(item['path']) != item: raise ValueError('frozen tool changed')
        linkage=subprocess.check_output(['ldd',str(frozen/'python/wolvrix/_wolvrix.so')],
            env=dict(os.environ,LD_LIBRARY_PATH=str(frozen)),text=True)
        (out/'frozen-linkage.log').write_text(linkage)
        if str(frozen/'libwolvrix-lib.so') not in linkage:raise ValueError('native compiler is not frozen')
        works = {}
        for label, mode in [('A', 'hardware'), ('B', 'commit-rat')]:
            config = argparse.Namespace(output=out/label, tools_dir=frozen,
                compiler='/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++',
                jobs=args.jobs, cpu=96, cycles=100000, repeats=8, sim_primitives='none',
                sim_models=mode, rtl_difftest='on', runtime_difftest='on',
                behavior_state_lowering=args.behavior_state_lowering if label=='B' else 'ordinary')
            works[label] = Baseline(config)
            sources = out/label/'sources.json'
            if sources.exists():
                for item in json.loads(sources.read_text()):
                    if identity(item['path']) != item: raise ValueError('source changed; use a new output: ' + item['path'])
            else:
                works[label].snapshot()
        if (out/'A/sources.json').read_bytes() != (out/'B/sources.json').read_bytes():
            raise ValueError('A/B source snapshots differ')
        # Include bytes of untracked new sources, which git diff cannot capture.
        for item in json.loads((out/'A/sources.json').read_text()):
            rel = Path(item['path']).relative_to(ROOT)
            if rel.name in ('BehaviorModels.scala', 'BehaviorDifftest.scala', 'BehaviorDifftestStudy.scala'):
                dest=out/'source-copy'/rel; dest.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(item['path'], dest)
        for label in ('B', 'A'):
            work=works[label]
            if not (work.out/'rtl_manifest.json').exists():
                work.stage('fresh RTL ' + label); work.rtl()
            save(work.out/'profile-gate.json', validate_profile(work.out, label=='B',
                grouped=label=='B' and args.behavior_state_lowering=='grouped'))
        def finish(label):
            work=works[label]
            if not (work.out/'model_manifest.json').exists(): work.emit()
            if not (work.out/'binary.json').exists(): work.compile()
            work.stage('build complete ' + label)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(finish,n) for n in ('A','B')]
            for f in futures: f.result()
        save(out/'build-complete.json',dict(variants={n:identity(w.out/'emu/grhsim-compile/emu') for n,w in works.items()},
            source_manifest=identity(out/'A/sources.json'), tools=identity(frozen/'identity.json')))

if __name__=='__main__': main()
