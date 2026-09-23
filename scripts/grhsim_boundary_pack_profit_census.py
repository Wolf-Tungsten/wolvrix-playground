"""Cost-aware filtering of boundary packing (same S, same C, 1-bit lanes).

Pool (per task spec): 1-bit two-state unsigned boundary values whose producer is a
pure compute op (core.compute.*, no objectRefs, not constant); consumers are all
compute-phase supernodes (no commit, no endpoint); C excludes S itself (in-S
consumers are free and do not join C). Group key = (S, frozenset(C)), k>=2.

Per group: save_it = (k-1)*act(S); cost_it = sum_lane sum_{X in C_lane} act(X)
= k * sum_{X in C} act(X); net instr-equiv = 3.0*save_it - 1.5*cost_it.
Total run ~242G cycles; the unrestricted variant measured -7.48% (~-18.1G cycles).
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
    for t in types:
        t_kind[t[0]] = t[2]
        t_signed[t[0]] = 1 if t[4] else 0
        if t[2] == "logic" and t[5] == "2-state":
            t_2s[t[0]] = 1
    v_1bit = bytearray(n_values + 1)
    for v in values:
        tid = v[1]
        if t_kind[tid] == "logic" and t_2s[tid] and not t_signed[tid] and types[tid - 1][3] == 1:
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
    for op in ops:
        op_id = op[0]
        for u in op[4]:
            if is_boundary[u]:
                consumers[u].append(op_id)
    print(f"passes done: {time.time() - t0:.1f}s", flush=True)

    act = {}
    sn_re = re.compile(r"\] sn (\d+) act=(\d+)")
    with open(args.dyn_log) as fh:
        for line in fh:
            m = sn_re.search(line)
            if m:
                act[int(m.group(1))] = int(m.group(2))

    # --- build pool ---
    excl = Counter()
    lanes = []  # (v, S, frozenset C)
    for v in range(1, n_values + 1):
        if not is_boundary[v] or not v_1bit[v]:
            continue
        pid = producer[v]
        if not pid:
            excl["no_producer"] += 1
            continue
        op = ops[pid - 1]
        name = strings[op[1] - 1]
        if not name.startswith("core.compute.") or op[6]:
            excl["producer_not_pure_compute"] += 1
            continue
        if name == "core.compute.constant":
            excl["producer_constant"] += 1
            continue
        S = resolved_sn[op_part[pid]]
        if not S:
            excl["producer_no_supernode"] += 1
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
            excl["commit_or_endpoint_consumer"] += 1
            continue
        lanes.append((v, S, frozenset(C)))
    print(f"pool lanes={len(lanes)}; exclusions: {dict(excl.most_common())}")

    groups = defaultdict(list)
    for v, S, C in lanes:
        groups[(S, C)].append(v)
    groups = {key: mem for key, mem in groups.items() if len(mem) >= 2}

    # --- per-group economics ---
    rows = []
    for (S, C), mem in groups.items():
        k = len(mem)
        act_s = act.get(S, 0)
        sum_act_c = sum(act.get(X, 0) for X in C)
        save_it = (k - 1) * act_s
        cost_it = k * sum_act_c
        net = 3.0 * save_it - 1.5 * cost_it
        rows.append((S, C, k, act_s, sum_act_c, save_it, cost_it, net))

    n_groups = len(rows)
    n_lanes = sum(r[2] for r in rows)
    t_save = sum(r[5] for r in rows)
    t_cost = sum(r[6] for r in rows)
    t_net = sum(r[7] for r in rows)
    print("\n== [1] full pool economics ==")
    print(f"groups={n_groups} lanes={n_lanes}")
    print(f"sum save_it={t_save}  sum cost_it={t_cost}")
    print(f"net = 3*save - 1.5*cost = {t_net:.0f} instr-equiv "
          f"({100.0 * t_net / 242e9:+.3f}% of 242G cycles; measured unrestricted regression was -7.48%)")

    # --- [2] profitable-only ---
    print("\n== [2] profitable groups only (net>0) ==")
    prof = [r for r in rows if r[7] > 0]
    p_groups = len(prof)
    p_lanes = sum(r[2] for r in prof)
    p_save = sum(r[5] for r in prof)
    p_cost = sum(r[6] for r in prof)
    p_net = sum(r[7] for r in prof)
    print(f"groups={p_groups} lanes={p_lanes}")
    print(f"save_it={p_save} cost_it={p_cost} net={p_net:.0f} "
          f"({100.0 * p_net / 242e9:+.3f}% of 242G cycles)")
    ratio_buckets = ("C_empty", ">=8", "4-8", "2-4", "1-2", "0.5-1", "<0.5")
    rb = {b: [0, 0, 0.0] for b in ratio_buckets}  # groups, lanes, net
    for S, C, k, act_s, sum_act_c, save_it, cost_it, net in prof:
        if not C:
            b = "C_empty"
        else:
            r = act_s / (sum_act_c / len(C)) if sum_act_c else float("inf")
            b = (">=8" if r >= 8 else "4-8" if r >= 4 else "2-4" if r >= 2
                 else "1-2" if r >= 1 else "0.5-1" if r >= 0.5 else "<0.5")
        rb[b][0] += 1
        rb[b][1] += k
        rb[b][2] += net
    print("profit concentration by act(S)/avg_act(X):")
    for b in ratio_buckets:
        g, l, n = rb[b]
        print(f"  {b:>8}: groups={g:>6} lanes={l:>7} net={n:>14.0f} ({100.0 * n / 242e9:+.3f}%)")
    k_hist = Counter()
    for r in prof:
        k = r[2]
        k_hist[k if k <= 4 else ("5-8" if k <= 8 else ("9-16" if k <= 16 else ("17-64" if k <= 64 else ">64")))] += 1
    print("profitable group size hist: " +
          " ".join(f"{b}={k_hist.get(b, 0)}" for b in (2, 3, 4, "5-8", "9-16", "17-64", ">64")))

    print(f"\nverdict: profitable-subset net = {100.0 * p_net / 242e9:+.3f}% cycles "
          f"({'>= 1%, viable' if p_net >= 0.01 * 242e9 else '< 1%, not viable'})")
    print(f"total runtime: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
