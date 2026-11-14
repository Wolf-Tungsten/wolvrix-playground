"""Validate static SemanticNode TSV snapshots and replay native pass journals.

after snapshots are opened only after replay; they never supply an edit.
SQLite is derived storage, with no inferred Nodes, connections or lineage.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3

SCHEMA = 'semantic-node-exchange.v1'
HEADERS = {
    'nodes': ('node_id', 'name_path_json', 'native_name'),
    'connections': ('connection_id', 'source_node_id', 'target_node_id', 'kind',
                    'resolution', 'candidate_sources_json', 'reason'),
    'evolution': ('record', 'seq', 'ordinal', 'action', 'reason', 'subject', 'side', 'object_id', 'detail_json'),
}
KINDS = {'dependency', 'state_update', 'storage_read', 'storage_write', 'external_binding', 'unknown'}
IDENTITY = ('schema', 'engine', 'run_id', 'graph_id', 'exchange_session_id')


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def encode_cell(value):
    if value is None:
        return r'\N'
    return str(value).replace('\\', '\\\\').replace('\t', '\\t').replace('\n', '\\n').replace('\r', '\\r')


def decode_cell(value):
    if value == r'\N':
        return None
    if '\\' not in value:
        return value
    result, position = [], 0
    escapes = {'\\': '\\', 't': '\t', 'n': '\n', 'r': '\r'}
    while position < len(value):
        character = value[position]
        position += 1
        if character == '\\':
            if position == len(value) or value[position] not in escapes:
                raise ValueError('invalid TSV escape')
            character = escapes[value[position]]
            position += 1
        result.append(character)
    return ''.join(result)


def checked_id(value):
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError('invalid object identity')
    return value


def integer(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError('invalid decimal identity or sequence')
    result = checked_id(int(value))
    if str(result) != value:
        raise ValueError('noncanonical integer')
    return result


def json_value(value, expected):
    try:
        result = json.loads(value)
    except (ValueError, TypeError) as error:
        raise ValueError('invalid JSON field') from error
    if not isinstance(result, expected):
        raise ValueError('invalid JSON field type')
    return result


def validate_line_ending(line):
    if not line.endswith('\n') or line.endswith('\r\n'):
        raise ValueError('invalid TSV line ending')


def parsed_row(line, columns):
    validate_line_ending(line)
    fields = line[:-1].split('\t')
    if len(fields) != len(columns):
        raise ValueError('invalid TSV field count')
    return dict(zip(columns, map(decode_cell, fields)))


def validate_node(row):
    if set(row) != set(HEADERS['nodes']):
        raise ValueError('invalid public Node definition fields')
    checked_id(row['node_id'])
    path = row['name_path_json']
    if path is not None and (not isinstance(path, list) or not path or
                             any(not isinstance(token, str) or not token for token in path)):
        raise ValueError('invalid current Node name path')
    if not isinstance(row['native_name'], str):
        raise ValueError('missing native Node name')
    return row['node_id'], compact(row), None


def validate_connection(row):
    if set(row) != set(HEADERS['connections']):
        raise ValueError('invalid public connection definition fields')
    identifier, target = checked_id(row['connection_id']), checked_id(row['target_node_id'])
    source, candidates = row['source_node_id'], row['candidate_sources_json']
    if (not isinstance(candidates, list) or any(type(item) is not int or not 0 <= item <= 2**63 - 1 for item in candidates)
            or candidates != sorted(set(candidates)) or not isinstance(row['kind'], str) or row['kind'] not in KINDS):
        raise ValueError('invalid connection kind or candidate set')
    if row['resolution'] == 'resolved':
        checked_id(source)
        if candidates or row['reason'] is not None or row['kind'] == 'unknown':
            raise ValueError('invalid resolved connection')
        key = [source, target, row['kind']]
    elif row['resolution'] == 'unresolved':
        if source is not None or not isinstance(row['reason'], str) or not row['reason']:
            raise ValueError('invalid unresolved connection')
        key = [target, row['kind'], candidates, row['reason']]
    else:
        raise ValueError('invalid connection resolution')
    return identifier, compact(row), compact([row['resolution'], key])


def validate_decision(row, detail, identifier, header, db):
    required = {'pass', 'outcome', 'blocker_node_ids'}
    if (row['action'] is not None or row['subject'] != 'node' or row['side'] != 'before'
            or not isinstance(row['reason'], str) or not row['reason'] or not isinstance(detail, dict)
            or not required <= set(detail) or set(detail) - required - {'update_ordinal', 'axis'}
            or not isinstance(detail['pass'], str) or not detail['pass'] or
            detail['pass'] not in header['pass'].split(',')
            or detail['outcome'] not in ('retain', 'replace')):
        raise ValueError('invalid native pass decision')
    blockers = detail['blocker_node_ids']
    if not isinstance(blockers, list):
        raise ValueError('invalid native decision blockers')
    # Validate scalar identities before hashing; malformed JSON containers must
    # produce a contract error, not an incidental unhashable-type exception.
    checked_blockers = [checked_id(item) for item in blockers]
    if len(set(checked_blockers)) != len(checked_blockers):
        raise ValueError('invalid native decision blockers')
    for node in [checked_id(identifier), *checked_blockers]:
        if not db.execute('SELECT 1 FROM before_nodes WHERE id=?', (node,)).fetchone():
            raise ValueError('decision refers outside the before inventory')
    for key in ('update_ordinal', 'axis'):
        if key in detail and (type(detail[key]) is not int or not 0 <= detail[key] <= 2**64 - 1):
            raise ValueError('invalid native decision coordinate')


def validate_coverage(value, counts=None):
    if not isinstance(value, dict) or set(value) != KINDS:
        raise ValueError('missing public connection coverage categories')
    for kind, coverage in value.items():
        if (not isinstance(coverage, dict) or coverage.get('status') not in
                ('complete', 'partial', 'unsupported', 'not_applicable') or
                any(type(coverage.get(field)) is not int or coverage[field] < 0
                    for field in ('resolved', 'unresolved'))):
            raise ValueError('invalid public connection coverage')
        if coverage['status'] == 'complete' and coverage['unresolved']:
            raise ValueError('unresolved connections falsely reported complete')
        if counts is not None and any(coverage[field] != counts[kind, field] for field in ('resolved', 'unresolved')):
            raise ValueError('coverage count differs from actual public inventory')


def create_database(db):
    for prefix in ('before', 'after', 'current'):
        db.executescript(f'''
            CREATE TABLE {prefix}_nodes(id INTEGER PRIMARY KEY,body TEXT NOT NULL);
            CREATE TABLE {prefix}_connections(id INTEGER PRIMARY KEY,body TEXT NOT NULL,key TEXT NOT NULL UNIQUE);
        ''')
    db.executescript('''
        CREATE TABLE seen_nodes(id INTEGER PRIMARY KEY);
        CREATE TABLE seen_connections(id INTEGER PRIMARY KEY);
        CREATE TABLE evolution(record TEXT,seq INTEGER,ordinal INTEGER,action TEXT,reason TEXT,
            subject TEXT,side TEXT,object_id INTEGER,detail_json TEXT,PRIMARY KEY(seq,ordinal));
        CREATE TABLE event_edits(subject TEXT,side TEXT,id INTEGER,body TEXT,key TEXT,PRIMARY KEY(subject,side,id));
        CREATE TABLE event_lineage(parent INTEGER,child INTEGER,relation TEXT,coordinates TEXT,
            PRIMARY KEY(parent,child,relation,coordinates));
        CREATE TABLE connection_refs(edge INTEGER,node INTEGER,PRIMARY KEY(edge,node));
        CREATE INDEX connection_refs_node ON connection_refs(node);
    ''')


def validate_active(db, prefix='current'):
    for (body,) in db.execute(f'SELECT body FROM {prefix}_connections'):
        row = json.loads(body)
        refs = [row['target_node_id'], *row['candidate_sources_json']]
        if row['source_node_id'] is not None:
            refs.append(row['source_node_id'])
        if any(not db.execute(f'SELECT 1 FROM {prefix}_nodes WHERE id=?', (item,)).fetchone() for item in refs):
            raise ValueError('connection or unresolved candidate refers to inactive Node')


def index_connection(db, identifier, payload):
    row = json.loads(payload)
    refs = {row['target_node_id'], *row['candidate_sources_json']}
    if row['source_node_id'] is not None:
        refs.add(row['source_node_id'])
    for item in refs:
        if not db.execute('SELECT 1 FROM current_nodes WHERE id=?', (item,)).fetchone():
            raise ValueError('connection or unresolved candidate refers to inactive Node')
    db.executemany('INSERT INTO connection_refs VALUES(?,?)', ((identifier, item) for item in refs))


def load_snapshot(directory, prefix, db, table_prefix):
    metadata, footers = {}, {}
    for table in ('nodes', 'connections'):
        path = Path(directory) / f'{prefix}{table}.tsv'
        with path.open(encoding='utf-8', newline='') as stream:
            first = stream.readline()
            validate_line_ending(first)
            if not first.startswith('#meta\t') or not first.endswith('\n'):
                raise ValueError(f'missing snapshot metadata: {path}')
            meta = json_value(first[len('#meta\t'):], dict)
            if (meta.get('schema') != SCHEMA or meta.get('table') != table or
                    any(not isinstance(meta.get(key), str) or not meta[key]
                        for key in (*IDENTITY[1:], 'snapshot_id', 'stage'))):
                raise ValueError('invalid static snapshot identity')
            if stream.readline() != '\t'.join(HEADERS[table]) + '\n':
                raise ValueError('invalid snapshot TSV columns')
            count, previous, footer, coverage_counts = 0, -1, None, Counter()
            for line in stream:
                validate_line_ending(line)
                if footer is not None:
                    raise ValueError('rows follow snapshot footer')
                if line.startswith('#footer\t'):
                    footer = json_value(line[len('#footer\t'):], dict)
                    continue
                row = parsed_row(line, HEADERS[table])
                if table == 'nodes':
                    row['node_id'] = integer(row['node_id'])
                    row['name_path_json'] = None if row['name_path_json'] is None else json_value(row['name_path_json'], list)
                    identifier, body, _ = validate_node(row)
                    db.execute(f'INSERT INTO {table_prefix}_nodes VALUES(?,?)', (identifier, body))
                else:
                    for field in ('connection_id', 'target_node_id'):
                        row[field] = integer(row[field])
                    row['source_node_id'] = None if row['source_node_id'] is None else integer(row['source_node_id'])
                    row['candidate_sources_json'] = json_value(row['candidate_sources_json'], list)
                    identifier, body, key = validate_connection(row)
                    coverage_counts[row['kind'], row['resolution']] += 1
                    db.execute(f'INSERT INTO {table_prefix}_connections VALUES(?,?,?)', (identifier, body, key))
                if identifier <= previous:
                    raise ValueError('static inventory is not uniquely sorted')
                previous, count = identifier, count + 1
            if not footer or footer.get('complete') is not True or footer.get('rowCount') != count:
                raise ValueError('incomplete static snapshot')
            if table == 'nodes' and type(footer.get('nodeInventoryComplete')) is not bool:
                raise ValueError('missing Node inventory coverage')
            if table == 'connections':
                validate_coverage(footer.get('connectionCoverage'), coverage_counts)
            metadata[table], footers[table] = meta, footer
    if any(metadata['nodes'].get(key) != metadata['connections'].get(key)
           for key in (*IDENTITY, 'snapshot_id', 'stage')):
        raise ValueError('Node and connection snapshots describe different moments')
    validate_active(db, table_prefix)
    return {'metadata': metadata['nodes'], 'nodes': footers['nodes'], 'connections': footers['connections']}


def verify_bundle(bundle, database=':memory:'):
    """Reconstruct static after from before plus native full-object edits."""
    bundle = Path(bundle)
    db = sqlite3.connect(str(database))
    try:
        create_database(db)
        before = load_snapshot(bundle, 'before.', db, 'before')
        for table in ('nodes', 'connections'):
            db.execute(f'INSERT INTO current_{table} SELECT * FROM before_{table}')
            db.execute(f'INSERT INTO seen_{table} SELECT id FROM before_{table}')
        for identifier, body in db.execute('SELECT id,body FROM before_connections'):
            index_connection(db, identifier, body)
        header = footer = event = None
        seq, ordinal, events, decisions, lineage_count = 0, -1, 0, 0, 0
        actions = Counter()

        def apply_event():
            nonlocal event
            if event is None:
                return
            sides = dict(db.execute('SELECT side,COUNT(*) FROM event_edits GROUP BY side'))
            expected = 'replace' if sides.get('before') and sides.get('after') else 'delete' if sides.get('before') else 'add'
            if not sides or event['action'] != expected:
                raise ValueError('event action does not match object cardinalities')
            for subject, side, identifier, body, _ in db.execute('SELECT * FROM event_edits'):
                table = 'nodes' if subject == 'node' else 'connections'
                if side == 'before' and db.execute(f'SELECT body FROM current_{table} WHERE id=?', (identifier,)).fetchone() != (body,):
                    raise ValueError('native event precondition failed')
                if side == 'after':
                    retained = db.execute("SELECT 1 FROM event_edits WHERE subject=? AND side='before' AND id=?", (subject, identifier)).fetchone()
                    seen = db.execute(f'SELECT 1 FROM seen_{table} WHERE id=?', (identifier,)).fetchone()
                    if seen and (subject == 'connection' or not retained):
                        raise ValueError('retired identity or immutable connection ID reused')
            for parent, child, _, _ in db.execute('SELECT * FROM event_lineage'):
                for side, identifier in (('before', parent), ('after', child)):
                    if not db.execute("SELECT 1 FROM event_edits WHERE subject='node' AND side=? AND id=?", (side, identifier)).fetchone():
                        raise ValueError('lineage refers outside its event sides')
            for subject, table in (('connection', 'connections'), ('node', 'nodes')):
                db.execute(f"DELETE FROM current_{table} WHERE id IN (SELECT id FROM event_edits WHERE subject=? AND side='before')", (subject,))
            db.execute("DELETE FROM connection_refs WHERE edge IN (SELECT id FROM event_edits WHERE subject='connection' AND side='before')")
            db.execute("INSERT INTO current_nodes SELECT id,body FROM event_edits WHERE subject='node' AND side='after'")
            db.execute("INSERT INTO current_connections SELECT id,body,key FROM event_edits WHERE subject='connection' AND side='after'")
            for subject, table in (('node', 'nodes'), ('connection', 'connections')):
                db.execute(f"INSERT OR IGNORE INTO seen_{table} SELECT id FROM event_edits WHERE subject=? AND side='after'", (subject,))
            for identifier, body in db.execute("SELECT id,body FROM event_edits WHERE subject='connection' AND side='after'"):
                index_connection(db, identifier, body)
            # Existing references can become invalid only when a Node retires.
            # The incident index keeps this check local to the actual edit set.
            if db.execute("""SELECT 1 FROM event_edits e JOIN connection_refs r ON r.node=e.id
                LEFT JOIN current_nodes n ON n.id=r.node
                WHERE e.subject='node' AND e.side='before' AND n.id IS NULL LIMIT 1""").fetchone():
                raise ValueError('connection or unresolved candidate refers to inactive Node')
            db.execute('DELETE FROM event_edits')
            db.execute('DELETE FROM event_lineage')
            event = None

        with (bundle / 'evolution.tsv').open(encoding='utf-8', newline='') as stream:
            if stream.readline() != '\t'.join(HEADERS['evolution']) + '\n':
                raise ValueError('invalid evolution TSV columns')
            for line in stream:
                row = parsed_row(line, HEADERS['evolution'])
                kind = row['record']
                current_seq, current_ordinal = integer(row['seq']), integer(row['ordinal'])
                if footer:
                    raise ValueError('records follow completion footer')
                if current_seq != seq:
                    if current_seq != seq + 1 or kind != 'event' or current_ordinal != 0:
                        raise ValueError('noncontiguous event sequence')
                    seq, ordinal = current_seq, -1
                if current_ordinal != ordinal + 1:
                    raise ValueError('noncontiguous record ordinal')
                ordinal = current_ordinal
                identifier = None if row['object_id'] is None else integer(row['object_id'])
                detail = None if row['detail_json'] is None else json_value(row['detail_json'], dict)
                db.execute('INSERT INTO evolution VALUES(?,?,?,?,?,?,?,?,?)',
                           (kind, seq, ordinal, row['action'], row['reason'], row['subject'], row['side'], identifier,
                            None if detail is None else compact(detail)))
                if header is None:
                    if kind != 'header' or seq or ordinal or not detail or detail.get('mode') != 'trace':
                        raise ValueError('missing native evolution header')
                    if any(detail.get(key) != before['metadata'].get(key) for key in IDENTITY):
                        raise ValueError('evolution and before identity mismatch')
                    if (detail.get('before_snapshot_id') != before['metadata']['snapshot_id'] or
                            not isinstance(detail.get('pass'), str) or not detail['pass'] or
                            not isinstance(detail.get('after_snapshot_id'), str) or not detail['after_snapshot_id']):
                        raise ValueError('evolution not bound to this before snapshot/pass')
                    header = detail
                elif kind == 'decision':
                    if seq != 0 or event is not None:
                        raise ValueError('invalid native pass decision')
                    validate_decision(row, detail, identifier, header, db)
                    decisions += 1
                elif kind == 'event':
                    apply_event()
                    events += 1
                    if seq != events or row['action'] not in ('add', 'delete', 'replace') or not row['reason']:
                        raise ValueError('invalid native event')
                    actions[row['action']] += 1
                    event = row
                elif kind == 'edit':
                    if event is None or row['side'] not in ('before', 'after') or not detail:
                        raise ValueError('edit outside native event')
                    validator = {'node': validate_node, 'connection': validate_connection}.get(row['subject'])
                    if validator is None:
                        raise ValueError('invalid edit subject')
                    payload_id, body, key = validator(detail)
                    if payload_id != identifier:
                        raise ValueError('edit identity differs from its full definition')
                    db.execute('INSERT INTO event_edits VALUES(?,?,?,?,?)', (row['subject'], row['side'], identifier, body, key))
                elif kind == 'lineage':
                    if event is None or row['subject'] != 'node' or row['side'] != 'before' or not detail:
                        raise ValueError('lineage outside Node event')
                    child, coordinates = checked_id(detail.get('to_node_id')), detail.get('coordinates')
                    if detail.get('relation') not in ('split', 'merge', 'derive'):
                        raise ValueError('invalid native lineage relation')
                    if coordinates is not None and (not isinstance(coordinates, list) or any(type(item) is not int or item < 0 for item in coordinates)):
                        raise ValueError('invalid member coordinates')
                    db.execute('INSERT INTO event_lineage VALUES(?,?,?,?)', (identifier, child, detail['relation'], compact(coordinates)))
                    lineage_count += 1
                elif kind == 'footer':
                    apply_event()
                    if not detail or detail.get('complete') is not True or detail.get('replayComplete') is not True:
                        raise ValueError('native pass evolution did not complete')
                    if detail.get('eventCount') != events:
                        raise ValueError('native event count mismatch')
                    if ('decisionCount' in detail and
                            (type(detail['decisionCount']) is not int or detail['decisionCount'] != decisions)):
                        raise ValueError('native decision count mismatch')
                    if type(detail.get('nodeInventoryComplete')) is not bool:
                        raise ValueError('missing native Node inventory coverage')
                    validate_coverage(detail.get('connectionCoverage'))
                    for table, before_key, after_key in (('nodes', 'beforeNodeCount', 'afterNodeCount'),
                                                         ('connections', 'beforeConnectionCount', 'afterConnectionCount')):
                        if (detail.get(before_key) != db.execute(f'SELECT COUNT(*) FROM before_{table}').fetchone()[0] or
                                detail.get(after_key) != db.execute(f'SELECT COUNT(*) FROM current_{table}').fetchone()[0]):
                            raise ValueError('native evolution inventory count mismatch')
                    footer = detail
                else:
                    raise ValueError('invalid native evolution record')
        if footer is None:
            raise ValueError('truncated native evolution')
        after = load_snapshot(bundle, 'after.', db, 'after')
        if (any(after['metadata'].get(key) != header.get(key) for key in IDENTITY) or
                after['metadata']['snapshot_id'] != header.get('after_snapshot_id')):
            raise ValueError('evolution and after identity mismatch')
        if (footer['nodeInventoryComplete'] != after['nodes']['nodeInventoryComplete'] or
                footer['connectionCoverage'] != after['connections']['connectionCoverage']):
            raise ValueError('native evolution coverage differs from actual after')
        for table in ('nodes', 'connections'):
            for left, right in (('current', 'after'), ('after', 'current')):
                if db.execute(f'SELECT * FROM {left}_{table} EXCEPT SELECT * FROM {right}_{table} LIMIT 1').fetchone():
                    raise ValueError('replayed public graph differs from actual after snapshot')
        db.commit()
        return {'schema': 'semantic-node-exchange-verification.v1', 'complete': True, 'replay_exact': True,
                'header': header, 'footer': footer, 'before': before, 'after': after,
                'events': events, 'decisions': decisions, 'actions': dict(actions), 'lineage_count': lineage_count}
    except sqlite3.IntegrityError as error:
        raise ValueError('duplicate object, edit, lineage, or active connection') from error
    finally:
        db.close()


def verify_snapshot(directory, database=':memory:'):
    db = sqlite3.connect(str(database))
    try:
        create_database(db)
        result = load_snapshot(directory, '', db, 'current')
        db.commit()
        return {'complete': True, 'snapshot': result}
    except sqlite3.IntegrityError as error:
        raise ValueError('duplicate public snapshot definition') from error
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--snapshot', action='store_true')
    parser.add_argument('--database', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.database and args.database.exists():
        parser.error('database must be a new file')
    result = (verify_snapshot if args.snapshot else verify_bundle)(args.bundle, args.database or ':memory:')
    encoded = json.dumps(result, indent=2) + '\n'
    if args.report:
        args.report.write_text(encoded)
    print(encoded, end='')


if __name__ == '__main__':
    main()
