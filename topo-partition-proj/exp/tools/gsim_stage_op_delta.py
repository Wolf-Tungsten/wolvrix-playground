#!/usr/bin/env python3

"""Per-stage gsim op contribution table from --dump-stats-json stage dumps.

Reads every ``<graph>_<idx><Stage>_Stats.json`` in a dump directory (produced
by ``gsim --dump-stats-json``), bucketizes ``expnodes.op_types`` with the same
bucket semantics as docs/18 (logic = OP_AND/OR/XOR/NOT/ANDR/ORR/XORR, ...),
and prints per-stage counts plus consecutive-stage deltas. Node refs are not
in op_types (they are counted separately as node_ref_count); OP_INT is the
only constant op.

Usage:

    gsim_stage_op_delta.py <dump_dir> [--out-json PATH]
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

BUCKETS = {
    "OP_MUX": "mux", "OP_WHEN": "mux",
    "OP_ADD": "arith", "OP_SUB": "arith", "OP_MUL": "arith", "OP_DIV": "arith",
    "OP_REM": "arith", "OP_NEG": "arith",
    "OP_LT": "cmp", "OP_LEQ": "cmp", "OP_GT": "cmp", "OP_GEQ": "cmp",
    "OP_EQ": "cmp", "OP_NEQ": "cmp",
    "OP_AND": "logic", "OP_OR": "logic", "OP_XOR": "logic", "OP_NOT": "logic",
    "OP_ANDR": "logic", "OP_ORR": "logic", "OP_XORR": "logic",
    "OP_DSHL": "shift", "OP_DSHR": "shift", "OP_SHL": "shift", "OP_SHR": "shift",
    "OP_HEAD": "slice", "OP_TAIL": "slice", "OP_BITS": "slice",
    "OP_BITS_NOSHIFT": "slice", "OP_INDEX_INT": "slice", "OP_INDEX": "slice",
    "OP_CAT": "concat", "OP_GROUP": "concat",
    "OP_CVT": "cast", "OP_ASUINT": "cast", "OP_ASSINT": "cast",
    "OP_ASCLOCK": "cast", "OP_ASASYNCRESET": "cast", "OP_PAD": "cast", "OP_SEXT": "cast",
    "OP_READ_MEM": "mem", "OP_WRITE_MEM": "mem", "OP_INFER_MEM": "mem",
    "OP_PRINTF": "special", "OP_ASSERT": "special", "OP_EXIT": "special",
    "OP_EXT_FUNC": "special", "OP_INVALID": "special", "OP_RESET": "special",
    "OP_STMT_SEQ": "statement", "OP_STMT_WHEN": "statement", "OP_STMT_NODE": "statement",
    "OP_INT": "const",
}

STAGE_FILE = re.compile(r"^(?P<graph>.+)_(?P<idx>\d+)(?P<stage>[A-Za-z_]\w*)_Stats\.json$")
BUCKET_ORDER = ["logic", "mux", "cmp", "arith", "shift", "slice", "concat", "cast",
                "mem", "special", "statement", "const", "other"]


def bucketize(op_types: dict[str, int]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for name, count in op_types.items():
        counter[BUCKETS.get(name, "other")] += int(count)
    return dict(counter)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out_json = None
    if "--out-json" in sys.argv:
        idx = sys.argv.index("--out-json")
        out_json = Path(sys.argv[idx + 1])
        args = [a for a in args if a != sys.argv[idx + 1]]
    if len(args) != 1:
        sys.stderr.write(__doc__ or "")
        return 2
    dump_dir = Path(args[0])
    stages = []
    for path in dump_dir.glob("*_Stats.json"):
        match = STAGE_FILE.match(path.name)
        if not match:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        expnodes = payload.get("expnodes", {})
        op_types = {str(k): int(v) for k, v in expnodes.get("op_types", {}).items()}
        stages.append({
            "idx": int(match.group("idx")),
            "stage": match.group("stage"),
            "file": path.name,
            "node_count": int(payload.get("node_count", 0)),
            "supernode_count": int(payload.get("supernode_count", 0)),
            "edge_count": int(payload.get("edge_count", 0)),
            "enode_unique_count": int(expnodes.get("unique_count", 0)),
            "enode_node_ref_count": int(expnodes.get("node_ref_count", 0)),
            "op_total": sum(op_types.values()),
            "op_types": op_types,
            "buckets": bucketize(op_types),
        })
    stages.sort(key=lambda s: s["idx"])
    if not stages:
        sys.stderr.write(f"no *_Stats.json found in {dump_dir}\n")
        return 1

    header = f"{'bucket':10s}" + "".join(f"{s['idx']:>2d}.{s['stage'][:14]:>15s}" for s in stages)
    print("== per-stage op-enode counts (unique, refs excluded) ==")
    print(header)
    for bucket in BUCKET_ORDER:
        row = f"{bucket:10s}"
        for s in stages:
            row += f"{s['buckets'].get(bucket, 0):>17d}"
        print(row)
    for label, key in (("op_total", "op_total"), ("node_count", "node_count"),
                       ("supernodes", "supernode_count"),
                       ("enode_refs", "enode_node_ref_count")):
        row = f"{label:10s}"
        for s in stages:
            row += f"{s[key]:>17d}"
        print(row)

    print("\n== delta vs previous stage ==")
    print(header)
    prev = None
    delta_rows: dict[str, list[int]] = {b: [] for b in BUCKET_ORDER}
    for s in stages:
        for bucket in BUCKET_ORDER:
            cur = s["buckets"].get(bucket, 0)
            base = prev["buckets"].get(bucket, 0) if prev else 0
            delta_rows[bucket].append(cur - base)
        prev = s
    for bucket in BUCKET_ORDER:
        row = f"{bucket:10s}"
        for delta in delta_rows[bucket]:
            row += f"{delta:>+17d}"
        print(row)
    prev = None
    for label, key in (("op_total", "op_total"), ("node_count", "node_count"),
                       ("enode_refs", "enode_node_ref_count")):
        row = f"{label:10s}"
        for s in stages:
            cur = s[key]
            base = prev[key] if prev else 0
            row += f"{cur - base:>+17d}"
            prev = s
        print(row)

    if out_json:
        out_json.write_text(json.dumps({"stages": stages}, indent=1), encoding="utf-8")
        print(f"\n[gsim_stage_op_delta] wrote {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
