"""Audit a completed F35 capture against the frozen native pass budgets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_f29_pass_trace import sha256, write_json_atomic
from capture_f35_pipeline import WORK, capture_lock, footer
from f33_guard import positive
from f35_gsim_reference import BUDGETS, SUMMARY, TIMING, load_frozen_reference
from f35_pass_guard import PASSES, REPORT_SCHEMA, Passes
from f35_trace_samples import read_summary
from semantic_node_exchange import SCHEMA as NODE_SCHEMA


def r4_identity(directory, summary):
    """Check the pass and snapshot IDs by reading only their headers and footers."""
    final = summary['final_inventory']
    snapshot = directory / 'R4/nodes.tsv'
    if final['path'] != 'R4/nodes.tsv' or snapshot.stat().st_size != final['bytes']:
        raise ValueError('GRH R4 inventory differs from the completed capture summary')

    after = directory / PASSES[-1] / summary['top'] / 'after.nodes.tsv'
    identities = []
    for path, stage in ((after, 'after-' + PASSES[-1]), (snapshot, 'post-fourth-dead-code-elim')):
        with path.open('rb') as stream:
            header = stream.readline()
        if not header.startswith(b'#meta\t'):
            raise ValueError('GRH inventory metadata missing from ' + str(path))
        metadata = json.loads(header[len(b'#meta\t'):])
        count = footer(path)
        if (not isinstance(metadata, dict) or metadata.get('schema') != NODE_SCHEMA
                or metadata.get('engine') != 'grh'
                or metadata.get('stage') != stage or metadata.get('table') != 'nodes'
                or not all(metadata.get(key) for key in ('run_id', 'graph_id', 'snapshot_id'))
                or count.get('nodeInventoryComplete') is not True
                or type(count.get('rowCount')) is not int or count['rowCount'] < 0):
            raise ValueError('invalid GRH R4 identity in ' + str(path))
        identities.append((metadata['run_id'], metadata['graph_id'], count['rowCount']))
    if identities[0] != identities[1]:
        raise ValueError('GRH R4 snapshot differs from the fourth DCE output')
    return {**final, 'snapshot_id': metadata['snapshot_id'], 'semantic_run_id': metadata['run_id'],
            'graph_id': metadata['graph_id'], 'row_count': count['rowCount']}


def audited_guard(directory, run_id):
    guard = json.loads((directory / 'guard.json').read_text(encoding='utf-8'))
    if (guard.get('schema') != REPORT_SCHEMA or guard.get('run_id') != run_id
            or guard.get('status') != 'completed' or type(guard.get('returncode')) is not int
            or guard['returncode'] != 0 or guard.get('trigger') is not None):
        raise ValueError('GRH guard did not complete the capture run')
    if set(guard['budgets_s']) != set(PASSES) or set(guard['pass_times_s']) != set(PASSES):
        raise ValueError('GRH guard does not cover all production passes')
    budgets = {key: positive(guard['budgets_s'][key], key + ' guard budget') for key in PASSES}
    times = {key: positive(guard['pass_times_s'][key], key + ' guard duration') for key in PASSES}
    tracker = Passes(run_id, budgets)
    events = directory / 'stage-events.jsonl'
    with events.open(encoding='utf-8') as stream:
        for event_index, line in enumerate(stream):
            if event_index >= 2 * len(PASSES):
                raise ValueError('GRH stage journal contains extra events')
            event = json.loads(line)
            pass_index = event_index // 2
            boundary = PASSES[pass_index - 1] if pass_index else 'ingest'
            if not isinstance(event, dict) or event.get('input_boundary') != boundary:
                raise ValueError('GRH stage journal does not follow the production boundaries')
            tracker.consume(event, float('inf'))
            if tracker.trigger is not None:
                raise ValueError('GRH stage journal exceeds its guard budget')
    if tracker.active is not None or tracker.completed != times:
        raise ValueError('GRH native stage events disagree with the completed guard')
    return budgets, times


def audit_timing(directory, reference, *, xmr_limit_s, flatten_limit_s):
    frozen = load_frozen_reference(reference)
    gsim = read_summary(reference, 'gsim')
    grh = read_summary(directory, 'grh')
    run_id = grh.get('run_id')
    expected_reference = {'path': SUMMARY, 'run_id': gsim['run_id'], **frozen['files'][SUMMARY]}
    if (not run_id or frozen['run_id'] != gsim['run_id'] or grh['top'] != gsim['top']
            or grh['inputs'] != gsim['inputs'] or grh['reference'] != expected_reference
            or tuple(stage['pass'] for stage in grh['passes']) != PASSES):
        raise ValueError('GRH capture does not match the frozen reference or production sequence')
    inventory = r4_identity(directory, grh)
    guard_budgets, guard_times = audited_guard(directory, run_id)
    paired = json.loads((reference / BUDGETS).read_text(encoding='utf-8'))['pass_budgets']
    unpaired = {PASSES[0]: positive(xmr_limit_s, 'xmr-resolve limit'),
                PASSES[1]: positive(flatten_limit_s, 'hier-flatten limit')}
    passes = []
    for name in PASSES:
        budget = paired[name] if name in paired else {'budget_s': unpaired[name]}
        actual = guard_times[name]
        row = {'grh_pass': name, **budget, 'actual_s': actual, 'guard_budget_s': guard_budgets[name],
               'passed': actual <= budget['budget_s']}
        if name in paired:
            row['grh_over_gsim'] = actual / budget['reference_s']
        passes.append(row)
    return {'schema': 'wolvrix.f35.timing-report.v1', 'passed': all(row['passed'] for row in passes),
            'grh_run_id': run_id, 'gsim_run_id': frozen['run_id'],
            'gsim_native_timing_sha256': frozen['files'][TIMING]['sha256'],
            'grh_guard_sha256': sha256(directory / 'guard.json'),
            'grh_stage_events_sha256': sha256(directory / 'stage-events.jsonl'),
            'grh_final_inventory': inventory, 'passes': passes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('grh', 'reference', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--xmr-limit', type=float, required=True)
    parser.add_argument('--flatten-limit', type=float, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.output == WORK or not args.output.is_relative_to(WORK):
        parser.error('timing report must be beneath ' + str(WORK))
    try:
        with capture_lock('grh', read_only=True):
            report = audit_timing(args.grh, args.reference, xmr_limit_s=args.xmr_limit,
                                  flatten_limit_s=args.flatten_limit)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(args.output, report)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f'{error}\n')
    print('| GRH call | GSIM timer | Reference (s) | Budget (s) | GRH (s) | GRH/GSIM | Result |')
    print('| --- | --- | ---: | ---: | ---: | ---: | --- |')
    for row in report['passes']:
        reference = f"{row['reference_s']:.6f}" if 'reference_s' in row else '-'
        ratio = f"{row['grh_over_gsim']:.4f}" if 'grh_over_gsim' in row else '-'
        print(f"| {row['grh_pass']} | {row.get('gsim_pass_instance', '-')} | {reference} | "
              f"{row['budget_s']:.6f} | {row['actual_s']:.6f} | {ratio} | "
              f"{'pass' if row['passed'] else 'over budget'} |")
    print(f'Timing report: {args.output}')
    return 0 if report['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
