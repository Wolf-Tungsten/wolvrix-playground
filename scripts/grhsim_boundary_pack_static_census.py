"""Static criteria for profitable boundary packing (same S, same C, 1-bit lanes).

Pool identical to census_boundary_pack_profit.py. Per group static features:
k, |C|, sum|C_lane|=k*|C|, fanin(S)/fanin(X) (distinct boundary operands of the
supernode's ops), op counts; truth net_dyn = 3*(k-1)*act(S) - 1.5*k*sum act(X),
r = act(S)/avg_act(X). Evaluates static selection rules against the +8.07G
positive-net total (242G cycles = 100%).
"""

import argparse
from array import array
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import statistics
import time

KIND_SUPER = 3
KIND_PHASE = 1
PHASE_COMMIT = 2


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
    value_slots = payload[3][3]
    n_ops, n_values = len(ops), len(values)

    n_types = max(t[0] for t in types)
    t_kind = [""] * (n_types + 1)
    t_signed = bytearray(n_types + 1)
    t_2s = bytearray(n_types + 1)
    t_width = array("I", [0]) * (n_types + 1)
    for t in types:
        t_kind[t[0]] = t[2]
        t_width[t[0]] = t[3]
        t_signed[t[0]] = 1 if t[4] else 0
        if t[2] == "logic" and t[5] == "2-state":
            t_2s[t[0]] = 1
    v_1bit = bytearray(n_values + 1)
    for v in values:
        tid = v[1]
        if t_2s[tid] and not t_signed[tid] and t_width[tid] == 1:
            v_1bit[v[0]] = 1

    max_pid = max(p[0] for p in partitions)
    p_kind = bytearray(max_pid + 1)
    p_phase = bytearray(max_pid + 1)
    p_parent = array("I", [0]) * (max_pid + 1)
    for p in partitions:
        p_kind[p[0]] = p[2]
        p_phase[p[0]] = p[3]
        p_parent[p[0]] = p[1]
    op_part = array("I", [0]) * (n_ops + 1)
    for p in partitions:
        for op_id in p[5]:
            op_part[op_id] = p[0]
    resolved_sn = array("I", [0]) * (max_pid + 1)
    resolved_phase = bytearray(max_pid + 1)
    for p in partitions:
        sn = ph = 0
        cur = p[0]
        while cur:
            if not sn and p_kind[cur] == KIND_SUPER:
                sn = cur
            if not ph and p_kind[cur] == KIND_PHASE:
                ph = p_phase[cur]
            cur = p_parent[cur]
        resolved_sn[p[0]] = sn
        resolved_phase[p[0]] = ph

    producer = array("I", [0]) * (n_values + 1)
    for op in ops:
        for v in op[5]:
            producer[v] = op[0]
    assert ops[0][0] == 1 and ops[-1][0] == n_ops
    is_boundary = bytearray(n_values + 1)
    for v in range(1, n_values + 1):
        if value_slots[v - 1][1] == 2:
            is_boundary[v] = 1

    consumers = defaultdict(list)
    boundary_inputs = defaultdict(set)   # sn -> distinct boundary operand values
    sn_ops = Counter()                   # sn -> op count
    for op in ops:
        op_id = op[0]
        sn = resolved_sn[op_part[op_id]]
        if sn:
            sn_ops[sn] += 1
        for u in op[4]:
            if is_boundary[u]:
                consumers[u].append(op_id)
                if sn:
                    boundary_inputs[sn].add(u)
    fanin = {sn: len(s) for sn, s in boundary_inputs.items()}
    print(f"passes done: {time.time() - t0:.1f}s", flush=True)

    act = {}
    sn_re = re.compile(r"\] sn (\d+) act=(\d+)")
    with open(args.dyn_log) as fh:
        for line in fh:
            m = sn_re.search(line)
            if m:
                act[int(m.group(1))] = int(m.group(2))

    # --- pool (identical to census_boundary_pack_profit) ---
    lanes = []
    for v in range(1, n_values + 1):
        if not is_boundary[v] or not v_1bit[v]:
            continue
        pid = producer[v]
        if not pid:
            continue
        op = ops[pid - 1]
        name = strings[op[1] - 1]
        if not name.startswith("core.compute.") or op[6] or name == "core.compute.constant":
            continue
        S = resolved_sn[op_part[pid]]
        if not S:
            continue
        C = set()
        blocked = False
        for cid in consumers.get(v, ()):
            cp = op_part[cid]
            if resolved_phase[cp] == PHASE_COMMIT:
                blocked = True
                break
            csn = resolved_sn[cp]
            if not csn:
                blocked = True
                break
            if csn != S:
                C.add(csn)
        if blocked:
            continue
        lanes.append((v, S, frozenset(C)))
    groups = defaultdict(list)
    for v, S, C in lanes:
        groups[(S, C)].append(v)
    groups = {key: mem for key, mem in groups.items() if len(mem) >= 2}
    print(f"pool: groups={len(groups)} lanes={sum(len(m) for m in groups.values())}")

    # --- per-group features ---
    rows = []
    for (S, C), mem in groups.items():
        k = len(mem)
        act_s = act.get(S, 0)
        sum_act_c = sum(act.get(X, 0) for X in C)
        net = 3.0 * (k - 1) * act_s - 1.5 * k * sum_act_c
        avg_act_c = sum_act_c / len(C) if C else 0.0
        r = act_s / avg_act_c if avg_act_c else float("inf")
        fan_s = fanin.get(S, 0)
        fan_c = [fanin.get(X, 0) for X in C]
        sumfan = sum(fan_c)
        maxfan = max(fan_c) if fan_c else 0
        ops_s = sn_ops.get(S, 0)
        ops_c = sum(sn_ops.get(X, 0) for X in C)
        rows.append(dict(S=S, C=C, k=k, nc=len(C), act_s=act_s, net=net, r=r,
                         fan_s=fan_s, sumfan=sumfan, maxfan=maxfan,
                         ops_s=ops_s, ops_c=ops_c))

    pos_total = sum(r["net"] for r in rows if r["net"] > 0)
    neg_total = sum(r["net"] for r in rows if r["net"] <= 0)
    print(f"truth: positive-net sum={pos_total:.0f} ({100.0 * pos_total / 242e9:+.3f}% cycles), "
          f"negative-net sum={neg_total:.0f}")

    # --- rule evaluation ---
    def eval_rule(name, pred):
        sel = [r for r in rows if pred(r)]
        net_sum = sum(r["net"] for r in sel)
        pos_gain = sum(r["net"] for r in sel if r["net"] > 0)
        collateral = -sum(r["net"] for r in sel if r["net"] <= 0)
        print(f"{name:>22}: groups={len(sel):>6} net_sum={net_sum:>14.0f} "
              f"({100.0 * net_sum / 242e9:+6.3f}%) capture={100.0 * pos_gain / max(pos_total, 1):5.1f}% "
              f"collateral={collateral:>13.0f}")

    print("\n== static rules ==")
    eval_rule("R_fanin: sumfan<=fan_s", lambda r: r["sumfan"] <= r["fan_s"])
    eval_rule("R_fanin2: maxfan<=fan_s", lambda r: r["maxfan"] <= r["fan_s"])
    eval_rule("R_size: k>=8", lambda r: r["k"] >= 8)
    eval_rule("R_size_fanin: k>=4&sf<=2fs", lambda r: r["k"] >= 4 and r["sumfan"] <= 2 * r["fan_s"])
    eval_rule("R_c1: |C|==1", lambda r: r["nc"] == 1)
    eval_rule("R_c1_fanin: |C|==1&fx<=fs", lambda r: r["nc"] == 1 and r["sumfan"] <= r["fan_s"])
    eval_rule("R_ops: ops_c<=ops_s", lambda r: r["ops_c"] <= r["ops_s"])
    eval_rule("R_c1_ops: |C|==1&ops_c<=ops_s", lambda r: r["nc"] == 1 and r["ops_c"] <= r["ops_s"])
    eval_rule("R_kC: k>=2*|C|", lambda r: r["k"] >= 2 * max(r["nc"], 1))
    eval_rule("R_c1_k4: |C|==1&k>=4", lambda r: r["nc"] == 1 and r["k"] >= 4)
    eval_rule("R_fanin_k4: sf<=fs&k>=4", lambda r: r["sumfan"] <= r["fan_s"] and r["k"] >= 4)
    eval_rule("R_fanin_half: 2sf<=fs", lambda r: 2 * r["sumfan"] <= r["fan_s"])
    eval_rule("R_c1_k8: |C|==1&k>=8", lambda r: r["nc"] == 1 and r["k"] >= 8)
    eval_rule("R_nc2_k4: |C|<=2&k>=4", lambda r: r["nc"] <= 2 and r["k"] >= 4)
    eval_rule("R_k4_ops: k>=4&ops_c<=ops_s", lambda r: r["k"] >= 4 and r["ops_c"] <= r["ops_s"])
    eval_rule("R_c1_k4_fanin2: c1&k4&sf<=2fs", lambda r: r["nc"] == 1 and r["k"] >= 4
              and r["sumfan"] <= 2 * r["fan_s"])

    print("\n== (|C|, k) grid: net_sum per cell ==")
    nc_b = lambda nc: nc if nc <= 3 else ("4-8" if nc <= 8 else ">8")
    k_b = lambda k: k if k <= 4 else ("5-8" if k <= 8 else ("9-16" if k <= 16 else ">16"))
    grid = defaultdict(lambda: [0, 0.0, 0.0])
    for r in rows:
        cell = grid[(nc_b(r["nc"]), k_b(r["k"]))]
        cell[0] += 1
        cell[1] += r["net"]
        cell[2] += r["net"] if r["net"] > 0 else 0
    ncs = (1, 2, 3, "4-8", ">8")
    ks = (2, 3, 4, "5-8", "9-16", ">16")
    header = "|C|\\k      " + "".join(f"{str(k):>16}" for k in ks)
    print(header)
    for nc in ncs:
        line = f"{str(nc):>10}"
        for k in ks:
            g, n, _p = grid.get((nc, k), (0, 0.0, 0.0))
            line += f"  {n / 1e9:>+8.3f}G/{g:<5d}" if g else "               0"
        print(line)

    # --- fanin-ratio vs act-ratio correlation ---
    print("\n== correlation: sumfan(C)/fanin(S) buckets vs act ratio r and net ==")
    buckets = [("<0.25", 0, 0.25), ("0.25-0.5", 0.25, 0.5), ("0.5-1", 0.5, 1), ("1-2", 1, 2),
               ("2-4", 2, 4), ("4-8", 4, 8), (">=8", 8, float("inf")), ("fan_s=0", None, None)]
    for label, lo, hi in buckets:
        if lo is None:
            sel = [r for r in rows if r["fan_s"] == 0]
        else:
            sel = [r for r in rows if r["fan_s"] > 0 and
                   lo <= r["sumfan"] / r["fan_s"] < hi]
        if not sel:
            print(f"  {label:>8}: 0 groups")
            continue
        rs = sorted(r["r"] for r in sel if r["r"] != float("inf"))
        med_r = statistics.median(rs) if rs else float("nan")
        net_sum = sum(r["net"] for r in sel)
        pos_share = sum(r["net"] for r in sel if r["net"] > 0) / max(pos_total, 1)
        print(f"  {label:>8}: groups={len(sel):>6} median_r={med_r:8.2f} "
              f"net_sum={net_sum:>14.0f} ({100.0 * net_sum / 242e9:+6.3f}%) pos_capture={100.0 * pos_share:5.1f}%")

    print(f"\ntotal runtime: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
