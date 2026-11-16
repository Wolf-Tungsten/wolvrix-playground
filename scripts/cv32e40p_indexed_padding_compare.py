#!/usr/bin/env python3
"""Validate one indexed-concat extension against the frozen shared decoder."""
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

REFERENCE = ROOT / 'build/cv32e40p/shared-equality-validated'


def build(out, tools, jobs):
    if not platform.node().startswith('node030'): raise ValueError('build on node030')
    ref = compare.check_identity(REFERENCE)
    baseline = Path(ref['baseline'])
    original = REFERENCE / compare.backend_names(ref)[1]
    out.mkdir(parents=True, exist_ok=False)
    for name in ('firmware', 'verification.json'): (out / name).symlink_to(baseline / name)
    backends = ('grhsim_baseline', 'grhsim_indexed_padding')
    (out / backends[0]).mkdir()
    shutil.copy2(original / 'emu', out / backends[0] / 'emu')
    (out / 'wolvrix.patch').write_bytes(subprocess.check_output(['git', '-C', ROOT / 'wolvrix', 'diff', '--binary']))
    frozen = out / 'native-frozen'; frozen.mkdir()
    for p in [tools / 'cv32e40p_emit', tools / 'grhsim32/wolvrix/libwolvrix-lib.so']:
        shutil.copy2(p, frozen / p.name)
    graph = Path(ref['graph']['path'])
    env = environment(); env['LD_LIBRARY_PATH'] = str(frozen)
    old_env = environment(); old_env['LD_LIBRARY_PATH'] = str(REFERENCE / 'native-frozen')
    # This extends an existing switch, so compare both emitters with that switch
    # disabled. Disabling it must remove the new and previously accepted paths.
    for name, executable, local_env in [
        ('off-before', REFERENCE / 'native-frozen/cv32e40p_emit', old_env),
        ('off-after', frozen / 'cv32e40p_emit', env)]:
        disabled = dict(local_env); disabled['WOLVRIX_GRHSIM_INDEXED_CONCAT_SLICE'] = '0'
        run([executable, graph, out / name, 'off'], out / f'logs/{name}-emit.log', env=disabled)
    before_off = {p.name: identity(p)['sha256'] for p in (out / 'off-before').glob('*.cpp')}
    after_off = {p.name: identity(p)['sha256'] for p in (out / 'off-after').glob('*.cpp')}
    if before_off != after_off: raise ValueError('disabled extension changes unrelated C++')
    env['WOLVRIX_GRHSIM_INDEXED_CONCAT_WIDE_CONSTANTS'] = '1'
    model = out / backends[1]
    run([frozen / 'cv32e40p_emit', graph, model, 'off'], out / 'logs/emit.log', env=env)
    if identity(model / 'normalized.json')['sha256'] != identity(original / 'normalized.json')['sha256']:
        raise ValueError('scheduled graph changed')
    def coverage(folder):
        return [dict(file=p.name, value=int(m[1])) for p in sorted(folder.glob('*_sched_*.cpp'))
                for m in re.finditer(r'const auto grhsim_concat_word_(\d+) =', p.read_text())]
    before, after = coverage(original), coverage(model)
    added = [x for x in after if x not in before]
    if not added: raise ValueError('extension did not add any indexed concat views')
    run(['make', '-C', model, '-j', jobs, 'CXX=' + str(CXX), 'CXXFLAGS=' + ' '.join(CFLAGS)], out / 'logs/compile.log')
    harness = Path(ref['harness']['path'])
    run([CXX, *CFLAGS, '-DCV32_GRHSIM', '-I', model, harness, model / 'libgrhsim_Cv32Bench.a', '-o', model / 'emu'],
        out / 'logs/link.log')
    save(out / 'structure.json', dict(models={'before': model_shape(original), 'after': model_shape(model)},
        indexed_concat_views=dict(before=before, after=after, added=added), scheduled_graph_equal=True,
        disabled_before_after_cpp_equal=True))
    sources = out / 'validation/sources'; sources.mkdir(parents=True)
    frozen_sources = []
    for p in [ROOT / 'wolvrix/lib/emit/grhsim_cpp.cpp', ROOT / 'wolvrix/tests/emit/test_emit_grhsim_cpp.cpp',
              ROOT / 'wolvrix/docs/emit/grhsim-indexed-concat-slices.md', Path(__file__)]:
        target = sources / p.relative_to(ROOT); target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target); frozen_sources.append(identity(target))
    save(out / 'build.json', dict(baseline=str(baseline), graph=identity(graph), reference_model=str(original),
        reference_manifest=identity(REFERENCE / 'build.json'), backend_pair=backends, lowering='indexed-concat-wide-constant-padding',
        cxx=identity(CXX), flags=CFLAGS, wolvrix_head=subprocess.check_output(['git', '-C', ROOT / 'wolvrix', 'rev-parse', 'HEAD'], text=True).strip(),
        patch=identity(out / 'wolvrix.patch'), native=[identity(p) for p in sorted(frozen.iterdir())],
        harness=identity(harness), driver=identity(__file__), binaries={b: identity(out / b / 'emu') for b in backends},
        additional_inputs=[identity(out / 'structure.json'), *ref['native'], *frozen_sources],
        disabled_before_after_cpp_equal=True, scheduled_graph_equal=True,
        explicit_options={'indexed_concat_wide_constants': True}))
    print(json.dumps(dict(added=added, before=len(before), after=len(after)), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('build', 'attach-verilator', 'verify', 'measure', 'profile', 'report'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tools', type=Path, default=ROOT / 'build/cv32e40p/tools')
    parser.add_argument('--jobs', type=int, default=16)
    args = parser.parse_args(); out = args.output.resolve()
    if args.stage == 'build': build(out, args.tools.resolve(), args.jobs)
    elif args.stage == 'attach-verilator': compare.attach_verilator(out)
    else: getattr(compare, args.stage)(out)


if __name__ == '__main__': main()
