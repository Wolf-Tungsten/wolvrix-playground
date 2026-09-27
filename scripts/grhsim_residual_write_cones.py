#!/usr/bin/env python3
"""Rank remaining scalar register families using pre-partition IR and body counts.

Counts describe executed IR work, not removable work or host instructions.
Name/width matches are diagnostic anchors, not proofs of equivalence.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import sys

from benchmark_grhsim_ir import digest, endpoint as parse_run
from grhsim_gsim_module_compare import is_generated_value_name, normalize_name
from grhsim_kind_cost_census import compute_task_units
from grhsim_rat_gcone_census import SN_LINE

READS = {"core.state.read", "core.input.read", "core.state.memRead"}
SEMANTIC_ARRAYS = ("states", "types", "values", "operations", "init", "inputs",
                   "outputs", "interface", "functions")
ROW = re.compile(r"^(.+)_(\d+)$")


def family_key(name, width):
    if name.startswith(("__event_", "packed_bits_", "__reg_to_mem_")):
        return None
    match = ROW.fullmatch(name)
    return (match[1], width) if match else None


def checked_fires(path):
    text = Path(path).read_text()
    # Runtime counters have no ANSI escapes; endpoint parsing strips them.
    # Archived runs used a thousands-grouping locale; the benchmark parser
    # normally sees LC_ALL=C output. Normalize numeric separators only.
    endpoint = parse_run(re.sub(r"(?<=\d),(?=\d)", "", text))
    if endpoint[:4] != (240349, 99996, 100001, "0x80000c0c"):
        raise ValueError("unexpected dynamic-run endpoint")
    fires = {}
    for line in text.splitlines():
        match = SN_LINE.fullmatch(line)
        if match:
            key = int(match[1])
            if key in fires:
                raise ValueError(f"duplicate body counter {key}")
            fires[key] = int(match[3])
    if not fires:
        raise ValueError("no body counters")
    return fires, endpoint[2]


def unit_index(model):
    payload = model["mappings"][0][-1]
    parts = {p[0]: p for p in payload[2]}
    tasks, _, _ = compute_task_units(parts, payload[4])
    unit_list = [uid for _, task_units in tasks for uid in task_units]
    units, owners = set(unit_list), {}
    if len(units) != len(unit_list):
        raise ValueError("duplicate scheduled compute unit")
    for uid in sorted(units):
        stack, visited = [uid], set()
        while stack:
            pid = stack.pop()
            if pid in visited:
                raise ValueError("cycle/duplicate in partition tree")
            visited.add(pid)
            node = parts[pid]
            stack.extend(node[4])
            for oid in node[5]:
                if oid in owners:
                    raise ValueError(f"multiple compute owners for op {oid}")
                owners[oid] = uid
    return units, owners


def cone(roots, producer, operations, kinds, names=None):
    """Full: include read op, stop there. Local: stop before any named/read value.

    Local leaves count occurrences, as in NO00020; internal ops are deduplicated.
    """
    seen, leaves = set(), 0
    stack = list(roots)
    while stack:
        vid = stack.pop()
        oid = producer.get(vid)
        if oid is None:
            raise ValueError(f"value {vid} has no producer")
        kind = kinds[oid]
        if names is not None and (kind in READS or
                                  not is_generated_value_name(names.get(vid, ""))):
            leaves += 1
            continue
        if oid in seen:
            continue
        seen.add(oid)
        if kind not in READS:
            stack.extend(operations[oid][4])
    return seen, leaves


def tree_summary(trees):
    """Separate RHS-reachable nodes from serialized lvalues/unreachable nodes."""
    stored, rhs, kinds, refs = 0, 0, Counter(), set()
    nonleaf = 0
    for tree in trees:
        nodes = tree["nodes"]
        stored += len(nodes)
        stack, visited = [tree["root"]], set()
        while stack:
            idx = stack.pop()
            if not isinstance(idx, int) or not 0 <= idx < len(nodes):
                raise ValueError("invalid gsim tree reference")
            if idx in visited:
                continue
            visited.add(idx)
            node = nodes[idx]
            kinds[node["op"]] += 1
            children = node.get("children") or []
            nonleaf += bool(children)
            stack.extend(children)
            if node.get("node"):
                refs.add(node["node"])
        rhs += len(visited)
    return {"stored_enodes": stored, "rhs_enodes": rhs,
            "nonleaf_enodes": nonleaf, "rhs_kinds": dict(sorted(kinds.items())),
            "refs": sorted(refs)}


def gsim_registers(payload):
    sources, destinations = defaultdict(list), {}
    for node in payload["nodes"]:
        if node["type"] == "NODE_REG_DST":
            if node["name"] in destinations:
                raise ValueError("duplicate gsim register destination")
            destinations[node["name"]] = tree_summary(node.get("assignTrees") or [])
        elif node["type"] == "NODE_REG_SRC":
            refs = set()
            for tree in node.get("assignTrees") or []:
                root = tree["root"]
                if not 0 <= root < len(tree["nodes"]):
                    raise ValueError("invalid gsim register source root")
                ref = tree["nodes"][root].get("node")
                if ref and ref != node["name"]:
                    refs.add(ref)
            sources[normalize_name(node["name"])].append({
                "name": node["name"], "width": node.get("width", 0),
                "dst": next(iter(refs)) if len(refs) == 1 else None})
    for records in sources.values():
        for record in records:
            record["tree"] = destinations.get(record["dst"])
    return sources


def match_register(name, width, sources, grh_names):
    key = normalize_name(name)
    records = sources.get(key, [])
    if grh_names[key] != 1 or len(records) > 1:
        return None, "ambiguous_name"
    if not records:
        return None, "no_exact_name"
    record = records[0]
    if record["width"] != width:
        return None, "width_mismatch"
    if not record["tree"] or not record["tree"]["stored_enodes"]:
        return None, "missing_update_tree"
    return record, "matched"


def fingerprint(model, key):
    digest = hashlib.sha256()
    for row in model[key]:
        digest.update(json.dumps(row, ensure_ascii=True, separators=(",", ":")).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def semantic_fingerprints(model):
    return {key: fingerprint(model, key) for key in SEMANTIC_ARRAYS}


def source_fingerprints(directory):
    files = [p for p in Path(directory).iterdir()
             if p.suffix in (".cpp", ".h", ".hpp") or p.name == "Makefile"]
    if not files:
        raise ValueError("empty generated model directory")
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def expression_sample(roots, producer, operations, kinds, names, strings, depth=4):
    """Bounded description for reviewing real input shapes; never executes IR."""
    def show(vid, remaining):
        name = names.get(vid, "")
        oid = producer[vid]
        op = operations[oid]
        node = {"op": kinds[oid], "value": vid}
        if name:
            node["name"] = name
        if len(op) > 7 and op[7]:
            node["parameters"] = {strings[p[0] - 1]: p[2] for p in op[7]}
        if remaining > 0 and kinds[oid] not in READS:
            node["operands"] = [show(value, remaining - 1) for value in op[4][:4]]
            if len(op[4]) > 4:
                node["omitted_operands"] = len(op[4]) - 4
        return node
    return [show(vid, depth) for vid in roots]


def analyze(model, sources, fires, cycles, min_rows=4):
    if cycles <= 0 or min_rows < 2:
        raise ValueError("cycles must be positive and families need at least two rows")
    strings = model["strings"]
    operations = {op[0]: op for op in model["operations"]}
    kinds = {oid: strings[op[1] - 1] for oid, op in operations.items()}
    producer = {}
    writes = defaultdict(list)
    for oid, op in operations.items():
        for vid in op[5]:
            if vid in producer:
                raise ValueError("duplicate value producer")
            producer[vid] = oid
        if kinds[oid] == "core.state.regWrite":
            # The first reference is the destination; later state references
            # own event histories and must not be treated as written rows.
            if not op[6] or op[6][0][0] != "state" or len(op[4]) < 2:
                raise ValueError("invalid regWrite")
            writes[op[6][0][1]].append(op[4][1])
    types = {t[0]: t for t in model["types"]}
    names = {v[0]: strings[v[2] - 1] if v[2] else "" for v in model["values"]}
    units, unit_of = unit_index(model)
    if set(fires) != units:
        raise ValueError(f"body-counter coverage mismatch: missing={len(units - set(fires))}, "
                         f"orphan={len(set(fires) - units)}")
    execs = {oid: fires[uid] for oid, uid in unit_of.items()}

    def price(ops):
        missing = ops - execs.keys()
        if missing:
            raise ValueError(f"{len(missing)} cone ops lack body counters: {sorted(missing)[:8]}")
        return sum(execs[oid] for oid in ops)

    groups, grh_names = defaultdict(list), Counter()
    for state in model["states"]:
        typ = types[state[2]]
        if typ[2] != "logic":
            continue
        name = strings[state[1] - 1]
        grh_names[normalize_name(name)] += 1
        key = family_key(name, typ[3])
        if key:
            groups[key].append((state[0], name))
    origins = {row[0]: row for row in model.get("origins", [])}
    state_origins = {row[0]: origins.get(row[3]) if len(row) > 3 else None
                     for row in model["states"]}
    coverage, all_ops, all_private, rows = Counter(), set(), set(), []
    inflated_ops, inflated_local, top_candidates = set(), set(), []
    for (family, width), members in sorted(groups.items()):
        if len(members) < min_rows:
            continue
        if len(rows) % 100 == 0:
            print(f"Analyzed {len(rows)} families", file=sys.stderr, flush=True)
        usage, local_union, matches, reasons = Counter(), set(), [], Counter()
        matched_local, gsim_stored, gsim_rhs, gsim_nonleaf = 0, 0, 0, 0
        writer_counts = Counter()
        for sid, name in sorted(members):
            roots = writes.get(sid, [])
            writer_counts[str(len(roots))] += 1
            coverage["rows"] += 1
            coverage["bits"] += width
            if not roots:
                reasons["no_grhsim_writer"] += 1
                continue
            full, _ = cone(roots, producer, operations, kinds)
            usage.update(full)
            local, leaves = cone(roots, producer, operations, kinds, names)
            local_union.update(local)
            record, reason = match_register(name, width, sources, grh_names)
            reasons[reason] += 1
            if record:
                coverage["matched_rows"] += 1
                coverage["matched_bits"] += width
                matched_local += len(local) + leaves
                tree = record["tree"]
                gsim_stored += tree["stored_enodes"]
                gsim_rhs += tree["rhs_enodes"]
                gsim_nonleaf += tree["nonleaf_enodes"]
                matches.append({"state": sid, "name": name, "width": width,
                                "local_ops": len(local), "local_leaves": leaves, "gsim": record})
        union = set(usage)
        private = {oid for oid, count in usage.items() if count == 1}
        shared = union - private
        total, exclusive, common = price(union), price(private), price(shared)
        if total != exclusive + common:
            raise ValueError("private/shared closure failed")
        all_ops.update(union)
        all_private.update(private)
        coverage.update({"reason_" + k: v for k, v in reasons.items()})
        hist = Counter()
        for oid in union:
            hist[kinds[oid]] += execs[oid]
        local_hist = Counter(kinds[oid] for oid in local_union)
        indices = sorted(int(ROW.fullmatch(name)[2]) for _, name in members)
        ratio = matched_local / gsim_stored if gsim_stored else None
        if ratio is not None and ratio >= 4:
            inflated_ops.update(union)
            inflated_local.update(local_union)
            top_candidates.append((total, family, width, union))
            top_candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
            del top_candidates[5:]
        matches.sort(key=lambda m: (-(m["local_ops"] + m["local_leaves"]), m["name"]))
        for sample in matches[:2]:
            sid = sample.pop("state")
            sample["grhsim_expression"] = expression_sample(
                writes[sid], producer, operations, kinds, names, strings)
            origin = state_origins[sid]
            if origin:
                sample["source"] = {"file": strings[origin[4] - 1] if origin[4] else "",
                                    "line": origin[5], "column": origin[6]}
        rows.append({"family": family, "width": width, "rows": len(members),
                     "indices_contiguous": indices == list(range(indices[0], indices[-1] + 1)),
                     "writer_counts": dict(sorted(writer_counts.items())),
                     "matching": dict(sorted(reasons.items())), "full_ops": len(union),
                     "private_ops": len(private), "shared_ops": len(shared),
                     "full_execs": total, "private_execs": exclusive, "shared_execs": common,
                     "full_per_cycle": total / cycles, "private_per_cycle": exclusive / cycles,
                     "local_ops": len(local_union), "local_execs": price(local_union),
                     "local_kinds": dict(sorted(local_hist.items())),
                     "dynamic_kinds": dict(sorted(hist.items())),
                     "matched_grhsim_local_size": matched_local,
                     "matched_gsim_stored_enodes": gsim_stored,
                     "matched_gsim_rhs_enodes": gsim_rhs,
                     "matched_gsim_nonleaf_enodes": gsim_nonleaf,
                     "local_ratio_stored": ratio,
                     "samples": matches[:2]})
    rows.sort(key=lambda r: (-r["full_execs"], r["family"], r["width"]))
    all_compute = sum(execs.values())
    top_union, top_summary = set(), []
    for total, family, width, ops in top_candidates:
        incremental = price(ops - top_union)
        top_union.update(ops)
        top_summary.append({"family": family, "width": width,
                            "execs": total, "incremental_execs": incremental})
    return {"cycles": cycles, "family_count": len(rows), "coverage": dict(sorted(coverage.items())),
            "compute_units": len(units), "compute_ops": len(execs),
            "all_compute_execs": all_compute, "union_ops": len(all_ops),
            "union_execs": price(all_ops), "private_union_ops": len(all_private),
            "private_union_execs": price(all_private),
            "inflated_union_execs": price(inflated_ops),
            "inflated_local_union_execs": price(inflated_local),
            "inflated_top5": top_summary,
            "inflated_top5_union_execs": price(top_union),
            "sum_family_execs_with_overlap": sum(row["full_execs"] for row in rows),
            "families": rows}


def render(report):
    data = report["analysis"]
    lines = ["# Remaining register write cones", "",
             f"Families: {data['family_count']}; coverage: {data['coverage']}",
             f"Deduplicated execs/cycle: {data['union_execs'] / data['cycles']:.3f}", "",
             "| Family | Rows | Full execs/cycle | Private execs/cycle | Local size ratio |",
             "|---|---:|---:|---:|---:|"]
    for row in data["families"][:30]:
        ratio = row["local_ratio_stored"]
        ratio_text = f"{ratio:.3f}" if ratio is not None else "unmatched"
        lines.append(f"| {row['family']} | {row['rows']} | {row['full_per_cycle']:.3f} | "
                     f"{row['private_per_cycle']:.3f} | {ratio_text} |")
    return "\n".join(lines) + "\n"


def inspect_gsim_references(payload, report):
    """Expose named intermediate trees behind the five preregistered examples.

    One layer at a time, with no name-based optimization or cost inference.
    Counts cannot be summed across layers because referenced DAGs may overlap.
    """
    selected = {item["family"] for item in report["analysis"]["inflated_top5"]}
    families = [row for row in report["analysis"]["families"] if row["family"] in selected]
    wanted = {ref for row in families for ref in row["samples"][0]["gsim"]["tree"]["refs"]}
    details = {}
    for depth in range(2):
        next_names = set()
        for node in payload["nodes"]:
            name = node["name"]
            if name not in wanted or name in details:
                continue
            summary = tree_summary(node.get("assignTrees") or [])
            details[name] = {"name": name, "type": node["type"], "width": node.get("width"),
                             "layer": depth + 1, "tree": summary}
            next_names.update(summary["refs"])
        missing = wanted - details.keys()
        if missing:
            raise ValueError(f"missing gsim referenced nodes: {sorted(missing)[:5]}")
        wanted = next_names - details.keys()
    return [{"family": row["family"], "sample": row["samples"][0]["name"],
             "direct_references": [details[name] for name in row["samples"][0]["gsim"]["tree"]["refs"]],
             "second_layer": [details[name] for name in sorted({
                 ref for name in row["samples"][0]["gsim"]["tree"]["refs"]
                 for ref in details[name]["tree"]["refs"]})]}
            for row in families]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pre", "final", "archive", "dynamic-model", "gsim", "run", "output"):
        parser.add_argument("--" + name, type=Path, required=name in ("gsim", "output"))
    parser.add_argument("--inspect-report", type=Path,
                        help="inspect gsim named intermediates for a completed census")
    args = parser.parse_args()
    output = args.output.resolve()
    root = Path(__file__).resolve().parents[1]
    if not output.is_relative_to(root / "ptmp"):
        parser.error("output must be under repository ptmp")
    if args.inspect_report:
        report = json.loads(args.inspect_report.read_bytes())
        details = inspect_gsim_references(json.loads(args.gsim.read_bytes()), report)
        output.mkdir(parents=True, exist_ok=True)
        (output / "gsim_details.json").write_text(json.dumps(details, indent=2, sort_keys=True) + "\n")
        return
    if any(getattr(args, key) is None for key in ("pre", "final", "archive", "dynamic_model", "run")):
        parser.error("census requires --pre, --final, --archive, --dynamic-model and --run")
    print("Loading gsim register trees", flush=True)
    sources = gsim_registers(json.loads(args.gsim.read_bytes()))
    print("Loading pre-partition model", flush=True)
    model = json.loads(args.pre.read_bytes())
    before = semantic_fingerprints(model)
    before_strings = model["strings"]
    del model
    print("Checking production model and source identity", flush=True)
    model = json.loads(args.final.read_bytes())
    after = semantic_fingerprints(model)
    # Preserve the pre-partition semantic proof while using only final mapping
    # to attach counters. No graph edit or selection uses the partition layout.
    if before != after:
        raise ValueError("pre/final semantic arrays differ: " +
                         str([k for k in before if before[k] != after[k]]))
    if before_strings != model["strings"][:len(before_strings)]:
        raise ValueError("pre/final referenced string table differs")
    appended_strings = len(model["strings"]) - len(before_strings)
    del before_strings
    final_digest = digest(args.final)
    if final_digest != digest(args.archive):
        raise ValueError("final/archive checkpoints differ")
    if final_digest != digest(args.dynamic_model):
        raise ValueError("dynamic-counter model differs from production checkpoint")
    if source_fingerprints(args.final.parent / "model") != source_fingerprints(args.archive.parent / "model"):
        raise ValueError("generated sources differ")
    fires, cycles = checked_fires(args.run)
    print("Ranking complete and local write cones", flush=True)
    analysis = analyze(model, sources, fires, cycles)
    report = {"schema": 1, "gates": {"G1_semantic_arrays": True, "G2_archive_identity": True,
                                      "G3_counter_coverage_and_closure": True},
              "semantic_fingerprints": after, "analysis": analysis}
    report["backend_appended_strings"] = appended_strings
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (output / "summary.md").write_text(render(report))
    with (output / "families.tsv").open("w") as handle:
        keys = ["family", "width", "rows", "full_ops", "full_per_cycle", "private_per_cycle",
                "local_ops", "local_execs", "local_ratio_stored", "matched_gsim_rhs_enodes"]
        writer = csv.DictWriter(handle, fieldnames=keys, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(analysis["families"])
    print(json.dumps({k: v for k, v in analysis.items() if k != "families"}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
