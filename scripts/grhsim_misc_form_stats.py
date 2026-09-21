"""Census small IR-form pools: register constants, constant memories, depth-1
arrays, one-hot decode patterns, and concat-equality patterns (gsim
constantAnalysis / patternDetect counterparts not yet mirrored in grhsim).

- register constant: every write port of a state writes the same constant as
  its init value (or its update condition is a constant false), so all reads
  fold to the constant;
- constant memory: every memWrite data input is the same constant;
- depth-1 array: array states with a single element (register pair form);
- one-hot decode: sliceDynamic(shl(1, x), i) compared against 1, i.e.
  gsim patternDetect's dshl(1,x)+bits => x==i form;
- concat == const: equality against a wide constant of a pure concat, which
  splits into per-lane equalities.
"""

import argparse
from array import array
from collections import Counter
import json
import re
from pathlib import Path

LITERAL_RE = re.compile(r"\s*(?:(\d+)\s*)?'\s*[sS]?([bBoOdDhH])\s*([0-9a-fA-F_xXzZ?]+)\s*")


def parse_sv_literal(text):
    match = LITERAL_RE.fullmatch(text)
    if match:
        base = {"b": 2, "o": 8, "d": 10, "h": 16}[match.group(2).lower()]
        digits = match.group(3).replace("_", "")
        if any(c in digits.lower() for c in "xz?"):
            return None
        try:
            return int(digits, base)
        except ValueError:
            return None
    if re.fullmatch(r"\d[\d_]*", text):
        return int(text.replace("_", ""))
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    model = json.loads(args.model.read_bytes())
    ops, values, strings = model["operations"], model["values"], model["strings"]
    types = {t[0]: t for t in model["types"]}
    names = [strings[op[1] - 1] for op in ops]
    states = model["states"]
    inits = model.get("init", [])

    producer = array("I", [0]) * (len(values) + 1)
    for op in ops:
        if op[5]:
            producer[op[5][0]] = op[0]

    def const_int_op(op_id):
        if not op_id or names[op_id - 1] != "core.compute.constant":
            return None
        for entry in ops[op_id - 1][7]:
            if len(entry) != 3:
                continue
            if entry[1] == "int" and 0 <= entry[2] < (1 << 64):
                return entry[2]
            if entry[1] == "string" and isinstance(entry[2], str):
                parsed = parse_sv_literal(entry[2])
                if parsed is not None and 0 <= parsed < (1 << 64):
                    return parsed
        return None

    def const_of(value):
        return const_int_op(producer[value])

    def logic_width(value):
        t = types[values[value - 1][1]]
        return t[3] if t[2] == "logic" else 0

    stats = Counter()

    # state write-port constant analysis
    write_ops = {"core.state.regWrite", "core.state.latchWrite", "core.state.memWrite",
                 "core.state.memWriteSeq", "core.state.memFill", "core.state.memAssign"}
    state_writes = {}
    for op in ops:
        name = names[op[0] - 1]
        if name not in write_ops or not op[6]:
            continue
        state_writes.setdefault(op[6][0][1] if isinstance(op[6][0], list) else op[6][0], []).append(op)
    print(f"states_total={len(states)} states_with_writes={len(state_writes)}")
    print(f"sample state entry: {states[0] if states else None}")
    print(f"sample init entry: {inits[0] if inits else None}")
    reg_const_candidates = 0
    for state_id, write_list in state_writes.items():
        kinds = {names[op[0] - 1] for op in write_list}
        if kinds != {"core.state.regWrite"} and kinds != {"core.state.latchWrite"}:
            continue
        nexts = set()
        all_false = True
        ok = True
        for op in write_list:
            operands = op[4]
            cond = const_of(operands[0])
            if cond != 0:
                all_false = False
            nxt = const_of(operands[1]) if len(operands) > 1 else None
            if nxt is None:
                ok = False
                break
            nexts.add(nxt)
        if all_false:
            stats["write_ports_all_cond_false"] += 1
            reg_const_candidates += 1
        elif ok and len(nexts) == 1:
            stats["write_ports_all_same_const"] += 1
            reg_const_candidates += 1
    stats["reg_const_candidates"] = reg_const_candidates

    # constant memory: memWrite/memWriteSeq/memFill data all the same constant
    for state_id, write_list in state_writes.items():
        kinds = {names[op[0] - 1] for op in write_list}
        if not kinds <= {"core.state.memWrite", "core.state.memWriteSeq", "core.state.memFill"}:
            continue
        datas = set()
        ok = True
        for op in write_list:
            name = names[op[0] - 1]
            if name == "core.state.memWrite":
                data_values = [op[4][2]] if len(op[4]) >= 3 else []
            elif name == "core.state.memFill":
                data_values = [op[4][1]] if len(op[4]) >= 2 else []
            else:
                data_values = []
                ok = False
                break
            for dv in data_values:
                c = const_of(dv)
                if c is None:
                    ok = False
                    break
                datas.add(c)
            if not ok:
                break
        if ok and len(datas) == 1:
            stats["constant_memory_candidates"] += 1

    # depth-1 arrays
    for state in states:
        t = types[state[1]] if len(state) > 1 and state[1] in types else None
        if t and t[2] == "array":
            depth = t[4] if len(t) > 4 else None
            if depth == 1:
                stats["depth1_arrays"] += 1

    # one-hot decode: sliceDynamic(shl(const 1, x), i) used as 1-bit value
    for op in ops:
        if names[op[0] - 1] != "core.compute.sliceDynamic" or len(op[4]) != 2:
            continue
        src = producer[op[4][0]]
        if not src or names[src - 1] != "core.compute.shl":
            continue
        shl_operands = ops[src - 1][4]
        if len(shl_operands) != 2:
            continue
        c = const_of(shl_operands[0])
        if c == 1:
            stats["onehot_dshl_slice"] += 1

    # concat == const
    for op in ops:
        if names[op[0] - 1] != "core.compute.eq" or len(op[4]) != 2:
            continue
        for side in (0, 1):
            if const_of(op[4][side]) is None:
                continue
            other = producer[op[4][1 - side]]
            if other and names[other - 1] == "core.compute.concat" and logic_width(op[4][1 - side]) > 1:
                stats["concat_eq_const"] += 1
            break

    print("== misc form census ==")
    for key in sorted(stats):
        print(f"{stats[key]:10d}  {key}")


if __name__ == "__main__":
    main()
