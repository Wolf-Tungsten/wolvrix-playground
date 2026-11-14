"""Export and compare public SemanticNode exchange on the full FIRRTL graph."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import resource
import sqlite3
import subprocess
import time

from benchmark_xs_firrtl_ingest import checked, request_from_manifest
from benchmark_f29_pass_trace import SPLIT_MAXIMUM_S, SplitWatchdog
from semantic_node_exchange import verify_bundle
from semantic_node_exchange import HEADERS, IDENTITY, SCHEMA, parsed_row

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def last_line(path: Path) -> str:
    with path.open("rb") as stream:
        end = stream.seek(0, 2)
        size = min(end, 8192)
        while size:
            start = end - size
            stream.seek(start)
            data = stream.read(size)
            if not data.endswith(b"\n"):
                raise ValueError(f"incomplete public exchange file: {path}")
            position = data.rfind(b"\n", 0, len(data) - 1)
            if position >= 0 or start == 0:
                return data[position + 1:].decode("utf-8")
            size = min(end, size * 2)
    raise ValueError(f"empty public exchange file: {path}")


def reuse_grh_bundle(source: Path, destination: Path, input_sha256: str, pass_name: str) -> dict:
    """Bind a completed native TSV bundle to this input before the full replay."""
    source = source.resolve()
    evolution = source / "evolution.tsv"
    with evolution.open(encoding="utf-8", newline="") as stream:
        if stream.readline() != "\t".join(HEADERS["evolution"]) + "\n":
            raise ValueError(f"invalid evolution header: {evolution}")
        header = parsed_row(stream.readline(), HEADERS["evolution"])
    footer = parsed_row(last_line(evolution), HEADERS["evolution"])
    detail = json.loads(header["detail_json"])
    completion = json.loads(footer["detail_json"])
    if (header["record"] != "header" or detail.get("schema") != SCHEMA or
            detail.get("engine") != "grh" or detail.get("mode") != "trace" or
            detail.get("pass") != pass_name or detail.get("input_sha256") != input_sha256):
        raise ValueError(f"reused GRH bundle is not bound to this input/pass: {source}")
    if (footer["record"] != "footer" or completion.get("complete") is not True or
            completion.get("replayComplete") is not True):
        raise ValueError(f"reused GRH bundle is incomplete: {source}")
    for phase in ("before", "after"):
        for table in ("nodes", "connections"):
            path = source / f"{phase}.{table}.tsv"
            with path.open(encoding="utf-8", newline="") as stream:
                metadata = stream.readline()
                if not metadata.startswith("#meta\t"):
                    raise ValueError(f"missing snapshot metadata: {path}")
                metadata = json.loads(metadata[len("#meta\t"):])
                if stream.readline() != "\t".join(HEADERS[table]) + "\n":
                    raise ValueError(f"invalid snapshot columns: {path}")
            inventory_footer = last_line(path)
            if not inventory_footer.startswith("#footer\t"):
                raise ValueError(f"incomplete reused snapshot: {path}")
            inventory = json.loads(inventory_footer[len("#footer\t"):])
            count = f"{phase}{'Node' if table == 'nodes' else 'Connection'}Count"
            if (any(metadata.get(key) != detail.get(key) for key in IDENTITY) or
                    metadata.get("table") != table or
                    metadata.get("snapshot_id") != detail.get(f"{phase}_snapshot_id") or
                    inventory.get("complete") is not True or
                    inventory.get("rowCount") != completion.get(count)):
                raise ValueError(f"reused snapshot is not part of this completed bundle: {path}")
    if destination.exists() or destination.is_symlink():
        if destination.resolve() != source:
            raise ValueError(f"refusing to replace an existing exchange path: {destination}")
    else:
        destination.symlink_to(source, target_is_directory=True)
    return {"source": str(source), "bundle": str(destination), "input_sha256": input_sha256,
            "full_replay_pending": True}


def run_stage(report: dict, name: str, action):
    started = time.perf_counter()
    before = resource.getrusage(resource.RUSAGE_SELF)
    row = {"name": name, "complete": False}
    report.setdefault("stages", []).append(row)
    write_report(report)
    print(f"[F29] {name}: started", flush=True)
    try:
        result = action()
        after = resource.getrusage(resource.RUSAGE_SELF)
        row.update({"complete": True, "wall_s": time.perf_counter() - started,
                    "cpu_s": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
                    "maxrss_kib": after.ru_maxrss})
        if result is not None:
            row["result"] = result
        write_report(report)
        print(f"[F29] {name}: completed in {row['wall_s']:.3f}s", flush=True)
        return result
    except Exception as error:
        row.update({"failed": True, "wall_s": time.perf_counter() - started,
                    "error": repr(error)})
        write_report(report)
        raise


def write_report(report: dict) -> None:
    report["maxrss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    path = Path(report["report_path"])
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


def run_gsim(binary: Path, source: Path, output: Path, report: dict) -> None:
    native = output / "gsim-native"
    exchange = output / "gsim-split"
    native.mkdir(parents=True, exist_ok=True)
    command = [str(binary), "--dir", str(native), "--stop-after-stage=SplitArray",
               "--semantic-node-exchange=" + str(exchange),
               "--semantic-node-exchange-mode=trace",
               "--trace-input-sha256=" + report["input"]["sha256"], str(source)]
    report["gsim_command"] = command

    def action():
        with (output / "gsim.log").open("w") as log:
            subprocess.run(command, cwd=ROOT / "reference/gsim", stdout=log,
                           stderr=subprocess.STDOUT, check=True)
        return {"bundle": str(exchange)}

    run_stage(report, "gsim-init-to-split-array", action)


def run_grh_split(session, output: Path, report: dict) -> None:
    """Enforce the same process-based pass deadline as the benchmark."""
    case_started = time.monotonic()
    row = {"stage": "grh-split-static-array", "pass": "split-static-array"}
    result = {"name": "grh-split-static-array", "mode": "trace", "trace": True,
              "status": "running", "complete": False, "passes": []}
    report["grh_split_pass"] = result
    write_report(report)
    watchdog = SplitWatchdog({
        "timeout_s": SPLIT_MAXIMUM_S, "parent_pid": os.getpid(), "row": row,
        "result": result, "report": report, "case_started": case_started,
        "case_key": "grh_split_pass", "timing_path": str(output / "grh-split-timing.json"),
        "summary_path": report["report_path"], "marker_path": str(output / "split-timeout.marker")})
    pass_started = time.monotonic()
    watchdog.arm(pass_started)
    try:
        pass_result = session.run_pass("split-static-array", design="design.main")
    except BaseException as error:
        pass_finished = time.monotonic()
        watchdog.finish(pass_finished)
        row.update(status="failed", pass_s=pass_finished - pass_started, error=repr(error))
        result["passes"].append(row)
        result.update(status="failed", wall_s=time.monotonic() - case_started)
        report["status"] = "failed"
        write_report(report)
        raise
    pass_finished = time.monotonic()
    watchdog.finish(pass_finished)
    row["pass_s"] = pass_finished - pass_started
    result["passes"].append(row)
    try:
        checked(pass_result, "split-static-array")
    except Exception as error:
        row.update(status="failed", error=repr(error))
        result.update(status="failed", wall_s=time.monotonic() - case_started)
        report["status"] = "failed"
        write_report(report)
        raise
    row["status"] = "passed"
    result.update(status="passed", complete=True, wall_s=time.monotonic() - case_started)
    write_report(report)
    print(f"[F29] grh-split-static-array: returned in {row['pass_s']:.3f}s", flush=True)


def canonical_firrtl_path(path: str | list[str] | None) -> str | None:
    """Compare flattened and hierarchical producer paths without guessing tokens."""
    if path is None:
        return None
    tokens = json.loads(path) if isinstance(path, str) else path
    if (not isinstance(tokens, list) or not tokens or
            any(not isinstance(token, str) or not token for token in tokens)):
        raise ValueError("invalid public name_path_json")
    return ".".join(tokens)


def name_comparison_metadata() -> dict:
    return {
        "normalization": "'.'.join(name_path_json tokens); original tokens are not split",
        "scope": "current FIRRTL producer paths; not a general SystemVerilog name decoder",
        "collision_policy": "candidate path must occur exactly once on each side after normalization",
        "match_semantics": "unique normalized FIRRTL name candidate; functional equivalence is not verified",
        "node_ratio_denominator": "all GRH semanticTree leaf Nodes at the recorded stage",
    }


def public_compare(grh_db: Path, gsim_db: Path) -> dict:
    """Compare names and public connections without materializing full rows."""
    db = sqlite3.connect(":memory:")
    try:
        db.create_function("canonical_firrtl_path", 1, canonical_firrtl_path, deterministic=True)
        db.execute("ATTACH DATABASE ? AS grh", (str(grh_db),))
        db.execute("ATTACH DATABASE ? AS gsim", (str(gsim_db),))
        result = {"name_comparison": name_comparison_metadata()}
        for phase in ("before", "after"):
            counts = {}
            for engine in ("grh", "gsim"):
                counts[f"{engine}_nodes_{phase}"] = db.execute(
                    f"SELECT COUNT(*) FROM {engine}.{phase}_nodes").fetchone()[0]
                counts[f"{engine}_connections_{phase}"] = db.execute(
                    f"SELECT COUNT(*) FROM {engine}.{phase}_connections").fetchone()[0]
            result.update(counts)
            db.executescript(f"""
                DROP TABLE IF EXISTS temp.grh_names;
                DROP TABLE IF EXISTS temp.gsim_names;
                CREATE TEMP TABLE grh_names AS
                    SELECT canonical_firrtl_path(json_extract(body, '$.name_path_json')) AS path, id
                    FROM grh.{phase}_nodes
                    WHERE json_extract(body, '$.name_path_json') IS NOT NULL
                    GROUP BY path HAVING COUNT(*) = 1;
                CREATE TEMP TABLE gsim_names AS
                    SELECT canonical_firrtl_path(json_extract(body, '$.name_path_json')) AS path, id
                    FROM gsim.{phase}_nodes
                    WHERE json_extract(body, '$.name_path_json') IS NOT NULL
                    GROUP BY path HAVING COUNT(*) = 1;
                CREATE UNIQUE INDEX grh_names_path ON grh_names(path);
                CREATE UNIQUE INDEX gsim_names_path ON gsim_names(path);
                DROP TABLE IF EXISTS temp.common_names;
                CREATE TEMP TABLE common_names AS
                    SELECT g.path, g.id AS grh_id, s.id AS gsim_id
                    FROM grh_names g JOIN gsim_names s ON g.path = s.path;
                CREATE UNIQUE INDEX common_names_grh ON common_names(grh_id);
                CREATE UNIQUE INDEX common_names_gsim ON common_names(gsim_id);
                CREATE UNIQUE INDEX common_names_path ON common_names(path);
            """)
            result[f"unique_name_candidates_{phase}"] = db.execute(
                "SELECT COUNT(*) FROM common_names").fetchone()[0]
            candidates = result[f"unique_name_candidates_{phase}"]
            grh_count = result[f"grh_nodes_{phase}"]
            result[f"grh_unmatched_nodes_{phase}"] = grh_count - candidates
            result[f"gsim_unmatched_nodes_{phase}"] = result[f"gsim_nodes_{phase}"] - candidates
            result[f"grh_node_candidate_ratio_{phase}"] = candidates / grh_count if grh_count else None
            # Translate each side's local endpoint IDs to its public path, then
            # compare only resolved endpoint/kind tuples with unique paths.
            for engine in ("grh", "gsim"):
                db.execute(f"DROP TABLE IF EXISTS temp.{engine}_resolved_{phase}")
                db.execute(f"""
                    CREATE TEMP TABLE {engine}_resolved_{phase}(
                        source_path TEXT, target_path TEXT, kind TEXT,
                        PRIMARY KEY(source_path, target_path, kind)
                    ) WITHOUT ROWID
                """)
                db.execute(f"""
                    INSERT INTO {engine}_resolved_{phase}
                    SELECT DISTINCT src.path, dst.path,
                           json_extract(edge.body, '$.kind') AS kind
                    FROM {engine}.{phase}_connections edge
                    JOIN common_names dst
                      ON dst.{engine}_id = json_extract(edge.body, '$.target_node_id')
                    JOIN common_names src
                      ON src.{engine}_id = json_extract(edge.body, '$.source_node_id')
                    WHERE json_extract(edge.body, '$.resolution') = 'resolved'
                """)
                result[f"{engine}_resolved_{phase}"] = db.execute(
                    f"SELECT COUNT(*) FROM {engine}.{phase}_connections "
                    "WHERE json_extract(body, '$.resolution')='resolved'").fetchone()[0]
                result[f"{engine}_comparable_resolved_{phase}"] = db.execute(
                    f"SELECT COUNT(*) FROM {engine}_resolved_{phase}").fetchone()[0]
            result[f"matched_resolved_{phase}"] = db.execute(
                f"""SELECT COUNT(*) FROM grh_resolved_{phase} g
                    JOIN gsim_resolved_{phase} s
                    ON g.source_path=s.source_path AND g.target_path=s.target_path AND g.kind=s.kind"""
            ).fetchone()[0]
            result[f"grh_unresolved_{phase}"] = db.execute(
                f"SELECT COUNT(*) FROM grh.{phase}_connections WHERE json_extract(body, '$.resolution')='unresolved'"
            ).fetchone()[0]
            result[f"gsim_unresolved_{phase}"] = db.execute(
                f"SELECT COUNT(*) FROM gsim.{phase}_connections WHERE json_extract(body, '$.resolution')='unresolved'"
            ).fetchone()[0]
        return result
    finally:
        db.close()


def verify_grh_continuity(comb_db: Path, split_db: Path, comb: dict, split: dict) -> dict:
    """Check adjacent verified snapshots using native Node identities and edge definitions."""
    for key in ("schema", "engine", "run_id", "graph_id", "input_sha256"):
        if not comb["header"].get(key) or comb["header"][key] != split["header"].get(key):
            raise ValueError(f"GRH comb/split chain identity mismatch: {key}")
    if comb["header"]["engine"] != "grh":
        raise ValueError("comb/split continuity requires native GRH bundles")
    db = sqlite3.connect(":memory:")
    try:
        db.execute("ATTACH DATABASE ? AS comb", (str(comb_db),))
        db.execute("ATTACH DATABASE ? AS split", (str(split_db),))
        # Node IDs persist across passes. Connection IDs belong to one exchange;
        # its validated key contains the complete definition without that ID.
        for table, columns in (("nodes", "id,body"), ("connections", "key")):
            for left, right in (("comb.after", "split.before"), ("split.before", "comb.after")):
                if db.execute(f"SELECT {columns} FROM {left}_{table} EXCEPT "
                              f"SELECT {columns} FROM {right}_{table} LIMIT 1").fetchone():
                    raise ValueError(f"GRH comb.after and split.before differ: {table}")
        return {"complete": True, "exact": True,
                "from_stage": comb["after"]["metadata"]["stage"],
                "to_stage": split["before"]["metadata"]["stage"],
                "node_count": comb["footer"]["afterNodeCount"],
                "connection_count": comb["footer"]["afterConnectionCount"],
                "connection_identity": "native endpoint/kind/resolution/candidates/reason; exchange-local ID excluded"}
    finally:
        db.close()


def comparison_boundaries(grh_split: dict, gsim_split: dict, grh_comb: dict | None = None) -> dict:
    """Describe actual producer boundaries without equating two different pass scopes."""
    def segment(verification):
        return {"pass": verification["header"]["pass"],
                "before_stage": verification["before"]["metadata"]["stage"],
                "after_stage": verification["after"]["metadata"]["stage"]}

    result = {"grh_split": segment(grh_split), "gsim_split": segment(gsim_split),
              "evolution_alignment_verified": False,
              "action_counts_are_diagnostic_only": True}
    if grh_comb:
        result["grh_comb"] = segment(grh_comb)
        result["grh_pass_chain"] = [grh_comb["header"]["pass"], grh_split["header"]["pass"]]
        result["split_before_note"] = (
            "GRH split starts after comb-loop-elim; GSIM starts at Init. "
            "GSIM splitArray performs array dependency cycle elimination and splitting, "
            "so compare its evolution with the composed GRH comb+split chain.")
    else:
        result["grh_pass_chain"] = [grh_split["header"]["pass"]]
        result["split_before_note"] = (
            "No separate GRH comb evolution is included. GRH and GSIM before snapshots "
            "are compared at their recorded stages; equivalent pass scope is not assumed.")
    result["gsim_pass_chain"] = [gsim_split["header"]["pass"]]
    return result


def evolution_summary(path: Path) -> dict:
    actions, reasons, relations = Counter(), Counter(), Counter()
    events = lineages = 0
    with path.open(encoding="utf-8", newline="") as stream:
        if stream.readline() != "\t".join(HEADERS["evolution"]) + "\n":
            raise ValueError(f"invalid evolution header: {path}")
        for line in stream:
            row = parsed_row(line, HEADERS["evolution"])
            if row["record"] == "event":
                events += 1
                actions[row["action"]] += 1
                reasons[row["reason"]] += 1
            elif row["record"] == "lineage":
                lineages += 1
                detail = json.loads(row["detail_json"])
                relations[detail["relation"]] += 1
    return {"events": events, "actions": dict(sorted(actions.items())),
            "reasons": dict(sorted(reasons.items())), "lineages": lineages,
            "lineage_relations": dict(sorted(relations.items()))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firrtl", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--gsim-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-comb", action="store_true",
                        help="capture GRH split directly after hier-flatten; GSIM starts at its native Init stage")
    parser.add_argument("--no-independent-snapshots", action="store_true",
                        help="use the before/after snapshots in the trace bundle only")
    parser.add_argument("--reuse-grh-split", type=Path,
                        help="reuse a completed split-static-array five-file public exchange; skip GRH ingest")
    parser.add_argument("--reuse-grh-comb", type=Path,
                        help="also reuse a completed comb-loop-elim exchange; requires --reuse-grh-split")
    args = parser.parse_args()
    if args.reuse_grh_comb and not args.reuse_grh_split:
        parser.error("--reuse-grh-comb requires --reuse-grh-split")
    include_comb = bool(args.reuse_grh_comb) if args.reuse_grh_split else not args.skip_comb
    source = args.firrtl.resolve()
    manifest = args.manifest.resolve()
    binary = args.gsim_binary.resolve()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "ptmp"):
        parser.error("output must be under repository ptmp/")
    if not source.is_file() or not manifest.is_file() or not binary.is_file():
        parser.error("full exchange requires existing FIRRTL, manifest, and GSIM binary")
    output.mkdir(parents=True, exist_ok=True)
    report = {"schema": "wolvrix.f29.full-exchange.v1", "complete": False,
              "report_path": str(output / "summary.json"), "input": {"path": str(source)},
              "manifest": str(manifest), "gsim_binary": str(binary), "stages": [],
              "grh_mode": "reuse" if args.reuse_grh_split else "trace",
              "split_timeout_s": SPLIT_MAXIMUM_S}
    report["input"]["bytes"] = source.stat().st_size
    report["input"]["sha256"] = sha256(source)
    request = request_from_manifest(manifest)
    report["request"] = request
    write_report(report)

    def grh():
        import wolvrix
        with wolvrix.Session() as session:
            session.log_level = "info"
            session.diagnostics_raise_min_level = "none"
            checked(session.read_sources(**request, out_design="design.main", pipeline="ingest"), "ingest")
            checked(session.run_pass("xmr-resolve", design="design.main",
                                     keep_declared_symbols=True), "xmr-resolve")
            checked(session.run_pass("hier-flatten", design="design.main",
                                     keep_declared_symbols=True), "hier-flatten")
            before = output / "grh-split-before-snapshot"
            if not args.skip_comb:
                comb = output / "grh-comb"
                session.semantic_exchange_start(design="design.main", top="SimTop", output=str(comb),
                                                stage="flatten", pass_name="comb-loop-elim",
                                                input_sha256=report["input"]["sha256"])
                checked(session.run_pass("comb-loop-elim", design="design.main"), "comb-loop-elim")
                session.semantic_exchange_finish(design="design.main", top="SimTop", stage="post-comb")
            if not args.no_independent_snapshots:
                session.semantic_snapshot(design="design.main", top="SimTop", output=str(before),
                                          stage="pre-split-after-comb" if not args.skip_comb else "post-hier-flatten")
            split = output / "grh-split"
            session.semantic_exchange_start(design="design.main", top="SimTop", output=str(split),
                                            stage="post-hier-flatten" if args.skip_comb else "pre-split-after-comb",
                                            pass_name="split-static-array",
                                            input_sha256=report["input"]["sha256"], validate_at_finish=False)
            run_grh_split(session, output, report)
            session.semantic_exchange_finish(design="design.main", top="SimTop", stage="post-split-static-array")
            after = output / "grh-split-after-snapshot"
            if not args.no_independent_snapshots:
                session.semantic_snapshot(design="design.main", top="SimTop", output=str(after),
                                          stage="post-split-static-array")
        result = {"split_bundle": str(split)}
        if not args.no_independent_snapshots:
            result.update({"before_snapshot": str(before), "after_snapshot": str(after)})
        if not args.skip_comb:
            result["comb_bundle"] = str(comb)
        return result

    if args.reuse_grh_split:
        def reuse():
            result = {"grh-split": reuse_grh_bundle(
                args.reuse_grh_split, output / "grh-split", report["input"]["sha256"], "split-static-array")}
            if args.reuse_grh_comb:
                result["grh-comb"] = reuse_grh_bundle(
                    args.reuse_grh_comb, output / "grh-comb", report["input"]["sha256"], "comb-loop-elim")
            return result
        run_stage(report, "reuse-grh-public-exchange", reuse)
    else:
        run_stage(report, "grh-ingest-to-split-array", grh)
    run_gsim(binary, source, output, report)
    report["grh_verification"] = {}
    for label in (["grh-comb"] if include_comb else []) + ["grh-split"]:
        bundle = output / label
        database = output / (label + ".sqlite")
        report["grh_verification"][label] = run_stage(
            report, "replay-" + label, lambda: verify_bundle(bundle, database))
    if include_comb:
        report["grh_continuity"] = run_stage(
            report, "verify-grh-comb-to-split-continuity",
            lambda: verify_grh_continuity(
                output / "grh-comb.sqlite", output / "grh-split.sqlite",
                report["grh_verification"]["grh-comb"], report["grh_verification"]["grh-split"]))
    report["gsim_verification"] = run_stage(
        report, "replay-gsim-split",
        lambda: verify_bundle(output / "gsim-split", output / "gsim-split.sqlite"))
    report["semantic_boundaries"] = comparison_boundaries(
        report["grh_verification"]["grh-split"], report["gsim_verification"],
        report["grh_verification"].get("grh-comb"))
    report["evolution_summary"] = {
        "grh_split": evolution_summary(output / "grh-split" / "evolution.tsv"),
        "gsim_split": evolution_summary(output / "gsim-split" / "evolution.tsv"),
    }
    if include_comb:
        report["evolution_summary"]["grh_comb"] = evolution_summary(output / "grh-comb/evolution.tsv")
    report["snapshot_verification"] = {}
    # Static snapshot verification is intentionally run after trace verification;
    # this also keeps the large SQLite imports independent and auditable.
    from semantic_node_exchange import verify_snapshot
    for label in ("grh-split-before-snapshot", "grh-split-after-snapshot"):
        if not args.reuse_grh_split and not args.no_independent_snapshots and (output / label).exists():
            report["snapshot_verification"][label] = run_stage(
                report, "verify-" + label,
                lambda: verify_snapshot(output / label, output / (label + ".sqlite")))
    report["comparison"] = run_stage(
        report, "compare-public-states",
        lambda: public_compare(output / "grh-split.sqlite", output / "gsim-split.sqlite"))
    report["comparison"]["evolution"] = {
        "grh_split": report["evolution_summary"]["grh_split"],
        "gsim_split": report["evolution_summary"]["gsim_split"],
    }
    if include_comb:
        report["comparison"]["evolution"]["grh_comb"] = report["evolution_summary"]["grh_comb"]
    report["comparison"]["semantic_boundaries"] = report["semantic_boundaries"]
    if include_comb:
        report["comparison"]["grh_continuity"] = report["grh_continuity"]
    report["complete"] = True
    write_report(report)


if __name__ == "__main__":
    main()
