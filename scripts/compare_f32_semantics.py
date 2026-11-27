"""Compare five native F32 inventories without confusing candidates with proofs.

TSV input is streamed into SQLite. The producers own membership, lifecycle and
slice geometry; this reader never repairs an inventory or invents a lineage.
Optional native structure uses the existing conservative typed normalizer.
Unsupported operations remain unverified, even when both sides are unsupported.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from functools import lru_cache
import hashlib
from itertools import product
import json
from math import prod
import os
from pathlib import Path
import re
import sqlite3
import time

from semantic_node_exchange import (HEADERS, IDENTITY, SCHEMA as EXCHANGE_SCHEMA,
    compact, integer, json_value, parsed_row, validate_connection, validate_coverage,
    validate_line_ending, validate_node)
from compare_f28_semantic_tree import STATE, Subgraphs, attr, candidate_name, records
from semantic_bitvector import (BVType, Term, Unverified, binary, boolean as bitvector_boolean,
                               cast, compare as compare_bitvectors, constant, evaluate, mux,
                               resize, slice_bits, source, source_types)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'wolvrix.f32.semantic-comparison.v1'
CAPTURE_SCHEMA = 'wolvrix.f32.pipeline-capture.v1'
STAGES = {
    'grh': ('post-first-dead-code-elim', 'post-expr-opt', 'post-used-bits',
            'post-split-nodes', 'post-second-dead-code-elim'),
    'gsim': ('RemoveDeadNodes0', 'ExprOpt', 'UsedBits', 'SplitNodes', 'RemoveDeadNodes1'),
}
DETAIL_COLUMNS = ('node_id', 'native_kind', 'width', 'signed', 'shape_json', 'clock_node_id',
                  'state_pair_node_id', 'native_status', 'used_width', 'assignment_count')
ENDPOINT_V1_COLUMNS = ('node_id', 'role', 'value_id', 'value_generation', 'operation_id',
    'operation_generation', 'native_kind', 'width', 'signed', 'shape_json', 'logic_domain',
    'source_width', 'source_signed', 'projection_json', 'source_bit_offset', 'source_bit_width', 'evidence')
ENDPOINT_COLUMNS = (*ENDPOINT_V1_COLUMNS[:13], 'source_shape_json', 'source_shape_field_depths_json',
                    *ENDPOINT_V1_COLUMNS[13:])
ENDPOINT_LAYOUTS = {'grh.semantic-node-endpoints.v1': ENDPOINT_V1_COLUMNS,
                    'grh.semantic-node-endpoints.v2': ENDPOINT_COLUMNS}
SLICE_COLUMNS = ('before_node_id', 'after_node_id', 'low', 'width')
BATCH = 8192


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.partial')
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    temporary.replace(path)


def boolean(value):
    if value not in ('true', 'false', '1', '0'):
        raise ValueError('invalid boolean in typed native sidecar')
    return value in ('true', '1')


def signed_integer(value):
    if not isinstance(value, str) or str(int(value)) != value:
        raise ValueError('invalid signed integer in native sidecar')
    return int(value)


def shape(value):
    result = json_value(value, list)
    if any(type(item) is not int or item < 0 for item in result):
        raise ValueError('invalid native shape')
    return result


def read_table(path, columns, artifact, expected, schema, consume):
    """Validate identity, escaping, footer and frozen hash during one read."""
    if not isinstance(artifact, dict) or Path(artifact.get('path', '')).resolve() != path.resolve():
        raise ValueError('missing frozen native table identity: ' + str(path))
    count, footer, metadata, total = 0, None, None, 0
    schemas = (schema,) if isinstance(schema, str) else tuple(schema)
    active_columns = columns
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for position, raw in enumerate(stream):
            sha.update(raw)
            total += len(raw)
            line = raw.decode('utf-8')
            validate_line_ending(line)
            if position == 0:
                if not line.startswith('#meta\t'):
                    raise ValueError('missing table metadata: ' + str(path))
                metadata = json_value(line[6:], dict)
                if metadata.get('schema') not in schemas or any(metadata.get(key) != value for key, value in expected.items()):
                    raise ValueError('mixed or unsupported native sidecar identity: ' + str(path))
                if isinstance(columns, dict):
                    active_columns = columns[metadata['schema']]
            elif position == 1:
                if line != '\t'.join(active_columns) + '\n':
                    raise ValueError('unsupported native sidecar columns: ' + str(path))
            elif footer is not None:
                raise ValueError('rows after native footer: ' + str(path))
            elif line.startswith('#footer\t'):
                footer = json_value(line[8:], dict)
            else:
                consume(parsed_row(line, active_columns))
                count += 1
    if (metadata is None or footer is None or footer.get('complete') is not True or
            type(footer.get('rowCount')) is not int or footer['rowCount'] != count):
        raise ValueError('incomplete native table: ' + str(path))
    if artifact.get('sha256') != sha.hexdigest() or artifact.get('bytes') != total:
        raise ValueError('native table changed since capture: ' + str(path))
    return metadata, footer


def capture(path, engine):
    summary_path = Path(path) / 'summary.json'
    summary = json.loads(summary_path.read_text())
    if (summary.get('schema') != CAPTURE_SCHEMA or summary.get('engine') != engine or
            summary.get('status') != 'completed' or summary.get('source') != 'raw-firrtl' or
            summary.get('trace_enabled') is not False or summary.get('trace_validation') is not False):
        raise ValueError('requires completed native raw-FIRRTL F32 capture: ' + str(path))
    if not isinstance(summary.get('input_sha256'), str) or re.fullmatch('[0-9a-f]{64}', summary['input_sha256']) is None:
        raise ValueError('capture lacks frozen original input identity')
    semantics = summary.get('window_semantics')
    if 'window_semantics' in summary:
        if semantics not in ('2state', '4state') or (engine == 'gsim' and semantics != '2state'):
            raise ValueError('unsupported explicit capture window semantics')
        if engine == 'grh':
            calls = summary.get('pass_calls', [])
            expected = ('xmr-resolve', 'hier-flatten', 'comb-loop-elim', 'split-static-array',
                        'dead-code-elim', 'expr-opt', 'used-bits', 'split-nodes', 'dead-code-elim')
            if tuple(row.get('pass') for row in calls) != expected or any(
                    row.get('parameters', {}).get('semantics') != semantics for row in calls[5:8]):
                raise ValueError('capture window semantics disagrees with actual pass parameters')
    snapshots = summary.get('snapshots', {})
    if set(snapshots) != {f'P{i}' for i in range(5)}:
        raise ValueError('F32 requires exactly five captured boundaries')
    for index in range(5):
        row = snapshots[f'P{index}']
        if row.get('stage') != STAGES[engine][index]:
            raise ValueError('capture boundary order is not F32')
        if Path(row.get('directory', '')).resolve() != (Path(path) / f'P{index}').resolve():
            raise ValueError('capture snapshot path is not its declared boundary')
    return summary


def database(path):
    db = sqlite3.connect(path)
    db.executescript('''
        PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA temp_store=FILE;
        PRAGMA cache_size=-262144;
        CREATE TABLE inventory(engine TEXT,stage INTEGER,id INTEGER,name TEXT,path TEXT,native TEXT,
            PRIMARY KEY(engine,stage,id));
        CREATE TABLE connections(engine TEXT,stage INTEGER,id INTEGER,source INTEGER,target INTEGER,
            kind TEXT,resolution TEXT,candidates TEXT,reason TEXT,PRIMARY KEY(engine,stage,id));
        CREATE TABLE endpoints(stage INTEGER,node INTEGER,ordinal INTEGER,value INTEGER,role TEXT,
            type_key TEXT,domain TEXT,evidence TEXT,payload TEXT,PRIMARY KEY(stage,node,ordinal));
        CREATE TABLE details(stage INTEGER,node INTEGER,type_key TEXT,kind TEXT,clock INTEGER,pair INTEGER,
            payload TEXT,PRIMARY KEY(stage,node));
        CREATE TABLE slices(engine TEXT,stage INTEGER,parent INTEGER,child INTEGER,low INTEGER,width INTEGER,
            PRIMARY KEY(engine,stage,parent,child,low,width));
        CREATE TABLE pairs(stage INTEGER,grh INTEGER,gsim INTEGER,name TEXT,
            PRIMARY KEY(stage,grh),UNIQUE(stage,gsim));
        CREATE TABLE types(engine TEXT,stage INTEGER,node INTEGER,type_key TEXT,evidence TEXT,
            PRIMARY KEY(engine,stage,node));
        CREATE TABLE differences(stage INTEGER,category TEXT,key TEXT,engine TEXT,grh INTEGER,gsim INTEGER,
            reason TEXT,evidence TEXT);
        CREATE TABLE structural(stage INTEGER,grh INTEGER,gsim INTEGER,status TEXT,reason TEXT,
            PRIMARY KEY(stage,grh));
        CREATE INDEX structural_reason ON structural(stage,status,reason);
        CREATE TABLE structural_diagnoses(stage INTEGER,grh INTEGER,gsim INTEGER,evidence TEXT,
            PRIMARY KEY(stage,grh));
        CREATE TABLE anchor_proofs(stage INTEGER,grh INTEGER,gsim INTEGER,method TEXT,
            projections INTEGER,exhaustive_projections INTEGER,PRIMARY KEY(stage,grh));
        CREATE TABLE state_transfers(stage INTEGER,grh INTEGER,gsim INTEGER,status TEXT,reason TEXT,evidence TEXT,
            PRIMARY KEY(stage,grh));
        CREATE INDEX state_transfer_reason ON state_transfers(stage,status,reason);
        CREATE VIEW common_domain_proofs AS SELECT stage,grh,gsim,
            CASE WHEN status='expression_checked' OR (status='structural_checked' AND
                reason IN ('equal_typed_boundary_structure_X_semantics_unproved',
                    'equal_two_state_boundary_expressions_X_semantics_unproved')) THEN 'expression_checked'
                ELSE 'interface_checked' END AS conditional_proof,
            'all paired free boundary bits are defined 0/1' AS premise FROM structural
            WHERE status IN ('expression_checked','interface_checked') OR (status='structural_checked'
                AND reason IN ('equal_typed_boundary_structure_X_semantics_unproved',
                               'equal_two_state_boundary_expressions_X_semantics_unproved',
                               'input_geometry_and_native_anchor_X_semantics_unproved'));
    ''')
    return db


def ingest_snapshot(db, engine, stage, capture_record, run, input_sha):
    directory = Path(capture_record['directory'])
    artifacts = capture_record.get('artifacts', {})
    pending = []

    def batched(sql, row):
        pending.append(row)
        if len(pending) >= BATCH:
            db.executemany(sql, pending)
            pending.clear()

    def finish(sql):
        if pending:
            db.executemany(sql, pending)
            pending.clear()

    node_sql = 'INSERT INTO inventory VALUES(?,?,?,?,?,?)'
    previous = -1
    def node(row):
        nonlocal previous
        row['node_id'] = integer(row['node_id'])
        row['name_path_json'] = None if row['name_path_json'] is None else json_value(row['name_path_json'], list)
        validate_node(row)
        if row['node_id'] <= previous:
            raise ValueError('native Node inventory is not uniquely sorted')
        previous = row['node_id']
        path = row['name_path_json']
        # Identical canonical names establish candidates only. Preserve the
        # actual token path for collision and identity evidence.
        name = '.'.join(path) if path else None
        batched(node_sql, (engine, stage, row['node_id'], name, compact(path), row['native_name']))
    expected = {'engine': engine, 'stage': STAGES[engine][stage], 'table': 'nodes'}
    meta, footer = read_table(directory / 'nodes.tsv', HEADERS['nodes'], artifacts.get('nodes.tsv'),
                               expected, EXCHANGE_SCHEMA, node)
    finish(node_sql)
    if footer.get('nodeInventoryComplete') is not True:
        raise ValueError('native Node inventory is partial')
    if any(not isinstance(meta.get(key), str) or not meta[key] for key in (*IDENTITY[1:], 'snapshot_id')):
        raise ValueError('missing native snapshot identity')
    if meta.get('input_identity', {}).get('sha256') not in (None, input_sha):
        raise ValueError('snapshot uses a different original input')
    if run is not None and run != meta['run_id']:
        raise ValueError('five boundaries must be captured from the same native run')
    expected = {key: meta[key] for key in (*IDENTITY[1:], 'snapshot_id', 'stage')}
    edge_sql = 'INSERT INTO connections VALUES(?,?,?,?,?,?,?,?,?)'
    coverage, previous = Counter(), -1
    def edge(row):
        nonlocal previous
        for key in ('connection_id', 'target_node_id'):
            row[key] = integer(row[key])
        row['source_node_id'] = None if row['source_node_id'] is None else integer(row['source_node_id'])
        row['candidate_sources_json'] = json_value(row['candidate_sources_json'], list)
        validate_connection(row)
        if row['connection_id'] <= previous:
            raise ValueError('native connections are not uniquely sorted')
        previous = row['connection_id']
        coverage[row['kind'], row['resolution']] += 1
        batched(edge_sql, (engine, stage, row['connection_id'], row['source_node_id'], row['target_node_id'],
            row['kind'], row['resolution'], compact(row['candidate_sources_json']), row['reason']))
    _, edge_footer = read_table(directory / 'connections.tsv', HEADERS['connections'], artifacts.get('connections.tsv'),
        {**expected, 'table': 'connections'}, EXCHANGE_SCHEMA, edge)
    finish(edge_sql)
    validate_coverage(edge_footer.get('connectionCoverage'), coverage)
    bad = db.execute('''SELECT 1 FROM connections e LEFT JOIN inventory t ON
        t.engine=e.engine AND t.stage=e.stage AND t.id=e.target LEFT JOIN inventory s ON
        s.engine=e.engine AND s.stage=e.stage AND s.id=e.source WHERE e.engine=? AND e.stage=?
        AND (t.id IS NULL OR (e.source IS NOT NULL AND s.id IS NULL)) LIMIT 1''', (engine, stage)).fetchone()
    bad_candidates = db.execute('''SELECT 1 FROM connections e,json_each(e.candidates) c
        LEFT JOIN inventory n ON n.engine=e.engine AND n.stage=e.stage AND n.id=c.value
        WHERE e.engine=? AND e.stage=? AND n.id IS NULL LIMIT 1''', (engine, stage)).fetchone()
    if bad or bad_candidates:
        raise ValueError('connection refers outside its actual native inventory')

    if engine == 'grh':
        endpoint_sql = 'INSERT INTO endpoints VALUES(?,?,?,?,?,?,?,?,?)'
        ordinal = 0
        def endpoint(row):
            nonlocal ordinal
            identifier, value = integer(row['node_id']), integer(row['value_id'])
            for key in ('value_generation', 'operation_id', 'operation_generation'):
                integer(row[key])
            # Native endpoint TSV already exports leafWidth(), unlike the
            # packed total `w` in full GRH design.json. Keep source shape.
            width = signed_integer(row['width'])
            sign, dimensions = boolean(row['signed']), shape(row['shape_json'])
            if width < 0 or row['logic_domain'] not in ('2state', '4state', 'none'):
                raise ValueError('invalid physical GRH endpoint type')
            source_width = signed_integer(row['source_width'])
            boolean(row['source_signed'])
            low, retained = signed_integer(row['source_bit_offset']), signed_integer(row['source_bit_width'])
            if (source_width < -1 or low < 0 or retained < -1 or
                    (retained == -1 and low != 0) or
                    (source_width >= 0 and retained >= 0 and low + retained > source_width)):
                raise ValueError('invalid source bit interval')
            projection = json_value(row['projection_json'], list)
            if any(type(item) is not int or item < -1 for item in projection):
                raise ValueError('invalid source array projection')
            if row['evidence'] not in ('native-binding', 'anchor-candidate', 'operation-only'):
                raise ValueError('unsupported GRH endpoint evidence')
            if row['evidence'] == 'native-binding' and source_width < 0:
                raise ValueError('native binding lacks source geometry')
            version_two = 'source_shape_json' in row
            if version_two:
                source_shape = shape(row['source_shape_json'])
                field_depths = json_value(row['source_shape_field_depths_json'], list)
                if projection and len(projection) != len(source_shape):
                    raise ValueError('source array projection differs from source rank')
                if any(coordinate >= extent for coordinate, extent in zip(projection, source_shape)):
                    raise ValueError('source array projection is out of range')
                if (any(type(item) is not int or item < 0 for item in field_depths) or
                        (field_depths and len(field_depths) != len(source_shape)) or
                        field_depths != sorted(field_depths)):
                    raise ValueError('invalid source shape field depths')
            row['source_geometry_schema'] = ('grh.semantic-node-endpoints.v2' if version_two else
                                             'grh.semantic-node-endpoints.v1')
            row['source_geometry_complete'] = version_two and row['evidence'] == 'native-binding'
            batched(endpoint_sql, (stage, identifier, ordinal, value, row['role'],
                compact([width, sign, dimensions]), row['logic_domain'], row['evidence'], compact(row)))
            ordinal += 1
        read_table(directory / 'node-endpoints.tsv', ENDPOINT_LAYOUTS, artifacts.get('node-endpoints.tsv'),
            {'engine': engine, 'run_id': meta['run_id'], 'snapshot_id': meta['snapshot_id'], 'stage': meta['stage']},
            ENDPOINT_LAYOUTS, endpoint)
        finish(endpoint_sql)
        missing = db.execute('''SELECT 1 FROM inventory n LEFT JOIN endpoints e ON e.stage=n.stage AND e.node=n.id
            WHERE n.engine='grh' AND n.stage=? AND e.node IS NULL LIMIT 1''', (stage,)).fetchone()
        extra = db.execute('''SELECT 1 FROM endpoints e LEFT JOIN inventory n ON n.engine='grh'
            AND n.stage=e.stage AND n.id=e.node WHERE e.stage=? AND n.id IS NULL LIMIT 1''', (stage,)).fetchone()
    else:
        detail_sql = 'INSERT INTO details VALUES(?,?,?,?,?,?,?)'
        def detail(row):
            width = signed_integer(row['width'])
            if width < 0 or not row['native_kind'].startswith('NODE_'):
                raise ValueError('invalid GSIM native type')
            batched(detail_sql, (stage, integer(row['node_id']),
                compact([width, boolean(row['signed']), shape(row['shape_json'])]), row['native_kind'],
                None if row['clock_node_id'] is None else integer(row['clock_node_id']),
                None if row['state_pair_node_id'] is None else integer(row['state_pair_node_id']), compact(row)))
        read_table(directory / 'node-details.tsv', DETAIL_COLUMNS, artifacts.get('node-details.tsv'),
            {**expected, 'table': 'node-details', 'detail_schema': 'gsim.node-details.v1'}, EXCHANGE_SCHEMA, detail)
        finish(detail_sql)
        missing = db.execute('''SELECT 1 FROM inventory n LEFT JOIN details d ON d.stage=n.stage AND d.node=n.id
            WHERE n.engine='gsim' AND n.stage=? AND d.node IS NULL LIMIT 1''', (stage,)).fetchone()
        extra = db.execute('''SELECT 1 FROM details d LEFT JOIN inventory n ON n.engine='gsim'
            AND n.stage=d.stage AND n.id=d.node WHERE d.stage=? AND n.id IS NULL LIMIT 1''', (stage,)).fetchone()
    if missing or extra:
        raise ValueError('typed sidecar does not exactly cover its native inventory')
    if engine == 'gsim':
        dangling = db.execute('''SELECT 1 FROM details d LEFT JOIN inventory c ON c.engine='gsim'
            AND c.stage=d.stage AND c.id=d.clock LEFT JOIN inventory p ON p.engine='gsim'
            AND p.stage=d.stage AND p.id=d.pair WHERE d.stage=? AND
            ((d.clock IS NOT NULL AND c.id IS NULL) OR (d.pair IS NOT NULL AND p.id IS NULL)) LIMIT 1''', (stage,)).fetchone()
        if dangling:
            raise ValueError('native clock/state endpoint refers outside its captured inventory')
    slice_sql = 'INSERT INTO slices VALUES(?,?,?,?,?,?)'
    def bit_slice(row):
        parent, child, low, width = (integer(row[key]) for key in SLICE_COLUMNS)
        if parent == child or not width:
            raise ValueError('invalid native slice geometry')
        batched(slice_sql, (engine, stage, parent, child, low, width))
    read_table(directory / 'bit-slices.tsv', SLICE_COLUMNS, artifacts.get('bit-slices.tsv'),
        {'engine': engine, 'run_id': meta['run_id'], 'snapshot_id': meta['snapshot_id'], 'stage': meta['stage']},
        'semantic-node-bit-slices.v1', bit_slice)
    finish(slice_sql)
    return {'run_id': meta['run_id'], 'snapshot_id': meta['snapshot_id'], 'nodes': footer['rowCount'],
            'connections': edge_footer['rowCount'], 'coverage': edge_footer['connectionCoverage']}


def derive(db):
    # Preserve ID affinity so canonical-edge joins can use the complete identity index.
    db.executescript('''
        CREATE INDEX inventory_names ON inventory(engine,stage,name);
        CREATE INDEX inventory_identity ON inventory(engine,id,stage);
        CREATE INDEX connections_source ON connections(engine,stage,source);
        CREATE INDEX connections_target ON connections(engine,stage,target);
        CREATE INDEX endpoints_type ON endpoints(stage,node,type_key);
        CREATE INDEX slices_child ON slices(engine,stage,child);
        CREATE INDEX slices_history ON slices(engine,parent,child,low,width,stage);
        CREATE TEMP TABLE unique_names(engine TEXT,stage INTEGER,name TEXT,id INTEGER);
        INSERT INTO unique_names SELECT engine,stage,name,min(id) id FROM inventory
            WHERE name IS NOT NULL GROUP BY engine,stage,name HAVING count(*)=1;
        CREATE UNIQUE INDEX unique_names_key ON unique_names(engine,stage,name);
        CREATE UNIQUE INDEX unique_names_id ON unique_names(engine,stage,id);
        INSERT INTO pairs SELECT g.stage,g.id,s.id,g.name FROM unique_names g JOIN unique_names s
            ON g.stage=s.stage AND g.name=s.name WHERE g.engine='grh' AND s.engine='gsim';
        CREATE INDEX pairs_name ON pairs(stage,name);
        INSERT INTO types SELECT 'grh',stage,node,
            CASE WHEN count(DISTINCT type_key)=1 THEN min(type_key) END,
            CASE WHEN min(evidence)='native-binding' AND max(evidence)='native-binding'
                THEN 'native-binding' ELSE 'candidate-endpoint' END FROM endpoints
            WHERE value>0 GROUP BY stage,node;
        INSERT INTO types SELECT 'gsim',stage,node,type_key,'native-node-detail' FROM details;
        CREATE INDEX types_identity ON types(engine,node,stage);
        CREATE TEMP TABLE canonical_edges AS SELECT DISTINCT e.engine,e.stage,e.source,e.target,e.kind,
            s.name source_name,t.name target_name,json_array(s.name,t.name,e.kind) edge_key
            FROM connections e JOIN inventory s ON s.engine=e.engine AND s.stage=e.stage AND s.id=e.source
            JOIN inventory t ON t.engine=e.engine AND t.stage=e.stage AND t.id=e.target
            JOIN unique_names su ON su.engine=s.engine AND su.stage=s.stage AND su.id=s.id
            JOIN unique_names tu ON tu.engine=t.engine AND tu.stage=t.stage AND tu.id=t.id
            WHERE e.resolution='resolved';
        CREATE INDEX canonical_edges_key ON canonical_edges(stage,edge_key,engine);
        INSERT INTO differences SELECT n.stage,'presence',json_array(n.name,n.engine),n.engine,n.id,NULL,
            'no_unique_cross_engine_name_candidate',json_object('native_id',n.id,'path',json(n.path),'native_name',n.native)
            FROM inventory n LEFT JOIN pairs p ON p.stage=n.stage AND n.id=p.grh
            WHERE n.engine='grh' AND p.grh IS NULL;
        INSERT INTO differences SELECT n.stage,'presence',json_array(n.name,n.engine),n.engine,NULL,n.id,
            'no_unique_cross_engine_name_candidate',json_object('native_id',n.id,'path',json(n.path),'native_name',n.native)
            FROM inventory n LEFT JOIN pairs p ON p.stage=n.stage AND n.id=p.gsim
            WHERE n.engine='gsim' AND p.gsim IS NULL;
        INSERT INTO differences SELECT p.stage,'type',json_array(p.name,g.type_key,s.type_key),'both',p.grh,p.gsim,
            'physical_type_disagreement',json_object('name',p.name,'grh_type',json(g.type_key),'gsim_type',json(s.type_key))
            FROM pairs p JOIN types g ON g.engine='grh' AND g.stage=p.stage AND g.node=p.grh
            JOIN types s ON s.engine='gsim' AND s.stage=p.stage AND s.node=p.gsim
            WHERE g.type_key IS NOT NULL AND s.type_key IS NOT NULL AND g.type_key!=s.type_key;
        INSERT INTO differences SELECT p.stage,'type_unverified',json_array(p.name),'both',p.grh,p.gsim,
            'missing_or_ambiguous_physical_endpoint_type',json_object('name',p.name,'grh_evidence',g.evidence,
                'gsim_evidence',s.evidence) FROM pairs p LEFT JOIN types g ON g.engine='grh' AND g.stage=p.stage AND g.node=p.grh
            LEFT JOIN types s ON s.engine='gsim' AND s.stage=p.stage AND s.node=p.gsim
            WHERE g.type_key IS NULL OR s.type_key IS NULL;
        INSERT INTO differences SELECT e.stage,'connection',json_array(e.engine,json(e.edge_key)),e.engine,
            CASE WHEN e.engine='grh' THEN e.target END,CASE WHEN e.engine='gsim' THEN e.target END,
            'native_dependency_not_present_in_other_inventory',json_object('source_node_id',e.source,
            'target_node_id',e.target,'source_name',e.source_name,'target_name',e.target_name,'kind',e.kind)
            FROM canonical_edges e WHERE NOT EXISTS(SELECT 1 FROM canonical_edges other WHERE
                other.engine!=e.engine AND other.stage=e.stage AND other.edge_key=e.edge_key);
        INSERT INTO differences SELECT e.stage,'unresolved_connection',json_array(e.engine,n.name,e.kind,e.reason,e.candidates),
            e.engine,CASE WHEN e.engine='grh' THEN e.target END,CASE WHEN e.engine='gsim' THEN e.target END,
            'native_source_resolution_is_unproven',json_object('connection_id',e.id,'target_name',n.name,
                'kind',e.kind,'reason',e.reason,'candidate_ids',json(e.candidates))
            FROM connections e JOIN inventory n ON n.engine=e.engine AND n.stage=e.stage AND n.id=e.target
            WHERE e.resolution='unresolved';
        CREATE INDEX differences_key ON differences(category,key,stage);
        CREATE INDEX differences_stage ON differences(stage,category,key);
    ''')


def slice_geometry(db):
    db.executescript('''
        CREATE TEMP TABLE historical_names AS SELECT engine,id,min(name) name FROM inventory
            GROUP BY engine,id HAVING count(DISTINCT name)=1;
        CREATE UNIQUE INDEX historical_names_id ON historical_names(engine,id);
        CREATE TEMP TABLE canonical_slices AS SELECT s.engine,s.stage,s.parent,s.child,s.low,s.width,
            p.name parent_name,c.name child_name,json_array(p.name,c.name,s.low,s.width) slice_key
            FROM slices s JOIN historical_names p ON p.engine=s.engine AND p.id=s.parent
            JOIN historical_names c ON c.engine=s.engine AND c.id=s.child;
        CREATE INDEX canonical_slices_key ON canonical_slices(stage,slice_key,engine);
        CREATE INDEX canonical_slices_native ON canonical_slices(engine,stage,parent,child,low,width);
        INSERT INTO differences SELECT s.stage,'split_geometry',json_array(s.engine,json(s.slice_key)),s.engine,
            CASE WHEN s.engine='grh' THEN s.child END,CASE WHEN s.engine='gsim' THEN s.child END,
            'native_slice_geometry_not_present_in_other_engine',json_object('parent_id',s.parent,'child_id',s.child,
            'parent_name',s.parent_name,'child_name',s.child_name,'low',s.low,'width',s.width)
            FROM canonical_slices s WHERE NOT EXISTS(SELECT 1 FROM canonical_slices o WHERE
                o.engine!=s.engine AND o.stage=s.stage AND o.slice_key=s.slice_key);
        INSERT INTO differences SELECT s.stage,'split_geometry_unverified',json_array(s.engine,s.parent,s.child,s.low,s.width),
            s.engine,CASE WHEN s.engine='grh' THEN s.child END,CASE WHEN s.engine='gsim' THEN s.child END,
            'native_slice_endpoint_has_no_captured_logical_name',json_object('parent_id',s.parent,'child_id',s.child,
                'low',s.low,'width',s.width) FROM slices s LEFT JOIN canonical_slices c ON c.engine=s.engine
                AND c.stage=s.stage AND c.parent=s.parent AND c.child=s.child AND c.low=s.low AND c.width=s.width
            WHERE c.parent IS NULL;
    ''')
    for engine, stage, parent, child, low, width in db.execute('SELECT * FROM slices'):
        before = db.execute('''SELECT type_key FROM types WHERE engine=? AND node=? AND stage<=?
            AND type_key IS NOT NULL ORDER BY stage DESC LIMIT 1''', (engine, parent, min(stage, 2))).fetchone()
        after = db.execute('''SELECT type_key FROM types WHERE engine=? AND node=? AND stage=?
            AND type_key IS NOT NULL''', (engine, child, stage)).fetchone()
        reason = None
        if before and low + width > json.loads(before[0])[0]:
            reason = 'native_slice_outside_parent_width'
        if after and (json.loads(after[0])[0] != width or json.loads(after[0])[2]):
            reason = 'native_child_type_disagrees_with_slice_geometry'
        if stage in (1, 2, 4) and not db.execute('''SELECT 1 FROM slices WHERE engine=? AND stage<?
                AND parent=? AND child=? AND low=? AND width=? LIMIT 1''', (engine, stage, parent, child, low, width)).fetchone():
            reason = 'new_bit_slice_outside_SplitNodes'
        if reason:
            db.execute('INSERT INTO differences VALUES(?,?,?,?,?,?,?,?)',
                (stage, 'split_geometry_invalid', compact([engine, parent, child, low, width, reason]), engine,
                 child if engine == 'grh' else None, child if engine == 'gsim' else None,
                 reason, compact({'parent_id': parent, 'child_id': child, 'low': low, 'width': width,
                                  'parent_type': json.loads(before[0]) if before else None,
                                  'child_type': json.loads(after[0]) if after else None})))


def lifecycle(db):
    for engine in ('grh', 'gsim'):
        for stage in range(1, 5):
            for identifier, old_name, new_name in db.execute('''SELECT n.id,o.name,n.name FROM inventory n JOIN inventory o
                    ON n.engine=o.engine AND n.id=o.id AND o.stage=n.stage-1
                    WHERE n.engine=? AND n.stage=? AND n.path!=o.path''', (engine, stage)):
                db.execute('INSERT INTO differences VALUES(?,?,?,?,?,?,?,?)',
                    (stage, 'lifecycle', compact([engine, identifier, old_name, new_name]), engine,
                     identifier if engine == 'grh' else None, identifier if engine == 'gsim' else None,
                     'surviving_logical_identity_renamed', compact({'before': old_name, 'after': new_name})))
            if stage != 3:
                for identifier, name in db.execute('''SELECT n.id,n.name FROM inventory n LEFT JOIN inventory o ON
                        n.engine=o.engine AND n.id=o.id AND o.stage=n.stage-1
                        WHERE n.engine=? AND n.stage=? AND o.id IS NULL''', (engine, stage)):
                    db.execute('INSERT INTO differences VALUES(?,?,?,?,?,?,?,?)',
                        (stage, 'lifecycle', compact([engine, identifier, 'new']), engine,
                         identifier if engine == 'grh' else None, identifier if engine == 'gsim' else None,
                         'unexpected_new_named_Node_outside_SplitNodes', compact({'name': name})))
            if stage in (1, 2):
                for identifier, name in db.execute('''SELECT o.id,o.name FROM inventory o LEFT JOIN inventory n ON
                        n.engine=o.engine AND n.id=o.id AND n.stage=o.stage+1
                        WHERE o.engine=? AND o.stage=? AND n.id IS NULL''', (engine, stage - 1)):
                    db.execute('INSERT INTO differences VALUES(?,?,?,?,?,?,?,?)',
                        (stage, 'lifecycle', compact([engine, identifier, 'removed']), engine,
                         identifier if engine == 'grh' else None, identifier if engine == 'gsim' else None,
                         'named_Node_removed_before_explicit_DCE', compact({'name': name})))
            if stage == 3:
                for identifier, name in db.execute('''SELECT n.id,n.name FROM inventory n LEFT JOIN inventory o ON
                        n.engine=o.engine AND n.id=o.id AND o.stage=n.stage-1 LEFT JOIN slices s ON
                        s.engine=n.engine AND s.stage=n.stage AND s.child=n.id
                        WHERE n.engine=? AND n.stage=3 AND o.id IS NULL AND s.child IS NULL''', (engine,)):
                    db.execute('INSERT INTO differences VALUES(?,?,?,?,?,?,?,?)',
                        (stage, 'lifecycle', compact([engine, identifier, 'missing_slice']), engine,
                         identifier if engine == 'grh' else None, identifier if engine == 'gsim' else None,
                         'new_split_Node_lacks_native_geometry', compact({'name': name})))
                for identifier, name in db.execute('''SELECT o.id,o.name FROM inventory o LEFT JOIN inventory n ON
                        n.engine=o.engine AND n.id=o.id AND n.stage=3 LEFT JOIN slices s ON
                        s.engine=o.engine AND s.stage=3 AND s.parent=o.id
                        WHERE o.engine=? AND o.stage=2 AND n.id IS NULL AND s.parent IS NULL''', (engine,)):
                    db.execute('INSERT INTO differences VALUES(?,?,?,?,?,?,?,?)',
                        (stage, 'lifecycle', compact([engine, identifier, 'unrecorded_retirement']), engine,
                         identifier if engine == 'grh' else None, identifier if engine == 'gsim' else None,
                         'retired_split_parent_lacks_native_children', compact({'name': name})))
            for identifier, name in db.execute('''SELECT n.id,n.name FROM inventory n LEFT JOIN inventory o ON
                    o.engine=n.engine AND o.stage=n.stage-1 AND o.id=n.id WHERE n.engine=? AND n.stage=?
                    AND o.id IS NULL AND EXISTS(SELECT 1 FROM inventory h WHERE h.engine=n.engine AND
                        h.id=n.id AND h.stage<n.stage-1)''', (engine, stage)):
                db.execute('INSERT INTO differences VALUES(?,?,?,?,?,?,?,?)',
                    (stage, 'lifecycle', compact([engine, identifier, 'reused_id']), engine,
                     identifier if engine == 'grh' else None, identifier if engine == 'gsim' else None,
                     'retired_logical_Node_identity_reused', compact({'name': name})))


class F32Subgraphs(Subgraphs):
    """The F28 checks plus explicitly ordered combinational array writes.

    Equality is still conditional on the producer's paired boundary anchors.
    Four-state input domains remain structure-only, as in the base checker.
    """
    def __init__(self, db, budget=10000, *, two_state=False):
        super().__init__(db, budget)
        self.two_state = two_state

    def geometry(self, row):
        previous = getattr(self, 'four_state', False)
        geometry = super().geometry(row)
        if self.two_state:
            self.four_state = previous
        return geometry

    @lru_cache(maxsize=8192)
    def operation(self, oid):
        operation = super().operation(oid)
        if not self.two_state or operation.get('kind') != 'grh.constant':
            return operation
        outputs = operation.get('out', [])
        if len(outputs) != 1:
            return operation
        width = self.value(outputs[0]).get('w', 0)
        if type(width) is not int or width < 1:
            return operation
        literal = attr(operation, 'constValue')
        # Only explicit simulation captures select X/Z-to-zero. Retain the
        # original physical/source records; normalize a local expression copy.
        if literal in ("'0", "'1", "'x", "'X", "'z", "'Z"):
            number = (1 << width) - 1 if literal == "'1" else 0
        elif re.fullmatch(r'[+-]?[0-9]+', str(literal)):
            number = int(literal, 10)
        else:
            match = re.fullmatch(r"(\d+)'[sS]?([bBoOdDhH])([+-]?[0-9a-fA-F_xXzZ?]+)", str(literal))
            if not match or int(match[1]) != width:
                return operation
            radix, digits = match[2].lower(), match[3].replace('_', '')
            if radix == 'd' and re.search('[xXzZ?]', digits):
                if not re.fullmatch('[xXzZ?]+', digits):
                    return operation
                number = 0
            else:
                try:
                    number = int(re.sub('[xXzZ?]', '0', digits), {'b': 2, 'o': 8, 'd': 10, 'h': 16}[radix])
                except ValueError as error:
                    return operation
        attrs = dict(operation.get('attrs', {}))
        attrs['constValue'] = {'v': str(width) + "'h" + format(number & ((1 << width) - 1), 'x')}
        return {**operation, 'attrs': attrs}
    @staticmethod
    def term_summary(term):
        return {'operation': term.op, 'width': term.type.width, 'signed': term.type.signed,
                'parameters': term.params, 'digest': term._digest.hex(),
                'operands': [arg._digest.hex() for arg in term.args]}

    @classmethod
    def first_term_difference(cls, left, right):
        pending, seen = deque([(left, right, ())]), set()
        while pending:
            a, b, path = pending.popleft()
            if a == b or (id(a), id(b)) in seen:
                continue
            seen.add((id(a), id(b)))
            if (a.op, a.type, a.params, len(a.args)) != (b.op, b.type, b.params, len(b.args)):
                return {'normalized_operand_path': path if len(path) <= 64 else path[:32] + path[-32:],
                        'normalized_operand_path_length': len(path),
                        'omitted_middle_operand_slots': max(0, len(path) - 64), 'grh': cls.term_summary(a),
                        'gsim': cls.term_summary(b)}
            pending.extend((x, y, path + (slot,)) for slot, (x, y) in enumerate(zip(a.args, b.args)))
        return None

    def paired_boundary_evidence(self, left, right):
        sources = {}
        for term in (left, right):
            sources.update(source_types(term))
        result = []
        for name, typ in sorted(sources.items(), key=lambda item: repr(item[0])):
            entry = {'source': name, 'width': typ.width, 'signed': typ.signed,
                     'domain': 'shared arbitrary defined 0/1'}
            if isinstance(name, tuple) and len(name) == 3 and name[0] == 'native_anchor':
                row = self.db.execute('''SELECT a.node,p.gsim,p.name FROM anchors a JOIN pairs p
                    ON p.grh=a.node WHERE a.value=? ORDER BY p.gsim LIMIT 1''', (name[1],)).fetchone()
                entry.update(grh_value_id=name[1], projection=name[2])
                if row:
                    entry.update(grh_node_id=row[0], gsim_node_id=row[1], name=row[2])
                    if hasattr(self, 'stage'):
                        count, complete = self.db.execute('''SELECT count(*),
                            min(json_extract(payload,'$.source_geometry_complete'))
                            FROM public_index.endpoints WHERE stage=? AND node=?''', (self.stage, row[0])).fetchone()
                        entry['source_geometry_complete'] = count > 0 and complete == 1
                        entry['source_binding_geometry'] = {'table': 'endpoints', 'stage': self.stage,
                            'node': row[0], 'rows': count, 'join': 'stable logical SemanticId only',
                            'endpoint_value_and_operation_ids': 'runtime graph namespace',
                            'grh_value_id': 'compact design.json namespace; no numeric physical-ID join'}
            result.append(entry)
        return result

    def record_term_origin(self, engine, term, origin):
        if not getattr(self, '_collect_origins', False):
            return
        entries = self._term_origins[engine].setdefault(term._digest.hex(), [])
        if len(entries) < 4 and origin not in entries:
            entries.append(origin)

    def record_native_origin(self, term, entries, eid, index):
        if getattr(self, '_collect_origins', False):
            self.record_term_origin('gsim', term, {'node_id': self.native_root_id,
                'assignment_tree_ordinal': getattr(self, '_native_tree_ordinal', None),
                'expression_id': eid, 'operation': entries[eid].get('op'), 'projection': index,
                'child_slots': [{'slot': slot, 'expression_id': child}
                                for slot, child in enumerate(entries[eid].get('children', []))]})

    @staticmethod
    def chain_edges(parents, target):
        edges = []
        while parents[target] is not None:
            target, edge = parents[target]
            edges.append(edge)
        return {'edges': edges if len(edges) <= 64 else edges[:32] + edges[-32:],
                'edge_count': len(edges), 'omitted_middle_edges': max(0, len(edges) - 64)}

    def grh_consumer_chain(self, target):
        """Shortest captured operand path to this Node's actual anchor, bounded locally."""
        pending, parents = deque([self.anchor_value]), {self.anchor_value: None}
        while pending:
            value = pending.popleft()
            if value == target:
                return {'status': 'found', 'scope': 'to_compared_Node_anchor', **self.chain_edges(parents, target)}
            producer = self.db.execute('SELECT op FROM producers WHERE value=?', (value,)).fetchone()
            if not producer or producer[0] not in self.members:
                continue
            operation = self.operation(producer[0])
            for slot, operand in enumerate(operation.get('in', [])):
                if operand in parents or len(parents) >= self.budget:
                    continue
                parents[operand] = (value, {'source_value_id': operand,
                    'consumer_operation_id': producer[0], 'operand_slot': slot,
                    'consumer_result_value_id': value})
                pending.append(operand)
        return {'status': 'not_reached_within_owned_Node_or_budget', 'scope': 'to_compared_Node_anchor'}

    def native_consumer_chain(self, origin):
        ordinal = origin.get('assignment_tree_ordinal')
        trees = self.native(self.native_root_id).get('assignTrees', [])
        if ordinal is None or ordinal >= len(trees) or trees[ordinal] is None:
            return {'status': 'no_captured_assignment_context'}
        tree = trees[ordinal]
        entries = {entry['id']: entry for entry in tree['nodes']}
        pending, parents = deque([tree['root']]), {tree['root']: None}
        while pending:
            eid = pending.popleft()
            if eid == origin['expression_id']:
                later = [i for i in range(ordinal + 1, len(trees)) if trees[i] is not None]
                return {'status': 'found', 'scope': 'to_captured_assignment_root',
                        'assignment_tree_ordinal': ordinal, **self.chain_edges(parents, eid),
                        'later_assignment_tree_ordinals': later[:16], 'later_assignment_tree_count': len(later),
                        'ordered_merge_is_not_a_captured_expression_edge': True}
            if eid not in entries:
                continue
            for slot, child in enumerate(entries[eid].get('children', [])):
                if child not in (None, -1) and child not in parents and len(parents) < self.budget:
                    parents[child] = (eid, {'source_expression_id': child,
                        'consumer_expression_id': eid, 'child_slot': slot})
                    pending.append(child)
        return {'status': 'not_reached_within_assignment_tree_or_budget'}

    def diagnose_projection(self, native, typ, index, left, right, proof):
        """Rerun only a differing projection to recover native provenance without hot-path tracing."""
        self._term_origins = {'grh': {}, 'gsim': {}}
        self._collect_origins = True
        previous_steps, self.steps = self.steps, 0
        provenance_error = None
        try:
            self.grh_expr(self.anchor_value, index)
            self.native_root(native, typ, index)
        except (Unverified, RecursionError) as error:
            provenance_error = str(error) or 'recursion_limit'
        finally:
            self._collect_origins, self.steps = False, previous_steps
        first = self.first_term_difference(left, right)
        if first:
            for engine in ('grh', 'gsim'):
                positions = self._term_origins[engine].get(first[engine]['digest'], [])
                first[engine]['native_positions'] = [{**position, 'consumer_chain':
                    self.grh_consumer_chain(position['value_id']) if engine == 'grh' else
                    self.native_consumer_chain(position)} for position in positions]
            first['position_meaning'] = 'native expressions producing this normalized term; normalized operand order is not native slot order'
        premises = self.paired_boundary_evidence(left, right)
        evidence = {'projection': index, 'canonical_structures_equal': False,
                    'first_term_difference': first, 'paired_boundary_premises': premises[:16],
                    'paired_boundary_premise_count': len(premises), 'premise_samples_complete': len(premises) <= 16,
                    'proof': {key: value for key, value in proof.items() if key not in ('inputs', 'left', 'right')},
                    'four_state_behavior_proved': False}
        if proof.get('status') == 'counterexample':
            evidence['counterexample'] = {'inputs': [{'source': name, 'value': value}
                for name, value in sorted(proof['inputs'].items(), key=lambda item: repr(item[0]))],
                'grh_value': proof['left'], 'gsim_value': proof['right'],
                'scope': 'defined two-state bit-vector expression under the recorded paired boundary premises'}
        if provenance_error:
            evidence['provenance_error'] = provenance_error
        self._term_origins = {'grh': {}, 'gsim': {}}
        return evidence

    def compare(self, grh_id, gsim_id):
        """Keep structural differences distinct from proven functional counterexamples."""
        self.root, self.steps, self.native_root_id = grh_id, 0, gsim_id
        self.four_state, self._collect_origins, self.last_diagnosis, self.last_anchor_proof = False, False, {}, None
        self.members = {row[0] for row in self.db.execute('SELECT op FROM members WHERE node=?', (grh_id,))}
        self.visited, self.active = set(), set()
        native = self.native(gsim_id)
        if native.get('type') in ('NODE_REG_SRC', 'NODE_REG_DST', 'NODE_MEMORY', 'NODE_READER', 'NODE_WRITER', 'NODE_SPECIAL', 'NODE_EXT'):
            return 'unverified', 'state_memory_effect_unverified'
        if any(STATE.search(self.operation(oid)['kind']) for oid in self.members):
            return 'unverified', 'state_memory_effect_unverified'
        anchors = [row[0] for row in self.db.execute('SELECT value FROM anchors WHERE node=?', (grh_id,))]
        if len(anchors) != 1:
            return 'unverified', 'no_unique_native_Node_anchor'
        try:
            self.anchor_value = anchors[0]
            reached = self.owned_reachable(self.anchor_value)
            disconnected = sorted(self.members - reached)
            sampled_membership = disconnected and getattr(self, '_membership_samples', 0) < 8
            for oid in disconnected:
                self.db.execute('INSERT OR REPLACE INTO disconnected_members VALUES(?,?,?)',
                                (grh_id, oid, self.operation(oid)['kind']))
            if sampled_membership:
                self._membership_samples = getattr(self, '_membership_samples', 0) + 1
                self.last_diagnosis['membership_coverage'] = {'status': 'unverified',
                    'reason': 'owned_operations_not_reached_from_anchor', 'disconnected_member_count': len(disconnected),
                    'examples': [{'operation_id': oid, 'kind': self.operation(oid)['kind'],
                                  'inputs': self.operation(oid).get('in', []), 'outputs': self.operation(oid).get('out', [])}
                                 for oid in disconnected[:16]],
                    'physical_liveness_outside_this_Node': 'not_inferred_from_local_anchor_reachability'}
            width, signed, shape = self.geometry(self.value(self.anchor_value))
            native_width, native_signed, native_shape = self.native_geometry(gsim_id)
            if native_shape != shape or native_width != width:
                return 'different', 'physical_geometry_disagreement'
            if native_signed != signed:
                return 'different', 'signedness_disagreement'
            if native.get('type') == 'NODE_INP':
                if self.members or not self.value(self.anchor_value).get('in'):
                    return 'different', 'input_boundary_disagreement'
                if native.get('width', -1) != width:
                    raise Unverified('unknown_native_input_width')
                return ('structural_checked', 'input_geometry_and_native_anchor_X_semantics_unproved') if self.four_state else \
                    ('interface_checked', 'input_type_and_native_anchor')
            if prod(shape) > 4096:
                raise Unverified('array_projection_budget_exceeded')
            checked, exhaustive, differences, anchor_boundaries = 0, 0, [], {}
            for index in product(*(range(dim) for dim in shape)):
                left = self.grh_expr(self.anchor_value, index)
                right = self.native_root(native, BVType(width, signed), index)
                if sampled_membership:
                    for boundary in self.paired_boundary_evidence(left, right):
                        anchor_boundaries[repr(boundary['source'])] = boundary
                if left != right:
                    proof = compare_bitvectors(left, right)
                    if len(differences) < 8 or proof['status'] != 'proved_exhaustive_two_state_equality':
                        differences.append(self.diagnose_projection(native, BVType(width, signed), index, left, right, proof))
                    self.last_diagnosis['canonical_differences'] = differences
                    if proof['status'] == 'counterexample':
                        self.last_diagnosis['anchor_expression_proof'] = {'status': 'counterexample', 'projection': index,
                            'scope': 'common defined two-state boundary domain', 'four_state_behavior_proved': False}
                        return 'different', 'two_state_boundary_counterexample'
                    if proof['status'] != 'proved_exhaustive_two_state_equality':
                        self.last_diagnosis['anchor_expression_proof'] = {'status': 'unverified', 'projection': index,
                            'reason': proof.get('reason', proof['status']), 'four_state_behavior_proved': False}
                        return 'unverified', proof.get('reason', proof['status'])
                    exhaustive += 1
                checked += 1
            if disconnected:
                self.last_anchor_proof = ('typed_normalization_and_bounded_exhaustive_evaluation' if exhaustive else
                    'typed_normalization', checked, exhaustive)
            if sampled_membership or differences:
                premises = list(anchor_boundaries.values()) if disconnected else []
                self.last_diagnosis['anchor_expression_proof'] = {'status': 'proved',
                    'method': 'typed_normalization_and_bounded_exhaustive_evaluation' if exhaustive else 'typed_normalization',
                    'checked_leaf_projections': checked, 'exhaustively_checked_leaf_projections': exhaustive,
                    'paired_boundary_premises': premises[:16], 'paired_boundary_premise_count': len(premises),
                    'premise_samples_complete': len(premises) <= 16,
                    'additional_premise_evidence': 'canonical_differences paired boundary premises and indexed native members/anchors',
                    'scope': 'anchor expression only under shared arbitrary defined 0/1 paired boundaries',
                    'membership_coverage_proved': not disconnected, 'four_state_behavior_proved': False}
            if disconnected:
                return 'unverified', 'owned_operations_not_reached_from_anchor'
            if self.visited != reached:
                return 'unverified', 'expression_check_did_not_visit_all_reachable_members'
            if self.four_state:
                return 'structural_checked', 'equal_two_state_boundary_expressions_X_semantics_unproved' if exhaustive else \
                    'equal_typed_boundary_structure_X_semantics_unproved'
            return 'expression_checked', 'exhaustively_equal_typed_boundary_expressions' if exhaustive else 'equal_typed_boundary_expressions'
        except (Unverified, RecursionError) as error:
            return 'unverified', str(error) or 'recursion_limit'

    @staticmethod
    def conjunction(left, right):
        if left.op == 'const':
            return right if left.params[0] else left
        if right.op == 'const':
            return left if right.params[0] else right
        return binary('and', BVType(1), left, right)

    @staticmethod
    def coordinate_match(address, coordinate):
        if address.type.signed:
            raise Unverified('signed_array_index_not_supported')
        width = max(address.type.width, max(1, coordinate.bit_length()))
        address = resize(address, BVType(width))
        target = constant(coordinate, BVType(width))
        if address.op == 'const':
            return constant(int(address.params[0] == coordinate), BVType(1))
        return binary('eq', BVType(1), address, target)

    @classmethod
    def guarded_update(cls, match, payload, prior, typ):
        if payload.op == 'mux' and payload.args[2] == prior:
            return mux(cls.conjunction(match, payload.args[0]), payload.args[1], prior, typ)
        return mux(match, payload, prior, typ)

    def grh_expr(self, vid, index=()):
        term = self.array_grh_expr(vid, index)
        if getattr(self, '_collect_origins', False):
            producer = self.db.execute('SELECT op FROM producers WHERE value=?', (vid,)).fetchone()
            origin = {'value_id': vid, 'projection': index}
            if producer and producer[0] in self.members:
                origin.update(operation_id=producer[0], operation_kind=self.operation(producer[0])['kind'])
            self.record_term_origin('grh', term, origin)
        return term

    def native_expr(self, entries, eid, expected, index=()):
        entry = entries.get(eid, {})
        operation = entry.get('op', '').removeprefix('OP_')
        if self.two_state and operation == 'INT' and re.search('[xXzZ?]', str(entry.get('strVal', ''))):
            literal = entry['strVal']
            match = re.fullmatch(r'(-?)0([boh])([0-9a-fA-FxXzZ?]+)', literal)
            if not match:
                raise Unverified('invalid_two_state_GSIM_constant')
            try:
                number = int(match[1] + re.sub('[xXzZ?]', '0', match[3]), {'b': 2, 'o': 8, 'h': 16}[match[2]])
            except ValueError as error:
                raise Unverified('invalid_two_state_GSIM_constant') from error
            entries = {**entries, eid: {**entry, 'strVal': str(number)}}
        if operation in ('HEAD', 'TAIL', 'DSHR', 'ASCLOCK', 'ASASYNCRESET'):
            self.step()
            children = entry.get('children', [])
            required = 2 if operation == 'DSHR' else 1
            if index or len(children) != required:
                raise Unverified('invalid_native_scalar_expression:' + operation)
            args = [self.native_expr(entries, child, None) for child in children]
            width, signed = entry.get('width', -1), bool(entry.get('sign', False))
            if width < 1:
                raise Unverified('unknown_native_expression_width:' + operation)
            typ = BVType(width, signed)
            if operation in ('HEAD', 'TAIL'):
                if not getattr(self, '_native_head_tail_updated', False):
                    raise Unverified('native_head_tail_stage_unproved')
                values = entry.get('values', [])
                if len(values) != 1 or type(values[0]) is not int or values[0] < 0:
                    raise Unverified('invalid_native_width_parameters:' + operation)
                if operation == 'TAIL' and width > values[0]:
                    raise Unverified('native_tail_stage_width_disagreement')
                term = slice_bits(args[0], values[0] if operation == 'HEAD' else 0, width, signed)
            elif operation == 'DSHR':
                # GSIM may narrow only the result. Shift the original operand
                # before truncating, so its high bits can reach retained bits.
                term = resize(Term('ashr' if args[0].type.signed else 'lshr', args[0].type, tuple(args)), typ)
            else:
                if width != 1:
                    raise Unverified('native_clock_reset_cast_is_not_one_bit')
                term = cast(bitvector_boolean(args[0]), typ)
            term = resize(term, expected) if expected is not None else term
        else:
            term = super().native_expr(entries, eid, expected, index)
        self.record_native_origin(term, entries, eid, index)
        return term

    def array_grh_expr(self, vid, index=()):
        producer = self.db.execute('SELECT op FROM producers WHERE value=?', (vid,)).fetchone()
        if not producer or producer[0] not in self.members:
            return super().grh_expr(vid, index)
        operation = self.operation(producer[0])
        if operation['kind'] != 'grh.combArrayUpdate':
            return super().grh_expr(vid, index)
        self.step()
        width, signed, dimensions = self.geometry(self.value(vid))
        if len(index) != len(dimensions) or any(not 0 <= value < extent for value, extent in zip(index, dimensions)):
            raise Unverified('GRH_array_projection_out_of_bounds')
        key = ('grh', vid, index)
        if key in self.active:
            raise Unverified('combinational_cycle')
        self.active.add(key)
        self.visited.add(producer[0])
        try:
            args, counts = operation.get('in', []), attr(operation, 'indexCounts')
            if (not isinstance(counts, list) or not counts or
                    any(type(count) is not int or not 0 <= count <= len(dimensions) for count in counts) or
                    len(args) != 1 + sum(count + 2 for count in counts)):
                raise Unverified('invalid_array_update_group_layout')
            typ, offset = BVType(width, signed), 1
            result = self.grh_expr(args[0], index)
            for count in counts:
                enabled = self.grh_expr(args[offset])
                if enabled.type.width != 1:
                    raise Unverified('array_update_enable_not_one_bit')
                match = cast(enabled, BVType(1))
                for axis in range(count):
                    address = self.grh_expr(args[offset + axis + 1])
                    match = self.conjunction(match, self.coordinate_match(address, index[axis]))
                payload = self.grh_expr(args[offset + count + 1], index[count:])
                result = self.guarded_update(match, payload, result, typ)
                offset += count + 2
            return result
        finally:
            self.active.remove(key)

    def native_index(self, entries, eid):
        self.step()
        if eid not in entries:
            raise Unverified('missing_GSIM_index_expression')
        entry = entries[eid]
        operation = entry.get('op', '').removeprefix('OP_')
        if operation == 'INDEX_INT':
            values = entry.get('values', [])
            if len(values) != 1 or type(values[0]) is not int or values[0] < 0:
                raise Unverified('invalid_GSIM_static_index')
            return constant(values[0], BVType(max(1, values[0].bit_length())))
        if operation == 'INDEX':
            children = entry.get('children', [])
            if len(children) != 1:
                raise Unverified('invalid_GSIM_dynamic_index')
            return self.native_expr(entries, children[0], None)
        raise Unverified('unsupported_GSIM_lvalue_index:' + operation)

    def native_assignment(self, entries, eid, typ, index, prior):
        # JSON null/-1 is explicit absence, not OP_INVALID or a guessed
        # missing array value. Old dumps dropping null slots stay unverified.
        if eid in (None, -1):
            if prior is None:
                raise Unverified('partial_GSIM_assignment_without_prior_value')
            return prior
        entry = entries.get(eid)
        if entry is None:
            raise Unverified('missing_GSIM_assignment_expression')
        operation = entry.get('op', '').removeprefix('OP_')
        if operation == 'WHEN':
            children = entry.get('children', [])
            if len(children) != 3:
                raise Unverified('partial_when_dump_lost_original_branch_slots')
            condition = self.native_expr(entries, children[0], BVType(1))
            yes = self.native_assignment(entries, children[1], typ, index, prior)
            no = self.native_assignment(entries, children[2], typ, index, prior)
            term = mux(condition, yes, no, typ)
            self.record_native_origin(term, entries, eid, index)
            return term
        return self.native_expr(entries, eid, typ, index)

    def native_root(self, native, typ, index):
        trees = native.get('assignTrees')
        if trees is None:
            raise Unverified('assign_trees_not_dumped')
        if not trees:
            raise Unverified('no_native_assignment_tree')
        # order/orderInSuper identify original scheduled Nodes visited by
        # inferAllWidth::updateHeadTail. Unscheduled/split-only records lack
        # this witness; auxiliary state slots are handled separately.
        self._native_head_tail_updated = native.get('order', -1) > 0 and native.get('orderInSuper', -1) >= 0
        result = None
        for ordinal, tree in enumerate(trees):
            if tree is None:
                continue
            self._native_tree_ordinal = ordinal
            entries = {item['id']: item for item in tree['nodes']}
            if len(entries) != len(tree['nodes']):
                raise Unverified('duplicate_GSIM_expression_identity')
            lvalue = entries.get(tree.get('lvalue'))
            if lvalue is None:
                raise Unverified('missing_GSIM_assignment_lvalue')
            addresses = lvalue.get('children', [])
            if len(addresses) > len(index):
                raise Unverified('GSIM_lvalue_array_rank_disagreement')
            match = constant(1, BVType(1))
            for axis, eid in enumerate(addresses):
                match = self.conjunction(match, self.coordinate_match(self.native_index(entries, eid), index[axis]))
            if match.op == 'const' and match.params[0] == 0:
                continue
            if result is None and not (match.op == 'const' and match.params[0] == 1):
                raise Unverified('partial_GSIM_assignment_without_prior_value')
            payload = self.native_assignment(entries, tree['root'], typ, index[len(addresses):], result)
            result = payload if result is None else self.guarded_update(match, payload, result, typ)
        if result is None:
            raise Unverified('no_GSIM_assignment_for_observed_projection')
        return result


class StateBits:
    """Bounded ROBDD proof of bitwise transfer expressions.

    Arithmetic/other already-typed terms become opaque bit variables. Equal
    BDDs are sound under that stronger independence premise; unequal BDDs are
    unverified, never a fabricated functional counterexample.
    """
    def __init__(self, budget):
        self.budget, self.nodes, self.unique = budget, [None, None], {}

    def node(self, variable, low, high):
        if low == high:
            return low
        key = (variable, low, high)
        if key not in self.unique:
            if len(self.nodes) >= self.budget:
                raise Unverified('state_bitwise_proof_budget_exceeded')
            self.unique[key] = len(self.nodes)
            self.nodes.append(key)
        return self.unique[key]

    @lru_cache(maxsize=65536)
    def apply(self, operation, left, right):
        if left < 2 and right < 2:
            return int({'and': bool(left and right), 'or': bool(left or right), 'xor': bool(left != right)}[operation])
        variables = [self.nodes[node][0] for node in (left, right) if node >= 2]
        variable = min(variables)
        branches = [(self.nodes[node][1:]) if node >= 2 and self.nodes[node][0] == variable else (node, node)
                    for node in (left, right)]
        return self.node(variable, self.apply(operation, branches[0][0], branches[1][0]),
                         self.apply(operation, branches[0][1], branches[1][1]))

    @lru_cache(maxsize=65536)
    def bit(self, term, index):
        if not 0 <= index < term.type.width:
            raise Unverified('invalid_state_bit_projection')
        if term.op == 'const':
            return (term.params[0] >> index) & 1
        if term.op == 'cast':
            return self.bit(term.args[0], index)
        if term.op in ('zext', 'sext'):
            arg = term.args[0]
            return self.bit(arg, index) if index < arg.type.width else \
                self.bit(arg, arg.type.width - 1) if term.op == 'sext' else 0
        if term.op == 'slice':
            return self.bit(term.args[0], index + term.params[0])
        if term.op == 'not':
            return self.apply('xor', self.bit(term.args[0], index), 1)
        if term.op in ('and', 'or', 'xor'):
            return self.apply(term.op, self.bit(term.args[0], index), self.bit(term.args[1], index))
        if term.op == 'mux':
            select = self.bit(term.args[0], 0)
            return self.apply('or', self.apply('and', select, self.bit(term.args[1], index)),
                self.apply('and', self.apply('xor', select, 1), self.bit(term.args[2], index)))
        if term.op == 'concat':
            for arg in reversed(term.args):
                if index < arg.type.width:
                    return self.bit(arg, index)
                index -= arg.type.width
            raise Unverified('invalid_state_concat')
        if term.op == 'replicate':
            return self.bit(term.args[0], index % term.args[0].type.width)
        return self.node((term._digest, index), 0, 1)

    def equal(self, left, right):
        return left.type == right.type and all(self.bit(left, bit) == self.bit(right, bit)
                                              for bit in range(left.type.width))


class F32StateSubgraphs(F32Subgraphs):
    """Common-posedge, scalar state transitions; initialization stays separate."""
    def grh_expr(self, vid, index=()):
        if vid in self.current_values:
            if index:
                raise Unverified('indexed_state_read_unverified')
            return self.old_state
        return super().grh_expr(vid, index)

    def native_ref(self, name, index=()):
        refs = self.db.execute('SELECT id FROM gs_nodes WHERE native_name=?', (name,)).fetchall()
        if len(refs) == 1 and refs[0][0] == self.current_native:
            if index:
                raise Unverified('indexed_native_state_read_unverified')
            return self.old_state
        return super().native_ref(name, index)

    def tree_value(self, tree, typ):
        if not isinstance(tree, dict):
            raise Unverified('missing_native_state_expression_tree')
        entries = {item['id']: item for item in tree['nodes']}
        if len(entries) != len(tree['nodes']):
            raise Unverified('duplicate_native_state_expression_identity')
        # This helper reads auxiliary resetCond/resetVal slots. Their raw
        # HEAD/TAIL parameters need not have passed updateHeadTail.
        self._native_head_tail_updated = False
        return self.native_expr(entries, tree['root'], typ)

    def clock_value(self, vid, native_clock):
        if self.gtype(vid) != BVType(1):
            raise Unverified('state_clock_is_not_scalar_one_bit')
        paired = self.db.execute('''SELECT 1 FROM anchors a JOIN pairs p ON p.grh=a.node
            WHERE a.value=? AND p.gsim=?''', (vid, native_clock)).fetchone()
        if not paired:
            raise Unverified('state_clock_lacks_exact_paired_boundary')
        if self.native_geometry(native_clock) != (1, False, ()) or not self.native(native_clock).get('isClock'):
            raise Unverified('native_state_clock_type_or_role_unproved')

    def compare_transfer(self, grh_id, gsim_id):
        self.root, self.steps, self.four_state = grh_id, 0, False
        self.members, self.visited, self.active = set(), set(), set()
        self.current_values, self.current_native, self.old_state = set(), None, None
        evidence = {'premise': 'all paired free boundary values and common old state contain only defined 0/1 bits',
                    'scope': 'one common posedge sample; no asynchronous reset-only step or initialization equivalence',
                    'initialization_status': 'unverified', 'full_four_state_state_equivalence': False}
        try:
            observed = self.native(gsim_id)
            if observed.get('type') not in ('NODE_REG_SRC', 'NODE_REG_DST'):
                raise Unverified('not_a_native_register_pair')
            source_id = gsim_id if observed['type'] == 'NODE_REG_SRC' else observed.get('regSourceId')
            if type(source_id) is not int or source_id < 0:
                raise Unverified('native_state_source_pair_missing')
            current = self.native(source_id)
            next_id = current.get('regDestinationId', current.get('regNextId'))
            if type(next_id) is not int or next_id < 0:
                raise Unverified('native_state_destination_pair_missing')
            following = self.native(next_id)
            if (current.get('type') != 'NODE_REG_SRC' or following.get('type') != 'NODE_REG_DST' or
                    current.get('regNextId') != next_id or following.get('regNextId') != source_id or
                    following.get('regSourceId') != source_id or following.get('regDestinationId') != next_id):
                raise Unverified('native_state_pair_is_not_reciprocal')
            current_trees = [tree for tree in current.get('assignTrees', []) if tree is not None]
            if len(current_trees) != 1:
                raise Unverified('native_state_sample_requires_one_destination_reference')
            current_entries = {item['id']: item for item in current_trees[0]['nodes']}
            sampled = current_entries.get(current_trees[0]['root'], {})
            if (sampled.get('op', '').removeprefix('OP_') != 'EMPTY' or sampled.get('children') or
                    sampled.get('node') != following.get('name') or sampled.get('nodeId', next_id) != next_id):
                raise Unverified('native_state_sample_is_not_the_paired_destination')
            for native_node in (current, following):
                for tree in native_node.get('assignTrees', []):
                    if tree is None:
                        continue
                    entries = {item['id']: item for item in tree['nodes']}
                    lvalue = entries.get(tree.get('lvalue'), {})
                    if (lvalue.get('op', '').removeprefix('OP_') != 'EMPTY' or lvalue.get('children') or
                            lvalue.get('node') != native_node.get('name') or
                            lvalue.get('nodeId', native_node['id']) != native_node['id']):
                        raise Unverified('native_state_assignment_lvalue_identity_disagreement')
            current_pair = self.db.execute('SELECT grh FROM pairs WHERE gsim=?', (source_id,)).fetchone()
            next_pair = self.db.execute('SELECT grh FROM pairs WHERE gsim=?', (next_id,)).fetchone()
            if not current_pair or not next_pair:
                raise Unverified('state_current_or_next_lacks_paired_logical_identity')
            current_grh, next_grh = current_pair[0], next_pair[0]
            anchors = self.db.execute('SELECT value FROM anchors WHERE node=?', (current_grh,)).fetchall()
            if len(anchors) != 1:
                raise Unverified('state_current_has_no_unique_native_anchor')
            current_value = anchors[0][0]
            width, signed, shape = self.geometry(self.value(current_value))
            if shape or self.native_geometry(source_id) != (width, signed, ()) or self.native_geometry(next_id) != (width, signed, ()):
                raise Unverified('state_scalar_geometry_disagreement')
            producer = self.db.execute('SELECT op FROM producers WHERE value=?', (current_value,)).fetchone()
            if not producer or self.operation(producer[0])['kind'] != 'grh.registerReadPort':
                raise Unverified('state_current_is_not_a_scalar_register_read')
            symbol = attr(self.operation(producer[0]), 'regSymbol')
            declaration = self.db.execute('SELECT op FROM state_declarations WHERE symbol=?', (symbol,)).fetchall()
            if len(declaration) != 1:
                raise Unverified('state_declaration_is_not_unique')
            declaration = self.operation(declaration[0][0])
            if (declaration['kind'] != 'grh.registerDecl' or attr(declaration, 'width') != width or
                    bool(attr(declaration, 'isSigned')) != signed or attr(declaration, 'shape', [])):
                raise Unverified('state_declaration_geometry_disagreement')
            typ = BVType(width, signed)
            self.current_native, self.native_root_id = source_id, next_id
            self.old_state = source(('paired_old_state', current_grh), typ)
            ports = [self.operation(op) for op, in self.db.execute('SELECT op FROM state_ports WHERE symbol=?', (symbol,))]
            writers, orders = [], set()
            for op in ports:
                if op['kind'] == 'grh.registerReadPort':
                    if op.get('in') or len(op.get('out', [])) != 1 or self.geometry(self.value(op['out'][0])) != (width, signed, ()):
                        raise Unverified('state_read_geometry_disagreement')
                    self.current_values.add(op['out'][0])
                elif op['kind'] in ('grh.registerWritePort', 'grh.registerWriteMaskPort'):
                    order = attr(op, 'writerOrder')
                    if type(order) is not int or order < 0 or order in orders:
                        raise Unverified('state_writer_order_missing_or_ambiguous')
                    orders.add(order)
                    writers.append((order, op))
                else:
                    raise Unverified('indexed_or_other_state_port_unverified')
            if not writers:
                raise Unverified('state_has_no_captured_writer')
            writers.sort(key=lambda item: item[0])
            # The next logical identity must own each actual writer. Never
            # identify a transition from a similarly named declaration alone.
            next_members = {op for op, in self.db.execute('SELECT op FROM members WHERE node=?', (next_grh,))}
            if any(op['id'] not in next_members for _, op in writers):
                raise Unverified('state_writer_not_owned_by_paired_next_identity')
            self.members = next_members | {op for op, in self.db.execute('SELECT op FROM members WHERE node=?', (current_grh,))}
            native_clock = current.get('clockId')
            if type(native_clock) is not int or native_clock < 0 or following.get('clockId') != native_clock:
                raise Unverified('state_common_clock_missing')
            evidence.update(grh_state_node_id=current_grh, grh_next_node_id=next_grh,
                gsim_state_node_id=source_id, gsim_next_node_id=next_id, gsim_clock_node_id=native_clock,
                register_symbol=symbol, grh_declaration_operation_id=declaration['id'],
                ordered_grh_writer_ids=[op['id'] for _, op in writers])
            result = self.old_state
            for _, op in writers:
                args = op.get('in', [])
                masked = op['kind'] == 'grh.registerWriteMaskPort'
                if attr(op, 'eventEdge') != ['posedge'] or len(args) != (4 if masked else 3):
                    raise Unverified('state_requires_one_posedge_clock_without_other_events')
                self.clock_value(args[-1], native_clock)
                enabled, data = self.grh_expr(args[0]), self.grh_expr(args[1])
                if enabled.type != BVType(1) or data.type != typ:
                    raise Unverified('state_writer_data_or_enable_type_disagreement')
                payload = data
                if masked:
                    mask = self.grh_expr(args[2])
                    if mask.type.width != width:
                        raise Unverified('state_writer_mask_width_disagreement')
                    mask = cast(mask, typ)
                    inverse = binary('xor', typ, mask, constant((1 << width) - 1, typ))
                    payload = binary('or', typ, binary('and', typ, result, inverse), binary('and', typ, data, mask))
                result = mux(enabled, payload, result, typ)
            native_result = self.native_root(following, typ, ())
            reset = current.get('reset')
            if type(reset) is not int:
                raise Unverified('native_reset_class_unresolved')
            if reset == 1:
                raise Unverified('asynchronous_reset_assertion_step_unverified')
            if reset not in (2, 3):
                raise Unverified('native_reset_class_unresolved')
            if reset == 2:
                reset_tree = current.get('resetTree')
                if not isinstance(reset_tree, dict):
                    raise Unverified('native_synchronous_reset_tree_missing')
                entries = {item['id']: item for item in reset_tree['nodes']}
                root = entries.get(reset_tree['root'], {})
                children = root.get('children', [])
                if root.get('op', '').removeprefix('OP_') != 'RESET' or len(children) != 2 or any(child is None for child in children):
                    raise Unverified('native_synchronous_reset_tree_layout_unproved')
                self._native_head_tail_updated = current.get('order', -1) > 0 and current.get('orderInSuper', -1) >= 0
                condition = self.native_expr(entries, children[0], BVType(1))
                reset_value = self.native_expr(entries, children[1], typ)
                auxiliary_checks = {}
                for slot, expected_term, slot_type in (('resetCond', condition, BVType(1)), ('resetVal', reset_value, typ)):
                    auxiliary_checks[slot] = 'absent origin slot; operative resetTree supplies behavior'
                    if current.get(slot) is not None:
                        if expected_term != self.tree_value(current[slot], slot_type):
                            raise Unverified('native_reset_tree_disagrees_with_captured_reset_slots')
                        auxiliary_checks[slot] = 'checked against operative resetTree'
                native_result = mux(condition, reset_value, native_result, typ)
                evidence['reset_timing'] = 'synchronous-only at common posedge'
                evidence['native_reset_policy'] = {'current_reset_class': reset, 'operative_reset_tree': 'captured OP_RESET',
                    'auxiliary_origin_checks': auxiliary_checks, 'next_reset_class_used': False}
            else:
                # ZERO_RESET is the current register's operative native
                # policy. SplitNodes preserves that enum and resetTree but
                # deliberately drops auxiliary resetCond/resetVal origins.
                if 'resetTree' not in current:
                    raise Unverified('native_zero_reset_tree_slot_not_captured')
                if current['resetTree'] is not None:
                    raise Unverified('zero_reset_class_has_nonzero_or_unproved_reset')
                condition_evidence = 'absent origin slot; explicit current ZERO_RESET policy'
                if current.get('resetCond') is not None:
                    condition = self.tree_value(current['resetCond'], BVType(1))
                    if condition.op != 'const' or condition.params[0] != 0:
                        raise Unverified('zero_reset_class_has_nonzero_or_unproved_reset')
                    condition_evidence = 'captured auxiliary reset condition checked as exactly zero'
                evidence['reset_timing'] = 'native current ZERO_RESET class; no reset overlay at common posedge'
                evidence['native_reset_policy'] = {'current_reset_class': reset, 'operative_reset_tree': 'explicit null',
                    'auxiliary_reset_condition': condition_evidence, 'next_reset_class_used': False,
                    'initial_state_inferred': False}
            evidence['grh_initialization'] = {key: attr(declaration, key) for key in declaration.get('attrs', {})
                if key.startswith('init')}
            evidence['initialization_reason'] = 'native GSIM structure supplies no initial-state policy; no inference from reset'
            bits = StateBits(max(1024, self.budget * 8))
            try:
                equal = bits.equal(result, native_result)
            finally:
                bits.bit.cache_clear()
                bits.apply.cache_clear()
            if not equal:
                raise Unverified('state_transition_expressions_not_proved_equal')
            evidence['proof'] = 'bounded bitwise ROBDD equality; other typed subexpressions are shared opaque bits'
            return 'common_posedge_transfer_checked', 'equal_scalar_state_transition_under_defined_boundary_premises', evidence
        except (Unverified, RecursionError, KeyError, TypeError) as error:
            return 'unverified', str(error) or 'state_proof_recursion_limit', evidence


def structure_index(grh, native, output):
    """Stream full native records into bounded insert batches, one stage at a time.

    Keep the F28 checker's table interface; never guess omitted member/anchor
    records or retain the complete graph as Python objects.
    """
    db = sqlite3.connect(output / 'comparison.sqlite')
    db.executescript('''
        PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=FILE;
        PRAGMA cache_size=-262144;
        CREATE TABLE grh_nodes(id INTEGER PRIMARY KEY,name TEXT NOT NULL);
        CREATE TABLE members(node INTEGER,op INTEGER,PRIMARY KEY(node,op));
        CREATE TABLE anchors(node INTEGER,value INTEGER,PRIMARY KEY(node,value));
        CREATE TABLE values_ir(id INTEGER PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE ops(id INTEGER PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE producers(value INTEGER PRIMARY KEY,op INTEGER NOT NULL);
        CREATE TABLE gs_nodes(id INTEGER PRIMARY KEY,name TEXT,native_name TEXT,inventory TEXT,payload TEXT NOT NULL);
        CREATE TABLE pairs(grh INTEGER PRIMARY KEY,gsim INTEGER UNIQUE,name TEXT NOT NULL);
        CREATE TABLE native_type_evidence(id INTEGER PRIMARY KEY,width INTEGER,signed INTEGER,shape TEXT,evidence TEXT);
        CREATE TABLE disconnected_members(node INTEGER,op INTEGER,kind TEXT,PRIMARY KEY(node,op));
        CREATE TABLE native_kinds(id INTEGER PRIMARY KEY,kind TEXT);
        CREATE TABLE state_operations(id INTEGER PRIMARY KEY);
        CREATE TABLE state_declarations(symbol TEXT,op INTEGER PRIMARY KEY);
        CREATE TABLE state_ports(symbol TEXT,op INTEGER PRIMARY KEY);
    ''')
    pending = {}
    def emit(sql, row):
        rows = pending.setdefault(sql, [])
        rows.append(row)
        if len(rows) >= BATCH:
            db.executemany(sql, rows)
            rows.clear()
    def flush():
        for sql, rows in pending.items():
            db.executemany(sql, rows)
            rows.clear()
    counts, flattened, active = Counter(), None, False
    with db:
        for section, row in records(grh):
            if section == 'graph':
                active = False
            elif section == 'flattened':
                if flattened is not None:
                    raise ValueError('expected one flattened graph with a SemanticTree')
                flattened, active = row, True
            elif section == 'paths' and active:
                counts['paths'] += 1
                if row['id'] != 1 or row['parent'] != 0:
                    raise ValueError('comparison requires post-flatten root-only Paths')
            elif section == 'nodes' and active:
                if row['parent'] != 1 or 'ops' not in row:
                    raise ValueError('requires named leaf Nodes with authoritative ops')
                emit('INSERT INTO grh_nodes VALUES(?,?)', (row['id'], row['name']))
                for key, table in (('ops', 'members'), ('anchors', 'anchors')):
                    refs = row.get(key, [])
                    if len(refs) != len(set(refs)):
                        raise ValueError('duplicate native Node ' + key)
                    for ref in refs:
                        emit('INSERT INTO ' + table + ' VALUES(?,?)', (row['id'], ref))
                counts['grh_nodes'] += 1
            elif section in ('vals', 'values') and active:
                emit('INSERT INTO values_ir VALUES(?,?)', (row['id'], compact(row)))
                counts['grh_values'] += 1
            elif section == 'ops' and active:
                emit('INSERT INTO ops VALUES(?,?)', (row['id'], compact(row)))
                for value in row.get('out', []):
                    emit('INSERT INTO producers VALUES(?,?)', (value, row['id']))
                if STATE.search(row['kind']):
                    emit('INSERT INTO state_operations VALUES(?)', (row['id'],))
                if row['kind'] in ('grh.registerDecl', 'grh.latch'):
                    emit('INSERT INTO state_declarations VALUES(?,?)', (row.get('sym'), row['id']))
                elif row['kind'].startswith(('grh.register', 'grh.latch')):
                    emit('INSERT INTO state_ports VALUES(?,?)', (attr(row, 'regSymbol'), row['id']))
                counts['grh_ops'] += 1
                if counts['grh_ops'] % 1000000 == 0:
                    flush()
                    print(f'[F32] indexed {counts["grh_ops"]:,} native GRH ops', flush=True)
        flush()
        if flattened is not True or counts['paths'] != 1:
            raise ValueError('requires namesFlattened=true and exactly one root Path')
        for section, row in records(native):
            if section not in ('nodes', 'memories'):
                continue
            if section == 'memories':
                # A physical memory may be present in both native sections.
                # Only byte-independent JSON equality permits this overlap;
                # conflicting definitions never overwrite the real Node.
                flush()
                existing = db.execute('SELECT payload FROM gs_nodes WHERE id=?', (row['id'],)).fetchone()
                if existing:
                    if json.loads(existing[0]) != row:
                        raise ValueError('conflicting GSIM Node definitions across native sections')
                    counts['gsim_repeated_memory_records'] += 1
                    continue
            emit('INSERT INTO gs_nodes VALUES(?,?,?,?,?)',
                 (row['id'], candidate_name(row), row.get('name', ''), section, compact(row)))
            emit('INSERT INTO native_kinds VALUES(?,?)', (row['id'], row.get('type', '')))
            counts['gsim_nodes'] += 1
            if counts['gsim_nodes'] % 1000000 == 0:
                flush()
                print(f'[F32] indexed {counts["gsim_nodes"]:,} native GSIM Nodes', flush=True)
        flush()
        db.executescript('''
            CREATE INDEX members_by_op ON members(op,node);
            CREATE INDEX anchors_by_value ON anchors(value,node);
            CREATE INDEX gs_native_names ON gs_nodes(native_name);
            CREATE INDEX state_declaration_symbol ON state_declarations(symbol);
            CREATE INDEX state_port_symbol ON state_ports(symbol);
        ''')
        missing = db.execute('''SELECT 1 FROM members m LEFT JOIN ops o ON o.id=m.op
            WHERE o.id IS NULL LIMIT 1''').fetchone()
        missing_anchor = db.execute('''SELECT 1 FROM anchors a LEFT JOIN values_ir v ON v.id=a.value
            WHERE v.id IS NULL LIMIT 1''').fetchone()
        if missing or missing_anchor:
            raise ValueError('native Node members/anchors refer to missing IR objects')
    return db, dict(counts)


def proof_groups(db, stage):
    groups = []
    for status, reason, count in db.execute('''SELECT status,reason,count(*) FROM structural
            WHERE stage=? GROUP BY status,reason ORDER BY status,reason''', (stage,)):
        inherited = db.execute('''SELECT count(*) FROM structural s JOIN pairs p ON
            p.stage=s.stage AND p.grh=s.grh JOIN pairs origin ON origin.stage=0 AND origin.name=p.name
            JOIN structural previous ON previous.stage=0 AND previous.grh=origin.grh
            WHERE s.stage=? AND s.status=? AND s.reason=? AND previous.status=s.status
                AND previous.reason=s.reason''', (stage, status, reason)).fetchone()[0]
        examples = [{'grh_node_id': grh, 'gsim_node_id': gsim, 'name': name}
            for grh, gsim, name in db.execute('''SELECT s.grh,s.gsim,p.name FROM structural s JOIN pairs p ON
                p.stage=s.stage AND p.grh=s.grh WHERE s.stage=? AND s.status=? AND s.reason=? ORDER BY s.grh LIMIT 8''',
                (stage, status, reason))]
        new_examples = [{'grh_node_id': grh, 'gsim_node_id': gsim, 'name': name}
            for grh, gsim, name in db.execute('''SELECT s.grh,s.gsim,p.name FROM structural s JOIN pairs p ON
                p.stage=s.stage AND p.grh=s.grh WHERE s.stage=? AND s.status=? AND s.reason=? AND NOT EXISTS(
                    SELECT 1 FROM pairs origin JOIN structural previous ON previous.stage=origin.stage
                    AND previous.grh=origin.grh WHERE origin.stage=0 AND origin.name=p.name
                    AND previous.status=s.status AND previous.reason=s.reason) ORDER BY s.grh LIMIT 8''',
                (stage, status, reason))]
        groups.append({'proof_status': status, 'reason': reason, 'affected_nodes': count,
                       'same_result_present_at_P0': inherited, 'not_present_with_same_result_at_P0': count - inherited,
                       'examples': examples, 'not_present_at_P0_examples': new_examples})
    return groups


def compare_state_transfers(db, local, stage, budget, node_limit, *, two_state=False):
    total = local.execute("SELECT count(*) FROM pairs p JOIN native_kinds k ON k.id=p.gsim WHERE k.kind IN ('NODE_REG_SRC','NODE_REG_DST')").fetchone()[0]
    checker, processed, last = F32StateSubgraphs(local, budget, two_state=two_state), 0, -1
    while node_limit is None or processed < node_limit:
        amount = BATCH if node_limit is None else min(BATCH, node_limit - processed)
        rows = local.execute('''SELECT p.grh,p.gsim FROM pairs p JOIN native_kinds k ON k.id=p.gsim
            WHERE k.kind IN ('NODE_REG_SRC','NODE_REG_DST') AND p.grh>? AND NOT EXISTS(SELECT 1 FROM
            public_index.state_transfers s WHERE s.stage=? AND s.grh=p.grh) ORDER BY p.grh LIMIT ?''',
            (last, stage, amount)).fetchall()
        if not rows:
            break
        results = []
        for grh, gsim in rows:
            status, reason, evidence = checker.compare_transfer(grh, gsim)
            results.append((stage, grh, gsim, status, reason, compact(evidence)))
            last = grh
        local.commit()
        with db:
            db.executemany('INSERT INTO state_transfers VALUES(?,?,?,?,?,?)', results)
        processed += len(rows)
    groups = []
    for status, reason, count in db.execute('''SELECT status,reason,count(*) FROM state_transfers
            WHERE stage=? GROUP BY status,reason ORDER BY status,reason''', (stage,)):
        examples = [{'grh_node_id': grh, 'gsim_node_id': gsim, 'name': name, 'evidence': json.loads(evidence)}
            for grh, gsim, name, evidence in db.execute('''SELECT s.grh,s.gsim,p.name,s.evidence FROM state_transfers s
                JOIN pairs p ON p.stage=s.stage AND p.grh=s.grh WHERE s.stage=? AND s.status=? AND s.reason=?
                ORDER BY s.grh LIMIT 4''', (stage, status, reason))]
        groups.append({'status': status, 'reason': reason, 'affected_nodes': count, 'examples': examples})
    counts = dict(db.execute('SELECT status,count(*) FROM state_transfers WHERE stage=? GROUP BY status', (stage,)))
    return {'scope': 'common posedge transfer from arbitrary shared defined scalar old state; initialization remains unverified',
            'counts': counts, 'results_by_reason': groups, 'paired_state_endpoints': total,
            'unprocessed_state_endpoints': total - sum(counts.values()), 'full_state_behavior_proved': False,
            'all_node_results': 'state_transfers table in comparison.sqlite'}


def compare_structure(db, captures, output, budget, node_limit=None, selected_stages=None):
    """Index actual full IR separately at each boundary; keep bounded local proofs."""
    reports = {}
    for stage in range(5):
        files = [captures[engine]['snapshots'][f'P{stage}'].get('structure') for engine in ('grh', 'gsim')]
        pairs = db.execute('SELECT count(*) FROM pairs WHERE stage=?', (stage,)).fetchone()[0]
        compared = db.execute('SELECT count(*) FROM structural WHERE stage=?', (stage,)).fetchone()[0]
        if not all(files):
            reports[f'P{stage}'] = {'status': 'not_captured', 'behavior_proved': False,
                                   'paired_nodes': pairs, 'unprocessed_nodes': pairs - compared}
            continue
        selected = selected_stages is None or stage in selected_stages
        if not selected and not compared:
            reports[f'P{stage}'] = {'status': 'not_requested', 'behavior_proved': False,
                                   'paired_nodes': pairs, 'unprocessed_nodes': pairs}
            continue
        identities = []
        for engine, filename in zip(('grh', 'gsim'), files):
            artifact = captures[engine]['snapshots'][f'P{stage}'].get('artifacts', {}).get('structure')
            path = Path(filename)
            if (not isinstance(artifact, dict) or artifact.get('sha256') != digest(path) or
                    artifact.get('bytes') != path.stat().st_size or Path(artifact.get('path', '')).resolve() != path.resolve()):
                raise ValueError('native structure changed since capture')
            identities.append({'path': str(path.resolve()), 'sha256': artifact['sha256'], 'bytes': artifact['bytes']})
        directory = output / 'structure' / f'P{stage}'
        directory.mkdir(parents=True, exist_ok=True)
        marker = directory / 'index.json'
        identity = {'schema': 'wolvrix.f32.structure-index.v1', 'inputs': identities}
        if marker.exists():
            previous = json.loads(marker.read_text())
            if any(previous.get(key) != value for key, value in identity.items()):
                raise ValueError('cached structure index has different native inputs')
            local = sqlite3.connect(directory / 'comparison.sqlite')
            local.executescript('PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA temp_store=FILE; PRAGMA cache_size=-262144;')
        else:
            # An interrupted index has no completed marker and supplies no
            # proof rows. Only this tool's known derived database is rebuilt.
            partial = directory / 'comparison.sqlite'
            if partial.exists():
                partial.unlink()
            local, index_counts = structure_index(Path(files[0]), Path(files[1]), directory)
            local.executescript('PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;')
            write_json(marker, {**identity, 'counts': index_counts})
        try:
            with local:
                local.execute('DELETE FROM pairs')
                local.executemany('INSERT INTO pairs VALUES(?,?,?)', db.execute(
                    'SELECT grh,gsim,name FROM pairs WHERE stage=?', (stage,)))
            missing = local.execute('''SELECT 1 FROM pairs p LEFT JOIN grh_nodes g ON g.id=p.grh
                LEFT JOIN gs_nodes s ON s.id=p.gsim WHERE g.id IS NULL OR s.id IS NULL LIMIT 1''').fetchone()
            if missing:
                raise ValueError('public candidate does not exist in captured native structure')
            local.execute('ATTACH DATABASE ? AS public_index', (str(output / 'comparison.sqlite'),))
            state_transfer = compare_state_transfers(db, local, stage, budget, node_limit if selected else 0,
                two_state=captures['grh'].get('window_semantics') == '2state')
            if selected and compared < pairs:
                # These classes are explicitly unverified in the checker;
                # aggregate their native kinds in SQL before expression work.
                skipped = local.execute('''SELECT p.grh,p.gsim FROM pairs p JOIN native_kinds k ON k.id=p.gsim
                    WHERE k.kind IN ('NODE_REG_SRC','NODE_REG_DST','NODE_MEMORY','NODE_READER','NODE_WRITER',
                        'NODE_SPECIAL','NODE_EXT') OR EXISTS(SELECT 1 FROM members m JOIN state_operations o
                        ON o.id=m.op WHERE m.node=p.grh) ORDER BY p.grh''')
                while True:
                    rows = skipped.fetchmany(BATCH)
                    if not rows:
                        break
                    with db:
                        db.executemany('INSERT OR IGNORE INTO structural VALUES(?,?,?,?,?)',
                            ((stage, grh, gsim, 'unverified', 'state_memory_effect_unverified') for grh, gsim in rows))
                checker = F32Subgraphs(local, budget, two_state=captures['grh'].get('window_semantics') == '2state')
                checker.stage = stage
                checker._membership_samples = db.execute('''SELECT count(*) FROM structural_diagnoses
                    WHERE stage=? AND json_type(evidence,'$.membership_coverage') IS NOT NULL''', (stage,)).fetchone()[0]
                query = '''SELECT p.grh,p.gsim FROM pairs p WHERE p.grh>? AND NOT EXISTS(SELECT 1 FROM
                    public_index.structural s WHERE s.stage=? AND s.grh=p.grh) ORDER BY p.grh LIMIT ?'''
                pending, diagnoses, anchor_rows, processed, last = [], [], [], 0, -1
                counts = Counter(dict(db.execute('SELECT status,count(*) FROM structural WHERE stage=? GROUP BY status', (stage,))))
                def checkpoint():
                    # Finish the attached database's read transaction before
                    # the inventory connection commits its next result batch.
                    local.commit()
                    with db:
                        db.executemany('INSERT INTO structural VALUES(?,?,?,?,?)', pending)
                        db.executemany('INSERT INTO structural_diagnoses VALUES(?,?,?,?)', diagnoses)
                        db.executemany('INSERT INTO anchor_proofs VALUES(?,?,?,?,?,?)', anchor_rows)
                    pending.clear()
                    diagnoses.clear()
                    anchor_rows.clear()
                    write_json(directory / 'proof-progress.json', {'schema': 'wolvrix.f32.structure-progress.v1',
                        'boundary': f'P{stage}', 'complete': False, 'counts': dict(counts),
                        'processed_this_invocation': processed, 'paired_nodes': pairs,
                        'compared_nodes': sum(counts.values())})
                    print(f'[F32] P{stage} structure {sum(counts.values()):,}/{pairs:,}: {dict(counts)}', flush=True)
                while node_limit is None or processed < node_limit:
                    amount = BATCH if node_limit is None else min(BATCH, node_limit - processed)
                    rows = local.execute(query, (last, stage, amount)).fetchall()
                    if not rows:
                        break
                    for grh_id, gsim_id in rows:
                        status, reason = checker.compare(grh_id, gsim_id)
                        pending.append((stage, grh_id, gsim_id, status, reason))
                        if checker.last_diagnosis:
                            diagnoses.append((stage, grh_id, gsim_id, compact({
                                'schema': 'wolvrix.f32.structural-diagnosis.v1',
                                'node_result': {'status': status, 'reason': reason}, **checker.last_diagnosis})))
                        if checker.last_anchor_proof:
                            anchor_rows.append((stage, grh_id, gsim_id, *checker.last_anchor_proof))
                        counts[status] += 1
                        processed += 1
                        last = grh_id
                    checkpoint()
            counts = Counter(dict(db.execute('SELECT status,count(*) FROM structural WHERE stage=? GROUP BY status', (stage,))))
            groups = proof_groups(db, stage)
            with db:
                db.execute("DELETE FROM differences WHERE stage=? AND category='structure'", (stage,))
                for group in groups:
                    if group['proof_status'] not in ('different', 'unverified'):
                        continue
                    first = group['examples'][0]
                    db.execute('INSERT INTO differences VALUES(?,?,?,?,?,?,?,?)',
                        (stage, 'structure', compact(['proof-reason-group', group['proof_status'], group['reason']]),
                         'both', first['grh_node_id'], first['gsim_node_id'], group['reason'], compact({**group,
                            'scope': 'owned_Node_subgraph_with_paired_boundary_premises',
                            'grh_structure': files[0], 'gsim_structure': files[1],
                            'all_node_results': str(output / 'comparison.sqlite') + ':structural',
                            'available_native_diagnoses': str(output / 'comparison.sqlite') + ':structural_diagnoses',
                            'aggregation': 'counts and examples; each Node remains separately queryable'})))
            compared = sum(counts.values())
            conditional_expressions = counts['expression_checked'] + sum(group['affected_nodes'] for group in groups
                if group['proof_status'] == 'structural_checked' and
                group['reason'] in ('equal_typed_boundary_structure_X_semantics_unproved',
                                    'equal_two_state_boundary_expressions_X_semantics_unproved'))
            conditional_interfaces = counts['interface_checked'] + sum(group['affected_nodes'] for group in groups
                if group['proof_status'] == 'structural_checked' and
                group['reason'] == 'input_geometry_and_native_anchor_X_semantics_unproved')
            reports[f'P{stage}'] = {'status': 'compared' if compared == pairs else 'partial', 'counts': dict(counts),
                'paired_nodes': pairs, 'compared_nodes': compared, 'unprocessed_nodes': pairs - compared,
                'results_by_reason': groups,
                'state_transfers': state_transfer,
                'native_diagnosis_rows': db.execute('SELECT count(*) FROM structural_diagnoses WHERE stage=?', (stage,)).fetchone()[0],
                'membership_diagnosis_detail_sample_limit': 8,
                'all_disconnected_members': str(directory / 'comparison.sqlite') + ':disconnected_members',
                'separately_proved_anchors_with_uncovered_members': db.execute(
                    'SELECT count(*) FROM anchor_proofs WHERE stage=?', (stage,)).fetchone()[0],
                'all_separate_anchor_proofs': str(output / 'comparison.sqlite') + ':anchor_proofs',
                'anchor_proof_does_not_prove_membership_or_full_Node': True,
                'two_state_expression_equivalence_under_boundary_premises': counts['expression_checked'],
                'common_two_state_domain': {
                    'expression_checked': conditional_expressions, 'interface_checked': conditional_interfaces,
                    'unproved_paired_nodes': pairs - conditional_expressions - conditional_interfaces,
                    'premise': 'every paired free boundary leaf and observed state sample is defined and contains only 0/1 bits',
                    'scope': 'typed combinational Node expressions under producer boundary pairing; state transitions and effects remain unverified',
                    'four_state_behavior_proved': False,
                    'unknown_constants': 'explicit simulation X/Z-to-zero' if captures['grh'].get('window_semantics') == '2state'
                        else 'X/Z literals remain unverified; no conversion to zero'},
                'four_state_behavior_proved': False,
                'limitations': 'state/effects/unsupported/partial operations remain unverified; structural_checked is not X/Z behavior proof'}
            write_json(directory / 'proof-progress.json', {'schema': 'wolvrix.f32.structure-progress.v1',
                'boundary': f'P{stage}', 'complete': compared == pairs, **reports[f'P{stage}']})
        finally:
            local.close()
    return reports


def export_report(db, captures, output, snapshots, structural, started):
    stages = {}
    for stage in range(5):
        total = lambda engine: db.execute('SELECT count(*) FROM inventory WHERE engine=? AND stage=?', (engine, stage)).fetchone()[0]
        pairs = db.execute('SELECT count(*) FROM pairs WHERE stage=?', (stage,)).fetchone()[0]
        types = db.execute('''SELECT count(*),sum(g.type_key=s.type_key),sum(g.evidence='native-binding')
            FROM pairs p JOIN types g ON g.engine='grh' AND g.stage=p.stage AND g.node=p.grh
            JOIN types s ON s.engine='gsim' AND s.stage=p.stage AND s.node=p.gsim
            WHERE p.stage=? AND g.type_key IS NOT NULL AND s.type_key IS NOT NULL''', (stage,)).fetchone()
        categories = dict(db.execute('SELECT category,count(*) FROM differences WHERE stage=? GROUP BY category', (stage,)))
        introduced = db.execute('''SELECT count(*) FROM differences d WHERE d.stage=? AND NOT EXISTS(
            SELECT 1 FROM differences p WHERE p.stage<d.stage AND p.category=d.category AND p.key=d.key)''', (stage,)).fetchone()[0]
        inherited = db.execute('''SELECT count(*) FROM differences d WHERE d.stage=? AND EXISTS(
            SELECT 1 FROM differences p WHERE p.stage=0 AND p.category=d.category AND p.key=d.key)''', (stage,)).fetchone()[0]
        source_geometry = db.execute('''SELECT count(*),sum(json_extract(payload,'$.source_geometry_complete')=1)
            FROM endpoints WHERE stage=?''', (stage,)).fetchone()
        grh_count, gsim_count = total('grh'), total('gsim')
        stages[f'P{stage}'] = {'grh_nodes': grh_count, 'gsim_nodes': gsim_count, 'unique_name_candidates': pairs,
            'grh_unique_name_candidate_ratio': pairs / grh_count if grh_count else None,
            'type_candidates_checked': types[0], 'equal_physical_geometry': types[1] or 0,
            'type_checks_with_native_GRH_binding': types[2] or 0,
            'GRH_source_geometry': {'endpoint_rows': source_geometry[0],
                'complete_v2_native_binding_rows': source_geometry[1] or 0,
                'incomplete_or_candidate_rows': source_geometry[0] - (source_geometry[1] or 0)},
            'differences_by_category': categories, 'first_seen_here': introduced,
            'same_difference_present_at_P0': inherited, 'structure': structural[f'P{stage}']}
    ledger = output / 'differences.jsonl'
    with ledger.open('w') as stream:
        for row in db.execute('''SELECT d.stage,d.category,d.key,d.engine,d.grh,d.gsim,d.reason,d.evidence,
            (SELECT min(p.stage) FROM differences p WHERE p.category=d.category AND p.key=d.key)
            FROM differences d ORDER BY d.stage,d.category,d.key'''):
            stage, category, key, engine, grh_id, gsim_id, reason, evidence, first = row
            evidence = json.loads(evidence)
            grouped = category == 'structure' and 'affected_nodes' in evidence
            same = evidence.get('same_result_present_at_P0', 0) if grouped else int(first == 0)
            affected = evidence['affected_nodes'] if grouped else 1
            stream.write(compact({'boundary': f'P{stage}', 'first_boundary': f'P{first}',
                'category': category, 'key': json.loads(key), 'engine': engine,
                'grh_node_id': grh_id, 'gsim_node_id': gsim_id, 'reason': reason,
                'evidence': evidence, 'semantic_explanation_status': 'unexplained',
                'aggregation_level': 'proof-reason' if grouped else 'native-difference',
                'same_node_results_present_at_P0': same,
                'new_node_results_since_P0': affected - same,
                'inherited_from_P0': first == 0 and same == affected,
                'partially_inherited_from_P0': 0 < same < affected}) + '\n')
    new_count = db.execute('''SELECT count(*) FROM differences d WHERE d.stage>0 AND NOT EXISTS(
        SELECT 1 FROM differences p WHERE p.stage=0 AND p.category=d.category AND p.key=d.key)''').fetchone()[0]
    full_structure = all(row.get('status') == 'compared' for row in structural.values())
    unproved = db.execute("SELECT count(*) FROM structural WHERE status NOT IN ('expression_checked','interface_checked')").fetchone()[0]
    unmatched = sum(row['grh_nodes'] + row['gsim_nodes'] - 2 * row['unique_name_candidates'] for row in stages.values())
    unprocessed = sum(structural[key].get('unprocessed_nodes', value['unique_name_candidates'])
                      for key, value in stages.items())
    incomplete_source_geometry = sum(row['GRH_source_geometry']['incomplete_or_candidate_rows'] for row in stages.values())
    report = {'schema': SCHEMA, 'status': 'analyzed', 'complete': True, 'input_sha256': captures['grh']['input_sha256'],
        'window_semantics': captures['grh'].get('window_semantics', 'legacy-unspecified'),
        'scope': 'post-first-DCE through second-DCE inclusive', 'snapshots': snapshots, 'boundaries': stages,
        'differences': str(ledger), 'comparison_database': str(output / 'comparison.sqlite'),
        'new_differences_not_present_at_P0': new_count, 'full_native_structure_compared': full_structure,
        'new_unproved_node_results_since_P0': sum(group['not_present_with_same_result_at_P0']
            for key, proof in structural.items() if key != 'P0' for group in proof.get('results_by_reason', [])
            if group['proof_status'] in ('unverified', 'different')),
        'structurally_unprocessed_paired_nodes': unprocessed, 'unproved_compared_pairs': unproved,
        'unpaired_native_nodes': unmatched,
        'incomplete_GRH_source_geometry_endpoint_rows': incomplete_source_geometry,
        'common_domain_proof_nodes': db.execute('SELECT count(*) FROM common_domain_proofs').fetchone()[0],
        'common_domain_proof_does_not_establish_full_four_state_equivalence': True,
        'semantic_acceptance': full_structure and new_count == 0 and unproved == 0 and unmatched == 0 and incomplete_source_geometry == 0,
        'four_state_behavior_proved': False, 'wall_s': time.monotonic() - started,
        'meaning': 'name candidates, physical types/dependencies, conditional expression proofs and unverified behavior are separate; no offline identity repair',
        'extra_capability_explanations_accepted': 0}
    write_json(output / 'summary.json', report)
    return report


def comparison_identity(grh, gsim):
    sources = ('compare_f32_semantics.py', 'compare_f28_semantic_tree.py', 'semantic_bitvector.py', 'semantic_node_exchange.py')
    return {'schema': 'wolvrix.f32.comparison-checkpoint.v1',
        'capture_summaries': {engine: {'path': str(Path(directory).resolve()),
            'sha256': digest(Path(directory) / 'summary.json')} for engine, directory in (('grh', grh), ('gsim', gsim))},
        'proof_implementation': {name: digest(ROOT / 'scripts' / name) for name in sources}}


def verify_cached_inventory(captures):
    """A resumed index must still refer to the same frozen native artifacts."""
    for engine in ('grh', 'gsim'):
        names = ('nodes.tsv', 'connections.tsv', 'bit-slices.tsv',
                 'node-endpoints.tsv' if engine == 'grh' else 'node-details.tsv')
        for stage in range(5):
            record = captures[engine]['snapshots'][f'P{stage}']
            for name in names:
                path = Path(record['directory']) / name
                artifact = record['artifacts'][name]
                if (Path(artifact['path']).resolve() != path.resolve() or artifact['bytes'] != path.stat().st_size or
                        artifact['sha256'] != digest(path)):
                    raise ValueError('native table changed since capture during resume: ' + str(path))


def compare(grh, gsim, output, *, budget=10000, structure=True, resume=False,
            node_limit=None, selected_stages=None):
    started = time.monotonic()
    captures = {'grh': capture(grh, 'grh'), 'gsim': capture(gsim, 'gsim')}
    if captures['grh']['input_sha256'] != captures['gsim']['input_sha256']:
        raise ValueError('GRH and GSIM captures have different raw FIRRTL inputs')
    if captures['grh'].get('window_semantics') != captures['gsim'].get('window_semantics'):
        raise ValueError('GRH and GSIM captures have different window semantics')
    output = Path(output)
    identity = comparison_identity(grh, gsim)
    checkpoint = output / 'inputs.json'
    if resume:
        previous = json.loads(checkpoint.read_text())
        if any(previous.get(key) != value for key, value in identity.items()):
            raise ValueError('resume requires the same frozen captures and proof implementation')
        if previous.get('inventory_complete') is not True:
            raise ValueError('interrupted inventory index is incomplete; use a new output directory')
        verify_cached_inventory(captures)
        db = sqlite3.connect(output / 'comparison.sqlite')
        db.executescript('PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA temp_store=FILE; PRAGMA cache_size=-262144;')
        snapshots = previous['snapshots']
    else:
        output.mkdir(parents=True, exist_ok=False)
        write_json(checkpoint, {**identity, 'inventory_complete': False})
        db = database(output / 'comparison.sqlite')
        snapshots = {}
    os.environ['SQLITE_TMPDIR'] = str(output.resolve())
    try:
        if not resume:
            with db:
                for engine in ('grh', 'gsim'):
                    snapshots[engine], run, identifiers = {}, None, set()
                    for stage in range(5):
                        record = ingest_snapshot(db, engine, stage, captures[engine]['snapshots'][f'P{stage}'],
                                                 run, captures[engine]['input_sha256'])
                        run = record['run_id']
                        if record['snapshot_id'] in identifiers:
                            raise ValueError('distinct boundaries reuse a native snapshot ID')
                        identifiers.add(record['snapshot_id'])
                        snapshots[engine][f'P{stage}'] = record
                        print(f'[F32] indexed {engine} P{stage}: {record["nodes"]:,} Nodes', flush=True)
                derive(db)
                lifecycle(db)
                slice_geometry(db)
            write_json(checkpoint, {**identity, 'inventory_complete': True, 'snapshots': snapshots})
        structural = compare_structure(db, captures, output, budget, node_limit, selected_stages) if structure else {
            f'P{i}': {'status': 'not_requested', 'behavior_proved': False} for i in range(5)}
        return export_report(db, captures, output, snapshots, structural, started)
    except BaseException as error:
        write_json(output / 'summary.json', {'schema': SCHEMA, 'status': 'failed', 'complete': False,
            'semantic_acceptance': False, 'error': repr(error), 'wall_s': time.monotonic() - started})
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--grh', type=Path, required=True)
    parser.add_argument('--gsim', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--local-budget', type=int, default=10000)
    parser.add_argument('--inventory-only', action='store_true')
    parser.add_argument('--resume', action='store_true', help='reuse validated inventory and completed per-Node proof batches')
    parser.add_argument('--structure-stage', action='append', choices=[f'P{i}' for i in range(5)],
                        help='check only selected boundaries; all omitted coverage remains explicit')
    parser.add_argument('--structure-node-limit', type=int,
                        help='maximum newly normalized Nodes per selected boundary; resume continues later batches')
    args = parser.parse_args()
    if args.local_budget < 1:
        parser.error('local budget must be positive')
    if args.structure_node_limit is not None and args.structure_node_limit < 1:
        parser.error('structure node limit must be positive')
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / 'ptmp').resolve()) or output == (ROOT / 'ptmp').resolve():
        parser.error('output must be a new directory under repository ptmp/')
    report = compare(args.grh.resolve(), args.gsim.resolve(), output,
                     budget=args.local_budget, structure=not args.inventory_only, resume=args.resume,
                     node_limit=args.structure_node_limit,
                     selected_stages=None if args.structure_stage is None else {int(stage[1:]) for stage in args.structure_stage})
    print(compact({'status': report['status'], 'semantic_acceptance': report['semantic_acceptance'],
                   'summary': str(output / 'summary.json')}))


if __name__ == '__main__':
    main()
