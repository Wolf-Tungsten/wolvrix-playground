"""Keep runtime timing units intact through module attribution."""

import io
from pathlib import Path
import tempfile
import unittest

import grhsim_module_attribution as attribution


ROOT = Path(__file__).resolve().parents[1]


class TimingUnitTests(unittest.TestCase):
    def test_units_preserve_values_and_labels(self):
        manifest, expected, _ = attribution.build_selftest_inputs()
        work = ROOT / "ptmp/remove-grhsim-ir/attribution-tests"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as directory:
            for unit in ("cycles", "nanoseconds"):
                path = Path(directory) / "timing.tsv"
                path.write_text(f"supernode_id\tphase\tfires\t{unit}\n" + "".join(
                    f"{ordinal}\t{phase}\t{fires}\t{ticks}\n"
                    for (ordinal, phase), (fires, ticks) in expected.items()))
                rows = attribution.read_timing(path)
                self.assertEqual(rows, expected)
                self.assertEqual(rows.unit, unit)
                analysis = attribution.analyze(manifest, rows, attribution.DEFAULT_WIDTH_MODEL, (1, 2), 3)
                self.assertEqual(analysis.time_unit, unit)
                self.assertTrue(analysis.conservation_ok)
                self.assertEqual(analysis.total_fired_cycles, sum(ticks for _, ticks in expected.values()))
                tsv, report = io.StringIO(), io.StringIO()
                attribution.write_tsv(analysis, tsv)
                attribution.write_report(analysis, manifest, path, report)
                self.assertIn(f"{unit}_equal\t{unit}_dominant", tsv.getvalue())
                self.assertIn(f"total fired {unit}:", report.getvalue())
                if unit == "nanoseconds":
                    self.assertNotIn("cycles", tsv.getvalue())
                    self.assertNotIn("cycles", report.getvalue())

    def test_ambiguous_or_invalid_unit_rejected(self):
        work = ROOT / "ptmp/remove-grhsim-ir/attribution-tests"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as directory:
            path = Path(directory) / "timing.tsv"
            for header, values in (
                ("cycles\tnanoseconds", "12\t34"), ("ticks", "12"),
                ("nanoseconds", "-1"), ("cycles", "invalid"),
            ):
                path.write_text(f"supernode_id\tphase\tfires\t{header}\n0\tGeneral\t1\t{values}\n")
                with self.subTest(header=header, values=values), self.assertRaises(attribution.AttributionError):
                    attribution.read_timing(path)


if __name__ == "__main__":
    unittest.main()
