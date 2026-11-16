#!/usr/bin/env python3
"""Validate one concat-slice simplification with the preceding frozen emitter."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

from cv32e40p_compare import ROOT, CXX, CFLAGS, environment, identity, run, save
import cv32e40p_regfile_compare as compare

REFERENCE = ROOT / 'build/cv32e40p/packed-slices-final'


def graph_shape(path):
    graph = json.loads(path.read_text())['graphs'][0]
    banks = {'core$_13862_', 'core$_13863_', 'core$_13859_', 'core$_13860_', 'core$_13861_'}
    return dict(identity=identity(path), operations=len(graph['ops']), values=len(graph['vals']),
        kinds=dict(Counter(op['kind'] for op in graph['ops'])),
        banks={name: dict(kind=op['kind'], operands=len(op['in']))
               for op in graph['ops'] for name in op['out'] if name in banks})


def model_shape(path):
    header = (path / 'grhsim_Cv32Bench.hpp').read_text()
    sources = sorted(path.glob('grhsim_Cv32Bench_sched_*.cpp'))
    code = '\n'.join(p.read_text() for p in sources)
    sections = subprocess.check_output(['size', '-A', str(path / 'emu')], text=True)
    return dict(value_slots={kind: int(count) for count, kind in
        re.findall(r'std::array<[^\n]+?, (\d+)> value_(\w+)_slots_', header)},
        compute_cpp_bytes=sum(p.stat().st_size for p in sources), batch_files=len(sources),
        scalar_comparisons=len(re.findall(r'const bool grhsim_changed_\d+ =', code)),
        packed_comparisons=len(re.findall(r'const auto grhsim_slice_changes_\d+ =', code)),
        direct_active_or_sites=len(re.findall(r'^\s*supernode_active_curr_\[.*?\] \|=', code, re.M)),
        supernodes=len(re.findall(r'// Supernode \d+:', code)),
        elf_sections={m[1]: int(m[2]) for m in re.finditer(r'^(\.\S+)\s+(\d+)\s+\d+', sections, re.M)},
        sources=[identity(p) for p in sources])


def build(out, tools, jobs):
    if not platform.node().startswith('node030'): raise ValueError('build on node030')
    reference = compare.check_identity(REFERENCE)
    baseline = Path(reference['baseline'])
    original = REFERENCE / compare.backend_names(reference)[1]
    out.mkdir(parents=True, exist_ok=False)
    for name in ('firmware', 'verification.json'): (out / name).symlink_to(baseline / name)
    backends = ('grhsim_baseline', 'grhsim_concat_slices')
    (out / backends[0]).mkdir()
    shutil.copy2(original / 'emu', out / backends[0] / 'emu')
    (out / 'wolvrix.patch').write_bytes(subprocess.check_output(['git', '-C', ROOT / 'wolvrix', 'diff', '--binary']))
    emitter = out / 'native-emitter'; emitter.mkdir()
    transform = out / 'native-transform'; transform.mkdir()
    for path in (REFERENCE / 'native-frozen').iterdir(): shutil.copy2(path, emitter / path.name)
    for path in [tools / 'cv32e40p_simplify', tools / 'grhsim32/wolvrix/libwolvrix-lib.so']:
        shutil.copy2(path, transform / path.name)
    env = environment(); env['LD_LIBRARY_PATH'] = str(emitter)
    new_env = dict(env); new_env['LD_LIBRARY_PATH'] = str(transform)
    for variant, library_env in [('control', env), ('candidate', new_env)]:
        run([transform / 'cv32e40p_simplify', baseline / 'graph.json', out / f'{variant}.json'],
            out / f'logs/{variant}-simplify.log', env=library_env)
    # Same tool binary with old/new libraries, then the SAME old emitter/library.
    run([emitter / 'cv32e40p_emit', out / 'control.json', out / 'control-source', 'off'],
        out / 'logs/control-emit.log', env=env)
    expected = {p.name: identity(p)['sha256'] for p in original.glob('*.cpp')}
    actual = {p.name: identity(p)['sha256'] for p in (out / 'control-source').glob('*.cpp')}
    if actual != expected: raise ValueError('extra old-library simplification does not reproduce frozen C++')
    model = out / backends[1]
    run([emitter / 'cv32e40p_emit', out / 'candidate.json', model, 'off'], out / 'logs/emit.log', env=env)
    run(['make', '-C', model, '-j', jobs, 'CXX=' + str(CXX), 'CXXFLAGS=' + ' '.join(CFLAGS)],
        out / 'logs/compile.log')
    harness = baseline / 'inputs/fixture/harness.cpp'
    run([CXX, *CFLAGS, '-DCV32_GRHSIM', '-I', model, harness, model / 'libgrhsim_Cv32Bench.a',
         '-o', model / 'emu'], out / 'logs/link.log')
    shape = dict(graphs={name: graph_shape(path) for name, path in [
        ('frozen_input', baseline / 'graph.json'), ('control', out / 'control.json'),
        ('candidate', out / 'candidate.json'), ('scheduled_before', original / 'normalized.json'),
        ('scheduled_after', model / 'normalized.json')]},
        models={'before': model_shape(original), 'after': model_shape(model)})
    save(out / 'structure.json', shape)
    save(out / 'build.json', dict(baseline=str(baseline), graph=identity(baseline / 'graph.json'),
        reference_model=str(original), reference_manifest=identity(REFERENCE / 'build.json'),
        backend_pair=backends, lowering='concat-slice-coalescing', cxx=identity(CXX), flags=CFLAGS,
        wolvrix_head=subprocess.check_output(['git', '-C', ROOT / 'wolvrix', 'rev-parse', 'HEAD'], text=True).strip(),
        patch=identity(out / 'wolvrix.patch'), native=[identity(p) for folder in [emitter, transform] for p in sorted(folder.iterdir())],
        harness=identity(harness), driver=identity(__file__), binaries={b: identity(out / b / 'emu') for b in backends},
        additional_inputs=[identity(out / n) for n in ['control.json', 'candidate.json', 'structure.json']],
        control_cpp_equal=True, emitter_library_identical=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['build', 'attach-verilator', 'verify', 'measure', 'profile', 'report'])
    parser.add_argument('--output', type=Path, default=ROOT / 'build/cv32e40p/concat-slices-v1')
    parser.add_argument('--tools', type=Path, default=ROOT / 'build/cv32e40p/tools')
    parser.add_argument('--jobs', type=int, default=16)
    args = parser.parse_args(); out = args.output.resolve()
    if args.stage == 'build': build(out, args.tools.resolve(), args.jobs)
    elif args.stage == 'attach-verilator': compare.attach_verilator(out)
    else: getattr(compare, args.stage)(out)


if __name__ == '__main__': main()
