"""Census: field-level fold of eq-OR chains (stride-contiguous constant sets).

For each eq-OR chain (or/logicOr tree, all leaves eq(x, Ci), common x; same
identification as census_motifs.py motif 1, no-claim variant), find a bit field
[lo,hi] (width 1..min(w,24)) such that (a) all Ci agree on ~V bits (common base
C0) and (b) field values (Ci>>lo)&fmask sorted cover a contiguous run
[Kmin,Kmax]. Fold: eq(and(x,~V),C0) & le(slice(x,lo,hi)-Kmin, Kmax-Kmin)
= 5 ops typical (2 if the run covers the whole field: mask-match only).
Outlier variant: <=2 constants off the main base/run reattached as residual
eq leaves (+1 or op each). Counts: static/dynamic op savings, k buckets,
top-20 chains, globally deduped net saving. Threshold: >=0.3% total time.

Conventions identical to census_motifs.py (payload, partitions, sn act).
"""
import json, re, time
from array import array
from collections import Counter, defaultdict
from pathlib import Path
import argparse

TOTAL_DYN = 99479933605.0
SV_LITERAL = re.compile(r"^(?:(\d+))?'[sS]?([bodhBODH])([0-9a-fA-FxzXZ?_]+)$")
BASES = {"b": 2, "o": 8, "d": 10, "h": 16}
KBUCKETS = ("2", "3", "4", "5-8", "9-16", "17-32", ">32")

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

def kbucket(k):
    if k <= 4:
        return str(k)
    if k <= 8:
        return "5-8"
    if k <= 16:
        return "9-16"
    if k <= 32:
        return "17-32"
    return ">32"

def core_ops(fw, w, kmin, kmax):
    full = (kmin == 0 and kmax == (1 << fw) - 1)
    base = 2 if fw < w else 0              # and + eq
    if full:
        field = 0
    else:                                  # [slice] + (le|ge) or (sub+le)
        field = (1 if fw < w else 0) + (1 if (kmin == 0 or kmax == (1 << fw) - 1) else 2)
    return base + field + (1 if (base and field) else 0)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", type=Path, default=Path(
        "ptmp/no00057_semantic_fixpoint_20260922/flow-dyn/xiangshan_grhsim_ir.json"))
    ap.add_argument("--dyn-log", type=Path, default=Path(
        "ptmp/no00057_semantic_fixpoint_20260922/logs_dyn2/xs_wolf_grhsim_no00057_dyn2.log"))
    args = ap.parse_args()

    t0 = time.time()
    model = json.loads(args.model.read_bytes())
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
            if p_kind[cur] == 3:
                sn = cur; break
            cur = p_parent[cur]
        resolved_sn[p[0]] = sn
    producer = array("I", [0]) * (n_values + 1)
    for op in ops:
        for v in op[5]:
            producer[v] = op[0]
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
    sid_of = {s: i + 1 for i, s in enumerate(strings)}
    ID_CONST = sid_of["core.compute.constant"]
    ID_EQ = sid_of["core.compute.eq"]
    OR_IDS = frozenset(sid_of[n] for n in ("core.compute.or", "core.compute.logicOr")
                       if n in sid_of)
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

    # ---- eq-OR chains (no-claim, per-leaf constant/shared tracking) ----
    chains = []
    for op in ops:
        oid = op[0]
        if op[1] not in OR_IDS or len(op[5]) != 1 or not v_2s[op[5][0]]:
            continue
        if any(ops[c - 1][1] in OR_IDS for c in consumers.get(op[5][0], ())):
            continue
        stack = [oid]; nodes = []; leaves = []
        while stack:
            o2 = stack.pop(); nodes.append(o2)
            for v in ops[o2 - 1][4]:
                p = producer[v]
                if p and ops[p - 1][1] in OR_IDS and v_2s[v] and len(ops[p - 1][5]) == 1:
                    stack.append(p)
                else:
                    leaves.append(v)
        infos = []
        ok = True
        for v in leaves:
            p = producer[v]
            if not p or ops[p - 1][1] != ID_EQ or len(ops[p - 1][4]) != 2 \
               or not v_2s[ops[p - 1][5][0]]:
                ok = False; break
            a, b = ops[p - 1][4]
            ca, cb = const_int(a), const_int(b)
            if ca is not None and cb is None:
                infos.append((b, ca, v))
            elif cb is not None and ca is None:
                infos.append((a, cb, v))
            else:
                ok = False; break
        if not ok or not infos:
            continue
        if len({i[0] for i in infos}) != 1:
            continue
        x = infos[0][0]; w = v_width[x]
        if not v_2s[x] or w == 0 or w > 64:
            continue
        mask = (1 << w) - 1
        leafconsts = [(c & mask, len(consumers.get(v, ())) > 1, v) for _x, c, v in infos]
        sns = {op_sn[n - 1] for n in nodes} | {op_sn[producer[v] - 1] for _x, _c, v in infos}
        chains.append(dict(root=oid, sn=op_sn[oid - 1], act=act.get(op_sn[oid - 1], 0),
                           k=len(infos), nodes=nodes, ops=len(infos) + len(nodes), w=w,
                           leafconsts=leafconsts, same_sn=len(sns) == 1))
    print(f"chains={len(chains)} loaded {time.time()-t0:.1f}s", flush=True)

    def best_fold(c, max_r):
        """Best (field, run) fold with <= max_r outliers; None if no positive saving."""
        w = c["w"]; k = c["k"]; nodes = len(c["nodes"])
        consts = [lc for lc, _s, _v in c["leafconsts"]]
        best = None
        for lo in range(w):
            for fw in range(1, min(w, 24) + 1):
                if lo + fw > w:
                    break
                fmask = (1 << fw) - 1
                nvmask = (~(fmask << lo)) & ((1 << w) - 1)
                groups = defaultdict(list)
                for idx, cv in enumerate(consts):
                    groups[cv & nvmask].append(idx)
                main_idx = max(groups.values(), key=len)
                out_base = k - len(main_idx)
                if out_base > max_r:
                    continue
                fvs = sorted(set((consts[i] >> lo) & fmask for i in main_idx))
                br = (fvs[0], fvs[0]); rs = prev = fvs[0]
                for v in fvs[1:]:
                    if v == prev + 1:
                        prev = v
                    else:
                        if prev - rs > br[1] - br[0]:
                            br = (rs, prev)
                        rs = prev = v
                if prev - rs > br[1] - br[0]:
                    br = (rs, prev)
                kmin, kmax = br
                covered = [i for i in main_idx if kmin <= ((consts[i] >> lo) & fmask) <= kmax]
                r = out_base + (len(main_idx) - len(covered))
                if r > max_r or len(covered) < 2:
                    continue
                cov_shared = sum(1 for i in covered if c["leafconsts"][i][1])
                dead = nodes + (len(covered) - cov_shared)
                newc = core_ops(fw, w, kmin, kmax) + r
                saving = dead - newc
                if saving <= 0:
                    continue
                key = (saving, -newc, len(covered))
                if best is None or key > best[0]:
                    best = (key, dict(lo=lo, fw=fw, hi=lo + fw - 1, r=r, kmin=kmin,
                                      kmax=kmax, covered=len(covered), dead=dead,
                                      new=newc, saving=saving,
                                      covered_leaves=[c["leafconsts"][i][2] for i in covered]))
        if w > 24:  # raw-interval fallback (motif-1 contiguous case)
            ks = sorted({cv for cv, _s, _v in c["leafconsts"]})
            if len(ks) > 1 and all(ks[i] - ks[i - 1] == 1 for i in range(1, len(ks))):
                shared = sum(1 for _cv, s, _v in c["leafconsts"] if s)
                dead = nodes + (k - shared)
                newc = 1 if ks[0] == 0 else 2
                saving = dead - newc
                if saving > 0:
                    key = (saving, -newc, k)
                    if best is None or key > best[0]:
                        best = (key, dict(lo=0, fw=w, hi=w - 1, r=0, kmin=ks[0],
                                          kmax=ks[-1], covered=k, dead=dead, new=newc,
                                          saving=saving, raw=True,
                                          covered_leaves=[v for _cv, _s, v in c["leafconsts"]]))
        return best

    res = []
    for c in chains:
        b0 = best_fold(c, 0)
        b2 = best_fold(c, 2)
        best = b2 if (b2 and (not b0 or b2[0] > b0[0])) else b0
        c["b0"] = b0[1] if b0 else None
        c["b2"] = b2[1] if b2 else None
        c["best"] = best[1] if best else None
        if best:
            res.append(c)
    print(f"fold enumeration done {time.time()-t0:.1f}s", flush=True)

    tot_chain_dyn = sum(c["ops"] * c["act"] for c in chains)
    n0 = sum(1 for c in chains if c["b0"])
    n2 = sum(1 for c in chains if c["best"] and not c["b0"])
    improved = sum(1 for c in chains if c["b0"] and c["b2"]
                   and c["b2"]["saving"] > c["b0"]["saving"])
    print(f"\n== summary ==")
    print(f"chains={len(chains)} ops={sum(c['ops'] for c in chains)} "
          f"chain-dyn={tot_chain_dyn} ({pct(tot_chain_dyn)})")
    print(f"foldable r=0: {n0}; rescued by <=2 outliers: {n2}; r<=2 improved r0-foldable: {improved}")

    def agg(sel):
        st = sum(c["best"]["saving"] for c in sel)
        dy = sum(c["best"]["saving"] * c["act"] for c in sel)
        ss = sum(c["best"]["saving"] * c["act"] for c in sel if c["same_sn"])
        return st, dy, ss

    st, dy, ss = agg(res)
    print(f"TOTAL foldable={len(res)} static-saved={st} dyn-saved={dy} ({pct(dy)} of 99.5G; "
          f"est {0.5*dy/TOTAL_DYN*100:.4f}-{0.75*dy/TOTAL_DYN*100:.4f}% of 242G cycles) "
          f"same-sn dyn={ss} ({pct(ss)})")
    fw_true = [c for c in res if not c["best"].get("raw") and c["best"]["fw"] < c["w"]]
    fw_pure = [c for c in res if not c["best"].get("raw") and c["best"]["fw"] == c["w"]]
    fw_raw = [c for c in res if c["best"].get("raw")]
    for name, sel in (("field fold proper (fw<w)", fw_true),
                      ("pure interval fw==w (motif-1 overlap)", fw_pure),
                      ("pure interval raw w>24 (motif-1 overlap)", fw_raw)):
        if sel:
            s2, d2, _ = agg(sel)
            print(f"  {name}: chains={len(sel)} static-saved={s2} dyn-saved={d2} ({pct(d2)})")
    r2sel = [c for c in res if c["best"]["r"] > 0]
    if r2sel:
        s2, d2, _ = agg(r2sel)
        print(f"  with outliers (r=1..2): chains={len(r2sel)} static-saved={s2} dyn-saved={d2} ({pct(d2)})")

    print(f"\n== k buckets (foldable) ==")
    print(f"{'k':>6} {'chains':>7} {'foldable':>8} {'dyn-saved':>14} {'%99.5G':>9}")
    for b in KBUCKETS:
        allb = [c for c in chains if kbucket(c["k"]) == b]
        fb = [c for c in res if kbucket(c["k"]) == b]
        d = sum(c["best"]["saving"] * c["act"] for c in fb)
        print(f"{b:>6} {len(allb):>7} {len(fb):>8} {d:>14} {pct(d):>9}")

    print(f"\n== top-20 chains by dyn saving ==")
    res.sort(key=lambda c: -c["best"]["saving"] * c["act"])
    for c in res[:20]:
        b = c["best"]
        fld = "raw" if b.get("raw") else f"[{b['lo']}:{b['hi']}]"
        print(f"root={c['root']} sn={c['sn']} act={c['act']} k={c['k']} w={c['w']} "
              f"field={fld} K=[{b['kmin']},{b['kmax']}] cov={b['covered']} r={b['r']} "
              f"dead={b['dead']} new={b['new']} save={b['saving']} "
              f"dyn={b['saving']*c['act']} same_sn={c['same_sn']}")

    # ---- global dedupe: unique dead ops vs new ops ----
    dead_ops = set()
    new_dyn = 0
    for c in res:
        b = c["best"]
        dead_ops.update(c["nodes"])
        for lv in b["covered_leaves"]:
            if len(consumers.get(lv, ())) <= 1:
                p = producer[lv]
                if p:
                    dead_ops.add(p)
        new_dyn += b["new"] * c["act"]
    uniq_dead_dyn = sum(act.get(op_sn[o - 1], 0) for o in dead_ops)
    net = uniq_dead_dyn - new_dyn
    print(f"\n== global dedupe ==")
    print(f"unique dead ops={len(dead_ops)} dyn={uniq_dead_dyn}; new-op dyn={new_dyn}; "
          f"NET dyn saving={net} ({pct(net)}) est time {0.5*net/TOTAL_DYN*100:.4f}-"
          f"{0.75*net/TOTAL_DYN*100:.4f}% of 242G cycles")
    print(f"\nruntime {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
