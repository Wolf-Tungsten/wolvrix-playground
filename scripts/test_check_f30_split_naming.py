"""Small native inventories check split naming and conservative ID comparisons."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import check_f30_split_naming as naming
from semantic_node_exchange import HEADERS, KINDS, SCHEMA, compact, encode_cell


ROOT = Path(__file__).resolve().parents[1]


def node(identifier, path, native_name=None):
    return {'node_id': identifier, 'name_path_json': [path],
            'native_name': path if native_name is None else native_name}


class SplitNamingTests(unittest.TestCase):
    def setUp(self):
        root = ROOT / 'ptmp/firrtl-ingest/F30/split-naming-contract'
        root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.output = self.work / 'report'
        self.bundles, self.inventory = {}, {}
        for variant in ('baseline', 'current'):
            for engine, offset in (('grh', 0), ('gsim', 100)):
                key = variant, engine
                self.bundles[key] = self.work / (variant + '-' + engine)
                before = [node(offset + 1, 'top.r_0'), node(offset + 2, 'top.r'), node(offset + 4, 'top.out')]
                after = [node(offset + 1, 'top.r_0'), node(offset + 3, 'top.r_0_0'), node(offset + 4, 'top.out')]
                if key == ('baseline', 'gsim'):
                    after[0] = node(101, 'top.r_0_0')
                    after[1] = node(103, 'top.r_0')
                self.inventory[key] = {'before': before, 'after': after,
                    'lineage': [{'parent': offset + 2, 'child': offset + 3, 'coordinates': [0]}]}
                self.write_bundle(key)
        self.known = ({'grh_original': 1, 'gsim_original': 101, 'gsim_child': 103,
                       'gsim_parent': 102, 'coordinates': [0]},)

    def write_bundle(self, key):
        variant, engine = key
        directory, inventory = self.bundles[key], self.inventory[key]
        directory.mkdir(exist_ok=True)
        session = variant + '-' + engine + '-session'
        identity = {'schema': SCHEMA, 'engine': engine, 'run_id': variant + '-' + engine + '-run',
                    'graph_id': 'top', 'exchange_session_id': session, 'root_name': 'top'}
        identity.update({'input_sha256': 'a' * 64} if engine == 'grh' else
                        {'input_identity': {'sha256': 'a' * 64}})
        header = {**identity, 'mode': 'trace', 'pass': 'split-static-array' if engine == 'grh' else 'splitArray',
                  'before_snapshot_id': session + '-before', 'after_snapshot_id': session + '-after'}
        coverage = {kind: {'status': 'complete', 'resolved': 0, 'unresolved': 0} for kind in KINDS}
        for phase in ('before', 'after'):
            for table in ('nodes', 'connections'):
                rows = inventory[phase] if table == 'nodes' else []
                metadata = {**identity, 'snapshot_id': header[phase + '_snapshot_id'],
                            'stage': phase, 'table': table}
                footer = {'complete': True, 'rowCount': len(rows),
                          **({'nodeInventoryComplete': True} if table == 'nodes' else
                             {'connectionCoverage': coverage})}
                with (directory / (phase + '.' + table + '.tsv')).open('w', encoding='utf-8') as stream:
                    stream.write('#meta\t' + compact(metadata) + '\n' + '\t'.join(HEADERS[table]) + '\n')
                    for row in sorted(rows, key=lambda value: value['node_id']):
                        cells = [compact(row[column]) if column.endswith('_json') else row[column]
                                 for column in HEADERS[table]]
                        stream.write('\t'.join(map(encode_cell, cells)) + '\n')
                    stream.write('#footer\t' + compact(footer) + '\n')
        records = []
        def append(record, seq, **values):
            ordinal = 0 if not records or records[-1]['seq'] != seq else records[-1]['ordinal'] + 1
            records.append({'record': record, 'seq': seq, 'ordinal': ordinal, **values})
        append('header', 0, detail_json=header)
        append('event', 1, action='replace', reason='native_array_split')
        before = {row['node_id']: row for row in inventory['before']}
        after = {row['node_id']: row for row in inventory['after']}
        for side, own, peer in (('before', before, after), ('after', after, before)):
            for identifier, definition in own.items():
                if peer.get(identifier) != definition:
                    append('edit', 1, subject='node', side=side, object_id=identifier, detail_json=definition)
        for link in inventory['lineage']:
            append('lineage', 1, subject='node', side='before', object_id=link['parent'],
                   detail_json={'to_node_id': link['child'], 'relation': 'split', 'coordinates': link['coordinates']})
        append('footer', 1, detail_json={'complete': True, 'replayComplete': True, 'eventCount': 1,
            'beforeNodeCount': len(before), 'afterNodeCount': len(after),
            'beforeConnectionCount': 0, 'afterConnectionCount': 0,
            'nodeInventoryComplete': True, 'connectionCoverage': coverage})
        with (directory / 'evolution.tsv').open('w', encoding='utf-8') as stream:
            stream.write('\t'.join(HEADERS['evolution']) + '\n')
            for row in records:
                stream.write('\t'.join(encode_cell(compact(row[column]) if column == 'detail_json' and
                    row.get(column) is not None else row.get(column)) for column in HEADERS['evolution']) + '\n')

    def check(self, *, known_cases=None, output=None):
        return naming.check(self.bundles['current', 'grh'], self.bundles['current', 'gsim'],
            self.bundles['baseline', 'grh'], self.bundles['baseline', 'gsim'], output or self.output,
            known_cases=self.known if known_cases is None else known_cases)

    def assert_semantic_failure(self, report):
        self.assertTrue(report['complete'])
        self.assertFalse(report['passed'])
        self.assertTrue(report['issues'])
        self.assertNotEqual(report['status'], 'passed')

    def test_original_preservation_corrects_known_name_candidate_without_inflating_ratio(self):
        report = self.check()
        self.assertTrue(report['complete'])
        self.assertTrue(report['passed'], report['issues'])
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['issues'], [])
        self.assertEqual(set(report['preservation']), {'grh', 'gsim'})
        self.assertEqual(len(report['known_cases']), 1)
        self.assertTrue(report['known_cases'][0]['passed'])
        for phase in ('baseline', 'current'):
            self.assertEqual(report['name_candidates'][phase]['unique_name_candidates'], 3)
            self.assertEqual(report['name_candidates'][phase]['grh_nodes'], 3)
            self.assertEqual(report['name_candidates'][phase]['gsim_nodes'], 3)
        self.assertEqual(report['name_candidates']['delta'], 0)
        for engine in ('grh', 'gsim'):
            self.assertEqual(report['after_id_sets'][engine]['added'], 0)
            self.assertEqual(report['after_id_sets'][engine]['removed'], 0)
            self.assertEqual(report['after_id_sets'][engine]['common'], 3)
        self.assertTrue((self.output / 'node-name-changes.tsv').exists())
        self.assertTrue((self.output / 'duplicate-names.tsv').exists())

    def test_before_inventory_drift_fails(self):
        self.inventory['current', 'gsim']['before'][0] = node(101, 'top.changed_before')
        self.write_bundle(('current', 'gsim'))
        self.assert_semantic_failure(self.check())

    def test_current_original_rename_fails(self):
        self.inventory['current', 'gsim']['after'][0] = node(101, 'top.renamed_original')
        self.write_bundle(('current', 'gsim'))
        self.assert_semantic_failure(self.check())

    def test_public_and_native_duplicates_fail_independently(self):
        original = deepcopy(self.inventory['current', 'gsim']['after'])
        for kind in ('public', 'native'):
            with self.subTest(kind=kind):
                self.inventory['current', 'gsim']['after'] = deepcopy(original)
                child = self.inventory['current', 'gsim']['after'][1]
                if kind == 'public':
                    child['name_path_json'] = ['top.r_0']
                else:
                    child['native_name'] = 'top.r_0'
                self.write_bundle(('current', 'gsim'))
                self.assert_semantic_failure(self.check(known_cases=(), output=self.work / (kind + '-report')))

    def test_grh_generated_after_id_drift_is_quantity_diagnostic_only(self):
        self.inventory['current', 'grh']['after'][1]['node_id'] = 5
        self.inventory['current', 'grh']['lineage'][0]['child'] = 5
        self.write_bundle(('current', 'grh'))
        report = self.check()
        self.assertTrue(report['passed'], report['issues'])
        counts = report['after_id_sets']['grh']
        self.assertEqual((counts['added'], counts['removed'], counts['common']), (1, 1, 2))
        scope = counts['generated_id_comparison_scope'].lower()
        self.assertIn('count', scope)
        self.assertTrue(any(token in scope for token in ('diagnostic', 'not', 'quantity')), scope)

    def test_gsim_after_id_drift_fails(self):
        self.inventory['current', 'gsim']['after'][1]['node_id'] = 105
        self.inventory['current', 'gsim']['lineage'][0]['child'] = 105
        self.write_bundle(('current', 'gsim'))
        report = self.check(known_cases=())
        self.assert_semantic_failure(report)
        counts = report['after_id_sets']['gsim']
        self.assertEqual((counts['added'], counts['removed'], counts['common']), (1, 1, 2))

    def test_known_child_requires_exact_parent_and_complete_coordinates(self):
        original = deepcopy(self.inventory['current', 'gsim']['lineage'][0])
        for kind, value in (('parent', 101), ('coordinates', [1]), ('coordinates', None)):
            with self.subTest(kind=kind, value=value):
                link = deepcopy(original)
                link[kind] = value
                self.inventory['current', 'gsim']['lineage'] = [link]
                self.write_bundle(('current', 'gsim'))
                report = self.check(output=self.work / ('known-' + kind + '-' + str(value)))
                self.assert_semantic_failure(report)
                self.assertFalse(report['known_cases'][0]['passed'])

    def test_incomplete_snapshot_footer_is_rejected_without_final_publication(self):
        path = self.bundles['current', 'gsim'] / 'after.nodes.tsv'
        contents = path.read_text(encoding='utf-8').replace('"complete":true', '"complete":false')
        path.write_text(contents, encoding='utf-8')
        with self.assertRaises(ValueError):
            self.check()
        self.assertFalse(any(self.output.glob('*.tsv')))
        self.assertFalse(json.loads((self.output / 'summary.json').read_text())['complete'])

    def test_incomplete_evolution_footer_is_rejected_without_final_publication(self):
        path = self.bundles['current', 'gsim'] / 'evolution.tsv'
        contents = path.read_text(encoding='utf-8').replace('"replayComplete":true', '"replayComplete":false')
        path.write_text(contents, encoding='utf-8')
        with self.assertRaises(ValueError):
            self.check()
        self.assertFalse(any(self.output.glob('*.tsv')))
        summary = self.output / 'summary.json'
        if summary.exists():
            self.assertFalse(json.loads(summary.read_text())['complete'])

    def test_source_mutation_after_snapshot_read_prevents_final_publication(self):
        target = self.bundles['current', 'gsim'] / 'after.nodes.tsv'
        original = naming.snapshot_rows
        changed = False
        def changing(identity, phase):
            nonlocal changed
            yield from original(identity, phase)
            source = Path(identity['directory']) / (phase + '.nodes.tsv')
            if not changed and source.resolve() == target.resolve():
                target.write_bytes(target.read_bytes() + b'\n')
                changed = True
        with patch.object(naming, 'snapshot_rows', side_effect=changing):
            with self.assertRaises(ValueError):
                self.check()
        self.assertTrue(changed, 'fixture did not mutate its selected snapshot after consumption')
        self.assertFalse(any(self.output.glob('*.tsv')))
        self.assertFalse(json.loads((self.output / 'summary.json').read_text())['complete'])


if __name__ == '__main__':
    unittest.main()
