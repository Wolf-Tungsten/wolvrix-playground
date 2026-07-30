"""Unit tests for harness.sampler on small synthetic graphs."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.graph import (  # noqa: E402
    KIND_DEF_USE,
    KIND_EXTERNAL_READ,
    KIND_ORDER,
    InstructionGraph,
    kahn_order,
)
from harness.sampler import EXTERNAL_SRC, Sampler, SamplerConfig, Region  # noqa: E402


def make_graph(
    node_count: int,
    du: list[tuple[int, int, int, int]] = (),
    er: list[tuple[int, int, int]] = (),
    order: list[tuple[int, int]] = (),
    ops: dict[int, int] | None = None,
    opcode_names: list[str] | None = None,
) -> InstructionGraph:
    """du = (src, dst, var, width); er = (dst, var, width); order = (src, dst)."""
    op = np.zeros(node_count, dtype=np.uint8)
    for node, value in (ops or {}).items():
        op[node] = value
    names = opcode_names or ["add"]
    empty = np.zeros(0, dtype=np.uint32)
    graph = InstructionGraph(
        instructions=node_count,
        variables=1000,
        op=op,
        opcode_names=names,
        width=np.ones(node_count, dtype=np.int32),
        state_write=np.zeros(node_count, dtype=bool),
        atom=np.arange(node_count, dtype=np.uint32),
        comb_loop_atom=np.zeros(node_count, dtype=bool),
        du_src=np.array([e[0] for e in du], dtype=np.uint32),
        du_dst=np.array([e[1] for e in du], dtype=np.uint32),
        du_var=np.array([e[2] for e in du], dtype=np.uint32),
        du_width=np.array([e[3] for e in du], dtype=np.int32),
        er_dst=np.array([e[0] for e in er], dtype=np.uint32),
        er_var=np.array([e[1] for e in er], dtype=np.uint32),
        er_width=np.array([e[2] for e in er], dtype=np.int32),
        ord_src=np.array([e[0] for e in order], dtype=np.uint32),
        ord_dst=np.array([e[1] for e in order], dtype=np.uint32),
        topo_order=np.empty(0, dtype=np.uint32),
        topo_pos=np.empty(0, dtype=np.uint32),
    )
    graph.topo_order = kahn_order(graph)
    graph.topo_pos = np.empty(node_count, dtype=np.uint32)
    graph.topo_pos[graph.topo_order] = np.arange(node_count, dtype=np.uint32)
    return graph


def chain_graph(n: int = 60) -> InstructionGraph:
    """0 -> 1 -> ... -> n-1 def_use chain (topo order = id order)."""
    du = [(i, i + 1, i, 32) for i in range(n - 1)]
    return make_graph(n, du=du)


def tiny_config(**kwargs) -> SamplerConfig:
    base = dict(
        min_internal=4,
        max_internal=8,
        halo_fanout_cap=512,
        holdout_frac=0.2,
        holdout_start_frac=0.4,
        rare_frac=0.25,
        cover_threshold=3,
        seed=7,
    )
    base.update(kwargs)
    return SamplerConfig(**base)


def test_topo_window_respects_holdout():
    graph = chain_graph(60)
    sampler = Sampler(graph, tiny_config())
    # holdout: topo positions [24, 36)
    assert sampler.holdout_start == 24 and sampler.holdout_end == 36
    rng = np.random.default_rng(0)
    for _ in range(50):
        window = sampler._topo_window(rng, rare=False)
        positions = graph.topo_pos[window]
        assert positions.min() >= 0
        assert positions.max() < 24 or positions.min() >= 36
        assert 4 <= window.size <= 8


def test_bfs_region_connected_and_sized():
    graph = chain_graph(60)
    sampler = Sampler(graph, tiny_config(holdout_frac=0.0, holdout_start_frac=1.0))
    rng = np.random.default_rng(1)
    members = sampler._bfs_grow(30, 6)
    assert members is not None and members.size == 6
    # On a chain, a 6-node undirected BFS blob is a contiguous run.
    assert members.max() - members.min() == 5


def test_halo_one_hop_asymmetric():
    graph = chain_graph(60)
    sampler = Sampler(graph, tiny_config())
    internal = np.array([20, 21, 22, 23], dtype=np.uint32)
    halo, capped = sampler._halo(internal)
    assert capped == 0
    # predecessors complete (19), successors one hop (24); no 2-hop nodes.
    assert set(halo.tolist()) == {19, 24}
    assert not set(halo.tolist()) & set(internal.tolist())


def test_halo_successor_cap():
    """A hub internal node with fanout > cap contributes only cap halo nodes."""
    n = 300
    du = [(0, i, i, 1) for i in range(1, n)]  # node 0 -> 1..299
    graph = make_graph(n, du=du)
    sampler = Sampler(graph, tiny_config(halo_fanout_cap=10))
    halo, capped = sampler._halo(np.array([0], dtype=np.uint32))
    assert capped == 1
    assert halo.size == 10


def test_build_region_edges():
    """Internal chain 2->3->4 with halo 1 and 5; check emitted edge kinds."""
    du = [(1, 2, 1, 32), (2, 3, 2, 64), (3, 4, 3, 96), (4, 5, 4, 128)]
    graph = make_graph(6, du=du, er=[(3, 900, 16)], order=[(1, 3)])
    sampler = Sampler(graph, tiny_config())
    region = sampler.build_region(np.array([2, 3, 4], dtype=np.uint32), {"method": "test"})
    assert region.internal_count == 3
    ids = region.node_id.tolist()
    assert ids[:3] == [2, 3, 4]
    assert set(ids[3:]) == {1, 5, 0} or set(ids[3:]) >= {1, 5}
    local = {g: i for i, g in enumerate(ids)}
    kinds = {
        (int(s), int(d)): int(k)
        for s, d, k in zip(region.edge_src, region.edge_dst, region.edge_kind)
    }
    # internal-internal def_use once
    assert kinds[(local[2], local[3])] == KIND_DEF_USE
    assert kinds[(local[3], local[4])] == KIND_DEF_USE
    # halo in-edge and out-edge present
    assert kinds[(local[1], local[2])] == KIND_DEF_USE
    assert kinds[(local[4], local[5])] == KIND_DEF_USE
    # no halo->halo edges
    halo = set(ids[3:])
    assert all(not (s in halo and d in halo) for s, d in kinds)
    # order edge 1 -> 3 present
    assert kinds[(local[1], local[3])] == KIND_ORDER
    # external_read into node 3 with sentinel src
    er = [
        (s, d)
        for s, d, k in zip(region.edge_src, region.edge_dst, region.edge_kind)
        if k == KIND_EXTERNAL_READ
    ]
    assert er == [(EXTERNAL_SRC, local[3])]
    # widths carried through
    w = {
        (int(s), int(d)): int(wd)
        for s, d, wd, k in zip(region.edge_src, region.edge_dst, region.edge_width, region.edge_kind)
        if k == KIND_DEF_USE
    }
    assert w[(local[3], local[4])] == 96


def test_must_cover_ultra_rare_op():
    """An opcode present once in the whole graph still lands in the dataset."""
    names = ["add", "mem.write", "changed.neg"]
    ops = {i: 1 for i in range(0, 60, 10)}
    ops[45] = 2  # the single changed.neg node (outside the holdout interval)
    graph = make_graph(
        60,
        du=[(i, i + 1, i, 32) for i in range(59)],
        ops=ops,
        opcode_names=names,
    )
    sampler = Sampler(graph, tiny_config(cover_threshold=3))
    regions, report = sampler.sample_round(8, seed=5)
    cov = report["coverage"]
    assert cov["opcode_hist"].get("changed.neg", 0) > 0
    assert cov["uncovered_ops"] == []
    seeded = [r for r in report["regions"] if r["cover_op"] == "changed.neg"]
    assert len(seeded) == 1


def test_roundtrip_and_rare_quota(tmp_path):
    names = ["add", "mem.write"]
    ops = {i: 1 for i in range(0, 60, 10)}  # rare nodes at 0,10,...,50
    graph = make_graph(
        60,
        du=[(i, i + 1, i, 32) for i in range(59)],
        ops=ops,
        opcode_names=names,
    )
    sampler = Sampler(graph, tiny_config())
    regions, report = sampler.sample_round(8, seed=3)
    assert len(regions) == 8
    cov = report["coverage"]
    assert cov["method_split"] == {"topo": 4, "bfs": 4}
    assert cov["holdout_violations"] == 0
    assert cov["rare_region_frac"] >= 0.25
    # npz round-trip
    path = tmp_path / "r0.npz"
    regions[0].save(path)
    loaded = Region.load(path)
    assert loaded.internal_count == regions[0].internal_count
    assert np.array_equal(loaded.node_id, regions[0].node_id)
    assert np.array_equal(loaded.edge_kind, regions[0].edge_kind)
