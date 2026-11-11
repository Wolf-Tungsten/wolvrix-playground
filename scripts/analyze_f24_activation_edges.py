"""Conservative scalar GSIM activation census from already emitted C++.

This reads generated files only. It neither invokes GSIM nor changes its model.
The recognized shapes are emitted by graph::activateNext in cppEmitter.cpp.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import time


IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"
COND = re.compile(
    rf"^\s*bool (?P<cond>cond_(?P<name>{IDENT})) = (?P=name) "
    r"(?:\^|!=) (?P=name)\$old\$(?P<node>\d+);\s*$"
)
COMPARE = re.compile(
    rf"^\s*if \((?P<name>{IDENT}) != (?P=name)\$old\$(?P<node>\d+)\) \{{\s*$"
)
GUARD = re.compile(r"^\s*if\(unlikely\(.+\)\) \{ // id=(\d+)\s*$")
ACTIVATE = re.compile(
    r"^\s*(?:oldFlag|(?:\*\(uint(?:8|16|32|64)_t\*\)&)?activeFlags\[\d+\])"
    r"\s*\|=\s*(?P<rhs>.+);\s*//\s*(?P<targets>\d+(?:\s+\d+)*)\s*$"
)
COND_TOKEN = re.compile(rf"\bcond_{IDENT}")


def file_identity(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path.resolve()), "bytes": path.stat().st_size,
            "sha256": digest.hexdigest()}


def census(model: Path, graph: str) -> dict:
    pairs: dict[int, str] = {}
    source_super: dict[int, int] = {}
    diagnostics: Counter = Counter()
    identities: list[dict] = []
    cpp_files = sorted(model.glob(f"{graph}[0-9]*.cpp"))
    if not cpp_files:
        raise ValueError(f"no generated C++ files under {model}")
    for path in cpp_files:
        guards: list[tuple[int, int]] = []
        compares: list[tuple[int, int, int]] = []
        current_cond: tuple[str, int, int] | None = None
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            for raw in stream:
                digest.update(raw)
                size += len(raw)
                line = raw.decode("utf-8")
                stripped = line.lstrip()
                indent = len(line) - len(stripped)
                if stripped.startswith("}"):
                    while guards and indent <= guards[-1][0]:
                        guards.pop()
                    while compares and indent <= compares[-1][0]:
                        compares.pop()
                guard = GUARD.fullmatch(line)
                if guard:
                    guards.append((indent, int(guard.group(1))))
                cond = COND.fullmatch(line)
                compare = COMPARE.fullmatch(line)
                if cond:
                    diagnostics["recognized_cond_definitions"] += 1
                    if guards:
                        current_cond = (cond.group("cond"), int(cond.group("node")), guards[-1][1])
                    else:
                        current_cond = None
                        diagnostics["cond_definitions_without_super_guard"] += 1
                    continue
                if compare:
                    diagnostics["recognized_compare_blocks"] += 1
                    if guards:
                        compares.append((indent, int(compare.group("node")), guards[-1][1]))
                    else:
                        diagnostics["compare_blocks_without_super_guard"] += 1
                    current_cond = None
                    continue
                activation = ACTIVATE.fullmatch(line)
                if not activation:
                    current_cond = None
                    continue
                diagnostics["activation_statements_with_target_comments"] += 1
                tokens = COND_TOKEN.findall(activation.group("rhs"))
                source: tuple[int, int] | None = None
                mode = ""
                if current_cond and tokens == [current_cond[0]]:
                    source = (current_cond[1], current_cond[2])
                    mode = "cond_variable"
                elif compares and not tokens:
                    source = (compares[-1][1], compares[-1][2])
                    mode = "compare_block"
                if source is None:
                    diagnostics["activation_statements_outside_confirmed_scalar_compare"] += 1
                    continue
                node, super_id = source
                if node in source_super and source_super[node] != super_id:
                    raise ValueError(f"node {node} emitted under inconsistent supernode guards")
                source_super[node] = super_id
                for target in map(int, activation.group("targets").split()):
                    # IDs fit the 32-bit GSIM int ABI. Packing avoids retaining
                    # a million Python tuples while the native generator runs.
                    if not 0 <= target < 2**32 or not 0 <= node < 2**32:
                        raise ValueError("GSIM ID exceeds the 32-bit census encoding")
                    key = (node << 32) | target
                    if key in pairs:
                        diagnostics["duplicate_node_target_emission"] += 1
                    else:
                        pairs[key] = mode
        identities.append({"path": str(path.resolve()), "bytes": size,
                           "sha256": digest.hexdigest()})
    count_by_mode: Counter = Counter()
    boundary_by_mode: Counter = Counter()
    for key, mode in pairs.items():
        count_by_mode[mode] += 1
        node, target = key >> 32, key & (2**32 - 1)
        if source_super[node] != target:
            boundary_by_mode[mode] += 1
    return {
        "cpp_files": identities,
        "confirmed_scalar_compare_edges": len(pairs),
        "confirmed_scalar_compare_boundary_edges": sum(boundary_by_mode.values()),
        "confirmed_scalar_compare_edges_by_emission": dict(sorted(count_by_mode.items())),
        "confirmed_scalar_compare_boundary_edges_by_emission": dict(sorted(boundary_by_mode.items())),
        "confirmed_scalar_compare_source_nodes": len(source_super),
        "diagnostics": dict(sorted(diagnostics.items())),
    }


RUNTIME_SCOPE_ASSUMPTIONS = [
    "Native nonsink-target publications cover the runtime's activity-bit-gated execution. Sink, event and output phase scans and writer-enable probes do not add value-change activation edges.",
    "The broad comparison counts each runtime's actual publication routes: native (ValueId or state, target nonsink compute owner), GSIM (Node ID, target emitted activation-bit supernode), excluding source-supernode self edges. It does not require GSIM targets to have the native nonsink classification.",
    "Native initialization seeds and unconditional per-eval external-function seeds are outside the publication census. GSIM always-active sources, input setters, async activateAll and unrecognized comparison shapes are omitted from its confirmed lower bound.",
    "Matching frozen FIRRTL input, intended graph/configuration and the applicability of this runtime scope require independent review. A count inequality or an evidence path alone does not certify the quality gate.",
]


def compare_native(native: dict, confirmed: int, compute_lower_bound: int) -> dict:
    if native.get("schema") != "grhsim-activation-stats.v1":
        raise ValueError("unsupported native activation stats schema")
    fields = ("value_change_activation_edges", "state_change_activation_edges",
              "state_write_activation_edges", "event_pulse_activation_edges", "total_activation_edges")
    counts = {}
    for field in fields:
        value = native.get(field)
        if type(value) is not int or value < 0:
            raise ValueError(f"native {field} must be a nonnegative integer")
        counts[field] = value
    values = counts["value_change_activation_edges"]
    conditional_upper_bound = values + counts["state_change_activation_edges"] + counts["state_write_activation_edges"]
    total = conditional_upper_bound + counts["event_pulse_activation_edges"]
    if total != counts["total_activation_edges"]:
        raise ValueError("native publication components do not sum to total_activation_edges")

    def comparison(numerator: int, lower_bound: int) -> dict:
        return {
            "native_edges_upper_bound": numerator,
            "gsim_edges_lower_bound": lower_bound,
            "native_edges_sufficient_limit": lower_bound * 3 // 2,
            "sufficient_count_inequality_holds": numerator * 2 <= lower_bound * 3,
            "inequality": "2 * native_edges_upper_bound <= 3 * gsim_edges_lower_bound",
        }

    compute = comparison(values, compute_lower_bound)
    compute["scope_note"] = "All native value publications upper-bound its compute-to-compute subset. The GSIM lower bound restricts source type to NODE_OTHERS, with all emitted activation-bit targets retained. This comparison alone does not cover native state publications."
    broad = comparison(conditional_upper_bound, confirmed)
    broad["native_upper_bound_formula"] = "value_change_activation_edges + state_change_activation_edges + state_write_activation_edges"
    broad["scope_note"] = "Both state fields are included because state_write_activation_edges mixes small-state value comparisons with large-state write triggers. This upper-bounds all native value-change publication edges, including state, and conservatively includes unconditional large-state writes. Event pulse assertion routes are excluded."
    stricter = comparison(total, confirmed)
    stricter["native_upper_bound_formula"] = "value_change_activation_edges + state_change_activation_edges + state_write_activation_edges + event_pulse_activation_edges"
    stricter["scope_note"] = "This stricter numerator also includes physical event-pulse assertion routes, including consecutive asserted pulses. It equals native total_activation_edges; initialization and unconditional per-eval seeds remain outside the publication census."
    return {
        "publication_components": counts,
        "all_value_change_activation_edges": values,
        # Retain the original field as an explicitly scoped compatibility alias.
        "sufficient_count_inequality_holds": compute["sufficient_count_inequality_holds"],
        "legacy_sufficient_count_inequality_scope": "compute_subset only; not the broad conditional comparison",
        "compute_subset": compute,
        "broad_conditional": broad,
        "publications_including_event_pulses": stricter,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gsim-model", type=Path, required=True)
    parser.add_argument("--graph", default="SimTop")
    parser.add_argument("--native-activation-stats", type=Path)
    parser.add_argument("--same-input-evidence", type=Path,
                        help="Record external identity evidence for independent review")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    start = time.monotonic()
    stats_path = args.gsim_model / f"{args.graph}_supernode_stats.json"
    stats = json.loads(stats_path.read_text())
    by_type = stats["boundary_activation_edges_by_node_type"]
    if sum(by_type.values()) != stats["boundary_activation_edges"]:
        raise ValueError("GSIM boundary type census does not sum to boundary_activation_edges")
    result = census(args.gsim_model, args.graph)
    confirmed = result["confirmed_scalar_compare_boundary_edges"]
    if confirmed > stats["boundary_activation_edges"]:
        raise ValueError("confirmed emitted boundary edges exceed GSIM stats")
    excluded_upper_bound = sum(value for kind, value in by_type.items() if kind != "NODE_OTHERS")
    lower_bound = max(0, confirmed - excluded_upper_bound)
    result.update({
        "schema": "f24-activation-edge-audit.v1",
        "graph": args.graph,
        "gsim_stats": file_identity(stats_path),
        "gsim_boundary_activation_edges": stats["boundary_activation_edges"],
        "gsim_boundary_activation_edges_by_node_type": by_type,
        "non_compute_boundary_edges_upper_bound": excluded_upper_bound,
        "compute_scalar_conditional_boundary_edges_lower_bound": lower_bound,
        "native_all_value_edges_sufficient_limit": lower_bound * 3 // 2,
        "native_broad_conditional_edges_sufficient_limit": confirmed * 3 // 2,
        "native_publications_including_event_pulses_sufficient_limit": confirmed * 3 // 2,
        "lower_bound_formula": "max(0, confirmed_scalar_compare_boundary_edges - sum(boundary_activation_edges_by_node_type except NODE_OTHERS))",
        "counting_unit": "distinct (GSIM Node ID, target emitted supernode ID); source supernode differs from target",
        "scope": "Only exact scalar compare shapes under generated supernode guards are counted. Always-active sources, input setters, async activateAll and unrecognized shapes are omitted. All non-NODE_OTHERS boundary edges are subtracted, including omitted sources, so this is a conservative compute conditional lower bound.",
        "runtime_scope_assumptions": RUNTIME_SCOPE_ASSUMPTIONS,
    })
    if args.native_activation_stats:
        native = json.loads(args.native_activation_stats.read_text())
        if native.get("graph") != args.graph:
            raise ValueError("native activation stats graph does not match requested graph")
        evidence = args.same_input_evidence
        result["native"] = {
            **compare_native(native, confirmed, lower_bound),
            "activation_stats": file_identity(args.native_activation_stats),
            "same_input_evidence": file_identity(evidence) if evidence else None,
            "external_identity_evidence_supplied": evidence is not None,
            "input_identity_verified_by_this_script": False,
            "quality_gate_certified_by_this_script": False,
            "scope_note": "Count inequalities require independent verification of matching frozen FIRRTL input, intended graph/configuration and the stated runtime scope. Merely supplying an evidence file does not certify that verification. A failed sufficient inequality is unresolved, not proof of failure.",
        }
    result["analysis_elapsed_seconds"] = time.monotonic() - start
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in (
        "confirmed_scalar_compare_boundary_edges", "non_compute_boundary_edges_upper_bound",
        "compute_scalar_conditional_boundary_edges_lower_bound", "native_all_value_edges_sufficient_limit",
        "native_broad_conditional_edges_sufficient_limit",
        "native_publications_including_event_pulses_sufficient_limit",
        "analysis_elapsed_seconds")}, indent=2))
    if "native" in result:
        print(json.dumps({key: result["native"][key] for key in (
            "compute_subset", "broad_conditional", "publications_including_event_pulses",
            "input_identity_verified_by_this_script", "quality_gate_certified_by_this_script")}, indent=2))


if __name__ == "__main__":
    main()
