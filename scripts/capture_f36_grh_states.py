"""Capture GRH state declarations, actions, and optional Nodes after the fourth DCE."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import uuid

from benchmark_f29_pass_trace import native_identity, sha256, write_json_atomic
from benchmark_f30_pipeline import verified_input_request, verify_loaded_native
from benchmark_f33_performance import environment, normalized_environment
from capture_f32_pipeline import table_artifact
from capture_f34_pipeline import package_identity, production_calls
from capture_f34_pass_trace import DESIGN
from capture_f35_pipeline import action, footer
from f35_pass_guard import F36_PASSES, reference_budgets, run_guarded, stage_event_options


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'ptmp/firrtl-ingest/F36'
R4_STAGE = 'post-fourth-dead-code-elim'
NODE_TABLES = ('nodes.tsv', 'node-endpoints.tsv', 'connections.tsv', 'bit-slices.tsv')


class PassObserver:
    def __init__(self, run_id):
        self.run_id = run_id
        self.last_boundary = 'ingest'

    def options(self, instance):
        return stage_event_options(self.run_id, instance, self.last_boundary)

    def finished(self, instance):
        self.last_boundary = instance


def child(args, request, inputs):
    sys.meta_path[:] = [finder for finder in sys.meta_path
                        if not type(finder).__module__.startswith('_wolvrix_editable')]
    sys.path.insert(0, str(args.package))
    import wolvrix
    from wolvrix_xs_grhsim import firrtl_canonical_pipeline

    package, package_details = package_identity(args.package)
    identity = native_identity(wolvrix)
    verify_loaded_native(args.package, package, identity)
    prefix, window = production_calls(firrtl_canonical_pipeline())
    calls = prefix + window
    if tuple(row[1] for row in calls) != F36_PASSES:
        raise ValueError('GRH production pass sequence does not end at the requested R4 boundary')
    observer = PassObserver(args.run_id)
    output = args.output / 'state-actions.jsonl'
    with wolvrix.Session() as session:
        session.log_level = 'error'
        session.diagnostics_raise_min_level = 'none'
        action(session.read_sources(**request, out_design=DESIGN, pipeline='ingest'), 'ingest')
        for name, instance, keep, options in calls:
            pass_options = dict(options)
            pass_options.update(observer.options(instance))
            action(session.run_pass(name, design=DESIGN, keep_declared_symbols=keep,
                                    **pass_options), instance)
            observer.finished(instance)
        if args.export_nodes:
            action(session.semantic_snapshot(design=DESIGN, top=args.top, output=str(args.output),
                                             stage=R4_STAGE, export_state_actions=True),
                   'final GRH Node and state/action inventories')
        else:
            action(session.semantic_state_actions(design=DESIGN, top=args.top, path=str(output),
                                                  stage=R4_STAGE),
                   'final GRH state/action inventory')
    _, sources = verified_input_request(args.firrtl, args.manifest)
    if sources != inputs['sources'] or sha256(args.manifest) != inputs['manifest_sha256']:
        raise ValueError('GRH inputs changed during capture')
    inventory_counts = footer(output)
    report = {'schema': 'wolvrix.f36.grh-state-capture.v1', 'complete': True,
              'provenance': 'execution-captured', 'run_id': args.run_id, 'top': args.top,
              'input': str(args.firrtl),
              'input_sha256': next(row['sha256'] for row in sources if row['language'] == 'firrtl'),
              'manifest_sha256': inputs['manifest_sha256'], 'sources': sources, 'inputs': inputs,
              'package': str(args.package),
              'package_identity_sha256': sha256(args.package / 'identity.json'),
              'package_source_revision': package['source_revision'], 'package_details': package_details,
              'binary': identity, 'environment': environment(), 'pass_instances': [row[1] for row in calls],
              'pass_configuration': [{'name': name, 'instance': instance, 'keep_declared_symbols': keep,
                                      'options': options} for name, instance, keep, options in calls],
              'stage': R4_STAGE, 'inventory': str(output),
              'inventory_sha256': sha256(output), 'inventory_counts': inventory_counts}
    if args.export_nodes:
        with output.open('rb') as stream:
            header = stream.readline()
        if not header.startswith(b'#meta\t'):
            raise ValueError('missing R4 state/action metadata')
        state_metadata = json.loads(header.removeprefix(b'#meta\t'))
        tables = {name: table_artifact(args.output / name) for name in NODE_TABLES}
        for name, table in tables.items():
            metadata = table['metadata']
            session = metadata.get('exchange_session_id', metadata.get('session_id'))
            if (metadata.get('engine') != 'grh' or metadata.get('stage') != R4_STAGE or
                    metadata.get('run_id') != state_metadata['run_id'] or
                    session != state_metadata['exchange_session_id']):
                raise ValueError('GRH state/action inventory and Node table differ in capture identity: ' + name)
        report['node_tables'] = tables
    write_json_atomic(args.output / 'capture.json', report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firrtl', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--work-root', type=Path, default=WORK)
    parser.add_argument('--xmr-limit', type=float, default=180)
    parser.add_argument('--flatten-limit', type=float, default=300)
    parser.add_argument('--min-free-bytes', type=int, default=0)
    parser.add_argument('--export-nodes', action='store_true')
    parser.add_argument('--child-run-id', help=argparse.SUPPRESS)
    args = parser.parse_args()
    for name in ('firrtl', 'manifest', 'reference', 'package', 'output', 'work_root'):
        setattr(args, name, getattr(args, name).resolve())
    if args.output == args.work_root or not args.output.is_relative_to(args.work_root):
        parser.error('capture output must be beneath work-root')
    normalized_environment()
    for name in ('WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC', 'WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC_NO_LIVENESS'):
        os.environ.pop(name, None)
    request, sources = verified_input_request(args.firrtl, args.manifest)
    if request.get('tops') != ['SimTop']:
        parser.error('F36 SimTop capture requires exactly the SimTop top')
    args.top = 'SimTop'
    if sum(row['language'] == 'firrtl' for row in sources) != 1:
        parser.error('manifest must identify the requested single FIRRTL input')
    inputs = {'manifest': str(args.manifest), 'manifest_sha256': sha256(args.manifest),
              'sources': sources, 'top': args.top, 'firrtl_options': request.get('firrtl_options', {})}
    args.run_id = args.child_run_id or f'f36-grh-{uuid.uuid4().hex}'
    if args.child_run_id:
        child(args, request, inputs)
        return 0
    from f35_gsim_reference import load_frozen_reference

    if args.output.exists():
        raise ValueError('refusing to overwrite existing F36 GRH capture: ' + str(args.output))
    frozen = load_frozen_reference(args.reference)
    reference = json.loads((args.reference / 'summary.json').read_text())
    if (reference.get('schema') != 'wolvrix.f35.capture.v1' or reference.get('complete') is not True or
            reference.get('engine') != 'gsim' or frozen['run_id'] != reference.get('run_id') or
            reference.get('inputs') != inputs):
        raise ValueError('F35 frozen reference does not match the requested SimTop production capture')
    budgets = reference_budgets(args.reference / 'native-timing.jsonl',
                                xmr_limit_s=args.xmr_limit, flatten_limit_s=args.flatten_limit)
    # GSIM removes singleton axes during ingest, without a separate pass timer.
    budgets['remove-singleton-state-axis#0'] = budgets['hier-flatten#0']
    args.output.mkdir(parents=True)
    command = [sys.executable, str(Path(__file__).resolve()), '--firrtl', str(args.firrtl),
               '--manifest', str(args.manifest), '--reference', str(args.reference),
               '--package', str(args.package), '--output', str(args.output),
               '--work-root', str(args.work_root), '--xmr-limit', str(args.xmr_limit),
               '--flatten-limit', str(args.flatten_limit), '--min-free-bytes', str(args.min_free_bytes),
               '--child-run-id', args.run_id]
    if args.export_nodes:
        command.append('--export-nodes')
    result = run_guarded(command, args.output, run_id=args.run_id, budgets=budgets,
                         min_free_bytes=args.min_free_bytes, passes=F36_PASSES)
    if result:
        print(json.dumps(json.loads((args.output / 'guard.json').read_text()), ensure_ascii=False))
    else:
        report = json.loads((args.output / 'capture.json').read_text())
        if report['inputs'] != inputs or tuple(report['pass_instances']) != F36_PASSES:
            raise ValueError('GRH child did not capture the requested inputs and production pass sequence')
        if args.export_nodes and set(report.get('node_tables', {})) != set(NODE_TABLES):
            raise ValueError('GRH child did not capture the requested R4 Node inventories')
        report['guard'] = json.loads((args.output / 'guard.json').read_text())
        report['reference'] = {'run_id': frozen['run_id'], 'path': str(args.reference),
                               'summary_sha256': frozen['files']['summary.json']['sha256']}
        write_json_atomic(args.output / 'capture.json', report)
        print(f"F36 GRH R4 inventory complete: {report['inventory']}")
        if args.export_nodes:
            print(f"F35 GRH R4 Node inventory complete: {args.output / 'nodes.tsv'}")
    return result


if __name__ == '__main__':
    raise SystemExit(main())
