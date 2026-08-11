#!/usr/bin/env python3
"""NO0002: decompose AM cross_values_compute_network by producer opcode."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "topo-partition-proj" / "exp"))
import numpy as np  # noqa: E402

from harness.graph import load_graph  # noqa: E402

AM_GRAPH = Path("build/logs/no0003/am_instruction_graph_v2_c5mw0.jsonl")
AM_ASSIGN = Path("build/logs/no0003/am_block_assignment_v2_c5mw0.jsonl")

from harness.scorer import load_assignment  # noqa: E402

graph = load_graph(AM_GRAPH, use_cache=True, verbose=False)
assignment = load_assignment(AM_ASSIGN)
instr_block = assignment.instr_block.astype(np.int64)

producer_block = instr_block[graph.du_src.astype(np.int64)]
consumer_block = instr_block[graph.du_dst.astype(np.int64)]
cross = producer_block != consumer_block
state_write_consumer = graph.state_write[graph.du_dst.astype(np.int64)]
mask = cross & ~state_write_consumer
cross_vars = np.unique(graph.du_var[mask])
print("cross_values_compute_network =", cross_vars.size)

# var -> producer instruction: the producer is du_src of any edge carrying var
# (def-use edges carry (src, dst, var); the producer instruction of var is
# the src where var was defined — take the first edge that defines it).
var_producer = {}
for src, var in zip(graph.du_src.tolist(), graph.du_var.tolist()):
    if var not in var_producer:
        var_producer[var] = src

# opcode per instruction from node records
import json
opcodes = {}
with open(AM_GRAPH, encoding="utf-8") as fh:
    for line in fh:
        rec = json.loads(line)
        if rec.get("record") == "node":
            opcodes[rec["id"]] = rec["opcode"]

GROUPS = {
    "bookkeeping(act/changed)": {"act.f", "act.b", "changed.any", "changed.pos", "changed.neg"},
    "slice/concat/assign": {"slice_static", "slice_dynamic", "concat", "assign"},
    "mux": {"mux"},
    "mem/state": {"mem.read", "mem.write.c", "mem.write.cm", "reg.write", "reg.write.m"},
}
GROUP_OF = {op: g for g, ops in GROUPS.items() for op in ops}

by_group = Counter()
by_opcode = Counter()
for var in cross_vars.tolist():
    producer = var_producer.get(var)
    op = opcodes.get(producer, "?")
    by_group[GROUP_OF.get(op, "compute(other)")] += 1
    by_opcode[op] += 1

print("\nby group:")
for name, count in by_group.most_common():
    print(f"  {name}: {count} ({count / cross_vars.size:.1%})")
print("\ntop opcodes:")
for name, count in by_opcode.most_common(20):
    print(f"  {name}: {count}")
