#!/usr/bin/env python3
"""Replay one frozen graph for shared equality decoding; no candidate search."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

from cv32e40p_compare import ROOT, CXX, CFLAGS, environment, identity, run, save
from cv32e40p_concat_compare import model_shape
import cv32e40p_regfile_compare as compare

REFERENCE = ROOT / 'build/cv32e40p/concat-slices-v1'


def coverage(out):
    manifest = compare.check_identity(out)
    model = out / compare.backend_names(manifest)[1]
    groups = []
    for p in sorted(model.glob('*_sched_*.cpp')):
        for m in re.finditer(r'auto &grhsim_eq_cache_(\d+) = shared_equality_cache_\[\d+u\];(.*?)grhsim_eq_cache_\1\.valid = true;',
                             p.read_text(), re.S):
            ids = re.findall(r'const bool grhsim_changed_(\d+)', m[2])
            groups.append(dict(file=p.name, cache=int(m[1]), predicates=len(ids), value_ids=ids))
    save(out / 'decode-coverage.json', dict(groups=groups, predicates=sum(g['predicates'] for g in groups)))


def build(out, tools, jobs):
    if not platform.node().startswith('node030'): raise ValueError('build on node030')
    ref = compare.check_identity(REFERENCE); baseline = Path(ref['baseline'])
    original = REFERENCE / compare.backend_names(ref)[1]
    out.mkdir(parents=True, exist_ok=False)
    for name in ('firmware', 'verification.json'): (out / name).symlink_to(baseline / name)
    backends = ('grhsim_baseline', 'grhsim_shared_equality')
    (out / backends[0]).mkdir(); shutil.copy2(original / 'emu', out / backends[0] / 'emu')
    (out / 'wolvrix.patch').write_bytes(subprocess.check_output(['git', '-C', ROOT / 'wolvrix', 'diff', '--binary']))
    frozen = out / 'native-frozen'; frozen.mkdir()
    for p in [tools / 'cv32e40p_emit', tools / 'grhsim32/wolvrix/libwolvrix-lib.so']:
        shutil.copy2(p, frozen / p.name)
    graph = REFERENCE / 'candidate.json'
    env = environment(); env['LD_LIBRARY_PATH'] = str(frozen)
    off_env = dict(env); off_env['WOLVRIX_GRHSIM_SHARED_EQUALITY_DECODE'] = '0'
    run([frozen / 'cv32e40p_emit', graph, out / 'off-source', 'off'], out / 'logs/off-emit.log', env=off_env)
    expected = {p.name: identity(p)['sha256'] for p in original.glob('*.cpp')}
    actual = {p.name: identity(p)['sha256'] for p in (out / 'off-source').glob('*.cpp')}
    if actual != expected: raise ValueError('disabled lowering does not reproduce frozen C++')
    model = out / backends[1]
    run([frozen / 'cv32e40p_emit', graph, model, 'off'], out / 'logs/emit.log', env=env)
    if identity(model / 'normalized.json')['sha256'] != identity(original / 'normalized.json')['sha256']:
        raise ValueError('scheduled graph changed')
    run(['make', '-C', model, '-j', jobs, 'CXX=' + str(CXX), 'CXXFLAGS=' + ' '.join(CFLAGS)], out / 'logs/compile.log')
    harness = baseline / 'inputs/fixture/harness.cpp'
    run([CXX, *CFLAGS, '-DCV32_GRHSIM', '-I', model, harness, model / 'libgrhsim_Cv32Bench.a', '-o', model / 'emu'],
        out / 'logs/link.log')
    matches = []
    for p in sorted(model.glob('*_sched_*.cpp')):
        for m in re.finditer(r'// Shared equality decode:.*?auto &grhsim_eq_cache_\d+ = shared_equality_cache_\[(\d+)u\]', p.read_text(), re.S):
            matches.append(dict(file=p.name, cache=int(m[1])))
    if not matches: raise ValueError('no shared equality groups emitted')
    save(out / 'structure.json', dict(models={'before': model_shape(original), 'after': model_shape(model)},
        shared_equality_groups=matches, scheduled_graph_equal=True))
    save(out / 'build.json', dict(baseline=str(baseline), graph=identity(graph), reference_model=str(original),
        reference_manifest=identity(REFERENCE / 'build.json'), backend_pair=backends, lowering='shared_equality_decode',
        cxx=identity(CXX), flags=CFLAGS, wolvrix_head=subprocess.check_output(['git', '-C', ROOT / 'wolvrix', 'rev-parse', 'HEAD'], text=True).strip(),
        patch=identity(out / 'wolvrix.patch'), native=[identity(p) for p in sorted(frozen.iterdir())],
        harness=identity(harness), driver=identity(__file__), binaries={b: identity(out / b / 'emu') for b in backends},
        additional_inputs=[identity(out / 'structure.json')], off_source_equal=True, scheduled_graph_equal=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['build', 'attach-verilator', 'verify', 'measure', 'profile', 'report'])
    parser.add_argument('--output', type=Path, default=ROOT / 'build/cv32e40p/shared-equality-v1')
    parser.add_argument('--tools', type=Path, default=ROOT / 'build/cv32e40p/tools')
    parser.add_argument('--jobs', type=int, default=16)
    args = parser.parse_args(); out = args.output.resolve()
    if args.stage == 'build': build(out, args.tools.resolve(), args.jobs)
    elif args.stage == 'attach-verilator': compare.attach_verilator(out)
    else:
        getattr(compare, args.stage)(out)
        if args.stage == 'report': coverage(out)


if __name__ == '__main__': main()
