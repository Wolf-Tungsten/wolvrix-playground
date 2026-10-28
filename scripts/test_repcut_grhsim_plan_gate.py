#!/usr/bin/env python3
"""Reject the incomplete or mismatched ledgers that can mislead candidate selection."""
import argparse
import csv
import json
from pathlib import Path
import tempfile
import unittest

import repcut_grhsim_plan_gate as gate


class PlanGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def fixture(self, name, *, options=None, mask_rows=1):
        folder = self.root / name
        folder.mkdir()
        data = {
            'summary': (['part', 'precision', 'feature', 'value'], [
                ['inst_part_0', 'range', f, v] for f, v in
                [('input_mask_words', mask_rows), ('compute_groups', 1), ('groups', 1), ('batches', 1)]]),
            'groups': (['part', 'group', 'phase', 'work', 'group_mask'],
                       [['inst_part_0', 7, 'compute', 3, 1]]),
            'batch_groups': (['part', 'batch'], [['inst_part_0', 0]]),
            'input_masks': (['part', 'mask'], [['inst_part_0', 1]] * mask_rows),
            'work_inventory': (['part', 'feature', 'value'], [
                ['Ginst_part_0_model', 'compute.groups', 1]]),
            'compute_lowering': (['part', 'feature', 'value'], [['Ginst_part_0_model', 'scalar', 3]]),
            'commit_bodies': (['part', 'body'], []),
            'work_conditional': (['part', 'mask', 'value'], [['Ginst_part_0_model', 1, 3]]),
            'backend_cost': (['part', 'value'], [['Ginst_part_0_model', 3]]),
            'mechanism_cost': (['part', 'precision', 'mask', 'unit', 'feature', 'value'], [
                ['Ginst_part_0_model', 'range', 1, 'scalar', 'add', 3],
                ['Ginst_part_0_model', 'range', 3, 'scalar', 'and', 2],
                ['Ginst_part_0_model', 'range', 0, 'wide', 'mux', 900]]),
        }
        for table, (header, entries) in data.items():
            with (folder / (table + '.csv')).open('w', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(header)
                writer.writerows(entries)
        record = dict(schema='grhsim-plan-gate-v1', status='pass',
                      options=options or {'WOLVRIX_GRHSIM_INPUT_BIT_ACTIVATION': '1'},
                      clock='clock', parts=['inst_part_0'], library={'sha256': 'a'},
                      probe={'sha256': 'b'},
                      files={n: gate.identity(folder / (n + '.csv')) for n in gate.TABLES})
        gate.save(folder / 'identity.json', record)
        return folder

    def test_complete_and_legally_empty_input_masks(self):
        for count in (0, 1):
            data = gate.validate(self.fixture(f'complete_{count}', mask_rows=count))
            self.assertEqual(data['parts'], ['inst_part_0'])
            self.assertEqual(data['row_counts']['input_masks'], count)
            self.assertEqual(data['conditional']['inst_part_0']['rise.scalar.add'], 3)
            self.assertEqual(data['conditional']['inst_part_0']['fall.scalar.and'], 2)
            self.assertNotIn('rise.wide.mux', data['conditional']['inst_part_0'])

    def test_missing_work_export_is_not_zero_work(self):
        folder = self.fixture('missing')
        (folder / 'compute_lowering.csv').unlink()
        with self.assertRaises(FileNotFoundError):
            gate.validate(folder)

    def test_empty_lowering_table_is_rejected(self):
        folder = self.fixture('empty')
        (folder / 'compute_lowering.csv').write_text('part,feature,value\n')
        with self.assertRaisesRegex(ValueError, 'missing compute lowering'):
            gate.validate(folder)

    def test_truncated_input_masks_are_rejected(self):
        folder = self.fixture('masks')
        (folder / 'input_masks.csv').write_text('part,mask\n')
        with self.assertRaisesRegex(ValueError, 'input-mask rows'):
            gate.validate(folder)

    def test_modified_artifact_is_rejected(self):
        folder = self.fixture('modified')
        with (folder / 'work_inventory.csv').open('a') as stream:
            stream.write('Ginst_part_0_model,extra,99\n')
        with self.assertRaisesRegex(ValueError, 'analysis table changed'):
            gate.load_verified(folder)

    def test_options_must_match_even_with_identical_csvs(self):
        a = self.fixture('a')
        b = self.fixture('b', options={'WOLVRIX_GRHSIM_INPUT_BIT_ACTIVATION': '0'})
        with self.assertRaisesRegex(ValueError, 'different options'):
            gate.compare(argparse.Namespace(baseline=a, candidate=b, output=self.root / 'diff.json'))

    def test_identical_input_has_no_deltas(self):
        a = self.fixture('identical')
        out = self.root / 'diff.json'
        gate.compare(argparse.Namespace(baseline=a, candidate=a, output=out))
        result = json.loads(out.read_text())
        self.assertEqual(result['status'], 'valid')
        self.assertTrue(all(value['delta'] == 0 for value in result['parts']['inst_part_0'].values()))

    def test_phase_risk_is_attached_after_identity_verification(self):
        a = self.fixture('phase_a')
        b = self.fixture('phase_b')
        out = self.root / 'phase_diff.json'
        gate.compare(argparse.Namespace(baseline=a, candidate=b, output=out, phase_risk=True))
        risk = json.loads(out.read_text())['phase_risk']
        self.assertEqual(risk['changed_parts'], [])
        self.assertTrue(risk['rule']['comparison_identity_checked'])
        c = self.fixture('phase_mismatch', options={'WOLVRIX_GRHSIM_INPUT_BIT_ACTIVATION': '0'})
        with self.assertRaisesRegex(ValueError, 'different options'):
            gate.compare(argparse.Namespace(baseline=a, candidate=c, output=out, phase_risk=True))

    def test_explicit_budgets_keep_source_and_global_risk_separate(self):
        report = {'global': {'work': {'sum': gate.delta(100, 110)}},
                  'parts': {'inst_part_2': {'work': gate.delta(20, 10)}}}
        rules = [{'scope': 'part', 'part': 'inst_part_2', 'feature': 'work', 'max_change_percent': -20},
                 {'scope': 'sum', 'feature': 'work', 'max_change_percent': 5}]
        result = gate.evaluate_budget(report, rules)
        self.assertTrue(result['checks'][0]['within_budget'])
        self.assertFalse(result['checks'][1]['within_budget'])
        self.assertFalse(result['within_budget'])
        front = gate.pareto_front({'better': [8, 9], 'worse': [9, 10], 'tradeoff': [7, 11]})
        self.assertEqual(front['worse'], ['better'])
        self.assertEqual(front['better'], [])
        self.assertEqual(front['tradeoff'], [])

    def test_zero_baseline_and_unknown_budget_fields_do_not_pass_silently(self):
        report = {'global': {'work': {'peak': gate.delta(0, 1)}}}
        rule = {'scope': 'peak', 'feature': 'work', 'max_change_percent': 10}
        self.assertFalse(gate.evaluate_budget(report, [rule])['within_budget'])
        with self.assertRaises(KeyError):
            gate.evaluate_budget(report, [dict(rule, feature='misspelled')])


if __name__ == '__main__':
    unittest.main()
