"""Indexed small inventories check direct native lineage classifications."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import inspect_f30_alignment_cases as inspect_cases
from export_f29_full_split_exchange import name_comparison_metadata
from inspect_f30_alignment_cases import ENGINES, PHASES, Inspector
from semantic_node_exchange import encode_cell


class AlignmentCaseTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        for phase in PHASES:
            for engine in ENGINES:
                prefix = phase + '_' + engine
                self.db.execute(f'CREATE TABLE {prefix}_nodes('
                    'id INTEGER PRIMARY KEY,path TEXT,path_json TEXT,native_name TEXT)')
                self.db.execute(f'CREATE TABLE {prefix}_names('
                    'path TEXT PRIMARY KEY,node_id INTEGER,occurrences INTEGER)')
        self.db.executescript('''
            CREATE TABLE lineage(engine,stage,parent,child,relation,coordinates);
            CREATE INDEX lineage_parent ON lineage(engine,parent);
            CREATE INDEX lineage_child ON lineage(engine,child);
            CREATE TABLE decisions(engine,stage,node_id,ordinal,pass,outcome,reason,
                blockers,update_ordinal,axis,detail);
            CREATE INDEX decision_node ON decisions(engine,node_id);
        ''')

    def node(self, engine, identifier, path, phases=('after',)):
        for phase in phases:
            self.db.execute(f'INSERT INTO {phase}_{engine}_nodes VALUES(?,?,?,?)',
                (identifier, path, json.dumps([path]), path))

    def link(self, engine, parent, child, coordinates):
        self.db.execute('INSERT INTO lineage VALUES(?,?,?,?,?,?)',
            (engine, 'split', parent, child, 'split', json.dumps(coordinates)))

    def parents(self, own_alive=False, peer_alive=False):
        self.node('grh', 1, 'top.a', ('pre_comb', 'before') + (('after',) if own_alive else ()))
        self.node('gsim', 101, 'top.a', ('pre_comb', 'before') + (('after',) if peer_alive else ()))

    def member(self, engine, parent, child, path, coordinates):
        self.node(engine, child, path)
        self.link(engine, parent, child, coordinates)

    def inspector(self, limit=4096):
        for phase in PHASES:
            for engine in ENGINES:
                prefix = phase + '_' + engine
                self.db.execute(f'DELETE FROM {prefix}_names')
                self.db.execute(f'INSERT INTO {prefix}_names '
                    f'SELECT path,MIN(id),COUNT(*) FROM {prefix}_nodes '
                    'WHERE path IS NOT NULL GROUP BY path')
        return Inspector(self.db, limit)

    def classify(self, engine, identifier, path, limit=4096):
        result = self.inspector(limit).classify(
            engine, identifier, path, 'missing_normalized_path_on_peer')
        self.assertTrue({'category', 'path_pattern', 'parent_id', 'peer_parent_id',
                         'peer_candidate_ids'}.issubset(result))
        return result

    def test_baseline_original_and_when_source_pattern(self):
        path = 'top.when@source.fir:12:3'
        self.node('grh', 1, path, PHASES)
        result = self.classify('grh', 1, path)
        self.assertEqual(result['category'], 'baseline_original_without_unique_public_peer')
        self.assertEqual(result['path_pattern'], 'when_at_leaf')
        self.assertEqual(result['peer_candidate_ids'], [])

    def test_live_parent_peer_split_and_residual_parent(self):
        self.parents(own_alive=True)
        self.member('gsim', 101, 102, 'top.a_0', [0])
        result = self.classify('grh', 1, 'top.a')
        self.assertEqual(result['category'], 'live_parent_unsplit_peer_split')
        self.assertEqual((result['parent_id'], result['peer_parent_id']), (1, 101))
        self.member('grh', 1, 2, 'top.a_residual_0', [0])
        result = self.classify('grh', 1, 'top.a')
        self.assertEqual(result['category'], 'live_parent_with_members_peer_retired')
        self.node('gsim', 101, 'top.a')
        result = self.classify('grh', 1, 'top.a')
        self.assertEqual(result['category'], 'live_parent_with_members_peer_alive')

    def test_reverse_split_member_peer_parent_retained(self):
        self.parents(peer_alive=True)
        self.member('grh', 1, 2, 'top.a_0', [0])
        result = self.classify('grh', 2, 'top.a_0')
        self.assertEqual(result['category'], 'split_member_peer_parent_retained')
        self.assertEqual((result['parent_id'], result['peer_parent_id']), (1, 101))

    def test_exact_multidimensional_coordinate_name_difference_and_ambiguity(self):
        self.parents()
        self.member('grh', 1, 2, 'top.a_1', [0, 1])
        self.member('gsim', 101, 102, 'top.a_0_1', [0, 1])
        result = self.classify('grh', 2, 'top.a_1')
        self.assertEqual(result['category'], 'split_member_same_coordinate_name_difference')
        self.assertEqual(result['peer_candidate_ids'], [102])
        self.node('gsim', 103, 'top.a_0_1')
        result = self.classify('grh', 2, 'top.a_1')
        self.assertEqual(result['category'], 'split_member_same_coordinate_name_ambiguous')
        self.assertEqual(result['peer_candidate_ids'], [102])
        self.link('gsim', 101, 103, [0, 1])
        result = self.classify('grh', 2, 'top.a_1')
        self.assertEqual(result['category'], 'split_member_coordinate_ambiguous')
        self.assertEqual(sorted(result['peer_candidate_ids']), [102, 103])

    def test_coordinate_rank_is_not_guessed_and_parent_requires_unique_peer(self):
        self.parents()
        self.member('gsim', 101, 102, 'top.a_1', [1])
        self.member('grh', 1, 2, 'top.a_0_1', [0, 1])
        result = self.classify('gsim', 102, 'top.a_1')
        self.assertEqual(result['category'], 'split_member_without_peer_coordinates')
        self.assertEqual(result['peer_candidate_ids'], [])
        self.node('grh', 3, 'top.a', ('pre_comb',))
        result = self.classify('gsim', 102, 'top.a_1')
        self.assertEqual(result['category'], 'split_member_parent_without_unique_public_peer')

    def test_truncated_group_does_not_claim_a_complete_classification(self):
        self.parents(own_alive=True)
        for child in (102, 103):
            self.member('gsim', 101, child, 'top.a_' + str(child), [child])
        self.assertEqual(self.classify('grh', 1, 'top.a', limit=1)['category'], 'other_unresolved')

    def test_common_live_parents_without_split_remain_unresolved(self):
        self.parents(own_alive=True, peer_alive=True)
        self.assertEqual(self.classify('grh', 1, 'top.a')['category'], 'other_unresolved')

    def test_missing_coordinates_on_either_member_remain_unresolved(self):
        self.parents()
        self.member('grh', 1, 2, 'top.a_0', [0])
        self.member('gsim', 101, 102, 'top.a_peer_0', [0])
        for engine in ENGINES:
            for coordinates in (None, 'null', '[]'):
                with self.subTest(engine=engine, coordinates=coordinates):
                    self.db.execute("UPDATE lineage SET coordinates='[0]'")
                    self.db.execute('UPDATE lineage SET coordinates=? WHERE engine=?', (coordinates, engine))
                    self.assertEqual(self.classify('grh', 2, 'top.a_0')['category'], 'other_unresolved')

    def test_derive_successor_is_retained_as_evidence_but_not_a_split_member(self):
        self.parents(own_alive=True)
        self.member('grh', 1, 2, 'top.a_derived', [0])
        self.db.execute("UPDATE lineage SET relation='derive'")
        self.member('gsim', 101, 102, 'top.a_peer_0', [0])
        children = self.inspector().children('grh', 1)
        self.assertEqual((children['live_children'], len(children['records'])), (0, 1))
        self.assertEqual(self.classify('grh', 1, 'top.a')['category'], 'live_parent_unsplit_peer_split')
        self.assertEqual(self.classify('grh', 2, 'top.a_derived')['category'], 'other_unresolved')

    def test_missing_direct_precomb_parent_does_not_compose_lineage(self):
        self.parents()
        self.member('grh', 1, 2, 'top.a_middle', [0])
        self.member('grh', 2, 3, 'top.a_final', [1])
        self.member('gsim', 101, 102, 'top.a_0_1', [0, 1])
        result = self.classify('grh', 3, 'top.a_final')
        self.assertEqual(result['category'], 'other_unresolved')
        self.assertEqual(result['peer_candidate_ids'], [])

    def test_all_lookup_plans_use_existing_indexes(self):
        plans = self.inspector().plans()
        self.assertEqual(len(plans), 2 * len(PHASES) * len(ENGINES) + 3)
        for name, rows in plans.items():
            with self.subTest(query=name):
                self.assertTrue(any('SEARCH ' in row[3].upper() for row in rows))
                self.assertFalse(any('SCAN ' in row[3].upper() for row in rows))

    def stream_fixture(self):
        root = inspect_cases.ROOT / 'ptmp/firrtl-ingest/F30/inspection-contract'
        root.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(temporary.cleanup)
        source, output = Path(temporary.name) / 'analysis', Path(temporary.name) / 'inspection'
        source.mkdir()
        rows = [('grh', 1, 'top.when@source.fir:12:3'), ('gsim', 101, 'top.$storage')]
        for engine, identifier, path in rows:
            self.node(engine, identifier, path, PHASES)
        self.inspector()
        self.db.commit()
        with sqlite3.connect(source / 'analysis.sqlite') as target:
            self.db.backup(target)
        reason = 'missing_normalized_path_on_peer'
        metadata = {'schema': 'wolvrix.f29.node-name-candidates.v1', 'phase': 'after',
            'grh_stage': 'after:split-static-array', 'gsim_stage': 'after:splitArray', **name_comparison_metadata()}
        with (source / 'after.unmatched.tsv').open('w', encoding='utf-8') as stream:
            stream.write('#meta\t' + json.dumps(metadata) + '\n' + '\t'.join(inspect_cases.UNMATCHED_COLUMNS) + '\n')
            for engine, identifier, path in rows:
                row = (engine, identifier, path, json.dumps([path]), path, reason, 1, 0)
                stream.write('\t'.join(encode_cell(value) for value in row) + '\n')
            stream.write('#footer\t' + json.dumps({'complete': True, 'rowCount': 2}) + '\n')
        summary = {'schema': 'wolvrix.f30.native-alignment-analysis.v1', 'complete': True,
            'input_sha256': 'a' * 64, 'comparison': {'after': {'complete': True,
                'unmatched_file': str(source / 'after.unmatched.tsv'),
                'grh_stage': metadata['grh_stage'], 'gsim_stage': metadata['gsim_stage'],
                'grh_unmatched_nodes': 1, 'gsim_unmatched_nodes': 1, 'unmatched_reasons': {reason: 2}}}}
        (source / 'summary.json').write_text(json.dumps(summary), encoding='utf-8')
        return source, output, summary

    def run_stream(self, source, output):
        with patch('sys.argv', ['inspect-f30', '--analysis', str(source), '--output', str(output), '--all-unmatched']), \
                redirect_stdout(io.StringIO()):
            inspect_cases.main()

    def test_stream_counts_both_engines_before_publishing_completed_files(self):
        source, output, _ = self.stream_fixture()
        self.run_stream(source, output)
        report = json.loads((output / 'summary.json').read_text())
        self.assertTrue(report['complete'])
        self.assertEqual(report['all_unmatched']['rows'], {'grh': 1, 'gsim': 1})
        for engine in ENGINES:
            final = output / (engine + '.unmatched.tsv')
            footer = json.loads(final.read_text().splitlines()[-1].split('\t', 1)[1])
            self.assertEqual(footer, {'complete': True, 'rowCount': 1})
            self.assertFalse((output / (engine + '.unmatched.pending')).exists())

    def test_stream_count_mismatch_keeps_pending_and_publishes_no_final_evidence(self):
        source, output, summary = self.stream_fixture()
        summary['comparison']['after']['grh_unmatched_nodes'] = 2
        (source / 'summary.json').write_text(json.dumps(summary), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'counts'):
            self.run_stream(source, output)
        self.assertFalse((output / 'summary.json').exists())
        for engine in ENGINES:
            self.assertFalse((output / (engine + '.unmatched.tsv')).exists())
            pending = output / (engine + '.unmatched.pending')
            self.assertTrue(pending.exists())
            self.assertNotIn('#footer\t', pending.read_text())

    def test_selected_member_detects_same_name_candidate_from_another_original_family(self):
        self.parents()
        for engine, identifier in (('grh', 4), ('gsim', 104)):
            self.node(engine, identifier, 'top.b', ('pre_comb', 'before'))
        self.member('grh', 1, 2, 'top.a_0', [0])
        self.member('gsim', 101, 102, 'top.a_0_0', [0])
        self.member('grh', 4, 5, 'top.a_0_0', [1])
        result = self.inspector().inspect('grh', 2)['identity_conflicts']
        self.assertEqual(result['status'], 'structural_identity_conflict')
        conflict = next(check for check in result['checks'] if check.get('candidate_node_id') == 5)
        self.assertEqual(conflict['status'], 'structural_identity_conflict')
        self.assertEqual(conflict['candidate_identity']['pre_comb_anchor']['path'], 'top.b')
        self.assertEqual(conflict['candidate_identity']['coordinates'], [1])

    def test_candidate_without_unique_complete_origin_is_only_collision_risk(self):
        self.parents()
        for engine, identifier in (('grh', 4), ('gsim', 104)):
            self.node(engine, identifier, 'top.b', ('pre_comb', 'before'))
        self.member('grh', 1, 2, 'top.a_0', [0])
        self.member('gsim', 101, 102, 'top.a_0_0', [0])
        self.node('grh', 5, 'top.a_0_0')
        for coordinates in ('missing-origin', None, 'null', '[]'):
            with self.subTest(coordinates=coordinates):
                self.db.execute("DELETE FROM lineage WHERE engine='grh' AND child=5")
                if coordinates != 'missing-origin':
                    self.db.execute('INSERT INTO lineage VALUES(?,?,?,?,?,?)',
                        ('grh', 'split', 4, 5, 'split', coordinates))
                result = self.inspector().inspect('grh', 2)['identity_conflicts']
                self.assertEqual(result['status'], 'collision_risk')
                self.assertFalse(any(check['status'] == 'structural_identity_conflict' for check in result['checks']))
        self.node('grh', 6, 'top.a_0_0')
        result = self.inspector().inspect('grh', 2)['identity_conflicts']
        self.assertNotEqual(result['status'], 'structural_identity_conflict')
        self.assertTrue(all(check['status'] == 'no_unique_name_candidate' for check in result['checks']))

    def test_renamed_original_conflicts_with_another_parents_split_member(self):
        self.parents(own_alive=True, peer_alive=True)
        self.db.execute("UPDATE after_gsim_nodes SET path='top.a_0' WHERE id=101")
        for engine, identifier in (('grh', 4), ('gsim', 104)):
            self.node(engine, identifier, 'top.b', ('pre_comb', 'before'))
        self.member('gsim', 104, 102, 'top.a', [1])
        result = self.inspector().inspect('gsim', 101)['identity_conflicts']
        self.assertEqual(result['status'], 'structural_identity_conflict')
        self.assertEqual(result['pair_basis'], 'stable_original_ids')
        conflict = next(check for check in result['checks'] if check.get('candidate_node_id') == 102)
        self.assertEqual(conflict['expected_peer_node_id'], 101)
        self.assertEqual(conflict['candidate_identity']['pre_comb_anchor']['path'], 'top.b')
        self.assertEqual(conflict['candidate_identity']['coordinates'], [1])

    def test_renamed_original_conflicts_with_a_different_original_identity(self):
        self.parents(own_alive=True, peer_alive=True)
        self.db.execute("UPDATE after_gsim_nodes SET path='top.a_0' WHERE id=101")
        for engine, identifier in (('grh', 4), ('gsim', 104)):
            self.node(engine, identifier, 'top.b', PHASES)
        self.db.execute("UPDATE after_gsim_nodes SET path='top.a' WHERE id=104")
        result = self.inspector().inspect('gsim', 101)['identity_conflicts']
        self.assertEqual(result['status'], 'structural_identity_conflict')
        conflict = next(check for check in result['checks'] if check.get('candidate_node_id') == 104)
        self.assertEqual(conflict['candidate_identity']['kind'], 'pre_comb_original')
        self.assertEqual(conflict['candidate_identity']['pre_comb_anchor']['path'], 'top.b')

    def test_renamed_original_ambiguous_or_incomplete_evidence_stays_conservative(self):
        self.parents(own_alive=True, peer_alive=True)
        self.db.execute("UPDATE after_gsim_nodes SET path='top.a_0' WHERE id=101")
        self.node('gsim', 102, 'top.a')
        result = self.inspector().inspect('gsim', 101)['identity_conflicts']
        self.assertEqual(result['status'], 'collision_risk')
        self.node('gsim', 103, 'top.a')
        result = self.inspector().inspect('gsim', 101)['identity_conflicts']
        self.assertEqual(result['status'], 'no_unique_name_collision')
        self.node('grh', 3, 'top.a', ('pre_comb',))
        result = self.inspector().inspect('gsim', 101)['identity_conflicts']
        self.assertEqual(result['status'], 'not_assessable')


if __name__ == '__main__':
    unittest.main()
