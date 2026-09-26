#!/usr/bin/env python3
"""NO00016 residue-fold census: post-schedule identity/constant residue folding.

Formalizes ptmp probe_identity4.py as the authoritative selection. An op is
foldable when its result is a local (non-boundary), unpinned, non-event-gate
value whose consumers are all pure compute ops in the SAME compute unit, and
one class rule matches:

  assign_strict      assign(x), type(x) == type(r)
  assign_width       assign(x), equal width, all consumers signedness-agnostic
  slice_full_strict  sliceStatic(x, 0, w-1) full range, same type
  slice_full_width   full range, width equal, agnostic consumers
  const_slice        sliceStatic(const c, start, end); rewires to an EXISTING
                     constant of the result type with value (c>>start)&mask
                     (CSE hit; no constant is created). The hit must be ordered
                     before the folded op in the verifier compute walk
                     (preorder partition DFS), so rewired consumers keep
                     defined-before-use ordering.
  not_not            not(not(x)), inner not single-use, type(x) == type(r);
                     two-state result (probe omission fixed here; no-op on the
                     production model: all candidates are two-state)
  self_{eq,ne,lt,gt,le,ge}  cmp(x, x), two-state result and operand; rewires
                     to an existing 0/1 constant of the result type (same
                     ordering rule as const_slice)
  dce_cascade        pure compute local op with zero uses after rewiring
                     (constants excluded), to fixpoint

Selected ops stay in the model; the CPU emitter skips them (schedule trailing
field). Dynamic saving = sum over selected ops of their unit's body fires
(same-model join with the baseline run).

Inputs
  --model      production mapped checkpoint JSON (NO00015 flow archive)
  --run        baseline dyn run log ([grhsim-dyn] sn rows; optional, only for
               the dynamic saving column)
  --output     directory for summary.md / summary.json / selected.json
  --cycles     guest cycles (default 100001)
"""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grhsim_demonitor_census import view_from_model, CONSTANT_KIND, EXPR_KIND  # noqa: E402
from grhsim_vchg_profile import SN_LINE  # noqa: E402

AGNOSTIC = {
    "core.compute.assign", "core.compute.and", "core.compute.or", "core.compute.xor",
    "core.compute.not", "core.compute.mux", "core.compute.concat",
    "core.compute.sliceStatic", "core.compute.bitSelect", "core.compute.eq",
    "core.compute.ne", "core.compute.logicAnd", "core.compute.logicOr",
    "core.compute.logicNot", "core.compute.reduceAnd", "core.compute.reduceOr",
    "core.compute.reduceXor", "core.compute.replicate",
}
CMP_SELF = {"core.compute.eq": 1, "core.compute.ne": 0, "core.compute.gt": 0,
            "core.compute.lt": 0, "core.compute.ge": 1, "core.compute.le": 1}

CLASSES = ["assign_strict", "assign_width", "slice_full_strict", "slice_full_width",
           "const_slice", "not_not", "self_eq", "self_ne", "self_lt", "self_gt",
           "self_le", "self_ge", "dce_cascade"]


def parse_sv_literal(text):
    """Mirror of the C++ parseSvLiteral: exact Python int, None on failure."""
    text = text.strip().replace("_", "")
    if not text:
        return None
    m = re.match(r"^(?:(\d+)\s*)?'([sS]?)([bBdDhHoO])([0-9a-fA-FxXzZ?]+)$", text)
    if m:
        base = {"b": 2, "o": 8, "d": 10, "h": 16}[m.group(3).lower()]
        digits = m.group(4).lower()
        if base == 10:
            return None if any(c in digits for c in "xz?") else int(digits, 10)
        val = 0
        for ch in digits:
            val = (val << {2: 1, 8: 3, 16: 4}[base]) | (0 if ch in "xz?" else int(ch, base))
        return val
    return int(text) if re.match(r"^[0-9]+$", text) else None


def tables_from_model(model):
    """Type/constant tables derived from the model JSON (no schedule view).

    Also computes verifier compute-walk positions (preorder partition DFS,
    children in listed order): a CSE hit constant must be ordered before the
    folded op so rewired consumers keep defined-before-use ordering.
    """
    strings = model["strings"]
    types = {t[0]: t for t in model["types"]}
    value_type = {v[0]: v[1] for v in model["values"]}
    type_width = {t[0]: (t[3] if t[2] == "logic" else 0) for t in model["types"]}
    two_state = {t[0]: (t[2] == "logic" and len(t) > 5 and t[5] == "2-state")
                 for t in model["types"]}

    payload = model["mappings"][0][-1]
    partitions = {p[0]: p for p in payload[2]}
    op_pos = {}
    order = 0
    stack = [payload[1]]
    while stack:
        row = partitions[stack.pop()]
        for oid in row[5]:
            order += 1
            op_pos[oid] = order
        stack.extend(reversed(row[4]))

    const_vals = {}
    for op in model["operations"]:
        if strings[op[1] - 1] != CONSTANT_KIND:
            continue
        res = op[5][0] if op[5] else 0
        for p in (op[7] if len(op) > 7 else []):
            pn = strings[p[0] - 1] if isinstance(p[0], int) else str(p[0])
            if pn in ("constValue", "value"):
                v = None
                if p[1] == "int":
                    v = int(p[2])
                elif p[1] == "bool":
                    v = 1 if p[2] else 0
                elif p[1] == "string":
                    v = parse_sv_literal(p[2])
                if v is not None and res:
                    const_vals[res] = v
                break

    # CSE candidates: (type_id, value masked to width) -> [value ids of
    # constant results in model order]
    cse = defaultdict(list)
    for v, c in const_vals.items():
        t = value_type[v]
        w = type_width.get(t, 0)
        if 1 <= w <= 64:
            cse[(t, c & ((1 << w) - 1))].append(v)

    return {"strings": strings, "types": types, "value_type": value_type,
            "type_width": type_width, "two_state": two_state,
            "const_vals": const_vals, "cse": cse, "op_pos": op_pos}


def select(view, tables):
    """Fold selection. Returns (selected {op_id: class}, rejects Counter,
    rewire {result value: source value}).

    Single primaries pass in model order + one cascade-DCE fixpoint, exactly
    the probe order (the C++ grhsim.fold-residue pass mirrors this).
    """
    strings = tables["strings"]
    value_type = tables["value_type"]
    type_width = tables["type_width"]
    two_state = tables["two_state"]
    const_vals = tables["const_vals"]
    cse = tables["cse"]

    op_name = view["op_name"]
    op_operands = view["op_operands"]
    producer_of = view["producer_of"]
    consumers_of = view["consumers_of"]
    unit_of_op = view["unit_of_op"]
    is_boundary = view["is_boundary"]
    pinned = view["pinned"]
    event_gate = view["event_gate_values"]
    op_pos = tables["op_pos"]

    def cse_hit(key, foldop):
        """First candidate (model order) positioned before foldop in the
        verifier compute walk; None if none qualifies."""
        before = op_pos.get(foldop, 0)
        for v in cse.get(key, ()):
            prod = producer_of.get(v, 0)
            pos = op_pos.get(prod, 0)
            if prod and pos and pos < before:
                return v
        return None

    def pure_compute(oid):
        n = op_name.get(oid, "")
        return n.startswith("core.compute.") and n not in (CONSTANT_KIND, EXPR_KIND)

    def eligible_result(v):
        if v in is_boundary or v in pinned or v in event_gate:
            return False
        prod = producer_of.get(v, 0)
        if not prod:
            return False
        unit = unit_of_op.get(prod, 0)
        if not unit:
            return False
        for c in consumers_of.get(v, ()):
            if not pure_compute(c) or unit_of_op.get(c, 0) != unit:
                return False
        return True

    def agnostic_consumers(v):
        return all(op_name.get(c, "") in AGNOSTIC for c in consumers_of.get(v, ()))

    selected = {}   # op id -> class
    rewire = {}     # result value -> source value
    reject = Counter()

    for op in view["operations"]:
        oid, name = op[0], strings[op[1] - 1]
        if not name.startswith("core.compute.") or name in (CONSTANT_KIND, EXPR_KIND):
            continue
        operands, results = op[4], op[5]
        if not results or not operands:
            continue
        r = results[0]
        if not eligible_result(r):
            continue
        rt = value_type[r]
        rw = type_width.get(rt, 0)
        cls = src = None
        if name == "core.compute.assign" and len(operands) == 1:
            x = operands[0]
            if value_type[x] == rt:
                cls, src = "assign_strict", x
            elif type_width.get(value_type[x], 0) == rw and agnostic_consumers(r):
                cls, src = "assign_width", x
            else:
                reject["assign_type"] += 1
        elif name == "core.compute.sliceStatic" and len(operands) == 1:
            start = end = None
            for p in (op[7] if len(op) > 7 else []):
                pn = strings[p[0] - 1] if isinstance(p[0], int) else str(p[0])
                if p[1] == "int" and pn == "sliceStart":
                    start = int(p[2])
                elif p[1] == "int" and pn == "sliceEnd":
                    end = int(p[2])
            x = operands[0]
            if start is not None and end is not None and start >= 0 and end >= start:
                w = end - start + 1
                if start == 0 and end + 1 == type_width.get(value_type[x], -1) and rw == w:
                    if value_type[x] == rt:
                        cls, src = "slice_full_strict", x
                    elif agnostic_consumers(r):
                        cls, src = "slice_full_width", x
                elif x in const_vals:
                    if not 1 <= w <= 64:
                        reject["const_slice_cse_miss"] += 1
                    elif const_vals[x] >= (1 << 64) and start + w > 64:
                        # value bits above 63 unresolvable from a u64 window
                        reject["const_slice_range"] += 1
                    else:
                        want = (const_vals[x] >> start) & ((1 << w) - 1)
                        hit = cse_hit((rt, want), oid)
                        if hit is not None:
                            cls, src = "const_slice", hit
                        else:
                            reject["const_slice_cse_miss"] += 1
        elif name == "core.compute.not" and len(operands) == 1:
            prod = producer_of.get(operands[0], 0)
            if prod and op_name.get(prod) == "core.compute.not":
                inner_ops = op_operands.get(prod, ())
                if (inner_ops and value_type.get(inner_ops[0]) == rt
                        and len(consumers_of.get(operands[0], ())) == 1):
                    if two_state.get(rt, False):
                        cls, src = "not_not", inner_ops[0]
                    else:
                        reject["twostate_guard"] += 1
        elif name in CMP_SELF and len(operands) == 2 and operands[0] == operands[1]:
            if not two_state.get(rt, False) or not two_state.get(value_type[operands[0]], False):
                reject["twostate_guard"] += 1
            else:
                hit = cse_hit((rt, CMP_SELF[name] & ((1 << rw) - 1)), oid) if 1 <= rw <= 64 else None
                if hit is not None:
                    cls, src = f"self_{name.split('.')[-1]}", hit
                else:
                    reject["self_cmp_cse_miss"] += 1
        if cls:
            selected[oid] = cls
            rewire[r] = src

    # cascade DCE fixpoint over pure-compute local ops (constants excluded)
    uses = defaultdict(int)
    for op in view["operations"]:
        if op[0] in selected:
            continue
        for v in op[4]:
            uses[v] += 1
    # rewiring transfers every use of the folded result to its source
    for r, src in rewire.items():
        uses[src] += uses.get(r, 0)
        uses[r] = 0
    fix = True
    while fix:
        fix = False
        for op in view["operations"]:
            oid = op[0]
            if oid in selected or not pure_compute(oid):
                continue
            results = op[5]
            if not results or len(results) != 1:
                continue
            r = results[0]
            if uses.get(r, 0) != 0:
                continue
            if not eligible_result(r):
                continue
            selected[oid] = "dce_cascade"
            fix = True
            for v in op[4]:
                uses[v] -= 1

    return selected, reject, rewire


def dynamic_savings(view, selected, run_path):
    """Sum of unit body fires per class (same-model join with baseline run)."""
    body = {}
    with open(run_path) as fh:
        for line in fh:
            m = SN_LINE.match(line)
            if m:
                body[int(m.group(1))] = int(m.group(3))
    dyn = Counter()
    for oid, cls in selected.items():
        dyn[cls] += body.get(view["unit_of_op"].get(oid, 0), 0)
    return dyn


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True)
    ap.add_argument("--run")
    ap.add_argument("--output", required=True)
    ap.add_argument("--cycles", type=int, default=100001)
    args = ap.parse_args()

    model = json.loads(Path(args.model).read_bytes())
    view = view_from_model(model)
    view["operations"] = model["operations"]
    tables = tables_from_model(model)
    selected, reject, rewire = select(view, tables)

    classes = Counter(selected.values())
    dyn = dynamic_savings(view, selected, args.run) if args.run else Counter()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "selected.json").write_text(json.dumps({str(k): v for k, v in selected.items()}) + "\n")
    summary = {
        "selected_ops": len(selected),
        "classes": {cls: classes.get(cls, 0) for cls in CLASSES if classes.get(cls, 0)},
        "rejects": dict(reject.most_common()),
        "dynamic_removed": sum(dyn.values()) if args.run else None,
        "dynamic_by_class": dict(dyn) if args.run else None,
        "cycles": args.cycles,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    lines = ["# NO00016 residue-fold census", "",
             f"selected ops: **{len(selected)}**", ""]
    if args.run:
        tot = sum(dyn.values())
        lines.append(f"dynamic execs removed: **{tot}** ({tot / args.cycles:.1f}/cycle)")
        lines.append("")
        lines.append("| class | static | dynamic | dyn/cycle |")
        lines.append("| --- | ---: | ---: | ---: |")
        for cls, n in classes.most_common():
            lines.append(f"| {cls} | {n} | {dyn.get(cls, 0)} | {dyn.get(cls, 0) / args.cycles:.1f} |")
    else:
        lines.append("| class | static |")
        lines.append("| --- | ---: |")
        for cls, n in classes.most_common():
            lines.append(f"| {cls} | {n} |")
    if reject:
        lines += ["", "rejects: " + ", ".join(f"{k}={v}" for k, v in reject.most_common())]
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print(f"selected={len(selected)} dyn={sum(dyn.values()) if args.run else 'n/a'} -> {out}")


if __name__ == "__main__":
    main()
