#!/usr/bin/env python3
"""NO00027 paired-register update-cone micro structural diff (gsim x GrhSIM IR).

Pairs gsim NODE_REG_SRC anchors with GrhSIM non-`__event_` logic states
(two-phase M-name matching reused from NO00020), extracts each side's register
update cone (GrhSIM: full backward cone of the regWrite data operand truncated
at state.read/input.read/memRead; gsim: REG_DST assignTree expansion with
named-reference inlining and leaf truncation at REG_SRC/NODE_INP/memory
ports/constants), computes canonical structural signatures on both sides with
the pre-registered normalizations (OP_PAD transparent, OP_WHEN and nested
mux/prioritySelect chains flattened to the same branch-sequence form, constants
keyed by (value, width), commutative child sorting, static slice/index
parameter decoding), matches them per strict member pair, classifies one-sided
excess (M-xo / M-xg) and joins deterministic dynamic counters closed-form.

Metrics (pre-registered in pdocs/NO00027-grhsim-ir-paired-cone-diff-20260928.md):
  M-pair        anchor bit-weighted coverage, both sides (gate >= 80%);
  M-cone-cover  paired-cone union execs/cycle over all-model compute
                execs/cycle (static op coverage reported alongside);
  M-leaf        cone leaf signature correspondence, both directions;
  M-match       structural signature match rates, distinct (primary) and
                occurrence-weighted (secondary), both directions;
  M-xo          GrhSIM-only excess ops by exhaustive priority-ordered classes:
                owner_(reg-to-mem)/(packed)/(events), width_norm,
                scalarization, event_bookkeeping, other_semantic;
  M-xg          gsim-only excess enodes (informational): node_ref_unpaired,
                pad, when_reshape, memory_port, other;
  M-xo-dyn      decision metric: execs/cycle of unmatched GrhSIM cone ops NOT
                in an owner bucket, over compute execs/cycle.

Dynamic shares are global deduplicated unions times unit body fires over guest
cycles; never a sum over per-group cones (NO00023 11.1x lesson).

Gates: G1a input identities (sha256 final==dynamic checkpoint, pre==final
semantic fingerprints, GrhSIM counts closure, gsim non-memory node count),
G1b dynamic-arm identity (endpoints + two-run fires/totals key-equal),
G2 determinism (--g2-reference byte compare excluding gates.G2), G3 dynamic
closures (counter sites vs generated sources, grp_pub/grp_fire, compute
closure, unit coverage, cone-op counter coverage), G4 fixed-seed sample
recheck with an independent reimplementation, G5 excess classification
closure + structural explanation payload, G6 coverage validity.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import gc
import json
import random
import re
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchmark_grhsim_ir import digest  # noqa: E402
from grhsim_bit_update_census import check_dynamic  # noqa: E402
from grhsim_bucket_dyn_price import attribute_op_modules, BUCKET_MODULES  # noqa: E402
from grhsim_declared_pack_census import declared_names  # noqa: E402
from grhsim_gsim_module_compare import (  # noqa: E402
    check_grhsim_counts, match_anchor_sets, match_report, normalize_name,
)
from grhsim_residual_write_cones import (  # noqa: E402
    READS, cone, semantic_fingerprints, unit_index,
)

REG_WRITE_KIND = "core.state.regWrite"
CONST_KIND = "core.compute.constant"
COMMUTATIVE = {"and", "or", "xor", "add", "mul", "eq", "ne"}

# Explicit per-op crosswalk (op name granularity, not bucket granularity).
# Ops absent from the table are unmatched by construction: their signatures
# carry a side-tagged class and can never equal a counterpart signature.
GSIM_CLASS = {
    "OP_AND": "and", "OP_OR": "or", "OP_XOR": "xor", "OP_NOT": "not",
    "OP_ANDR": "reduceAnd", "OP_ORR": "reduceOr", "OP_XORR": "reduceXor",
    "OP_ADD": "add", "OP_SUB": "sub", "OP_MUL": "mul", "OP_DIV": "div",
    "OP_REM": "mod",
    "OP_EQ": "eq", "OP_NEQ": "ne", "OP_LT": "lt", "OP_LEQ": "le",
    "OP_GT": "gt", "OP_GEQ": "ge",
    "OP_CAT": "concat",
}
GRH_CLASS = {
    "core.compute.and": "and", "core.compute.or": "or",
    "core.compute.xor": "xor", "core.compute.not": "not",
    "core.compute.logicAnd": "logicAnd", "core.compute.logicOr": "logicOr",
    "core.compute.logicNot": "logicNot",
    "core.compute.reduceAnd": "reduceAnd", "core.compute.reduceOr": "reduceOr",
    "core.compute.reduceXor": "reduceXor",
    "core.compute.reduceNor": "reduceNor",
    "core.compute.reduceNand": "reduceNand",
    "core.compute.reduceXnor": "reduceXnor",
    "core.compute.add": "add", "core.compute.sub": "sub",
    "core.compute.mul": "mul", "core.compute.div": "div",
    "core.compute.mod": "mod",
    "core.compute.eq": "eq", "core.compute.ne": "ne", "core.compute.lt": "lt",
    "core.compute.le": "le", "core.compute.gt": "gt", "core.compute.ge": "ge",
    "core.compute.concat": "concat",
}

M_XO_CLASSES = ["owner_(reg-to-mem)", "owner_(packed)", "owner_(events)",
                "width_norm", "scalarization", "event_bookkeeping",
                "other_semantic"]
M_XG_CLASSES = ["node_ref_unpaired", "pad", "when_reshape", "memory_port",
                "other"]

EXPECTED_GSIM_NON_MEMORY = 2708079
EXPECTED_ENDPOINT = (240349, 99996, 100001, "0x80000c0c")

_CONST_RE = re.compile(r"^(?:(\d+))?'([sS]?)([bBdDhHoO])([0-9a-fA-FxzXZ?_-]+)$")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def peak_rss_gb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 << 20)


def parse_const_literal(text, width):
    """Verilog literal -> (residue, width); None when not a 2-state literal."""
    match = _CONST_RE.fullmatch(str(text).strip())
    if not match:
        return None
    w = int(match[1]) if match[1] else width
    base = {"b": 2, "o": 8, "d": 10, "h": 16}[match[3].lower()]
    digits = match[4].replace("_", "").replace("?", "x")
    neg = digits.startswith("-")
    digits = digits.lstrip("-")
    if not digits or "x" in digits.lower() or "z" in digits.lower():
        return None
    value = int(digits, base)
    if neg:
        value = -value
    if w > 0:
        value %= 1 << w
    return value, w


def parse_gsim_int(text, width):
    """gsim OP_INT strVal is a decimal string (possibly negative)."""
    try:
        value = int(text)
    except ValueError:
        try:
            value = int(text, 0)
        except ValueError:
            return None
    if width > 0:
        value %= 1 << width
    return value, width


# ---------------------------------------------------------------------------
# GrhSIM side loading (mirrors grhsim_gsim_module_compare.analyze_grhsim decode)
# ---------------------------------------------------------------------------


def load_grhsim_final(path):
    """Load the final checkpoint once; keep padded id-indexed arrays only."""
    log(f"grhsim: loading {path}")
    model = json.loads(Path(path).read_bytes())
    strings = model["strings"]
    counts_ok, counts_checks = full_counts_check(model)
    fingerprints = semantic_fingerprints(model)
    declared = declared_names(model)
    types = {row[0]: row for row in model["types"]}

    op_module, _value_named_module, _owner, aux = attribute_op_modules(model)

    n_states = len(model["states"])
    state_name = aux["state_name"]
    state_width = [0] * (n_states + 1)
    state_is_array = [False] * (n_states + 1)
    state_origin = [0] * (n_states + 1)
    for row in model["states"]:
        sid, type_idx = row[0], row[2]
        trow = types[type_idx]
        state_is_array[sid] = trow[2] == "array"
        state_width[sid] = trow[3] if trow[2] == "logic" else 0
        if len(row) > 3:
            state_origin[sid] = row[3]

    n_values = len(model["values"])
    value_name = aux["value_name"]
    value_width = [0] * (n_values + 1)
    value_sign = [False] * (n_values + 1)
    for row in model["values"]:
        vid, type_idx = row[0], row[1]
        trow = types[type_idx]
        value_width[vid] = trow[3] if trow[2] == "logic" else 0
        value_sign[vid] = trow[4] if trow[2] == "logic" else False

    operations = {op[0]: op for op in model["operations"]}
    kinds = {oid: strings[op[1] - 1] for oid, op in operations.items()}
    producer = {}
    writes = defaultdict(list)
    latch_only = 0
    for oid, op in operations.items():
        for vid in op[5]:
            if vid in producer:
                raise ValueError("duplicate value producer")
            producer[vid] = oid
        kind = kinds[oid]
        if kind in (REG_WRITE_KIND, "core.state.latchWrite"):
            if not op[6] or op[6][0][0] != "state" or len(op[4]) < 2:
                raise ValueError("invalid regWrite")
            if kind == REG_WRITE_KIND:
                writes[op[6][0][1]].append(op[4][1])
            else:
                latch_only += 1

    inputs = [strings[row[1] - 1] for row in model["inputs"]]
    kept = {
        "strings": strings,
        "origins": {row[0]: row for row in model.get("origins", [])},
        "mappings": model["mappings"],
        "counts_checks": counts_checks,
        "counts_ok": counts_ok,
        "fingerprints": fingerprints,
        "declared": declared,
        "state_name": state_name,
        "state_width": state_width,
        "state_is_array": state_is_array,
        "state_origin": state_origin,
        "value_name": value_name,
        "value_width": value_width,
        "value_sign": value_sign,
        "operations": operations,
        "kinds": kinds,
        "op_operands": aux["op_operands"],
        "op_refs": aux["op_refs"],
        "op_module": op_module,
        "producer": producer,
        "writes": writes,
        "latch_only_writes": latch_only,
        "inputs": inputs,
        "n_ops": aux["n_ops"],
        "counts": dict(model["counts"]),
    }
    del model
    log(f"grhsim: states={n_states} values={n_values} ops={kept['n_ops']} "
        f"peak RSS {peak_rss_gb():.1f} GiB")
    return kept


# ---------------------------------------------------------------------------
# gsim side loading: retain compact assignTrees, release the raw JSON tree
# ---------------------------------------------------------------------------


class GsimGraph:
    def __init__(self):
        self.nodes = {}          # name -> [type, width, trees|None]
        self.reg_src = []        # (name, width, dst|None)
        self.memories = []
        self.inputs = []
        self.type_counts = Counter()
        self.total_enodes = 0
        self.stats = Counter()
        self._intern = {}


def load_gsim(path):
    """Parse the PreCoarsen export and reduce it to compact interned trees."""
    log(f"gsim: loading {path}")
    payload = json.loads(Path(path).read_bytes())
    nodes = payload["nodes"]
    del payload
    log(f"gsim: parsed {len(nodes)} node records, reducing to compact trees "
        f"(peak RSS {peak_rss_gb():.1f} GiB)")
    graph = GsimGraph()
    intern = graph._intern

    def sym(text):
        got = intern.get(text)
        if got is None:
            intern[text] = text
            return text
        return got

    op_ids = {}

    for node in nodes:
        name = sym(node["name"])
        ntype = sym(node["type"])
        graph.type_counts[ntype] += 1
        width = node.get("width", 0)
        raw_trees = node.get("assignTrees") or ()
        keep = (ntype not in ("NODE_REG_SRC", "NODE_MEMORY")
                and "MPORT" not in name)
        trees = []
        dst_ref = None
        for tree in raw_trees:
            flat = tree["nodes"]
            root = tree.get("root", -1)
            compact = []
            for enode in flat:
                op = enode["op"]
                oid = op_ids.get(op)
                if oid is None:
                    oid = len(op_ids) + 1
                    op_ids[op] = oid
                    sym(op)
                ref = enode.get("node")
                compact.append((oid, enode.get("width", 0),
                                1 if enode.get("sign") else 0,
                                tuple(enode.get("children") or ()),
                                sym(ref) if ref else None,
                                enode.get("strVal"),
                                tuple(enode["values"]) if enode.get("values") else None))
                graph.total_enodes += 1
            if ntype == "NODE_REG_SRC" and dst_ref is None \
                    and 0 <= root < len(compact):
                ref = compact[root][4]
                if ref and ref != name:
                    dst_ref = ref
            if keep:
                trees.append((root, tuple(compact)))
        graph.nodes[name] = [ntype, width, tuple(trees) if keep else None]
        if ntype == "NODE_REG_SRC":
            graph.reg_src.append((name, width, dst_ref))
        elif ntype == "NODE_MEMORY":
            graph.memories.append(name)
        elif ntype == "NODE_INP":
            graph.inputs.append(name)
    del nodes
    graph.op_names = {v: k for k, v in op_ids.items()}
    graph.non_memory = len(graph.nodes) - graph.type_counts.get("NODE_MEMORY", 0)
    log(f"gsim: reduced to {len(graph.nodes)} nodes, "
        f"{graph.total_enodes} enodes scanned, peak RSS {peak_rss_gb():.1f} GiB")
    return graph


# ---------------------------------------------------------------------------
# Canonical signature engines
# ---------------------------------------------------------------------------

class Signatures:
    """Collision-free hash-consed DAG; children are integer signature ids.

    This avoids recursively hashing expanded trees at every shared fanout.
    The key contains width and operation parameters, not a textual hash.
    """

    def __init__(self):
        self.index = {}
        self.keys = [None]

    def add(self, tag, width, params=(), children=()):
        key = (tag, width, tuple(params), tuple(children))
        result = self.index.get(key)
        if result is None:
            result = len(self.keys)
            self.index[key] = result
            self.keys.append(key)
        return result

    def node(self, tag, width, children, params=()):
        if tag in COMMUTATIVE:
            if params and len(params) == len(children) and all(p in (0, 1) for p in params):
                ordered = sorted(zip(children, params))
                children, params = zip(*ordered)
            else:
                children = sorted(children)
        return self.add(tag, width, params, children)

    def select(self, width, conditions, arms, default):
        branches = []
        for condition, arm in zip(conditions, arms):
            branches.extend((condition, arm))
        tail = self.keys[default]
        if tail[0] == "when" and tail[1] == width:
            branches.extend(tail[3])
        else:
            branches.append(default)
        return self.add("when", width, (), branches)

    def explain(self, sid, depth=2):
        tag, width, params, children = self.keys[sid]
        out = {"op": tag, "width": width}
        if params:
            out["params"] = params
        if children and depth:
            out["args"] = [self.explain(c, depth - 1) for c in children[:5]]
        return out


def member_pairs(groups):
    """Keep full suffixes and widths. A chunk group is not a shared leaf."""
    pairs, gkeys, rkeys = [], {}, {}
    remainder = Counter()
    for group in groups:
        left = defaultdict(list)
        right = defaultdict(list)
        for name, width in group["gsim"]:
            left[(normalize_name(name), width)].append(name)
        for name, width in group["grhsim"]:
            right[(normalize_name(name), width)].append(name)
        used_g, used_r = set(), set()
        for key in sorted(left.keys() & right.keys()):
            # Normalization collisions remain ambiguous, never arbitrarily zip.
            if len(left[key]) != 1 or len(right[key]) != 1:
                remainder["ambiguous_keys"] += 1
                continue
            gn, rn = left[key][0], right[key][0]
            pair_id = len(pairs)
            pairs.append({"id": pair_id, "key": key[0], "width": key[1],
                          "gsim": gn, "grhsim": rn, "group": group["key"]})
            gkeys[gn] = pair_id
            rkeys[rn] = pair_id
            used_g.add(gn)
            used_r.add(rn)
        remainder["gsim_members"] += len(group["gsim"]) - len(used_g)
        remainder["grhsim_members"] += len(group["grhsim"]) - len(used_r)
        remainder["gsim_bits"] += sum(w for n, w in group["gsim"] if n not in used_g)
        remainder["grhsim_bits"] += sum(w for n, w in group["grhsim"] if n not in used_r)
    return pairs, gkeys, rkeys, dict(remainder)


class GrhSignatures:
    def __init__(self, model, keys, pool):
        self.model, self.keys, self.pool = model, keys, pool
        self.memo = {}
        self.active = set()
        self.stats = Counter()

    def dependencies(self, oid):
        if self.model["kinds"][oid] in READS:
            return []
        return [self.model["producer"][v] for v in self.model["operations"][oid][4]]

    def sig(self, root):
        stack = [(root, False)]
        while stack:
            oid, done = stack.pop()
            if oid in self.memo:
                continue
            if done:
                children = [self.memo[d] for d in self.dependencies(oid)]
                self.memo[oid] = self.normalize(oid, children)
                self.active.remove(oid)
            else:
                if oid in self.active:
                    raise ValueError(f"GrhSIM combinational cycle at {oid}")
                self.active.add(oid)
                stack.append((oid, True))
                stack.extend((d, False) for d in reversed(self.dependencies(oid))
                             if d not in self.memo)
        return self.memo[root]

    def normalize(self, oid, children):
        m, pool = self.model, self.pool
        op = m["operations"][oid]
        kind = m["kinds"][oid]
        width = m["value_width"][op[5][0]] if op[5] else 0
        params = {m["strings"][p[0] - 1]: p[2] for p in op[7]}
        if kind in READS:
            if kind == "core.input.read":
                ids = [r[1] for r in op[6] if r[0] == "input"]
                name = m["inputs"][ids[0] - 1] if len(ids) == 1 else f"?{oid}"
                return pool.add("input", width, (normalize_name(name),))
            ids = [r[1] for r in op[6] if r[0] == "state"]
            if len(ids) != 1:
                return pool.add("grh_leaf", width, (oid,))
            sid = ids[0]
            name = m["state_name"][sid]
            if kind == "core.state.memRead" or m["state_is_array"][sid]:
                # A memory name alone cannot identify an addressed read. Keep
                # this an opaque, side-specific boundary, never a false match.
                return pool.add("grh_mem", width, (name, oid))
            if name in self.keys:
                return pool.add("reg", width, (self.keys[name],))
            return pool.add("grh_reg", width, (name,))
        if kind == CONST_KIND:
            parsed = parse_const_literal(params.get("constValue"), width)
            if parsed is not None:
                return pool.add("const", width, (parsed[0],))
            self.stats["unparsed_constant"] += 1
            return pool.add("grh_const", width, (str(params.get("constValue")),))
        if kind == "core.compute.mux":
            return pool.select(width, children[:1], children[1:2], children[2])
        if kind == "core.compute.prioritySelect":
            n = (len(children) - 1) // 2
            return pool.select(width, children[:n], children[n:2*n], children[-1])
        if kind == "core.compute.sliceStatic":
            return pool.node("slice", width, children,
                             (int(params["sliceStart"]), int(params["sliceEnd"])))
        if kind in ("core.compute.sliceDynamic", "core.compute.sliceArray"):
            tag = "slice_dyn" if kind.endswith("sliceDynamic") else "index_dyn"
            return pool.node(tag, width, children, (int(params.get("sliceWidth", width)),))
        if kind in ("core.compute.shl", "core.compute.lshr", "core.compute.ashr"):
            amount = pool.keys[children[1]]
            if amount[0] == "const":
                return pool.node(kind.split(".")[-1], width, children[:1], (amount[2][0],))
            return pool.node(kind.split(".")[-1], width, children)
        if kind == "core.compute.replicate":
            return pool.node("replicate", width, children, (int(params["rep"]),))
        tag = GRH_CLASS.get(kind)
        if tag:
            # Signedness of operands governs comparisons, division, extension.
            signs = tuple(int(m["value_sign"][v]) for v in op[4])
            semantic_sign = signs if any(signs) else ()
            return pool.node(tag, width, children, semantic_sign)
        return pool.node("grh:" + kind, width, children,
                         (json.dumps(params, sort_keys=True),))


class GsimSignatures:
    """Iterative expansion of named references and RHS-reachable enodes."""

    def __init__(self, graph, keys, pool):
        self.graph, self.keys, self.pool = graph, keys, pool
        self.graph.op_names[-1] = "OP_ASSIGN_SEQUENCE"
        self.memo = {}
        self.stats = Counter()
        self.cycle_edges = set()

    def row(self, location):
        name, tid, index = location
        if tid == -1:
            return (-1, self.graph.nodes[name][1], 0, (), None, None, ())
        return self.graph.nodes[name][2][tid][1][index]

    def root(self, name):
        info = self.graph.nodes.get(name)
        if info is None or not info[2]:
            return None
        if len(info[2]) != 1:
            return (name, -1, -1)
        return (name, 0, info[2][0][0])

    def leaf(self, name, width):
        info = self.graph.nodes.get(name)
        if info is None:
            return self.pool.add("gsim_missing", width, (name,))
        kind, _width, trees = info
        if kind == "NODE_REG_SRC":
            if name in self.keys:
                return self.pool.add("reg", width, (self.keys[name],))
            return self.pool.add("gsim_reg", width, (name,))
        if kind == "NODE_INP":
            return self.pool.add("input", width, (normalize_name(name),))
        if kind == "NODE_MEMORY" or "MPORT" in name:
            return self.pool.add("gsim_mem", width, (name,))
        if not trees:
            return self.pool.add("gsim_opaque", width, (name,))
        return None

    def dependencies(self, location):
        name, tid, index = location
        if tid == -1:
            return [(name, i, tree[0]) for i, tree in enumerate(self.graph.nodes[name][2])]
        row = self.row(location)
        op = self.graph.op_names[row[0]]
        if op == "OP_EMPTY" and row[4] is not None:
            if self.leaf(row[4], row[1]) is not None:
                return []
            ref = self.root(row[4])
            return [ref] + [(name, tid, c) for c in row[3]]
        return [(name, tid, c) for c in row[3]]

    def sig(self, root):
        active = set()
        stack = [(root, False)]
        while stack:
            loc, done = stack.pop()
            if loc in self.memo:
                continue
            deps = self.dependencies(loc)
            if done:
                child = [self.pool.add("gsim_cycle", self.row(d)[1], (d[0],))
                         if (loc, d) in self.cycle_edges else self.memo[d] for d in deps]
                self.memo[loc] = self.normalize(loc, child)
                active.remove(loc)
            else:
                active.add(loc)
                stack.append((loc, True))
                for d in reversed(deps):
                    if d in active:
                        self.cycle_edges.add((loc, d))
                    elif d not in self.memo:
                        stack.append((d, False))
        return self.memo[root]

    def normalize(self, location, child):
        row, pool = self.row(location), self.pool
        op_id, width, sign, children, ref, sval, vals = row
        op = self.graph.op_names[op_id]
        vals = vals or ()
        if op == "OP_ASSIGN_SEQUENCE":
            # Ordered roots preserve last-connect semantics. This virtual key
            # has no counterpart op and is not counted as a stored enode.
            return pool.node("gsim:assign_sequence", width, child)
        if op == "OP_EMPTY" and ref is not None:
            leaf = self.leaf(ref, width)
            if leaf is not None:
                if children:
                    # Index into a boundary is opaque unless it is a memory
                    # port already represented by this exact named port.
                    return pool.add("gsim_indexed_leaf", width, (ref, location))
                return leaf
            base = child[0]
            flat = self.graph.nodes[location[0]][2][location[1]][1]
            for index, marker_id in enumerate(children):
                marker = flat[marker_id]
                marker_op = self.graph.op_names[marker[0]]
                if marker_op == "OP_INDEX_INT" and marker[6]:
                    lo = marker[6][0] * width
                    base = pool.node("slice", width, (base,), (lo, lo + width - 1))
                elif marker_op == "OP_INDEX":
                    marker_sig = pool.keys[child[index + 1]]
                    base = pool.node("index_dyn", width, (base,) + marker_sig[3], (width,))
                else:
                    base = pool.node("gsim_index", width, (base, child[index + 1]))
            return base
        if op == "OP_INT":
            parsed = parse_gsim_int(sval or "0", width)
            return pool.add("const", width, (parsed[0],)) if parsed else pool.add("gsim_const", width, (sval,))
        if op == "OP_PAD" and len(child) == 1:
            return child[0]
        if op in ("OP_WHEN", "OP_MUX") and len(child) == 3:
            return pool.select(width, child[:1], child[1:2], child[2])
        if op == "OP_BITS" and len(vals) == 2:
            return pool.node("slice", width, child, (vals[1], vals[0]))
        if op in ("OP_HEAD", "OP_TAIL") and vals:
            flat = self.graph.nodes[location[0]][2][location[1]][1]
            source_width = flat[children[0]][1]
            lo, hi = ((source_width - vals[0], source_width - 1) if op == "OP_HEAD"
                      else (0, source_width - vals[0] - 1))
            return pool.node("slice", width, child, (lo, hi))
        if op in ("OP_SHL", "OP_SHR", "OP_DSHL", "OP_DSHR"):
            tag = "shl" if "SHL" in op else ("ashr" if sign else "lshr")
            return pool.node(tag, width, child, vals if op in ("OP_SHL", "OP_SHR") else ())
        tag = GSIM_CLASS.get(op)
        if tag:
            flat = self.graph.nodes[location[0]][2][location[1]][1]
            signs = tuple(flat[c][2] for c in children)
            return pool.node(tag, width, child, signs if any(signs) else ())
        return pool.node("gsim:" + op, width, child, vals)

    def cone(self, root):
        """Each stored enode once; aliases are transparent, not occurrences."""
        stack, seen, retained = [root], set(), set()
        while stack:
            loc = stack.pop()
            if loc in seen:
                continue
            seen.add(loc)
            row = self.row(loc)
            op = self.graph.op_names[row[0]]
            deps = self.dependencies(loc)
            stack.extend(d for d in deps if (loc, d) not in self.cycle_edges)
            alias = op == "OP_EMPTY" and row[4] is not None and not row[3] and deps
            if not alias and op not in ("OP_INDEX", "OP_INDEX_INT", "OP_ASSIGN_SEQUENCE"):
                retained.add(loc)
        for loc in sorted(retained):
            self.sig(loc)
        return retained


def classify_grh(oid, model):
    """Exhaustive priority taxonomy; bitSelect is a mask merge, not slicing."""
    owner = model["op_module"][oid]
    if owner in BUCKET_MODULES:
        return "owner_" + owner
    kind = model["kinds"][oid].removeprefix("core.compute.")
    if kind in ("assign", "cast", "zext", "sext", "trunc"):
        return "width_norm"
    if kind in ("sliceStatic", "sliceDynamic", "sliceArray", "concat", "replicate"):
        return "scalarization"
    op = model["operations"][oid]
    if any(model["value_name"][v].startswith("__event_") for v in op[4]):
        return "event_bookkeeping"
    if any(r[0] == "state" and model["state_name"][r[1]].startswith("__event_") for r in op[6]):
        return "event_bookkeeping"
    return "other_semantic"


def classify_gsim(location, engine):
    row = engine.row(location)
    op = engine.graph.op_names[row[0]]
    if op == "OP_EMPTY":
        return "memory_port" if row[4] and "MPORT" in row[4] else "node_ref_unpaired"
    if op == "OP_PAD":
        return "pad"
    if op in ("OP_WHEN", "OP_MUX", "OP_RESET"):
        return "when_reshape"
    if op in ("OP_READ_MEM", "OP_WRITE_MEM", "OP_INFER_MEM"):
        return "memory_port"
    return "other"


def independent_grh(oid, model, keys, pool, cache):
    """Separate recursive traversal/normalization for the fixed G4 sample."""
    if oid in cache:
        return cache[oid]
    op = model["operations"][oid]
    kind = model["kinds"][oid].removeprefix("core.compute.")
    width = model["value_width"][op[5][0]] if op[5] else 0
    params = {model["strings"][p[0]-1]: p[2] for p in op[7]}
    def add(tag, params=(), children=()):
        return pool.add(tag, width, params, children)
    if model["kinds"][oid] in READS:
        refs = dict(op[6])
        if "input" in refs:
            result = add("input", (normalize_name(model["inputs"][refs["input"]-1]),))
        else:
            sid = refs["state"]
            name = model["state_name"][sid]
            if kind == "core.state.memRead" or model["state_is_array"][sid]:
                result = add("grh_mem", (name, oid))
            elif name in keys:
                result = add("reg", (keys[name],))
            else:
                result = add("grh_reg", (name,))
    elif kind == "constant":
        constant = parse_const_literal(params.get("constValue"), width)
        result = add("const", (constant[0],)) if constant else add("grh_const", (str(params.get("constValue")),))
    else:
        children = [independent_grh(model["producer"][v], model, keys, pool, cache) for v in op[4]]
        if kind in ("mux", "prioritySelect"):
            n = 1 if kind == "mux" else (len(children)-1)//2
            sequence = [v for pair in zip(children[:n], children[n:2*n]) for v in pair]
            tail = pool.keys[children[-1]]
            sequence.extend(tail[3] if tail[:2] == ("when", width) else [children[-1]])
            result = add("when", children=sequence)
        elif kind == "sliceStatic":
            result = add("slice", (int(params["sliceStart"]), int(params["sliceEnd"])), children)
        elif kind in ("sliceDynamic", "sliceArray"):
            result = add("slice_dyn" if kind == "sliceDynamic" else "index_dyn",
                         (int(params.get("sliceWidth", width)),), children)
        elif kind in ("shl", "lshr", "ashr"):
            amount = pool.keys[children[1]]
            result = add(kind, (amount[2][0],), children[:1]) if amount[0] == "const" else add(kind, children=children)
        elif kind == "replicate":
            result = add("replicate", (int(params["rep"]),), children)
        elif "core.compute." + kind in GRH_CLASS:
            tag = GRH_CLASS["core.compute." + kind]
            signs = tuple(int(model["value_sign"][v]) for v in op[4])
            if tag in COMMUTATIVE:
                ordered = sorted(zip(children, signs))
                children, signs = tuple(x[0] for x in ordered), tuple(x[1] for x in ordered)
            result = add(tag, signs if any(signs) else (), children)
        else:
            result = add("grh:" + model["kinds"][oid], (json.dumps(params, sort_keys=True),), children)
    cache[oid] = result
    return result


def independent_gsim(root, engine):
    """Recursive reference interpreter; fresh caches, no main memo or cones.

    Keys use the same interner for exact comparison. Normalization below is
    deliberately separate; semantic counterexamples are also unit-tested.
    """
    graph, pool, keys = engine.graph, engine.pool, engine.keys
    memo, active, retained = {}, set(), set()

    def visit(loc):
        if loc in memo:
            return memo[loc]
        if loc[1] == -1:
            if loc in active:
                return pool.add("gsim_cycle", graph.nodes[loc[0]][1], (loc[0],))
            active.add(loc)
            args = [visit((loc[0], i, tree[0])) for i, tree in enumerate(graph.nodes[loc[0]][2])]
            result = pool.add("gsim:assign_sequence", graph.nodes[loc[0]][1], (), args)
            active.remove(loc)
            memo[loc] = result
            return result
        row = graph.nodes[loc[0]][2][loc[1]][1][loc[2]]
        op_id, width, sign, children, ref, sval, vals = row
        op = graph.op_names[op_id]
        vals = vals or ()
        if loc in active:
            return pool.add("gsim_cycle", width, (loc[0],))
        active.add(loc)
        flat = graph.nodes[loc[0]][2][loc[1]][1]
        is_alias = False
        def add(tag, params=(), child=()):
            return pool.add(tag, width, params, child)
        if op == "OP_EMPTY" and ref is not None:
            target = graph.nodes.get(ref)
            tag = None
            if target is None:
                tag, parameters = "gsim_missing", (ref,)
            elif target[0] == "NODE_REG_SRC":
                tag, parameters = ("reg", (keys[ref],)) if ref in keys else ("gsim_reg", (ref,))
            elif target[0] == "NODE_INP":
                tag, parameters = "input", (normalize_name(ref),)
            elif target[0] == "NODE_MEMORY" or "MPORT" in ref:
                tag, parameters = "gsim_mem", (ref,)
            elif not target[2]:
                tag, parameters = "gsim_opaque", (ref,)
            if tag:
                result = add("gsim_indexed_leaf", (ref, loc)) if children else add(tag, parameters)
            else:
                target_root = (ref, 0, target[2][0][0]) if len(target[2]) == 1 else (ref, -1, -1)
                base = visit(target_root)
                is_alias = not children
                for c in children:
                    marker = flat[c]
                    marker_sig = visit((loc[0], loc[1], c))
                    marker_op = graph.op_names[marker[0]]
                    if marker_op == "OP_INDEX_INT" and marker[6]:
                        lo = marker[6][0] * width
                        base = add("slice", (lo, lo + width - 1), (base,))
                    elif marker_op == "OP_INDEX":
                        base = add("index_dyn", (width,), (base,) + pool.keys[marker_sig][3])
                    else:
                        base = add("gsim_index", child=(base, marker_sig))
                result = base
        elif op == "OP_INT":
            constant = parse_gsim_int(sval or "0", width)
            result = add("const", (constant[0],)) if constant else add("gsim_const", (sval,))
        else:
            args = [visit((loc[0], loc[1], c)) for c in children]
            if op == "OP_PAD" and len(args) == 1:
                result = args[0]
            elif op in ("OP_WHEN", "OP_MUX") and len(args) == 3:
                tail = pool.keys[args[2]]
                seq = args[:2] + (list(tail[3]) if tail[:2] == ("when", width) else args[2:])
                result = add("when", child=seq)
            elif op == "OP_BITS" and len(vals) == 2:
                result = add("slice", (vals[1], vals[0]), args)
            elif op in ("OP_HEAD", "OP_TAIL") and vals:
                source_width = flat[children[0]][1]
                lo, hi = ((source_width - vals[0], source_width - 1) if op == "OP_HEAD" else (0, source_width - vals[0] - 1))
                result = add("slice", (lo, hi), args)
            elif op in ("OP_SHL", "OP_SHR", "OP_DSHL", "OP_DSHR"):
                tag = "shl" if "SHL" in op else ("ashr" if sign else "lshr")
                result = add(tag, vals if op in ("OP_SHL", "OP_SHR") else (), args)
            elif op in GSIM_CLASS:
                tag = GSIM_CLASS[op]
                signs = tuple(flat[c][2] for c in children)
                if tag in COMMUTATIVE:
                    ordered = sorted(zip(args, signs))
                    args, signs = tuple(x[0] for x in ordered), tuple(x[1] for x in ordered)
                result = add(tag, signs if any(signs) else (), args)
            else:
                result = add("gsim:" + op, vals, args)
        if not is_alias and op not in ("OP_INDEX", "OP_INDEX_INT"):
            retained.add(loc)
        memo[loc] = result
        active.remove(loc)
        return result

    visit(root)
    return retained, {loc: memo[loc] for loc in retained}


def independent_classification(oid, model):
    owner = model["op_module"][oid]
    if owner in ("(reg-to-mem)", "(packed)", "(events)"):
        return "owner_" + owner
    kind = model["kinds"][oid]
    if kind in {"core.compute." + k for k in ("assign", "cast", "zext", "sext", "trunc")}:
        return "width_norm"
    if kind in {"core.compute." + k for k in ("sliceStatic", "sliceDynamic", "sliceArray", "concat", "replicate")}:
        return "scalarization"
    names = [model["value_name"][v] for v in model["operations"][oid][4]]
    names += [model["state_name"][r[1]] for r in model["operations"][oid][6] if r[0] == "state"]
    return "event_bookkeeping" if any(n[:8] == "__event_" for n in names) else "other_semantic"


def cone_reference(roots, model):
    visited = set()
    def visit(value):
        oid = model["producer"][value]
        if oid in visited:
            return
        visited.add(oid)
        if model["kinds"][oid] not in READS:
            for operand in model["operations"][oid][4]:
                visit(operand)
    for root in roots:
        visit(root)
    return visited


def pool_flags(pool):
    """Track unmatched boundaries and unsupported forms without pricing them."""
    flags = [0] * len(pool.keys)
    for sid, key in enumerate(pool.keys[1:], 1):
        tag, _width, _params, children = key
        own = 1 if tag.startswith(("grh_", "gsim_")) else 0
        own |= 2 if tag.startswith(("grh:", "gsim:")) else 0
        for c in children:
            own |= flags[c]
        flags[sid] = own
    return flags


def full_counts_check(model):
    ok, checks = check_grhsim_counts(model)
    # The inherited helper checks only a subset of the counts section.
    actual = {
        "function_arguments": sum(len(f[6]) for f in model["functions"]),
        "parameters": sum(len(o[7]) for o in model["operations"]),
        "init_records": len(model["init"]),
        "init_steps": sum(len(r[1]) for r in model["init"]),
        "init_parameters": sum(len(s[1]) for r in model["init"] for s in r[1]),
        "mapping_parameters": sum(len(m[3]) for m in model["mappings"]),
    }
    for key, value in actual.items():
        checks[key] = {"expected": model["counts"].get(key), "actual": value,
                       "ok": model["counts"].get(key) == value}
    return ok and all(v["ok"] for v in checks.values()), checks


def dynamic_identity(first, second):
    """Compare every serialized counter key, not only fires and two totals."""
    def read(path):
        rows, totals = {}, None
        for line in Path(path).read_text().splitlines():
            if line.startswith("[grhsim-dyn]"):
                # Include all diagnostic fields; timings are a separate prefix.
                if " sn " in line:
                    key = int(re.search(r" sn (\d+)", line)[1])
                    if key in rows:
                        raise ValueError("duplicate dynamic row")
                    rows[key] = line
                elif "totals" in line:
                    if totals is not None:
                        raise ValueError("duplicate totals")
                    totals = line
        if not rows or totals is None:
            raise ValueError("missing complete dynamic counters")
        return rows, totals
    a, b = read(first), read(second)
    if a != b:
        raise ValueError("dynamic counter rows/totals differ")
    return {"rows": len(a[0]), "all_counter_fields_equal": True}


def evidence(oid, model, engine, execs, cycles, pair):
    op = model["operations"][oid]
    m = model
    result = {"op": oid, "kind": m["kinds"][oid],
              "owner": m["op_module"][oid], "pair": pair,
              "execs_per_cycle": execs[oid] / cycles,
              "signature": engine.pool.explain(engine.memo[oid]),
              "result_names": [m["value_name"][v] for v in op[5]],
              "operands": []}
    for v in op[4]:
        prod = m["producer"][v]
        result["operands"].append({"value": v, "op": prod, "kind": m["kinds"][prod],
                                    "name": m["value_name"][v], "width": m["value_width"][v]})
    origin = m["origins"].get(op[3])
    if origin and len(origin) > 6:
        result["source"] = {"file": m["strings"][origin[4]-1] if origin[4] else "",
                             "line": origin[5], "column": origin[6]}
    return result


def analyze_pairs(pairs, grh, graph, grh_engine, gs_engine, execs, cycles, out_dir, sample_n, seed):
    pool = grh_engine.pool
    sid_of = {name: sid for sid, name in enumerate(grh["state_name"]) if sid}
    dst_of = {name: dst for name, _w, dst in graph.reg_src}
    selected = set(random.Random(seed).sample(range(len(pairs)), min(sample_n, len(pairs))))
    sample_checks, sample_errors = [], []
    op_union, g_union, xo, xg, matched_ops = set(), set(), set(), set(), set()
    r_signature_union, g_signature_union = set(), set()
    r_leaf_union, g_leaf_union = set(), set()
    frontier_ops, equal_leaf_ops = set(), set()
    pair_totals = Counter()
    links = Counter()
    first_pair = {}
    per_pair = []
    sample_roots = {}
    leaf_tags = {"reg", "input", "const", "grh_reg", "gsim_reg",
                 "grh_mem", "gsim_mem", "gsim_indexed_leaf", "gsim_missing", "gsim_opaque",
                 "grh_const", "gsim_const", "grh_leaf", "gsim_cycle"}
    for i, pair in enumerate(pairs):
        sid = sid_of[pair["grhsim"]]
        roots = grh["writes"].get(sid, [])
        dst = dst_of.get(pair["gsim"])
        groot = gs_engine.root(dst) if dst else None
        if not roots or groot is None:
            links["no_grh_reg_write" if not roots else "no_unique_gsim_update"] += 1
            rops, glocs = set(), set()
            if roots:
                rops, _ = cone(roots, grh["producer"], grh["operations"], grh["kinds"])
            if groot:
                gs_engine.sig(groot)
                glocs = gs_engine.cone(groot)
        else:
            links["linked"] += 1
            rops, _ = cone(roots, grh["producer"], grh["operations"], grh["kinds"])
            gs_engine.sig(groot)
            glocs = gs_engine.cone(groot)
        rmap = {oid: grh_engine.sig(oid) for oid in sorted(rops)}
        gmap = {loc: gs_engine.memo[loc] for loc in glocs}
        rsigs, gsigs = set(rmap.values()), set(gmap.values())
        shared = rsigs & gsigs
        local_xo = {oid for oid, sig in rmap.items() if sig not in gsigs}
        local_xg = {loc for loc, sig in gmap.items() if sig not in rsigs}
        local_matched = rops - local_xo
        op_union.update(rops)
        g_union.update(glocs)
        xo.update(local_xo)
        xg.update(local_xg)
        matched_ops.update(local_matched)
        r_signature_union.update(rsigs)
        g_signature_union.update(gsigs)
        rleaf = {s for s in rsigs if pool.keys[s][0] in leaf_tags}
        gleaf = {s for s in gsigs if pool.keys[s][0] in leaf_tags}
        r_leaf_union.update(rleaf)
        g_leaf_union.update(gleaf)
        if rleaf == gleaf:
            equal_leaf_ops.update(local_xo)
        for oid in local_xo:
            signature = pool.keys[rmap[oid]]
            if signature[3] and all(child in gsigs for child in signature[3]):
                frontier_ops.add(oid)
        pair_totals.update(r_distinct=len(rsigs), g_distinct=len(gsigs), match_distinct=len(shared),
                           r_occurrence=len(rops), g_occurrence=len(glocs),
                           r_match_occurrence=len(local_matched), g_match_occurrence=len(glocs)-len(local_xg),
                           r_leaves=len(rleaf), g_leaves=len(gleaf), matched_leaves=len(rleaf & gleaf))
        for oid in local_xo:
            first_pair.setdefault(oid, pair["key"])
        per_pair.append({"id": i, "key": pair["key"], "width": pair["width"],
                         "grh_ops": len(rops), "gsim_enodes": len(glocs),
                         "grh_unmatched": len(local_xo), "gsim_unmatched": len(local_xg),
                         "grh_distinct": len(rsigs), "gsim_distinct": len(gsigs),
                         "matched_distinct": len(shared),
                         "unmatched_execs": sum(execs[o] for o in local_xo)})
        if i in selected:
            iv_rops = cone_reference(roots, grh)
            iv_cache = {}
            iv_rmap = {oid: independent_grh(oid, grh, grh_engine.keys, pool, iv_cache) for oid in iv_rops}
            iv_glocs, iv_gmap = independent_gsim(groot, gs_engine) if groot else (set(), {})
            iv_rsigs, iv_gsigs = set(iv_rmap.values()), set(iv_gmap.values())
            errors = []
            if iv_rops != rops or iv_rmap != rmap:
                errors.append("GrhSIM cone/signatures")
            if iv_glocs != glocs or iv_gmap != gmap:
                errors.append("gsim cone/signatures")
            if {o for o, s in iv_rmap.items() if s not in iv_gsigs} != local_xo:
                errors.append("GrhSIM match decisions")
            if {o for o, s in iv_gmap.items() if s not in iv_rsigs} != local_xg:
                errors.append("gsim match decisions")
            if any(classify_grh(o, grh) != independent_classification(o, grh) for o in rops):
                errors.append("classification")
            sample_checks.append({"pair": pair["key"], "grh_ops": len(rops),
                                  "gsim_enodes": len(glocs), "errors": errors})
            sample_errors.extend((pair["key"], e) for e in errors)
            sample_roots[pair["key"]] = {"grhsim": [pool.explain(grh_engine.sig(grh["producer"][r]), 3) for r in roots],
                                               "gsim": pool.explain(gs_engine.memo[groot], 3) if groot else None}
        if (i + 1) % 5000 == 0:
            log(f"paired {i+1}/{len(pairs)}; union {len(op_union)} ops; signatures {len(pool.keys)-1}")
    missing = op_union - execs.keys()
    if missing:
        raise ValueError(f"cone counter coverage missing {len(missing)} ops")
    def fraction(n, d):
        return n / d if d else 0.0
    def price(ids):
        return sum(execs[o] for o in ids)
    compute_total = sum(execs.values())
    classes = {name: {"ops": 0, "execs": 0} for name in M_XO_CLASSES}
    class_kind, class_owner = defaultdict(set), defaultdict(set)
    for oid in sorted(xo):
        category = classify_grh(oid, grh)
        classes[category]["ops"] += 1
        classes[category]["execs"] += execs[oid]
        class_kind[(category, grh["kinds"][oid])].add(oid)
        class_owner[(category, grh["op_module"][oid])].add(oid)
    for row in classes.values():
        row["execs_per_cycle"] = row["execs"] / cycles
        row["share_of_compute"] = row["execs"] / compute_total
    def rank(mapping):
        records = [{"class": key[0], "name": key[1], "ops": len(ids),
                    "execs": price(ids), "execs_per_cycle": price(ids)/cycles} for key, ids in mapping.items()]
        return sorted(records, key=lambda r: (-r["execs"], r["class"], r["name"]))
    ranked_kinds, ranked_owners = rank(class_kind), rank(class_owner)
    explanation = []
    pair_by_key = {pair["key"]: pair for pair in pairs}
    for row in ranked_kinds[:5]:
        ids = class_kind[(row["class"], row["name"])]
        sample = sorted(ids, key=lambda o: (-execs[o], o))[:2]
        samples = []
        for oid in sample:
            entry = evidence(oid, grh, grh_engine, execs, cycles, first_pair[oid])
            pair = pair_by_key[first_pair[oid]]
            sid = sid_of[pair["grhsim"]]
            groot = gs_engine.root(dst_of[pair["gsim"]])
            entry["grhsim_update"] = [pool.explain(grh_engine.sig(grh["producer"][r]), 3)
                                       for r in grh["writes"].get(sid, [])]
            entry["gsim_update"] = pool.explain(gs_engine.memo[groot], 3) if groot else None
            samples.append(entry)
        explanation.append({**row, "samples": samples})
    flags = pool_flags(pool)
    nonbucket = {o for o in xo if not classify_grh(o, grh).startswith("owner_")}
    clean = {o for o in nonbucket if flags[grh_engine.memo[o]] == 0}
    only_unmatched = nonbucket - matched_ops
    frontier = frontier_ops & nonbucket
    frontier_kinds = defaultdict(set)
    for oid in frontier:
        frontier_kinds[(classify_grh(oid, grh), grh["kinds"][oid])].add(oid)
    xg_classes = {name: {"enodes": 0, "signatures": set()} for name in M_XG_CLASSES}
    for loc in sorted(xg):
        row = xg_classes[classify_gsim(loc, gs_engine)]
        row["enodes"] += 1
        row["signatures"].add(gs_engine.memo[loc])
    for row in xg_classes.values():
        row["signatures"] = len(row["signatures"])
    metrics = {
        "M-cone-cover": {"ops": len(op_union), "compute_ops": len(execs),
                           "static_fraction": len(op_union)/len(execs),
                           "execs": price(op_union), "execs_per_cycle": price(op_union)/cycles,
                           "compute_execs": compute_total, "compute_execs_per_cycle": compute_total/cycles,
                           "dynamic_fraction": price(op_union)/compute_total, "gsim_enodes": len(g_union)},
        "M-match": {"pair_totals": dict(pair_totals),
                    "grhsim_distinct_fraction": fraction(pair_totals["match_distinct"], pair_totals["r_distinct"]),
                    "gsim_distinct_fraction": fraction(pair_totals["match_distinct"], pair_totals["g_distinct"]),
                    "grhsim_occurrence_fraction": fraction(pair_totals["r_match_occurrence"], pair_totals["r_occurrence"]),
                    "gsim_occurrence_fraction": fraction(pair_totals["g_match_occurrence"], pair_totals["g_occurrence"]),
                    "global_grh_signatures": len(r_signature_union), "global_gsim_signatures": len(g_signature_union)},
        "M-leaf": {"grhsim_union": len(r_leaf_union), "gsim_union": len(g_leaf_union),
                   "union_intersection": len(r_leaf_union & g_leaf_union),
                   "grhsim_pair_fraction": fraction(pair_totals["matched_leaves"], pair_totals["r_leaves"]),
                   "gsim_pair_fraction": fraction(pair_totals["matched_leaves"], pair_totals["g_leaves"])},
        "M-xo": {"ops": len(xo), "execs": price(xo), "execs_per_cycle": price(xo)/cycles,
                 "classes": classes, "top_kinds": ranked_kinds[:25], "top_owners": ranked_owners[:25]},
        "M-xg": {"enodes": len(xg), "distinct_signatures": len({gs_engine.memo[l] for l in xg}),
                 "classes": xg_classes},
        "M-xo-dyn": {"ops": len(nonbucket), "execs": price(nonbucket),
                      "execs_per_cycle": price(nonbucket)/cycles, "fraction": price(nonbucket)/compute_total,
                      "never_matched_in_any_pair_execs": price(only_unmatched),
                      "fully_anchored_supported_grh_execs": price(clean),
                      "fully_anchored_supported_grh_fraction": price(clean)/compute_total,
                      "other_semantic_fraction": classes["other_semantic"]["share_of_compute"],
                      "equal_leaf_set_ops": len(equal_leaf_ops & nonbucket),
                      "equal_leaf_set_execs": price(equal_leaf_ops & nonbucket),
                      "matched_input_frontier_ops": len(frontier),
                      "matched_input_frontier_execs": price(frontier),
                      "matched_input_frontier_fraction": price(frontier)/compute_total,
                      "frontier_top_kinds": rank(frontier_kinds)[:10],
                      "interpretation": "Executed unmatched representations; not proved removable work or host instructions"},
    }
    g4 = {"pass": len(sample_checks) >= 100 and not sample_errors, "sampled": len(sample_checks),
          "seed": seed, "mismatches": sample_errors, "samples": sample_checks}
    g5 = {"pass": sum(r["ops"] for r in classes.values()) == len(xo) and
                  sum(r["execs"] for r in classes.values()) == price(xo) and
                  sum(r["enodes"] for r in xg_classes.values()) == len(xg) and len(explanation) == 5,
          "static_closure": [sum(r["ops"] for r in classes.values()), len(xo)],
          "dynamic_closure": [sum(r["execs"] for r in classes.values()), price(xo)],
          "gsim_closure": [sum(r["enodes"] for r in xg_classes.values()), len(xg)],
          "explanations": explanation}
    with (out_dir / "pairs.tsv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(per_pair[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(per_pair)
    (out_dir / "sample_roots.json").write_text(json.dumps(sample_roots, sort_keys=True, indent=1) + "\n")
    return metrics, g4, g5, dict(links)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("gsim-json", "grhsim-final", "grhsim-pre", "grhsim-dynamic",
                 "model-dir", "run1", "run2", "out-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--gsim-sha256", required=True)
    parser.add_argument("--sample-verify", type=int, default=100)
    parser.add_argument("--sample-seed", type=int, default=20260928)
    parser.add_argument("--g2-reference", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.out_dir.resolve()
    if not output.is_relative_to(root / "ptmp") or output.exists():
        parser.error("output must be a new directory under repository ptmp")
    if args.sample_verify < 100:
        parser.error("G4 requires at least 100 pairs")
    output.mkdir(parents=True)
    sys.setrecursionlimit(20000)
    start = time.monotonic()
    hashes = {name: digest(getattr(args, name)) for name in
              ("gsim_json", "grhsim_final", "grhsim_dynamic")}
    if hashes["gsim_json"] != args.gsim_sha256 or hashes["grhsim_final"] != hashes["grhsim_dynamic"]:
        raise ValueError("G1a input hashes differ from registered inputs")
    grh = load_grhsim_final(args.grhsim_final)
    log("loading pre-partition for semantic identity gate")
    pre = json.loads(args.grhsim_pre.read_bytes())
    pre_identity = semantic_fingerprints(pre) == grh["fingerprints"]
    pre_strings = pre["strings"] == grh["strings"][:len(pre["strings"])]
    del pre
    gc.collect()
    fires, cycles, dynamic = check_dynamic({"mappings": grh["mappings"]}, args.run1, args.run2, args.model_dir)
    dynamic.update(dynamic_identity(args.run1, args.run2))
    units, owners = unit_index({"mappings": grh["mappings"]})
    execs = {o: fires[u] for o, u in owners.items()}
    graph = load_gsim(args.gsim_json)
    gitems = [(n, w) for n, w, _d in graph.reg_src]
    ritems = [(n, grh["state_width"][sid]) for sid, n in enumerate(grh["state_name"])
              if sid and not grh["state_is_array"][sid] and not n.startswith("__event_")]
    groups, ug, ur = match_anchor_sets(gitems, ritems)
    group_report = match_report(groups, ug, ur, sum(w for n, w in gitems), sum(w for n, w in ritems))
    pairs, gkeys, rkeys, remainders = member_pairs(groups)
    paired_bits = sum(p["width"] for p in pairs)
    pairing = {"groups": len(groups), "group_coverage": group_report["coverage"],
               "pairs": len(pairs), "paired_bits": paired_bits,
               "gsim_total_bits": sum(w for n, w in gitems), "grhsim_total_bits": sum(w for n, w in ritems),
               "gsim_bit_fraction": paired_bits/sum(w for n, w in gitems),
               "grhsim_bit_fraction": paired_bits/sum(w for n, w in ritems),
               "group_members_not_paired": remainders,
               "grhsim_paired_declared": sum(p["grhsim"] in grh["declared"] for p in pairs)}
    pool = Signatures()
    ge, se = GrhSignatures(grh, rkeys, pool), GsimSignatures(graph, gkeys, pool)
    log(f"matching {len(pairs)} strict pairs, {paired_bits} bits")
    metrics, g4, g5, links = analyze_pairs(pairs, grh, graph, ge, se, execs, cycles, output, args.sample_verify, args.sample_seed)
    metrics["M-pair"] = pairing
    gates = {
        "G1a": {"pass": pre_identity and pre_strings and grh["counts_ok"] and graph.non_memory == EXPECTED_GSIM_NON_MEMORY,
                 "hashes": hashes, "pre_semantic_arrays_equal": pre_identity, "pre_strings_prefix_equal": pre_strings,
                 "counts": grh["counts_checks"], "gsim_non_memory": graph.non_memory},
        "G1b": {"pass": True, "endpoint": EXPECTED_ENDPOINT, "counter_rows": dynamic["rows"],
                 "all_counter_fields_equal": True},
        "G3": {"pass": len(units) == len(fires) and sum(execs.values()) == dynamic["compute_execs"],
                **dynamic, "missing_units": len(units - fires.keys()), "orphan_units": len(fires.keys() - units),
                "cone_ops_without_counter": 0},
        "G4": g4, "G5": g5,
        "G6": {"pass": min(pairing["gsim_bit_fraction"], pairing["grhsim_bit_fraction"]) >= .8,
                "cone_dynamic_fraction": metrics["M-cone-cover"]["dynamic_fraction"],
                "scope_limited_below_30_percent": metrics["M-cone-cover"]["dynamic_fraction"] < .3},
    }
    summary = {"schema": 2, "gates": gates, "metrics": metrics, "context": {
        "grh_counts": grh["counts"], "gsim_nodes": len(graph.nodes),
        "gsim_enodes_stored": graph.total_enodes, "gsim_cycle_edges": len(se.cycle_edges),
        "links": links, "signature_count": len(pool.keys)-1,
        "grh_stats": dict(ge.stats), "cycles": cycles, "compute_units": len(units)}}
    if args.g2_reference:
        old = json.loads(args.g2_reference.read_text())
        old["gates"].pop("G2", None)
        equal = json.dumps(old, sort_keys=True) == json.dumps(summary, sort_keys=True)
        artifacts = {name: digest(output / name) == digest(args.g2_reference.parent / name)
                     for name in ("pairs.tsv", "sample_roots.json")}
        gates["G2"] = {"pass": equal and all(artifacts.values()), "summary_equal": equal, "artifacts": artifacts}
    else:
        gates["G2"] = {"pass": None, "note": "pending independent second full run"}
    (output / "summary.json").write_text(json.dumps(summary, sort_keys=True, indent=1) + "\n")
    failures = [k for k, v in gates.items() if v["pass"] is False]
    log(f"done in {time.monotonic()-start:.2f}s; peak RSS {peak_rss_gb():.2f} GiB; failures={failures}")
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
