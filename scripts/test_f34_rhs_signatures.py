"""Deterministic comparison and failure contracts for the F34 RHS ledger."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from f34_rhs_signatures import (
    BOUNDARIES, FIELDS, HEADER, LEDGER, ROOT, SCHEMA, TABLE, UNKNOWN, canonical_boundaries, compare, differences,
    name_list, preflight, read_table, replacement_sources, tsv_row,
)
from benchmark_xs_firrtl_ingest import request_from_manifest
from capture_f32_pipeline import action
from semantic_node_exchange import compact, decode_cell


GRH_ALIAS = ('true', 'kAssign', 'reference', 8, 'false', '[]', 'source', '[]', 1, 1, 'false')
GSIM_ALIAS = ('true', 'OP_EMPTY:nodePtr', 'reference', 8, 'false', '[]', 'source', '[]', 1, 1, 'false')


def with_fields(signature, **fields):
    return tuple(fields.get(field, value) for field, value in zip(FIELDS, signature))


class RhsContract(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.grh = self.work / 'grh'
        self.gsim = self.work / 'gsim'
        self.ledger = self.work / 'ledger.tsv'

    def table(self, engine, boundary, rows, header=HEADER):
        directory, stage = ((self.grh, boundary) if engine == 'grh'
                            else (self.gsim, BOUNDARIES[boundary][1]))
        directory = directory / stage
        directory.mkdir(parents=True, exist_ok=True)
        data = '#meta\t' + compact(dict(schema=SCHEMA, engine=engine, stage=stage, table=TABLE, scope='all')) + '\n'
        data += tsv_row(header)
        for name, node, signature in rows:
            if engine == 'gsim' and stage == 'Init':
                signature = with_fields(signature, width=UNKNOWN, signed=UNKNOWN)
            data += tsv_row((name, node, *signature))
        data += '#footer\t' + compact(dict(complete=True, rowCount=len(rows))) + '\n'
        (directory / (TABLE + '.tsv')).write_text(data)

    def run_ledger(self, points, names):
        compare(self.grh, self.gsim, points, names, self.ledger)
        lines = self.ledger.read_text().splitlines()
        self.assertEqual(tuple(lines[0].split('\t')), LEDGER)
        records = [dict(zip(LEDGER, map(decode_cell, line.split('\t')))) for line in lines[1:]]
        return {row['name']: row for row in records}

    def test_missing_boundary_rejected(self):
        self.table('grh', 'B0', [])
        with self.assertRaisesRegex(ValueError, 'missing boundary B0'):
            self.run_ledger(('B0',), {'x': set()})
        self.assertFalse(self.ledger.exists())

    def test_preflight_waits_for_both_thresholds(self):
        group = self.work / 'cgroup'
        group.mkdir()
        pressure = group / 'memory.pressure'
        pressure.write_text('some avg10=5.00 avg60=0.00 avg300=0.00 total=0\n')
        (group / 'memory.stat').write_text('anon 1\nfile 2\nactive_file 3\n')
        log = self.work / 'preflight.log'
        availability = iter((119, 120, 120))

        def read_free(*_args, **_kwargs):
            return f'Mem: 187 0 0 0 0 {next(availability)}\n'

        def relax_pressure(_seconds):
            if sleep.call_count == 2:
                pressure.write_text('some avg10=4.99 avg60=0.00 avg300=0.00 total=0\n')

        with patch('f34_rhs_signatures.subprocess.check_output', side_effect=read_free):
            with patch('f34_rhs_signatures.time.sleep', side_effect=relax_pressure) as sleep:
                preflight(log, group)
        self.assertEqual(sleep.call_count, 2)
        self.assertIn('available_gib=120 some_avg10=4.99 passed', log.read_text())

    def test_reordering_keeps_native_rows_joined_by_name(self):
        self.table('grh', 'B0', [('x', 1, GRH_ALIAS), ('y', 2, GRH_ALIAS)])
        self.table('gsim', 'B0', [('y', 3, GSIM_ALIAS), ('x', 4, GSIM_ALIAS)])
        rows = self.run_ledger(('B0',), {'y': set(), 'x': set()})
        self.assertEqual({name: row['differing_fields'] for name, row in rows.items()}, {'x': '', 'y': ''})

    def test_missing_field_rejected(self):
        self.table('grh', 'B0', [('x', 1, GRH_ALIAS)], header=HEADER[:-1])
        self.table('gsim', 'B0', [('x', 2, GSIM_ALIAS)])
        with self.assertRaisesRegex(ValueError, 'missing or reordered signature field'):
            self.run_ledger(('B0',), {'x': set()})
        self.assertFalse(self.ledger.exists())
        self.table('grh', 'B0', [('x', 1, GRH_ALIAS[:-1])])
        with self.assertRaisesRegex(ValueError, 'missing signature field'):
            self.run_ledger(('B0',), {'x': set()})

    def test_multi_anchor_preserves_existence_and_predecessors(self):
        multi_anchor = ('true', None, None, None, None, None, None, None, 1, None, None)
        self.table('grh', 'R0', [('x', 1, multi_anchor)])
        self.table('gsim', 'R0', [('x', 2, GSIM_ALIAS)])
        row = self.run_ledger(('R0',), {'x': {'A'}})['x']
        raw = json.loads(row['grh_signature'])
        self.assertTrue(raw['exists'])
        self.assertEqual(raw['predecessor_count'], 1)
        self.assertIsNone(raw['root_op'])
        self.assertIsNone(raw['assignment_count'])
        self.assertNotIn('exists', row['differing_fields'])

    def test_unnamed_node_does_not_supply_a_name(self):
        self.table('grh', 'B0', [(None, 1, GRH_ALIAS)])
        self.table('gsim', 'B0', [('x', 1, GSIM_ALIAS)])
        row = self.run_ledger(('B0',), {'x': {'D'}})['x']
        self.assertEqual(row['differing_fields'], 'exists')
        self.assertFalse(json.loads(row['grh_signature'])['exists'])

    def test_side_specific_names_and_cohort_membership(self):
        for cohort, name in [('C', 'grhOnly'), ('D', 'gsimOnly')]:
            (self.work / f'cohort-{cohort}.tsv').write_text('name\tgrh_node_id\tgsim_node_id\n' + name + '\t1\t2\n')
        self.table('grh', 'R1', [('grhOnly', 1, GRH_ALIAS)])
        self.table('gsim', 'R1', [('gsimOnly', 2, GSIM_ALIAS)])
        rows = self.run_ledger(('R1',), name_list(sorted(self.work.glob('cohort-*.tsv'))))
        self.assertEqual({name: (row['cohort'], row['differing_fields'], row['disposition'])
                          for name, row in rows.items()},
                         {'grhOnly': ('C', 'exists', ''), 'gsimOnly': ('D', 'exists', '')})

    def test_first_middle_divergence_survives_later_agreement(self):
        points = ('B0', 'P1', 'P2', 'P3')
        for point in points:
            grh = GRH_ALIAS if point != 'P2' else with_fields(
                GRH_ALIAS, root_class='kConcat', named_source=None, predecessor_count=2)
            self.table('grh', point, [('x', 3, grh)])
            self.table('gsim', point, [('x', 2, GSIM_ALIAS)])
        row = self.run_ledger(points, {'x': {'B'}})['x']
        self.assertEqual((row['divergence_boundary'], row['culprit_pass'], row['differing_fields']),
                         ('P2', 'used-bits#0 / UsedBits', 'root_class,named_source,predecessor_count'))
        self.assertEqual(row['unknown_fields'], 'width,signed')

    def test_native_root_spelling_is_evidence_at_known_width(self):
        for side, signature in [('grh', GRH_ALIAS), ('gsim', GSIM_ALIAS)]:
            self.table(side, 'B1', [('x', 1, signature)])
        row = self.run_ledger(('B1',), {'x': set()})['x']
        self.assertEqual(row['divergence_boundary'], '')
        self.assertEqual(row['unknown_fields'], '')

    def test_init_unknown_width_and_sign_are_skipped(self):
        self.table('grh', 'B0', [('x', 1, GRH_ALIAS)])
        self.table('gsim', 'B0', [('x', 1, with_fields(GSIM_ALIAS, width=None, signed=None))])
        row = self.run_ledger(('B0',), {'x': set()})['x']
        self.assertEqual(row['differing_fields'], '')
        self.assertEqual(row['unknown_fields'], 'width,signed')

    def test_null_field_is_not_unknown(self):
        self.table('grh', 'B1', [('x', 1, GRH_ALIAS)])
        self.table('gsim', 'B1', [('x', 1, with_fields(GSIM_ALIAS, width=None, signed=None))])
        row = self.run_ledger(('B1',), {'x': set()})['x']
        self.assertEqual(row['differing_fields'], 'width,signed')
        self.assertEqual(row['unknown_fields'], '')

    def test_boundaries_canonicalize_and_refuse_duplicates(self):
        self.assertEqual(canonical_boundaries('P3,Q0,Q2,R1'), ('P3', 'P4', 'R0', 'R1'))
        with self.assertRaisesRegex(ValueError, 'production order'):
            canonical_boundaries('Q0,P4')

    def test_indexed_node_root_mapping_preserves_indices(self):
        grh = (True, 'kAssign', 'array_index', 8, False, [], 'elements', [1], 1, 1, False)
        gsim = with_fields(grh, root_op='OP_EMPTY:nodePtr')
        self.assertEqual(differences(grh, gsim), ([], []))
        self.assertEqual(differences(grh, with_fields(gsim, constant_indices=[None])), (['constant_indices'], []))

    def test_replacement_sources_use_the_expression_root(self):
        cohort = self.work / 'cohort-A.tsv'
        cohort.write_text('name\tgrh_node_id\tgsim_node_id\nx\t10\t1\n')
        index = self.work / 'migrations.tsv'
        index.write_text('from_id\tto_id\troot_node\n1\t2\t3\n7\t2\t2\n')
        nodes = self.work / 'nodes.tsv'
        nodes.write_text('#meta\t{"engine":"gsim"}\nnode_id\tname_path_json\tnative_name\n'
                         '2\t["direct"]\tdirect\n3\t["a","root"]\ta$root\n'
                         '#footer\t{"complete":true,"rowCount":2}\n')
        self.assertEqual(replacement_sources([cohort], index, nodes), {'a.root'})

    def test_native_grh_keeps_one_hop_and_preserves_multi_anchor_ambiguity(self):
        import wolvrix

        selected = self.work / 'native-names.txt'
        selected.write_text('fullBits\n')
        stored = self.work / 'before.json'
        reread = self.work / 'after.json'
        request = request_from_manifest(ROOT / 'scripts/fixtures/f34_rhs_roots.json')
        with wolvrix.Session() as session:
            action(session.read_sources(**request), 'fixture')
            action(session.store_json(design='design.main', output=str(stored)), 'store before')
            action(session.semantic_snapshot(design='design.main', output=str(self.work), stage='B0',
                                             rhs_only=True, rhs_names=str(selected)), 'one hop')
            rows, _ = read_table(self.work / (TABLE + '.tsv'), 'grh', 'B0',
                                 {'fullBits', 'namedAlias', 'source'})
            self.assertEqual(set(rows), {'fullBits', 'namedAlias'})
            action(session.store_json(design='design.main', output=str(reread)), 'store after')
            self.assertEqual(stored.read_bytes(), reread.read_bytes())

            design = json.loads(stored.read_text())
            nodes = {node['name']: node for node in design['graphs'][0]['semanticTree']['nodes']}
            nodes['namedAlias']['anchors'] += nodes['source']['anchors']
            action(session.load_json_text(json.dumps(design), out_design='design.multiple'), 'multi-anchor fixture')
            action(session.semantic_snapshot(design='design.multiple', output=str(self.work), stage='B0',
                                             rhs_only=True, rhs_names=str(selected)), 'multi-anchor export')
            rows, _ = read_table(self.work / (TABLE + '.tsv'), 'grh', 'B0', {'namedAlias'})
            self.assertEqual(rows['namedAlias'][:8], (True, None, None, None, None, None, None, None))
            self.assertEqual(rows['namedAlias'][-2:], (None, None))

    def test_native_grh_reads_internal_index_slice_and_sign_views(self):
        import wolvrix

        request = request_from_manifest(ROOT / 'scripts/fixtures/f34_rhs_roots.json')
        with wolvrix.Session() as session:
            action(session.read_sources(**request), 'fixture')
            action(session.semantic_snapshot(design='design.main', output=str(self.work), stage='B0',
                                             rhs_only=True), 'normalized roots')
        rows, _ = read_table(self.work / (TABLE + '.tsv'), 'grh', 'B0',
                             {'indexed', 'partialBits', 'signedView', 'state', 'state$NEXT'})
        gsim_indexed = (True, 'OP_EMPTY:nodePtr', 'array_index', 8, False, [], 'elements', [1], 1, 1, False)
        self.assertEqual(rows['indexed'][1], 'kAssign')
        self.assertEqual(differences(rows['indexed'], gsim_indexed), ([], []))
        self.assertEqual(rows['partialBits'][1:3], ('kAssign', 'kSliceStatic'))
        self.assertEqual(rows['signedView'][1:3], ('kAssign', 'sign_view'))
        self.assertEqual(rows['signedView'][6], 'namedAlias')
        predecessor = FIELDS.index('predecessor_count')
        self.assertEqual(rows['state'][predecessor], 0)
        self.assertEqual(rows['state$NEXT'][predecessor], 1)


if __name__ == '__main__':
    unittest.main()
