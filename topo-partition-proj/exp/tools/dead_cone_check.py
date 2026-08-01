#!/usr/bin/env python3

"""Dead-cone check on an instruction_graph.jsonl export (docs/19 §4 method,
solidified for T2 validation): roots = state_write nodes + side-effect ops
(system.task / dpi.call / changed.* / mem.write / mem.fill) + order-edge
endpoints; BFS along the def_use reverse graph; unreachable = dead.

Reports total/dead counts, dead share, and the dead breakdown for the
logic bucket (and/or/xor/xnor/not/reduce_*/logic_* on AM; OP_AND/OP_OR/
OP_XOR/OP_NOT/OP_ANDR/OP_ORR/OP_XORR/OP_XNOR on gsim flatten), matching the
docs/18 logic-family definition.

Usage:

    dead_cone_check.py <instruction_graph.jsonl> [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import time
from collections import deque
from pathlib import Path

import numpy as np

SIDE_EFFECT_OPS = (
    "system.task",
    "dpi.call",
    "mem.write",
    "mem.fill",
)
SIDE_EFFECT_PREFIXES = ("changed.",)

AM_LOGIC = {
    "and", "or", "xor", "xnor", "not",
    "logic_and", "logic_or", "logic_not",
    "reduce_or", "reduce_and", "reduce_xor",
}
GSIM_LOGIC = {
    "OP_AND", "OP_OR", "OP_XOR", "OP_NOT",
    "OP_ANDR", "OP_ORR", "OP_XORR", "OP_XNOR",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph")
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    started = time.time()
    path = Path(args.graph)

    # Pass 1: nodes (opcode, state_write) and edge endpoints.
    opcodes: list[str] = []
    state_write = np.zeros(0, dtype=bool)
    def_src = np.zeros(0, dtype=np.uint32)
    def_dst = np.zeros(0, dtype=np.uint32)
    order_pairs: list[tuple[int, int]] = []
    node_count = 0
    def_cap = 1 << 22
    def_src = np.empty(def_cap, dtype=np.uint32)
    def_dst = np.empty(def_cap, dtype=np.uint32)
    def_n = 0

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            rec = json.loads(line)
            kind = rec.get("record")
            if kind == "header":
                node_count = int(rec["instructions"])
                state_write = np.zeros(node_count, dtype=bool)
                opcodes = [""] * node_count
                continue
            if kind == "node":
                idx = int(rec["id"])
                opcodes[idx] = str(rec["opcode"])
                state_write[idx] = bool(rec.get("state_write", False))
                continue
            if kind != "edge":
                continue
            ekind = rec.get("kind")
            if ekind == "def_use":
                if def_n == def_cap:
                    def_cap *= 2
                    def_src.resize(def_cap)
                    def_dst.resize(def_cap)
                def_src[def_n] = int(rec["src"])
                def_dst[def_n] = int(rec["dst"])
                def_n += 1
            elif ekind == "order":
                order_pairs.append((int(rec["src"]), int(rec["dst"])))

    def_src = def_src[:def_n]
    def_dst = def_dst[:def_n]

    # Roots: state_write + side-effect ops + order-edge endpoints.
    alive = state_write.copy()
    for idx, opcode in enumerate(opcodes):
        if not alive[idx] and (
            opcode in SIDE_EFFECT_OPS or opcode.startswith(SIDE_EFFECT_PREFIXES)
        ):
            alive[idx] = True
    for src, dst in order_pairs:
        alive[src] = True
        alive[dst] = True

    # Reverse CSR over def_use: preds[dst] -> [src, ...].
    degree = np.bincount(def_dst, minlength=node_count).astype(np.int64)
    offsets = np.zeros(node_count + 1, dtype=np.int64)
    np.cumsum(degree, out=offsets[1:])
    preds = np.empty(def_n, dtype=np.uint32)
    cursor = offsets[:-1].copy()
    for edge in range(def_n):
        dst = int(def_dst[edge])
        preds[cursor[dst]] = def_src[edge]
        cursor[dst] += 1

    # BFS from roots along predecessor edges.
    stack = deque(int(node) for node in np.flatnonzero(alive))
    while stack:
        node = stack.pop()
        begin, end = offsets[node], offsets[node + 1]
        for pred in preds[begin:end]:
            pred = int(pred)
            if not alive[pred]:
                alive[pred] = True
                stack.append(pred)

    dead_mask = ~alive
    dead_count = int(dead_mask.sum())
    dead_ops: dict[str, int] = {}
    dead_logic = 0
    for idx, opcode in enumerate(opcodes):
        if not dead_mask[idx]:
            continue
        dead_ops[opcode] = dead_ops.get(opcode, 0) + 1
        if opcode in AM_LOGIC or opcode in GSIM_LOGIC:
            dead_logic += 1

    top_dead = sorted(dead_ops.items(), key=lambda kv: -kv[1])[:12]
    result = {
        "graph": str(path),
        "nodes": node_count,
        "def_use_edges": def_n,
        "order_edges": len(order_pairs),
        "dead": dead_count,
        "dead_share": round(dead_count / node_count, 6) if node_count else 0.0,
        "dead_logic": dead_logic,
        "top_dead_ops": top_dead,
        "scan_seconds": round(time.time() - started, 1),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
