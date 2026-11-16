#!/usr/bin/env python3
"""Account for fixed repair comparisons without choosing a faster candidate."""
import argparse
import json
from pathlib import Path

from cv32e40p_compare import identity, save, signature, summarize_named
from cv32e40p_conditional_mux_analysis import perf_counts
from cv32e40p_event_regions_compare import check
from cv32e40p_repair_compare import BASE_BACKEND


def read(path):
    return json.loads(path.read_text())


def counter_rates(observed):
    cycles, counts = observed['cycles'], observed['counts']
    if cycles <= 0 or any(len(v) != 4 or any(n < 0 for n in v) for v in counts.values()):
        raise ValueError('invalid counter shape or cycles')
    for prefix, total in (('cmp:', 'scalar_comparisons'), ('chg:', 'scalar_changes')):
        values = [v for k, v in counts.items() if k.startswith(prefix)]
        if not values or [sum(v[p] for v in values) for p in range(4)] != counts[total]:
            raise ValueError('per-value accounting differs from aggregate')
    return {k: [n / cycles for n in v] for k, v in counts.items()}


def analyze(source, directories, retained_backend=BASE_BACKEND):
    dest = source / 'repair-analysis.json'
    if dest.exists():
        raise FileExistsError(dest)
    manifest = check(source)
    candidate, backends = manifest['candidate'], manifest['backends']
    functional = read(source / 'functional.json')
    if functional['status'] != 'pass' or functional['build'] != identity(source / 'build.json'):
        raise ValueError('functional identity mismatch')
    reference = functional['workloads']['coremark'][candidate]
    diagnostic = read(source / 'diagnostics.json')
    if diagnostic['build'] != identity(source / 'build.json'):
        raise ValueError('PMU identity mismatch')
    for row in diagnostic['runs'].values():
        if signature(row) != signature(reference):
            raise ValueError('PMU workload mismatch')
    pmu = {b: perf_counts(source / (b + '-stat.csv'), reference['cycles']) for b in backends}
    snapshots, rates, counter_inputs = {}, {}, []
    for backend, folder in directories.items():
        inputs, data = read(folder / 'inputs.json'), read(folder / 'counts.json')['coremark']
        actual = identity(Path(inputs['model']['path']))
        if actual != inputs['model'] or any(actual[k] != manifest['binaries'][backend][k] for k in ('sha256', 'bytes')):
            raise ValueError('counter binary mismatch: ' + backend)
        if not inputs['detailed'] or data['cycles'] != reference['cycles'] or data['trace']['sha256'] != reference['trace']['sha256']:
            raise ValueError('counter workload mismatch: ' + backend)
        rates[backend] = counter_rates(data)
        snapshots[backend] = {k: v for k, v in rates[backend].items()
                              if k.startswith(('round', 'scalar_', 'direct_active_or_', 'group:'))}
        counter_inputs.extend(identity(folder / name) for name in ('inputs.json', 'counts.json'))
    invariants = None
    previous = manifest['comparisons'][0]
    if manifest['feature'] == 'shared_region_order_guard' and candidate in rates and previous in rates:
        # These numeric IDs may be paired only because this comparison proved
        # identical graph, groups and membership; only the local order changed.
        structure = read(source / 'structure.json')
        if not structure['graph_equal'] or not structure['membership_equal']:
            raise ValueError('cannot pair graph-local IDs')
        keys = {k for k in rates[previous] | rates[candidate]
                if k.startswith(('group:', 'cmp:', 'chg:')) or k in ('round', 'scalar_comparisons', 'scalar_changes')}
        differences = {k: dict(before=rates[previous].get(k), after=rates[candidate].get(k))
                       for k in sorted(keys) if rates[previous].get(k) != rates[candidate].get(k)}
        invariants = dict(checked=len(keys), differences=differences)
    fields = ('bytes', 'instructions', 'branches', 'calls', 'memory_operand_instructions',
              'stack_operand_instructions', 'compare_or_test', 'cmov_or_setcc')
    machine = {}
    for backend, functions in diagnostic['models'].items():
        machine[backend] = dict(functions=functions, totals={k: sum(f[k] for f in functions) for k in fields})
    candidate_instructions = pmu[candidate]['per_guest_cycle']['instructions:u']
    instruction_deltas = {b: dict(
        per_guest_cycle=candidate_instructions - pmu[b]['per_guest_cycle']['instructions:u'],
        percent=100 * (candidate_instructions / pmu[b]['per_guest_cycle']['instructions:u'] - 1))
        for b in manifest['comparisons']}
    result = dict(candidate=candidate, comparisons=read(source / 'summary.json'), pmu=pmu,
        instruction_deltas=instruction_deltas, machine=machine, counters=snapshots,
        ordering_counter_invariants=invariants,
        retained_relative_to_verilator=summarize_named(read(source / 'pairs.json'), retained_backend, 'verilator'),
        build_wall_s={p.name: read(p)['wall_s'] for p in sorted((source / 'logs').glob('*.result.json'))},
        inputs=[identity(source / name) for name in ('build.json', 'functional.json', 'diagnostics.json',
            'structure.json', 'summary.json', 'pairs.json')] + counter_inputs +
            [identity(source / (b + '-stat.csv')) for b in backends] + [identity(Path(__file__).resolve())],
        limits='PMU is one separate execution per backend. Static stack operands are not dynamic spill counts. '
               'Diagnostic counters describe IR scheduling and cannot be added to retired instructions. '
               'No cross-experiment timing subtraction or candidate selection.')
    save(dest, result)
    print(json.dumps(dict(candidate=candidate, instruction_deltas=instruction_deltas,
        counter_totals={b:{k:sum(v) for k,v in c.items() if k.startswith(('scalar_', 'round', 'direct_active_or_'))}
                        for b,c in snapshots.items()}, ordering_counter_invariants=invariants), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--counts', action='append', default=[], metavar='BACKEND=DIRECTORY')
    args = parser.parse_args()
    directories = dict(item.split('=', 1) for item in args.counts)
    analyze(args.source.resolve(), {b: Path(p).resolve() for b, p in directories.items()})
