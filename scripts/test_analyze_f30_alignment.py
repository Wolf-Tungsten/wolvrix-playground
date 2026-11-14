"""Small native exchange fixtures exercise F30 reports without ingesting a design."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import analyze_f30_alignment as analysis
import test_semantic_node_exchange as exchange
from semantic_node_exchange import verify_bundle


class AlignmentAnalysisTests(unittest.TestCase):
    def setUp(self):
        root = analysis.ROOT / 'ptmp' / 'firrtl-ingest' / 'F30' / 'alignment-contract'
        root.mkdir(parents=True, exist_ok=True)
        self.work = tempfile.TemporaryDirectory(dir=root)
        self.directory = Path(self.work.name)
        self.comb = self.directory / 'comb'
        self.split = self.directory / 'split'
        self.gsim_work = self.directory / 'gsim'
        self.gsim_work.mkdir()
        self.make_bundle(self.comb, 'grh', False, 'comb-loop-elim')
        self.make_bundle(self.split, 'grh', True, 'split-static-array', decisions=[{
            'object_id': 2, 'reason': 'static_update_projection', 'detail_json': {
                'pass': 'split-static-array', 'outcome': 'replace', 'blocker_node_ids': [1],
                'update_ordinal': 0, 'axis': 0}}])
        self.make_bundle(self.gsim_work / 'gsim-split', 'gsim', False, 'splitArray')
        verified = verify_bundle(self.gsim_work / 'gsim-split', self.gsim_work / 'gsim-split.sqlite')
        (self.gsim_work / 'summary.json').write_text(json.dumps({
            'input': {'sha256': '1' * 64}, 'gsim_verification': verified, 'complete': True}))

    def tearDown(self):
        self.work.cleanup()

    def make_bundle(self, directory, engine, split, pass_name, decisions=()):
        writer = exchange.ExchangeContractTests()
        writer.setUp()
        temporary = writer.directory
        try:
            directory.mkdir(parents=True)
            writer.directory = directory
            writer.identity.update(engine=engine, run_id='grh-run' if engine == 'grh' else 'gsim-run',
                root_name='top', input_sha256='1' * 64)
            if not split:
                writer.after_nodes, writer.after_edges, writer.events = writer.before_nodes, writer.before_edges, []
            writer.decisions = deepcopy(decisions)
            writer.write()
            writer.rows[0]['detail_json']['pass'] = pass_name
            writer.write_rows()
        finally:
            shutil.rmtree(temporary)

    def test_full_replay_ratios_native_decisions_and_parent_blockers(self):
        output = self.directory / 'analysis'
        report = analysis.analyze(self.comb, self.split, self.gsim_work, output)
        self.assertTrue(report['complete'])
        self.assertEqual(report['verification_workers'], 3)
        self.assertTrue(report['grh_continuity']['exact'])
        self.assertEqual(report['comparison']['before']['grh_node_candidate_ratio'], 1)
        after = report['comparison']['after']
        self.assertEqual((after['grh_nodes'], after['gsim_nodes'], after['unique_name_candidates']), (4, 3, 2))
        self.assertEqual(after['grh_node_candidate_ratio'], 0.5)
        self.assertEqual(report['decision_count'], 1)
        self.assertEqual(report['unmatched_categories'], {'grh_split_gsim_retained': 2})
        text = (output / 'unmatched-reasons.tsv').read_text()
        self.assertIn('static_update_projection', text)
        self.assertIn('blocker_nodes_json', text)
        self.assertIn('input', text)
        self.assertFalse(report['gsim_source_evidence']['reused'])
        self.assertTrue((output / 'gsim-verification-cache.json').is_file())

    def test_old_database_with_same_counts_cannot_replace_a_fresh_native_replay(self):
        with sqlite3.connect(self.gsim_work / 'gsim-split.sqlite') as db:
            body = json.loads(db.execute('SELECT body FROM after_nodes WHERE id=2').fetchone()[0])
            body['native_name'] = 'corrupted'
            db.execute('UPDATE after_nodes SET body=? WHERE id=2', (json.dumps(body),))
        output = self.directory / 'reverified'
        report = analysis.analyze(self.comb, self.split, self.gsim_work, output, verification_workers=1)
        self.assertEqual(report['verification_workers'], 1)
        self.assertFalse(report['gsim_source_evidence']['reused'])
        with sqlite3.connect(output / 'gsim-split.sqlite') as db:
            value = json.loads(db.execute('SELECT body FROM after_nodes WHERE id=2').fetchone()[0])
        self.assertEqual(value['native_name'], 'a')

    def test_verified_cache_requires_file_and_database_hashes(self):
        first = self.directory / 'first'
        analysis.analyze(self.comb, self.split, self.gsim_work, first, verification_workers=1)
        second = self.directory / 'second'
        second.mkdir()
        with patch.object(analysis, 'verify_bundle', wraps=verify_bundle) as replay:
            database, verified, evidence = analysis.verified_gsim(first, second)
            self.assertEqual(replay.call_count, 0)
        self.assertTrue(evidence['reused'])
        self.assertTrue(verified['replay_exact'])
        with sqlite3.connect(database) as db:
            db.execute("UPDATE after_nodes SET body=replace(body,'input','tampered') WHERE id=1")
        third = self.directory / 'third'
        third.mkdir()
        with patch.object(analysis, 'verify_bundle', wraps=verify_bundle) as replay:
            _, _, evidence = analysis.verified_gsim(first, third)
            self.assertEqual(replay.call_count, 1)
        self.assertFalse(evidence['reused'])

    def test_continuity_and_input_mismatches_reject_partial_report(self):
        path = self.split / 'before.nodes.tsv'
        content = path.read_text()
        path.write_text(content.replace('a\n', 'wrong\n'))
        rejected = self.directory / 'bad-continuity'
        with self.assertRaises(ValueError):
            analysis.analyze(self.comb, self.split, self.gsim_work, rejected, verification_workers=1)
        report = json.loads((rejected / 'summary.json').read_text())
        self.assertFalse(report['complete'])
        self.assertTrue(report['failed'])
        self.assertEqual([failure['input'] for failure in report['verification_failures']], ['grh-split'])
        self.assertTrue((rejected / 'grh-comb.sqlite').is_file())
        self.assertTrue((rejected / 'gsim-verification-cache.json').is_file())
        path.write_text(content)
        evolution = self.gsim_work / 'gsim-split/evolution.tsv'
        evolution.write_text(evolution.read_text().replace('1' * 64, '2' * 64))
        with self.assertRaisesRegex(ValueError, 'different FIRRTL inputs'):
            analysis.analyze(self.comb, self.split, self.gsim_work, self.directory / 'bad-input', verification_workers=1)

    def interrupted_report(self, output, report):
        report = deepcopy(report)
        report['complete'] = False
        for field in ('decision_count', 'decision_breakdown', 'unmatched_categories', 'unmatched_decision_reason_occurrences'):
            report.pop(field, None)
        (output / 'summary.json').write_text(json.dumps(report))
        (output / 'unmatched-reasons.pending').write_bytes(b'interrupted partial explanation\n')
        return report

    def test_resume_is_read_only_reuses_proofs_and_preserves_duplicate_decisions(self):
        split = self.directory / 'split-duplicates'
        decision = {'object_id': 2, 'reason': 'static_update_projection', 'detail_json': {
            'pass': 'split-static-array', 'outcome': 'replace', 'blocker_node_ids': [1],
            'update_ordinal': 0, 'axis': 0}}
        self.make_bundle(split, 'grh', True, 'split-static-array', decisions=[decision, decision])
        output = self.directory / 'resumed'
        original = analysis.analyze(self.comb, split, self.gsim_work, output, verification_workers=1)
        expected = (output / 'unmatched-reasons.tsv').read_bytes()
        decisions = (output / 'decisions.tsv').read_bytes()
        database = (output / 'analysis.sqlite').read_bytes()
        before = self.interrupted_report(output, original)
        exporter = analysis.export_decisions_and_reasons

        def read_only_export(db, *args, **kwargs):
            with self.assertRaises(sqlite3.OperationalError):
                db.execute('DELETE FROM decisions')
            return exporter(db, *args, **kwargs)

        with patch.object(analysis, 'verify_bundle', side_effect=AssertionError('no native replay')), \
                patch.object(analysis, 'load_nodes', side_effect=AssertionError('no inventory import')), \
                patch.object(analysis, 'compare_phase', side_effect=AssertionError('no name comparison')), \
                patch.object(analysis, 'public_compare', side_effect=AssertionError('no connection comparison')), \
                patch.object(analysis, 'export_decisions_and_reasons', side_effect=read_only_export):
            report = analysis.resume_export(output)
        self.assertTrue(report['complete'])
        self.assertEqual(report['decision_count'], 2)
        self.assertEqual(report['unmatched_decision_reason_occurrences'], {'static_update_projection': 4})
        self.assertEqual((output / 'unmatched-reasons.tsv').read_bytes(), expected)
        self.assertEqual((output / 'decisions.tsv').read_bytes(), decisions)
        self.assertEqual((output / 'analysis.sqlite').read_bytes(), database)
        self.assertEqual(json.loads((output / 'summary.before-resume-1.json').read_text()), before)
        self.assertEqual((output / 'unmatched-reasons.interrupted-1.pending').read_bytes(), b'interrupted partial explanation\n')
        self.assertFalse(report['resume_export']['native_replay_repeated'])
        with self.assertRaisesRegex(ValueError, 'completed native replay'):
            analysis.resume_export(output)

    def test_resume_rejects_incomplete_proof_tsv_and_imports_without_overwriting_summary(self):
        output = self.directory / 'reject-resume'
        completed = analysis.analyze(self.comb, self.split, self.gsim_work, output, verification_workers=1)
        report = self.interrupted_report(output, completed)
        invalid = deepcopy(report)
        invalid['grh_verification']['grh-split']['replay_exact'] = False
        summary = output / 'summary.json'
        summary.write_text(json.dumps(invalid))
        with self.assertRaisesRegex(ValueError, 'three completed exact'):
            analysis.resume_export(output)
        self.assertEqual(json.loads(summary.read_text()), invalid)
        summary.write_text(json.dumps(report))
        path = output / 'after.unmatched.tsv'
        text = path.read_text()
        path.write_text(text[:text.rfind('#footer\t')])
        with self.assertRaisesRegex(ValueError, 'incomplete TSV footer'):
            analysis.resume_export(output)
        self.assertEqual(json.loads(summary.read_text()), report)
        path.write_text(text)
        with sqlite3.connect(output / 'analysis.sqlite') as db:
            db.execute('DELETE FROM decisions')
        with self.assertRaisesRegex(ValueError, 'imported native trace count'):
            analysis.resume_export(output)
        self.assertEqual(json.loads(summary.read_text()), report)
        self.assertFalse((output / 'summary.before-resume-1.json').exists())
        self.assertTrue((output / 'unmatched-reasons.pending').exists())

    def test_recursive_ancestors_use_both_index_columns_and_keep_merge_cycle_semantics(self):
        with sqlite3.connect(':memory:') as db:
            db.executescript('CREATE TABLE lineage(engine,stage,parent,child,relation,coordinates); '
                             'CREATE INDEX lineage_child ON lineage(engine,child);')
            db.executemany('INSERT INTO lineage VALUES(?,?,?,?,?,?)', [
                ('grh', 'split', 1, 3, 'split', '[0]'), ('grh', 'split', 2, 3, 'split', '[0]'),
                ('grh', 'split', 3, 4, 'split', '[0]'), ('grh', 'split', 4, 3, 'split', '[0]'),
                ('gsim', 'split', 99, 3, 'split', '[0]')])
            for identifier in (1, 3, 4, 999):
                self.assertEqual(db.execute(analysis.ANCESTOR_QUERY, (identifier,)).fetchall(),
                                 db.execute(analysis.LEGACY_ANCESTOR_QUERY, (identifier,)).fetchall())
            self.assertEqual(db.execute(analysis.ANCESTOR_QUERY, (4,)).fetchall(), [(1,), (2,), (3,), (4,)])
            plan = [row[3] for row in db.execute('EXPLAIN QUERY PLAN ' + analysis.ANCESTOR_QUERY, (4,))]
            self.assertTrue(any('lineage_child (engine=? AND child=?)' in row for row in plan), plan)

    def test_unmatched_input_validates_stage_reason_and_footer(self):
        output = self.directory / 'invalid-unmatched'
        report = analysis.analyze(self.comb, self.split, self.gsim_work, output, verification_workers=1)
        path = output / 'after.unmatched.tsv'
        original = path.read_text()
        for bad, expected in ((original.replace('"phase":"after"', '"phase":"before"'), 'identity'),
                              (original.replace('missing_normalized_path_on_peer', 'unknown_reason'), 'engine/reason'),
                              (original[:original.rfind('#footer\t')], 'footer')):
            with self.subTest(expected=expected):
                path.write_text(bad)
                with self.assertRaisesRegex(ValueError, expected):
                    list(analysis.unmatched_grh_rows(output, report))
        path.write_text(original)
        self.assertEqual(len(list(analysis.unmatched_grh_rows(output, report))), 2)


if __name__ == '__main__':
    unittest.main()
