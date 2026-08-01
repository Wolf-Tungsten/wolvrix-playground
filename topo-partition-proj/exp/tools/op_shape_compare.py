#!/usr/bin/env python3

"""Compare per-op node/edge shapes of two instruction_graph.jsonl exports.

Streams both graphs (no harness load) and joins per-opcode statistics:
node count, node width sum, state_write count, def_use out/in edge counts
(by src/dst opcode) and external_read in-count (by dst opcode). Intended
for op-count attribution between grhsim AM and gsim flatten exports
(docs/15 follow-up).

Usage:

    op_shape_compare.py <graph_a.jsonl> <graph_b.jsonl> [--out-json PATH]

A and B are labelled from the header ``source`` field when present
(``gsim`` for the gsim export, ``am`` otherwise).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def scan_graph(path: Path) -> dict:
    started = time.time()
    node_stats: dict[str, dict[str, int]] = {}

    def node_slot(opcode: str) -> dict[str, int]:
        slot = node_stats.get(opcode)
        if slot is None:
            slot = {
                "nodes": 0,
                "width_sum": 0,
                "state_write": 0,
                "def_use_out": 0,
                "def_use_out_width": 0,
                "def_use_in": 0,
                "external_read_in": 0,
            }
            node_stats[opcode] = slot
        return slot

    # op name per dense node id, needed to attribute edges to src/dst op.
    node_ops: list[str] = []
    header: dict = {}
    counts = {"node": 0, "def_use": 0, "external_read": 0, "order": 0}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            rec = json.loads(line)
            kind = rec.get("record")
            if kind == "header":
                header = rec
                continue
            if kind == "node":
                opcode = str(rec["opcode"])
                node_ops.append(opcode)
                slot = node_slot(opcode)
                slot["nodes"] += 1
                slot["width_sum"] += int(rec.get("width", 0))
                if rec.get("state_write"):
                    slot["state_write"] += 1
                counts["node"] += 1
                continue
            if kind != "edge":
                continue
            ekind = rec.get("kind")
            counts[ekind] = counts.get(ekind, 0) + 1
            if ekind == "def_use":
                src_slot = node_slot(node_ops[int(rec["src"])])
                src_slot["def_use_out"] += 1
                src_slot["def_use_out_width"] += int(rec.get("width", 0))
                node_slot(node_ops[int(rec["dst"])])["def_use_in"] += 1
            elif ekind == "external_read":
                node_slot(node_ops[int(rec["dst"])])["external_read_in"] += 1
    return {
        "path": str(path),
        "source": str(header.get("source", "am")),
        "header": header,
        "counts": counts,
        "ops": node_stats,
        "scan_seconds": round(time.time() - started, 1),
    }


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out_json = None
    if "--out-json" in sys.argv:
        idx = sys.argv.index("--out-json")
        out_json = Path(sys.argv[idx + 1])
        args = [a for a in args if a != sys.argv[idx + 1]]
    if len(args) != 2:
        sys.stderr.write(__doc__ or "")
        return 2
    graphs = [scan_graph(Path(p)) for p in args]
    graphs.sort(key=lambda g: g["source"] != "am")  # am first, gsim second
    am, gsim = graphs[0], graphs[1]
    all_ops = sorted(set(am["ops"]) | set(gsim["ops"]))
    rows = []
    for op in all_ops:
        a = am["ops"].get(op, {})
        b = gsim["ops"].get(op, {})
        rows.append(
            {
                "opcode": op,
                "am_nodes": a.get("nodes", 0),
                "gsim_nodes": b.get("nodes", 0),
                "delta_nodes": a.get("nodes", 0) - b.get("nodes", 0),
                "am_width_sum": a.get("width_sum", 0),
                "gsim_width_sum": b.get("width_sum", 0),
                "am_state_write": a.get("state_write", 0),
                "gsim_state_write": b.get("state_write", 0),
                "am_def_use_out": a.get("def_use_out", 0),
                "gsim_def_use_out": b.get("def_use_out", 0),
                "delta_def_use_out": a.get("def_use_out", 0) - b.get("def_use_out", 0),
                "am_def_use_in": a.get("def_use_in", 0),
                "gsim_def_use_in": b.get("def_use_in", 0),
                "am_external_read_in": a.get("external_read_in", 0),
                "gsim_external_read_in": b.get("external_read_in", 0),
            }
        )
    rows.sort(key=lambda r: -abs(r["delta_nodes"]))
    report = {
        "am": {k: am[k] for k in ("path", "counts", "scan_seconds")},
        "gsim": {k: gsim[k] for k in ("path", "counts", "scan_seconds")},
        "rows": rows,
    }
    print(f"{'opcode':24s} {'am_nodes':>10s} {'gsim_nodes':>10s} {'delta':>10s} "
          f"{'am_du_out':>10s} {'gsim_du_out':>10s}")
    for r in rows:
        print(f"{r['opcode']:24s} {r['am_nodes']:>10d} {r['gsim_nodes']:>10d} "
              f"{r['delta_nodes']:>10d} {r['am_def_use_out']:>10d} {r['gsim_def_use_out']:>10d}")
    if out_json:
        out_json.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(f"[op_shape_compare] wrote {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
