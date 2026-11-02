"""SV ingest transactions and source ownership through the public Session API."""

import json
import os
import unittest
from pathlib import Path

import wolvrix


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "wolvrix/tests/ingest/data"
WORK = Path(os.environ.get("INGEST_SESSION_TEST_WORK", ROOT / "ptmp/firrtl-ingest/F01/session"))


class IngestSessionTest(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)
        self.session = wolvrix.Session()
        self.addCleanup(self.session.close)
        self.session.diagnostics_raise_min_level = "none"
        self.session.diagnostics_print_min_level = "none"
        self.session.log_level = "off"

    def read_good(self, key="design.main", *, replace=False, args_only=False):
        path = str(DATA / "graph_assembly_basic.sv")
        diagnostics = self.session.read_sv(
            None if args_only else path, out_design=key, replace=replace,
            slang_args=([path] if args_only else []) + ["--top", "graph_assembly_basic"],
        )
        self.assertFalse(any(d["kind"] == "error" for d in diagnostics), diagnostics)

    def snapshot(self, key="design.main"):
        path = WORK / "snapshot.json"
        self.session.store_json(design=key, output=str(path))
        return json.loads(path.read_text())

    def test_failed_replacement_preserves_design_and_diagnostics(self):
        self.read_good()
        before = self.snapshot()
        diagnostics = self.session.read_sv(
            str(DATA / "stmt_lowerer_errors.sv"), replace=True,
            slang_args=["--top", "stmt_lowerer_while_stmt"],
        )
        errors = [d for d in diagnostics if d["kind"] == "error"]
        self.assertTrue(errors)
        located = [d for d in errors if d.get("file", "").endswith("stmt_lowerer_errors.sv")]
        self.assertTrue(located, errors)
        self.assertGreater(located[0]["line"], 0)
        self.assertGreater(located[0]["column"], 0)
        self.assertIn("^", located[0]["text"])
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(any(d["kind"] == "error" for d in self.session.read_sv(
            None, replace=True, slang_args=["--ingest-f01-no-such-option"])))
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(KeyError):
            self.read_good()
        self.assertEqual(self.snapshot(), before)

    def test_clone_copy_and_same_key_keep_sources(self):
        self.read_good(args_only=True)
        before = self.snapshot()
        self.session.clone_design(design="design.main", out_design="design.clone")
        self.session.copy("design.main", "design.copy")
        self.session.delete("design.main")
        self.assertEqual(self.snapshot("design.clone"), before)
        self.assertEqual(self.snapshot("design.copy"), before)
        self.session.clone_design(design="design.clone", out_design="design.clone", replace=True)
        self.session.copy("design.copy", "design.copy", replace=True)
        self.assertEqual(self.snapshot("design.clone"), before)
        self.assertEqual(self.snapshot("design.copy"), before)
        # The two clones keep their original source manager across further transactions.
        self.read_good()
        self.read_good(replace=True)
        self.assertEqual(self.snapshot("design.clone"), before)

    def test_failed_replacement_preserves_other_session_value(self):
        self.session.put("design.main", {"kept": True}, kind="fixture")
        diagnostics = self.session.read_sv(
            str(DATA / "missing-f01-input.sv"), replace=True)
        self.assertTrue(any(d["kind"] == "error" for d in diagnostics))
        self.assertEqual(self.session.get("design.main"), {"kept": True})
        self.read_good(replace=True)
        self.assertEqual(self.session.kind("design.main"), "design")

    def test_json_file_failure_preserves_existing_design_and_value(self):
        self.read_good()
        before = self.snapshot()
        valid = WORK / "valid-file-copy.json"
        valid.write_text(json.dumps(before))
        late = json.loads(valid.read_text())
        late["graphs"][-1]["ops"].append({"sym": "late_bad_file_op", "kind": "kAssign",
                                            "in": ["missing_file_value"], "out": []})
        unknown = WORK / "late-invalid-file.json"
        unknown.write_text(json.dumps(late))
        truncated = WORK / "truncated-file.json"
        truncated.write_text(valid.read_text()[:-1])
        missing = WORK / "missing-file-checkpoint.json"
        missing.unlink(missing_ok=True)
        self.session.put("kept.value", {"kept": True}, kind="fixture")
        for path in (unknown, truncated, missing):
            with self.subTest(path=path.name):
                for key in ("design.main", "kept.value", "failed.file"):
                    diagnostics = self.session.read_json_file(str(path), out_design=key, replace=True)
                    self.assertTrue(any(d["kind"] == "error" for d in diagnostics), diagnostics)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.session.get("kept.value"), {"kept": True})
                self.assertNotIn("failed.file", self.session.keys())
        diagnostics = self.session.read_json_file(str(valid), out_design="kept.value", replace=True)
        self.assertFalse(any(d["kind"] == "error" for d in diagnostics), diagnostics)
        self.assertEqual(self.snapshot("kept.value"), before)


if __name__ == "__main__":
    unittest.main()
