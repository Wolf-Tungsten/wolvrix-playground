"""Census: feasibility of fusing same-condition 1-bit bitSelect groups into word ops.

Model: bitSelect(mask, whenSet, whenClear) with 1-bit two-state result. A group is
all bitSelect ops sharing the same mask ValueId, size >= 2. A group is fusable when
  - every whenSet  is sliceStatic(A, i, i) of one common source A, bits distinct,
  - every whenClear is sliceStatic(B, i, i) of one common source B, same bit index,
  - every result has exactly one consumer, all in one core.compute.concat,
  - inside that concat (operands MSB-first) the results occupy a contiguous span
    whose bit indices descend consecutively (gather of A[hi:lo]/B[hi:lo]).
Fusion then replaces k bitSelects + (maybe) the concat with
  mux(mask, slice(A, lo, hi), slice(B, lo, hi))   (1-bit cond selects whole words).

Parsing conventions follow scripts/grhsim_op_mix_stats.py (op[1]=name sid,
op[4]=operands, op[5]=results; type[2]=kind, type[3]=width, type[5]=domain).
"""

import argparse
from array import array
from collections import Counter, defaultdict
import json
from pathlib import Path
import time


def span_bucket(w):
    if w == 2:
        return "2"
    if w <= 8:
        return "3-8"
    if w <= 16:
        return "9-16"
    if w <= 32:
        return "17-32"
    if w <= 64:
        return "33-64"
    return ">64"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path,
                        default=Path("ptmp/no00055_init_zero_elide_20260922/flow-final/xiangshan_grhsim_ir.json"))
    args = parser.parse_args()

    t0 = time.time()
    model = json.loads(args.model.read_bytes())
    print(f"json load: {time.time() - t0:.1f}s", flush=True)
    strings, types, values, ops = model["strings"], model["types"], model["values"], model["operations"]

    n_types = max(t[0] for t in types)
    t_kind = [""] * (n_types + 1)
    t_width = array("I", [0]) * (n_types + 1)
    t_2s = bytearray(n_types + 1)
    for t in types:
        t_kind[t[0]] = t[2]
        t_width[t[0]] = t[3]
        if t[2] == "logic" and t[5] == "2-state":
            t_2s[t[0]] = 1

    n_values = len(values)
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

    sid_of = {s: i + 1 for i, s in enumerate(strings)}
    ID_SLICE_START = sid_of["sliceStart"]
    ID_SLICE_END = sid_of["sliceEnd"]
    ID_BITSELECT = sid_of["core.compute.bitSelect"]
    ID_CONCAT = sid_of["core.compute.concat"]
    ID_SLICE = sid_of["core.compute.sliceStatic"]

    producer = array("I", [0]) * (n_values + 1)
    for op in ops:
        for v in op[5]:
            producer[v] = op[0]
    assert ops[0][0] == 1 and ops[-1][0] == len(ops)

    # sliceStatic value -> (source value, start, end); also (source,start,end) -> value
    slice_of_value = {}
    slice_by_range = {}
    n_slice_ops = 0
    for op in ops:
        if op[1] != ID_SLICE or len(op[4]) != 1 or len(op[5]) != 1:
            continue
        start = end = None
        for p in op[7]:
            if p[1] != "int":
                continue
            if p[0] == ID_SLICE_START:
                start = p[2]
            elif p[0] == ID_SLICE_END:
                end = p[2]
        if start is None or end is None or start < 0 or end < start:
            continue
        n_slice_ops += 1
        result = op[5][0]
        slice_of_value[result] = (op[4][0], start, end)
        slice_by_range.setdefault((op[4][0], start, end), result)
    print(f"sliceStatic ops: {n_slice_ops}")

    # collect bitSelect groups by mask
    groups = defaultdict(list)  # mask -> [(op_id, set, clear, result)]
    n_bs = n_bs_wide = 0
    for op in ops:
        if op[1] != ID_BITSELECT or len(op[4]) != 3 or len(op[5]) != 1:
            continue
        result = op[5][0]
        if not v_2s[result]:
            continue
        if v_width[result] != 1:
            n_bs_wide += 1
            continue
        n_bs += 1
        groups[op[4][0]].append((op[0], op[4][1], op[4][2], result))
    groups = {m: g for m, g in groups.items() if len(g) >= 2}
    n_grouped = sum(len(g) for g in groups.values())
    print(f"1-bit two-state bitSelect: {n_bs} (wider skipped: {n_bs_wide}); "
          f"groups(>=2): {len(groups)} covering {n_grouped} ops")

    # consumers of grouped bitSelect results
    marked = bytearray(n_values + 1)
    for g in groups.values():
        for _op_id, _s, _c, result in g:
            marked[result] = 1
    consumers = defaultdict(list)  # value -> [consumer op_id] (one per operand occurrence)
    for op in ops:
        op_id = op[0]
        for v in op[4]:
            if marked[v]:
                consumers[v].append(op_id)
    print(f"passes done: {time.time() - t0:.1f}s", flush=True)

    # ---- group classification ----
    cat = Counter()          # category -> groups
    cat_ops = Counter()      # category -> ops
    exclusion = Counter()    # primary reason -> groups
    exclusion_ops = Counter()
    set_nonslice_producer = Counter()    # producer op kind of non-slice whenSet
    clear_nonslice_producer = Counter()
    consumer_kind = Counter()            # consumer op kind of grouped results
    groups_results_all_concat = 0        # regardless of branch structure
    all_concat_ops = 0
    all_concat_sizes = Counter()
    fused_groups = []
    src_class = Counter()    # (set_single, clear_single) among all-slice groups

    for mask, g in groups.items():
        k = len(g)
        set_info = [slice_of_value.get(s) for _o, s, _c, _r in g]
        clear_info = [slice_of_value.get(c) for _o, _s, c, _r in g]
        set_all_slice = all(i is not None for i in set_info)
        clear_all_slice = all(i is not None for i in clear_info)

        def single_source_unique(infos):
            if not all(i is not None for i in infos):
                return None
            srcs = {i[0] for i in infos}
            bits = [i[1] for i in infos]
            one_bit = all(i[1] == i[2] for i in infos)
            return (len(srcs) == 1 and one_bit and len(set(bits)) == len(bits),
                    next(iter(srcs)) if len(srcs) == 1 else None)

        if set_all_slice and clear_all_slice:
            s_ok = single_source_unique(set_info)
            c_ok = single_source_unique(clear_info)
            src_class[(bool(s_ok and s_ok[0]), bool(c_ok and c_ok[0]))] += 1

        for i, (_o, s, c, _r) in enumerate(g):
            if set_info[i] is None:
                pid = producer[s]
                set_nonslice_producer[strings[ops[pid - 1][1] - 1] if pid else "<input/undriven>"] += 1
            if clear_info[i] is None:
                pid = producer[c]
                clear_nonslice_producer[strings[ops[pid - 1][1] - 1] if pid else "<input/undriven>"] += 1
        all_concat = True
        for _o, _s, _c, r in g:
            cl = consumers.get(r, [])
            if len(cl) != 1 or ops[cl[0] - 1][1] != ID_CONCAT:
                all_concat = False
            for cid0 in cl:
                consumer_kind[strings[ops[cid0 - 1][1] - 1]] += 1
        if all_concat:
            groups_results_all_concat += 1
            all_concat_ops += k
            all_concat_sizes[k if k <= 8 else ("9-32" if k <= 32 else ("33-64" if k <= 64 else ">64"))] += 1

        reason = None
        if not set_all_slice:
            reason = "whenSet_not_all_slice"
        elif not clear_all_slice:
            reason = "whenClear_not_all_slice"
        else:
            s_ok = single_source_unique(set_info)
            c_ok = single_source_unique(clear_info)
            if not (s_ok and s_ok[0]) or not (c_ok and c_ok[0]):
                reason = "multi_source_or_dup_bits"
            elif any(s_i[1] != c_i[1] for s_i, c_i in zip(set_info, clear_info)):
                reason = "set_clear_bit_mismatch"
            else:
                src_a, src_b = s_ok[1], c_ok[1]
                # consumers: every result exactly one consumer, all concat
                cons_lists = [consumers.get(r, []) for _o, _s, _c, r in g]
                if any(len(cl) != 1 for cl in cons_lists):
                    reason = "result_multi_use_or_dead"
                elif any(ops[cl[0] - 1][1] != ID_CONCAT for cl in cons_lists):
                    reason = "result_not_concat_consumed"
                else:
                    cids = {cl[0] for cl in cons_lists}
                    if len(cids) != 1:
                        reason = "split_across_concats"
                    else:
                        cid = next(iter(cids))
                        cat_op = ops[cid - 1]
                        cat_operands = cat_op[4]
                        pos = {}
                        bad = False
                        for idx, v in enumerate(cat_operands):
                            if marked[v]:
                                if v in pos:
                                    bad = True
                                pos.setdefault(v, idx)
                        if bad or len(pos) != k:
                            reason = "concat_operand_mismatch"
                        else:
                            order = sorted(pos.values())
                            contiguous = order[-1] - order[0] + 1 == k
                            # operand list runs MSB-first: bits must descend by 1
                            bits_by_pos = sorted(((pos[r], set_info[i][1])
                                                  for i, (_o, _s, _c, r) in enumerate(g)))
                            descending = all(bits_by_pos[j][1] - bits_by_pos[j + 1][1] == 1
                                             for j in range(k - 1))
                            if not contiguous or not descending:
                                reason = "concat_bit_order_bad"
                            else:
                                hi = bits_by_pos[0][1]
                                lo = bits_by_pos[-1][1]
                                fused_groups.append((mask, g, cid, src_a, src_b, lo, hi))
                                continue
        exclusion[reason] += 1
        exclusion_ops[reason] += k

    print(f"\n== [1] group composition (all-slice groups, by single-source-ness) ==")
    n_all_slice = sum(src_class.values())
    print(f"groups where BOTH branches are all 1-bit sliceStatic: {n_all_slice} / {len(groups)}")
    for (s_ok, c_ok), cnt in sorted(src_class.items()):
        print(f"  set_single={s_ok} clear_single={c_ok}: {cnt}")

    print(f"\n== [2] fusable groups ==")
    n_fused = len(fused_groups)
    fused_ops = sum(len(g) for _m, g, _c, _a, _b, _l, _h in fused_groups)
    span_widths = Counter()
    concat_widths = Counter()
    concat_die = 0
    slices_needed = 0
    slices_reused = 0
    for mask, g, cid, src_a, src_b, lo, hi in fused_groups:
        span = hi - lo + 1
        span_widths[span_bucket(span)] += 1
        cat_op = ops[cid - 1]
        rw = v_width[cat_op[5][0]] if cat_op[5] else 0
        concat_widths[span_bucket(rw) if rw else 0] += 1
        if len(cat_op[4]) == len(g):
            concat_die += 1
        for src in (src_a, src_b):
            if lo == 0 and hi + 1 == v_width[src]:
                slices_reused += 1  # the source itself, no slice needed
            elif (src, lo, hi) in slice_by_range:
                slices_reused += 1
            else:
                slices_needed += 1
    print(f"fusable groups: {n_fused} covering bitSelect ops: {fused_ops}")
    print("fused span width (resulting mux width): " +
          " ".join(f"{b}={span_widths.get(b, 0)}" for b in ("2", "3-8", "9-16", "17-32", "33-64", ">64")))
    print("gather concat result width: " +
          " ".join(f"{b}={concat_widths.get(b, 0)}" for b in ("2", "3-8", "9-16", "17-32", "33-64", ">64")))
    print(f"concat fully covered by group (concat dies): {concat_die}")
    print(f"branch slice A/B[hi:lo]: reuse existing/full-width={slices_reused}, need new slice={slices_needed}")

    print(f"\n== [3] exclusion reasons (primary, in check order) ==")
    for reason, cnt in exclusion.most_common():
        print(f"{cnt:>8} groups {exclusion_ops[reason]:>8} ops  {reason}")

    print(f"\n== [3b] what the non-slice branch operands actually are ==")
    print("whenSet non-slice producers (top 12):")
    for name, cnt in set_nonslice_producer.most_common(12):
        print(f"{cnt:>9} {name}")
    print("whenClear non-slice producers (top 12):")
    for name, cnt in clear_nonslice_producer.most_common(12):
        print(f"{cnt:>9} {name}")
    print(f"groups whose results are ALL single-use concat-consumed (any branch shape): "
          f"{groups_results_all_concat} / {len(groups)}, covering {all_concat_ops} ops")
    print("  group size mix: " +
          " ".join(f"{b}={all_concat_sizes.get(b, 0)}" for b in (2, 3, 4, 5, 6, 7, 8, "9-32", "33-64", ">64")))
    print("result consumer op kinds (top 12):")
    for name, cnt in consumer_kind.most_common(12):
        print(f"{cnt:>9} {name}")

    print(f"\n== [4] net op change estimate ==")
    removed_bs = fused_ops
    added_mux = n_fused
    removed_concat = concat_die
    optimistic = removed_bs + removed_concat - added_mux
    conservative = optimistic - slices_needed
    print(f"remove {removed_bs} bitSelect + up to {removed_concat} concat; "
          f"add {added_mux} wide mux + up to {slices_needed} sliceStatic")
    print(f"net op reduction upper bound: {optimistic} (optimistic, slices reused)")
    print(f"net op reduction conservative: {conservative} (new branch slices counted)")
    print(f"\ntotal runtime: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
