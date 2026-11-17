"""Bounded native-origin audits never replace transformation certificates."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from audit_f32_window_origins import MAX_LINEAGE_DEPTH, ROOT, TABLES, analyze, audit


class WindowOriginTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get('F32_ORIGIN_TEST_ROOT', ROOT / 'ptmp/firrtl-ingest/F32/origin-contract-tmp'))
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.comparison = self.work / 'comparison'
        self.comparison.mkdir()
        self.tables = {table: [] for table in TABLES}
        self.summary = {'schema': 'wolvrix.f32.semantic-comparison.v1', 'status': 'analyzed',
            'complete': True, 'semantic_acceptance': False, 'input_sha256': 'a' * 64,
            'snapshots': {engine: {f'P{i}': {'run_id': engine + '-run',
                'snapshot_id': engine + '-snapshot-' + str(i), 'nodes': 0}
                for i in range(5)} for engine in ('grh', 'gsim')}}
        for engine in ('grh', 'gsim'):
            for stage in range(5):
                self.node(engine, stage, 1, 'source', 8)
                self.node(engine, stage, 2, 'out', 8)
        for stage in range(5):
            for identifier, name in ((1, 'source'), (2, 'out')):
                self.tables['pairs'].append((stage, identifier, identifier, name))

    def node(self, engine, stage, identifier, name, width, shape=None, binding=True):
        self.tables['inventory'].append((engine, stage, identifier, name, json.dumps([name]), name))
        typ = json.dumps([width, False, shape or []])
        if engine == 'grh':
            payload = {'source_geometry_schema': 'grh.semantic-node-endpoints.v2',
                'source_geometry_complete': True, 'source_width': str(width),
                'source_signed': 'false', 'logic_domain': '4state',
                'source_bit_offset': '0', 'source_bit_width': '-1',
                'source_shape_json': json.dumps(shape or []), 'source_shape_field_depths_json': '[]',
                'projection_json': '[]'}
            self.tables['endpoints'].append((stage, identifier, identifier, identifier, 'value', typ,
                '4state', 'native-binding' if binding else 'anchor-candidate', json.dumps(payload)))
        else:
            self.tables['details'].append((stage, identifier, typ, 'NODE_OTHERS', None, None, '{}'))

    def projection(self, engine, parent, child, low, width, *, stage=3, name=None):
        for current in range(stage, 5):
            self.node(engine, current, child, name or 'part-' + str(child), width)
            self.tables['slices'].append((engine, current, parent, child, low, width))

    def write(self):
        database = self.comparison / 'comparison.sqlite'
        if database.exists():
            database.unlink()
        with closing(sqlite3.connect(database)) as db:
            for table, columns in TABLES.items():
                db.execute('CREATE TABLE ' + table + '(' + ','.join(columns) + ')')
                db.executemany('INSERT INTO ' + table + ' VALUES(' + ','.join('?' for _ in columns) + ')',
                               self.tables[table])
            db.commit()
        for engine in ('grh', 'gsim'):
            for stage in range(5):
                self.summary['snapshots'][engine][f'P{stage}']['nodes'] = sum(
                    row[0] == engine and row[1] == stage for row in self.tables['inventory'])
        (self.comparison / 'summary.json').write_text(json.dumps(self.summary) + '\n')

    def run_audit(self, **options):
        self.write()
        output = self.work / 'audit'
        report = audit(self.comparison, output, **options)
        origins = [json.loads(line) for line in (output / 'origins.jsonl').read_text().splitlines()]
        obligations = [json.loads(line) for line in (output / 'window_obligations.jsonl').read_text().splitlines()]
        return report, {(row['engine'], row['stage'], row['node_id']): row for row in origins}, obligations

    def test_surviving_identity_is_not_a_semantic_certificate_even_if_upstream_gate_true(self):
        self.summary['semantic_acceptance'] = True
        report, origins, obligations = self.run_audit()
        self.assertTrue(report['upstream_semantic_acceptance'])
        self.assertFalse(report['window_acceptance'])
        self.assertEqual(report['semantic_transformation_certificates_checked'], 0)
        self.assertFalse(report['certificate_ingestion_implemented'])
        self.assertFalse(report['obligations_are_error_count'])
        self.assertFalse(report['memory_model']['production_scale_validated'])
        self.assertIn('endpoints', report['memory_model']['resident'])
        self.assertEqual(origins['grh', 'P4', 2]['classification'], 'unchanged-identity')
        self.assertFalse(origins['grh', 'P4', 2]['semantic_preservation_proved'])
        self.assertTrue(any(row['kind'] == 'semantic-transformation-certificate-missing' for row in obligations))

    def test_native_projection_and_composed_projection_use_real_ids_not_name_suffix(self):
        self.projection('grh', 2, 10, 2, 4, name='unrelated-spelling')
        self.projection('grh', 10, 11, 1, 2)
        _, origins, _ = self.run_audit()
        child = origins['grh', 'P4', 11]
        self.assertEqual(child['classification'], 'producer-projection')
        self.assertEqual(child['p0_node_id'], 2)
        self.assertEqual(child['projection'], {'low': 3, 'width': 2})
        self.assertEqual(len(child['lineage']), 2)

    def test_same_name_new_id_does_not_restore_a_retired_identity(self):
        self.tables['inventory'] = [row for row in self.tables['inventory'] if row[:3] != ('grh', 3, 2)
                                    and row[:3] != ('grh', 4, 2)]
        self.tables['endpoints'] = [row for row in self.tables['endpoints'] if not (row[0] >= 3 and row[1] == 2)]
        self.tables['pairs'] = [row for row in self.tables['pairs'] if not (row[0] >= 3 and row[1] == 2)]
        self.node('grh', 3, 20, 'out', 8)
        self.node('grh', 4, 20, 'out', 8)
        _, origins, _ = self.run_audit()
        self.assertEqual(origins['grh', 'P4', 20]['classification'], 'new')
        self.assertIsNone(origins['grh', 'P4', 20]['p0_node_id'])

    def test_retirement_requires_its_own_certificate_even_with_actual_child_projection(self):
        self.tables['inventory'] = [row for row in self.tables['inventory']
                                    if not (row[0] == 'grh' and row[1] >= 3 and row[2] == 2)]
        self.tables['endpoints'] = [row for row in self.tables['endpoints'] if not (row[0] >= 3 and row[1] == 2)]
        self.tables['pairs'] = [row for row in self.tables['pairs'] if not (row[0] >= 3 and row[1] == 2)]
        self.projection('grh', 2, 10, 2, 4)
        self.tables['inventory'] = [row for row in self.tables['inventory'] if row[:3] != ('grh', 4, 10)]
        self.tables['endpoints'] = [row for row in self.tables['endpoints'] if row[:2] != (4, 10)]
        _, origins, obligations = self.run_audit()
        self.assertEqual(origins['grh', 'P3', 10]['p0_node_id'], 2)
        retired = {(row['boundary'], row['node_id']): row for row in obligations
                   if row['kind'] == 'retirement-semantic-certificate-missing'}
        self.assertEqual(set(retired), {('P3', 2), ('P4', 10)})
        parent = retired['P3', 2]
        self.assertEqual(parent['evidence']['prior_origin']['stage'], 'P2')
        self.assertEqual(parent['evidence']['published_child_projections'][0]['child'], 10)
        self.assertIsNone(parent['semantic_certificate'])
        self.assertEqual(retired['P4', 10]['status'], 'unclosed')

    def test_changed_identity_geometry_preserves_ancestry_but_drops_unpublished_bit_mapping(self):
        endpoints = []
        for row in self.tables['endpoints']:
            if row[0] >= 1 and row[1] == 2:
                payload = json.loads(row[8])
                payload['source_width'] = '4'
                row = (*row[:5], '[4,false,[]]', *row[6:8], json.dumps(payload))
            endpoints.append(row)
        self.tables['endpoints'] = endpoints
        self.projection('grh', 2, 10, 0, 2)
        _, origins, _ = self.run_audit()
        parent = origins['grh', 'P2', 2]
        self.assertEqual(parent['classification'], 'unchanged-identity')
        self.assertEqual(parent['p0_node_id'], 2)
        self.assertIsNone(parent['projection'])
        self.assertIn('identity-physical-geometry-change-needs-projection-evidence', parent['issues'])
        self.assertEqual(origins['grh', 'P3', 10]['classification'], 'unresolved-origin')

    def test_missing_or_inconsistent_names_do_not_claim_preserved_naming(self):
        variants = ((10, None, 'null', 'native'), (11, 'empty', '[]', 'native'),
                    (12, 'canonical', '["different"]', 'native'),
                    (13, 'unnamed', '["unnamed"]', ''), (14, 'bad-json', '{', 'native'))
        for identifier, name, path, native in variants:
            for stage in range(5):
                self.node('grh', stage, identifier, 'temporary', 8)
                self.tables['inventory'][-1] = ('grh', stage, identifier, name, path, native)
        _, origins, _ = self.run_audit()
        for identifier, *_ in variants:
            row = origins['grh', 'P4', identifier]
            self.assertEqual(row['classification'], 'unresolved-origin')
            self.assertIsNone(row['p0_node_id'])
            self.assertIn('missing-or-invalid-native-name-path', row['issues'])

    def test_stale_retired_parent_cannot_supply_a_later_split_input(self):
        self.node('grh', 0, 99, 'stale-parent', 8)
        self.projection('grh', 99, 10, 0, 4)
        _, origins, _ = self.run_audit()
        row = origins['grh', 'P3', 10]
        self.assertEqual(row['classification'], 'unresolved-origin')
        self.assertIn('missing-or-self-producer-parent', row['issues'])

    def test_long_lineage_stops_at_explicit_depth_budget(self):
        for identifier in range(100, 100 + MAX_LINEAGE_DEPTH + 5):
            parent = identifier + 1 if identifier < 100 + MAX_LINEAGE_DEPTH + 4 else 2
            self.projection('grh', parent, identifier, 0, 4)
        report, origins, _ = self.run_audit()
        self.assertEqual(report['bounds']['maximum_lineage_depth'], MAX_LINEAGE_DEPTH)
        self.assertIn('producer-lineage-depth-budget-exceeded', origins['grh', 'P3', 100]['issues'])
        self.assertEqual(origins['grh', 'P3', 100]['classification'], 'unresolved-origin')

    def test_surviving_rename_and_identity_reappearance_stay_unresolved(self):
        self.tables['inventory'] = [row if row[:3] != ('grh', 3, 2) else
            (*row[:3], 'renamed', '["renamed"]', 'renamed') for row in self.tables['inventory']]
        self.tables['pairs'] = [row for row in self.tables['pairs'] if not (row[0] == 3 and row[1] == 2)]
        self.tables['inventory'] = [row for row in self.tables['inventory'] if row[:3] != ('gsim', 2, 2)]
        self.tables['details'] = [row for row in self.tables['details'] if row[:2] != (2, 2)]
        self.tables['pairs'] = [row for row in self.tables['pairs'] if row[:2] != (2, 2)]
        _, origins, _ = self.run_audit()
        self.assertEqual(origins['grh', 'P4', 2]['classification'], 'unresolved-origin')
        self.assertIn('retired-native-identity-reappeared', origins['gsim', 'P3', 2]['issues'])

    def test_missing_binding_never_borrows_geometry_from_matching_gsim_name(self):
        self.tables['endpoints'] = [(*row[:7], 'anchor-candidate', row[8]) if row[1] == 2 else row
                                   for row in self.tables['endpoints']]
        _, origins, obligations = self.run_audit()
        self.assertFalse(origins['grh', 'P4', 2]['source_binding_geometry_checked'])
        self.assertTrue(origins['grh', 'P4', 1]['source_binding_geometry_checked'])
        self.assertTrue(any(row['kind'] == 'cross-engine-name-candidate-is-not-lineage-or-semantic-proof'
                            for row in obligations))

    def test_forged_complete_flag_and_stale_source_interval_stay_unproved(self):
        rows = []
        for row in self.tables['endpoints']:
            payload = json.loads(row[8])
            if row[1] == 2:
                payload['source_width'] = '4'
            rows.append((*row[:8], json.dumps(payload)))
        self.tables['endpoints'] = rows
        _, origins, _ = self.run_audit()
        self.assertFalse(origins['grh', 'P4', 2]['source_binding_geometry_checked'])

    def test_malformed_binding_payload_and_unmatched_array_geometry_stay_unproved(self):
        rows = []
        for row in self.tables['endpoints']:
            if row[1] == 1:
                row = (*row[:8], '[]')
            else:
                payload = json.loads(row[8])
                payload['source_shape_json'] = '[2]'
                payload['projection_json'] = '[-1]'
                row = (*row[:8], json.dumps(payload))
            rows.append(row)
        self.tables['endpoints'] = rows
        _, origins, _ = self.run_audit()
        self.assertFalse(origins['grh', 'P4', 1]['source_binding_geometry_checked'])
        self.assertFalse(origins['grh', 'P4', 2]['source_binding_geometry_checked'])

    def test_invalid_source_signed_or_logic_domain_never_pass_geometry_checks(self):
        rows = []
        for row in self.tables['endpoints']:
            payload = json.loads(row[8])
            if row[1] == 1:
                payload['source_signed'] = 'maybe'
                row = (*row[:8], json.dumps(payload))
            else:
                payload['logic_domain'] = 'invalid-domain'
                row = (*row[:6], 'invalid-domain', row[7], json.dumps(payload))
            rows.append(row)
        self.tables['endpoints'] = rows
        _, origins, _ = self.run_audit()
        self.assertFalse(origins['grh', 'P4', 1]['source_binding_geometry_checked'])
        self.assertFalse(origins['grh', 'P4', 2]['source_binding_geometry_checked'])

    def test_bad_projection_bounds_missing_axes_and_ambiguous_parent_are_unresolved(self):
        self.projection('grh', 2, 10, 7, 4)
        self.projection('grh', 999, 11, 0, 4)
        self.projection('grh', 2, 12, 0, 4)
        self.tables['slices'].append(('grh', 3, 1, 12, 0, 4))
        self.node('gsim', 2, 40, 'array', 8, shape=[2])
        self.projection('gsim', 40, 41, 0, 4)
        _, origins, _ = self.run_audit()
        for engine, identifier in (('grh', 10), ('grh', 11), ('grh', 12), ('gsim', 41)):
            self.assertEqual(origins[engine, 'P3', identifier]['classification'], 'unresolved-origin')

    def test_operation_only_state_next_parent_has_unknown_geometry_before_real_split_children(self):
        # The closed v7 smoke sidecar has this P0-P2 row: value_id=0,
        # native_kind=kConstant, width=0, logic_domain=none, operation-only.
        for stage in range(3):
            self.node('grh', stage, 14, 'state$NEXT', 0)
            payload = {'source_geometry_schema': 'grh.semantic-node-endpoints.v2',
                'source_geometry_complete': False, 'node_id': '14', 'role': 'value',
                'value_id': '0', 'value_generation': '0', 'operation_id': '11',
                'operation_generation': '0', 'native_kind': 'kConstant', 'width': '0',
                'signed': '0', 'shape_json': '[]', 'logic_domain': 'none',
                'source_width': '0', 'source_signed': '0', 'source_shape_json': '[]',
                'source_shape_field_depths_json': '[]', 'projection_json': '[]',
                'source_bit_offset': '0', 'source_bit_width': '-1', 'evidence': 'operation-only'}
            self.tables['endpoints'][-1] = (stage, 14, 14, 0, 'value', '[0,false,[]]',
                                           'none', 'operation-only', json.dumps(payload))
        for stage in range(5):
            self.node('gsim', stage, 14, 'state$NEXT', 256)
        self.projection('grh', 14, 19, 0, 128, name='state$NEXT$0')
        self.projection('grh', 14, 20, 128, 128, name='state$NEXT$1')
        report, origins, _ = self.run_audit()
        for stage in range(3):
            parent = origins['grh', f'P{stage}', 14]
            self.assertIsNone(parent['physical_geometry'])
            self.assertIsNone(parent['projection'])
            self.assertFalse(parent['source_binding_geometry_checked'])
        for identifier in (19, 20):
            child = origins['grh', 'P3', identifier]
            self.assertEqual(child['physical_geometry']['leaf_width'], 128)
            self.assertEqual(child['classification'], 'unresolved-origin')
            self.assertIn('incomplete-physical-scalar-projection-geometry', child['issues'])
            self.assertNotIn('producer-projection-out-of-bounds-or-width-mismatch', child['issues'])
        self.assertFalse(report['window_acceptance'])

    def test_nonvalue_rows_do_not_override_available_grh_physical_value_geometry(self):
        for stage in range(5):
            for value, evidence in ((0, 'native-binding'), (-1, 'anchor-candidate'),
                                    (100, 'operation-only')):
                self.tables['endpoints'].append((stage, 2, 100 + value, value, 'value',
                    '[0,false,[]]', 'none', evidence, '{}'))
        _, origins, _ = self.run_audit()
        for stage in range(5):
            row = origins['grh', f'P{stage}', 2]
            self.assertEqual(row['physical_geometry'], {'leaf_width': 8, 'signed': False, 'shape': []})
            self.assertEqual(row['projection'], {'low': 0, 'width': 8})

    def test_cycle_and_late_slice_cannot_invent_a_P0_origin(self):
        self.projection('grh', 11, 10, 0, 4)
        self.projection('grh', 10, 11, 0, 4)
        self.node('gsim', 3, 20, 'late', 4)
        self.projection('gsim', 2, 20, 0, 4, stage=4)
        _, origins, _ = self.run_audit()
        self.assertEqual(origins['grh', 'P3', 10]['classification'], 'unresolved-origin')
        self.assertEqual(origins['gsim', 'P3', 20]['classification'], 'new')
        self.assertEqual(origins['gsim', 'P4', 20]['classification'], 'unresolved-origin')

    def test_same_reason_and_declining_difference_count_never_close_obligations(self):
        for stage in (0, 1):
            self.tables['differences'].append((stage, 'structure', '["same-reason"]', 'both', 2, 2,
                                               'unverified', '{"affected_nodes":1}'))
        report, _, obligations = self.run_audit()
        reviewed = [row for row in obligations if row['kind'] == 'comparison-difference-needs-origin-and-semantic-review']
        self.assertEqual(len(reviewed), 2)
        self.assertTrue(all(row['status'] == 'unclosed' for row in reviewed))
        self.assertFalse(report['window_acceptance'])

    def test_running_summary_and_sqlite_sidecars_reject_before_database_open(self):
        self.write()
        self.summary['status'] = 'running'
        (self.comparison / 'summary.json').write_text(json.dumps(self.summary))
        with patch('audit_f32_window_origins.sqlite3.connect') as connect:
            with self.assertRaisesRegex(ValueError, 'completed comparison'):
                audit(self.comparison, self.work / 'no-running')
            connect.assert_not_called()
        self.summary['status'] = 'analyzed'
        self.write()
        for suffix in ('-wal', '-shm', '-journal'):
            with self.subTest(suffix=suffix):
                sidecar = self.comparison / ('comparison.sqlite' + suffix)
                sidecar.touch()
                with patch('audit_f32_window_origins.sqlite3.connect') as connect:
                    with self.assertRaisesRegex(ValueError, 'sidecars'):
                        audit(self.comparison, self.work / 'no-sidecar')
                    connect.assert_not_called()
                sidecar.unlink()

    def test_bounds_and_native_run_mismatch_reject_without_claiming_completion(self):
        self.write()
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            audit(self.comparison, self.work / 'small-bytes', max_bytes=10)
        with self.assertRaisesRegex(ValueError, 'row limit'):
            audit(self.comparison, self.work / 'small-rows', max_rows=1)
        self.summary['snapshots']['grh']['P4']['run_id'] = 'other-run'
        (self.comparison / 'summary.json').write_text(json.dumps(self.summary))
        with self.assertRaisesRegex(ValueError, 'share one run'):
            audit(self.comparison, self.work / 'different-run')

    def test_explicit_capacity_override_accepts_an_otherwise_closed_input(self):
        self.write()
        with self.assertRaisesRegex(ValueError, 'row limit'):
            audit(self.comparison, self.work / 'small', max_rows=19)
        report = audit(self.comparison, self.work / 'sufficient', max_rows=20, max_bytes=1024**2)
        self.assertEqual(report['bounds']['maximum_rows_per_table'], 20)
        self.assertFalse(report['window_acceptance'])

    def test_database_connection_is_closed_after_streaming_reports(self):
        self.write()
        original_connect = sqlite3.connect
        opened = []

        def record_connection(*args, **kwargs):
            db = original_connect(*args, **kwargs)
            opened.append(db)
            return db

        with patch('audit_f32_window_origins.sqlite3.connect', side_effect=record_connection):
            audit(self.comparison, self.work / 'closed')
        self.assertEqual(len(opened), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            opened[0].execute('SELECT 1')

    def test_input_change_during_report_prevents_completed_summary(self):
        self.write()

        def modify_after_read(summary, tables):
            result = analyze(summary, tables)
            path = self.comparison / 'summary.json'
            path.write_text(path.read_text() + ' ')
            return result

        output = self.work / 'changed'
        with patch('audit_f32_window_origins.analyze', side_effect=modify_after_read):
            with self.assertRaisesRegex(ValueError, 'comparison changed'):
                audit(self.comparison, output)
        self.assertFalse((output / 'summary.json').exists())

    def test_malformed_pair_id_or_difference_stage_cannot_produce_a_completed_report(self):
        self.tables['pairs'][0] = (0, '1', 1, 'source')
        self.write()
        with self.assertRaisesRegex(ValueError, 'native integer'):
            audit(self.comparison, self.work / 'bad-pair')
        self.tables['pairs'][0] = (0, 1, 1, 'source')
        self.tables['differences'].append((5, 'structure', '[]', 'both', None, None, 'gap', '{}'))
        self.write()
        with self.assertRaisesRegex(ValueError, 'outside F32'):
            audit(self.comparison, self.work / 'bad-difference')

    def test_audit_preserves_input_bytes_and_does_not_overwrite_existing_output(self):
        self.write()
        before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in self.comparison.iterdir()}
        output = self.work / 'audit'
        audit(self.comparison, output)
        self.assertEqual(before, {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
                                  for path in self.comparison.iterdir()})
        with self.assertRaisesRegex(ValueError, 'new directory'):
            audit(self.comparison, output)


if __name__ == '__main__':
    unittest.main()
