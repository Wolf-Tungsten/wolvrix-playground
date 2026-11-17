"""Seed selected unchanged F32 inventory partitions from a completed reader cache.

This preserves the locked reader's cache trust, not an independent proof of all
source database rows. Only raw tables are copied; every derived result is new.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import time

import compare_f32_semantics as reader

SCHEMA = 'wolvrix.f32.inventory-seed.v1'
CHUNK = 4 * 1024**2
MAX_LINE = 1024**2
RAW_COLUMNS = {
    'inventory': ('engine', 'stage', 'id', 'name', 'path', 'native'),
    'connections': ('engine', 'stage', 'id', 'source', 'target', 'kind', 'resolution', 'candidates', 'reason'),
    'endpoints': ('stage', 'node', 'ordinal', 'value', 'role', 'type_key', 'domain', 'evidence', 'payload'),
    'details': ('stage', 'node', 'type_key', 'kind', 'clock', 'pair', 'payload'),
    'slices': ('engine', 'stage', 'parent', 'child', 'low', 'width'),
}


def stamp(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('seed input must be a regular file: ' + str(path))
    info = path.stat()
    return {key: getattr(info, 'st_' + key) for key in ('dev', 'ino', 'size', 'mtime_ns', 'ctime_ns')}


def closed_database(path):
    before = stamp(path)
    if any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError('seed source database has SQLite sidecars; it must be completed and closed')
    return before


def frozen_json(path):
    before = stamp(path)
    if before['size'] > 4 * 1024**2:
        raise ValueError('seed JSON metadata exceeds byte limit')
    body = path.read_bytes()
    if stamp(path) != before:
        raise ValueError('seed metadata changed during read')
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError('seed metadata must be an object')
    return value, {'path': str(path), 'sha256': hashlib.sha256(body).hexdigest(),
                   'bytes': len(body), 'stat_before': before}


def verify_json(record):
    path = Path(record['path'])
    after = stamp(path)
    record['stat_after'] = after
    record['sha256_after'] = reader.digest(path)
    if after != record['stat_before'] or record['sha256_after'] != record['sha256']:
        raise ValueError('seed source metadata changed during seeding')


def table_contract(engine, stage, name, meta, node_meta, input_sha):
    """The identity/schema/header checks used by locked read_table/ingest_snapshot.

    Row validation is inherited only after the complete body equals the already
    validated source body. The source cache itself has existing-resume trust.
    """
    expected = {'engine': engine, 'stage': reader.STAGES[engine][stage]}
    schema, columns = reader.EXCHANGE_SCHEMA, None
    if name == 'nodes.tsv':
        expected['table'] = 'nodes'
        columns = reader.HEADERS['nodes']
        for field in (*reader.IDENTITY[1:], 'snapshot_id'):
            if not isinstance(meta.get(field), str) or not meta[field]:
                raise ValueError('missing native snapshot identity')
        original = meta.get('input_identity', {})
        if not isinstance(original, dict) or original.get('sha256') not in (None, input_sha):
            raise ValueError('snapshot uses a different original input')
    elif name in ('connections.tsv', 'node-details.tsv'):
        expected.update({key: node_meta[key] for key in (*reader.IDENTITY[1:], 'snapshot_id', 'stage')})
        if name == 'connections.tsv':
            expected['table'], columns = 'connections', reader.HEADERS['connections']
        else:
            expected.update(table='node-details', detail_schema='gsim.node-details.v1')
            columns = reader.DETAIL_COLUMNS
    else:
        expected.update({key: node_meta[key] for key in ('run_id', 'snapshot_id', 'stage')})
        if name == 'node-endpoints.tsv':
            schema = tuple(reader.ENDPOINT_LAYOUTS)
            columns = reader.ENDPOINT_LAYOUTS.get(meta.get('schema'))
        else:
            schema, columns = 'semantic-node-bit-slices.v1', reader.SLICE_COLUMNS
    supported = (schema,) if isinstance(schema, str) else schema
    if meta.get('schema') not in supported or any(meta.get(key) != value for key, value in expected.items()):
        raise ValueError('mixed or unsupported native sidecar identity')
    return columns


def compare_table(old_record, new_record, engine, stage, name, node_meta, input_sha):
    paths, streams, results = [], [], []
    try:
        for index, captured in enumerate((old_record, new_record)):
            path = Path(captured['directory']) / name
            artifact = captured.get('artifacts', {}).get(name)
            if not isinstance(artifact, dict) or Path(artifact.get('path', '')).resolve() != path.resolve():
                raise ValueError('missing frozen native table identity')
            before = stamp(path)
            stream = path.open('rb')
            streams.append(stream)
            paths.append(path)
            raw = stream.readline(MAX_LINE + 1)
            line = raw.decode('utf-8')
            reader.validate_line_ending(line)
            if len(raw) > MAX_LINE or not line.startswith('#meta\t'):
                raise ValueError('missing or oversized native table metadata')
            meta = reader.json_value(line[6:], dict)
            columns = table_contract(engine, stage, name, meta, node_meta[index] if node_meta else None, input_sha)
            header = stream.readline(MAX_LINE + 1)
            if header != ('\t'.join(columns) + '\n').encode('utf-8'):
                raise ValueError('unsupported native sidecar columns')
            full, body = hashlib.sha256(), hashlib.sha256()
            full.update(raw + header)
            body.update(header)
            results.append({'path': str(path.resolve()), 'sha256': None, 'body_sha256': None,
                'bytes': len(raw) + len(header), 'body_bytes': len(header), 'metadata': meta,
                'stat_before': before, '_artifact': artifact, '_full': full, '_body': body,
                '_tail': b'', '_lines': 1, '_header': header})
        equal = results[0]['_header'] == results[1]['_header']
        while True:
            chunks = [stream.read(CHUNK) for stream in streams]
            if not any(chunks):
                break
            equal = equal and chunks[0] == chunks[1]
            for result, chunk in zip(results, chunks):
                result['_full'].update(chunk)
                result['_body'].update(chunk)
                result['bytes'] += len(chunk)
                result['body_bytes'] += len(chunk)
                result['_lines'] += chunk.count(b'\n')
                result['_tail'] = (result['_tail'] + chunk)[-MAX_LINE:]
        for path, result in zip(paths, results):
            tail = result['_tail']
            if not tail.endswith(b'\n'):
                raise ValueError('incomplete native table footer')
            footer_line = tail[:-1].rsplit(b'\n', 1)[-1].decode('utf-8') + '\n'
            reader.validate_line_ending(footer_line)
            if not footer_line.startswith('#footer\t'):
                raise ValueError('missing native table footer')
            footer = reader.json_value(footer_line[8:], dict)
            if (footer.get('complete') is not True or type(footer.get('rowCount')) is not int or
                    footer['rowCount'] < 0 or result['_lines'] != footer['rowCount'] + 2):
                raise ValueError('incomplete native table or incorrect row count')
            if name == 'nodes.tsv' and footer.get('nodeInventoryComplete') is not True:
                raise ValueError('native Node inventory is partial')
            result['footer'] = footer
            result['sha256'], result['body_sha256'] = result['_full'].hexdigest(), result['_body'].hexdigest()
            if (result['_artifact'].get('sha256') != result['sha256'] or
                    result['_artifact'].get('bytes') != result['bytes']):
                raise ValueError('native table changed since capture')
            after = stamp(path)
            if after != result['stat_before']:
                raise ValueError('native table changed while comparing row bodies')
            result['stat_after'] = after
            result['artifact'] = result['_artifact']
            for key in tuple(result):
                if key.startswith('_'):
                    del result[key]
        return {'name': name, 'body_equal': equal, 'old': results[0], 'new': results[1]}
    finally:
        for stream in streams:
            stream.close()


def compare_partition(old, new, engine, stage, input_sha, source_snapshot):
    files = [compare_table(old, new, engine, stage, 'nodes.tsv', None, input_sha)]
    node_meta = [files[0][side]['metadata'] for side in ('old', 'new')]
    for name in ('connections.tsv', 'node-endpoints.tsv' if engine == 'grh' else 'node-details.tsv', 'bit-slices.tsv'):
        files.append(compare_table(old, new, engine, stage, name, node_meta, input_sha))
    snapshots = []
    for index, side in enumerate(('old', 'new')):
        nodes, edges = files[0][side]['footer'], files[1][side]['footer']
        record = {'run_id': node_meta[index]['run_id'], 'snapshot_id': node_meta[index]['snapshot_id'],
                  'nodes': nodes['rowCount'], 'connections': edges['rowCount'],
                  'coverage': edges.get('connectionCoverage')}
        if side == 'old' and record != source_snapshot:
            raise ValueError('source checkpoint differs from its frozen sidecar metadata')
        snapshots.append(record)
    return {'engine': engine, 'stage': f'P{stage}', 'reusable': all(row['body_equal'] for row in files),
            'files': files, 'current_snapshot': snapshots[1]}


def current_identities(captures):
    identities = {}
    for engine in ('grh', 'gsim'):
        run, identifiers = None, set()
        for stage in range(5):
            record = captures[engine]['snapshots'][f'P{stage}']
            with (Path(record['directory']) / 'nodes.tsv').open('rb') as stream:
                raw = stream.readline(MAX_LINE + 1)
                line = raw.decode('utf-8')
                reader.validate_line_ending(line)
                if len(raw) > MAX_LINE or not line.startswith('#meta\t'):
                    raise ValueError('missing or oversized native table metadata')
                meta = reader.json_value(line[6:], dict)
                columns = table_contract(engine, stage, 'nodes.tsv', meta, None, captures[engine]['input_sha256'])
                if stream.readline(MAX_LINE + 1) != ('\t'.join(columns) + '\n').encode('utf-8'):
                    raise ValueError('unsupported native sidecar columns')
            if run is not None and meta['run_id'] != run:
                raise ValueError('five boundaries must be captured from the same native run')
            if meta['snapshot_id'] in identifiers:
                raise ValueError('distinct boundaries reuse a native snapshot ID')
            run = meta['run_id']
            identifiers.add(meta['snapshot_id'])
            identities[engine, stage] = (meta['run_id'], meta['snapshot_id'])
    return identities


def source_cache(source, identity, captures):
    summary, summary_record = frozen_json(source / 'summary.json')
    inputs, inputs_record = frozen_json(source / 'inputs.json')
    if (summary.get('schema') != reader.SCHEMA or summary.get('status') != 'analyzed' or
            summary.get('complete') is not True or inputs.get('inventory_complete') is not True):
        raise ValueError('seed requires a completed source comparison and inventory checkpoint')
    if (inputs.get('schema') != identity['schema'] or
            inputs.get('proof_implementation') != identity['proof_implementation']):
        raise ValueError('seed requires the same locked reader and dependency implementation')
    if summary.get('snapshots') != inputs.get('snapshots'):
        raise ValueError('source completed summary and checkpoint disagree')
    old_captures, json_records = {}, [summary_record, inputs_record]
    for engine in ('grh', 'gsim'):
        artifact = inputs['capture_summaries'][engine]
        directory = Path(artifact['path']).resolve()
        _, captured_record = frozen_json(directory / 'summary.json')
        if captured_record['sha256'] != artifact['sha256']:
            raise ValueError('source frozen capture summary changed')
        old_captures[engine] = reader.capture(directory, engine)
        json_records.append(captured_record)
        if (old_captures[engine]['input_sha256'] != captures[engine]['input_sha256'] or
                summary.get('input_sha256') != captures[engine]['input_sha256']):
            raise ValueError('seed captures use different original FIRRTL inputs')
    path = source / 'comparison.sqlite'
    before = closed_database(path)
    database = {'path': str(path), 'sha256': reader.digest(path), 'bytes': before['size'], 'stat_before': before}
    if closed_database(path) != before:
        raise ValueError('source database changed during freeze')
    return inputs, old_captures, json_records, database


def copy_partition(db, engine, stage, check):
    names = ('inventory', 'connections', 'endpoints' if engine == 'grh' else 'details', 'slices')
    footers = {name: row['old']['footer']['rowCount'] for name, row in zip(names, check['files'])}
    # files are nodes, connections, typed sidecar, slices, in that order.
    for table in names:
        columns = ','.join(RAW_COLUMNS[table])
        expected = RAW_COLUMNS[table]
        actual = tuple(row[1] for row in db.execute('PRAGMA seed.table_info(' + table + ')'))
        if actual != expected:
            raise ValueError('source raw table schema differs from the locked reader: ' + table)
        where, values = ('engine=? AND stage=?', (engine, stage)) if table in ('inventory', 'connections', 'slices') else ('stage=?', (stage,))
        changed = db.total_changes
        db.execute('INSERT INTO main.' + table + '(' + columns + ') SELECT ' + columns +
                   ' FROM seed.' + table + ' WHERE ' + where, values)
        if db.total_changes - changed != footers[table]:
            raise ValueError('source database partition row count differs from its frozen sidecar: ' + table)


def seed_inventory(grh, gsim, source, output, reuse):
    started = time.monotonic()
    grh, gsim, source, output = (Path(path).resolve() for path in (grh, gsim, source, output))
    root = (reader.ROOT / 'ptmp').resolve()
    if output == root or not output.is_relative_to(root) or output.exists():
        raise ValueError('seed output must be a new directory under repository ptmp/')
    requested = set()
    for engine, stage in reuse:
        if engine not in ('grh', 'gsim') or type(stage) is not int or stage not in range(5):
            raise ValueError('invalid requested seed partition')
        if (engine, stage) in requested:
            raise ValueError('duplicate requested seed partition')
        requested.add((engine, stage))
    if not requested:
        raise ValueError('at least one requested seed partition is required')
    captures = {'grh': reader.capture(grh, 'grh'), 'gsim': reader.capture(gsim, 'gsim')}
    if captures['grh']['input_sha256'] != captures['gsim']['input_sha256']:
        raise ValueError('GRH and GSIM captures have different raw FIRRTL inputs')
    native_identities = current_identities(captures)
    identity = reader.comparison_identity(grh, gsim)
    previous, old_captures, source_json, database = source_cache(source, identity, captures)
    checks = {}
    for engine, stage in sorted(requested):
        checks[engine, stage] = compare_partition(old_captures[engine]['snapshots'][f'P{stage}'],
            captures[engine]['snapshots'][f'P{stage}'], engine, stage, captures[engine]['input_sha256'],
            previous['snapshots'][engine][f'P{stage}'])
    output.mkdir(parents=True, exist_ok=False)
    checkpoint = output / 'inputs.json'
    reader.write_json(checkpoint, {**identity, 'inventory_complete': False})
    receipt = {'schema': SCHEMA, 'status': 'seeding', 'source_database': database,
        'source_metadata': source_json, 'current_comparison_identity': identity,
        'requested_partitions': [{'engine': engine, 'stage': f'P{stage}'} for engine, stage in sorted(requested)],
        'partition_checks': list(checks.values()), 'reused_partitions': [], 'ingested_partitions': [],
        'independent_source_row_revalidation': False,
        'source_cache_trust': 'same as locked-reader resume: completed cache trusted; not an independent proof of every source database row',
        'derived_tables_reused': False, 'structure_indexes_reused': False,
        'semantic_acceptance_evaluated': False}
    os.environ['SQLITE_TMPDIR'] = str(output)
    try:
        with closing(reader.database(output / 'comparison.sqlite')) as db:
            db.execute('ATTACH DATABASE ? AS seed', (Path(database['path']).as_uri() + '?mode=ro&immutable=1',))
            snapshots = {}
            with db:
                for engine in ('grh', 'gsim'):
                    snapshots[engine], run, identifiers = {}, None, set()
                    for stage in range(5):
                        check = checks.get((engine, stage))
                        partition = {'engine': engine, 'stage': f'P{stage}'}
                        if check and check['reusable']:
                            copy_partition(db, engine, stage, check)
                            record = check['current_snapshot']
                            receipt['reused_partitions'].append(partition)
                        else:
                            record = reader.ingest_snapshot(db, engine, stage,
                                captures[engine]['snapshots'][f'P{stage}'], run, captures[engine]['input_sha256'])
                            receipt['ingested_partitions'].append(partition)
                        if run is not None and record['run_id'] != run:
                            raise ValueError('five boundaries must be captured from the same native run')
                        if (record['run_id'], record['snapshot_id']) != native_identities[engine, stage]:
                            raise ValueError('current native snapshot identity changed during seeding')
                        if record['snapshot_id'] in identifiers:
                            raise ValueError('distinct boundaries reuse a native snapshot ID')
                        run = record['run_id']
                        identifiers.add(record['snapshot_id'])
                        snapshots[engine][f'P{stage}'] = record
            db.execute('DETACH DATABASE seed')
            with db:
                reader.derive(db)
                reader.lifecycle(db)
                reader.slice_geometry(db)
        for record in source_json:
            verify_json(record)
        after = closed_database(Path(database['path']))
        database['stat_after'] = after
        database['sha256_after'] = reader.digest(database['path'])
        if after != database['stat_before'] or database['sha256_after'] != database['sha256']:
            raise ValueError('source database changed during seeding')
        if reader.comparison_identity(grh, gsim) != identity:
            raise ValueError('current frozen captures or reader changed during seeding')
        # Reused current tables were compared before SQL copying; recheck their
        # stamps before sealing. Ordinary ingestion validates its own frozen hash.
        for check in checks.values():
            for row in check['files']:
                for side in ('old', 'new'):
                    if stamp(Path(row[side]['path'])) != row[side]['stat_after']:
                        raise ValueError('frozen native table changed during seeding')
        receipt.update(status='seeded', wall_s=time.monotonic() - started, snapshots=snapshots)
        reader.write_json(output / 'seed-receipt.json', receipt)
        reader.write_json(checkpoint, {**identity, 'inventory_complete': True, 'snapshots': snapshots})
        return receipt
    except BaseException as error:
        reader.write_json(checkpoint, {**identity, 'inventory_complete': False})
        reader.write_json(output / 'seed-receipt.json', {**receipt, 'status': 'failed', 'error': repr(error)})
        raise


def requested_partition(value):
    try:
        engine, stage = value.split(':')
        if engine not in ('grh', 'gsim') or stage not in {f'P{i}' for i in range(5)}:
            raise ValueError
        return engine, int(stage[1:])
    except ValueError as error:
        raise argparse.ArgumentTypeError('partition must be grh:P0 through gsim:P4') from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--grh', type=Path, required=True)
    parser.add_argument('--gsim', type=Path, required=True)
    parser.add_argument('--source-comparison', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reuse', type=requested_partition, action='append', required=True)
    args = parser.parse_args()
    receipt = seed_inventory(args.grh, args.gsim, args.source_comparison, args.output, args.reuse)
    print(reader.compact({key: receipt[key] for key in ('status', 'reused_partitions', 'ingested_partitions')}))


if __name__ == '__main__':
    main()
