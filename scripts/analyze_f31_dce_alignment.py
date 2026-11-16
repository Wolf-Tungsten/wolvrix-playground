"""Replay native first-DCE exchanges and compare a frozen split-stage mapping.

This is an evidence consumer. It never optimizes IR or manufactures evolution.
Names establish candidates only; runtime records are links, not causal proofs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager, nullcontext
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time

from compare_f29_node_names import input_digest
from export_f29_full_split_exchange import canonical_firrtl_path, name_comparison_metadata
from export_f30_connection_differences import file_identity, phase_progress, save_json
from semantic_node_exchange import (IDENTITY, compact, create_database, encode_cell,
                                    load_snapshot, verify_bundle)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'wolvrix.f31.dce-alignment.v1'
CACHE_SCHEMA = 'wolvrix.f31.verified-input-cache.v1'
VERIFIER_FILES = ('analyze_f31_dce_alignment.py', 'semantic_node_exchange.py',
                  'compare_f29_node_names.py', 'export_f29_full_split_exchange.py',
                  'export_f30_connection_differences.py')
FILES = ('before.nodes.tsv', 'before.connections.tsv', 'evolution.tsv',
         'after.nodes.tsv', 'after.connections.tsv')
PREPARATION_FILES = tuple(name for name in FILES if name != 'evolution.tsv') + ('summary.json',)
OUTPUT_COLUMNS = {
    'node-deletion-matrix.tsv': ('category', 'before_path', 'grh_node_id', 'gsim_node_id',
        'grh_alive', 'gsim_alive', 'grh_evidence_json', 'gsim_evidence_json'),
    'node-retention-explanations.tsv': ('before_path', 'grh_node_id', 'gsim_node_id',
        'classification', 'proof_kind', 'evidence_json'),
    'node-deletion-reason-counts.tsv': ('category', 'grh_reason_labels_json', 'gsim_reason_labels_json',
        'node_count', 'evidence_scope'),
    'node-name-changes.tsv': ('engine', 'node_id', 'before_json', 'after_json'),
    'node-differences.tsv': ('engine', 'node_id', 'before_path', 'category', 'alive', 'evidence_json'),
    'live-operation-owner-violations.tsv': ('operation_id', 'operation_generation', 'original_owner_ids_json',
        'membership_records', 'original_owner_count', 'minimum_recorded_owner_count',
        'maximum_recorded_owner_count', 'missing_recorded_owner_count', 'missing_before_owner_count',
        'changed_surviving_owner_count', 'surviving_original_owner_count', 'violations_json'),
    'connection-differences.tsv': ('comparison', 'phase', 'category', 'engine', 'connection_id',
        'kind', 'resolution', 'body_json', 'evidence_json'),
    'attribution.tsv': ('subject', 'comparison', 'category', 'engine', 'object_id',
        'grh_node_id', 'gsim_node_id', 'evidence_status', 'evidence_json'),
}
GENERIC_REASONS = {'dce', 'dead-code-elim', 'removeDeadNodes', 'RemoveDeadNodes',
                   'complete-pass:dead-code-elim', 'complete-pass:removeDeadNodes'}


def digest_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def cache_key(label, database_kind, source_digests, verifier_digests):
    identity = {'schema': CACHE_SCHEMA, 'sources': source_digests,
                'verifiers': verifier_digests, 'label': label,
                'database_kind': database_kind}
    return hashlib.sha256(compact(identity).encode('utf-8')).hexdigest()


def cached_result_matches_database(db, result, cache_identity):
    expected_digest = hashlib.sha256(compact(result).encode('utf-8')).hexdigest()
    binding = db.execute('SELECT cache_key,result_sha256 FROM f31_cache_binding').fetchone()
    if binding != (cache_identity, expected_digest):
        return False
    for phase in ('before', 'after'):
        for table, suffix in (('nodes', 'nodes'), ('connections', 'connections')):
            expected = result[phase][table]['rowCount']
            actual = db.execute(f'SELECT COUNT(*) FROM {phase}_{suffix}').fetchone()[0]
            if actual != expected:
                return False
    return True


def cached_verification(label, directory, source_names, watcher, verifier_digests,
                        cache_dir, verify, database_kind):
    source_digests = {name: watcher.files[str((directory / name).resolve())]['sha256']
                      for name in source_names}
    key = cache_key(label, database_kind, source_digests, verifier_digests)
    entry = cache_dir / key
    database = entry / 'verified.sqlite'
    manifest = entry / 'manifest.json'
    expected = {'schema': CACHE_SCHEMA, 'cache_key': key, 'label': label,
                'database_kind': database_kind, 'sources': source_digests,
                'verifiers': verifier_digests}

    if database.is_file() and manifest.is_file():
        try:
            metadata = json.loads(manifest.read_text(encoding='utf-8'))
            if all(metadata.get(name) == value for name, value in expected.items()):
                with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
                    check = db.execute('PRAGMA quick_check(1)').fetchone()
                    tables = {row[0] for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'")}
                if check == ('ok',) and {'before_nodes', 'after_nodes', 'current_nodes',
                                         'before_connections', 'after_connections',
                                         'current_connections', 'evolution',
                                         'f31_cache_binding'} <= tables:
                    result = metadata.get('result')
                    if isinstance(result, dict) and result.get('complete') is True:
                        if database_kind != 'dce' or result.get('replay_exact') is True:
                            if metadata.get('database_identity') != file_identity(database):
                                raise ValueError('verified cache database identity mismatch')
                            with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
                                if cached_result_matches_database(db, result, key):
                                    print(json.dumps({'event': 'verified-cache-hit', 'label': label,
                                                      'cache_key': key}, sort_keys=True), flush=True)
                                    return result, database, 'hit'
        except (OSError, sqlite3.Error, ValueError, TypeError):
            pass

    cache_dir.mkdir(parents=True, exist_ok=True)
    entry.mkdir(parents=True, exist_ok=True)
    source_bytes = sum(watcher.files[str((directory / name).resolve())]['identity']['bytes']
                       for name in source_names)
    available_bytes = shutil.disk_usage(cache_dir).free
    minimum_free_bytes = max(1024 * 1024 * 1024, source_bytes * 2 + 1024 * 1024 * 1024)
    if available_bytes < minimum_free_bytes:
        raise OSError(f'insufficient space for F31 verified cache: need at least {minimum_free_bytes} bytes, '
                      f'have {available_bytes}')
    with tempfile.NamedTemporaryFile(prefix='.' + key + '.', suffix='.sqlite',
                                     dir=cache_dir, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    temporary_path.unlink()
    try:
        result = verify(directory, temporary_path)
        result_digest = hashlib.sha256(compact(result).encode('utf-8')).hexdigest()
        with sqlite3.connect(temporary_path) as db:
            db.execute('CREATE TABLE f31_cache_binding(cache_key TEXT PRIMARY KEY,result_sha256 TEXT NOT NULL)')
            db.execute('INSERT INTO f31_cache_binding VALUES(?,?)', (key, result_digest))
            db.commit()
        with sqlite3.connect(temporary_path.as_uri() + '?mode=ro', uri=True) as db:
            check = db.execute('PRAGMA quick_check(1)').fetchone()
            if check != ('ok',):
                raise ValueError('newly verified cache database failed SQLite quick_check')
            if not cached_result_matches_database(db, result, key):
                raise ValueError('newly verified cache database does not match its result manifest')
        os.replace(temporary_path, database)
        payload = {**expected, 'result': result, 'database_identity': file_identity(database)}
        with tempfile.NamedTemporaryFile(mode='w', prefix='.manifest.', suffix='.pending',
                                         dir=entry, encoding='utf-8', delete=False) as stream:
            manifest_temp = Path(stream.name)
            stream.write(json.dumps(payload, sort_keys=True, separators=(',', ':')) + '\n')
        os.replace(manifest_temp, manifest)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    print(json.dumps({'event': 'verified-cache-miss', 'label': label,
                      'cache_key': key}, sort_keys=True), flush=True)
    return result, database, 'miss'


class Sources:
    def __init__(self):
        self.files = {}

    def watch(self, path):
        path = Path(path).resolve()
        identity = file_identity(path)
        digest = digest_file(path)
        if file_identity(path) != identity:
            raise ValueError('source changed while hashing: ' + str(path))
        self.files[str(path)] = {'identity': identity, 'sha256': digest}

    def check(self):
        # Each source was hashed before consumption. Ordinary concurrent writes
        # change its stat identity; no second complete inventory read is needed.
        for path, expected in self.files.items():
            if file_identity(Path(path)) != expected['identity']:
                raise ValueError('source changed during analysis: ' + path)


def require_identity(header, engine, *, dce=False):
    if header.get('engine') != engine or not isinstance(header.get('root_name'), str) or not header['root_name']:
        raise ValueError('native engine/root identity is missing or incompatible')
    digest = input_digest(header, Path(engine + '-native-header'))
    if dce:
        expected = 'dead-code-elim' if engine == 'grh' else 'removeDeadNodes'
        if header.get('pass') != expected:
            raise ValueError('bundle is not the requested first DCE pass: ' + engine)
        if engine == 'gsim' and header.get('pass_instance') != 'RemoveDeadNodes#0':
            raise ValueError('GSIM bundle does not identify RemoveDeadNodes#0')
    return digest, header['root_name']


def require_grh_snapshot_identity(metadata, expected):
    """GRH snapshot metadata omits input/root fields carried by its trace header."""
    if metadata.get('engine') != 'grh':
        raise ValueError('GRH snapshot engine identity is missing or incompatible')
    root = metadata.get('root_name')
    if root is not None and (not isinstance(root, str) or not root or root != expected[1]):
        raise ValueError('GRH snapshot root identity differs from its verified evolution header')
    digest = input_digest(metadata, Path('grh-native-snapshot'), required=False)
    if digest is not None and digest != expected[0]:
        raise ValueError('GRH snapshot input identity differs from its verified evolution header')
    return expected


def verify_preparation(directory, database):
    summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
    if summary.get('complete') is not True:
        raise ValueError('GSIM preparation bridge is incomplete')
    with sqlite3.connect(database) as db:
        create_database(db)
        before = load_snapshot(directory, 'before.', db, 'before')
        after = load_snapshot(directory, 'after.', db, 'after')
        if any(before['metadata'].get(key) != after['metadata'].get(key) for key in IDENTITY):
            raise ValueError('preparation snapshots describe different native runs')
        if any(db.execute(f'SELECT * FROM {left}_nodes EXCEPT SELECT * FROM {right}_nodes LIMIT 1').fetchone()
               for left, right in (('before', 'after'), ('after', 'before'))):
            raise ValueError('GSIM preparation changed Node IDs, names or path tokens')
    for phase, detail in (('before', before), ('after', after)):
        declared = summary.get(phase + '_snapshot_id')
        if declared is not None and declared != detail['metadata']['snapshot_id']:
            raise ValueError('preparation summary refers to a different snapshot')
    return {'complete': True, 'node_identity_stable': True, 'before': before, 'after': after,
            'summary': summary, 'scope': 'independent static S0/S1 snapshots; no evolution replay is claimed'}


def equal_tables(db, left, right, columns='*'):
    return not any(db.execute(f'SELECT {columns} FROM {one} EXCEPT SELECT {columns} FROM {two} LIMIT 1').fetchone()
                   for one, two in ((left, right), (right, left)))


def import_evidence(db, engine):
    db.execute('''INSERT INTO native_events SELECT ?,seq,action,reason FROM ''' + engine +
               ".evolution WHERE record='event'", (engine,))
    db.execute('''INSERT INTO edits SELECT ?,e.subject,e.object_id,e.seq,e.ordinal,e.side,v.action,v.reason
        FROM ''' + engine + '''.evolution e JOIN native_events v ON v.engine=? AND v.seq=e.seq
        WHERE e.record='edit' ''', (engine, engine))
    db.execute('''INSERT INTO decisions SELECT ?,object_id,seq,ordinal,reason,detail_json FROM ''' + engine +
               ".evolution WHERE record='decision'", (engine,))


def connection_evidence_sql(engine, identifier):
    # Match compact()'s key order and the original seq/ordinal record order.
    # Return JSON text directly from the streaming comparison cursor.
    return f'''(SELECT json_group_array(json(payload)) FROM (
        SELECT json_object('action',action,'ordinal',ordinal,'reason',reason,
                           'record','edit','seq',seq,'side',side) AS payload
        FROM edits WHERE engine='{engine}' AND subject='connection' AND id={identifier}
        ORDER BY seq,ordinal))'''


def connection_transition_evidence_sql(engine, identifier):
    return f'''(SELECT detail_json FROM {engine}.connection_transition_evidence
        WHERE connection_id={identifier})'''


def connection_removal_evidence_sql(engine, identifier):
    return f'''(SELECT CASE WHEN COUNT(*)=0 THEN NULL ELSE json_group_array(json(detail_json)) END
        FROM (SELECT detail_json FROM {engine}.connection_removal_evidence
            WHERE connection_id={identifier} ORDER BY seq,ordinal))'''


def add_transition_evidence(facts, transition):
    if transition is None:
        return facts
    return compact({'native_connection_edits': json.loads(facts),
                    'native_transition_evidence': json.loads(transition)})


def connection_transition_category(transition):
    cause = json.loads(transition)['cause']
    if cause == 'candidate_pruned_by_node_deletion':
        return 'introduced_by_dce_candidate_prune'
    if cause == 'dependency_exposed_by_boundary_retirement':
        return 'introduced_by_dce_boundary_retirement'
    raise ValueError('unsupported validated native connection transition cause')


def node_evidence_sql(engine, identifier):
    # Correlated indexed lookups execute within one streaming SQLite cursor.
    # The full matrix can have millions of pairs; avoid four Python/SQL calls
    # and deserializing all retained decision payloads for every single pair.
    return f'''(SELECT json_group_array(json(payload)) FROM (
        SELECT json_object('record','edit','seq',seq,'ordinal',ordinal,'side',side,
                           'action',action,'reason',reason) AS payload,0 AS category,seq,ordinal
        FROM edits WHERE engine='{engine}' AND subject='node' AND id={identifier}
        UNION ALL
        SELECT json_object('record','decision','seq',seq,'ordinal',ordinal,'reason',reason,
                           'detail',json(detail)) AS payload,1 AS category,seq,ordinal
        FROM decisions WHERE engine='{engine}' AND id={identifier}
        ORDER BY category,seq,ordinal))'''


def audit_dce(db, engine):
    if db.execute('''SELECT 1 FROM decisions d LEFT JOIN ''' + engine + '''.after_nodes n ON n.id=d.id
        WHERE d.engine=? AND json_extract(d.detail,'$.outcome')='retain' AND n.id IS NULL LIMIT 1''',
        (engine,)).fetchone():
        raise ValueError('native DCE retain decision refers to a deleted Node: ' + engine)
    if db.execute(f'''SELECT 1 FROM {engine}.after_nodes a LEFT JOIN {engine}.before_nodes b USING(id)
                     WHERE b.id IS NULL LIMIT 1''').fetchone():
        raise ValueError('DCE created a new Node: ' + engine)
    if db.execute(f'''SELECT 1 FROM {engine}.after_nodes a JOIN {engine}.before_nodes b USING(id)
                     WHERE a.body<>b.body LIMIT 1''').fetchone():
        raise ValueError('DCE changed a surviving Node name or path: ' + engine)
    if db.execute(f'''SELECT 1 FROM {engine}.evolution e LEFT JOIN {engine}.before_nodes b ON b.id=e.object_id
        WHERE e.record='edit' AND e.subject='node' AND e.side='after'
        AND (b.id IS NULL OR b.body<>e.detail_json) LIMIT 1''').fetchone():
        raise ValueError('DCE transiently created or renamed a Node: ' + engine)
    if db.execute(f"SELECT 1 FROM {engine}.evolution WHERE record='lineage' LIMIT 1").fetchone():
        raise ValueError('DCE must not split or merge public Nodes: ' + engine)
    if db.execute(f'''SELECT 1 FROM {engine}.before_connections b JOIN {engine}.after_connections a USING(key)
                     WHERE a.id<>b.id LIMIT 1''').fetchone():
        raise ValueError('unchanged DCE connection received a different ID: ' + engine)
    before = db.execute(f'SELECT COUNT(*) FROM {engine}.before_nodes').fetchone()[0]
    after = db.execute(f'SELECT COUNT(*) FROM {engine}.after_nodes').fetchone()[0]
    placeholders = ','.join('?' for _ in GENERIC_REASONS)
    deleted, covered, generic = db.execute(f'''WITH deleted AS (
            SELECT b.id FROM {engine}.before_nodes b LEFT JOIN {engine}.after_nodes a USING(id)
            WHERE a.id IS NULL), retired_edits AS (
            SELECT e.id,e.reason FROM edits e JOIN deleted d USING(id)
            WHERE e.engine=? AND e.subject='node' AND e.side='before' AND NOT EXISTS(
                SELECT 1 FROM edits a WHERE a.engine=e.engine AND a.subject=e.subject
                AND a.id=e.id AND a.seq=e.seq AND a.side='after'))
        SELECT (SELECT COUNT(*) FROM deleted), (SELECT COUNT(DISTINCT id) FROM retired_edits),
            (SELECT COUNT(*) FROM deleted d WHERE NOT EXISTS(
                SELECT 1 FROM retired_edits e WHERE e.id=d.id AND e.reason NOT IN ({placeholders}))
            AND NOT EXISTS(SELECT 1 FROM decisions v WHERE v.engine=? AND v.id=d.id
                AND json_extract(v.detail,'$.outcome')='delete' AND v.reason NOT IN ({placeholders})))''',
        (engine, *sorted(GENERIC_REASONS), engine, *sorted(GENERIC_REASONS))).fetchone()
    if deleted != covered:
        raise ValueError('actual Node deletion lacks runtime evolution evidence: ' + engine)
    structured_deletion_decisions, structured_deletion_nodes = db.execute('''SELECT
        COUNT(*),COUNT(DISTINCT id) FROM decisions WHERE engine=?
        AND json_extract(detail,'$.outcome')='delete'
        AND json_type(detail,'$.dce_deletion')='object' ''', (engine,)).fetchone()
    structured_rules = dict(db.execute('''SELECT json_extract(detail,'$.dce_deletion.rule'),COUNT(DISTINCT id)
        FROM decisions WHERE engine=? AND json_extract(detail,'$.outcome')='delete'
        AND json_type(detail,'$.dce_deletion')='object' GROUP BY 1 ORDER BY 1''', (engine,)))
    return {'before': before, 'after': after, 'deleted': before - after, 'new_nodes': 0,
            'renamed_nodes': 0, 'runtime_deletions_covered': covered, 'generic_deletion_reasons': generic,
            'structured_deletion_decisions': structured_deletion_decisions,
            'structured_deletion_nodes_covered': structured_deletion_nodes,
            'structured_deletion_rule_node_counts': structured_rules}


def initialize_index(db):
    db.create_function('canonical_path', 1, canonical_firrtl_path, deterministic=True)
    for engine, source in (('grh', 'grh.before_nodes'), ('gsim', 'prep.before_nodes')):
        db.execute(f'''CREATE TABLE {engine}_original AS SELECT id,canonical_path(json_extract(body,'$.name_path_json')) AS path,
            json_extract(body,'$.name_path_json') AS path_json,json_extract(body,'$.native_name') AS name FROM {source}''')
        db.execute(f'CREATE UNIQUE INDEX {engine}_original_id ON {engine}_original(id)')
        db.execute(f'CREATE INDEX {engine}_original_path ON {engine}_original(path)')
        db.execute(f'''CREATE TABLE {engine}_names(path TEXT PRIMARY KEY,id INTEGER,occurrences INTEGER NOT NULL) WITHOUT ROWID''')
        db.execute(f'''INSERT INTO {engine}_names SELECT path,MIN(id),COUNT(*) FROM {engine}_original
                      WHERE path IS NOT NULL GROUP BY path''')
    db.execute('''CREATE TABLE mapping(grh_id INTEGER PRIMARY KEY,gsim_id INTEGER NOT NULL UNIQUE,path TEXT NOT NULL)''')
    db.execute('''INSERT INTO mapping SELECT g.id,s.id,g.path FROM grh_names g JOIN gsim_names s USING(path)
                  WHERE g.occurrences=1 AND s.occurrences=1''')
    db.execute('''CREATE TABLE common(grh_id INTEGER PRIMARY KEY,gsim_id INTEGER NOT NULL UNIQUE)''')
    db.execute('''INSERT INTO common SELECT m.grh_id,m.gsim_id FROM mapping m
                  JOIN grh.after_nodes g ON g.id=m.grh_id JOIN gsim.after_nodes s ON s.id=m.gsim_id''')
    # Native GRH rules append numerical witnesses after these delimiters. Keep
    # those in full evidence, but group only the rule label in the count report.
    # SQLite's scalar MIN propagates NULL; use a sentinel for absent markers.
    marker = "MIN(" + ','.join("COALESCE(NULLIF(instr(reason,'" + suffix + "'),0),length(reason)+1)"
                             for suffix in (';anchor_value=', ';operation=', ';demanded_by_operation=')) + ")"
    db.execute('''CREATE TABLE node_reason_groups(engine TEXT,id INTEGER,outcome TEXT,labels TEXT NOT NULL,
        PRIMARY KEY(engine,id,outcome)) WITHOUT ROWID''')
    db.execute(f'''INSERT INTO node_reason_groups
        SELECT engine,id,outcome,json_group_array(label) FROM (
            SELECT DISTINCT engine,id,json_extract(detail,'$.outcome') AS outcome,
                CASE WHEN engine='grh' THEN substr(reason,1,{marker}-1) ELSE reason END AS label
            FROM decisions WHERE json_extract(detail,'$.outcome') IN ('retain','delete')
            ORDER BY engine,id,outcome,label)
        GROUP BY engine,id,outcome''')


@contextmanager
def tsv_outputs(output, metadata):
    streams, counts = {}, Counter()
    try:
        for name, columns in OUTPUT_COLUMNS.items():
            stream = (output / name).with_suffix('.pending').open('x', encoding='utf-8')
            streams[name] = stream
            stream.write('#meta\t' + compact(metadata) + '\n' + '\t'.join(columns) + '\n')

        def write(name, values):
            if len(values) != len(OUTPUT_COLUMNS[name]):
                raise ValueError('incorrect report column count: ' + name)
            streams[name].write('\t'.join(encode_cell(value) for value in values) + '\n')
            counts[name] += 1

        yield write, counts
        for name, stream in streams.items():
            stream.write('#footer\t' + compact({'complete': True, 'rowCount': counts[name]}) + '\n')
    finally:
        for stream in streams.values():
            stream.close()


def node_deletion_reason_counts(db, write=None):
    counts = []
    for category, grh_labels, gsim_labels, count in db.execute('''SELECT
        CASE WHEN g.id IS NOT NULL AND s.id IS NOT NULL THEN 'both_retained'
            WHEN g.id IS NULL AND s.id IS NULL THEN 'both_deleted'
            WHEN g.id IS NULL THEN 'grh_deleted_gsim_retained' ELSE 'grh_retained_gsim_deleted' END,
        COALESCE(gr.labels,'[]'),COALESCE(sr.labels,'[]'),COUNT(*)
        FROM mapping m LEFT JOIN grh.after_nodes g ON g.id=m.grh_id LEFT JOIN gsim.after_nodes s ON s.id=m.gsim_id
        LEFT JOIN node_reason_groups gr ON gr.engine='grh' AND gr.id=m.grh_id
            AND gr.outcome=CASE WHEN g.id IS NULL THEN 'delete' ELSE 'retain' END
        LEFT JOIN node_reason_groups sr ON sr.engine='gsim' AND sr.id=m.gsim_id
            AND sr.outcome=CASE WHEN s.id IS NULL THEN 'delete' ELSE 'retain' END
        GROUP BY 1,2,3 ORDER BY 1,2,3'''):
        if write is not None:
            write('node-deletion-reason-counts.tsv', (category, grh_labels, gsim_labels, count,
                                                    'native_rule_labels_only_no_equivalence_claim'))
        counts.append({'category': category, 'grh_reason_labels': json.loads(grh_labels),
                       'gsim_reason_labels': json.loads(gsim_labels), 'nodes': count})
    return counts


def liveness_provenance_context(db):
    header_row = db.execute("SELECT detail_json FROM grh.evolution WHERE record='header' ORDER BY seq,ordinal LIMIT 1").fetchone()
    if not header_row or json.loads(header_row[0]).get('liveness_provenance') != 'dce-causality.v1':
        return None
    roots = {}
    for (payload,) in db.execute("SELECT detail_json FROM grh.liveness_provenance WHERE relation='root'"):
        detail = json.loads(payload)
        roots[(detail['entity_kind'], detail['entity_id'], detail['generation'])] = detail
    return {'roots': roots, 'starts': {}, 'rooted_predecessors': {key: None for key in roots},
            'unrooted_entities': set()}


def rooted_liveness_path(db, target, context):
    predecessors = context.setdefault('rooted_predecessors', {key: None for key in context['roots']})
    unrooted = context.setdefault('unrooted_entities', set())
    if target in unrooted:
        return None
    if target not in predecessors:
        queue = [target]
        previous = {target: None}
        previous_edge = {}
        cursor = 0
        found = None
        while cursor < len(queue):
            current = queue[cursor]
            cursor += 1
            for (payload,) in db.execute('''SELECT detail_json FROM grh.liveness_provenance
                    WHERE relation='edge' AND to_kind=? AND to_id=? AND to_generation=?
                    ORDER BY id''', current):
                edge = json.loads(payload)
                next_key = (edge['from_kind'], edge['from_id'], edge['from_generation'])
                if next_key in previous or next_key in unrooted:
                    continue
                previous[next_key] = current
                previous_edge[next_key] = edge
                if next_key in predecessors:
                    found = next_key
                    break
                queue.append(next_key)
            if found is not None:
                break
        if found is None:
            # Only a complete unsuccessful search proves every visited entity
            # unrooted. A successful BFS can leave unexplored rooted branches.
            unrooted.update(previous)
            return None
        while previous[found] is not None:
            child = previous[found]
            predecessors[child] = (found, previous_edge[found])
            found = child
    keys, edges, seen = [], [], set()
    current = target
    while True:
        if current in seen:
            raise ValueError('cycle in cached DCE rooted liveness path')
        seen.add(current)
        keys.append(current)
        predecessor = predecessors[current]
        if predecessor is None:
            if current not in context['roots']:
                raise ValueError('cached DCE liveness path does not terminate at a root')
            return keys, edges
        current, edge = predecessor
        edges.append(edge)


def explain_retained_node(db, node_id, facts, provenance_context=None):
    if provenance_context is None:
        return 'unexplained', 'missing_liveness_provenance', {
            'claim': 'legacy reason strings and local clock witnesses do not establish a rooted causal path'}
    return explain_retained_node_from_provenance(db, node_id, provenance_context)


def explain_retained_node_from_provenance(db, node_id, context):
    roots = context['roots']
    if node_id not in context['starts']:
        context['starts'][node_id] = [json.loads(payload) for (payload,) in db.execute('''
            SELECT detail_json FROM grh.liveness_provenance WHERE relation='start' AND node_id=? ORDER BY id''',
            (node_id,))]
    starts = context['starts'][node_id]
    if not starts:
        return 'unexplained', 'missing_liveness_start', {
            'claim': 'the DCE trace has no live anchor, owned operation, boundary use, or structural binding for this Node'}

    def incoming(key):
        return (json.loads(row[0]) for row in db.execute('''
            SELECT detail_json FROM grh.liveness_provenance
            WHERE relation='edge' AND to_kind=? AND to_id=? AND to_generation=?
            ORDER BY id''', key))

    def owns_operation(owner, operation, generation):
        return db.execute('''SELECT 1 FROM grh.liveness_provenance
            WHERE relation='start' AND node_id=? AND json_extract(detail_json,'$.start_kind')='owned_operation'
                AND json_extract(detail_json,'$.entity_kind')='operation'
                AND json_extract(detail_json,'$.entity_id')=?
                AND json_extract(detail_json,'$.generation')=? LIMIT 1''',
            (owner, operation, generation)).fetchone() is not None

    for start in starts:
        kind = start['start_kind']
        if kind == 'zero_width_binding':
            binding = start['binding']
            if binding['source_width'] == 0 or any(size == 0 for size in binding['shape']):
                return 'explained', 'zero_width_binding', {
                    'start': start, 'claim': 'the exact FIRRTL binding has zero source width or a zero-length array axis'}
            continue
        if kind == 'input_port':
            return 'explained', 'exact_input_port_identity', {
                'start': start,
                'claim': 'the native Port metadata, actual input/inout Port Value, and exact Node anchor or binding agree'}
        if kind not in ('anchor', 'owned_operation', 'boundary_use'):
            continue
        target = (start['entity_kind'], start['entity_id'], start['generation'])
        residual = None
        if kind == 'owned_operation':
            groups = context.setdefault('residual_groups', {})
            if target not in groups:
                row = db.execute('''SELECT detail_json FROM grh.liveness_provenance
                    WHERE relation='residual' AND entity_kind=? AND entity_id=? AND generation=?''', target).fetchone()
                groups[target] = json.loads(row[0]) if row else None
            residual = groups[target]
            if residual is not None:
                # verify_bundle checked all original memberships/cardinalities,
                # residual decisions, and after survival for the entire group.
                # The rooted operation path is still required below.
                if node_id not in residual['owner_ids'] or start.get('owner_count') != len(residual['owner_ids']):
                    continue
        # Shared membership establishes who owns an implementation, but does
        # not establish which owner actually needs that implementation.
        if kind == 'owned_operation' and residual is None and start.get('owner_count') != 1:
            continue
        path = rooted_liveness_path(db, target, context)
        if path is None:
            continue
        keys, edges = path
        if kind == 'boundary_use':
            boundary = start['boundary']
            # The boundary target must really own its live consumer operation;
            # a rooted operation elsewhere in the graph cannot justify this
            # Node merely because its operand happens to use the same Value.
            if not owns_operation(boundary['target'], boundary['user'], boundary['user_generation']):
                continue
            operand_edge = next((edge for edge in incoming(('value', boundary['value'], boundary['value_generation']))
                                 if edge['edge_kind'] == 'operation_operand' and
                                 edge['slot'] == boundary['operand_index'] and
                                 edge['from_id'] == boundary['user'] and
                                 edge['from_generation'] == boundary['user_generation'] and
                                 (boundary['kind'] != 'clock' or edge.get('operand_role') == 'clock')), None)
            if operand_edge is None:
                continue
            root = roots[keys[-1]]
            if boundary['kind'] == 'clock':
                # A writer or clock gate can be rooted through a state read
                # consumed by a different observable operation. Only a direct
                # SystemTask consumer must match that root's own clock slot.
                if (root.get('root_kind') == 'observable_operation' and
                        root.get('operation_kind') == 'kSystemTask' and
                        root.get('root_identity') == boundary['user'] and
                        root.get('root_identity_generation') == boundary['user_generation'] and
                        root.get('clock_operand') != boundary['operand_index']):
                    continue
            return 'explained', 'rooted_boundary_dependency', {
                'start': start, 'root': root,
                'path': [{'entity': list(key), 'edge_toward_root': edges[index] if index < len(edges) else None}
                         for index, key in enumerate(keys)],
                'boundary_operand_edge': operand_edge,
                'claim': 'a concrete live root reaches the boundary use operation, whose exact operand slot consumes the boundary Value'}
        return 'explained', 'rooted_residual_owner_group' if residual else 'rooted_liveness_dependency', {
            'start': start, 'root': roots[keys[-1]],
            **({'residual_group': residual} if residual else {}),
            'path': [{'entity': list(key), 'edge_toward_root': edges[index] if index < len(edges) else None}
                     for index, key in enumerate(keys)],
            'claim': ('a concrete DCE root reaches a live operation whose complete original owner set is retained '
                      'simultaneously under the explicit residual rule' if residual else
                      'a concrete DCE root reaches this Node live anchor or owned operation through native operand/state-family edges')}
    return 'unexplained', 'no_rooted_liveness_path', {
        'starts': starts, 'claim': 'no exact Node start reaches a concrete DCE root through recorded dependency edges'}


def export_nodes(db, write=None):
    matrix, unmatched = Counter(), {engine: Counter() for engine in ('grh', 'gsim')}
    retention = Counter()
    unexplained_samples = []
    provenance_context = liveness_provenance_context(db)
    if write is None:
        matrix.update(dict(db.execute('''SELECT CASE
            WHEN g.id IS NOT NULL AND s.id IS NOT NULL THEN 'both_retained'
            WHEN g.id IS NULL AND s.id IS NULL THEN 'both_deleted'
            WHEN g.id IS NULL THEN 'grh_deleted_gsim_retained' ELSE 'grh_retained_gsim_deleted' END,
            COUNT(*) FROM mapping m LEFT JOIN grh.after_nodes g ON g.id=m.grh_id
            LEFT JOIN gsim.after_nodes s ON s.id=m.gsim_id GROUP BY 1''')))
        for grh, gsim, path in db.execute('''SELECT m.grh_id,m.gsim_id,m.path FROM mapping m
                JOIN grh.after_nodes g ON g.id=m.grh_id
                LEFT JOIN gsim.after_nodes s ON s.id=m.gsim_id WHERE s.id IS NULL ORDER BY m.grh_id'''):
            classification, proof_kind, proof = explain_retained_node(db, grh, None, provenance_context)
            retention[classification] += 1
            retention[proof_kind] += 1
            if classification == 'unexplained' and len(unexplained_samples) < 25:
                unexplained_samples.append({'before_path': path, 'grh_node_id': grh,
                    'gsim_node_id': gsim, 'proof_kind': proof_kind, 'evidence': proof})
    else:
        for grh, gsim, path, g_alive, s_alive, grh_facts, gsim_facts in db.execute(f'''SELECT
            m.grh_id,m.gsim_id,m.path,g.id IS NOT NULL,s.id IS NOT NULL,
            {node_evidence_sql('grh', 'm.grh_id')},{node_evidence_sql('gsim', 'm.gsim_id')}
            FROM mapping m LEFT JOIN grh.after_nodes g ON g.id=m.grh_id LEFT JOIN gsim.after_nodes s ON s.id=m.gsim_id
            ORDER BY m.grh_id'''):
            category = ('both_retained' if g_alive and s_alive else 'both_deleted' if not g_alive and not s_alive else
                        'grh_deleted_gsim_retained' if not g_alive else 'grh_retained_gsim_deleted')
            matrix[category] += 1
            write('node-deletion-matrix.tsv', (category, path, grh, gsim, bool(g_alive), bool(s_alive),
                                             grh_facts, gsim_facts))
            if category == 'grh_retained_gsim_deleted':
                classification, proof_kind, proof = explain_retained_node(db, grh, grh_facts, provenance_context)
                retention[classification] += 1
                retention[proof_kind] += 1
                if classification == 'unexplained' and len(unexplained_samples) < 25:
                    unexplained_samples.append({'before_path': path, 'grh_node_id': grh,
                        'gsim_node_id': gsim, 'proof_kind': proof_kind, 'evidence': proof})
                write('node-retention-explanations.tsv', (path, grh, gsim, classification, proof_kind,
                                                           compact(proof)))
            if category not in ('both_retained', 'both_deleted'):
                own = {'grh': json.loads(grh_facts), 'gsim': json.loads(gsim_facts)}
                write('attribution.tsv', ('node', 'fixed_before_mapping', category, None, None, grh, gsim,
                                         'native_evidence_link_only', compact(own)))
    for engine in ('grh', 'gsim'):
        peer = 'gsim' if engine == 'grh' else 'grh'
        if write is None:
            for category, count in db.execute(f'''SELECT CASE
                    WHEN n.path IS NULL THEN 'missing_public_path'
                    WHEN own.occurrences>1 OR peer.occurrences>1 THEN 'ambiguous_original_path'
                    ELSE 'missing_original_peer' END || CASE WHEN a.id IS NOT NULL THEN '_retained' ELSE '_deleted' END,
                    COUNT(*) FROM {engine}_original n
                    LEFT JOIN mapping m ON m.{engine}_id=n.id LEFT JOIN {engine}.after_nodes a ON a.id=n.id
                    LEFT JOIN {engine}_names own ON own.path=n.path LEFT JOIN {peer}_names peer ON peer.path=n.path
                    WHERE m.grh_id IS NULL GROUP BY 1'''):
                unmatched[engine][category] += count
            continue
        for identifier, path, alive, self_count, peer_count, facts in db.execute(f'''SELECT n.id,n.path,a.id IS NOT NULL,
            COALESCE(own.occurrences,0),COALESCE(peer.occurrences,0),{node_evidence_sql(engine, 'n.id')}
            FROM {engine}_original n
            LEFT JOIN mapping m ON m.{engine}_id=n.id LEFT JOIN {engine}.after_nodes a ON a.id=n.id
            LEFT JOIN {engine}_names own ON own.path=n.path LEFT JOIN {peer}_names peer ON peer.path=n.path
            WHERE m.grh_id IS NULL ORDER BY n.id'''):
            reason = ('missing_public_path' if path is None else 'ambiguous_original_path' if self_count > 1 or peer_count > 1
                      else 'missing_original_peer')
            category = reason + ('_retained' if alive else '_deleted')
            unmatched[engine][category] += 1
            write('node-differences.tsv', (engine, identifier, path, category, bool(alive), facts))
            write('attribution.tsv', ('node', 'unmatched_before', category, engine, identifier,
                                     identifier if engine == 'grh' else None, identifier if engine == 'gsim' else None,
                                     'native_evidence_link_only', facts))
    candidates = sum(matrix.values())
    explained = retention['explained']
    unexplained = retention['unexplained']
    return {'before_candidates': candidates, 'deletion_matrix': dict(matrix),
            'unexplained_samples': unexplained_samples,
            'unexplained_sample_limit': 25,
            'retention_explanations': {
                'gsim_deleted_grh_retained': matrix['grh_retained_gsim_deleted'],
                'explained': explained, 'unexplained': unexplained,
                'proof_kinds': {key: value for key, value in sorted(retention.items())
                                if key not in ('explained', 'unexplained')}},
            'native_reason_label_counts': node_deletion_reason_counts(db, write),
            'native_reason_label_scope': {
                'mapping': 'same fixed unique before Node mapping as node-deletion-matrix.tsv',
                'labels': 'distinct sorted native lifecycle decision labels matching actual retain/delete; internal replace excluded',
                'witnesses': 'GRH numerical anchor/operation suffixes excluded from labels; complete evidence retained separately',
                'empty_labels': 'no native lifecycle decision supplied; no reason inferred',
                'claim': 'native rule label counts only; not causal proof or functional equivalence'},
            'common_survivors': matrix['both_retained'],
            'common_survivor_fraction_of_before_candidates': matrix['both_retained'] / candidates if candidates else None,
            'stable_identity_fraction_of_common_survivors': 1.0 if matrix['both_retained'] else None,
            'unmatched_before': {engine: dict(counts) for engine, counts in unmatched.items()}}


def audit_live_operation_owners(db, write=None):
    """Audit every captured live owned op against stable surviving Node IDs.

    Public Node inventories intentionally omit operation membership. This
    checks survival of the original owners; native tests separately check
    that surviving operations keep their membership in those surviving Nodes.
    """
    scope = {
        'operations': 'all owned_operation starts captured by native DCE before mutation',
        'coverage': 'complete original owner sets and unchanged original Node identities surviving after DCE',
        'originally_ownerless_operations': 'outside this invariant; no new Node is required',
        'after_operation_membership': 'not independently exported; covered by native before/after invariants',
    }
    header = db.execute("SELECT detail_json FROM grh.evolution WHERE record='header'").fetchone()
    if not header or json.loads(header[0]).get('liveness_provenance') != 'dce-causality.v1':
        return {'status': 'unavailable', 'complete': False, 'passed': None,
                'violating_operations': None,
                'reason': 'missing_liveness_provenance', 'scope': scope}
    # One indexed start scan and disk-backed aggregation cover the full graph.
    # Only compact per-operation counts/owner IDs enter the derived table;
    # no second copy of the much larger provenance payload is retained.
    db.execute('''CREATE TABLE live_operation_owner_coverage(
        operation_id INTEGER,operation_generation INTEGER,original_owner_ids_json TEXT,
        membership_records INTEGER,original_owner_count INTEGER,
        minimum_recorded_owner_count INTEGER,maximum_recorded_owner_count INTEGER,
        missing_recorded_owner_count INTEGER,missing_before_owner_count INTEGER,
        changed_surviving_owner_count INTEGER,surviving_original_owner_count INTEGER,
        PRIMARY KEY(operation_id,operation_generation)) WITHOUT ROWID''')
    db.execute('''INSERT INTO live_operation_owner_coverage
        SELECT p.entity_id,p.generation,json_group_array(p.node_id),COUNT(*),COUNT(DISTINCT p.node_id),
            MIN(json_extract(p.detail_json,'$.owner_count')),MAX(json_extract(p.detail_json,'$.owner_count')),
            SUM(json_type(p.detail_json,'$.owner_count') IS NOT 'integer'),SUM(b.id IS NULL),
            COUNT(DISTINCT CASE WHEN a.id IS NOT NULL AND a.body<>b.body THEN p.node_id END),
            COUNT(DISTINCT CASE WHEN a.id IS NOT NULL THEN p.node_id END)
        FROM grh.liveness_provenance p
        LEFT JOIN grh.before_nodes b ON b.id=p.node_id LEFT JOIN grh.after_nodes a ON a.id=p.node_id
        WHERE p.relation='start' AND p.entity_kind='operation'
            AND json_extract(p.detail_json,'$.start_kind')='owned_operation'
        GROUP BY p.entity_id,p.generation''')
    incomplete = '''(membership_records<>original_owner_count OR missing_recorded_owner_count<>0 OR
        minimum_recorded_owner_count<>original_owner_count OR maximum_recorded_owner_count<>original_owner_count OR
        missing_before_owner_count<>0)'''
    invalid = f'({incomplete} OR changed_surviving_owner_count<>0 OR surviving_original_owner_count=0)'
    totals = db.execute(f'''SELECT COUNT(*),COALESCE(SUM(membership_records),0),
        COALESCE(SUM({incomplete}),0),COALESCE(SUM(changed_surviving_owner_count<>0),0),
        COALESCE(SUM(surviving_original_owner_count=0),0),COALESCE(SUM({invalid}),0)
        FROM live_operation_owner_coverage''').fetchone()
    for row in (() if write is None else db.execute(f'''SELECT * FROM live_operation_owner_coverage WHERE {invalid}
            ORDER BY operation_id,operation_generation''')):
        operation, generation, owners, records, count, minimum, maximum, missing, absent, changed, surviving = row
        violations = []
        if records != count or missing or minimum != count or maximum != count or absent:
            violations.append('incomplete_original_owner_set')
        if changed:
            violations.append('changed_surviving_owner_identity')
        if not surviving:
            violations.append('no_surviving_original_owner')
        write('live-operation-owner-violations.tsv',
              (operation, generation, compact(sorted(json.loads(owners))), records, count, minimum, maximum,
               missing, absent, changed, surviving, compact(violations)))
    operations, memberships, incomplete_sets, changed_identities, uncovered, violations = totals
    return {'status': 'verified' if not violations else 'failed', 'complete': True, 'passed': not violations,
            'live_owned_operations': operations, 'owner_memberships': memberships,
            'incomplete_original_owner_sets': incomplete_sets,
            'changed_surviving_owner_identities': changed_identities,
            'newly_uncovered_live_operations': uncovered, 'violating_operations': violations, 'scope': scope}


def project_connections_summary(db, label, source, engine):
    db.execute(f'''CREATE TABLE {label}(key TEXT PRIMARY KEY,id INTEGER,kind TEXT,resolution TEXT,body TEXT) WITHOUT ROWID''')
    resolved = f'''SELECT e.id,e.body,json_extract(e.body,'$.kind') AS kind,
        json_extract(e.body,'$.reason') AS reason,t.grh_id AS target,s.grh_id AS source
        FROM {source} e LEFT JOIN common t ON t.{engine}_id=json_extract(e.body,'$.target_node_id')
        LEFT JOIN common s ON s.{engine}_id=json_extract(e.body,'$.source_node_id')
        WHERE json_extract(e.body,'$.resolution')='resolved' '''
    db.execute(f'''INSERT INTO {label}
        SELECT json_array('resolved',target,kind,json_array(source),reason),id,kind,'resolved',body
        FROM ({resolved}) WHERE target IS NOT NULL AND source IS NOT NULL''')

    unresolved = f'''SELECT e.id,e.body,json_extract(e.body,'$.kind') AS kind,
        json_extract(e.body,'$.reason') AS reason,t.grh_id AS target,
        (SELECT COUNT(*) FROM json_each(e.body,'$.candidate_sources_json')) AS candidate_count,
        (SELECT COUNT(*) FROM json_each(e.body,'$.candidate_sources_json') c
            JOIN common m ON m.{engine}_id=c.value) AS mapped_count,
        (SELECT json_group_array(grh_id) FROM (
            SELECT m.grh_id AS grh_id FROM json_each(e.body,'$.candidate_sources_json') c
            JOIN common m ON m.{engine}_id=c.value ORDER BY m.grh_id)) AS normalized_sources
        FROM {source} e LEFT JOIN common t ON t.{engine}_id=json_extract(e.body,'$.target_node_id')
        WHERE json_extract(e.body,'$.resolution')<>'resolved' '''
    db.execute(f'''INSERT INTO {label}
        SELECT json_array('unresolved',target,kind,json(normalized_sources),reason),
            id,kind,'unresolved',body FROM ({unresolved})
        WHERE target IS NOT NULL AND candidate_count=mapped_count''')

    counts = Counter()
    counts['comparable_resolved'] = db.execute(
        f"SELECT COUNT(*) FROM {label} WHERE resolution='resolved'").fetchone()[0]
    for category, resolution, count in db.execute(f'''WITH edges AS (
            SELECT e.body,json_extract(e.body,'$.resolution') AS resolution,
                t.grh_id AS target,s.grh_id AS source,
                (SELECT COUNT(*) FROM json_each(e.body,'$.candidate_sources_json')) AS candidate_count,
                (SELECT COUNT(*) FROM json_each(e.body,'$.candidate_sources_json') c
                    JOIN common m ON m.{engine}_id=c.value) AS mapped_count
            FROM {source} e
            LEFT JOIN common t ON t.{engine}_id=json_extract(e.body,'$.target_node_id')
            LEFT JOIN common s ON s.{engine}_id=json_extract(e.body,'$.source_node_id'))
        SELECT CASE WHEN target IS NULL THEN 'outside_common_survivors'
                    WHEN resolution='resolved' AND source IS NULL THEN 'source_or_candidates_outside_common_survivors'
                    WHEN resolution<>'resolved' AND candidate_count<>mapped_count
                        THEN 'source_or_candidates_outside_common_survivors'
                    ELSE 'comparable' END,
               resolution,COUNT(*) FROM edges
        WHERE resolution<>'resolved' OR target IS NULL OR source IS NULL
        GROUP BY 1,2'''):
        counts[category + '_' + resolution] += count
    counts['raw'] = sum(counts.values())
    return dict(counts)


def project_connections(db, label, source, engine, phase, write=None):
    """Keep resolved and unresolved graphs; unmatched candidates stay explicit."""
    if write is None:
        return project_connections_summary(db, label, source, engine)
    db.execute(f'''CREATE TABLE {label}(key TEXT PRIMARY KEY,id INTEGER,kind TEXT,resolution TEXT,body TEXT) WITHOUT ROWID''')
    counts, batch = Counter(), []
    # Most edges are resolved. Join their fixed original-ID mapping in SQLite,
    # avoiding a Python JSON parse and two Python/SQL round trips per edge.
    projection = f'''SELECT e.id,e.body,json_extract(e.body,'$.kind') AS kind,
        json_extract(e.body,'$.reason') AS reason,t.grh_id AS target,s.grh_id AS source
        FROM {source} e LEFT JOIN common t ON t.{engine}_id=json_extract(e.body,'$.target_node_id')
        LEFT JOIN common s ON s.{engine}_id=json_extract(e.body,'$.source_node_id')
        WHERE json_extract(e.body,'$.resolution')='resolved' '''
    db.execute(f'''INSERT INTO {label}
        SELECT json_array('resolved',target,kind,json_array(source),reason),id,kind,'resolved',body
        FROM ({projection}) WHERE target IS NOT NULL AND source IS NOT NULL''')
    counts['comparable_resolved'] = db.execute(f'SELECT COUNT(*) FROM {label}').fetchone()[0]
    for identifier, body, kind, _, target, _ in db.execute(f'''SELECT * FROM ({projection})
            WHERE target IS NULL OR source IS NULL ORDER BY id'''):
        category = ('outside_common_survivors' if target is None else
                    'source_or_candidates_outside_common_survivors')
        counts[category + '_resolved'] += 1
        write('connection-differences.tsv', ('scope', phase, category, engine, identifier,
            kind, 'resolved', body, compact([])))
    # Unresolved candidates have arbitrary cardinality; preserve every candidate
    # and its reason instead of silently dropping unprojectable alternatives.
    for identifier, body in db.execute(f'''SELECT id,body FROM {source}
            WHERE json_extract(body,'$.resolution')<>'resolved' ORDER BY id'''):
        edge = json.loads(body)
        target = db.execute(f'SELECT grh_id FROM common WHERE {engine}_id=?', (edge['target_node_id'],)).fetchone()
        sources = [edge['source_node_id']] if edge['resolution'] == 'resolved' else edge['candidate_sources_json']
        normalized = []
        for source_id in sources:
            found = db.execute(f'SELECT grh_id FROM common WHERE {engine}_id=?', (source_id,)).fetchone()
            if found is None:
                normalized = None
                break
            normalized.append(found[0])
        category = ('outside_common_survivors' if target is None else
                    'source_or_candidates_outside_common_survivors' if normalized is None else 'comparable')
        counts[category + '_' + edge['resolution']] += 1
        if category != 'comparable':
            write('connection-differences.tsv', ('scope', phase, category, engine, identifier,
                edge['kind'], edge['resolution'], body, compact([])))
            continue
        key = compact([edge['resolution'], target[0], edge['kind'], sorted(normalized), edge['reason']])
        batch.append((key, identifier, edge['kind'], edge['resolution'], body))
        if len(batch) >= 20000:
            db.executemany(f'INSERT INTO {label} VALUES(?,?,?,?,?)', batch)
            batch.clear()
    if batch:
        db.executemany(f'INSERT INTO {label} VALUES(?,?,?,?,?)', batch)
    counts['raw'] = sum(value for key, value in counts.items() if key != 'raw')
    return dict(counts)


def connection_changes_summary(db, engine, samples=None, sample_limit=20):
    counts = Counter()
    for side, own, peer in (('removed', 'before', 'after'), ('added', 'after', 'before')):
        rows = db.execute(f'''SELECT e.id,e.body,
            EXISTS(SELECT 1 FROM {engine}.after_nodes n WHERE n.id=json_extract(e.body,'$.target_node_id'))
            AND (json_extract(e.body,'$.source_node_id') IS NULL OR EXISTS(SELECT 1 FROM {engine}.after_nodes n
                WHERE n.id=json_extract(e.body,'$.source_node_id')))
            AND NOT EXISTS(SELECT 1 FROM json_each(e.body,'$.candidate_sources_json') candidate
                LEFT JOIN {engine}.after_nodes n ON n.id=candidate.value WHERE n.id IS NULL),
            (SELECT detail_json FROM {engine}.connection_transition_evidence t WHERE t.connection_id=e.id),
            EXISTS(SELECT 1 FROM {engine}.connection_removal_evidence r WHERE r.connection_id=e.id)
            FROM {engine}.{own}_connections e LEFT JOIN {engine}.{peer}_connections p USING(key)
            WHERE p.id IS NULL ORDER BY e.id''')
        for identifier, body, incident, transition, has_removal in rows:
            if side == 'added':
                category = connection_transition_category(transition) if transition is not None else None
                if transition is None:
                    counts['requires_semantic_review'] += 1
                category = category or (side + ('_between_surviving_endpoints' if incident else '_incident_to_deleted_node'))
            else:
                category = side + ('_between_surviving_endpoints' if incident else '_incident_to_deleted_node')
                if incident and has_removal:
                    category = 'removed_by_dce_operand_pruning'
                elif incident:
                    counts['removed_requires_semantic_review'] += 1
            counts[category] += 1
            needs_review = ((side == 'added' and transition is None) or
                            (side == 'removed' and incident and not has_removal))
            if samples is not None and needs_review and len(samples) < sample_limit:
                connection = json.loads(body)
                samples.append({'engine': engine, 'change': side, 'category': category,
                    'connection_id': identifier, 'kind': connection['kind'],
                    'resolution': connection['resolution'], 'connection': connection,
                    'native_event_linked': True,
                    'claim': 'sample requires semantic review; event linkage is not a causal explanation'})
    return dict(counts)


def connection_changes(db, engine, write=None, samples=None):
    if write is None:
        return connection_changes_summary(db, engine, samples=samples)
    counts = Counter()
    for side, own, peer in (('removed', 'before', 'after'), ('added', 'after', 'before')):
        for identifier, body, incident, kind, resolution, facts, transition, removal in db.execute(f'''SELECT e.id,e.body,
            EXISTS(SELECT 1 FROM {engine}.after_nodes n WHERE n.id=json_extract(e.body,'$.target_node_id'))
            AND (json_extract(e.body,'$.source_node_id') IS NULL OR EXISTS(SELECT 1 FROM {engine}.after_nodes n
                WHERE n.id=json_extract(e.body,'$.source_node_id')))
            AND NOT EXISTS(SELECT 1 FROM json_each(e.body,'$.candidate_sources_json') candidate
                LEFT JOIN {engine}.after_nodes n ON n.id=candidate.value WHERE n.id IS NULL),
            json_extract(e.body,'$.kind'),json_extract(e.body,'$.resolution'),
            {connection_evidence_sql(engine, 'e.id')},
            {connection_transition_evidence_sql(engine, 'e.id')},
            {connection_removal_evidence_sql(engine, 'e.id')}
            FROM {engine}.{own}_connections e
            LEFT JOIN {engine}.{peer}_connections p USING(key) WHERE p.id IS NULL ORDER BY e.id'''):
            category = side + ('_between_surviving_endpoints' if incident else '_incident_to_deleted_node')
            evidence_status = 'native_evidence_link_only'
            if side == 'added' and transition is not None:
                category = connection_transition_category(transition)
                evidence_status = 'native_transition_evidence'
            elif side == 'added':
                counts['requires_semantic_review'] += 1
            elif incident:
                if removal is not None:
                    category = 'removed_by_dce_operand_pruning'
                    evidence_status = 'native_removal_evidence'
                else:
                    counts['removed_requires_semantic_review'] += 1
            counts[category] += 1
            evidence = add_transition_evidence(facts, transition)
            if side == 'removed' and removal is not None:
                evidence = compact({'native_connection_edits': json.loads(facts),
                                    'native_removal_evidence': json.loads(removal)})
            write('connection-differences.tsv', ('within_engine_dce', 'dce', category, engine, identifier,
                kind, resolution, body, evidence))
            write('attribution.tsv', ('connection', 'within_engine_dce', category, engine, identifier,
                None, None, 'requires_semantic_review' if ((side == 'added' and transition is None) or
                    (side == 'removed' and incident and removal is None)) else evidence_status,
                evidence))
    return dict(counts)


def compare_connections_summary(db):
    stages = {'split': ('g0', 's0'), 'dce_before': ('g0', 's1'), 'dce_after': ('g1', 's2')}
    for stage, (grh, gsim) in stages.items():
        for engine, own, peer in (('grh', grh, gsim), ('gsim', gsim, grh)):
            db.execute(f'''CREATE TABLE {stage}_{engine}_only AS SELECT o.* FROM {own} o
                           LEFT JOIN {peer} p USING(key) WHERE p.key IS NULL''')
            db.execute(f'CREATE UNIQUE INDEX {stage}_{engine}_only_key ON {stage}_{engine}_only(key)')
    totals = {stage: {} for stage in stages}
    for stage in stages:
        for engine in ('grh', 'gsim'):
            totals[stage][engine + '_only'] = db.execute(
                f'SELECT COUNT(*) FROM {stage}_{engine}_only').fetchone()[0]
    inherited = Counter()
    for engine in ('grh', 'gsim'):
        for category, count in db.execute(f'''SELECT CASE
                WHEN '{engine}'='grh' AND t.connection_id IS NOT NULL
                    AND json_extract(t.detail_json,'$.cause')='candidate_pruned_by_node_deletion'
                    THEN 'introduced_by_dce_candidate_prune'
                WHEN '{engine}'='grh' AND t.connection_id IS NOT NULL
                    AND json_extract(t.detail_json,'$.cause')='dependency_exposed_by_boundary_retirement'
                    THEN 'introduced_by_dce_boundary_retirement'
                WHEN b.key IS NOT NULL THEN 'inherited_from_split'
                WHEN p.key IS NOT NULL THEN 'introduced_by_gsim_preparation'
                ELSE 'introduced_by_dce' END, COUNT(*)
            FROM dce_after_{engine}_only a
            LEFT JOIN split_{engine}_only b USING(key)
            LEFT JOIN dce_before_{engine}_only p USING(key)
            LEFT JOIN {engine}.connection_transition_evidence t ON t.connection_id=a.id
            GROUP BY 1'''):
            inherited[category] += count
    preparation = Counter()
    for side, own, peer in (('removed', 's0', 's1'), ('added', 's1', 's0')):
        for _resolution, count in db.execute(f'''SELECT json_extract(a.body,'$.resolution'),COUNT(*) FROM {own} a
                LEFT JOIN {peer} b USING(key) WHERE b.key IS NULL
                GROUP BY json_extract(a.body,'$.resolution')'''):
            preparation[side] += count
    return {'cross_engine': totals, 'after_difference_origins': dict(inherited),
            'preparation_on_common_survivors': dict(preparation)}


def compare_connections(db, write=None):
    if write is None:
        return compare_connections_summary(db)
    stages = {'split': ('g0', 's0'), 'dce_before': ('g0', 's1'), 'dce_after': ('g1', 's2')}
    for stage, (grh, gsim) in stages.items():
        for engine, own, peer in (('grh', grh, gsim), ('gsim', gsim, grh)):
            db.execute(f'''CREATE TABLE {stage}_{engine}_only AS SELECT o.* FROM {own} o
                           LEFT JOIN {peer} p USING(key) WHERE p.key IS NULL''')
            db.execute(f'CREATE UNIQUE INDEX {stage}_{engine}_only_key ON {stage}_{engine}_only(key)')
    totals = {stage: {} for stage in stages}
    for stage in stages:
        for engine in ('grh', 'gsim'):
            totals[stage][engine + '_only'] = db.execute(f'SELECT COUNT(*) FROM {stage}_{engine}_only').fetchone()[0]
    inherited = Counter()
    for engine in ('grh', 'gsim'):
        for identifier, kind, resolution, body, old, prepared, facts, transition in db.execute(f'''SELECT a.id,a.kind,a.resolution,a.body,
            b.key IS NOT NULL,p.key IS NOT NULL,{connection_evidence_sql(engine, 'a.id')},
            {connection_transition_evidence_sql(engine, 'a.id')}
            FROM dce_after_{engine}_only a
            LEFT JOIN split_{engine}_only b USING(key) LEFT JOIN dce_before_{engine}_only p USING(key) ORDER BY a.id'''):
            category = ('inherited_from_split' if old else 'introduced_by_gsim_preparation' if prepared else 'introduced_by_dce')
            evidence_status = 'stage_membership_only_no_causal_inference'
            if engine == 'grh' and transition is not None:
                category = connection_transition_category(transition)
                evidence_status = 'native_transition_evidence'
            elif engine == 'grh' and category == 'introduced_by_dce':
                evidence_status = 'requires_semantic_review'
            inherited[category] += 1
            evidence = add_transition_evidence(facts, transition)
            write('connection-differences.tsv', ('cross_engine', 'dce_after', category, engine,
                identifier, kind, resolution, body, evidence))
            write('attribution.tsv', ('connection', 'cross_engine', category, engine, identifier,
                None, None, evidence_status, evidence))
    preparation = Counter()
    for side, own, peer in (('removed', 's0', 's1'), ('added', 's1', 's0')):
        for identifier, kind, resolution, body in db.execute(f'''SELECT a.id,a.kind,a.resolution,a.body FROM {own} a
                LEFT JOIN {peer} b USING(key) WHERE b.key IS NULL ORDER BY a.id'''):
            preparation[side] += 1
            write('connection-differences.tsv', ('gsim_preparation', 'preparation', side, 'gsim',
                identifier, kind, resolution, body, compact([])))
    return {'cross_engine': totals, 'after_difference_origins': dict(inherited),
            'preparation_on_common_survivors': dict(preparation)}


def preparation_changes(db, write=None):
    counts = Counter()
    if write is None:
        for side, own, peer in (('removed', 'before', 'after'), ('added', 'after', 'before')):
            for resolution, count in db.execute(f'''SELECT json_extract(e.body,'$.resolution'),COUNT(*)
                    FROM prep.{own}_connections e LEFT JOIN prep.{peer}_connections p USING(key)
                    WHERE p.key IS NULL GROUP BY json_extract(e.body,'$.resolution')'''):
                counts[side] += count
                counts[side + '_' + resolution] += count
        return dict(counts)
    for side, own, peer in (('removed', 'before', 'after'), ('added', 'after', 'before')):
        for identifier, body in db.execute(f'''SELECT e.id,e.body FROM prep.{own}_connections e
            LEFT JOIN prep.{peer}_connections p USING(key) WHERE p.id IS NULL ORDER BY e.id'''):
            edge = json.loads(body)
            counts[side] += 1
            counts[side + '_' + edge['resolution']] += 1
            write('connection-differences.tsv', ('gsim_preparation_all_nodes', 'preparation', side,
                'gsim', identifier, edge['kind'], edge['resolution'], body, compact([])))
    return dict(counts)


def analyze(grh_bundle, gsim_bundle, gsim_preparation, output, *, gsim_split_bundle=None,
            summary_only=False, cache_dir=None):
    started = time.monotonic()
    directories = {'grh': Path(grh_bundle).resolve(), 'gsim': Path(gsim_bundle).resolve(),
                   'prep': Path(gsim_preparation).resolve()}
    if gsim_split_bundle is not None:
        directories['split'] = Path(gsim_split_bundle).resolve()
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT / 'ptmp'):
        raise ValueError('analysis output must be under repository ptmp/')
    if cache_dir is not None:
        cache_dir = Path(cache_dir).resolve()
        if not cache_dir.is_relative_to(ROOT / 'ptmp'):
            raise ValueError('analysis cache must be under repository ptmp/')
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('refusing to overwrite existing analysis artifacts')
    report = {'schema': SCHEMA, 'complete': False, 'passed': False, 'issues': [],
              'diagnostic_only': bool(summary_only),
              'acceptance_eligible': not summary_only,
              'artifact_scope': 'summary_only' if summary_only else 'full_report',
              'name_comparison': name_comparison_metadata(), 'scope': {
                  'mapping': 'unique G0/S0 before paths, frozen through the native-ID-stable preparation bridge',
                  'connections': 'typed resolved and unresolved edges on fixed common surviving Nodes; out-of-scope edges retained explicitly',
                  'cross_session_bridge': 'exact Node bodies and semantic connection keys; connection IDs are session-local',
                  'attribution': 'native event links and stage membership only; no inferred semantic cause or functional equivalence',
                  'source_scope': 'all exported native Nodes; no unmatched names excluded as auxiliary SV'}}
    save_json(output / 'summary.json', report)
    scratch = tempfile.TemporaryDirectory(prefix='.summary-scratch-', dir=output) if summary_only else None
    scratch_dir = Path(scratch.name) if scratch is not None else output
    watcher, verified, database_paths, cache_results, db = Sources(), {}, {}, {}, None
    try:
        with phase_progress('hash-native-source-files', started):
            for label, directory in directories.items():
                for name in PREPARATION_FILES if label == 'prep' else FILES:
                    watcher.watch(directory / name)
            for name in VERIFIER_FILES:
                watcher.watch(Path(__file__).resolve().with_name(name))
        verifier_digests = {name: watcher.files[str((Path(__file__).resolve().with_name(name)).resolve())]['sha256']
                            for name in VERIFIER_FILES}
        database_kinds = {'grh': 'dce', 'gsim': 'dce', 'prep': 'preparation', 'split': 'dce'}
        for engine in ('grh', 'gsim'):
            with phase_progress('replay-native-dce', started, engine=engine):
                if cache_dir is None:
                    database_paths[engine] = scratch_dir / (engine + '.sqlite')
                    verified[engine] = verify_bundle(directories[engine], database_paths[engine])
                    cache_results[engine] = 'disabled'
                else:
                    verified[engine], database_paths[engine], cache_results[engine] = cached_verification(
                        engine, directories[engine], FILES, watcher, verifier_digests, cache_dir,
                        verify_bundle, database_kinds[engine])
        with phase_progress('verify-gsim-preparation', started):
            if cache_dir is None:
                database_paths['prep'] = scratch_dir / 'prep.sqlite'
                verified['prep'] = verify_preparation(directories['prep'], database_paths['prep'])
                cache_results['prep'] = 'disabled'
            else:
                verified['prep'], database_paths['prep'], cache_results['prep'] = cached_verification(
                    'prep', directories['prep'], PREPARATION_FILES, watcher, verifier_digests, cache_dir,
                    verify_preparation, database_kinds['prep'])
        if 'split' in directories:
            with phase_progress('replay-current-gsim-split', started):
                if cache_dir is None:
                    database_paths['split'] = scratch_dir / 'split.sqlite'
                    verified['split'] = verify_bundle(directories['split'], database_paths['split'])
                    cache_results['split'] = 'disabled'
                else:
                    verified['split'], database_paths['split'], cache_results['split'] = cached_verification(
                        'split', directories['split'], FILES, watcher, verifier_digests, cache_dir,
                        verify_bundle, database_kinds['split'])
        identities = [require_identity(verified[engine]['header'], engine, dce=True) for engine in ('grh', 'gsim')]
        prep_identity = require_identity(verified['prep']['before']['metadata'], 'gsim')
        if len(set(identities + [prep_identity])) != 1:
            raise ValueError('native inputs or root names differ')
        for label in verified:
            for phase in ('before', 'after'):
                engine = label if label in ('grh', 'gsim') else 'gsim'
                metadata = verified[label][phase]['metadata']
                actual = (require_grh_snapshot_identity(metadata, identities[0]) if label == 'grh'
                          else require_identity(metadata, engine))
                if actual != identities[0]:
                    raise ValueError('snapshot input/root identity differs from native run')
        gsim_header = verified['gsim']['header']
        if any(verified['prep']['after']['metadata'].get(key) != gsim_header.get(key)
               for key in ('run_id', 'graph_id')):
            raise ValueError('GSIM preparation and DCE are not from the same native run')
        report.update(input_sha256=identities[0][0], root_name=identities[0][1], verification=verified)
        db = sqlite3.connect(scratch_dir / 'analysis.sqlite')
        db.execute('PRAGMA temp_store=FILE')
        db.execute('PRAGMA main.cache_size=-16384')
        for label in directories:
            db.execute('ATTACH DATABASE ? AS ' + label, ((database_paths[label].as_uri() + '?mode=ro'),))
            db.execute('PRAGMA ' + label + '.cache_size=-8192')
        for table in ('nodes', 'connections'):
            columns = '*' if table == 'nodes' else 'key'
            if not equal_tables(db, 'prep.after_' + table, 'gsim.before_' + table, columns):
                raise ValueError('preparation after differs from actual GSIM DCE before: ' + table)
            if 'split' in directories and not equal_tables(db, 'split.after_' + table, 'prep.before_' + table, columns):
                raise ValueError('current split after differs from preparation before: ' + table)
        db.executescript('''CREATE TABLE native_events(engine TEXT,seq INTEGER,action TEXT,reason TEXT,
            PRIMARY KEY(engine,seq)) WITHOUT ROWID;
            CREATE TABLE edits(engine TEXT,subject TEXT,id INTEGER,seq INTEGER,ordinal INTEGER,side TEXT,action TEXT,reason TEXT);
            CREATE INDEX edits_lookup ON edits(engine,subject,id,side,seq);
            CREATE TABLE decisions(engine TEXT,id INTEGER,seq INTEGER,ordinal INTEGER,reason TEXT,detail TEXT);
            CREATE INDEX decisions_lookup ON decisions(engine,id);''')
        for engine in ('grh', 'gsim'):
            import_evidence(db, engine)
        with phase_progress('audit-native-dce-identities', started):
            report['inventories'] = {engine: audit_dce(db, engine) for engine in ('grh', 'gsim')}
        initialize_index(db)
        report['verified_database_cache'] = dict(cache_results)
        output_context = (nullcontext((None, Counter())) if summary_only else
                          tsv_outputs(output, {'schema': SCHEMA, 'input_sha256': report['input_sha256'],
                                               'root_name': report['root_name']}))
        connection_samples = []
        with output_context as (write, rows):
            with phase_progress('audit-all-live-operation-owners', started):
                report['live_operation_owners'] = audit_live_operation_owners(db, write)
            if report['live_operation_owners'].get('violating_operations', 0):
                report['issues'].append({'kind': 'live_operation_owner_coverage',
                                        'operations': report['live_operation_owners']['violating_operations']})
            if not report['live_operation_owners'].get('complete'):
                report['issues'].append({'kind': 'live_operation_owner_audit_unavailable',
                                         'reason': report['live_operation_owners'].get('reason')})
            with phase_progress('export-fixed-node-deletion-matrix', started):
                report['nodes'] = export_nodes(db, write)
            gsim_deleted_grh_retained = report['nodes']['deletion_matrix'].get(
                'grh_retained_gsim_deleted', 0)
            unexplained_retention = report['nodes']['retention_explanations']['unexplained']
            report['nodes']['deletion_contract'] = {
                'required': 'every_gsim_deleted_grh_retained_node_has_a_rooted_semantic_explanation',
                'violations': unexplained_retention,
                'explained_retention': report['nodes']['retention_explanations']['explained'],
                'unexplained_retention': unexplained_retention,
                'allowed_grh_extra_deletions': report['nodes']['deletion_matrix'].get(
                    'grh_deleted_gsim_retained', 0),
            }
            if unexplained_retention:
                report['issues'].append({'kind': 'unexplained_grh_retention',
                                         'nodes': unexplained_retention})
            with phase_progress('project-complete-typed-connections', started):
                projections = {'g0': ('grh.before_connections', 'grh', 'G0'),
                    'g1': ('grh.after_connections', 'grh', 'G1'), 's0': ('prep.before_connections', 'gsim', 'S0'),
                    's1': ('gsim.before_connections', 'gsim', 'S1'), 's2': ('gsim.after_connections', 'gsim', 'S2')}
                report['connection_scope'] = {label: project_connections(db, label, source, engine, phase, write)
                    for label, (source, engine, phase) in projections.items()}
            with phase_progress('compare-typed-connection-evolution', started):
                report['connections'] = compare_connections(db, write)
                report['connections']['preparation_all_nodes'] = preparation_changes(db, write)
                report['connections']['dce_changes'] = {engine: connection_changes(
                    db, engine, write, connection_samples if summary_only else None)
                    for engine in ('grh', 'gsim')}
            report['output_rows'] = dict(rows)
        if summary_only:
            report['diagnostic_node_samples'] = {
                'unexplained_retention': report['nodes']['unexplained_samples'],
                'sample_limit': report['nodes']['unexplained_sample_limit'],
                'unexplained_retention_count': report['nodes']['retention_explanations']['unexplained'],
                'note': 'sample is bounded; total count is authoritative and omitted classes are not zero'}
            report['diagnostic_connection_samples'] = {
                'samples': connection_samples, 'sample_limit': 20,
                'unexplained_added_count': sum(
                    report['connections']['dce_changes'][engine].get('requires_semantic_review', 0)
                    for engine in ('grh', 'gsim')),
                'unexplained_surviving_endpoint_removal_count': sum(
                    report['connections']['dce_changes'][engine].get('removed_requires_semantic_review', 0)
                    for engine in ('grh', 'gsim')),
                'note': 'samples are bounded and native event links alone do not prove a causal explanation'}
        if summary_only:
            report.pop('output_rows', None)
            report['required_checks_run'] = True
            report['bulk_tsv_outputs'] = 'omitted_by_diagnostic_mode'
            report['full_report_complete'] = False
        for engine, counts in report['inventories'].items():
            if counts['generic_deletion_reasons']:
                report['issues'].append({'kind': 'generic_deletion_reason', 'engine': engine,
                                        'nodes': counts['generic_deletion_reasons']})
            additions = report['connections']['dce_changes'][engine].get('requires_semantic_review', 0)
            if additions:
                report['issues'].append({'kind': 'new_dce_connections_require_semantic_review',
                                        'engine': engine, 'connections': additions})
            removals = report['connections']['dce_changes'][engine].get('removed_requires_semantic_review', 0)
            if removals:
                report['issues'].append({'kind': 'removed_dce_connections_require_semantic_review',
                                        'engine': engine, 'connections': removals})
        watcher.check()
        db.commit()
        if not summary_only:
            for name in OUTPUT_COLUMNS:
                (output / name).with_suffix('.pending').replace(output / name)
        report.update(complete=True, passed=None if summary_only else not report['issues'],
                      diagnostic_passed=(not report['issues']) if summary_only else None,
                      sources=watcher.files, wall_s=time.monotonic() - started)
        save_json(output / 'summary.json', report)
        return report
    except BaseException as error:
        report.update(complete=False, passed=False, error=str(error))
        save_json(output / 'summary.json', report)
        raise
    finally:
        if db is not None:
            db.close()
        if scratch is not None:
            scratch.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('grh-bundle', 'gsim-bundle', 'gsim-preparation', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--gsim-split-bundle', type=Path)
    parser.add_argument('--summary-only', action='store_true',
                        help='run all checks but emit a diagnostic summary without bulk TSVs')
    parser.add_argument('--cache-dir', type=Path,
                        help='reuse verified input SQLite databases from this ptmp directory')
    args = parser.parse_args()
    result = analyze(args.grh_bundle, args.gsim_bundle, args.gsim_preparation, args.output,
                     gsim_split_bundle=args.gsim_split_bundle, summary_only=args.summary_only,
                     cache_dir=args.cache_dir)
    print(compact({'complete': result['complete'], 'passed': result['passed'],
                   'nodes': result['nodes'], 'issues': result['issues']}), flush=True)
    if (result['diagnostic_passed'] if args.summary_only else result['passed']) is not True:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
