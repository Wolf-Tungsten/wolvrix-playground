"""CPU inference floor measurement (docs/04 Phase 0 task 5, risk R3).

The compile machine has no GPU, so the full-graph GNN inference at compile
time runs on CPU (K7: hidden <= 64, 2-3 layers; 02 §6.5 budgets ~10-60 s for
inference). A GraphSAGE layer is two memory-bound kernels — gather neighbor
vectors along edges, then segment-sum them (SpMM) — plus one BLAS matmul.
This benchmark times exactly those kernels at full XiangShan scale
(4.67M nodes, ~8.05M def_use+order edges) with numpy, which is the right
proxy for the hand-written C++ gather/SpMM that production will use (D6,
Phase 4 task 1), and derives the per-layer / per-model cost table.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from .graph import InstructionGraph


@dataclass
class BenchResult:
    nodes: int
    edges: int
    dims: list[int]
    gather_s: dict[int, float]  # dim -> seconds for one E x dim gather
    spmm_s: dict[int, float]  # dim -> seconds for one segment-sum
    matmul_s: dict[int, float]  # dim -> seconds for N x dim @ dim x dim
    gather_gbs: dict[int, float]

    def layer_s(self, dim: int) -> float:
        """One GraphSAGE layer: gather + segment-mean + [h, agg] @ W (2d x d)."""
        return self.gather_s[dim] + self.spmm_s[dim] + 2 * self.matmul_s[dim]

    def model_s(self, dim: int, layers: int) -> float:
        return layers * self.layer_s(dim) + self.matmul_s[dim]  # + score head


def _time(fn, repeats: int = 3) -> float:
    best = float("inf")
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - started)
    return best


def run_bench(graph: InstructionGraph, dims: tuple[int, ...] = (32, 64)) -> BenchResult:
    """Time gather/SpMM/matmul on the real edge list."""
    src, dst = graph.dependency_edges()
    nodes, edges = graph.instructions, src.size
    src = src.astype(np.int64)
    # CSR by dst for the segment-sum.
    order = np.argsort(dst, kind="stable")
    dst_sorted = dst[order].astype(np.int64)
    src_sorted = src[order]
    offsets = np.zeros(nodes + 1, dtype=np.int64)
    np.add.at(offsets, dst_sorted + 1, 1)
    np.cumsum(offsets, out=offsets)
    nonempty = np.diff(offsets) > 0
    seg_starts = offsets[:-1][nonempty]
    degree = np.maximum(1, np.diff(offsets)).astype(np.float32)

    rng = np.random.default_rng(0)
    gather_s: dict[int, float] = {}
    spmm_s: dict[int, float] = {}
    matmul_s: dict[int, float] = {}
    gather_gbs: dict[int, float] = {}
    for dim in dims:
        x = rng.standard_normal((nodes, dim), dtype=np.float32)
        messages: dict[str, np.ndarray] = {}

        def gather():
            messages["m"] = x[src_sorted]

        def spmm():
            out = np.zeros((nodes, dim), dtype=np.float32)
            out[nonempty] = np.add.reduceat(messages["m"], seg_starts, axis=0)
            out /= degree[:, None]

        gather_t = _time(gather)
        spmm_t = _time(spmm)
        w = rng.standard_normal((dim, dim), dtype=np.float32)
        matmul_t = _time(lambda: x @ w)
        gather_s[dim] = gather_t
        spmm_s[dim] = spmm_t
        matmul_s[dim] = matmul_t
        gather_gbs[dim] = edges * dim * 4 / gather_t / 1e9
        del messages, x
    return BenchResult(
        nodes=nodes,
        edges=int(edges),
        dims=list(dims),
        gather_s=gather_s,
        spmm_s=spmm_s,
        matmul_s=matmul_s,
        gather_gbs=gather_gbs,
    )


def format_report(result: BenchResult) -> str:
    lines = [
        f"nodes={result.nodes} edges={result.edges}",
        f"{'dim':>4} {'gather':>8} {'spmm':>8} {'matmul':>8} {'layer':>8} "
        f"{'2-layer':>8} {'3-layer':>8} {'GB/s':>6}",
    ]
    for dim in result.dims:
        lines.append(
            f"{dim:>4} {result.gather_s[dim]:>7.2f}s {result.spmm_s[dim]:>7.2f}s "
            f"{result.matmul_s[dim]:>7.2f}s {result.layer_s(dim):>7.2f}s "
            f"{result.model_s(dim, 2):>7.2f}s {result.model_s(dim, 3):>7.2f}s "
            f"{result.gather_gbs[dim]:>5.1f}"
        )
    return "\n".join(lines)
