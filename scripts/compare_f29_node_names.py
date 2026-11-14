"""Compare full native Node TSV inventories by unique normalized FIRRTL names.

This inventory-only report does not replay evolution or verify functional
equivalence. Producer path tokens are joined with '.', never split or guessed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import time

from export_f29_full_split_exchange import canonical_firrtl_path, name_comparison_metadata
from semantic_node_exchange import HEADERS, IDENTITY, SCHEMA, decode_cell, encode_cell, parsed_row

ROOT = Path(__file__).resolve().parents[1]
BATCH_SIZE = 20000


def save_report(report: dict) -> None:
    path = Path(report["report_path"])
    pending = path.with_suffix(".pending")
    pending.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    pending.replace(path)


def progress(report: dict, message: str, **detail) -> None:
    report["progress"] = {"stage": message, **detail}
    save_report(report)
    print(f"[F29 names] {message}: {json.dumps(detail, ensure_ascii=False)}", flush=True)


def cell(value: str) -> str | None:
    return decode_cell(value) if "\\" in value else value


def input_digest(detail: dict, source: Path, required: bool = True) -> str | None:
    nested = detail.get("input_identity")
    if nested is not None and not isinstance(nested, dict):
        raise ValueError(f"invalid native input identity: {source}")
    values = [value for value in (detail.get("input_sha256"), (nested or {}).get("sha256"))
              if value is not None]
    if not values:
        if required:
            raise ValueError(f"missing native bundle input SHA256: {source}")
        return None
    for value in values:
        if (not isinstance(value, str) or len(value) != 64 or
                any(character not in "0123456789abcdefABCDEF" for character in value)):
            raise ValueError(f"invalid native input SHA256: {source}")
    if len({value.lower() for value in values}) != 1:
        raise ValueError(f"conflicting native input SHA256 declarations: {source}")
    return values[0].lower()


def bundle_identity(bundle: Path, engine: str) -> dict:
    source = bundle / "evolution.tsv"
    with source.open(encoding="utf-8", newline="") as stream:
        if stream.readline() != "\t".join(HEADERS["evolution"]) + "\n":
            raise ValueError(f"invalid evolution columns: {source}")
        row = parsed_row(stream.readline(), HEADERS["evolution"])
    header = json.loads(row["detail_json"])
    if (row["record"] != "header" or row["seq"] != "0" or row["ordinal"] != "0" or
            header.get("schema") != SCHEMA or header.get("engine") != engine or
            header.get("mode") != "trace" or
            any(not isinstance(header.get(key), str) or not header[key]
                for key in (*IDENTITY[1:], "root_name", "before_snapshot_id", "after_snapshot_id"))):
        raise ValueError(f"invalid native bundle identity: {source}")
    digest = input_digest(header, source)
    return {"directory": str(bundle), "header": header, "input_sha256": digest}


def load_nodes(db, source: Path, prefix: str, engine: str, phase: str,
               identity: dict, report: dict) -> dict:
    header, digest = identity["header"], identity["input_sha256"]
    started = time.monotonic()
    progress(report, "import-" + prefix, source=str(source))
    db.execute(f"CREATE TABLE {prefix}_nodes(id INTEGER PRIMARY KEY, path TEXT, path_json TEXT, native_name TEXT NOT NULL)")
    count, previous, footer, batch = 0, -1, None, []
    with source.open(encoding="utf-8", newline="") as stream:
        first = stream.readline()
        if not first.startswith("#meta\t") or not first.endswith("\n"):
            raise ValueError(f"missing Node inventory metadata: {source}")
        metadata = json.loads(first[len("#meta\t"):])
        metadata_digest = input_digest(metadata, source, required=False)
        if (metadata.get("schema") != SCHEMA or metadata.get("table") != "nodes" or
                metadata.get("engine") != engine or not metadata.get("stage") or
                any(metadata.get(key) != header.get(key) for key in IDENTITY) or
                metadata.get("snapshot_id") != header[phase + "_snapshot_id"] or
                (metadata.get("root_name") is not None and metadata["root_name"] != header["root_name"]) or
                (metadata_digest is not None and metadata_digest != digest)):
            raise ValueError(f"invalid Node inventory identity: {source}")
        if stream.readline() != "\t".join(HEADERS["nodes"]) + "\n":
            raise ValueError(f"invalid Node inventory columns: {source}")
        for line in stream:
            if footer is not None or not line.endswith("\n") or line.endswith("\r\n"):
                raise ValueError(f"invalid or incomplete Node inventory: {source}")
            if line.startswith("#footer\t"):
                footer = json.loads(line[len("#footer\t"):])
                continue
            fields = line[:-1].split("\t")
            if len(fields) != 3:
                raise ValueError(f"invalid Node inventory row: {source}")
            identifier = int(fields[0])
            if identifier <= previous or str(identifier) != fields[0] or identifier > 2**63 - 1:
                raise ValueError(f"Node inventory IDs are not uniquely sorted: {source}")
            path_json, native_name = cell(fields[1]), cell(fields[2])
            if native_name is None:
                raise ValueError(f"missing native Node name: {source}")
            path = canonical_firrtl_path(path_json)
            batch.append((identifier, path, path_json, native_name))
            count, previous = count + 1, identifier
            if len(batch) == BATCH_SIZE:
                db.executemany(f"INSERT INTO {prefix}_nodes VALUES(?,?,?,?)", batch)
                batch.clear()
                if count % 1000000 == 0:
                    progress(report, "import-" + prefix, rows=count,
                             wall_s=time.monotonic() - started)
        if batch:
            db.executemany(f"INSERT INTO {prefix}_nodes VALUES(?,?,?,?)", batch)
    if (not footer or footer.get("complete") is not True or footer.get("rowCount") != count or
            footer.get("nodeInventoryComplete") is not True):
        raise ValueError(f"incomplete Node inventory footer: {source}")
    db.commit()
    progress(report, "index-" + prefix, rows=count, wall_s=time.monotonic() - started)
    db.execute(f"CREATE INDEX {prefix}_nodes_path ON {prefix}_nodes(path)")
    db.execute(f"CREATE TABLE {prefix}_names(path TEXT PRIMARY KEY, node_id INTEGER, occurrences INTEGER NOT NULL) WITHOUT ROWID")
    db.execute(f"INSERT INTO {prefix}_names SELECT path, MIN(id), COUNT(*) FROM {prefix}_nodes "
               "WHERE path IS NOT NULL GROUP BY path")
    db.commit()
    return {"source": str(source), "metadata": metadata, "footer": footer,
            "nodes": count, "wall_s": time.monotonic() - started}


def write_rows(path: Path, columns: tuple[str, ...], rows, metadata: dict, report: dict) -> Counter:
    pending = path.with_suffix(".pending")
    counts = Counter()
    with pending.open("w", encoding="utf-8", newline="") as stream:
        stream.write("#meta\t" + json.dumps(metadata, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.write("\t".join(columns) + "\n")
        for row in rows:
            stream.write("\t".join(encode_cell(value) for value in row) + "\n")
            counts["rows"] += 1
            if "reason" in columns:
                counts[row[columns.index("reason")]] += 1
            if counts["rows"] % 1000000 == 0:
                progress(report, "export-" + path.name, rows=counts["rows"])
        stream.write("#footer\t" + json.dumps({"complete": True, "rowCount": counts["rows"]}) + "\n")
    pending.replace(path)
    return counts


def compare_phase(db, phase: str, output: Path, report: dict) -> dict:
    grh, gsim = phase + "_grh", phase + "_gsim"
    grh_count = report["inventories"][grh]["nodes"]
    gsim_count = report["inventories"][gsim]["nodes"]
    candidates = db.execute(f"""SELECT COUNT(*) FROM {grh}_names g JOIN {gsim}_names s USING(path)
        WHERE g.occurrences=1 AND s.occurrences=1""").fetchone()[0]
    result = {
        "grh_nodes": grh_count, "gsim_nodes": gsim_count,
        "unique_name_candidates": candidates,
        "grh_unmatched_nodes": grh_count - candidates,
        "gsim_unmatched_nodes": gsim_count - candidates,
        "grh_node_candidate_ratio": candidates / grh_count if grh_count else None,
        "grh_node_candidate_percent": 100 * candidates / grh_count if grh_count else None,
        "grh_stage": report["inventories"][grh]["metadata"]["stage"],
        "gsim_stage": report["inventories"][gsim]["metadata"]["stage"],
        "candidate_file": str(output / f"{phase}.candidates.tsv"),
        "unmatched_file": str(output / f"{phase}.unmatched.tsv"),
        "complete": False,
    }
    report["comparison"][phase] = result
    progress(report, "counted-" + phase, **result)
    metadata = {"schema": "wolvrix.f29.node-name-candidates.v1", "phase": phase,
                "grh_stage": result["grh_stage"], "gsim_stage": result["gsim_stage"],
                **name_comparison_metadata()}
    candidate_rows = db.execute(f"""SELECT g.node_id, s.node_id, g.path
        FROM {grh}_names g JOIN {gsim}_names s USING(path)
        WHERE g.occurrences=1 AND s.occurrences=1 ORDER BY g.path""")
    written = write_rows(Path(result["candidate_file"]),
                        ("grh_node_id", "gsim_node_id", "canonical_firrtl_path"),
                        candidate_rows, metadata, report)
    if written["rows"] != candidates:
        raise ValueError("candidate export count differs from Node comparison")
    columns = ("engine", "node_id", "canonical_firrtl_path", "name_path_json", "native_name",
               "reason", "self_path_count", "peer_path_count")

    def unmatched_rows():
        for engine, own, peer in (("grh", grh, gsim), ("gsim", gsim, grh)):
            yield from db.execute(f"""SELECT ?, n.id, n.path, n.path_json, n.native_name,
                CASE WHEN n.path IS NULL THEN 'missing_public_path'
                     WHEN a.occurrences>1 THEN 'ambiguous_normalized_path_on_self'
                     WHEN b.occurrences IS NULL THEN 'missing_normalized_path_on_peer'
                     ELSE 'ambiguous_normalized_path_on_peer' END,
                COALESCE(a.occurrences,0), COALESCE(b.occurrences,0)
                FROM {own}_nodes n LEFT JOIN {own}_names a ON n.path=a.path
                LEFT JOIN {peer}_names b ON n.path=b.path
                WHERE n.path IS NULL OR a.occurrences<>1 OR b.occurrences IS NULL OR b.occurrences<>1
                ORDER BY n.id""", (engine,))

    unmatched = write_rows(Path(result["unmatched_file"]), columns, unmatched_rows(), metadata, report)
    if unmatched["rows"] != grh_count + gsim_count - 2 * candidates:
        raise ValueError("unmatched export count differs from Node comparison")
    result["unmatched_reasons"] = {key: value for key, value in unmatched.items() if key != "rows"}
    result["complete"] = True
    progress(report, "completed-" + phase, **result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grh-bundle", type=Path, required=True)
    parser.add_argument("--gsim-bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "ptmp"):
        parser.error("output must be under repository ptmp/")
    database = output / "nodes.sqlite"
    if database.exists():
        parser.error("Node comparison database already exists; choose a new output directory")
    output.mkdir(parents=True, exist_ok=True)
    report = {"schema": "wolvrix.f29.node-name-comparison.v1", "complete": False,
              "report_path": str(output / "summary.json"), "database": str(database),
              "name_comparison": name_comparison_metadata(), "inventories": {}, "comparison": {},
              "validation_scope": "Node inventories and native evolution-header identity/input binding only; connections and evolution edits are not replayed"}
    save_report(report)
    started = time.monotonic()
    db = sqlite3.connect(database)
    try:
        report["bundles"] = {engine: bundle_identity(bundle.resolve(), engine)
                             for engine, bundle in (("grh", args.grh_bundle), ("gsim", args.gsim_bundle))}
        headers = [report["bundles"][engine]["header"] for engine in ("grh", "gsim")]
        if (headers[0]["root_name"] != headers[1]["root_name"] or
                report["bundles"]["grh"]["input_sha256"] != report["bundles"]["gsim"]["input_sha256"]):
            raise ValueError("native bundles have different circuit roots or input SHA256")
        report["native_header_input_identity_verified"] = True
        report["root_name"] = headers[0]["root_name"]
        report["input_sha256"] = report["bundles"]["grh"]["input_sha256"]
        save_report(report)
        # This derived database is disposable; completed TSVs and the report
        # are published only after all counts and inventory footers agree.
        db.execute("PRAGMA journal_mode=OFF")
        db.execute("PRAGMA synchronous=OFF")
        db.execute("PRAGMA temp_store=FILE")
        db.execute("PRAGMA cache_size=-65536")
        # Publish the final-stage ratio first, independently of large edge replay.
        for phase in ("after", "before"):
            for engine, bundle in (("grh", args.grh_bundle), ("gsim", args.gsim_bundle)):
                prefix = phase + "_" + engine
                report["inventories"][prefix] = load_nodes(
                    db, bundle.resolve() / f"{phase}.nodes.tsv", prefix, engine, phase,
                    report["bundles"][engine], report)
            compare_phase(db, phase, output, report)
        report.update(complete=True, wall_s=time.monotonic() - started)
        save_report(report)
    except Exception as error:
        report.update(failed=True, error=repr(error), wall_s=time.monotonic() - started)
        save_report(report)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
