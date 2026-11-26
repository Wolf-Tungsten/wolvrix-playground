from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from benchmark_f29_pass_trace import sha256
from capture_f35_pipeline import capture_lock
from f35_trace_samples import alias_trace, bundle_evidence, evolution, explicit_samples, finish_representatives, gsim_bridges, recheck_pass
from semantic_node_exchange import HEADERS
from test_f35_compare import node, write_table


ROOT = Path(__file__).resolve().parents[1]
LEGACY_TRACE = ROOT / 'ptmp/firrtl-ingest/F34/pass-trace/verified-gsim-mutations'


class TraceSamplesTest(unittest.TestCase):
    def test_capture_replacement_excludes_sample_queries(self):
        with TemporaryDirectory() as temporary, patch('capture_f35_pipeline.WORK', Path(temporary)):
            with capture_lock('grh', read_only=True), capture_lock('grh', read_only=True):
                with self.assertRaisesRegex(ValueError, 'capture files are in use'), capture_lock('grh'):
                    self.fail('capture acquired a lock held by readers')
            with capture_lock('grh'):
                with self.assertRaisesRegex(ValueError, 'capture files are in use'), capture_lock('grh', read_only=True):
                    self.fail('sample query acquired a lock held by the capture')

    def test_evolution_selects_exact_nodes_and_nested_reference_fields(self):
        with TemporaryDirectory() as temporary:
            trace = Path(temporary) / 'evolution.tsv'
            trace.write_text('\n'.join([
                '\t'.join(HEADERS['evolution']),
                'event\t0\t0\treplace\tfixture\t\\N\t\\N\t\\N\t{}',
                'decision\t0\t1\tretain\tfixture\tnode\tbefore\t120\t{}',
                'decision\t0\t2\tretain\tfixture\tnode\tbefore\t12\t{}',
                'mutation\t0\t3\treplace\tfixture\toperand\ttransition\t88\t{"owner_node_ids":[120,12]}',
                'edit\t0\t4\tadd\tfixture\tconnection\tafter\t89\t{"source_node_id":120,"target_node_id":121}',
                'lineage\t0\t5\t\\N\t\\N\tnode\tbefore\t10\t{"to_node_id":12,"relation":"merge"}',
                'footer\t0\t6\t\\N\t\\N\t\\N\t\\N\t\\N\t{"complete":true,"replayComplete":true}',
            ]) + '\n')
            report, related = evolution(trace, {'12'})
            self.assertEqual([row['line'] for row in report['rows']], [4, 5, 7])
            self.assertEqual(report['event_headers'][0]['line'], 2)
            self.assertEqual(report['lineage']['rows'][0]['to_node_id'], 12)
            self.assertEqual(related, {'10', '12'})

    def test_recovered_reference_translates_representative_ids(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            mapping = root / 'bridge.tsv'
            mapping.write_text('before_node_id\tafter_node_id\n19\t23\n23\t19\n')
            summary = {'binary': {'recovery_bridge': {'dce-3': {'node_id_remap': mapping.name}}}}
            frozen = {'files': {mapping.name: {'sha256': sha256(mapping)}}}
            bundle = root / 'dce-3'
            bundle.mkdir()
            for side in ('before', 'after'):
                write_table(bundle / f'{side}.nodes.tsv', {}, HEADERS['nodes'], [
                    node(19, ['different']), node(23, ['representative']),
                ], nodeInventoryComplete=True)
            earlier = {'pass': 'common-expr', 'follow_forward': ['19']}
            later = {'pass': 'dce-3', 'directory': str(bundle), 'follow_forward': []}
            bridges = gsim_bridges(root, summary, frozen)
            self.assertEqual(bridges['dce-3'][1]['23'], '19')
            finish_representatives([earlier, later], bridges)
            self.assertEqual(later['after_earlier_representatives']['rows'][0]['name'], 'representative')
            mapping.write_text('before_node_id\tafter_node_id\n19\t23\n')
            with self.assertRaisesRegex(ValueError, 'bridge changed'):
                gsim_bridges(root, summary, frozen)

    def test_liveness_provenance_matches_node_payload(self):
        with TemporaryDirectory() as temporary:
            trace = Path(temporary) / 'evolution.tsv'
            trace.write_text('\n'.join([
                '\t'.join(HEADERS['evolution']),
                'provenance\t0\t1\t\\N\tstart\tliveness\tbefore\t12\t{"relation":"start","node_id":121}',
                'provenance\t0\t2\t\\N\tstart\tliveness\tbefore\t741\t{"relation":"start","node_id":12}',
                'provenance\t0\t3\t\\N\tresidual\tliveness\tbefore\t742\t{"relation":"residual","owner_ids":[45,12]}',
                'footer\t0\t4\t\\N\t\\N\t\\N\t\\N\t\\N\t{"complete":true,"replayComplete":true}',
            ]) + '\n')
            report, _ = evolution(trace, {'12'})
            self.assertEqual([row['object_id'] for row in report['rows']], [741, 742])

    def test_grh_alias_trace_matches_new_target(self):
        with TemporaryDirectory() as temporary:
            trace = Path(temporary) / 'alias-analysis-migrations.jsonl'
            trace.write_text('\n'.join([
                '{"record":"header","engine":"grh"}',
                '{"record":"boundary-use","from":1,"to":2,"target":3,"targetAfter":4}',
                '{"record":"footer","complete":true}',
            ]) + '\n')
            self.assertEqual(alias_trace(trace, {'4'})['matching_rows'], 1)

    def test_explicit_names_include_arbitrary_samples_and_recheck_changes(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            gs = root / 'gs.nodes.tsv'
            gr = root / 'gr.nodes.tsv'
            write_table(gs, {}, HEADERS['nodes'], [node(1, ['matched'])], nodeInventoryComplete=True)
            write_table(gr, {}, HEADERS['nodes'], [
                node(2, ['matched']), node(3, ['mod', 'unlisted']), node(4, ['mod.unlisted']),
            ], nodeInventoryComplete=True)
            report = {'grh_nodes': {'path': str(gr)}, 'gsim_nodes': {'path': str(gs)}, 'classes': []}
            self.assertEqual(explicit_samples(report, ['mod.unlisted']), [
                {'node_id': 3, 'name': 'mod.unlisted'}, {'node_id': 4, 'name': 'mod.unlisted'},
            ])
            with self.assertRaisesRegex(ValueError, 'same-name'):
                explicit_samples(report, ['matched'])
            self.assertEqual(explicit_samples(report, ['matched', 'removed'], recheck=True), [
                {'node_id': 2, 'name': 'matched', 'grh_r4_ids': [2], 'gsim_r4_ids': [1]},
                {'node_id': None, 'name': 'removed', 'grh_r4_ids': [], 'gsim_r4_ids': []},
            ])

    @unittest.skipUnless((LEGACY_TRACE / 'common-expr/native-mutations.jsonl').is_file(),
                         'F34 native trace fixture has not been captured')
    def test_gsim_merge_follows_concrete_representative(self):
        names = {'expr0': 'expr0'}
        common, identifiers = bundle_evidence(LEGACY_TRACE / 'common-expr', 'common-expr', names, set())
        self.assertEqual(common['before_exact_names']['expr0'], ['19'])
        self.assertNotIn('expr0', common['after_exact_names'])
        self.assertEqual(identifiers, {'19', '23'})
        self.assertEqual(common['follow_forward'], ['23'])
        self.assertEqual(common['after_lineage_nodes']['rows'][0]['name'], 'expr4')
        self.assertTrue(any(row['action'] == 'retire' and row['node_id'] == 19
                            for row in common['native_mutations']['rows']))
        self.assertTrue(any(row['action'] == 'redirect' and row['before_node_id'] == 19
                            for row in common['native_mutations']['rows']))
        self.assertEqual(common['evolution']['lineage']['matching_rows'], 1)
        selected = recheck_pass({'passes': [
            {'pass': 'split-nodes#0', 'bundles': ['unused']},
            {'pass': 'common-expr#0', 'bundles': [LEGACY_TRACE / 'common-expr']},
        ]}, 'common-expr#0', names, [])
        self.assertEqual(selected['passes'][0]['follow_forward'], ['23'])
        self.assertEqual(selected['passes'][0]['before_exact_names'], {'expr0': ['19']})

        if (LEGACY_TRACE / 'dce-3/evolution.tsv').is_file():
            dce, _ = bundle_evidence(LEGACY_TRACE / 'dce-3', 'dce-3', names, set())
            finish_representatives([common, dce])
            self.assertEqual(dce['after_earlier_representatives']['rows'][0]['name'], 'expr4')


if __name__ == '__main__':
    unittest.main()
