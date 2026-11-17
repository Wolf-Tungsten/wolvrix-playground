"""Inventory diagnostics do not infer missing modes or prove semantics."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from compare_f32_semantics import CAPTURE_SCHEMA, STAGES
from report_f32_inventory import ROOT, report
from semantic_node_exchange import HEADERS, SCHEMA, compact, encode_cell


class InventoryReportTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / 'ptmp/firrtl-ingest/F32/inventory-contract-tmp'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)

    def capture(self, engine, names, semantics=None):
        directory = self.work / engine
        directory.mkdir()
        summary = {'schema': CAPTURE_SCHEMA, 'engine': engine, 'status': 'completed',
            'source': 'raw-firrtl', 'trace_enabled': False, 'trace_validation': False,
            'input_sha256': 'a' * 64, 'snapshots': {}}
        for index, stage in enumerate(STAGES[engine]):
            folder = directory / f'P{index}'
            folder.mkdir()
            summary['snapshots'][f'P{index}'] = {'directory': str(folder), 'stage': stage}
        metadata = {'schema': SCHEMA, 'engine': engine, 'stage': STAGES[engine][4],
            'table': 'nodes', 'run_id': engine + '-run', 'graph_id': 'top',
            'exchange_session_id': engine + '-session', 'snapshot_id': engine + '-P4'}
        lines = ['#meta\t' + compact(metadata), '\t'.join(HEADERS['nodes'])]
        for identifier, name in enumerate(names, 1):
            path = None if name is None else [name]
            lines.append('\t'.join(encode_cell(value) for value in
                (identifier, None if path is None else compact(path), name or 'anonymous')))
        lines.append('#footer\t' + compact({'complete': True, 'nodeInventoryComplete': True,
            'rowCount': len(names)}))
        table = directory / 'P4/nodes.tsv'
        table.write_text('\n'.join(lines) + '\n')
        summary['snapshots']['P4']['artifacts'] = {'nodes.tsv': {'path': str(table),
            'bytes': table.stat().st_size, 'sha256': hashlib.sha256(table.read_bytes()).hexdigest()}}
        if semantics is not None:
            summary['window_semantics'] = semantics
            if engine == 'grh':
                passes = ('xmr-resolve', 'hier-flatten', 'comb-loop-elim', 'split-static-array',
                    'dead-code-elim', 'expr-opt', 'used-bits', 'split-nodes', 'dead-code-elim')
                summary['pass_calls'] = [{'pass': name, 'parameters':
                    {'semantics': semantics} if index in (5, 6, 7) else {}}
                    for index, name in enumerate(passes)]
        (directory / 'summary.json').write_text(compact(summary))
        return directory

    def test_legacy_mode_is_explicitly_unspecified_without_mutating_capture(self):
        grh = self.capture('grh', ['input', 'out'], '2state')
        gsim = self.capture('gsim', ['input', 'out'])
        original = (gsim / 'summary.json').read_bytes()
        result = report(grh, gsim, self.work / 'report')
        self.assertEqual(result['status'], 'diagnostic-inventory')
        self.assertEqual(result['window_semantics_by_engine'], {'grh': '2state', 'gsim': None})
        self.assertEqual(result['window_semantics_comparison'], 'unspecified')
        self.assertFalse(result['semantic_comparison_performed'])
        self.assertFalse(result['semantic_acceptance'])
        self.assertFalse(result['functional_equivalence_proved'])
        self.assertEqual((gsim / 'summary.json').read_bytes(), original)
        self.assertEqual(json.loads((self.work / 'report/summary.json').read_text()), result)

    def test_counts_and_candidates_exclude_duplicate_and_anonymous_names(self):
        grh = self.capture('grh', ['input', 'duplicate', 'duplicate', None, 'grh-only'])
        gsim = self.capture('gsim', ['input', 'duplicate', 'gsim-only'])
        result = report(grh, gsim, self.work / 'report')
        self.assertEqual({engine: row['nodes'] for engine, row in result['snapshots'].items()},
            {'grh': 5, 'gsim': 3})
        self.assertEqual(result['unique_name_candidates'], 1)
        self.assertEqual(result['grh_unique_name_candidate_ratio'], 0.2)
        self.assertEqual(result['unpaired_nodes'], {'grh': 4, 'gsim': 2})
        self.assertEqual(result['window_semantics_comparison'], 'unspecified')

    def test_explicit_mode_mismatch_stays_a_count_diagnostic(self):
        grh = self.capture('grh', ['out'], '4state')
        gsim = self.capture('gsim', ['out'], '2state')
        result = report(grh, gsim, self.work / 'report')
        self.assertEqual(result['window_semantics_comparison'], 'explicit-mismatch')
        self.assertFalse(result['semantic_acceptance'])
        self.assertEqual(result['unique_name_candidates'], 1)

    def test_equal_explicit_modes_still_do_not_prove_behavior(self):
        grh = self.capture('grh', ['out'], '2state')
        gsim = self.capture('gsim', ['out'], '2state')
        result = report(grh, gsim, self.work / 'report')
        self.assertEqual(result['window_semantics_comparison'], 'explicit-match')
        self.assertFalse(result['functional_equivalence_proved'])

    def test_changed_frozen_node_table_is_rejected(self):
        grh = self.capture('grh', ['out'])
        gsim = self.capture('gsim', ['out'])
        path = gsim / 'P4/nodes.tsv'
        path.write_bytes(path.read_bytes().replace(b'out', b'new'))
        with self.assertRaisesRegex(ValueError, 'changed since capture'):
            report(grh, gsim, self.work / 'report')

    def test_different_original_inputs_are_rejected(self):
        grh = self.capture('grh', ['out'])
        gsim = self.capture('gsim', ['out'])
        path = gsim / 'summary.json'
        summary = json.loads(path.read_text())
        summary['input_sha256'] = 'b' * 64
        path.write_text(compact(summary))
        with self.assertRaisesRegex(ValueError, 'different original FIRRTL inputs'):
            report(grh, gsim, self.work / 'report')


if __name__ == '__main__':
    unittest.main()
