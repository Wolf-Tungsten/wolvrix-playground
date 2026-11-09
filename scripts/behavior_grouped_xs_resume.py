#!/usr/bin/env python3
"""Reuse matched RTL after the grouped importer's terminal-newline fix.

Hardware A never invokes this importer. Reuse its in-progress build, retaining
the original configuration/source records and an explicit one-file source audit.
"""
import argparse
import fcntl
import json
import os
import platform
import resource
import shutil
import subprocess
import time
from pathlib import Path
from grhsim_single_baseline import Baseline, ROOT, identity, save
from behavior_difftest_xs_study import validate_profile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--previous', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if not platform.node().startswith('node030'): raise ValueError('node030 required')
    resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    os.sched_setaffinity(0, set(range(96, 128)))
    previous = args.previous.resolve(); out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    with (out/'build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = json.loads((previous/'B/sources.json').read_text())
        changed = [x['path'] for x in before if identity(x['path']) != x]
        allowed = [str(ROOT/'wolvrix/app/pybind/wolvrix/behavior_state.py')]
        if changed != allowed: raise ValueError('unexpected changes since matched RTL generation: '+str(changed))
        for filename in ('rtl_manifest.json', 'difftest_generated_manifest.json'):
            for record in json.loads((previous/'B'/filename).read_text()):
                if identity(record['path']) != record: raise ValueError('previous RTL/header changed')
        frozen = out/'tools-frozen'
        if not frozen.exists():
            shutil.copytree(previous/'tools-frozen', frozen,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            shutil.copy2(allowed[0], frozen/'python/wolvrix/behavior_state.py')
            (frozen/'identity.json').unlink()
            save(frozen/'identity.json', [identity(x) for x in sorted(frozen.rglob('*')) if x.is_file()])
        for record in json.loads((frozen/'identity.json').read_text()):
            if '__pycache__' in Path(record['path']).parts:
                continue  # Derived interpreter caches are not compiler inputs.
            if identity(record['path']) != record: raise ValueError('frozen tools changed')
        for name in ('libwolvrix-lib.so','python/wolvrix/_wolvrix.so'):
            if identity(frozen/name)['sha256'] != identity(previous/'tools-frozen'/name)['sha256']:
                raise ValueError('native compiler differs from hardware A')
        linkage = subprocess.check_output(['ldd', str(frozen/'python/wolvrix/_wolvrix.so')],
            env=dict(os.environ, LD_LIBRARY_PATH=str(frozen)), text=True)
        (out/'frozen-linkage.log').write_text(linkage)
        if str(frozen/'libwolvrix-lib.so') not in linkage: raise ValueError('wrong native library')
        if not (out/'A').exists(): (out/'A').symlink_to(previous/'A', target_is_directory=True)
        config = argparse.Namespace(output=out/'B', tools_dir=frozen,
            compiler='/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++',
            jobs=16, cpu=96, cycles=100000, repeats=8, sim_primitives='none', sim_models='commit-rat',
            behavior_state_lowering='grouped', rtl_difftest='on', runtime_difftest='on')
        work = Baseline(config)
        work.env['PYTHONDONTWRITEBYTECODE'] = '1'
        if not (work.out/'sources.json').exists(): work.snapshot()
        for name in ('rtl','chisel-home'):
            if not (work.out/name).exists(): (work.out/name).symlink_to(previous/'B'/name, target_is_directory=True)
        for name in ('rtl_manifest.json','difftest_generated_manifest.json','simulation_models_manifest.json'):
            if not (work.out/name).exists(): shutil.copy2(previous/'B'/name, work.out/name)
        save(work.out/'profile-gate.json', validate_profile(work.out, True, grouped=True))
        save(out/'source-audit.json', dict(previous=str(previous), changed_files=changed,
            reused_rtl=identity(previous/'B/rtl_manifest.json'),
            native=identity(frozen/'libwolvrix-lib.so'),
            reason='Only grouped carrier EOF parsing changed; A uses ordinary import, native compiler and all RTL-generation sources unchanged. Original A records retained.'))
        if not (work.out/'model_manifest.json').exists(): work.emit()
        if not (work.out/'binary.json').exists(): work.compile()
        while not (out/'A/binary.json').exists():
            result=out/'A/logs/compile.result.json'
            if result.exists() and json.loads(result.read_text())['returncode']:
                raise RuntimeError('hardware A compile failed')
            print('waiting for the existing hardware A build', flush=True); time.sleep(15)
        save(out/'build-complete.json', dict(variants={v:identity(out/v/'emu/grhsim-compile/emu') for v in 'AB'},
            tools=identity(frozen/'identity.json'), reuse_audit=identity(out/'source-audit.json')))
        work.stage('grouped S3 and hardware A build complete')


if __name__ == '__main__': main()
