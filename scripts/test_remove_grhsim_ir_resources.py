"""Concurrent tree RSS must not collapse to a maximum child or reuse PIDs."""

from pathlib import Path
import tempfile
import unittest
import shlex

from measure_remove_grhsim_ir_resources import ROOT, measure, process_snapshot, python_command, tree_sample


class ResourceTest(unittest.TestCase):
    def test_isolated_interpreter_survives_make_command(self):
        for isolated in (False, True):
            self.assertEqual(shlex.split(python_command("/workspace with spaces/python", isolated)),
                             ["/workspace with spaces/python"] + (["-S"] if isolated else []))

    def test_concurrent_tree_and_orphan_identity(self):
        row = lambda parent, group, start, rss: dict(parent=parent, group=group, start=start, rss_kib=rss)
        records = {10: row(1, 10, 100, 11), 11: row(10, 10, 101, 23),
                   12: row(11, 12, 102, 37), 90: row(1, 90, 900, 999)}
        known = set()
        self.assertEqual(tree_sample(records, 10, known), (3, 71))
        records[12]["parent"] = 1
        self.assertEqual(tree_sample(records, 10, known), (3, 71))
        records[12]["start"] = 200
        self.assertEqual(tree_sample(records, 10, known), (2, 34))

    def test_proc_stat_handles_spaces_and_parentheses(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "ptmp/remove-grhsim-ir") as directory:
            root = Path(directory); process = root / "42"; process.mkdir()
            fields = ["S", "10", "42"] + ["0"] * 16 + ["123", "1000", "7"]
            (process / "stat").write_text("42 (compiler (worker)) " + " ".join(fields))
            snapshot = process_snapshot(root)
            self.assertEqual(snapshot[42]["parent"], 10)
            self.assertEqual(snapshot[42]["start"], 123)
            self.assertGreaterEqual(snapshot[42]["rss_kib"], 7)
            fields[0] = "Z"
            (process / "stat").write_text("42 (zombie) " + " ".join(fields))
            self.assertEqual(process_snapshot(root), {})

    def test_measurement_refuses_reusing_outputs(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "ptmp/remove-grhsim-ir") as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "must be new"):
                measure("generate_remove_grhsim_ir_xs", root / "flow", root)
            (root / "flow/model").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "fresh model"):
                measure("generate_remove_grhsim_ir_xs", root / "flow", root / "out")
            with self.assertRaisesRegex(ValueError, "without compiled artifacts"):
                measure("xs_grhsim_build_emu", root / "flow", root / "out")


if __name__ == "__main__":
    unittest.main()
