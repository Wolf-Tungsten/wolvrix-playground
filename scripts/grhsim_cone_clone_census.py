"""Census: clone a boundary value's in-supernode compute cone into its consumers.

For boundary value v produced in supernode S by a pure compute op: the cone is
built by walking operands up; recursion continues through in-S pure compute ops
(core.compute.*, no objectRefs; sliceStatic/constant are cloned through, the
slice source becomes a leaf; sliceDynamic/sliceArray disqualify the cone) whose
intermediate result is partition_local (slot[1]==1). Anything else is a leaf:
  boundary  -> changing leaf L(v) (S's boundary inputs or in-S boundary values)
  state.read-> state leaf (X must contain a state.read of the same state object)
  input/memRead/other -> disqualifying for the strict criterion
Cone size limited to 8 ops. v is fully eliminable iff every consumer supernode
X (compute phase, X != S) already has all changing leaves among its boundary
inputs (and, strict, reads every state leaf's state), and v has no commit or
endpoint consumer. Saving ~= act(S) writebacks per run (~4 instr each); cost =
sum over X of cone_ops * act(X) (1 instr each).
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
MAX_CONE = 8


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

    # --- partitions ---
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

    # --- producer / boundary / storage ---
    producer = array("I", [0]) * (n_values + 1)
    for op in ops:
        for v in op[5]:
            producer[v] = op[0]
    assert ops[0][0] == 1 and ops[-1][0] == n_ops
    slot_kind = bytearray(n_values + 1)
    for v in range(1, n_values + 1):
        slot_kind[v] = value_slots[v - 1][1]
    is_boundary = bytearray(n_values + 1)
    for v in range(1, n_values + 1):
        if slot_kind[v] == 2:
            is_boundary[v] = 1

    # --- consumers of boundary values; X boundary inputs; state.read by supernode ---
    consumers = defaultdict(list)
    boundary_inputs = defaultdict(set)       # sn -> set of boundary values used by its ops
    state_reads_in_sn = defaultdict(set)     # sn -> set of state object indices read
    for op in ops:
        op_id = op[0]
        sn = resolved_sn[op_part[op_id]]
        for u in op[4]:
            if is_boundary[u]:
                consumers[u].append(op_id)
                if sn:
                    boundary_inputs[sn].add(u)
        if sn and op[1] and strings[op[1] - 1] == "core.state.read":
            refs = op[6]
            if refs and refs[0][0] == "state":
                state_reads_in_sn[sn].add(refs[0][1])
    print(f"passes done: {time.time() - t0:.1f}s; supernodes with boundary inputs={len(boundary_inputs)}",
          flush=True)

    # --- dyn log ---
    act = {}
    sn_re = re.compile(r"\] sn (\d+) act=(\d+)")
    with open(args.dyn_log) as fh:
        for line in fh:
            m = sn_re.search(line)
            if m:
                act[int(m.group(1))] = int(m.group(2))
    print(f"dyn log sn entries={len(act)}")

    # --- per-boundary-value cone analysis ---
    skip_reason = Counter()
    cone_size_hist = Counter()
    xcount_hist = Counter()
    satisfy_class = Counter()       # all / some / none / no_consumers
    elim_relaxed = 0
    elim_strict = 0
    elim_prod_kind = Counter()
    elim_cone_size = Counter()
    elim_leaf_stats = Counter()
    save_relaxed = save_strict = 0
    clone_cost_strict = 0
    clone_cost_relaxed = 0
    partial_count = 0
    partial_act_sum = 0
    n_boundary = 0
    # corrected model: dead cone in S also stops evaluating -> +(cone_ops)*act(S)
    save2_strict = 0
    cost2_strict = 0
    profitable_vals = 0
    profitable_net2 = 0
    profitable_save2 = 0
    profitable_cost2 = 0
    const_only = 0
    const_only_save = 0

    for v in range(1, n_values + 1):
        if not is_boundary[v]:
            continue
        n_boundary += 1
        pid = producer[v]
        if not pid:
            skip_reason["no_producer"] += 1
            continue
        op = ops[pid - 1]
        name = strings[op[1] - 1]
        if not name.startswith("core.compute.") or op[6]:
            skip_reason["producer_not_pure_compute:" + name] += 1
            continue
        if name in ("core.compute.sliceDynamic", "core.compute.sliceArray"):
            skip_reason["producer_dyn_slice"] += 1
            continue
        S = resolved_sn[op_part[pid]]
        if not S:
            skip_reason["producer_not_in_supernode"] += 1
            continue
        # build cone
        cone_ops = {pid}
        leaves_b = set()
        leaves_s = set()   # state object indices
        bad_leaf = 0
        has_dyn = 0
        too_big = 0
        stack = list(op[4])
        while stack and not too_big and not bad_leaf and not has_dyn:
            u = stack.pop()
            pu = producer[u]
            if not pu:
                bad_leaf = 1  # graph input or undriven
                continue
            uop = ops[pu - 1]
            uname = strings[uop[1] - 1]
            if resolved_sn[op_part[pu]] != S:
                if slot_kind[u] == 2:
                    leaves_b.add(u)
                else:
                    bad_leaf = 1  # produced elsewhere but not boundary: cannot source in X
                continue
            if uname in ("core.compute.sliceDynamic", "core.compute.sliceArray"):
                has_dyn = 1
                continue
            if uname == "core.state.read":
                refs = uop[6]
                leaves_s.add(refs[0][1] if refs and refs[0][0] == "state" else -1)
                continue
            if not uname.startswith("core.compute.") or uop[6]:
                bad_leaf = 1  # memRead, dpi, system, ...
                continue
            if slot_kind[u] != 1:
                if slot_kind[u] == 2:
                    leaves_b.add(u)  # in-S boundary intermediate
                else:
                    bad_leaf = 1    # object storage of non-state origin
                continue
            if pu in cone_ops:
                continue
            cone_ops.add(pu)
            if len(cone_ops) > MAX_CONE:
                too_big = 1
                continue
            stack.extend(uop[4])
        if bad_leaf:
            skip_reason["bad_leaf"] += 1
            continue
        if has_dyn:
            skip_reason["has_dyn_slice"] += 1
            continue
        if too_big:
            skip_reason["too_big"] += 1
            continue
        cone_size_hist[len(cone_ops)] += 1

        # consumers
        xs = set()
        has_commit = 0
        has_endpoint = 0
        for cid in consumers.get(v, ()):
            cpart = op_part[cid]
            csn = resolved_sn[cpart]
            if resolved_phase[cpart] == PHASE_COMMIT:
                has_commit = 1
            elif not csn:
                has_endpoint = 1
            elif csn != S:
                xs.add(csn)
        xc = len(xs)
        xcount_hist[xc if xc <= 8 else ("9-32" if xc <= 32 else ">32")] += 1
        n_sat = 0
        n_sat_strict = 0
        for X in xs:
            xin = boundary_inputs.get(X, ())
            if leaves_b.issubset(xin):
                n_sat += 1
                xreads = state_reads_in_sn.get(X, ())
                if leaves_s.issubset(xreads):
                    n_sat_strict += 1
        if not xs:
            satisfy_class["no_compute_consumers"] += 1
        elif n_sat == xc:
            satisfy_class["all"] += 1
        elif n_sat:
            satisfy_class["some"] += 1
        else:
            satisfy_class["none"] += 1

        blocked = has_commit or has_endpoint
        fully_relaxed = not blocked and (not xs or n_sat == xc)
        fully_strict = not blocked and (not xs or n_sat_strict == xc)
        if fully_relaxed:
            elim_relaxed += 1
            a = act.get(S, 0)
            save_relaxed += a
            cone_n = len(cone_ops)
            clone_cost_relaxed += cone_n * sum(act.get(X, 0) for X in xs)
        if fully_strict:
            elim_strict += 1
            elim_prod_kind[name] += 1
            elim_cone_size[len(cone_ops)] += 1
            elim_leaf_stats["boundary_leaves"] += len(leaves_b)
            elim_leaf_stats["state_leaves"] += len(leaves_s)
            a = act.get(S, 0)
            save_strict += a
            cone_n = len(cone_ops)
            sum_act_x = sum(act.get(X, 0) for X in xs)
            clone_cost_strict += cone_n * sum_act_x
            net2 = (4 + cone_n) * a - cone_n * sum_act_x
            save2_strict += (4 + cone_n) * a
            cost2_strict += cone_n * sum_act_x
            if net2 > 0:
                profitable_vals += 1
                profitable_net2 += net2
                profitable_save2 += (4 + cone_n) * a
                profitable_cost2 += cone_n * sum_act_x
            if not leaves_b and not leaves_s:
                const_only += 1
                const_only_save += 4 * a
        elif not blocked and xs and n_sat and n_sat < xc:
            partial_count += 1
            partial_act_sum += act.get(S, 0)

    print("\n== [1] candidates & cones ==")
    print(f"boundary values={n_boundary}")
    for reason, cnt in skip_reason.most_common(15):
        print(f"{cnt:>9} skip {reason}")
    n_cand = sum(cone_size_hist.values())
    print(f"cone-built candidates={n_cand}")
    print("cone size hist: " + " ".join(f"{s}={cone_size_hist.get(s, 0)}" for s in range(1, MAX_CONE + 1)))

    print("\n== [2] consumer-supernode leaf-superset satisfaction ==")
    print("consumer-sn count hist: " +
          " ".join(f"{b}={xcount_hist.get(b, 0)}" for b in (0, 1, 2, 3, 4, 5, 6, 7, 8, "9-32", ">32")))
    for cls in ("all", "some", "none", "no_compute_consumers"):
        print(f"{satisfy_class.get(cls, 0):>9} {cls}")

    print("\n== [3] fully eliminable values ==")
    print(f"relaxed (boundary leaves only): {elim_relaxed}")
    print(f"strict  (+ state leaves readable in X): {elim_strict}")
    print("strict: producer op kinds (top 10):")
    for name, cnt in elim_prod_kind.most_common(10):
        print(f"{cnt:>9} {name}")
    print("strict: cone size hist: " +
          " ".join(f"{s}={elim_cone_size.get(s, 0)}" for s in range(1, MAX_CONE + 1)))
    print(f"strict: leaf totals {dict(elim_leaf_stats)}")

    print("\n== [4] dynamic estimate (instr-equivalents) ==")
    print(f"partial (>=1 X satisfied, not all, no commit/endpoint): {partial_count} values, "
          f"act-sum={partial_act_sum}")
    print(f"relaxed: save={save_relaxed} writebacks (~{4 * save_relaxed} instr), "
          f"clone cost={clone_cost_relaxed} -> net={4 * save_relaxed - clone_cost_relaxed}")
    print(f"strict:  save={save_strict} writebacks (~{4 * save_strict} instr), "
          f"clone cost={clone_cost_strict} -> net={4 * save_strict - clone_cost_strict}")
    print(f"baseline writebacks=22.1G/run; total run ~242G cycles")
    net = 4 * save_strict - clone_cost_strict
    print(f"strict net as share of 242G cycles: {100.0 * net / 242e9:.3f}%")
    print("\ncorrected model incl. dead-cone removal in S "
          "(save=(4+cone_ops)*act(S), cost=cone_ops*sum(act(X))):")
    net2_all = save2_strict - cost2_strict
    print(f"strict all-eliminable: save={save2_strict} cost={cost2_strict} net={net2_all} "
          f"({100.0 * net2_all / 242e9:.3f}% of cycles)")
    print(f"per-value profitable subset: values={profitable_vals} "
          f"save={profitable_save2} cost={profitable_cost2} net={profitable_net2} "
          f"({100.0 * profitable_net2 / 242e9:.3f}% of cycles)")
    print(f"leaf-free (constant-like) cones: {const_only} values, writeback save ~{const_only_save} instr")
    print(f"\ntotal runtime: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
