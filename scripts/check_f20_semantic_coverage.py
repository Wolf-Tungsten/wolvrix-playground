"""Check operation SemanticId coverage in a PrettyCompact GRH v4 JSON file."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPERATION = re.compile(
    r'\{"id":\s*\d+,\s*(?:"sym":\s*"(?:\\.|[^"\\])*",\s*)?"kind":\s*"([^"]+)"')
SEMANTIC_IDS = re.compile(r'"semanticIds"\s*:\s*\[')
GRAPH = re.compile(r'^\s*"symbol":\s*"((?:\\.|[^"\\])*)"')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path,
                        help="by-kind report path under repository ptmp/")
    parser.add_argument("--examples", type=int, default=0,
                        help="include at most this many unannotated operation examples")
    args = parser.parse_args()
    source = args.input.resolve()
    output = args.output.resolve()
    if not source.is_file():
        parser.error(f"input not found: {source}")
    if not output.is_relative_to(ROOT / "ptmp"):
        parser.error("output must be under repository ptmp/")
    if args.examples < 0:
        parser.error("--examples must be non-negative")

    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    examples = []
    graph = "<unknown>"
    scoped = False
    skipped = 0
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            graph_match = GRAPH.match(line)
            if graph_match:
                graph = graph_match.group(1)
                scoped = False
            if '"semanticTree":' in line:
                scoped = True
            match = OPERATION.search(line)
            if not match:
                continue
            if not scoped:
                skipped += 1
                continue
            entry = counts[match.group(1)]
            entry[0] += 1
            annotated = SEMANTIC_IDS.search(line) is not None
            entry[1] += annotated
            if not annotated and len(examples) < args.examples:
                examples.append({"graph": graph, "kind": match.group(1),
                                 "operation": line.strip()[:500]})

    total = sum(entry[0] for entry in counts.values())
    annotated = sum(entry[1] for entry in counts.values())
    missing = total - annotated
    rows = sorted(((entry[0], entry[1], kind) for kind, entry in counts.items()),
                  key=lambda row: (-row[0], row[2]))
    text = "".join(f"{entry_total} {entry_annotated} {kind}\n"
                   for entry_total, entry_annotated, kind in rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    summary = {"input": str(source), "output": str(output), "operations": total,
               "annotated": annotated, "missing": missing, "examples": examples,
               "skipped_operations_without_semantic_tree": skipped}
    print(text, end="")
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
