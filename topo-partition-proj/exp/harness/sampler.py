"""Region sampler (docs/04 Phase 0 task 3, parameters D4).

Cuts the full-graph canonical topo order into training regions, half as
contiguous topo windows (the world the segment DP sees) and half as BFS
blobs grown from a seed (the natural shape of a clump of logic).

Holdout discipline: a contiguous ``holdout_frac`` slice of the topo order is
forbidden for training samples (contiguous, because nearby windows overlap
heavily — random scattering would leak the exam into training). Regions
whose internal set touches the holdout interval are rejected and resampled.

Each region carries a read-only halo — context for features and for the
search's view of cut edges, never a training/label target. As-built
(2026-07-30, recorded in docs/07) the halo is **one hop, asymmetric by
direction**: predecessor halo (producers + order predecessors) is complete
because those values enter the region cost as permanent boundaries;
successor halo is capped per internal node (``halo_fanout_cap``) because
heavy-tail hubs (max out-degree ~16k) otherwise explode the region file —
an uncapped 2-hop halo measures a median 236k / max 629k nodes on the full
XiangShan graph, which makes D4's literal "2 hops" default infeasible.

Rare-structure quota, two layers: at least ``rare_frac`` of regions are
steered to MemoryWrite/DPI-style opcodes (window centered on a rare node, or
BFS seeded at one); additionally every opcode type with fewer than
``cover_threshold`` nodes globally gets one dedicated BFS-seeded region, so
ultra-rare types (changed.neg appears exactly once in the whole graph) still
show up in training data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .graph import (
    KIND_DEF_USE,
    KIND_EXTERNAL_READ,
    KIND_ORDER,
    InstructionGraph,
    build_csr,
)

#: Opcodes treated as rare structures (D4: MemoryWrite/DPI and friends).
RARE_OPCODES = ("mem.write", "mem.fill", "latch.write", "dpi.call", "system.task")

#: Sentinel used as edge_src of external_read edges in region files (they
#: have no producer node).
EXTERNAL_SRC = np.iinfo(np.uint32).max


@dataclass
class SamplerConfig:
    min_internal: int = 2048
    max_internal: int = 8192
    halo_fanout_cap: int = 512  # per internal node, successor direction only
    holdout_frac: float = 0.10
    holdout_start_frac: float = 0.45  # contiguous mid-range interval
    rare_frac: float = 0.125  # target >= 0.10 (D4)
    cover_threshold: int = 2048  # opcodes rarer than this get a seeded region
    seed: int = 20260730
    rare_opcodes: tuple[str, ...] = RARE_OPCODES


@dataclass
class Region:
    """One sampled region. Local node order: internal first, then halo."""

    node_id: np.ndarray  # (M,) uint32 global instruction ids
    internal_count: int
    op: np.ndarray  # (M,) uint8
    width: np.ndarray  # (M,) int32
    state_write: np.ndarray  # (M,) bool
    comb_loop_atom: np.ndarray  # (M,) bool
    topo_pos: np.ndarray  # (M,) uint32 position in the canonical order
    edge_src: np.ndarray  # (E,) uint32 local index or EXTERNAL_SRC
    edge_dst: np.ndarray  # (E,) uint32 local index
    edge_kind: np.ndarray  # (E,) uint8 KIND_*
    edge_var: np.ndarray  # (E,) uint32 (-1 for order edges)
    edge_width: np.ndarray  # (E,) int32 (0 for order edges)
    meta: dict = field(default_factory=dict)

    @property
    def halo_count(self) -> int:
        return int(self.node_id.size) - self.internal_count

    def save(self, path: str | Path) -> None:
        np.savez(
            Path(path),
            node_id=self.node_id,
            internal_count=np.array([self.internal_count]),
            op=self.op,
            width=self.width,
            state_write=self.state_write,
            comb_loop_atom=self.comb_loop_atom,
            topo_pos=self.topo_pos,
            edge_src=self.edge_src,
            edge_dst=self.edge_dst,
            edge_kind=self.edge_kind,
            edge_var=self.edge_var,
            edge_width=self.edge_width,
            meta=np.array([json.dumps(self.meta, sort_keys=True)]),
        )

    @staticmethod
    def load(path: str | Path) -> "Region":
        with np.load(Path(path), allow_pickle=False) as data:
            return Region(
                node_id=data["node_id"],
                internal_count=int(data["internal_count"][0]),
                op=data["op"],
                width=data["width"],
                state_write=data["state_write"],
                comb_loop_atom=data["comb_loop_atom"],
                topo_pos=data["topo_pos"],
                edge_src=data["edge_src"],
                edge_dst=data["edge_dst"],
                edge_kind=data["edge_kind"],
                edge_var=data["edge_var"],
                edge_width=data["edge_width"],
                meta=json.loads(str(data["meta"][0])),
            )


class Sampler:
    def __init__(self, graph: InstructionGraph, config: SamplerConfig | None = None):
        self.graph = graph
        self.config = config or SamplerConfig()
        self.out_off, self.out_tgt = graph.out_csr()
        self.in_off, self.in_src = graph.in_csr()
        # Kind-specific incidence for edge extraction.
        self.du_out_off, du_out_idx = build_csr(graph.du_src, np.arange(graph.du_src.size), graph.instructions)
        self.du_in_off, du_in_idx = build_csr(graph.du_dst, np.arange(graph.du_dst.size), graph.instructions)
        self.du_out_idx, self.du_in_idx = du_out_idx, du_in_idx
        self.ord_out_off, ord_out_idx = build_csr(graph.ord_src, np.arange(graph.ord_src.size), graph.instructions)
        self.ord_in_off, ord_in_idx = build_csr(graph.ord_dst, np.arange(graph.ord_dst.size), graph.instructions)
        self.ord_out_idx, self.ord_in_idx = ord_out_idx, ord_in_idx
        self.er_in_off, er_in_idx = build_csr(graph.er_dst, np.arange(graph.er_dst.size), graph.instructions)
        self.er_in_idx = er_in_idx
        # Rare-structure nodes.
        rare_ops = {
            op for op, name in enumerate(graph.opcode_names) if name in self.config.rare_opcodes
        }
        self.rare_mask = np.isin(graph.op, list(rare_ops))
        self.rare_nodes = np.flatnonzero(self.rare_mask)
        # Holdout interval in topo positions.
        n = graph.instructions
        self.holdout_start = int(n * self.config.holdout_start_frac)
        self.holdout_end = self.holdout_start + int(n * self.config.holdout_frac)
        self._in_holdout = np.zeros(n, dtype=bool)
        self._in_holdout[self.holdout_start : self.holdout_end] = True
        self._node_in_holdout = self._in_holdout[graph.topo_pos]

    # ---- expansion primitives ------------------------------------------

    def _neighbors(self, node: int) -> tuple[np.ndarray, np.ndarray]:
        out = self.out_tgt[self.out_off[node] : self.out_off[node + 1]]
        inn = self.in_src[self.in_off[node] : self.in_off[node + 1]]
        return out, inn

    def _bfs_grow(self, seed: int, target: int) -> np.ndarray | None:
        """Undirected BFS from seed until target nodes; None if exhausted."""
        visited = np.zeros(self.graph.instructions, dtype=bool)
        visited[seed] = True
        members = [seed]
        frontier = [seed]
        while frontier and len(members) < target:
            next_frontier: list[int] = []
            for node in frontier:
                out, inn = self._neighbors(node)
                for neighbor in np.concatenate([out, inn]):
                    neighbor = int(neighbor)
                    if not visited[neighbor]:
                        visited[neighbor] = True
                        members.append(neighbor)
                        next_frontier.append(neighbor)
                        if len(members) >= target:
                            break
                if len(members) >= target:
                    break
            frontier = next_frontier
        if len(members) < target:
            return None
        return np.array(members, dtype=np.uint32)

    def _halo(self, internal: np.ndarray) -> tuple[np.ndarray, int]:
        """One-hop, asymmetric halo; returns (halo ids, capped node count).

        Predecessors (def_use producers + order predecessors) are complete:
        they are the region's permanent boundary. Successors are capped per
        internal node at ``halo_fanout_cap`` (first neighbors in CSR order):
        context only, and heavy-tail hubs would otherwise explode the file.
        """
        config = self.config
        in_internal = np.zeros(self.graph.instructions, dtype=bool)
        in_internal[internal] = True
        seen = in_internal.copy()
        halo: list[int] = []
        capped = 0
        for node in internal.tolist():
            inn = self.in_src[self.in_off[node] : self.in_off[node + 1]]
            for neighbor in inn:
                neighbor = int(neighbor)
                if not seen[neighbor]:
                    seen[neighbor] = True
                    halo.append(neighbor)
            out = self.out_tgt[self.out_off[node] : self.out_off[node + 1]]
            if out.size > config.halo_fanout_cap:
                out = out[: config.halo_fanout_cap]
                capped += 1
            for neighbor in out:
                neighbor = int(neighbor)
                if not seen[neighbor]:
                    seen[neighbor] = True
                    halo.append(neighbor)
        return np.array(halo, dtype=np.uint32), capped

    # ---- region assembly -------------------------------------------------

    def build_region(self, internal: np.ndarray, meta: dict) -> Region:
        graph = self.graph
        internal = np.unique(internal.astype(np.uint32))
        halo, capped = self._halo(internal)
        node_id = np.concatenate([internal, halo])
        local_of = np.full(graph.instructions, -1, dtype=np.int64)
        local_of[node_id] = np.arange(node_id.size)
        edge_src: list[int] = []
        edge_dst: list[int] = []
        edge_kind: list[int] = []
        edge_var: list[int] = []
        edge_width: list[int] = []

        def emit(src, dst, kind, var, width):
            edge_src.append(src)
            edge_dst.append(dst)
            edge_kind.append(kind)
            edge_var.append(var)
            edge_width.append(width)

        for local, node in enumerate(node_id.tolist()):
            if local >= internal.size:
                break  # only internal nodes emit; halo endpoints are targets
            # external_read into the node: permanent boundary values.
            for idx in self.er_in_idx[self.er_in_off[node] : self.er_in_off[node + 1]]:
                idx = int(idx)
                emit(EXTERNAL_SRC, local, KIND_EXTERNAL_READ,
                     int(graph.er_var[idx]), int(graph.er_width[idx]))
            # def_use in-edges (covers internal<-internal and internal<-halo).
            for idx in self.du_in_idx[self.du_in_off[node] : self.du_in_off[node + 1]]:
                idx = int(idx)
                source = local_of[graph.du_src[idx]]
                if source >= 0:  # else: halo truncated away
                    emit(int(source), local, KIND_DEF_USE,
                         int(graph.du_var[idx]), int(graph.du_width[idx]))
            # def_use out-edges to halo only (internal->internal already
            # emitted as the target's in-edge).
            for idx in self.du_out_idx[self.du_out_off[node] : self.du_out_off[node + 1]]:
                idx = int(idx)
                target = local_of[graph.du_dst[idx]]
                if target >= internal.size:  # halo (or -1 impossible: 1-hop neighbor)
                    if target >= 0:
                        emit(local, int(target), KIND_DEF_USE,
                             int(graph.du_var[idx]), int(graph.du_width[idx]))
            # order edges, same rule: in-edges always, out-edges to halo only.
            for idx in self.ord_in_idx[self.ord_in_off[node] : self.ord_in_off[node + 1]]:
                idx = int(idx)
                source = local_of[graph.ord_src[idx]]
                if source >= 0:
                    emit(int(source), local, KIND_ORDER, 0xFFFFFFFF, 0)
            for idx in self.ord_out_idx[self.ord_out_off[node] : self.ord_out_off[node + 1]]:
                idx = int(idx)
                target = local_of[graph.ord_dst[idx]]
                if target >= internal.size and target >= 0:
                    emit(local, int(target), KIND_ORDER, 0xFFFFFFFF, 0)
        meta = dict(meta)
        meta["halo_capped_nodes"] = int(capped)
        return Region(
            node_id=node_id,
            internal_count=int(internal.size),
            op=graph.op[node_id],
            width=graph.width[node_id],
            state_write=graph.state_write[node_id],
            comb_loop_atom=graph.comb_loop_atom[node_id],
            topo_pos=graph.topo_pos[node_id],
            edge_src=np.array(edge_src, dtype=np.uint32),
            edge_dst=np.array(edge_dst, dtype=np.uint32),
            edge_kind=np.array(edge_kind, dtype=np.uint8),
            edge_var=np.array(edge_var, dtype=np.uint32),
            edge_width=np.array(edge_width, dtype=np.int32),
            meta=meta,
        )

    # ---- sampling strategies ---------------------------------------------

    def _size(self, rng: np.random.Generator) -> int:
        return int(rng.integers(self.config.min_internal, self.config.max_internal + 1))

    def _topo_window(self, rng: np.random.Generator, rare: bool) -> np.ndarray:
        order = self.graph.topo_order
        n = order.size
        for _ in range(200):
            size = self._size(rng)
            if rare:
                node = int(self.rare_nodes[rng.integers(self.rare_nodes.size)])
                start = int(self.graph.topo_pos[node]) - size // 2
                start = min(max(start, 0), n - size)
            else:
                start = int(rng.integers(0, n - size + 1))
            if start < self.holdout_end and start + size > self.holdout_start:
                continue  # overlaps the forbidden interval
            return order[start : start + size]
        raise RuntimeError("could not place a topo window outside the holdout")

    def _bfs_region(self, rng: np.random.Generator, rare: bool) -> np.ndarray:
        for _ in range(200):
            if rare:
                seed = int(self.rare_nodes[rng.integers(self.rare_nodes.size)])
            else:
                seed = int(rng.integers(self.graph.instructions))
            members = self._seeded_region(rng, seed)
            if members is not None:
                return members
        raise RuntimeError("could not grow a BFS region outside the holdout")

    def _seeded_region(self, rng: np.random.Generator, seed: int) -> np.ndarray | None:
        """BFS blob around a fixed seed; topo window fallback; None if the
        holdout makes the seed unusable."""
        if self._node_in_holdout[seed]:
            return None
        members = self._bfs_grow(seed, self._size(rng))
        if members is not None and not self._node_in_holdout[members].any():
            return members
        # Fallback: a topo window centered at the seed (still covers its op).
        order = self.graph.topo_order
        n = order.size
        size = self._size(rng)
        start = min(max(int(self.graph.topo_pos[seed]) - size // 2, 0), n - size)
        if start < self.holdout_end and start + size > self.holdout_start:
            return None
        return order[start : start + size]

    def _must_cover_seeds(self, rng: np.random.Generator) -> tuple[list[tuple[int, str]], list[str]]:
        """One seed node per ultra-rare opcode type; (seeds, uncovered names)."""
        counts = np.bincount(self.graph.op, minlength=len(self.graph.opcode_names))
        seeds: list[tuple[int, str]] = []
        uncovered: list[str] = []
        for op, name in enumerate(self.graph.opcode_names):
            if not name or counts[op] == 0 or counts[op] >= self.config.cover_threshold:
                continue
            candidates = np.flatnonzero(self.graph.op == op)
            candidates = candidates[rng.permutation(candidates.size)]
            seed = next(
                (int(node) for node in candidates if not self._node_in_holdout[node]),
                None,
            )
            if seed is None:
                uncovered.append(name)
            else:
                seeds.append((seed, name))
        return seeds, uncovered

    def sample_round(self, count: int, seed: int | None = None) -> tuple[list[Region], dict]:
        """Sample one round of regions; returns (regions, coverage report)."""
        config = self.config
        rng = np.random.default_rng(config.seed if seed is None else seed)
        cover_seeds, uncovered_ops = self._must_cover_seeds(rng)
        plan: list[dict] = [
            {"method": "bfs", "rare": True, "seed": node, "cover_op": name}
            for node, name in cover_seeds
        ]
        remaining = count - len(plan)
        splits = {"topo": remaining // 2, "bfs": remaining - remaining // 2}
        for method in ("topo", "bfs"):
            total = splits[method]
            rare_count = int(round(total * config.rare_frac))
            plan.extend({"method": method, "rare": True} for _ in range(rare_count))
            plan.extend({"method": method, "rare": False} for _ in range(total - rare_count))
        rng.shuffle(plan)
        regions: list[Region] = []
        report_regions: list[dict] = []
        opcode_hist = np.zeros(max(1, len(self.graph.opcode_names)), dtype=np.int64)
        union_internal = np.zeros(self.graph.instructions, dtype=bool)
        for index, entry in enumerate(plan):
            if "seed" in entry:
                internal = self._seeded_region(rng, entry["seed"])
                if internal is None:  # seed blocked by holdout after all
                    uncovered_ops.append(entry["cover_op"])
                    continue
            elif entry["method"] == "topo":
                internal = self._topo_window(rng, entry["rare"])
            else:
                internal = self._bfs_region(rng, entry["rare"])
            meta = {
                "index": index,
                "method": entry["method"],
                "rare_guided": entry["rare"],
                "cover_op": entry.get("cover_op"),
                "seed": int(rng.integers(2**31)),
            }
            region = self.build_region(internal, meta)
            regions.append(region)
            internal_nodes = region.node_id[: region.internal_count]
            union_internal[internal_nodes] = True
            ops, counts = np.unique(region.op[: region.internal_count], return_counts=True)
            opcode_hist[ops] += counts
            rare_internal = bool(self.rare_mask[internal_nodes].any())
            report_regions.append(
                {
                    "index": index,
                    "method": entry["method"],
                    "rare_guided": entry["rare"],
                    "cover_op": entry.get("cover_op"),
                    "internal": region.internal_count,
                    "halo": region.halo_count,
                    "edges": int(region.edge_src.size),
                    "state_write_internal": int(region.state_write[: region.internal_count].sum()),
                    "rare_internal": rare_internal,
                    "halo_capped_nodes": int(region.meta["halo_capped_nodes"]),
                }
            )
        sizes = np.array([entry["internal"] for entry in report_regions])
        halo_sizes = np.array([entry["halo"] for entry in report_regions])
        rare_regions = sum(1 for entry in report_regions if entry["rare_internal"])
        report = {
            "config": {
                "min_internal": config.min_internal,
                "max_internal": config.max_internal,
                "halo_fanout_cap": config.halo_fanout_cap,
                "holdout_frac": config.holdout_frac,
                "holdout_start_frac": config.holdout_start_frac,
                "holdout_interval": [self.holdout_start, self.holdout_end],
                "rare_frac_target": config.rare_frac,
                "rare_opcodes": list(config.rare_opcodes),
                "cover_threshold": config.cover_threshold,
                "seed": config.seed if seed is None else seed,
            },
            "regions": report_regions,
            "coverage": {
                "region_count": len(regions),
                "method_split": {
                    "topo": sum(1 for e in report_regions if e["method"] == "topo"),
                    "bfs": sum(1 for e in report_regions if e["method"] == "bfs"),
                },
                "internal_size": {
                    "min": int(sizes.min()),
                    "median": float(np.median(sizes)),
                    "max": int(sizes.max()),
                },
                "halo_size": {
                    "min": int(halo_sizes.min()),
                    "median": float(np.median(halo_sizes)),
                    "max": int(halo_sizes.max()),
                },
                "rare_region_frac": rare_regions / max(1, len(regions)),
                "rare_region_count": rare_regions,
                "opcode_hist": {
                    name or f"op{op}": int(opcode_hist[op])
                    for op, name in enumerate(self.graph.opcode_names)
                    if opcode_hist[op] > 0 or name
                },
                "opcode_types_covered": int((opcode_hist > 0).sum()),
                "opcode_types_in_graph": int(len({op for op in self.graph.op})),
                "uncovered_ops": sorted(uncovered_ops),
                "union_internal_nodes": int(union_internal.sum()),
                "union_internal_frac_of_graph": float(union_internal.sum() / self.graph.instructions),
                "holdout_violations": int(
                    sum(
                        self._node_in_holdout[r.node_id[: r.internal_count]].sum()
                        for r in regions
                    )
                ),
                "regions_with_halo_cap": sum(
                    1 for e in report_regions if e["halo_capped_nodes"] > 0
                ),
            },
        }
        return regions, report


def save_dataset(regions: list[Region], report: dict, out_dir: str | Path) -> None:
    """Write region npz files + manifest.json into out_dir."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = dict(report)
    manifest["files"] = []
    for region, entry in zip(regions, report["regions"]):
        name = f"region_{entry['index']:04d}.npz"
        region.save(out_dir / name)
        manifest["files"].append(name)
    with open(out_dir / "manifest.json", "w") as stream:
        json.dump(manifest, stream, indent=1, ensure_ascii=False)
