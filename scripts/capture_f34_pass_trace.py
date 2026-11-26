"""Capture native Node inventories and mutations for each F34 pipeline pass."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from benchmark_f29_pass_trace import native_identity, sha256, write_json_atomic
from benchmark_f30_pipeline import verified_input_request, verify_loaded_native
from benchmark_f33_performance import normalized_environment
from capture_f32_pipeline import action
from capture_f34_pipeline import GSIM_ROOT, WORK, package_identity, production_calls
from semantic_node_exchange import verify_bundle


DESIGN = 'design.main'
GSIM_BUNDLES = (
    'split', 'detect-loop', 'topo-sort', 'infer-width', 'dce', 'expr-opt',
    'used-bits', 'split-nodes', 'dce-1', 'constant-analysis', 'dce-2',
    'alias-analysis', 'pattern-detect', 'common-expr', 'dce-3',
)


def graph_inventory(session, directory, stage, graphs, *, observer=None):
    for graph in graphs:
        output = directory / graph
        action(session.semantic_snapshot(design=DESIGN, top=graph, stage=stage, output=str(output)), stage)
        if observer:
            observer.release_snapshot_cache(output.iterdir())


def run_grh(args, request, input_sha, *, observer=None):
    if args.package:
        package, _ = package_identity(args.package)
        sys.meta_path[:] = [finder for finder in sys.meta_path
                            if not type(finder).__module__.startswith('_wolvrix_editable')]
        sys.path.insert(0, str(args.package))
    import wolvrix
    from wolvrix_xs_grhsim import firrtl_canonical_pipeline

    identity = native_identity(wolvrix)
    if args.package:
        verify_loaded_native(args.package, package, identity)
    prefix, window = production_calls(firrtl_canonical_pipeline(remove_singleton_state_axis=False))
    calls = prefix + window
    if args.stop_before_final_dce:
        calls = calls[:-1]
    stages = []
    with wolvrix.Session() as session:
        session.log_level = 'error'
        print('GRH ingest', flush=True)
        action(session.read_sources(**request, out_design=DESIGN, pipeline='ingest'), 'ingest')
        if observer:
            observer.ingested(session)
        for name, instance, keep, options in calls:
            print('GRH ' + instance, flush=True)
            directory = args.output / instance
            graphs = session.semantic_graphs(design=DESIGN)
            if name == 'hier-flatten':
                graph_inventory(session, directory / 'before-modules', 'before-' + instance, graphs, observer=observer)
                traced = [args.top]
            else:
                traced = graphs
            if not traced:
                raise RuntimeError('no GRH SemanticTree at ' + instance)
            for graph in traced:
                action(session.semantic_exchange_start(
                    design=DESIGN, top=graph, output=str(directory / graph),
                    stage='before-' + instance, pass_name=instance.split('#')[0],
                    pass_instance=instance, input_sha256=input_sha), 'start ' + instance)
                if observer:
                    observer.release_snapshot_cache((directory / graph / name
                                                     for name in ('before.nodes.tsv', 'before.connections.tsv')))
            pass_options = dict(options)
            if name == 'alias-analysis':
                pass_options.update(trace_alias_migrations=str(directory / 'alias-analysis-migrations.jsonl'),
                                    trace_input_sha256=input_sha)
            if observer:
                pass_options.update(observer.pass_options(instance, keep, options))
            action(session.run_pass(name, design=DESIGN, keep_declared_symbols=keep, **pass_options), instance)
            for graph in traced:
                action(session.semantic_exchange_finish(design=DESIGN, top=graph,
                                                        stage='after-' + instance), 'finish ' + instance)
                if observer:
                    observer.release_snapshot_cache((directory / graph).iterdir())
            if name == 'hier-flatten':
                remaining = set(session.semantic_graphs(design=DESIGN)) - set(traced)
                graph_inventory(session, directory / 'after-modules', 'after-' + instance,
                                sorted(remaining), observer=observer)
            stage = {'pass': instance, 'bundles': [str(directory / graph) for graph in traced]}
            if name == 'hier-flatten':
                stage.update(before_modules=[str(directory / 'before-modules' / graph) for graph in graphs],
                             after_modules=[str(directory / 'after-modules' / graph) for graph in sorted(remaining)])
            stages.append(stage)
            if observer:
                observer.finished(instance)
        if observer:
            observer.final_inventory(session)
    return identity, stages


def run_gsim(args, input_sha, *, extra_options=(), selection='pipeline'):
    if args.binary is None:
        raise ValueError('GSIM trace capture requires --binary')
    stop = 'CommonExpr' if args.stop_before_final_dce else 'RemoveDeadNodes3'
    bundles = GSIM_BUNDLES[:-1] if args.stop_before_final_dce else GSIM_BUNDLES
    model = args.output / 'model'
    model.mkdir()
    state_port_dir = args.output if getattr(args, 'export_state_actions', False) else None
    state_port_options = ['--state-port-inventory=' + str(state_port_dir)] if state_port_dir else []
    command = [str(args.binary), '--dir=' + str(model), '--stop-after-stage=' + stop,
               '--semantic-node-exchange=' + str(args.output),
               '--semantic-node-exchange-mode=trace', '--semantic-node-exchange-pass=' + selection,
               '--trace-alias-analysis=' + str(args.output / 'alias-analysis-migrations.jsonl'),
               '--trace-input-sha256=' + input_sha, *state_port_options, *extra_options, str(args.firrtl)]
    with (args.output / 'gsim.log').open('x') as log:
        subprocess.run(command, cwd=GSIM_ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    return {'path': str(args.binary), 'sha256': sha256(args.binary), 'command': command}, [
        {'pass': name, 'bundles': [str(args.output / name)]} for name in bundles
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True, choices=('grh', 'gsim'))
    for name in ('firrtl', 'manifest', 'output'):
        parser.add_argument('--' + name, type=lambda path: Path(path).resolve(), required=True)
    for name in ('package', 'binary'):
        parser.add_argument('--' + name, type=lambda path: Path(path).resolve())
    parser.add_argument('--stop-before-final-dce', action='store_true')
    parser.add_argument('--verify-replay', action='store_true',
                        help='independently replay each Node and connection bundle into SQLite')
    args = parser.parse_args()
    if args.output == WORK or not args.output.is_relative_to(WORK):
        parser.error('trace artifacts must be under ptmp/firrtl-ingest/F34/')
    normalized_environment()
    for name in ('WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC', 'WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC_NO_LIVENESS'):
        os.environ.pop(name, None)
    request, sources = verified_input_request(args.firrtl, args.manifest)
    input_sha = next(row['sha256'] for row in sources if row['path'] == str(args.firrtl))
    tops = request.get('tops', [])
    if len(tops) != 1:
        parser.error('the manifest must select exactly one top')
    args.top = tops[0]
    args.output.mkdir(parents=True, exist_ok=False)
    identity, stages = (run_grh(args, request, input_sha) if args.engine == 'grh'
                        else run_gsim(args, input_sha))
    for stage in stages:
        for bundle in map(Path, stage['bundles']):
            for artifact in ('before.nodes.tsv', 'after.nodes.tsv', 'before.connections.tsv',
                             'after.connections.tsv', 'evolution.tsv'):
                if not (bundle / artifact).is_file():
                    raise RuntimeError('missing native pass artifact ' + str(bundle / artifact))
            if args.verify_replay:
                with TemporaryDirectory(dir=args.output) as scratch:
                    report = verify_bundle(bundle, Path(scratch) / 'replay.sqlite3')
                write_json_atomic(bundle / 'verification.json', report)
    write_json_atomic(args.output / 'summary.json', {
        'engine': args.engine, 'sources': sources, 'manifest_sha256': sha256(args.manifest),
        'binary': identity, 'passes': stages, 'verified_replay': args.verify_replay,
    })


if __name__ == '__main__':
    main()
