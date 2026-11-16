#!/usr/bin/env python3
"""One fixed structural factoring of scheduler and cache notification source sets."""
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
from cv32e40p_grouped_notify_compare import notify_groups
from cv32e40p_repair_compare import (GRAPH, HARNESS, emit_environment, same_sources,
    compile_model, cone_sites, verify, measure, diagnose, native_library, snapshot_source)

BASE = ROOT / 'build/cv32e40p/grouped-notify-cache-v1'
BASE_BACKEND = 'grhsim_grouped_notify_cache'
RETAINED = 'grhsim_mux_input_cache'
CANDIDATE = 'grhsim_joint_notify_cache'


def joint_plans(folder):
    return [dict(producer=int(a), buckets=int(b), sources=int(c), before=int(d), after=int(e), file=p.name)
            for p in sorted(folder.glob('*_sched_*.cpp'))
            for a,b,c,d,e in re.findall(r'Joint notify plan: producer=(\d+) buckets=(\d+) sources=(\d+) before=(\d+) after=(\d+)',p.read_text())]


def check_partition(before, after, plans):
    """Independently reconstruct destination source sets from generated code."""
    reports=[]
    for plan in plans:
        filename, producer=plan['file'],str(plan['producer'])
        old=(before/filename).read_text();new=(after/filename).read_text()
        source_sets={}
        pattern=r'(grhsim_any_changed|grhsim_mux_notify_group)_'+producer+r'_(\d+) = static_cast<bool>\([^\n]+? \| \(?grhsim_changed_(\d+)\)?\);'
        for kind, target, source in re.findall(pattern,old):
            source_sets.setdefault(('deferred' if kind=='grhsim_any_changed' else 'cache',int(target)),set()).add(int(source))
        buckets=[]
        pattern=r'Joint notify bucket: producer='+producer+r' bucket=(\d+) sources=([\d,]*) deferred=([\d,]*) cache=([\d,]*)'
        parse=lambda text:[int(v) for v in text.split(',') if v]
        all_sources=set();reconstructed={}
        for index,sources,groups,caches in re.findall(pattern,new):
            values=set(parse(sources))
            if all_sources&values:raise ValueError('joint source appears in multiple buckets')
            all_sources |= values
            destinations=[('deferred',i) for i in parse(groups)]+[('cache',i) for i in parse(caches)]
            for destination in destinations:reconstructed.setdefault(destination,set()).update(values)
            buckets.append(dict(index=int(index),sources=sorted(values),destinations=destinations))
        if len(buckets)!=plan['buckets'] or len(all_sources)!=plan['sources']:
            raise ValueError('joint plan size mismatch')
        expected={k:v&all_sources for k,v in source_sets.items() if v&all_sources}
        if reconstructed!=expected:raise ValueError('factored target source set differs from original code')
        original=sum(map(len,expected.values()))
        factored=len(all_sources)+sum(len(b['destinations']) for b in buckets)
        if original!=plan['before'] or factored!=plan['after']:raise ValueError('static contribution count mismatch')
        reports.append(dict(producer=int(producer),buckets=buckets,original=original,factored=factored,
                            exact_target_sets_equal=True,disjoint_source_sets=True))
    return reports


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
                ROOT / 'scripts/cv32e40p_joint_notify_analysis.py', Path(__file__).resolve()):
        archived = src if src.parent.name == 'scripts' else snapshot_source(tools, src)
        shutil.copy2(archived, snapshot / src.name)
    save(out / 'hypothesis.json', dict(
        change='Partition sources by their exact scheduler/cache destination membership. Accumulate each source once and reconstruct each exact target predicate at producer exit.',
        expected='Remove duplicated OR contributions across grouped-cache and ordinary deferred scheduler predicates without changing any target source set or cache miss.',
        controls='Identical grouped-notification cache sites and graph; nondeferred, same-region, packed/direct/shared/strict overlays retain existing lowering.',
        static_gate='Enable only when source contributions plus bucket-to-target reconstruction contributions are strictly fewer than the original contributions. No runtime data is read by the emitter or build stage.',
        bounds=dict(max_targets=64, max_sources=1024, max_buckets=64),
        policy='One fixed candidate and one eight-round forward/reverse four-backend comparison on CPU96 NUMA1. Runtime data is validation/evaluation only, never a selection input or tuning feedback.'))
    env = emit_environment(native)
    env.update(CV32_EVENT_REGIONS_SHARED='1', WOLVRIX_GRHSIM_SHARED_EQUALITY_FAMILIES='1',
               WOLVRIX_GRHSIM_CONDITIONAL_MUX_INPUT_CACHE='1',
               WOLVRIX_GRHSIM_CONDITIONAL_MUX_CHANGE_CACHE='1',
               WOLVRIX_GRHSIM_CONDITIONAL_MUX_CHANGE_GROUPED='1',
               WOLVRIX_GRHSIM_CONDITIONAL_MUX_CHANGE_JOINT='0')
    run([native / 'cv32e40p_emit', GRAPH, out / BASE_BACKEND, 'off'], out / 'logs/off-emit.log', env=env)
    if not same_sources(out / BASE_BACKEND, BASE / BASE_BACKEND): raise ValueError('retained source drift')
    env['WOLVRIX_GRHSIM_CONDITIONAL_MUX_CHANGE_JOINT'] = '1'
    run([native / 'cv32e40p_emit', GRAPH, out / CANDIDATE, 'off'], out / 'logs/candidate-emit.log', env=env)
    shutil.copy2(BASE / 'sources.csv', out / 'sources.csv')
    if identity(out / CANDIDATE / 'normalized.json')['sha256'] != identity(BASE / BASE_BACKEND / 'normalized.json')['sha256']:
        raise ValueError('normalized graph changed')
    old_shape, new_shape = shapes(out / BASE_BACKEND), shapes(out / CANDIDATE)
    for field in ('checked_values', 'supernodes', 'value_slots'):
        if old_shape[field] != new_shape[field]: raise ValueError('activity boundary changed: ' + field)
    sites = change_sites(out / CANDIDATE)
    groups = notify_groups(out / CANDIDATE)
    plans = joint_plans(out / CANDIDATE)
    if not plans or any(p['after'] >= p['before'] for p in plans): raise ValueError('no statically profitable joint plan')
    partitions = check_partition(out / BASE_BACKEND, out / CANDIDATE, plans)
    save(out / 'joint-partition.json', partitions)
    if groups != notify_groups(out / BASE_BACKEND): raise ValueError('notification sites changed')
    if sites != change_sites(out / BASE_BACKEND): raise ValueError('change-cache eligibility drift')
    if not sites or any(not 5 <= site['sources'] <= 32 for site in sites):
        raise ValueError('change-trigger coverage missing or outside fixed boundary')
    if cone_sites(out / CANDIDATE) != cone_sites(out / BASE_BACKEND): raise ValueError('conditional mux sites changed')
    if cache_sites(out / CANDIDATE) != cache_sites(out / BASE_BACKEND): raise ValueError('existing exact cache sites changed')
    save(out / 'structure.json', dict(baseline=old_shape, candidate=new_shape, change_sites=sites, notify_groups=groups, joint_plans=plans,
        exact_cache_sites=cache_sites(out / CANDIDATE), feature_off_sources_equal=True, graph_equal=True,
        region_membership_equal=True, conditional_mux_sites_equal=True, exact_cache_sites_equal=True))
    compile_model(out / CANDIDATE, out, CANDIDATE, jobs)
    for backend in (RETAINED, BASE_BACKEND, 'verilator'):
        (out / backend).mkdir(exist_ok=True)
        shutil.copy2(retained['binaries'][backend]['path'], out / backend / 'emu')
    backends = [RETAINED, BASE_BACKEND, CANDIDATE, 'verilator']
    save(out / 'build.json', dict(feature='conditional_mux_joint_notification_factoring', backends=backends,
        candidate=CANDIDATE, comparisons=[RETAINED, BASE_BACKEND, 'verilator'], flags=CFLAGS,
        binaries={b:identity(out / b / 'emu') for b in backends},
        frozen_inputs=[identity(p) for p in (BASE / 'build.json', GRAPH, HARNESS, CXX,
            out / 'hypothesis.json', out / 'structure.json', out / 'joint-partition.json', out / 'verification.json', out / 'sources.csv',
            *native.iterdir(), *snapshot.iterdir())]))
    print(json.dumps(dict(sites=sites, groups=groups, plans=plans, structure=new_shape), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('build', 'verify', 'measure', 'diagnose'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tools', type=Path, default=ROOT / 'build/cv32e40p/tools')
    parser.add_argument('--jobs', type=int, default=12)
    args = parser.parse_args()
    if args.stage == 'build': build(args.output.resolve(), args.tools.resolve(), args.jobs)
    else: {'verify':verify, 'measure':measure, 'diagnose':diagnose}[args.stage](args.output.resolve())
