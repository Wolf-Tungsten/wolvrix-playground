"""Resolve F21 GRH-extra rows against GSIM pre-DCE forward reachability.

This is an analysis-only companion to ``analyze_f21_anchor_alignment.py``.  It
indexes the lexicographically emitted GSIM edge list once, then performs
bounded forward walks from the exact GSIM counterpart of each unresolved GRH
anchor.  The walk is deliberately conservative: a missing counterpart, a
budget exhaustion, or an unmapped GRH path remains unresolved.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import resource
import sys
import time
from array import array
from collections import Counter, deque
from pathlib import Path

from grhsim_f21_dce_compare import normalize


ROOT_TYPES = {"NODE_OUT", "NODE_SPECIAL", "NODE_EXT", "NODE_EXT_IN", "NODE_EXT_OUT"}
EDGE_LINE = re.compile(r'^\s*\["((?:\\.|[^"\\])*)", "((?:\\.|[^"\\])*)"\]')


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def tbool(value: str) -> bool:
    return value.strip().lower() == "true"


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, delimiter="\t",
                                extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            values = {}
            for column in columns:
                value = row.get(column, "")
                if isinstance(value, (list, dict)):
                    value = json.dumps(value, sort_keys=True, separators=(",", ":"))
                values[column] = "" if value is None else str(value).replace("\t", " ").replace("\n", " ")
            writer.writerow(values)


class GraphIndex:
    """Compact source-sorted adjacency for a GSIM JSON graph.

    GraphJsonDumper writes ``std::set<pair<name,name>>`` edges, so all outgoing
    edges for a source are contiguous.  The index stores only target IDs and a
    pair of byte offsets per source ID; the original JSON remains the source
    of truth for names and metadata.
    """

    def __init__(self) -> None:
        self.names: list[str] = []
        self.name_to_id: dict[str, int] = {}
        self.linenos = array("q")
        self.root_kind: dict[int, str] = {}
        self.starts = array("Q")
        self.ends = array("Q")
        self.targets = array("I")
        self.edge_count = 0

    def add_name(self, name: str, lineno: int = -1, kind: str = "") -> int:
        value = normalize(name)
        found = self.name_to_id.get(value)
        if found is not None:
            if lineno >= 0 and self.linenos[found] < 0:
                self.linenos[found] = lineno
            if kind in ROOT_TYPES:
                self.root_kind[found] = kind
            return found
        index = len(self.names)
        self.name_to_id[value] = index
        self.names.append(value)
        self.linenos.append(lineno)
        self.starts.append(0)
        self.ends.append(0)
        if kind in ROOT_TYPES:
            self.root_kind[index] = kind
        return index

    @classmethod
    def build(cls, source: Path, scratch: Path) -> "GraphIndex":
        index = cls()
        started_edges = False
        current_source = -1
        current_start = 0
        with source.open("r", encoding="utf-8", buffering=1024 * 1024) as stream:
            for line_no, line in enumerate(stream, start=1):
                if not started_edges:
                    if line.strip() == '"edges": [':
                        started_edges = True
                        continue
                    if not line.lstrip().startswith('{"id":'):
                        continue
                    try:
                        record = json.loads(line.rstrip().rstrip(","))
                    except json.JSONDecodeError:
                        continue
                    name = record.get("name", "")
                    if not name:
                        continue
                    index.add_name(name, int(record.get("lineno", -1)), record.get("type", ""))
                    continue
                if line.strip() == "]":
                    break
                match = EDGE_LINE.match(line)
                if match is None:
                    continue
                source_name = normalize(match.group(1))
                target_name = normalize(match.group(2))
                source_id = index.add_name(source_name)
                target_id = index.add_name(target_name)
                if source_id != current_source:
                    if current_source >= 0:
                        index.ends[current_source] = index.edge_count
                    current_source = source_id
                    current_start = index.edge_count
                    index.starts[source_id] = current_start
                index.targets.append(target_id)
                index.edge_count += 1
        if current_source >= 0:
            index.ends[current_source] = index.edge_count
        log(f"GSIM edge index: names={len(index.names)} edges={index.edge_count} roots={len(index.root_kind)}")
        # Keep a small manifest so a later run can identify the scratch format.
        (scratch / "gsim-edge-index.json").write_text(
            json.dumps({"source": str(source), "size": source.stat().st_size,
                        "names": len(index.names), "edges": index.edge_count,
                        "format": 1}, sort_keys=True) + "\n", encoding="utf-8")
        return index

    def outgoing(self, node: int):
        end = self.ends[node]
        if end <= self.starts[node]:
            return ()
        return self.targets[self.starts[node]:end]


def candidate_names(row: dict[str, str], trace: dict | None, index: GraphIndex) -> list[str]:
    values = []
    for key in ("gsim_name", "grh_name"):
        value = normalize(row.get(key, ""))
        if value and value not in values:
            values.append(value)
    if trace:
        for entry in trace.get("path", []) or []:
            for key in ("symbol", "storageSymbol"):
                value = normalize(entry.get(key) or "")
                if value and value not in values:
                    values.append(value)
            for value in entry.get("semanticPaths", []) or []:
                value = normalize(value)
                if value and value not in values:
                    values.append(value)
    return [value for value in values if value in index.name_to_id]


def mapped_names(entry: dict, index: GraphIndex) -> list[str]:
    values = []
    for key in ("symbol", "storageSymbol"):
        value = normalize(entry.get(key) or "")
        if value and value not in values:
            values.append(value)
    for value in entry.get("semanticPaths", []) or []:
        value = normalize(value)
        if value and value not in values:
            values.append(value)
    return [value for value in values if value in index.name_to_id]


def forward_reachable(index: GraphIndex, start: int, budget: int) -> dict:
    """Walk source->next edges, stopping at the first GSIM root.

    The returned set is the observed forward-reachable set.  Root termination
    is intentional: it proves the item has a path to a root without expanding
    unrelated fanout after the proof is complete.
    """
    seen = {start}
    pending = deque([start])
    root = index.root_kind.get(start)
    if root:
        return {"seen": seen, "root": start, "truncated": False, "reason": "start_is_root"}
    while pending:
        node = pending.popleft()
        for target in index.outgoing(node):
            target = int(target)
            if target in seen:
                continue
            seen.add(target)
            if target in index.root_kind:
                return {"seen": seen, "root": target, "truncated": False,
                        "reason": "root_reached"}
            pending.append(target)
            if budget and len(seen) >= budget:
                return {"seen": seen, "root": None, "truncated": True,
                        "reason": f"forward-walk budget {budget} exceeded"}
    return {"seen": seen, "root": None, "truncated": False, "reason": "exhausted_without_root"}


def mechanism(kind: str, source: str) -> str:
    text = source.lower()
    if kind in {"kConcat", "kSliceStatic"}:
        return "concat_to_static_slice_liveness"
    if kind == "kSliceArray":
        return "whole_vector_consumer_of_split_members"
    if kind == "kMux":
        if "when" in text or "mux" in text or "node" in text:
            return "mux_with_constant_or_known_select"
        return "mux_liveness_overapproximation"
    if kind == "kAssign":
        return "assign_alias_chain"
    if kind in {"kAnd", "kOr", "kEq", "kNeq", "kNot"}:
        return "guard_enable_or_compare_not_simplified"
    if "register" in kind.lower() or "latch" in kind.lower():
        return "state_write_dependency_overapproximation"
    return f"{kind or 'unknown'}_dependency_divergence"


def source_lines(source: Path, line_numbers: set[int]) -> dict[int, str]:
    if not line_numbers:
        return {}
    result = {}
    wanted = set(line_numbers)
    with source.open("r", encoding="utf-8", errors="replace", buffering=1024 * 1024) as stream:
        for number, line in enumerate(stream, start=1):
            if number in wanted:
                result[number] = line.rstrip("\n")
                if len(result) == len(wanted):
                    break
    return result


def update_report(args) -> dict:
    started = time.monotonic()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    scratch = args.out_dir / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    ledger = read_tsv(args.ledger)
    trace_payload = json.loads(args.trace.read_text(encoding="utf-8"))
    trace_targets = trace_payload.get("targets", {})
    index = GraphIndex.build(args.gsim_before, scratch)

    unresolved = [row for row in ledger
                  if not row.get("verdict", "").startswith("legitimate:")
                  and tbool(row.get("grh_post", ""))]
    log(f"unresolved live GRH-extra rows selected: {len(unresolved)}")
    reach_cache: dict[int, dict] = {}
    row_reach: dict[str, dict] = {}
    divergence_rows = []
    needed_lines: set[int] = set()

    for position, row in enumerate(unresolved, start=1):
        name = row.get("grh_name", "")
        trace = trace_targets.get(name, {})
        candidates = candidate_names(row, trace, index)
        if not candidates:
            row["verdict"] = "unresolved:GSIM counterpart name absent from pre-DCE graph"
            row["mechanism"] = "gsim_counterpart_absent"
            row["verdict_reason"] = "No normalized row/path name occurs in SimTop_0TopoSort.json"
            row["divergence_source"] = "GSIM pre-DCE name lookup failed"
            row["gsim_reach_status"] = "missing_counterpart"
            row["gsim_reachable_count"] = 0
            row["gsim_reach_root"] = ""
            row_reach[name] = {"candidate": "", "status": "missing_counterpart",
                               "reachable_count": 0, "reason": row["verdict_reason"]}
            divergence_rows.append(row)
            continue
        candidate = candidates[0]
        candidate_id = index.name_to_id[candidate]
        if candidate_id not in reach_cache:
            reach_cache[candidate_id] = forward_reachable(index, candidate_id, args.visit_budget)
        reach = reach_cache[candidate_id]
        root_id = reach.get("root")
        root_name = index.names[root_id] if root_id is not None else ""
        row_reach[name] = {
            "candidate": candidate,
            "status": "root_reached" if root_id is not None else ("budget_exceeded" if reach["truncated"] else "exhausted_without_root"),
            "reachable_count": len(reach["seen"]),
            "root_name": root_name,
            "root_kind": index.root_kind.get(root_id, "") if root_id is not None else "",
            "reason": reach["reason"],
        }
        row["gsim_reach_status"] = row_reach[name]["status"]
        row["gsim_reachable_count"] = row_reach[name]["reachable_count"]
        row["gsim_reach_root"] = root_name
        path = trace.get("path", []) or []
        start_index = -1
        for idx, entry in enumerate(path):
            names = mapped_names(entry, index)
            if candidate in names or normalize(row.get("grh_name", "")) in names:
                start_index = idx
                break
        if start_index < 0:
            # The initial read port may be represented only by the direct state
            # symbol.  Begin at the first path entity in that case.
            start_index = 0
        divergence = None
        before_previous = path[start_index - 1] if start_index > 0 else {}
        previous = path[start_index] if path else {}
        for entry in path[start_index + 1:]:
            names = mapped_names(entry, index)
            if not names:
                previous = entry
                continue
            mapped = names[0]
            mapped_id = index.name_to_id[mapped]
            if mapped_id not in reach["seen"]:
                divergence = (before_previous, previous, entry, mapped)
                break
            before_previous = previous
            previous = entry
        if divergence is None:
            if reach["truncated"]:
                row["verdict"] = "unresolved:forward reachability budget exhausted"
                row["mechanism"] = "gsim_reachability_budget"
                row["verdict_reason"] = reach["reason"]
            elif root_id is not None:
                row["verdict"] = "unresolved:GSIM counterpart reaches a root but no path divergence was found"
                row["mechanism"] = "gsim_path_not_divergent"
                row["verdict_reason"] = f"Observed GSIM forward set reaches {root_name}"
            else:
                row["verdict"] = "unresolved:no mapped GRH successor in GSIM reachability set"
                row["mechanism"] = "gsim_dependency_unresolved"
                row["verdict_reason"] = reach["reason"]
            row["divergence_source"] = "No mapped successor outside observed GSIM forward set"
            divergence_rows.append(row)
            continue
        before_previous, previous, entry, mapped = divergence
        # A GSIM-mapped value is often the result of the operation immediately
        # before it in the GRH trace.  Attribute the divergence to that op so
        # the ledger reports an operation kind and an entering edge, rather
        # than an empty value kind.
        op_entry = entry
        edge_from = previous
        if not op_entry.get("kind") and previous.get("entity") == "op":
            op_entry = previous
            edge_from = before_previous
        line_number = index.linenos[index.name_to_id[mapped]]
        kind = op_entry.get("kind", "")
        row["divergence_op_id"] = op_entry.get("id", "")
        row["divergence_kind"] = kind
        semantic_ids = op_entry.get("semanticIds", []) or []
        row["divergence_semantic_id"] = semantic_ids[0] if semantic_ids else ""
        row["divergence_lineno"] = line_number if line_number >= 0 else ""
        row["divergence_gsim_name"] = mapped
        row["divergence_edge_from"] = edge_from.get("id", "")
        row["divergence_edge_to"] = op_entry.get("id", "")
        row["divergence_op_symbol"] = op_entry.get("symbol") or op_entry.get("storageSymbol") or ""
        if line_number >= 0:
            needed_lines.add(line_number)
        # A live mapped root is required before calling a dependency difference
        # an optimization gap.  The v2 root catalog provides this evidence for
        # system-task/top-output rows; DPI rows without a mapped root stay open.
        if row.get("gsim_root_alive", "").strip().lower() == "true":
            row["verdict"] = "optimization-gap:pending_source_snippet"
            row["mechanism"] = mechanism(kind, "")
            row["verdict_reason"] = (
                "GSIM root is live, but the first mapped successor is outside the "
                "GRH item's observed GSIM forward set"
            )
        else:
            row["verdict"] = "unresolved:GSIM root mapping is not established"
            row["mechanism"] = "gsim_root_mapping_unresolved"
            row["verdict_reason"] = "A dependency divergence was observed, but no live GSIM root mapping is recorded"
        row["divergence_source"] = "first mapped GRH successor outside R_gsim"
        divergence_rows.append(row)
        if position % 50 == 0 or position == len(unresolved):
            log(f"reachability rows: {position}/{len(unresolved)}; cached starts={len(reach_cache)}")

    snippets = source_lines(args.firrtl, needed_lines)
    for row in divergence_rows:
        if row.get("divergence_lineno", "") != "":
            line_number = int(row["divergence_lineno"])
            row["divergence_source"] = snippets.get(line_number, "<FIRRTL line unavailable>")
            if row.get("verdict", "").startswith("optimization-gap:"):
                kind = row.get("divergence_kind", "")
                row["mechanism"] = mechanism(kind, row["divergence_source"])
                row["verdict"] = f"optimization-gap:{row['mechanism']}"

    # Replace only the unresolved rows; representation-boundary rows and any
    # pre-DCE-only rows remain exactly as v2 recorded them.
    replacements = {row.get("grh_name", ""): row for row in divergence_rows}
    for row in ledger:
        replacement = replacements.get(row.get("grh_name", ""))
        if replacement is not None and not row.get("verdict", "").startswith("legitimate:"):
            row.update(replacement)

    columns = list(ledger[0].keys()) if ledger else []
    for extra in ("divergence_gsim_name", "divergence_edge_from", "divergence_edge_to", "divergence_op_symbol",
                  "gsim_reach_status", "gsim_reachable_count", "gsim_reach_root"):
        if extra not in columns:
            columns.append(extra)
    write_tsv(args.ledger, ledger, columns)

    verdict_counts = Counter()
    mechanism_counts = Counter()
    representatives = {}
    for row in ledger:
        verdict = row.get("verdict", "")
        if verdict.startswith("legitimate:"):
            verdict_counts[verdict] += 1
        elif verdict.startswith("optimization-gap:"):
            verdict_counts["optimization-gap"] += 1
            mechanism_counts[verdict.split(":", 1)[1]] += 1
            representatives.setdefault(verdict.split(":", 1)[1], {
                "name": row.get("grh_name", ""),
                "divergence_kind": row.get("divergence_kind", ""),
                "divergence_op_id": row.get("divergence_op_id", ""),
                "divergence_semantic_id": row.get("divergence_semantic_id", ""),
                "divergence_lineno": row.get("divergence_lineno", ""),
                "firrtl": row.get("divergence_source", ""),
            })
        elif verdict.startswith("unresolved"):
            verdict_counts["unresolved"] += 1
            mechanism_counts[row.get("mechanism", "unresolved")] += 1
        else:
            verdict_counts[verdict] += 1
    verdict_counts.setdefault("optimization-gap", 0)
    verdict_counts.setdefault("unresolved", 0)
    legitimate = sum(value for key, value in verdict_counts.items() if key.startswith("legitimate:"))
    total = len(ledger)
    closure = total == legitimate + verdict_counts["optimization-gap"] + verdict_counts["unresolved"]

    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    old_summary = summary.get("grh_extra", {})
    reach_summary = {
        "rows": len(unresolved),
        "counterparts_missing": sum(value.get("status") == "missing_counterpart" for value in row_reach.values()),
        "root_reached": sum(value.get("status") == "root_reached" for value in row_reach.values()),
        "exhausted_without_root": sum(value.get("status") == "exhausted_without_root" for value in row_reach.values()),
        "budget_exceeded": sum(value.get("status") == "budget_exceeded" for value in row_reach.values()),
        "cached_starts": len(reach_cache),
        "rows_with_divergence": sum(bool(row.get("divergence_op_id", "")) for row in divergence_rows),
        "method": "GSIM pre-DCE source-sorted edge index; forward walk terminates at first output/special/ext root or the explicit visit budget",
        "watch_rows": row_reach,
    }
    summary["schema"] = "wolvrix.f21.anchor-alignment.v3"
    summary["grh_extra"] = dict(old_summary)
    summary["grh_extra"].update({
        "total": total,
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "optimization_gap_mechanisms": dict(sorted({key: value for key, value in mechanism_counts.items()
                                                     if any(row.get("verdict", "").startswith("optimization-gap:") and row.get("mechanism") == key for row in ledger)}.items())),
        "mechanism_counts": dict(sorted(mechanism_counts.items())),
        "unresolved_mechanisms": dict(sorted({key: value for key, value in mechanism_counts.items()
                                               if any(row.get("verdict", "").startswith("unresolved") and row.get("mechanism") == key for row in ledger)}.items())),
        "mechanism_representatives": dict(sorted(representatives.items())),
        "reachability": reach_summary,
        "v2_v3_delta": {
            # These are the v2 checkpoint values.  Keep them fixed across
            # reruns so the delta cannot drift after a prior v3 rewrite.
            "previous_unresolved": 640,
            "previous_optimization_gap": 0,
            "previous_legitimate": 14,
            "current_unresolved": verdict_counts["unresolved"],
            "current_optimization_gap": verdict_counts["optimization-gap"],
            "current_legitimate": legitimate,
        },
    })
    summary.setdefault("closure", {})["grh_extra_total_equals_verdict_sum"] = closure
    summary["closure"]["grh_extra_total"] = total
    summary["closure"]["grh_extra_legitimate"] = legitimate
    summary["closure"]["grh_extra_optimization_gap"] = verdict_counts["optimization-gap"]
    summary["closure"]["grh_extra_unresolved"] = verdict_counts["unresolved"]
    summary["verdict"] = {
        "anchor_identity_mapping_complete_enough_for_support_set_comparison": False,
        "reason": "Part 1 GSIM reachability divergence still has unresolved GRH-extra rows; this is an identity/liveness report only.",
    }
    summary["performance"] = {
        **summary.get("performance", {}),
        "reachability_elapsed_seconds": time.monotonic() - started,
        "reachability_max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Keep the existing v2 report intact and append a self-contained v2->v3
    # section, so the delta is reviewable without losing the v2 tables.
    report_path = args.out_dir / "report.md"
    existing = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    marker = "\n## v2 → v3 GSIM reachability divergence"
    if marker in existing:
        existing = existing.split(marker, 1)[0]
    mechanism_rows = []
    for key, count in sorted(mechanism_counts.items(), key=lambda item: (-item[1], item[0])):
        representative = representatives.get(key, {})
        snippet = representative.get('firrtl', '')
        if len(snippet) > 240:
            snippet = snippet[:237] + "..."
        mechanism_rows.append(
            f"| {key} | {count} | {representative.get('name', '')} | {representative.get('divergence_kind', '')} | {representative.get('divergence_op_id', '')} | {representative.get('divergence_lineno', '')} | {snippet} |"
        )
    top_optimization = sorted(
        ((key, value) for key, value in mechanism_counts.items()
         if any(row.get("verdict", "").startswith("optimization-gap:") and row.get("mechanism") == key for row in ledger)),
        key=lambda item: (-item[1], item[0]))[:3]
    section = [
        "", "## v2 → v3 GSIM reachability divergence", "",
        f"The v3 pass rechecked the **{len(unresolved)}** unresolved live GRH-extra rows using the GSIM pre-DCE `edges` section. The edge list was indexed once by source name; each row's forward walk stopped at the first GSIM output/special/ext root or at the explicit budget.", "",
        f"Closure: GRH-extra total **{total}** = legitimate **{legitimate}** + optimization-gap **{verdict_counts['optimization-gap']}** + unresolved **{verdict_counts['unresolved']}**. The closure check is **{str(closure).lower()}**.", "",
        "| Verdict bucket | Count |", "| --- | ---: |",
    ]
    for key, count in sorted(verdict_counts.items()):
        section.append(f"| {key} | {count} |")
    section += [
        "", "### Reachability mechanism table", "",
        "| Mechanism | Count | Representative | Divergence op | Op id | GSIM line | FIRRTL source |", "| --- | ---: | --- | --- | ---: | ---: | --- |",
        *mechanism_rows,
        "", "The ledger records `divergence_edge_from` → `divergence_edge_to`, the mapped GSIM name, its `lineno`, and the FIRRTL statement text. A row remains unresolved when the counterpart is absent, the walk exhausts its budget, the mapped successor cannot be found, or the live GSIM root cannot be established. Reaching a root is not a legitimacy criterion.",
        "",
        "### Top mechanism source locations",
        "",
        "| Mechanism | Pass/code location | Interpretation |", "| --- | --- | --- |",
        *[f"| {key} | " + ("`wolvrix/lib/transform/dead_code_elim.cpp:644-704`" if key == "state_write_dependency_overapproximation" else "`wolvrix/lib/transform/dead_code_elim.cpp:644-704` for alias/liveness propagation" if key == "assign_alias_chain" else "`wolvrix/lib/transform/simplify.cpp:90-122`; `wolvrix/lib/transform/dead_code_elim.cpp:644-704` for mux/constant liveness") + " | Highest-count observed divergence mechanism; the listed pass is the responsible GRH liveness/simplification location to inspect. |" for key, _count in top_optimization],
        "",
        "The state-write bucket is a GRH state-port dependency that reaches a live GSIM effect root through another mapped path; the evidence does not show a rootless cycle, so it is reported as a dependency over-approximation rather than a proven state ring. The assign bucket identifies the first mapped successor after an alias operation whose GSIM counterpart is outside the item's forward set. The mux bucket has a FIRRTL declaration at the recorded GSIM line; the remaining select/constant condition is not serialized in the anchor dump, so the pass location is a mechanism candidate rather than a semantic claim.",
        "",
        "The exact per-row evidence is in `grh-extra-justification.tsv`; `summary.json.grh_extra.reachability` contains the bounded walk status for every row.",
    ]
    report_path.write_text(existing.rstrip() + "\n" + "\n".join(section) + "\n", encoding="utf-8")
    (args.out_dir / "gsim-reachability.tsv").write_text(
        "grh_name\tgsim_candidate\tstatus\treachable_count\troot_kind\troot_name\treason\n" +
        "".join("\t".join(str(row.get("grh_name", "")) if key == "grh_name" else str(row_reach.get(row.get("grh_name", ""), {}).get(key, ""))
                             for key in ("grh_name", "candidate", "status", "reachable_count", "root_kind", "root_name", "reason")) + "\n"
                for row in unresolved), encoding="utf-8")
    log(f"v3 closure={closure}; verdicts={dict(verdict_counts)}; mechanisms={dict(mechanism_counts)}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gsim-before", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--firrtl", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--visit-budget", type=int, default=2_000_000)
    args = parser.parse_args()
    if args.visit_budget < 0:
        raise ValueError("visit budget must be non-negative")
    update_report(args)


if __name__ == "__main__":
    main()
