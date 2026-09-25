#!/usr/bin/env python3
"""NO00013 static census: zero-new-edge boundary-op migration candidates
(single-op and cone-closure variants).

A boundary value v produced by pure-compute op X in unit A, all of whose
consumers are compute ops inside a single different unit B, can be migrated
(X moved into B immediately before its earliest consumer) so that v stops
being a boundary value: the boundary store, change detection and fanout
arming for v disappear. Migration is statically safe (no activation widening)
exactly when every operand of the migrated ops is already available in B
without adding a fanout/input edge. Operands that are A-local values produced
by other pure-compute ops can be co-migrated as a cone: the cone must be
closed (every consumer of every cone intermediate is either in the cone or in
B) and all of its external operands must satisfy the same availability rule.
core.compute.constant producers are cloned for free (no consumer closure
needed, zero activation semantics).

Equivalence (verified against the emitter): init() flags every active word
with 255 so the first eval runs every unit once in flattened topological
order, publishing initial values before any consumer reads them; within a
round the compute phase dispatch follows the same topological order, and all
of X's operand producers precede X, hence precede B's insertion point, so X
re-evaluates in B with exactly the operand values A would have seen. B's
firing set is unchanged (v-change events are a subset of X's-operand-change
events, all of which already trigger B); A's firing set can only shrink.

Inputs
  --model      production mapped checkpoint JSON (NO00004/NO00010 flow archive)
  --run        NO00012 diagnostic run log (for [grhsim-vchg] and [grhsim-dyn]
               sn rows; optional, only needed for the profit re-score)
  --output     directory for summary.md / summary.json
  --cycles     guest cycles (default 100001)

Census (static, dependency-driven; no dynamic data influences eligibility):
  anchors       boundary values passing the anchor prefilter (single consumer
                unit, compute-only consumers, pure-compute single-result
                producer in a different unit, 1..64b, no refs, not event gate)
  cone          minimal co-migration cone per anchor (constants cloned free);
                failure reasons: third_unit_edge / input_unseen /
                shared_intermediate / non_pure_member / wide_member
  caps          eligibility and profit for cone-size caps 1,2,4,8,16,32,inf

Profit re-score (dynamic, estimate only; same constants as NO00012):
  save    = wr_v * (K_DETECT + K_STORE)          (detection + store removed)
  reeval  = body_B * sum K_EVAL(cone ops)        (conservative: no body_A credit)
  profit  = save - reeval                        (zero new edges => widen == 0)
"""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grhsim_vchg_profile import (SN_LINE, VCHG_LINE,  # noqa: E402
                                 coldness_bucket, cons_class, width_bucket)

KIND_SUPER = 3
STORAGE_BOUNDARY = 2
CONSTANT_KIND = "core.compute.constant"
EXPR_KIND = "core.compute.expr"
COMPUTE_PREFIX = "core.compute."

CAPS = (1, 2, 4, 8, 16, 32, 0)  # 0 = no cap

K_DETECT = 3
K_STORE = 1
K_EVAL = {"core.compute.mux": 3, "core.compute.and": 2, "core.compute.or": 2,
          "core.compute.xor": 2, "core.compute.not": 2, "core.compute.eq": 2,
          "core.compute.logicNot": 1, "core.compute.sliceStatic": 2,
          "core.compute.bitSelect": 2, "core.compute.add": 3, "core.compute.sub": 3}


class MigrationView:
    """Static model facts needed for migration eligibility (plain attributes so
    tests can populate them directly without a checkpoint JSON)."""

    def __init__(self):
        self.op_name = {}          # op id -> kind name
        self.op_operands = {}      # op id -> [value ids]
        self.op_results = {}       # op id -> [value ids]
        self.op_has_refs = {}      # op id -> bool
        self.producer_of = {}      # value id -> op id (0 when none)
        self.consumers_of = {}     # value id -> [op ids]
        self.unit_of_op = {}       # op id -> supernode partition id (0 = none)
        self.unit_inputs = {}      # supernode id -> set of cross-unit operand values
        self.unit_op_count = Counter()
        self.is_boundary = set()   # value ids with Boundary storage
        self.event_gate_values = set()
        self.width = {}            # value id -> logic width (0 for non-logic)

    def producer_unit(self, value):
        return self.unit_of_op.get(self.producer_of.get(value, 0), 0)

    def pure_compute(self, op):
        name = self.op_name.get(op, "")
        return (name.startswith(COMPUTE_PREFIX) and name != EXPR_KIND
                and not self.op_has_refs.get(op, True)
                and len(self.op_results.get(op, ())) == 1)


def load_view(model_path):
    """Build a MigrationView from a mapped checkpoint JSON (schema per
    wolvrix writeCpuMapping: partition row = [id, parent, kind, phase,
    children, ops, eventGate, ...]; eventGate = [] or [source, [[v, edge]...]])."""
    model = json.loads(Path(model_path).read_bytes())
    strings = model["strings"]
    types = {t[0]: t for t in model["types"]}
    payload = model["mappings"][0][-1]
    partitions = {p[0]: p for p in payload[2]}
    value_slots = payload[3][3]

    view = MigrationView()
    view.is_boundary = {vid for vid, slot in enumerate(value_slots, start=1)
                        if slot[1] == STORAGE_BOUNDARY}
    for row in partitions.values():
        gate = row[6] if len(row) > 6 else []
        if gate:
            for event in gate[1]:
                view.event_gate_values.add(event[0])

    unit_of_op = {}
    for pid, part in partitions.items():
        if part[2] != KIND_SUPER:
            continue
        stack = [pid]
        while stack:
            node = partitions[stack.pop()]
            stack.extend(node[4])
            for op_id in node[5]:
                unit_of_op[op_id] = pid
                view.unit_op_count[pid] += 1
    view.unit_of_op = unit_of_op

    consumers_of = defaultdict(list)
    for op in model["operations"]:
        oid, name_idx, _, _, operands, results, refs, _ = op[:8]
        view.op_name[oid] = strings[name_idx - 1]
        view.op_operands[oid] = operands
        view.op_results[oid] = results
        view.op_has_refs[oid] = bool(refs)
        for v in results:
            view.producer_of[v] = oid
        for v in operands:
            consumers_of[v].append(oid)
    view.consumers_of = consumers_of

    for v in model["values"]:
        t = types[v[1]]
        view.width[v[0]] = t[3] if t[2] == "logic" else 0

    unit_inputs = defaultdict(set)
    for oid, unit in unit_of_op.items():
        for w in view.op_operands.get(oid, ()):  # cross-unit operand => unit input
            if view.producer_unit(w) != unit:
                unit_inputs[unit].add(w)
    view.unit_inputs = unit_inputs
    return view


def anchor_prefilter(view, vid):
    """Return (xop, unit_a, unit_b, kind, width) for a migratable anchor value,
    or a rejection reason string."""
    cons = view.consumers_of.get(vid, [])
    if not cons:
        return "dead"
    if {cons_class(view.op_name.get(c, "?")) for c in cons} != {"compute"}:
        return "non_compute_consumer"
    units = {view.unit_of_op.get(c, 0) for c in cons}
    if len(units) != 1 or 0 in units:
        return "multi_consumer_unit"
    unit_b = next(iter(units))
    xop = view.producer_of.get(vid, 0)
    unit_a = view.unit_of_op.get(xop, 0)
    if unit_a == 0 or unit_a == unit_b:
        return "producer_not_in_unit"
    kind = view.op_name.get(xop, "")
    if not kind.startswith(COMPUTE_PREFIX) or kind == EXPR_KIND:
        return "producer_kind"
    if view.op_has_refs.get(xop, True) or len(view.op_results.get(xop, ())) != 1:
        return "refs_or_results"
    width = view.width.get(vid, 0)
    if width < 1 or width > 64:
        return "width"
    if vid in view.event_gate_values:
        return "event_gate"
    return (xop, unit_a, unit_b, kind, width)


def build_cone(view, xop, unit_a, unit_b):
    """Minimal co-migration cone for anchor op xop (in unit_a, consumers in
    unit_b). Returns (member op ids excluding free constant clones, None) or
    (None, failure reason). Deterministic: the closure is unique, so cone size
    is the minimal feasible cap."""
    inputs_b = view.unit_inputs.get(unit_b, set())
    members = {xop}
    stack = [xop]
    while stack:
        y = stack.pop()
        for w in view.op_operands.get(y, ()):
            if view.producer_unit(w) == unit_b or w in inputs_b:
                continue
            prod = view.producer_of.get(w, 0)
            if prod == 0:
                return None, "input_unseen"
            if view.op_name.get(prod, "") == CONSTANT_KIND:
                continue  # inlined at any read site by the emitter, wherever it lives
            if view.unit_of_op.get(prod, 0) != unit_a:
                return None, "third_unit_edge"
            if prod in members:
                continue
            if not view.pure_compute(prod):
                return None, "non_pure_member"
            if view.width.get(w, 0) < 1 or view.width.get(w, 0) > 64:
                return None, "wide_member"
            for cons in view.consumers_of.get(w, ()):
                if cons in members:
                    continue
                if view.unit_of_op.get(cons, 0) != unit_b:
                    return None, "shared_intermediate"
            members.add(prod)
            stack.append(prod)
    return members, None


def cone_census(view):
    """Run anchor prefilter + cone closure over all boundary values.

    Returns (anchors, rejections) where anchors is a list of dicts with v, op,
    kind, unit_a, unit_b, width, cone (sorted member op ids), cone_size."""
    anchors = []
    rejections = Counter()
    for vid in sorted(view.is_boundary):
        pre = anchor_prefilter(view, vid)
        if isinstance(pre, str):
            rejections[pre] += 1
            continue
        xop, unit_a, unit_b, kind, width = pre
        members, fail = build_cone(view, xop, unit_a, unit_b)
        if members is None:
            rejections[fail] += 1
            continue
        anchors.append({"v": vid, "op": xop, "kind": kind, "unit_a": unit_a,
                        "unit_b": unit_b, "width": width,
                        "cone": sorted(members), "cone_size": len(members)})
    return anchors, rejections


def rescore(anchors, vchg, body):
    """Dynamic profit re-score (estimate only)."""
    kind_of = {}
    rows = []
    for cand in anchors:
        wr, ch = vchg.get(cand["v"], (0, 0))
        save = wr * (K_DETECT + K_STORE)
        rows.append({**cand, "wr": wr, "ch": ch, "save": save, "body_b": body.get(cand["unit_b"], 0)})
    return rows


def profit_of(row, view):
    reeval = row["body_b"] * sum(K_EVAL.get(view.op_name.get(op, ""), 3)
                                 for op in row["cone"])
    return row["save"] - reeval, reeval


def parse_run(text):
    vchg, body = {}, {}
    for line in text.splitlines():
        m = VCHG_LINE.match(line)
        if m:
            vchg[int(m.group(1))] = (int(m.group(2)), int(m.group(3)))
            continue
        m = SN_LINE.match(line)
        if m:
            body[int(m.group(1))] = int(m.group(3))
    return vchg, body


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=100001)
    args = parser.parse_args(argv)

    view = load_view(args.model)
    anchors, rejections = cone_census(view)

    out = {"boundary": len(view.is_boundary), "anchors": len(anchors),
           "rejections": dict(rejections),
           "cone_sizes": dict(Counter(a["cone_size"] for a in anchors)),
           "by_kind": dict(Counter(a["kind"] for a in anchors)),
           "by_width": dict(Counter(width_bucket(a["width"]) for a in anchors))}
    lines = ["# NO00013 migration census", "",
             f"boundary values: {out['boundary']}",
             f"anchors (cone feasible): {out['anchors']}", "", "## rejections"]
    lines += [f"- {k}: {v}" for k, v in sorted(rejections.items())]
    lines += ["", "## cone size distribution"]
    lines += [f"- size {k}: {v}" for k, v in sorted(out["cone_sizes"].items())]

    vchg, body = ({}, {})
    if args.run:
        vchg, body = parse_run(args.run.read_text(errors="replace"))
    rows = rescore(anchors, vchg, body) if vchg else []

    cap_table = []
    for cap in CAPS:
        subset = [a for a in anchors if cap == 0 or a["cone_size"] <= cap]
        entry = {"cap": cap or "inf", "candidates": len(subset),
                 "cone_ops": sum(a["cone_size"] for a in subset)}
        if rows:
            srows = [r for r in rows if cap == 0 or r["cone_size"] <= cap]
            profits = [profit_of(r, view) for r in srows]
            entry["save_pc"] = sum(r["save"] for r in srows) / args.cycles
            entry["reeval_pc"] = sum(p[1] for p in profits) / args.cycles
            entry["profit_pc"] = sum(p[0] for p in profits) / args.cycles
            entry["positive_n"] = sum(1 for p in profits if p[0] > 0)
            entry["positive_pc"] = sum(p[0] for p in profits if p[0] > 0) / args.cycles
        cap_table.append(entry)
    out["caps"] = cap_table
    lines += ["", "## cap sweep" + (" (dynamic profit re-score)" if rows else "")]
    for entry in cap_table:
        line = (f"- cap {entry['cap']}: candidates={entry['candidates']} "
                f"cone_ops={entry['cone_ops']}")
        if "profit_pc" in entry:
            line += (f" save={entry['save_pc']:+.1f}/cyc reeval={entry['reeval_pc']:+.1f}/cyc"
                     f" profit={entry['profit_pc']:+.1f}/cyc"
                     f" positive={entry['positive_n']} ({entry['positive_pc']:+.1f}/cyc)")
        lines.append(line)

    if rows:
        agg = defaultdict(lambda: {"n": 0, "save": 0.0, "profit": 0.0})
        for row in rows:
            profit, _ = profit_of(row, view)
            key = (row["kind"], coldness_bucket(row["ch"] / row["wr"] if row["wr"] else 0.0))
            agg[key]["n"] += 1
            agg[key]["save"] += row["save"] / args.cycles
            agg[key]["profit"] += profit / args.cycles
        out["by_class"] = {str(k): v for k, v in
                           sorted(agg.items(), key=lambda kv: -kv[1]["profit"])[:20]}
        lines += ["", "## top classes by profit/cycle"]
        lines += [f"- {k}: n={v['n']} save={v['save']:+.1f} profit={v['profit']:+.1f}"
                  for k, v in (list(agg.items()) and
                               sorted(agg.items(), key=lambda kv: -kv[1]["profit"])[:20])]

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(out, indent=1))
    (args.output / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
