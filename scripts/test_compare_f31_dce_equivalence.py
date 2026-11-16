"""Contracts for actual-state DCE equivalence evidence."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from compare_f31_dce_equivalence import checked_capture, compare, digest_file, public_fingerprint
from semantic_node_exchange import HEADERS, KINDS, compact, encode_cell, verify_snapshot


class ActualStateEquivalenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='f31-equivalence-')
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)

    def capture(self, name):
        directory = self.work / name
        directory.mkdir()
        files = [directory / name for name in ('actual-ir.json', 'nodes.tsv', 'connections.tsv')]
        files[0].write_text('{}\n')
        identity = {'schema': 'semantic-node-exchange.v1', 'engine': 'grh', 'run_id': name,
                    'graph_id': '1', 'exchange_session_id': name, 'snapshot_id': name, 'stage': 'after'}
        definitions = {'nodes': [dict(node_id=1, name_path_json=['r_3'], native_name='r_3'),
                                 dict(node_id=2, name_path_json=['out'], native_name='out')],
                       'connections': [dict(connection_id=7, source_node_id=1, target_node_id=2,
                                            kind='dependency', resolution='resolved',
                                            candidate_sources_json=[], reason=None)]}
        for table in ('nodes', 'connections'):
            with (directory / (table + '.tsv')).open('w') as stream:
                stream.write('#meta\t' + compact({**identity, 'table': table}) + '\n')
                stream.write('\t'.join(HEADERS[table]) + '\n')
                for row in definitions[table]:
                    stream.write('\t'.join(encode_cell(compact(row[key]) if key.endswith('_json') else row[key])
                                           for key in HEADERS[table]) + '\n')
                footer = {'complete': True, 'rowCount': len(definitions[table])}
                if table == 'nodes':
                    footer['nodeInventoryComplete'] = True
                else:
                    footer['connectionCoverage'] = {
                        kind: {'status': 'complete', 'resolved': int(kind == 'dependency'), 'unresolved': 0}
                        for kind in KINDS}
                stream.write('#footer\t' + compact(footer) + '\n')
        database = directory / 'public.sqlite'
        verification = verify_snapshot(directory, database)
        return {'signature': {'ir_sha256': digest_file(files[0]), **public_fingerprint(database)},
                'artifacts': [{'path': str(path), 'sha256': digest_file(path)} for path in files],
                'public_verification': verification}

    def samples(self):
        result = []
        for mode in ('no-trace', 'trace'):
            path = self.work / (mode + '.json')
            sample = {'schema': 'wolvrix.f31.dce-benchmark.v1', 'status': 'passed', 'engine': 'grh',
                      'mode': mode, 'source': 'raw-firrtl', 'verify': True,
                      'input_sha256': 'same-input', 'manifest_sha256': 'same-manifest',
                      'configuration': {'threads': 1}, 'package_identity': {'source': 'same-source'},
                      'sources': [{'sha256': 'auxiliary-input'}], 'dependencies': {'content': 'deps'},
                      'dce': {'actual_after': self.capture(mode + '-after'),
                              'actual_repeated': self.capture(mode + '-repeated'),
                              'repeated_dce_history': {'changed': False}}}
            path.write_text(json.dumps(sample))
            result.append(path)
        return result

    def test_equal_actual_states_pass(self):
        self.assertTrue(compare(*self.samples())['passed'])

    def test_tampered_artifact_fails(self):
        capture = self.capture('tampered')
        Path(capture['artifacts'][1]['path']).write_text('changed Node\n')
        with self.assertRaisesRegex(ValueError, 'artifact changed'):
            checked_capture(capture)

    def test_cross_run_identity_and_repeated_graph_changes_fail(self):
        off, on = self.samples()
        original = json.loads(on.read_text())
        for field in ('input_sha256', 'manifest_sha256', 'configuration', 'package_identity', 'sources', 'dependencies'):
            with self.subTest(field=field):
                sample = {**original, field: 'other'}
                on.write_text(json.dumps(sample))
                with self.assertRaisesRegex(ValueError, 'identities differ'):
                    compare(off, on)
        original['dce']['repeated_dce_history']['changed'] = True
        on.write_text(json.dumps(original))
        with self.assertRaisesRegex(ValueError, 'second DCE'):
            compare(off, on)

    def test_copied_signature_cannot_hide_different_actual_nodes(self):
        capture = self.capture('forged')
        nodes = next(item for item in capture['artifacts'] if Path(item['path']).name == 'nodes.tsv')
        path = Path(nodes['path'])
        path.write_text(path.read_text().replace('r_3', 'r_3_0'))
        nodes['sha256'] = digest_file(path)
        with self.assertRaisesRegex(ValueError, 'differs from actual inventory'):
            checked_capture(capture)

    def test_incomplete_inventory_is_rejected(self):
        capture = self.capture('partial')
        nodes = next(item for item in capture['artifacts'] if Path(item['path']).name == 'nodes.tsv')
        path = Path(nodes['path'])
        path.write_text(path.read_text().replace('"nodeInventoryComplete":true', '"nodeInventoryComplete":false'))
        nodes['sha256'] = digest_file(path)
        with self.assertRaisesRegex(ValueError, 'inventory is incomplete'):
            checked_capture(capture)

    def test_connection_ids_are_local_but_node_identity_is_exact(self):
        database = self.work / 'public.sqlite'
        with sqlite3.connect(database) as db:
            db.executescript('CREATE TABLE current_nodes(id INTEGER,body TEXT);'
                             'CREATE TABLE current_connections(id INTEGER,body TEXT,key TEXT);')
            db.execute('INSERT INTO current_nodes VALUES(?,?)', (1, '{"name":"r_3"}'))
            db.execute('INSERT INTO current_connections VALUES(?,?,?)', (7, '{}', '["dependency",1,2]'))
        first = public_fingerprint(database)
        with sqlite3.connect(database) as db:
            db.execute('UPDATE current_connections SET id=999')
        self.assertEqual(public_fingerprint(database), first)
        with sqlite3.connect(database) as db:
            db.execute('UPDATE current_nodes SET body=?', ('{"name":"r_3_0"}',))
        self.assertNotEqual(public_fingerprint(database), first)


if __name__ == '__main__':
    unittest.main()
