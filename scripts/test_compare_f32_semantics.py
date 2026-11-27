"""F32 native comparison contracts; matching names never prove behavior."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from compare_f32_semantics import (CAPTURE_SCHEMA, DETAIL_COLUMNS, ENDPOINT_COLUMNS, ENDPOINT_V1_COLUMNS,
                                  F32StateSubgraphs, F32Subgraphs, SLICE_COLUMNS, STAGES, capture, compare,
                                  database, derive, ingest_snapshot, lifecycle, slice_geometry, structure_index)
from semantic_bitvector import BVType, Unverified, evaluate, mux, source
from semantic_node_exchange import HEADERS, KINDS, SCHEMA, compact, encode_cell

ROOT = Path(__file__).resolve().parents[1]


def coverage(edges):
    return {kind: {'status': 'partial' if any(row[3] == kind and row[4] == 'unresolved' for row in edges) else 'complete',
                   'resolved': sum(row[3] == kind and row[4] == 'resolved' for row in edges),
                   'unresolved': sum(row[3] == kind and row[4] == 'unresolved' for row in edges)} for kind in KINDS}


def artifact(path):
    return {'path': str(path), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


class InventoryIndexTests(unittest.TestCase):
    def inventory_database(self, *, legacy_indexes=False, legacy_lookups=False, boundary_cases=False):
        db = database(':memory:')
        self.addCleanup(db.close)
        db.execute('PRAGMA automatic_index=OFF')
        for engine in ('grh', 'gsim'):
            for stage in range(5):
                nodes = [(1, 'input', 8), (2, 'parent', 8), (3, 'out', 8),
                         (4, 'shared_slice', 4), (5, 'late_slice', 4)]
                if stage >= 3:
                    nodes.append((6, 'extra_slice', 4))
                if boundary_cases:
                    nodes.extend([(7, None, 8), (8, 'duplicate', 8), (9, 'duplicate', 8),
                                  (10, 'before' if stage < 2 else 'after', 8),
                                  (11, 'type_mismatch', 8 if engine == 'grh' else 4),
                                  (12, 'missing_type', 8)])
                    if stage >= 3:
                        nodes.extend([(13, 'geometry_slice', 2), (14, 'renamed_parent_slice', 2),
                                      (15, 'missing_parent_slice', 2), (16, 'null_parent_slice', 2),
                                      (17, 'duplicate_slice', 2), (18, 'duplicate_slice', 2)])
                for identifier, name, width in nodes:
                    db.execute('INSERT INTO inventory VALUES(?,?,?,?,?,?)',
                        (engine, stage, identifier, name, compact([name]), name))
                    typ = compact([width, False, []])
                    if engine == 'grh':
                        if not (boundary_cases and identifier == 12):
                            db.execute('INSERT INTO endpoints VALUES(?,?,?,?,?,?,?,?,?)',
                                (stage, identifier, identifier, identifier, 'value', typ,
                                 '2state', 'native-binding', '{}'))
                    else:
                        db.execute('INSERT INTO details VALUES(?,?,?,?,?,?,?)',
                            (stage, identifier, typ, 'NODE_OTHERS', None, None, '{}'))
                edges = [(1, 1, 2)]
                if (engine, stage) in (('grh', 1), ('gsim', 2)):
                    # The same edge in another boundary must not hide either difference.
                    edges.append((2, 2, 3))
                if boundary_cases:
                    edges.extend([(3, 7, 3), (4, 8, 3), (5, 11, 3), (6, 1, 2)])
                for identifier, source, target in edges:
                    db.execute('INSERT INTO connections VALUES(?,?,?,?,?,?,?,?,?)',
                        (engine, stage, identifier, source, target, 'dependency', 'resolved', '[]', None))
                if boundary_cases:
                    db.execute('INSERT INTO connections VALUES(?,?,?,?,?,?,?,?,?)',
                        (engine, stage, 7, None, 3, 'dependency', 'unresolved', '[8,9]',
                         'ambiguous-native-boundary'))
                slices = []
                if stage >= 3:
                    slices.append((2, 4, 0, 4))
                    if engine == 'grh':
                        slices.append((2, 6, 4, 4))
                if stage == 4:
                    slices.append((2, 5, 4, 4))
                if boundary_cases and stage >= 3:
                    slices.extend([(2, 13, 0 if engine == 'grh' else 2, 2), (10, 14, 0, 2),
                                   (998, 15, 0, 2), (2, 997, 0, 2), (7, 16, 0, 2),
                                   (8, 17, 0, 2), (9, 18, 0, 2)])
                db.executemany('INSERT INTO slices VALUES(?,?,?,?,?,?)',
                    [(engine, stage, *geometry) for geometry in slices])

        class InventoryConnection:
            # Record plans for the exact production statements before they run.
            # Legacy modes change only table declarations or index access paths.
            def __init__(self):
                self.query_plans = {}

            def execute(self, sql, parameters=()):
                if 'CREATE TEMP TABLE canonical_edges AS' in sql:
                    key = 'canonical_edges'
                elif "'split_geometry_unverified'" in sql:
                    key = 'missing_slice_name'
                elif 'CREATE TEMP TABLE canonical_slices AS' in sql:
                    key = 'canonical_slices'
                else:
                    key = None
                if key:
                    self.query_plans[key] = [row[3] for row in
                        db.execute('EXPLAIN QUERY PLAN ' + sql, parameters)]
                return db.execute(sql, parameters)

            def executescript(self, sql):
                pending = ''
                for character in sql:
                    pending += character
                    if character != ';' or not sqlite3.complete_statement(pending):
                        continue
                    statement, pending = pending.strip(), ''
                    if legacy_lookups:
                        if statement.startswith('CREATE TEMP TABLE unique_names('):
                            continue
                        if statement.startswith('INSERT INTO unique_names SELECT '):
                            statement = 'CREATE TEMP TABLE unique_names AS ' + statement[len('INSERT INTO unique_names '):]
                        if statement.startswith('CREATE INDEX canonical_slices_native '):
                            continue
                    if legacy_indexes:
                        statement = statement.replace('ON canonical_edges(stage,edge_key,engine)',
                                                      'ON canonical_edges(engine,stage,edge_key)')
                        statement = statement.replace('ON canonical_slices(stage,slice_key,engine)',
                                                      'ON canonical_slices(engine,stage,slice_key)')
                        if statement.startswith('CREATE INDEX ') and ' ON slices(' in statement:
                            continue
                    self.execute(statement)
                if pending.strip():
                    self.execute(pending)

            def __getattr__(self, name):
                return getattr(db, name)

        connection = InventoryConnection()
        derive(connection)
        lifecycle(connection)
        slice_geometry(connection)
        return connection

    def test_inventory_lookups_use_all_equality_columns_before_stage_ranges(self):
        db = self.inventory_database()
        queries = (
            ('edge counterpart', '''SELECT e.edge_key FROM canonical_edges e WHERE NOT EXISTS(
                SELECT 1 FROM canonical_edges other WHERE other.engine!=e.engine
                AND other.stage=e.stage AND other.edge_key=e.edge_key)''', (), 'other',
                ('stage=?', 'edge_key=?')),
            ('slice counterpart', '''SELECT s.slice_key FROM canonical_slices s WHERE NOT EXISTS(
                SELECT 1 FROM canonical_slices o WHERE o.engine!=s.engine
                AND o.stage=s.stage AND o.slice_key=s.slice_key)''', (), 'o',
                ('stage=?', 'slice_key=?')),
            ('split child', '''SELECT n.id,n.name FROM inventory n LEFT JOIN inventory o ON
                n.engine=o.engine AND n.id=o.id AND o.stage=n.stage-1 LEFT JOIN slices s ON
                s.engine=n.engine AND s.stage=n.stage AND s.child=n.id
                WHERE n.engine=? AND n.stage=3 AND o.id IS NULL AND s.child IS NULL''', ('grh',), 's',
                ('engine=?', 'stage=?', 'child=?')),
            ('slice history', '''SELECT 1 FROM slices WHERE engine=? AND stage<?
                AND parent=? AND child=? AND low=? AND width=? LIMIT 1''', ('grh', 4, 2, 4, 0, 4), 'slices',
                ('engine=?', 'parent=?', 'child=?', 'low=?', 'width=?', 'stage<?')))
        for name, sql, parameters, alias, constraints in queries:
            with self.subTest(lookup=name):
                plan = [row[3] for row in db.execute('EXPLAIN QUERY PLAN ' + sql, parameters)]
                self.assertTrue(any('SEARCH ' + alias + ' ' in step and
                    all(constraint in step for constraint in constraints) for step in plan), plan)

    def test_index_revision_preserves_complete_inventory_difference_rows(self):
        revised, legacy = self.inventory_database(), self.inventory_database(legacy_indexes=True)
        sql = '''SELECT * FROM differences
            ORDER BY stage,category,key,engine,grh,gsim,reason,evidence'''
        self.assertEqual(revised.execute(sql).fetchall(), legacy.execute(sql).fetchall())
        rows = revised.execute('SELECT stage,category,engine,grh,gsim,reason FROM differences').fetchall()
        self.assertCountEqual(rows, [
            (1, 'connection', 'grh', 3, None, 'native_dependency_not_present_in_other_inventory'),
            (2, 'connection', 'gsim', None, 3, 'native_dependency_not_present_in_other_inventory'),
            (3, 'lifecycle', 'gsim', None, 6, 'new_split_Node_lacks_native_geometry'),
            (3, 'split_geometry', 'grh', 6, None, 'native_slice_geometry_not_present_in_other_engine'),
            (4, 'split_geometry', 'grh', 6, None, 'native_slice_geometry_not_present_in_other_engine'),
            (4, 'split_geometry_invalid', 'grh', 5, None, 'new_bit_slice_outside_SplitNodes'),
            (4, 'split_geometry_invalid', 'gsim', None, 5, 'new_bit_slice_outside_SplitNodes')])

    def test_canonical_node_and_slice_joins_use_complete_native_identity(self):
        revised, legacy = self.inventory_database(), self.inventory_database(legacy_lookups=True)
        self.assertEqual(dict((row[1], row[2]) for row in revised.execute(
            'PRAGMA temp.table_info(unique_names)'))['id'], 'INTEGER')
        self.assertEqual(dict((row[1], row[2]) for row in legacy.execute(
            'PRAGMA temp.table_info(unique_names)'))['id'], '')
        checks = (
            ('canonical_edges', 'su', ('engine=?', 'stage=?', 'id=?')),
            ('canonical_edges', 'tu', ('engine=?', 'stage=?', 'id=?')),
            ('missing_slice_name', 'c', ('engine=?', 'stage=?', 'parent=?', 'child=?', 'low=?', 'width=?')))
        for statement, alias, constraints in checks:
            with self.subTest(statement=statement, alias=alias):
                def has_lookup(plan):
                    return any('SEARCH ' + alias + ' ' in step and
                        all(constraint in step for constraint in constraints) for step in plan)
                self.assertTrue(has_lookup(revised.query_plans[statement]), revised.query_plans[statement])
                self.assertFalse(has_lookup(legacy.query_plans[statement]), legacy.query_plans[statement])
        for alias in ('p', 'c'):
            self.assertTrue(any('SEARCH ' + alias + ' ' in step and 'engine=?' in step and 'id=?' in step
                for step in revised.query_plans['canonical_slices']), revised.query_plans['canonical_slices'])

    def test_typed_name_and_slice_index_preserve_all_difference_rows(self):
        for boundary_cases in (False, True):
            with self.subTest(boundary_cases=boundary_cases):
                revised = self.inventory_database(boundary_cases=boundary_cases)
                legacy = self.inventory_database(legacy_lookups=True, boundary_cases=boundary_cases)
                self.assertCountEqual(revised.execute('SELECT * FROM differences').fetchall(),
                                      legacy.execute('SELECT * FROM differences').fetchall())
                self.assertCountEqual(revised.execute('SELECT * FROM pairs').fetchall(),
                                      legacy.execute('SELECT * FROM pairs').fetchall())
                self.assertCountEqual(revised.execute('SELECT * FROM canonical_edges').fetchall(),
                                      legacy.execute('SELECT * FROM canonical_edges').fetchall())
                if boundary_cases:
                    categories = {row[0] for row in revised.execute('SELECT DISTINCT category FROM differences')}
                    self.assertTrue({'presence', 'type', 'type_unverified', 'connection', 'unresolved_connection',
                        'lifecycle', 'split_geometry', 'split_geometry_invalid', 'split_geometry_unverified'} <= categories)


class NativeComparisonTests(unittest.TestCase):
    def setUp(self):
        work = ROOT / 'ptmp' / 'firrtl-ingest' / 'F32' / 'semantics-contract'
        work.mkdir(parents=True, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(dir=work))
        self.frames = {engine: [{'nodes': [(1, 'input'), (2, 'middle'), (3, 'out')],
            'edges': [(1, 1, 2, 'dependency', 'resolved', [], None),
                      (2, 2, 3, 'dependency', 'resolved', [], None)],
            'widths': {}, 'shapes': {}, 'slices': [], 'structure': None} for _ in range(5)] for engine in ('grh', 'gsim')}

    def tearDown(self):
        shutil.rmtree(self.work)

    def table(self, path, meta, columns, rows, footer):
        with path.open('w') as stream:
            stream.write('#meta\t' + compact(meta) + '\n')
            stream.write('\t'.join(columns) + '\n')
            for row in rows:
                stream.write('\t'.join(encode_cell(compact(value) if key.endswith('_json') and value is not None else value)
                    for key, value in zip(columns, row)) + '\n')
            stream.write('#footer\t' + compact({'complete': True, 'rowCount': len(rows), **footer}) + '\n')

    def write_capture(self, engine):
        directory = self.work / engine
        directory.mkdir()
        summary = {'schema': CAPTURE_SCHEMA, 'status': 'completed', 'engine': engine,
                   'source': 'raw-firrtl', 'input_sha256': 'a' * 64, 'trace_enabled': False,
                   'trace_validation': False, 'snapshots': {}, 'full_structure': False}
        for index, frame in enumerate(self.frames[engine]):
            stage = directory / f'P{index}'
            stage.mkdir()
            meta = {'schema': SCHEMA, 'engine': engine, 'run_id': engine + '-run', 'graph_id': 'top',
                    'exchange_session_id': engine + '-session', 'snapshot_id': f'{engine}-P{index}',
                    'stage': STAGES[engine][index]}
            artifacts = {}
            self.table(stage / 'nodes.tsv', {**meta, 'table': 'nodes'}, HEADERS['nodes'],
                [(identifier, [name], name) for identifier, name in sorted(frame['nodes'])], {'nodeInventoryComplete': True})
            self.table(stage / 'connections.tsv', {**meta, 'table': 'connections'}, HEADERS['connections'],
                       frame['edges'], {'connectionCoverage': coverage(frame['edges'])})
            if engine == 'grh':
                schema = frame.get('endpoint_schema', 'grh.semantic-node-endpoints.v2')
                columns = ENDPOINT_V1_COLUMNS if schema.endswith('.v1') else ENDPOINT_COLUMNS
                rows = []
                for identifier, _ in frame['nodes']:
                    row = dict(zip(ENDPOINT_COLUMNS, (identifier, 'value', identifier, 0,
                        identifier if identifier > 1 else 0, 0, 'grh.assign' if identifier > 1 else 'input',
                        frame['widths'].get(identifier, 8), 'false', frame['shapes'].get(identifier, []),
                        '2state', frame['widths'].get(identifier, 8), 'false',
                        frame['shapes'].get(identifier, []), [], [], 0, -1, 'native-binding')))
                    row.update(frame.get('endpoints', {}).get(identifier, {}))
                    rows.append(tuple(row[key] for key in columns))
                self.table(stage / 'node-endpoints.tsv', {**meta, 'schema': schema}, columns, rows, {})
                typed = 'node-endpoints.tsv'
            else:
                self.table(stage / 'node-details.tsv', {**meta, 'table': 'node-details', 'detail_schema': 'gsim.node-details.v1'},
                    DETAIL_COLUMNS, [(identifier, 'NODE_INP' if identifier == 1 else 'NODE_OTHERS',
                        frame['widths'].get(identifier, 8), 'false', frame['shapes'].get(identifier, []), None, None, 0, -1, 0 if identifier == 1 else 1)
                        for identifier, _ in frame['nodes']], {})
                typed = 'node-details.tsv'
            self.table(stage / 'bit-slices.tsv', {**meta, 'schema': 'semantic-node-bit-slices.v1'},
                       SLICE_COLUMNS, frame['slices'], {})
            for name in ('nodes.tsv', 'connections.tsv', typed, 'bit-slices.tsv'):
                artifacts[name] = artifact(stage / name)
            structure = None
            if frame['structure'] is not None:
                structure = str(stage / 'design.json')
                Path(structure).write_text(json.dumps(frame['structure'], indent=2) + '\n')
                artifacts['structure'] = artifact(Path(structure))
                summary['full_structure'] = True
            summary['snapshots'][f'P{index}'] = {'directory': str(stage), 'stage': STAGES[engine][index],
                'structure': structure, 'artifacts': artifacts, 'node_count': len(frame['nodes'])}
        (directory / 'summary.json').write_text(compact(summary))
        return directory

    def run_comparison(self, structure=False):
        return compare(self.write_capture('grh'), self.write_capture('gsim'), self.work / 'comparison', structure=structure)

    def explicit_semantics(self, directory, semantics='2state'):
        path = directory / 'summary.json'
        summary = json.loads(path.read_text())
        summary['window_semantics'] = semantics
        if summary['engine'] == 'grh':
            names = ('xmr-resolve', 'hier-flatten', 'comb-loop-elim', 'split-static-array',
                     'dead-code-elim', 'expr-opt', 'used-bits', 'split-nodes', 'dead-code-elim')
            summary['pass_calls'] = [{'pass': name, 'parameters': {'semantics': semantics}
                if name in names[5:8] else {}} for name in names]
        path.write_text(compact(summary))

    def test_explicit_semantics_requires_matching_actual_pass_parameters(self):
        directory = self.write_capture('grh')
        self.explicit_semantics(directory)
        self.assertEqual(capture(directory, 'grh')['window_semantics'], '2state')
        path = directory / 'summary.json'
        summary = json.loads(path.read_text())
        summary['pass_calls'][6]['parameters']['semantics'] = '4state'
        path.write_text(compact(summary))
        with self.assertRaisesRegex(ValueError, 'actual pass parameters'):
            capture(directory, 'grh')

    def test_mixed_capture_semantics_are_rejected(self):
        grh, gsim = self.write_capture('grh'), self.write_capture('gsim')
        self.explicit_semantics(grh)
        with self.assertRaisesRegex(ValueError, 'different window semantics'):
            compare(grh, gsim, self.work / 'comparison', structure=False)

    def test_explicit_two_state_preserves_known_bits_of_unknown_literals(self):
        self.attach_structure(four_state=True)
        for stage in range(5):
            op = self.frames['grh'][stage]['structure']['graphs'][0]['ops'][0]
            op.update(kind='grh.constant', **{'in': [], 'attrs': {'constValue': "8'b0x1z10xz"}})
            tree = self.frames['gsim'][stage]['structure']['nodes'][1]['assignTrees'][0]
            tree['nodes'][0].update(op='OP_INT', children=[], strVal='0h28')
        grh, gsim = self.write_capture('grh'), self.write_capture('gsim')
        self.explicit_semantics(grh)
        self.explicit_semantics(gsim)
        report = compare(grh, gsim, self.work / 'comparison')
        self.assertEqual(report['window_semantics'], '2state')
        self.assertEqual(report['boundaries']['P4']['structure']['counts']['expression_checked'], 2)
        self.assertFalse(report['four_state_behavior_proved'])
        self.assertFalse(any(row['reason'] == 'two_state_boundary_counterexample' for row in self.ledger()))

    def test_explicit_two_state_accepts_native_unsized_decimal_constant(self):
        self.attach_structure(four_state=True)
        for stage in range(5):
            op = self.frames['grh'][stage]['structure']['graphs'][0]['ops'][0]
            op.update(kind='grh.constant', **{'in': [], 'attrs': {'constValue': '0'}})
            tree = self.frames['gsim'][stage]['structure']['nodes'][1]['assignTrees'][0]
            tree['nodes'][0].update(op='OP_INT', children=[], strVal='0')
        grh, gsim = self.write_capture('grh'), self.write_capture('gsim')
        self.explicit_semantics(grh)
        self.explicit_semantics(gsim)
        report = compare(grh, gsim, self.work / 'comparison')
        self.assertEqual(report['boundaries']['P4']['structure']['counts']['expression_checked'], 2)

    def test_explicit_two_state_flattens_native_unknown_digits_individually(self):
        self.attach_structure(four_state=True)
        for stage in range(5):
            op = self.frames['grh'][stage]['structure']['graphs'][0]['ops'][0]
            op.update(kind='grh.constant', **{'in': [], 'attrs': {'constValue': "8'h28"}})
            tree = self.frames['gsim'][stage]['structure']['nodes'][1]['assignTrees'][0]
            tree['nodes'][0].update(op='OP_INT', children=[], strVal='0b0x1z10xz')
        grh, gsim = self.write_capture('grh'), self.write_capture('gsim')
        self.explicit_semantics(grh)
        self.explicit_semantics(gsim)
        report = compare(grh, gsim, self.work / 'comparison')
        self.assertEqual(report['boundaries']['P4']['structure']['counts']['expression_checked'], 2)
        self.assertEqual(report['boundaries']['P4']['structure']['counts']['interface_checked'], 1)
        self.assertFalse(report['four_state_behavior_proved'])

    def test_explicit_two_state_keeps_known_bit_counterexample(self):
        self.attach_structure(four_state=True)
        for stage in range(5):
            op = self.frames['grh'][stage]['structure']['graphs'][0]['ops'][0]
            op.update(kind='grh.constant', **{'in': [], 'attrs': {'constValue': "8'b0x1z10xz"}})
            tree = self.frames['gsim'][stage]['structure']['nodes'][1]['assignTrees'][0]
            tree['nodes'][0].update(op='OP_INT', children=[], strVal='0h08')
        grh, gsim = self.write_capture('grh'), self.write_capture('gsim')
        self.explicit_semantics(grh)
        self.explicit_semantics(gsim)
        report = compare(grh, gsim, self.work / 'comparison')
        self.assertFalse(report['semantic_acceptance'])
        self.assertEqual(self.diagnoses()[0, 2]['node_result']['reason'], 'two_state_boundary_counterexample')
        counterexample = self.diagnoses()[0, 2]['canonical_differences'][0]['counterexample']
        self.assertEqual((counterexample['grh_value'], counterexample['gsim_value']), (0x28, 0x08))

    def ledger(self):
        return [json.loads(line) for line in (self.work / 'comparison' / 'differences.jsonl').read_text().splitlines()]

    def attach_structure(self, *, unsupported=False, four_state=False):
        for stage in range(5):
            self.frames['grh'][stage]['structure'] = {'graphs': [{'symbol': 'top',
                'semanticTree': {'rootPath': 1, 'namesFlattened': True, 'paths': [{'id': 1, 'parent': 0}],
                    'nodes': [{'id': 1, 'parent': 1, 'name': 'input', 'ops': [], 'anchors': [1]},
                              {'id': 2, 'parent': 1, 'name': 'middle', 'ops': [1], 'anchors': [2]},
                              {'id': 3, 'parent': 1, 'name': 'out', 'ops': [2], 'anchors': [3]}]},
                'vals': [{'id': i, 'w': 8, 'sgn': False, 'shape': [], 'type': 'logic',
                          'domain': '4state' if four_state else '2state', 'in': i == 1} for i in range(1, 4)],
                'ops': [{'id': 1, 'kind': 'kMystery' if unsupported else 'grh.bitNot', 'in': [1], 'out': [2], 'attrs': {}},
                        {'id': 2, 'kind': 'grh.assign', 'in': [2], 'out': [3], 'attrs': {}}]}]}
            def tree(operation, source):
                entries = [{'id': 0, 'op': operation, 'width': 8, 'sign': False, 'children': [1]},
                           {'id': 1, 'op': 'OP_EMPTY', 'width': 8, 'sign': False, 'children': [], 'node': source},
                           {'id': 2, 'op': 'OP_EMPTY', 'width': 8, 'sign': False, 'children': [], 'node': 'unused'}]
                return {'root': 0 if operation != 'OP_EMPTY' else 1, 'lvalue': 2, 'nodes': entries}
            self.frames['gsim'][stage]['structure'] = {'nodes': [
                {'id': i, 'name': name, 'nodePath': [name], 'type': 'NODE_INP' if i == 1 else 'NODE_OTHERS',
                 'width': 8, 'sign': False, 'dimension': [],
                 'assignTrees': [] if i == 1 else [tree('OP_MYSTERY' if unsupported and i == 2 else
                                                      'OP_NOT' if i == 2 else 'OP_EMPTY', 'input' if i == 2 else 'middle')]}
                for i, name in ((1, 'input'), (2, 'middle'), (3, 'out'))], 'memories': []}

    def test_equal_inventory_is_only_a_candidate_result(self):
        report = self.run_comparison()
        self.assertEqual(report['boundaries']['P4']['unique_name_candidates'], 3)
        self.assertEqual(report['boundaries']['P4']['equal_physical_geometry'], 3)
        self.assertFalse(report['semantic_acceptance'])
        self.assertEqual(self.ledger(), [])

    def test_same_native_run_required_across_five_boundaries(self):
        grh, gsim = self.write_capture('grh'), self.write_capture('gsim')
        path = grh / 'P2' / 'nodes.tsv'
        path.write_text(path.read_text().replace('grh-run', 'different-run'))
        summary = json.loads((grh / 'summary.json').read_text())
        summary['snapshots']['P2']['artifacts']['nodes.tsv'] = artifact(path)
        (grh / 'summary.json').write_text(compact(summary))
        with self.assertRaisesRegex(ValueError, 'same native run'):
            compare(grh, gsim, self.work / 'comparison', structure=False)

    def test_capture_hashes_are_rechecked(self):
        grh, gsim = self.write_capture('grh'), self.write_capture('gsim')
        path = grh / 'P0' / 'nodes.tsv'
        path.write_text(path.read_text().replace('middle', 'changed'))
        with self.assertRaisesRegex(ValueError, 'changed since capture'):
            compare(grh, gsim, self.work / 'comparison', structure=False)

    def test_initial_and_new_type_differences_are_separate(self):
        for stage in range(5):
            self.frames['gsim'][stage]['widths'][2] = 4
        self.frames['grh'][2]['widths'][2] = 3
        report = self.run_comparison()
        inherited = [row for row in self.ledger() if row['category'] == 'type' and row['boundary'] == 'P1']
        introduced = [row for row in self.ledger() if row['category'] == 'type' and row['boundary'] == 'P2']
        self.assertTrue(inherited[0]['inherited_from_P0'])
        self.assertEqual(introduced[0]['first_boundary'], 'P2')
        self.assertGreater(report['new_differences_not_present_at_P0'], 0)

    def test_endpoint_tsv_width_is_leaf_width_for_both_engines(self):
        for engine in ('grh', 'gsim'):
            for frame in self.frames[engine]:
                frame['shapes'][2] = [2, 3]
        report = self.run_comparison()
        self.assertEqual(report['boundaries']['P4']['equal_physical_geometry'], 3)
        self.assertFalse(any(row['category'].startswith('type') for row in self.ledger()))

    def ingest_grh_endpoint_rows(self):
        directory = self.write_capture('grh')
        captured = capture(directory, 'grh')
        db = database(':memory:')
        try:
            ingest_snapshot(db, 'grh', 0, captured['snapshots']['P0'], None, captured['input_sha256'])
            return {node: json.loads(payload) for node, payload in db.execute(
                'SELECT node,payload FROM endpoints WHERE stage=0 ORDER BY node')}
        finally:
            db.close()

    def test_v2_source_geometry_preserves_original_axes_separately_from_physical_shape(self):
        self.frames['grh'][0]['endpoints'] = {
            1: {'shape_json': [2, 3], 'source_shape_json': [2, 3], 'projection_json': []},
            2: {'shape_json': [], 'source_shape_json': [2, 3], 'source_shape_field_depths_json': [0, 2],
                'projection_json': [1, 2], 'source_width': 16, 'source_signed': 'true',
                'source_bit_offset': 4, 'source_bit_width': 8},
            3: {'shape_json': [3], 'source_shape_json': [2, 3], 'source_shape_field_depths_json': [0, 2],
                'projection_json': [1, -1]}}
        rows = self.ingest_grh_endpoint_rows()
        for identifier in (1, 2, 3):
            self.assertTrue(rows[identifier]['source_geometry_complete'])
            self.assertEqual(rows[identifier]['source_geometry_schema'], 'grh.semantic-node-endpoints.v2')
            self.assertEqual(json.loads(rows[identifier]['source_shape_json']), [2, 3])
        self.assertEqual(json.loads(rows[2]['shape_json']), [])
        self.assertEqual(json.loads(rows[2]['source_shape_field_depths_json']), [0, 2])
        self.assertEqual(json.loads(rows[2]['projection_json']), [1, 2])
        self.assertEqual((rows[2]['source_width'], rows[2]['source_signed'],
                          rows[2]['source_bit_offset'], rows[2]['source_bit_width']), ('16', 'true', '4', '8'))
        self.assertEqual(json.loads(rows[3]['shape_json']), [3])
        self.assertEqual(json.loads(rows[3]['projection_json']), [1, -1])

    def test_v2_source_geometry_rejects_invalid_rank_bounds_and_field_depths(self):
        cases = (
            ({'projection_json': [1]}, 'projection differs from source rank'),
            ({'projection_json': [2, -1]}, 'projection is out of range'),
            ({'projection_json': [-2, -1]}, 'invalid source array projection'),
            ({'projection_json': [True, -1]}, 'invalid source array projection'),
            ({'source_shape_json': [-1, 3]}, 'invalid native shape'),
            ({'source_shape_json': [True, 3]}, 'invalid native shape'),
            ({'source_shape_field_depths_json': [0]}, 'invalid source shape field depths'),
            ({'source_shape_field_depths_json': [2, 0]}, 'invalid source shape field depths'),
            ({'source_shape_field_depths_json': [-1, 0]}, 'invalid source shape field depths'),
            ({'source_shape_field_depths_json': [False, 0]}, 'invalid source shape field depths'),
            ({'source_bit_offset': 1, 'source_bit_width': -1}, 'invalid source bit interval'),
            ({'source_bit_offset': 4, 'source_bit_width': 5}, 'invalid source bit interval'))
        for overrides, reason in cases:
            with self.subTest(overrides=overrides):
                self.frames['grh'][0]['endpoints'] = {2: {'source_shape_json': [2, 3],
                    'source_shape_field_depths_json': [0, 1], 'projection_json': [1, -1], **overrides}}
                try:
                    with self.assertRaisesRegex(ValueError, reason):
                        self.ingest_grh_endpoint_rows()
                finally:
                    shutil.rmtree(self.work / 'grh')

    def test_v1_endpoints_remain_diagnostic_without_complete_source_geometry(self):
        self.frames['grh'][0]['endpoint_schema'] = 'grh.semantic-node-endpoints.v1'
        self.frames['grh'][0]['endpoints'] = {2: {'projection_json': [999]}}
        rows = self.ingest_grh_endpoint_rows()
        self.assertEqual(rows[2]['evidence'], 'native-binding')
        self.assertEqual(json.loads(rows[2]['projection_json']), [999])
        self.assertNotIn('source_shape_json', rows[2])
        self.assertFalse(rows[2]['source_geometry_complete'])
        self.assertEqual(rows[2]['source_geometry_schema'], 'grh.semantic-node-endpoints.v1')

    def test_v2_candidates_do_not_claim_complete_source_geometry(self):
        self.frames['grh'][0]['endpoints'] = {
            2: {'evidence': 'anchor-candidate', 'source_width': -1},
            3: {'evidence': 'operation-only', 'value_id': 0, 'source_width': 0}}
        rows = self.ingest_grh_endpoint_rows()
        self.assertTrue(rows[1]['source_geometry_complete'])
        self.assertFalse(rows[2]['source_geometry_complete'])
        self.assertFalse(rows[3]['source_geometry_complete'])

    def test_new_dependency_keeps_native_endpoints_as_evidence(self):
        for stage in range(1, 5):
            self.frames['grh'][stage]['edges'].append((3, 1, 3, 'dependency', 'resolved', [], None))
        self.run_comparison()
        row = next(row for row in self.ledger() if row['category'] == 'connection')
        self.assertEqual(row['first_boundary'], 'P1')
        self.assertEqual(row['evidence']['source_node_id'], 1)
        self.assertEqual(row['evidence']['target_name'], 'out')
        self.assertEqual(row['semantic_explanation_status'], 'unexplained')

    def test_surviving_identity_must_not_be_renamed(self):
        for engine in ('grh', 'gsim'):
            self.frames[engine][2]['nodes'][1] = (2, 'renamed')
        self.run_comparison()
        self.assertTrue(any(row['reason'] == 'surviving_logical_identity_renamed' for row in self.ledger()))

    def test_new_split_children_need_real_geometry(self):
        for engine in ('grh', 'gsim'):
            for stage in (3, 4):
                self.frames[engine][stage]['nodes'].append((4, 'slice'))
        self.run_comparison()
        self.assertTrue(any(row['reason'] == 'new_split_Node_lacks_native_geometry' for row in self.ledger()))

    def test_slice_geometry_compared_even_when_child_names_match(self):
        for engine in ('grh', 'gsim'):
            for stage in (3, 4):
                self.frames[engine][stage]['nodes'].append((4, 'slice'))
                self.frames[engine][stage]['widths'][4] = 4
                self.frames[engine][stage]['slices'] = [(2, 4, 0 if engine == 'grh' else 4, 4)]
        self.run_comparison()
        self.assertTrue(any(row['category'] == 'split_geometry' for row in self.ledger()))

    def test_incomplete_public_inventory_is_rejected(self):
        grh, gsim = self.write_capture('grh'), self.write_capture('gsim')
        path = grh / 'P1' / 'nodes.tsv'
        path.write_text(path.read_text().replace('"nodeInventoryComplete":true', '"nodeInventoryComplete":false'))
        summary = json.loads((grh / 'summary.json').read_text())
        summary['snapshots']['P1']['artifacts']['nodes.tsv'] = artifact(path)
        (grh / 'summary.json').write_text(compact(summary))
        with self.assertRaisesRegex(ValueError, 'partial'):
            compare(grh, gsim, self.work / 'comparison', structure=False)

    def test_dangling_connection_rejected(self):
        self.frames['grh'][1]['edges'][0] = (1, 99, 2, 'dependency', 'resolved', [], None)
        with self.assertRaisesRegex(ValueError, 'outside its actual native inventory'):
            self.run_comparison()

    def test_actual_two_state_expression_proof_is_separate_from_names(self):
        self.attach_structure()
        report = self.run_comparison(structure=True)
        self.assertTrue(report['full_native_structure_compared'])
        self.assertEqual(report['boundaries']['P4']['structure']['counts']['expression_checked'], 2)
        self.assertTrue(report['semantic_acceptance'])

    def attach_double_not(self, width=4, *, four_state=False):
        self.attach_structure(four_state=four_state)
        for stage in range(5):
            for engine in ('grh', 'gsim'):
                self.frames[engine][stage]['widths'] = {identifier: width for identifier in range(1, 4)}
            graph = self.frames['grh'][stage]['structure']['graphs'][0]
            for value in graph['vals']:
                value['w'] = width
            graph['vals'].append({**graph['vals'][0], 'id': 4, 'in': False})
            graph['ops'][0]['in'] = [4]
            graph['ops'].append({'id': 3, 'kind': 'grh.bitNot', 'in': [1], 'out': [4], 'attrs': {}})
            graph['semanticTree']['nodes'][1]['ops'].append(3)
            for node in self.frames['gsim'][stage]['structure']['nodes']:
                node['width'] = width
                for tree in node['assignTrees']:
                    for entry in tree['nodes']:
                        entry['width'] = width
            middle = self.frames['gsim'][stage]['structure']['nodes'][1]
            middle['assignTrees'][0]['root'] = 1

    def diagnoses(self):
        with sqlite3.connect(self.work / 'comparison' / 'comparison.sqlite') as db:
            return {(stage, grh): json.loads(evidence) for stage, grh, evidence in db.execute(
                'SELECT stage,grh,evidence FROM structural_diagnoses')}

    def test_different_canonical_terms_can_be_exhaustively_equal(self):
        self.attach_double_not()
        report = self.run_comparison(structure=True)
        self.assertTrue(report['semantic_acceptance'])
        diagnosis = self.diagnoses()[0, 2]
        proof = diagnosis['canonical_differences'][0]
        self.assertFalse(proof['canonical_structures_equal'])
        self.assertEqual(proof['proof']['status'], 'proved_exhaustive_two_state_equality')
        self.assertEqual(proof['proof']['assignments'], 16)
        self.assertEqual(diagnosis['anchor_expression_proof']['status'], 'proved')
        position = proof['first_term_difference']['grh']['native_positions'][0]
        self.assertEqual(position['operation_id'], 1)
        self.assertEqual(position['consumer_chain']['edges'], [])
        boundary = proof['paired_boundary_premises'][0]
        self.assertEqual((boundary['grh_value_id'], boundary['gsim_node_id']), (1, 1))
        self.assertTrue(boundary['source_geometry_complete'])

    def test_real_counterexample_has_reproducible_inputs_and_native_slots(self):
        self.attach_double_not()
        for stage in range(5):
            self.frames['gsim'][stage]['structure']['nodes'][1]['assignTrees'][0]['root'] = 0
        report = self.run_comparison(structure=True)
        self.assertFalse(report['semantic_acceptance'])
        diagnosis = self.diagnoses()[0, 2]
        self.assertEqual(diagnosis['node_result'], {'status': 'different', 'reason': 'two_state_boundary_counterexample'})
        evidence = diagnosis['canonical_differences'][0]
        witness = evidence['counterexample']
        self.assertEqual(witness['inputs'], [{'source': ['native_anchor', 1, []], 'value': 0}])
        self.assertEqual((witness['grh_value'], witness['gsim_value']), (0, 15))
        first = evidence['first_term_difference']
        self.assertEqual(first['normalized_operand_path'], [0])
        grh = first['grh']['native_positions'][0]
        self.assertEqual((grh['operation_id'], grh['value_id']), (3, 4))
        self.assertEqual(grh['consumer_chain']['edges'][0]['operand_slot'], 0)
        native = first['gsim']['native_positions'][0]
        self.assertEqual((native['assignment_tree_ordinal'], native['expression_id']), (0, 1))
        self.assertEqual(native['consumer_chain']['edges'][0]['child_slot'], 0)

    def test_diagnosis_scopes_reused_expression_ids_by_assignment_ordinal(self):
        self.attach_double_not()
        for stage in range(5):
            middle = self.frames['gsim'][stage]['structure']['nodes'][1]
            tree = deepcopy(middle['assignTrees'][0])
            tree['root'] = 0
            middle['assignTrees'] = [middle['assignTrees'][0], None, tree]
        self.run_comparison(structure=True)
        evidence = self.diagnoses()[0, 2]['canonical_differences'][0]
        origins = evidence['first_term_difference']['gsim']['native_positions']
        actual = next(origin for origin in origins if origin['assignment_tree_ordinal'] == 2)
        self.assertEqual(actual['expression_id'], 1)
        self.assertEqual(actual['consumer_chain']['assignment_tree_ordinal'], 2)
        self.assertEqual(actual['consumer_chain']['edges'][0], {
            'source_expression_id': 1, 'consumer_expression_id': 0, 'child_slot': 0})

    def test_legacy_source_geometry_blocks_full_acceptance(self):
        self.attach_structure()
        for stage in range(5):
            self.frames['grh'][stage]['endpoint_schema'] = 'grh.semantic-node-endpoints.v1'
        report = self.run_comparison(structure=True)
        self.assertFalse(report['semantic_acceptance'])
        self.assertEqual(report['unproved_compared_pairs'], 0)
        self.assertEqual(report['incomplete_GRH_source_geometry_endpoint_rows'], 15)

    def test_source_geometry_joins_logical_node_across_physical_id_namespaces(self):
        self.attach_double_not()
        for frame in self.frames['grh']:
            frame['endpoints'] = {1: {'value_id': 101}}
        self.run_comparison(structure=True)
        boundary = self.diagnoses()[0, 2]['canonical_differences'][0]['paired_boundary_premises'][0]
        self.assertEqual(boundary['grh_value_id'], 1)
        self.assertTrue(boundary['source_geometry_complete'])
        self.assertEqual(boundary['source_binding_geometry']['join'], 'stable logical SemanticId only')
        with sqlite3.connect(self.work / 'comparison' / 'comparison.sqlite') as db:
            self.assertEqual(db.execute('SELECT value FROM endpoints WHERE stage=0 AND node=1').fetchone()[0], 101)

    def test_membership_detail_sampling_keeps_every_anchor_and_member_result(self):
        self.attach_structure()
        for stage in range(5):
            graph = self.frames['grh'][stage]['structure']['graphs'][0]
            graph['vals'].append({**graph['vals'][0], 'id': 99, 'in': False})
            graph['ops'].append({'id': 99, 'kind': 'grh.constant', 'in': [], 'out': [99], 'attrs': {'constValue': "8'b1"}})
            for identifier in range(4, 14):
                name = 'extra' + str(identifier)
                for engine in ('grh', 'gsim'):
                    self.frames[engine][stage]['nodes'].append((identifier, name))
                graph['vals'].append({**graph['vals'][0], 'id': identifier, 'in': False})
                graph['ops'].append({'id': identifier, 'kind': 'grh.assign', 'in': [1], 'out': [identifier], 'attrs': {}})
                graph['semanticTree']['nodes'].append({'id': identifier, 'parent': 1, 'name': name,
                                                      'ops': [identifier], 'anchors': [identifier]})
                native = deepcopy(self.frames['gsim'][stage]['structure']['nodes'][2])
                native.update(id=identifier, name=name, nodePath=[name])
                native['assignTrees'][0]['nodes'][1]['node'] = 'input'
                self.frames['gsim'][stage]['structure']['nodes'].append(native)
            for node in graph['semanticTree']['nodes'][1:]:
                node['ops'].append(99)
        report = self.run_comparison(structure=True)
        proof = report['boundaries']['P0']['structure']
        self.assertEqual(proof['native_diagnosis_rows'], 8)
        self.assertEqual(proof['separately_proved_anchors_with_uncovered_members'], 12)
        with sqlite3.connect(self.work / 'comparison' / 'comparison.sqlite') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM anchor_proofs').fetchone()[0], 60)
        with sqlite3.connect(self.work / 'comparison' / 'structure' / 'P0' / 'comparison.sqlite') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM disconnected_members').fetchone()[0], 12)

    def test_canonical_difference_above_bit_budget_stays_unverified(self):
        self.attach_double_not(13)
        report = self.run_comparison(structure=True)
        self.assertFalse(report['semantic_acceptance'])
        diagnosis = self.diagnoses()[0, 2]
        self.assertEqual(diagnosis['node_result'], {'status': 'unverified',
            'reason': 'nonidentical_expression_exceeds_exhaustive_bit_budget'})
        evidence = diagnosis['canonical_differences'][0]
        self.assertEqual(evidence['proof']['input_bits'], 13)
        self.assertNotIn('counterexample', evidence)

    def test_exhaustive_common_domain_proof_never_proves_four_state_behavior(self):
        self.attach_double_not(four_state=True)
        report = self.run_comparison(structure=True)
        self.assertFalse(report['semantic_acceptance'])
        self.assertFalse(report['four_state_behavior_proved'])
        self.assertEqual(report['boundaries']['P0']['structure']['common_two_state_domain']['expression_checked'], 2)
        self.assertEqual(report['common_domain_proof_nodes'], 15)
        self.assertEqual(self.diagnoses()[0, 2]['node_result']['status'], 'structural_checked')

    def test_disconnected_member_preserves_separate_anchor_proof(self):
        self.attach_structure()
        for stage in range(5):
            graph = self.frames['grh'][stage]['structure']['graphs'][0]
            graph['semanticTree']['nodes'][1]['ops'].append(99)
            graph['vals'].append({**graph['vals'][0], 'id': 99, 'in': False})
            graph['ops'].append({'id': 99, 'kind': 'grh.bitNot', 'in': [1], 'out': [99], 'attrs': {}})
        report = self.run_comparison(structure=True)
        self.assertFalse(report['semantic_acceptance'])
        self.assertEqual(report['boundaries']['P0']['structure']['separately_proved_anchors_with_uncovered_members'], 1)
        diagnosis = self.diagnoses()[0, 2]
        self.assertEqual(diagnosis['node_result']['status'], 'unverified')
        self.assertEqual(diagnosis['membership_coverage']['examples'][0]['operation_id'], 99)
        self.assertEqual(diagnosis['anchor_expression_proof']['status'], 'proved')
        self.assertFalse(diagnosis['anchor_expression_proof']['membership_coverage_proved'])
        self.assertEqual(diagnosis['anchor_expression_proof']['paired_boundary_premises'][0]['grh_node_id'], 1)
        with sqlite3.connect(self.work / 'comparison' / 'structure' / 'P0' / 'comparison.sqlite') as db:
            self.assertEqual(db.execute('SELECT * FROM disconnected_members').fetchall(), [(2, 99, 'grh.bitNot')])

    def test_both_sides_unsupported_never_become_equal(self):
        self.attach_structure(unsupported=True)
        report = self.run_comparison(structure=True)
        self.assertFalse(report['semantic_acceptance'])
        self.assertTrue(any(row['category'] == 'structure' and row['evidence']['proof_status'] == 'unverified'
                            for row in self.ledger()))

    def test_four_state_structure_is_not_behavior_proof(self):
        self.attach_structure(four_state=True)
        report = self.run_comparison(structure=True)
        self.assertFalse(report['semantic_acceptance'])
        self.assertFalse(report['four_state_behavior_proved'])
        self.assertGreater(report['boundaries']['P4']['structure']['counts']['structural_checked'], 0)
        common = report['boundaries']['P4']['structure']['common_two_state_domain']
        self.assertEqual((common['expression_checked'], common['interface_checked']), (2, 1))
        self.assertEqual(report['common_domain_proof_nodes'], 15)
        self.assertIn('0/1', common['premise'])

    def test_unknown_literal_is_not_assumed_zero_in_common_domain_proof(self):
        self.attach_structure(four_state=True)
        for stage in range(5):
            op = self.frames['grh'][stage]['structure']['graphs'][0]['ops'][0]
            op.update(kind='grh.constant', **{'in': [], 'attrs': {'constValue': "8'b0x1z10xz"}})
            tree = self.frames['gsim'][stage]['structure']['nodes'][1]['assignTrees'][0]
            tree['nodes'][0].update(op='OP_INT', children=[], strVal='0hxx')
        report = self.run_comparison(structure=True)
        common = report['boundaries']['P4']['structure']['common_two_state_domain']
        self.assertEqual(common['unproved_paired_nodes'], 1)
        self.assertFalse(report['semantic_acceptance'])

    def test_selected_limited_structure_is_resumable_and_never_passes_early(self):
        self.attach_structure()
        grh, gsim = self.write_capture('grh'), self.write_capture('gsim')
        output = self.work / 'comparison'
        partial = compare(grh, gsim, output, selected_stages={0}, node_limit=1)
        self.assertEqual(partial['boundaries']['P0']['structure']['status'], 'partial')
        self.assertEqual(partial['structurally_unprocessed_paired_nodes'], 14)
        self.assertFalse(partial['semantic_acceptance'])
        index = output / 'structure' / 'P0' / 'comparison.sqlite'
        indexed_at = index.stat().st_ino
        again = compare(grh, gsim, output, resume=True, selected_stages={0}, node_limit=1)
        self.assertEqual(again['boundaries']['P0']['structure']['compared_nodes'], 2)
        self.assertEqual(index.stat().st_ino, indexed_at)
        self.assertFalse(again['semantic_acceptance'])
        with patch('compare_f32_semantics.BATCH', 2):
            finished = compare(grh, gsim, output, resume=True)
        self.assertEqual(finished['structurally_unprocessed_paired_nodes'], 0)
        self.assertTrue(finished['semantic_acceptance'])
        with sqlite3.connect(output / 'comparison.sqlite') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM structural').fetchone()[0], 15)

    def test_inventory_only_index_can_resume_with_structure(self):
        self.attach_structure()
        grh, gsim = self.write_capture('grh'), self.write_capture('gsim')
        output = self.work / 'comparison'
        self.assertFalse(compare(grh, gsim, output, structure=False)['semantic_acceptance'])
        self.assertTrue(compare(grh, gsim, output, resume=True)['semantic_acceptance'])

    def test_resume_rejects_mutation_of_frozen_inventory(self):
        grh, gsim = self.write_capture('grh'), self.write_capture('gsim')
        output = self.work / 'comparison'
        compare(grh, gsim, output, structure=False)
        path = grh / 'P0' / 'nodes.tsv'
        path.write_text(path.read_text().replace('middle', 'changed'))
        with self.assertRaisesRegex(ValueError, 'changed since capture during resume'):
            compare(grh, gsim, output, resume=True)

    def test_unverified_groups_track_existing_and_new_nodes_at_P0(self):
        self.attach_structure(unsupported=True)
        for stage in range(2, 5):
            self.frames['grh'][stage]['structure']['graphs'][0]['ops'][1]['kind'] = 'kMystery'
            self.frames['gsim'][stage]['structure']['nodes'][2]['assignTrees'][0]['nodes'][0]['op'] = 'OP_MYSTERY'
            self.frames['gsim'][stage]['structure']['nodes'][2]['assignTrees'][0]['root'] = 0
        report = self.run_comparison(structure=True)
        group = next(row for row in report['boundaries']['P2']['structure']['results_by_reason']
                     if row['proof_status'] == 'unverified')
        self.assertEqual(group['affected_nodes'], 2)
        self.assertEqual(group['same_result_present_at_P0'], 1)
        self.assertEqual(group['not_present_with_same_result_at_P0'], 1)
        self.assertEqual(group['not_present_at_P0_examples'][0]['name'], 'out')
        ledger = next(row for row in self.ledger() if row['boundary'] == 'P2' and row['category'] == 'structure')
        self.assertEqual(ledger['aggregation_level'], 'proof-reason')
        self.assertEqual(ledger['new_node_results_since_P0'], 1)
        self.assertFalse(ledger['inherited_from_P0'])
        self.assertTrue(ledger['partially_inherited_from_P0'])
        self.assertEqual(report['new_unproved_node_results_since_P0'], 3)
        self.assertFalse(report['semantic_acceptance'])

    def test_inherited_unpaired_nodes_are_unproved_coverage(self):
        self.attach_structure()
        for stage in range(5):
            self.frames['grh'][stage]['nodes'].append((4, 'extra-input'))
            graph = self.frames['grh'][stage]['structure']['graphs'][0]
            graph['semanticTree']['nodes'].append({'id': 4, 'parent': 1, 'name': 'extra-input', 'ops': [], 'anchors': [4]})
            graph['vals'].append({'id': 4, 'w': 8, 'sgn': False, 'shape': [], 'type': 'logic', 'domain': '2state', 'in': True})
        report = self.run_comparison(structure=True)
        self.assertEqual(report['new_differences_not_present_at_P0'], 0)
        self.assertEqual(report['unpaired_native_nodes'], 5)
        self.assertFalse(report['semantic_acceptance'])

    def test_native_state_classes_are_aggregated_without_expression_claim(self):
        self.attach_structure()
        for stage in range(5):
            self.frames['gsim'][stage]['structure']['nodes'][1]['type'] = 'NODE_REG_SRC'
        report = self.run_comparison(structure=True)
        group = next(row for row in report['boundaries']['P4']['structure']['results_by_reason']
                     if row['reason'] == 'state_memory_effect_unverified')
        self.assertEqual(group['affected_nodes'], 1)
        self.assertEqual(group['same_result_present_at_P0'], 1)
        self.assertFalse(report['semantic_acceptance'])

    def test_identical_memory_record_overlap_is_read_without_inventing_nodes(self):
        self.attach_structure()
        for stage in range(5):
            native = self.frames['gsim'][stage]['structure']
            native['nodes'][1]['type'] = 'NODE_MEMORY'
            native['memories'].append(deepcopy(native['nodes'][1]))
        report = self.run_comparison(structure=True)
        self.assertEqual(report['boundaries']['P4']['structure']['compared_nodes'], 3)
        self.assertFalse(report['semantic_acceptance'])

    def test_conflicting_memory_record_overlap_is_rejected(self):
        self.attach_structure()
        native = self.frames['gsim'][0]['structure']
        native['memories'].append({**native['nodes'][1], 'width': 9})
        with self.assertRaisesRegex(ValueError, 'conflicting GSIM Node definitions'):
            self.run_comparison(structure=True)

    @unittest.skipUnless(os.environ.get('F32_GSIM_CAPTURE'), 'optional actual native GSIM capture integration')
    def test_actual_native_gsim_wrapper_five_boundaries(self):
        self.attach_structure()
        grh = self.work / 'grh-fixture.json'
        grh.write_text(json.dumps(self.frames['grh'][0]['structure'], indent=2) + '\n')
        captured = capture(Path(os.environ['F32_GSIM_CAPTURE']), 'gsim')
        db = database(self.work / 'native-inventory.sqlite')
        try:
            run = None
            for stage in range(5):
                record = captured['snapshots'][f'P{stage}']
                checked = ingest_snapshot(db, 'gsim', stage, record, run, captured['input_sha256'])
                run = checked['run_id']
                output = self.work / f'native-index-P{stage}'
                output.mkdir()
                local, _ = structure_index(grh, Path(record['structure']), output)
                try:
                    actual = local.execute('SELECT count(*) FROM gs_nodes').fetchone()[0]
                    self.assertEqual(actual, checked['nodes'])
                    for identifier, in db.execute("SELECT id FROM inventory WHERE engine='gsim' AND stage=?", (stage,)):
                        self.assertIsNotNone(local.execute('SELECT id FROM gs_nodes WHERE id=?', (identifier,)).fetchone())
                finally:
                    local.close()
        finally:
            db.close()

    @unittest.skipUnless(os.environ.get('F32_GSIM_STRUCTURE'), 'optional actual native GSIM partial assignment integration')
    def test_actual_native_null_slots_and_ordered_partial_assignments(self):
        native = Path(os.environ['F32_GSIM_STRUCTURE'])
        fixture = {'graphs': [{'symbol': 'top', 'semanticTree': {
            'rootPath': 1, 'namesFlattened': True, 'paths': [{'id': 1, 'parent': 0}],
            'nodes': [{'id': identifier, 'parent': 1, 'name': name, 'ops': [], 'anchors': [identifier]}
                      for identifier, name in ((10, 'c0'), (11, 'c1'), (12, 'a'), (13, 'b'))]},
            'vals': [{'id': identifier, 'w': 1 if identifier < 12 else 8, 'sgn': False,
                      'shape': [], 'type': 'logic', 'domain': '2state', 'in': True} for identifier in range(10, 14)],
            'ops': []}]}
        grh = self.work / 'grh-fixture.json'
        grh.write_text(json.dumps(fixture, indent=2) + '\n')
        output = self.work / 'native-partial-index'
        output.mkdir()
        db, counts = structure_index(grh, native, output)
        try:
            self.assertIn(counts.get('gsim_repeated_memory_records', 0), (0, 1))
            with db:
                db.executemany('INSERT INTO pairs VALUES(?,?,?)', [(i, i, str(i)) for i in range(10, 14)])
            checker = F32Subgraphs(db)
            checker.native_root_id, checker.four_state = 14, False
            destination = checker.native(14)
            prior, typ = source('prior', BVType(8)), BVType(8)
            trees = destination['assignTrees']
            for ordinal, tree in enumerate(trees):
                entries = {item['id']: item for item in tree['nodes']}
                actual = checker.native_assignment(entries, tree['root'], typ, (), prior)
                condition = source(('native_anchor', 10 + ordinal, ()), BVType(1))
                payload = source(('native_anchor', 12 + ordinal, ()), typ)
                self.assertEqual(actual, mux(condition, payload if ordinal == 0 else prior,
                                              prior if ordinal == 0 else payload, typ))
            with self.assertRaisesRegex(Unverified, 'partial_GSIM_assignment_without_prior_value'):
                checker.native_root(destination, typ, ())
        finally:
            db.close()


class OrderedArrayFixture(unittest.TestCase):
    """Exercise both engines' actual array write layouts, not inventory names."""
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.executescript('''
            CREATE TABLE values_ir(id INTEGER PRIMARY KEY,payload TEXT);
            CREATE TABLE ops(id INTEGER PRIMARY KEY,payload TEXT);
            CREATE TABLE producers(value INTEGER PRIMARY KEY,op INTEGER);
            CREATE TABLE members(node INTEGER,op INTEGER);
            CREATE TABLE anchors(node INTEGER,value INTEGER);
            CREATE TABLE pairs(grh INTEGER,gsim INTEGER,name TEXT);
            CREATE TABLE gs_nodes(id INTEGER PRIMARY KEY,name TEXT,native_name TEXT,inventory TEXT,payload TEXT);
            CREATE TABLE disconnected_members(node INTEGER,op INTEGER,kind TEXT,PRIMARY KEY(node,op));
            CREATE TABLE native_type_evidence(id INTEGER PRIMARY KEY,width INTEGER,signed INTEGER,shape TEXT,evidence TEXT);
            CREATE TABLE state_declarations(symbol TEXT,op INTEGER PRIMARY KEY);
            CREATE TABLE state_ports(symbol TEXT,op INTEGER PRIMARY KEY);
        ''')
        self.checker = F32Subgraphs(self.db)
        self.checker.native_root_id = 100
        self.checker.four_state = False

    def tearDown(self):
        self.db.close()

    @staticmethod
    def expression(op, *children, width=8, **kwargs):
        return {'op': op, 'width': width, 'sign': False, 'children': list(children), **kwargs}

    def ref(self, name, width=8):
        return self.expression('OP_EMPTY', width=width, node=name)

    def tree(self, rhs, *indices):
        entries = []
        def flatten(expr):
            if expr is None:
                return None
            identifier = len(entries)
            entry = {**expr, 'id': identifier}
            entries.append(entry)
            entry['children'] = [flatten(child) for child in expr.get('children', [])]
            return identifier
        root = flatten(rhs)
        lvalue = flatten(self.expression('OP_EMPTY', *indices, node='out'))
        return {'root': root, 'lvalue': lvalue, 'nodes': entries}

    def input(self, identifier, name, *, width=8, shape=()):
        size = width
        for extent in shape:
            size *= extent
        value = {'id': identifier, 'w': size, 'sgn': False, 'shape': list(shape),
                 'type': 'logic', 'domain': '2state', 'in': True}
        native = {'id': identifier, 'name': name, 'type': 'NODE_INP', 'width': width,
                  'sign': False, 'dimension': list(shape), 'assignTrees': []}
        self.db.execute('INSERT INTO values_ir VALUES(?,?)', (identifier, compact(value)))
        self.db.execute('INSERT INTO gs_nodes VALUES(?,?,?,?,?)',
                        (identifier, name, name, 'nodes', compact(native)))
        self.db.execute('INSERT INTO anchors VALUES(?,?)', (identifier, identifier))
        self.db.execute('INSERT INTO pairs VALUES(?,?,?)', (identifier, identifier, name))

    def output(self, args, counts, trees, *, shape=(2,)):
        size = 8
        for extent in shape:
            size *= extent
        self.db.execute('INSERT INTO values_ir VALUES(?,?)', (100, compact(
            {'id': 100, 'w': size, 'sgn': False, 'shape': list(shape), 'type': 'logic', 'domain': '2state'})))
        self.db.execute('INSERT INTO ops VALUES(?,?)', (100, compact(
            {'id': 100, 'kind': 'grh.combArrayUpdate', 'in': args, 'out': [100], 'attrs': {'indexCounts': counts}})))
        self.db.execute('INSERT INTO producers VALUES(?,?)', (100, 100))
        self.db.execute('INSERT INTO members VALUES(?,?)', (100, 100))
        self.db.execute('INSERT INTO anchors VALUES(?,?)', (100, 100))
        self.db.execute('INSERT INTO gs_nodes VALUES(?,?,?,?,?)', (100, 'out', 'out', 'nodes', compact(
            {'id': 100, 'name': 'out', 'type': 'NODE_OTHERS', 'width': 8, 'sign': False,
             'dimension': list(shape), 'assignTrees': trees})))
        return self.checker.compare(100, 100)

    def ordinary_inputs(self, shape=(2,)):
        self.input(1, 'base', shape=shape)
        self.input(2, 'payload')
        self.input(3, 'enable', width=1)
        self.input(4, 'address', width=2)

    def guarded_write(self, payload='payload', *, absent_true=False, addresses=True):
        value = self.ref(payload)
        rhs = self.expression('OP_WHEN', self.ref('enable', 1),
                              None if absent_true else value, value if absent_true else None)
        indices = [self.expression('OP_INDEX', self.ref('address', 2), width=2)] if addresses else []
        return self.tree(rhs, *indices)


class OrderedArrayExpressionTests(OrderedArrayFixture):
    def test_dynamic_write_matches_ordered_guarded_assignment(self):
        self.ordinary_inputs()
        status, _ = self.output([1, 3, 4, 2], [1],
                                [self.tree(self.ref('base')), self.guarded_write()])
        self.assertEqual(status, 'expression_checked')

    def test_ordered_overwrites_preserve_last_writer(self):
        self.ordinary_inputs()
        self.input(5, 'later')
        status, _ = self.output([1, 3, 4, 2, 3, 4, 5], [1, 1],
            [self.tree(self.ref('base')), self.guarded_write(), self.guarded_write('later')])
        self.assertEqual(status, 'expression_checked')

    def test_reversing_native_write_order_requires_a_behavior_proof(self):
        self.ordinary_inputs()
        self.input(5, 'later')
        status, reason = self.output([1, 3, 4, 2, 3, 4, 5], [1, 1],
            [self.tree(self.ref('base')), self.guarded_write('later'), self.guarded_write()])
        self.assertEqual((status, reason), ('unverified', 'nonidentical_expression_exceeds_exhaustive_bit_budget'))
        self.assertFalse(self.checker.last_diagnosis['canonical_differences'][0]['canonical_structures_equal'])

    def test_partial_multidimensional_write_keeps_remaining_axes(self):
        self.ordinary_inputs((2, 3))
        self.input(6, 'row', shape=(3,))
        status, _ = self.output([1, 3, 4, 6], [1],
            [self.tree(self.ref('base')), self.guarded_write('row')], shape=(2, 3))
        self.assertEqual(status, 'expression_checked')

    def test_whole_array_write_uses_zero_indices(self):
        self.ordinary_inputs()
        self.input(6, 'replacement', shape=(2,))
        status, _ = self.output([1, 3, 6], [0],
            [self.tree(self.ref('base')), self.guarded_write('replacement', addresses=False)])
        self.assertEqual(status, 'expression_checked')

    def test_null_assignment_tree_slot_preserves_native_order(self):
        self.ordinary_inputs()
        status, _ = self.output([1, 3, 4, 2], [1],
            [None, self.tree(self.ref('base')), None, self.guarded_write(), None])
        self.assertEqual(status, 'expression_checked')

    def test_static_out_of_bounds_write_preserves_base(self):
        self.ordinary_inputs()
        self.input(6, 'outside', width=2)
        # Native index 3 cannot select either member of a two-element array.
        self.db.execute('DELETE FROM values_ir WHERE id=6')
        self.db.execute('INSERT INTO values_ir VALUES(?,?)', (6, compact(
            {'id': 6, 'w': 2, 'sgn': False, 'shape': [], 'type': 'logic', 'domain': '2state'})))
        self.db.execute('INSERT INTO ops VALUES(?,?)', (6, compact(
            {'id': 6, 'kind': 'grh.constant', 'in': [], 'out': [6], 'attrs': {'constValue': "2'h3"}})))
        self.db.execute('INSERT INTO producers VALUES(?,?)', (6, 6))
        self.db.execute('INSERT INTO members VALUES(?,?)', (100, 6))
        static = self.tree(self.ref('payload'), self.expression('OP_INDEX_INT', width=2, values=[3]))
        status, _ = self.output([1, 3, 6, 2], [1], [self.tree(self.ref('base')), static])
        self.assertEqual(status, 'expression_checked')

    def test_null_true_and_false_slots_retain_distinct_semantics(self):
        self.ordinary_inputs()
        typ = BVType(8)
        prior = source('prior', typ)
        condition = source(('native_anchor', 3, ()), BVType(1))
        payload = source(('native_anchor', 2, ()), typ)
        for absent_true in (False, True):
            tree = self.guarded_write(absent_true=absent_true, addresses=False)
            entries = {entry['id']: entry for entry in tree['nodes']}
            actual = self.checker.native_assignment(entries, tree['root'], typ, (), prior)
            expected = mux(condition, prior if absent_true else payload,
                           payload if absent_true else prior, typ)
            self.assertEqual(actual, expected)

    def test_old_dump_missing_null_slot_remains_unverified(self):
        self.ordinary_inputs()
        tree = self.guarded_write()
        tree['nodes'][tree['root']]['children'].pop()
        status, reason = self.output([1, 3, 4, 2], [1], [self.tree(self.ref('base')), tree])
        self.assertEqual((status, reason), ('unverified', 'partial_when_dump_lost_original_branch_slots'))

    def test_initial_dynamic_write_without_prior_is_unverified(self):
        self.ordinary_inputs()
        status, reason = self.output([1, 3, 4, 2], [1], [self.guarded_write()])
        self.assertEqual((status, reason), ('unverified', 'partial_GSIM_assignment_without_prior_value'))

    def test_malformed_update_layout_is_unverified(self):
        self.ordinary_inputs()
        status, reason = self.output([1, 3, 4, 2], [0], [self.tree(self.ref('base'))])
        self.assertEqual((status, reason), ('unverified', 'invalid_array_update_group_layout'))


class NativeExpressionStageTests(OrderedArrayFixture):
    @unittest.skipUnless(os.environ.get('F32_GSIM_NATIVE_EXAMPLES'), 'optional actual native HEAD/TAIL/DSHR records')
    def test_actual_native_inferred_head_tail_and_shift_records(self):
        directory = Path(os.environ['F32_GSIM_NATIVE_EXAMPLES'])
        values = {'OP_HEAD': [0xFEDCBA9876543210], 'OP_TAIL': [0x1B], 'OP_DSHR': [0x87654321, 7]}
        expected = {'OP_HEAD': 0xFEDCBA987654, 'OP_TAIL': 0xB, 'OP_DSHR': 0x87654321 >> 7}
        for operation in values:
            with self.subTest(operation=operation):
                native = json.loads((directory / (operation + '.node.json')).read_text())
                tree = native['assignTrees'][0]
                entries = {entry['id']: entry for entry in tree['nodes']}
                root = entries[tree['root']]
                self.assertEqual(root['op'], operation)
                self.assertGreater(native['order'], 0)
                self.assertGreaterEqual(native['orderInSuper'], 0)
                inputs = {}
                for eid, value in zip(root['children'], values[operation]):
                    child = entries[eid]
                    self.input(child['nodeId'], child['node'], width=child['width'])
                    inputs['native_anchor', child['nodeId'], ()] = value
                term = self.checker.native_root(native, BVType(native['width'], bool(native['sign'])), ())
                self.assertEqual(evaluate(term, inputs), expected[operation])

    def native_term(self, rhs, *, scheduled=True):
        native = {'assignTrees': [self.tree(rhs)]}
        if scheduled:
            native.update(order=5, orderInSuper=0)
        return self.checker.native_root(native, BVType(rhs['width'], rhs.get('sign', False)), ())

    def test_head_uses_post_inference_low_bit_offset(self):
        self.input(1, 'data', width=16)
        term = self.native_term(self.expression('OP_HEAD', self.ref('data', 16), width=4, values=[12]))
        self.assertEqual(evaluate(term, {('native_anchor', 1, ()): 0xABCD}), 0xA)

    def test_tail_retained_width_can_exceed_used_result_width(self):
        self.input(1, 'data', width=16)
        term = self.native_term(self.expression('OP_TAIL', self.ref('data', 16), width=8, values=[12]))
        self.assertEqual(evaluate(term, {('native_anchor', 1, ()): 0xABCD}), 0xCD)

    def test_unscheduled_head_tail_parameters_are_not_guessed(self):
        self.input(1, 'data', width=16)
        for operation in ('OP_HEAD', 'OP_TAIL'):
            with self.subTest(operation=operation), self.assertRaisesRegex(Unverified, 'native_head_tail_stage_unproved'):
                self.native_term(self.expression(operation, self.ref('data', 16), width=8, values=[8]), scheduled=False)

    def test_dynamic_right_shift_preserves_high_operand_bits_before_truncation(self):
        self.input(1, 'data', width=16)
        self.input(2, 'amount', width=4)
        term = self.native_term(self.expression('OP_DSHR', self.ref('data', 16), self.ref('amount', 4), width=8))
        self.assertEqual(evaluate(term, {('native_anchor', 1, ()): 0x0100, ('native_anchor', 2, ()): 8}), 1)

    def test_dynamic_arithmetic_right_shift_preserves_signed_operand_width(self):
        self.input(1, 'data', width=16)
        self.input(2, 'amount', width=5)
        value = json.loads(self.db.execute('SELECT payload FROM values_ir WHERE id=1').fetchone()[0])
        value['sgn'] = True
        self.db.execute('UPDATE values_ir SET payload=? WHERE id=1', (compact(value),))
        native = json.loads(self.db.execute('SELECT payload FROM gs_nodes WHERE id=1').fetchone()[0])
        native['sign'] = True
        self.db.execute('UPDATE gs_nodes SET payload=? WHERE id=1', (compact(native),))
        term = self.native_term(self.expression('OP_DSHR', {**self.ref('data', 16), 'sign': True},
            self.ref('amount', 5), width=8, sign=True))
        self.assertEqual(evaluate(term, {('native_anchor', 1, ()): 0xFF00, ('native_anchor', 2, ()): 8}), 0xFF)
        self.assertEqual(evaluate(term, {('native_anchor', 1, ()): 0xFF00, ('native_anchor', 2, ()): 16}), 0xFF)

    def test_wide_clock_and_async_reset_casts_reduce_all_bits(self):
        self.input(1, 'data', width=16)
        for operation in ('OP_ASCLOCK', 'OP_ASASYNCRESET'):
            with self.subTest(operation=operation):
                term = self.native_term(self.expression(operation, self.ref('data', 16), width=1))
                self.assertEqual(evaluate(term, {('native_anchor', 1, ()): 0x0100}), 1)
                self.assertEqual(evaluate(term, {('native_anchor', 1, ()): 0}), 0)


class ScalarStateTransferTests(OrderedArrayFixture):
    def fixture(self, *, reset=False, masked=False):
        self.input(1, 'clock', width=1)
        self.input(2, 'enable', width=1)
        self.input(3, 'data')
        self.input(4, 'reset', width=1)
        self.input(5, 'resetValue')
        self.input(6, 'mask')
        clock = json.loads(self.db.execute('SELECT payload FROM gs_nodes WHERE id=1').fetchone()[0])
        clock['isClock'] = True
        self.db.execute('UPDATE gs_nodes SET payload=? WHERE id=1', (compact(clock),))
        current = {'id': 100, 'w': 8, 'sgn': False, 'shape': [], 'type': 'logic', 'domain': '4state'}
        self.db.execute('INSERT INTO values_ir VALUES(?,?)', (100, compact(current)))
        self.db.execute('INSERT INTO anchors VALUES(?,?)', (100, 100))
        self.db.executemany('INSERT INTO pairs VALUES(?,?,?)', ((100, 100, 'state'), (101, 101, 'state$NEXT')))
        declaration = {'id': 1000, 'sym': 'state', 'kind': 'grh.registerDecl', 'in': [], 'out': [], 'attrs': {
            'width': 8, 'isSigned': False, 'initSpecKinds': ['const'], 'initSpecValues': ["8'bx"]}}
        self.db.execute('INSERT INTO ops VALUES(?,?)', (1000, compact(declaration)))
        self.db.execute('INSERT INTO state_declarations VALUES(?,?)', ('state', 1000))
        self.db.execute('INSERT INTO members VALUES(?,?)', (100, 1000))
        self.op(1001, 'grh.registerReadPort', [], [100], {'regSymbol': 'state'}, owner=100)
        self.db.execute('INSERT INTO state_ports VALUES(?,?)', ('state', 1001))
        enabled = 2
        if reset:
            self.value(7, 1)
            self.op(1002, 'grh.bitNot', [4], [7])
            self.value(8, 1)
            self.op(1003, 'grh.bitAnd', [7, 2], [8])
            enabled = 8
        args = [enabled, 3, 6, 1] if masked else [enabled, 3, 1]
        self.op(1010, 'grh.registerWriteMaskPort' if masked else 'grh.registerWritePort', args, [],
                {'regSymbol': 'state', 'eventEdge': ['posedge'], 'writerOrder': 0})
        self.db.execute('INSERT INTO state_ports VALUES(?,?)', ('state', 1010))
        if reset:
            self.op(1011, 'grh.registerWritePort', [4, 5, 1], [],
                {'regSymbol': 'state', 'eventEdge': ['posedge'], 'writerOrder': 1})
            self.db.execute('INSERT INTO state_ports VALUES(?,?)', ('state', 1011))
        q, payload = self.ref('state'), self.ref('data')
        if masked:
            payload = self.expression('OP_OR', self.expression('OP_AND', q,
                self.expression('OP_NOT', self.ref('mask'))),
                self.expression('OP_AND', self.ref('data'), self.ref('mask')))
        rhs = self.expression('OP_MUX', self.ref('enable', 1), payload, q)
        following = {'id': 101, 'name': 'next', 'type': 'NODE_REG_DST', 'width': 8, 'sign': False,
            'dimension': [], 'clockId': 1, 'regNextId': 100, 'regSourceId': 100, 'regDestinationId': 101,
            'assignTrees': [self.tree(rhs)]}
        current = {'id': 100, 'name': 'state', 'type': 'NODE_REG_SRC', 'width': 8, 'sign': False,
            'dimension': [], 'clockId': 1, 'regNextId': 101, 'regSourceId': 100, 'regDestinationId': 101,
            'reset': 2 if reset else 3, 'assignTrees': [self.tree(self.ref('next'))], 'resetTree': None,
            'resetCond': self.tree(self.ref('reset', 1) if reset else self.expression('OP_INT', width=1, strVal='0')),
            'resetVal': self.tree(self.ref('resetValue')) if reset else self.tree(q)}
        if reset:
            current['resetTree'] = self.tree(self.expression('OP_RESET', self.ref('reset', 1), self.ref('resetValue')))
        for node in (current, following):
            for tree in node['assignTrees']:
                tree['nodes'][tree['lvalue']]['node'] = node['name']
            self.db.execute('INSERT INTO gs_nodes VALUES(?,?,?,?,?)',
                (node['id'], node['name'], node['name'], 'nodes', compact(node)))
        self.checker = F32StateSubgraphs(self.db)

    def value(self, identifier, width):
        self.db.execute('INSERT INTO values_ir VALUES(?,?)', (identifier, compact(
            {'id': identifier, 'w': width, 'sgn': False, 'shape': [], 'type': 'logic', 'domain': '4state'})))

    def op(self, identifier, kind, args, outputs, attrs=None, owner=101):
        self.db.execute('INSERT INTO ops VALUES(?,?)', (identifier, compact(
            {'id': identifier, 'kind': kind, 'in': args, 'out': outputs, 'attrs': attrs or {}})))
        self.db.execute('INSERT INTO members VALUES(?,?)', (owner, identifier))
        for value in outputs:
            self.db.execute('INSERT INTO producers VALUES(?,?)', (value, identifier))

    def test_sampled_transfer_includes_hold_and_does_not_claim_initial_state(self):
        self.fixture()
        for identifier in (100, 101):
            status, _, evidence = self.checker.compare_transfer(identifier, identifier)
            self.assertEqual(status, 'common_posedge_transfer_checked')
            self.assertEqual(evidence['initialization_status'], 'unverified')
            self.assertEqual(evidence['grh_initialization']['initSpecValues'], ["8'bx"])
            self.assertFalse(evidence['full_four_state_state_equivalence'])

    def test_zero_reset_policy_survives_missing_split_origin_slots(self):
        self.fixture()
        current = json.loads(self.db.execute('SELECT payload FROM gs_nodes WHERE id=100').fetchone()[0])
        current.update(resetCond=None, resetVal=None, resetTree=None)
        following = json.loads(self.db.execute('SELECT payload FROM gs_nodes WHERE id=101').fetchone()[0])
        following['reset'] = 2
        for node in (current, following):
            self.db.execute('UPDATE gs_nodes SET payload=? WHERE id=?', (compact(node), node['id']))
        for identifier in (100, 101):
            status, _, evidence = self.checker.compare_transfer(identifier, identifier)
            self.assertEqual(status, 'common_posedge_transfer_checked')
            self.assertEqual(evidence['initialization_status'], 'unverified')
            self.assertEqual(evidence['grh_initialization']['initSpecValues'], ["8'bx"])
            policy = evidence['native_reset_policy']
            self.assertEqual(policy['current_reset_class'], 3)
            self.assertEqual(policy['operative_reset_tree'], 'explicit null')
            self.assertFalse(policy['next_reset_class_used'])
            self.assertFalse(policy['initial_state_inferred'])

    def test_zero_reset_requires_explicit_policy_and_consistent_operative_slot(self):
        self.fixture()
        original = json.loads(self.db.execute('SELECT payload FROM gs_nodes WHERE id=100').fetchone()[0])
        original.update(resetCond=None, resetVal=None)
        cases = [(None, 'reset', 'native_reset_class_unresolved'),
                 ({'reset': 0}, None, 'native_reset_class_unresolved'),
                 ({'reset': False}, None, 'native_reset_class_unresolved'),
                 (None, 'resetTree', 'native_zero_reset_tree_slot_not_captured'),
                 ({'resetTree': self.tree(self.expression('OP_RESET', self.ref('reset', 1), self.ref('data')))},
                  None, 'zero_reset_class_has_nonzero_or_unproved_reset'),
                 ({'resetCond': self.tree(self.expression('OP_INT', width=1, strVal='1'))},
                  None, 'zero_reset_class_has_nonzero_or_unproved_reset')]
        for overrides, removed, reason in cases:
            with self.subTest(overrides=overrides, removed=removed):
                current = deepcopy(original)
                if overrides:
                    current.update(overrides)
                if removed:
                    del current[removed]
                self.db.execute('UPDATE gs_nodes SET payload=? WHERE id=100', (compact(current),))
                checker = F32StateSubgraphs(self.db)
                self.assertEqual(checker.compare_transfer(100, 100)[:2], ('unverified', reason))

    def test_synchronous_reset_uses_operative_tree_when_origin_slots_are_absent(self):
        self.fixture(reset=True)
        current = json.loads(self.db.execute('SELECT payload FROM gs_nodes WHERE id=100').fetchone()[0])
        current.update(resetCond=None, resetVal=None)
        self.db.execute('UPDATE gs_nodes SET payload=? WHERE id=100', (compact(current),))
        status, _, evidence = self.checker.compare_transfer(100, 100)
        self.assertEqual(status, 'common_posedge_transfer_checked')
        self.assertEqual(evidence['initialization_status'], 'unverified')
        self.assertEqual(evidence['native_reset_policy']['operative_reset_tree'], 'captured OP_RESET')
        self.assertFalse(evidence['native_reset_policy']['next_reset_class_used'])
        current['resetTree'] = None
        self.db.execute('UPDATE gs_nodes SET payload=? WHERE id=100', (compact(current),))
        self.assertEqual(F32StateSubgraphs(self.db).compare_transfer(100, 100)[:2],
                         ('unverified', 'native_synchronous_reset_tree_missing'))

    def test_synchronous_reset_priority_matches_native_reset_overlay(self):
        self.fixture(reset=True)
        status, _, evidence = self.checker.compare_transfer(100, 100)
        self.assertEqual(status, 'common_posedge_transfer_checked')
        self.assertIn('synchronous', evidence['reset_timing'])

    def test_mask_preserves_old_unwritten_bits(self):
        self.fixture(masked=True)
        self.assertEqual(self.checker.compare_transfer(100, 100)[0], 'common_posedge_transfer_checked')

    def test_all_writer_rhs_read_old_state_instead_of_intermediate_update(self):
        self.fixture()
        self.value(7, 8)
        self.op(1002, 'grh.bitNot', [100], [7])
        operation = json.loads(self.db.execute('SELECT payload FROM ops WHERE id=1010').fetchone()[0])
        operation['in'][1] = 7
        self.db.execute('UPDATE ops SET payload=? WHERE id=1010', (compact(operation),))
        self.op(1011, 'grh.registerWritePort', [2, 7, 1], [],
                {'regSymbol': 'state', 'eventEdge': ['posedge'], 'writerOrder': 1})
        self.db.execute('INSERT INTO state_ports VALUES(?,?)', ('state', 1011))
        native = json.loads(self.db.execute('SELECT payload FROM gs_nodes WHERE id=101').fetchone()[0])
        native['assignTrees'] = [self.tree(self.expression('OP_MUX', self.ref('enable', 1),
            self.expression('OP_NOT', self.ref('state')), self.ref('state')))]
        tree = native['assignTrees'][0]
        tree['nodes'][tree['lvalue']]['node'] = 'next'
        self.db.execute('UPDATE gs_nodes SET payload=? WHERE id=101', (compact(native),))
        self.assertEqual(self.checker.compare_transfer(100, 100)[0], 'common_posedge_transfer_checked')

    def test_clock_requires_exact_identity_mapping(self):
        self.fixture()
        self.db.execute('DELETE FROM pairs WHERE gsim=1')
        self.assertEqual(self.checker.compare_transfer(100, 100)[1], 'state_clock_lacks_exact_paired_boundary')

    def test_nonposedge_edge_remains_unverified(self):
        self.fixture()
        operation = json.loads(self.db.execute('SELECT payload FROM ops WHERE id=1010').fetchone()[0])
        operation['attrs']['eventEdge'] = ['negedge']
        self.db.execute('UPDATE ops SET payload=? WHERE id=1010', (compact(operation),))
        self.assertEqual(self.checker.compare_transfer(100, 100)[1],
                         'state_requires_one_posedge_clock_without_other_events')

    def test_async_reset_cannot_be_proved_by_clock_sample_alone(self):
        self.fixture(reset=True)
        native = json.loads(self.db.execute('SELECT payload FROM gs_nodes WHERE id=100').fetchone()[0])
        native['reset'] = 1
        self.db.execute('UPDATE gs_nodes SET payload=? WHERE id=100', (compact(native),))
        self.assertEqual(self.checker.compare_transfer(100, 100)[1], 'asynchronous_reset_assertion_step_unverified')

    def test_reversed_reset_writer_priority_is_not_accepted(self):
        self.fixture(reset=True)
        op = json.loads(self.db.execute('SELECT payload FROM ops WHERE id=1010').fetchone()[0])
        op['in'][0] = 2
        op['attrs']['writerOrder'] = 2
        self.db.execute('UPDATE ops SET payload=? WHERE id=1010', (compact(op),))
        self.assertEqual(self.checker.compare_transfer(100, 100)[1], 'state_transition_expressions_not_proved_equal')

    def test_native_sample_and_reset_tree_are_checked_beyond_dst_expression(self):
        self.fixture(reset=True)
        native = json.loads(self.db.execute('SELECT payload FROM gs_nodes WHERE id=100').fetchone()[0])
        native['resetTree']['nodes'][native['resetTree']['root']]['children'].reverse()
        self.db.execute('UPDATE gs_nodes SET payload=? WHERE id=100', (compact(native),))
        self.assertEqual(self.checker.compare_transfer(100, 100)[1],
                         'native_reset_tree_disagrees_with_captured_reset_slots')


if __name__ == '__main__':
    unittest.main()
