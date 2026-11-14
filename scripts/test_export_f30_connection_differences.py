"""Small inventories check coarse edge direction, exclusions and publication gates."""
from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import export_f30_connection_differences as export
from semantic_node_exchange import decode_cell


class ConnectionDifferencesTests(unittest.TestCase):
    def setUp(self):
        root = export.ROOT / 'ptmp/firrtl-ingest/F30/connection-difference-contract'
        root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=root)
        self.work = Path(self.temporary.name)
        self.analysis = self.work / 'analysis'
        self.analysis.mkdir()
        self.output = self.work / 'differences'
        self.grh = [(1, 1, 2, 'dependency', 'resolved'), (2, 1, 2, 'dependency', 'resolved'),
                    (3, 2, 3, 'dependency', 'resolved'), (4, 3, 4, 'storage_read', 'resolved'),
                    (5, 1, 1, 'dependency', 'resolved'), (6, None, 1, 'dependency', 'unresolved'),
                    (7, 1, 5, 'dependency', 'resolved'), (8, 7, 2, 'dependency', 'resolved'),
                    (9, 8, 4, 'dependency', 'resolved'), (10, 9, 1, 'dependency', 'resolved')]
        self.gsim = [(1, 101, 102, 'dependency', 'resolved'), (2, 101, 102, 'dependency', 'resolved'),
                     (3, 101, 102, 'dependency', 'resolved'), (4, 103, 101, 'dependency', 'resolved'),
                     (5, 102, 103, 'storage_write', 'resolved'), (6, None, 101, 'dependency', 'unresolved'),
                     (7, 101, 105, 'dependency', 'resolved'), (8, 106, 102, 'dependency', 'resolved'),
                     (9, 108, 104, 'dependency', 'resolved'), (10, 109, 101, 'dependency', 'resolved')]
        self.fixture()

    def tearDown(self):
        self.temporary.cleanup()

    def fixture(self):
        for engine, rows in (('grh', self.grh), ('gsim', self.gsim)):
            with sqlite3.connect(self.analysis / (engine + '-split.sqlite')) as db:
                db.execute('CREATE TABLE after_connections(id INTEGER PRIMARY KEY,body TEXT)')
                for identifier, source, target, kind, resolution in rows:
                    db.execute('INSERT INTO after_connections VALUES(?,?)', (identifier, json.dumps({
                        'connection_id': identifier, 'source_node_id': source, 'target_node_id': target,
                        'kind': kind, 'resolution': resolution,
                        'reason': ('ambiguous-native-boundary' if engine == 'grh' else 'external-binding')
                                  if resolution == 'unresolved' else None,
                        'candidate_sources_json': [2, 3] if engine == 'grh' and resolution == 'unresolved' else []})))
        with sqlite3.connect(self.analysis / 'analysis.sqlite') as db:
            for engine, offset in (('grh', 0), ('gsim', 100)):
                db.execute(f'CREATE TABLE after_{engine}_names(path TEXT PRIMARY KEY,node_id INTEGER,occurrences INTEGER)')
                db.executemany(f'INSERT INTO after_{engine}_names VALUES(?,?,?)',
                               [('top.' + name, offset + index, 1) for index, name in enumerate('abcd', 1)])
            db.executemany('INSERT INTO after_grh_names VALUES(?,?,?)',
                           [('top.ambiguous', 5, 2), ('top.peer_ambiguous', 7, 1), ('top.grh_only', 8, 1)])
            db.executemany('INSERT INTO after_gsim_names VALUES(?,?,?)',
                           [('top.ambiguous', 105, 1), ('top.peer_ambiguous', 106, 2), ('top.gsim_only', 108, 1)])
            for engine, offset in (('grh', 0), ('gsim', 100)):
                db.execute(f'CREATE TABLE after_{engine}_nodes(id INTEGER PRIMARY KEY,path TEXT,native_name TEXT)')
                db.execute(f'''INSERT INTO after_{engine}_nodes SELECT node_id,path,path
                    FROM after_{engine}_names''')
                db.execute(f'INSERT INTO after_{engine}_nodes VALUES(?,?,?)', (offset + 9, None, 'no-public-path'))
        self.report = {'schema': 'wolvrix.f30.native-alignment-analysis.v1', 'complete': True,
            'report_path': str(self.analysis / 'summary.json'), 'input_sha256': 'a' * 64, 'root_name': 'top',
            'comparison': {'after': {'complete': True, 'unique_name_candidates': 4}},
            'grh_verification': {'grh-split': self.verification('grh')},
            'gsim_verification': self.verification('gsim'),
            'public_comparison': {'name_comparison': export.name_comparison_metadata(),
                'unique_name_candidates_after': 4, 'grh_connections_after': 10, 'gsim_connections_after': 10,
                'grh_resolved_after': 9, 'gsim_resolved_after': 9,
                'grh_unresolved_after': 1, 'gsim_unresolved_after': 1,
                'grh_comparable_resolved_after': 4, 'gsim_comparable_resolved_after': 3,
                'matched_resolved_after': 1}}
        self.write_report()

    def write_report(self):
        (self.analysis / 'summary.json').write_text(json.dumps(self.report))

    @staticmethod
    def verification(engine):
        header = {'engine': engine, 'root_name': 'top', 'run_id': engine + '-run', 'graph_id': 'graph',
                  'pass': 'split-static-array' if engine == 'grh' else 'splitArray'}
        header.update({'input_sha256': 'a' * 64} if engine == 'grh' else {'input_identity': {'sha256': 'a' * 64}})
        return {'complete': True, 'replay_exact': True, 'header': header}

    def read_tsv(self, filename):
        lines = (self.output / filename).read_text().splitlines()
        self.assertTrue(lines[0].startswith('#meta\t'))
        self.assertTrue(lines[-1].startswith('#footer\t'))
        columns = lines[1].split('\t')
        self.assertTrue(all(len(line.split('\t')) == len(columns) for line in lines[2:-1]))
        rows = [dict(zip(columns, map(decode_cell, line.split('\t')))) for line in lines[2:-1]]
        self.assertEqual(json.loads(lines[-1].split('\t', 1)[1]), {'complete': True, 'rowCount': len(rows)})
        return json.loads(lines[0].split('\t', 1)[1]), rows

    def test_direction_distinct_kind_exclusions_and_affected_nodes(self):
        report = export.export(self.analysis, self.output)
        self.assertTrue(report['complete'])
        self.assertTrue(report['public_comparison_crosscheck']['exact'])
        total = report['totals']
        self.assertEqual(total['grh_only_distinct'], 3)
        self.assertEqual(total['gsim_only_distinct'], 2)
        self.assertEqual(total['matched_distinct'], 1)
        self.assertEqual(total['grh_duplicates_in_comparable_resolved'], 1)
        self.assertEqual(total['gsim_duplicates_in_comparable_resolved'], 2)
        self.assertEqual(total['grh_excluded_resolved_unmatched_endpoints'], 4)
        self.assertEqual(total['gsim_excluded_resolved_unmatched_endpoints'], 4)
        self.assertEqual(total['grh_raw_unresolved'], 1)
        metadata, grh_rows = self.read_tsv('grh-only.connections.tsv')
        _, gsim_rows = self.read_tsv('gsim-only.connections.tsv')
        pairs = lambda rows: {(row['source_path'], row['target_path'], row['kind']) for row in rows}
        self.assertEqual(pairs(grh_rows), {('top.a', 'top.a', 'dependency'), ('top.b', 'top.c', 'dependency'),
                                         ('top.c', 'top.d', 'storage_read')})
        self.assertEqual(pairs(gsim_rows), {('top.c', 'top.a', 'dependency'), ('top.b', 'top.c', 'storage_write')})
        edge = next(row for row in grh_rows if row['source_path'] == 'top.b')
        self.assertEqual([edge[key] for key in export.EDGE_COLUMNS[3:]], ['2', '3', '102', '103'])
        self.assertEqual(report['affected_nodes']['total'], 4)
        self.assertEqual(report['affected_nodes']['top_cases'][0]['canonical_firrtl_path'], 'top.c')
        self.assertEqual(report['affected_nodes']['top_cases'][0]['difference_incidents'], 4)
        _, nodes = self.read_tsv('affected-nodes.tsv')
        self.assertEqual(sum(int(row['difference_incidents']) for row in nodes), 10)
        self.assertEqual(metadata['input_sha256'], 'a' * 64)
        expected_hash = hashlib.sha256((self.analysis / 'summary.json').read_bytes()).hexdigest()
        self.assertEqual(metadata['source_report_sha256'], expected_hash)
        self.assertEqual(report['source_report_sha256'], expected_hash)
        by_kind = {row['kind']: row for row in report['per_kind']}
        self.assertEqual(by_kind['dependency']['matched_distinct'], 1)
        self.assertEqual(by_kind['dependency']['grh_only_distinct'], 2)
        self.assertEqual(by_kind['storage_read']['grh_only_distinct'], 1)
        self.assertEqual(by_kind['storage_write']['gsim_only_distinct'], 1)
        self.assertFalse((self.output / 'scratch.sqlite').exists())

    def test_native_databases_are_read_only_and_cache_temp_storage_are_bounded(self):
        before = {path.name: path.read_bytes() for path in self.analysis.glob('*.sqlite')}
        original = export.build_connections
        def checked(db, engine):
            self.assertEqual(db.execute('PRAGMA temp_store').fetchone()[0], 1)
            total_kib = 0
            for schema in ('main', 'temp', 'analysis', 'grh', 'gsim'):
                cache = db.execute('PRAGMA ' + schema + '.cache_size').fetchone()[0]
                self.assertEqual(cache, -8192)
                total_kib += -cache
            self.assertLessEqual(total_kib, 64 * 1024)
            with self.assertRaisesRegex(sqlite3.OperationalError, 'readonly'):
                db.execute('DELETE FROM ' + engine + '.after_connections')
            return original(db, engine)
        with patch.object(export, 'build_connections', side_effect=checked):
            export.export(self.analysis, self.output)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.analysis.glob('*.sqlite')})

    def test_unresolved_reason_groups_bounded_samples_and_phase_logging(self):
        rows = [(11, 1, [2, 3], 'ambiguous-native-boundary'),
                (12, 1, [2, 3], 'ambiguous-native-boundary'),
                (13, 1, [2, 3], 'ambiguous-native-boundary'),
                (14, 1, list(range(1, 21)), 'ambiguous-native-boundary'),
                (15, 1, [], 'missing-native-boundary'),
                (16, 1, [], 'missing-native-boundary'),
                (17, 9, [], 'unowned-undriven-value')]
        with sqlite3.connect(self.analysis / 'grh-split.sqlite') as db:
            for identifier, target, candidates, reason in rows:
                db.execute('INSERT INTO after_connections VALUES(?,?)', (identifier, json.dumps({
                    'connection_id': identifier, 'source_node_id': None, 'target_node_id': target,
                    'kind': 'dependency', 'resolution': 'unresolved', 'reason': reason,
                    'candidate_sources_json': candidates})))
        self.report['public_comparison']['grh_connections_after'] += len(rows)
        self.report['public_comparison']['grh_unresolved_after'] += len(rows)
        self.write_report()
        messages = io.StringIO()
        with redirect_stdout(messages):
            report = export.export(self.analysis, self.output)
        diagnostic = report['unresolved_diagnostics']
        self.assertTrue(diagnostic['samples_are_not_population_counts'])
        self.assertEqual(diagnostic['grh']['total'], 8)
        self.assertEqual(diagnostic['grh']['by_reason'], [
            {'reason': 'ambiguous-native-boundary', 'connections': 5},
            {'reason': 'missing-native-boundary', 'connections': 2},
            {'reason': 'unowned-undriven-value', 'connections': 1}])
        groups = {(group['reason'], group['candidate_source_count']): group
                  for group in diagnostic['grh']['groups']}
        group = groups['ambiguous-native-boundary', 2]
        self.assertEqual(group['connections'], 4)
        self.assertEqual(len(group['examples']), 3)
        self.assertEqual(group['examples'][0]['target_path'], 'top.a')
        self.assertEqual([node['canonical_firrtl_path'] for node in group['examples'][0]['candidate_sources']],
                         ['top.b', 'top.c'])
        example = groups['ambiguous-native-boundary', 20]['examples'][0]
        self.assertTrue(example['candidates_truncated'])
        self.assertEqual(len(example['candidate_sources']), 16)
        self.assertEqual(example['candidate_sources'][-1],
                         {'node_id': 16, 'canonical_firrtl_path': None, 'native_name': None})
        self.assertIsNone(groups['unowned-undriven-value', 0]['examples'][0]['target_path'])
        self.assertEqual(diagnostic['gsim']['by_reason'], [{'reason': 'external-binding', 'connections': 1}])
        self.assertEqual(report['totals']['grh_only_distinct'], 3)
        self.assertEqual(report['totals']['gsim_only_distinct'], 2)
        events = [json.loads(line) for line in messages.getvalue().splitlines()]
        self.assertEqual(len(events), 2 * 12)
        for start, end in zip(events[::2], events[1::2]):
            self.assertEqual(start['event'], 'phase-start')
            self.assertEqual(end['event'], 'phase-end')
            self.assertEqual(start['phase'], end['phase'])
            self.assertGreaterEqual(end['phase_wall_s'], 0)

    def test_incomplete_or_mismatched_source_is_rejected_before_sql(self):
        for field in ('complete', 'replay_exact', 'input'):
            with self.subTest(field=field):
                if field == 'complete':
                    self.report['complete'] = False
                elif field == 'replay_exact':
                    self.report['complete'] = True
                    self.report['gsim_verification']['replay_exact'] = False
                else:
                    self.report['gsim_verification']['replay_exact'] = True
                    self.report['gsim_verification']['header']['input_identity']['sha256'] = 'b' * 64
                self.write_report()
                with patch.object(export.sqlite3, 'connect', side_effect=AssertionError('no SQL before source validation')):
                    with self.assertRaises(ValueError):
                        export.export(self.analysis, self.output)
        self.assertFalse(self.output.exists())

    def test_summary_crosscheck_failure_publishes_no_difference_files(self):
        self.report['public_comparison']['matched_resolved_after'] = 2
        self.write_report()
        with self.assertRaisesRegex(ValueError, 'counts differ'):
            export.export(self.analysis, self.output)
        self.assertFalse(any(self.output.glob('*.tsv')))
        failed = json.loads((self.output / 'summary.json').read_text())
        self.assertFalse(failed['complete'])
        self.assertEqual(failed['status'], 'failed')

    def test_changed_source_report_prevents_publication(self):
        original = export.write_tsv
        def changing(*args):
            result = original(*args)
            path = self.analysis / 'summary.json'
            path.write_bytes(path.read_bytes() + b'\n')
            return result
        with patch.object(export, 'write_tsv', side_effect=changing):
            with self.assertRaisesRegex(ValueError, 'changed during'):
                export.export(self.analysis, self.output)
        self.assertFalse(any(self.output.glob('*.tsv')))

    def test_new_source_journal_prevents_publication(self):
        original = export.write_tsv
        for suffix in ('-wal', '-journal'):
            with self.subTest(suffix=suffix):
                self.output = self.work / ('differences' + suffix)
                sidecar = self.analysis / ('grh-split.sqlite' + suffix)
                def changing(*args):
                    result = original(*args)
                    sidecar.write_bytes(b'new-source-write')
                    return result
                with patch.object(export, 'write_tsv', side_effect=changing):
                    with self.assertRaisesRegex(ValueError, 'pending journal'):
                        export.export(self.analysis, self.output)
                self.assertFalse(any(self.output.glob('*.tsv')))
                self.assertFalse(json.loads((self.output / 'summary.json').read_text())['complete'])
                sidecar.unlink()

    def test_actual_edge_and_candidate_queries_use_point_indexes(self):
        original_edges = export.build_connections
        original_unresolved = export.summarize_unresolved
        def checked_edges(db, engine):
            statements = []
            db.set_trace_callback(statements.append)
            result = original_edges(db, engine)
            db.set_trace_callback(None)
            query = next(sql for sql in statements if sql.startswith('INSERT OR IGNORE'))
            plan = [row[3] for row in db.execute('EXPLAIN QUERY PLAN ' + query)]
            self.assertTrue(any('SCAN e' in detail for detail in plan), plan)
            for endpoint in ('src', 'dst'):
                expected = 'SEARCH ' + endpoint + ' USING INDEX common_' + engine
                self.assertTrue(any(expected in detail.replace('COVERING ', '') for detail in plan), plan)
            if engine == 'gsim':
                plan = [row[3] for row in db.execute('''EXPLAIN QUERY PLAN SELECT * FROM grh_edges e
                    WHERE NOT EXISTS(SELECT 1 FROM gsim_edges p
                    WHERE p.source=e.source AND p.target=e.target AND p.kind=e.kind)''')]
                self.assertTrue(any('SEARCH p USING PRIMARY KEY' in detail for detail in plan), plan)
            return result
        def checked_unresolved(db, engine, expected):
            statements = []
            db.set_trace_callback(statements.append)
            result = original_unresolved(db, engine, expected)
            db.set_trace_callback(None)
            query = next(sql for sql in statements if sql.startswith('SELECT j.value'))
            plan = [row[3] for row in db.execute('EXPLAIN QUERY PLAN ' + query)]
            self.assertTrue(any('SEARCH u USING INDEX ' + engine + '_unresolved_group' in detail
                                for detail in plan), plan)
            self.assertTrue(any('SEARCH n USING INTEGER PRIMARY KEY' in detail for detail in plan), plan)
            return result
        with patch.object(export, 'build_connections', side_effect=checked_edges), \
                patch.object(export, 'summarize_unresolved', side_effect=checked_unresolved), redirect_stdout(io.StringIO()):
            export.export(self.analysis, self.output)

    def test_empty_connection_graph_and_refusal_to_overwrite(self):
        for engine in ('grh', 'gsim'):
            with sqlite3.connect(self.analysis / (engine + '-split.sqlite')) as db:
                db.execute('DELETE FROM after_connections')
        for key in self.report['public_comparison']:
            if key != 'name_comparison' and key != 'unique_name_candidates_after':
                self.report['public_comparison'][key] = 0
        self.write_report()
        report = export.export(self.analysis, self.output)
        self.assertEqual(report['totals']['matched_distinct'], 0)
        self.assertEqual(report['affected_nodes']['total'], 0)
        self.assertEqual(report['per_kind'], [])
        for filename in ('grh-only.connections.tsv', 'gsim-only.connections.tsv', 'affected-nodes.tsv'):
            self.assertEqual(self.read_tsv(filename)[1], [])
        saved = (self.output / 'summary.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            export.export(self.analysis, self.output)
        self.assertEqual((self.output / 'summary.json').read_bytes(), saved)


if __name__ == '__main__':
    unittest.main()
