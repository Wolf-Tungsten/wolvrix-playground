#!/usr/bin/env python3
"""One fixed comparison of producer-change invalidation for larger mux cones."""
import argparse
import json
from pathlib import Path
import platform
import re
import shutil

from cv32e40p_compare import ROOT, CXX, CFLAGS, run, save, identity
from cv32e40p_event_regions_compare import check, shapes
from cv32e40p_mux_input_cache_compare import cache_sites
from cv32e40p_repair_compare import (GRAPH, HARNESS, emit_environment, same_sources,
    compile_model, cone_sites, verify, measure, diagnose, native_library, snapshot_source)

BASE = ROOT / 'build/cv32e40p/mux-input-cache-v1'
BASE_BACKEND = 'grhsim_mux_input_cache'
CANDIDATE = 'grhsim_change_trigger_cache'


def change_sites(folder):
    return [dict(root=int(root), sources=int(count), file=p.name)
            for p in sorted(folder.glob('*_sched_*.cpp'))
            for root, count in re.findall(
                r'Conditional mux change-trigger cache: root=(\d+) sources=(\d+)', p.read_text())]


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
                ROOT / 'scripts/cv32e40p_repair_compare.py',
                ROOT / 'scripts/cv32e40p_event_region_counts.py', Path(__file__).resolve()):
        archived = src if src.parent.name == 'scripts' else snapshot_source(tools, src)
        shutil.copy2(archived, snapshot / src.name)
    save(out / 'hypothesis.json', dict(
        change='For existing private conditional mux cones with 5-32 exact scalar boundary sources, invalidate the cached output from source change events instead of comparing every source value at each region visit.',
        expected='Keep multi-input cone outputs valid while avoiding repeated wide key comparisons when an unrelated region dependency causes reevaluation.',
        bounds=dict(input_cache_exact_keys=[1, 4], change_cache_sources=[5, 32],
                    parent_arm_operations=[16, 256], dependency_depth=32, visited_values=256),
        controls='Retain the previously measured exact-key cache for 1-4 source cones. Compare only the additional producer-change triggers against that fixed binary.',
        policy='One fixed structural rule; eight forward/reverse three-backend rounds on CPU96 NUMA1. No profile-based candidate choice, thresholds or extra timing runs.'))
    env = emit_environment(native)
    env.update(CV32_EVENT_REGIONS_SHARED='1', WOLVRIX_GRHSIM_SHARED_EQUALITY_FAMILIES='1',
               WOLVRIX_GRHSIM_CONDITIONAL_MUX_INPUT_CACHE='1',
               WOLVRIX_GRHSIM_CONDITIONAL_MUX_CHANGE_CACHE='0')
    run([native / 'cv32e40p_emit', GRAPH, out / BASE_BACKEND, 'off'], out / 'logs/off-emit.log', env=env)
    if not same_sources(out / BASE_BACKEND, BASE / BASE_BACKEND): raise ValueError('retained source drift')
    env['WOLVRIX_GRHSIM_CONDITIONAL_MUX_CHANGE_CACHE'] = '1'
    run([native / 'cv32e40p_emit', GRAPH, out / CANDIDATE, 'off'], out / 'logs/candidate-emit.log', env=env)
    shutil.copy2(BASE / 'sources.csv', out / 'sources.csv')
    if identity(out / CANDIDATE / 'normalized.json')['sha256'] != identity(BASE / BASE_BACKEND / 'normalized.json')['sha256']:
        raise ValueError('normalized graph changed')
    old_shape, new_shape = shapes(out / BASE_BACKEND), shapes(out / CANDIDATE)
    for field in ('checked_values', 'supernodes', 'value_slots'):
        if old_shape[field] != new_shape[field]: raise ValueError('activity boundary changed: ' + field)
    sites = change_sites(out / CANDIDATE)
    if not sites or any(not 5 <= site['sources'] <= 32 for site in sites):
        raise ValueError('change-trigger coverage missing or outside fixed boundary')
    if cone_sites(out / CANDIDATE) != cone_sites(out / BASE_BACKEND): raise ValueError('conditional mux sites changed')
    if cache_sites(out / CANDIDATE) != cache_sites(out / BASE_BACKEND): raise ValueError('existing exact cache sites changed')
    save(out / 'structure.json', dict(baseline=old_shape, candidate=new_shape, change_sites=sites,
        exact_cache_sites=cache_sites(out / CANDIDATE), feature_off_sources_equal=True, graph_equal=True,
        region_membership_equal=True, conditional_mux_sites_equal=True, exact_cache_sites_equal=True))
    compile_model(out / CANDIDATE, out, CANDIDATE, jobs)
    for backend in (BASE_BACKEND, 'verilator'):
        (out / backend).mkdir(exist_ok=True)
        shutil.copy2(retained['binaries'][backend]['path'], out / backend / 'emu')
    backends = [BASE_BACKEND, CANDIDATE, 'verilator']
    save(out / 'build.json', dict(feature='conditional_mux_producer_change_cache', backends=backends,
        candidate=CANDIDATE, comparisons=[BASE_BACKEND, 'verilator'], flags=CFLAGS,
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
