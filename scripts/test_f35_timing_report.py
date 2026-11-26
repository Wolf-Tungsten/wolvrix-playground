"""Test the formal pass budgets over a completed F35 timing journal."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from benchmark_f29_pass_trace import sha256, write_json_atomic
from f35_gsim_reference import BUDGET_SCHEMA, BUDGETS, FROZEN, FROZEN_SCHEMA, SUMMARY, TIMING, pass_budgets
from f35_pass_guard import EVENT_SCHEMA, GSIM_TIMER_ORDER, PASSES, REPORT_SCHEMA
from f35_timing_report import audit_timing
from semantic_node_exchange import SCHEMA as NODE_SCHEMA


class F35TimingReportTests(unittest.TestCase):
    def setUp(self):
        scratch = self.enterContext(TemporaryDirectory())
        self.grh = Path(scratch) / 'grh'
        self.gsim = Path(scratch) / 'gsim'
        self.grh.mkdir()
        self.gsim.mkdir()
        self.inputs = {'top': 'Fixture', 'sources': []}
        summary = dict(schema='wolvrix.f35.capture.v1', complete=True, top='Fixture', inputs=self.inputs)
        write_json_atomic(self.gsim / SUMMARY, {**summary, 'engine': 'gsim', 'run_id': 'gsim-test'})
        self.record_times()
        self.write_inventory(self.grh / PASSES[-1] / 'Fixture/after.nodes.tsv', 'after-' + PASSES[-1])
        snapshot = self.grh / 'R4/nodes.tsv'
        self.write_inventory(snapshot, 'post-fourth-dead-code-elim')
        self.summary = {**summary, 'engine': 'grh', 'run_id': 'grh-test',
                        'passes': [{'pass': name} for name in PASSES],
                        'reference': {'path': SUMMARY, 'run_id': 'gsim-test', **self.file_record(self.gsim / SUMMARY)},
                        'final_inventory': {'path': 'R4/nodes.tsv', **self.file_record(snapshot)}}
        write_json_atomic(self.grh / SUMMARY, self.summary)
        self.guard = dict(schema=REPORT_SCHEMA, run_id='grh-test', status='completed', returncode=0,
                          budgets_s=dict.fromkeys(PASSES, 2.0), pass_times_s=dict.fromkeys(PASSES, 1.0))
        self.write_guard()

    @staticmethod
    def file_record(path):
        return {'bytes': path.stat().st_size, 'sha256': sha256(path)}

    def record_times(self):
        timing = self.gsim / TIMING
        with timing.open('w') as stream:
            for stage, instance in GSIM_TIMER_ORDER:
                row = dict(schema='gsim-stage-timing.v1', stage=stage, pass_instance=instance,
                           scope='pass', clock='steady_clock', wall_s=1.0, complete=True, batch_count=1)
                stream.write(json.dumps(row) + '\n')
        write_json_atomic(self.gsim / BUDGETS, dict(schema=BUDGET_SCHEMA, run_id='gsim-test',
                                                   native_timing_sha256=sha256(timing),
                                                   pass_budgets=pass_budgets(timing)))
        write_json_atomic(self.gsim / FROZEN, dict(schema=FROZEN_SCHEMA, run_id='gsim-test',
                                                   files={name: self.file_record(self.gsim / name)
                                                          for name in (SUMMARY, TIMING, BUDGETS)}))

    @staticmethod
    def write_inventory(path, stage, run_id='semantic-test'):
        path.parent.mkdir(parents=True, exist_ok=True)
        header = dict(schema=NODE_SCHEMA, engine='grh', stage=stage, table='nodes', run_id=run_id,
                      graph_id='graph-test', snapshot_id=stage)
        footer = dict(complete=True, nodeInventoryComplete=True, rowCount=1)
        path.write_text(f'#meta\t{json.dumps(header)}\n#footer\t{json.dumps(footer)}\n')

    def write_guard(self, *, event_run_id='grh-test'):
        write_json_atomic(self.grh / 'guard.json', self.guard)
        with (self.grh / 'stage-events.jsonl').open('w') as stream:
            boundary = 'ingest'
            for index, name in enumerate(PASSES, start=1):
                start = dict(schema=EVENT_SCHEMA, run_id=event_run_id, logical_instance=name,
                             input_boundary=boundary, event='start', monotonic_s=index * 100)
                actual = self.guard['pass_times_s'][name]
                end = dict(start, event='end', monotonic_s=start['monotonic_s'] + actual, wall_s=actual)
                for event in (start, end):
                    stream.write(json.dumps(event) + '\n')
                boundary = name

    def audit(self):
        return audit_timing(self.grh, self.gsim, xmr_limit_s=2, flatten_limit_s=2)

    def test_equal_budget_passes_and_uses_the_original_gsim_timer(self):
        self.guard['pass_times_s'][PASSES[-1]] = 2.0
        self.write_guard()
        report = self.audit()
        self.assertTrue(report['passed'])
        self.assertEqual([row['grh_pass'] for row in report['passes']], list(PASSES))
        last = report['passes'][-1]
        self.assertEqual(last['gsim_pass_instance'], 'RemoveDeadNodes#2')
        self.assertEqual(last['grh_over_gsim'], 2.0)
        self.assertEqual(report['grh_final_inventory']['row_count'], 1)

    def test_guard_floor_does_not_raise_the_frozen_budget(self):
        self.guard['budgets_s'][PASSES[-1]] = 60.0
        self.guard['pass_times_s'][PASSES[-1]] = 3.0
        self.write_guard()
        report = self.audit()
        self.assertFalse(report['passed'])
        last = report['passes'][-1]
        self.assertFalse(last['passed'])
        self.assertEqual((last['budget_s'], last['guard_budget_s']), (2.0, 60.0))

    def test_interrupted_guard_is_rejected(self):
        self.guard['status'] = 'running'
        self.write_guard()
        with self.assertRaisesRegex(ValueError, 'guard did not complete'):
            self.audit()

    def test_journal_from_another_run_is_rejected(self):
        self.write_guard(event_run_id='another-run')
        with self.assertRaisesRegex(ValueError, 'event identity'):
            self.audit()

    def test_snapshot_from_another_semantic_run_is_rejected(self):
        self.write_inventory(self.grh / 'R4/nodes.tsv', 'post-fourth-dead-code-elim', run_id='swapped-test!')
        with self.assertRaisesRegex(ValueError, 'differs from the fourth DCE output'):
            self.audit()

    def test_summary_from_another_gsim_reference_is_rejected(self):
        self.summary['reference']['run_id'] = 'other-gsim'
        write_json_atomic(self.grh / SUMMARY, self.summary)
        with self.assertRaisesRegex(ValueError, 'does not match the frozen reference'):
            self.audit()
