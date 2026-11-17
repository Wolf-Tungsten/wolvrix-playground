"""Reusable F32 structure indexes preserve frozen native capture identity."""
from copy import deepcopy
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch

import test_compare_f32_semantics as native_fixtures
from compare_f32_semantics import compare
import index_f32_structure as index_tool
from index_f32_structure import prebuild, reuse_prebuilt


class StructurePrebuildTests(unittest.TestCase):
    def setUp(self):
        self.native = native_fixtures.NativeComparisonTests(
            'test_equal_inventory_is_only_a_candidate_result')
        self.native.setUp()
        self.addCleanup(self.native.tearDown)
        self.native.attach_structure()
        self.grh = self.native.write_capture('grh')
        self.gsim = self.native.write_capture('gsim')
        self.work = self.native.work

    def summary(self, directory):
        return json.loads((directory / 'summary.json').read_text())

    def write_summary(self, directory, summary):
        (directory / 'summary.json').write_text(json.dumps(summary) + '\n')

    def test_exact_marker_and_native_database_are_reusable(self):
        output = self.work / 'prebuilt-P0'
        marker = prebuild(self.grh, self.gsim, 0, output)
        expected = {
            'schema': 'wolvrix.f32.structure-index.v1',
            'inputs': [{key: self.summary(directory)['snapshots']['P0']['artifacts']['structure'][key]
                        for key in ('path', 'sha256', 'bytes')} for directory in (self.grh, self.gsim)],
            'counts': {'paths': 1, 'grh_nodes': 3, 'grh_values': 3, 'grh_ops': 2, 'gsim_nodes': 3}}
        self.assertEqual(marker, expected)
        self.assertEqual(json.loads((output / 'index.json').read_text()), expected)
        db = sqlite3.connect(output / 'comparison.sqlite')
        self.addCleanup(db.close)
        self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(), ('ok',))
        self.assertEqual(db.execute('SELECT id,name FROM grh_nodes ORDER BY id').fetchall(),
                         [(1, 'input'), (2, 'middle'), (3, 'out')])
        self.assertEqual(db.execute('SELECT id,name FROM gs_nodes ORDER BY id').fetchall(),
                         [(1, 'input'), (2, 'middle'), (3, 'out')])
        self.assertEqual(db.execute('SELECT node,op FROM members ORDER BY node,op').fetchall(), [(2, 1), (3, 2)])
        self.assertEqual(db.execute('SELECT count(*) FROM pairs').fetchone(), (0,))

    def test_compare_resume_reuses_prebuilt_stage_without_reindexing(self):
        comparison = self.work / 'comparison'
        compare(self.grh, self.gsim, comparison, structure=False)
        output = comparison / 'structure' / 'P0'
        marker = prebuild(self.grh, self.gsim, 0, output)
        with patch('compare_f32_semantics.structure_index',
                   side_effect=AssertionError('completed native structure must be reused')) as indexer:
            report = compare(self.grh, self.gsim, comparison, resume=True, selected_stages={0})
        indexer.assert_not_called()
        self.assertEqual(report['boundaries']['P0']['structure']['counts']['expression_checked'], 2)
        self.assertEqual(report['boundaries']['P1']['structure']['status'], 'not_requested')
        self.assertEqual(json.loads((output / 'index.json').read_text()), marker)

    def test_rejects_incomplete_mismatched_and_unfrozen_native_sources(self):
        original = self.summary(self.gsim)
        cases = (
            ('incomplete', lambda row: row.update(status='running')),
            ('different-input', lambda row: row.update(input_sha256='b' * 64)),
            ('wrong-hash', lambda row: row['snapshots']['P0']['artifacts']['structure'].update(sha256='0' * 64)),
            ('wrong-size', lambda row: row['snapshots']['P0']['artifacts']['structure'].update(bytes=1)),
            ('wrong-path', lambda row: row['snapshots']['P0']['artifacts']['structure'].update(
                path=str(self.gsim / 'P0' / 'other.json'))),
            ('no-structure', lambda row: row['snapshots']['P0'].update(structure=None)))
        for name, mutate in cases:
            with self.subTest(source=name):
                changed = deepcopy(original)
                mutate(changed)
                self.write_summary(self.gsim, changed)
                output = self.work / name
                with patch('index_f32_structure.structure_index') as indexer:
                    with self.assertRaises(ValueError):
                        prebuild(self.grh, self.gsim, 0, output)
                indexer.assert_not_called()
                self.assertFalse(output.exists())
        self.write_summary(self.gsim, original)

    def test_changed_native_file_is_rejected_before_output_creation(self):
        native = self.grh / 'P0' / 'design.json'
        native.write_text(native.read_text() + '\n')
        output = self.work / 'changed-source'
        with patch('index_f32_structure.structure_index') as indexer:
            with self.assertRaisesRegex(ValueError, 'changed since capture'):
                prebuild(self.grh, self.gsim, 0, output)
        indexer.assert_not_called()
        self.assertFalse(output.exists())

    def test_existing_directory_and_sentinel_are_preserved(self):
        output = self.work / 'existing'
        output.mkdir()
        sentinel = output / 'sentinel.txt'
        sentinel.write_text('existing task data\n')
        with patch('index_f32_structure.structure_index') as indexer:
            with self.assertRaisesRegex(ValueError, 'new directory'):
                prebuild(self.grh, self.gsim, 0, output)
        indexer.assert_not_called()
        self.assertEqual(sentinel.read_text(), 'existing task data\n')
        self.assertEqual([path.name for path in output.iterdir()], ['sentinel.txt'])

    def test_native_build_failure_has_no_completed_index_marker(self):
        native = self.grh / 'P0' / 'design.json'
        design = json.loads(native.read_text())
        design['graphs'][0]['semanticTree']['nodes'][1]['ops'].append(999)
        native.write_text(json.dumps(design, indent=2) + '\n')
        summary = self.summary(self.grh)
        summary['snapshots']['P0']['artifacts']['structure'] = native_fixtures.artifact(native)
        self.write_summary(self.grh, summary)
        output = self.work / 'failed-native-index'
        with self.assertRaisesRegex(ValueError, 'refer to missing IR objects'):
            prebuild(self.grh, self.gsim, 0, output)
        self.assertTrue(output.is_dir())
        self.assertTrue((output / 'comparison.sqlite').exists())
        self.assertFalse((output / 'index.json').exists())
        with self.assertRaisesRegex(ValueError, 'new directory'):
            prebuild(self.grh, self.gsim, 0, output)
        self.assertFalse((output / 'index.json').exists())

    def test_source_stat_change_during_build_does_not_publish_marker(self):
        output = self.work / 'changed-during-build'

        def build_then_touch(grh, gsim, directory):
            db, counts = native_fixtures.structure_index(grh, gsim, directory)
            stat = grh.stat()
            os.utime(grh, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000))
            return db, counts

        with patch('index_f32_structure.structure_index', side_effect=build_then_touch):
            with self.assertRaisesRegex(ValueError, 'changed during prebuild'):
                prebuild(self.grh, self.gsim, 0, output)
        self.assertTrue((output / 'comparison.sqlite').exists())
        self.assertFalse((output / 'index.json').exists())


class StructureReuseTests(unittest.TestCase):
    summary = StructurePrebuildTests.summary
    write_summary = StructurePrebuildTests.write_summary

    def setUp(self):
        StructurePrebuildTests.setUp(self)
        self.source = self.work / 'prebuilt-P0'
        prebuild(self.grh, self.gsim, 0, self.source)
        self.previous_work = self.native.work
        self.native.work = self.work / 'new-captures'
        self.native.work.mkdir()
        self.new_grh = self.native.write_capture('grh')
        self.new_gsim = self.native.write_capture('gsim')
        self.native.work = self.previous_work
        self.output = self.work / 'reused-P0'
        self.output_index = 0

    def reuse(self):
        self.output_index += 1
        self.output = self.work / ('reused-' + str(self.output_index))
        return reuse_prebuilt(self.new_grh, self.new_gsim, 0, self.source, self.output)

    def database(self, directory):
        return directory / 'comparison.sqlite'

    def assert_no_seal(self):
        self.assertFalse((self.output / 'index.json').exists())

    def test_same_native_bytes_new_paths_independent_inode_and_source_unchanged(self):
        source_db = self.database(self.source)
        before = index_tool.file_stamp(source_db)
        sha = index_tool.digest(source_db)
        marker = self.reuse()
        self.assertEqual(marker['inputs'], [{key: self.summary(directory)['snapshots']['P0']['artifacts']['structure'][key]
                                             for key in ('path', 'sha256', 'bytes')}
                                            for directory in (self.new_grh, self.new_gsim)])
        self.assertEqual(index_tool.file_stamp(source_db), before)
        self.assertEqual(index_tool.digest(source_db), sha)
        target = self.database(self.output)
        self.assertNotEqual((target.stat().st_dev, target.stat().st_ino), (source_db.stat().st_dev, source_db.stat().st_ino))
        self.assertEqual(index_tool.digest(target), sha)
        index_tool.validate_database(target, index_tool.expected_schema())
        receipt = json.loads((self.output / 'reuse.json').read_text())
        self.assertEqual(receipt['status'], 'completed')
        self.assertFalse(receipt['hardlink_used'])
        self.assertFalse(receipt['proof_rows_reused'])
        self.assertFalse(receipt['comparison_results_reused'])
        self.assertFalse(receipt['raw_rows_independently_rederived'])
        self.assertEqual(receipt['source_database']['stat_before'], receipt['source_database']['stat_after'])
        self.assertEqual(receipt['source_database']['sha256'], receipt['copied_database']['sha256'])

    def test_P1_and_P2_prebuilt_native_indexes_are_reusable(self):
        for stage in (1, 2):
            with self.subTest(stage=stage):
                source = self.work / f'prebuilt-P{stage}'
                output = self.work / f'reused-P{stage}'
                prebuild(self.grh, self.gsim, stage, source)
                marker = reuse_prebuilt(self.new_grh, self.new_gsim, stage, source, output)
                self.assertEqual(marker['inputs'][0]['path'],
                                 self.summary(self.new_grh)['snapshots'][f'P{stage}']['structure'])
                self.assertEqual(json.loads((output / 'reuse.json').read_text())['stage'], f'P{stage}')
                index_tool.validate_database(output / 'comparison.sqlite', index_tool.expected_schema())

    def test_reused_resume_matches_fresh_small_comparison(self):
        seeded = self.work / 'comparison-reused'
        compare(self.new_grh, self.new_gsim, seeded, structure=False)
        reuse_prebuilt(self.new_grh, self.new_gsim, 0, self.source, seeded / 'structure/P0')
        with patch('compare_f32_semantics.structure_index', side_effect=AssertionError('must reuse P0')):
            reused = compare(self.new_grh, self.new_gsim, seeded, resume=True, selected_stages={0})
        fresh = compare(self.new_grh, self.new_gsim, self.work / 'comparison-fresh', selected_stages={0})
        for key in ('boundaries', 'semantic_acceptance', 'four_state_behavior_proved', 'unproved_compared_pairs',
                    'new_differences_not_present_at_P0'):
            self.assertEqual(json.dumps(reused[key], sort_keys=True).replace(str(seeded), 'COMPARISON'),
                json.dumps(fresh[key], sort_keys=True).replace(str(self.work / 'comparison-fresh'), 'COMPARISON'))
        with closing(sqlite3.connect(seeded / 'comparison.sqlite')) as reused_db, closing(sqlite3.connect(
                self.work / 'comparison-fresh/comparison.sqlite')) as fresh_db:
            for table in ('structural', 'structural_diagnoses', 'anchor_proofs', 'state_transfers'):
                self.assertEqual(reused_db.execute('SELECT * FROM ' + table + ' ORDER BY stage,grh').fetchall(),
                                 fresh_db.execute('SELECT * FROM ' + table + ' ORDER BY stage,grh').fetchall())

    def test_each_mutable_cache_table_must_be_empty(self):
        records = {'pairs': (1, 1, 'input'), 'native_type_evidence': (1, 8, 0, '[]', 'inferred'),
                   'disconnected_members': (1, 1, 'kAssign')}
        for table, row in records.items():
            with self.subTest(table=table):
                with closing(sqlite3.connect(self.database(self.source))) as db, db:
                    db.execute('INSERT INTO ' + table + ' VALUES(' + ','.join('?' for _ in row) + ')', row)
                with patch.object(index_tool, 'copy_database') as copier:
                    with self.assertRaisesRegex(ValueError, 'empty prebuilt table'):
                        self.reuse()
                    copier.assert_not_called()
                self.assert_no_seal()
                with closing(sqlite3.connect(self.database(self.source))) as db, db:
                    db.execute('DELETE FROM ' + table)

    def test_source_sidecars_and_proof_files_rejected_before_connect_or_copy(self):
        for name in ('comparison.sqlite-wal', 'comparison.sqlite-shm', 'comparison.sqlite-journal', 'proof-progress.json'):
            with self.subTest(name=name):
                path = self.source / name
                path.touch()
                with patch.object(index_tool.sqlite3, 'connect') as connect, patch.object(index_tool, 'copy_database') as copier:
                    with self.assertRaisesRegex(ValueError, 'no sidecars or proof files'):
                        self.reuse()
                    connect.assert_not_called()
                    copier.assert_not_called()
                path.unlink()

    def test_missing_or_empty_database_never_gets_created_as_valid_source(self):
        source_db = self.database(self.source)
        source_db.unlink()
        with self.assertRaisesRegex(ValueError, 'closed prebuilt stage'):
            self.reuse()
        self.assertFalse(source_db.exists())
        source_db.touch()
        with patch.object(index_tool, 'copy_database') as copier:
            with self.assertRaisesRegex(ValueError, 'schema differs'):
                self.reuse()
            copier.assert_not_called()
        self.assert_no_seal()

    def test_schema_injection_or_missing_objects_rejected(self):
        baseline = self.work / 'baseline.sqlite'
        shutil.copyfile(self.database(self.source), baseline)
        changes = ('CREATE TABLE injected(value TEXT)', 'CREATE VIEW injected AS SELECT * FROM ops',
            'CREATE TRIGGER injected AFTER INSERT ON pairs BEGIN SELECT 1; END',
            'ALTER TABLE gs_nodes ADD COLUMN injected TEXT', 'DROP INDEX anchors_by_value')
        for sql in changes:
            with self.subTest(sql=sql):
                shutil.copyfile(baseline, self.database(self.source))
                with closing(sqlite3.connect(self.database(self.source))) as db, db:
                    db.executescript(sql)
                with patch.object(index_tool, 'copy_database') as copier:
                    with self.assertRaisesRegex(ValueError, 'schema differs'):
                        self.reuse()
                    copier.assert_not_called()
                self.assert_no_seal()

    def test_old_marker_sha_bytes_schema_and_partial_source_rejected(self):
        path = self.source / 'index.json'
        original = path.read_text()
        cases = (lambda value: value.update(schema='unknown'),
                 lambda value: value['inputs'][0].update(sha256='0' * 64),
                 lambda value: value['inputs'][1].update(bytes=1),
                 lambda value: value['counts'].update(grh_nodes=True))
        for change in cases:
            value = json.loads(original)
            change(value)
            path.write_text(json.dumps(value))
            with patch.object(index_tool, 'copy_database') as copier:
                with self.assertRaises(ValueError):
                    self.reuse()
                copier.assert_not_called()
            self.assert_no_seal()
        path.write_text(original)
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'closed prebuilt stage'):
            self.reuse()

    def test_changed_or_unfrozen_new_native_input_rejected(self):
        path = self.new_grh / 'P0/design.json'
        original = path.read_text()
        path.write_text(original + '\n')
        with patch.object(index_tool, 'copy_database') as copier:
            with self.assertRaisesRegex(ValueError, 'hash/bytes mismatch'):
                self.reuse()
            copier.assert_not_called()
        changed = self.summary(self.new_grh)
        changed['snapshots']['P0']['artifacts']['structure'] = native_fixtures.artifact(path)
        self.write_summary(self.new_grh, changed)
        with self.assertRaisesRegex(ValueError, 'hash/bytes mismatch'):
            self.reuse()

    def test_incomplete_capture_rejected(self):
        changed = self.summary(self.new_grh)
        changed['status'] = 'running'
        self.write_summary(self.new_grh, changed)
        with patch.object(index_tool, 'copy_database') as copier:
            with self.assertRaisesRegex(ValueError, 'completed native'):
                self.reuse()
            copier.assert_not_called()

    def test_source_database_mutation_during_copy_has_no_marker(self):
        real_copy = index_tool.copy_database
        def copy_then_touch(source, target):
            real_copy(source, target)
            info = source.stat()
            os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000))
        with patch.object(index_tool, 'copy_database', side_effect=copy_then_touch):
            with self.assertRaisesRegex(ValueError, 'source prebuilt database changed'):
                self.reuse()
        self.assert_no_seal()

    def test_source_sidecar_appearing_during_copy_has_no_marker(self):
        real_copy = index_tool.copy_database
        def copy_then_sidecar(source, target):
            real_copy(source, target)
            Path(str(source) + '-wal').touch()
        with patch.object(index_tool, 'copy_database', side_effect=copy_then_sidecar):
            with self.assertRaisesRegex(ValueError, 'no sidecars or proof files'):
                self.reuse()
        self.assert_no_seal()

    def test_native_or_capture_metadata_mutation_during_copy_has_no_marker(self):
        real_copy = index_tool.copy_database
        for path in (self.new_grh / 'P0/design.json', self.new_gsim / 'summary.json'):
            with self.subTest(path=path):
                original = path.read_bytes()
                def copy_then_change(source, target):
                    real_copy(source, target)
                    path.write_bytes(original + b'\n')
                with patch.object(index_tool, 'copy_database', side_effect=copy_then_change):
                    with self.assertRaisesRegex(ValueError, 'changed during reuse'):
                        self.reuse()
                self.assert_no_seal()
                path.write_bytes(original)

    def test_hardlink_copy_is_rejected(self):
        with patch.object(index_tool, 'copy_database', side_effect=os.link):
            with self.assertRaisesRegex(ValueError, 'never a hardlink'):
                self.reuse()
        self.assert_no_seal()

    def test_corrupt_copy_is_rejected(self):
        def corrupt_copy(source, target):
            target.write_bytes(source.read_bytes() + b'corrupt')
        with patch.object(index_tool, 'copy_database', side_effect=corrupt_copy):
            with self.assertRaisesRegex(ValueError, 'copied structure database differs'):
                self.reuse()
        self.assert_no_seal()

    def test_copied_database_sidecar_rejected_before_marker(self):
        real_copy = index_tool.copy_database
        def copy_then_sidecar(source, target):
            real_copy(source, target)
            Path(str(target) + '-wal').touch()
        with patch.object(index_tool, 'copy_database', side_effect=copy_then_sidecar):
            with self.assertRaisesRegex(ValueError, 'sidecars or unexpected files'):
                self.reuse()
        self.assert_no_seal()

    def test_existing_output_sentinel_preserved_and_reuse_stage_limited(self):
        self.output.mkdir()
        sentinel = self.output / 'sentinel'
        sentinel.write_text('keep')
        with self.assertRaisesRegex(ValueError, 'new directory'):
            reuse_prebuilt(self.new_grh, self.new_gsim, 0, self.source, self.output)
        self.assertEqual(sentinel.read_text(), 'keep')
        for stage in (3, 4, False):
            with self.assertRaisesRegex(ValueError, 'limited to P0 through P2'):
                reuse_prebuilt(self.new_grh, self.new_gsim, stage, self.source, self.work / 'stage-output')

    def test_receipt_published_before_marker_and_marker_failure_is_unsealed(self):
        real_write = index_tool.write_json
        published = []
        def write(path, value):
            published.append(path.name)
            if path.name == 'index.json':
                self.assertEqual(published[0], 'reuse.json')
                raise OSError('marker publication failed')
            real_write(path, value)
        with patch.object(index_tool, 'write_json', side_effect=write):
            with self.assertRaisesRegex(OSError, 'marker publication failed'):
                self.reuse()
        self.assert_no_seal()
        self.assertEqual(json.loads((self.output / 'reuse.json').read_text())['status'], 'publication_failed')

    def test_receipt_failure_never_publishes_marker(self):
        with patch.object(index_tool, 'write_json', side_effect=OSError('receipt publication failed')):
            with self.assertRaisesRegex(OSError, 'receipt publication failed'):
                self.reuse()
        self.assert_no_seal()

    def test_implementation_changed_since_module_load_rejected_before_copy(self):
        changed = dict(index_tool.LOADED_IMPLEMENTATION)
        changed[str(index_tool.IMPLEMENTATION_PATHS[0])] = '0' * 64
        with patch.object(index_tool, 'LOADED_IMPLEMENTATION', changed), patch.object(index_tool, 'copy_database') as copier:
            with self.assertRaisesRegex(ValueError, 'implementation changed since module load'):
                self.reuse()
            copier.assert_not_called()
        self.assert_no_seal()

    def test_changes_during_receipt_publication_do_not_seal_stage(self):
        real_write = index_tool.write_json
        for mutation in ('source-sidecar', 'target-sidecar', 'target-stat', 'native-stat', 'summary-stat'):
            with self.subTest(mutation=mutation):
                def publish_then_mutate(path, value):
                    real_write(path, value)
                    if path.name != 'reuse.json' or value['status'] != 'completed':
                        return
                    if mutation == 'source-sidecar':
                        (self.source / 'comparison.sqlite-wal').touch()
                    elif mutation == 'target-sidecar':
                        (path.parent / 'comparison.sqlite-wal').touch()
                    else:
                        changed = {'target-stat': path.parent / 'comparison.sqlite',
                                   'native-stat': self.new_grh / 'P0/design.json',
                                   'summary-stat': self.new_gsim / 'summary.json'}[mutation]
                        info = changed.stat()
                        os.utime(changed, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000))
                with patch.object(index_tool, 'write_json', side_effect=publish_then_mutate):
                    with self.assertRaises(ValueError):
                        self.reuse()
                self.assert_no_seal()
                self.assertEqual(json.loads((self.output / 'reuse.json').read_text())['status'], 'publication_failed')
                if mutation == 'source-sidecar':
                    (self.source / 'comparison.sqlite-wal').unlink()


if __name__ == '__main__':
    unittest.main()
