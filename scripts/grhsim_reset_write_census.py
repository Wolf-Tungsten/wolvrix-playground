#!/usr/bin/env python3
"""Census: folded reset patterns in GrhSIM IR ``core.state.regWrite`` ops.

Scope: every ``core.state.regWrite`` in the model's ``operations`` array
(primary account; cross-checked against op ids collected from all mapping
partitions — schedule-shape independent).

regWrite operand layout is ``(en, next, mask)`` (+ trailing event operands only
in the pre-B2 ``event_edges`` form, stripped here). The ``event_acts`` int
parameter holds the event-cluster indices: len==1 = single clock cluster
(synchronous logic, where an RTL ``if (rst) q <= C; else if (en0) q <= d;``
has been folded by ingest into ``en = or(rst, en0)``, ``next = mux(rst, C, d)``);
len>=2 = async-style writes (clock edge + reset edge clusters).

Shape taxonomy for the ``next`` producer of len==1 writes (A5 simplify rewrites
1-bit muxes to bitSelect and folds mux-with-constant to and/or; bitSelect is
``mask ? whenSet : whenClear`` and matches like a mux):
  R1: mux/bitSelect(c, K, d) or (c, d, K), exactly one constant arm;
  R2: nested chain of R1 links (depth = #const-arm links);
  R3: prioritySelect ([c0..cN-1, a0..aN-1, default]) with a constant arm;
  R4: 1-bit or(and(c, K), and(not(c), d)) form;
  R5a: 1-bit and(...)-form with a negated input in the subtree (mux(rst,0,d)
       folded by A5 to and(~rst, d)); reset value 0;
  R5b: 1-bit or(...)-form with a direct input in the subtree (mux(rst,1,d)
       folded to or(rst, d)); reset value 1;
  R0: anything else (producer-kind histogram reported for surprises).

For R1/R2/R3 the (first) condition is traced to a root through <=6 layers of
not/logicNot/bitSelect/sliceStatic/assign shells (input:<port> / state:<name> /
const / unknown:<kind>). Additionally a bounded subtree DFS (<=48 nodes)
collects input ports reachable from the cond and en subtrees (with negation
polarity): the folded-reset signature is "same input present in both the cond
subtree and the en subtree (or en == constant 1)".

Usage: grhsim_reset_write_census.py --model <grhsim_ir.json> [--out-json x.json] [--top 20]
"""
import argparse
from array import array
from collections import Counter, deque
import json
import re
import sys
import time

SV_LITERAL = re.compile(r"^(?:(\d+))?'[sS]?([bodhBODH])([0-9a-fA-FxzXZ?_]+)$")
BASES = {"b": 2, "o": 8, "d": 10, "h": 16}

NEEDED_KINDS = {
    "core.state.regWrite", "core.state.read", "core.input.read",
    "core.compute.mux", "core.compute.bitSelect", "core.compute.prioritySelect",
    "core.compute.constant", "core.compute.or", "core.compute.and",
    "core.compute.not", "core.compute.logicNot", "core.compute.sliceStatic",
    "core.compute.assign",
}
TRACE_KINDS = ("core.compute.not", "core.compute.logicNot", "core.compute.bitSelect",
               "core.compute.sliceStatic", "core.compute.assign")
MAX_TRACE = 6
DFS_BUDGET = 1024


def parse_sv_literal(text):
    s = text.strip().replace("_", "")
    m = SV_LITERAL.match(s)
    if m:
        digits = m.group(3).lower()
        if any(c in "xz?" for c in digits):
            return None
        try:
            return int(digits, BASES[m.group(2).lower()])
        except ValueError:
            return None
    try:
        return int(s, 10)
    except ValueError:
        return None


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def jsify(obj):
    if isinstance(obj, Counter):
        return {str(k): v for k, v in obj.items()}
    if isinstance(obj, dict):
        return {str(k): jsify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsify(v) for v in obj]
    return obj


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    t0 = time.time()
    with open(args.model, "rb") as fh:
        model = json.load(fh)
    log(f"[load] {time.time() - t0:.1f}s")

    strings = [None] + model["strings"]
    types = model["types"]
    states = model["states"]
    inputs = model.get("inputs", [])
    ops = model["operations"]
    n_ops = len(ops)
    n_values = len(model["values"])

    sid_of = {}
    for i, s in enumerate(model["strings"], start=1):
        if s in NEEDED_KINDS:
            sid_of[s] = i
            if len(sid_of) == len(NEEDED_KINDS):
                break

    def ksid(name):
        return sid_of.get(name, -1)

    SID_RW = ksid("core.state.regWrite")
    SID_MUX = ksid("core.compute.mux")
    SID_BS = ksid("core.compute.bitSelect")
    SID_PRISEL = ksid("core.compute.prioritySelect")
    SID_CONST = ksid("core.compute.constant")
    SID_OR = ksid("core.compute.or")
    SID_AND = ksid("core.compute.and")
    SID_NOT = ksid("core.compute.not")
    SID_LNOT = ksid("core.compute.logicNot")
    SID_INPUT = ksid("core.input.read")
    SID_STATE_READ = ksid("core.state.read")
    TRACE_SIDS = frozenset(sid_of[k] for k in TRACE_KINDS if k in sid_of)
    MUXLIKE = (SID_MUX, SID_BS)

    state_name = [None] * (len(states) + 1)
    state_width = array("i", bytes(4 * (len(states) + 1)))
    for s in states:
        state_name[s[0]] = strings[s[1]] if s[1] else f"#{s[0]}"
        t = types[s[2] - 1]
        state_width[s[0]] = t[3] if t[2] != "array" else types[t[6] - 1][3] * t[7]
    input_name = {inp[0]: (strings[inp[1]] if inp[1] else f"#{inp[0]}") for inp in inputs}

    assert ops[0][0] == 1 and ops[-1][0] == n_ops, "op ids not contiguous"
    producer = array("i", bytes(4 * (n_values + 1)))
    use_count = array("i", bytes(4 * (n_values + 1)))
    kind_sid = array("i", bytes(4 * (n_ops + 1)))
    for op in ops:
        oid = op[0]
        kind_sid[oid] = op[1]
        for v in op[5]:
            producer[v] = oid
        for v in op[4]:
            use_count[v] += 1
    log(f"[index] {time.time() - t0:.1f}s ops={n_ops} values={n_values} states={len(states)}")

    # boundary slots from the mapping layout (older checkpoints: payload[3][3]
    # per-value [cpuType, storageKind, owner, offset], kind 2 = boundary)
    payload = None
    for mapping in model.get("mappings", []):
        if len(mapping) > 4 and mapping[4]:
            payload = mapping[4]
    slot_kind = None
    if payload is not None:
        try:
            value_slots = payload[3][3]
            slot_kind = bytearray(n_values + 1)
            for v, slot in enumerate(value_slots, start=1):
                if v <= n_values and len(slot) > 1 and slot[1] == 2:
                    slot_kind[v] = 1
        except (TypeError, IndexError, KeyError):
            log("[info] no per-value boundary slots in this checkpoint's layout payload")

    def const_info(v):
        """None if v's producer is not a constant; else (parsed_value_or_None, raw)."""
        pid = producer[v]
        if not pid or kind_sid[pid] != SID_CONST:
            return None
        prms = ops[pid - 1][7]
        if not prms:
            return (None, "<noparam>")
        _n, tag, val = prms[0]
        if tag == "string":
            return (parse_sv_literal(val), val)
        if tag == "int":
            return (val, str(val))
        if tag == "bool":
            return (1 if val else 0, str(val))
        return (None, f"<{tag}>")

    def trace_root(v):
        cur = v
        for _ in range(MAX_TRACE):
            pid = producer[cur]
            if not pid:
                return ("noproducer", None)
            k = kind_sid[pid]
            if k == SID_INPUT:
                refs = ops[pid - 1][6]
                iid = refs[0][1] if refs else 0
                return ("input", input_name.get(iid, f"#{iid}"))
            if k == SID_STATE_READ:
                refs = ops[pid - 1][6]
                sid = refs[0][1] if refs else 0
                return ("state", state_name[sid] if 0 < sid <= len(states) else f"#{sid}")
            if k == SID_CONST:
                return ("const", None)
            if k in TRACE_SIDS:
                operands = ops[pid - 1][4]
                if not operands:
                    return ("unknown", strings[k])
                cur = operands[0]
                continue
            return ("unknown", strings[k])
        return ("depth", None)

    def root_key(root):
        kind, name = root
        return f"{kind}:{name}" if name else kind

    def subtree_signals(v, budget=DFS_BUDGET):
        """DFS the value's producer subtree; -> (ins, neg_ins, sts, neg_sts) Counters.

        Polarity tracks not/logicNot gates; state roots are full state names.
        """
        ins = Counter()
        neg_ins = Counter()
        sts = Counter()
        neg_sts = Counter()
        seen = set()
        queue = deque([(v, False)])  # BFS: shallow reset branches first
        while queue and len(seen) < budget:
            cur, inv = queue.popleft()
            if cur in seen:
                continue
            seen.add(cur)
            pid = producer[cur]
            if not pid:
                continue
            k = kind_sid[pid]
            if k == SID_INPUT:
                refs = ops[pid - 1][6]
                nm = input_name.get(refs[0][1] if refs else 0, "?")
                (neg_ins if inv else ins)[nm] += 1
                continue
            if k == SID_STATE_READ:
                refs = ops[pid - 1][6]
                sid = refs[0][1] if refs else 0
                nm = state_name[sid] if 0 < sid <= len(states) else f"#{sid}"
                (neg_sts if inv else sts)[nm] += 1
                continue
            ninv = inv ^ (k == SID_NOT or k == SID_LNOT)
            for ov in ops[pid - 1][4]:
                queue.append((ov, ninv))
        return ins, neg_ins, sts, neg_sts

    def match_r4(or_pid):
        """or(and(c, K), and(not(c), d)) with both ands 2-operand; loose (no c equality check)."""
        oo = ops[or_pid - 1][4]
        if len(oo) != 2:
            return None
        ands = []
        for v in oo:
            p = producer[v]
            if not p or kind_sid[p] != SID_AND or len(ops[p - 1][4]) != 2:
                return None
            ands.append(p)
        k_val = None
        k_raw = None
        have_not = False
        c_val = None
        for ap in ands:
            for ov in ops[ap - 1][4]:
                ci = const_info(ov)
                if ci is not None and ci[0] is not None:
                    k_val, k_raw = ci
                    continue
                pp = producer[ov]
                if pp and kind_sid[pp] in (SID_NOT, SID_LNOT):
                    have_not = True
                    inner = ops[pp - 1][4]
                    if inner:
                        c_val = inner[0]
                elif c_val is None:
                    c_val = ov
        if k_val is None or not have_not:
            return None
        return {"cond": c_val, "k": (k_val, k_raw), "ops": [or_pid] + ands}

    def classify_sync(next_v):
        """-> (shape, detail). detail carries cond value, K parse, chain op ids."""
        pid = producer[next_v]
        if not pid:
            return ("R0", {"producer": "none"})
        k = kind_sid[pid]
        if k in MUXLIKE:
            depth = 0
            conds = []
            ks = []
            chain_ops = []
            kinds_used = Counter()
            cur = next_v
            while True:
                p = producer[cur]
                if not p or kind_sid[p] not in MUXLIKE:
                    break
                o = ops[p - 1][4]
                if len(o) != 3:
                    break
                c, a, b = o
                ca, cb = const_info(a), const_info(b)
                if ca is not None and cb is None:
                    depth += 1
                    conds.append(c)
                    ks.append(ca)
                    chain_ops.append(p)
                    kinds_used[strings[kind_sid[p]].rsplit(".", 1)[-1]] += 1
                    cur = b
                elif cb is not None and ca is None:
                    depth += 1
                    conds.append(c)
                    ks.append(cb)
                    chain_ops.append(p)
                    kinds_used[strings[kind_sid[p]].rsplit(".", 1)[-1]] += 1
                    cur = a
                else:
                    if depth == 0 and ca is not None and cb is not None:
                        return ("R0", {"producer": "mux_both_const"})
                    break
            if depth >= 2:
                return ("R2", {"depth": depth, "cond": conds[0], "k": ks[0],
                               "chain_ops": chain_ops, "kinds": kinds_used})
            if depth == 1:
                return ("R1", {"depth": 1, "cond": conds[0], "k": ks[0],
                               "chain_ops": chain_ops, "kinds": kinds_used})
            return ("R0", {"producer": "mux_no_const_arm"})
        if k == SID_PRISEL:
            o = ops[pid - 1][4]
            n = (len(o) - 1) // 2
            conds = o[:n]
            arms = o[n:2 * n]
            const_arms = [i for i, av in enumerate(arms) if const_info(av) is not None]
            d_ci = const_info(o[-1])
            if const_arms or d_ci is not None:
                first = const_arms[0] if const_arms else None
                kinfo = const_info(arms[first]) if first is not None else d_ci
                return ("R3", {"n": n, "const_arms": len(const_arms),
                               "default_const": d_ci is not None,
                               "cond": conds[first] if first is not None else None,
                               "k": kinfo, "chain_ops": [pid]})
            return ("R0", {"producer": "prisel_no_const_arm"})
        if k == SID_OR:
            r4 = match_r4(pid)
            if r4 is not None:
                return ("R4", r4)
            return ("R0", {"producer": "core.compute.or"})
        if k == SID_AND:
            return ("R0", {"producer": "core.compute.and"})
        return ("R0", {"producer": strings[k]})

    def chain_depth(next_v, cap=256):
        depth = 0
        cur = next_v
        while depth < cap:
            p = producer[cur]
            if not p:
                break
            k = kind_sid[p]
            if k in MUXLIKE and len(ops[p - 1][4]) == 3:
                depth += 1
                o = ops[p - 1][4]
                nxt = None
                for cand in (o[2], o[1]):
                    pc = producer[cand]
                    if pc and (kind_sid[pc] in MUXLIKE or kind_sid[pc] == SID_PRISEL):
                        nxt = cand
                        break
                if nxt is None:
                    break
                cur = nxt
            elif k == SID_PRISEL:
                o = ops[p - 1][4]
                depth += (len(o) - 1) // 2
                cur = o[-1]
            else:
                break
        return depth

    # ---------------- gather all regWrite ops (operations-array account) -------------
    regwrites = []
    state_write_kinds = Counter()
    for op in ops:
        ksid2 = op[1]
        if ksid2 == SID_RW:
            regwrites.append(op)
        else:
            kname = strings[ksid2]
            if kname.startswith("core.state.") and kname != "core.state.read":
                state_write_kinds[kname] += 1
    log(f"[scan] regWrite={len(regwrites)} {time.time() - t0:.1f}s")

    # cross-check: op ids collected from all mapping partitions (schedule independent)
    mapped_regwrites = -1
    mapped_ops_total = -1
    if payload is not None:
        try:
            cnt = 0
            total = 0
            for p in payload[2]:
                for opid in p[5] or []:
                    total += 1
                    if kind_sid[opid] == SID_RW:
                        cnt += 1
            mapped_regwrites = cnt
            mapped_ops_total = total
        except (TypeError, IndexError) as exc:
            log(f"[warn] mapping cross-check unavailable: {exc}")
        log(f"[map] mapped ops={mapped_ops_total} mapped regWrite={mapped_regwrites} "
            f"{time.time() - t0:.1f}s")

    result = {"model": args.model,
              "model_inputs": sorted(input_name.values()),
              "totals": {"operations": n_ops, "values": n_values, "states": len(states),
                         "regWrite": len(regwrites),
                         "mapped_operations": mapped_ops_total,
                         "mapped_regWrite": mapped_regwrites,
                         "other_state_write_kinds": dict(state_write_kinds)}}

    # ---------------- A. event-shape totals ------------------------------------------
    len_dist = Counter()
    sig_count = Counter()
    per_state_writers = Counter()
    rw_width = Counter()
    parsed_ops = []  # (op, en_v, next_v, acts_tuple, sid)
    for op in regwrites:
        acts = None
        n_edges = 0
        for prm in op[7] or []:
            nm = strings[prm[0]]
            if nm == "event_acts":
                acts = prm[2]
            elif nm == "event_edges":
                n_edges = len(prm[2])
        operands = op[4] or []
        if n_edges and len(operands) > n_edges:
            operands = operands[:-n_edges]
        sid = op[6][0][1] if op[6] else 0
        n_acts = len(acts) if acts is not None else n_edges
        len_dist[n_acts if n_acts <= 3 else "3+"] += 1
        sig_count[tuple(acts) if acts is not None else ("edges", n_edges)] += 1
        per_state_writers[sid] += 1
        rw_width[state_width[sid]] += 1
        en_v = operands[0] if len(operands) >= 1 else 0
        next_v = operands[1] if len(operands) >= 2 else 0
        parsed_ops.append((op, en_v, next_v,
                           tuple(acts) if acts is not None else None, sid))

    result["A"] = {
        "event_acts_len": dict(len_dist),
        "top_signatures": [[list(sig), c] for sig, c in sig_count.most_common(15)],
        "distinct_signatures": len(sig_count),
        "regwrite_state_width_top": rw_width.most_common(10),
    }

    # ---------------- B. sync (len==1) reset-shape classification --------------------
    shape_count = Counter()
    shape_width = {}
    r0_producer = Counter()
    r0_producer_1bit = Counter()
    sync_1bit_total = 0
    root_stats = {}
    k_dist = Counter()
    k_raw_top = Counter()
    en_form_count = Counter()
    r2_depth = Counter()
    r3_n = Counter()
    elim_ops_total = 0
    elim_write_total = 0
    boundary_next = 0
    boundary_en = 0
    boundary_union = set()
    matched_next_vals = set()
    # folded-reset signature stats (subtree-DFS based)
    rst_sig = Counter()          # signature class -> writes
    rst_root = Counter()         # "i:<input>"/"s:<state>" -> writes (strong signature)
    rst_root_k = {}              # root -> Counter zero/nonzero
    rst_root_width = {}          # root -> Counter width
    cond_any_signal = 0
    cond_reset_name = 0
    r5_kinds = Counter()
    input_name_values = set(input_name.values())

    def root_bucket(key):
        st = root_stats.get(key)
        if st is None:
            st = root_stats[key] = {"writes": 0, "widths": Counter(),
                                    "shapes": Counter(), "en": Counter(),
                                    "k": Counter()}
        return st

    for op, en_v, next_v, acts, sid in parsed_ops:
        if acts is None or len(acts) != 1 or not next_v:
            continue
        width = state_width[sid]
        shape, det = classify_sync(next_v)
        if width == 1:
            sync_1bit_total += 1
        # R5a/R5b: 1-bit and/or forms with a reachable signal (A5-folded reset:
        # mux(rst,0,d) -> and(~rst,d); mux(rst,1,d) -> or(rst,d)); the reset net
        # may be the raw input or an internal resetSync state register.
        r5_cand = None
        if shape == "R0" and width == 1 and det["producer"] in ("core.compute.and",
                                                                "core.compute.or"):
            ins, neg_ins, sts, neg_sts = subtree_signals(next_v)
            if det["producer"] == "core.compute.and" and (neg_ins or neg_sts):
                shape = "R5a"
                r5_cand = neg_ins + neg_sts
                det = {"cond": None, "k": (0, "implicit-0"),
                       "chain_ops": [producer[next_v]]}
            elif det["producer"] == "core.compute.or" and (ins or sts):
                shape = "R5b"
                r5_cand = ins + sts
                det = {"cond": None, "k": (1, "implicit-1"),
                       "chain_ops": [producer[next_v]]}
            else:
                r5_kinds[f"1bit_{det['producer'].rsplit('.', 1)[-1]}_no_signal"] += 1
        shape_count[shape] += 1
        shape_width.setdefault(shape, Counter())[width] += 1
        if shape == "R0":
            r0_producer[det["producer"]] += 1
            if width == 1:
                r0_producer_1bit[det["producer"]] += 1
            continue
        if shape == "R2":
            r2_depth[det["depth"]] += 1
        if shape == "R3":
            r3_n[det["n"]] += 1
        cond_v = det.get("cond")
        root = trace_root(cond_v) if cond_v else ("unknown", "no_cond")
        rkey = root_key(root)
        rb = root_bucket(rkey)
        rb["writes"] += 1
        rb["widths"][width] += 1
        rb["shapes"][shape] += 1
        kinfo = det.get("k")
        kval = kinfo[0] if kinfo else None
        kraw = kinfo[1] if kinfo else "<?>"
        k_cls = "zero" if kval == 0 else ("nonzero" if kval is not None else "unparsed")
        k_dist[k_cls] += 1
        k_raw_top[str(kraw)[:40]] += 1
        rb["k"][k_cls] += 1
        # en form: or(cond, ...) with same signal, or constant 1
        en_kind = "other"
        en_pid = producer[en_v]
        if en_pid and kind_sid[en_pid] == SID_OR:
            en_kind = "or_other"
            for ov in ops[en_pid - 1][4]:
                if ov == cond_v:
                    en_kind = "or_same_cond"
                    break
            if en_kind == "or_other":
                for ov in ops[en_pid - 1][4]:
                    if root_key(trace_root(ov)) == rkey:
                        en_kind = "or_same_root"
                        break
        else:
            ci = const_info(en_v)
            if ci is not None:
                en_kind = "const1" if ci[0] == 1 else "const_other"
        en_form_count[en_kind] += 1
        rb["en"][en_kind] += 1
        # folded-reset signature via subtree DFS (cond side + en side):
        # candidate root = input port or state reachable from the cond (or, for
        # R5, the whole next) subtree; strong when the same root also appears in
        # the en subtree (folded en = or(rst, en0)) or en is constant 1.
        if cond_v:
            c_ins, c_neg, c_sts, c_nsts = subtree_signals(cond_v)
            cand = c_ins + c_neg + c_sts + c_nsts
        else:
            cand = r5_cand if r5_cand is not None else Counter()
        if cand:
            cond_any_signal += 1
            if any("reset" in nm.lower() for nm in cand):
                cond_reset_name += 1
        if en_v:
            e_ins, e_neg, e_sts, e_nsts = subtree_signals(en_v)
            e_all = e_ins + e_neg + e_sts + e_nsts
        else:
            e_all = Counter()
        en_const1 = en_kind == "const1"
        best = None
        for nm, _cnt in cand.most_common(4):
            if nm in e_all or en_const1:
                best = nm
                break
        if best is None and cand:
            best = cand.most_common(1)[0][0]
        if cand:
            strong = best in e_all or en_const1
            rst_sig["strong" if strong else "cond_only"] += 1
            if strong:
                key = ("i:" if best in input_name_values else "s:") + best
                rst_root[key] += 1
                rst_root_k.setdefault(key, Counter())[k_cls] += 1
                rst_root_width.setdefault(key, Counter())[width] += 1
        # C: eliminable ops (fanout==1 on the op's single result)
        elim = 0
        for pid in det.get("chain_ops", det.get("ops", [])):
            res = ops[pid - 1][5]
            if len(res) == 1 and use_count[res[0]] == 1:
                elim += 1
        if en_kind.startswith("or_") and en_pid:
            res = ops[en_pid - 1][5]
            if len(res) == 1 and use_count[res[0]] == 1:
                elim += 1
        if elim:
            elim_write_total += 1
            elim_ops_total += elim
        if slot_kind is not None:
            bn = slot_kind[next_v]
            be = slot_kind[en_v] if en_v else 0
            boundary_next += bn
            boundary_en += be
            if bn:
                boundary_union.add(next_v)
            if be and en_v:
                boundary_union.add(en_v)
        matched_next_vals.add(next_v)

    result["B"] = {
        "sync_writes": sum(shape_count.values()),
        "sync_1bit_writes": sync_1bit_total,
        "shapes": dict(shape_count),
        "shape_width_top": {s: shape_width[s].most_common(6) for s in shape_width},
        "r0_producer_top": r0_producer.most_common(15),
        "r0_producer_1bit_top": r0_producer_1bit.most_common(15),
        "r2_depth": dict(r2_depth),
        "r3_n": dict(r3_n),
        "k_value": dict(k_dist),
        "k_raw_top": k_raw_top.most_common(10),
        "en_form": dict(en_form_count),
        "reset_signature": dict(rst_sig),
        "cond_with_any_signal": cond_any_signal,
        "cond_with_reset_named_signal": cond_reset_name,
        "reset_roots_top": [
            {"root": nm, "writes": c,
             "k": dict(rst_root_k.get(nm, {})),
             "widths": rst_root_width.get(nm, Counter()).most_common(6)}
            for nm, c in rst_root.most_common(15)],
        "r5_leftover": dict(r5_kinds),
        "roots_top": [
            {"root": k, "writes": v["writes"], "widths": v["widths"].most_common(5),
             "shapes": dict(v["shapes"]), "en": dict(v["en"]), "k": dict(v["k"])}
            for k, v in sorted(root_stats.items(), key=lambda kv: -kv[1]["writes"])[:args.top]],
    }
    result["C"] = {
        "matched_writes_R1_R5": sum(shape_count[s] for s in ("R1", "R2", "R3", "R4", "R5a", "R5b")),
        "writes_with_eliminable_ops": elim_write_total,
        "eliminable_ops": elim_ops_total,
        "eliminable_frac_of_model_ops": elim_ops_total / n_ops if n_ops else 0,
        "boundary_next_operand_writes": boundary_next,
        "boundary_en_operand_writes": boundary_en,
        "boundary_union_values": len(boundary_union),
        "distinct_next_values": len(matched_next_vals),
        "boundary_available": slot_kind is not None,
    }

    # ---------------- D. async writes (len(event_acts) >= 2) --------------------------
    async_total = 0
    async_next_kind = Counter()
    async_mux_root_input = 0
    async_roots = Counter()
    async_sig = Counter()       # next muxlike: const arm x signal presence classes
    async_sig_k = Counter()
    async_cond_root = Counter()   # top root signal (i:/s:) per async cond subtree
    async_reset_name = Counter()
    async_reset_k = Counter()
    async_reset_k_raw = Counter()
    for op, en_v, next_v, acts, sid in parsed_ops:
        if acts is None or len(acts) < 2 or not next_v:
            continue
        async_total += 1
        pid = producer[next_v]
        kname = strings[kind_sid[pid]] if pid else "none"
        async_next_kind[kname] += 1
        cond_vals = []
        const_arm = None
        if pid and kind_sid[pid] in MUXLIKE and len(ops[pid - 1][4]) == 3:
            o = ops[pid - 1][4]
            cond_vals = [o[0]]
            ca, cb = const_info(o[1]), const_info(o[2])
            const_arm = ca if ca is not None else cb
        elif pid and kind_sid[pid] == SID_PRISEL:
            o = ops[pid - 1][4]
            n = (len(o) - 1) // 2
            cond_vals = list(o[:n])
            for av in o[n:]:
                ci = const_info(av)
                if ci is not None:
                    const_arm = ci
                    break
        if not cond_vals:
            continue
        root = trace_root(cond_vals[0])
        async_roots[root_key(root)] += 1
        if root[0] == "input":
            async_mux_root_input += 1
        all_sig = Counter()
        for cv in cond_vals:
            ci2, cn2, cs2, cns2 = subtree_signals(cv)
            all_sig += ci2 + cn2 + cs2 + cns2
        if all_sig:
            for nm in all_sig:
                key = ("i:" if nm in input_name_values else "s:") + nm
                async_cond_root[key] += 1
            if any("reset" in s.lower() for s in all_sig):
                async_reset_name["muxlike_cond_has_reset_name"] += 1
                if const_arm is not None:
                    kval = const_arm[0]
                    async_reset_k["zero" if kval == 0 else ("nonzero" if kval is not None else "unparsed")] += 1
                    if kval is not None:
                        async_reset_k_raw[str(const_arm[1])[:40]] += 1
        if const_arm is not None and all_sig:
            async_sig["muxlike_const_arm_with_signal"] += 1
            kval = const_arm[0]
            async_sig_k["zero" if kval == 0 else ("nonzero" if kval is not None else "unparsed")] += 1
        elif all_sig:
            async_sig["muxlike_signal_no_const_arm"] += 1
        elif const_arm is not None:
            async_sig["muxlike_const_arm_no_signal"] += 1
    result["D"] = {
        "async_writes": async_total,
        "next_producer_top": async_next_kind.most_common(10),
        "mux_cond_traces_to_input_shallow": async_mux_root_input,
        "mux_cond_roots_top": async_roots.most_common(15),
        "cond_subtree_signature": dict(async_sig),
        "cond_subtree_roots_top": async_cond_root.most_common(15),
        "cond_with_reset_named_signal": dict(async_reset_name),
        "const_arm_value_when_reset_named": dict(async_reset_k),
        "const_arm_raw_top": async_reset_k_raw.most_common(10),
        "const_arm_value_all": dict(async_sig_k),
    }

    # ---------------- E. decode chains + multi-writer states --------------------------
    deep_writes = 0
    deep_writes_sync = 0
    depth_hist = Counter()
    for op, en_v, next_v, acts, sid in parsed_ops:
        if not next_v:
            continue
        d = chain_depth(next_v)
        if d:
            depth_hist[d if d < 8 else "8+"] += 1
        if d >= 4:
            deep_writes += 1
            if acts is not None and len(acts) == 1:
                deep_writes_sync += 1
    multi_writer = sum(1 for _s, c in per_state_writers.items() if c > 1)
    result["E"] = {
        "decode_chain_depth_hist": dict(depth_hist),
        "writes_chain_depth_ge4": deep_writes,
        "writes_chain_depth_ge4_sync": deep_writes_sync,
        "states_with_multi_regWrite": multi_writer,
        "states_with_any_regWrite": len(per_state_writers),
    }

    # ---------------- report ----------------------------------------------------------
    P = print
    P(f"model: {args.model}")
    P(f"total ops={n_ops} values={n_values} states={len(states)} inputs={sorted(input_name.values())}")
    P(f"regWrite ops={len(regwrites)} (mapped-partitions account: {mapped_regwrites}, "
      f"mapped ops total: {mapped_ops_total})")
    P(f"other state write kinds: {dict(state_write_kinds)}")
    P("\n== A. event shape ==")
    P(f"len(event_acts) distribution: {dict(len_dist)}")
    P(f"distinct signatures: {len(sig_count)}; top-15:")
    for sig, c in sig_count.most_common(15):
        P(f"  {c:>8}  acts={list(sig)}")
    P(f"regWrite target state width top: {rw_width.most_common(10)}")

    P("\n== B. sync writes (len==1) shape census ==")
    P(f"sync writes={sum(shape_count.values())} (1-bit state: {sync_1bit_total})")
    for s, c in shape_count.most_common():
        P(f"  {s}: {c}  widths(top)={shape_width[s].most_common(6)}")
    P(f"R0 next-producer kinds (top-15): {r0_producer.most_common(15)}")
    P(f"R0 next-producer kinds, 1-bit writes (top-15): {r0_producer_1bit.most_common(15)}")
    P(f"R5 leftover (1-bit and/or without reachable signal): {dict(r5_kinds)}")
    P(f"R2 chain depth: {dict(sorted(r2_depth.items()))}")
    P(f"R3 prioritySelect N: {dict(sorted(r3_n.items()))}")
    P(f"K value class: {dict(k_dist)}; raw top: {k_raw_top.most_common(10)}")
    P(f"en form: {dict(en_form_count)}")
    P(f"folded-reset signature: {dict(rst_sig)}; matched writes with any cond-subtree "
      f"signal: {cond_any_signal}; with /reset/i-named signal: {cond_reset_name}")
    P("strong-signature reset roots (top-15):")
    for row in result["B"]["reset_roots_top"]:
        P(f"  {row['writes']:>8}  {row['root'][:110]}")
        P(f"           k={row['k']} widths={row['widths']}")
    P(f"top-{args.top} cond roots (R1+R2+R3+R4):")
    for row in result["B"]["roots_top"]:
        P(f"  {row['writes']:>8}  {row['root'][:110]}")
        P(f"           widths={row['widths']} shapes={row['shapes']} en={row['en']} k={row['k']}")

    P("\n== C. eliminable op estimate (R1-R5, fanout==1) ==")
    P(f"matched writes={result['C']['matched_writes_R1_R5']}; "
      f"writes with >=1 eliminable op={elim_write_total}; eliminable ops={elim_ops_total} "
      f"({100.0 * elim_ops_total / n_ops:.3f}% of model ops)")
    if slot_kind is not None:
        P(f"boundary values: next-operand writes={boundary_next}, en-operand writes={boundary_en}, "
          f"distinct boundary values (union)={len(boundary_union)}")
    else:
        P("boundary values: unavailable in this checkpoint (no per-value slots in layout payload)")

    P("\n== D. async writes (len(event_acts)>=2) ==")
    P(f"async writes={async_total}")
    P(f"next producer kinds: {async_next_kind.most_common(10)}")
    P(f"mux-shaped next with cond tracing to an input (shallow): {async_mux_root_input}")
    P(f"mux cond roots shallow (top-15): {async_roots.most_common(15)}")
    P(f"cond-subtree signature: {dict(async_sig)}")
    P(f"cond-subtree top roots (top-15):")
    for nm, c in async_cond_root.most_common(15):
        P(f"  {c:>8}  {nm[:120]}")
    P(f"cond subtree has /reset/i-named signal: {dict(async_reset_name)}")
    P(f"const-arm value class (all signal-cond): {dict(async_sig_k)}; "
      f"(reset-named cond): {dict(async_reset_k)} raw top: {async_reset_k_raw.most_common(10)}")

    P("\n== E. decode chains / multi-writer states ==")
    P(f"chain depth histogram (all regWrite): {dict(depth_hist)}")
    P(f"writes with chain depth>=4: {deep_writes} (sync: {deep_writes_sync})")
    P(f"states with >1 regWrite writers: {multi_writer} "
      f"(states with any regWrite: {len(per_state_writers)} / {len(states)})")

    if args.out_json:
        with open(args.out_json, "w") as fh:
            json.dump(jsify(result), fh, indent=1, sort_keys=False)
        log(f"[json] wrote {args.out_json}")
    log(f"[done] {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
