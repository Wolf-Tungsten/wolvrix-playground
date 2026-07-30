"""Smoke test for harness.gnn_bench on a tiny synthetic graph."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.gnn_bench import run_bench  # noqa: E402
from harness.graph import InstructionGraph  # noqa: E402


def test_bench_runs_on_tiny_graph():
    n = 100
    du_src = np.arange(n - 1, dtype=np.uint32)
    du_dst = du_src + 1
    empty = np.zeros(0, dtype=np.uint32)
    graph = InstructionGraph(
        instructions=n,
        variables=n,
        op=np.zeros(n, dtype=np.uint8),
        opcode_names=["op0"],
        width=np.ones(n, dtype=np.int32),
        state_write=np.zeros(n, dtype=bool),
        atom=np.arange(n, dtype=np.uint32),
        comb_loop_atom=np.zeros(n, dtype=bool),
        du_src=du_src,
        du_dst=du_dst,
        du_var=du_src.copy(),
        du_width=np.ones(n - 1, dtype=np.int32),
        er_dst=empty,
        er_var=empty,
        er_width=np.zeros(0, dtype=np.int32),
        ord_src=empty,
        ord_dst=empty,
        topo_order=np.arange(n, dtype=np.uint32),
        topo_pos=np.arange(n, dtype=np.uint32),
    )
    result = run_bench(graph, dims=(8,))
    assert result.edges == n - 1
    assert result.layer_s(8) > 0
    assert result.model_s(8, 2) > result.layer_s(8)
