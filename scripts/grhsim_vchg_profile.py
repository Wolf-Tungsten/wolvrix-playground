#!/usr/bin/env python3
"""NO00012 per-value change-rate profile, monitored-set activation economics,
and wide-value cost baseline (diagnostic).

Inputs
  --model        production mapped checkpoint JSON (NO00004 flow archive)
  --run1/--run2  diagnostic run logs (raw emu logs with [grhsim-vchg]/[grhsim-dyn])
  --gen-model    generated C++ model dir of the diagnostic build (scan order +
                 static wide-helper census)
  --output       directory for summary.md / summary.json
  --cycles       guest cycles (default 100001)

Gates (all must pass; failures are reported and exit non-zero)
  endpoint: both runs match --expect-endpoint instrCnt,cycleCnt,guest,pc exactly
  determinism: run1/run2 vchg rows, sn rows and kind rows identical
  closure: sum(wr) and sum(ch) over vchg rows equal the kind-row aggregates of
           the same run exactly (same counter sites), and match --expect-totals

M-vchg: per-boundary-value chg distribution (zero share, percentiles, top
shares) stratified by producer kind x width bucket; monitored vs silent vs
never-evaluated decomposition of the 812,234 boundary values.

M-econ: per-value economics join = chg rate x producer-unit body fires x
consumer-unit body fires x generated-code scan order; candidate tables for
monitored-set shrinkage (single-consumer pure-compute op migration re-scored
with measured chg) and cold/hot structure.

M-wide: static wide-helper call-site census (generated code), wide boundary
value count/change stats, and the perf-attributed dynamic cost recorded from
the NO00011 instruction attribution archive.
"""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys

# ---------------------------------------------------------------- pure parsers

ANSI = re.compile(r"\x1b\[[0-9;]*m")
VCHG_LINE = re.compile(r"^\[grhsim-vchg] v (\d+) wr=(\d+) ch=(\d+)$")
SN_LINE = re.compile(r"^\[grhsim-dyn] sn (\d+) act=(\d+) body=(\d+) grp=(\d+) chg=(\d+)$")
KIND_LINE = re.compile(r"^\[grhsim-dyn] kind (\S+) wr=(\d+) ch=(\d+) silent=(\d+)$")
PC_LINE = re.compile(r"EXCEEDING CYCLE/INSTR LIMIT at pc = (0x[0-9a-fA-F]+)")
INSTR_LINE = re.compile(r"Core-0 instrCnt = ([\d,]+), cycleCnt = ([\d,]+)")
GUEST_LINE = re.compile(r"Guest cycle spent: ([\d,]+)")
HOST_LINE = re.compile(r"Host time spent: ([\d,]+)ms")


def strip_ansi(text):
    return ANSI.sub("", text)


def parse_vchg(text):
    """-> {value_index: (wr, ch)}; duplicate indices raise ValueError."""
    rows = {}
    for line in strip_ansi(text).splitlines():
        m = VCHG_LINE.match(line)
        if m:
            idx = int(m.group(1))
            if idx in rows:
                raise ValueError(f"duplicate vchg row for value {idx}")
            rows[idx] = (int(m.group(2)), int(m.group(3)))
    return rows


def parse_sn(text):
    """-> {unit_index: (act, body, grp, chg)}."""
    rows = {}
    for line in strip_ansi(text).splitlines():
        m = SN_LINE.match(line)
        if m:
            rows[int(m.group(1))] = (int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
    return rows


def parse_kinds(text):
    """-> {kind_name: (wr, ch, silent)}."""
    rows = {}
    for line in strip_ansi(text).splitlines():
        m = KIND_LINE.match(line)
        if m:
            rows[m.group(1)] = (int(m.group(2)), int(m.group(3)), int(m.group(4)))
    return rows


def _int_commas(text):
    return int(text.replace(",", ""))


def parse_endpoint(text):
    """-> {instrCnt, cycleCnt, guest, pc, host_ms} (None for missing fields)."""
    text = strip_ansi(text)
    out = {"instrCnt": None, "cycleCnt": None, "guest": None, "pc": None, "host_ms": None}
    m = PC_LINE.search(text)
    if m:
        out["pc"] = m.group(1).lower()
    m = INSTR_LINE.search(text)
    if m:
        out["instrCnt"] = _int_commas(m.group(1))
        out["cycleCnt"] = _int_commas(m.group(2))
    m = GUEST_LINE.search(text)
    if m:
        out["guest"] = _int_commas(m.group(1))
    m = HOST_LINE.search(text)
    if m:
        out["host_ms"] = _int_commas(m.group(1))
    return out


def check_endpoint(endpoint, expected):
    """expected = (instrCnt, cycleCnt, guest, pc). -> list of mismatch strings."""
    instr, cycles, guest, pc = expected
    fails = []
    for key, want in (("instrCnt", instr), ("cycleCnt", cycles), ("guest", guest)):
        if endpoint.get(key) != want:
            fails.append(f"{key}={endpoint.get(key)} != {want}")
    if (endpoint.get("pc") or "").lower() != pc.lower():
        fails.append(f"pc={endpoint.get('pc')} != {pc}")
    return fails


def closure_check(vchg, kinds):
    """Sum vchg rows vs kind aggregates. -> dict with ok flags."""
    sum_wr = sum(w for w, _ in vchg.values())
    sum_ch = sum(c for _, c in vchg.values())
    kind_wr = sum(w for w, _, _ in kinds.values())
    kind_ch = sum(c for _, c, _ in kinds.values())
    return {"sum_wr": sum_wr, "sum_ch": sum_ch, "kind_wr": kind_wr, "kind_ch": kind_ch,
            "wr_ok": sum_wr == kind_wr, "ch_ok": sum_ch == kind_ch}


def dist_stats(counts):
    """Distribution of a list of non-negative ints.

    -> {n, total, zero_share, p50, p90, p99, max, top1p_share, top10p_share}
    Percentiles are nearest-rank; top shares use ceil(n*p) largest entries.
    """
    n = len(counts)
    if n == 0:
        return {"n": 0, "total": 0, "zero_share": 0.0, "p50": 0, "p90": 0, "p99": 0,
                "max": 0, "top1p_share": 0.0, "top10p_share": 0.0}
    ordered = sorted(counts)
    total = sum(ordered)

    def pct(p):
        rank = max(1, int(p * n + 0.999999))
        return ordered[rank - 1]

    def top_share(p):
        k = max(1, int(p * n + 0.999999))
        return (sum(ordered[-k:]) / total) if total else 0.0

    zeros = sum(1 for c in ordered if c == 0)
    return {"n": n, "total": total, "zero_share": zeros / n, "p50": pct(0.50),
            "p90": pct(0.90), "p99": pct(0.99), "max": ordered[-1],
            "top1p_share": top_share(0.01), "top10p_share": top_share(0.10)}


# ---------------------------------------------------------------- scan order

EVAL_TASK = re.compile(r"if\(cpu_flags\[\d+\]\)cpu_task_(\d+)\(\);")
TASK_DEF = re.compile(r"^grhsim_SimTop_task_(\d+)\.cpp$")
SN_ACT = re.compile(r"cpu_dyn_sn_act\[(\d+)\]")


def eval_task_order(simtop_cpp_text):
    """eval() task call sequence -> {task_id: position} (0-based)."""
    return {int(t): i for i, t in enumerate(EVAL_TASK.findall(simtop_cpp_text))}


def unit_scan_order(gen_dir):
    """Unit -> (task_id, position within task) from first cpu_dyn_sn_act mention.

    Raises ValueError if a unit appears in two tasks or twice in one task.
    """
    gen_dir = Path(gen_dir)
    order = {}
    for path in sorted(gen_dir.glob("grhsim_SimTop_task_*.cpp")):
        m = TASK_DEF.match(path.name)
        if not m:
            continue
        task_id = int(m.group(1))
        seen = []
        for line in path.read_text(errors="replace").splitlines():
            for hit in SN_ACT.findall(line):
                seen.append(int(hit))
        first = {}
        for pos, unit in enumerate(seen):
            if unit in first:
                raise ValueError(f"unit {unit} twice in task {task_id}")
            first[unit] = pos
        for unit, pos in first.items():
            if unit in order:
                raise ValueError(f"unit {unit} in tasks {order[unit][0]} and {task_id}")
            order[unit] = (task_id, pos)
    return order


# ---------------------------------------------------------------- wide census

WIDE_HELPERS = [
    "grhsim_insert_scalar_words", "grhsim_insert_words",
    "cpu_bitwise_words_changed", "cpu_shift_words_changed",
    "cpu_arithmetic_words_changed", "cpu_replicate_words_changed",
    "grhsim_and_words", "grhsim_or_words", "grhsim_xor_words", "grhsim_not_words",
    "grhsim_shl_words", "grhsim_lshr_words", "grhsim_ashr_words",
    "grhsim_add_words", "grhsim_sub_words", "memcmp",
    "grhsim_trunc_u64", "grhsim_cast_u64", "grhsim_sign_extend_i64", "grhsim_index_words",
]


def helper_census_text(text):
    """Count wide-helper call sites in one source text -> Counter."""
    counts = Counter()
    for name in WIDE_HELPERS:
        counts[name] += len(re.findall(r"\b" + re.escape(name) + r"\s*(?:<[^;>]*>)?\s*\(", text))
    return counts


def helper_census(gen_dir):
    """Aggregate helper call sites over generated task/hpp sources."""
    gen_dir = Path(gen_dir)
    total = Counter()
    per_file = {}
    for path in sorted(gen_dir.glob("grhsim_SimTop*.cpp")) + sorted(gen_dir.glob("grhsim_SimTop*.hpp")):
        counts = helper_census_text(path.read_text(errors="replace"))
        if sum(counts.values()):
            per_file[path.name] = counts
            total.update(counts)
    return total, per_file


# ---------------------------------------------------------------- model join

KIND_SUPER = 3
STORAGE_BOUNDARY = 2
PORT_OPS = {"core.state.regWrite", "core.state.latchWrite", "core.state.memWrite",
            "core.state.memWriteSeq", "core.state.memFill", "core.state.memAssign"}
READ_OPS = {"core.state.read", "core.state.memRead"}
SINK_PREFIX = ("core.system.", "core.dpi.", "core.output.")


def cons_class(name):
    if name.startswith("core.compute."):
        return "compute"
    if name in PORT_OPS:
        return "port"
    if name in READ_OPS:
        return "read"
    if name.startswith(SINK_PREFIX):
        return "sink"
    return "other"


def width_bucket(width):
    if width <= 1:
        return "1"
    if width <= 8:
        return "2-8"
    if width <= 32:
        return "9-32"
    if width <= 64:
        return "33-64"
    return ">64"


class ModelView:
    """Boundary values with producer kind/width/unit and consumer classes/units."""

    def __init__(self, model_path):
        model = json.loads(Path(model_path).read_bytes())
        strings = model["strings"]
        types = {t[0]: t for t in model["types"]}
        payload = model["mappings"][0][-1]
        partitions = {p[0]: p for p in payload[2]}
        value_slots = payload[3][3]

        op_name = [""] * (len(model["operations"]) + 1)
        producer_of = {}
        consumers_of = defaultdict(list)
        for op in model["operations"]:
            oid, name_idx, _, _, operands, results, refs, _ = op[:8]
            op_name[oid] = strings[name_idx - 1]
            for v in results:
                producer_of[v] = oid
            for v in operands:
                consumers_of[v].append(oid)

        unit_of_op = {}
        unit_op_count = Counter()
        for pid, part in partitions.items():
            if part[2] != KIND_SUPER:
                continue
            stack = [pid]
            while stack:
                node = partitions[stack.pop()]
                stack.extend(node[4])
                for op_id in node[5]:
                    unit_of_op[op_id] = pid
                    unit_op_count[pid] += 1

        width_of = {}
        for v in model["values"]:
            t = types[v[1]]
            width_of[v[0]] = t[3] if t[2] == "logic" else 0

        self.boundary = [vid for vid, slot in enumerate(value_slots, start=1)
                         if slot[1] == STORAGE_BOUNDARY]
        self.is_boundary = set(self.boundary)
        self.unit_op_count = unit_op_count
        self.producer_kind = {}
        self.producer_unit = {}
        self.width = {}
        self.consumer_units = {}
        self.consumer_classes = {}
        for vid in self.boundary:
            prod = producer_of.get(vid, 0)
            self.producer_kind[vid] = op_name[prod] if prod else "<none>"
            self.producer_unit[vid] = unit_of_op.get(prod, 0)
            self.width[vid] = width_of.get(vid, 0)
            cons = consumers_of.get(vid, [])
            units = {unit_of_op[c] for c in cons if unit_of_op.get(c)}
            units.discard(0)
            units.discard(self.producer_unit[vid])
            self.consumer_units[vid] = units
            self.consumer_classes[vid] = "".join(sorted({cons_class(op_name[c])[:1] for c in cons})) or "-"

        # Migration candidates (IR-static): single consumer unit, pure-compute
        # producer, <=64b, consumers all compute-class. Collect producer-op
        # operands in a second pass for the new-edge pricing in econ_tables.
        cand_values = {vid for vid in self.boundary
                       if len(self.consumer_units[vid]) == 1
                       and self.consumer_classes[vid] == "c"
                       and self.producer_kind[vid].startswith("core.compute.")
                       and self.width[vid] <= 64}
        cand_ops = {producer_of[vid]: vid for vid in cand_values if producer_of.get(vid)}
        self.candidate_operands = {}
        for op in model["operations"]:
            oid = op[0]
            if oid in cand_ops:
                self.candidate_operands[cand_ops[oid]] = op[4]


# ---------------------------------------------------------------- economics

def coldness_bucket(rate):
    if rate == 0.0:
        return "0"
    if rate < 0.001:
        return "(0,0.1%)"
    if rate < 0.01:
        return "[0.1%,1%)"
    if rate < 0.1:
        return "[1%,10%)"
    return ">=10%"


# Cost model constants for the migration profit estimate (instructions, from the
# NO00010/NO00011 disassembly censuses): detection = compare + flag-or (+RMW on
# the group flag), boundary store = 1 store per write, op re-eval per kind,
# activation widening = new-edge changes x consumer unit body ops x K_OP
# (= M-idens 3.86 instr/dynOp). Widening is an upper bound (co-activation of
# edges collapses); unmonitored new edges additionally need fresh detection.
K_DETECT = 3
K_STORE = 1
K_OP = 3.86
K_EVAL = {"core.compute.mux": 3, "core.compute.and": 2, "core.compute.or": 2,
          "core.compute.xor": 2, "core.compute.not": 2, "core.compute.eq": 2,
          "core.compute.logicNot": 1, "core.compute.sliceStatic": 2,
          "core.compute.bitSelect": 2, "core.compute.add": 3, "core.compute.sub": 3}


def migration_profit(view, vchg, sn):
    """Re-score single-consumer pure-compute migration candidates with measured chg.

    Per candidate value v (producer op X, consumer unit C):
      save       = wr_v * (K_DETECT + K_STORE)     (detection + boundary store removed)
      reeval     = body_C * K_EVAL(kind)           (X re-evaluates on every C body fire)
      widen      = sum ch_w * ops_C * K_OP         (new-edge change activations, monitored w)
      new_detect = sum body_{P_w} * K_DETECT       (unmonitored new edges need detection)
      profit     = save - reeval - widen - new_detect
    Constant operands (core.compute.constant) are free (folded at emit).
    -> (per-candidate rows, aggregate by (kind, coldness))
    """
    body = {u: b for u, (_, b, _, _) in sn.items()}
    rows = []
    for vid, operands in view.candidate_operands.items():
        wr, ch = vchg.get(vid, (0, 0))
        kind = view.producer_kind.get(vid, "?")
        punit = view.producer_unit.get(vid, 0)
        cons = next(iter(view.consumer_units[vid]))
        body_c = body.get(cons, 0)
        ops_c = view.unit_op_count.get(cons, 0)
        widen = 0.0
        new_detect = 0
        edges = 0
        cold_edges = 0
        for w in operands:
            if view.producer_kind.get(w) == "core.compute.constant":
                continue
            if not view.is_boundary.__contains__(w):
                continue
            w_unit = view.producer_unit.get(w, 0)
            if w_unit == cons or w_unit == 0:
                continue
            edges += 1
            w_wr, w_ch = vchg.get(w, (0, 0))
            if w_wr:
                widen += w_ch * ops_c * K_OP
                if w_ch == 0:
                    cold_edges += 1
            else:
                new_detect += body.get(w_unit, 0) * K_DETECT
        save = wr * (K_DETECT + K_STORE)
        reeval = body_c * K_EVAL.get(kind, 3)
        profit = save - reeval - widen - new_detect
        rows.append({"v": vid, "kind": kind, "wr": wr, "ch": ch,
                     "rate": (ch / wr) if wr else 0.0, "cons": cons,
                     "body_c": body_c, "ops_c": ops_c, "edges": edges,
                     "cold_edges": cold_edges, "save": save, "reeval": reeval,
                     "widen": widen, "new_detect": new_detect, "profit": profit})

    agg = defaultdict(lambda: {"ops": 0, "save": 0, "reeval": 0, "widen": 0.0,
                               "new_detect": 0, "profit": 0.0, "profitable": 0})
    for r in rows:
        key = (r["kind"], coldness_bucket(r["rate"]))
        a = agg[key]
        a["ops"] += 1
        a["save"] += r["save"]
        a["reeval"] += r["reeval"]
        a["widen"] += r["widen"]
        a["new_detect"] += r["new_detect"]
        a["profit"] += r["profit"]
        a["profitable"] += 1 if r["profit"] > 0 else 0
    return rows, agg


def undumped_decomposition(view, vchg, sn):
    """Split boundary values without vchg rows into dead (producer unit never
    fired) vs evaluated-without-detection (aliased / static-constant / silent
    write classes); the latter's producer body fires bound the silent writes.
    """
    body = {u: b for u, (_, b, _, _) in sn.items()}
    dumped = set(vchg)
    undumped = [v for v in view.boundary if v not in dumped]
    dead = [v for v in undumped if body.get(view.producer_unit.get(v, 0), 0) == 0]
    nodetect = [v for v in undumped if v not in set(dead)]
    by_kind = Counter(view.producer_kind.get(v, "?") for v in nodetect)
    nodetect_body = sum(body.get(view.producer_unit.get(v, 0), 0) for v in nodetect)
    return {"undumped": len(undumped), "dead": len(dead), "nodetect": len(nodetect),
            "nodetect_by_kind": dict(by_kind.most_common(12)),
            "nodetect_body_fires": nodetect_body}


def econ_tables(view, vchg, sn, cycles):
    """Per-value economics join. Returns (rows, by_coldness, migration).

    rows: per dumped value dicts. by_coldness: aggregate by chg-rate bucket.
    migration: single-consumer pure-compute <=64b candidates re-scored with chg.
    """
    body = {u: b for u, (_, b, _, _) in sn.items()}
    rows = []
    for vid, (wr, ch) in vchg.items():
        punit = view.producer_unit.get(vid, 0)
        bp = body.get(punit, 0)
        rate = (ch / wr) if wr else 0.0
        cunits = view.consumer_units.get(vid, set())
        cbody = sum(body.get(u, 0) for u in cunits)
        rows.append({"v": vid, "kind": view.producer_kind.get(vid, "?"),
                     "width": view.width.get(vid, 0), "punit": punit, "bp": bp,
                     "wr": wr, "ch": ch, "rate": rate, "ncons": len(cunits),
                     "cbody": cbody, "cls": view.consumer_classes.get(vid, "-")})

    cold = {}
    for bucket in ("0", "(0,0.1%)", "[0.1%,1%)", "[1%,10%)", ">=10%"):
        cold[bucket] = {"values": 0, "wr": 0, "ch": 0, "cbody": 0}
    for r in rows:
        agg = cold[coldness_bucket(r["rate"])]
        agg["values"] += 1
        agg["wr"] += r["wr"]
        agg["ch"] += r["ch"]
        agg["cbody"] += r["cbody"]
    return rows, cold


# ---------------------------------------------------------------- orchestration

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--run1", type=Path, required=True)
    ap.add_argument("--run2", type=Path, required=True)
    ap.add_argument("--gen-model", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--cycles", type=int, default=100001)
    ap.add_argument("--expect-endpoint", default="240349,99996,100001,0x80000c0c")
    ap.add_argument("--expect-totals", default="22134521354,1267630634")
    args = ap.parse_args(argv)

    instr, cycl, guest, pc = args.expect_endpoint.split(",")
    expected_endpoint = (int(instr), int(cycl), int(guest), pc)
    exp_wr, exp_ch = (int(x) for x in args.expect_totals.split(","))

    text1 = args.run1.read_text(errors="replace")
    text2 = args.run2.read_text(errors="replace")
    vchg1, vchg2 = parse_vchg(text1), parse_vchg(text2)
    sn1, sn2 = parse_sn(text1), parse_sn(text2)
    kinds1, kinds2 = parse_kinds(text1), parse_kinds(text2)
    ep1, ep2 = parse_endpoint(text1), parse_endpoint(text2)

    gates = []
    fails1 = check_endpoint(ep1, expected_endpoint)
    fails2 = check_endpoint(ep2, expected_endpoint)
    gates.append(("endpoint_run1", not fails1, ";".join(fails1)))
    gates.append(("endpoint_run2", not fails2, ";".join(fails2)))
    mismatch = "mismatch" in strip_ansi(text1).lower() or "mismatch" in strip_ansi(text2).lower()
    gates.append(("difftest_clean", not mismatch, "mismatch found" if mismatch else ""))
    gates.append(("determinism_vchg", vchg1 == vchg2,
                  f"rows {len(vchg1)} vs {len(vchg2)}" if vchg1 != vchg2 else ""))
    gates.append(("determinism_sn", sn1 == sn2, ""))
    gates.append(("determinism_kinds", kinds1 == kinds2, ""))
    clo = closure_check(vchg1, kinds1)
    gates.append(("closure_wr_vs_kinds", clo["wr_ok"], f'{clo["sum_wr"]} vs {clo["kind_wr"]}'))
    gates.append(("closure_ch_vs_kinds", clo["ch_ok"], f'{clo["sum_ch"]} vs {clo["kind_ch"]}'))
    gates.append(("closure_wr_vs_archive", clo["sum_wr"] == exp_wr, f'{clo["sum_wr"]} vs {exp_wr}'))
    gates.append(("closure_ch_vs_archive", clo["sum_ch"] == exp_ch, f'{clo["sum_ch"]} vs {exp_ch}'))

    view = ModelView(args.model)
    cycles = args.cycles
    monitored = {v for v in view.boundary if view.consumer_units[v]}
    silent = set(view.boundary) - monitored
    dumped = set(vchg1)
    never_eval = monitored - dumped
    ch_counts = [c for _, c in vchg1.values()]
    profile = dist_stats(ch_counts)

    # stratified distributions (kind x width bucket), keeping wr/ch sums too
    strata_rows = []
    by_strata = defaultdict(lambda: {"values": 0, "wr": 0, "ch": 0, "chs": []})
    for vid, (wr, ch) in vchg1.items():
        key = (view.producer_kind.get(vid, "?"), width_bucket(view.width.get(vid, 0)))
        agg = by_strata[key]
        agg["values"] += 1
        agg["wr"] += wr
        agg["ch"] += ch
        agg["chs"].append(ch)
    for (kind, wb), agg in sorted(by_strata.items(), key=lambda kv: -kv[1]["ch"]):
        d = dist_stats(agg["chs"])
        strata_rows.append({"kind": kind, "width": wb, "values": agg["values"],
                            "wr": agg["wr"], "ch": agg["ch"],
                            "chg_rate": agg["ch"] / agg["wr"] if agg["wr"] else 0.0,
                            "zero_share": d["zero_share"], "p50": d["p50"], "p99": d["p99"]})

    rows, cold = econ_tables(view, vchg1, sn1, cycles)
    migr_rows, migr_agg = migration_profit(view, vchg1, sn1)
    decomp = undumped_decomposition(view, vchg1, sn1)
    migr_total = {"candidates": len(migr_rows),
                  "profitable": sum(1 for r in migr_rows if r["profit"] > 0),
                  "save": sum(r["save"] for r in migr_rows),
                  "reeval": sum(r["reeval"] for r in migr_rows),
                  "widen": sum(r["widen"] for r in migr_rows),
                  "new_detect": sum(r["new_detect"] for r in migr_rows),
                  "profit": sum(r["profit"] for r in migr_rows)}

    wide_total, wide_files = helper_census(args.gen_model)
    wide_values = [v for v in view.boundary if view.width.get(v, 0) > 64]
    wide_dumped = [v for v in wide_values if v in vchg1]
    wide_ch = [vchg1[v][1] for v in wide_dumped]

    eval_order = {}
    simtop = args.gen_model / "grhsim_SimTop.cpp"
    if simtop.exists():
        eval_order = eval_task_order(simtop.read_text(errors="replace"))
    scan = unit_scan_order(args.gen_model)

    args.output.mkdir(parents=True, exist_ok=True)
    summary = {
        "gates": [{"name": n, "ok": ok, "detail": d} for n, ok, d in gates],
        "runs": {"run1": ep1, "run2": ep2},
        "closure": clo,
        "boundary": {"total": len(view.boundary), "monitored": len(monitored),
                     "silent": len(silent), "dumped": len(dumped), "never_eval": len(never_eval),
                     "undumped_decomposition": decomp},
        "m_vchg": {"profile": profile, "strata": strata_rows[:40]},
        "m_econ": {"coldness": cold, "migration_total": migr_total,
                   "migration_by_class": [
                       {"kind": k[0], "cold": k[1], **v}
                       for k, v in sorted(migr_agg.items(), key=lambda kv: kv[1]["profit"])[:60]]},
        "m_wide": {"static_helpers": dict(wide_total),
                   "wide_boundary_values": len(wide_values),
                   "wide_monitored_evaluated": len(wide_dumped),
                   "wide_chg_profile": dist_stats(wide_ch)},
        "scan_order": {"tasks_in_eval": len(eval_order), "units_located": len(scan)},
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=1))

    ok_all = all(ok for _, ok, _ in gates)
    lines = ["# NO00012 vchg profile summary", ""]
    lines.append("## gates")
    for name, ok, detail in gates:
        lines.append(f"- {'PASS' if ok else 'FAIL'} {name} {detail}")
    lines += ["", "## runs", f"- run1 host_ms={ep1['host_ms']} endpoint={ep1}",
              f"- run2 host_ms={ep2['host_ms']} endpoint={ep2}", ""]
    lines.append(f"## boundary decomposition: total={len(view.boundary)} monitored={len(monitored)} "
                 f"silent={len(silent)} dumped(wr>0)={len(dumped)} never_eval={len(never_eval)}")
    lines.append(f"## undumped decomposition: {decomp}")
    lines.append(f"## M-vchg profile (dumped values): {profile}")
    lines.append("## M-econ coldness buckets (values / wr / ch / consumer body fires)")
    for bucket, agg in cold.items():
        lines.append(f"- {bucket}: {agg}")
    lines.append(f"## M-econ migration total (instr-model units over the run): {migr_total}")
    lines.append("## M-econ migration worst classes (by profit):")
    for k, v in sorted(migr_agg.items(), key=lambda kv: kv[1]["profit"])[:12]:
        lines.append(f"- {k[0]} {k[1]}: {v}")
    lines.append("## M-wide static helpers: " + json.dumps(dict(wide_total)))
    lines.append(f"## M-wide boundary: values={len(wide_values)} evaluated={len(wide_dumped)} "
                 f"chg={dist_stats(wide_ch)}")
    (args.output / "summary.md").write_text("\n".join(lines) + "\n")

    print("\n".join(lines[:30]))
    print(f"[analyze_grhsim_vchg_profile] gates {'ALL PASS' if ok_all else 'FAILED'}; wrote {args.output}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
