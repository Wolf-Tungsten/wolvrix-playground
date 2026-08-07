#!/usr/bin/env python3
"""Pass-impact simulation on the split AM compute graph export.

Estimates ge2-node / sum_outdeg reduction from candidate graph rewrites
before implementing them in C++ (compute-partition topic, NO0003 follow-up).

Stages (cumulative):
  S0 baseline         : export as-is
  S1 assign-forward   : assign with a single external operand and only pure
                        consumers is bypassed (approximates the refined
                        assignAlias rule; commit-side consumption is not
                        visible in the compute export, so slightly optimistic)
  S2 logic-unify      : logic_and/logic_or/logic_not with all-1-bit operands
                        and result -> and/or/not
  S3 gvn              : iterative hash-consing over commutative/unary pure ops
  S4 reassoc-gvn      : chain-flattening canonical hash (and/or/xor) + gvn
                        (estimates extra CSE from reassociation)

Operand identity: ("n", producer_node) via def_use, ("x", var) via
external_read. Non-commutative ops are never merged. slice_static carries an
invisible lsb attribute, so it is excluded from merging.
"""

from __future__ import annotations

import json
import sys
import threading
from collections import Counter
from pathlib import Path

import numpy as np

sys.setrecursionlimit(2_000_000)

PATH = Path(sys.argv[1] if len(sys.argv) > 1 else
            "build/xs/am-split-export/named.compute.jsonl")

COMMUTATIVE = {"and", "or", "xor", "xnor", "eq", "ne",
               "logic_and", "logic_or", "and!", "or!"}
UNARY = {"not", "logic_not"}
PURE_OPS = COMMUTATIVE | UNARY | {"mux", "add", "sub", "mul", "div", "mod",
                                  "lt", "le", "gt", "ge", "shl", "shr_dyn",
                                  "shl_dyn", "slice_static", "slice_dynamic",
                                  "concat", "replicate", "assign",
                                  "reduce_and", "reduce_or", "reduce_xor",
                                  "reduce_nand", "reduce_nor", "reduce_xnor",
                                  "mem.read", "array.mux", "array.broadcast",
                                  "array.reduce_or", "array.reduce_and",
                                  "array.reduce_xor", "array.onehot",
                                  "array.reduce_lanes_or",
                                  "array.reduce_lanes_and",
                                  "array.reduce_lanes_xor", "pad", "sext",
                                  "asuint", "assint", "cvt", "slice"}
FLATTENABLE = {"and", "or", "xor"}


def load(path: Path):
    gids, ops, widths = [], [], []
    es, ed = [], []
    rd, rv, rw = [], [], []
    with open(path) as f:
        for line in f:
            line = line.replace('\\"', '"')
            if '"record":"node"' in line:
                r = json.loads(line)
                gids.append(r["id"])
                ops.append(r["opcode"])
                widths.append(r["width"])
            elif '"kind":"def_use"' in line:
                r = json.loads(line)
                es.append(r["src"])
                ed.append(r["dst"])
            elif '"kind":"external_read"' in line:
                r = json.loads(line)
                rd.append(r["dst"])
                rv.append(r["var"])
                rw.append(r["width"])
    gid = np.array(gids, dtype=np.int64)
    lut = np.full(int(gid.max()) + 1, -1, dtype=np.int64)
    lut[gid] = np.arange(gid.size, dtype=np.int64)
    es = np.array(es, dtype=np.int64)
    ed = np.array(ed, dtype=np.int64)
    keep = (lut[es] >= 0) & (lut[ed] >= 0)
    rd = np.array(rd, dtype=np.int64)
    rv = np.array(rv, dtype=np.int64)
    rw = np.array(rw, dtype=np.int64)
    m = rd < lut.size
    rd, rv, rw = rd[m], rv[m], rw[m]
    m = lut[rd] >= 0
    return (ops, np.array(widths, dtype=np.int64),
            lut[es[keep]], lut[ed[keep]], lut[rd[m]], rv[m], rw[m])


class Sim:
    def __init__(self, ops, width, es, ed, rd, rv, rw):
        self.op = list(ops)
        self.width = width.tolist()
        n = len(self.op)
        self.n = n
        # operand lists: node -> list of ("n", src) / ("x", var)
        self.operands: list[list[tuple]] = [[] for _ in range(n)]
        for s, d in zip(es.tolist(), ed.tolist()):
            self.operands[d].append(("n", int(s)))
        for d, v in zip(rd.tolist(), rv.tolist()):
            self.operands[d].append(("x", int(v)))
        self.op_width: list[dict[int, int]] = [dict() for _ in range(n)]
        for s, d in zip(es.tolist(), ed.tolist()):
            pass  # def_use width equals producer result width
        for d, v, w in zip(rd.tolist(), rv.tolist(), rw.tolist()):
            self.op_width[d][("x", int(v)).__hash__()] = int(w)
        self.alive = [True] * n
        self.alias = list(range(n))

    def find(self, x: int) -> int:
        while self.alias[x] != x:
            self.alias[x] = self.alias[self.alias[x]]
            x = self.alias[x]
        return x

    def resolved_operands(self, node: int) -> list[tuple]:
        out = []
        for kind, ref in self.operands[node]:
            if kind == "n":
                out.append(("n", self.find(ref)))
            else:
                out.append(("x", ref))
        return out

    def consumer_count(self) -> np.ndarray:
        cnt = np.zeros(self.n, dtype=np.int64)
        for node in range(self.n):
            if not self.alive[node]:
                continue
            seen = set()
            for kind, ref in self.resolved_operands(node):
                if kind == "n" and self.alive[ref]:
                    seen.add(ref)
            for ref in seen:
                cnt[ref] += 1
        return cnt

    def stats(self, label: str):
        cnt = self.consumer_count()
        ge2 = 0
        sumod = 0
        alive_nodes = 0
        per_op_ge2: Counter = Counter()
        for node in range(self.n):
            if not self.alive[node]:
                continue
            alive_nodes += 1
            od = int(cnt[node])
            sumod += od
            if od >= 2:
                ge2 += 1
                per_op_ge2[self.op[node]] += 1
        print(f"[{label}] alive={alive_nodes} ge2={ge2} sum_outdeg={sumod}",
              flush=True)
        return ge2, sumod, per_op_ge2

    # S1: bypass external-reading assigns with pure-only consumers
    def s1_assign_forward(self):
        consumers: list[list[int]] = [[] for _ in range(self.n)]
        for node in range(self.n):
            if not self.alive[node]:
                continue
            for kind, ref in self.resolved_operands(node):
                if kind == "n" and self.alive[ref]:
                    consumers[ref].append(node)
        killed = 0
        for node in range(self.n):
            if not self.alive[node] or self.op[node] != "assign":
                continue
            ops = self.resolved_operands(node)
            if len(ops) != 1 or ops[0][0] != "x":
                continue
            if any(self.op[c] not in PURE_OPS for c in consumers[node]):
                continue
            # bypass: point every consumer's operand at the external var
            for c in consumers[node]:
                self.operands[c] = [("x", ops[0][1]) if (k == "n" and r == node)
                                    else (k, r) for k, r in self.operands[c]]
            self.alive[node] = False
            killed += 1
        print(f"  s1 killed assigns: {killed}")

    # S2: logic_* -> bitwise on 1-bit
    def s2_logic_unify(self):
        conv = 0
        for node in range(self.n):
            if not self.alive[node]:
                continue
            op = self.op[node]
            if op not in ("logic_and", "logic_or", "logic_not"):
                continue
            if self.width[node] != 1:
                continue
            ok = True
            for kind, ref in self.resolved_operands(node):
                if kind == "n":
                    if not self.alive[ref] or self.width[ref] != 1:
                        ok = False
                        break
                else:
                    if self.op_width[node].get(hash(("x", ref)), 1) != 1:
                        ok = False
                        break
            if not ok:
                continue
            self.op[node] = {"logic_and": "and", "logic_or": "or",
                             "logic_not": "not"}[op]
            conv += 1
        print(f"  s2 unified logic ops: {conv}")

    # S3: iterative GVN over commutative/unary pure ops
    def s3_gvn(self, flatten: bool = False):
        total = 0
        while True:
            merged = self._gvn_round(flatten)
            total += merged
            if merged == 0:
                break
        print(f"  s3 gvn merged (flatten={flatten}): {total}")

    def _key(self, node: int, flatten: bool, memo: dict) -> tuple | None:
        op = self.op[node]
        if op in UNARY:
            ops = self.resolved_operands(node)
            if len(ops) != 1:
                return None
            kind, ref = ops[0]
            sub = self._deep_key(ref, flatten, memo) if kind == "n" else ("x", ref)
            return (op, self.width[node], sub)
        if op in COMMUTATIVE:
            ops = self.resolved_operands(node)
            if len(ops) < 2:
                return None
            subs = []
            for kind, ref in ops:
                if kind == "n":
                    subs.append(self._deep_key(ref, flatten, memo))
                else:
                    subs.append(("x", ref))
            if flatten and op in FLATTENABLE:
                flat = []
                for s in subs:
                    if isinstance(s, tuple) and len(s) == 3 and s[0] == op:
                        flat.extend(s[2])
                    else:
                        flat.append(s)
                subs = flat
            return (op, self.width[node], tuple(sorted(set(subs), key=repr)))
        return None

    def _deep_key(self, node: int, flatten: bool, memo: dict) -> tuple:
        node = self.find(node)
        if not self.alive[node]:
            return ("dead", node)
        if not flatten:
            return ("n", node)
        if node in memo:
            return memo[node]
        key = self._key(node, flatten, memo)
        if key is None:
            key = ("n", node)
        memo[node] = key
        return key

    def _gvn_round(self, flatten: bool) -> int:
        memo: dict = {}
        reps: dict[tuple, int] = {}
        merged = 0
        for node in range(self.n):
            if not self.alive[node]:
                continue
            key = self._key(node, flatten, memo)
            if key is None:
                continue
            found = reps.get(key)
            if found is None:
                reps[key] = node
                continue
            # merge node into representative
            self.alias[node] = found
            self.alive[node] = False
            merged += 1
        return merged


def main() -> int:
    ops, width, es, ed, rd, rv, rw = load(PATH)
    print(f"loaded {len(ops)} nodes")
    sim = Sim(ops, width, es, ed, rd, rv, rw)
    g0, s0, base_op = sim.stats("S0 baseline")
    print("  top ge2 ops:", base_op.most_common(8))
    sim.s1_assign_forward()
    g1, s1, p1 = sim.stats("S1 +assign-forward")
    sim.s2_logic_unify()
    g2, s2, p2 = sim.stats("S2 +logic-unify")
    sim.s3_gvn(flatten=False)
    g3, s3, p3 = sim.stats("S3 +gvn")
    sim.s3_gvn(flatten=True)
    g4, s4, p4 = sim.stats("S4 +reassoc-gvn")
    print("\nper-op ge2 deltas vs baseline (top):")
    ops_all = sorted(set(base_op) | set(p4))
    deltas = sorted(((base_op.get(o, 0) - p4.get(o, 0), o) for o in ops_all),
                    reverse=True)
    for d, o in deltas[:15]:
        print(f"  {o:16s} {base_op.get(o,0):8d} -> {p4.get(o,0):8d} (-{d})")
    print(f"\ngsim reference: ge2=252832 sum_outdeg baseline compare")
    print(f"ge2 path: {g0} -> {g1} -> {g2} -> {g3} -> {g4}")
    return 0


if __name__ == "__main__":
    # deep chains need a large C stack for the recursive flatten hash
    threading.stack_size(1024 * 1024 * 1024)
    worker = threading.Thread(target=lambda: sys.exit(main()))
    worker.start()
    worker.join()
