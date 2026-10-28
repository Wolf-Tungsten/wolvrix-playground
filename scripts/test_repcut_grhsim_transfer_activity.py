import json
from pathlib import Path
import tempfile
import unittest

from repcut_grhsim_transfer_activity import compare


def _write_variant(root: Path, variant: str, calls: int, source: str = "unit_part_0_->out_1",
                   destination: str = "unit_part_1_->in_0"):
    (root / variant / "traffic").mkdir(parents=True)
    (root / "runs").mkdir(exist_ok=True)
    sites = [{"id": 0, "sender": 0, "receiver": 1, "words": 1,
              "helper": "copy_changed_wide_words_", "dst": destination,
              "src": source, "marker": "nullptr", "tracked": False}]
    edge = {"id": 0, "sender": 0, "receiver": 1, "src": 1, "dst": 2,
            "marker": 0, "bytes": 8, "tracked": 0,
            "counts": [[0, 0, 0, 0, 0], [calls, 0, 0, calls, calls * 8],
                       [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]]}
    (root / variant / "traffic" / "sites.json").write_text(json.dumps(sites))
    record = {"status": "pass", "steps": 100, "phase_steps": [50, 50, 0, 0], "edges": [edge]}
    for index in (1, 2):
        (root / "runs" / f"traffic-{index}-{variant}.edges.json").write_text(json.dumps(record))


class TransferActivityTest(unittest.TestCase):
    def test_ignores_destination_index_and_reports_dynamic_delta(self):
        with tempfile.TemporaryDirectory() as folder:
            baseline = Path(folder) / "baseline"
            candidate = Path(folder) / "candidate"
            _write_variant(baseline, "baseline", 10)
            _write_variant(candidate, "candidate", 12, destination="unit_part_1_->in_25")
            report = compare(baseline, candidate, None, None, [], 20)
            self.assertEqual(report["totals"]["delta"]["calls"], 2)
            self.assertEqual(report["totals"]["delta"]["bytes"], 16)
            self.assertEqual(report["phases"]["all"]["changes"]["pair"]["rows"][0]["key"], [0, 1])
            self.assertEqual(report['phases']['clock0']['changes']['pair']['changed_count'], 0)
            self.assertEqual(report['phases']['clock1']['totals']['delta']['calls'], 2)

    def test_source_expression_is_a_secondary_explanation_key(self):
        with tempfile.TemporaryDirectory() as folder:
            baseline = Path(folder) / "baseline"
            candidate = Path(folder) / "candidate"
            _write_variant(baseline, "baseline", 10, "unit_part_0_->out_1")
            _write_variant(candidate, "candidate", 10, "unit_part_0_->out_2")
            report = compare(baseline, candidate, None, None, [], 20)
            self.assertEqual(report["totals"]["delta"]["bytes"], 0)
            self.assertEqual(report["phases"]["all"]["changes"]["coarse"]["changed_count"], 0)
            self.assertEqual(report["phases"]["all"]["changes"]["source"]["changed_count"], 2)

    def test_same_variant_self_compare(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _write_variant(root, 'baseline', 10)
            report = compare(root, root, None, None, [], 20, 'baseline', 'baseline')
            self.assertEqual(report['totals']['delta'], dict.fromkeys(('calls', 'scalar', 'blocks', 'tails', 'bytes'), 0))

    def test_rejects_non_repeated_counters(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _write_variant(root, 'baseline', 10)
            path = root / 'runs/traffic-2-baseline.edges.json'
            record = json.loads(path.read_text())
            record['edges'][0]['counts'][1] = [11, 0, 0, 11, 88]
            path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, 'not repeated'):
                compare(root, root, None, None, [], 20, 'baseline', 'baseline')

    def test_layout_join_checks_packet_width_and_receiver_set(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _write_variant(root, 'baseline', 10)
            layout = root / 'transfers.csv'
            layout.write_text('owner,readers,width,members\n0,1;,64,5:64:0;\n')
            report = compare(root, root, layout, layout, [], 20, 'baseline', 'baseline')
            self.assertTrue(report['layout_impact']['packet_join_audited'])
            self.assertEqual(report['layout_impact']['changed_bundle_activity'], [])
            layout.write_text('owner,readers,width,members\n0,1;,65,5:65:0;\n')
            with self.assertRaisesRegex(ValueError, 'widths differ'):
                compare(root, root, layout, layout, [], 20, 'baseline', 'baseline')


if __name__ == "__main__":
    unittest.main()
