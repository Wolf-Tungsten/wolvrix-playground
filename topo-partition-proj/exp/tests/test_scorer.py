"""Unit tests for harness.scorer — the width-weighted cost semantics that the
production scoreboard cannot check for us (docs/04 Phase 0 task 2: "位宽折算
的正确性靠单元测试保证")."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.graph import InstructionGraph  # noqa: E402
from harness.scorer import score_assignment  # noqa: E402


def make_graph(
    node_count: int,
    variable_count: int,
    du: list[tuple[int, int, int, int]] = (),
    er: list[tuple[int, int, int]] = (),
    state_write: tuple[int, ...] = (),
) -> InstructionGraph:
    """Build a minimal graph. du = (src, dst, var, width); er = (dst, var, width)."""
    sw = np.zeros(node_count, dtype=bool)
    sw[list(state_write)] = True
    empty_u32 = np.zeros(0, dtype=np.uint32)
    return InstructionGraph(
        instructions=node_count,
        variables=variable_count,
        op=np.zeros(node_count, dtype=np.uint8),
        opcode_names=["op0"],
        width=np.ones(node_count, dtype=np.int32),
        state_write=sw,
        atom=np.arange(node_count, dtype=np.uint32),
        comb_loop_atom=np.zeros(node_count, dtype=bool),
        du_src=np.array([e[0] for e in du], dtype=np.uint32),
        du_dst=np.array([e[1] for e in du], dtype=np.uint32),
        du_var=np.array([e[2] for e in du], dtype=np.uint32),
        du_width=np.array([e[3] for e in du], dtype=np.int32),
        er_dst=np.array([e[0] for e in er], dtype=np.uint32),
        er_var=np.array([e[1] for e in er], dtype=np.uint32),
        er_width=np.array([e[2] for e in er], dtype=np.int32),
        ord_src=empty_u32,
        ord_dst=empty_u32,
        topo_order=np.arange(node_count, dtype=np.uint32),
        topo_pos=np.arange(node_count, dtype=np.uint32),
    )


def blocks(mapping: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """Dense 0-based blocks, all compute: (instr_block, commit_mask)."""
    instr_block = np.array(mapping, dtype=np.uint32)
    return instr_block, np.zeros(int(instr_block.max()) + 1, dtype=bool)


def test_doc_example():
    """docs/04 example: A makes x(32)/y(128); B uses x,y; C uses x -> cost 4."""
    graph = make_graph(
        node_count=4,
        variable_count=2,
        du=[(0, 2, 0, 32), (1, 2, 1, 128), (0, 3, 0, 32)],
    )
    # node 0,1 = block A(0); node 2 = block B(1); node 3 = block C(2)
    instr_block, commit_mask = blocks([0, 0, 1, 2])
    board = score_assignment(graph, instr_block, commit_mask)
    assert board.cost == 3 + 1
    assert board.compute_compute_value_pairs == 3
    assert board.dag_edges == 2  # (A,B) and (A,C), deduped
    assert board.footprint == 3


def test_width_to_copies():
    """ceil(width/64) with a floor of 1: 1->1, 64->1, 65->2, 128->2, 129->3."""
    widths = [1, 64, 65, 128, 129]
    expected = [1, 1, 2, 2, 3]
    du = [(0, index + 1, index, w) for index, w in enumerate(widths)]
    graph = make_graph(node_count=6, variable_count=5, du=du)
    instr_block, commit_mask = blocks([0, 1, 1, 1, 1, 1])
    board = score_assignment(graph, instr_block, commit_mask)
    assert board.cost == sum(expected)
    assert board.compute_compute_value_pairs == len(widths)
    assert board.dag_edges == 1


def test_same_block_is_free():
    graph = make_graph(node_count=2, variable_count=1, du=[(0, 1, 0, 256)])
    instr_block, commit_mask = blocks([0, 0])
    board = score_assignment(graph, instr_block, commit_mask)
    assert board.cost == 0
    assert board.compute_compute_value_pairs == 0
    assert board.dag_edges == 0


def test_dedup_same_value_same_block():
    """Two instructions in one block using the same value count once."""
    graph = make_graph(
        node_count=3, variable_count=1, du=[(0, 1, 0, 32), (0, 2, 0, 32)]
    )
    instr_block, commit_mask = blocks([0, 1, 1])
    board = score_assignment(graph, instr_block, commit_mask)
    assert board.cost == 1
    assert board.compute_compute_value_pairs == 1


def test_external_read_permanent_boundary():
    """State-target/interface inputs count for every consuming compute block,
    and are free inside commit blocks."""
    graph = make_graph(
        node_count=3,
        variable_count=1,
        er=[(0, 0, 32), (1, 0, 32), (2, 0, 32)],
        state_write=(2,),
    )
    instr_block = np.array([0, 1, 2], dtype=np.uint32)
    commit_mask = np.array([False, False, True])
    board = score_assignment(graph, instr_block, commit_mask)
    assert board.compute_compute_value_pairs == 2  # blocks 0 and 1, not commit 2
    assert board.cost == 2


def test_commit_block_reads_free_but_dag_edges_count():
    graph = make_graph(
        node_count=2, variable_count=1, du=[(0, 1, 0, 32)], state_write=(1,)
    )
    instr_block = np.array([0, 1], dtype=np.uint32)
    commit_mask = np.array([False, True])
    board = score_assignment(graph, instr_block, commit_mask)
    assert board.cost == 0
    assert board.compute_compute_value_pairs == 0
    assert board.dag_edges == 1  # structural edge into the commit block
    assert board.commit_blocks == 1
    assert board.compute_blocks == 1
