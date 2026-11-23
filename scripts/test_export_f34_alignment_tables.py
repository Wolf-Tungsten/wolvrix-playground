"""Contract tests for parallel F34 snapshot and migration-table export."""

import json
from pathlib import Path
import tempfile
import unittest

import export_f34_alignment_tables as export


def write_table(path, engine, stage, header, rows, session):
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema": "semantic-node-exchange.v1", "engine": engine, "run_id": "test-run",
        "graph_id": "top", "exchange_session_id": session, "snapshot_id": session + "-snapshot",
        "stage": stage, "table": path.stem,
    }
    with path.open("w") as stream:
        stream.write("#meta\t" + json.dumps(metadata) + "\n")
        stream.write("\t".join(header) + "\n")
        for row in rows:
            stream.write("\t".join(export.tsv(value) for value in row) + "\n")
        stream.write("#footer\t" + json.dumps({"complete": True, "rowCount": len(rows)}) + "\n")


def node_row(node_id, name):
    return (node_id, json.dumps([name]), name)


def engine_metadata(path):
    with path.open() as stream:
        return json.loads(next(stream).split("\t", 1)[1])


def edge_row(edge_id, source, target, kind="dependency", resolution="resolved", candidates="[]", reason=None):
    return (edge_id, source, target, kind, resolution, candidates, reason)


def capture(root, engine, old_names, new_names, old_edges, new_edges):
    for point, names, edges, stage, session in (
        ("R0", old_names, old_edges, "post-third-dead-code-elim", "s0"),
        ("R1", new_names, new_edges, "post-alias-analysis", "s1"),
    ):
        write_table(root / point / "nodes.tsv", engine, stage, export.NODE_HEADER,
                    [node_row(node_id, name) for node_id, name in names], session)
        write_table(root / point / "connections.tsv", engine, stage, export.CONNECTION_HEADER,
                    edges, session)


class F34AlignmentTables(unittest.TestCase):
    def test_parallel_snapshots_and_connection_backed_migration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            grh = root / "grh-capture"
            gsim = root / "gsim-capture"
            output = root / "tables"
            capture(grh, "grh", [(1, "source"), (2, "retired"), (3, "consumer")],
                    [(1, "source"), (3, "consumer")],
                    [edge_row(1, 1, 3), edge_row(2, 2, 3)],
                    [edge_row(1, 1, 3), edge_row(2, 1, 3)])
            capture(gsim, "gsim", [(1, "source"), (2, "retired"), (3, "consumer")],
                    [(1, "source"), (3, "consumer")],
                    [edge_row(1, 1, 3), edge_row(2, 2, 3)],
                    [edge_row(1, 1, 3), edge_row(2, 1, 3)])

            manifest = export.export(grh, gsim, output)
            self.assertTrue((output / "grh/R0/nodes.tsv").is_symlink())
            self.assertTrue((output / "gsim/R1/connections.tsv").is_symlink())
            self.assertEqual(manifest["engines"], ["grh", "gsim"])
            self.assertEqual(manifest["retired_nodes"], 2)
            self.assertEqual(engine_metadata(output / "grh/R0/nodes.tsv")["engine"], "grh")
            self.assertEqual(engine_metadata(output / "gsim/R0/nodes.tsv")["engine"], "gsim")
            with (output / "migration.tsv").open() as stream:
                header = tuple(next(stream).rstrip("\n").split("\t"))
                rows = [line.rstrip("\n").split("\t") for line in stream]
            self.assertEqual(header, export.MIGRATION_HEADER)
            self.assertEqual(len(rows), 2)
            for row in rows:
                self.assertIn(row[0], {"grh", "gsim"})
                self.assertEqual(row[5], "dependency")
                self.assertEqual(row[8], "replacement-candidate")
                self.assertEqual(row[9], "1")
                self.assertEqual(row[10], "source")

    def test_ambiguous_replacements_remain_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            grh = root / "grh-capture"
            gsim = root / "gsim-capture"
            capture(grh, "grh", [(1, "old"), (2, "new-a"), (3, "new-b"), (4, "consumer")],
                    [(2, "new-a"), (3, "new-b"), (4, "consumer")],
                    [edge_row(1, 1, 4)],
                    [edge_row(1, 2, 4), edge_row(2, 3, 4)])
            capture(gsim, "gsim", [(1, "old"), (2, "new-a"), (3, "new-b"), (4, "consumer")],
                    [(2, "new-a"), (3, "new-b"), (4, "consumer")],
                    [edge_row(1, 1, 4)],
                    [edge_row(1, 2, 4), edge_row(2, 3, 4)])
            output = root / "tables"
            export.export(grh, gsim, output)
            with (output / "migration.tsv").open() as stream:
                next(stream)
                rows = [line.rstrip("\n").split("\t") for line in stream]
            self.assertEqual({row[8] for row in rows}, {"ambiguous"})
            self.assertEqual({row[0] for row in rows}, {"grh", "gsim"})

    def test_finalize_existing_validates_migration_and_writes_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            grh = root / "grh-capture"
            gsim = root / "gsim-capture"
            for engine, capture_root in (("grh", grh), ("gsim", gsim)):
                capture(capture_root, engine, [(1, "old"), (2, "new"), (3, "consumer")],
                        [(2, "new"), (3, "consumer")], [edge_row(1, 1, 3)],
                        [edge_row(1, 2, 3)])
            output = root / "tables"
            export.export(grh, gsim, output)
            (output / "manifest.json").unlink()

            manifest = export.finalize_existing(grh, gsim, output)
            self.assertEqual(manifest["migration_rows"], 2)
            self.assertTrue((output / "manifest.json").is_file())

            (output / "manifest.json").unlink()
            migration = output / "migration.tsv"
            with migration.open() as stream:
                header = stream.readline()
            migration.write_text(header)
            with self.assertRaisesRegex(ValueError, "is missing"):
                export.finalize_existing(grh, gsim, output)
            repaired = export.finalize_existing(grh, gsim, output, repair_truncated=True)
            self.assertEqual(repaired["migration_rows"], 2)

            with migration.open("r+") as stream:
                lines = stream.readlines()
                lines[1] = lines[1].replace("old", "bad", 1)
                stream.seek(0)
                stream.writelines(lines)
                stream.truncate()
            with self.assertRaisesRegex(ValueError, "does not match"):
                export.finalize_existing(grh, gsim, output, repair_truncated=True)


if __name__ == "__main__":
    unittest.main()
