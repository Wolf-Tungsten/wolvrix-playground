#!/usr/bin/env python3
"""Create parallel GRH/GSIM F34 node, connection and migration tables."""

from collections import defaultdict
import argparse
import json
import os
from pathlib import Path
import sqlite3

from semantic_node_exchange import decode_cell


NODE_HEADER = ("node_id", "name_path_json", "native_name")
CONNECTION_HEADER = (
    "connection_id", "source_node_id", "target_node_id", "kind", "resolution",
    "candidate_sources_json", "reason",
)
MIGRATION_HEADER = (
    "engine", "old_node_id", "old_name", "target_node_id", "target_name", "connection_kind",
    "removed_connection_count", "old_resolution", "migration_status",
    "replacement_source_node_id", "replacement_source_name", "new_resolution", "evidence",
)
INSERT_BATCH = 8192


def open_table(path, expected_header):
    stream = path.open()
    metadata = json.loads(next(stream).split("\t", 1)[1])
    header = tuple(next(stream).rstrip("\n").split("\t"))
    if header != expected_header:
        stream.close()
        raise ValueError(f"unexpected columns in {path}")
    return stream, metadata


def qualified_name(cell):
    return ".".join(json.loads(decode_cell(cell)))


def create_database(path):
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA temp_store=FILE")
    connection.execute("PRAGMA cache_size=-32768")
    connection.execute("""
        CREATE TABLE nodes(
            engine TEXT NOT NULL,
            node_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            present_r0 INTEGER NOT NULL DEFAULT 0,
            present_r1 INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(engine,node_id)
        ) WITHOUT ROWID
    """)
    connection.execute("CREATE INDEX nodes_name ON nodes(engine,name)")
    connection.execute("""
        CREATE TABLE edges(
            engine TEXT NOT NULL,
            target INTEGER NOT NULL,
            kind TEXT NOT NULL,
            source INTEGER,
            resolution TEXT NOT NULL,
            candidates TEXT NOT NULL,
            reason TEXT NOT NULL,
            old_count INTEGER NOT NULL DEFAULT 0,
            new_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(engine,target,kind,source,resolution,candidates,reason)
        ) WITHOUT ROWID
    """)
    return connection


def import_nodes(database, engine, path, *, old):
    stream, _ = open_table(path, NODE_HEADER)
    present_column = "present_r0" if old else "present_r1"
    updates = []
    try:
        count = 0
        for line in stream:
            if line.startswith("#footer\t"):
                footer = json.loads(line.split("\t", 1)[1])
                if not footer.get("complete") or footer.get("rowCount") != count:
                    raise ValueError(f"incomplete snapshot {path}")
                break
            fields = line.rstrip("\n").split("\t")
            if len(fields) != len(NODE_HEADER):
                raise ValueError(f"invalid node row in {path}")
            updates.append((engine, int(fields[0]), qualified_name(fields[1])))
            count += 1
            if len(updates) >= INSERT_BATCH:
                database.executemany(
                    f"INSERT INTO nodes(engine,node_id,name,{present_column}) VALUES(?,?,?,1) "
                    f"ON CONFLICT(engine,node_id) DO UPDATE SET name=excluded.name,{present_column}=1", updates)
                updates.clear()
        else:
            raise ValueError(f"snapshot lacks footer: {path}")
        if updates:
            database.executemany(
                f"INSERT INTO nodes(engine,node_id,name,{present_column}) VALUES(?,?,?,1) "
                f"ON CONFLICT(engine,node_id) DO UPDATE SET name=excluded.name,{present_column}=1", updates)
        database.commit()
    finally:
        stream.close()


def import_connections(database, engine, path, *, old):
    stream, _ = open_table(path, CONNECTION_HEADER)
    count_column = "old_count" if old else "new_count"
    batch = []
    try:
        count = 0
        for line in stream:
            if line.startswith("#footer\t"):
                footer = json.loads(line.split("\t", 1)[1])
                if not footer.get("complete") or footer.get("rowCount") != count:
                    raise ValueError(f"incomplete snapshot {path}")
                break
            fields = line.rstrip("\n").split("\t")
            if len(fields) != len(CONNECTION_HEADER):
                raise ValueError(f"invalid connection row in {path}")
            source = -1 if fields[1] == r"\N" else int(fields[1])
            batch.append((engine, int(fields[2]), fields[3], source, fields[4], fields[5], fields[6]))
            count += 1
            if len(batch) >= INSERT_BATCH:
                _insert_edges(database, count_column, batch)
                batch.clear()
        else:
            raise ValueError(f"snapshot lacks footer: {path}")
        if batch:
            _insert_edges(database, count_column, batch)
        database.commit()
    finally:
        stream.close()


def _insert_edges(database, count_column, batch):
    database.executemany(
        f"INSERT INTO edges(engine,target,kind,source,resolution,candidates,reason,{count_column}) "
        f"VALUES(?,?,?,?,?,?,?,1) "
        f"ON CONFLICT(engine,target,kind,source,resolution,candidates,reason) "
        f"DO UPDATE SET {count_column}={count_column}+1", batch)


def tsv(value):
    if value is None:
        return r"\N"
    return str(value).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def migration_rows(database):
    database.execute("""
        CREATE TEMP TABLE replacement_sources AS
        SELECT e.engine,e.target,e.kind,e.source,
               SUM(e.new_count-e.old_count) AS added_count,
               GROUP_CONCAT(DISTINCT e.resolution) AS resolutions
        FROM edges AS e
        JOIN nodes AS source ON source.engine=e.engine AND source.node_id=e.source
        WHERE e.new_count>e.old_count AND source.present_r1=1
        GROUP BY e.engine,e.target,e.kind,e.source
    """)
    database.execute("CREATE INDEX replacement_lookup ON replacement_sources(engine,target,kind)")
    query = database.execute("""
        SELECT e.engine,e.source,n.name,e.target,e.kind,SUM(e.old_count-e.new_count),
               GROUP_CONCAT(DISTINCT e.resolution),target_node.name
        FROM edges AS e
        JOIN nodes AS n ON n.engine=e.engine AND n.node_id=e.source
        LEFT JOIN nodes AS target_node ON target_node.engine=e.engine AND target_node.node_id=e.target
        WHERE e.old_count>e.new_count AND n.present_r0=1 AND n.present_r1=0
        GROUP BY e.engine,e.source,n.name,e.target,e.kind,target_node.name
        ORDER BY e.engine,e.target,e.kind,e.source
    """)
    cached_key = None
    cached_candidates = []
    for engine, old_id, old_name, target, kind, removed_count, old_resolution, target_name in query:
        key = (engine, target, kind)
        if key != cached_key:
            cached_candidates = database.execute("""
                SELECT r.source,n.name,r.resolutions
                FROM replacement_sources AS r
                JOIN nodes AS n ON n.engine=r.engine AND n.node_id=r.source
                WHERE r.engine=? AND r.target=? AND r.kind=?
                ORDER BY r.source
            """, key).fetchall()
            cached_key = key
        sources = {row[0] for row in cached_candidates}
        if len(sources) == 1:
            replacement = next(iter(sources))
            replacement_name = next(row[1] for row in cached_candidates if row[0] == replacement)
            resolution = next(row[2] for row in cached_candidates if row[0] == replacement)
            status = "replacement-candidate"
            evidence = "unique R1 added source to same target and kind"
        elif sources:
            replacement = replacement_name = resolution = None
            status = "ambiguous"
            evidence = "multiple R1 added sources to same target and kind"
        else:
            replacement = replacement_name = resolution = None
            status = "no-replacement"
            evidence = "no R1 added source to same target and kind"
        yield (engine, old_id, old_name, target, target_name, kind, removed_count,
               old_resolution, status, replacement, replacement_name, resolution, evidence)

    database.execute("""
        CREATE TEMP TABLE removed_sources AS
        SELECT DISTINCT engine,source FROM edges WHERE old_count>new_count
    """)
    database.execute("CREATE UNIQUE INDEX removed_sources_lookup ON removed_sources(engine,source)")
    no_edges = database.execute("""
        SELECT n.engine,n.node_id,n.name
        FROM nodes AS n
        WHERE n.present_r0=1 AND n.present_r1=0
          AND NOT EXISTS (
              SELECT 1 FROM removed_sources AS r
              WHERE r.engine=n.engine AND r.source=n.node_id
          )
        ORDER BY n.engine,n.node_id
    """)
    for engine, old_id, old_name in no_edges:
        yield (engine, old_id, old_name, None, None, None, 0, None,
               "no-outgoing-connection", None, None, None,
               "retired R0 node has no removed outgoing connection")


def write_migrations(database, output):
    count = 0
    retired_node_count = database.execute(
        "SELECT COUNT(*) FROM nodes WHERE present_r0=1 AND present_r1=0").fetchone()[0]
    with (output / "migration.tsv").open("x") as stream:
        stream.write("\t".join(MIGRATION_HEADER) + "\n")
        for values in migration_rows(database):
            stream.write("\t".join(tsv(value) for value in values) + "\n")
            count += 1
    return count, retired_node_count


def validate_existing_migrations(database, output, *, repair_truncated=False):
    path = output / "migration.tsv"
    count = 0
    expected_rows = iter(migration_rows(database))
    with path.open("r+", encoding="utf-8", newline="") as stream:
        header = stream.readline()
        if tuple(header.rstrip("\n").split("\t")) != MIGRATION_HEADER:
            raise ValueError(f"unexpected migration columns in {path}")
        for line in stream:
            expected = next(expected_rows, None)
            if expected is None:
                raise ValueError("migration TSV has extra or incomplete rows")
            expected_line = "\t".join(tsv(value) for value in expected) + "\n"
            if line != expected_line:
                raise ValueError(f"migration row {count + 1} does not match its index")
            count += 1

        next_row = next(expected_rows, None)
        if next_row is not None and not repair_truncated:
            raise ValueError(f"migration row {count + 1} is missing")
        if next_row is not None:
            stream.seek(0, os.SEEK_END)
            while next_row is not None:
                stream.write("\t".join(tsv(value) for value in next_row) + "\n")
                count += 1
                next_row = next(expected_rows, None)
            stream.flush()
            os.fsync(stream.fileno())

    retired_node_count = database.execute(
        "SELECT COUNT(*) FROM nodes WHERE present_r0=1 AND present_r1=0").fetchone()[0]
    return count, retired_node_count


def table_metadata(path, expected_header, engine, table):
    stream, metadata = open_table(path, expected_header)
    stream.close()
    if metadata.get("engine") != engine or metadata.get("table") != table:
        raise ValueError(f"unexpected snapshot metadata in {path}")
    return metadata


def write_manifest(output, captures, migration_count, retired_node_count):
    manifests = {}
    for engine, capture in captures.items():
        checkpoints = {}
        for point in ("R0", "R1"):
            point_dir = output / engine / point
            for filename, header in (("nodes.tsv", NODE_HEADER), ("connections.tsv", CONNECTION_HEADER)):
                source = capture / point / filename
                exported = point_dir / filename
                if not exported.is_symlink() or exported.resolve() != source.resolve():
                    raise ValueError(f"snapshot link mismatch: {exported}")
                table = filename.removesuffix(".tsv")
                metadata = table_metadata(source, header, engine, table)
                checkpoints.setdefault(point, {})[table] = metadata
        manifests[engine] = {"capture": str(capture.resolve()), "checkpoints": checkpoints}

    manifest = {
        "schema": "wolvrix.f34.alignment-tables.v1",
        "engines": ["grh", "gsim"], "checkpoints": ["R0", "R1"],
        "node_columns_match": True, "connection_columns_match": True,
        "migration_columns": list(MIGRATION_HEADER), "migration_rows": migration_count,
        "retired_nodes": retired_node_count,
        "migration_path": str(output / "migration.tsv"),
        "migration_index": str(output / "migration-index.sqlite"),
        "mapping_rule": "retired R0 source joined to added R1 sources by target and connection kind; ambiguous candidates remain explicit",
        "captures": manifests,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def export(grh_capture, gsim_capture, output):
    output.mkdir(parents=True, exist_ok=False)
    captures = {"grh": grh_capture, "gsim": gsim_capture}
    for engine, capture in captures.items():
        engine_dir = output / engine
        engine_dir.mkdir()
        for point in ("R0", "R1"):
            point_dir = engine_dir / point
            point_dir.mkdir()
            for filename in ("nodes.tsv", "connections.tsv"):
                source = capture / point / filename
                if not source.is_file():
                    raise FileNotFoundError(source)
                (point_dir / filename).symlink_to(source.resolve())

    database = create_database(output / "migration-index.sqlite")
    try:
        for engine, capture in captures.items():
            import_nodes(database, engine, capture / "R0/nodes.tsv", old=True)
            import_nodes(database, engine, capture / "R1/nodes.tsv", old=False)
            import_connections(database, engine, capture / "R0/connections.tsv", old=True)
            import_connections(database, engine, capture / "R1/connections.tsv", old=False)
        migration_count, retired_node_count = write_migrations(database, output)
    finally:
        database.close()

    return write_manifest(output, captures, migration_count, retired_node_count)


def finalize_existing(grh_capture, gsim_capture, output, *, repair_truncated=False):
    captures = {"grh": grh_capture, "gsim": gsim_capture}
    database_path = output / "migration-index.sqlite"
    if not database_path.is_file() or not (output / "migration.tsv").is_file():
        raise FileNotFoundError("existing alignment export lacks its migration index or TSV")
    database = sqlite3.connect(database_path)
    try:
        migration_count, retired_node_count = validate_existing_migrations(
            database, output, repair_truncated=repair_truncated)
    finally:
        database.close()
    return write_manifest(output, captures, migration_count, retired_node_count)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grh-capture", type=Path, required=True)
    parser.add_argument("--gsim-capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--finalize-existing", action="store_true")
    parser.add_argument("--repair-truncated", action="store_true")
    args = parser.parse_args()
    if args.repair_truncated and not args.finalize_existing:
        parser.error("--repair-truncated requires --finalize-existing")
    if args.finalize_existing:
        manifest = finalize_existing(
            args.grh_capture, args.gsim_capture, args.output,
            repair_truncated=args.repair_truncated)
    else:
        manifest = export(args.grh_capture, args.gsim_capture, args.output)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
