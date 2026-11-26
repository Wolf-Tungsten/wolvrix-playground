"""Capture the frozen GSIM reference and guarded GRH F35 traces."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
import uuid

from benchmark_f29_pass_trace import sha256, write_json_atomic
from benchmark_f30_pipeline import verified_input_request
from benchmark_f33_performance import environment, normalized_environment
from capture_f32_pipeline import action
from capture_f34_pass_trace import DESIGN, run_grh
from release_f32_cache import release_files
from semantic_node_exchange import verify_bundle


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'ptmp/firrtl-ingest/F35'
TRACE_FILES = ('before.nodes.tsv', 'after.nodes.tsv', 'before.connections.tsv',
               'after.connections.tsv', 'evolution.tsv')


def footer(path):
    with path.open('rb') as stream:
        stream.seek(0, os.SEEK_END)
        length = stream.tell()
        stream.seek(max(0, length - 16384))
        tail = stream.read()
    if not tail.endswith(b'\n'):
        raise ValueError('unterminated capture artifact: ' + str(path))
    last = tail[:-1].rsplit(b'\n', 1)[-1]
    record = json.loads(last.rsplit(b'\t', 1)[-1])
    if record.get('complete') is not True:
        raise ValueError('incomplete capture artifact: ' + str(path))
    return record


def artifact(path, root):
    return {'path': str(path.relative_to(root)), 'bytes': path.stat().st_size,
            'sha256': sha256(path)}


def validate_stages(args, stages):
    for stage in stages:
        for directory in map(Path, stage['bundles']):
            records = {name: footer(directory / name) for name in TRACE_FILES}
            replay = records['evolution.tsv']
            if replay.get('replayComplete') is not True:
                raise ValueError('incomplete trace: ' + str(directory))
            for side in ('before', 'after'):
                for noun in ('nodes', 'connections'):
                    name = f'{side}.{noun}.tsv'
                    key = side + noun[:-1].capitalize() + 'Count'
                    if records[name]['rowCount'] != replay[key]:
                        raise ValueError('trace inventory count disagrees: ' + str(directory / name))
            if args.verify_replay:
                with TemporaryDirectory(dir=os.environ.get('TMPDIR', args.output.parent)) as scratch:
                    report = verify_bundle(directory, Path(scratch) / 'replay.sqlite3')
                write_json_atomic(directory / 'verification.json', report)


def source_version(directory):
    command = ['git', '-C', str(directory)]
    return {'head': subprocess.check_output(command + ['rev-parse', 'HEAD'], text=True).strip(),
            'worktree': subprocess.check_output(command + ['status', '--porcelain'], text=True).splitlines()}


def write_manifest(args, inputs, identity, stages, **evidence):
    validate_stages(args, stages)
    report = {'schema': 'wolvrix.f35.capture.v1', 'complete': True, 'engine': args.engine,
              'run_id': identity.get('run_id', args.run_id), 'top': args.top,
              'inputs': inputs, 'sources': inputs['sources'], 'binary': identity,
              'repository': source_version(ROOT),
              'engine_source': source_version(ROOT / ('wolvrix' if args.engine == 'grh' else 'reference/gsim')),
              'environment': environment(), 'passes': stages,
              'verified_replay': args.verify_replay, **evidence}
    write_json_atomic(args.output / 'summary.json', report)
    return report


@contextmanager
def capture_lock(engine, *, read_only=False):
    with (WORK / f'capture-{engine}.lock').open('a') as lock:
        mode = fcntl.LOCK_SH if read_only else fcntl.LOCK_EX
        try:
            fcntl.flock(lock.fileno(), mode | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(f'F35 {engine} capture files are in use') from None
        yield


class GrhObserver:
    def __init__(self, args):
        self.args = args
        self.last_boundary = 'ingest'
        self.ingest_started = time.monotonic()
        self.ingest = []
        self.passes = {}
        self.cache_release = {'files': 0, 'bytes': 0, 'wall_s': 0.0, 'errors': []}

    def release_snapshot_cache(self, paths):
        started = time.monotonic()
        result = release_files(paths, sync=True, artifact_root=WORK)
        self.cache_release['files'] += len(result['files'])
        self.cache_release['bytes'] += result['bytes']
        self.cache_release['wall_s'] += time.monotonic() - started
        for error in result['errors']:
            self.cache_release['errors'].append(error)
            print('GRH snapshot cache advice failed: ' + json.dumps(error), flush=True)

    def ingested(self, session):
        self.ingest_wall_s = time.monotonic() - self.ingest_started
        for graph in sorted(session.semantic_graphs(design=DESIGN)):
            path = self.args.output / 'ingest-origins' / f'{graph}.jsonl'
            action(session.semantic_snapshot(design=DESIGN, top=graph, output=str(path),
                                             origins_only=True), 'ingest origin inventory: ' + graph)
            self.ingest.append({'graph': graph, 'path': str(path), **footer(path)})
            self.release_snapshot_cache((path,))

    def pass_options(self, instance, keep, options):
        from f35_pass_guard import stage_event_options

        self.passes[instance] = {'keep_declared_symbols': keep, 'options': options}
        return stage_event_options(self.args.run_id, instance, self.last_boundary)

    def finished(self, instance):
        self.last_boundary = instance
        write_json_atomic(self.args.output / 'progress.json', {'last_complete_boundary': instance})

    def final_inventory(self, session):
        directory = self.args.output / 'R4'
        action(session.semantic_snapshot(design=DESIGN, top=self.args.top,
                                         output=str(directory),
                                         stage='post-fourth-dead-code-elim',
                                         export_state_actions=self.args.export_state_actions),
               'final GRH classification inventory')
        if self.args.export_state_actions and not (directory / 'state-actions.jsonl').is_file():
            raise ValueError('GRH state/action inventory was not written at R4')
        self.release_snapshot_cache(directory.iterdir())


def grh_child(args, request, input_sha):
    observer = GrhObserver(args)
    identity, stages = run_grh(args, request, input_sha, observer=observer)
    for stage in stages:
        stage.update(observer.passes[stage['pass']])
    modules = {Path(bundle).name: Path(bundle) / 'before.nodes.tsv' for bundle in stages[0]['bundles']}
    for info in observer.ingest:
        if footer(modules[info['graph']])['rowCount'] != info['node_count']:
            raise ValueError('ingest provenance does not cover initial Node inventory: ' + info['graph'])
    write_json_atomic(args.output / 'capture.json', {'binary': identity, 'passes': stages,
                      'ingest_wall_s': observer.ingest_wall_s, 'ingest_origins': observer.ingest,
                      'snapshot_cache_release': observer.cache_release})


def preserve_grh_run(output, guard):
    evidence = output.parent / 'grh-run-evidence' / guard['run_id']
    evidence.mkdir(parents=True, exist_ok=True)
    for name in ('guard.json', 'guard-trigger.json', 'stage-events.jsonl', 'grh.log', 'progress.json', 'summary.json'):
        path = output / name
        if path.is_file():
            shutil.copy2(path, evidence / name)


def grh(args, inputs):
    from f35_gsim_reference import TIMING, load_frozen_reference
    from f35_pass_guard import GSIM_CALLS, PASSES, reference_budgets, run_guarded

    summary_path = args.reference / 'summary.json'
    timing = args.reference / TIMING
    if args.recovery_timing:
        from f35_gsim_reference import recovery_timing_evidence

        input_sha = next(row['sha256'] for row in inputs['sources'] if row['path'] == str(args.firrtl))
        timing, provenance = recovery_timing_evidence(args.reference, input_sha)
    else:
        frozen = load_frozen_reference(args.reference)
        reference = json.loads(summary_path.read_text())
        if (reference.get('schema') != 'wolvrix.f35.capture.v1' or reference.get('complete') is not True
                or reference.get('engine') != 'gsim' or reference['inputs'] != inputs):
            raise ValueError('GSIM reference capture does not match the GRH inputs')
        if frozen['run_id'] != reference['run_id']:
            raise ValueError('frozen GSIM reference run ID changed')
        provenance = {'run_id': reference['run_id'], **artifact(summary_path, args.reference)}
    budgets = reference_budgets(timing, xmr_limit_s=args.xmr_limit,
                                flatten_limit_s=args.flatten_limit)
    if args.paired_capture:
        # Small designs can complete a GSIM pass in microseconds. Keep a
        # watchdog for diagnostic captures with a floor on the matched budgets.
        for name in GSIM_CALLS:
            budgets[name] = max(budgets[name], 60)
    if args.output.exists():
        if not args.replace_grh or not (args.output / 'guard.json').is_file():
            raise ValueError('existing GRH capture; extract evidence and explicitly request replacement')
        if (args.output / 'summary.json').exists() and not args.previous_comparison:
            raise ValueError('preserve the completed GRH comparison before replacing its capture')
        if args.previous_comparison:
            comparison = json.loads(args.previous_comparison.read_text())
            if sha256(args.output / 'R4/nodes.tsv') != comparison['grh_nodes']['sha256']:
                raise ValueError('previous comparison does not identify the GRH capture being replaced')
        preserve_grh_run(args.output, json.loads((args.output / 'guard.json').read_text()))
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True)
    command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:],
               '--child-run-id', args.run_id]
    result = run_guarded(command, args.output, run_id=args.run_id, budgets=budgets,
                         min_free_bytes=args.min_free_bytes)
    if result:
        guard = json.loads((args.output / 'guard.json').read_text())
        print(json.dumps(guard.get('trigger', {}), ensure_ascii=False), flush=True)
        if guard.get('status') == 'performance-blocked':
            preserve_grh_run(args.output, guard)
            for directory in (*PASSES, 'ingest-origins', 'R4'):
                path = args.output / directory
                if path.is_dir():
                    shutil.rmtree(path)
        return result
    captured = json.loads((args.output / 'capture.json').read_text())
    stages = captured.pop('passes')
    if tuple(stage['pass'] for stage in stages) != PASSES:
        raise ValueError('incomplete GRH pass sequence')
    write_manifest(args, inputs, captured.pop('binary'), stages,
                   reference=provenance,
                   final_inventory=artifact(args.output / 'R4/nodes.tsv', args.output),
                   **captured)
    print('GRH capture complete: ' + str(args.output), flush=True)
    return 0


def main():
    global WORK
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('engine', choices=('gsim', 'grh'))
    for name in ('firrtl', 'manifest', 'output'):
        parser.add_argument('--' + name, type=lambda path: Path(path).resolve(), required=True)
    for name in ('package', 'binary', 'reference', 'previous-comparison'):
        parser.add_argument('--' + name, type=lambda path: Path(path).resolve())
    parser.add_argument('--recovery-maps', type=lambda path: Path(path).resolve())
    parser.add_argument('--verify-replay', action='store_true')
    parser.add_argument('--replace-grh', action='store_true')
    parser.add_argument('--export-state-actions', action='store_true',
                        help='export live GRH/GSIM state declarations and their read/write evidence at R4')
    parser.add_argument('--recovery-timing', action='store_true')
    parser.add_argument('--paired-capture', action='store_true', help=argparse.SUPPRESS)
    gsim_mode = parser.add_mutually_exclusive_group()
    gsim_mode.add_argument('--finalize-reference', action='store_true')
    gsim_mode.add_argument('--recover-gsim-tail', action='store_true')
    parser.add_argument('--xmr-limit', type=float)
    parser.add_argument('--flatten-limit', type=float)
    parser.add_argument('--min-free-bytes', type=int, default=0,
                        help='stop the GRH capture if available filesystem space falls below this floor')
    parser.add_argument('--work-root', type=lambda path: Path(path).resolve(),
                        help='override the capture artifact root for an isolated alignment phase')
    parser.add_argument('--child-run-id', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.work_root:
        WORK = args.work_root
    if args.output == WORK or not args.output.is_relative_to(WORK):
        parser.error('capture output must be beneath ' + str(WORK))
    if args.min_free_bytes < 0 or (args.min_free_bytes and args.engine != 'grh'):
        parser.error('--min-free-bytes requires GRH and a nonnegative value')
    normalized_environment()
    for name in ('WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC', 'WOLVRIX_DEAD_ANCHOR_DIAGNOSTIC_NO_LIVENESS'):
        os.environ.pop(name, None)
    request, sources = verified_input_request(args.firrtl, args.manifest)
    tops = request.get('tops', [])
    if len(tops) != 1:
        parser.error('the manifest must specify exactly one top')
    args.top = tops[0]
    args.stop_before_final_dce = False
    args.run_id = args.child_run_id or f'f35-{args.engine}-{uuid.uuid4().hex}'
    input_sha = next(row['sha256'] for row in sources if row['path'] == str(args.firrtl))
    inputs = {'manifest': str(args.manifest), 'manifest_sha256': sha256(args.manifest), 'sources': sources,
              'top': args.top, 'firrtl_options': request.get('firrtl_options', {})}
    if args.top == 'SimTop':
        options = inputs['firrtl_options']
        if (options.get('init_policy'), options.get('invalid_policy')) != ('unknown', 'zero'):
            parser.error('SimTop requires the F34 init and invalid policies')
        if not args.paired_capture:
            reference = WORK / 'gsim-reference'
            if args.engine == 'gsim' and args.output != reference:
                parser.error('SimTop GSIM must use ' + str(reference))
            if args.engine == 'grh':
                if args.reference != reference:
                    parser.error('SimTop GRH must use the frozen F35 GSIM reference')
                if args.output.parent != WORK or not args.output.name.startswith('grh-'):
                    parser.error('SimTop GRH output must be a grh-* directory directly below ' + str(WORK))
    if args.child_run_id:
        if args.engine != 'grh':
            parser.error('only guarded GRH launches a capture child')
        grh_child(args, request, input_sha)
        return 0
    with capture_lock(args.engine):
        if args.engine == 'grh':
            if not args.reference or args.xmr_limit is None or args.flatten_limit is None:
                parser.error('GRH requires the frozen reference and both unpaired pass limits')
            return grh(args, inputs)
        if not args.binary:
            parser.error('GSIM requires --binary')
        from f35_gsim_reference import FROZEN, freeze_reference, recover_reference, resume_reference, run_gsim_reference

        if args.export_state_actions and args.output != WORK / 'gsim-reference':
            args.output.mkdir(parents=True, exist_ok=False)
            args.run_id = args.child_run_id or f'f36-{args.engine}-{uuid.uuid4().hex}'
            identity, stages = run_gsim_reference(args, input_sha)
            summary = write_manifest(args, inputs, identity, stages)
            freeze_reference(args, summary)
            print('F36 GSIM capture frozen: ' + str(args.output), flush=True)
            return 0

        if (args.output / FROZEN).exists():
            raise ValueError('GSIM reference has already been frozen: ' + str(args.output))
        if args.finalize_reference:
            identity, stages = resume_reference(args, input_sha)
        elif args.recover_gsim_tail:
            identity, stages = recover_reference(args, input_sha)
        else:
            args.output.mkdir(parents=True, exist_ok=False)
            identity, stages = run_gsim_reference(args, input_sha)
        summary = write_manifest(args, inputs, identity, stages)
        freeze_reference(args, summary)
        print('GSIM reference frozen: ' + str(args.output), flush=True)
        return 0


if __name__ == '__main__':
    sys.exit(main())
