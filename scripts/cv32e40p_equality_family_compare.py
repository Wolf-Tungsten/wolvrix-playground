#!/usr/bin/env python3
"""One fixed test of sparse equality caches across shared-region composition."""
import argparse
import json
from pathlib import Path
import platform
import re
import shutil

from cv32e40p_compare import ROOT, CXX, CFLAGS, run, save, identity
from cv32e40p_event_regions_compare import check, shapes
from cv32e40p_repair_compare import (BASE, BASE_BACKEND, GRAPH, HARNESS, emit_environment,
    same_sources, compile_model, cone_sites, verify, measure, diagnose, native_library, snapshot_source)

CONTROL = ROOT / 'build/cv32e40p/region-order-repair-v1'
CONTROL_BACKEND = 'grhsim_shared_unguarded'
CANDIDATE = 'grhsim_equality_families'


def family_sites(folder):
    return [dict(source=int(source), predicates=int(count), file=p.name)
            for p in sorted(folder.glob('*_sched_*.cpp'))
            for source, count in re.findall(r'Shared equality family: source=(\d+) predicates=(\d+)', p.read_text())]


def build(out, tools, jobs):
    if not platform.node().startswith('node030'): raise ValueError('build on node030 for -march=native')
    if out.exists(): raise FileExistsError(out)
    retained, control = check(BASE), check(CONTROL)
    out.mkdir(parents=True)
    (out / 'firmware').symlink_to(BASE / 'firmware')
    (out / 'verification.json').symlink_to(BASE / 'verification.json')
    native = out / 'native-frozen'; native.mkdir()
    for src in (tools / 'cv32e40p_emit', tools / 'cv32e40p_map', native_library(tools)):
        shutil.copy2(src, native / src.name)
    snapshot = out / 'source-snapshot'; snapshot.mkdir()
    for src in (ROOT / 'wolvrix/lib/emit/grhsim_cpp.cpp', ROOT / 'wolvrix/tests/emit/test_emit_grhsim_cpp.cpp',
                ROOT / 'wolvrix/CMakeLists.txt', ROOT / 'testcase/cv32e40p-bench/emit.cpp',
                ROOT / 'scripts/cv32e40p_repair_compare.py', Path(__file__).resolve()):
        archived = src if src.parent.name == 'scripts' else snapshot_source(tools, src)
        shutil.copy2(archived, snapshot / src.name)
    save(out / 'hypothesis.json', dict(
        change='Group stored equality predicates by source SSA within a pure supernode, maintain sparse cache at first comparison after source is available.',
        controls='Same frozen shared-region schedule and conditional mux policy; no local one-hot table or slice transform.',
        expected='Restore cache reuse lost when source becomes local or equality operations are interleaved with consumers; reduce comparison/update work while preserving every activation target.',
        bounds=dict(width=[2,12], predicates=[16,256], exclusive_boolean_result_slots=True),
        policy='One fixed candidate. Eight forward/reverse four-backend rounds on CPU96 NUMA1. No thresholds, group selection, layout search or additional timing runs.'))
    env = emit_environment(native); env['WOLVRIX_GRHSIM_SHARED_EQUALITY_FAMILIES'] = '0'
    run([native / 'cv32e40p_emit', GRAPH, out / 'retained-source', 'off'], out / 'logs/retained-emit.log', env=env)
    if not same_sources(out / 'retained-source', BASE / BASE_BACKEND): raise ValueError('retained source drift')
    env['CV32_EVENT_REGIONS_SHARED'] = '1'
    run([native / 'cv32e40p_emit', GRAPH, out / CONTROL_BACKEND, 'off'], out / 'logs/control-emit.log', env=env)
    if not same_sources(out / CONTROL_BACKEND, CONTROL / CONTROL_BACKEND): raise ValueError('shared control source drift')
    env['WOLVRIX_GRHSIM_SHARED_EQUALITY_FAMILIES'] = '1'
    run([native / 'cv32e40p_emit', GRAPH, out / CANDIDATE, 'off'], out / 'logs/candidate-emit.log', env=env)
    run([native / 'cv32e40p_map', GRAPH, out / 'sources.csv', '--shared-event-regions'], out / 'logs/map.log', env=env)
    if identity(out / CANDIDATE / 'normalized.json')['sha256'] != identity(out / CONTROL_BACKEND / 'normalized.json')['sha256']:
        raise ValueError('normalized graph changed')
    old_shape, new_shape = shapes(out / CONTROL_BACKEND), shapes(out / CANDIDATE)
    for field in ('checked_values', 'supernodes', 'value_slots'):
        if old_shape[field] != new_shape[field]: raise ValueError('activity boundary changed: ' + field)
    sites = family_sites(out / CANDIDATE)
    if not sites: raise ValueError('no family formed')
    if cone_sites(out / CANDIDATE) != cone_sites(out / CONTROL_BACKEND): raise ValueError('conditional mux sites changed')
    save(out / 'structure.json', dict(baseline=shapes(BASE / BASE_BACKEND), control=old_shape, candidate=new_shape,
        family_sites=sites, feature_off_sources_equal=True, graph_equal=True,
        region_membership_equal=True, conditional_mux_sites_equal=True))
    compile_model(out / CANDIDATE, out, CANDIDATE, jobs)
    for backend, record in ((BASE_BACKEND, retained['binaries'][BASE_BACKEND]),
                            (CONTROL_BACKEND, control['binaries'][CONTROL_BACKEND]),
                            ('verilator', retained['binaries']['verilator'])):
        (out / backend).mkdir(exist_ok=True); shutil.copy2(record['path'], out / backend / 'emu')
    backends = [BASE_BACKEND, CONTROL_BACKEND, CANDIDATE, 'verilator']
    save(out / 'build.json', dict(feature='shared_equality_families', backends=backends, candidate=CANDIDATE,
        comparisons=[CONTROL_BACKEND, BASE_BACKEND, 'verilator'], flags=CFLAGS,
        binaries={b:identity(out / b / 'emu') for b in backends},
        frozen_inputs=[identity(p) for p in (BASE / 'build.json', CONTROL / 'build.json', GRAPH, HARNESS, CXX,
            out / 'hypothesis.json', out / 'structure.json', out / 'verification.json', out / 'sources.csv',
            *native.iterdir(), *snapshot.iterdir())]))
    print(json.dumps(dict(sites=sites, structure=new_shape), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('build', 'verify', 'measure', 'diagnose'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tools', type=Path, default=ROOT / 'build/cv32e40p/tools')
    parser.add_argument('--jobs', type=int, default=12)
    args = parser.parse_args()
    if args.stage == 'build': build(args.output.resolve(), args.tools.resolve(), args.jobs)
    else: {'verify':verify, 'measure':measure, 'diagnose':diagnose}[args.stage](args.output.resolve())
