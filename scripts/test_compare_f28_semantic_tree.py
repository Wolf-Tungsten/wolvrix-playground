"""Native F28 consumer checks: names are candidates; real expressions decide."""
from __future__ import annotations

import csv
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from compare_f28_semantic_tree import ROOT, Subgraphs, candidate_name, compare, qualified, records


def value(vid, width=8, shape=(), input=False):
    return {'id': vid, 'w': width, 'sgn': False, 'shape': list(shape),
            'type': 'logic', 'domain': '2state', 'in': input}


def op(oid, kind, args=(), out=(), **attrs):
    return {'id': oid, 'kind': kind, 'in': list(args), 'out': list(out), 'attrs': attrs}


def enode(eid, kind, children=(), width=8, **rest):
    return {'id': eid, 'op': kind, 'children': list(children), 'width': width, 'sign': False, **rest}


def tree(entries, root=0):
    return {'root': root, 'lvalue': len(entries), 'nodes': entries + [enode(len(entries), 'OP_EMPTY', node='unused')]}


def native(nid, name, trees=None, type='NODE_OTHERS', width=8, shape=()):
    row = {'id': nid, 'name': name, 'type': type, 'width': width, 'sign': False,
           'dimension': list(shape), 'semantic': {'path': [name], 'role': 'value'}}
    if trees is not None:
        row['assignTrees'] = trees
    return row


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        work = ROOT / 'ptmp' / 'F28-consumer-tests'
        work.mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(dir=work))
        self.gsdir = self.directory / 'gsim'
        self.gsdir.mkdir()
        self.grh = {'formatVersion': 5, 'graphs': [{'symbol': 'Top', 'semanticTree': {
            'rootPath': 1, 'namesFlattened': True, 'paths': [{'id': 1, 'parent': 0, 'name': 'Top'}],
            'nodes': []}, 'vals': [], 'ops': []}]}
        self.gs = {'nodes': [], 'memories': [], 'sourceAggregates': [], 'edges': []}

    def tearDown(self):
        shutil.rmtree(self.directory)

    @property
    def graph(self):
        return self.grh['graphs'][0]

    def node(self, nid, name, ops=(), anchors=()):
        self.graph['semanticTree']['nodes'].append({'id': nid, 'parent': 1, 'name': name,
                                                  'ops': list(ops), 'anchors': list(anchors)})

    def run_comparison(self, captures=False):
        grh = self.directory / 'flatten.json'
        grh.write_text(json.dumps(self.grh, indent=2) + '\n')
        (self.gsdir / 'Top_0Init.json').write_text(json.dumps(self.gs, indent=2) + '\n')
        if captures:
            for label, path in (('grh', grh), ('gsim', self.gsdir / 'Top_0Init.json')):
                (self.directory / f'capture-summary-{label}.json').write_text(json.dumps({
                    'complete': True, 'input': {'sha256': 'same-firrtl-content'},
                    'dump': {'path': str(path), 'bytes': path.stat().st_size,
                             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}))
        return compare(grh, self.gsdir, self.directory / 'comparison')

    def statuses(self):
        with (self.directory / 'comparison' / 'grh-nodes.tsv').open() as stream:
            return {row['qualified_name']: row for row in csv.DictReader(stream, delimiter='\t')}

    def test_combinational_alias_and_array_use_actual_member_subgraphs(self):
        self.node(1, 'x', anchors=[1])
        self.node(2, 'alias', anchors=[1])
        self.node(3, 'y', ops=[1], anchors=[2])
        self.node(4, 'arr', ops=[2, 3], anchors=[4])
        self.graph['vals'] = [value(1, input=True), value(2), value(3), value(4, 16, [2])]
        self.graph['ops'] = [op(1, 'kNot', [1], [2]),
                             op(2, 'kConstant', out=[3], constValue="8'b00000101"),
                             op(3, 'kArrayCreate', [1, 3], [4])]
        self.gs['nodes'] = [native(1, 'x', [], 'NODE_INP'),
                            native(2, 'alias', [tree([enode(0, 'OP_EMPTY', node='x')])]),
                            native(3, 'y', [tree([enode(0, 'OP_NOT', [1]), enode(1, 'OP_EMPTY', node='x')])]),
                            native(4, 'arr', [tree([enode(0, 'OP_GROUP', [1, 2]),
                               enode(1, 'OP_EMPTY', node='x'), enode(2, 'OP_INT', strVal='5')])], shape=[2])]
        result = self.run_comparison()
        self.assertEqual(result['statuses'], {'interface_checked': 1, 'expression_checked': 3})
        self.assertEqual(result['grh_op_coverage']['unique_covered_ops'], 3)
        self.assertEqual(result['grh_op_coverage']['membership_edges'], 3)
        self.assertEqual(result['candidate_fraction_of_grh_nodes'], 1)

    def test_same_name_different_expression_is_never_checked(self):
        self.node(1, 'x', anchors=[1])
        self.node(2, 'y', ops=[1], anchors=[2])
        self.graph['vals'] = [value(1, input=True), value(2)]
        self.graph['ops'] = [op(1, 'kNot', [1], [2])]
        self.gs['nodes'] = [native(1, 'x', [], 'NODE_INP'),
                            native(2, 'y', [tree([enode(0, 'OP_EMPTY', node='x')])])]
        result = self.run_comparison()
        self.assertEqual(result['unique_name_candidates'], 2)
        self.assertEqual(self.statuses()['y']['status'], 'different')
        self.assertEqual(result['checked_fraction_of_grh_nodes'], 0.5)

    def test_four_state_native_GRH_is_structural_only(self):
        self.node(1, 'x', anchors=[1])
        self.node(2, 'y', ops=[1], anchors=[2])
        self.graph['vals'] = [value(1, input=True), value(2)]
        for row in self.graph['vals']:
            row['domain'] = '4state'
        self.graph['ops'] = [op(1, 'kNot', [1], [2])]
        self.gs['nodes'] = [native(1, 'x', [], 'NODE_INP'),
                            native(2, 'y', [tree([enode(0, 'OP_NOT', [1]), enode(1, 'OP_EMPTY', node='x')])])]
        result = self.run_comparison()
        self.assertEqual(result['statuses'], {'structural_checked': 2})
        self.assertEqual(result['checked_fraction_of_grh_nodes'], 0)
        self.assertEqual(result['structurally_checked_fraction_of_grh_nodes'], 1)
        self.assertIn('X_semantics_unproved', self.statuses()['y']['reason'])

    def test_unknown_native_boundary_width_is_inferred_from_actual_assignments(self):
        self.node(1, 'x', anchors=[1])
        self.node(2, 'n', ops=[1], anchors=[2])
        self.node(3, 'y', ops=[2], anchors=[3])
        self.graph['vals'] = [value(1, input=True), value(2), value(3)]
        self.graph['ops'] = [op(1, 'kNot', [1], [2]), op(2, 'kAssign', [2], [3])]
        self.gs['nodes'] = [native(1, 'x', [], 'NODE_INP'),
                            native(2, 'n', [tree([enode(0, 'OP_NOT', [1], width=-1),
                                                  enode(1, 'OP_EMPTY', node='x')])], width=-1),
                            native(3, 'y', [tree([enode(0, 'OP_EMPTY', node='n')])])]
        result = self.run_comparison()
        self.assertEqual(result['statuses'], {'interface_checked': 1, 'expression_checked': 2})
        evidence = (self.directory / 'comparison' / 'gsim-derived-types.tsv').read_text()
        self.assertIn('2\t8\t0\t[]\tactual_native_assignTrees', evidence)

    def test_explicit_memory_address_endpoints_do_not_hide_the_reader_candidate(self):
        self.node(1, 'reader', anchors=[1])
        self.graph['vals'] = [value(1)]
        self.gs['nodes'] = [native(1, 'reader', type='NODE_READER'),
                            native(2, 'reader_addr', type='NODE_REG_SRC'),
                            native(3, 'reader_next', type='NODE_REG_DST')]
        for row, endpoint in zip(self.gs['nodes'][1:], ('current', 'next')):
            row['semantic'] = {'path': ['reader'], 'role': 'memory-read-address', 'endpoint': endpoint}
        result = self.run_comparison()
        self.assertEqual(result['unique_name_candidates'], 1)
        self.assertEqual(self.statuses()['reader']['status'], 'unverified')
        unpaired = (self.directory / 'comparison' / 'unpaired-gsim.tsv').read_text()
        self.assertEqual(unpaired.count('missing_pipeline_stage_correspondence'), 2)

    def test_memory_storage_candidate_uses_native_scope_depth_before_all_bundle_fields(self):
        self.node(1, qualified(['u', 'ram', '$storage', 'payload', 'flag']))
        self.node(2, qualified(['u', 'ram', '$storage', 'payload', 'data']))
        for nid, field in ((1, 'flag'), (2, 'data')):
            row = native(nid, f'native_{field}', type='NODE_MEMORY')
            row['semantic'] = {'path': ['u', 'ram', 'payload', field], 'scopeDepth': 1,
                               'role': 'memory-storage'}
            self.gs['memories'].append(row)
        result = self.run_comparison()
        self.assertEqual(result['unique_name_candidates'], 2)
        self.assertEqual(result['statuses'], {'unverified': 2})
        row = self.gs['memories'][0]
        self.assertEqual(candidate_name(row), r'u.ram.$storage.payload.flag')
        row['semantic']['scopeDepth'] = 2
        self.assertEqual(candidate_name(row), r'u.ram.payload.$storage.flag')
        del row['semantic']['scopeDepth']
        self.assertIsNone(candidate_name(row))
        row['semantic']['path'] = ['ram']
        self.assertEqual(candidate_name(row), 'ram.$storage')

    def seed_legacy_memory_candidates(self, anchored=False):
        self.node(1, 'x', anchors=[1])
        self.node(2, 'u.ram.$storage.payload.flag', ops=[1], anchors=[2] if anchored else [])
        self.graph['vals'] = [value(1, input=True), value(3)] + ([value(2)] if anchored else [])
        self.graph['ops'] = [op(1, 'kRegister', out=[2] if anchored else []), op(2, 'kNot', [1], [3])]
        row = native(2, 'native_memory', type='NODE_MEMORY')
        row['semantic'] = {'path': ['u', 'ram', 'payload', 'flag'], 'scopeDepth': 1,
                           'role': 'memory-storage'}
        # A storage role can occur outside the memories inventory after a
        # native replacement; the refresh must inspect the producer role.
        self.gs['nodes'] = [native(1, 'x', [], 'NODE_INP'), row]

        def legacy_candidate(item):
            if item.get('semantic', {}).get('role') == 'memory-storage':
                return qualified(item['semantic']['path'] + ['$storage'])
            return candidate_name(item)

        with patch('compare_f28_semantic_tree.candidate_name', side_effect=legacy_candidate):
            return self.run_comparison(captures=True)

    def test_refresh_reuses_unchanged_results_only_when_changed_endpoints_have_no_anchors(self):
        original = self.seed_legacy_memory_candidates()
        self.assertEqual(original['unique_name_candidates'], 1)
        output = self.directory / 'comparison'
        members = (output / 'grh-node-members.tsv').read_bytes()
        members_mtime = (output / 'grh-node-members.tsv').stat().st_mtime_ns
        (output / 'grh-node-anchors.tsv').unlink()
        # Exercise the initial report's one-time capture-identity adoption.
        original.pop('input_identity')
        (output / 'summary.json').write_text(json.dumps(original))
        with patch.object(Subgraphs, 'compare', autospec=True, side_effect=Subgraphs.compare) as checked:
            result = compare(self.directory / 'flatten.json', self.gsdir, output, reuse_index=True, refresh=True)
        self.assertEqual(checked.call_count, 1)
        self.assertEqual(result['unique_name_candidates'], 2)
        self.assertEqual(result['candidate_refresh']['changed_pair_anchor_edges'], 0)
        self.assertEqual(result['candidate_refresh']['pairs_rechecked'], 1)
        self.assertEqual(result['candidate_refresh']['recheck_scope'], 'changed_pairs_only')
        self.assertEqual((output / 'grh-node-members.tsv').read_bytes(), members)
        self.assertEqual((output / 'grh-node-members.tsv').stat().st_mtime_ns, members_mtime)
        self.assertTrue((output / 'grh-node-anchors.tsv').is_file())
        self.assertEqual(result['grh_op_coverage'], original['grh_op_coverage'])
        self.assertIn('sha256', result['input_identity']['grh'])
        diagnostic = json.loads((output / 'unlocated-ops.jsonl').read_text())
        self.assertEqual(diagnostic['op_id'], 2)
        self.assertEqual(diagnostic['op']['in'], [1])
        self.assertEqual(diagnostic['boundary_anchors'], [{'value': 1, 'node_id': 1, 'name': 'x'}])
        with sqlite3.connect(output / 'comparison.sqlite') as db:
            self.assertEqual(db.execute('SELECT node,op FROM members').fetchall(), [(2, 1)])

    def test_refresh_with_changed_anchor_premises_rechecks_all_pairs(self):
        self.seed_legacy_memory_candidates(anchored=True)
        with patch.object(Subgraphs, 'compare', autospec=True, side_effect=Subgraphs.compare) as checked:
            result = compare(self.directory / 'flatten.json', self.gsdir,
                             self.directory / 'comparison', reuse_index=True, refresh=True)
        self.assertEqual(checked.call_count, 2)
        self.assertEqual(result['candidate_refresh']['changed_pair_anchor_edges'], 1)
        self.assertEqual(result['candidate_refresh']['recheck_scope'], 'all_pairs')

    def test_refresh_rejects_changed_capture_content_identity(self):
        self.seed_legacy_memory_candidates()
        summary = self.directory / 'capture-summary-gsim.json'
        capture = json.loads(summary.read_text())
        capture['input']['sha256'] = 'different-firrtl-content'
        summary.write_text(json.dumps(capture))
        with self.assertRaisesRegex(ValueError, 'different FIRRTL content'):
            compare(self.directory / 'flatten.json', self.gsdir,
                    self.directory / 'comparison', reuse_index=True, refresh=True)

    def seed_native_inventory_refresh(self):
        self.node(1, 'x', anchors=[1])
        self.node(2, 'y', ops=[1], anchors=[2])
        self.graph['vals'] = [value(1, input=True), value(2), value(3)]
        self.graph['ops'] = [op(1, 'kNot', [1], [2]), op(2, 'kConstant', out=[3], constValue="8'b0")]
        self.graph['metadata'] = {'firrtl.invalidPolicy': {'t': 'string', 'v': 'zero'}}
        self.gs['nodes'] = [native(1, 'x', [], 'NODE_INP'),
                            native(2, 'y', [tree([enode(0, 'OP_NOT', [1]), enode(1, 'OP_EMPTY', node='x')])])]
        return self.run_comparison(captures=True)

    def new_native_capture(self, label='updated', mutate=None):
        directory = self.directory / label
        directory.mkdir()
        updated = deepcopy(self.grh)
        graph = updated['graphs'][0]
        graph['semanticTree']['nodes'][1]['ops'] = [1, 2]
        graph['ops'][1]['loc'] = {'pass': 'ingest-firrtl-abi', 'file': 'native-abi', 'line': 1}
        graph['vals'][2]['loc'] = graph['ops'][1]['loc']
        if mutate:
            mutate(graph)
        path = directory / 'flatten.json'
        path.write_text(json.dumps(updated, indent=2) + '\n')
        (directory / 'capture-summary-grh.json').write_text(json.dumps({
            'complete': True, 'input': {'sha256': 'same-firrtl-content'},
            'grh_producer_libraries': [{'sha256': 'updated-native-library'}],
            'dump': {'path': str(path), 'bytes': path.stat().st_size,
                     'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}))
        return path

    def test_native_refresh_checks_all_objects_and_rechecks_only_changed_membership_nodes(self):
        original = self.seed_native_inventory_refresh()
        source = self.directory / 'comparison' / 'summary.json'
        original_report = source.read_bytes()
        original_index = (source.parent / 'comparison.sqlite').read_bytes()
        updated = self.new_native_capture()
        with patch.object(Subgraphs, 'compare', autospec=True, side_effect=Subgraphs.compare) as checked:
            result = compare(updated, self.gsdir, updated.parent / 'comparison',
                             reuse_grh_from=source, expected_added=1)
        self.assertEqual(checked.call_count, 1)
        evidence = result['native_inventory_refresh']
        self.assertEqual(evidence['verified_objects'], {'paths': 1, 'nodes': 2, 'memberships': 2,
                                                      'anchors': 2, 'values': 3, 'ops': 2})
        self.assertEqual(evidence['member_edges_added'], 1)
        self.assertEqual(evidence['membership_nodes_changed'], 1)
        self.assertEqual(evidence['physical_payloads_changed'], 0)
        self.assertEqual(evidence['op_locations_changed'], 1)
        self.assertEqual(evidence['value_locations_changed'], 1)
        self.assertEqual(result['grh_op_coverage']['unique_covered_ops'], 2)
        self.assertEqual(result['grh_op_coverage']['uncovered_ops'], 0)
        self.assertEqual(evidence['reused_native_artifacts'], ['grh-node-anchors.tsv'])
        self.assertEqual(result['statuses'], {'interface_checked': 1, 'unverified': 1})
        self.assertEqual(source.read_bytes(), original_report)
        self.assertEqual((source.parent / 'comparison.sqlite').read_bytes(), original_index)
        self.assertEqual(original['grh_op_coverage']['unique_covered_ops'], 1)
        with sqlite3.connect(updated.parent / 'comparison' / 'comparison.sqlite') as db:
            self.assertEqual(db.execute('SELECT node,op FROM members ORDER BY node,op').fetchall(), [(2, 1), (2, 2)])
            self.assertEqual(json.loads(db.execute('SELECT payload FROM ops WHERE id=2').fetchone()[0])['loc']['pass'],
                             'ingest-firrtl-abi')
        self.assertTrue(result['complete'])

    def test_native_location_only_refresh_reports_unowned_firrtl_abi_instead_of_unknown(self):
        self.seed_native_inventory_refresh()
        updated = self.new_native_capture(mutate=lambda graph: graph['semanticTree']['nodes'][1].update(ops=[1]))
        with patch.object(Subgraphs, 'compare', autospec=True, side_effect=Subgraphs.compare) as checked:
            result = compare(updated, self.gsdir, updated.parent / 'comparison',
                             reuse_grh_from=self.directory / 'comparison' / 'summary.json', expected_added=0)
        self.assertEqual(checked.call_count, 0)
        self.assertEqual(result['grh_op_coverage']['uncovered_by_source'], {
            'confirmed_FIRRTL_missing_membership': 1, 'confirmed_SV': 0, 'unknown': 0})

    def test_native_refresh_rejects_stale_destination_artifacts_without_touching_them(self):
        self.seed_native_inventory_refresh()
        for label, filename in (('stale-members', 'grh-node-members.tsv'),
                                ('stale-uncovered', 'uncovered-ops.tsv'),
                                ('stale-jsonl', 'unlocated-ops.jsonl')):
            with self.subTest(filename=filename):
                updated = self.new_native_capture(label)
                output = updated.parent / 'comparison'
                output.mkdir()
                artifact = output / filename
                artifact.write_text('stale relation artifact\n')
                with self.assertRaisesRegex(ValueError, 'existing TSV or JSONL'):
                    compare(updated, self.gsdir, output,
                            reuse_grh_from=self.directory / 'comparison' / 'summary.json', expected_added=1)
                self.assertEqual(artifact.read_text(), 'stale relation artifact\n')
                self.assertFalse((output / 'comparison.sqlite').exists())

    def test_native_refresh_counts_shared_added_memberships_without_inflating_coverage(self):
        self.seed_native_inventory_refresh()
        updated = self.new_native_capture(mutate=lambda graph: graph['semanticTree']['nodes'][0].update(ops=[2]))
        result = compare(updated, self.gsdir, updated.parent / 'comparison',
                         reuse_grh_from=self.directory / 'comparison' / 'summary.json', expected_added=2)
        self.assertEqual(result['grh_op_coverage']['membership_edges'], 3)
        self.assertEqual(result['grh_op_coverage']['unique_covered_ops'], 2)
        self.assertEqual(result['grh_op_coverage']['shared_ops'], 1)
        self.assertEqual(result['grh_op_coverage']['empty_op_nodes'], 0)

    def test_native_refresh_rejects_changed_identity_physical_ir_or_existing_relations(self):
        self.seed_native_inventory_refresh()
        source = self.directory / 'comparison' / 'summary.json'
        original_index = (source.parent / 'comparison.sqlite').read_bytes()
        mutations = {
            'node_id': lambda g: g['semanticTree']['nodes'][1].update(id=4),
            'node_name': lambda g: g['semanticTree']['nodes'][1].update(name='other'),
            'node_parent': lambda g: g['semanticTree']['nodes'][1].update(parent=2),
            'anchors': lambda g: g['semanticTree']['nodes'][1].update(anchors=[1]),
            'boolean_anchor': lambda g: g['semanticTree']['nodes'][0].update(anchors=[True]),
            'removed_member': lambda g: g['semanticTree']['nodes'][1].update(ops=[2]),
            'duplicate_member': lambda g: g['semanticTree']['nodes'][1].update(ops=[1, 1, 2]),
            'missing_member_op': lambda g: g['semanticTree']['nodes'][1].update(ops=[1, 999]),
            'missing_node': lambda g: g['semanticTree']['nodes'].pop(),
            'missing_op': lambda g: g['ops'].pop(),
            'op_kind': lambda g: g['ops'][0].update(kind='kAssign'),
            'op_connection': lambda g: g['ops'][0].update(out=[3]),
            'value_width': lambda g: g['vals'][0].update(w=9),
            'value_number_type': lambda g: g['vals'][0].update(w=8.0),
            'root_name': lambda g: g['semanticTree']['paths'][0].update(name='Other'),
            'unflattened': lambda g: g['semanticTree'].update(namesFlattened=False),
            'metadata': lambda g: g['metadata']['firrtl.invalidPolicy'].update(v='random')}
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                updated = self.new_native_capture(label, mutate)
                with self.assertRaises(ValueError):
                    compare(updated, self.gsdir, updated.parent / 'comparison',
                            reuse_grh_from=source, expected_added=1)
                self.assertFalse(json.loads((updated.parent / 'comparison' / 'summary.json').read_text())['complete'])
                self.assertEqual((source.parent / 'comparison.sqlite').read_bytes(), original_index)

    def test_shared_coverage_unpaired_missing_dump_and_state_are_separate(self):
        self.node(1, 'x', anchors=[1])
        self.node(2, 'y', ops=[1], anchors=[2])
        self.node(3, 'shared', ops=[1], anchors=[2])
        self.node(4, 'reg', ops=[2], anchors=[3])
        self.node(5, 'only_grh')
        self.graph['vals'] = [value(1, input=True), value(2), value(3)]
        self.graph['ops'] = [op(1, 'kNot', [1], [2]), op(2, 'kRegister', out=[3]),
                             op(3, 'kConstant', constValue="1'b0")]
        self.gs['nodes'] = [native(1, 'x', [], 'NODE_INP'), native(2, 'y'),
                            native(3, 'shared'), native(4, 'reg', type='NODE_REG_SRC'), native(5, 'only_gsim')]
        result = self.run_comparison()
        self.assertEqual(result['grh_op_coverage']['shared_ops'], 1)
        self.assertEqual(result['grh_op_coverage']['membership_edges'], 3)
        self.assertEqual(result['grh_op_coverage']['unique_covered_ops'], 2)
        self.assertEqual(result['grh_op_coverage']['uncovered_ops'], 1)
        self.assertEqual(result['reasons']['assign_trees_not_dumped'], 2)
        self.assertEqual(result['reasons']['state_memory_effect_unverified'], 1)
        self.assertEqual(len((self.directory / 'comparison' / 'unpaired-grh.tsv').read_text().splitlines()), 2)
        self.assertEqual(len((self.directory / 'comparison' / 'unpaired-gsim.tsv').read_text().splitlines()), 2)

    def test_disconnected_owned_operation_prevents_complete_check(self):
        self.node(1, 'x', anchors=[1])
        self.node(2, 'y', ops=[1, 2], anchors=[2])
        self.graph['vals'] = [value(1, input=True), value(2), value(3)]
        self.graph['ops'] = [op(1, 'kAssign', [1], [2]), op(2, 'kConstant', out=[3], constValue="8'b0")]
        self.gs['nodes'] = [native(1, 'x', [], 'NODE_INP'), native(2, 'y', [tree([enode(0, 'OP_EMPTY', node='x')])])]
        self.run_comparison()
        self.assertEqual(self.statuses()['y']['reason'], 'owned_operations_not_reached_from_anchor')

    def test_uncovered_origin_requires_producer_location_and_registered_sv_input(self):
        sv = self.directory / 'source' / 'SimJTAG.v'
        firrtl = self.directory / 'source' / 'Top.fir'
        (self.directory / 'capture-summary-grh.json').write_text(json.dumps({'request': {'sources': [
            {'language': 'systemverilog', 'path': str(sv)},
            {'language': 'firrtl', 'path': str(firrtl)}]}}))
        self.node(1, 'owned_firrtl', ops=[1])
        self.graph['ops'] = [op(index, 'kConstant', constValue="1'b0") for index in range(1, 8)]
        locations = [
            {'pass': 'ingest-firrtl', 'file': str(firrtl)},
            {'pass': 'ingest-firrtl', 'file': str(sv)},
            {'file': str(sv.parent / 'nested' / '..' / sv.name)},
            {'file': str(self.directory / 'elsewhere' / sv.name)},
            {},
            {'file': str(firrtl)},
            {'file': str(firrtl), 'pass': 'ingest-sv'}]
        for row, location in zip(self.graph['ops'], locations):
            row['loc'] = location
        result = self.run_comparison()
        coverage = result['grh_op_coverage']
        self.assertEqual(coverage['total_ops'], 7)
        self.assertEqual(coverage['unique_covered_ops'], 1)
        self.assertEqual(coverage['uncovered_ops'], 6)
        self.assertEqual(coverage['covered_fraction'], 1 / 7)
        self.assertEqual(coverage['uncovered_by_source'], {
            'confirmed_FIRRTL_missing_membership': 1, 'confirmed_SV': 1, 'unknown': 4})
        with (self.directory / 'comparison' / 'uncovered-ops.tsv').open() as stream:
            rows = {int(row['op_id']): row for row in csv.DictReader(stream, delimiter='\t')}
        self.assertEqual(rows[2]['source_class'], 'confirmed_FIRRTL_missing_membership')
        self.assertEqual(rows[3]['source_class'], 'confirmed_SV')
        self.assertEqual(rows[4]['source_class'], 'unknown')
        self.assertEqual(result['uncovered_source_evidence']['registered_sv_files'], [str(sv)])

    def test_missing_source_registry_never_infers_sv_from_a_filename(self):
        self.node(1, 'arbitrary_name')
        self.graph['ops'] = [op(1, 'kConstant', constValue="1'b0"),
                             op(2, 'kConstant', constValue="1'b0")]
        self.graph['ops'][0]['loc'] = {'file': '/registered/SimJTAG.v'}
        self.graph['ops'][1]['loc'] = {'pass': 'ingest-firrtl'}
        result = self.run_comparison()
        self.assertEqual(result['grh_op_coverage']['uncovered_by_source'], {
            'confirmed_FIRRTL_missing_membership': 1, 'confirmed_SV': 0, 'unknown': 1})
        self.assertIsNone(result['uncovered_source_evidence']['capture_summary'])

    def test_missing_ir_reference_and_unflattened_tree_are_rejected(self):
        self.node(1, 'x', ops=[999])
        with self.assertRaisesRegex(ValueError, 'missing IR'):
            self.run_comparison()
        self.graph['semanticTree']['namesFlattened'] = False
        with self.assertRaisesRegex(ValueError, 'namesFlattened'):
            self.run_comparison()

    def test_qualifier_escapes_keep_literal_dots_distinct(self):
        self.assertNotEqual(qualified(['u.core', 'x']), qualified(['u', 'core', 'x']))
        self.node(1, qualified(['u.core', 'x']))
        self.gs['nodes'] = [native(1, 'native')]
        self.gs['nodes'][0]['semantic']['path'] = ['u.core', 'x']
        result = self.run_comparison()
        self.assertEqual(result['unique_name_candidates'], 1)


if __name__ == '__main__':
    unittest.main()
