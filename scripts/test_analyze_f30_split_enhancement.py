"""Small native exchanges test fresh split accounting against before-only indexes."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import analyze_f30_split_enhancement as enhancement
from export_f30_connection_differences import closed_database_identity, file_identity
from semantic_node_exchange import HEADERS, KINDS, SCHEMA, compact, decode_cell, encode_cell


ROOT = Path(__file__).resolve().parents[1]
DIGEST = 'a' * 64


def node(identifier, name):
    return {'node_id': identifier, 'name_path_json': [name], 'native_name': name}


def write_bundle(directory, engine, inventory, *, variant='current', root='top', digest=DIGEST):
    directory.mkdir(parents=True, exist_ok=True)
    session = variant + '-' + engine + '-session'
    identity = {'schema': SCHEMA, 'engine': engine, 'run_id': variant + '-' + engine + '-run',
                'graph_id': 'top', 'exchange_session_id': session, 'root_name': root}
    identity.update({'input_sha256': digest} if engine == 'grh' else
                    {'input_identity': {'sha256': digest}})
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
    for decision in inventory.get('decisions', []):
        append('decision', 0, subject='node', side='before', object_id=decision['node_id'],
               reason=decision['reason'], detail_json={'pass': header['pass'],
                   'outcome': decision['outcome'], 'blocker_node_ids': decision.get('blockers', [])})
    append('event', 1, action='replace', reason='native_array_split')
    before = {row['node_id']: row for row in inventory['before']}
    after = {row['node_id']: row for row in inventory['after']}
    for side, own, peer in (('before', before, after), ('after', after, before)):
        for identifier, definition in own.items():
            if peer.get(identifier) != definition:
                append('edit', 1, subject='node', side=side, object_id=identifier, detail_json=definition)
    for link in inventory['lineage']:
        detail = {'to_node_id': link['child'], 'relation': link.get('relation', 'split')}
        if 'coordinates' in link:
            detail['coordinates'] = link['coordinates']
        append('lineage', 1, subject='node', side='before', object_id=link['parent'],
               detail_json=detail)
    append('footer', 1, detail_json={'complete': True, 'replayComplete': True, 'eventCount': 1,
        'beforeNodeCount': len(before), 'afterNodeCount': len(after),
        'beforeConnectionCount': 0, 'afterConnectionCount': 0,
        'decisionCount': len(inventory.get('decisions', [])),
        'nodeInventoryComplete': True, 'connectionCoverage': coverage})
    with (directory / 'evolution.tsv').open('w', encoding='utf-8') as stream:
        stream.write('\t'.join(HEADERS['evolution']) + '\n')
        for row in records:
            stream.write('\t'.join(encode_cell(compact(row[column]) if column == 'detail_json' and
                row.get(column) is not None else row.get(column)) for column in HEADERS['evolution']) + '\n')


class SplitEnhancementTests(unittest.TestCase):
    def setUp(self):
        root = ROOT / 'ptmp/firrtl-ingest/F30/split-enhancement-contract'
        root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.output = self.work / 'report'
        self.bundles, self.inventory = {}, {}
        for variant in ('baseline', 'current'):
            for engine, offset in (('grh', 0), ('gsim', 100)):
                before = [node(offset + 1, 'top.keep'), node(offset + 2, 'top.array'),
                          node(offset + 3, 'top.newsplit'), node(offset + 4, 'top.out')]
                families = [(2, [20, 21])]
                if variant == 'current' or engine == 'gsim':
                    families.append((3, [30, 31, 32]))
                after = deepcopy([row for row in before if row['node_id'] - offset not in
                                  {parent for parent, _ in families}])
                links = []
                for parent, children in families:
                    parent_name = before[parent - 1]['native_name']
                    for index, child in enumerate(children):
                        after.append(node(offset + child, parent_name + '_' + str(index)))
                        links.append({'parent': offset + parent, 'child': offset + child,
                                      'coordinates': [index]})
                key = variant, engine
                self.bundles[key] = self.work / (variant + '-' + engine)
                self.inventory[key] = {'before': before, 'after': after, 'lineage': links}
                self.write(key)
        self.analysis = self.work / 'baseline-analysis'
        self.naming = self.work / 'baseline-naming'
        self.baseline = self.work / 'baseline-gap'
        for directory in (self.analysis, self.naming, self.baseline):
            directory.mkdir()
        self.database = self.analysis / 'analysis.sqlite'
        with sqlite3.connect(self.database) as database:
            for engine in ('grh', 'gsim'):
                prefix = 'before_' + engine
                database.execute(f'CREATE TABLE {prefix}_nodes(id INTEGER PRIMARY KEY, path TEXT, '
                                 'path_json TEXT, native_name TEXT NOT NULL)')
                database.execute(f'CREATE INDEX {prefix}_nodes_path ON {prefix}_nodes(path)')
                database.executemany(f'INSERT INTO {prefix}_nodes VALUES(?,?,?,?)',
                    [(row['node_id'], row['native_name'], compact(row['name_path_json']), row['native_name'])
                     for row in self.inventory['baseline', engine]['before']])
                database.execute(f'CREATE TABLE {prefix}_names(path TEXT PRIMARY KEY, node_id INTEGER, '
                                 'occurrences INTEGER NOT NULL) WITHOUT ROWID')
                database.execute(f'INSERT INTO {prefix}_names SELECT path,MIN(id),COUNT(*) '
                                 f'FROM {prefix}_nodes GROUP BY path')
        self.write_baseline_reports()

    def write(self, key, **kwargs):
        variant, engine = key
        write_bundle(self.bundles[key], engine, self.inventory[key], variant=variant, **kwargs)

    def save(self, path, report):
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def write_baseline_reports(self):
        inventories, sources = {}, {}
        for engine in ('grh', 'gsim'):
            source = self.bundles['baseline', engine] / 'before.nodes.tsv'
            lines = source.read_text(encoding='utf-8').splitlines()
            inventories['before_' + engine] = {'source': str(source), 'nodes': 4,
                'metadata': json.loads(lines[0].split('\t', 1)[1]),
                'footer': json.loads(lines[-1].split('\t', 1)[1])}
            sources[str(source)] = file_identity(source)
        self.save(self.analysis / 'summary.json', {
            'schema': 'wolvrix.f30.native-alignment-analysis.v1', 'complete': True,
            'input_sha256': DIGEST, 'root_name': 'top', 'inventories': inventories})
        self.save(self.naming / 'summary.json', {
            'schema': 'wolvrix.f30.split-naming-check.v1', 'complete': True, 'passed': True,
            'input_sha256': DIGEST, 'root_name': 'top', 'source_files': sources})
        self.prior = {'schema': 'wolvrix.f30.split-gap.v1', 'complete': True,
            'input_sha256': DIGEST, 'root_name': 'top', 'analysis': str(self.analysis),
            'naming': str(self.naming), 'database': closed_database_identity(self.database),
            'report_inputs': {str(path): {'identity': file_identity(path),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in
                (self.analysis / 'summary.json', self.naming / 'summary.json')},
            'accounting': {'grh': {'before': 4, 'after': 5, 'survivors': 3, 'new_nodes': 2,
                'retired_originals': 1, 'parents': 1, 'children': 2, 'retired': 1, 'residual': 0},
                'gsim': {'before': 4, 'after': 7, 'survivors': 2, 'new_nodes': 5,
                'retired_originals': 2, 'parents': 2, 'children': 5, 'retired': 2, 'residual': 0}},
            'net_split_gap': 2}
        self.save(self.baseline / 'summary.json', self.prior)

    def analyze(self):
        return enhancement.analyze(self.baseline / 'summary.json', self.bundles['current', 'grh'],
                                   self.bundles['current', 'gsim'], self.output)

    def assert_rejected(self):
        with self.assertRaises(ValueError):
            self.analyze()
        self.assertFalse(any(self.output.glob('*.tsv')), 'failed evidence published a final TSV')
        summary = self.output / 'summary.json'
        if summary.exists():
            self.assertFalse(json.loads(summary.read_text(encoding='utf-8'))['complete'])

    def coordinate_rows(self):
        lines = (self.output / 'coordinate-differences.tsv').read_text(encoding='utf-8').splitlines()
        rows = [line for line in lines if not line.startswith('#')]
        columns = rows[0].split('\t')
        return [dict(zip(columns, map(decode_cell, row.split('\t')))) for row in rows[1:]]

    def coordinate_members(self, rows):
        return {(None if row['coordinates_json'] is None else
                 tuple(json.loads(row['coordinates_json'])) if row['coordinates_json'] != 'null' else None,
                 None if row['grh_child'] is None else int(row['grh_child']),
                 None if row['gsim_child'] is None else int(row['gsim_child'])) for row in rows}

    def test_fresh_lineage_accounts_for_improvement_using_before_only_database(self):
        before = self.database.read_bytes()
        report = self.analyze()
        self.assertEqual(report['schema'], 'wolvrix.f30.split-enhancement.v1')
        self.assertTrue(report['complete'])
        self.assertEqual(report['baseline_net_split_gap'], 2)
        self.assertEqual(report['net_split_gap'], 0)
        self.assertEqual(report['net_split_gap_reduction'], 2)
        self.assertEqual(report['parent_families'], 2)
        for engine in ('grh', 'gsim'):
            self.assertEqual(report['accounting'][engine], {'before': 4, 'after': 7,
                'survivors': 2, 'new_nodes': 5, 'retired_originals': 2,
                'parents': 2, 'children': 5, 'retired': 2, 'residual': 0})
        self.assertEqual(sum(row['net_gap'] for row in report['categories']), 0)
        self.assertEqual(sum(row['families'] for row in report['categories']), 2)
        self.assertEqual(report['coordinate_categories'], [{'reason': 'both_split_coordinates_equal',
            'families': 2, 'grh_children': 5, 'gsim_children': 5, 'net_gap': 0}])
        self.assertEqual(report['coordinate_differences_rows'], 0)
        self.assertEqual(self.coordinate_rows(), [])
        self.assertTrue((self.output / 'parent-families.tsv').is_file())
        self.assertEqual(self.database.read_bytes(), before, 'baseline database must stay read-only')
        with sqlite3.connect(self.database) as database:
            tables = {row[0] for row in database.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        self.assertEqual(tables, {'before_grh_nodes', 'before_grh_names', 'before_gsim_nodes', 'before_gsim_names'})

    def test_equal_child_counts_with_different_coordinates_are_not_geometry_matches(self):
        self.inventory['current', 'gsim']['lineage'][1]['coordinates'] = [2]
        self.write(('current', 'gsim'))
        report = self.analyze()
        self.assertTrue(report['complete'])
        self.assertEqual(report['net_split_gap'], 0)
        categories = {row['reason']: row for row in report['coordinate_categories']}
        self.assertEqual(categories['both_split_coordinates_different'], {
            'reason': 'both_split_coordinates_different', 'families': 1,
            'grh_children': 2, 'gsim_children': 2, 'net_gap': 0})
        self.assertEqual(categories['both_split_coordinates_equal']['families'], 1)
        self.assertEqual(report['coordinate_differences_rows'], 2)
        rows = self.coordinate_rows()
        self.assertEqual(self.coordinate_members(rows), {((1,), 21, None), ((2,), None, 121)})
        for row in rows:
            self.assertEqual((row['category'], row['parent_path'], row['grh_parent'], row['gsim_parent']),
                ('both_split_coordinates_different', 'top.array', '2', '102'))
            self.assertNotEqual(row['side'], 'unavailable')
        self.assertEqual(len({row['side'] for row in rows}), 2)

    def test_duplicate_coordinate_within_one_original_parent_is_rejected(self):
        links = self.inventory['current', 'grh']['lineage']
        links[1]['coordinates'] = deepcopy(links[0]['coordinates'])
        self.write(('current', 'grh'))
        self.assert_rejected()

    def test_missing_and_null_coordinates_are_unavailable_without_guessed_members(self):
        original = deepcopy(self.inventory['current', 'grh']['lineage'])
        for kind in ('missing', 'null'):
            with self.subTest(kind=kind):
                links = deepcopy(original)
                if kind == 'missing':
                    del links[0]['coordinates']
                else:
                    # Unknown coordinates are not duplicate coordinate tuples.
                    links[0]['coordinates'] = links[1]['coordinates'] = None
                self.inventory['current', 'grh']['lineage'] = links
                self.write(('current', 'grh'))
                self.output = self.work / (kind + '-coordinates-report')
                report = self.analyze()
                self.assertTrue(report['complete'])
                categories = {row['reason']: row for row in report['coordinate_categories']}
                self.assertEqual(categories['both_split_coordinates_unavailable']['families'], 1)
                self.assertEqual(categories['both_split_coordinates_equal']['families'], 1)
                self.assertEqual(report['coordinate_differences_rows'], 1)
                rows = self.coordinate_rows()
                self.assertEqual(self.coordinate_members(rows), {(None, None, None)})
                self.assertEqual(rows[0]['side'], 'unavailable')
                self.assertEqual(rows[0]['category'], 'both_split_coordinates_unavailable')

    def test_singleton_coordinate_axis_is_compared_without_dropping_it(self):
        self.inventory['current', 'gsim']['lineage'][0]['coordinates'] = [0, 0]
        self.write(('current', 'gsim'))
        report = self.analyze()
        self.assertTrue(report['complete'])
        categories = {row['reason']: row for row in report['coordinate_categories']}
        self.assertEqual(categories['both_split_coordinates_different']['families'], 1)
        self.assertEqual(report['coordinate_differences_rows'], 2)
        self.assertEqual(self.coordinate_members(self.coordinate_rows()),
                         {((0,), 20, None), ((0, 0), None, 120)})

    def test_complete_coordinate_difference_also_closes_unequal_child_counts(self):
        inventory = self.inventory['current', 'grh']
        inventory['lineage'] = [link for link in inventory['lineage'] if link['child'] != 32]
        inventory['after'] = [row for row in inventory['after'] if row['node_id'] != 32]
        self.write(('current', 'grh'))
        report = self.analyze()
        self.assertTrue(report['complete'])
        self.assertEqual(report['net_split_gap'], 1)
        self.assertEqual(sum(row['net_gap'] for row in report['coordinate_categories']), 1)
        categories = {row['reason']: row for row in report['coordinate_categories']}
        self.assertEqual(categories['both_split_coordinates_different'], {
            'reason': 'both_split_coordinates_different', 'families': 1,
            'grh_children': 2, 'gsim_children': 3, 'net_gap': 1})
        self.assertEqual(report['coordinate_differences_rows'], 1)
        self.assertEqual(self.coordinate_members(self.coordinate_rows()), {((2,), None, 132)})

    def test_current_before_body_drift_is_rejected_despite_equal_ids_and_names(self):
        self.inventory['current', 'grh']['before'][0]['native_name'] = 'different_native_name'
        self.write(('current', 'grh'))
        self.assert_rejected()

    def test_all_current_retain_reasons_group_without_double_counting_family(self):
        inventory = self.inventory['current', 'grh']
        inventory['lineage'] = [link for link in inventory['lineage'] if link['parent'] != 3]
        inventory['after'] = [row for row in inventory['after'] if row['node_id'] not in (30, 31, 32)]
        inventory['after'].append(node(3, 'top.newsplit'))
        inventory['decisions'] = [
            {'node_id': 3, 'reason': 'first_attempt', 'outcome': 'retain', 'blockers': [2]},
            {'node_id': 3, 'reason': 'second_attempt', 'outcome': 'retain', 'blockers': []},
            {'node_id': 3, 'reason': 'second_attempt', 'outcome': 'retain', 'blockers': []}]
        self.write(('current', 'grh'))
        report = self.analyze()
        self.assertTrue(report['complete'])
        self.assertEqual(report['net_split_gap'], 2)
        self.assertEqual(report['net_split_gap_reduction'], 0)
        self.assertEqual(report['immediate_reasons'], [{'reason': 'first_attempt+second_attempt',
            'families': 1, 'grh_children': 0, 'gsim_children': 3, 'net_gap': 2}])
        exported = (self.output / 'parent-families.tsv').read_text(encoding='utf-8')
        self.assertIn('grh_decisions_json', exported)
        self.assertIn('first_attempt', exported)
        self.assertIn('second_attempt', exported)

    def test_current_grh_only_split_groups_native_replace_reason(self):
        inventory = self.inventory['current', 'gsim']
        inventory['lineage'] = [link for link in inventory['lineage'] if link['parent'] != 103]
        inventory['after'] = [row for row in inventory['after'] if row['node_id'] not in (130, 131, 132)]
        inventory['after'].append(node(103, 'top.newsplit'))
        self.inventory['current', 'grh']['decisions'] = [
            {'node_id': 3, 'reason': 'state_array_split', 'outcome': 'replace', 'blockers': []}]
        self.write(('current', 'grh'))
        self.write(('current', 'gsim'))
        report = self.analyze()
        self.assertTrue(report['complete'])
        self.assertEqual(report['net_split_gap'], -2)
        self.assertEqual(report['grh_only_reasons'], [{'reason': 'state_array_split',
            'families': 1, 'grh_children': 3, 'gsim_children': 0, 'net_gap': -2}])
        self.assertEqual(report['immediate_reasons'], [])

    def test_current_native_decision_blocker_must_exist_before_pass(self):
        self.inventory['current', 'grh']['decisions'] = [
            {'node_id': 3, 'reason': 'invalid_blocker', 'outcome': 'retain', 'blockers': [999]}]
        self.write(('current', 'grh'))
        self.assert_rejected()

    def test_live_residual_parent_contributes_without_becoming_a_retirement(self):
        self.inventory['current', 'grh']['after'].append(node(2, 'top.array'))
        self.write(('current', 'grh'))
        report = self.analyze()
        self.assertTrue(report['complete'])
        counts = report['accounting']['grh']
        self.assertEqual((counts['before'], counts['after'], counts['survivors']), (4, 8, 3))
        self.assertEqual((counts['children'], counts['retired'], counts['residual']), (5, 1, 1))
        self.assertEqual((report['net_split_gap'], report['net_split_gap_reduction']), (-1, 3))
        self.assertEqual(sum(row['net_gap'] for row in report['categories']), -1)
        self.assertEqual(report['coordinate_categories'], [{'reason': 'both_split_coordinates_equal',
            'families': 2, 'grh_children': 5, 'gsim_children': 5, 'net_gap': -1}])
        self.assertEqual(report['coordinate_differences_rows'], 0)
        self.assertEqual(self.coordinate_rows(), [])

    def test_current_before_id_drift_is_rejected(self):
        self.inventory['current', 'grh']['before'][0]['node_id'] = 9
        self.write(('current', 'grh'))
        self.assert_rejected()

    def test_duplicate_split_child_is_rejected(self):
        links = self.inventory['current', 'grh']['lineage']
        links.append({**links[0], 'parent': 3})
        self.write(('current', 'grh'))
        self.assert_rejected()

    def test_non_split_lineage_relation_is_rejected(self):
        self.inventory['current', 'gsim']['lineage'][0]['relation'] = 'merge'
        self.write(('current', 'gsim'))
        self.assert_rejected()

    def test_split_child_must_be_live_after_pass(self):
        self.inventory['current', 'gsim']['lineage'][0]['child'] = 999
        self.write(('current', 'gsim'))
        self.assert_rejected()

    def test_split_child_must_be_new_after_pass(self):
        self.inventory['current', 'gsim']['lineage'][0]['child'] = 101
        self.write(('current', 'gsim'))
        self.assert_rejected()

    def test_split_parent_must_exist_before_pass(self):
        self.inventory['current', 'grh']['lineage'][0]['parent'] = 999
        self.write(('current', 'grh'))
        self.assert_rejected()

    def test_unexplained_live_addition_cannot_close_inventory_accounting(self):
        self.inventory['current', 'grh']['lineage'].pop()
        self.write(('current', 'grh'))
        self.assert_rejected()

    def test_unexplained_retirement_cannot_close_inventory_accounting(self):
        inventory = self.inventory['current', 'grh']
        inventory['lineage'] = [link for link in inventory['lineage'] if link['parent'] != 3]
        inventory['after'] = [row for row in inventory['after'] if row['node_id'] not in (30, 31, 32)]
        self.write(('current', 'grh'))
        self.assert_rejected()

    def test_different_native_input_digest_is_rejected(self):
        self.write(('current', 'gsim'), digest='b' * 64)
        self.assert_rejected()

    def test_different_native_root_is_rejected(self):
        self.write(('current', 'grh'), root='other')
        self.assert_rejected()

    def test_baseline_report_source_mutation_is_rejected(self):
        path = self.analysis / 'summary.json'
        path.write_bytes(path.read_bytes() + b'\n')
        self.assert_rejected()

    def test_baseline_report_digest_mismatch_is_rejected_even_with_current_stat(self):
        path = self.analysis / 'summary.json'
        path.write_bytes(path.read_bytes() + b'\n')
        self.prior['report_inputs'][str(path)]['identity'] = file_identity(path)
        self.save(self.baseline / 'summary.json', self.prior)
        self.assert_rejected()

    def test_baseline_before_snapshot_source_mutation_is_rejected(self):
        path = self.bundles['baseline', 'grh'] / 'before.nodes.tsv'
        path.write_bytes(path.read_bytes() + b'\n')
        self.assert_rejected()

    def test_report_mutation_during_inventory_scan_prevents_final_publication(self):
        path = self.naming / 'summary.json'
        original = enhancement.scan_nodes
        changed = False

        def changing(*args, **kwargs):
            nonlocal changed
            result = original(*args, **kwargs)
            if not changed:
                path.write_bytes(path.read_bytes() + b'\n')
                changed = True
            return result

        with patch.object(enhancement, 'scan_nodes', side_effect=changing):
            self.assert_rejected()
        self.assertTrue(changed, 'fixture did not mutate a source after scanning began')


class SparseIdTests(unittest.TestCase):
    def test_membership_and_duplicates_across_large_sparse_ids(self):
        identifiers = enhancement.SparseIds()
        values = (1, 257, 2**32 + 17, 2**63 - 1)
        for identifier in values:
            self.assertNotIn(identifier, identifiers)
            identifiers.add(identifier)
            self.assertIn(identifier, identifiers)
        for identifier in values:
            identifiers.add(identifier)
            self.assertIn(identifier, identifiers)
        for identifier in (0, 2, 256, 2**32 + 18, 2**63 - 2):
            self.assertNotIn(identifier, identifiers)


if __name__ == '__main__':
    unittest.main()
