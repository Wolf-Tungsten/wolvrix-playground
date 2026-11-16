#!/usr/bin/env python3
"""One fixed comparison of exact input caching for closed conditional mux cones."""
import argparse
import json
from pathlib import Path
import platform
import re
import shutil

from cv32e40p_compare import ROOT, CXX, CFLAGS, run, save, identity
from cv32e40p_event_regions_compare import check, shapes
from cv32e40p_equality_family_compare import family_sites
from cv32e40p_repair_compare import (GRAPH, HARNESS, emit_environment, same_sources,
    compile_model, cone_sites, verify, measure, diagnose, native_library, snapshot_source)

BASE = ROOT / 'build/cv32e40p/equality-families-v1'
BASE_BACKEND = 'grhsim_equality_families'
CANDIDATE = 'grhsim_mux_input_cache'


def cache_sites(folder):
    return [dict(root=int(root), keys=int(keys), file=p.name)
            for p in sorted(folder.glob('*_sched_*.cpp'))
            for root, keys in re.findall(r'Conditional mux input cache: root=(\d+) inputs=(\d+)', p.read_text())]


def build(out, tools, jobs):
    if not platform.node().startswith('node030'): raise ValueError('build on node030 for -march=native')
    if out.exists(): raise FileExistsError(out)
    retained = check(BASE)
    out.mkdir(parents=True)
    (out / 'firmware').symlink_to(BASE / 'firmware')
    (out / 'verification.json').symlink_to(BASE / 'verification.json')
    native = out / 'native-frozen'; native.mkdir()
    for src in (tools / 'cv32e40p_emit', tools / 'cv32e40p_map', native_library(tools)):
        shutil.copy2(src, native / src.name)
    snapshot = out / 'source-snapshot'; snapshot.mkdir()
    for src in (ROOT / 'wolvrix/lib/emit/grhsim_cpp.cpp',
                ROOT / 'wolvrix/tests/emit/test_emit_grhsim_conditional_mux.cpp',
                ROOT / 'wolvrix/CMakeLists.txt', ROOT / 'testcase/cv32e40p-bench/emit.cpp',
                ROOT / 'scripts/cv32e40p_repair_compare.py', Path(__file__).resolve()):
        archived = src if src.parent.name == 'scripts' else snapshot_source(tools, src)
        shutil.copy2(archived, snapshot / src.name)
    save(out / 'hypothesis.json', dict(
        change='Cache exact scalar read sets of existing conditional mux cones with exclusive persistent result slots.',
        expected='Avoid recomputing inactive internal control logic when a merged region runs for another dependency. Keep existing equality families and conditional cone membership.',
        bounds=dict(keys=[1, 4], parent_arm_operations=[16, 256], dependency_depth=32,
                    visited_values=256, exclusive_result_slot=True),
        policy='One fixed structural rule. Eight forward/reverse three-backend rounds on CPU96 NUMA1. No profile-based selections, threshold search or extra timing runs.'))
    env = emit_environment(native)
    env.update(CV32_EVENT_REGIONS_SHARED='1', WOLVRIX_GRHSIM_SHARED_EQUALITY_FAMILIES='1',
               WOLVRIX_GRHSIM_CONDITIONAL_MUX_INPUT_CACHE='0')
    run([native / 'cv32e40p_emit', GRAPH, out / BASE_BACKEND, 'off'], out / 'logs/off-emit.log', env=env)
    if not same_sources(out / BASE_BACKEND, BASE / BASE_BACKEND): raise ValueError('retained source drift')
    env['WOLVRIX_GRHSIM_CONDITIONAL_MUX_INPUT_CACHE'] = '1'
    run([native / 'cv32e40p_emit', GRAPH, out / CANDIDATE, 'off'], out / 'logs/candidate-emit.log', env=env)
    shutil.copy2(BASE / 'sources.csv', out / 'sources.csv')
    if identity(out / CANDIDATE / 'normalized.json')['sha256'] != identity(out / BASE_BACKEND / 'normalized.json')['sha256']:
        raise ValueError('normalized graph changed')
    old_shape, new_shape = shapes(out / BASE_BACKEND), shapes(out / CANDIDATE)
    for field in ('checked_values', 'supernodes', 'value_slots'):
        if old_shape[field] != new_shape[field]: raise ValueError('activity boundary changed: ' + field)
    sites = cache_sites(out / CANDIDATE)
    if not sites or any(not 1 <= site['keys'] <= 4 for site in sites): raise ValueError('cache coverage mismatch')
    if cone_sites(out / CANDIDATE) != cone_sites(out / BASE_BACKEND): raise ValueError('conditional mux sites changed')
    if family_sites(out / CANDIDATE) != family_sites(out / BASE_BACKEND): raise ValueError('equality family sites changed')
    save(out / 'structure.json', dict(baseline=old_shape, candidate=new_shape,
        cache_sites=sites, feature_off_sources_equal=True, graph_equal=True,
        region_membership_equal=True, conditional_mux_sites_equal=True, equality_family_sites_equal=True))
    compile_model(out / CANDIDATE, out, CANDIDATE, jobs)
    for backend in (BASE_BACKEND, 'verilator'):
        (out / backend).mkdir(exist_ok=True)
        shutil.copy2(retained['binaries'][backend]['path'], out / backend / 'emu')
    backends = [BASE_BACKEND, CANDIDATE, 'verilator']
    save(out / 'build.json', dict(feature='conditional_mux_input_cache', backends=backends, candidate=CANDIDATE,
        comparisons=[BASE_BACKEND, 'verilator'], flags=CFLAGS,
        binaries={b:identity(out / b / 'emu') for b in backends},
        frozen_inputs=[identity(p) for p in (BASE / 'build.json', GRAPH, HARNESS, CXX,
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
