#!/usr/bin/env python3

"""P0 array guard probe (docs/27). Two phases per target array population.

Phase 2 (PRE-reg-to-mem graph — the shape ingest produces / the matcher
rejected): write-structure classification per sampled element.

Write-model handled (both observed in XiangShan):
  - explicit-enable form: updateCond = or(branch guards), nextValue =
    mux-chain whose final fallback (self read) is dead -> whole-element
    write; classify the updateCond guard DNF.
  - always-write RMW form: updateCond = 1, nextValue encodes
    set/clear/keep in a mux/boolean chain -> extract (select, data)
    branches from the chain (1-bit boolean forms
    and(not(X),Y) == mux(X,0,Y) are rewritten), classify each branch
    guard; self read in a branch *data* is a true read-modify-write (C).

Guard classes (per branch guard DNF, address equation = eq(sig, elem_idx),
with eq-to-0 recognized as eq(x,0)/not(reduceOr(x))/reduceNor(x)/not(x) for
elem_idx==0 when x is a known address signal of the same array):
  - A: every addressed term carries exactly one address equation (any
    number of distinct address signals = multi write ports, encodable);
    whole-element data. "+clr": extra element-independent clear/fill terms
    (map to kMemoryFill / ordered const writes).
  - B: every addressed term carries exactly two address equations on a
    consistent signal pair (bankSel, ptr) -> address expression encodable.
  - C: non-all-ones mask, or true read-modify-write data, or unextractable
    next chain mixing old value (field-level partial update).
  - V: lane-clear terms — element-indexed conditions with no address
    equation (per-lane vector update, e.g. commit clears entries[i].valid).
  - D: anything else (DNF overflow, negated composites, cross-address eqs,
    anti-address terms, inconsistent address shape).
  - F: no address equation at all (pure fill/broadcast).

Phase 1 (E1 post-stats graph — final exploded cost): per field cluster:
registers, write/read ports, mask/reset-event ports, write-side fanin cone
(in-module and global, bounded at register/memory read ports + constants),
read-side shape (select-tree vs parallel/direct users, tree op counts).

Usage:

    p0_array_guard_probe.py --pre /tmp/grh_pre_index.pkl \
        --pre-consts /tmp/grh_pre_consts.pkl --e1 /tmp/grh_e1_index.pkl \
        --json /tmp/p0_guard.json [--only Rob.robEntries,MSHR_64] [--sample 6]
"""

from __future__ import annotations

import argparse
import json
import pickle
import re
import time
from collections import Counter, defaultdict

IDX_RUN = re.compile(r"_\d+")

BOUNDARY_KINDS = {
    "kRegisterReadPort",
    "kMemoryReadPort",
    "kConstant",
    "kRegister",
    "kMemory",
    "kInputPort",
    "kInput",
}
OR_KINDS = {"kOr", "kLogicOr"}
AND_KINDS = {"kAnd", "kLogicAnd"}
NOT_KINDS = {"kNot", "kLogicNot"}
REG_READ_KINDS = {"kRegisterReadPort", "kMemoryReadPort"}

MAX_TERMS = 512
MAX_TERM_LEAVES = 256

TARGETS = [
    ("Rob.robEntries", "Rob.sv", "$rob$robEntries_"),
    ("Rob.other_arrays", "Rob.sv", None),
    ("RenameBuffer", "RenameBuffer.sv", None),
    ("MSHR_64", "MSHR_64.sv", None),
    ("MSHR", "MSHR.sv", None),
    ("DataModule__64entry_16", "DataModule__64entry_16.sv", None),
    ("DataModule__64entry", "DataModule__64entry.sv", None),
    ("WriteBuffer_12", "WriteBuffer_12.sv", None),
    ("WriteBuffer_4", "WriteBuffer_4.sv", None),
    ("SQData8Module", "SQData8Module.sv", None),
    ("Ftq", "Ftq.sv", None),
    ("LoadQueueReplay", "LoadQueueReplay.sv", None),
    ("StoreQueue", "StoreQueue.sv", None),
    ("BusyTable.int", "BusyTable.sv", None),
    ("BusyTable.fp", "BusyTable_1.sv", None),
    ("SbufferData", "SbufferData.sv", None),
    ("OthersEntry_238", "OthersEntry_238.sv", None),
    ("OthersEntry_78", "OthersEntry_78.sv", None),
    ("IntFile", "IntFile.sv", None),
    ("MissEntry", "MissEntry.sv", None),
    ("AheadBtb", "AheadBtb.sv", None),
    ("TLBFA.itlb", "TLBFA.sv", None),
    ("LogPerfEndpoint", "LogPerfEndpoint.sv", None),
]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def split_sym(sym: str):
    if "$" in sym:
        path, _, name = sym.rpartition("$")
        return path, name
    return "", sym


def cluster_elem_indices(mems):
    """Element index per member = the numeric run (over the whole symbol,
    path included) with the largest distinct-value count across members."""
    runs = {s: [int(m.group(0)[1:]) for m in IDX_RUN.finditer(s)] for s in mems}
    n_runs = max((len(r) for r in runs.values()), default=0)
    best_pos, best_key = None, None
    for pos in range(n_runs):
        vals = {r[pos] for r in runs.values() if len(r) > pos}
        if len(vals) <= 1:
            continue
        key = (len(vals), -pos)
        if best_key is None or key > best_key:
            best_key, best_pos = key, pos
    out = {}
    for s, r in runs.items():
        out[s] = r[best_pos] if best_pos is not None and len(r) > best_pos else -1
    return out


# ----------------------------------------------------------------- pre graph


class PreGraph:
    def __init__(self, path: str, consts_path: str):
        log(f"loading pre index {path}")
        with open(path, "rb") as fh:
            self.ops, self.defs, self.meta = pickle.load(fh)
        with open(consts_path, "rb") as fh:
            self.consts = pickle.load(fh)
        log(f"pre ops={len(self.ops)} consts={len(self.consts)}")

    def const_value(self, value_sym: str):
        op = self.defs.get(value_sym)
        if op is None or self.ops[op][0] != "kConstant":
            return None
        return self.consts.get(op)

    def is_const(self, value_sym: str, want: int) -> bool:
        return self.const_value(value_sym) == want

    def dnf(self, value: str, depth: int = 0):
        """OR-of-ANDs expansion -> (terms, error).

        leaf = ('eq', signal_value, const) | ('eq_nc', value) |
               ('reg', target, value) | ('const1',) | ('const0',) |
               ('neg', leaf) | ('op', kind, value)
        """
        if depth > 40:
            return None, "deep"
        op_sym = self.defs.get(value)
        if op_sym is None:
            return [[("op", "free", value)]], None
        kind, ins, _outs = self.ops[op_sym]
        if kind in REG_READ_KINDS:
            return [[("reg", self.meta[op_sym][1], value)]], None
        if kind == "kConstant":
            v = self.consts.get(op_sym)
            if v == 1:
                return [[("const1",)]], None
            if v == 0:
                return [[("const0",)]], None
            return [[("op", "kConstant", value)]], None
        if kind in OR_KINDS:
            terms = []
            for iv in ins:
                sub, err = self.dnf(iv, depth + 1)
                if err:
                    return None, err
                terms.extend(sub)
                if len(terms) > MAX_TERMS:
                    return None, "overflow"
            return terms, None
        if kind in AND_KINDS:
            terms = [[]]
            for iv in ins:
                sub, err = self.dnf(iv, depth + 1)
                if err:
                    return None, err
                terms = [t + s for t in terms for s in sub]
                if len(terms) > MAX_TERMS or any(len(t) > MAX_TERM_LEAVES for t in terms):
                    return None, "overflow"
            return terms, None
        if kind in NOT_KINDS and len(ins) == 1:
            return self.dnf_neg(ins[0], depth + 1)
        if kind == "kReduceNor" and len(ins) == 1:
            return [[("eq", ins[0], 0)]], None
        if kind == "kReduceOr" and len(ins) == 1:
            cat_sym = self.defs.get(ins[0])
            if cat_sym and self.ops[cat_sym][0] == "kConcat":
                terms = []
                for iv in self.ops[cat_sym][1]:
                    sub, err = self.dnf(iv, depth + 1)
                    if err:
                        return None, err
                    terms.extend(sub)
                    if len(terms) > MAX_TERMS:
                        return None, "overflow"
                return terms, None
            return [[("op", kind, value)]], None
        if kind == "kEq" and len(ins) == 2:
            c0 = self.const_value(ins[0])
            c1 = self.const_value(ins[1])
            if c1 is not None and c0 is None:
                return [[("eq", ins[0], c1)]], None
            if c0 is not None and c1 is None:
                return [[("eq", ins[1], c0)]], None
            return [[("eq_nc", value)]], None
        return [[("op", kind, value)]], None

    def dnf_neg(self, value: str, depth: int):
        """DNF of NOT(value) with De Morgan through and/or."""
        op_sym = self.defs.get(value)
        kind = self.ops[op_sym][0] if op_sym else None
        if kind in AND_KINDS or kind in OR_KINDS:
            ins = self.ops[op_sym][1]
            parts = []
            for iv in ins:
                t, err = self.dnf_neg(iv, depth + 1)
                if err:
                    return None, err
                parts.append(t)
            if kind in AND_KINDS:  # not(and) = or(not...)
                terms = []
                for t in parts:
                    terms.extend(t)
                    if len(terms) > MAX_TERMS:
                        return None, "overflow"
                return terms, None
            terms = [[]]  # not(or) = and(not...)
            for t in parts:
                terms = [x + y for x in terms for y in t]
                if len(terms) > MAX_TERMS:
                    return None, "overflow"
            return terms, None
        if kind in NOT_KINDS and len(self.ops[op_sym][1]) == 1:
            # double negation
            return self.dnf(self.ops[op_sym][1][0], depth + 1)
        if kind == "kReduceOr" and len(self.ops[op_sym][1]) == 1:
            return [[("eq", self.ops[op_sym][1][0], 0)]], None
        if kind == "kReduceNor" and len(self.ops[op_sym][1]) == 1:
            # not(x==0): a disequality — opaque condition
            return [[("neg", ("eq", self.ops[op_sym][1][0], 0))]], None
        leaf_terms, err = self.dnf(value, depth)
        if err:
            return None, err
        if len(leaf_terms) == 1 and len(leaf_terms[0]) == 1:
            l = leaf_terms[0][0]
            if l[0] == "const1":
                return [[("const0",)]], None
            if l[0] == "const0":
                return [[("const1",)]], None
            return [[("neg", l)]], None
        return None, "neg_composite"


def classify_path(pre: PreGraph, path, elem_idx: int, addr_signals):
    """-> (cls, reason, detail). cls in A/B/D/V/F ('+clr' suffix possible).

    path: list of (value, polarity) literals ANDed together (+1/-1).
    addr_signals: value syms known to be address signals of this array
    (collected from positive eq leaves of other elements) — used to recognize
    eq-to-0 encodings (not(x), not(reduceOr(x))) when elem_idx == 0.
    """
    terms = [[]]
    for value, pol in path:
        if pol > 0:
            sub, err = pre.dnf(value)
        else:
            sub, err = pre.dnf_neg(value, 0)
        if err:
            return "D", f"dnf_{err}", None
        terms = [t + s for t in terms for s in sub]
        if len(terms) > MAX_TERMS or any(len(t) > MAX_TERM_LEAVES for t in terms):
            return "D", "dnf_overflow", None
    cleaned = []
    for term in terms:
        if any(l[0] == "const0" for l in term):
            continue
        cleaned.append([l for l in term if l[0] != "const1"])
    if not cleaned:
        return "D", "cond_const0", None

    def addr_leaf(l):
        """-> signal value if l is an address equation for elem_idx."""
        if l[0] == "eq" and l[2] == elem_idx:
            return l[1]
        if elem_idx == 0 and l[0] == "neg":
            inner = l[1]
            if inner[0] in ("reg", "op") and inner[-1] in addr_signals:
                return inner[-1]
        return None

    addressed = []
    clears = []
    negs = 0
    xeq = 0
    for term in cleaned:
        sigs = set()
        term_xeq = 0
        term_anti = 0
        for l in term:
            sig = addr_leaf(l)
            if sig is not None:
                sigs.add(sig)
            elif l[0] == "eq":
                term_xeq += 1
            elif l[0] == "neg":
                negs += 1
                inner = l[1]
                if inner[0] == "eq" and len(inner) >= 3 and inner[2] == elem_idx:
                    term_anti += 1
        if sigs:
            addressed.append((sigs, term_xeq))
            xeq += term_xeq
        elif term_anti:
            return "D", "anti_addr_term", None
        else:
            clears.append(term)
    union_sigs = set().union(*(s for s, _x in addressed)) if addressed else set()
    detail = {
        "terms": len(cleaned),
        "addr_terms": len(addressed),
        "clear_terms": len(clears),
        "addr_sigs": len(union_sigs),
        "xeq": xeq,
        "negs": negs,
    }
    if not addressed:
        return "F", "no_addr", detail
    if any(tx > 0 for _s, tx in addressed):
        return "D", "cross_addr_eq", detail
    counts = {len(s) for s, _x in addressed}
    if counts == {1}:
        base = "A"
    elif counts == {2} and len(union_sigs) == 2:
        base = "B"
    else:
        return "D", f"addr_sig_shape_{sorted(counts)}_union{len(union_sigs)}", detail
    lane = False
    clear_targets = set()
    for term in clears:
        for l in term:
            if l[0] == "reg":
                clear_targets.add(l[1])
                if IDX_RUN.search(l[1]):
                    lane = True
    detail["clear_lane"] = lane
    detail["clear_targets"] = sorted(clear_targets)[:8]
    if lane:
        return "V", "lane_clear", detail
    if clears:
        return base + "+clr", "clear_terms", detail
    return base, "ok", detail


def classify_guard(pre: PreGraph, cond_value: str, elem_idx: int, addr_signals):
    return classify_path(pre, [(cond_value, 1)], elem_idx, addr_signals)


def self_read_count(pre: PreGraph, value: str, member: str, cap=200_000):
    """Number of kRegisterReadPort(target==member) in value's cone (capped)."""
    seen = set()
    stack = [value]
    n = 0
    while stack:
        v = stack.pop()
        op_sym = pre.defs.get(v)
        if op_sym is None or op_sym in seen:
            continue
        seen.add(op_sym)
        if len(seen) > cap:
            return n, True
        kind, ins, _o = pre.ops[op_sym]
        if kind == "kRegisterReadPort":
            if pre.meta[op_sym][1] == member:
                n += 1
            continue
        if kind == "kMemoryReadPort" or not ins:
            continue
        stack.extend(ins)
    return n, False


MAX_BRANCHES = 512


def decompose_next(pre: PreGraph, value: str, member: str, width: int, path=(), depth: int = 0):
    """Decompose nextValue into (branches, keeps_old, err).

    branches: [(path, data)] — path = tuple of (value, polarity, origin)
    literals; origin 'mux' = mux-chain select descent (negative ones encode
    branch priority only), 'bool' = 1-bit boolean rewrite (semantic).
    data = graph value, or the strings 'ZERO'/'ONE' (1-bit consts).
    keeps_old: True if the old value can survive.
    Handles kMux chains of any width and, for 1-bit registers, the boolean
    encodings and(a,b)==mux(a,b,0), or(a,b)==mux(a,1,b).
    """
    if depth > 96:
        return [], True, "deep"
    op_sym = pre.defs.get(value)
    if op_sym is None:
        return [(path, value)], False, None
    kind, ins, _o = pre.ops[op_sym]
    if kind == "kRegisterReadPort":
        if pre.meta[op_sym][1] == member:
            return [], True, None
        return [(path, value)], False, None
    if kind == "kConstant":
        v = pre.consts.get(op_sym)
        if width == 1 and v == 0:
            return [(path, "ZERO")], False, None
        if width == 1 and v == 1:
            return [(path, "ONE")], False, None
        return [(path, value)], False, None
    if kind == "kMux" and len(ins) == 3:
        b1, k1, e1 = decompose_next(pre, ins[1], member, width, path + ((ins[0], 1, "mux"),), depth + 1)
        b2, k2, e2 = decompose_next(pre, ins[2], member, width, path + ((ins[0], -1, "mux"),), depth + 1)
        if e1 or e2:
            return [], True, e1 or e2
        branches = b1 + b2
        if len(branches) > MAX_BRANCHES:
            return [], True, "branch_overflow"
        return branches, k1 or k2, None
    if width == 1 and kind in AND_KINDS and len(ins) == 2:
        # and(a,b) == mux(a, b, 0)
        b1, k1, e1 = decompose_next(pre, ins[1], member, width, path + ((ins[0], 1, "bool"),), depth + 1)
        if e1:
            return [], True, e1
        branches = b1 + [(path + ((ins[0], -1, "bool"),), "ZERO")]
        if len(branches) > MAX_BRANCHES:
            return [], True, "branch_overflow"
        return branches, k1, None
    if width == 1 and kind in OR_KINDS and len(ins) == 2:
        # or(a,b) == mux(a, 1, b)
        b1, k1, e1 = decompose_next(pre, ins[1], member, width, path + ((ins[0], -1, "bool"),), depth + 1)
        if e1:
            return [], True, e1
        branches = [(path + ((ins[0], 1, "bool"),), "ONE")] + b1
        if len(branches) > MAX_BRANCHES:
            return [], True, "branch_overflow"
        return branches, k1, None
    # opaque data expression (may still contain self reads — checked by caller)
    return [(path, value)], False, None


def branch_class_path(path):
    """Guard literals for classification: all positive literals plus the
    semantic negative 'bool' ones; negative mux literals are branch priority
    and would only blow up the DNF."""
    return [(v, pol) for (v, pol, origin) in path if pol > 0 or origin == "bool"]


# ------------------------------------------------------------- E1 helpers


def cone_size(ops, defs, meta, roots, count_loc=None, cap=2_000_000):
    """Backward BFS from root values; boundary ops not counted. If count_loc
    is given, only ops with that loc.file basename are counted (traversal
    still passes through)."""
    seen = set()
    counted = 0
    boundary_hits = Counter()
    stack = list(roots)
    while stack:
        v = stack.pop()
        op_sym = defs.get(v)
        if op_sym is None or op_sym in seen:
            continue
        kind, ins, _o = ops[op_sym]
        if kind in BOUNDARY_KINDS or not ins:
            boundary_hits[kind] += 1
            continue
        seen.add(op_sym)
        if count_loc is None or meta[op_sym][0] == count_loc:
            counted += 1
        if len(seen) > cap:
            break
        stack.extend(ins)
    return counted, len(seen), dict(boundary_hits)


def no_member_read(value, ops, defs, meta, members, depth=0, budget=None):
    """True if the cone contains no read of THIS array's members (other
    registers — address pointers etc. — are allowed; they become address
    expressions after memory conversion)."""
    if budget is None:
        budget = [256]
    if budget[0] <= 0 or depth > 12:
        return False
    budget[0] -= 1
    op_sym = defs.get(value)
    if op_sym is None:
        return True
    kind, ins, _o = ops[op_sym]
    if kind in REG_READ_KINDS:
        return meta[op_sym][1] not in members
    if not ins:
        return True
    return all(no_member_read(iv, ops, defs, meta, members, depth + 1, budget) for iv in ins)


TRANSPARENT_KINDS = {"kAssign"}


def effective_users(value, read_users, ops, max_hops=4):
    """Users of value, looking through transparent unary ops (kAssign)."""
    out = []
    frontier = [(value, 0)]
    seen = {value}
    while frontier:
        v, hops = frontier.pop()
        for u in read_users.get(v, ()):
            kind, _i, outs = ops[u]
            if kind in TRANSPARENT_KINDS and hops < max_hops:
                for ov in outs:
                    if ov not in seen:
                        seen.add(ov)
                        frontier.append((ov, hops + 1))
            else:
                out.append(u)
    return out


# ------------------------------------------------------------------- driver


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pre", required=True)
    ap.add_argument("--pre-consts", required=True)
    ap.add_argument("--e1", required=True)
    ap.add_argument("--json", required=True)
    ap.add_argument("--only", default=None)
    ap.add_argument("--sample", type=int, default=6)
    args = ap.parse_args()

    only = set(args.only.split(",")) if args.only else None
    targets = [t for t in TARGETS if only is None or t[0] in only]

    log("loading e1 index")
    with open(args.e1, "rb") as fh:
        e1_ops, e1_defs, e1_meta = pickle.load(fh)
    log(f"e1 ops={len(e1_ops)}")

    populations: dict[str, dict[tuple, list[str]]] = {}
    loc_of_label = {}
    for sym, m in e1_meta.items():
        if e1_ops[sym][0] != "kRegister":
            continue
        loc = m[0]
        for label, locfile, pathsub in targets:
            if loc != locfile:
                continue
            if pathsub is not None and pathsub not in sym:
                continue
            if label == "Rob.other_arrays" and "$rob$robEntries_" in sym:
                continue
            path, name = split_sym(sym)
            path_pattern = "$".join(IDX_RUN.sub("_#", c) for c in path.split("$"))
            pattern = IDX_RUN.sub("_#", name)
            fkey = (path_pattern, pattern, m[2])
            populations.setdefault(label, {}).setdefault(fkey, []).append(sym)
            loc_of_label[label] = locfile
            break
    for label in populations:
        nregs = sum(len(v) for v in populations[label].values())
        log(f"target {label}: {nregs} regs in {len(populations[label])} field-clusters")

    member_set = set()
    for fields in populations.values():
        for mems in fields.values():
            member_set.update(mems)
    wports: dict[str, list[str]] = defaultdict(list)
    rports: dict[str, list[str]] = defaultdict(list)
    for sym, (kind, _i, _o) in e1_ops.items():
        if kind == "kRegisterWritePort" or kind == "kRegisterReadPort":
            t = e1_meta[sym][1]
            if t in member_set:
                (wports if kind == "kRegisterWritePort" else rports)[t].append(sym)
    log(f"e1 ports: {sum(len(v) for v in wports.values())} write, "
        f"{sum(len(v) for v in rports.values())} read")

    target_read_values = {}
    for reg, ports in rports.items():
        for p in ports:
            for v in e1_ops[p][2]:
                target_read_values[v] = reg
    tv_set = set(target_read_values)
    read_users: dict[str, list[str]] = defaultdict(list)
    for sym, (kind, ins, _o) in e1_ops.items():
        if not ins:
            continue
        for iv in ins:
            if iv in tv_set:
                read_users[iv].append(sym)
    log(f"e1 read users collected for {len(read_users)} values")

    # ---------------- phase 2: pre-graph guard classification
    pre = PreGraph(args.pre, args.pre_consts)
    pre_wports: dict[str, list[str]] = defaultdict(list)
    for sym, (kind, _i, _o) in pre.ops.items():
        if kind == "kRegisterWritePort":
            t = pre.meta[sym][1]
            if t in member_set:
                pre_wports[t].append(sym)
    log(f"pre write ports for targets: {sum(len(v) for v in pre_wports.values())}")

    guard_rows: dict[tuple, dict] = {}
    for label, fields in populations.items():
        for fkey, mems in fields.items():
            idx_map = cluster_elem_indices(mems)
            mems_sorted = sorted(mems, key=lambda s: idx_map[s])
            n = len(mems_sorted)
            if n <= args.sample:
                picks = mems_sorted
            else:
                step = n / args.sample
                picks = [mems_sorted[int(i * step)] for i in range(args.sample)]
                picks.append(mems_sorted[-1])
            # pass 1: collect address-signal candidates from positive eq leaves
            addr_signals = set()
            raw = {}
            for m in picks:
                for wp in pre_wports.get(m, ()):
                    ins = pre.ops[wp][1]
                    terms, err = pre.dnf(ins[0])
                    raw[(m, wp)] = (terms, err)
                    if err:
                        continue
                    for term in terms or ():
                        for l in term:
                            if l[0] == "eq" and l[2] == idx_map[m] and l[2] != 0:
                                addr_signals.add(l[1])
            elem_rows = []
            cls_hist = Counter()
            clear_sigs = Counter()
            for m in picks:
                width = pre.meta[m][2]
                ports = pre_wports.get(m, ())
                port_rows = []
                elem_cls = None
                rank = {"D": 6, "V": 5, "C": 4, "B": 3, "A": 2, "F": 1}

                def absorb(c):
                    nonlocal elem_cls
                    base = c.split("+")[0]
                    if elem_cls is None or rank.get(base, 6) > rank.get(elem_cls, 6):
                        elem_cls = base

                for wp in ports:
                    ins = pre.ops[wp][1]
                    events = list(ins[3:])
                    is_reset_event = any(e != "clock" for e in events)
                    mask_v = ins[2] if len(ins) >= 3 else None
                    mask_const = pre.const_value(mask_v) if mask_v else None
                    mask_all_ones = mask_const is not None and mask_const == (1 << width) - 1
                    cond_is_one = pre.is_const(ins[0], 1)
                    branches, keeps_old, derr = decompose_next(pre, ins[1], m, width)
                    prow = {
                        "reset_event": is_reset_event,
                        "mask_all_ones": mask_all_ones,
                        "cond_is_one": cond_is_one,
                        "keeps_old": keeps_old,
                        "n_branches": len(branches),
                    }
                    if derr:
                        prow["decompose_err"] = derr
                    if not mask_all_ones:
                        prow["cls_eff"] = "C"
                        prow["reason_eff"] = "masked_write"
                        absorb("C")
                        port_rows.append(prow)
                        continue
                    if derr:
                        prow["cls_eff"] = "D"
                        prow["reason_eff"] = f"decompose_{derr}"
                        absorb("D")
                        port_rows.append(prow)
                        continue
                    if cond_is_one and not keeps_old:
                        # unconditional rewrite every cycle (no keep path):
                        # every lane takes a branch/default each cycle — a
                        # vector lane update, not a single-address write.
                        absorb("V")
                        prow["always_rewrite"] = True
                    # data RMW check: self read inside a branch data value
                    rmw = 0
                    for bpath, data in branches:
                        if data in ("ZERO", "ONE"):
                            continue
                        cnt, _cap = self_read_count(pre, data, m)
                        rmw += cnt
                    brows = []
                    if cond_is_one:
                        # always-write form (valid-style): the write structure
                        # lives in the branch selects.
                        for bpath, data in branches:
                            cpath = branch_class_path(bpath)
                            bcls, breason, bdet = classify_path(pre, cpath, idx_map[m], addr_signals)
                            if bdet and bcls.endswith("+clr"):
                                clear_sigs[(bdet["clear_terms"], tuple(bdet.get("clear_targets", ())))] += 1
                            brows.append({"cls": bcls, "reason": breason, "const_data": data in ("ZERO", "ONE")})
                            absorb(bcls)
                        if not keeps_old:
                            absorb("V")
                            prow["always_rewrite"] = True
                    else:
                        # explicit-enable form: the updateCond IS the write
                        # enable structure (multi-OR-term = multi write port).
                        pcls, reason, detail = classify_guard(pre, ins[0], idx_map[m], addr_signals)
                        if detail and pcls.endswith("+clr"):
                            clear_sigs[(detail["clear_terms"], tuple(detail.get("clear_targets", ())))] += 1
                        absorb(pcls)
                        prow["guard"] = {"cls": pcls, "reason": reason}
                        if detail is not None:
                            prow["guard"]["detail"] = detail
                        # informational: branch-select classes (data selection
                        # among ports; complexity here stays combinational)
                        for bpath, data in branches[:4]:
                            cpath = branch_class_path(bpath)
                            bcls, breason, _bd = classify_path(pre, cpath, idx_map[m], addr_signals)
                            brows.append({"cls": bcls, "reason": breason, "const_data": data in ("ZERO", "ONE")})
                    prow["branches"] = brows[:8]
                    if rmw:
                        absorb("C")
                        prow["rmw_data"] = rmw
                    prow["cls_eff"] = elem_cls
                    prow["reason_eff"] = "branch_analysis"
                    port_rows.append(prow)
                cls_hist[elem_cls or "?"] += 1
                elem_rows.append(
                    {
                        "member": split_sym(m)[1],
                        "idx": idx_map[m],
                        "n_ports": len(ports),
                        "cls": elem_cls,
                        "ports": port_rows[:3],
                    }
                )
            guard_rows[(label,) + fkey] = {
                "sampled": len(picks),
                "cls_hist": dict(cls_hist),
                "clear_sig_variants": len(clear_sigs),
                "elements": elem_rows,
            }
        agg = Counter()
        for k, r in guard_rows.items():
            if k[0] == label:
                for c, cnt in r["cls_hist"].items():
                    agg[c] += cnt
        log(f"phase2 {label}: element classes {dict(agg)}")
        with open(args.json + ".g", "w") as fh:
            json.dump({str(k): v for k, v in guard_rows.items()}, fh, ensure_ascii=False)

    # ---------------- phase 1: E1 footprint + read-side
    results = {}
    for label, fields in populations.items():
        t0 = time.time()
        field_rows = []
        tot = Counter()
        target_roots: list[str] = []
        target_tree_ops: set[str] = set()
        loc = loc_of_label.get(label)
        for fkey, mems in sorted(fields.items(), key=lambda kv: -len(kv[1])):
            ppat, pat, width = fkey
            idx_map = cluster_elem_indices(mems)
            mems_sorted = sorted(mems, key=lambda s: idx_map[s])
            n = len(mems_sorted)
            member_set_f = set(mems_sorted)
            roots = []
            wp_count = 0
            rp_count = 0
            nonconst_mask = 0
            reset_ports = 0
            for m in mems_sorted:
                for wp in wports.get(m, ()):
                    wp_count += 1
                    ins = e1_ops[wp][1]
                    if len(ins) >= 2:
                        roots.extend([ins[0], ins[1]])
                        target_roots.extend([ins[0], ins[1]])
                    if len(ins) >= 3:
                        mv = ins[2]
                        md = e1_defs.get(mv)
                        if not (md and e1_ops[md][0] == "kConstant"):
                            nonconst_mask += 1
                    if any(e != "clock" for e in ins[3:]):
                        reset_ports += 1
                rp_count += len(rports.get(m, ()))
            cone_ops, cone_seen, boundary = cone_size(e1_ops, e1_defs, e1_meta, roots, count_loc=loc)
            reads_select = 0
            reads_parallel = 0
            parallel_kinds = Counter()
            tree_ops: set[str] = set()
            for m in mems_sorted:
                for rp in rports.get(m, ()):
                    for v in e1_ops[rp][2]:
                        for u in effective_users(v, read_users, e1_ops):
                            ukind, uins, _uo = e1_ops[u]
                            is_select = False
                            if ukind in ("kAnd", "kLogicAnd"):
                                others = [x for x in uins if x != v]
                                if others and all(
                                    no_member_read(x, e1_ops, e1_defs, e1_meta, member_set_f)
                                    for x in others
                                ):
                                    is_select = True
                                    stack = [u] + list(others)
                                    or_frontier = [u]
                                    while stack:
                                        xv = stack.pop()
                                        xo = e1_defs.get(xv) if xv in e1_defs else None
                                        if xo is None or xo in tree_ops:
                                            continue
                                        xk, xi, _xout = e1_ops[xo]
                                        tree_ops.add(xo)
                                        if xk not in REG_READ_KINDS:
                                            stack.extend(xi)
                                    while or_frontier:
                                        cur = or_frontier.pop()
                                        for pv in e1_ops[cur][2]:
                                            for pu in effective_users(pv, read_users, e1_ops):
                                                pk, _pi, _po = e1_ops[pu]
                                                if pk in ("kOr", "kLogicOr") and pu not in tree_ops:
                                                    tree_ops.add(pu)
                                                    or_frontier.append(pu)
                            elif ukind == "kMux" and len(uins) == 3 and v in (uins[1], uins[2]):
                                if no_member_read(uins[0], e1_ops, e1_defs, e1_meta, member_set_f):
                                    is_select = True
                                    tree_ops.add(u)
                                    frontier = [u]
                                    while frontier:
                                        cur = frontier.pop()
                                        for pv in e1_ops[cur][2]:
                                            for pu in effective_users(pv, read_users, e1_ops):
                                                pk, pi, _po = e1_ops[pu]
                                                if pk == "kMux" and len(pi) == 3 and pu not in tree_ops:
                                                    if no_member_read(pi[0], e1_ops, e1_defs, e1_meta, member_set_f):
                                                        tree_ops.add(pu)
                                                        frontier.append(pu)
                            if is_select:
                                reads_select += 1
                            else:
                                reads_parallel += 1
                                parallel_kinds[ukind] += 1
            grow = guard_rows.get((label,) + fkey, {})
            field_rows.append(
                {
                    "path": ppat,
                    "pattern": pat,
                    "width": width,
                    "members": n,
                    "write_ports": wp_count,
                    "read_ports": rp_count,
                    "nonconst_mask_ports": nonconst_mask,
                    "reset_event_ports": reset_ports,
                    "write_cone_ops": cone_ops,
                    "write_cone_seen": cone_seen,
                    "boundary": boundary,
                    "reads_select": reads_select,
                    "reads_parallel": reads_parallel,
                    "parallel_kinds": dict(parallel_kinds),
                    "select_tree_ops": len(tree_ops),
                    "guard": {k: v for k, v in grow.items() if k != "elements"},
                }
            )
            tot["members"] += n
            tot["write_cone_ops_fieldsum"] += cone_ops
            tot["select_tree_ops"] += len(tree_ops)
            tot["reads_select"] += reads_select
            tot["reads_parallel"] += reads_parallel
            target_tree_ops |= tree_ops
        union_cone, union_seen, _ub = cone_size(e1_ops, e1_defs, e1_meta, target_roots, count_loc=loc)
        union_cone_all, _us, _ub2 = cone_size(e1_ops, e1_defs, e1_meta, target_roots, count_loc=None)
        tot["write_cone_ops_union"] = union_cone
        tot["write_cone_ops_union_all_locs"] = union_cone_all
        tot["select_tree_ops_union"] = len(target_tree_ops)
        results[label] = {"fields": field_rows, "totals": dict(tot)}
        log(f"{label}: {len(field_rows)} fields, members={tot['members']} "
            f"write_cone(union,{loc})={tot['write_cone_ops_union']} "
            f"select_trees(union)={tot['select_tree_ops_union']} "
            f"reads sel/par={tot['reads_select']}/{tot['reads_parallel']} ({time.time()-t0:.0f}s)")
        with open(args.json + ".partial", "w") as fh:
            json.dump(results, fh, ensure_ascii=False)

    out = {"footprint": results, "guards": {json.dumps(list(k), ensure_ascii=False): v for k, v in guard_rows.items()}}
    with open(args.json, "w") as fh:
        json.dump(out, fh, ensure_ascii=False)
    log(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
