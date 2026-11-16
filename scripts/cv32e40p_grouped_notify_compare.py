#!/usr/bin/env python3
"""One fixed comparison of producer-region aggregation for change-cache notifications."""
import argparse
import json
from pathlib import Path
import platform
import re
import shutil

from cv32e40p_compare import ROOT, CXX, CFLAGS, run, save, identity
from cv32e40p_event_regions_compare import check, shapes
from cv32e40p_mux_input_cache_compare import cache_sites
from cv32e40p_change_trigger_cache_compare import change_sites
from cv32e40p_repair_compare import (GRAPH, HARNESS, emit_environment, same_sources,
    compile_model, cone_sites, verify, measure, diagnose, native_library, snapshot_source)

BASE = ROOT / 'build/cv32e40p/change-trigger-cache-v1'
BASE_BACKEND = 'grhsim_change_trigger_cache'
RETAINED = 'grhsim_mux_input_cache'
CANDIDATE = 'grhsim_grouped_notify_cache'


def notify_groups(folder):
    return [dict(producer=int(a), bucket=int(b), sources=int(c), targets=int(d), reuse=bool(int(e)), file=p.name)
            for p in sorted(folder.glob('*_sched_*.cpp'))
            for a,b,c,d,e in re.findall(r'Conditional mux notify group: producer=(\d+) bucket=(\d+) sources=(\d+) targets=(\d+) reuse=(\d+)',p.read_text())]


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
                ROOT / 'scripts/cv32e40p_event_region_counts.py',
                ROOT / 'scripts/cv32e40p_grouped_notify_analysis.py', Path(__file__).resolve()):
        archived = src if src.parent.name == 'scripts' else snapshot_source(tools, src)
        shutil.copy2(archived, snapshot / src.name)
    save(out / 'hypothesis.json', dict(
        change='Aggregate change-cache notifications at the producing compute region exit. Share identical source subsets across cache targets; reuse existing deferred predicates only for an exactly equal source set.',
        expected='Replace repeated writes to persistent dirty bits with local predicates and one update per producer-region/target. Preserve exact cache invalidation and every consumer execution.',
        controls='Same change-cache sites and source sets as TNO0024. Intra-region consumers, single-source notifications, state commits and inputs retain immediate notification. No region membership or cache eligibility changes.',
        bounds=dict(min_sources_per_producer_group=2),
        policy='One fixed structural rule; eight forward/reverse four-backend rounds on CPU96 NUMA1. No profile-based site selection or threshold changes.'))
    env = emit_environment(native)
    env.update(CV32_EVENT_REGIONS_SHARED='1', WOLVRIX_GRHSIM_SHARED_EQUALITY_FAMILIES='1',
               WOLVRIX_GRHSIM_CONDITIONAL_MUX_INPUT_CACHE='1',
               WOLVRIX_GRHSIM_CONDITIONAL_MUX_CHANGE_CACHE='1',
               WOLVRIX_GRHSIM_CONDITIONAL_MUX_CHANGE_GROUPED='0')
    run([native / 'cv32e40p_emit', GRAPH, out / BASE_BACKEND, 'off'], out / 'logs/off-emit.log', env=env)
    if not same_sources(out / BASE_BACKEND, BASE / BASE_BACKEND): raise ValueError('retained source drift')
    env['WOLVRIX_GRHSIM_CONDITIONAL_MUX_CHANGE_GROUPED'] = '1'
    run([native / 'cv32e40p_emit', GRAPH, out / CANDIDATE, 'off'], out / 'logs/candidate-emit.log', env=env)
    shutil.copy2(BASE / 'sources.csv', out / 'sources.csv')
    if identity(out / CANDIDATE / 'normalized.json')['sha256'] != identity(BASE / BASE_BACKEND / 'normalized.json')['sha256']:
        raise ValueError('normalized graph changed')
    old_shape, new_shape = shapes(out / BASE_BACKEND), shapes(out / CANDIDATE)
    for field in ('checked_values', 'supernodes', 'value_slots'):
        if old_shape[field] != new_shape[field]: raise ValueError('activity boundary changed: ' + field)
    sites = change_sites(out / CANDIDATE)
    groups = notify_groups(out / CANDIDATE)
    if not groups: raise ValueError('no grouped notifications')
    if sites != change_sites(out / BASE_BACKEND): raise ValueError('change-cache eligibility drift')
    if not sites or any(not 5 <= site['sources'] <= 32 for site in sites):
        raise ValueError('change-trigger coverage missing or outside fixed boundary')
    if cone_sites(out / CANDIDATE) != cone_sites(out / BASE_BACKEND): raise ValueError('conditional mux sites changed')
    if cache_sites(out / CANDIDATE) != cache_sites(out / BASE_BACKEND): raise ValueError('existing exact cache sites changed')
    save(out / 'structure.json', dict(baseline=old_shape, candidate=new_shape, change_sites=sites, notify_groups=groups,
        exact_cache_sites=cache_sites(out / CANDIDATE), feature_off_sources_equal=True, graph_equal=True,
        region_membership_equal=True, conditional_mux_sites_equal=True, exact_cache_sites_equal=True))
    compile_model(out / CANDIDATE, out, CANDIDATE, jobs)
    for backend in (RETAINED, BASE_BACKEND, 'verilator'):
        (out / backend).mkdir(exist_ok=True)
        shutil.copy2(retained['binaries'][backend]['path'], out / backend / 'emu')
    backends = [RETAINED, BASE_BACKEND, CANDIDATE, 'verilator']
    save(out / 'build.json', dict(feature='conditional_mux_grouped_change_notifications', backends=backends,
        candidate=CANDIDATE, comparisons=[RETAINED, BASE_BACKEND, 'verilator'], flags=CFLAGS,
        binaries={b:identity(out / b / 'emu') for b in backends},
        frozen_inputs=[identity(p) for p in (BASE / 'build.json', GRAPH, HARNESS, CXX,
            out / 'hypothesis.json', out / 'structure.json', out / 'verification.json', out / 'sources.csv',
            *native.iterdir(), *snapshot.iterdir())]))
    print(json.dumps(dict(sites=sites, groups=groups, structure=new_shape), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('build', 'verify', 'measure', 'diagnose'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tools', type=Path, default=ROOT / 'build/cv32e40p/tools')
    parser.add_argument('--jobs', type=int, default=12)
    args = parser.parse_args()
    if args.stage == 'build': build(args.output.resolve(), args.tools.resolve(), args.jobs)
    else: {'verify':verify, 'measure':measure, 'diagnose':diagnose}[args.stage](args.output.resolve())
