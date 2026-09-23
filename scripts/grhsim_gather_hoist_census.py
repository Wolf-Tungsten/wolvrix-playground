"""Census: gather-hoist repair variant + constant-boundary + constant-chain algebra pools.

(1) Whole-concat match: concat C_x (two-state, >=2 operands) whose operands are ALL
    boundary values produced in the SAME supernode S (S != X) and whose sole consumer
    is C_x -> S can emit w=concat(lanes), C_x becomes assign(w); writeback k -> 1.
    Saving = act(S)*(k-1). Variants with constant lanes counted separately.
(2) Constant boundary values: producer core.compute.constant; writeback cost act(S);
    commit consumers disqualify.
(3) Constant-chain algebra patterns canonicalize does not cover; static count +
    dynamic exec estimate (act of the op's supernode).
(4) Boundary values produced by state.read: writeback cost (stats only).

sn id == partition id (verified in census_boundary_pack.py).
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
    value_slots = payload[3][3]
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
    v_type = array("I", [0]) * (n_values + 1)
    for v in values:
        v_type[v[0]] = v[1]
    v_width = array("I", [0]) * (n_values + 1)
    v_2s = bytearray(n_values + 1)
    for v in values:
        tid = v_type[v[0]]
        if t_kind[tid] == "logic":
            v_width[v[0]] = t_width[tid]
            if t_2s[tid]:
                v_2s[v[0]] = 1

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

    # consumers of boundary values: uses count + commit flag
    uses = array("I", [0]) * (n_values + 1)
    commit_use = bytearray(n_values + 1)
    for op in ops:
        op_id = op[0]
        cp = op_part[op_id]
        is_commit = 1 if resolved_phase[cp] == PHASE_COMMIT else 0
        for u in op[4]:
            if is_boundary[u]:
                uses[u] += 1
                if is_commit:
                    commit_use[u] = 1
    print(f"passes done: {time.time() - t0:.1f}s", flush=True)

    act = {}
    sn_re = re.compile(r"\] sn (\d+) act=(\d+)")
    with open(args.dyn_log) as fh:
        for line in fh:
            m = sn_re.search(line)
            if m:
                act[int(m.group(1))] = int(m.group(2))

    ID_CONSTANT = None
    sid_of = {s: i + 1 for i, s in enumerate(strings)}
    ID_CONSTANT = sid_of["core.compute.constant"]
    ID_SLICE = sid_of["core.compute.sliceStatic"]

    const_cache = {}

    def const_value(op_id):
        if op_id in const_cache:
            return const_cache[op_id]
        op = ops[op_id - 1]
        result = None
        if op[1] == ID_CONSTANT and len(op[7]) == 1:
            _n, tag, val = op[7][0]
            if tag == "string":
                result = parse_sv_literal(val)
            elif tag == "int":
                result = val
            elif tag == "bool":
                result = 1 if val else 0
        const_cache[op_id] = result
        return result

    def sn_act_of_op(op_id):
        return act.get(resolved_sn[op_part[op_id]], 0)

    # ================= [1] whole-concat gather-hoist pool =================
    print("\n== [1] whole-concat gather-hoist pool ==")
    cat_stats = Counter()       # category -> concat count
    cat_values = Counter()      # category -> boundary lanes covered
    cat_save = Counter()        # category -> dynamic saving
    cat_k = defaultdict(Counter)
    n_concat_2s = 0
    for op in ops:
        if strings[op[1] - 1] != "core.compute.concat":
            continue
        results, operands = op[5], op[4]
        if len(operands) < 2 or len(results) != 1 or not v_2s[results[0]]:
            continue
        n_concat_2s += 1
        X = resolved_sn[op_part[op[0]]]
        widths = [v_width[u] for u in operands]
        sns = set()
        n_boundary = n_const = n_other = 0
        sole_use = True
        for u in operands:
            pu = producer[u]
            if pu and strings[ops[pu - 1][1] - 1] == "core.compute.constant":
                n_const += 1
                continue
            if not pu or not is_boundary[u]:
                n_other += 1
                continue
            n_boundary += 1
            sns.add(resolved_sn[op_part[pu]])
            if uses[u] != 1:
                sole_use = False
        if n_other or not sns:
            cat_stats["disqualified_other_or_noboundary"] += 1
            continue
        if len(sns) != 1:
            cat_stats["multi_producer_supernode"] += 1
            continue
        S = next(iter(sns))
        if S == X or S == 0:
            cat_stats["same_supernode_or_no_sn"] += 1
            continue
        k = len(operands)
        if all(w == 1 for w in widths):
            wb = "all_1bit"
        elif len(set(widths)) == 1 and widths[0] <= 8:
            wb = "same_width_le8"
        else:
            wb = "mixed"
        if n_const:
            wb += "+const_lanes"
        if not sole_use:
            wb += "+multi_use_lanes"
        cat_stats[wb] += 1
        cat_values[wb] += k
        cat_k[wb][k if k <= 8 else ("9-32" if k <= 32 else ("33-64" if k <= 64 else ">64"))] += 1
        if sole_use and not n_const:
            cat_save[wb] += act.get(S, 0) * (k - 1)
    print(f"two-state concat ops with >=2 operands: {n_concat_2s}")
    for cat, cnt in cat_stats.most_common():
        kb = " ".join(f"{b}={c}" for b, c in sorted(cat_k[cat].items(), key=str))
        print(f"{cnt:>9} concats {cat_values[cat]:>8} lanes  {cat}  (k hist: {kb})")
    total_save = sum(cat_save.values())
    print(f"strict (all-boundary, sole-use, no const lanes) dynamic saving by bucket:")
    for cat, sv in cat_save.items():
        print(f"  {cat}: {sv}")
    print(f"TOTAL strict saving upper bound: {total_save} writeback iters/run "
          f"({100.0 * total_save / 22.1e9:.2f}% of 22.1G)")

    # ================= [2] constant boundary pool =================
    print("\n== [2] constant boundary values ==")
    n_cb = n_cb_commit = 0
    save_cb = save_cb_nocommit = 0
    for v in range(1, n_values + 1):
        if not is_boundary[v]:
            continue
        pid = producer[v]
        if not pid or ops[pid - 1][1] != ID_CONSTANT:
            continue
        n_cb += 1
        a = act.get(resolved_sn[op_part[pid]], 0)
        save_cb += a
        if commit_use[v]:
            n_cb_commit += 1
        else:
            save_cb_nocommit += a
    print(f"constant-produced boundary values: {n_cb} (with commit consumer: {n_cb_commit})")
    print(f"writeback cost: all={save_cb} iters/run, no-commit={save_cb_nocommit} "
          f"({100.0 * save_cb_nocommit / 22.1e9:.2f}% of 22.1G)")

    # ================= [3] constant-chain algebra pool =================
    print("\n== [3] constant-chain algebra patterns (two-state) ==")
    pat_count = Counter()
    pat_act = Counter()

    def one_const_oper(op):
        """Return (x_value, const_op_id) if exactly one operand is a known constant."""
        operands = op[4]
        if len(operands) != 2:
            return None
        p0, p1 = producer[operands[0]], producer[operands[1]]
        c0 = const_value(p0) if p0 else None
        c1 = const_value(p1) if p1 else None
        if c0 is not None and c1 is None:
            return operands[1], p0, c0
        if c1 is not None and c0 is None:
            return operands[0], p1, c1
        return None

    CHAIN_AB = {"core.compute.add": "add_chain", "core.compute.sub": "sub_chain",
                "core.compute.and": "and_chain", "core.compute.or": "or_chain",
                "core.compute.xor": "xor_chain"}
    SHIFTS = {"core.compute.shl": "shl_chain", "core.compute.lshr": "lshr_chain"}
    POW2 = {"core.compute.mul": "mul_pow2", "core.compute.div": "div_pow2",
            "core.compute.urem": "urem_pow2", "core.compute.srem": "srem_pow2",
            "core.compute.mod": "mod_pow2"}
    for op in ops:
        name = strings[op[1] - 1]
        results = op[5]
        if len(results) != 1 or not v_2s[results[0]]:
            continue
        hit = None
        if name in CHAIN_AB:
            got = one_const_oper(op)
            if got:
                x, _c_op, _c_val = got
                px = producer[x]
                if px:
                    inner = ops[px - 1]
                    if strings[inner[1] - 1] == name and len(inner[5]) == 1 and \
                            v_2s[inner[5][0]] and one_const_oper(inner):
                        hit = CHAIN_AB[name]
        elif name in SHIFTS:
            operands = op[4]
            if len(operands) == 2:
                p1 = producer[operands[1]]
                if p1 and const_value(p1) is not None:
                    px = producer[operands[0]]
                    if px:
                        inner = ops[px - 1]
                        if strings[inner[1] - 1] == name and len(inner[4]) == 2 and \
                                len(inner[5]) == 1 and v_2s[inner[5][0]]:
                            pi = producer[inner[4][1]]
                            if pi and const_value(pi) is not None:
                                hit = SHIFTS[name]
        elif name == "core.compute.sliceStatic":
            operands = op[4]
            if len(operands) == 1:
                px = producer[operands[0]]
                if px and ops[px - 1][1] == ID_SLICE:
                    hit = "nested_sliceStatic"
        elif name in POW2:
            got = one_const_oper(op)
            if got and got[2] is not None and got[2] > 0 and (got[2] & (got[2] - 1)) == 0:
                hit = POW2[name]
        if hit:
            pat_count[hit] += 1
            pat_act[hit] += sn_act_of_op(op[0])
    for pat, cnt in pat_count.most_common():
        print(f"{cnt:>9} ops  act-sum={pat_act[pat]:>13}  {pat}")

    # ================= [4] state.read boundary writeback cost =================
    print("\n== [4] state.read-produced boundary values (stats only) ==")
    n_sr = 0
    save_sr = 0
    ID_READ = sid_of["core.state.read"]
    for v in range(1, n_values + 1):
        if not is_boundary[v]:
            continue
        pid = producer[v]
        if pid and ops[pid - 1][1] == ID_READ:
            n_sr += 1
            save_sr += act.get(resolved_sn[op_part[pid]], 0)
    print(f"state.read boundary values: {n_sr}, writeback cost {save_sr} iters/run "
          f"({100.0 * save_sr / 22.1e9:.2f}% of 22.1G)")

    print(f"\ntotal runtime: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
