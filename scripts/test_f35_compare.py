from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from f35_compare import ENDPOINT_HEADER, ENDPOINT_SCHEMA, classify, compare, last_seen_in_gsim
from benchmark_f29_pass_trace import sha256
from semantic_node_exchange import HEADERS, SCHEMA, encode_cell


def write_table(path, metadata, header, rows, **footer):
    with path.open('w', encoding='utf-8') as stream:
        stream.write('#meta\t' + json.dumps(metadata) + '\n')
        stream.write('\t'.join(header) + '\n')
        for row in rows:
            stream.write('\t'.join(map(encode_cell, row)) + '\n')
        stream.write('#footer\t' + json.dumps({'complete': True, 'rowCount': len(rows), **footer}) + '\n')


def node(identifier, path):
    return identifier, json.dumps(path) if path is not None else None, 'native-name-is-not-a-match-key'


def endpoint(identifier, kind, evidence='anchor-candidate', role='value', shape='[]'):
    return (identifier, role, 1, 0, 2, 0, kind, 8, 0, shape, '4state', -1, 0,
            '[]', '[]', '[]', 0, -1, evidence)


class CompareTest(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.gsim = self.root / 'gsim.tsv'
        write_table(self.gsim, {
            'schema': SCHEMA, 'engine': 'gsim', 'table': 'nodes',
            'stage': 'RemoveDeadNodes3', 'pass_instance': 'RemoveDeadNodes#2',
        }, HEADERS['nodes'], [
            node(1, ['mod', 'back\\slash\tfield']), node(2, ['mod.back\\slash\tfield']),
            node(3, None), node(4, ['mod', 'gsim-only']),
        ], nodeInventoryComplete=True)

    def grh(self, name, nodes, endpoints, connections):
        out = self.root / name
        out.mkdir()
        meta = {
            'engine': 'grh', 'stage': 'after-dead-code-elim#3', 'run_id': name, 'graph_id': '1',
            'snapshot_id': name + ':after',
        }
        write_table(out / 'nodes.tsv', {**meta, 'schema': SCHEMA, 'table': 'nodes'}, HEADERS['nodes'], nodes,
                    nodeInventoryComplete=True)
        write_table(out / 'connections.tsv', {**meta, 'schema': SCHEMA, 'table': 'connections'},
                    HEADERS['connections'], connections)
        write_table(out / 'endpoints.tsv', {
            **meta, 'schema': ENDPOINT_SCHEMA, 'snapshot_id': 'separate-export',
        }, ENDPOINT_HEADER, endpoints)
        return out

    def compare(self, grh, **options):
        return compare(grh / 'nodes.tsv', self.gsim, grh / 'endpoints.tsv', grh / 'connections.tsv', **options)

    def test_names_shapes_and_duplicate_accounting(self):
        joined = ['mod.back\\slash\tfield']
        grh = self.grh('initial', [
            node(1, joined), node(2, joined), node(3, None), node(4, ['core', 'mux']),
            node(5, ['core', 'effect']), node(6, ['core', 'state']), node(7, ['other', 'packed']),
            node(8, ['other', 'assign']), node(9, ['other', 'mixed']), node(10, ['other', 'constant']),
        ], [
            endpoint(3, 'grh.constant'), endpoint(4, 'grh.mux'), endpoint(5, 'grh.systemTask', 'operation-only'),
            endpoint(6, 'grh.registerReadPort'), endpoint(7, 'grh.sliceStatic'), endpoint(8, 'grh.assign'),
            endpoint(9, 'grh.assign'), endpoint(9, 'grh.bitOr'), endpoint(10, 'grh.constant'),
        ], [
            (1, 6, 4, 'state_update', 'resolved', '[]', None),
            (2, 4, 8, 'dependency', 'resolved', '[]', None),
        ])
        report = self.compare(grh)
        self.assertEqual((report['numerator'], report['denominator'], report['unmatched']), (2, 10, 8))
        self.assertEqual(report['grh_nodes']['anonymous_nodes'], 1)
        self.assertEqual(report['gsim_nodes']['anonymous_nodes'], 1)
        self.assertEqual(report['grh_nodes']['duplicate_names'], 1)
        self.assertEqual(report['gsim_nodes']['duplicate_rows_beyond_first'], 1)
        counts = {row['category']: row['count'] for row in report['classes']}
        self.assertEqual(counts, {
            'anonymous': 1, 'assignments': 1, 'state-and-storage': 2, 'external-effects': 1,
            'slices-and-packing': 1, 'mixed-endpoints': 1, 'constants': 1,
        })
        self.assertFalse(report['target_met'])

    def test_registered_port_kind_classifies_without_boundary_edges(self):
        port = ('value', 'grh.registerReadPort', 8, False, 'anchor-candidate', True)
        self.assertEqual(classify('state', [port], {}), 'state-and-storage')

    def test_cross_round_deltas_count_same_name_multiplicity(self):
        old = self.grh('old', [
            node(1, ['mod', 'back\\slash\tfield']), node(2, ['mod', 'gone']),
            node(3, ['mod', 'gone']), node(4, None),
        ], [endpoint(2, 'grh.mux'), endpoint(3, 'grh.mux'), endpoint(4, 'grh.assign')], [])
        index = self.root / 'unmatched.tsv'
        previous = self.root / 'previous.json'
        previous.write_text(json.dumps(self.compare(old, unmatched_index=index)), encoding='utf-8')
        new = self.grh('new', [
            node(1, ['mod', 'back\\slash\tfield']), node(2, ['mod', 'gone']),
            node(5, ['core', 'new\\name\t']), node(6, ['mod', 'gsim-only']),
        ], [endpoint(2, 'grh.mux'), endpoint(5, 'grh.assign')], [])
        report = self.compare(new, previous_index=index, previous_report=previous)
        self.assertEqual(report['change_pp'], 25)
        self.assertEqual(report['change_by_category'], {'anonymous': -1, 'assignments': 1, 'muxes': -1})
        self.assertEqual(report['unmatched_delta'], {
            'eliminated_named_rows': 1, 'introduced_named_rows': 1, 'previous_anonymous_rows': 1,
            'current_anonymous_rows': 0,
        })

    def test_target_is_inclusive_at_99_5_percent(self):
        matched = [node(identifier, ['mod', 'same']) for identifier in range(1, 200)]
        write_table(self.gsim, {
            'schema': SCHEMA, 'engine': 'gsim', 'table': 'nodes',
            'stage': 'RemoveDeadNodes3', 'pass_instance': 'RemoveDeadNodes#2',
        }, HEADERS['nodes'], [matched[0]], nodeInventoryComplete=True)
        missing = node(200, ['mod', 'missing'])
        shapes = [endpoint(200, 'grh.assign')]
        at_target = self.compare(self.grh('at-target', [*matched, missing], shapes, []))
        below_target = self.compare(self.grh('below-target', [*matched[:-1], missing], shapes, []))

        self.assertEqual(at_target['target_ratio'], 0.995)
        self.assertTrue(at_target['target_met'])
        self.assertFalse(below_target['target_met'])

    def test_incomplete_and_unrelated_evidence_rejected(self):
        grh = self.grh('test', [node(1, ['unique'])], [], [])
        with self.assertRaisesRegex(ValueError, 'endpoint evidence missing'):
            self.compare(grh)
        connections = grh / 'connections.tsv'
        connections.write_text(connections.read_text().replace('test:after', 'other:after'))
        with self.assertRaisesRegex(ValueError, 'different GRH R4 snapshot'):
            self.compare(grh)
        self.gsim.write_text(self.gsim.read_text().rsplit('#footer', 1)[0])
        with self.assertRaisesRegex(ValueError, 'line ending'):
            self.compare(grh)

    def test_last_seen_uses_latest_native_boundary(self):
        history = self.root / 'history'
        frozen = {'files': {'dce-3/after.nodes.tsv': {'sha256': 'same'}}}
        for boundary, names in (('split', ['removedEarly', 'removedLast']),
                                ('dce-3', ['removedLast'])):
            bundle = history / boundary
            bundle.mkdir(parents=True)
            snapshot = bundle / 'before.nodes.tsv'
            write_table(snapshot, {}, HEADERS['nodes'], [
                node(identifier, ['mod', name]) for identifier, name in enumerate(names, 1)
            ], nodeInventoryComplete=True)
            frozen['files'][f'{boundary}/before.nodes.tsv'] = {'sha256': sha256(snapshot)}
        with patch('f35_compare.GSIM_BUNDLES', ('split', 'dce-3')), \
                patch('f35_compare.load_frozen_reference', return_value=frozen):
            self.assertEqual(last_seen_in_gsim(history, {'sha256': 'same'},
                                               ['mod.removedEarly', 'mod.removedLast', 'never-present']),
                             {'mod.removedEarly': 'split', 'mod.removedLast': 'dce-3'})


if __name__ == '__main__':
    unittest.main()
