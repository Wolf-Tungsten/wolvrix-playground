#!/usr/bin/env python3
"""NO00017 kind-cost census: post-compile per-op-kind dynamic instruction attribution.

Links three deterministic archives of one production build (default: the
NO00015 archive, the current-best configuration):

  1. production checkpoint -> per-unit op composition, ChangedGroup mirror,
     fanout/port-arm structure, per-unit frame bytes (dataLayout), task->unit
     mapping (schedule), mirroring cpu_emit.cpp construction rules;
  2. production PGO binary -> per-function static instruction counts (objdump
     disassembly, same symbol pattern as NO00009's grhsim_disasm_census.py);
  3. dyn run log           -> per-unit body/chg fires ([grhsim-dyn] sn rows).

A weighted non-negative least-squares fit over the task functions

    instr_f = sum_k c_k * n_{f,k} + c_unit*n_units + c_grp*n_grp
              + c_det*n_det + c_arm*n_arm + c_frame*frame_bytes + c0

yields post-compile marginal static costs per op kind (M-kindcost); the closed
join with per-unit deterministic fires yields dynamic instr/cycle per kind
(M-kinddyn), per result-width bucket (M-widthdyn, second fit on width
features + bookkeeping) and for bookkeeping classes (M-bkacct).

Gates (pre-registered in pdocs/NO00017-*.md):
  G1 data joins: disasm task symbols == schedule tasks; helper symbols all
     attributed; compute-excluding-constant body*ops == NO00016 dynOps
     reference within tolerance; all-ops body*ops == grhsim_dynamic_stats
     cross-validation total exactly; sum chg == totals.grp_fire exactly.
  G3 fit quality: weighted R^2 >= 0.90; bootstrap 95% CI halfwidth <= 30% of
     the point estimate for kinds covering >= 1% of dynamic instructions.
     Degradation path (pre-registered): on R^2 miss, refit on 13 semantic
     buckets (logic1/logicN/arith/muldiv/cmp/mux/slice/concat/shift/reduce/
     state/mem/other) and deliver that granularity instead.
  G4 closure: predicted dynamic compute instr/cycle within 10% of the
     perfstat compute baseline (formula: body x (kinds + grp + det)
     + chg x arms; frame/n_units are static-only absorbers).
  (G2 determinism is exercised by running the tool twice and byte-comparing.)

Inputs
  --model      production mapped checkpoint JSON
  --run        dyn run log ([grhsim-dyn] sn/totals rows)
  --emu        production PGO emu binary (objdump target)
  --output     directory for summary.md / summary.json
  --cycles     guest cycles (default 100001)
  --dynops-ref dynOps reference total per run (default 92212.3e6, NO00016 census
               caliber on the same archives)
  --compute-ref perfstat compute baseline instr/cycle (default 3173679.4,
               NO00016 baseline measurement of the NO00015 production build)
"""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grhsim_demonitor_census import CONSTANT_KIND, view_from_model  # noqa: E402
from grhsim_vchg_profile import SN_LINE  # noqa: E402

EXEC_COMPUTE = 0    # CpuExecution::ActivityDrivenCompute
DPI_KIND = "core.dpi.call"

DISASM_LABEL = re.compile(
    r"^[0-9a-f]+ <_ZN13GrhSIM_SimTop\d+(cpu_(?:task_\d+|helper_\d+_\d+))E[^>]*>:")
DISASM_INSN = re.compile(r"^\s+[0-9a-f]+:\s+(\S+)\s*(.*)$")
HELPER_NAME = re.compile(r"^cpu_helper_(\d+)_(\d+)$")


def two_state_logic(type_row):
    """IR type row [id, ref, kind, width, signed, domain, elem, count]."""
    return type_row[2] == "logic" and type_row[5] == "2-state" and type_row[3] > 0

# ---------------------------------------------------------------------------
# Checkpoint mirrors (pure functions over plain containers, unit-testable)
# ---------------------------------------------------------------------------


def compute_task_units(partitions, schedule):
    """Schedule walk: return (compute_tasks, all_task_ids, unit_to_task).

    compute_tasks = [(task_id, [unit partition ids])] for ActivityDrivenCompute
    tasks; a compute task's partition children are words, a word's children are
    the unit supernodes (mirrors cpu_emit.cpp taskBody). Commit tasks hold ops
    one level up (task -> unit -> ops).
    """
    compute_tasks = []
    all_task_ids = []
    unit_to_task = {}
    for numa in schedule[0]:
        for core in numa[1]:
            for row in core[1]:
                task_id, part, execution = row[0], row[1], row[3]
                all_task_ids.append(task_id)
                if execution != EXEC_COMPUTE:
                    continue
                units = []
                for word in partitions[part][4]:
                    units.extend(partitions[word][4])
                for unit in units:
                    unit_to_task[unit] = task_id
                compute_tasks.append((task_id, units))
    return compute_tasks, all_task_ids, unit_to_task


def direct_commit_states(operations, op_name, op_refs, types, state_type):
    """Mirror cpu_emit.cpp planDirectCommits: a state is direct-commit when a
    single write port owns it and every state reference comes from state.read
    ops or that port (no memWrite/event/DPI reference), logic two-state 1..64.
    """
    references = Counter()
    allowed = Counter()
    writers = Counter()
    for op in operations:
        oid = op[0]
        name = op_name[oid]
        refs = [r for r in op_refs[oid] if r[0] == "state"]
        for ref in refs:
            references[ref[1]] += 1
        if name == "core.state.read":
            for ref in refs:
                allowed[ref[1]] += 1
        elif name in ("core.state.regWrite", "core.state.latchWrite") and refs:
            allowed[refs[0][1]] += 1
            writers[refs[0][1]] += 1
    direct = set()
    for sid, tid in state_type.items():
        t = types[tid]
        if (writers[sid] == 1 and references[sid] == allowed[sid]
                and two_state_logic(t) and t[3] <= 64):
            direct.add(sid)
    return direct


def mirror_port_arms(operations, view, types, state_type, partitions, schedule):
    """Mirror cpu_emit.cpp planPortArms. Returns {value: [(word, mask), ...]}
    with per-offset masks merged, exactly like the emitter's flatten pass.
    Commit tasks are walked in schedule order; their partition children hold
    ops directly (no node layer).
    """
    op_name, op_operands, op_refs = view["op_name"], view["op_operands"], view["op_refs"]
    producer_of = view["producer_of"]
    direct = direct_commit_states(operations, op_name, op_refs, types, state_type)
    value_type = {v[0]: v[1] for v in view["values_rows"]}

    def armable(op):
        name = op_name[op[0]]
        if name not in ("core.state.regWrite", "core.state.latchWrite"):
            return False
        refs = op_refs[op[0]]
        operands = op_operands[op[0]]
        if not refs or len(operands) < 3:
            return False
        if refs[0][1] not in direct:
            return False
        for i in range(3):
            operand = operands[i]
            if operand in view["aliased_read_values"]:
                return False
            t = types[value_type[operand]]
            if not two_state_logic(t) or t[3] > 64:
                return False
            if operand not in view["is_boundary"]:
                return False
            producer = producer_of.get(operand)
            if not producer:
                return False
            pname = op_name[producer]
            if (not pname.startswith("core.compute.")
                    and pname not in ("core.state.read", "core.state.memRead", "core.input.read")):
                return False
        return True

    raw = defaultdict(list)
    word_count = 0
    for numa in schedule[0]:
        for core in numa[1]:
            for row in core[1]:
                _task_id, part, execution = row[0], row[1], row[3]
                if execution == EXEC_COMPUTE:
                    continue
                ordinal = 0
                for unit in partitions[part][4]:
                    for op_id in partitions[unit][5]:
                        op = view["op_by_id"][op_id]
                        if not armable(op):
                            continue
                        word = word_count + ordinal // 8
                        mask = 1 << (ordinal % 8)
                        operands = op_operands[op[0]]
                        for i in range(3):
                            raw[operands[i]].append((word, mask))
                        ordinal += 1
                word_count += (ordinal + 7) // 8
    merged = {}
    for value, targets in raw.items():
        per_offset = defaultdict(int)
        for word, mask in targets:
            per_offset[word] |= mask
        merged[value] = sorted(per_offset.items())
    return merged


def active_offsets(partitions, layout_runtime):
    """activeOffset/activeMask per unit partition (mirror of the emit ctor):
    ActiveWord runtime slots are owned by the parent word; a unit's own mask is
    1 << (activeId % 8) from its partition attrs.
    """
    word_offset = {}
    for slot in layout_runtime:
        if slot[0] == 0:  # CpuRuntimeKind::ActiveWord
            word_offset[slot[1]] = slot[4]
    active_off = {}
    active_mask = {}
    for pid, part in partitions.items():
        attrs = part[7] if len(part) > 7 else None
        if not attrs or not attrs[0]:
            continue
        active_id = attrs[0][0]
        parent = part[1]
        if parent not in word_offset:
            continue
        active_off[pid] = word_offset[parent]
        active_mask[pid] = 1 << (active_id % 8)
    return active_off, active_mask


def unit_group_features(view, ports_map, active_off, active_mask):
    """Mirror the ChangedGroup construction in cpu_emit.cpp computeGroup.

    Returns {unit: {"groups", "dets", "arms"}}: changed groups (one bool
    zero-init + one guard each), detection sites (group members: compare+store
    per body fire) and epilogue arm lines (activate word lines + domain-arm
    lines + port lines, executed per group fire).
    """
    op_name, op_results = view["op_name"], view["op_results"]
    fanout_activate, fanout_arm = view["fanout_activate"], view["fanout_arm"]
    out = {}
    for unit, ops in view["unit_ops"].items():
        keys = {}
        members = 0
        for op_id in ops:
            results = op_results[op_id]
            name = op_name[op_id]
            if len(results) != 1 or name == DPI_KIND or name == CONSTANT_KIND:
                continue
            result = results[0]
            if result in view["aliased_read_values"]:
                continue
            if view["width"].get(result, 0) == 0:
                continue
            act = fanout_activate.get(result)
            arm = fanout_arm.get(result)
            ports = ports_map.get(result)
            if act is None and arm is None and not ports:
                continue
            key = (tuple(sorted(act)) if act else (),
                   tuple(sorted(arm)) if arm else (),
                   tuple(ports) if ports else ())
            keys.setdefault(key, (act, arm, ports))
            members += 1
        n_arm_lines = 0
        own_off, own_mask = active_off.get(unit), active_mask.get(unit, 0)
        for act, arm, ports in keys.values():
            offsets = set()
            local = False
            if act:
                for target in act:
                    off = active_off.get(target)
                    mask = active_mask.get(target, 0)
                    if own_off is not None and off == own_off and mask > own_mask:
                        local = True
                    elif off is not None:
                        offsets.add(off)
            n_arm_lines += len(offsets) + (1 if local else 0)
            n_arm_lines += len(arm) if arm else 0
            n_arm_lines += len(ports) if ports else 0
        out[unit] = {"groups": len(keys), "dets": members, "arms": n_arm_lines}
    return out


def frame_sizes(local_frames, unit_set):
    """Per-unit local frame bytes from dataLayout localFrames ([owner, size,
    alignment]), which is what emit frameSizes_ serializes."""
    return {row[0]: row[1] for row in local_frames if row[0] in unit_set}


def width_bucket_of(view, types, value_type, op_id):
    """Result-width bucket of an op: 'w1' | 'w2_64' | 'w65p' | 'none'."""
    width = result_width_of(view, types, value_type, op_id)
    if width <= 0:
        return "none"
    if width <= 1:
        return "w1"
    if width <= 64:
        return "w2_64"
    return "w65p"


def result_width_of(view, types, value_type, op_id):
    """Logic result width of an op (0 when the op has no logic result)."""
    results = view["op_results"][op_id]
    if not results:
        return 0
    t = types[value_type[results[0]]]
    return t[3] if t[2] == "logic" else 0


LOGIC_KINDS = {"core.compute.and", "core.compute.or", "core.compute.xor",
               "core.compute.not", "core.compute.logicNot",
               "core.compute.logicAnd", "core.compute.logicOr"}
SEMANTIC_BUCKET_NAMES = ["logic1", "logicN", "arith", "muldiv", "cmp", "mux",
                         "slice", "concat", "shift", "reduce", "state", "mem",
                         "other"]
_SEMANTIC_BUCKETS = {
    "arith": ("core.compute.add", "core.compute.sub"),
    "muldiv": ("core.compute.mul", "core.compute.div", "core.compute.mod"),
    "cmp": ("core.compute.eq", "core.compute.ne", "core.compute.lt",
            "core.compute.le", "core.compute.gt", "core.compute.ge"),
    "mux": ("core.compute.mux", "core.compute.prioritySelect"),
    "slice": ("core.compute.sliceStatic", "core.compute.sliceDynamic",
              "core.compute.sliceArray", "core.compute.bitSelect"),
    "concat": ("core.compute.concat", "core.compute.replicate"),
    "shift": ("core.compute.shl", "core.compute.lshr", "core.compute.ashr"),
    "reduce": ("core.compute.reduceAnd", "core.compute.reduceOr",
               "core.compute.reduceXor"),
    "state": ("core.state.read", "core.input.read", "core.output.write"),
    "mem": ("core.state.memRead", "core.state.memWrite"),
}


def semantic_bucket_of(kind, width):
    """Pre-registered degradation-path semantic bucket for an op kind."""
    if kind in LOGIC_KINDS:
        return "logic1" if width <= 1 else "logicN"
    for bucket, names in _SEMANTIC_BUCKETS.items():
        if kind in names:
            return bucket
    return "other"


# ---------------------------------------------------------------------------
# Disassembly census (same symbol pattern as NO00009 grhsim_disasm_census.py)
# ---------------------------------------------------------------------------


def disasm_instruction_counts(emu_path):
    """objdump the emu binary; return {func_name: instruction_count}."""
    counts = {}
    current = None
    proc = subprocess.Popen(
        ["objdump", "-d", "--no-show-raw-insn", str(emu_path)],
        stdout=subprocess.PIPE, text=True, bufsize=1 << 20)
    for line in proc.stdout:
        match = DISASM_LABEL.match(line)
        if match:
            current = match.group(1)
            counts[current] = 0
            continue
        if line.startswith("0") and "<" in line:
            current = None
            continue
        if current is not None and DISASM_INSN.match(line):
            counts[current] += 1
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"objdump failed on {emu_path}")
    return counts


# ---------------------------------------------------------------------------
# Fit (weighted non-negative least squares, Lawson-Hanson active set)
# ---------------------------------------------------------------------------


def nnls(a_mat, b_vec, itmax=None):
    """Lawson-Hanson NNLS; minimum-norm lstsq on the passive set."""
    a_mat = np.asarray(a_mat, dtype=np.float64)
    b_vec = np.asarray(b_vec, dtype=np.float64)
    m, n = a_mat.shape
    itmax = itmax or 5 * n
    x = np.zeros(n)
    passive = np.zeros(n, dtype=bool)
    grad = a_mat.T @ b_vec
    tol = 1e-12 * max(1.0, float(np.abs(grad).max(initial=0.0)))
    for _ in range(itmax):
        if passive.all() or grad[~passive].max(initial=-np.inf) <= tol:
            break
        j = int(np.argmax(np.where(passive, -np.inf, grad)))
        passive[j] = True
        while True:
            sub = np.linalg.lstsq(a_mat[:, passive], b_vec, rcond=None)[0]
            if (sub > 0).all():
                x[passive] = sub
                break
            current = x[passive]
            alpha = min(x_i / (x_i - s_i)
                        for x_i, s_i in zip(current, sub) if s_i <= 0)
            x[passive] = current + alpha * (sub - current)
            passive[x <= 0] = False
            x[x <= 0] = 0.0
            if not passive.any():
                break
        grad = a_mat.T @ (b_vec - a_mat @ x)
    return x


def weighted_r2(y, pred, weights):
    """Weighted R^2 on whitened residuals."""
    y = np.asarray(y, dtype=np.float64)
    pred = np.asarray(pred, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    mean = float(np.average(y, weights=weights ** 2))
    ss_res = float(np.sum((weights * (y - pred)) ** 2))
    ss_tot = float(np.sum((weights * (y - mean)) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0


def bootstrap_ci(features, target, weights, iters, seed):
    """Percentile bootstrap over fit samples; returns (2.5%, 97.5%) per column."""
    rng = np.random.default_rng(seed)
    n = features.shape[0]
    estimates = []
    for _ in range(iters):
        pick = rng.integers(0, n, n)
        estimates.append(nnls(features[pick] * weights[pick, None],
                              target[pick] * weights[pick]))
    estimates = np.asarray(estimates)
    return np.percentile(estimates, 2.5, axis=0), np.percentile(estimates, 97.5, axis=0)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def load_dyn_fires(run_path):
    """Parse [grhsim-dyn] sn rows ({unit: body}, {unit: chg}) and totals."""
    body = {}
    chg = {}
    totals = {}
    with open(run_path) as handle:
        for line in handle:
            match = SN_LINE.match(line)
            if match:
                unit = int(match.group(1))
                body[unit] = int(match.group(3))
                chg[unit] = int(match.group(5))
                continue
            if line.startswith("[grhsim-dyn] totals "):
                for field in line.split()[2:]:
                    key, _, value = field.partition("=")
                    totals[key] = int(value)
    return body, chg, totals


BOOKKEEPING_NAMES = ["n_units", "n_grp", "n_det", "n_arm", "frame_bytes", "intercept"]
BUCKET_NAMES = ["w1", "w2_64", "w65p", "none"]


def build_features(model, view):
    """Assemble per-task/per-unit feature tables from the checkpoint."""
    payload = model["mappings"][0][-1]
    partitions = view["partitions"]
    schedule = payload[4]
    layout = payload[3]
    types = {t[0]: t for t in model["types"]}
    state_type = {s[0]: s[2] for s in model["states"]}
    view["values_rows"] = model["values"]
    view["op_by_id"] = {op[0]: op for op in model["operations"]}
    view["op_refs"] = {op[0]: op[6] for op in model["operations"]}

    compute_tasks, all_task_ids, unit_to_task = compute_task_units(partitions, schedule)
    ports_map = mirror_port_arms(
        model["operations"], view, types, state_type, partitions, schedule)
    active_off, active_mask = active_offsets(partitions, layout[5])
    group_feats = unit_group_features(view, ports_map, active_off, active_mask)

    unit_set = {unit for _task, units in compute_tasks for unit in units}
    frames = frame_sizes(layout[4], unit_set)

    value_type = {v[0]: v[1] for v in model["values"]}
    kinds = sorted({view["op_name"][op]
                    for _task, units in compute_tasks
                    for unit in units for op in view["unit_ops"][unit]})

    per_unit = {}
    for _task, units in compute_tasks:
        for unit in units:
            ops = view["unit_ops"][unit]
            kind_counts = Counter(view["op_name"][op] for op in ops)
            bucket_counts = Counter(
                width_bucket_of(view, types, value_type, op) for op in ops)
            sbucket_counts = Counter(
                semantic_bucket_of(view["op_name"][op],
                                   result_width_of(view, types, value_type, op))
                for op in ops)
            group = group_feats.get(unit, {"groups": 0, "dets": 0, "arms": 0})
            per_unit[unit] = {
                "kinds": kind_counts, "buckets": bucket_counts,
                "sbuckets": sbucket_counts,
                "groups": group["groups"], "dets": group["dets"],
                "arms": group["arms"], "frame": frames.get(unit, 0),
                "ops": len(ops),
            }
    per_task = []
    for task_id, units in compute_tasks:
        kinds_sum = Counter()
        buckets_sum = Counter()
        sbuckets_sum = Counter()
        totals = Counter()
        for unit in units:
            feats = per_unit[unit]
            kinds_sum.update(feats["kinds"])
            buckets_sum.update(feats["buckets"])
            sbuckets_sum.update(feats["sbuckets"])
            for key in ("groups", "dets", "arms", "frame", "ops"):
                totals[key] += feats[key]
        per_task.append({
            "task": task_id, "units": len(units), "kinds": kinds_sum,
            "buckets": buckets_sum, "sbuckets": sbuckets_sum, **dict(totals),
        })
    return {
        "compute_tasks": compute_tasks, "all_task_ids": all_task_ids,
        "unit_to_task": unit_to_task, "per_unit": per_unit,
        "per_task": per_task, "kinds": kinds,
    }


def feature_matrix(per_task, kinds):
    """Feature rows: [per-kind counts..., n_units, n_grp, n_det, n_arm,
    frame_bytes, intercept]."""
    rows = []
    for task in per_task:
        rows.append([task["kinds"].get(kind, 0) for kind in kinds]
                    + [task["units"], task["groups"], task["dets"],
                       task["arms"], task["frame"], 1])
    return rows


def bucket_matrix(per_task):
    rows = []
    for task in per_task:
        rows.append([task["buckets"].get(name, 0) for name in BUCKET_NAMES]
                    + [task["units"], task["groups"], task["dets"],
                       task["arms"], task["frame"], 1])
    return rows


def sbucket_matrix(per_task):
    """Degradation-path semantic-bucket features (13 buckets + bookkeeping)."""
    rows = []
    for task in per_task:
        rows.append([task["sbuckets"].get(name, 0) for name in SEMANTIC_BUCKET_NAMES]
                    + [task["units"], task["groups"], task["dets"],
                       task["arms"], task["frame"], 1])
    return rows


def fit(feature_rows, target):
    """Weighted NNLS (weights 1/max(y,50)); returns (coef, weighted R^2)."""
    x_mat = np.asarray(feature_rows, dtype=np.float64)
    y_vec = np.asarray(target, dtype=np.float64)
    weights = np.array([1.0 / max(y, 50.0) for y in y_vec])
    coef = nnls(x_mat * weights[:, None], y_vec * weights)
    return coef, weighted_r2(y_vec, x_mat @ coef, weights), weights


def dynamic_by_key(per_unit, fires, costs, key_of):
    """Sum fires[unit] * cost over the per-unit feature chosen by key_of."""
    out = Counter()
    for unit, feats in per_unit.items():
        body = fires.get(unit, 0)
        if not body:
            continue
        for key, count in key_of(feats).items():
            out[key] += body * count * costs.get(key, 0.0)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--emu", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cycles", type=int, default=100001)
    parser.add_argument("--dynops-ref", type=float, default=92212.3e6,
                        help="NO00016 documented caliber: compute ops excluding "
                             "core.compute.constant, body x unit ops")
    parser.add_argument("--dynops-full-ref", type=float, default=99495719495,
                        help="all-ops caliber, cross-validated against "
                             "grhsim_dynamic_stats.py total_dynamic_compute_ops")
    parser.add_argument("--compute-ref", type=float, default=3173679.4)
    parser.add_argument("--bootstrap", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260926)
    args = parser.parse_args(argv)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    model = json.loads(Path(args.model).read_bytes())
    view = view_from_model(model)
    feats = build_features(model, view)
    body_fires, chg_fires, totals = load_dyn_fires(args.run)
    disasm = disasm_instruction_counts(args.emu)

    gates = {}
    # --- G1: data joins -----------------------------------------------------
    disasm_tasks = {name for name in disasm if name.startswith("cpu_task_")}
    disasm_helpers = {name for name in disasm if name.startswith("cpu_helper_")}
    unit_to_task = feats["unit_to_task"]
    helper_to_task = {}
    helper_orphans = []
    for name in disasm_helpers:
        unit = int(HELPER_NAME.match(name).group(1))
        if unit in unit_to_task:
            helper_to_task[name] = unit_to_task[unit]
        else:
            helper_orphans.append(name)
    gates["g1_task_symbols"] = (len(disasm_tasks) == len(feats["all_task_ids"]),
                                [len(disasm_tasks), len(feats["all_task_ids"])])
    gates["g1_helpers"] = (not helper_orphans, [len(disasm_helpers), len(helper_orphans)])
    dynops = sum(body_fires.get(unit, 0) * feats["per_unit"][unit]["ops"]
                 for unit in feats["per_unit"])
    dynops_compute = sum(
        body_fires.get(unit, 0) * sum(
            count for kind, count in feats["per_unit"][unit]["kinds"].items()
            if kind.startswith("core.compute.") and kind != CONSTANT_KIND)
        for unit in feats["per_unit"])
    gates["g1_dynops_compute"] = (
        abs(dynops_compute - args.dynops_ref) <= 0.0001 * args.dynops_ref,
        [dynops_compute, args.dynops_ref])
    gates["g1_dynops_full"] = (dynops == args.dynops_full_ref,
                               [dynops, args.dynops_full_ref])
    chg_total = sum(chg_fires.get(unit, 0) for unit in feats["per_unit"])
    gates["g1_grp_fire"] = (chg_total == totals.get("grp_fire"),
                            [chg_total, totals.get("grp_fire")])

    # --- static fit (kind model) ---------------------------------------------
    per_task = feats["per_task"]
    kinds = feats["kinds"]
    helper_sums = Counter()
    for name, task_id in helper_to_task.items():
        helper_sums[task_id] += disasm[name]
    target = [disasm.get(f"cpu_task_{task['task']}", 0) + helper_sums[task["task"]]
              for task in per_task]
    features = feature_matrix(per_task, kinds)
    names = list(kinds) + BOOKKEEPING_NAMES
    coef, r2, weights = fit(features, target)
    gates["g3_r2"] = (r2 >= 0.90, [r2])
    lo, hi = bootstrap_ci(np.asarray(features, dtype=np.float64),
                          np.asarray(target, dtype=np.float64), weights,
                          args.bootstrap, args.seed)
    coef_of = dict(zip(names, coef))

    # --- width model (second fit, bucket features) ----------------------------
    bucket_features = bucket_matrix(per_task)
    bucket_names = BUCKET_NAMES + BOOKKEEPING_NAMES
    bcoef, br2, _ = fit(bucket_features, target)
    gates["g3_width_r2"] = (br2 >= 0.90, [br2])
    bcoef_of = dict(zip(bucket_names, bcoef))

    # --- degradation path: semantic-bucket model ------------------------------
    sfeatures = sbucket_matrix(per_task)
    snames = SEMANTIC_BUCKET_NAMES + BOOKKEEPING_NAMES
    scoef, sr2, sweights = fit(sfeatures, target)
    slo, shi = bootstrap_ci(np.asarray(sfeatures, dtype=np.float64),
                            np.asarray(target, dtype=np.float64), sweights,
                            args.bootstrap, args.seed)
    scoef_of = dict(zip(snames, scoef))
    gates["g3_sbucket_r2"] = (sr2 >= 0.90, [sr2])

    # --- dynamic attribution ---------------------------------------------------
    # Pre-registered closure: body x (sum c_k*n_k + c_grp*grp + c_det*det)
    # + chg x c_arm*arms. frame_bytes / n_units stay static-only absorbers;
    # their dynamic share belongs to the registered unmodeled residual.
    per_unit = feats["per_unit"]

    def closure_total(coef_of_, key_of):
        total = 0.0
        for unit, u in per_unit.items():
            body = body_fires.get(unit, 0)
            chg = chg_fires.get(unit, 0)
            base = (sum(coef_of_[key] * count for key, count in key_of(u).items())
                    + coef_of_["n_grp"] * u["groups"]
                    + coef_of_["n_det"] * u["dets"])
            total += body * base + chg * coef_of_["n_arm"] * u["arms"]
        return total

    kind_dyn_total = closure_total(coef_of, lambda u: u["kinds"])
    sbucket_dyn_total = closure_total(scoef_of, lambda u: u["sbuckets"])
    delivered = "kind" if r2 >= 0.90 else ("sbucket" if sr2 >= 0.90 else None)
    dyn_total = sbucket_dyn_total if delivered == "sbucket" else kind_dyn_total
    dyn_per_cycle = dyn_total / args.cycles
    residual = dyn_per_cycle - args.compute_ref
    gates["g4_closure"] = (delivered is not None
                           and abs(residual) <= 0.10 * args.compute_ref,
                           [dyn_per_cycle, args.compute_ref, residual,
                            delivered or "none"])

    kind_exec = dynamic_by_key(per_unit, body_fires, {k: 1.0 for k in kinds},
                               lambda u: u["kinds"])
    kind_dyn = dynamic_by_key(per_unit, body_fires, coef_of, lambda u: u["kinds"])
    sbucket_exec = dynamic_by_key(per_unit, body_fires,
                                  {b: 1.0 for b in SEMANTIC_BUCKET_NAMES},
                                  lambda u: u["sbuckets"])
    sbucket_dyn = dynamic_by_key(per_unit, body_fires, scoef_of,
                                 lambda u: u["sbuckets"])
    bucket_exec = dynamic_by_key(per_unit, body_fires, {b: 1.0 for b in BUCKET_NAMES},
                                 lambda u: u["buckets"])
    bucket_dyn = dynamic_by_key(per_unit, body_fires, bcoef_of, lambda u: u["buckets"])

    def ci_gate(clo, chi, ccoef, cnames, shares):
        rows, ok = [], True
        for i, name in enumerate(cnames):
            if shares.get(name, 0) < 0.01:
                continue
            half = (chi[i] - clo[i]) / 2
            point = max(float(ccoef[i]), 1e-12)
            ci_pass = bool(half / point <= 0.30)
            rows.append([name, float(ccoef[i]), float(clo[i]), float(chi[i]), ci_pass])
            ok = ok and ci_pass
        return ok, rows

    kind_share = {kind: (kind_dyn[kind] / kind_dyn_total if kind_dyn_total else 0.0)
                  for kind in kinds}
    ci_kind_ok, ci_kind_rows = ci_gate(lo, hi, coef, names, kind_share)
    sbucket_share = {b: (sbucket_dyn[b] / sbucket_dyn_total if sbucket_dyn_total else 0.0)
                     for b in SEMANTIC_BUCKET_NAMES}
    ci_sbucket_ok, ci_sbucket_rows = ci_gate(slo, shi, scoef, snames, sbucket_share)
    if delivered == "kind":
        gates["g3_ci"] = (ci_kind_ok, ci_kind_rows)
    elif delivered == "sbucket":
        gates["g3_ci"] = (ci_sbucket_ok, ci_sbucket_rows)
    else:
        gates["g3_ci"] = (False, {"kind": ci_kind_rows, "sbucket": ci_sbucket_rows})

    dcoef_of = scoef_of if delivered == "sbucket" else coef_of
    bookkeeping_dyn = {
        "detections": (sum(body_fires.get(u, 0) * per_unit[u]["dets"] for u in per_unit)
                       * dcoef_of["n_det"] / args.cycles),
        "groups": (sum(body_fires.get(u, 0) * per_unit[u]["groups"] for u in per_unit)
                   * dcoef_of["n_grp"] / args.cycles),
        "arms": (sum(chg_fires.get(u, 0) * per_unit[u]["arms"] for u in per_unit)
                 * dcoef_of["n_arm"] / args.cycles),
        "units": (sum(body_fires.get(u, 0) for u in per_unit)
                  * dcoef_of["n_units"] / args.cycles),
        "frames": (sum(body_fires.get(u, 0) * per_unit[u]["frame"] for u in per_unit)
                   * dcoef_of["frame_bytes"] / args.cycles),
    }

    summary = {
        "gates": {key: bool(value[0]) for key, value in gates.items()},
        "gate_details": {key: value[1] for key, value in gates.items()},
        "delivered_model": delivered or "none",
        "fit": {"weighted_r2": r2, "width_r2": br2, "sbucket_r2": sr2,
                "coefficients": {name: float(coef_of[name]) for name in names},
                "ci95": {name: [float(lo[i]), float(hi[i])] for i, name in enumerate(names)},
                "width_coefficients": {name: float(bcoef_of[name]) for name in bucket_names},
                "sbucket_coefficients": {name: float(scoef_of[name]) for name in snames},
                "sbucket_ci95": {name: [float(slo[i]), float(shi[i])]
                                 for i, name in enumerate(snames)}},
        "kind_dynamic": {
            kind: {"execs_per_cycle": kind_exec[kind] / args.cycles,
                   "instr_per_cycle": kind_dyn[kind] / args.cycles,
                   "share_of_attributed": (kind_dyn[kind] / kind_dyn_total) if kind_dyn_total else 0.0,
                   "marginal_cost": float(coef_of[kind])}
            for kind in kinds},
        "sbucket_dynamic": {
            b: {"execs_per_cycle": sbucket_exec[b] / args.cycles,
                "instr_per_cycle": sbucket_dyn[b] / args.cycles,
                "share_of_attributed": (sbucket_dyn[b] / sbucket_dyn_total) if sbucket_dyn_total else 0.0,
                "marginal_cost": float(scoef_of[b])}
            for b in SEMANTIC_BUCKET_NAMES},
        "width_dynamic": {
            bucket: {"execs_per_cycle": bucket_exec[bucket] / args.cycles,
                     "instr_per_cycle": bucket_dyn[bucket] / args.cycles,
                     "share_of_attributed": (bucket_dyn[bucket] / dyn_total) if dyn_total else 0.0,
                     "marginal_cost": float(bcoef_of[bucket])}
            for bucket in BUCKET_NAMES},
        "bookkeeping": bookkeeping_dyn,
        "closure": {"predicted_per_cycle": dyn_per_cycle,
                    "compute_ref": args.compute_ref, "residual": residual,
                    "kind_model_per_cycle": kind_dyn_total / args.cycles,
                    "sbucket_model_per_cycle": sbucket_dyn_total / args.cycles},
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True))

    lines = ["# NO00017 kind-cost census summary", "",
             f"- weighted R^2: kind {r2:.4f} / semantic-bucket {sr2:.4f} "
             f"(degradation) / width-bucket {br2:.4f}; delivered model: "
             f"{delivered or 'none'}",
             f"- predicted dynamic compute instr/cycle: {dyn_per_cycle:.1f} "
             f"(ref {args.compute_ref}, residual {residual:+.1f}; "
             f"kind-model {kind_dyn_total / args.cycles:.1f}, "
             f"sbucket-model {sbucket_dyn_total / args.cycles:.1f})",
             f"- gates: {json.dumps({k: bool(v[0]) for k, v in gates.items()}, sort_keys=True)}",
             "", "## M-kinddyn (dynamic instr/cycle per op kind)", "",
             "| kind | execs/cycle | marginal instr | instr/cycle | share |",
             "|---|---|---|---|---|"]
    for kind in sorted(kinds, key=lambda k: -kind_dyn[k]):
        row = summary["kind_dynamic"][kind]
        lines.append(f"| {kind} | {row['execs_per_cycle']:.1f} | {row['marginal_cost']:.3f} "
                     f"| {row['instr_per_cycle']:.1f} | {row['share_of_attributed'] * 100:.2f}% |")
    lines += ["", "## M-kinddyn degradation (semantic buckets)", "",
              "| bucket | execs/cycle | marginal instr | instr/cycle | share |",
              "|---|---|---|---|---|"]
    for b in sorted(SEMANTIC_BUCKET_NAMES, key=lambda b: -sbucket_dyn[b]):
        row = summary["sbucket_dynamic"][b]
        lines.append(f"| {b} | {row['execs_per_cycle']:.1f} | {row['marginal_cost']:.3f} "
                     f"| {row['instr_per_cycle']:.1f} | {row['share_of_attributed'] * 100:.2f}% |")
    lines += ["", "## M-widthdyn (dynamic instr/cycle per result-width bucket)", "",
              "| bucket | execs/cycle | marginal instr | instr/cycle | share |",
              "|---|---|---|---|---|"]
    for bucket in BUCKET_NAMES:
        row = summary["width_dynamic"][bucket]
        lines.append(f"| {bucket} | {row['execs_per_cycle']:.1f} | {row['marginal_cost']:.3f} "
                     f"| {row['instr_per_cycle']:.1f} | {row['share_of_attributed'] * 100:.2f}% |")
    lines += ["", "## M-bkacct (bookkeeping marginal costs, post-compile)", "",
              "| class | coefficient | dynamic instr/cycle |", "|---|---|---|"]
    for key, value in bookkeeping_dyn.items():
        coef_name = {"detections": "n_det", "groups": "n_grp", "arms": "n_arm",
                     "units": "n_units", "frames": "frame_bytes"}[key]
        lines.append(f"| {key} | {dcoef_of[coef_name]:.3f} | {value:.1f} |")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n")

    print(json.dumps({key: bool(value[0]) for key, value in gates.items()}, indent=1))
    print(f"weighted_r2={r2:.4f} sbucket_r2={sr2:.4f} width_r2={br2:.4f} "
          f"delivered={delivered or 'none'} dyn/cycle={dyn_per_cycle:.1f} "
          f"ref={args.compute_ref} resid={residual:+.1f}")
    return 0 if all(value[0] for value in gates.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
