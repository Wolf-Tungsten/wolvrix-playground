"""Audit the 267 exceptional F29 Node names using native split lineage.

Inputs are the current full-graph inventories and the derived native lineage
index. Name equality locates before-pass parents; parent identity plus exact
coordinates then locates after-pass members without guessing their names.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import time

from semantic_node_exchange import encode_cell, parsed_row

ROOT = Path(__file__).resolve().parents[1]
NODE_COLUMNS = ("id", "path", "path_json", "native_name")
UNMATCHED_COLUMNS = ("engine", "node_id", "canonical_firrtl_path", "name_path_json",
                     "native_name", "reason", "self_path_count", "peer_path_count")


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def node(db, phase, engine, identifier):
    row = db.execute(f"SELECT id,path,path_json,native_name FROM names.{phase}_{engine}_nodes "
                     "WHERE id=?", (identifier,)).fetchone()
    return None if row is None else dict(zip(NODE_COLUMNS, row))


def named(db, phase, engine, path):
    return [dict(zip(NODE_COLUMNS, row)) for row in db.execute(
        f"SELECT id,path,path_json,native_name FROM names.{phase}_{engine}_nodes "
        "WHERE path=? ORDER BY id", (path,))]


def coordinates(value):
    result = json.loads(value)
    if not isinstance(result, list) or any(type(item) is not int or item < 0 for item in result):
        raise ValueError("invalid native split coordinates")
    return result


def origins(db, engine, child):
    result = []
    for parent, value in db.execute(f"SELECT parent,coordinates FROM {engine}_lineage WHERE child=?",
                                    (child,)):
        result.append({"parent_id": parent, "coordinates": coordinates(value),
                       "parent_before": node(db, "before", engine, parent)})
    return result


def children(db, engine, parent):
    return [{"child_id": child, "coordinates": coordinates(value),
             "child_after": node(db, "after", engine, child)}
            for child, value in db.execute(
                f"SELECT child,coordinates FROM {engine}_lineage WHERE parent=? ORDER BY child",
                (parent,))]


def pair_origin(db, origin):
    before = origin["parent_before"]
    candidates = [] if before is None else named(db, "before", "gsim", before["path"])
    result = {"grh_parent_id": origin["parent_id"], "coordinates": origin["coordinates"],
              "grh_parent_before": before, "gsim_parent_candidates": candidates,
              "grh_before_parent_path_occurrences":
                  0 if before is None else len(named(db, "before", "grh", before["path"])),
              "gsim_members": []}
    if len(candidates) == 1 and result["grh_before_parent_path_occurrences"] == 1:
        result["gsim_parent_id"] = candidates[0]["id"]
        result["gsim_members"] = [item for item in children(db, "gsim", candidates[0]["id"])
                                  if item["coordinates"] == origin["coordinates"]]
    return result


def audit(db, target, bucket):
    identifier = int(target["node_id"])
    after = node(db, "after", "grh", identifier)
    if after is None or after["path"] != target["canonical_firrtl_path"]:
        raise ValueError("selected target differs from current GRH inventory")
    before = node(db, "before", "grh", identifier)
    relation = origins(db, "grh", identifier)
    native_children = children(db, "grh", identifier)
    exact_peers = named(db, "after", "gsim", after["path"])
    exact_details = [{"node": peer, "origins": origins(db, "gsim", peer["id"]),
                      "same_id_before": node(db, "before", "gsim", peer["id"])}
                     for peer in exact_peers]
    pairs = [pair_origin(db, item) for item in relation]
    matched = [item for pair in pairs for item in pair["gsim_members"]
               if item["child_after"] is not None]
    status = "unresolved_exception"
    correspondence = "not_established"
    naming = None
    if (len(relation) == 1 and pairs[0]["grh_before_parent_path_occurrences"] == 1 and
            len(pairs[0]["gsim_parent_candidates"]) == 1 and len(matched) == 1):
        peer = matched[0]["child_after"]
        correspondence = "same_unique_before_parent_path_and_native_split_coordinates"
        if len(exact_peers) > 1 and peer["path"] == after["path"]:
            status = "native_member_correspondence_hidden_by_gsim_name_collision"
        elif peer["path"] != after["path"]:
            status = "native_member_correspondence_with_different_after_name"
        elif len(exact_peers) == 1:
            status = "unexpected_unique_exact_name_peer"
        suffix = "".join("_" + str(value) for value in relation[0]["coordinates"])
        parent_path = relation[0]["parent_before"]["path"]
        naming = {"grh_matches_parent_plus_coordinates": after["path"] == parent_path + suffix,
                  "gsim_matches_parent_plus_coordinates": peer["path"] == parent_path + suffix,
                  "grh_matches_parent_plus_rename_zero_plus_coordinates":
                      after["path"] == parent_path + "_0" + suffix,
                  "gsim_matches_parent_plus_rename_zero_plus_coordinates":
                      peer["path"] == parent_path + "_0" + suffix,
                  "grh_matches_coordinates_then_rename_zero":
                      after["path"] == parent_path + suffix + "_0",
                  "gsim_matches_coordinates_then_rename_zero":
                      peer["path"] == parent_path + suffix + "_0",
                  "grh_after_path": after["path"], "gsim_after_path": peer["path"],
                  "gsim_native_name": peer["native_name"],
                  "grh_parent_same_id_after": node(db, "after", "grh", relation[0]["parent_id"]),
                  "gsim_parent_same_id_after": node(db, "after", "gsim", pairs[0]["gsim_parent_id"]),
                  "grh_member_same_id_before": before,
                  "gsim_member_same_id_before": node(db, "before", "gsim", peer["id"])}
    residual = None
    if not relation and before is not None and native_children:
        parent_candidates = named(db, "before", "gsim", before["path"])
        residual = {"gsim_parent_candidates": parent_candidates, "grh_children": native_children}
        if len(parent_candidates) == 1:
            parent_id = parent_candidates[0]["id"]
            residual["gsim_same_id_after"] = node(db, "after", "gsim", parent_id)
            peer_children = children(db, "gsim", parent_id)
            residual["gsim_children"] = peer_children
            own_coords = sorted(tuple(item["coordinates"]) for item in native_children)
            peer_coords = sorted(tuple(item["coordinates"]) for item in peer_children)
            residual["same_complete_coordinate_inventory"] = own_coords == peer_coords
            if (len(named(db, "before", "grh", before["path"])) == 1 and
                    residual["gsim_same_id_after"] is None and own_coords == peer_coords and
                    all(item["child_after"] is not None for item in peer_children)):
                status = "grh_retains_split_parent_gsim_retires_parent"
                correspondence = "same_unique_before_parent_path_and_complete_native_child_coordinates"
    family = ("new_vec" if ".new_vec_" in after["path"] else
              "wire" if "WIRE" in after["path"] else "other")
    return {"bucket": bucket, "family": family, "grh_node_id": identifier,
            "grh_path": after["path"], "status": status, "correspondence_basis": correspondence,
            "grh_before": before, "grh_after": after, "grh_origins": relation,
            "same_name_gsim_nodes": exact_details, "native_origin_pairs": pairs,
            "naming_detail": naming, "residual_parent_detail": residual}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--names", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--classification", type=Path, required=True)
    parser.add_argument("--unmatched-reasons", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "ptmp"):
        parser.error("output must be inside repository ptmp/")
    output.mkdir(parents=True, exist_ok=True)
    unclassified = {}
    for line in args.classification.read_text().splitlines():
        if line.startswith("UNCLASSIFIED "):
            _, identifier, path = line.split(" ", 2)
            unclassified[int(identifier)] = path
    selected = []
    with (args.names / "after.unmatched.tsv").open(encoding="utf-8", newline="") as stream:
        stream.readline()
        if stream.readline() != "\t".join(UNMATCHED_COLUMNS) + "\n":
            raise ValueError("invalid unmatched inventory columns")
        for line in stream:
            if line.startswith("#footer\t"):
                continue
            row = parsed_row(line, UNMATCHED_COLUMNS)
            if row["engine"] != "grh":
                continue
            if row["reason"] == "ambiguous_normalized_path_on_peer":
                selected.append((row, "collision"))
            elif int(row["node_id"]) in unclassified:
                if unclassified[int(row["node_id"])] != row["canonical_firrtl_path"]:
                    raise ValueError("classification and unmatched inventory differ")
                selected.append((row, "previously_unclassified"))
    selection = Counter(bucket for _, bucket in selected)
    if selection != {"collision": 104, "previously_unclassified": 163}:
        raise ValueError(f"unexpected exceptional inventory: {selection}")
    started = time.monotonic()
    db = sqlite3.connect(args.evidence.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        db.execute("ATTACH DATABASE ? AS names", (args.names.joinpath("nodes.sqlite").resolve().as_uri() +
                                                 "?mode=ro",))
        records = []
        for target, bucket in selected:
            records.append(audit(db, target, bucket))
        counts = Counter(record["status"] for record in records)
        family_counts = Counter((record["bucket"], record["family"], record["status"]) for record in records)
        rename_counts = Counter()
        for record in records:
            detail = record["naming_detail"]
            if detail:
                for key in ("grh_matches_parent_plus_coordinates", "gsim_matches_parent_plus_coordinates",
                            "gsim_matches_parent_plus_rename_zero_plus_coordinates"):
                    if detail[key]:
                        rename_counts[key] += 1
        summary = {"schema": "wolvrix.f29.exceptional-node-lineage-audit.v1", "complete": True,
                   "functional_equivalence_verified": False,
                   "source_scope": "current full-graph public before/after inventories and native pass lineage only",
                   "names_database": str(args.names / "nodes.sqlite"),
                   "native_lineage_index": str(args.evidence), "selected": dict(selection),
                   "classification": dict(counts), "naming_detail_counts": dict(rename_counts),
                   "families": [{"bucket": bucket, "family": family, "status": status, "count": count}
                                for (bucket, family, status), count in sorted(family_counts.items())],
                   "wall_s": time.monotonic() - started}
        if args.unmatched_reasons:
            difference_records = []
            with args.unmatched_reasons.open(encoding="utf-8", newline="") as stream:
                stream.readline()
                reason_columns = tuple(stream.readline().rstrip("\n").split("\t"))
                for line in stream:
                    if line.startswith("#footer\t"):
                        continue
                    row = parsed_row(line, reason_columns)
                    if row["category"] == "split_member_name_difference":
                        difference_records.append(audit(db, {"node_id": row["grh_node_id"],
                            "canonical_firrtl_path": row["grh_path"]}, "all_native_name_differences"))
            histogram = Counter()
            for record in difference_records:
                detail = record["naming_detail"]
                if detail is None:
                    label = "native_pair_not_reproduced"
                elif (detail["grh_matches_parent_plus_coordinates"] and
                      detail["gsim_matches_parent_plus_rename_zero_plus_coordinates"]):
                    label = "gsim_inherited_rename_zero"
                elif (detail["gsim_matches_parent_plus_coordinates"] and
                      detail["grh_matches_parent_plus_rename_zero_plus_coordinates"]):
                    label = "grh_inherited_rename_zero"
                elif (detail["gsim_matches_parent_plus_coordinates"] and
                      detail["grh_matches_coordinates_then_rename_zero"]):
                    label = "grh_member_rename_zero_after_coordinates"
                elif detail["grh_matches_parent_plus_coordinates"]:
                    label = "gsim_other_name_change"
                elif detail["gsim_matches_parent_plus_coordinates"]:
                    label = "grh_other_name_change"
                else:
                    label = "both_names_changed"
                record["naming_classification"] = label
                if detail is not None and label in ("gsim_inherited_rename_zero", "grh_inherited_rename_zero",
                                                     "grh_member_rename_zero_after_coordinates"):
                    engine = "gsim" if label == "gsim_inherited_rename_zero" else "grh"
                    parent_path = record["grh_origins"][0]["parent_before"]["path"]
                    suffix = "".join("_" + str(value) for value in record["grh_origins"][0]["coordinates"])
                    collision_path = (parent_path + suffix if label == "grh_member_rename_zero_after_coordinates"
                                      else parent_path)
                    before_witness = named(db, "before", engine, collision_path)
                    after_witness = named(db, "after", engine, collision_path)
                    record["collision_witness"] = {"engine": engine, "collision_path": collision_path,
                        "before_nodes": before_witness,
                        "after_nodes": [{"node": item, "origins": origins(db, engine, item["id"]),
                                         "same_id_before": node(db, "before", engine, item["id"])}
                                        for item in after_witness]}
                histogram[label] += 1
            collision_histogram = Counter()
            for record in records:
                if record["bucket"] != "collision":
                    continue
                peer_origins = [origin for peer in record["same_name_gsim_nodes"]
                                for origin in peer["origins"]]
                distinct_parents = {origin["parent_id"] for origin in peer_origins}
                collision_histogram[(len(record["same_name_gsim_nodes"]),
                                     len(peer_origins), len(distinct_parents))] += 1
            summary["all_native_name_differences"] = {
                "rows": len(difference_records), "histogram": dict(histogram),
                "same_id_intermediate_parent_rename_proven": sum(
                    bool(record["naming_detail"] and any(
                        record["naming_detail"][key] is not None and
                        record["naming_detail"][key]["path"] != record["grh_origins"][0]["parent_before"]["path"]
                        for key in ("grh_parent_same_id_after", "gsim_parent_same_id_after")))
                    for record in difference_records),
                "native_collision_path_reoccupied_by_other_split_child": sum(
                    bool(record.get("collision_witness") and any(
                        item["same_id_before"] is None and any(
                            origin["parent_id"] != (
                                record["native_origin_pairs"][0]["gsim_parent_id"]
                                if record["collision_witness"]["engine"] == "gsim"
                                else record["grh_origins"][0]["parent_id"])
                            for origin in item["origins"])
                        for item in record["collision_witness"]["after_nodes"]))
                    for record in difference_records),
                "scope_note": "Parent and coordinate correspondence is native evidence; a retired parent has no public after object, so an intermediate rename of that same ID cannot be established by the boundary snapshots alone."}
            summary["collision_peer_origin_histogram"] = [
                {"same_name_gsim_nodes": peers, "native_origins": origins_count,
                 "distinct_native_before_parents": parents, "count": count}
                for (peers, origins_count, parents), count in sorted(collision_histogram.items())]
            (output / "name-difference-details.json").write_text(
                json.dumps(difference_records, ensure_ascii=False, indent=2) + "\n")
            with (output / "name-differences.tsv").open("w", encoding="utf-8", newline="") as stream:
                stream.write("grh_node_id\tgrh_path\tnaming_classification\tnative_origin_pairs_json\tnaming_detail_json\tcollision_witness_json\n")
                for record in difference_records:
                    stream.write("\t".join(encode_cell(value) for value in (
                        record["grh_node_id"], record["grh_path"], record["naming_classification"],
                        compact(record["native_origin_pairs"]), compact(record["naming_detail"]),
                        compact(record.get("collision_witness")))) + "\n")
        summary["wall_s"] = time.monotonic() - started
        columns = ("grh_node_id", "grh_path", "bucket", "family", "status", "correspondence_basis",
                   "grh_origins_json", "same_name_gsim_nodes_json", "native_origin_pairs_json",
                   "naming_detail_json", "residual_parent_detail_json")
        with (output / "exceptional-nodes.tsv").open("w", encoding="utf-8", newline="") as stream:
            stream.write("#meta\t" + compact({key: value for key, value in summary.items()
                                             if key not in ("classification", "families")}) + "\n")
            stream.write("\t".join(columns) + "\n")
            for record in records:
                row = [record[key] for key in columns[:6]]
                row.extend(compact(record[key]) for key in ("grh_origins", "same_name_gsim_nodes",
                           "native_origin_pairs", "naming_detail", "residual_parent_detail"))
                stream.write("\t".join(encode_cell(value) for value in row) + "\n")
            stream.write("#footer\t" + compact({"complete": True, "rowCount": len(records)}) + "\n")
        (output / "details.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
