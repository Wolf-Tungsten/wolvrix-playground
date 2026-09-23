"""Census GrhSIM IR simplification candidate pools on the XiangShan final checkpoint.

Parsing conventions follow scripts/grhsim_op_mix_stats.py /
scripts/grhsim_algebra_residue_stats.py:
  op    = [id, opTypeStringId, name, origin, operands, results, objectRefs, parameters]
  value = [id, type, name, origin]
  type  = [id, typeRef, kind, width, isSigned, domain, elementType, count]
  state = [id, name, type, origin]
  refs  = [[kindString, index], ...]        parameters = [[nameStringId, tag, value], ...]

Semantics confirmed from wolvrix/lib/grhsim/pass/canonicalize_compute.cpp:312-380,
wolvrix/lib/grhsim/pass/pack_bit_registers.cpp and docs/grhsim_ir/passes/pack-bit-registers.md:
  - sliceStatic params sliceStart/sliceEnd are INCLUSIVE (width == end - start + 1)
  - concat operands run MSB-first (operand[0] is the most significant segment)
  - mux operands = [cond, trueValue, falseValue]
  - regWrite operands = [updateCond, nextValue, mask, events...],
    refs = [target, history per event], params = [event_edges]
"""

import argparse
from array import array
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import time


def width_bucket_slice(w):
    if w == 1:
        return "1"
    if w <= 8:
        return "2-8"
    if w <= 32:
        return "9-32"
    if w <= 64:
        return "33-64"
    return ">64"


def width_bucket_reg(w):
    if w == 1:
        return "1"
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


SV_LITERAL = re.compile(r"^(?:(\d+))?'[sS]?([bodhBODH])([0-9a-fA-FxzXZ?_]+)$")
BASES = {"b": 2, "o": 8, "d": 10, "h": 16}


def parse_sv_literal(text):
    """Parse a SystemVerilog integer literal; None if it carries X/Z/?."""
    s = text.strip().replace("_", "")
    m = SV_LITERAL.match(s)
    if m:
        digits = m.group(2 + 1).lower()
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
                        default=Path("ptmp/no00055_init_zero_elide_20260922/flow-final/xiangshan_grhsim_ir.json"))
    args = parser.parse_args()

    t0 = time.time()
    model = json.loads(args.model.read_bytes())
    print(f"json load: {time.time() - t0:.1f}s", flush=True)

    counts = model.get("counts", {})
    strings = model["strings"]
    types = model["types"]
    values = model["values"]
    ops = model["operations"]
    states = model["states"]
    inits = model["init"]
    mappings = model["mappings"]
    print(f"ops={len(ops)} values={len(values)} states={len(states)} "
          f"strings={len(strings)} types={len(types)}")

    # --- type tables (1-based dense ids) ---
    n_types = max(t[0] for t in types)
    t_kind = [""] * (n_types + 1)
    t_width = array("I", [0]) * (n_types + 1)
    t_signed = bytearray(n_types + 1)
    t_2s = bytearray(n_types + 1)  # two-state logic
    for t in types:
        tid = t[0]
        t_kind[tid] = t[2]
        t_width[tid] = t[3]
        t_signed[tid] = 1 if t[4] else 0
        if t[2] == "logic" and t[5] == "2-state":
            t_2s[tid] = 1

    # --- value tables ---
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

    # --- state tables ---
    n_states = len(states)
    s_type = array("I", [0]) * (n_states + 1)
    s_width = array("I", [0]) * (n_states + 1)
    s_2s_logic = bytearray(n_states + 1)
    s_array = bytearray(n_states + 1)
    for s in states:
        sid, tid = s[0], s[2]
        s_type[sid] = tid
        if t_kind[tid] == "logic":
            s_width[sid] = t_width[tid]
            if t_2s[tid]:
                s_2s_logic[sid] = 1
        elif t_kind[tid] == "array":
            s_array[sid] = 1

    sid_of = {s: i + 1 for i, s in enumerate(strings)}
    ID_SLICE_START = sid_of.get("sliceStart")
    ID_SLICE_END = sid_of.get("sliceEnd")
    ID_EVENT_EDGES = sid_of.get("event_edges")
    ID_VALUE = sid_of.get("value")
    ID_CONST_VALUE = sid_of.get("constValue")
    ID_INIT_CONST = sid_of.get("core.init.const")

    # --- quiescence projection (schedule is payload[4]) ---
    payload = mappings[0][-1]
    schedule = payload[4] if len(payload) > 4 else None
    if schedule is not None:
        proj_bits, proj_words = schedule[7], schedule[8]
        print(f"schedule present: projection bits={proj_bits} words={len(proj_words)}")
    else:
        proj_bits, proj_words = 0, []
        print("WARNING: no CPU schedule in mapping; quiescence projection treated as all-zero")

    def projected(sid):
        return sid < proj_bits and ((proj_words[sid >> 6] >> (sid & 63)) & 1) == 1

    # --- init values per state: known const -> int, else None ---
    init_known = {}
    for record in inits:
        sid, steps = record[0], record[1]
        if len(steps) != 1:
            continue
        kind_id, params = steps[0]
        if kind_id != ID_INIT_CONST or len(params) != 1:
            continue
        name_id, tag, value = params[0]
        if name_id != ID_VALUE:
            continue
        if tag == "string":
            parsed = parse_sv_literal(value)
        elif tag == "int":
            parsed = value
        elif tag == "bool":
            parsed = 1 if value else 0
        else:
            parsed = None
        if parsed is not None:
            init_known[sid] = parsed

    # --- pass A: producer + state references ---
    producer = array("I", [0]) * (n_values + 1)
    uses = array("I", [0]) * (n_values + 1)
    references = array("I", [0]) * (n_states + 1)
    for op in ops:
        op_id = op[0]
        for v in op[5]:
            producer[v] = op_id
        for v in op[4]:
            uses[v] += 1
        for ref in op[6]:
            if ref[0] == "state":
                references[ref[1]] += 1

    assert ops[0][0] == 1 and ops[-1][0] == len(ops), "op ids not dense"

    # --- pass B: per-op census ---
    slice_of_slice = Counter()          # width bucket -> count
    slice_of_slice_4s_skipped = 0
    slice_concat_total = 0
    slice_concat_exact_single_use = 0
    slice_concat_contained = Counter()  # width bucket -> count
    slice_concat_exact = Counter()      # slice == whole concat operand
    slice_concat_straddle = 0
    nested_concat_ops = 0
    nested_concat_edges = 0
    nested_concat_max_edges = 0
    mux_const_branch = 0
    mux_const_branch_widths = Counter()
    mux_const_1bit_10_01 = 0
    mux_const_equal = 0
    mux_wide = 0
    mux_wide_cond1 = 0
    mux_wide_widths = Counter()
    regwrite_buckets = Counter()
    regwrite_non2s = 0
    read_buckets = Counter()
    read_non2s = 0
    bitselect_by_mask = defaultdict(int)
    bitselect_by_mask_width = defaultdict(int)
    bitselect_total = 0
    writes = array("I", [0]) * (n_states + 1)
    reads = array("I", [0]) * (n_states + 1)
    write_op = array("I", [0]) * (n_states + 1)
    reg_targets = set()
    latch_targets = set()
    const_cache = {}  # op_id -> Optional[int]

    def const_value(op_id):
        if op_id in const_cache:
            return const_cache[op_id]
        op = ops[op_id - 1]
        result = None
        if strings[op[1] - 1] == "core.compute.constant" and len(op[7]) == 1:
            name_id, tag, value = op[7][0]
            if name_id in (ID_CONST_VALUE, ID_VALUE):
                if tag == "string":
                    result = parse_sv_literal(value)
                elif tag == "int":
                    result = value
                elif tag == "bool":
                    result = 1 if value else 0
        const_cache[op_id] = result
        return result

    for op in ops:
        name = strings[op[1] - 1]
        operands = op[4]
        results = op[5]
        if name == "core.compute.sliceStatic":
            if len(operands) != 1 or len(results) != 1 or not v_2s[results[0]]:
                slice_of_slice_4s_skipped += 1
                continue
            w = v_width[results[0]]
            pid = producer[operands[0]]
            if not pid:
                continue
            inner = ops[pid - 1]
            inner_name = strings[inner[1] - 1]
            if inner_name == "core.compute.sliceStatic":
                slice_of_slice[width_bucket_slice(w)] += 1
            elif inner_name == "core.compute.concat":
                slice_concat_total += 1
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
                # concat operands run MSB-first: accumulate offsets from the LSB side
                cat_operands = inner[4]
                widths = [v_width[v] for v in cat_operands]
                offset = 0
                hit = None  # (index, offset, width, exact)
                for i in range(len(cat_operands) - 1, -1, -1):
                    wi = widths[i]
                    if start >= offset and end < offset + wi:
                        hit = (i, offset, wi, start == offset and end == offset + wi - 1)
                        break
                    offset += wi
                if hit is not None:
                    bucket = width_bucket_slice(w)
                    slice_concat_contained[bucket] += 1
                    if hit[3]:
                        slice_concat_exact[bucket] += 1
                        if uses[operands[0]] == 1:
                            slice_concat_exact_single_use += 1
                else:
                    slice_concat_straddle += 1
        elif name == "core.compute.concat":
            if len(results) != 1 or not v_2s[results[0]]:
                continue
            edges = 0
            for v in operands:
                pid = producer[v]
                if pid and strings[ops[pid - 1][1] - 1] == "core.compute.concat":
                    edges += 1
            if edges:
                nested_concat_ops += 1
                nested_concat_edges += edges
                if edges > nested_concat_max_edges:
                    nested_concat_max_edges = edges
        elif name == "core.compute.mux":
            if len(operands) != 3 or len(results) != 1 or not v_2s[results[0]]:
                continue
            w = v_width[results[0]]
            if w > 64:
                mux_wide += 1
                mux_wide_widths[w] += 1
                if v_width[operands[0]] == 1:
                    mux_wide_cond1 += 1
            pt = producer[operands[1]]
            pf = producer[operands[2]]
            if pt and pf:
                vt = const_value(pt)
                vf = const_value(pf)
                if vt is not None and vf is not None:
                    mux_const_branch += 1
                    mux_const_branch_widths[w] += 1
                    if vt == vf:
                        mux_const_equal += 1
                    if w == 1 and ((vt & 1, vf & 1) in ((1, 0), (0, 1))):
                        mux_const_1bit_10_01 += 1
        elif name == "core.state.regWrite":
            refs = op[6]
            if refs and refs[0][0] == "state":
                target = refs[0][1]
                writes[target] += 1
                write_op[target] = op[0]
                reg_targets.add(target)
                if s_2s_logic[target]:
                    regwrite_buckets[width_bucket_reg(s_width[target])] += 1
                else:
                    regwrite_non2s += 1
        elif name == "core.state.latchWrite":
            refs = op[6]
            if refs and refs[0][0] == "state":
                latch_targets.add(refs[0][1])
        elif name == "core.state.read":
            refs = op[6]
            if (len(refs) == 1 and refs[0][0] == "state" and len(results) == 1
                    and not op[7] and not operands
                    and v_type[results[0]] == s_type[refs[0][1]]):
                target = refs[0][1]
                reads[target] += 1
                if s_2s_logic[target]:
                    read_buckets[width_bucket_reg(s_width[target])] += 1
                else:
                    read_non2s += 1
        elif name == "core.compute.bitSelect":
            if len(operands) == 3 and results and v_2s[results[0]]:
                bitselect_total += 1
                bitselect_by_mask[operands[0]] += 1
                bitselect_by_mask_width[(operands[0], v_width[results[0]])] += 1

    print(f"pass B done: {time.time() - t0:.1f}s total", flush=True)

    # ================= report =================
    def show_buckets(title, counter, order):
        total = sum(counter.values())
        parts = " ".join(f"{b}={counter.get(b, 0)}" for b in order)
        print(f"{title}: total={total} | {parts}")
        return total

    print("\n== [1] slice-of-slice (two-state) ==")
    show_buckets("slice(slice(...))", slice_of_slice, ("1", "2-8", "9-32", "33-64", ">64"))
    print(f"non-two-state sliceStatic skipped: {slice_of_slice_4s_skipped}")

    print("\n== [2] slice-of-concat (two-state; concat operands MSB-first, bounds inclusive) ==")
    print(f"sliceStatic-of-concat total: {slice_concat_total}")
    show_buckets("fully inside one concat operand", slice_concat_contained,
                 ("1", "2-8", "9-32", "33-64", ">64"))
    show_buckets("...of which exactly one whole operand", slice_concat_exact,
                 ("1", "2-8", "9-32", "33-64", ">64"))
    print(f"straddling operand boundaries (not foldable this way): {slice_concat_straddle}")
    print(f"exact + concat result single-use (concat also dies): {slice_concat_exact_single_use}")

    print("\n== [3] nested concat (two-state) ==")
    print(f"concat ops with >=1 concat operand: {nested_concat_ops}")
    print(f"total concat->concat operand edges: {nested_concat_edges} (max per op {nested_concat_max_edges})")

    print("\n== [4] const-branch mux (two-state) ==")
    print(f"mux with both data branches constant: {mux_const_branch}")
    common = ",".join(f"{w}:{c}" for w, c in sorted(mux_const_branch_widths.items())[:10])
    print(f"width mix: {common}")
    print(f"1-bit result with branches (1,0) or (0,1): {mux_const_1bit_10_01}")
    print(f"branches equal constant (mux -> const, deletable): {mux_const_equal}")

    print("\n== [5] wide mux (two-state, result >64b) ==")
    print(f"wide mux: {mux_wide}, of which 1-bit condition: {mux_wide_cond1}")
    common = ",".join(f"{w}:{c}" for w, c in sorted(mux_wide_widths.items())[:12])
    print(f"width mix: {common}")

    print("\n== [6] state / regWrite / read width profile ==")
    show_buckets("regWrite data width", regwrite_buckets, ("1", "2", "3-8", "9-16", "17-32", "33-64", ">64"))
    print(f"regWrite on non-two-state/array targets: {regwrite_non2s}")
    show_buckets("state.read result width", read_buckets, ("1", "2", "3-8", "9-16", "17-32", "33-64", ">64"))
    print(f"state.read on non-two-state/array targets: {read_non2s}")
    n_memory = sum(s_array)
    n_reg = len(reg_targets)
    n_latch = len(latch_targets)
    n_other = n_states - n_memory - n_reg - n_latch
    print(f"states total={n_states} memory(array)={n_memory} "
          f"regWrite-target regs={n_reg} latch-only={n_latch} other(event-history/unused)={n_other}")

    # ================= [7] narrow register packing pool =================
    print("\n== [7] narrow register packing pool (pack-bit-registers criteria, width relaxed) ==")
    # collect per-state the single write op for validation
    for w_max in (1, 8, 32):
        groups = defaultdict(list)  # signature -> [(state, width)]
        candidates = 0
        for sid in range(1, n_states + 1):
            if not s_2s_logic[sid] or s_width[sid] == 0 or s_width[sid] > w_max:
                continue
            if t_signed[s_type[sid]]:
                continue
            if sid not in init_known or writes[sid] != 1:
                continue
            if references[sid] != reads[sid] + 1 or not reads[sid]:
                continue
            op = ops[write_op[sid] - 1]
            operands, refs, params = op[4], op[6], op[7]
            if len(operands) < 4 or len(refs) != len(operands) - 2 or op[5]:
                continue
            if any(ref[0] != "state" for ref in refs):
                continue
            if len(params) != 1 or params[0][0] != ID_EVENT_EDGES or params[0][1] != "strings":
                continue
            edges = params[0][2]
            if not edges or len(edges) + 3 != len(operands):
                continue
            if any(e not in ("posedge", "negedge") for e in edges):
                continue
            # enable 1-bit two-state; data/mask exact state type; events 1-bit two-state
            if not (v_2s[operands[0]] and v_width[operands[0]] == 1 and not t_signed[v_type[operands[0]]]):
                continue
            if v_type[operands[1]] != s_type[sid] or v_type[operands[2]] != s_type[sid]:
                continue
            ok = True
            key = [operands[0], operands[2], 1 if projected(sid) else 0]
            for i, edge in enumerate(edges):
                history = refs[1 + i][1]
                event = operands[3 + i]
                if not (v_2s[event] and v_width[event] == 1):
                    ok = False
                    break
                if references[history] != 1 or not s_2s_logic[history] or s_width[history] != 1 \
                        or t_signed[s_type[history]] or history not in init_known:
                    ok = False
                    break
                key.append((event, edge, init_known[history] & 1))
            if not ok:
                continue
            candidates += 1
            groups[tuple(key)].append((sid, s_width[sid]))
        # greedy 64-bit chunk packing; drop chunks holding a single register
        grouped_regs = packed_regs = words = 0
        n_groups = 0
        for key, members in groups.items():
            if len(members) < 2:
                continue
            n_groups += 1
            grouped_regs += len(members)
            cur_bits = cur_regs = 0
            for _sid, w in members:
                if cur_bits + w > 64:
                    if cur_regs >= 2:
                        words += 1
                        packed_regs += cur_regs
                    cur_bits = cur_regs = 0
                cur_bits += w
                cur_regs += 1
            if cur_regs >= 2:
                words += 1
                packed_regs += cur_regs
        print(f"width<= {w_max}: candidate regs={candidates} signature groups(>=2 regs)={n_groups} "
              f"regs in groups={grouped_regs} -> packed words={words} (regs actually packed={packed_regs})")

    # ================= [8] bitSelect chains =================
    print("\n== [8] bitSelect shared-condition chains (two-state) ==")
    print(f"bitSelect ops total: {bitselect_total}, distinct conditions: {len(bitselect_by_mask)}")
    chain_hist = Counter()
    conds_ge2 = 0
    ops_in_chains = 0
    for cond, cnt in bitselect_by_mask.items():
        if cnt >= 2:
            conds_ge2 += 1
            ops_in_chains += cnt
            if cnt == 2:
                chain_hist["2"] += 1
            elif cnt == 3:
                chain_hist["3"] += 1
            elif cnt == 4:
                chain_hist["4"] += 1
            elif cnt <= 8:
                chain_hist["5-8"] += 1
            else:
                chain_hist[">8"] += 1
    print(f"conditions with >=2 bitSelect: {conds_ge2}, ops involved: {ops_in_chains}")
    print("chain size histogram (conds): " +
          " ".join(f"{b}={chain_hist.get(b, 0)}" for b in ("2", "3", "4", "5-8", ">8")))
    mw_ge2 = sum(1 for c in bitselect_by_mask_width.values() if c >= 2)
    mw_ops = sum(c for c in bitselect_by_mask_width.values() if c >= 2)
    widths = Counter()
    for (mask, w), c in bitselect_by_mask_width.items():
        if c >= 2:
            widths[w] += 1
    common = ",".join(f"{w}:{c}" for w, c in sorted(widths.items())[:10])
    print(f"(mask,width) groups with >=2 bitSelect: {mw_ge2}, ops involved: {mw_ops}")
    print(f"grouped-op width mix: {common}")

    print(f"\ntotal runtime: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
