"""Estimate foldable boolean-cone coverage for a candidate LUT op on a GrhSIM model.

A foldable cone is a connected subgraph of 1-bit two-state pure compute ops
(and/or/xor/xnor/not/logicAnd/logicOr/logicNot/mux/bitSelect/eq/ne) whose
non-constant input count fits the LUT index budget. Constant operands are
absorbed into the truth table and do not consume index bits. The cone is only
worth folding when its internal op count m is superlinear in its input count
n: the emitted LUT costs ~2n index-assembly instructions plus one table read,
while each folded op costs several instructions including frame traffic.

The selection pass is greedy: roots are considered by descending score
(m - 2*n), already-claimed ops cannot join a second cone, and internal ops
are absorbed only while all users of their result stay inside the cone (no
duplication). This mirrors the intended grhsim.lut-fold pass semantics.
"""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path


BIT_OPS_BINARY = {
    "core.compute.and", "core.compute.or", "core.compute.xor", "core.compute.xnor",
    "core.compute.logicAnd", "core.compute.logicOr", "core.compute.eq", "core.compute.ne",
}
BIT_OPS_UNARY = {"core.compute.not", "core.compute.logicNot"}
BIT_OPS_SELECT = {"core.compute.mux", "core.compute.bitSelect"}
BIT_OPS = BIT_OPS_BINARY | BIT_OPS_UNARY | BIT_OPS_SELECT
CONSTANT_OP = "core.compute.constant"
SLICE_OPS = {"core.compute.sliceStatic", "core.compute.bitSelect"}
WIDE_OPS = {
    "core.compute.and", "core.compute.or", "core.compute.xor", "core.compute.xnor",
    "core.compute.not", "core.compute.eq", "core.compute.ne",
    "core.compute.lt", "core.compute.le", "core.compute.gt", "core.compute.ge",
    "core.compute.add", "core.compute.sub",
    "core.compute.mux", "core.compute.bitSelect",
}
WIDE_MAX_INPUT_BITS = 6
WIDE_TABLE_BITS = 64

# Per-kind dynamic execution counts from the NO00036 instrumented 100k run
# (ptmp/no00036_dynamic_coverage_20260916/dyn-analysis.log), and the static
# candidate op counts of that same model where available.
DYN_EXEC = {
    "core.compute.and": 26026100203,
    "core.compute.mux": 21783642541,
    "core.compute.or": 21338966498,
    "core.compute.eq": 6720238469,
    "core.compute.bitSelect": 5391868563,
    "core.compute.not": 3395849845,
    "core.compute.logicNot": 2502835032,
    "core.compute.xor": 333088675,
    "core.compute.logicAnd": 130587338,
    "core.compute.ne": 116764886,
    "core.compute.xnor": 0,
}
DYN_TOTAL_PER_EVAL = 574636.5
DYN_EVALS = 200102


def table_bytes(n: int) -> int:
    if n <= 6:
        return 8  # uint64 immediate, no rodata
    return 1 << (n - 3)  # bitplane bytes for n in {7, 8}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True,
                        help="mapped xiangshan_grhsim_ir.json checkpoint")
    parser.add_argument("--max-inputs", type=int, default=8,
                        help="LUT index bit budget (default 8)")
    parser.add_argument("--min-ops", type=int, default=3,
                        help="minimum cone size m to fold (default 3)")
    parser.add_argument("--ratio", type=float, default=2.0,
                        help="fold only when m >= ratio * n as well (default 2.0)")
    parser.add_argument("--select", action="store_true",
                        help="run the greedy non-overlapping selection pass")
    parser.add_argument("--cross", action="store_true",
                        help="report supernode crossings and internalized boundary values")
    parser.add_argument("--min-crossing", type=int, default=0,
                        help="fold only cones internalizing >= N boundary values (needs mapping)")
    parser.add_argument("--tables", action="store_true",
                        help="compute truth tables (bitmask-evaluated) and dedup statistics")
    parser.add_argument("--group", action="store_true",
                        help="simulate union-clustered multi-output LUT grouping on the selection")
    parser.add_argument("--concat-sinks", action="store_true",
                        help="survey pack-bit concat sinks and adjacent-lane LUT segment grouping")
    parser.add_argument("--profit-gate", action="store_true",
                        help="apply per-cone mapping-aware profitability gates during selection")
    parser.add_argument("--wide-cones", action="store_true",
                        help="survey small-width (2-8 bit) multi-bit LUT cones")
    args = parser.parse_args()
    if args.max_inputs <= 0:
        parser.error("--max-inputs must be positive")

    model = json.loads(args.model.read_bytes())
    strings = model["strings"]
    ops = model["operations"]
    values = model["values"]
    types = {t[0]: t for t in model["types"]}

    bit_value = bytearray(len(values) + 1)
    for value in values:
        t = types[value[1]]
        if t[2] == "logic" and t[3] == 1 and t[5] == "2-state":
            bit_value[value[0]] = 1

    op_names = [strings[op[1] - 1] for op in ops]
    operands_of = [op[4] for op in ops]
    results_of = [op[5] for op in ops]

    producer = [0] * (len(values) + 1)
    for index, results in enumerate(results_of):
        for value in results:
            producer[value] = index + 1  # 1-based op ordinal

    is_const1 = bytearray(len(ops) + 1)
    candidate = bytearray(len(ops) + 1)
    const_value = {}

    def parse_const(parameters) -> int:
        for entry in parameters:
            if len(entry) != 3:
                continue
            _name_id, tag, wrapped = entry
            if tag == "int":
                return int(wrapped) & 1
            if tag == "bool":
                return int(wrapped)
            if tag == "string":
                text = str(wrapped).strip().lstrip("-").replace("_", "").lower()
                # Two-state projection: X/Z bits flatten to zero.
                text = text.replace("x", "0").replace("z", "0")
                if "'" in text:
                    _base, digits = text.split("'", 1)
                    if digits.startswith("h"):
                        return int(digits[1:] or "0", 16) & 1
                    if digits.startswith("d"):
                        return int(digits[1:] or "0") & 1
                    if digits.startswith("b"):
                        return int(digits[1:] or "0", 2) & 1
                    if digits.startswith("o"):
                        return int(digits[1:] or "0", 8) & 1
                    if digits.startswith("s") and len(digits) > 1:
                        return int(digits[2:] or "0", 16) & 1
                return int(text, 0) & 1
        return 0

    for index, name in enumerate(op_names):
        ordinal = index + 1
        if name == CONSTANT_OP:
            results = results_of[index]
            if len(results) == 1 and bit_value[results[0]]:
                is_const1[ordinal] = 1
                if args.tables:
                    const_value[results[0]] = parse_const(ops[index][7])
            continue
        if name not in BIT_OPS:
            continue
        results = results_of[index]
        if len(results) != 1 or not bit_value[results[0]]:
            continue
        if all(bit_value[v] for v in operands_of[index]):
            candidate[ordinal] = 1

    candidate_total = sum(candidate)
    print(f"total_ops={len(ops)} values={len(values)} candidate_bit_ops={candidate_total}")

    # Users are only needed for values produced by candidate ops.
    users = defaultdict(list)
    for index in range(len(ops)):
        ordinal = index + 1
        for v in operands_of[index]:
            p = producer[v]
            if p and candidate[p]:
                users[v].append(ordinal)

    boundary_value = bytearray(len(values) + 1)
    if (args.min_crossing > 0 or args.cross or args.group
            or args.concat_sinks or args.profit_gate):
        payload = model["mappings"][0][-1]
        for idx, slot in enumerate(payload[3][3]):
            if slot[1] == 2:
                boundary_value[idx + 1] = 1

    op_supernode_cache = {}

    def op_supernode_map():
        if "map" in op_supernode_cache:
            return op_supernode_cache["map"]
        partitions = model["mappings"][0][-1][2]
        by_id = {part[0]: part for part in partitions}

        def subtree_ops(root_id):
            result = []
            stack = [root_id]
            while stack:
                part = by_id[stack.pop()]
                result.extend(part[5])
                stack.extend(part[4])
            return result

        mapping = {}
        for part in partitions:
            if part[2] != 3:
                continue
            for op_id in subtree_ops(part[0]):
                mapping[op_id] = part[0]
        op_supernode_cache["map"] = mapping
        return mapping

    def non_const_count(boundary) -> int:
        count = 0
        for v in boundary:
            p = producer[v]
            if not (p and is_const1[p]):
                count += 1
        return count

    def grow(root: int, claimed=None):
        """Greedy fixpoint cone expansion from root; returns (cone, boundary, n) or None."""
        if claimed is not None and claimed[root]:
            return None
        cone = {root}
        cone_values = set(results_of[root - 1])
        boundary = set()
        for v in operands_of[root - 1]:
            boundary.add(v)
        queue = list(boundary)
        failed = []
        while queue:
            v = queue.pop()
            if v not in boundary:
                continue
            p = producer[v]
            if p and is_const1[p]:
                boundary.discard(v)  # absorb constant into the truth table
                continue
            if (not p or not candidate[p] or p in cone
                    or (claimed is not None and claimed[p])):
                continue  # boundary stays
            us = users.get(v)
            if us and any(u not in cone for u in us):
                continue  # shared value stays a cone input
            prospective = (boundary - {v}) | (set(operands_of[p - 1]) - cone_values)
            if sum(1 for w in prospective
                   if not (producer[w] and is_const1[producer[w]])) > args.max_inputs:
                continue  # index budget exceeded
            boundary = prospective
            cone.add(p)
            cone_values.update(results_of[p - 1])
            queue.extend(w for w in operands_of[p - 1] if w in boundary)
            queue.extend(failed)
            failed.clear()
        n = non_const_count(boundary)
        return cone, boundary, n

    def non_const_inputs(boundary):
        return frozenset(v for v in boundary
                         if not (producer[v] and is_const1[producer[v]]))

    def run_wide_cones():
        """Survey small-width (2-8 bit) two-state unsigned multi-bit LUT cones."""
        wide_width = [0] * (len(values) + 1)
        for value in values:
            t = types[value[1]]
            if (t[2] == "logic" and 2 <= t[3] <= 8 and not t[4]
                    and t[5] == "2-state"):
                wide_width[value[0]] = t[3]

        is_const_wide = bytearray(len(ops) + 1)
        wide_candidate = bytearray(len(ops) + 1)
        for index, name in enumerate(op_names):
            ordinal = index + 1
            if name == CONSTANT_OP:
                results = results_of[index]
                if len(results) == 1 and wide_width[results[0]]:
                    is_const_wide[ordinal] = 1
                continue
            if name not in WIDE_OPS:
                continue
            results = results_of[index]
            if len(results) != 1 or not wide_width[results[0]]:
                continue
            if all(wide_width[v] for v in operands_of[index]):
                wide_candidate[ordinal] = 1

        wide_total = sum(wide_candidate)
        wide_users = defaultdict(list)
        for index in range(len(ops)):
            ordinal = index + 1
            for v in operands_of[index]:
                p = producer[v]
                if p and wide_candidate[p]:
                    wide_users[v].append(ordinal)

        def wide_bits(boundary):
            return sum(wide_width[v] for v in boundary
                       if not (producer[v] and is_const_wide[producer[v]]))

        def grow_wide(root, claimed=None):
            if claimed is not None and claimed[root]:
                return None
            cone = {root}
            cone_values = set(results_of[root - 1])
            boundary = set(operands_of[root - 1])
            queue = list(boundary)
            while queue:
                v = queue.pop()
                if v not in boundary:
                    continue
                p = producer[v]
                if p and is_const_wide[p]:
                    boundary.discard(v)  # absorb constant into the truth table
                    continue
                if (not p or not wide_candidate[p] or p in cone
                        or (claimed is not None and claimed[p])):
                    continue
                us = wide_users.get(v)
                if us and any(u not in cone for u in us):
                    continue
                prospective = (boundary - {v}) | (set(operands_of[p - 1]) - cone_values)
                if wide_bits(prospective) > WIDE_MAX_INPUT_BITS:
                    continue
                boundary = prospective
                cone.add(p)
                cone_values.update(results_of[p - 1])
                queue.extend(w for w in operands_of[p - 1] if w in boundary)
            n_bits = wide_bits(boundary)
            n_vals = sum(1 for v in boundary
                         if not (producer[v] and is_const_wide[producer[v]]))
            k = wide_width[results_of[root - 1][0]]
            return cone, n_bits, n_vals, k

        def acceptable(n_bits, k):
            return (n_bits <= WIDE_MAX_INPUT_BITS
                    and (1 << n_bits) * k <= WIDE_TABLE_BITS)

        # Pass 1: overlap allowed.
        shapes = []
        for ordinal in range(1, len(ops) + 1):
            if not wide_candidate[ordinal]:
                continue
            cone, n_bits, n_vals, k = grow_wide(ordinal)
            if acceptable(n_bits, k):
                shapes.append((len(cone), n_bits, n_vals, k, ordinal))

        # Pass 2: greedy non-overlapping selection by descending score (m - 2*n_bits).
        shapes.sort(key=lambda item: (-(item[0] - 2 * item[1]), item[4]))
        claimed_w = bytearray(len(ops) + 1)
        selected_w = []
        for _m, _nb, _nv, _k, root in shapes:
            if claimed_w[root]:
                continue
            result = grow_wide(root, claimed_w)
            if result is None:
                continue
            cone, n_bits, n_vals, k = result
            if not acceptable(n_bits, k):
                continue
            for member in cone:
                claimed_w[member] = 1
            selected_w.append((cone, n_bits, n_vals, k))

        sum_m = sum(len(cone) for cone, _nb, _nv, _k in selected_w)
        m_hist = Counter(len(cone) for cone, _nb, _nv, _k in selected_w)
        nbits_hist = Counter(nb for _c, nb, _nv, _k in selected_w)
        inwidth_hist = Counter()
        for cone, _nb, _nv, _k in selected_w:
            seen = set()
            for member in cone:
                for v in operands_of[member - 1]:
                    if v in seen or (producer[v] and producer[v] in cone):
                        continue
                    seen.add(v)
                    if not (producer[v] and is_const_wide[producer[v]]):
                        inwidth_hist[wide_width[v]] += 1
        k_hist = Counter(k for _c, _nb, _nv, k in selected_w)
        table_bits = sum((1 << nb) * k for _c, nb, _nv, k in selected_w)
        lut_cost = sum(3 * nv + 2 * k for _c, _nb, nv, k in selected_w)
        kind_folded_w = Counter()
        for cone, _nb, _nv, _k in selected_w:
            for member in cone:
                kind_folded_w[op_names[member - 1]] += 1

        dyn_known = 0.0
        static_w = Counter(op_names)
        ratios = []
        for name, dyn in DYN_EXEC.items():
            static = static_w.get(name, 0)
            if static:
                ratios.append(dyn / static)
        avg_ratio = sum(ratios) / max(len(ratios), 1)
        missing = Counter()
        for name, count in kind_folded_w.items():
            dyn = DYN_EXEC.get(name)
            static = static_w.get(name, 0)
            if dyn is not None and static:
                dyn_known += count * (dyn / static)
            else:
                missing[name] += count
        dyn_est = sum(count * avg_ratio for count in missing.values())
        dyn_known_pe = dyn_known / DYN_EVALS
        dyn_est_pe = dyn_est / DYN_EVALS

        print(f"\n== wide multi-bit cone survey (input bits<={WIDE_MAX_INPUT_BITS}, "
              f"table<={WIDE_TABLE_BITS} bits, unsigned 2-state 2-8b) ==")
        print(f"candidate wide ops={wide_total} "
              f"({100.0 * wide_total / max(len(ops), 1):.3f}% of all ops)")
        print(f"cones overlap-allowed={len(shapes)} greedy-selected={len(selected_w)} "
              f"folded_ops={sum_m}")
        print(f"m histogram (selected): {dict(sorted(m_hist.items()))}")
        print(f"cone input-bits histogram: {dict(sorted(nbits_hist.items()))}")
        print(f"input value width histogram: {dict(sorted(inwidth_hist.items()))}")
        print(f"output width k histogram: {dict(sorted(k_hist.items()))}")
        print(f"truth-table bits={table_bits} ({table_bits / 8.0 / 1024.0:.1f} KiB)")
        print(f"cost model: cone ops at 2 instr/op = {2 * sum_m}; "
              f"lut cost 3*nvals+2k = {lut_cost}; net={lut_cost - 2 * sum_m:+d}")
        print(f"kinds folded: {dict(sorted(kind_folded_w.items()))}")
        print(f"dyn saving per eval: known-kinds={dyn_known_pe:.1f} "
              f"({100.0 * dyn_known_pe / DYN_TOTAL_PER_EVAL:.3f}%) "
              f"+ avg-ratio estimate for {dict(sorted(missing.items()))} "
              f"={dyn_est_pe:.1f} ({100.0 * dyn_est_pe / DYN_TOTAL_PER_EVAL:.3f}%)")

    def run_concat_sinks():
        """Survey core.compute.concat sinks that pack candidate 1-bit lanes."""
        concats = []
        for index, name in enumerate(op_names):
            if name != "core.compute.concat":
                continue
            operands = operands_of[index]
            if len(operands) < 3 or not all(bit_value[v] for v in operands):
                continue
            if all(producer[v] and candidate[producer[v]] for v in operands):
                concats.append(operands)

        total_lanes = 0
        total_lane_ops = 0
        total_segments = 0
        seg_len_hist = Counter()
        seg_union_hist = Counter()
        boundary_lanes = 0
        old_cost = 0
        new_cost_units = 0  # sum over segments of (2u-1) + 2*seg_len
        for operands in concats:
            k = len(operands)
            total_lanes += k
            old_cost += 2 * (k - 1)
            cur_union = set()
            cur_len = 0
            for v in operands:
                if boundary_value[v]:
                    boundary_lanes += 1
                cone, boundary, _n = grow(producer[v])
                total_lane_ops += len(cone)
                old_cost += len(cone)
                lane_inputs = non_const_inputs(boundary)
                merged = cur_union | lane_inputs
                if cur_len and (len(merged) > args.max_inputs
                                or (1 << len(merged)) * (cur_len + 1) > 64):
                    seg_len_hist[cur_len] += 1
                    seg_union_hist[len(cur_union)] += 1
                    new_cost_units += (2 * len(cur_union) - 1) + 2 * cur_len
                    total_segments += 1
                    cur_union = set(lane_inputs)
                    cur_len = 1
                else:
                    cur_union = merged
                    cur_len += 1
            if cur_len:
                seg_len_hist[cur_len] += 1
                seg_union_hist[len(cur_union)] += 1
                new_cost_units += (2 * len(cur_union) - 1) + 2 * cur_len
                total_segments += 1

        print(f"\n== packed concat sink survey (max_inputs={args.max_inputs}) ==")
        print(f"qualifying concats={len(concats)} total_lanes={total_lanes} "
              f"(avg lanes per concat="
              f"{total_lanes / max(len(concats), 1):.2f})")
        print(f"lane cones: total_lane_ops={total_lane_ops} avg m per lane="
              f"{total_lane_ops / max(total_lanes, 1):.2f}")
        print(f"segments={total_segments} (avg lanes per segment="
              f"{total_lanes / max(total_segments, 1):.2f})")
        print(f"segment length histogram: {dict(sorted(seg_len_hist.items()))}")
        print(f"segment union-size histogram: {dict(sorted(seg_union_hist.items()))}")
        print(f"lane values that are boundary values={boundary_lanes} "
              f"({100.0 * boundary_lanes / max(total_lanes, 1):.2f}% of lanes)")
        print(f"old cost (sum lane m + 2*(k-1) per concat)={old_cost}")
        for alpha in (1.0, 0.75):
            new_cost = alpha * new_cost_units
            print(f"alpha={alpha:.2f}: new segment cost={new_cost:.0f} "
                  f"delta vs old={new_cost - old_cost:+.0f}")

    # Pass 1: per-root cone shapes (upper bound, overlap allowed).
    shape_counter = Counter()
    shape_kept = []
    min_ops = args.min_ops
    for ordinal in range(1, len(ops) + 1):
        if not candidate[ordinal]:
            continue
        result = grow(ordinal)
        if result is None:
            continue
        cone, _boundary, n = result
        m = len(cone)
        shape_counter[(n, m)] += 1
        if m >= min_ops:
            shape_kept.append((m, n, ordinal))

    print("\n== cone shape histogram (n inputs, m ops; overlap allowed) ==")
    print("(n, m) -> roots; only cells with >= 100 roots shown")
    for (n, m), count in sorted(shape_counter.items()):
        if count >= 100:
            print(f"n={n:2d} m={m:3d} roots={count}")

    if not args.select:
        if args.concat_sinks:
            run_concat_sinks()
        if args.wide_cones:
            run_wide_cones()
        return

    # Pass 2: greedy non-overlapping selection by descending score (m - 2n).
    claimed = bytearray(len(ops) + 1)
    selected = []
    shape_kept.sort(key=lambda item: -(item[0] - 2 * item[1]))
    for _m, _n, root in shape_kept:
        if claimed[root]:
            continue
        result = grow(root, claimed)
        if result is None:
            continue
        cone, boundary, n = result
        m = len(cone)
        if m < min_ops or m < args.ratio * max(n, 1):
            continue
        if args.min_crossing > 0:
            internal = sum(1 for member in cone if member != root
                           and results_of[member - 1]
                           and boundary_value[results_of[member - 1][0]])
            if internal < args.min_crossing:
                continue
        for member in cone:
            claimed[member] = 1
        selected.append((root, cone, boundary, n, m))

    folded_ops = sum(m for _r, _c, _b, _n, m in selected)
    lut_ops = len(selected)
    n_hist = Counter(n for _r, _c, _b, n, _m in selected)
    m_hist = Counter(m for _r, _c, _b, _n, m in selected)
    kind_folded = Counter()
    mux_cones = 0
    for _root, cone, _boundary, _n, _m in selected:
        has_mux = False
        for member in cone:
            name = op_names[member - 1]
            kind_folded[name] += 1
            if name in BIT_OPS_SELECT:
                has_mux = True
        if has_mux:
            mux_cones += 1
    const_absorbed = 0
    slice_inputs = 0
    input_groups = defaultdict(list)
    for index, (_root, _cone, boundary, _n, _m) in enumerate(selected):
        key = tuple(sorted(v for v in boundary
                           if not (producer[v] and is_const1[producer[v]])))
        input_groups[key].append(index)
        for v in boundary:
            p = producer[v]
            if p and is_const1[p]:
                const_absorbed += 1
            elif p and op_names[p - 1] in SLICE_OPS:
                slice_inputs += 1
    shared_groups = [g for g in input_groups.values() if len(g) >= 2]
    shared_outputs = sum(len(g) for g in shared_groups)

    total_tables = sum(table_bytes(n) for _r, _c, _b, n, _m in selected)
    est_instr_saved = sum(3 * m - (2 * n + 3) for _r, _c, _b, n, m in selected)

    print(f"\n== greedy selection (min_ops={min_ops}, ratio={args.ratio}, "
          f"max_inputs={args.max_inputs}) ==")
    print(f"cones={lut_ops} folded_ops={folded_ops} "
          f"net_op_delta={lut_ops - folded_ops} "
          f"({100.0 * folded_ops / max(candidate_total, 1):.2f}% of candidate bit ops, "
          f"{100.0 * folded_ops / len(ops):.3f}% of all ops)")
    print(f"cones containing mux/bitSelect={mux_cones}")
    print(f"const boundary inputs absorbed={const_absorbed} slice-produced inputs={slice_inputs}")
    print(f"n histogram: {dict(sorted(n_hist.items()))}")
    print(f"m histogram: {dict(sorted(m_hist.items()))}")
    print(f"shared-input multi-output groups={len(shared_groups)} outputs={shared_outputs}")
    print(f"truth-table bytes (no dedup)={total_tables} "
          f"({total_tables / 1024.0:.1f} KiB)")
    print(f"rough instruction saving estimate (3m-(2n+3)) per cone total={est_instr_saved}")

    internalized_boundary = 0
    if args.cross and selected:
        op_supernode = op_supernode_map()
        crossing = 0
        for root, cone, _boundary, _n, _m in selected:
            sns = {op_supernode.get(member) for member in cone}
            if len(sns) > 1:
                crossing += 1
            root_result = results_of[root - 1][0]
            for member in cone:
                if member == root:
                    continue
                result_value = results_of[member - 1][0]
                if boundary_value[result_value]:
                    internalized_boundary += 1
        print(f"supernode-crossing cones={crossing} "
              f"internalized boundary values={internalized_boundary} "
              f"(adjusted saving estimate={est_instr_saved + 5 * internalized_boundary})")

    if args.tables and selected:
        patterns = {}

        def input_patterns(n: int):
            if n not in patterns:
                size = 1 << n
                pats = []
                for i in range(n):
                    mask = 0
                    for j in range(size):
                        if (j >> i) & 1:
                            mask |= 1 << j
                    pats.append(mask)
                patterns[n] = (pats, (1 << size) - 1)
            return patterns[n]

        table_counter = Counter()
        lut_tables = []
        for root, cone, boundary, n, _m in selected:
            pats, full = input_patterns(n)
            inputs = sorted(v for v in boundary
                            if not (producer[v] and is_const1[producer[v]]))
            position = {v: i for i, v in enumerate(inputs)}
            masks = {}

            def value_mask(v, cone=cone, position=position, pats=pats, full=full):
                if v in masks:
                    return masks[v]
                p = producer[v]
                if p and is_const1[p]:
                    mask = full if const_value[v] else 0
                elif p and p in cone:
                    name = op_names[p - 1]
                    args_ = [value_mask(w) for w in operands_of[p - 1]]
                    if name in ("core.compute.and", "core.compute.logicAnd"):
                        mask = args_[0] & args_[1]
                    elif name in ("core.compute.or", "core.compute.logicOr"):
                        mask = args_[0] | args_[1]
                    elif name in ("core.compute.xor", "core.compute.ne"):
                        mask = args_[0] ^ args_[1]
                    elif name in ("core.compute.xnor", "core.compute.eq"):
                        mask = ~(args_[0] ^ args_[1]) & full
                    elif name in ("core.compute.not", "core.compute.logicNot"):
                        mask = ~args_[0] & full
                    elif name in ("core.compute.mux", "core.compute.bitSelect"):
                        mask = (args_[0] & args_[1]) | ((~args_[0] & full) & args_[2])
                    else:
                        raise ValueError(f"unexpected cone op {name}")
                else:
                    mask = pats[position[v]]
                masks[v] = mask
                return mask

            table = value_mask(results_of[root - 1][0])
            table_counter[(n, table)] += 1

        unique = len(table_counter)
        unique_bytes = sum(table_bytes(n) for n, _t in table_counter)
        shared = sum(1 for count in table_counter.values() if count >= 2)
        print(f"truth tables: unique={unique} of {lut_ops} "
              f"(shared by >=2 cones: {shared}); unique-table bytes={unique_bytes} "
              f"({unique_bytes / 1024.0:.1f} KiB)")

    static_by_kind = Counter(op_names)

    def dyn_saving_per_eval(kinds):
        saved = 0.0
        for name, count in kinds.items():
            dyn = DYN_EXEC.get(name)
            if dyn is None:
                continue
            static = static_by_kind.get(name, 0)
            if static:
                saved += count * (dyn / static)
        return saved / DYN_EVALS

    dyn_saved_per_eval = dyn_saving_per_eval(kind_folded)
    print(f"estimated dynamic op saving per eval={dyn_saved_per_eval:.1f} "
          f"({100.0 * dyn_saved_per_eval / DYN_TOTAL_PER_EVAL:.2f}% of dynamic compute ops) "
          f"before LUT index/lookup cost ({lut_ops} static lut ops)")

    if args.profit_gate:
        gates = [
            ("G1 m>=2n+1", lambda m, n, i: m >= 2 * n + 1),
            ("G2 m+5int>=2n+1", lambda m, n, i: m + 5 * i >= 2 * n + 1),
            ("G3 m+8int>=2n+1", lambda m, n, i: m + 8 * i >= 2 * n + 1),
            ("G4 int>=2 & m+5int>=2n+1",
             lambda m, n, i: i >= 2 and m + 5 * i >= 2 * n + 1),
        ]
        print(f"\n== mapping-aware profit gates (min_ops={min_ops}, "
              f"ratio={args.ratio}, max_inputs={args.max_inputs}) ==")
        print("(net = sum(2n+1)-sum(m), positive means instructions added; "
              "combined = net - 5*sum_int, negative means profitable)")
        for label, gate in gates:
            gclaimed = bytearray(len(ops) + 1)
            g_cones = 0
            sum_m = 0
            sum_n = 0
            sum_int = 0
            int_strata = Counter()
            n_hist_g = Counter()
            int_by_n = Counter()
            gk_kind = Counter()
            for _m, _n, root in shape_kept:
                if gclaimed[root]:
                    continue
                result = grow(root, gclaimed)
                if result is None:
                    continue
                cone, _boundary, n = result
                m = len(cone)
                if m < min_ops or m < args.ratio * max(n, 1):
                    continue
                internal = 0
                for member in cone:
                    if member != root and boundary_value[results_of[member - 1][0]]:
                        internal += 1
                if not gate(m, n, internal):
                    continue
                for member in cone:
                    gclaimed[member] = 1
                    gk_kind[op_names[member - 1]] += 1
                g_cones += 1
                sum_m += m
                sum_n += n
                sum_int += internal
                int_strata[min(internal, 3)] += 1
                n_hist_g[n] += 1
                int_by_n[n] += internal
            index_cost = 2 * sum_n + g_cones
            net1 = index_cost - sum_m
            net075 = 0.75 * index_cost - sum_m
            benefit = 5 * sum_int
            dyn_pe = dyn_saving_per_eval(gk_kind)
            print(f"{label}: cones={g_cones} sum_m={sum_m} sum_n={sum_n} "
                  f"sum_int={sum_int} net(a=1)={net1:+d} net(a=0.75)={net075:+.0f} "
                  f"combined(a=1)={net1 - benefit:+d} "
                  f"combined(a=0.75)={net075 - benefit:+.0f} "
                  f"dyn_saving_per_eval={dyn_pe:.1f} "
                  f"({100.0 * dyn_pe / DYN_TOTAL_PER_EVAL:.2f}%)")
            if label.startswith("G2"):
                print(f"  G2 int strata: int=0:{int_strata[0]} int=1:{int_strata[1]} "
                      f"int=2:{int_strata[2]} int>=3:{int_strata[3]}")
            wide_n = sum(c for nn, c in n_hist_g.items() if nn >= 7)
            wide_int = sum(i for nn, i in int_by_n.items() if nn >= 7)
            wide_bits = sum((1 << nn) * c for nn, c in n_hist_g.items() if nn >= 7)
            mem_extra = 2 * wide_n
            print(f"  n histogram: {dict(sorted(n_hist_g.items()))}; "
                  f"n>=7 cones={wide_n} (their sum_int={wide_int}); "
                  f"n>=7 table bits={wide_bits} ({wide_bits / 8.0 / 1024.0:.1f} KiB); "
                  f"rodata-mem model (+2 instr per n>=7 cone): "
                  f"combined(a=1)={net1 - benefit + mem_extra:+d} "
                  f"combined(a=0.75)={net075 - benefit + mem_extra:+.0f} "
                  f"(each +-1 instr/access shifts combined by {wide_n})")

    if args.group and selected:
        op_supernode = op_supernode_map()
        cone_inputs = [non_const_inputs(boundary)
                       for _r, _c, boundary, _n, _m in selected]
        order = sorted(range(len(selected)),
                       key=lambda i: (-selected[i][4], selected[i][0]))
        clusters = []  # each entry: [union input set, member cone indices]
        value_clusters = defaultdict(set)
        for i in order:
            inputs = cone_inputs[i]
            cand_ids = set()
            for v in inputs:
                cand_ids.update(value_clusters.get(v, ()))
            best_key = None
            best_cid = None
            for cid in cand_ids:
                union_set, members = clusters[cid]
                extra = sum(1 for v in inputs if v not in union_set)
                new_size = len(union_set) + extra
                if new_size > args.max_inputs:
                    continue
                key = (new_size, -len(members), cid)
                if best_key is None or key < best_key:
                    best_key = key
                    best_cid = cid
            if best_cid is None:
                cid = len(clusters)
                clusters.append([set(inputs), [i]])
                for v in inputs:
                    value_clusters[v].add(cid)
            else:
                union_set, members = clusters[best_cid]
                for v in inputs:
                    if v not in union_set:
                        union_set.add(v)
                        value_clusters[v].add(best_cid)
                members.append(i)

        sub_uk = []  # (union size u, member count k) per supernode sub-cluster
        cluster_size_hist = Counter()
        multi_cluster_members = 0
        same_sn_members = 0
        for union_set, members in clusters:
            cluster_size_hist[len(members)] += 1
            by_sn = defaultdict(list)
            for i in members:
                sn = op_supernode.get(selected[i][0])
                by_sn[sn if sn is not None else ("unmapped", selected[i][0])].append(i)
            if len(members) >= 2:
                multi_cluster_members += len(members)
            for group in by_sn.values():
                if len(group) > 1:
                    u = len(set().union(*(cone_inputs[i] for i in group)))
                    if len(members) >= 2:
                        same_sn_members += len(group)
                else:
                    u = len(cone_inputs[group[0]])
                sub_uk.append((u, len(group)))

        total_m = folded_ops
        k_hist = Counter(k for _u, k in sub_uk)
        u_hist = Counter(u for u, _k in sub_uk)
        internalized = 0
        for root, cone, _b, _n, _m in selected:
            for member in cone:
                if member != root and boundary_value[results_of[member - 1][0]]:
                    internalized += 1
        baseline_units = sum(2 * n + 1 for _r, _c, _b, n, _m in selected)
        clustered_units = sum((2 * u - 1) + 2 * k for u, k in sub_uk)

        print(f"\n== union-clustered multi-output LUT grouping "
              f"(max_inputs={args.max_inputs}) ==")
        print(f"selected cones={len(selected)} folded_ops={total_m} "
              f"internalized boundary values={internalized}")
        print(f"clusters={len(clusters)} "
              f"(avg members={len(selected) / max(len(clusters), 1):.2f}) "
              f"subclusters after supernode split={len(sub_uk)} "
              f"(avg k={len(selected) / max(len(sub_uk), 1):.2f} "
              f"avg u={sum(u for u, _k in sub_uk) / max(len(sub_uk), 1):.2f})")
        print(f"cluster size histogram (members per cluster): "
              f"{dict(sorted(cluster_size_hist.items()))}")
        print(f"subcluster k histogram (cones per subcluster): "
              f"{dict(sorted(k_hist.items()))}")
        print(f"subcluster union-size u histogram: {dict(sorted(u_hist.items()))}")
        print(f"cones in multi-member clusters={multi_cluster_members}; of those, "
              f"sharing supernode with >=1 cluster mate={same_sn_members} "
              f"({100.0 * same_sn_members / max(multi_cluster_members, 1):.2f}%)")
        print(f"shared-input multi-output groups={len(shared_groups)} "
              f"outputs={shared_outputs}")
        for alpha in (1.0, 0.75):
            baseline_net = alpha * baseline_units - total_m
            clustered_net = alpha * clustered_units - total_m
            print(f"alpha={alpha:.2f}: baseline net (sum a(2n+1)-m)={baseline_net:+.0f} "
                  f"clustered net (sum a((2u-1)+2k)-m)={clustered_net:+.0f} "
                  f"clustering reduction={baseline_net - clustered_net:.0f} "
                  f"clustered net - 5*internalized={clustered_net - 5 * internalized:+.0f} "
                  f"(baseline - 5*internalized={baseline_net - 5 * internalized:+.0f})")

    if args.concat_sinks:
        run_concat_sinks()

    if args.wide_cones:
        run_wide_cones()


if __name__ == "__main__":
    main()
