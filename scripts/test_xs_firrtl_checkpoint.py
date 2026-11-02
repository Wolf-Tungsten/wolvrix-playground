"""Failed exports must leave the previously published checkpoint intact."""

import stat
import tempfile
import unittest
from pathlib import Path

from grhsim_flow import store_checkpoint


WORK = Path(__file__).resolve().parents[1] / "ptmp/firrtl-ingest/F10/checkpoint-publication-tests"


class CheckpointPublicationTest(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)
        self.work = tempfile.TemporaryDirectory(dir=WORK)
        self.addCleanup(self.work.cleanup)
        self.path = Path(self.work.name) / "checkpoint.json"
        self.path.write_bytes(b"previous checkpoint")

    def test_only_completed_export_replaces_checkpoint(self):
        destination = self.path
        self.path.chmod(0o640)

        class Session:
            def store_json(self, **options):
                self.options = options
                self.pending = Path(options["output"])
                self.previous = destination.read_bytes()
                self.pending.write_bytes(b'{"graphs": []}')
                return []

        session = Session()
        store_checkpoint(session, self.path, design="design.main", top="top")
        self.assertEqual(session.previous, b"previous checkpoint")
        self.assertEqual(self.path.read_bytes(), b'{"graphs": []}')
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)
        self.assertEqual(session.options["mode"], "pretty-compact")
        self.assertEqual(session.options["top"], ["top"])
        self.assertEqual(session.pending.parent, self.path.parent)
        self.assertFalse(session.pending.exists())

    def test_new_checkpoint_uses_normal_file_creation_permissions(self):
        self.path.unlink()
        reference = self.path.parent / "normal-file"
        reference.write_bytes(b"reference")

        class Session:
            def store_json(self, **options):
                Path(options["output"]).write_bytes(b'{"graphs": []}')
                return []

        store_checkpoint(Session(), self.path, design="design.main", top="top")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), stat.S_IMODE(reference.stat().st_mode))

    def test_partial_failure_keeps_previous_checkpoint(self):
        class Session:
            def store_json(self, **options):
                Path(options["output"]).write_bytes(b'{"graphs": [')
                return [{"kind": "error", "message": "write failed"}]

        with self.assertRaisesRegex(RuntimeError, "write failed"):
            store_checkpoint(Session(), self.path, design="design.main", top="top")
        self.assertEqual(self.path.read_bytes(), b"previous checkpoint")
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_interrupted_export_keeps_previous_checkpoint(self):
        class Session:
            def store_json(self, **options):
                Path(options["output"]).write_bytes(b'{"graphs": [')
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            store_checkpoint(Session(), self.path, design="design.main", top="top")
        self.assertEqual(self.path.read_bytes(), b"previous checkpoint")
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_missing_export_is_not_published(self):
        class Session:
            def store_json(self, **options):
                return []

        with self.assertRaisesRegex(RuntimeError, "empty checkpoint"):
            store_checkpoint(Session(), self.path, design="design.main", top="top")
        self.assertEqual(self.path.read_bytes(), b"previous checkpoint")
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])


if __name__ == "__main__":
    unittest.main()
