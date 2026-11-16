"""Validate static SemanticNode TSV snapshots and replay native pass journals.

after snapshots are opened only after replay; they never supply an edit.
SQLite is derived storage, with no inferred Nodes, connections or lineage.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import re
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
PROVENANCE_BATCH_SIZE = 8192
SQLITE_CACHE_KIB = 256 * 1024


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


def validate_decision(row, detail, identifier, header):
    required = {'pass', 'outcome', 'blocker_node_ids'}
    operation_summary = {'operation_removal_count', 'operation_ids_hash',
                         'first_operation', 'last_operation'}
    dce_deletion_fields = {'rule', 'anchor_count', 'demanded_anchor_count',
                           'owned_operation_count', 'live_owned_operation_count',
                           'port_root', 'protected_boundary_root', 'state_family',
                           'memory_node', 'zero_width_boundary'}
    if (row['action'] is not None or row['subject'] != 'node' or row['side'] != 'before'
            or not isinstance(row['reason'], str) or not row['reason'] or not isinstance(detail, dict)
            or not required <= set(detail) or set(detail) - required - {'update_ordinal', 'axis'} - operation_summary - {'dce_deletion'}
            or not isinstance(detail['pass'], str) or not detail['pass'] or
            detail['pass'] not in header['pass'].split(',')
            or detail['outcome'] not in ('retain', 'replace', 'delete')):
        raise ValueError('invalid native pass decision')
    summary_fields = operation_summary & set(detail)
    if summary_fields:
        if (detail['outcome'] != 'replace' or summary_fields != operation_summary or
                type(detail['operation_removal_count']) is not int or
                not 1 <= detail['operation_removal_count'] <= 2**32 - 1 or
                not isinstance(detail['operation_ids_hash'], str) or
                re.fullmatch('[0-9a-f]{16}', detail['operation_ids_hash']) is None or
                any(type(detail[key]) is not int or not 0 <= detail[key] <= 2**32 - 1
                    for key in ('first_operation', 'last_operation')) or
                row['reason'] != 'owned_operations_removed;count=' + str(detail['operation_removal_count']) +
                ';hash=' + detail['operation_ids_hash']):
            raise ValueError('invalid operation-removal summary decision')
    if 'dce_deletion' in detail:
        deletion = detail['dce_deletion']
        rules = {'memory_without_live_ports', 'dead_state_family', 'dead_owner_anchor',
                 'no_observable_node_demand'}
        count_fields = ('anchor_count', 'demanded_anchor_count',
                        'owned_operation_count', 'live_owned_operation_count')
        bool_fields = ('port_root', 'protected_boundary_root', 'state_family',
                       'memory_node', 'zero_width_boundary')
        if (detail['outcome'] != 'delete' or detail['blocker_node_ids'] != [] or
                not isinstance(deletion, dict) or set(deletion) != dce_deletion_fields or
                not isinstance(deletion.get('rule'), str) or deletion['rule'] not in rules or
                row['reason'] != deletion['rule'] or
                any(type(deletion.get(key)) is not int or not 0 <= deletion[key] <= 2**32 - 1
                    for key in count_fields) or
                deletion['demanded_anchor_count'] > deletion['anchor_count'] or
                deletion['live_owned_operation_count'] > deletion['owned_operation_count'] or
                any(type(deletion.get(key)) is not bool for key in bool_fields)):
            raise ValueError('invalid structured DCE deletion evidence')
    blockers = detail['blocker_node_ids']
    if not isinstance(blockers, list):
        raise ValueError('invalid native decision blockers')
    # Validate scalar identities before hashing; malformed JSON containers must
    # produce a contract error, not an incidental unhashable-type exception.
    checked_blockers = [checked_id(item) for item in blockers]
    if len(set(checked_blockers)) != len(checked_blockers):
        raise ValueError('invalid native decision blockers')
    checked_id(identifier)
    for key in ('update_ordinal', 'axis'):
        if key in detail and (type(detail[key]) is not int or not 0 <= detail[key] <= 2**64 - 1):
            raise ValueError('invalid native decision coordinate')


def validate_liveness_provenance(row, detail, identifier):
    checked_id(identifier)
    if not isinstance(detail, dict) or detail.get('relation') not in ('root', 'edge', 'start', 'residual'):
        raise ValueError('invalid DCE liveness provenance record')
    relation = detail['relation']
    if row['reason'] != relation:
        raise ValueError('DCE liveness provenance relation mismatch')
    entity_kinds = {'value', 'operation'}
    node_id = entity_id = generation = from_id = from_generation = to_id = to_generation = None
    entity_kind = from_kind = to_kind = None
    if relation == 'root':
        required = {'relation', 'entity_kind', 'entity_id', 'generation', 'root_kind'}
        optional = {'root_identity', 'root_identity_generation', 'operation_kind', 'storage_symbol', 'clock_operand'}
        if (not required <= set(detail) or set(detail) - required - optional or
                detail['entity_kind'] not in entity_kinds or
                detail['root_kind'] not in ('output_port', 'declared_value', 'declared_storage',
                                            'observable_operation')):
            raise ValueError('invalid DCE liveness root record')
        entity_kind, entity_id, generation = detail['entity_kind'], detail['entity_id'], detail['generation']
        checked_id(entity_id)
        checked_id(generation)
        if 'root_identity' in detail:
            checked_id(detail['root_identity'])
        if 'root_identity_generation' in detail:
            checked_id(detail['root_identity_generation'])
        if ('root_identity' in detail) != ('root_identity_generation' in detail):
            raise ValueError('incomplete DCE liveness root identity')
        if detail['root_kind'] in ('output_port', 'declared_value'):
            if (entity_kind != 'value' or 'root_identity' in detail or
                    any(key in detail for key in ('operation_kind', 'storage_symbol', 'clock_operand'))):
                raise ValueError('DCE value root has incompatible entity or operation metadata')
        elif detail['root_kind'] == 'declared_storage':
            if (entity_kind != 'operation' or not isinstance(detail.get('operation_kind'), str) or
                    detail['operation_kind'] not in (
                        'kRegister', 'kLatch', 'kRegisterWritePort', 'kRegisterWriteMaskPort',
                        'kRegisterWriteArrayPort', 'kRegisterWriteArrayMaskPort',
                        'kRegisterFillPort', 'kLatchWritePort') or
                    not isinstance(detail.get('storage_symbol'), str) or not detail['storage_symbol'] or
                    'root_identity' not in detail or 'clock_operand' in detail):
                raise ValueError('incomplete DCE declared-storage root identity')
        else:
            if (entity_kind != 'operation' or not isinstance(detail.get('operation_kind'), str) or
                    detail['operation_kind'] not in (
                        'kInstance', 'kBlackbox', 'kSystemFunction', 'kSystemTask',
                        'kDpicImport', 'kDpicCall', 'kXMRWrite') or 'storage_symbol' in detail or
                    'root_identity' not in detail or detail['root_identity'] != entity_id or
                    detail['root_identity_generation'] != generation):
                raise ValueError('invalid DCE observable-operation root identity')
        if 'operation_kind' in detail and (entity_kind != 'operation' or
                                            not isinstance(detail['operation_kind'], str) or
                                            not detail['operation_kind']):
            raise ValueError('invalid DCE liveness root operation kind')
        if detail.get('operation_kind') == 'kSystemTask':
            if ('clock_operand' not in detail or detail['root_kind'] != 'observable_operation' or
                    detail.get('root_identity') != entity_id or
                    detail.get('root_identity_generation') != generation):
                raise ValueError('incomplete native DCE SystemTask root identity')
        if 'storage_symbol' in detail and (detail['root_kind'] != 'declared_storage' or
                                           not isinstance(detail['storage_symbol'], str) or
                                           not detail['storage_symbol']):
            raise ValueError('invalid DCE declared-storage root symbol')
        if 'clock_operand' in detail and (detail.get('operation_kind') != 'kSystemTask' or
                                           type(detail['clock_operand']) is not int or
                                           not 0 <= detail['clock_operand'] <= 2**32 - 1):
            raise ValueError('invalid DCE SystemTask clock operand')
    elif relation == 'edge':
        required = {'relation', 'edge_kind', 'from_kind', 'from_id', 'from_generation',
                    'to_kind', 'to_id', 'to_generation', 'slot'}
        optional = {'storage_symbol', 'operand_role'}
        if (not required <= set(detail) or set(detail) - required - optional or
                detail['edge_kind'] not in ('value_definition', 'operation_operand', 'state_family') or
                detail['from_kind'] not in entity_kinds or detail['to_kind'] not in entity_kinds):
            raise ValueError('invalid DCE liveness edge record')
        from_kind, from_id, from_generation = detail['from_kind'], detail['from_id'], detail['from_generation']
        to_kind, to_id, to_generation = detail['to_kind'], detail['to_id'], detail['to_generation']
        for value in (from_id, from_generation, to_id, to_generation):
            checked_id(value)
        slot = detail['slot']
        if slot is not None and (type(slot) is not int or not 0 <= slot <= 2**32 - 1):
            raise ValueError('invalid DCE liveness edge slot')
        if detail['edge_kind'] == 'value_definition':
            valid = from_kind == 'value' and to_kind == 'operation' and slot is not None
        elif detail['edge_kind'] == 'operation_operand':
            valid = from_kind == 'operation' and to_kind == 'value' and slot is not None
        else:
            valid = (from_kind == to_kind == 'operation' and slot is None and
                     isinstance(detail.get('storage_symbol'), str) and bool(detail['storage_symbol']))
        if (not valid or ('storage_symbol' in detail and detail['edge_kind'] != 'state_family') or
                ('operand_role' in detail and (detail['edge_kind'] != 'operation_operand' or
                                                detail['operand_role'] != 'clock'))):
            raise ValueError('inconsistent DCE liveness edge endpoints')
    elif relation == 'residual':
        fields = {'relation', 'entity_kind', 'entity_id', 'generation', 'owner_ids',
                  'ordinary_retained_owner_count', 'retention_rule'}
        if (set(detail) != fields or detail['entity_kind'] != 'operation' or
                type(detail['ordinary_retained_owner_count']) is not int or
                detail['ordinary_retained_owner_count'] != 0 or
                detail['retention_rule'] != 'preserve_original_owner_set' or
                not isinstance(detail['owner_ids'], list) or not detail['owner_ids']):
            raise ValueError('invalid DCE residual owner group')
        entity_kind, entity_id, generation = 'operation', checked_id(detail['entity_id']), checked_id(detail['generation'])
        owners = [checked_id(owner) for owner in detail['owner_ids']]
        if len(set(owners)) != len(owners):
            raise ValueError('duplicate DCE residual owner identity')
    else:
        required = {'relation', 'node_id', 'start_kind'}
        optional = {'entity_kind', 'entity_id', 'generation', 'boundary', 'binding', 'owner_count',
                    'port_name', 'port_kind'}
        starts = {'anchor', 'owned_operation', 'boundary_use', 'zero_width_binding', 'unresolved', 'input_port'}
        if (not required <= set(detail) or set(detail) - required - optional or
                detail['start_kind'] not in starts):
            raise ValueError('invalid DCE liveness Node start record')
        node_id = checked_id(detail['node_id'])
        if detail['start_kind'] in ('anchor', 'owned_operation', 'boundary_use', 'input_port'):
            if (detail.get('entity_kind') not in entity_kinds or 'entity_id' not in detail or
                    'generation' not in detail):
                raise ValueError('incomplete DCE liveness Node start entity')
            entity_kind, entity_id, generation = detail['entity_kind'], detail['entity_id'], detail['generation']
            checked_id(entity_id)
            checked_id(generation)
            if ((detail['start_kind'] in ('anchor', 'input_port')) != (entity_kind == 'value') or
                    (detail['start_kind'] in ('owned_operation', 'boundary_use') and
                     entity_kind != 'operation')):
                raise ValueError('inconsistent DCE liveness Node start kind')
        elif any(key in detail for key in ('entity_kind', 'entity_id', 'generation')):
            raise ValueError('unexpected entity on structural DCE liveness Node start')
        if 'owner_count' in detail and (detail['start_kind'] != 'owned_operation' or
                                       type(detail['owner_count']) is not int or
                                       not 1 <= detail['owner_count'] <= 2**32 - 1):
            raise ValueError('invalid DCE owned-operation owner count')
        if detail['start_kind'] == 'input_port':
            if (not isinstance(detail.get('port_name'), str) or not detail['port_name'] or
                    detail.get('port_kind') not in ('input', 'inout')):
                raise ValueError('invalid exact DCE input Port start')
        elif any(key in detail for key in ('port_name', 'port_kind')):
            raise ValueError('Port evidence on a non-input DCE start')
        if detail['start_kind'] == 'boundary_use':
            boundary = detail.get('boundary')
            fields = {'source', 'target', 'value', 'value_generation', 'user',
                      'user_generation', 'operand_index', 'kind'}
            if (not isinstance(boundary, dict) or set(boundary) != fields or
                    any(type(boundary[key]) is not int or not 0 <= boundary[key] <= 2**63 - 1
                        for key in fields - {'kind'}) or
                    not isinstance(boundary['kind'], str) or not boundary['kind'] or
                    boundary['source'] != node_id or boundary['user'] != entity_id or
                    boundary['user_generation'] != generation):
                raise ValueError('invalid exact DCE boundary-use start')
        elif 'boundary' in detail:
            raise ValueError('boundary evidence on a non-boundary DCE start')
        if detail['start_kind'] == 'zero_width_binding':
            binding = detail.get('binding')
            binding_fields = {'role', 'source_width', 'shape', 'shape_field_depths', 'projection'}
            if (not isinstance(binding, dict) or set(binding) != binding_fields or
                    not isinstance(binding['role'], str) or not binding['role'] or
                    type(binding['source_width']) is not int or
                    any(not isinstance(binding[key], list) or any(type(item) is not int for item in binding[key])
                        for key in ('shape', 'shape_field_depths', 'projection'))):
                raise ValueError('invalid structural DCE binding start')
        elif 'binding' in detail:
            raise ValueError('binding evidence on a non-structural DCE start')
    columns = (node_id, entity_kind, entity_id, generation,
               from_kind, from_id, from_generation, to_kind, to_id, to_generation)
    return relation, compact(detail), columns


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


def validate_residual_owner_groups(db):
    if db.execute("SELECT 1 FROM liveness_provenance WHERE relation='residual' LIMIT 1").fetchone() is None:
        return
    if db.execute('''SELECT 1 FROM liveness_provenance WHERE relation='residual'
            GROUP BY entity_kind,entity_id,generation HAVING COUNT(*)!=1 LIMIT 1''').fetchone():
        raise ValueError('duplicate DCE residual operation group')
    # Scan operation starts once, probing the much smaller residual index.
    # This also detects contradictory extra memberships outside owner_ids.
    db.execute('''CREATE TEMP TABLE residual_owner_memberships AS
        SELECT r.id AS group_id,p.node_id,json_extract(p.detail_json,'$.owner_count') AS owner_count
        FROM liveness_provenance p CROSS JOIN liveness_provenance r
        WHERE p.relation='start' AND p.entity_kind='operation'
            AND r.relation='residual' AND r.entity_kind=p.entity_kind
            AND r.entity_id=p.entity_id AND r.generation=p.generation
            AND json_extract(p.detail_json,'$.start_kind')='owned_operation' ''')
    db.execute('CREATE INDEX residual_owner_memberships_group ON residual_owner_memberships(group_id)')
    for group_id, payload in db.execute("SELECT id,detail_json FROM liveness_provenance WHERE relation='residual'"):
        group = json.loads(payload)
        owners = group['owner_ids']
        memberships = db.execute('SELECT node_id,owner_count FROM residual_owner_memberships WHERE group_id=?',
                                 (group_id,)).fetchall()
        if (sorted(owner for owner, _ in memberships) != sorted(owners) or
                any(count != len(owners) for _, count in memberships)):
            raise ValueError('DCE residual group differs from complete original operation memberships')
        for owner in owners:
            if (db.execute('SELECT 1 FROM current_nodes WHERE id=?', (owner,)).fetchone() is None or
                    db.execute('''SELECT 1 FROM evolution WHERE record='decision' AND subject='node'
                        AND side='before' AND object_id=? AND substr(reason,1,9)='residual:'
                        AND json_extract(detail_json,'$.outcome')='retain' LIMIT 1''', (owner,)).fetchone() is None):
                raise ValueError('DCE residual group lacks complete original memberships, retained owners, or residual decisions')
    db.execute('DROP TABLE residual_owner_memberships')


def create_database(db):
    # Bound the derived database's page cache while keeping random provenance
    # index updates from cycling through SQLite's small default cache.
    db.execute(f'PRAGMA main.cache_size=-{SQLITE_CACHE_KIB}')
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
        CREATE INDEX residual_retention_decisions ON evolution(object_id)
            WHERE record='decision' AND subject='node' AND side='before' AND substr(reason,1,9)='residual:';
        CREATE TABLE event_edits(subject TEXT,side TEXT,id INTEGER,body TEXT,key TEXT,PRIMARY KEY(subject,side,id));
        CREATE TABLE event_lineage(parent INTEGER,child INTEGER,relation TEXT,coordinates TEXT,
            PRIMARY KEY(parent,child,relation,coordinates));
        CREATE TABLE event_transition_evidence(seq INTEGER,ordinal INTEGER,connection_id INTEGER,
            reason TEXT NOT NULL,subject TEXT NOT NULL,side TEXT NOT NULL,detail_json TEXT NOT NULL,
            PRIMARY KEY(seq,ordinal),UNIQUE(seq,connection_id));
        CREATE TABLE connection_transition_evidence(seq INTEGER,ordinal INTEGER,connection_id INTEGER,
            detail_json TEXT NOT NULL,PRIMARY KEY(seq,ordinal),UNIQUE(connection_id));
        CREATE TABLE event_removal_evidence(seq INTEGER,ordinal INTEGER,connection_id INTEGER,
            detail_json TEXT NOT NULL,PRIMARY KEY(seq,ordinal),UNIQUE(connection_id,detail_json));
        CREATE TABLE connection_removal_evidence(seq INTEGER,ordinal INTEGER,connection_id INTEGER,
            detail_json TEXT NOT NULL,PRIMARY KEY(seq,ordinal),UNIQUE(connection_id,detail_json));
        CREATE TABLE connection_evidence(connection_id INTEGER,detail_json TEXT,
            PRIMARY KEY(connection_id,detail_json));
        CREATE TABLE operand_mutations(mutation_id INTEGER PRIMARY KEY,operation_id INTEGER NOT NULL,
            operation_generation INTEGER NOT NULL,action TEXT NOT NULL,before_slot INTEGER,before_value_id INTEGER,
            before_value_generation INTEGER,after_slot INTEGER,after_value_id INTEGER,after_value_generation INTEGER,
            reason TEXT NOT NULL);
        CREATE TABLE operand_mutation_owners(mutation_id INTEGER NOT NULL,node_id INTEGER NOT NULL,
            PRIMARY KEY(mutation_id,node_id));
        CREATE TABLE boundary_retirements(boundary_id INTEGER PRIMARY KEY,detail_json TEXT NOT NULL);
        CREATE TABLE anchor_removals(anchor_removal_id INTEGER PRIMARY KEY,target_node_id INTEGER NOT NULL,
            operation_id INTEGER NOT NULL,operation_generation INTEGER NOT NULL,
            value_id INTEGER NOT NULL,value_generation INTEGER NOT NULL);
        CREATE INDEX operand_mutation_owners_node ON operand_mutation_owners(node_id);
        CREATE TABLE liveness_provenance(id INTEGER PRIMARY KEY,relation TEXT NOT NULL,detail_json TEXT NOT NULL,
            node_id INTEGER,entity_kind TEXT,entity_id INTEGER,generation INTEGER,
            from_kind TEXT,from_id INTEGER,from_generation INTEGER,
            to_kind TEXT,to_id INTEGER,to_generation INTEGER);
        CREATE INDEX liveness_provenance_node ON liveness_provenance(relation,node_id) WHERE relation='start';
        CREATE INDEX liveness_provenance_entity ON liveness_provenance(relation,entity_kind,entity_id,generation) WHERE relation='root';
        CREATE INDEX liveness_provenance_residual ON liveness_provenance(relation,entity_kind,entity_id,generation) WHERE relation='residual';
        CREATE INDEX liveness_provenance_target ON liveness_provenance(relation,to_kind,to_id,to_generation) WHERE relation='edge';
        CREATE TABLE connection_refs(edge INTEGER,node INTEGER,PRIMARY KEY(edge,node));
        CREATE INDEX connection_refs_node ON connection_refs(node);
    ''')


def validate_active(db, prefix='current'):
    validate_connection_refs(db, f'{prefix}_nodes', f'SELECT id,body FROM {prefix}_connections')


def validate_connection_refs(db, nodes, connections):
    # All scalar/JSON types were checked while loading. Keep endpoint checks in
    # SQLite rather than issuing two or more Python queries per full-graph edge.
    if db.execute(f'''SELECT 1 FROM ({connections}) e
        LEFT JOIN {nodes} t ON t.id=json_extract(e.body,'$.target_node_id')
        LEFT JOIN {nodes} s ON s.id=json_extract(e.body,'$.source_node_id')
        WHERE t.id IS NULL OR (json_extract(e.body,'$.source_node_id') IS NOT NULL AND s.id IS NULL)
        UNION ALL SELECT 1 FROM ({connections}) e,json_each(e.body,'$.candidate_sources_json') c
        LEFT JOIN {nodes} n ON n.id=c.value WHERE n.id IS NULL LIMIT 1''').fetchone():
        raise ValueError('connection or unresolved candidate refers to inactive Node')


def validate_connection_evidence(db, header, footer):
    if header.get('connection_evidence') != 'postpass-native-walk':
        if any(key in footer for key in ('connectionEvidenceRequestCount', 'connectionEvidenceConnectionCount',
                                         'connectionEvidenceRecordCount', 'connectionEvidenceMissingSupportCount',
                                         'connectionEvidenceMutationMatchCount')):
            raise ValueError('connection evidence footer is missing its header declaration')
        if db.execute('SELECT 1 FROM connection_evidence LIMIT 1').fetchone():
            raise ValueError('undeclared native connection evidence')
        return None

    fields = ('connectionEvidenceRequestCount', 'connectionEvidenceConnectionCount',
              'connectionEvidenceRecordCount', 'connectionEvidenceMissingSupportCount')
    mutation_trace = header.get('mutation_trace')
    if mutation_trace is not None:
        if mutation_trace != 'operand-rewrite.v1':
            raise ValueError('unsupported native mutation trace declaration')
        fields += ('connectionEvidenceMutationMatchCount',)
    if any(type(footer.get(field)) is not int or footer[field] < 0 for field in fields):
        raise ValueError('invalid connection evidence footer counts')
    record_count = db.execute('SELECT COUNT(*) FROM connection_evidence').fetchone()[0]
    connection_count = db.execute('SELECT COUNT(DISTINCT connection_id) FROM connection_evidence').fetchone()[0]
    missing_count = db.execute("""SELECT COUNT(*) FROM connection_evidence
        WHERE json_extract(detail_json,'$.witness_kind')='missing_native_boundary'""").fetchone()[0]
    mutation_match_count = db.execute("""SELECT COUNT(*) FROM connection_evidence
        WHERE json_extract(detail_json,'$.mutation_id') IS NOT NULL""").fetchone()[0]
    expected = db.execute("""SELECT COUNT(DISTINCT e.object_id) FROM evolution e
        JOIN current_connections c ON c.id=e.object_id
        WHERE e.record='edit' AND e.subject='connection' AND e.side='after'
          AND json_extract(c.body,'$.kind')='dependency'""").fetchone()[0]
    if (footer['connectionEvidenceRecordCount'] != record_count or
            footer['connectionEvidenceConnectionCount'] != connection_count or
            footer['connectionEvidenceMissingSupportCount'] != missing_count or
            (mutation_trace is not None and
             footer['connectionEvidenceMutationMatchCount'] != mutation_match_count) or
            footer['connectionEvidenceRequestCount'] != expected or connection_count != expected):
        raise ValueError('connection evidence does not cover every surviving added dependency')
    if db.execute("""WITH expected(id) AS (
          SELECT DISTINCT e.object_id FROM evolution e
          JOIN current_connections c ON c.id=e.object_id
          WHERE e.record='edit' AND e.subject='connection' AND e.side='after'
            AND json_extract(c.body,'$.kind')='dependency'
        ), actual(id) AS (SELECT DISTINCT connection_id FROM connection_evidence)
        SELECT 1 FROM expected e LEFT JOIN actual a ON a.id=e.id WHERE a.id IS NULL
        UNION ALL
        SELECT 1 FROM actual a LEFT JOIN expected e ON e.id=a.id WHERE e.id IS NULL
        LIMIT 1""").fetchone():
        raise ValueError('connection evidence IDs differ from surviving added dependencies')
    if db.execute("""SELECT 1 FROM connection_evidence e
        LEFT JOIN current_connections c ON c.id=e.connection_id
        LEFT JOIN evolution a ON a.record='edit' AND a.subject='connection' AND a.side='after'
            AND a.object_id=e.connection_id
        WHERE c.id IS NULL OR a.object_id IS NULL OR
          json_extract(c.body,'$.kind')<>'dependency' OR
          json_extract(e.detail_json,'$.phase')<>'postpass-native-walk' OR
          json_extract(e.detail_json,'$.connection_id')<>e.connection_id OR
          json_extract(e.detail_json,'$.witness_kind') NOT IN
            ('boundary_use','fallback_value_owner','missing_native_boundary','external_operation') OR
          (json_extract(e.detail_json,'$.supporting_node_id') IS NOT NULL AND NOT (
            (json_extract(c.body,'$.source_node_id') IS NOT NULL AND
             json_extract(e.detail_json,'$.supporting_node_id')=json_extract(c.body,'$.source_node_id')) OR
            EXISTS (SELECT 1 FROM json_each(c.body,'$.candidate_sources_json') x
                    WHERE x.value=json_extract(e.detail_json,'$.supporting_node_id')))) OR
          (json_extract(e.detail_json,'$.witness_kind')='boundary_use' AND
           (json_extract(e.detail_json,'$.reference_target_node_id')<>
                json_extract(c.body,'$.target_node_id') OR
            CASE
              WHEN json_extract(e.detail_json,'$.boundary_kind') IN ('data','clock','reset','predicate') THEN 'dependency'
              WHEN json_extract(e.detail_json,'$.boundary_kind')='state-update' THEN 'state_update'
              WHEN json_extract(e.detail_json,'$.boundary_kind') IN
                ('dependency','state_update','storage_read','storage_write','external_binding','unknown')
                THEN json_extract(e.detail_json,'$.boundary_kind')
              ELSE 'unknown'
            END <> json_extract(c.body,'$.kind'))) OR
          (json_extract(e.detail_json,'$.witness_kind')='external_operation' AND
           (json_extract(c.body,'$.kind')<>'external_binding' OR
            json_extract(e.detail_json,'$.operation_id') IS NULL)) OR
          (json_extract(e.detail_json,'$.mutation_id') IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM operand_mutations m WHERE m.mutation_id=json_extract(e.detail_json,'$.mutation_id')
              AND m.action IN ('add','replace')
              AND m.operation_id=json_extract(e.detail_json,'$.operation_id')
              AND m.operation_generation=json_extract(e.detail_json,'$.operation_generation')
              AND m.after_slot=json_extract(e.detail_json,'$.operand_index')
              AND m.after_value_id=json_extract(e.detail_json,'$.value_id')
              AND m.after_value_generation=json_extract(e.detail_json,'$.value_generation')
              AND json_extract(e.detail_json,'$.mutation_match')='exact_consumer_operand_value'
            UNION ALL
            SELECT 1 FROM operand_mutations m
            WHERE m.mutation_id=json_extract(e.detail_json,'$.mutation_id')
              AND m.action IN ('add','replace')
              AND m.operation_id=json_extract(e.detail_json,'$.reference_operation_id')
              AND m.operation_generation=json_extract(e.detail_json,'$.reference_operation_generation')
              AND m.after_slot=json_extract(e.detail_json,'$.reference_operand_index')
              AND m.after_value_id=json_extract(e.detail_json,'$.value_id')
              AND m.after_value_generation=json_extract(e.detail_json,'$.value_generation')
              AND json_extract(e.detail_json,'$.mutation_match')='exact_boundary_reference_value'))
        LIMIT 1""").fetchone():
        raise ValueError('native connection witness does not support its final dependency')
    if mutation_trace is None and mutation_match_count:
        raise ValueError('native connection witness uses undeclared mutation evidence')
    return {'requests': expected, 'connections': connection_count,
            'records': record_count, 'missing_support_records': missing_count,
            'exact_operand_mutation_matches': mutation_match_count,
            'unmatched_witness_records': record_count - mutation_match_count}


def validate_connection_evidence_record(detail, identifier, header):
    common = {'phase', 'connection_id', 'witness_kind'}
    optional = {'supporting_node_id', 'reference_target_node_id', 'value_id', 'value_generation',
                'operation_id', 'operation_generation', 'operand_index', 'reference_operation_id',
                'reference_operation_generation', 'reference_operand_index',
                'value_definition_operation_id', 'value_definition_operation_generation', 'boundary_kind',
                'mutation_id', 'mutation_match'}
    if (not isinstance(detail, dict) or header.get('connection_evidence') != 'postpass-native-walk' or
            not common <= set(detail) or set(detail) - common - optional or
            detail.get('phase') != 'postpass-native-walk' or detail.get('connection_id') != identifier):
        raise ValueError('invalid native connection witness identity')
    witness_kind = detail.get('witness_kind')
    if witness_kind not in ('boundary_use', 'fallback_value_owner',
                            'missing_native_boundary', 'external_operation'):
        raise ValueError('invalid native connection witness identity')

    node_ids = ('supporting_node_id', 'reference_target_node_id')
    value_ids = ('value_id', 'value_generation')
    operation_pairs = (('operation_id', 'operation_generation'),
                       ('reference_operation_id', 'reference_operation_generation'),
                       ('value_definition_operation_id', 'value_definition_operation_generation'))
    for key in node_ids:
        if key in detail and (type(detail[key]) is not int or not 1 <= detail[key] <= 2**32 - 1):
            raise ValueError('invalid native connection witness Node ID')
    if 'value_id' in detail:
        if (type(detail['value_id']) is not int or not 1 <= detail['value_id'] <= 2**32 - 1 or
                type(detail.get('value_generation')) is not int or not 0 <= detail['value_generation'] <= 2**32 - 1):
            raise ValueError('invalid native connection witness value ID')
    elif 'value_generation' in detail:
        raise ValueError('invalid native connection witness value ID')
    for identity, generation in operation_pairs:
        if identity in detail:
            if (type(detail[identity]) is not int or not 1 <= detail[identity] <= 2**32 - 1 or
                    type(detail.get(generation)) is not int or not 0 <= detail[generation] <= 2**32 - 1):
                raise ValueError('invalid native connection witness operation ID')
        elif generation in detail:
            raise ValueError('invalid native connection witness operation ID')
    for key in ('operand_index', 'reference_operand_index'):
        if key in detail and (type(detail[key]) is not int or not 0 <= detail[key] < 2**32 - 1):
            raise ValueError('invalid native connection witness operand index')
    if 'operand_index' in detail and 'operation_id' not in detail:
        raise ValueError('native connection witness consumer operation is incomplete')
    if ('mutation_id' in detail) != ('mutation_match' in detail):
        raise ValueError('native connection witness mutation link is incomplete')
    if 'mutation_id' in detail and (type(detail['mutation_id']) is not int or detail['mutation_id'] < 1 or
                                    detail['mutation_match'] not in ('exact_consumer_operand_value',
                                                                     'exact_boundary_reference_value') or
                                    not {'value_id', 'value_generation'} <= set(detail) or
                                    (detail['mutation_match'] == 'exact_consumer_operand_value' and
                                     not {'operation_id', 'operation_generation', 'operand_index'} <= set(detail)) or
                                    (detail['mutation_match'] == 'exact_boundary_reference_value' and
                                     not {'reference_operation_id', 'reference_operation_generation',
                                          'reference_operand_index'} <= set(detail))):
        raise ValueError('invalid native connection witness mutation link')
    if witness_kind == 'boundary_use':
        if (not {'supporting_node_id', 'reference_target_node_id', 'boundary_kind'} <= set(detail) or
                not isinstance(detail['boundary_kind'], str) or not detail['boundary_kind']):
            raise ValueError('native boundary witness is incomplete')
    elif witness_kind == 'fallback_value_owner':
        if (not {'supporting_node_id', 'value_id', 'operation_id', 'operand_index'} <= set(detail)):
            raise ValueError('native fallback witness is incomplete')
    elif witness_kind == 'external_operation' and 'operation_id' not in detail:
        raise ValueError('native external-operation witness has no operation')


def validate_connection_transition_record(db, row, detail, identifier, header, event, event_sequence):
    if isinstance(detail, dict) and detail.get('cause') == 'dependency_exposed_by_boundary_retirement':
        return validate_boundary_retirement_transition(db, row, detail, identifier, header, event, event_sequence)
    required = {'phase', 'cause', 'event_sequence', 'source_connection_id', 'deleted_node_ids'}
    if (header.get('connection_transition_trace') != 'candidate-prune.v1' or event is None or
            row['action'] is not None or row['reason'] != 'candidate_pruned_by_node_deletion' or
            row['subject'] != 'connection' or row['side'] != 'after' or
            not isinstance(detail, dict) or set(detail) != required or
            detail.get('phase') != 'pass-transition' or
            detail.get('cause') != 'candidate_pruned_by_node_deletion' or
            type(detail.get('event_sequence')) is not int or detail['event_sequence'] != event_sequence):
        raise ValueError('invalid candidate-prune transition evidence identity')
    source_id = checked_id(detail['source_connection_id'])
    deleted_ids = detail['deleted_node_ids']
    if (not isinstance(deleted_ids, list) or not deleted_ids or
            any(type(node_id) is not int or not 0 <= node_id <= 2**63 - 1 for node_id in deleted_ids) or
            deleted_ids != sorted(set(deleted_ids))):
        raise ValueError('invalid candidate-prune deleted Node set')
    if identifier == source_id:
        raise ValueError('candidate-prune transition reuses its source connection ID')

    before = db_connection_edit(db, 'before', source_id)
    after = db_connection_edit(db, 'after', identifier)
    if before is None or after is None:
        raise ValueError('candidate-prune transition does not name same-event connection edits')
    old = json.loads(before)
    new = json.loads(after)
    if (old['resolution'] != 'unresolved' or old['kind'] != 'dependency' or
            old['source_node_id'] is not None):
        raise ValueError('candidate-prune source is not an unresolved dependency')
    if db.execute('SELECT 1 FROM before_connections WHERE id=?', (source_id,)).fetchone() is None:
        raise ValueError('candidate-prune source connection is not in the before snapshot')
    if db.execute('SELECT 1 FROM before_connections WHERE id=?', (identifier,)).fetchone() is not None:
        raise ValueError('candidate-prune created connection is not new')
    if db_connection_edit(db, 'after', source_id) is not None:
        raise ValueError('candidate-prune source connection was not erased')

    deleted = set(deleted_ids)
    candidates = set(old['candidate_sources_json'])
    if not deleted <= candidates:
        raise ValueError('candidate-prune deleted Nodes are not source candidates')
    expected_candidates = sorted(candidates - deleted)
    resolves = len(expected_candidates) == 1 and old['reason'] == 'ambiguous-native-boundary'
    if resolves:
        if (new['resolution'] != 'resolved' or new['kind'] != 'dependency' or
                new['source_node_id'] != expected_candidates[0] or
                new['target_node_id'] != old['target_node_id'] or
                new['candidate_sources_json'] != [] or new['reason'] is not None):
            raise ValueError('candidate-prune resolved connection does not match the pruned candidate set')
    elif (new['resolution'] != 'unresolved' or new['kind'] != 'dependency' or
          new['source_node_id'] is not None or new['target_node_id'] != old['target_node_id'] or
          new['candidate_sources_json'] != expected_candidates or new['reason'] != old['reason']):
        raise ValueError('candidate-prune created connection does not match the pruned candidate set')

    for node_id in deleted_ids:
        if (db.execute("SELECT 1 FROM event_edits WHERE subject='node' AND side='before' AND id=?",
                       (node_id,)).fetchone() is None or
                db.execute("SELECT 1 FROM event_edits WHERE subject='node' AND side='after' AND id=?",
                           (node_id,)).fetchone() is not None):
            raise ValueError('candidate-prune deleted Node was not retired in the same event')


def validate_boundary_retirement_record(row, detail, identifier, header):
    fields = {'boundary_id', 'source_node_id', 'target_node_id', 'value_id', 'value_generation',
              'operation_id', 'operation_generation', 'operand_index', 'boundary_kind'}
    if (header.get('boundary_retirement_trace') != 'boundary-retirement.v1' or
            row['action'] != 'delete' or row['reason'] != 'retired_node_boundary' or
            row['subject'] != 'boundary' or row['side'] != 'before' or
            not isinstance(detail, dict) or set(detail) != fields or
            type(detail.get('boundary_id')) is not int or detail['boundary_id'] != identifier or
            not 1 <= identifier <= 2**63 - 1):
        raise ValueError('invalid native boundary retirement identity')
    for field in ('source_node_id', 'target_node_id', 'value_id'):
        if type(detail[field]) is not int or not 1 <= detail[field] <= 2**32 - 1:
            raise ValueError('invalid native boundary retirement endpoint')
    for field in ('value_generation', 'operation_id', 'operation_generation'):
        if type(detail[field]) is not int or not 0 <= detail[field] <= 2**32 - 1:
            raise ValueError('invalid native boundary retirement entity')
    slot = detail['operand_index']
    if slot is not None and (type(slot) is not int or not 0 <= slot < 2**32 - 1):
        raise ValueError('invalid native boundary retirement operand')
    if not detail['operation_id'] and (detail['operation_generation'] or slot is not None):
        raise ValueError('incomplete native boundary retirement operation')
    if detail['boundary_kind'] not in ('data', 'clock', 'reset', 'predicate', 'dependency', 'value_owner'):
        raise ValueError('unsupported native boundary retirement kind')
    if detail['boundary_kind'] == 'value_owner' and detail['operation_id']:
        raise ValueError('value-owner retirement has a boundary operation')


def validate_boundary_retirement_transition(db, row, detail, identifier, header, event, event_sequence):
    fields = {'phase', 'cause', 'event_sequence', 'source_connection_id', 'boundary_id',
              'supporting_node_id', 'start_context', 'path'}
    if (header.get('boundary_retirement_trace') != 'boundary-retirement.v1' or event is None or
            row['action'] is not None or row['reason'] != 'dependency_exposed_by_boundary_retirement' or
            row['subject'] != 'connection' or row['side'] != 'after' or set(detail) != fields or
            detail.get('phase') != 'pass-transition' or
            detail.get('cause') != 'dependency_exposed_by_boundary_retirement' or
            type(detail.get('event_sequence')) is not int or detail['event_sequence'] != event_sequence):
        raise ValueError('invalid boundary-retirement transition identity')
    source_id = checked_id(detail['source_connection_id'])
    boundary_id = checked_id(detail['boundary_id'])
    supporting_node = checked_id(detail['supporting_node_id'])
    record = db.execute('SELECT detail_json FROM boundary_retirements WHERE boundary_id=?',
                        (boundary_id,)).fetchone()
    if record is None:
        raise ValueError('boundary-retirement transition has no native retirement record')
    boundary = json.loads(record[0])
    before = db_connection_edit(db, 'before', source_id)
    after = db_connection_edit(db, 'after', identifier)
    if before is None or after is None or source_id == identifier:
        raise ValueError('boundary-retirement transition does not name distinct same-event connection edits')
    old, new = json.loads(before), json.loads(after)
    old_sources = ([old['source_node_id']] if old['source_node_id'] is not None
                   else old['candidate_sources_json'])
    new_sources = ([new['source_node_id']] if new['source_node_id'] is not None
                   else new['candidate_sources_json'])
    if (old['kind'] != 'dependency' or new['kind'] != 'dependency' or
            old['target_node_id'] != boundary['target_node_id'] or
            new['target_node_id'] != boundary['target_node_id'] or
            boundary['source_node_id'] not in old_sources or
            supporting_node not in new_sources or not new_sources):
        raise ValueError('boundary-retirement transition does not support its dependency endpoints')
    if (db.execute('SELECT 1 FROM before_connections WHERE id=?', (source_id,)).fetchone() is None or
            db.execute('SELECT 1 FROM before_connections WHERE id=?', (identifier,)).fetchone() is not None or
            db_connection_edit(db, 'after', source_id) is not None):
        raise ValueError('boundary-retirement transition does not replace a before connection')
    retired = boundary['source_node_id']
    if (db.execute("SELECT 1 FROM event_edits WHERE subject='node' AND side='before' AND id=?",
                   (retired,)).fetchone() is None or
            db.execute("SELECT 1 FROM event_edits WHERE subject='node' AND side='after' AND id=?",
                       (retired,)).fetchone() is not None):
        raise ValueError('boundary-retirement source Node was not retired in the same event')

    context = detail['start_context']
    if (not isinstance(context, dict) or set(context) != {'operation_id', 'operation_generation', 'operand_index'} or
            any(type(context[field]) is not int or not 0 <= context[field] <= 2**32 - 1
                for field in ('operation_id', 'operation_generation')) or
            (context['operand_index'] is not None and
             (type(context['operand_index']) is not int or not 0 <= context['operand_index'] < 2**32 - 1)) or
            (not context['operation_id'] and (context['operation_generation'] or context['operand_index'] is not None))):
        raise ValueError('invalid boundary-retirement start context')
    if boundary['operation_id'] and (
            context['operation_id'] != boundary['operation_id'] or
            context['operation_generation'] != boundary['operation_generation'] or
            (boundary['operand_index'] is not None and context['operand_index'] != boundary['operand_index'])):
        raise ValueError('boundary-retirement start does not match the retired operand use')
    steps = detail['path']
    if not isinstance(steps, list):
        raise ValueError('boundary-retirement transition has no native dependency path')
    if not steps and (not boundary['operation_id'] or boundary['operand_index'] is None):
        raise ValueError('zero-step boundary retirement requires an exact native operand use')
    step_fields = {'value_id', 'value_generation', 'definition_operation_id',
                   'definition_operation_generation', 'operand_index', 'operand_value_id',
                   'operand_value_generation'}
    value = (boundary['value_id'], boundary['value_generation'])
    reached = {value}
    for step in steps:
        if (not isinstance(step, dict) or set(step) != step_fields or
                any(type(step[field]) is not int or not 0 <= step[field] <= 2**32 - 1
                    for field in step_fields) or
                not step['value_id'] or not step['definition_operation_id'] or not step['operand_value_id'] or
                step['operand_index'] == 2**32 - 1 or
                (step['value_id'], step['value_generation']) != value):
            raise ValueError('invalid or disconnected boundary-retirement native path')
        value = (step['operand_value_id'], step['operand_value_generation'])
        if value in reached:
            raise ValueError('cyclic boundary-retirement native path')
        reached.add(value)
    terminal_operation = context['operation_id']
    terminal_generation = context['operation_generation']
    terminal_slot = context['operand_index']
    if steps:
        last = steps[-1]
        terminal_operation = last['definition_operation_id']
        terminal_generation = last['definition_operation_generation']
        terminal_slot = last['operand_index']
    # A path proves the whole public candidate edge only when every source has
    # native support at its exact terminal operand, including unresolved edges.
    for source in new_sources:
        if db.execute('''SELECT 1 FROM connection_evidence WHERE connection_id=?
            AND json_extract(detail_json,'$.supporting_node_id')=?
            AND json_extract(detail_json,'$.witness_kind') IN ('boundary_use','fallback_value_owner')
            AND json_extract(detail_json,'$.value_id')=?
            AND json_extract(detail_json,'$.value_generation')=?
            AND json_extract(detail_json,'$.operation_id')=?
            AND json_extract(detail_json,'$.operation_generation')=?
            AND json_extract(detail_json,'$.operand_index')=? LIMIT 1''',
            (identifier, source, *value, terminal_operation,
             terminal_generation, terminal_slot)).fetchone() is None:
            raise ValueError('boundary-retirement path has no exact terminal native support')


def db_connection_edit(db, side, identifier):
    row = db.execute(
        "SELECT body FROM event_edits WHERE subject='connection' AND side=? AND id=?",
        (side, identifier)).fetchone()
    return None if row is None else row[0]


def connection_removal_terminal(detail):
    steps = detail['path']
    if not isinstance(steps, list):
        raise ValueError('connection removal lacks a native dependency path')
    fields = {'value_id', 'value_generation', 'definition_operation_id',
              'definition_operation_generation', 'operand_index', 'operand_value_id',
              'operand_value_generation'}
    value = (detail['value_id'], detail['value_generation'])
    reached = {value}
    terminal = (detail['operation_id'], detail['operation_generation'], detail['operand_index'])
    for step in steps:
        if (not isinstance(step, dict) or set(step) != fields or
                any(type(step[field]) is not int or not 0 <= step[field] <= 2**32 - 1
                    for field in fields) or
                not step['value_id'] or not step['definition_operation_id'] or not step['operand_value_id'] or
                step['operand_index'] == 2**32 - 1 or
                (step['value_id'], step['value_generation']) != value):
            raise ValueError('invalid or disconnected connection removal native path')
        value = (step['operand_value_id'], step['operand_value_generation'])
        if value in reached:
            raise ValueError('cyclic connection removal native path')
        reached.add(value)
        terminal = (step['definition_operation_id'], step['definition_operation_generation'],
                    step['operand_index'])
    return terminal


def validate_connection_removal_support(detail, terminal=None):
    for field in ('reference_target_node_id', 'reference_operation_id', 'reference_operation_generation',
                  'value_definition_operation_id', 'value_definition_operation_generation'):
        if type(detail[field]) is not int or not 0 <= detail[field] <= 2**32 - 1:
            raise ValueError('invalid native connection removal support identity')
    reference = (detail['reference_operation_id'], detail['reference_operation_generation'])
    definition = (detail['value_definition_operation_id'], detail['value_definition_operation_generation'])
    slot = detail['reference_operand_index']
    if ((slot is not None and (type(slot) is not int or not 0 <= slot < 2**32 - 1)) or
            (not reference[0] and reference[1]) or (not definition[0] and definition[1])):
        raise ValueError('invalid native connection removal support generation or slot')
    if detail['support_kind'] == 'fallback_value_owner':
        if (detail['boundary_kind'] is not None or detail['reference_target_node_id'] != 0 or
                reference != (0, 0) or slot is not None):
            raise ValueError('fallback connection removal has fabricated native boundary context')
    elif detail['support_kind'] == 'boundary_use':
        if (detail['boundary_kind'] not in ('data', 'clock', 'reset', 'predicate') or
                detail['reference_target_node_id'] != detail['target_node_id']):
            raise ValueError('invalid native connection removal boundary support')
        operation, generation, operand = (terminal if terminal is not None else
                                         (detail['operation_id'], detail['operation_generation'],
                                          detail['operand_index']))
        actual = (operation, generation)
        if reference == actual:
            valid = slot is None or slot == operand
        elif reference == (0, 0):
            valid = slot is None
        else:
            valid = reference == definition and slot is None
        if not valid:
            raise ValueError('native connection removal reference does not match its actual or producer use')
    else:
        raise ValueError('invalid native connection removal support kind')


def validate_anchor_removal_record(row, detail, identifier, header):
    fields = {'anchor_removal_id', 'pass', 'operation_id', 'operation_generation',
              'value_id', 'value_generation'}
    if (header.get('connection_anchor_removal_trace') != 'dead-anchor-cone.v1' or
            row['action'] != 'delete' or row['reason'] != 'dead_anchor_definition' or
            row['subject'] != 'anchor' or row['side'] != 'before' or
            not isinstance(detail, dict) or set(detail) != fields or
            type(identifier) is not int or not 1 <= identifier <= 2**32 - 1 or
            type(detail['anchor_removal_id']) is not int or not 1 <= detail['anchor_removal_id'] <= 2**63 - 1 or
            not isinstance(detail['pass'], str) or detail['pass'] not in header.get('pass', '').split(',') or
            any(type(detail[key]) is not int or not 1 <= detail[key] <= 2**32 - 1
                for key in ('operation_id', 'value_id')) or
            any(type(detail[key]) is not int or not 0 <= detail[key] <= 2**32 - 1
                for key in ('operation_generation', 'value_generation'))):
        raise ValueError('invalid native anchor definition removal')


def validate_anchor_connection_removal(db, detail, identifier, edge, sources, header):
    fields = {'cause', 'connection_id', 'anchor_removal_id', 'source_node_id', 'target_node_id', 'path',
              'support_kind', 'boundary_kind', 'reference_target_node_id', 'reference_operation_id',
              'reference_operation_generation', 'reference_operand_index',
              'value_definition_operation_id', 'value_definition_operation_generation'}
    if (header.get('connection_anchor_removal_trace') != 'dead-anchor-cone.v1' or
            set(detail) != fields or detail['cause'] != 'dead_anchor_cone' or
            type(detail['connection_id']) is not int or detail['connection_id'] != identifier or
            type(detail['anchor_removal_id']) is not int or not 1 <= detail['anchor_removal_id'] <= 2**63 - 1 or
            any(type(detail[key]) is not int or not 1 <= detail[key] <= 2**32 - 1
                for key in ('source_node_id', 'target_node_id')) or
            detail['source_node_id'] not in sources or detail['target_node_id'] != edge['target_node_id'] or
            not isinstance(detail['path'], list) or not detail['path']):
        raise ValueError('invalid dead anchor connection removal evidence')
    fact = db.execute('''SELECT target_node_id,operation_id,operation_generation,value_id,value_generation
        FROM anchor_removals WHERE anchor_removal_id=?''', (detail['anchor_removal_id'],)).fetchone()
    if fact is None or fact[0] != detail['target_node_id']:
        raise ValueError('connection removal lacks its exact target anchor definition removal')
    context = {**detail, 'operation_id': fact[1], 'operation_generation': fact[2],
               'value_id': fact[3], 'value_generation': fact[4], 'operand_index': 0}
    terminal = connection_removal_terminal(context)
    first = detail['path'][0]
    if (first['definition_operation_id'], first['definition_operation_generation']) != (fact[1], fact[2]):
        raise ValueError('connection removal path does not start at the removed anchor definition')
    validate_connection_removal_support(detail, terminal)


def validate_operation_path_connection_removal(detail, identifier, edge, sources, header):
    fields = {'cause', 'connection_id', 'removed_operation_id', 'removed_operation_generation',
              'source_node_id', 'target_node_id', 'value_id', 'value_generation',
              'operation_id', 'operation_generation', 'operand_index', 'support_kind', 'boundary_kind',
              'reference_target_node_id', 'reference_operation_id', 'reference_operation_generation',
              'reference_operand_index', 'value_definition_operation_id',
              'value_definition_operation_generation', 'root_value_id', 'root_value_generation',
              'root_user_operation_id', 'root_user_operation_generation', 'root_operand_index', 'path'}
    if (header.get('connection_operation_removal_trace') != 'removed-operation-path.v1' or
            not isinstance(detail, dict) or set(detail) != fields or
            detail['cause'] != 'removed_operation_path' or
            type(detail['connection_id']) is not int or detail['connection_id'] != identifier or
            any(type(detail[key]) is not int or not 1 <= detail[key] <= 2**32 - 1
                for key in ('removed_operation_id', 'source_node_id', 'target_node_id', 'value_id',
                            'operation_id', 'root_value_id')) or
            any(type(detail[key]) is not int or not 0 <= detail[key] <= 2**32 - 1
                for key in ('removed_operation_generation', 'value_generation', 'operation_generation',
                            'operand_index', 'root_value_generation', 'root_user_operation_id',
                            'root_user_operation_generation')) or
            (detail['root_operand_index'] is not None and
             (type(detail['root_operand_index']) is not int or
              not 0 <= detail['root_operand_index'] < 2**32 - 1)) or
            ((detail['root_user_operation_id'] == 0) != (detail['root_operand_index'] is None)) or
            (detail['root_user_operation_id'] == 0 and detail['root_user_operation_generation'] != 0) or
            detail['operand_index'] == 2**32 - 1 or detail['source_node_id'] not in sources or
            detail['target_node_id'] != edge['target_node_id'] or not isinstance(detail['path'], list)):
        raise ValueError('invalid native removed-operation path evidence')
    current = (detail['root_value_id'], detail['root_value_generation'])
    reached = {current}
    path_operations = set()
    if detail['root_user_operation_id']:
        path_operations.add((detail['root_user_operation_id'], detail['root_user_operation_generation']))
    terminal = None
    step_fields = {'value_id', 'value_generation', 'definition_operation_id',
                   'definition_operation_generation', 'operand_index', 'operand_value_id',
                   'operand_value_generation'}
    for step in detail['path']:
        if (not isinstance(step, dict) or set(step) != step_fields or
                any(type(step[field]) is not int or not 0 <= step[field] <= 2**32 - 1
                    for field in step_fields) or
                not step['value_id'] or not step['definition_operation_id'] or
                not step['operand_value_id'] or step['operand_index'] == 2**32 - 1 or
                (step['value_id'], step['value_generation']) != current):
            raise ValueError('invalid or disconnected removed-operation path')
        current = (step['operand_value_id'], step['operand_value_generation'])
        if current in reached:
            raise ValueError('cyclic removed-operation path')
        reached.add(current)
        terminal = (step['definition_operation_id'], step['definition_operation_generation'],
                    step['operand_index'])
        path_operations.add(terminal[:2])
    expected_terminal = (detail['operation_id'], detail['operation_generation'], detail['operand_index'])
    if current != (detail['value_id'], detail['value_generation']) or (terminal is not None and terminal != expected_terminal):
        raise ValueError('removed-operation path does not reach its exact native boundary')
    removed = (detail['removed_operation_id'], detail['removed_operation_generation'])
    if removed != expected_terminal[:2] and removed not in path_operations:
        raise ValueError('removed operation is outside the canonical dependency path')
    validate_connection_removal_support(detail, expected_terminal)


def validate_connection_removal_records(db, sequence, header):
    version = header.get('connection_removal_trace')
    extended = version in ('pruned-operand-support.v1', 'pruned-operand-support.v2')
    path_support = version == 'pruned-operand-support.v2'
    for (identifier,) in db.execute('''SELECT DISTINCT connection_id FROM event_removal_evidence
            WHERE seq=? ORDER BY connection_id''', (sequence,)):
        body = db_connection_edit(db, 'before', identifier)
        original = db.execute('SELECT body FROM before_connections WHERE id=?', (identifier,)).fetchone()
        if (body is None or original != (body,) or db_connection_edit(db, 'after', identifier) is not None):
            raise ValueError('native connection removal lacks same-event old edge retirement')
        edge = json.loads(body)
        if edge['kind'] != 'dependency':
            raise ValueError('operand pruning cannot prove a non-dependency connection removal')
        sources = ([edge['source_node_id']] if edge['source_node_id'] is not None
                   else edge['candidate_sources_json'])
        if not sources:
            raise ValueError('native connection removal lacks original source identities')
        for node in [edge['target_node_id'], *sources]:
            current = db.execute('SELECT body FROM current_nodes WHERE id=?', (node,)).fetchone()
            edited = db.execute("SELECT body FROM event_edits WHERE subject='node' AND side='before' AND id=?",
                                (node,)).fetchone()
            replacement = db.execute("SELECT body FROM event_edits WHERE subject='node' AND side='after' AND id=?",
                                     (node,)).fetchone()
            if current is None or (edited is not None and replacement != current):
                raise ValueError('native connection removal endpoints must survive unchanged')
        supported = set()
        for (payload,) in db.execute('''SELECT detail_json FROM event_removal_evidence
                WHERE seq=? AND connection_id=? ORDER BY ordinal''', (sequence, identifier)):
            detail = json.loads(payload)
            if isinstance(detail, dict) and detail.get('cause') == 'dead_anchor_cone':
                validate_anchor_connection_removal(db, detail, identifier, edge, sources, header)
                supported.add(detail['source_node_id'])
                continue
            if isinstance(detail, dict) and detail.get('cause') == 'removed_operation_path':
                validate_operation_path_connection_removal(detail, identifier, edge, sources, header)
                supported.add(detail['source_node_id'])
                continue
            fields = {'cause', 'connection_id', 'mutation_id', 'source_node_id', 'target_node_id',
                      'value_id', 'value_generation', 'operation_id', 'operation_generation',
                      'operand_index', 'boundary_kind'}
            if extended:
                fields |= {'support_kind', 'reference_target_node_id', 'reference_operation_id',
                           'reference_operation_generation', 'reference_operand_index',
                           'value_definition_operation_id', 'value_definition_operation_generation'}
            if path_support:
                fields.add('path')
            if (not isinstance(detail, dict) or set(detail) != fields or
                    detail.get('cause') != 'pruned_operand_boundary' or
                    type(detail['connection_id']) is not int or detail['connection_id'] != identifier or
                    type(detail['mutation_id']) is not int or not 1 <= detail['mutation_id'] <= 2**63 - 1 or
                    any(type(detail[key]) is not int or not 1 <= detail[key] <= 2**32 - 1
                        for key in ('source_node_id', 'target_node_id', 'value_id', 'operation_id')) or
                    any(type(detail[key]) is not int or not 0 <= detail[key] <= 2**32 - 1
                        for key in ('value_generation', 'operation_generation')) or
                    type(detail['operand_index']) is not int or not 0 <= detail['operand_index'] < 2**32 - 1 or
                    (not extended and detail['boundary_kind'] not in ('data', 'clock', 'reset', 'predicate')) or
                    detail['source_node_id'] not in sources or detail['target_node_id'] != edge['target_node_id']):
                raise ValueError('invalid exact native pruned-operand boundary evidence')
            if extended:
                terminal = connection_removal_terminal(detail) if path_support else None
                validate_connection_removal_support(detail, terminal)
            mutation = db.execute('''SELECT operation_id,operation_generation,action,before_slot,
                before_value_id,before_value_generation,after_value_id,after_value_generation,reason
                FROM operand_mutations WHERE mutation_id=?''', (detail['mutation_id'],)).fetchone()
            expected = (detail['operation_id'], detail['operation_generation'], detail['operand_index'],
                        detail['value_id'], detail['value_generation'])
            if (mutation is None or tuple(mutation[index] for index in (0, 1, 3, 4, 5)) != expected or
                    mutation[2] not in ('delete', 'replace') or
                    (mutation[6], mutation[7]) == (detail['value_id'], detail['value_generation']) or
                    mutation[8] not in ('array_update_group_pruning', 'undemanded_operand_defined_zero') or
                    db.execute('SELECT 1 FROM operand_mutation_owners WHERE mutation_id=? AND node_id=?',
                               (detail['mutation_id'], detail['target_node_id'])).fetchone() is None):
                raise ValueError('connection removal lacks its exact destructive operand mutation')
            supported.add(detail['source_node_id'])
        if supported != set(sources):
            raise ValueError('connection removal lacks native support for every original candidate')
        if db.execute("""SELECT 1 FROM event_edits WHERE subject='connection' AND side='after' AND key=?""",
                      (validate_connection(edge)[2],)).fetchone() is not None:
            raise ValueError('native connection removal reintroduces the same public dependency')


def validate_operand_mutation(row, detail, identifier, header):
    common = {'mutation_id', 'pass', 'operation_generation', 'owner_node_ids'}
    before = {'before_slot', 'before_value_id', 'before_value_generation'}
    after = {'after_slot', 'after_value_id', 'after_value_generation'}
    if (header.get('mutation_trace') != 'operand-rewrite.v1' or row['action'] not in ('add', 'delete', 'replace') or
            row['subject'] != 'operand' or row['side'] != 'transition' or
            not isinstance(row['reason'], str) or not row['reason'] or not isinstance(detail, dict) or
            not common <= set(detail) or set(detail) - common - before - after or
            not isinstance(detail.get('pass'), str) or detail['pass'] not in header.get('pass', '').split(',') or
            type(detail.get('mutation_id')) is not int or not 1 <= detail['mutation_id'] <= 2**63 - 1 or
            type(detail.get('operation_generation')) is not int or
            not 0 <= detail['operation_generation'] <= 2**32 - 1 or
            not isinstance(detail.get('owner_node_ids'), list) or
            any(type(owner) is not int or not 1 <= owner <= 2**32 - 1
                for owner in detail['owner_node_ids']) or
            detail['owner_node_ids'] != sorted(set(detail['owner_node_ids']))):
        raise ValueError('invalid native operand mutation identity')
    has_before, has_after = before <= set(detail), after <= set(detail)
    if ((set(detail) & before not in (set(), before)) or (set(detail) & after not in (set(), after)) or
            (row['action'] == 'add' and (has_before or not has_after)) or
            (row['action'] == 'delete' and (not has_before or has_after)) or
            (row['action'] == 'replace' and (not has_before or not has_after)) or
            (has_before and detail['before_slot'] == detail.get('after_slot') and
             detail['before_value_id'] == detail.get('after_value_id') and
             detail['before_value_generation'] == detail.get('after_value_generation'))):
        raise ValueError('invalid native operand mutation transition')
    checked_id(identifier)
    if not 1 <= identifier <= 2**32 - 1:
        raise ValueError('invalid native operand mutation operation')
    if 'before_slot' in detail:
        if type(detail['before_slot']) is not int or not 0 <= detail['before_slot'] < 2**32 - 1:
            raise ValueError('invalid native operand mutation before identity')
        if type(detail['before_value_id']) is not int or not 1 <= detail['before_value_id'] <= 2**32 - 1:
            raise ValueError('invalid native operand mutation before identity')
        if type(detail['before_value_generation']) is not int or not 0 <= detail['before_value_generation'] <= 2**32 - 1:
            raise ValueError('invalid native operand mutation before identity')
    if 'after_slot' in detail:
        if type(detail['after_slot']) is not int or not 0 <= detail['after_slot'] < 2**32 - 1:
            raise ValueError('invalid native operand mutation after identity')
        if type(detail['after_value_id']) is not int or not 1 <= detail['after_value_id'] <= 2**32 - 1:
            raise ValueError('invalid native operand mutation after identity')
        if type(detail['after_value_generation']) is not int or not 0 <= detail['after_value_generation'] <= 2**32 - 1:
            raise ValueError('invalid native operand mutation after identity')


def index_connections(db, connections, *, validated=False):
    if not validated:
        validate_connection_refs(db, 'current_nodes', connections)
    db.execute(f'''INSERT INTO connection_refs
        SELECT id,json_extract(body,'$.target_node_id') FROM ({connections})''')
    db.execute(f'''INSERT OR IGNORE INTO connection_refs
        SELECT id,json_extract(body,'$.source_node_id') FROM ({connections})
        WHERE json_extract(body,'$.source_node_id') IS NOT NULL''')
    db.execute(f'''INSERT OR IGNORE INTO connection_refs
        SELECT e.id,c.value FROM ({connections}) e,json_each(e.body,'$.candidate_sources_json') c''')


def validate_decision_refs(db):
    # Decisions precede all edits and refer to the immutable before inventory.
    # Validate the entire decision section before applying its first event.
    if db.execute('''SELECT 1 FROM evolution d LEFT JOIN before_nodes n ON n.id=d.object_id
        WHERE d.seq=0 AND d.record='decision' AND n.id IS NULL
        UNION ALL SELECT 1 FROM evolution d,json_each(d.detail_json,'$.blocker_node_ids') c
        LEFT JOIN before_nodes n ON n.id=c.value
        WHERE d.seq=0 AND d.record='decision' AND n.id IS NULL LIMIT 1''').fetchone():
        raise ValueError('decision refers outside the before inventory')


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
        index_connections(db, 'SELECT id,body FROM before_connections', validated=True)
        header = footer = event = None
        connectionEvidence = None
        seq, ordinal, events, decisions, lineage_count, mutation_count = 0, -1, 0, 0, 0, 0
        liveness_provenance_count = 0
        liveness_batch = []
        boundary_retirement_count = 0
        anchor_removal_count = 0
        actions = Counter()
        decisions_checked = False

        def flush_liveness_batch():
            if not liveness_batch:
                return
            db.executemany('''INSERT INTO liveness_provenance
                (id,relation,detail_json,node_id,entity_kind,entity_id,generation,
                 from_kind,from_id,from_generation,to_kind,to_id,to_generation)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''', liveness_batch)
            liveness_batch.clear()

        def apply_event():
            nonlocal event
            if event is None:
                return
            event_sequence = integer(event['seq'])
            sides = dict(db.execute('SELECT side,COUNT(*) FROM event_edits GROUP BY side'))
            expected = 'replace' if sides.get('before') and sides.get('after') else 'delete' if sides.get('before') else 'add'
            if not sides or event['action'] != expected:
                raise ValueError('event action does not match object cardinalities')
            for subject, table in (('node', 'nodes'), ('connection', 'connections')):
                if db.execute(f'''SELECT 1 FROM event_edits e LEFT JOIN current_{table} c ON c.id=e.id
                    WHERE e.subject=? AND e.side='before' AND (c.id IS NULL OR c.body<>e.body) LIMIT 1''',
                    (subject,)).fetchone():
                    raise ValueError('native event precondition failed')
                if db.execute(f'''SELECT 1 FROM event_edits e JOIN seen_{table} s ON s.id=e.id
                    LEFT JOIN event_edits b ON b.subject=e.subject AND b.side='before' AND b.id=e.id
                    WHERE e.subject=? AND e.side='after' AND (?='connection' OR b.id IS NULL) LIMIT 1''',
                    (subject, subject)).fetchone():
                    raise ValueError('retired identity or immutable connection ID reused')
            if db.execute('''SELECT 1 FROM event_lineage l
                LEFT JOIN event_edits b ON b.subject='node' AND b.side='before' AND b.id=l.parent
                LEFT JOIN event_edits a ON a.subject='node' AND a.side='after' AND a.id=l.child
                WHERE b.id IS NULL OR a.id IS NULL LIMIT 1''').fetchone():
                raise ValueError('lineage refers outside its event sides')
            transitions = db.execute('''SELECT ordinal,connection_id,reason,subject,side,detail_json
                FROM event_transition_evidence WHERE seq=? ORDER BY ordinal''', (event_sequence,)).fetchall()
            for ordinal, connection_id, reason, subject, side, detail_json in transitions:
                validate_connection_transition_record(db,
                    {'action': None, 'reason': reason, 'subject': subject, 'side': side},
                    json.loads(detail_json), connection_id, header, event, event_sequence)
                db.execute('INSERT INTO connection_transition_evidence VALUES(?,?,?,?)',
                           (event_sequence, ordinal, connection_id, detail_json))
            validate_connection_removal_records(db, event_sequence, header)
            db.execute('''INSERT INTO connection_removal_evidence
                SELECT * FROM event_removal_evidence WHERE seq=?''', (event_sequence,))
            for subject, table in (('connection', 'connections'), ('node', 'nodes')):
                db.execute(f"DELETE FROM current_{table} WHERE id IN (SELECT id FROM event_edits WHERE subject=? AND side='before')", (subject,))
            db.execute("DELETE FROM connection_refs WHERE edge IN (SELECT id FROM event_edits WHERE subject='connection' AND side='before')")
            db.execute("INSERT INTO current_nodes SELECT id,body FROM event_edits WHERE subject='node' AND side='after'")
            db.execute("INSERT INTO current_connections SELECT id,body,key FROM event_edits WHERE subject='connection' AND side='after'")
            for subject, table in (('node', 'nodes'), ('connection', 'connections')):
                db.execute(f"INSERT OR IGNORE INTO seen_{table} SELECT id FROM event_edits WHERE subject=? AND side='after'", (subject,))
            index_connections(db, "SELECT id,body FROM event_edits WHERE subject='connection' AND side='after'")
            # Existing references can become invalid only when a Node retires.
            # The incident index keeps this check local to the actual edit set.
            if db.execute("""SELECT 1 FROM event_edits e JOIN connection_refs r ON r.node=e.id
                LEFT JOIN current_nodes n ON n.id=r.node
                WHERE e.subject='node' AND e.side='before' AND n.id IS NULL LIMIT 1""").fetchone():
                raise ValueError('connection or unresolved candidate refers to inactive Node')
            db.execute('DELETE FROM event_edits')
            db.execute('DELETE FROM event_lineage')
            db.execute('DELETE FROM event_transition_evidence')
            db.execute('DELETE FROM event_removal_evidence')
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
                # Provenance has its own complete indexed table. Retain its
                # streaming position checks above without duplicating the
                # potentially huge payload in this derived journal cache.
                if kind != 'provenance':
                    # A subsequent record may consume provenance (notably
                    # footer Node-reference validation). Preserve stream order.
                    flush_liveness_batch()
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
                    if detail.get('mutation_trace') not in (None, 'operand-rewrite.v1'):
                        raise ValueError('unsupported native mutation trace declaration')
                    if detail.get('connection_transition_trace') not in (None, 'candidate-prune.v1'):
                        raise ValueError('unsupported native connection transition trace declaration')
                    if detail.get('boundary_retirement_trace') not in (None, 'boundary-retirement.v1'):
                        raise ValueError('unsupported native boundary retirement trace declaration')
                    if detail.get('connection_removal_trace') not in (None, 'pruned-operand-boundary.v1',
                                                                    'pruned-operand-support.v1',
                                                                    'pruned-operand-support.v2'):
                        raise ValueError('unsupported native connection removal trace declaration')
                    if detail.get('connection_anchor_removal_trace') not in (None, 'dead-anchor-cone.v1'):
                        raise ValueError('unsupported native anchor connection removal trace declaration')
                    if detail.get('connection_operation_removal_trace') not in (None, 'removed-operation-path.v1'):
                        raise ValueError('unsupported native operation-path removal trace declaration')
                    if detail.get('liveness_provenance') not in (None, 'dce-causality.v1'):
                        raise ValueError('unsupported native liveness provenance declaration')
                    header = detail
                elif kind == 'decision':
                    if seq != 0 or event is not None:
                        raise ValueError('invalid native pass decision')
                    validate_decision(row, detail, identifier, header)
                    decisions += 1
                elif kind == 'provenance':
                    if (seq != 0 or event is not None or header.get('liveness_provenance') != 'dce-causality.v1' or
                            row['action'] is not None or row['subject'] != 'liveness' or
                            row['side'] != 'before' or identifier != liveness_provenance_count + 1):
                        raise ValueError('invalid native DCE liveness provenance position or identity')
                    relation, body, columns = validate_liveness_provenance(row, detail, identifier)
                    liveness_batch.append((identifier, relation, body, *columns))
                    if len(liveness_batch) >= PROVENANCE_BATCH_SIZE:
                        flush_liveness_batch()
                    liveness_provenance_count += 1
                elif kind == 'mutation':
                    if seq != 0 or event is not None:
                        raise ValueError('invalid native operand mutation position')
                    if row['subject'] == 'anchor':
                        validate_anchor_removal_record(row, detail, identifier, header)
                        if detail['anchor_removal_id'] != anchor_removal_count + 1:
                            raise ValueError('noncontiguous native anchor removal IDs')
                        anchor_removal_count += 1
                        db.execute('INSERT INTO anchor_removals VALUES(?,?,?,?,?,?)',
                                   (anchor_removal_count, identifier, detail['operation_id'],
                                    detail['operation_generation'], detail['value_id'], detail['value_generation']))
                    elif row['subject'] == 'boundary':
                        validate_boundary_retirement_record(row, detail, identifier, header)
                        if identifier != boundary_retirement_count + 1:
                            raise ValueError('noncontiguous native boundary retirement IDs')
                        boundary_retirement_count += 1
                        db.execute('INSERT INTO boundary_retirements VALUES(?,?)', (identifier, compact(detail)))
                    else:
                        validate_operand_mutation(row, detail, identifier, header)
                        mutation_id = detail['mutation_id']
                        if mutation_id != mutation_count + 1:
                            raise ValueError('noncontiguous native operand mutation IDs')
                        mutation_count += 1
                        db.execute('''INSERT INTO operand_mutations VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (
                            mutation_id, identifier, detail['operation_generation'], row['action'],
                            detail.get('before_slot'), detail.get('before_value_id'),
                            detail.get('before_value_generation'), detail.get('after_slot'),
                            detail.get('after_value_id'), detail.get('after_value_generation'), row['reason']))
                        db.executemany('INSERT INTO operand_mutation_owners VALUES(?,?)',
                                       ((mutation_id, owner) for owner in detail['owner_node_ids']))
                elif kind == 'evidence':
                    if row['reason'] in ('pruned_operand_boundary', 'dead_anchor_cone',
                                         'removed_operation_path'):
                        if (not seq or event is None or integer(event['seq']) != seq or
                                row['action'] is not None or row['subject'] != 'connection' or
                                row['side'] != 'before' or identifier is None):
                            raise ValueError('invalid native connection removal evidence position')
                        if row['reason'] == 'dead_anchor_cone':
                            declared = header.get('connection_anchor_removal_trace') == 'dead-anchor-cone.v1'
                        elif row['reason'] == 'removed_operation_path':
                            declared = (header.get('connection_operation_removal_trace') ==
                                        'removed-operation-path.v1')
                        else:
                            declared = header.get('connection_removal_trace') in (
                                'pruned-operand-boundary.v1', 'pruned-operand-support.v1',
                                'pruned-operand-support.v2')
                        if not declared or not isinstance(detail, dict) or detail.get('cause') != row['reason']:
                            raise ValueError('invalid native connection removal evidence declaration or cause')
                        db.execute('INSERT INTO event_removal_evidence VALUES(?,?,?,?)',
                                   (seq, current_ordinal, identifier, compact(detail)))
                    elif seq == 0:
                        if (event is not None or row['action'] is not None or
                                row['reason'] != 'postpass-native-witness' or row['subject'] != 'connection' or
                                row['side'] != 'after' or identifier is None):
                            raise ValueError('invalid native connection evidence record')
                        validate_connection_evidence_record(detail, identifier, header)
                        db.execute('INSERT INTO connection_evidence VALUES(?,?)', (identifier, compact(detail)))
                    else:
                        if (event is None or integer(event['seq']) != seq or row['action'] is not None or
                                row['subject'] != 'connection' or row['side'] != 'after' or identifier is None or
                                not ((row['reason'] == 'candidate_pruned_by_node_deletion' and
                                      header.get('connection_transition_trace') == 'candidate-prune.v1') or
                                     (row['reason'] == 'dependency_exposed_by_boundary_retirement' and
                                      header.get('boundary_retirement_trace') == 'boundary-retirement.v1'))):
                            raise ValueError('invalid candidate-prune transition evidence position')
                        if (not isinstance(detail, dict) or
                                type(detail.get('event_sequence')) is not int or detail['event_sequence'] != seq):
                            raise ValueError('invalid candidate-prune transition evidence identity')
                        db.execute('''INSERT INTO event_transition_evidence
                            VALUES(?,?,?,?,?,?,?)''',
                            (seq, current_ordinal, identifier, row['reason'], row['subject'], row['side'],
                             compact(detail)))
                elif kind == 'event':
                    if not decisions_checked:
                        validate_decision_refs(db)
                        decisions_checked = True
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
                    if not decisions_checked:
                        validate_decision_refs(db)
                        decisions_checked = True
                    apply_event()
                    if not detail or detail.get('complete') is not True or detail.get('replayComplete') is not True:
                        raise ValueError('native pass evolution did not complete')
                    if detail.get('eventCount') != events:
                        raise ValueError('native event count mismatch')
                    if ('decisionCount' in detail and
                            (type(detail['decisionCount']) is not int or detail['decisionCount'] != decisions)):
                        raise ValueError('native decision count mismatch')
                    if header.get('liveness_provenance') == 'dce-causality.v1':
                        if (type(detail.get('livenessProvenanceCount')) is not int or
                                detail['livenessProvenanceCount'] != liveness_provenance_count):
                            raise ValueError('native liveness provenance count mismatch')
                        if db.execute('''SELECT 1 FROM liveness_provenance p LEFT JOIN before_nodes n ON n.id=p.node_id
                            WHERE p.relation='start' AND n.id IS NULL LIMIT 1''').fetchone():
                            raise ValueError('DCE liveness start refers outside the before Node inventory')
                        if db.execute('''SELECT 1 FROM liveness_provenance p LEFT JOIN current_nodes n ON n.id=p.node_id
                            WHERE p.relation='start' AND json_extract(p.detail_json,'$.start_kind')='input_port'
                                AND n.id IS NULL LIMIT 1''').fetchone():
                            raise ValueError('exact DCE input Port Node was retired')
                        validate_residual_owner_groups(db)
                    elif 'livenessProvenanceCount' in detail or liveness_provenance_count:
                        raise ValueError('native liveness provenance is missing its header declaration')
                    if header.get('mutation_trace') == 'operand-rewrite.v1':
                        if type(detail.get('mutationRecordCount')) is not int or detail['mutationRecordCount'] != mutation_count:
                            raise ValueError('native operand mutation count mismatch')
                        if db.execute('''SELECT 1 FROM operand_mutation_owners o
                            LEFT JOIN before_nodes n ON n.id=o.node_id WHERE n.id IS NULL LIMIT 1''').fetchone():
                            raise ValueError('operand mutation owner is outside the before inventory')
                    elif 'mutationRecordCount' in detail or mutation_count:
                        raise ValueError('native operand mutations are missing their header declaration')
                    if header.get('boundary_retirement_trace') == 'boundary-retirement.v1':
                        if (type(detail.get('boundaryRetirementRecordCount')) is not int or
                                detail['boundaryRetirementRecordCount'] != boundary_retirement_count):
                            raise ValueError('native boundary retirement count mismatch')
                        if db.execute('''SELECT 1 FROM boundary_retirements b
                            LEFT JOIN before_nodes s ON s.id=json_extract(b.detail_json,'$.source_node_id')
                            LEFT JOIN before_nodes t ON t.id=json_extract(b.detail_json,'$.target_node_id')
                            WHERE s.id IS NULL OR t.id IS NULL LIMIT 1''').fetchone():
                            raise ValueError('boundary retirement endpoint is outside the before inventory')
                    elif 'boundaryRetirementRecordCount' in detail or boundary_retirement_count:
                        raise ValueError('native boundary retirements are missing their header declaration')
                    removal_count, removal_connections = db.execute('''SELECT COUNT(*),
                        COUNT(DISTINCT connection_id) FROM connection_removal_evidence''').fetchone()
                    anchor_evidence_count, anchor_evidence_connections = db.execute('''SELECT COUNT(*),
                        COUNT(DISTINCT connection_id) FROM connection_removal_evidence
                        WHERE json_extract(detail_json,'$.cause')='dead_anchor_cone' ''').fetchone()
                    operation_evidence_count, operation_evidence_connections = db.execute('''SELECT COUNT(*),
                        COUNT(DISTINCT connection_id) FROM connection_removal_evidence
                        WHERE json_extract(detail_json,'$.cause')='removed_operation_path' ''').fetchone()
                    anchor_fields = ('anchorRemovalRecordCount', 'connectionAnchorRemovalEvidenceRecordCount',
                                     'connectionAnchorRemovalEvidenceConnectionCount')
                    if header.get('connection_anchor_removal_trace') == 'dead-anchor-cone.v1':
                        if (any(type(detail.get(key)) is not int for key in anchor_fields) or
                                tuple(detail[key] for key in anchor_fields) !=
                                (anchor_removal_count, anchor_evidence_count, anchor_evidence_connections)):
                            raise ValueError('native anchor connection removal evidence footer mismatch')
                        if db.execute('''SELECT 1 FROM anchor_removals r
                            LEFT JOIN before_nodes b ON b.id=r.target_node_id
                            LEFT JOIN current_nodes a ON a.id=r.target_node_id
                            WHERE b.id IS NULL OR a.id IS NULL OR b.body<>a.body LIMIT 1''').fetchone():
                            raise ValueError('anchor removal target must survive unchanged from the before inventory')
                    elif any(key in detail for key in anchor_fields) or anchor_removal_count or anchor_evidence_count:
                        raise ValueError('native anchor removals lack their header declaration')
                    operation_fields = ('connectionOperationRemovalEvidenceRecordCount',
                                        'connectionOperationRemovalEvidenceConnectionCount')
                    if header.get('connection_operation_removal_trace') == 'removed-operation-path.v1':
                        if (any(type(detail.get(key)) is not int for key in operation_fields) or
                                tuple(detail[key] for key in operation_fields) !=
                                (operation_evidence_count, operation_evidence_connections)):
                            raise ValueError('native operation-path removal evidence footer mismatch')
                    elif any(key in detail for key in operation_fields) or operation_evidence_count:
                        raise ValueError('native operation-path removal evidence lacks its declaration')
                    removal_fields = ('connectionRemovalEvidenceRecordCount', 'connectionRemovalEvidenceConnectionCount')
                    if db.execute('''SELECT 1 FROM connection_removal_evidence r
                        LEFT JOIN before_nodes bs ON bs.id=json_extract(r.detail_json,'$.source_node_id')
                        LEFT JOIN current_nodes a_s ON a_s.id=bs.id
                        LEFT JOIN before_nodes bt ON bt.id=json_extract(r.detail_json,'$.target_node_id')
                        LEFT JOIN current_nodes a_t ON a_t.id=bt.id
                        WHERE bs.id IS NULL OR a_s.id IS NULL OR bs.body<>a_s.body
                            OR bt.id IS NULL OR a_t.id IS NULL OR bt.body<>a_t.body LIMIT 1''').fetchone():
                        raise ValueError('native connection removal endpoints must survive unchanged to the final inventory')
                    if db.execute('''SELECT 1 FROM connection_removal_evidence r
                        JOIN before_connections b ON b.id=r.connection_id
                        JOIN current_connections a ON a.key=b.key LIMIT 1''').fetchone():
                        raise ValueError('native connection removal is contradicted by the final public dependency')
                    if (header.get('connection_anchor_removal_trace') == 'dead-anchor-cone.v1' or
                            header.get('connection_operation_removal_trace') == 'removed-operation-path.v1' or
                            header.get('connection_removal_trace') in ('pruned-operand-boundary.v1',
                                                                 'pruned-operand-support.v1',
                                                                 'pruned-operand-support.v2')):
                        if (any(type(detail.get(key)) is not int for key in removal_fields) or
                                tuple(detail[key] for key in removal_fields) != (removal_count, removal_connections)):
                            raise ValueError('native connection removal evidence footer mismatch')
                    elif any(key in detail for key in removal_fields) or removal_count:
                        raise ValueError('native connection removal evidence lacks its declaration')
                    if type(detail.get('nodeInventoryComplete')) is not bool:
                        raise ValueError('missing native Node inventory coverage')
                    validate_coverage(detail.get('connectionCoverage'))
                    connectionEvidence = validate_connection_evidence(db, header, detail)
                    transition_count = db.execute(
                        'SELECT COUNT(*) FROM connection_transition_evidence').fetchone()[0]
                    if (header.get('connection_transition_trace') != 'candidate-prune.v1' and
                            header.get('boundary_retirement_trace') != 'boundary-retirement.v1'):
                        if 'connectionTransitionEvidenceCount' in detail or transition_count:
                            raise ValueError('connection transition evidence is missing its header declaration')
                    elif 'connectionTransitionEvidenceCount' in detail and (
                            type(detail['connectionTransitionEvidenceCount']) is not int or
                            detail['connectionTransitionEvidenceCount'] != transition_count):
                        raise ValueError('connection transition evidence count mismatch')
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
        if db.execute("""SELECT 1 FROM evolution d JOIN after_nodes n ON n.id=d.object_id
            WHERE d.record='decision' AND json_extract(d.detail_json,'$.outcome')='delete' LIMIT 1""").fetchone():
            raise ValueError('native delete decision refers to a surviving Node')
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
                'events': events, 'decisions': decisions, 'actions': dict(actions), 'lineage_count': lineage_count,
                'connection_evidence': connectionEvidence,
                'liveness_provenance_count': liveness_provenance_count,
                'boundary_retirement_count': boundary_retirement_count,
                'connection_transition_evidence': db.execute(
                    'SELECT COUNT(*) FROM connection_transition_evidence').fetchone()[0],
                'connection_removal_evidence_records': removal_count,
                'connection_removal_evidence_connections': removal_connections,
                'anchor_removal_count': anchor_removal_count,
                'connection_anchor_removal_evidence_records': anchor_evidence_count,
                'connection_anchor_removal_evidence_connections': anchor_evidence_connections,
                'connection_operation_removal_evidence_records': operation_evidence_count,
                'connection_operation_removal_evidence_connections': operation_evidence_connections}
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
