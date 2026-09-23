"""Census: mux algebra folding pools not covered by canonicalize (two-state only).

Patterns:
 1. same-condition nested mux: mux(c, mux(c,a,b), d) / mux(c, a, mux(c,b,d))
 2. distributivity: mux(c, f(xs..), f(ys..)) with same op kind f, same arity,
    <=1 differing operand position (params equal for sliceStatic)
 3. not(mux(c,a,b)) where a or b is itself not-produced
 4. eq(x,y) and ne(x,y) both present (order-insensitive)
Dynamic weight = act of the op's supernode (sn id == partition id).
"""

import argparse
from array import array
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import time

KIND_SUPER = 3
KIND_PHASE = 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path,
                        default=Path("ptmp/no00057_semantic_fixpoint_20260922/flow-dyn/xiangshan_grhsim_ir.json"))
    parser.add_argument("--dyn-log", type=Path,
                        default=Path("ptmp/no00057_semantic_fixpoint_20260922/logs_dyn2/xs_wolf_grhsim_no00057_dyn2.log"))
    args = parser.parse_args()

    t0 = time.time()
    model = json.loads(args.model.read_bytes())
    print(f"json load: {time.time() - t0:.1f}s", flush=True)
    strings, types, values, ops = model["strings"], model["types"], model["values"], model["operations"]
    payload = model["mappings"][0][-1]
    partitions = payload[2]
    n_ops, n_values = len(ops), len(values)

    n_types = max(t[0] for t in types)
    t_kind = [""] * (n_types + 1)
    t_width = array("I", [0]) * (n_types + 1)
    t_2s = bytearray(n_types + 1)
    for t in types:
        t_kind[t[0]] = t[2]
        t_width[t[0]] = t[3]
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
        p_kind[p[0]] = p[2]
        p_parent[p[0]] = p[1]
    op_part = array("I", [0]) * (n_ops + 1)
    for p in partitions:
        for op_id in p[5]:
            op_part[op_id] = p[0]
    resolved_sn = array("I", [0]) * (max_pid + 1)
    for p in partitions:
        cur = p[0]
        sn = 0
        while cur:
            if p_kind[cur] == KIND_SUPER:
                sn = cur
                break
            cur = p_parent[cur]
        resolved_sn[p[0]] = sn

    producer = array("I", [0]) * (n_values + 1)
    uses = array("I", [0]) * (n_values + 1)
    for op in ops:
        for v in op[5]:
            producer[v] = op[0]
        for v in op[4]:
            uses[v] += 1
    assert ops[0][0] == 1 and ops[-1][0] == n_ops

    act = {}
    sn_re = re.compile(r"\] sn (\d+) act=(\d+)")
    with open(args.dyn_log) as fh:
        for line in fh:
            m = sn_re.search(line)
            if m:
                act[int(m.group(1))] = int(m.group(2))
    print(f"passes done: {time.time() - t0:.1f}s", flush=True)

    def act_of(op_id):
        return act.get(resolved_sn[op_part[op_id]], 0)

    sid_of = {s: i + 1 for i, s in enumerate(strings)}
    ID_MUX = sid_of["core.compute.mux"]
    ID_NOT = sid_of["core.compute.not"]
    ID_LOGICNOT = sid_of.get("core.compute.logicNot")
    ID_EQ = sid_of["core.compute.eq"]
    ID_NE = sid_of["core.compute.ne"]
    DISTRIB_KINDS = {sid_of[n]: n for n in
                     ("core.compute.and", "core.compute.or", "core.compute.xor",
                      "core.compute.add", "core.compute.sub", "core.compute.sliceStatic")
                     if n in sid_of}

    # ---- [1] same-condition nested mux ----
    n_true = n_false = n_both = 0
    act_true = act_false = 0
    inner_single_use = 0
    # ---- [2] distributivity ----
    dist_count = Counter()
    dist_act = Counter()
    dist_zero_diff = 0
    # ---- [3] not(mux) with not-produced branch ----
    n_notmux = 0
    act_notmux = 0
    # ---- [4] eq/ne pairs ----
    eq_ops = defaultdict(list)
    ne_ops = defaultdict(list)

    for op in ops:
        sid = op[1]
        results = op[5]
        if len(results) != 1 or not v_2s[results[0]]:
            if sid == ID_EQ or sid == ID_NE:
                pass
            else:
                continue
        operands = op[4]
        if sid == ID_MUX and len(operands) == 3 and v_2s[results[0]]:
            c, tv, fv = operands
            pt, pf = producer[tv], producer[fv]
            hit_t = hit_f = False
            if pt:
                inner = ops[pt - 1]
                if inner[1] == ID_MUX and len(inner[4]) == 3 and inner[4][0] == c:
                    hit_t = True
                    if uses[tv] == 1:
                        inner_single_use += 1
            if pf:
                inner = ops[pf - 1]
                if inner[1] == ID_MUX and len(inner[4]) == 3 and inner[4][0] == c:
                    hit_f = True
                    if uses[fv] == 1:
                        inner_single_use += 1
            if hit_t:
                n_true += 1
                act_true += act_of(op[0])
            if hit_f:
                n_false += 1
                act_false += act_of(op[0])
            if hit_t and hit_f:
                n_both += 1
            # distributivity
            if pt and pf:
                ot, of = ops[pt - 1], ops[pf - 1]
                fname = DISTRIB_KINDS.get(ot[1])
                if fname and ot[1] == of[1] and len(ot[4]) == len(of[4]) and ot[4]:
                    if ot[7] == of[7]:  # params identical (sliceStatic ranges etc.)
                        diff = [i for i, (a, b) in enumerate(zip(ot[4], of[4])) if a != b]
                        w = v_width[results[0]]
                        bucket = fname + (":1bit" if w == 1 else ":multi")
                        if len(diff) == 1:
                            dist_count[bucket] += 1
                            dist_act[bucket] += act_of(op[0])
                        elif not diff:
                            dist_zero_diff += 1
        elif sid == ID_NOT and len(operands) == 1 and v_2s[results[0]]:
            pm = producer[operands[0]]
            if pm:
                mop = ops[pm - 1]
                if mop[1] == ID_MUX and len(mop[4]) == 3:
                    for branch in mop[4][1:]:
                        pb = producer[branch]
                        if pb and ops[pb - 1][1] in (ID_NOT, ID_LOGICNOT):
                            n_notmux += 1
                            act_notmux += act_of(op[0])
                            break
        elif sid == ID_EQ and len(operands) == 2 and v_2s[results[0]]:
            eq_ops[(min(operands), max(operands))].append(op[0])
        elif sid == ID_NE and len(operands) == 2 and v_2s[results[0]]:
            ne_ops[(min(operands), max(operands))].append(op[0])

    print("\n== [1] same-condition nested mux ==")
    print(f"mux(c, mux(c,_,_), _) true-branch : {n_true}  act-sum={act_true}")
    print(f"mux(c, _, mux(c,_,_)) false-branch: {n_false}  act-sum={act_false}")
    print(f"both branches: {n_both}; nested inner single-use (inner dies): {inner_single_use}")
    tot1 = n_true + n_false
    act1 = act_true + act_false
    print(f"total={tot1} act-sum={act1} ({100.0 * act1 / 22.1e9:.4f}% of 22.1G writebacks)")

    print("\n== [2] mux distributivity (one differing operand) ==")
    tot2 = sum(dist_count.values())
    act2 = sum(dist_act.values())
    for bucket, cnt in dist_count.most_common():
        print(f"{cnt:>9} ops act-sum={dist_act[bucket]:>12}  {bucket}")
    print(f"identical-branch mux (0 diff, CSE residue): {dist_zero_diff}")
    print(f"total={tot2} act-sum={act2} ({100.0 * act2 / 22.1e9:.4f}%)")

    print("\n== [3] not(mux(c,a,b)) with not-produced branch ==")
    print(f"count={n_notmux} act-sum={act_notmux} ({100.0 * act_notmux / 22.1e9:.4f}%)")

    print("\n== [4] eq/ne same-pair coexistence ==")
    pairs = set(eq_ops) & set(ne_ops)
    n_eq_op = sum(len(eq_ops[p]) for p in pairs)
    n_ne_op = sum(len(ne_ops[p]) for p in pairs)
    act_ne = sum(act_of(o) for p in pairs for o in ne_ops[p])
    print(f"pairs with both eq and ne: {len(pairs)} (eq ops={n_eq_op}, ne ops={n_ne_op})")
    print(f"ne-op act-sum (foldable to not(eq)): {act_ne} ({100.0 * act_ne / 22.1e9:.4f}%)")

    print("\n== conversion reference ==")
    print("total writebacks 22.1G/run; 242G cycles/run; "
      "rule of thumb: dynamic op 1% ~ total time 0.5-0.75%")
    print(f"total runtime: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
