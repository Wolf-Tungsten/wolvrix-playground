#!/usr/bin/env python3
"""Used-bits backward analysis census on a stored GrhSIM checkpoint.

Computes, for every two-state logic value and register state, the highest used
bit (prefix form, gsim usedBits style), then reports what a width-narrowing
pass could recover: narrowable values, >64-to-<=64 downgrades, wide-op word
work reduction, narrowable register states, and the boundary-slice cost.

Sink policy (conservative, matching the planned pass v1):
  - outputs, inputs, DPI/system arguments, memory (array) data/address ports,
    and event/condition operands are always fully used.
  - shift amounts, comparison operands, division/modulo operands, reduction
    operands, logical-truth operands, and dynamic-slice data are fully used.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

FULL = 1 << 62  # sentinel: fully used (capped by actual width when applied)

# Op kinds whose result low-k bits depend only on operand low-k bits
# (truncation-transparent for the data path).
TRANSPARENT2 = {"add", "sub", "mul", "and", "or", "xor", "xnor"}
FULL_OPS = {
    "div", "mod", "eq", "ne", "caseEq", "caseNe", "wildcardEq", "wildcardNe",
    "lt", "le", "gt", "ge", "logicAnd", "logicOr", "logicNot",
    "reduceAnd", "reduceOr", "reduceXor", "reduceNor", "reduceNand",
    "reduceXnor",
}


def bucket(width: int) -> str:
    if width <= 1:
        return "1"
    if width <= 8:
        return "2-8"
    if width <= 16:
        return "9-16"
    if width <= 32:
        return "17-32"
    if width <= 64:
        return "33-64"
    if width <= 128:
        return "65-128"
    if width <= 256:
        return "129-256"
    return ">256"


def words(width: int) -> int:
    return (width + 63) // 64 if width > 64 else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()

    with args.model.open("r", encoding="utf-8") as handle:
        doc = json.load(handle)

    strings = ["<invalid>"] + doc["strings"]

    types = [None]  # 1-based: (kind, width, isSigned, domain)
    for entry in doc["types"]:
        _, _ref, kind, width, is_signed, domain, _elem, _count = entry
        types.append((kind, width, bool(is_signed), domain))

    def logic_width(type_index: int) -> int:
        kind, width, _signed, domain = types[type_index]
        if kind != "logic" or domain != "2-state":
            return 0
        return width

    value_type = [0]  # 1-based type index per value
    for entry in doc["values"]:
        value_type.append(entry[1])

    state_type = [0]
    for entry in doc["states"]:
        state_type.append(entry[2])

    op_type_name = []
    op_operands = []
    op_results = []
    op_refs = []  # list of (kind, index)
    op_params = []
    for entry in doc["operations"]:
        _, op_type, _name, _origin, operands, results, refs, params = entry
        op_type_name.append(strings[op_type])
        op_operands.append(operands)
        op_results.append(results)
        op_refs.append([(kind, index) for kind, index in refs])
        op_params.append({strings[name]: value for name, value in
                          ((p[0], p[1:]) for p in params)})

    nops = len(op_type_name)
    nvalues = len(value_type)
    nstates = len(state_type)

    producer = [0] * nvalues  # value -> op index (0 = none)
    for i, results in enumerate(op_results):
        for value in results:
            producer[value] = i + 1

    writers_by_state = [[] for _ in range(nstates)]
    for i, (name, refs) in enumerate(zip(op_type_name, op_refs)):
        if name in ("core.state.regWrite", "core.state.latchWrite") and refs and refs[0][0] == "state":
            writers_by_state[refs[0][1]].append(i)

    width_of_value = [0] * nvalues
    for v in range(1, nvalues):
        width_of_value[v] = logic_width(value_type[v])
    width_of_state = [0] * nstates
    for s in range(1, nstates):
        kind, width, _signed, domain = types[state_type[s]]
        # Arrays stay fully used in v1; only plain logic states participate.
        width_of_state[s] = width if kind == "logic" and domain == "2-state" else 0

    used = [0] * nvalues
    used_state = [0] * nstates

    queue = collections.deque(range(nops))  # op indices to (re)apply
    in_queue = bytearray(nops)
    for i in range(nops):
        in_queue[i] = 1

    def raise_value(value: int, req: int, queue: collections.deque) -> None:
        if value <= 0:
            return
        cap = width_of_value[value]
        if cap == 0:
            return
        req = min(req, cap)
        if req > used[value]:
            used[value] = req
            prod = producer[value]
            if prod:
                idx = prod - 1
                if not in_queue[idx]:
                    in_queue[idx] = 1
                    queue.append(idx)

    def raise_state(state: int, req: int, queue: collections.deque) -> None:
        cap = width_of_state[state]
        if cap == 0:
            return
        req = min(req, cap)
        if req > used_state[state]:
            used_state[state] = req
            for idx in writers_by_state[state]:
                if not in_queue[idx]:
                    in_queue[idx] = 1
                    queue.append(idx)

    def full(value: int) -> int:
        return width_of_value[value]

    def apply(op_index: int, queue: collections.deque) -> None:
        name = op_type_name[op_index]
        operands = op_operands[op_index]
        results = op_results[op_index]
        refs = op_refs[op_index]
        if name == "core.state.read":
            if refs and results:
                raise_state(refs[0][1], used[results[0]], queue)
            return
        if name in ("core.state.regWrite", "core.state.latchWrite"):
            if refs:
                req = used_state[refs[0][1]]
                # operands: [updateCond, data, mask, events...]
                if len(operands) >= 3:
                    raise_value(operands[0], full(operands[0]), queue)
                    raise_value(operands[1], req, queue)
                    raise_value(operands[2], req, queue)
                    for value in operands[3:]:
                        raise_value(value, full(value), queue)
            return
        if name in ("core.output.write", "core.system.task", "core.dpi.call",
                    "core.state.memWrite", "core.state.memFill",
                    "core.state.memWriteSeq", "core.state.memAssign"):
            for value in operands:
                raise_value(value, full(value), queue)
            return
        if name == "core.state.memRead":
            for value in operands:
                raise_value(value, full(value), queue)
            if results:
                raise_value(results[0], full(results[0]), queue)
            return
        if name == "core.input.read":
            if results:
                raise_value(results[0], full(results[0]), queue)
            return
        if name == "core.system.function":
            for value in operands:
                raise_value(value, full(value), queue)
            return
        if not name.startswith("core.compute.") or not results:
            return
        result = results[0]
        k = used[result]
        if k == 0:
            return
        kind = name[len("core.compute."):]
        if kind == "constant":
            return
        if kind == "assign":
            raise_value(operands[0], k, queue)
        elif kind in TRANSPARENT2 or kind == "not":
            for value in operands:
                raise_value(value, k, queue)
        elif kind in FULL_OPS:
            for value in operands:
                raise_value(value, full(value), queue)
        elif kind == "shl":
            raise_value(operands[0], k, queue)
            raise_value(operands[1], full(operands[1]), queue)
        elif kind in ("lshr", "ashr"):
            for value in operands:
                raise_value(value, full(value), queue)
        elif kind == "mux":
            raise_value(operands[0], full(operands[0]), queue)
            raise_value(operands[1], k, queue)
            raise_value(operands[2], k, queue)
        elif kind == "bitSelect":
            for value in operands:
                raise_value(value, k, queue)
        elif kind == "prioritySelect":
            count = (len(operands) - 1) // 2
            for value in operands[:count]:
                raise_value(value, full(value), queue)
            for value in operands[count:]:
                raise_value(value, k, queue)
        elif kind == "concat":
            offset = 0
            for value in reversed(operands):
                w = width_of_value[value]
                req = max(0, min(w, k - offset))
                raise_value(value, req, queue)
                offset += w
        elif kind == "replicate":
            w = width_of_value[operands[0]]
            raise_value(operands[0], min(k, w) if k < w else w, queue)
        elif kind == "sliceStatic":
            start = op_params[op_index].get("sliceStart", ("int", 0))[1]
            raise_value(operands[0], min(width_of_value[operands[0]], start + k), queue)
        elif kind in ("sliceDynamic", "sliceArray"):
            for value in operands:
                raise_value(value, full(value), queue)
        else:
            for value in operands:
                raise_value(value, full(value), queue)

    while queue:
        op_index = queue.popleft()
        in_queue[op_index] = 0
        apply(op_index, queue)

    # ---- census ----
    # Lightweight scalar constant tracking for offset analysis.
    const_value: dict[int, int] = {}
    for i in range(nops):
        if op_type_name[i] != "core.compute.constant":
            continue
        results = op_results[i]
        if not results:
            continue
        w = width_of_value[results[0]]
        if w == 0 or w > 64:
            continue
        for pname, pval in op_params[i].items():
            if pname not in ("constValue", "value"):
                continue
            tag, raw = pval
            try:
                if tag == "string":
                    text = raw
                    if "'h" in text:
                        const_value[results[0]] = int(text.split("'h", 1)[1], 16)
                    elif "'d" in text:
                        const_value[results[0]] = int(text.split("'d", 1)[1])
                    elif "'b" in text:
                        const_value[results[0]] = int(text.split("'b", 1)[1], 2)
                    else:
                        const_value[results[0]] = int(text)
                elif tag == "int":
                    const_value[results[0]] = int(raw)
                elif tag == "bool":
                    const_value[results[0]] = 1 if raw else 0
            except ValueError:
                pass
            break

    narrowable = 0
    downgrades = 0  # >64 -> <=64
    dead = 0
    bits_saved = 0
    transitions = collections.Counter()
    value_hist = collections.Counter()
    for v in range(1, nvalues):
        w = width_of_value[v]
        if w == 0:
            continue
        value_hist[bucket(w)] += 1
        if used[v] == 0:
            dead += 1
            continue
        if used[v] < w:
            narrowable += 1
            bits_saved += w - used[v]
            transitions[(bucket(w), bucket(used[v]))] += 1
            if w > 64 and used[v] <= 64:
                downgrades += 1

    op_narrowed = collections.Counter()   # Case A rewrites by kind
    op_boundary = collections.Counter()   # Case B: keep wide op + slice
    wide_words_before = 0
    wide_words_after = 0
    wide_ops = 0
    for i in range(nops):
        name = op_type_name[i]
        if not name.startswith("core.compute."):
            continue
        results = op_results[i]
        if not results:
            continue
        result = results[0]
        w = width_of_value[result]
        if w == 0:
            continue
        kind = name[len("core.compute."):]
        k = used[result]
        if w > 64:
            wide_ops += 1
            wide_words_before += words(w)
            wide_words_after += words(k) if (k > 64 or k == 0) else 0
        if 0 < k < w:
            narrowable_kind = kind in TRANSPARENT2 or kind in {
                "not", "shl", "mux", "bitSelect", "prioritySelect", "assign",
                "concat", "replicate", "sliceStatic", "constant"}
            if narrowable_kind:
                op_narrowed[kind] += 1
            else:
                op_boundary[kind] += 1

    state_narrowed = 0
    state_downgrades = 0
    state_bits_saved = 0
    state_hist = collections.Counter()
    for s in range(1, nstates):
        w = width_of_state[s]
        if w == 0:
            continue
        state_hist[bucket(w)] += 1
        if 0 < used_state[s] < w:
            state_narrowed += 1
            state_bits_saved += w - used_state[s]
            if w > 64 and used_state[s] <= 64:
                state_downgrades += 1

    print(f"model: {args.model}")
    print(f"ops={nops} values={nvalues - 1} states={nstates - 1}")
    print("value width histogram:", dict(sorted(value_hist.items())))
    print(f"narrowable values: {narrowable} (dead: {dead})")
    print(f"  >64 -> <=64 downgrades: {downgrades}")
    print(f"  value bits saved (declared-used): {bits_saved}")
    print("  transitions (from -> to):")
    for (src, dst), count in sorted(transitions.items(), key=lambda kv: -kv[1])[:24]:
        print(f"    {src:>8} -> {dst:<8} {count}")
    print("narrowed compute ops by kind (Case A):")
    for kind, count in op_narrowed.most_common(24):
        print(f"    {kind:<16} {count}")
    print("boundary-slice-only results by kind (Case B):")
    for kind, count in op_boundary.most_common(24):
        print(f"    {kind:<16} {count}")
    print(f"wide (>64) compute ops: {wide_ops}")
    print(f"  wide word-work before: {wide_words_before}")
    print(f"  wide word-work after:  {wide_words_after}")
    print("state width histogram:", dict(sorted(state_hist.items())))
    print(f"narrowable register states: {state_narrowed}")
    print(f"  >64 -> <=64 state downgrades: {state_downgrades}")
    print(f"  state bits saved: {state_bits_saved}")

    # Dead values by producer kind; pure compute producers are removable.
    dead_by_kind = collections.Counter()
    dead_samples = collections.defaultdict(list)
    for v in range(1, nvalues):
        w = width_of_value[v]
        if w == 0 or used[v] != 0:
            continue
        prod = producer[v]
        kind = op_type_name[prod - 1] if prod else "<no producer>"
        dead_by_kind[kind] += 1
        if len(dead_samples[kind]) < 3:
            dead_samples[kind].append(v)
    print("dead values by producer kind:")
    for kind, count in dead_by_kind.most_common(24):
        print(f"    {kind:<32} {count}")

    # Constant-offset shifts/dynamic slices that narrowing could turn into
    # plain sliceStatic (lshr result used k bits, offset constant c, c+k <= w).
    lshr_const = 0
    lshr_const_narrowable = 0
    for i in range(nops):
        if op_type_name[i] != "core.compute.lshr":
            continue
        operands = op_operands[i]
        if len(operands) != 2 or operands[1] not in const_value:
            continue
        lshr_const += 1
        result = op_results[i][0]
        k, w = used[result], width_of_value[result]
        if 0 < k < w and const_value[operands[1]] + k <= w:
            lshr_const_narrowable += 1
    print(f"lshr with constant offset: {lshr_const} (narrowing-convertible: {lshr_const_narrowable})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
