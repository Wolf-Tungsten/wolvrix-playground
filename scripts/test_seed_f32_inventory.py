"""Seeded inventories preserve frozen rows and the current native run identity."""
from contextlib import closing
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

import compare_f32_semantics as reader
import test_compare_f32_semantics as native_fixtures
from seed_f32_inventory import seed_inventory

ROOT = Path(__file__).resolve().parents[1]
ENGINES = ('grh', 'gsim')
PARTITIONS = {(engine, stage) for engine in ENGINES for stage in range(5)}


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + '\n')


class SeedInventoryTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get('F32_SEED_TEST_ROOT', ROOT / 'ptmp/firrtl-ingest/F32/seed-contract-tmp'))
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        fixture = native_fixtures.NativeComparisonTests('test_equal_inventory_is_only_a_candidate_result')
        fixture.work = self.work / 'source-captures'
        fixture.work.mkdir()
        fixture.frames = {engine: [{'nodes': [(1, 'input'), (2, 'middle'), (3, 'out')],
            'edges': [(1, 1, 2, 'dependency', 'resolved', [], None),
                      (2, 2, 3, 'dependency', 'resolved', [], None)],
            'widths': {}, 'shapes': {}, 'slices': [], 'structure': None}
            for _ in range(5)] for engine in ENGINES}
        fixture.attach_structure()
        self.original = {engine: fixture.write_capture(engine) for engine in ENGINES}
        self.source = self.work / 'source-comparison'
        reader.compare(self.original['grh'], self.original['gsim'], self.source, structure=False)
        self.current = {}
        for engine in ENGINES:
            destination = self.work / 'current-captures' / engine
            shutil.copytree(self.original[engine], destination)
            summary = read_json(destination / 'summary.json')
            for stage in range(5):
                record = summary['snapshots'][f'P{stage}']
                directory = destination / f'P{stage}'
                record['directory'] = str(directory)
                record['structure'] = str(directory / 'design.json')
                for name in record['artifacts']:
                    path = directory / ('design.json' if name == 'structure' else name)
                    if name != 'structure':
                        first, body = path.read_bytes().split(b'\n', 1)
                        metadata = json.loads(first[6:])
                        metadata.update(run_id=engine + '-current-run', graph_id='current-top',
                            exchange_session_id=engine + '-current-session',
                            snapshot_id=f'{engine}-current-P{stage}')
                        path.write_bytes(('#meta\t' + reader.compact(metadata) + '\n').encode() + body)
                    record['artifacts'][name] = native_fixtures.artifact(path)
            write_json(destination / 'summary.json', summary)
            self.current[engine] = destination

    def seed(self, output='seeded', reuse=PARTITIONS):
        destination = self.work / output
        return destination, seed_inventory(self.current['grh'], self.current['gsim'],
                                           self.source, destination, reuse)

    def receipt_partitions(self, receipt, field):
        return {(row['engine'], int(row['stage'][1:])) for row in receipt[field]}

    def refresh_artifact(self, engine, stage, name, *, original=False):
        capture = (self.original if original else self.current)[engine]
        summary = read_json(capture / 'summary.json')
        summary['snapshots'][f'P{stage}']['artifacts'][name] = native_fixtures.artifact(capture / f'P{stage}' / name)
        write_json(capture / 'summary.json', summary)

    def replace_metadata(self, engine, stage, updates, *, names=None):
        capture = self.current[engine]
        summary = read_json(capture / 'summary.json')
        record = summary['snapshots'][f'P{stage}']
        for name in names or (key for key in record['artifacts'] if key != 'structure'):
            path = capture / f'P{stage}' / name
            first, body = path.read_bytes().split(b'\n', 1)
            metadata = json.loads(first[6:])
            metadata.update(updates)
            path.write_bytes(('#meta\t' + reader.compact(metadata) + '\n').encode() + body)
            record['artifacts'][name] = native_fixtures.artifact(path)
        write_json(capture / 'summary.json', summary)

    def query(self, comparison, sql, parameters=()):
        path = comparison / 'comparison.sqlite'
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            return db.execute(sql, parameters).fetchall()

    def raw_partition(self, comparison, engine, stage):
        rows = {}
        for table in ('inventory', 'connections', 'slices', 'endpoints' if engine == 'grh' else 'details'):
            where = 'stage=?' if table in ('endpoints', 'details') else 'engine=? AND stage=?'
            parameters = (stage,) if table in ('endpoints', 'details') else (engine, stage)
            rows[table] = sorted(self.query(comparison, 'SELECT * FROM ' + table + ' WHERE ' + where,
                                           parameters), key=repr)
        return rows

    def source_stamp(self):
        return {path.name: (file_hash(path), path.stat().st_size, path.stat().st_mtime_ns,
                            path.stat().st_ctime_ns, path.stat().st_ino)
                for path in self.source.iterdir() if path.is_file()}

    def test_partial_reuse_skips_ingest_only_for_equal_requested_partitions(self):
        path = self.current['grh'] / 'P3/nodes.tsv'
        path.write_bytes(path.read_bytes().replace(b'2\t["middle"]\tmiddle\n',
                                                   b'2\t["middle-current"]\tmiddle-current\n'))
        self.refresh_artifact('grh', 3, 'nodes.tsv')
        requested = {('grh', 0), ('gsim', 0), ('grh', 1), ('grh', 3)}
        expected_reuse = requested - {('grh', 3)}
        with patch.object(reader, 'ingest_snapshot', wraps=reader.ingest_snapshot) as ingest:
            output, receipt = self.seed(reuse=requested)
        self.assertEqual(self.receipt_partitions(receipt, 'reused_partitions'), expected_reuse)
        self.assertEqual(self.receipt_partitions(receipt, 'ingested_partitions'), PARTITIONS - expected_reuse)
        self.assertEqual({(call.args[1], call.args[2]) for call in ingest.call_args_list},
                         PARTITIONS - expected_reuse)
        for engine, stage in expected_reuse:
            self.assertEqual(self.raw_partition(output, engine, stage), self.raw_partition(self.source, engine, stage))
        self.assertEqual(self.query(output, "SELECT name,native FROM inventory WHERE engine='grh' AND stage=3 AND id=2"),
                         [('middle-current', 'middle-current')])
        self.assertFalse((output / 'summary.json').exists())

    def test_all_reused_rows_keep_genuine_current_run_snapshot_and_comparison_identity(self):
        with patch.object(reader, 'ingest_snapshot', side_effect=AssertionError('eligible rows must be copied')) as ingest:
            output, receipt = self.seed()
        ingest.assert_not_called()
        self.assertEqual(self.receipt_partitions(receipt, 'reused_partitions'), PARTITIONS)
        self.assertEqual(receipt['ingested_partitions'], [])
        checkpoint = read_json(output / 'inputs.json')
        self.assertTrue(checkpoint['inventory_complete'])
        for key, value in reader.comparison_identity(self.current['grh'], self.current['gsim']).items():
            self.assertEqual(checkpoint[key], value)
        for engine in ENGINES:
            snapshots = checkpoint['snapshots'][engine]
            self.assertEqual({row['run_id'] for row in snapshots.values()}, {engine + '-current-run'})
            self.assertEqual({row['snapshot_id'] for row in snapshots.values()},
                             {f'{engine}-current-P{stage}' for stage in range(5)})
        self.assertEqual(read_json(output / 'seed-receipt.json'), receipt)

    def test_every_selected_table_body_including_footer_is_byte_sensitive(self):
        cases = (('grh', 'nodes.tsv'), ('grh', 'connections.tsv'), ('grh', 'node-endpoints.tsv'),
                 ('grh', 'bit-slices.tsv'), ('gsim', 'node-details.tsv'))
        for index, (engine, name) in enumerate(cases):
            with self.subTest(engine=engine, table=name):
                path = self.current[engine] / 'P0' / name
                original = path.read_bytes()
                # Trailing JSON whitespace is semantically harmless but is a real body-byte change.
                path.write_bytes(original[:-1] + b' \n')
                self.refresh_artifact(engine, 0, name)
                output, receipt = self.seed(output=f'body-miss-{index}', reuse={(engine, 0)})
                self.assertEqual(receipt['reused_partitions'], [])
                self.assertEqual(self.receipt_partitions(receipt, 'ingested_partitions'), PARTITIONS)
                self.assertEqual(self.raw_partition(output, engine, 0), self.raw_partition(self.source, engine, 0))
                path.write_bytes(original)
                self.refresh_artifact(engine, 0, name)

    def test_seed_receipt_binds_source_hash_and_declares_resume_cache_trust(self):
        before = self.source_stamp()
        expected_hash = file_hash(self.source / 'comparison.sqlite')
        output, receipt = self.seed()
        self.assertEqual(receipt['status'], 'seeded')
        self.assertEqual(receipt['source_database']['sha256'], expected_hash)
        self.assertEqual(receipt['source_database']['path'], str(self.source / 'comparison.sqlite'))
        self.assertEqual(receipt['source_database']['bytes'], (self.source / 'comparison.sqlite').stat().st_size)
        self.assertIs(receipt['independent_source_row_revalidation'], False)
        self.assertTrue(receipt['source_cache_trust'])
        self.assertEqual(before, self.source_stamp())
        self.assertEqual({path.name for path in output.iterdir()},
                         {'inputs.json', 'comparison.sqlite', 'seed-receipt.json'})
        self.assertNotEqual((output / 'comparison.sqlite').stat().st_ino,
                            (self.source / 'comparison.sqlite').stat().st_ino)

    def test_source_proof_and_derived_rows_are_not_copied(self):
        with closing(sqlite3.connect(self.source / 'comparison.sqlite')) as db:
            db.execute('INSERT INTO structural VALUES(?,?,?,?,?)',
                       (0, 1, 1, 'different', 'source-proof-must-not-be-copied'))
            db.execute('INSERT INTO differences VALUES(?,?,?,?,?,?,?,?)',
                       (0, 'structure', '["old-proof"]', 'both', 1, 1, 'old-proof', '{}'))
            db.execute('INSERT INTO pairs VALUES(?,?,?,?)', (9, 999, 999, 'source-derived-only'))
            db.commit()
        output, _ = self.seed()
        self.assertEqual(self.query(output, 'SELECT * FROM structural'), [])
        self.assertEqual(self.query(output, 'SELECT * FROM state_transfers'), [])
        self.assertEqual(self.query(output, "SELECT * FROM differences WHERE category='structure'"), [])
        self.assertEqual(self.query(output, 'SELECT count(*) FROM pairs'), [(15,)])

    def test_source_database_change_during_seed_leaves_checkpoint_incomplete(self):
        original_derive = reader.derive
        source_db = self.source / 'comparison.sqlite'

        def external_change_after_derivation(db):
            original_derive(db)
            info = source_db.stat()
            os.utime(source_db, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000000))

        with patch.object(reader, 'derive', side_effect=external_change_after_derivation):
            with self.assertRaisesRegex(ValueError, 'source database changed'):
                self.seed(output='changed-source')
        output = self.work / 'changed-source'
        self.assertFalse(read_json(output / 'inputs.json')['inventory_complete'])
        failed = read_json(output / 'seed-receipt.json')
        self.assertEqual(failed['status'], 'failed')
        self.assertNotEqual(failed['source_database']['stat_before'], failed['source_database']['stat_after'])
        self.assertFalse((output / 'summary.json').exists())

    def test_receipt_precedes_complete_checkpoint_and_final_publish_failure_is_incomplete(self):
        original_write = reader.write_json
        output = self.work / 'failed-final-seal'

        def fail_final_checkpoint(path, value):
            if path == output / 'inputs.json' and value.get('inventory_complete') is True:
                self.assertEqual(read_json(output / 'seed-receipt.json')['status'], 'seeded')
                self.assertFalse(read_json(output / 'inputs.json')['inventory_complete'])
                raise OSError('simulated final checkpoint publication failure')
            original_write(path, value)

        with patch.object(reader, 'write_json', side_effect=fail_final_checkpoint):
            with self.assertRaisesRegex(OSError, 'final checkpoint publication failure'):
                self.seed(output=output.name)
        self.assertFalse(read_json(output / 'inputs.json')['inventory_complete'])
        self.assertEqual(read_json(output / 'seed-receipt.json')['status'], 'failed')

    def test_source_completion_and_reader_identity_are_required_before_ingesting(self):
        original_summary = read_json(self.source / 'summary.json')
        original_checkpoint = read_json(self.source / 'inputs.json')
        for name in ('running-summary', 'incomplete-summary', 'incomplete-index', 'different-reader'):
            with self.subTest(case=name):
                summary, checkpoint = deepcopy(original_summary), deepcopy(original_checkpoint)
                if name == 'running-summary':
                    summary['status'] = 'running'
                elif name == 'incomplete-summary':
                    summary['complete'] = False
                elif name == 'incomplete-index':
                    checkpoint['inventory_complete'] = False
                else:
                    checkpoint['proof_implementation']['semantic_bitvector.py'] = '0' * 64
                write_json(self.source / 'summary.json', summary)
                write_json(self.source / 'inputs.json', checkpoint)
                with patch.object(reader, 'ingest_snapshot') as ingest:
                    with self.assertRaises(ValueError):
                        self.seed(output=name)
                ingest.assert_not_called()
                self.assertFalse((self.work / name / 'seed-receipt.json').exists())
        write_json(self.source / 'summary.json', original_summary)
        write_json(self.source / 'inputs.json', original_checkpoint)

    def test_sqlite_sidecars_are_rejected_without_touching_source_database(self):
        before = file_hash(self.source / 'comparison.sqlite')
        for index, suffix in enumerate(('-wal', '-shm', '-journal')):
            with self.subTest(sidecar=suffix):
                path = self.source / ('comparison.sqlite' + suffix)
                path.touch()
                with patch.object(reader, 'ingest_snapshot') as ingest:
                    with self.assertRaises(ValueError):
                        self.seed(output=f'sidecar-{index}')
                ingest.assert_not_called()
                self.assertEqual(before, file_hash(self.source / 'comparison.sqlite'))
                self.assertTrue(path.exists())
                path.unlink()

    def test_current_and_original_full_file_hashes_are_rechecked(self):
        for index, original in enumerate((False, True)):
            with self.subTest(original_source=original):
                directory = (self.original if original else self.current)['grh']
                path = directory / 'P0/nodes.tsv'
                contents = path.read_bytes()
                path.write_bytes(contents + b'\n')
                with self.assertRaises(ValueError):
                    self.seed(output=f'unfrozen-{index}', reuse={('grh', 0)})
                self.assertFalse((self.work / f'unfrozen-{index}' / 'seed-receipt.json').exists())
                path.write_bytes(contents)

    def test_reused_metadata_still_enforces_one_current_run_and_distinct_snapshots(self):
        cases = ({'run_id': 'another-current-run'}, {'snapshot_id': 'grh-current-P0'})
        for index, updates in enumerate(cases):
            with self.subTest(metadata=updates):
                self.replace_metadata('grh', 1, updates)
                with self.assertRaises(ValueError):
                    self.seed(output=f'bad-current-identity-{index}')
                self.assertFalse((self.work / f'bad-current-identity-{index}' / 'seed-receipt.json').exists())
                self.replace_metadata('grh', 1, {'run_id': 'grh-current-run', 'snapshot_id': 'grh-current-P1'})

    def test_reused_metadata_cannot_hide_wrong_engine_or_typed_schema(self):
        cases = (('nodes.tsv', {'engine': 'gsim'}),
                 ('node-endpoints.tsv', {'schema': 'grh.semantic-node-endpoints.v999'}))
        for index, (name, updates) in enumerate(cases):
            with self.subTest(table=name):
                path = self.current['grh'] / 'P0' / name
                contents = path.read_bytes()
                self.replace_metadata('grh', 0, updates, names=[name])
                with self.assertRaises(ValueError):
                    self.seed(output=f'bad-current-meta-{index}', reuse={('grh', 0)})
                self.assertFalse((self.work / f'bad-current-meta-{index}' / 'seed-receipt.json').exists())
                path.write_bytes(contents)
                self.refresh_artifact('grh', 0, name)

    def test_existing_output_preserves_user_files(self):
        output = self.work / 'already-exists'
        output.mkdir()
        sentinel = output / 'sentinel.txt'
        sentinel.write_text('keep task data\n')
        with self.assertRaises(ValueError):
            self.seed(output=output.name)
        self.assertEqual(sentinel.read_text(), 'keep task data\n')
        self.assertEqual({path.name for path in output.iterdir()}, {'sentinel.txt'})

    def test_locked_reader_resume_proof_matches_fresh_current_comparison(self):
        output, _ = self.seed()
        resumed = reader.compare(self.current['grh'], self.current['gsim'], output,
                                 resume=True, selected_stages={0}, node_limit=2)
        fresh_output = self.work / 'fresh-current-comparison'
        fresh = reader.compare(self.current['grh'], self.current['gsim'], fresh_output,
                               selected_stages={0}, node_limit=2)
        for table in ('inventory', 'connections', 'endpoints', 'details', 'slices', 'pairs', 'types',
                      'structural', 'structural_diagnoses', 'anchor_proofs', 'state_transfers'):
            self.assertEqual(sorted(self.query(output, 'SELECT * FROM ' + table), key=repr),
                             sorted(self.query(fresh_output, 'SELECT * FROM ' + table), key=repr), table)
        sql = 'SELECT stage,category,key,engine,grh,gsim,reason FROM differences'
        self.assertEqual(sorted(self.query(output, sql), key=repr), sorted(self.query(fresh_output, sql), key=repr))
        self.assertEqual(resumed['snapshots'], fresh['snapshots'])
        self.assertEqual(resumed['semantic_acceptance'], fresh['semantic_acceptance'])
        left, right = resumed['boundaries']['P0']['structure'], fresh['boundaries']['P0']['structure']
        for field in ('status', 'counts', 'paired_nodes', 'compared_nodes', 'unprocessed_nodes'):
            self.assertEqual(left[field], right[field], field)
        self.assertEqual(left['compared_nodes'], 2)
        self.assertEqual(resumed['boundaries']['P1']['structure']['status'], 'not_requested')


if __name__ == '__main__':
    unittest.main()
