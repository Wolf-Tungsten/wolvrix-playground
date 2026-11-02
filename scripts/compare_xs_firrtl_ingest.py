"""Compare full-design F12 benchmark evidence without loading the graph JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


def read(work: Path, name: str) -> dict:
    return json.loads((work / name).read_text(encoding="utf-8"))


def diagnostics_identity(entries: list) -> str:
    # Only the request-local temporary directory is nondeterministic.
    return re.sub(r"transactions/\d+-\d+/", "transactions/<request>/",
                  json.dumps(entries, sort_keys=True))


def profile_report(work: Path) -> dict:
    path = work / "profile.jsonl"
    if not path.is_file():
        return {}
    profile = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    stages = profile["stages"]
    # These scopes are siblings in Transaction::run. In particular scan_index,
    # scan_validate, parse_module and lower_module overlap these parent scopes.
    names = ("scan_interfaces_us", "collect_annotations_us", "resolve_phase_us",
             "ensure_phase_us", "check_hierarchy_us", "verify_linked_design_us")
    accounted = sum(stages.get(name, 0) for name in names)
    total = profile["total_us"]
    modules = profile.get("modules", [])
    return {
        "total_us": total,
        "nonoverlapping_stages_us": {name: stages.get(name, 0) for name in names},
        "accounted_fraction": accounted / total,
        "unattributed_us": total - accounted,
        "top20_lower_self": sorted(modules, key=lambda row: row.get("lower_us", 0), reverse=True)[:20],
        "top20_resolve_self": sorted(modules, key=lambda row: row.get("resolve_self_us", 0), reverse=True)[:20],
        "counts": profile.get("counts", {}),
        "counters": profile.get("counters", {}),
    }


def graph_inventory(path: Path) -> tuple[dict, dict]:
    """Hash each pretty-printed graph independently, retaining every graph byte."""
    graphs, tail = {}, b""
    digest, name = None, None
    with path.open("rb") as stream:
        for line in stream:
            if line.startswith(b'      "symbol": '):
                name = json.loads(line.partition(b":")[2].strip().removesuffix(b","))
                if name in graphs:
                    raise ValueError(f"duplicate graph {name}")
                digest = hashlib.sha256()
            if digest is not None:
                if line.startswith(b"    }"):
                    digest.update(line.rstrip(b",\r\n") + b"\n")
                    graphs[name] = digest.hexdigest()
                    digest, name = None, None
                else:
                    digest.update(line)
            elif line.startswith(b'  "aliases":'):
                tail = line + stream.read()
                break
    if digest is not None or not tail:
        raise ValueError("unsupported or incomplete pretty graph JSON")
    globals_ = json.loads(b"{\n" + tail)
    globals_["declaredSymbols"] = sorted(globals_.get("declaredSymbols", []))
    return graphs, globals_


def inspect_order(baseline: Path, candidate: Path, before: dict, after: dict) -> dict:
    left, left_globals = graph_inventory(baseline / "ingest.json")
    right, right_globals = graph_inventory(candidate / "ingest.json")
    changed = [name for name in sorted(left.keys() | right.keys()) if left.get(name) != right.get(name)]
    left_diagnostics = Counter(diagnostics_identity([entry]) for entry in before["diagnostics"])
    right_diagnostics = Counter(diagnostics_identity([entry]) for entry in after["diagnostics"])
    return {"graph_count": [len(left), len(right)], "graph_contents_equal": not changed,
            "changed_graphs": changed, "global_fields_equal_after_declaration_sort": left_globals == right_globals,
            "diagnostic_inventory_equal": left_diagnostics == right_diagnostics,
            "note": "Order inspection is explanatory; raw identity checks remain authoritative."}


def compare(baseline: Path, candidate: Path, *, timing_only: bool = False, inspect_ordering: bool = False) -> dict:
    before = read(baseline, "timing.json")
    after = read(candidate, "timing.json")
    before_graph = None if timing_only else read(baseline, "graph-identity.json")
    after_graph = None if timing_only else read(candidate, "graph-identity.json")
    fingerprints = [(work / "source-sha256.txt").read_bytes() if (work / "source-sha256.txt").is_file() else None
                    for work in (baseline, candidate)]
    checks = {
        "manifest": before["manifest_sha256"] == after["manifest_sha256"],
        "cpu_affinity": before.get("cpu_affinity") == after.get("cpu_affinity"),
        "diagnostics": diagnostics_identity(before["diagnostics"]) == diagnostics_identity(after["diagnostics"]),
        "dependencies": before["dependencies"] == after["dependencies"],
        "metadata_keys": before["metadata_keys"] == after["metadata_keys"],
    }
    if not timing_only:
        checks["graph"] = all(before_graph[key] == after_graph[key] for key in ("bytes", "sha256"))
    if any(value is not None for value in fingerprints):
        checks["source_fingerprints"] = fingerprints[0] is not None and fingerprints[0] == fingerprints[1]
    result = {
        "baseline": str(baseline.resolve()), "candidate": str(candidate.resolve()),
        "checks": checks, "equal": all(checks.values()),
        "graph_checked": not timing_only,
        "source_fingerprints_sha256": [hashlib.sha256(value).hexdigest() if value is not None else None
                                       for value in fingerprints],
        "diagnostic_counts": [len(before["diagnostics"]), len(after["diagnostics"])],
        "ingest_s": [before["ingest_s"], after["ingest_s"]],
        "maxrss_kib": [before["maxrss_kib"], after["maxrss_kib"]],
        "native_libraries": [before["native_libraries"], after["native_libraries"]],
        "graph_identity": [before_graph, after_graph],
        "profile": {"baseline": profile_report(baseline), "candidate": profile_report(candidate)},
    }
    if inspect_ordering:
        result["order_analysis"] = inspect_order(baseline, candidate, before, after)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timing-only", action="store_true",
                        help="compare repeat timing evidence without claiming full graph identity")
    parser.add_argument("--inspect-order", action="store_true", help="explain graph/diagnostic ordering differences")
    args = parser.parse_args()
    result = compare(args.baseline, args.candidate, timing_only=args.timing_only, inspect_ordering=args.inspect_order)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("equal", "checks", "graph_checked")}, sort_keys=True))
    if not result["equal"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
