#!/usr/bin/env python3
"""Measure one endpoint-class region policy against frozen event regions."""
import argparse
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

from cv32e40p_compare import ROOT, CXX, CFLAGS, environment, identity, run, save
from cv32e40p_event_regions_compare import check, source_inventory, shapes, verify, measure

BASE = ROOT / 'build/cv32e40p/event-regions-v3'
BACKENDS = ('grhsim_event_regions', 'grhsim_shared_regions', 'verilator')


def build(out, tools, jobs):
    if not platform.node().startswith('node030'):
        raise ValueError('build on node030 for -march=native')
    if out.exists():
        raise FileExistsError('use a new output directory')
    original = check(BASE)
    model = BASE / 'grhsim_event_regions'
    out.mkdir(parents=True)
    (out / 'firmware').symlink_to(BASE / 'firmware', target_is_directory=True)
    (out / 'verification.json').symlink_to(BASE / 'verification.json')
    frozen = out / 'native-frozen'; frozen.mkdir()
    for src in (tools / 'cv32e40p_emit', tools / 'cv32e40p_map', tools / 'grhsim32/wolvrix/libwolvrix-lib.so'):
        shutil.copy2(src, frozen / src.name)
    graph = ROOT / 'build/cv32e40p/concat-slices-v1/candidate.json'
    harness = ROOT / 'build/cv32e40p/run2/inputs/fixture/harness.cpp'
    env = environment(); env['LD_LIBRARY_PATH'] = str(frozen)
    env['CV32_EVENT_REGIONS'] = '1'; env['CV32_EVENT_REGIONS_SHARED'] = '0'
    env['WOLVRIX_GRHSIM_LOCAL_EQUALITY_DECODE'] = '0'
    run([frozen / 'cv32e40p_emit', graph, out / 'off-source', 'off'], out / 'logs/off-emit.log', env=env)
    shape = lambda entries: {name: (record['bytes'], record['sha256']) for name, record in entries.items()}
    if shape(source_inventory(model)) != shape(source_inventory(out / 'off-source')):
        save(out / 'source-mismatch.json', dict(baseline=source_inventory(model), off=source_inventory(out / 'off-source')))
        raise ValueError('feature-off does not reproduce frozen event-region sources')
    candidate = out / BACKENDS[1]
    env['CV32_EVENT_REGIONS_SHARED'] = '1'
    save(out / 'hypothesis.json', dict(
        mechanism='Most residual change checks exist solely between compute groups with shared downstream endpoints.',
        change='After single-terminal regions, treat protected memory/event/effect groups as endpoints; classify whole compute nodes, refine mixed pure groups, and contract matching multi-endpoint classes.',
        bounds=dict(max_region_ops=8192, max_endpoints=32),
        expected='Fewer persistent intermediates, checks and activity updates; first-use order limits added live ranges.',
        risks='More unconditional recomputation within merged groups; decoder reuse and register pressure can worsen.',
        policy='One structural rule; no profile-based selection, parameter scan or post-run candidate selection.'))
    run([frozen / 'cv32e40p_emit', graph, candidate, 'off'], out / 'logs/emit.log', env=env)
    if identity(candidate / 'normalized.json')['sha256'] != identity(model / 'normalized.json')['sha256']:
        raise ValueError('shared regions changed the frozen graph')
    if not re.search(r'shared event-regions: regions=[1-9]', (out / 'logs/emit.log').read_text()):
        raise ValueError('no shared region formed; stop before compilation or timing')
    if shapes(candidate)['checked_values'] >= shapes(model)['checked_values']:
        raise ValueError('candidate did not reduce checked boundary values; stop before timing')
    run([frozen / 'cv32e40p_map', graph, out / 'sources.csv', '--shared-event-regions'], out / 'logs/mapping.log', env=env)
    run(['make', '-C', candidate, '-j', jobs, 'CXX=' + str(CXX), 'CXXFLAGS=' + ' '.join(CFLAGS)], out / 'logs/compile.log')
    run([CXX, *CFLAGS, '-DCV32_GRHSIM', '-I', candidate, harness,
         candidate / 'libgrhsim_Cv32Bench.a', '-o', candidate / 'emu'], out / 'logs/link.log')
    for backend in (BACKENDS[0], 'verilator'):
        (out / backend).mkdir(); shutil.copy2(original['binaries'][backend]['path'], out / backend / 'emu')
    snapshot = out / 'source-snapshot'; snapshot.mkdir()
    for src in (ROOT / 'wolvrix/lib/emit/grhsim_cpp.cpp', ROOT / 'testcase/cv32e40p-bench/emit.cpp',
                ROOT / 'testcase/cv32e40p-bench/map.cpp', ROOT / 'wolvrix/lib/transform/activity_schedule.cpp',
                ROOT / 'wolvrix/include/transform/activity_schedule.hpp', ROOT / 'wolvrix/lib/core/transform.cpp',
                Path(__file__).resolve(), ROOT / 'scripts/cv32e40p_event_regions_compare.py'):
        shutil.copy2(src, snapshot / src.name)
    patch = out / 'wolvrix.patch'
    patch.write_bytes(subprocess.check_output(['git', '-C', ROOT / 'wolvrix', 'diff', '--binary']))
    save(out / 'structure.json', dict(baseline=shapes(model), candidate=shapes(candidate),
        off_source_identical=True, scheduled_graph_identical=True,
        emitted_sources=list(source_inventory(candidate).values())))
    save(out / 'build.json', dict(feature='event_regions_shared', backend_pair=BACKENDS[:2],
        frozen_inputs=[identity(p) for p in (BASE / 'build.json', graph, harness, CXX, patch, out / 'sources.csv',
            out / 'hypothesis.json', out / 'structure.json', out / 'verification.json',
            *sorted(frozen.iterdir()), *sorted(snapshot.iterdir()))],
        binaries={backend: identity(out / backend / 'emu') for backend in BACKENDS}, flags=CFLAGS,
        scope='same normalized RTL and emitter; one shared-region schedule policy'))
    print(json.dumps(shapes(candidate), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('build', 'verify', 'measure'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tools', type=Path, default=ROOT / 'build/cv32e40p/tools')
    parser.add_argument('--jobs', type=int, default=12)
    args = parser.parse_args()
    if args.stage == 'build': build(args.output.resolve(), args.tools.resolve(), args.jobs)
    elif args.stage == 'verify': verify(args.output.resolve())
    else: measure(args.output.resolve())
