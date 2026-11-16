#!/usr/bin/env python3
"""Test local decoder reuse without undoing event-region fusion."""
import argparse
import json
from pathlib import Path
import platform
import shutil
import subprocess

from cv32e40p_compare import ROOT, CXX, CFLAGS, environment, identity, run, save
from cv32e40p_event_regions_compare import check, source_inventory, shapes, verify, measure

BASE = ROOT / 'build/cv32e40p/event-regions-v3'
BACKENDS = ('grhsim_event_regions', 'grhsim_local_decode', 'verilator')


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
    for src in (tools / 'cv32e40p_emit', tools / 'grhsim32/wolvrix/libwolvrix-lib.so'):
        shutil.copy2(src, frozen / src.name)
    graph = ROOT / 'build/cv32e40p/concat-slices-v1/candidate.json'
    harness = ROOT / 'build/cv32e40p/run2/inputs/fixture/harness.cpp'
    env = environment(); env['LD_LIBRARY_PATH'] = str(frozen); env['CV32_EVENT_REGIONS'] = '1'
    env['WOLVRIX_GRHSIM_SHARED_EQUALITY_DECODE'] = '1'
    env['WOLVRIX_GRHSIM_LOCAL_EQUALITY_DECODE'] = '0'
    run([frozen / 'cv32e40p_emit', graph, out / 'off-source', 'off'], out / 'logs/off-emit.log', env=env)
    shape = lambda entries: {name: (record['bytes'], record['sha256']) for name, record in entries.items()}
    if shape(source_inventory(model)) != shape(source_inventory(out / 'off-source')):
        raise ValueError('feature-off does not reproduce the frozen event-region source')
    candidate = out / BACKENDS[1]
    env['WOLVRIX_GRHSIM_LOCAL_EQUALITY_DECODE'] = '1'
    save(out / 'hypothesis.json', dict(
        mechanism='Region fusion makes a stable 171-predicate decoder local and ineligible for the previous slot-only cache.',
        change='Cache narrow local equality families independently of activity boundaries; retain graph and schedule.',
        expected='Fewer repeated decoder computations and shorter live local predicate ranges; no functional or boundary change.',
        policy='One structural implementation. No group-size, domain, or option search.'))
    run([frozen / 'cv32e40p_emit', graph, candidate, 'off'], out / 'logs/emit.log', env=env)
    if identity(candidate / 'normalized.json')['sha256'] != identity(model / 'normalized.json')['sha256']:
        raise ValueError('local decode changed the graph')
    code = '\n'.join(p.read_text() for p in candidate.glob('*_sched_*.cpp'))
    if '// Local equality decode:' not in code:
        raise ValueError('local decode did not trigger')
    run(['make', '-C', candidate, '-j', jobs, 'CXX=' + str(CXX), 'CXXFLAGS=' + ' '.join(CFLAGS)], out / 'logs/compile.log')
    run([CXX, *CFLAGS, '-DCV32_GRHSIM', '-I', candidate, harness,
         candidate / 'libgrhsim_Cv32Bench.a', '-o', candidate / 'emu'], out / 'logs/link.log')
    for backend in (BACKENDS[0], 'verilator'):
        (out / backend).mkdir(); shutil.copy2(original['binaries'][backend]['path'], out / backend / 'emu')
    snapshot = out / 'source-snapshot'; snapshot.mkdir()
    for src in (ROOT / 'wolvrix/lib/emit/grhsim_cpp.cpp', ROOT / 'testcase/cv32e40p-bench/emit.cpp',
                ROOT / 'wolvrix/lib/transform/activity_schedule.cpp', Path(__file__).resolve(),
                ROOT / 'scripts/cv32e40p_event_regions_compare.py'):
        shutil.copy2(src, snapshot / src.name)
    patch = out / 'wolvrix.patch'
    patch.write_bytes(subprocess.check_output(['git', '-C', ROOT / 'wolvrix', 'diff', '--binary']))
    save(out / 'structure.json', dict(baseline=shapes(model), candidate=shapes(candidate),
        off_source_identical=True, scheduled_graph_identical=True,
        local_decode_groups=code.count('// Local equality decode:'),
        emitted_sources=list(source_inventory(candidate).values())))
    save(out / 'build.json', dict(feature='local_equality_decode', backend_pair=BACKENDS[:2],
        frozen_inputs=[identity(p) for p in (BASE / 'build.json', graph, harness, CXX, patch,
            out / 'hypothesis.json', out / 'structure.json', out / 'verification.json',
            *sorted(frozen.iterdir()), *sorted(snapshot.iterdir()))],
        binaries={backend: identity(out / backend / 'emu') for backend in BACKENDS}, flags=CFLAGS,
        scope='same event-region schedule and normalized RTL; one cache composability fix'))
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
