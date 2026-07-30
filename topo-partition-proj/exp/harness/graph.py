"""Instruction-graph loader for the wolvrix AM instruction-graph JSONL export.

Format ``wolvrix.am-instruction-graph.v1`` (docs/05, wolvrix
grhsim-am-pipeline.md §3.2.4): one JSON record per line — a header, node
records, and three edge kinds (def_use / external_read / order).

The full XiangShan export is 1.44 GB / 14.9M lines, so this module parses it
once into compact numpy arrays and caches the result as ``graph_cache.npz``
next to the JSONL. It also computes the canonical topological order used by
the sampler (topo windows) and the searcher (baseline order): deterministic
Kahn over def_use + order edges with smallest-instruction-id tie-break. The
raw instruction id order is NOT topological (hundreds of thousands of
back-edges), so this order is computed, not assumed.
"""

from __future__ import annotations

import heapq
import json
import time
from array import array
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

GRAPH_FORMAT = "wolvrix.am-instruction-graph.v1"
CACHE_VERSION = 1

# Edge kinds used throughout the harness.
KIND_DEF_USE = 0
KIND_EXTERNAL_READ = 1
KIND_ORDER = 2


@dataclass
class InstructionGraph:
    """Flat arrays for the exported instruction graph."""

    instructions: int
    variables: int
    op: np.ndarray  # (N,) uint8, Opcode number (embedding index)
    opcode_names: list[str]  # op -> name
    width: np.ndarray  # (N,) int32, sum of result widths
    state_write: np.ndarray  # (N,) bool, commit-kind instruction
    atom: np.ndarray  # (N,) uint32, SCC component id from the exporter
    comb_loop_atom: np.ndarray  # (N,) bool
    du_src: np.ndarray = field(repr=False)  # (E1,) uint32
    du_dst: np.ndarray = field(repr=False)
    du_var: np.ndarray = field(repr=False)
    du_width: np.ndarray = field(repr=False)  # int32
    er_dst: np.ndarray = field(repr=False)  # (E2,) uint32
    er_var: np.ndarray = field(repr=False)
    er_width: np.ndarray = field(repr=False)  # int32
    ord_src: np.ndarray = field(repr=False)  # (E3,) uint32
    ord_dst: np.ndarray = field(repr=False)
    topo_order: np.ndarray = field(repr=False)  # (N,) uint32, topo_order[pos] = node
    topo_pos: np.ndarray = field(repr=False)  # (N,) uint32, topo_pos[node] = pos

    # ---- derived views -------------------------------------------------

    def dependency_edges(self) -> tuple[np.ndarray, np.ndarray]:
        """(src, dst) over def_use + order edges: the DAG adjacency."""
        src = np.concatenate([self.du_src, self.ord_src])
        dst = np.concatenate([self.du_dst, self.ord_dst])
        return src, dst

    def out_csr(self) -> tuple[np.ndarray, np.ndarray]:
        """CSR keyed by src: (offsets[N+1], targets[E]) sorted by src."""
        src, dst = self.dependency_edges()
        return build_csr(src, dst, self.instructions)

    def in_csr(self) -> tuple[np.ndarray, np.ndarray]:
        """CSR keyed by dst: (offsets[N+1], sources[E]) sorted by dst."""
        src, dst = self.dependency_edges()
        return build_csr(dst, src, self.instructions)

    def var_def(self) -> np.ndarray:
        """(V,) int32: defining instruction of each variable, -1 if none."""
        definition = np.full(self.variables, -1, dtype=np.int32)
        # One definition per variable by construction (SSA-style AM values).
        definition[self.du_var] = self.du_src.astype(np.int32)
        return definition

    def comb_groups(self) -> tuple[np.ndarray, np.ndarray]:
        """Contract comb-loop-atoms into indivisible groups.

        Returns (group_of_node[N] uint32, group_weight[G] uint32). Nodes with
        comb_loop_atom=false are singleton groups; the full XiangShan graph
        has comb_loop_atoms=0, so this is the identity there.
        """
        key = np.where(
            self.comb_loop_atom,
            self.atom.astype(np.int64),
            self.atom.max().astype(np.int64) + 1 + np.arange(self.instructions),
        )
        _, group_of_node = np.unique(key, return_inverse=True)
        group_weight = np.bincount(group_of_node).astype(np.uint32)
        return group_of_node.astype(np.uint32), group_weight


def build_csr(keys: np.ndarray, values: np.ndarray, count: int) -> tuple[np.ndarray, np.ndarray]:
    """Build (offsets, values-sorted-by-key) CSR from parallel arrays."""
    order = np.argsort(keys, kind="stable")
    sorted_values = values[order].astype(np.uint32, copy=False)
    sorted_keys = keys[order]
    offsets = np.zeros(count + 1, dtype=np.int64)
    np.add.at(offsets, sorted_keys.astype(np.int64) + 1, 1)
    np.cumsum(offsets, out=offsets)
    return offsets, sorted_values


def kahn_order(graph: InstructionGraph) -> np.ndarray:
    """Deterministic Kahn topo order, smallest instruction id tie-break.

    Runs on the comb-loop-contracted DAG (docs/03: a comb-loop-atom is
    indivisible), then expands groups back to node level (members by id).
    """
    group_of_node, _ = graph.comb_groups()
    group_count = int(group_of_node.max()) + 1
    src, dst = graph.dependency_edges()
    gsrc = group_of_node[src].astype(np.int64)
    gdst = group_of_node[dst].astype(np.int64)
    keep = gsrc != gdst
    gsrc, gdst = gsrc[keep], gdst[keep]
    indegree = np.bincount(gdst, minlength=group_count).astype(np.int64)
    offsets, targets = build_csr(gsrc, gdst, group_count)
    # Tie-break on the smallest member instruction id of the group.
    min_member = np.full(group_count, np.iinfo(np.uint32).max, dtype=np.uint32)
    np.minimum.at(min_member, group_of_node, np.arange(graph.instructions, dtype=np.uint32))
    ready = [(int(min_member[g]), g) for g in np.flatnonzero(indegree == 0)]
    heapq.heapify(ready)
    group_order = np.empty(group_count, dtype=np.uint32)
    placed = 0
    while ready:
        _, group = heapq.heappop(ready)
        group_order[placed] = group
        placed += 1
        for index in range(offsets[group], offsets[group + 1]):
            target = int(targets[index])
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, (int(min_member[target]), target))
    if placed != group_count:
        raise ValueError(
            f"instruction graph is cyclic past comb-loop contraction: "
            f"placed {placed} of {group_count} groups"
        )
    # Expand groups to node level: groups in topo order, members by id.
    member_lists: list[list[int]] = [[] for _ in range(group_count)]
    for node in range(graph.instructions):
        member_lists[group_of_node[node]].append(node)
    order = np.empty(graph.instructions, dtype=np.uint32)
    cursor = 0
    for group in group_order:
        for node in sorted(member_lists[group]):
            order[cursor] = node
            cursor += 1
    return order


def load_graph(jsonl_path: str | Path, use_cache: bool = True, verbose: bool = True) -> InstructionGraph:
    """Load the JSONL export, using/rebuilding the npz cache next to it."""
    jsonl_path = Path(jsonl_path)
    cache_path = jsonl_path.with_name("graph_cache.npz")
    if use_cache and cache_path.exists() and cache_path.stat().st_mtime >= jsonl_path.stat().st_mtime:
        if verbose:
            print(f"[graph] loading cache {cache_path}")
        return _load_cache(cache_path)
    started = time.time()
    graph = _parse_jsonl(jsonl_path)
    if verbose:
        print(f"[graph] parsed {jsonl_path.name} in {time.time() - started:.1f}s")
    started = time.time()
    order = kahn_order(graph)
    pos = np.empty(graph.instructions, dtype=np.uint32)
    pos[order] = np.arange(graph.instructions, dtype=np.uint32)
    graph.topo_order = order
    graph.topo_pos = pos
    if verbose:
        print(f"[graph] Kahn topo order in {time.time() - started:.1f}s")
    if use_cache:
        _save_cache(graph, cache_path)
        if verbose:
            print(f"[graph] cache written to {cache_path}")
    return graph


def _parse_jsonl(jsonl_path: Path) -> InstructionGraph:
    header = None
    op = array("B")
    width = array("i")
    state_write = array("b")
    atom = array("I")
    comb_loop = array("b")
    opcode_of: dict[str, int] = {}
    opcode_names: list[str] = []
    du_src, du_dst, du_var, du_width = array("I"), array("I"), array("I"), array("i")
    er_dst, er_var, er_width = array("I"), array("I"), array("i")
    ord_src, ord_dst = array("I"), array("I")
    node_records = 0
    with open(jsonl_path) as stream:
        for line in stream:
            record = json.loads(line)
            kind = record["record"]
            if kind == "header":
                if record["format"] != GRAPH_FORMAT:
                    raise ValueError(f"unsupported graph format: {record['format']}")
                header = record
            elif kind == "node":
                name = record["opcode"]
                op_value = record["op"]
                if name not in opcode_of:
                    # op numbers come from the exporter's Opcode enum; keep the
                    # name table indexable by op value.
                    while len(opcode_names) <= op_value:
                        opcode_names.append("")
                    opcode_names[op_value] = name
                    opcode_of[name] = op_value
                op.append(op_value)
                width.append(record["width"])
                state_write.append(1 if record["state_write"] else 0)
                atom.append(record["atom"])
                comb_loop.append(1 if record["comb_loop_atom"] else 0)
                node_records += 1
            elif kind == "edge":
                edge_kind = record["kind"]
                if edge_kind == "def_use":
                    du_src.append(record["src"])
                    du_dst.append(record["dst"])
                    du_var.append(record["var"])
                    du_width.append(record["width"])
                elif edge_kind == "external_read":
                    er_dst.append(record["dst"])
                    er_var.append(record["var"])
                    er_width.append(record["width"])
                else:
                    ord_src.append(record["src"])
                    ord_dst.append(record["dst"])
    if header is None:
        raise ValueError(f"{jsonl_path} has no header record")
    counts = {
        "instructions": node_records,
        "def_use_edges": len(du_src),
        "external_reads": len(er_dst),
        "order_edges": len(ord_src),
    }
    for key, actual in counts.items():
        if header[key] != actual:
            raise ValueError(f"{jsonl_path}: header {key}={header[key]} != parsed {actual}")
    graph = InstructionGraph(
        instructions=header["instructions"],
        variables=header["variables"],
        op=np.frombuffer(op, dtype=np.uint8).copy(),
        opcode_names=opcode_names,
        width=np.frombuffer(width, dtype=np.int32).copy(),
        state_write=np.frombuffer(state_write, dtype=np.int8).astype(bool),
        atom=np.frombuffer(atom, dtype=np.uint32).copy(),
        comb_loop_atom=np.frombuffer(comb_loop, dtype=np.int8).astype(bool),
        du_src=np.frombuffer(du_src, dtype=np.uint32).copy(),
        du_dst=np.frombuffer(du_dst, dtype=np.uint32).copy(),
        du_var=np.frombuffer(du_var, dtype=np.uint32).copy(),
        du_width=np.frombuffer(du_width, dtype=np.int32).copy(),
        er_dst=np.frombuffer(er_dst, dtype=np.uint32).copy(),
        er_var=np.frombuffer(er_var, dtype=np.uint32).copy(),
        er_width=np.frombuffer(er_width, dtype=np.int32).copy(),
        ord_src=np.frombuffer(ord_src, dtype=np.uint32).copy(),
        ord_dst=np.frombuffer(ord_dst, dtype=np.uint32).copy(),
        topo_order=np.empty(0, dtype=np.uint32),
        topo_pos=np.empty(0, dtype=np.uint32),
    )
    if graph.instructions != node_records:
        raise ValueError("node ids are not dense 0..N-1")
    return graph


def _save_cache(graph: InstructionGraph, cache_path: Path) -> None:
    np.savez(
        cache_path,
        cache_version=np.array([CACHE_VERSION]),
        instructions=np.array([graph.instructions]),
        variables=np.array([graph.variables]),
        op=graph.op,
        opcode_names=np.array([json.dumps(graph.opcode_names)]),
        width=graph.width,
        state_write=graph.state_write,
        atom=graph.atom,
        comb_loop_atom=graph.comb_loop_atom,
        du_src=graph.du_src,
        du_dst=graph.du_dst,
        du_var=graph.du_var,
        du_width=graph.du_width,
        er_dst=graph.er_dst,
        er_var=graph.er_var,
        er_width=graph.er_width,
        ord_src=graph.ord_src,
        ord_dst=graph.ord_dst,
        topo_order=graph.topo_order,
        topo_pos=graph.topo_pos,
    )


def _load_cache(cache_path: Path) -> InstructionGraph:
    with np.load(cache_path, allow_pickle=False) as data:
        if int(data["cache_version"][0]) != CACHE_VERSION:
            raise ValueError(f"{cache_path}: stale cache version, delete and rebuild")
        return InstructionGraph(
            instructions=int(data["instructions"][0]),
            variables=int(data["variables"][0]),
            op=data["op"],
            opcode_names=json.loads(str(data["opcode_names"][0])),
            width=data["width"],
            state_write=data["state_write"],
            atom=data["atom"],
            comb_loop_atom=data["comb_loop_atom"],
            du_src=data["du_src"],
            du_dst=data["du_dst"],
            du_var=data["du_var"],
            du_width=data["du_width"],
            er_dst=data["er_dst"],
            er_var=data["er_var"],
            er_width=data["er_width"],
            ord_src=data["ord_src"],
            ord_dst=data["ord_dst"],
            topo_order=data["topo_order"],
            topo_pos=data["topo_pos"],
        )
