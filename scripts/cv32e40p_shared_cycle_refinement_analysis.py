#!/usr/bin/env python3
"""Offline source/count accounting for the frozen shared-region cycle refinement.

This script reads existing diagnostics; it never executes a model or supplies
measurements to schedule construction.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

from cv32e40p_compare import ROOT, identity, save
from cv32e40p_event_regions_compare import check, shapes
from cv32e40p_event_region_counts import RegionProbes, instrument_region_source
from cv32e40p_equality_family_compare import family_sites
from cv32e40p_mux_input_cache_compare import cache_sites
from cv32e40p_covered_state_views_compare import sites
from cv32e40p_state_expression_compare import composed
from cv32e40p_repair_compare import cone_sites

BASELINE = 'grhsim_state_expression_inline'
CANDIDATE = 'grhsim_shared_cycle_refinement'


def read(path):
    return json.loads(path.read_text())


def group_phases(folder):
    phases = {}
    for path in sorted(folder.glob('*_sched_*.cpp')):
        for phase, body in re.findall(
                r'void GrhSIM_Cv32Bench::eval_(compute|commit)_batch_\d+\([^\n]*\)\s*\{'
                r'(.*?)(?=void GrhSIM_Cv32Bench::|\Z)', path.read_text(), re.S):
            for group in re.findall(r'// Supernode (\d+):', body):
                if group in phases:
                    raise ValueError('duplicate emitted group ' + group)
                phases[group] = phase
    return phases


def prove_count_sources(folder, diagnostic):
    """Reconstruct instrumentation to bind old diagnostics to current C++.

    Rebuilding identical model sources under another directory changes ELF
    identity (including debug paths). We do not claim the rebuilt ELF is the
    old diagnostic ELF. Exact source/header and probe-label equality is the
    independent bridge for the previously collected behavioral counters.
    """
    origin = read(diagnostic / 'inputs.json')
    if not origin['detailed']:
        raise ValueError('per-value probes required')
    for record in [origin['binary'], *origin['counter_sources']]:
        if identity(record['path']) != record:
            raise ValueError('diagnostic input drift: ' + record['path'])
    data = read(diagnostic / 'counts.json')
    probes = RegionProbes()
    matched = []
    for path in sorted(folder.glob('*.cpp')):
        text = path.read_text()
        if '_sched_' in path.name or path.name.endswith(('_eval.cpp', '_state.cpp')):
            text = instrument_region_source(probes, path.name, text)
        archived = diagnostic / 'grhsim-counts' / path.name
        if text != archived.read_text():
            raise ValueError('reconstructed instrumentation drift: ' + path.name)
        matched.append(path.name)
    for path in folder.glob('*.hpp'):
        if path.read_bytes() != (diagnostic / 'grhsim-counts' / path.name).read_bytes():
            raise ValueError('diagnostic model header drift: ' + path.name)
        matched.append(path.name)
    for workload in ('smoke', 'coremark'):
        if probes.entries != list(data[workload]['counts']):
            raise ValueError('probe labels/order differ: ' + workload)
        counts = data[workload]['counts']
        for prefix, aggregate in [('cmp:', 'scalar_comparisons'), ('chg:', 'scalar_changes')]:
            summed = [sum(v[i] for k, v in counts.items() if k.startswith(prefix)) for i in range(4)]
            if summed != counts[aggregate]:
                raise ValueError('per-value count totals do not close')
    return data, dict(original_model=origin['model'], current_model=identity(folder / 'emu'),
        original_model_elf_equal=origin['model']['sha256'] == identity(folder / 'emu')['sha256'],
        exact_reinstrumented_sources_and_headers=True, probe_order_equal=True,
        matched_files=sorted(matched), probes=len(probes.entries))


def source_model(folder):
    views = sites(folder)
    expressions = composed(folder)
    return dict(shape=shapes(folder), group_phases=group_phases(folder),
        views=views, view_modes=dict(Counter(row['mode'] for row in views)),
        composed=expressions, composed_modes=dict(Counter(row['mode'] for row in expressions)),
        families=family_sites(folder), mux_caches=cache_sites(folder), cones=cone_sites(folder))


def dynamic_model(data, phases):
    counts = data['counts']
    cycles = data['cycles']
    groups = {k[6:]: v for k, v in counts.items() if k.startswith('group:')}
    if groups.keys() != phases.keys():
        raise ValueError('group source/probe coverage mismatch')
    totals = {k: sum(counts.get(k, [])) for k in (
        'scalar_comparisons', 'scalar_changes', 'direct_active_or_executions', 'round')}
    for phase in ('compute', 'commit'):
        totals[phase + '_group_executions'] = sum(sum(v) for k, v in groups.items() if phases[k] == phase)
    for prefix in ('mux_root:', 'mux_true:', 'mux_false:', 'mux_cache_visits:', 'mux_cache_misses:',
                   'decode_visits:', 'decode_initializations:', 'decode_address_changes:'):
        totals[prefix[:-1]] = sum(sum(v) for k, v in counts.items() if k.startswith(prefix))
    return dict(cycles=cycles, totals=totals, per_cycle={k: v / cycles for k, v in totals.items()},
        group_executions=[dict(group=int(k), phase=phases[k], count=sum(v), per_cycle=sum(v) / cycles,
                              by_phase=v) for k, v in sorted(groups.items(), key=lambda item: int(item[0]))])


def analyze(out, baseline_counts, candidate_counts):
    manifest = check(out)
    source = {}
    data = {}
    provenance = {}
    inputs = [identity(out / 'build.json'), identity(out / 'structure.json'), identity(Path(__file__).resolve())]
    for backend, diagnostic in ((BASELINE, baseline_counts), (CANDIDATE, candidate_counts)):
        folder = out / backend
        source[backend] = source_model(folder)
        data[backend], provenance[backend] = prove_count_sources(folder, diagnostic)
        inputs.extend(identity(diagnostic / name) for name in ('inputs.json', 'counts.json'))
        if identity(folder / 'emu') != manifest['binaries'][backend]:
            raise ValueError('model identity mismatch')
    comparisons = {}
    for workload in ('smoke', 'coremark'):
        old = data[BASELINE][workload]
        new = data[CANDIDATE][workload]
        if old['cycles'] != new['cycles'] or old['trace']['sha256'] != new['trace']['sha256']:
            raise ValueError('diagnostic workload differs')
        a, b = old['counts'], new['counts']
        stable_keys = ['round', *sorted(k for k in a if k.startswith('function:'))]
        invariant = {k: a[k] for k in stable_keys if k in b and a[k] == b[k]}
        if a['round'] != b['round']: raise ValueError('fixed-point round count changed')
        dynamic = {backend: dynamic_model(data[backend][workload], source[backend]['group_phases'])
                   for backend in (BASELINE, CANDIDATE)}
        old_ids = {k[4:] for k in a if k.startswith('cmp:')}
        new_ids = {k[4:] for k in b if k.startswith('cmp:')}
        breakdown = {}
        for label, ids in [('common', old_ids & new_ids), ('added', new_ids - old_ids), ('removed', old_ids - new_ids)]:
            breakdown[label] = dict(values=len(ids), ids=sorted(map(int, ids)),
                before_per_cycle=sum(sum(a.get('cmp:' + i, [])) for i in ids) / old['cycles'],
                after_per_cycle=sum(sum(b.get('cmp:' + i, [])) for i in ids) / new['cycles'])
        lost_views = {r['value'] for r in source[BASELINE]['views']} - {r['value'] for r in source[CANDIDATE]['views']}
        breakdown['lost_view_checks'] = dict(values=len(lost_views),
            checked_values=sum('cmp:' + str(i) in b for i in lost_views),
            after_per_cycle=sum(sum(b.get('cmp:' + str(i), [])) for i in lost_views) / new['cycles'])
        comparisons[workload] = dict(models=dynamic, scalar_check_breakdown=breakdown,
            invariant_function_and_round_keys=len(invariant), full_trace_equal=True,
            relative_change_percent={k: 100 * (dynamic[CANDIDATE]['per_cycle'][k] / v - 1) if v else None
                for k, v in dynamic[BASELINE]['per_cycle'].items()})
    source_difference = {}
    for name in ('views', 'composed'):
        old_ids = {row['value'] for row in source[BASELINE][name]}
        new_ids = {row['value'] for row in source[CANDIDATE][name]}
        source_difference[name] = dict(before=len(old_ids), after=len(new_ids),
            retained=sorted(old_ids & new_ids), lost=sorted(old_ids - new_ids),
            added=sorted(new_ids - old_ids))
    source_difference['cones_equal'] = source[BASELINE]['cones'] == source[CANDIDATE]['cones']
    source_difference['mux_cache_roots_and_keys_equal'] = (
        [(r['root'], r['keys']) for r in source[BASELINE]['mux_caches']] ==
        [(r['root'], r['keys']) for r in source[CANDIDATE]['mux_caches']])
    source_difference['normalized_graph_equal'] = (
        identity(out / BASELINE / 'normalized.json')['sha256'] ==
        identity(out / CANDIDATE / 'normalized.json')['sha256'])
    if not source_difference['normalized_graph_equal']:
        raise ValueError('value ID accounting requires the same normalized graph')
    save(out / 'cycle-source-count-analysis.json', dict(
        decision=read(out / 'structure.json')['decision'], models=source, count_provenance=provenance,
        source_difference=source_difference, workloads=comparisons, inputs=inputs,
        limits='Existing diagnostic counts only; not PMU instructions or time attribution. '
               'Group IDs differ, so executions are aggregated by compute/commit phase. '
               'Fewer groups do not imply fewer group executions or less maintenance. '
               'No counts feed generation, thresholds or a next candidate.'))
    print(json.dumps({backend: comparisons['coremark']['models'][backend]['per_cycle']
                      for backend in (BASELINE, CANDIDATE)}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--baseline-counts', type=Path, default=ROOT / 'build/cv32e40p/state-expression-inline-counts-v1')
    parser.add_argument('--candidate-counts', type=Path, default=ROOT / 'build/cv32e40p/shared-cycle-refinement-counts-v1')
    args = parser.parse_args()
    analyze(args.source.resolve(), args.baseline_counts.resolve(), args.candidate_counts.resolve())
