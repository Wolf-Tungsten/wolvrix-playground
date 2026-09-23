"""Census: complex-subgraph replacement motifs (two-state only).

Motifs:
 1. eq-OR chains -> interval check: or/logicOr trees whose leaves are all
    eq(x, Ci) with common x and distinct constants; foldable iff sorted
    constants form contiguous runs (1 run: le(sub(x,Cmin),k-1) = 2 ops).
 2. ne-AND chains -> outside-interval check (symmetric), plus De Morgan
    variant and(not(eq(x,Ci))...).
 3. same-operand-pair comparison coexistence within one supernode
    (incl. reversed-equivalent duplicates lt(a,b)&gt(b,a)).
 4. mux(c, a+C, a) / mux(c, a, a+C) increment-or-not.
 5. eq/ne(and(x,m), 0|m) bit tests; plus generic eq/ne(X,0) producer histogram.
 6. generic 2-op adjacency scan: (producer kind, op kind) and (op kind,
    consumer kind) top-30, dynamic weighted.

Dynamic weight = act of the op's supernode (sn id == partition id, verified).
Totals: 99.48G dynamic compute ops/run (dyn-analysis.txt), 242G cycles/run.
Mapping conventions follow census_boundary_pack.py:
  payload=mappings[0][-1], partitions=payload[2], op=[id,sid,?,?,operands,
  results,objrefs,params]; constant param=[[name_sid,tag,sv_literal]].
"""
import argparse, json, re, time
from array import array
from collections import Counter, defaultdict
from pathlib import Path

TOTAL_DYN = 99479933605.0
KIND_SUPER = 3
SV_LITERAL = re.compile(r"^(?:(\d+))?'[sS]?([bodhBODH])([0-9a-fA-FxzXZ?_]+)$")
BASES = {"b": 2, "o": 8, "d": 10, "h": 16}
WORDER = {"1": 1, "2": 2, "4": 3, "8": 4, "16": 5, "32": 6, "64": 7, ">64": 8}

def parse_sv(text):
    s = text.strip().replace("_", "")
    m = SV_LITERAL.match(s)
    if m:
        d = m.group(3).lower()
        if any(c in "xz?" for c in d):
            return None
        try:
            return int(d, BASES[m.group(2).lower()])
        except ValueError:
            return None
    try:
        return int(s, 10)
    except ValueError:
        return None

def wb(w):
    for b in (1, 2, 4, 8, 16, 32, 64):
        if w <= b:
            return str(b)
    return ">64"

def kord(s):
    return int(s.lstrip(">").split("-")[0])

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", type=Path, default=Path(
        "ptmp/no00057_semantic_fixpoint_20260922/flow-dyn/xiangshan_grhsim_ir.json"))
    ap.add_argument("--dyn-log", type=Path, default=Path(
        "ptmp/no00057_semantic_fixpoint_20260922/logs_dyn2/xs_wolf_grhsim_no00057_dyn2.log"))
    args = ap.parse_args()

    t0 = time.time()
    model = json.loads(args.model.read_bytes())
    print(f"json load: {time.time()-t0:.1f}s", flush=True)
    strings, types, values, ops = (model["strings"], model["types"],
                                   model["values"], model["operations"])
    partitions = model["mappings"][0][-1][2]
    n_ops, n_values = len(ops), len(values)

    n_types = max(t[0] for t in types)
    t_kind = [""] * (n_types + 1)
    t_width = array("I", [0]) * (n_types + 1)
    t_2s = bytearray(n_types + 1)
    for t in types:
        t_kind[t[0]] = t[2]; t_width[t[0]] = t[3]
        if t[2] == "logic" and t[5] == "2-state":
            t_2s[t[0]] = 1
    v_width = array("I", [0]) * (n_values + 1)
    v_2s = bytearray(n_values + 1)
    for v in values:
        tid = v[1]
        if t_kind[tid] == "logic":
            v_width[v[0]] = t_width[tid]
            if t_2s[tid]:
                v_2s[v[0]] = 1

    max_pid = max(p[0] for p in partitions)
    p_kind = bytearray(max_pid + 1)
    p_parent = array("I", [0]) * (max_pid + 1)
    for p in partitions:
        p_kind[p[0]] = p[2]; p_parent[p[0]] = p[1]
    op_part = array("I", [0]) * (n_ops + 1)
    for p in partitions:
        for oid in p[5]:
            op_part[oid] = p[0]
    resolved_sn = array("I", [0]) * (max_pid + 1)
    for p in partitions:
        cur = p[0]; sn = 0
        while cur:
            if p_kind[cur] == KIND_SUPER:
                sn = cur; break
            cur = p_parent[cur]
        resolved_sn[p[0]] = sn

    producer = array("I", [0]) * (n_values + 1)
    for op in ops:
        for v in op[5]:
            producer[v] = op[0]
    assert ops[0][0] == 1 and ops[-1][0] == n_ops
    consumers = defaultdict(list)
    for op in ops:
        for v in op[4]:
            consumers[v].append(op[0])

    act = {}
    sn_re = re.compile(r"\] sn (\d+) act=(\d+)")
    with open(args.dyn_log) as fh:
        for line in fh:
            m = sn_re.search(line)
            if m:
                act[int(m.group(1))] = int(m.group(2))
    print(f"passes done: {time.time()-t0:.1f}s sn_in_log={len(act)}", flush=True)

    sid_of = {s: i + 1 for i, s in enumerate(strings)}
    def SID(n): return sid_of.get(n, 0)
    ID_CONST, ID_EQ, ID_NE = SID("core.compute.constant"), SID("core.compute.eq"), SID("core.compute.ne")
    ID_LT, ID_LE = SID("core.compute.lt"), SID("core.compute.le")
    ID_GT, ID_GE = SID("core.compute.gt"), SID("core.compute.ge")
    ID_OR, ID_LOR = SID("core.compute.or"), SID("core.compute.logicOr")
    ID_AND, ID_LAND = SID("core.compute.and"), SID("core.compute.logicAnd")
    ID_NOT, ID_LNOT = SID("core.compute.not"), SID("core.compute.logicNot")
    ID_MUX, ID_ADD, ID_SUB = SID("core.compute.mux"), SID("core.compute.add"), SID("core.compute.sub")
    OR_IDS = frozenset(x for x in (ID_OR, ID_LOR) if x)
    AND_IDS = frozenset(x for x in (ID_AND, ID_LAND) if x)
    NOT_IDS = frozenset(x for x in (ID_NOT, ID_LNOT) if x)
    CMP_IDS = (ID_EQ, ID_NE, ID_LT, ID_LE, ID_GT, ID_GE)
    CMP_NAME = {ID_EQ: "eq", ID_NE: "ne", ID_LT: "lt", ID_LE: "le", ID_GT: "gt", ID_GE: "ge"}
    op_sn = array("I", [resolved_sn[op_part[op[0]]] for op in ops])
    def pct(x): return f"{100.0*x/TOTAL_DYN:.4f}%"

    def const_int(v):
        p = producer[v]
        if not p:
            return None
        op = ops[p - 1]
        if op[1] != ID_CONST or len(op[7]) != 1 or not op[5] or not v_2s[op[5][0]]:
            return None
        _n, tag, val = op[7][0]
        if tag == "string":
            return parse_sv(val)
        if tag == "int":
            return val
        if tag == "bool":
            return 1 if val else 0
        return None

    def cmpleaf(v, want_sid):
        """(x, c) if v is produced by want_sid(x, const), two-state; else None."""
        p = producer[v]
        if not p:
            return None
        op = ops[p - 1]
        if op[1] != want_sid or len(op[4]) != 2 or len(op[5]) != 1 or not v_2s[op[5][0]]:
            return None
        a, b = op[4]
        ca, cb = const_int(a), const_int(b)
        if ca is not None and cb is None:
            return (b, ca)
        if cb is not None and ca is None:
            return (a, cb)
        return None

    # ---- motifs 1+2: maximal tree flatten, no claiming; dedupe by op id ----
    def chain_census(tree_ids, leaf_sid, label):
        chains = []
        n_trees = 0
        for op in ops:
            oid = op[0]
            if op[1] not in tree_ids or len(op[5]) != 1 or not v_2s[op[5][0]]:
                continue
            if any(ops[c - 1][1] in tree_ids for c in consumers.get(op[5][0], ())):
                continue
            n_trees += 1
            stack = [oid]; nodes = []; leaves = []
            while stack:
                o2 = stack.pop(); nodes.append(o2)
                for v in ops[o2 - 1][4]:
                    p = producer[v]
                    if p and ops[p - 1][1] in tree_ids and v_2s[v] and len(ops[p - 1][5]) == 1:
                        stack.append(p)
                    else:
                        leaves.append(v)
            infos = [cmpleaf(v, leaf_sid) for v in leaves]
            if any(i is None for i in infos):
                continue
            xs = {i[0] for i in infos}
            if len(xs) != 1:
                continue
            x = infos[0][0]; w = v_width[x]
            if not v_2s[x] or w == 0 or w > 64:
                continue
            mask = (1 << w) - 1
            ks = sorted({c & mask for _x, c in infos})
            runs = 1 + sum(1 for i in range(1, len(ks)) if ks[i] - ks[i - 1] != 1)
            leaf_ops = {producer[v] for v in leaves}
            shared = sum(1 for v in leaves if len(consumers.get(v, ())) > 1)
            sns = {op_sn[n - 1] for n in nodes} | {op_sn[p2 - 1] for p2 in leaf_ops}
            chains.append(dict(root=oid, sn=op_sn[oid - 1], act=act.get(op_sn[oid - 1], 0),
                               k=len(leaves), nodes=len(nodes), ops=len(leaves) + len(nodes),
                               w=w, runs=runs, shared=shared, same_sn=len(sns) == 1,
                               allops=nodes + list(leaf_ops), ks=ks))
        uniq = set()
        for c in chains:
            uniq.update(c["allops"])
        udyn = sum(act.get(op_sn[o - 1], 0) for o in uniq)
        khist = Counter(str(c["k"]) if c["k"] <= 8 else ("9-16" if c["k"] <= 16 else
                        ("17-32" if c["k"] <= 32 else ">32")) for c in chains)
        whist = Counter(wb(c["w"]) for c in chains)
        rhist = Counter(str(c["runs"]) if c["runs"] <= 3 else ">3" for c in chains)
        print(f"\n== {label} ==")
        print(f"rooted trees={n_trees} chains={len(chains)} unique-ops={len(uniq)} "
              f"dyn={udyn} ({pct(udyn)})")
        print(f"k hist: {dict(sorted(khist.items(), key=lambda kv: kord(kv[0])))}")
        print(f"x width hist: {dict(sorted(whist.items(), key=lambda kv: WORDER[kv[0]]))}")
        print(f"runs hist (1=contiguous): {dict(sorted(rhist.items(), key=lambda kv: kord(kv[0])))}")
        ss = [c for c in chains if c["same_sn"]]
        print(f"same-supernode chains: {len(ss)} dyn={sum(c['ops']*c['act'] for c in ss)} "
              f"({pct(sum(c['ops']*c['act'] for c in ss))})")
        for rmax, name in ((1, "contiguous->2ops"), (3, "<=3runs")):
            save = save_dyn = save_ss = 0
            sel = [c for c in chains if c["runs"] <= rmax]
            for c in sel:
                new = 2 if c["runs"] == 1 else 3 * c["runs"] - 1
                s = c["nodes"] + (c["k"] - c["shared"]) - new
                if s > 0:
                    save += s; save_dyn += s * c["act"]
                    if c["same_sn"]:
                        save_ss += s * c["act"]
            print(f"savings[{name}]: chains={len(sel)} static-saved={save} dyn-saved={save_dyn} "
                  f"({pct(save_dyn)}) same-sn dyn-saved={save_ss} ({pct(save_ss)})")
        fr = sum(1 for c in chains if c["w"] <= 20 and len(c["ks"]) == (1 << c["w"]))
        print(f"full-range chains (const-fold residue): {fr}")
        chains.sort(key=lambda c: -c["ops"] * c["act"])
        for c in chains[:12]:
            ksh = ",".join(hex(v) for v in c["ks"][:6]) + ("..." if len(c["ks"]) > 6 else "")
            print(f"  root={c['root']} sn={c['sn']} act={c['act']} k={c['k']} w={c['w']} "
                  f"runs={c['runs']} ops={c['ops']} shared={c['shared']} same_sn={c['same_sn']} "
                  f"dyn={c['ops']*c['act']} consts=[{ksh}]")
        return chains

    ch1 = chain_census(OR_IDS, ID_EQ, "[1] eq-OR chains -> interval check")
    ch2 = chain_census(AND_IDS, ID_NE, "[2] ne-AND chains -> outside-interval")

    # De Morgan variant: and-tree leaves are not/logicNot(eq(x,Ci))
    dm = dm_dyn = 0
    for op in ops:
        oid = op[0]
        if op[1] not in AND_IDS or len(op[5]) != 1 or not v_2s[op[5][0]]:
            continue
        if any(ops[c - 1][1] in AND_IDS for c in consumers.get(op[5][0], ())):
            continue
        stack = [oid]; nodes = []; leaves = []
        while stack:
            o2 = stack.pop(); nodes.append(o2)
            for v in ops[o2 - 1][4]:
                p = producer[v]
                if p and ops[p - 1][1] in AND_IDS and v_2s[v] and len(ops[p - 1][5]) == 1:
                    stack.append(p)
                else:
                    leaves.append(v)
        infos = []
        ok = True
        for v in leaves:
            p = producer[v]
            if not p or ops[p - 1][1] not in NOT_IDS or len(ops[p - 1][4]) != 1:
                ok = False; break
            inner = cmpleaf(ops[p - 1][4][0], ID_EQ)
            if inner is None:
                ok = False; break
            infos.append(inner)
        if ok and infos and len({i[0] for i in infos}) == 1:
            dm += 1
            dm_dyn += (len(leaves) + len(nodes)) * act.get(op_sn[oid - 1], 0)
    print(f"\n[2b] De Morgan and(not(eq(x,Ci))...) chains={dm} dyn={dm_dyn} ({pct(dm_dyn)})")

    # ---- motif 3 ----
    print("\n== [3] same-pair comparison coexistence (same supernode) ==")
    pair_kinds = defaultdict(set)
    cmp_by_pair = defaultdict(list)
    for op in ops:
        if op[1] in CMP_IDS and len(op[4]) == 2 and len(op[5]) == 1 and v_2s[op[5][0]]:
            a, b = op[4]
            if not (v_2s[a] and v_2s[b]):
                continue
            sn = op_sn[op[0] - 1]
            if not sn:
                continue
            key = (sn, min(a, b), max(a, b))
            pair_kinds[key].add(op[1])
            cmp_by_pair[key].append((op[1], a, b, op[0]))
    combo_cnt, combo_dyn = Counter(), Counter()
    rev_cnt, rev_dyn = Counter(), Counter()
    multi = 0
    for key, kinds in pair_kinds.items():
        if len(kinds) < 2:
            continue
        multi += 1
        combo = "+".join(sorted(CMP_NAME[k] for k in kinds))
        for k, a, b, oid in cmp_by_pair[key]:
            combo_cnt[combo] += 1
            combo_dyn[combo] += act.get(op_sn[oid - 1], 0)
        seen = {(k, a, b) for k, a, b, _o in cmp_by_pair[key]}
        for fwd, rev in ((ID_LT, ID_GT), (ID_LE, ID_GE)):
            for k, a, b, _o in cmp_by_pair[key]:
                if k == fwd and (rev, b, a) in seen:
                    tag = f"{CMP_NAME[fwd]}(a,b)&{CMP_NAME[rev]}(b,a)"
                    rev_cnt[tag] += 1
                    rev_dyn[tag] += act.get(op_sn[_o - 1], 0)
        for sym in (ID_EQ, ID_NE):
            ab = sum(1 for k, a, b, _o in cmp_by_pair[key] if k == sym and a < b)
            ba = sum(1 for k, a, b, _o in cmp_by_pair[key] if k == sym and a > b)
            if ab and ba:
                rev_cnt[f"{CMP_NAME[sym]}-argorder-dup"] += min(ab, ba)
    print(f"pairs with >=2 cmp kinds: {multi}")
    for combo, c in combo_cnt.most_common(15):
        print(f"{c:>9} ops dyn={combo_dyn[combo]:>12} ({pct(combo_dyn[combo])})  {combo}")
    print("reversed-equivalent duplicates:")
    for k2, c in rev_cnt.most_common():
        print(f"{c:>9} pairs dyn={rev_dyn[k2]:>12} ({pct(rev_dyn[k2])})  {k2}")

    # ---- motif 4 ----
    print("\n== [4] mux(c, a+C, a) increment-or-not ==")
    m4, m4_dyn, m4_c = Counter(), Counter(), Counter()
    for op in ops:
        if op[1] != ID_MUX or len(op[4]) != 3 or len(op[5]) != 1 or not v_2s[op[5][0]]:
            continue
        c, t, f = op[4]
        hit = None
        for branch, other, tag in ((t, f, "true"), (f, t, "false")):
            p = producer[branch]
            if not p:
                continue
            po = ops[p - 1]
            if po[1] not in (ID_ADD, ID_SUB) or len(po[4]) != 2:
                continue
            x, y = po[4]
            cx, cy = const_int(x), const_int(y)
            if cx is None and cy is None:
                continue
            if cx is not None:
                if po[1] == ID_SUB:
                    continue  # sub(C, x) is not inc-or-not
                base, C = y, cx
            else:
                base, C = x, cy
            if base != other:
                continue
            hit = (tag, po[1] == ID_SUB, v_width[op[5][0]], C,
                   len(consumers.get(branch, ())) > 1)
            break
        if not hit:
            continue
        tag, isub, w, C, shared = hit
        a = act.get(op_sn[op[0] - 1], 0)
        key = f"{tag}-branch {'sub(x,C)' if isub else 'add'} w={wb(w)} {'shared' if shared else 'own'}-add"
        m4[key] += 1; m4_dyn[key] += a
        m4_c["C=1" if C == 1 else ("C=2" if C == 2 else ("C=4" if C == 4 else "other"))] += 1
    print(f"total={sum(m4.values())} dyn={sum(m4_dyn.values())} ({pct(sum(m4_dyn.values()))})")
    for k2, c in m4.most_common(12):
        print(f"{c:>9} ops dyn={m4_dyn[k2]:>12} ({pct(m4_dyn[k2])})  {k2}")
    print(f"constant hist: {dict(m4_c.most_common())}")

    # ---- motif 5 ----
    print("\n== [5] eq/ne(and(x,m), 0|m) + generic eq/ne(X,0) producers ==")
    m5, m5_dyn = Counter(), Counter()
    z, z_dyn = Counter(), Counter()
    for op in ops:
        if op[1] not in (ID_EQ, ID_NE) or len(op[4]) != 2 or len(op[5]) != 1 or not v_2s[op[5][0]]:
            continue
        a, b = op[4]
        ca, cb = const_int(a), const_int(b)
        a2 = act.get(op_sn[op[0] - 1], 0)
        for xv, cc in ((a, cb), (b, ca)):
            if cc is None:
                continue
            p = producer[xv]
            if cc == 0:
                pk = strings[ops[p - 1][1] - 1] if p else "<input>"
                key = f"{CMP_NAME[op[1]]}({pk},0)"
                z[key] += 1; z_dyn[key] += a2
            if not p:
                continue
            po = ops[p - 1]
            if po[1] != ID_AND or len(po[4]) != 2:
                continue
            cu, cw = const_int(po[4][0]), const_int(po[4][1])
            m = cu if cu is not None else cw
            if m is None:
                continue
            shape = "0" if cc == 0 else ("m" if cc == m else None)
            if shape is None:
                continue
            key = f"{CMP_NAME[op[1]]}(and,{shape})"
            m5[key] += 1; m5_dyn[key] += a2
            break
    print(f"and-mask bit tests: total={sum(m5.values())} dyn={sum(m5_dyn.values())}")
    for k2, c in m5.most_common():
        print(f"{c:>9} ops dyn={m5_dyn[k2]:>12} ({pct(m5_dyn[k2])})  {k2}")
    print(f"generic eq/ne(X,0): total={sum(z.values())} dyn={sum(z_dyn.values())} ({pct(sum(z_dyn.values()))})")
    for k2, c in z.most_common(10):
        print(f"{c:>9} ops dyn={z_dyn[k2]:>12} ({pct(z_dyn[k2])})  {k2}")

    # ---- motif 6 ----
    print("\n== [6] generic 2-op adjacency (two-state compute ops) ==")
    prod_pair, prod_dyn, prod_same = Counter(), Counter(), Counter()
    cons_pair, cons_dyn = Counter(), Counter()
    cache = {}
    def opname(sid):
        nm = cache.get(sid)
        if nm is None:
            nm = strings[sid - 1]
            if nm.startswith("core.compute."):
                nm = nm[len("core.compute."):]
            cache[sid] = nm
        return nm
    for op in ops:
        sid = op[1]
        if not strings[sid - 1].startswith("core.compute.") or not op[5] or not v_2s[op[5][0]]:
            continue
        oid = op[0]
        a = act.get(op_sn[oid - 1], 0)
        sn = op_sn[oid - 1]
        ok = opname(sid)
        for v in op[4]:
            p = producer[v]
            pk = opname(ops[p - 1][1]) if p else "<input>"
            prod_pair[(pk, ok)] += 1; prod_dyn[(pk, ok)] += a
            if p and op_sn[p - 1] == sn:
                prod_same[(pk, ok)] += 1
        for rv in op[5]:
            for cid in consumers.get(rv, ()):
                ck = opname(ops[cid - 1][1])
                cons_pair[(ok, ck)] += 1; cons_dyn[(ok, ck)] += a
    print("-- (producer -> this) top-30 by dyn --")
    for (pk, ok), d in prod_dyn.most_common(30):
        print(f"{prod_pair[(pk,ok)]:>9} ops dyn={d:>13} ({pct(d)}) sameSn={prod_same[(pk,ok)]:>8}  {pk} -> {ok}")
    print("-- (this -> consumer) top-30 by dyn --")
    for (ok, ck), d in cons_dyn.most_common(30):
        print(f"{cons_pair[(ok,ck)]:>9} ops dyn={d:>13} ({pct(d)})  {ok} -> {ck}")
    print(f"\ntotal runtime: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
