"""Census: constant-branch pools of 1-bit two-state bitSelect (and mux residue).

bitSelect(mask, whenSet, whenClear) = mask ? whenSet : whenClear (per bit).
1-bit constant-branch folds:
  bitSelect(m, s, 0) -> and(m, s)        bitSelect(m, s, 1) -> or(not(m), s)
  bitSelect(m, 0, c) -> and(not(m), c)   bitSelect(m, 1, c) -> or(m, c)
  both const: m?1:0 -> m, m?0:1 -> not(m), m?k:k -> k
Each fold saves ~2 instructions per activation. Dynamic weight = act of the
op's supernode. Baseline: 99.5G dynamic ops/run; 1% dyn ops ~ 0.5-0.75% time.
"""

import argparse
from array import array
from collections import Counter
import json
from pathlib import Path
import re
import time

KIND_SUPER = 3
SV_LITERAL = re.compile(r"^(?:(\d+))?'[sS]?([bodhBODH])([0-9a-fA-FxzXZ?_]+)$")
BASES = {"b": 2, "o": 8, "d": 10, "h": 16}


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
    v_1bit2s = bytearray(n_values + 1)
    for v in values:
        tid = v[1]
        if t_2s[tid] and t_width[tid] == 1:
            v_1bit2s[v[0]] = 1

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
    for op in ops:
        for v in op[5]:
            producer[v] = op[0]
    assert ops[0][0] == 1 and ops[-1][0] == n_ops

    act = {}
    sn_re = re.compile(r"\] sn (\d+) act=(\d+)")
    with open(args.dyn_log) as fh:
        for line in fh:
            m = sn_re.search(line)
            if m:
                act[int(m.group(1))] = int(m.group(2))
    print(f"passes done: {time.time() - t0:.1f}s", flush=True)

    sid_of = {s: i + 1 for i, s in enumerate(strings)}
    ID_BS = sid_of["core.compute.bitSelect"]
    ID_MUX = sid_of["core.compute.mux"]
    ID_CONST = sid_of["core.compute.constant"]

    def const_bit(value):
        """0/1 if value's producer is a 1-bit two-state constant, else None."""
        pid = producer[value]
        if not pid:
            return None
        op = ops[pid - 1]
        if op[1] != ID_CONST or len(op[7]) != 1 or not op[5] or not v_1bit2s[op[5][0]]:
            return None
        _n, tag, val = op[7][0]
        if tag == "string":
            parsed = parse_sv_literal(val)
        elif tag == "int":
            parsed = val
        elif tag == "bool":
            parsed = 1 if val else 0
        else:
            parsed = None
        return None if parsed is None else parsed & 1

    cls_count = Counter()
    cls_act = Counter()
    n_bs = 0
    act_bs = 0
    for op in ops:
        sid = op[1]
        if sid != ID_BS or len(op[4]) != 3 or len(op[5]) != 1 or not v_1bit2s[op[5][0]]:
            continue
        n_bs += 1
        a = act.get(resolved_sn[op_part[op[0]]], 0)
        act_bs += a
        _mask, when_set, when_clear = op[4]
        s = const_bit(when_set)
        c = const_bit(when_clear)
        if s is None and c is None:
            continue
        if s is not None and c is not None:
            key = f"both_const(s={s},c={c})"
        elif s is not None:
            key = f"whenSet={s}"
        else:
            key = f"whenClear={c}"
        cls_count[key] += 1
        cls_act[key] += a

    print("\n== [1/2] 1-bit two-state bitSelect constant branches ==")
    print(f"total 1-bit 2s bitSelect: {n_bs} (act-sum={act_bs})")
    tot_c = sum(cls_count.values())
    tot_a = sum(cls_act.values())
    for key in ("whenClear=0", "whenClear=1", "whenSet=0", "whenSet=1",
                "both_const(s=1,c=0)", "both_const(s=0,c=1)",
                "both_const(s=0,c=0)", "both_const(s=1,c=1)"):
        if cls_count.get(key):
            print(f"{cls_count[key]:>9} ops  act-sum={cls_act[key]:>12}  {key}")
    print(f"TOTAL constant-branch: {tot_c} ops act-sum={tot_a} "
          f"({100.0 * tot_a / 99.5e9:.4f}% of 99.5G dyn ops)")

    print("\n== [4] 1-bit two-state mux constant-branch residue ==")
    n_mux1 = 0
    cls_mux = Counter()
    act_mux = Counter()
    for op in ops:
        if op[1] != ID_MUX or len(op[4]) != 3 or len(op[5]) != 1 or not v_1bit2s[op[5][0]]:
            continue
        n_mux1 += 1
        _c, tv, fv = op[4]
        st = const_bit(tv)
        sf = const_bit(fv)
        if st is None and sf is None:
            continue
        key = f"true={st}" if st is not None else f"false={sf}"
        if st is not None and sf is not None:
            key = f"both({st},{sf})"
        cls_mux[key] += 1
        act_mux[key] += act.get(resolved_sn[op_part[op[0]]], 0)
    print(f"1-bit 2s mux total: {n_mux1}")
    for key, cnt in cls_mux.most_common():
        print(f"{cnt:>9} ops  act-sum={act_mux[key]:>12}  {key}")
    print(f"constant-branch mux residue: {sum(cls_mux.values())}")

    print("\n== conversion ==")
    print(f"bitSelect const-branch fold upper bound: {100.0 * tot_a / 99.5e9:.4f}% dyn ops "
          f"~ {0.5 * tot_a / 99.5e9 * 100:.3f}-{0.75 * tot_a / 99.5e9 * 100:.3f}% total time")
    print(f"total runtime: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
