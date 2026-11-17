"""Audit exact data identity between two completed GRH F32 captures.

This compares frozen capture data, not behavior or cross-engine equivalence.
No comparison database or difference ledger is opened. Invoke through Make.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import time

from benchmark_f30_pipeline import (verified_dependencies, verify_loaded_native,
                                    verify_package_identity)
from benchmark_xs_firrtl_ingest import request_from_manifest
import compare_f32_semantics as reader
from seed_f32_inventory import CHUNK, compare_table, stamp


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'wolvrix.f32.capture-data-identity.v1'
SHA = re.compile('[0-9a-f]{64}')
TABLES = ('nodes.tsv', 'connections.tsv', 'node-endpoints.tsv', 'bit-slices.tsv')
CALLS = ('xmr-resolve#0', 'hier-flatten#0', 'comb-loop-elim#0',
         'split-static-array#0', 'dead-code-elim#0', 'expr-opt#0',
         'used-bits#0', 'split-nodes#0', 'dead-code-elim#1')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate metadata JSON field: ' + key)
        result[key] = value
    return result


class Frozen:
    def __init__(self):
        self.files = {}

    def track(self, path):
        path = Path(path).absolute()
        require(path.resolve() == path, 'frozen file has a symlink component: ' + str(path))
        current = stamp(path)
        record = self.files.setdefault(str(path), {'path': str(path), 'stat_before': current})
        require(current == record['stat_before'], 'frozen input changed: ' + str(path))
        return path, record

    def json(self, path):
        path, record = self.track(path)
        require(record['stat_before']['size'] <= 4 * 1024**2, 'metadata exceeds byte limit')
        data = path.read_bytes()
        value = json.loads(data, object_pairs_hook=unique_object)
        require(isinstance(value, dict), 'frozen metadata must be an object')
        actual = hashlib.sha256(data).hexdigest()
        require(record.get('sha256', actual) == actual, 'metadata changed during audit')
        record.update(sha256=actual, metadata=True)
        self.track(path)
        return value, record

    def verify_blob(self, path, expected, expected_bytes=None):
        path, record = self.track(path)
        require(isinstance(expected, str) and SHA.fullmatch(expected), 'invalid frozen hash')
        if 'sha256' not in record:
            record['sha256'] = reader.digest(path)
        require(record['sha256'] == expected and
                (expected_bytes is None or record['stat_before']['size'] == expected_bytes),
                'frozen artifact hash/bytes mismatch: ' + str(path))
        self.track(path)
        return record

    def finish(self):
        for record in self.files.values():
            self.track(record['path'])
            if record.get('metadata'):
                require(reader.digest(Path(record['path'])) == record['sha256'],
                        'metadata changed before receipt publication')
            record['stat_after'] = stamp(Path(record['path']))


def bound_path(value, expected, context):
    require(isinstance(value, str) and Path(value).is_absolute() and Path(value) == expected,
            context + ' path mismatch')


def guard_contract(directory, summary, frozen):
    reference = summary.get('resource_guard')
    require(isinstance(reference, dict) and reference.get('status') == 'completed',
            'capture guard is not completed')
    bound_path(reference.get('path'), directory / 'guard.json', 'guard')
    guard, _ = frozen.json(directory / 'guard.json')
    require(guard.get('schema') == 'wolvrix.f30.resource-guard.v1' and
            guard.get('status') == 'completed' and type(guard.get('returncode')) is int and
            guard['returncode'] == 0 and guard.get('reason') == 'child_completed' and
            'termination' not in summary, 'capture guard did not complete successfully')
    command = guard.get('command')
    require(isinstance(command, list) and all(isinstance(item, str) for item in command) and
            command.count('--guard-child') == 1, 'guard lacks its capture command')
    for option, expected in (('--engine', 'grh'), ('--output', str(directory)),
                             ('--firrtl', summary.get('input')),
                             ('--manifest', summary.get('manifest')),
                             ('--package', summary.get('package_identity', {}).get('package'))):
        require(command.count(option) == 1 and command.index(option) + 1 < len(command) and
                command[command.index(option) + 1] == expected, 'guard command identity mismatch: ' + option)
    return guard


def package_contract(summary, frozen):
    captured = summary.get('package_identity')
    require(isinstance(captured, dict) and isinstance(captured.get('package'), str),
            'capture lacks frozen package identity')
    package = Path(captured['package'])
    require(package.is_absolute() and package.resolve() == package, 'invalid frozen package path')
    identity_path = package / 'identity.json'
    bound_path(summary.get('identity_file'), identity_path, 'package identity')
    identity, identity_record = frozen.json(identity_path)
    require(identity_record['sha256'] == summary.get('identity_sha256') and identity == captured,
            'capture package metadata differs from frozen identity')
    source = identity.get('source', {})
    for value in (identity.get('build_cache'), source.get('dependencies')):
        require(isinstance(value, dict) and isinstance(value.get('path'), str),
                'package lacks bound build/dependency metadata')
        frozen.track(value['path'])
    for field in ('archive', 'patch', 'head_file'):
        if field in source:
            frozen.track(source[field])
    for library in identity.get('libraries', []):
        require(isinstance(library, dict) and isinstance(library.get('path'), str),
                'invalid frozen library inventory')
        relative = Path(library['path'])
        require(not relative.is_absolute() and '..' not in relative.parts, 'unsafe library path')
        frozen.track(package / relative)
    dependencies, _ = frozen.json(package / 'dependencies.json')
    require(isinstance(dependencies.get('archive'), str), 'missing dependency archive')
    frozen.track(dependencies['archive'])
    # Use the capture producer's source/build/library/dependency verification.
    require(verify_package_identity(package, identity_path) == identity,
            'frozen package verification disagrees')
    verified = verified_dependencies(package, package / 'dependencies.json', identity)
    require(verified == summary.get('dependencies'), 'capture dependency metadata mismatch')
    verify_loaded_native(package, identity, summary.get('native'))
    return {'identity': identity, 'identity_sha256': identity_record['sha256'],
            'native': summary['native'], 'dependencies': verified}


def capture_contract(directory, frozen):
    summary, metadata = frozen.json(directory / 'summary.json')
    require(summary.get('engine') == 'grh', 'this audit supports same-engine GRH captures only')
    # Locked reader checks complete raw-FIRRTL/no-trace and exact five boundary paths.
    require(reader.capture(directory, 'grh') == summary, 'capture metadata changed')
    require(summary.get('full_structure') is True, 'audit requires complete captured structures')
    require(type(summary.get('serialization_id_map')) is bool, 'missing explicit map presence')
    guard = guard_contract(directory, summary, frozen)
    package = package_contract(summary, frozen)
    require(isinstance(summary.get('input'), str) and Path(summary['input']).is_absolute() and
            type(summary.get('input_bytes')) is int and summary['input_bytes'] >= 0,
            'invalid original input identity')
    frozen.verify_blob(summary['input'], summary['input_sha256'], summary['input_bytes'])
    manifest = Path(summary.get('manifest', ''))
    require(manifest.is_absolute(), 'capture lacks manifest identity')
    _, manifest_record = frozen.json(manifest)
    require(manifest_record['sha256'] == summary.get('manifest_sha256'), 'manifest hash mismatch')
    request = request_from_manifest(manifest)
    sources = summary.get('sources')
    require(isinstance(sources, list) and len(sources) == len(request['sources']),
            'capture source inventory differs from manifest')
    actual_firrtl = False
    for source, requested in zip(sources, request['sources']):
        require(isinstance(source, dict) and all(source.get(key) == requested.get(key)
                for key in ('path', 'language', 'unit')), 'actual source identity differs from manifest')
        require(type(source.get('bytes')) is int and source['bytes'] >= 0, 'invalid source length')
        frozen.verify_blob(source['path'], source.get('sha256'), source['bytes'])
        if source['language'] == 'firrtl' and source['path'] == summary['input']:
            actual_firrtl = source['sha256'] == summary['input_sha256']
    require(actual_firrtl, 'declared FIRRTL is not the actual manifest input')
    calls = summary.get('pass_calls')
    require(isinstance(calls, list) and tuple(row.get('logical_instance') for row in calls) == CALLS,
            'capture pass sequence differs from the F32 prefix/window')
    for index, call in enumerate(calls):
        timers = [row for row in call.get('native_timers', []) if row.get('scope') == 'pass']
        require(call.get('prefix') is (index < 5) and len(timers) == 1 and
                timers[0].get('complete') is True and timers[0].get('stage') == call.get('pass') and
                call.get('pass') == CALLS[index].split('#')[0], 'incomplete native pass evidence')
    for stage in range(5):
        record = summary['snapshots'][f'P{stage}']
        require(record.get('semantic_validation', {}).get('valid') is True,
                'capture contains invalid semantic validation')
        artifacts = record.get('artifacts')
        require(isinstance(artifacts, dict), 'missing snapshot artifacts')
        mapped = 'serialization-id-map.tsv' in artifacts
        require(mapped == summary['serialization_id_map'] and
                (directory / f'P{stage}/serialization-id-map.tsv').exists() == mapped,
                'serialization map presence differs from frozen capture')
    return summary, {'directory': str(directory), 'summary_sha256': metadata['sha256'],
                     'input': {key: summary[key] for key in ('input', 'input_bytes', 'input_sha256')},
                     'manifest': {'path': str(manifest), 'sha256': manifest_record['sha256']},
                     'sources': sources, 'package': package,
                     'guard': {'path': str(directory / 'guard.json'), 'returncode': guard['returncode'],
                               'limits': guard.get('limits')}}


def compare_structure(before, after, frozen):
    records, streams = [], []
    try:
        for snapshot in (before, after):
            artifact = snapshot.get('artifacts', {}).get('structure')
            require(isinstance(artifact, dict), 'missing frozen structure artifact')
            path = Path(snapshot.get('structure', ''))
            bound_path(artifact.get('path'), path, 'structure artifact')
            require(path == Path(snapshot['directory']) / 'design.json', 'unexpected GRH structure path')
            path, tracked = frozen.track(path)
            require(type(artifact.get('bytes')) is int and artifact['bytes'] > 0 and
                    artifact['bytes'] == tracked['stat_before']['size'] and
                    isinstance(artifact.get('sha256'), str) and SHA.fullmatch(artifact['sha256']),
                    'invalid frozen structure identity')
            records.append({'path': str(path), 'bytes': 0, '_digest': hashlib.sha256(),
                            '_expected': artifact['sha256']})
            streams.append(path.open('rb'))
        equal = True
        while True:
            chunks = [stream.read(CHUNK) for stream in streams]
            if not any(chunks):
                break
            equal = equal and chunks[0] == chunks[1]
            for record, chunk in zip(records, chunks):
                record['_digest'].update(chunk)
                record['bytes'] += len(chunk)
        for record in records:
            record['sha256'] = record.pop('_digest').hexdigest()
            require(record['sha256'] == record.pop('_expected'), 'structure hash mismatch')
            _, tracked = frozen.track(record['path'])
            tracked['sha256'] = record['sha256']
        return {'exact_bytes_equal': equal, 'before': records[0], 'after': records[1],
                'JSON_fields_parsed_or_normalized': False}
    finally:
        for stream in streams:
            stream.close()


def audit(before, after, output):
    started = time.monotonic()
    before, after = (Path(path).absolute() for path in (before, after))
    require(before.resolve() == before and after.resolve() == after and before != after,
            'audit requires distinct nonsymlink capture paths')
    output = Path(output).absolute()
    require(output.resolve() == output and output.is_relative_to(ROOT / 'ptmp') and
            output != ROOT / 'ptmp' and not output.exists() and
            not output.is_relative_to(before) and not output.is_relative_to(after),
            'audit output must be a fresh directory under repository ptmp')
    output.mkdir(parents=True, exist_ok=False)
    frozen = Frozen()
    report = {'schema': SCHEMA, 'status': 'running', 'complete': False,
              'scope': 'same-engine GRH frozen capture table bodies and complete structure bytes',
              'semantic_acceptance_evaluated': False, 'behavior_equivalence_proved': False,
              'source_geometry_proved': False, 'full_Node_semantics_proved': False,
              'comparison_database_opened': False, 'row_semantics_revalidated': False,
              'serialized_endpoint_mapping_proved': False,
              'exchange_session_scope': 'each native snapshot has its own exporter session; same underlying Session is producer evidence',
              'implementation': {name: reader.digest(ROOT / 'scripts' / name) for name in (
                  'audit_f32_capture_identity.py', 'seed_f32_inventory.py', 'compare_f32_semantics.py',
                  'benchmark_f30_pipeline.py', 'snapshot_f30_package.py',
                  'benchmark_xs_firrtl_ingest.py', 'semantic_node_exchange.py')}, 'boundaries': {}}
    try:
        summaries, captures = [], []
        for directory in (before, after):
            summary, evidence = capture_contract(directory, frozen)
            summaries.append(summary)
            captures.append(evidence)
        report['before'], report['after'] = captures
        require(summaries[0]['input_sha256'] == summaries[1]['input_sha256'] and
                summaries[0]['input_bytes'] == summaries[1]['input_bytes'] and
                summaries[0]['manifest_sha256'] == summaries[1]['manifest_sha256'] and
                summaries[0]['sources'] == summaries[1]['sources'],
                'before/after original input or manifest identities differ')
        require(summaries[0]['serialization_id_map'] == summaries[1]['serialization_id_map'],
                'before/after serialization map presence differs')
        require(not summaries[0]['serialization_id_map'],
                'mapped captures are unsupported by this streaming identity audit')
        histories = [{'runs': set(), 'graphs': set(), 'snapshots': set(), 'sessions': set()}
                     for _ in summaries]
        for stage in range(5):
            snapshots = [summary['snapshots'][f'P{stage}'] for summary in summaries]
            tables = []
            for name in TABLES:
                for snapshot in snapshots:
                    frozen.track(Path(snapshot['directory']) / name)
                nodes = None if name == 'nodes.tsv' else [tables[0][side]['metadata'] for side in ('before', 'after')]
                checked = compare_table(*snapshots, 'grh', stage, name, nodes, summaries[0]['input_sha256'])
                checked['before'], checked['after'] = checked.pop('old'), checked.pop('new')
                # compare_table checks locked schema fields; endpoint/slice exporters
                # additionally identify this snapshot via session_id, not exchange_session_id.
                for index, side in enumerate(('before', 'after')):
                    meta = checked[side]['metadata']
                    captured_meta = snapshots[index]['artifacts'][name].get('metadata')
                    require(captured_meta is None or captured_meta == meta, 'frozen table metadata mismatch')
                    if nodes is not None and name != 'connections.tsv':
                        require(meta.get('engine') == 'grh' and
                                meta.get('session_id') == nodes[index]['exchange_session_id'],
                                'mixed endpoint/slice exporter session')
                tables.append(checked)
            for index, side in enumerate(('before', 'after')):
                meta = tables[0][side]['metadata']
                history = histories[index]
                require(meta['snapshot_id'] == meta['exchange_session_id'] + ':snapshot:' + meta['stage'],
                        'GRH snapshot is not bound to its exporter session/stage')
                require(meta['snapshot_id'] not in history['snapshots'] and
                        meta['exchange_session_id'] not in history['sessions'], 'duplicate native snapshot/session identity')
                for field, value in (('runs', meta['run_id']), ('graphs', meta['graph_id']),
                                     ('snapshots', meta['snapshot_id']), ('sessions', meta['exchange_session_id'])):
                    history[field].add(value)
                require(len(history['runs']) == 1 and len(history['graphs']) == 1,
                        'five boundaries have mixed native run/graph identity')
                require(summaries[index].get('snapshot_run_id') == meta['run_id'] and
                        snapshots[index].get('node_count') == tables[0][side]['footer']['rowCount'],
                        'capture summary differs from its native snapshot inventory')
            structure = compare_structure(*snapshots, frozen)
            report['boundaries'][f'P{stage}'] = {
                'tables': tables, 'structure': structure,
                'data_equal': all(table['body_equal'] for table in tables) and structure['exact_bytes_equal']}
        report['native_histories'] = [{key: sorted(value) for key, value in history.items()} for history in histories]
        frozen.finish()
        for name, sha in report['implementation'].items():
            require(reader.digest(ROOT / 'scripts' / name) == sha, 'audit implementation changed during run')
        report.update(status='completed', complete=True,
                      data_equal=all(row['data_equal'] for row in report['boundaries'].values()),
                      frozen_files=list(frozen.files.values()), wall_s=time.monotonic() - started)
        report['result'] = 'equal' if report['data_equal'] else 'different'
        reader.write_json(output / 'receipt.json', report)
        return report
    except BaseException as error:
        report.pop('result', None)
        report.pop('data_equal', None)
        report.update(status='failed', complete=False, error=repr(error), wall_s=time.monotonic() - started)
        reader.write_json(output / 'receipt.json', report)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.before, args.after, args.output)
    print(json.dumps({key: report[key] for key in ('status', 'result', 'data_equal')}))


if __name__ == '__main__':
    main()
