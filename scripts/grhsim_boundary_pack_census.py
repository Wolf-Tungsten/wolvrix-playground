"""Census: pack same-producer-supernode, same-consumer-set narrow boundary values.

Idea: k 1-bit boundary values produced by supernode S with identical consumer
supernode set C could be merged into one k-bit concat word: 1 writeback instead
of k per producer activation, identical wake set (zero wake inflation); consumers
become sliceStatic(word, i, i).

Mapping conventions (scripts/grhsim_boundary_layout_stats.py, grhsim_op_mix_stats.py):
  payload      = mappings[0][-1]
  partitions   = payload[2]  # [id, parent, kind, phase, children, ops, ...]
  value_slots  = payload[3][3]  # [cpuType, storageKind, owner, offset]; kind 2 = boundary
  CpuPartitionKind: Root=0 Phase=1 EventDomain=2 Supernode=3 Node=4 ActiveWord=5 EmitFunction=6
  CpuPhase: None=0 Compute=1 Commit=2
Op -> supernode: op's owning partition (ops list), walk parents to first
Supernode-kind ancestor; the Phase-kind ancestor gives Compute vs Commit.
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
PHASE_COMPUTE = 1
PHASE_COMMIT = 2

WBUCKETS = ("1", "2-8", "9-32", "33-64", ">64")
GBUCKETS = ("2", "3", "4", "5-8", "9-16", "17-32", "33-64", ">64")


def wbucket(w):
    if w == 1:
        return "1"
    if w <= 8:
        return "2-8"
    if w <= 32:
        return "9-32"
    if w <= 64:
        return "33-64"
    return ">64"


def gbucket(k):
    if k <= 4:
        return str(k)
    if k <= 8:
        return "5-8"
    if k <= 16:
        return "9-16"
    if k <= 32:
        return "17-32"
    if k <= 64:
        return "33-64"
    return ">64"


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

    # --- type/value tables ---
    n_types = max(t[0] for t in types)
    t_kind = [""] * (n_types + 1)
    t_width = array("I", [0]) * (n_types + 1)
    t_signed = bytearray(n_types + 1)
    t_2s = bytearray(n_types + 1)
    for t in types:
        t_kind[t[0]] = t[2]
        t_width[t[0]] = t[3]
        t_signed[t[0]] = 1 if t[4] else 0
        if t[2] == "logic" and t[5] == "2-state":
            t_2s[t[0]] = 1
    v_type = array("I", [0]) * (n_values + 1)
    for v in values:
        v_type[v[0]] = v[1]
    v_width = array("I", [0]) * (n_values + 1)
    v_2s = bytearray(n_values + 1)
    v_signed = bytearray(n_values + 1)
    for v in values:
        tid = v_type[v[0]]
        if t_kind[tid] == "logic":
            v_width[v[0]] = t_width[tid]
            if t_2s[tid]:
                v_2s[v[0]] = 1
            if t_signed[tid]:
                v_signed[v[0]] = 1

    # --- partition tables ---
    max_pid = max(p[0] for p in partitions)
    p_kind = bytearray(max_pid + 1)
    p_phase = bytearray(max_pid + 1)
    p_parent = array("I", [0]) * (max_pid + 1)
    for p in partitions:
        p_kind[p[0]] = p[2]
        p_phase[p[0]] = p[3]
        p_parent[p[0]] = p[1]
    n_super = sum(1 for p in partitions if p[2] == KIND_SUPER)
    kind_hist = Counter(p[2] for p in partitions)
    print(f"partitions={len(partitions)} kinds={dict(sorted(kind_hist.items()))} supernodes={n_super}")

    op_part = array("I", [0]) * (n_ops + 1)
    for p in partitions:
        pid = p[0]
        for op_id in p[5]:
            op_part[op_id] = pid

    resolved_sn = array("I", [0]) * (max_pid + 1)   # 0 = not under a supernode
    resolved_phase = bytearray(max_pid + 1)         # 0 none, 1 compute, 2 commit
    for p in partitions:
        pid = p[0]
        sn = 0
        ph = 0
        cur = pid
        while cur:
            if not sn and p_kind[cur] == KIND_SUPER:
                sn = cur
            if not ph and p_kind[cur] == KIND_PHASE:
                ph = p_phase[cur]
            cur = p_parent[cur]
        resolved_sn[pid] = sn
        resolved_phase[pid] = ph

    # --- producer + boundary marks ---
    producer = array("I", [0]) * (n_values + 1)
    for op in ops:
        for v in op[5]:
            producer[v] = op[0]
    assert ops[0][0] == 1 and ops[-1][0] == n_ops

    is_boundary = bytearray(n_values + 1)
    for v in range(1, n_values + 1):
        if value_slots[v - 1][1] == 2:
            is_boundary[v] = 1
    n_boundary = sum(is_boundary)

    # consumers of boundary values
    consumers = defaultdict(list)
    for op in ops:
        op_id = op[0]
        for v in op[4]:
            if is_boundary[v]:
                consumers[v].append(op_id)
    print(f"passes done: {time.time() - t0:.1f}s boundary values={n_boundary}", flush=True)

    # --- item 1: boundary width buckets + producer kind ---
    width_hist = Counter()
    prod_kind = Counter()
    non_logic = 0
    for v in range(1, n_values + 1):
        if not is_boundary[v]:
            continue
        if v_width[v]:
            width_hist[wbucket(v_width[v])] += 1
        else:
            non_logic += 1
        pid = producer[v]
        prod_kind[strings[ops[pid - 1][1] - 1] if pid else "<none>"] += 1
    print("\n== [1] boundary values ==")
    print(f"total={n_boundary} non-logic/array={non_logic}")
    print("width: " + " ".join(f"{b}={width_hist.get(b, 0)}" for b in WBUCKETS))
    print("producer op kinds (top 10):")
    for name, cnt in prod_kind.most_common(10):
        print(f"{cnt:>9} {name}")

    # --- exclusions for the pack pool (1-bit values) ---
    excl_state_read = excl_params = excl_4s_signed = 0
    excl_param_kinds = Counter()
    pool = []  # (value, S, frozenset compute consumer sns, has_commit, width)
    for v in range(1, n_values + 1):
        if not is_boundary[v]:
            continue
        w = v_width[v]
        if w == 0 or w > 8:
            continue
        pid = producer[v]
        if not pid:
            continue
        op = ops[pid - 1]
        name = strings[op[1] - 1]
        if not v_2s[v] or v_signed[v]:
            excl_4s_signed += 1
            continue
        if name == "core.state.read":
            excl_state_read += 1
            continue
        if op[7]:
            excl_params += 1
            excl_param_kinds[name] += 1
            continue
        part = op_part[pid]
        S = resolved_sn[part]
        csn = set()
        has_commit = 0
        n_other = 0
        for cid in consumers.get(v, ()):
            cpart = op_part[cid]
            csn_id = resolved_sn[cpart]
            cph = resolved_phase[cpart]
            if cph == PHASE_COMMIT:
                has_commit = 1
            elif csn_id:
                csn.add(csn_id)
            else:
                n_other += 1
        pool.append((v, S, frozenset(csn), has_commit, w, n_other))

    print("\n== [5] exclusions (1..8-bit boundary values) ==")
    print(f"state.read-produced: {excl_state_read}")
    print(f"parameterized producer: {excl_params} ({dict(excl_param_kinds.most_common(6))})")
    print(f"four-state/signed: {excl_4s_signed}")
    print(f"pool after exclusions: {len(pool)}")

    def report_grouping(title, keyfn, dyn_act):
        groups = defaultdict(list)
        skipped_s0 = 0
        for entry in pool:
            if entry[1] == 0:
                skipped_s0 += 1
                continue
            key = keyfn(entry)
            if key is not None:
                groups[key].append(entry)
        hist = Counter()
        covered = 0
        valid = 0
        saved = 0
        saved_known = 0
        missing_act = 0
        for key, members in groups.items():
            k = len(members)
            if k < 2:
                continue
            valid += 1
            covered += k
            hist[gbucket(k)] += 1
            S = members[0][1]
            if dyn_act is not None:
                act = dyn_act.get(S)
                if act is None:
                    missing_act += 1
                else:
                    saved += (k - 1) * act
                    saved_known += 1
        print(f"\n{title}: groups(>=2)={valid} values covered={covered} "
              f"(skipped producer-not-in-supernode: {skipped_s0})")
        print("  group size hist: " + " ".join(f"{b}={hist.get(b, 0)}" for b in GBUCKETS))
        if dyn_act is not None:
            print(f"  dynamic writeback saving upper bound: {saved} /run "
                  f"(groups with act data={saved_known}, missing act={missing_act})")
        return valid, covered, saved

    # --- item 2: 1-bit, (S, C) groupings ---
    one_bit = [e for e in pool if e[4] == 1]
    print(f"\n== [2] 1-bit pool: {len(one_bit)} values ==")
    dyn_act = None  # filled later; report grouping statically first
    pure = [e for e in one_bit if not e[3] and not e[5]]
    print(f"pure-compute-consumer values (no commit/other): {len(pure)}")

    def key_pure(e):
        return (e[1], e[2])

    def key_all(e):
        return (e[1], e[2], e[3])

    save_pool = pool
    pool = pure
    report_grouping("[2a] key=(S, C_compute) pure-compute values, 1-bit", key_pure, None)
    pool = one_bit
    report_grouping("[2b] key=(S, C_compute, has_commit) all 1-bit values", key_all, None)

    # --- item 3: 2..8-bit same width, on the full pool ---
    pool = save_pool
    report_grouping("[3] key=(S, C_compute, has_commit, width) 2..8-bit values",
                    lambda e: (e[1], e[2], e[3], e[4]) if e[4] > 1 else None, None)

    # --- fallback key: (S, width, consumer count) ---
    report_grouping("[fb] key=(S, width, |C|, has_commit) 1..8-bit values",
                    lambda e: (e[1], e[4], len(e[2]), e[3]), None)

    # --- item 4: dynamic weighting ---
    print("\n== [4] dynamic weighting ==")
    act = {}
    sn_re = re.compile(r"\] sn (\d+) act=(\d+)")
    wr_total = 0
    wr_re = re.compile(r"\] kind (\S+) wr=(\d+)")
    with open(args.dyn_log) as fh:
        for line in fh:
            m = sn_re.search(line)
            if m:
                act[int(m.group(1))] = int(m.group(2))
                continue
            m = wr_re.search(line)
            if m:
                wr_total += int(m.group(2))
    n_sn_in_log = len(act)
    n_sn_match = sum(1 for sn in act if sn <= max_pid and p_kind[sn] == KIND_SUPER)
    print(f"log sn entries={n_sn_in_log}, matching supernode partition ids={n_sn_match}; "
          f"total per-kind wr (writeback ops) = {wr_total}")
    if n_sn_match * 2 < n_sn_in_log:
        print("WARNING: log sn ids do not align with partition ids; dynamic numbers unreliable")

    pool = pure
    report_grouping("[4a] 1-bit pure (S,C) groups, dynamic", key_pure, act)
    pool = one_bit
    report_grouping("[4b] 1-bit all (S,C,commit) groups, dynamic", key_all, act)
    pool = save_pool
    report_grouping("[4c] <=8-bit (S,C,commit,width) groups, dynamic",
                    lambda e: (e[1], e[2], e[3], e[4]), act)
    report_grouping("[4d] fallback (S,width,|C|,commit) groups, dynamic",
                    lambda e: (e[1], e[4], len(e[2]), e[3]), act)

    print(f"\ntotal runtime: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
