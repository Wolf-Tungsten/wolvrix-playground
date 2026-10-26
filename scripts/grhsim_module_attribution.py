#!/usr/bin/env python3

"""Module-level grhsim simulation-time attribution.

Joins the supernode-origin manifest (schema grhsim-supernode-origin-manifest/v1)
with the runtime per-supernode timing TSV and attributes simulator host cycles
to RTL module paths. Current workflow: pdocs/grhsim.md section 6.

Attribution model:
  A(m) += cycles_s * (sum_{i: m in M_i} w_i / |M_i|) / (sum_i w_i)
with op weights w_i = base[kind_i] * widthFactor(width_i), where base[kind] is
calibrated by non-negative least squares (NNLS) over all fired supernodes
against their measured single-fire cost t_s = cycles_s / fires_s.

NNLS backend selection, first available wins: scipy.optimize.nnls, then a
numpy projected-gradient solver, then a pure-stdlib Lee-Seung multiplicative-
update solver. Runs on plain python3 stdlib as the floor.

Usage:
  grhsim_module_attribution.py --manifest manifest.json --timing timing.tsv \
      --out-tsv module_attribution.tsv --report module_attribution.md
  grhsim_module_attribution.py --selftest
"""

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

SCHEMA_ID = "grhsim-supernode-origin-manifest/v1"
TIMING_COLUMNS = ("supernode_id", "phase", "fires")
CONSERVATION_TOLERANCE = 0.01
R2_CONFIDENCE_THRESHOLD = 0.7
TAU_CONFIDENCE_THRESHOLD = 0.8
SELFTEST_TAU_THRESHOLD = 0.8
SELFTEST_TOLERANCE = 1e-9
DEFAULT_TOP = 30
DEFAULT_ROLLUP_DEPTHS = (1, 2, 3)
CROSS_MODULE = "__cross_module__"
UNKNOWN_MODULE = "__unknown__"
# Suffix that --selftest appends to every fabricated module path, so a stray
# real-world name can never alias the synthetic ground truth.
SELFTEST_SUFFIX = "$__selftest_mod__"

# Default widthFactor buckets, evaluated in order; overrides --width-model.
#   0/unknown -> 1.0, 1 -> 1.0, 2-8 -> 1.0, 9-32 -> 1.0, 33-64 -> 1.0,
#   65-128 -> 2.0, 129-256 -> 4.0, >256 -> ceil(width/64)
# Expressed with a `<=` bound (inclusive, null = unbounded), a fixed factor,
# or per-64-bit-limb linear growth ("per_limb_divisor": 64 -> ceil(w/64)).
DEFAULT_WIDTH_MODEL = [
    {"le": 0, "factor": 1.0},
    {"le": 1, "factor": 1.0},
    {"le": 8, "factor": 1.0},
    {"le": 32, "factor": 1.0},
    {"le": 64, "factor": 1.0},
    {"le": 128, "factor": 2.0},
    {"le": 256, "factor": 4.0},
    {"le": None, "per_limb_divisor": 64},
]

# Ground-truth base[kind] used by --selftest; recovery by the NNLS fit is one
# of the asserted properties.
SELFTEST_BASE = {"kAnd": 3.0, "kAdd": 5.0, "kMux": 8.0}


class AttributionError(Exception):
    pass


def fail(message: str) -> None:
    raise AttributionError(message)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def load_width_model(path: Path | None):
    if path is None:
        return DEFAULT_WIDTH_MODEL
    try:
        model = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as ex:
        fail(f"{path}: invalid width model JSON: {ex}")
    if not isinstance(model, list) or not model:
        fail(f"{path}: width model must be a non-empty JSON array of rules")
    for index, rule in enumerate(model):
        if not isinstance(rule, dict):
            fail(f"{path}: width model rule #{index} must be an object")
        if "le" in rule and rule["le"] is not None:
            if not isinstance(rule["le"], int) or rule["le"] < 0:
                fail(f"{path}: width model rule #{index}: 'le' must be a non-negative integer or null")
        if "factor" in rule:
            if not isinstance(rule["factor"], (int, float)) or isinstance(rule["factor"], bool):
                fail(f"{path}: width model rule #{index}: 'factor' must be a number")
            if rule["factor"] <= 0:
                fail(f"{path}: width model rule #{index}: 'factor' must be positive")
        if "per_limb_divisor" in rule:
            if not isinstance(rule["per_limb_divisor"], int) or rule["per_limb_divisor"] <= 0:
                fail(f"{path}: width model rule #{index}: 'per_limb_divisor' must be a positive integer")
        if "factor" not in rule and "per_limb_divisor" not in rule:
            fail(f"{path}: width model rule #{index}: needs 'factor' or 'per_limb_divisor'")
    return model


def width_factor(width: int, model) -> float:
    for rule in model:
        bound = rule.get("le")
        if bound is not None and width > bound:
            continue
        if "per_limb_divisor" in rule:
            return float(max(1, math.ceil(width / rule["per_limb_divisor"])))
        return float(rule["factor"])
    fail("width model has no fallback rule (last rule must have 'le': null)")
    return 1.0


def parse_origins(value, context: str) -> list[int]:
    if not isinstance(value, list):
        fail(f"{context}: origins must be an array")
    origins = []
    for item in value:
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            fail(f"{context}: origin module index must be a non-negative integer: {item!r}")
        origins.append(item)
    return origins


def load_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as ex:
        fail(f"{path}: invalid manifest JSON: {ex}")
    if not isinstance(manifest, dict):
        fail(f"{path}: manifest root must be an object")
    if manifest.get("schema") != SCHEMA_ID:
        fail(f"{path}: unsupported schema: {manifest.get('schema')!r} (expected {SCHEMA_ID!r})")
    for name in ("module_table", "kind_table", "supernodes"):
        if not isinstance(manifest.get(name), list):
            fail(f"{path}: missing or invalid {name!r} array")
    module_count = len(manifest["module_table"])
    kind_count = len(manifest["kind_table"])
    for name, entries in (("module_table", manifest["module_table"]), ("kind_table", manifest["kind_table"])):
        for index, entry in enumerate(entries):
            if not isinstance(entry, str) or not entry:
                fail(f"{path}: {name}[{index}] must be a non-empty string")
    declared = manifest.get("supernode_count")
    if declared is not None:
        if not isinstance(declared, int) or declared != len(manifest["supernodes"]):
            fail(
                f"{path}: supernode_count={declared!r} does not match "
                f"len(supernodes)={len(manifest['supernodes'])}"
            )

    groups_by_ordinal: dict[int, list[tuple[int, int, tuple[int, ...], int]]] = {}
    for sn_index, sn in enumerate(manifest["supernodes"]):
        context = f"{path}: supernodes[{sn_index}]"
        if not isinstance(sn, dict):
            fail(f"{context}: must be an object")
        ordinal = sn.get("ordinal")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
            fail(f"{context}: 'ordinal' must be a non-negative integer: {ordinal!r}")
        if ordinal in groups_by_ordinal:
            fail(f"{context}: duplicate supernode ordinal {ordinal}")
        groups = []
        if "groups" in sn and sn["groups"] is not None:
            if not isinstance(sn["groups"], list):
                fail(f"{context}: 'groups' must be an array")
            for group_index, group in enumerate(sn["groups"]):
                group_context = f"{context}.groups[{group_index}]"
                if not isinstance(group, dict):
                    fail(f"{group_context}: must be an object")
                kind_idx = group.get("kind_idx")
                if not isinstance(kind_idx, int) or isinstance(kind_idx, bool) or not (0 <= kind_idx < kind_count):
                    fail(f"{group_context}: kind_idx {kind_idx!r} out of range [0, {kind_count})")
                width = group.get("width")
                if not isinstance(width, int) or isinstance(width, bool) or width < 0:
                    fail(f"{group_context}: width must be a non-negative integer: {width!r}")
                count = group.get("count")
                if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
                    fail(f"{group_context}: count must be a positive integer: {count!r}")
                origins = parse_origins(group.get("origins", []), group_context)
                for mod_idx in origins:
                    if mod_idx >= module_count:
                        fail(f"{group_context}: module index {mod_idx} out of range [0, {module_count})")
                groups.append((kind_idx, width, tuple(sorted(set(origins))), count))
        elif "ops" in sn and sn["ops"] is not None:
            if not isinstance(sn["ops"], list):
                fail(f"{context}: 'ops' must be an array")
            for op_index, op in enumerate(sn["ops"]):
                op_context = f"{context}.ops[{op_index}]"
                if not isinstance(op, (list, tuple)) or len(op) != 4:
                    fail(f"{op_context}: op entry must be a 4-element array [opId, kindIdx, width, [modIdx,...]]")
                _, kind_idx, width, mod_idxs = op
                if not isinstance(kind_idx, int) or isinstance(kind_idx, bool) or not (0 <= kind_idx < kind_count):
                    fail(f"{op_context}: kindIdx {kind_idx!r} out of range [0, {kind_count})")
                if not isinstance(width, int) or isinstance(width, bool) or width < 0:
                    fail(f"{op_context}: width must be a non-negative integer: {width!r}")
                origins = parse_origins(mod_idxs, op_context)
                for mod_idx in origins:
                    if mod_idx >= module_count:
                        fail(f"{op_context}: module index {mod_idx} out of range [0, {module_count})")
                groups.append((kind_idx, width, tuple(sorted(set(origins))), 1))
        else:
            fail(f"{context}: supernode has neither 'groups' nor 'ops'")
        declared_ops = sn.get("op_count")
        if declared_ops is not None:
            actual_ops = sum(group[3] for group in groups)
            if declared_ops != actual_ops:
                fail(f"{context}: op_count={declared_ops} does not match group/op total {actual_ops}")
        groups_by_ordinal[ordinal] = groups

    if not groups_by_ordinal:
        fail(f"{path}: manifest has no supernodes")
    return {
        "path": path,
        "model": manifest.get("model"),
        "module_table": manifest["module_table"],
        "kind_table": manifest["kind_table"],
        "groups_by_ordinal": groups_by_ordinal,
    }


class TimingRows(dict):
    def __init__(self, unit="cycles"):
        super().__init__()
        self.unit = unit


def read_timing(path: Path) -> TimingRows:
    try:
        source = path.open("r", encoding="utf-8", newline="")
    except OSError as ex:
        fail(f"{path}: cannot open timing TSV: {ex}")
    with source:
        reader = csv.DictReader(source, delimiter="\t")
        if reader.fieldnames is None:
            fail(f"{path}: missing TSV header")
        missing = sorted(set(TIMING_COLUMNS) - set(reader.fieldnames))
        if missing:
            fail(f"{path}: missing required columns: {', '.join(missing)}")
        units = set(reader.fieldnames) & {"cycles", "nanoseconds"}
        if len(units) != 1:
            fail(f"{path}: expected exactly one timing unit column: cycles or nanoseconds")
        rows = TimingRows(units.pop())
        for line, raw in enumerate(reader, start=2):
            context = f"{path}:{line}"
            try:
                supernode_id = int(raw["supernode_id"])
            except (TypeError, ValueError):
                fail(f"{context}: invalid integer in supernode_id: {raw['supernode_id']!r}")
            if supernode_id < 0:
                fail(f"{context}: negative supernode_id: {supernode_id}")
            phase = raw["phase"]
            if not phase:
                fail(f"{context}: empty phase")
            try:
                fires = int(raw["fires"])
                cycles = int(raw[rows.unit])
            except (TypeError, ValueError) as ex:
                fail(f"{context}: invalid integer: {ex}")
            if fires <= 0:
                fail(f"{context}: fires must be positive (never-fired supernodes are absent from the TSV): {fires}")
            if cycles < 0:
                fail(f"{context}: negative {rows.unit}: {cycles}")
            key = (supernode_id, phase)
            if key in rows:
                fail(f"{context}: duplicate key: supernode_id={supernode_id} phase={phase!r}")
            rows[key] = (fires, cycles)
    if not rows:
        fail(f"{path}: no timing data rows")
    return rows


# ---------------------------------------------------------------------------
# NNLS backends: scipy -> numpy projected gradient -> stdlib Lee-Seung
# ---------------------------------------------------------------------------


def nnls_scipy(a_rows, b):
    from scipy.optimize import nnls

    import numpy as np

    solution, _ = nnls(np.array(a_rows, dtype=float), np.array(b, dtype=float))
    return [float(v) for v in solution]


def nnls_numpy_projected_gradient(a_rows, b, max_iter: int = 20000, tol: float = 1e-12):
    import numpy as np

    a = np.array(a_rows, dtype=float)
    target = np.array(b, dtype=float)
    n_unknowns = a.shape[1]
    ata = a.T @ a
    atb = a.T @ target
    eigenvalues = np.linalg.eigvalsh(ata)
    lipschitz = float(eigenvalues[-1]) if eigenvalues.size else 0.0
    if lipschitz <= 0.0:
        return [0.0] * n_unknowns
    step = 1.0 / lipschitz
    x = np.maximum(atb, 0.0)
    previous_objective = math.inf
    for _ in range(max_iter):
        x = np.maximum(x - step * (ata @ x - atb), 0.0)
        residual = ata @ x - atb
        objective = 0.5 * float(x @ residual)
        if previous_objective - objective <= tol * max(1.0, objective):
            break
        previous_objective = objective
    return [float(v) for v in x]


def nnls_python_multiplicative(a_rows, b, iterations: int = 2000):
    n_rows = len(a_rows)
    n_unknowns = len(a_rows[0])
    ata = [[0.0] * n_unknowns for _ in range(n_unknowns)]
    atb = [0.0] * n_unknowns
    for row, target in zip(a_rows, b):
        for i, a_i in enumerate(row):
            if a_i == 0.0:
                continue
            atb[i] += a_i * target
            ata_row_i = ata[i]
            for j in range(i + 1):
                ata_row_i[j] += a_i * row[j]
    for i in range(n_unknowns):
        for j in range(i):
            ata[j][i] = ata[i][j]
    eps = 1e-12
    x = [max(atb[i], 1.0) for i in range(n_unknowns)]
    for _ in range(iterations):
        changed = 0.0
        for i in range(n_unknowns):
            numerator = atb[i]
            denominator = 0.0
            ata_row_i = ata[i]
            for j in range(n_unknowns):
                denominator += ata_row_i[j] * x[j]
            new_value = x[i] * numerator / (denominator + eps)
            changed = max(changed, abs(new_value - x[i]))
            x[i] = new_value
        if changed <= 1e-12:
            break
    return x


def solve_nnls(a_rows, b):
    """Return (backend_name, solution); first available backend wins.

    Row-normalize before fitting: each supernode contributes one equation
    sum_k a_row[k]*base[k] = t_s. Raw rdtscp cycles and op-weight counts span
    many orders of magnitude, so the un-normalized normal equations are
    dominated by the largest supernodes and projected-gradient/multiplicative
    solvers collapse to base=0 for every kind (observed on the 54k-supernode
    XiangShan fit: all base[kind]=0, R^2 ~ -1e6). Dividing each row and its
    target by the row's static-weight sum gives every supernode equal vote and
    keeps base[kind] in a comparable range. base[kind] retains the same
    physical units (cycles per unit static weight) because both sides are
    divided by the same positive scalar; prediction on the original a_row is
    unchanged.
    """
    norm_rows = []
    norm_b = []
    for row, target in zip(a_rows, b):
        row_sum = sum(row)
        if row_sum > 0.0:
            norm_rows.append([v / row_sum for v in row])
            norm_b.append(target / row_sum)
        else:
            norm_rows.append(list(row))
            norm_b.append(target)
    try:
        return "scipy.optimize.nnls", nnls_scipy(norm_rows, norm_b)
    except ImportError:
        pass
    try:
        import numpy  # noqa: F401

        return "numpy projected-gradient", nnls_numpy_projected_gradient(norm_rows, norm_b)
    except ImportError:
        pass
    return "pure-python Lee-Seung multiplicative-update (2000 iterations)", nnls_python_multiplicative(norm_rows, norm_b)


# ---------------------------------------------------------------------------
# Fit, validation, attribution
# ---------------------------------------------------------------------------


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def r_squared(measured: list[float], predicted: list[float]) -> float | None:
    if len(measured) < 2:
        return None
    avg = mean(measured)
    ss_tot = sum((v - avg) ** 2 for v in measured)
    ss_res = sum((m - p) ** 2 for m, p in zip(measured, predicted))
    if ss_tot == 0.0:
        return 1.0 if ss_res == 0.0 else 0.0
    return 1.0 - ss_res / ss_tot


def percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = min(len(sorted_values) - 1, max(0, math.ceil(q * len(sorted_values)) - 1))
    return sorted_values[rank]


def relative_errors(measured: list[float], predicted: list[float]) -> list[float]:
    errors = []
    for m, p in zip(measured, predicted):
        if m > 0.0:
            errors.append(abs(p - m) / m)
    return sorted(errors)


def kendall_tau(equal_ranking: list[str], dominant_ranking: list[str]) -> tuple[float, int, int]:
    """Kendall tau over the union of both top lists.

    Both lists are complete rankings of the union by construction (ties broken
    by module name in the caller), so no tie correction is needed.
    """
    union = sorted(set(equal_ranking) | set(dominant_ranking))
    if len(union) < 2:
        return 1.0, 0, 0
    rank_a = {module: index for index, module in enumerate(equal_ranking)}
    rank_b = {module: index for index, module in enumerate(dominant_ranking)}
    concordant = 0
    discordant = 0
    for i in range(len(union)):
        for j in range(i + 1, len(union)):
            a_i, a_j = rank_a[union[i]], rank_a[union[j]]
            b_i, b_j = rank_b[union[i]], rank_b[union[j]]
            if (a_i - a_j) * (b_i - b_j) > 0:
                concordant += 1
            else:
                discordant += 1
    total = concordant + discordant
    tau = (concordant - discordant) / total if total else 1.0
    return tau, concordant, discordant


def truncate_path(path: str, depth: int | None) -> str:
    if depth is None:
        return path
    segments = path.split("$")
    return "$".join(segments[:depth]) if len(segments) > depth else path


@dataclass
class Analysis:
    module_table: list[str]
    kind_table: list[str]
    total_supernodes: int
    fired_supernodes: list[dict]
    unfired_ordinals: list[int]
    nnls_backend: str
    base_by_kind: list[float]
    r2_all: float | None
    r2_single_origin: float | None
    single_origin_count: int
    quantile_points: tuple
    relerr_all: list[float]
    relerr_single: list[float]
    equal_cycles: dict = field(default_factory=dict)
    dominant_cycles: dict = field(default_factory=dict)
    glue_cycles: dict = field(default_factory=dict)
    total_fired_cycles: int = 0
    conservation_relative_gap: float = 0.0
    conservation_ok: bool = False
    rollup_depths: tuple = DEFAULT_ROLLUP_DEPTHS
    top: int = DEFAULT_TOP
    equal_top_ranking: list = field(default_factory=list)
    dominant_top_ranking: list = field(default_factory=list)
    tau: float = 1.0
    tau_concordant: int = 0
    tau_discordant: int = 0
    tau_ok: bool = True
    zero_weight_supernodes: list = field(default_factory=list)
    time_unit: str = "cycles"

    def module_name(self, module_idx: int) -> str:
        return self.module_table[module_idx] if module_idx is not None else UNKNOWN_MODULE


def top_ranking(cycles: dict, top: int, universe: list[str]) -> list[str]:
    scored = sorted(cycles.items(), key=lambda item: (-item[1], item[0]))[:top]
    ranked = [module for module, value in scored if value > 0.0]
    # Extend with zero-cycle modules so both rankings are total orders over the
    # union (ties broken by name); required for a well-defined Kendall tau.
    ranked_set = set(ranked)
    ranked.extend(sorted(module for module in universe if module not in ranked_set))
    return ranked


def analyze(manifest: dict, timing_rows, width_model, rollup_depths, top: int) -> Analysis:
    module_table = manifest["module_table"]
    kind_table = manifest["kind_table"]
    groups_by_ordinal = manifest["groups_by_ordinal"]

    timing_by_ordinal: dict[int, list[tuple[str, int, int]]] = defaultdict(list)
    for (supernode_id, phase), (fires, cycles) in timing_rows.items():
        timing_by_ordinal[supernode_id].append((phase, fires, cycles))
    unknown_ids = sorted(set(timing_by_ordinal) - set(groups_by_ordinal))
    if unknown_ids:
        shown = ", ".join(str(v) for v in unknown_ids[:10])
        fail(f"timing TSV references {len(unknown_ids)} supernode id(s) absent from the manifest: {shown}")

    unfired_ordinals = sorted(set(groups_by_ordinal) - set(timing_by_ordinal))
    width_factors = {kind_idx: {} for kind_idx in range(len(kind_table))}
    fired = []
    for ordinal in sorted(timing_by_ordinal):
        groups = groups_by_ordinal[ordinal]
        # A[s, kind] = sum over groups with that kind of count * widthFactor(width).
        a_row = [0.0] * len(kind_table)
        static_weight_by_kind = [0.0] * len(kind_table)
        module_static_weight: dict[int | None, float] = defaultdict(float)
        distinct_modules = set()
        total_ops = 0
        for kind_idx, width, origins, count in groups:
            if width not in width_factors[kind_idx]:
                width_factors[kind_idx][width] = width_factor(width, width_model)
            factor = width_factors[kind_idx][width]
            weight = count * factor
            a_row[kind_idx] += weight
            static_weight_by_kind[kind_idx] += weight
            total_ops += count
            if origins:
                share = weight / len(origins)
                for mod_idx in origins:
                    module_static_weight[mod_idx] += share
                    distinct_modules.add(mod_idx)
            else:
                module_static_weight[None] += weight
        phases = sorted(phase for phase, _, _ in timing_by_ordinal[ordinal])
        fires_total = sum(fires for _, fires, _ in timing_by_ordinal[ordinal])
        cycles_total = sum(cycles for _, _, cycles in timing_by_ordinal[ordinal])
        fired.append(
            {
                "ordinal": ordinal,
                "phases": phases,
                "fires": fires_total,
                "cycles": cycles_total,
                "t_s": cycles_total / fires_total,
                "a_row": a_row,
                "static_weight_by_kind": static_weight_by_kind,
                "module_static_weight": dict(module_static_weight),
                "single_origin": len(distinct_modules) == 1,
                "op_count": total_ops,
            }
        )

    a_rows = [sn["a_row"] for sn in fired]
    b = [sn["t_s"] for sn in fired]
    nnls_backend, base_by_kind = solve_nnls(a_rows, b)

    # Holdout validation: predicted t_s from fitted weights vs measured.
    measured_all = []
    predicted_all = []
    measured_single = []
    predicted_single = []
    for sn in fired:
        predicted = sum(a * x for a, x in zip(sn["a_row"], base_by_kind))
        sn["predicted_t_s"] = predicted
        measured_all.append(sn["t_s"])
        predicted_all.append(predicted)
        if sn["single_origin"]:
            measured_single.append(sn["t_s"])
            predicted_single.append(predicted)
    result_r2_all = r_squared(measured_all, predicted_all)
    result_r2_single = r_squared(measured_single, predicted_single)
    quantile_points = (0.50, 0.90, 0.99)

    # Attribution (plan section 6.1), one group-level pass per supernode:
    #   equal    — multi-origin op weight split evenly across its origins;
    #              ops with empty origins go to __unknown__ (conserves cycles).
    #   dominant — the whole supernode's cycles go to the module with the
    #              largest equal-view weight share (conserves cycles).
    #   glue     — multi-origin op share diverted to __cross_module__;
    #              __unknown__ kept as its own bucket.
    equal_cycles: dict[str, float] = defaultdict(float)
    dominant_cycles: dict[str, float] = defaultdict(float)
    glue_cycles: dict[str, float] = defaultdict(float)
    zero_weight_supernodes: list[int] = []
    total_fired_cycles = 0
    for sn in fired:
        cycles_s = sn["cycles"]
        total_fired_cycles += cycles_s
        if cycles_s == 0:
            continue
        fitted = sum(
            static * base for static, base in zip(sn["static_weight_by_kind"], base_by_kind)
        )
        if fitted <= 0.0:
            # NNLS may zero a whole kind column on tiny/degenerate fits (few
            # supernodes, near-noise timing). Those ops still consumed cycles;
            # fall back to their raw static weight so no supernode becomes
            # unattributable, and count it for the report. The op-level weights
            # below must use the SAME fallback (base=1 per kind) or the
            # numerator shares would not sum to this denominator and cycles
            # would silently vanish from the conservation check.
            fitted = sum(sn["static_weight_by_kind"])
            zero_weight_supernodes.append(sn["ordinal"])
            effective_base = [1.0] * len(base_by_kind)
        else:
            effective_base = base_by_kind
        denominator = fitted
        if denominator <= 0.0:
            fail(
                f"supernode {sn['ordinal']}: fitted weights give zero total "
                f"(degenerate cost model); cannot attribute {cycles_s} cycles"
            )
        equal_shares: dict[int | None, float] = defaultdict(float)
        glue_shares: dict[str, float] = defaultdict(float)
        for kind_idx, width, origins, count in groups_by_ordinal[sn["ordinal"]]:
            op_weight = count * width_factors[kind_idx][width] * effective_base[kind_idx]
            if op_weight == 0.0:
                continue
            if origins:
                for mod_idx in origins:
                    equal_shares[mod_idx] += op_weight / len(origins)
            else:
                equal_shares[None] += op_weight
            if not origins:
                glue_shares[UNKNOWN_MODULE] += op_weight
            elif len(origins) == 1:
                glue_shares[module_table[origins[0]]] += op_weight
            else:
                glue_shares[CROSS_MODULE] += op_weight
        for mod_idx, weight in equal_shares.items():
            name = module_table[mod_idx] if mod_idx is not None else UNKNOWN_MODULE
            equal_cycles[name] += cycles_s * weight / denominator
        for name, weight in glue_shares.items():
            glue_cycles[name] += cycles_s * weight / denominator
        if equal_shares:
            winner = min(equal_shares, key=lambda m: (-equal_shares[m], m if m is not None else -1))
            dominant_cycles[module_table[winner] if winner is not None else UNKNOWN_MODULE] += cycles_s

    total_equal = sum(equal_cycles.values())
    relative_gap = abs(total_equal - total_fired_cycles) / total_fired_cycles if total_fired_cycles else 0.0

    universe = sorted(set(equal_cycles) | set(dominant_cycles))
    equal_top_ranking = top_ranking(equal_cycles, top, universe)
    dominant_top_ranking = top_ranking(dominant_cycles, top, universe)
    tau, concordant, discordant = kendall_tau(equal_top_ranking, dominant_top_ranking)

    analysis = Analysis(
        module_table=module_table,
        kind_table=kind_table,
        total_supernodes=len(groups_by_ordinal),
        fired_supernodes=fired,
        unfired_ordinals=unfired_ordinals,
        nnls_backend=nnls_backend,
        base_by_kind=list(base_by_kind),
        r2_all=result_r2_all,
        r2_single_origin=result_r2_single,
        single_origin_count=len(measured_single),
        quantile_points=quantile_points,
        relerr_all=relative_errors(measured_all, predicted_all),
        relerr_single=relative_errors(measured_single, predicted_single),
        equal_cycles=dict(equal_cycles),
        dominant_cycles=dict(dominant_cycles),
        glue_cycles=dict(glue_cycles),
        total_fired_cycles=total_fired_cycles,
        time_unit=getattr(timing_rows, "unit", "cycles"),
        conservation_relative_gap=relative_gap,
        conservation_ok=relative_gap <= CONSERVATION_TOLERANCE,
        rollup_depths=tuple(rollup_depths),
        top=top,
        equal_top_ranking=equal_top_ranking,
        dominant_top_ranking=dominant_top_ranking,
        tau=tau,
        tau_concordant=concordant,
        tau_discordant=discordant,
        tau_ok=tau >= TAU_CONFIDENCE_THRESHOLD,
        zero_weight_supernodes=list(zero_weight_supernodes),
    )
    return analysis


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


def confidence_warnings(analysis: Analysis) -> list[str]:
    warnings = []
    r2_all = analysis.r2_all
    if r2_all is None:
        warnings.append("R^2 over fired supernodes is undefined (fewer than 2 fired supernodes); fit confidence is LOW.")
    elif r2_all < R2_CONFIDENCE_THRESHOLD:
        warnings.append(
            f"LOW CONFIDENCE: cost-model R^2 = {r2_all:.4f} < {R2_CONFIDENCE_THRESHOLD} over fired supernodes. "
            "Per plan section 6.2, fall back to a per-kind bucketed weighted-median model and treat the "
            "attribution below as indicative only."
        )
    r2_single = analysis.r2_single_origin
    if analysis.single_origin_count >= 2 and r2_single is not None and r2_single < R2_CONFIDENCE_THRESHOLD:
        warnings.append(
            f"LOW CONFIDENCE: single-origin holdout R^2 = {r2_single:.4f} < {R2_CONFIDENCE_THRESHOLD} "
            f"({analysis.single_origin_count} supernodes)."
        )
    if not analysis.tau_ok:
        warnings.append(
            f"RANK INSTABILITY: Kendall tau between equal and dominant top-{analysis.top} rankings is "
            f"{analysis.tau:.4f} < {TAU_CONFIDENCE_THRESHOLD}; conclusions are sensitive to the sharing rule. "
            "Prefer the equal view and treat divergent modules with care."
        )
    if analysis.zero_weight_supernodes:
        warnings.append(
            f"DEGENERATE FIT: {len(analysis.zero_weight_supernodes)} fired supernode(s) "
            f"(ordinals {analysis.zero_weight_supernodes[:10]}{'...' if len(analysis.zero_weight_supernodes) > 10 else ''}) "
            "got zero fitted weight from NNLS and were attributed with raw static-weight fallback. "
            "Their intra-supernode module shares are cost-model-free; treat their module attributions as low confidence."
        )
    if not analysis.conservation_ok:
        warnings.append(
            f"CONSERVATION VIOLATION: attributed {analysis.time_unit} deviate from fired {analysis.time_unit} by "
            f"{analysis.conservation_relative_gap * 100.0:.4f}% > {CONSERVATION_TOLERANCE * 100.0:.0f}%."
        )
    return warnings


def write_tsv(analysis: Analysis, out: TextIO) -> None:
    unit = analysis.time_unit
    print("# grhsim module attribution (grhsim_module_attribution.py)", file=out)
    print(f"# model: w_i = base[kind_i] * widthFactor(width_i); base[kind] calibrated by NNLS against t_s = {unit}/fires", file=out)
    print(f"# attribution: A(m) += {unit}_s * (sum_{{i: m in M_i}} w_i / |M_i|) / (sum_i w_i)  (plan section 6.1)", file=out)
    print("# columns:", file=out)
    print("#   module                   module path ('$'-joined); depth < 0 means the full leaf path", file=out)
    print("#   depth                    rollup depth: -1 = leaf, 1..N = path truncated to first N segments", file=out)
    print(f"#   {unit}_equal             attributed {unit}, multi-origin op weight split evenly across origins", file=out)
    print(f"#   {unit}_dominant          attributed {unit}, whole supernode assigned to the largest-share module", file=out)
    print(f"#   {unit}_glue              attributed {unit}, multi-origin op share diverted to __cross_module__", file=out)
    print(f"#   glue_excluded_share      1 - {unit}_glue(module)/total_fired_{unit}: share of total NOT in this", file=out)
    print("#                            module under the glue view (sum over modules >= depth-specific totals,", file=out)
    print("#                            because __cross_module__ is not a module row)", file=out)
    print(f"#   pct_of_total             {unit}_equal / total_fired_{unit} * 100", file=out)
    print(f"# total_fired_{unit}: {analysis.total_fired_cycles}", file=out)
    print(f"module\tdepth\t{unit}_equal\t{unit}_dominant\t{unit}_glue\tglue_excluded_share\tpct_of_total", file=out)
    total = analysis.total_fired_cycles
    depths: list[int | None] = [None, *sorted(analysis.rollup_depths)]
    seen: set[tuple[str, int]] = set()
    rows = []
    for depth in depths:
        equal_roll: dict[str, float] = defaultdict(float)
        dominant_roll: dict[str, float] = defaultdict(float)
        glue_roll: dict[str, float] = defaultdict(float)
        for module in set(analysis.equal_cycles) | set(analysis.dominant_cycles) | set(analysis.glue_cycles):
            key = truncate_path(module, depth)
            equal_roll[key] += analysis.equal_cycles.get(module, 0.0)
            dominant_roll[key] += analysis.dominant_cycles.get(module, 0.0)
            glue_roll[key] += analysis.glue_cycles.get(module, 0.0)
        depth_label = -1 if depth is None else depth
        for key in sorted(equal_roll, key=lambda m: (-equal_roll[m], m)):
            if (key, depth_label) in seen:
                continue
            seen.add((key, depth_label))
            glue_value = glue_roll.get(key, 0.0)
            glue_excluded_share = (1.0 - glue_value / total) if total else 0.0
            pct = (100.0 * equal_roll[key] / total) if total else 0.0
            rows.append((key, depth_label, equal_roll[key], dominant_roll.get(key, 0.0), glue_value, glue_excluded_share, pct))
    for key, depth_label, equal_value, dominant_value, glue_value, glue_excluded_share, pct in rows:
        print(
            f"{key}\t{depth_label}\t{equal_value:.1f}\t{dominant_value:.1f}\t"
            f"{glue_value:.1f}\t{glue_excluded_share:.6f}\t{pct:.4f}",
            file=out,
        )


def format_quantiles(errors: list[float], quantile_points) -> str:
    if not errors:
        return "n/a"
    parts = [f"p{int(q * 100)}={percentile(errors, q):.4f}" for q in quantile_points]
    return " ".join(parts)


def module_mix_text(analysis: Analysis, sn: dict) -> str:
    total_static = sum(sn["module_static_weight"].values())
    if total_static <= 0.0:
        return "n/a"
    parts = []
    for mod_idx, static_weight in sorted(
        sn["module_static_weight"].items(),
        key=lambda item: (-item[1], analysis.module_name(item[0])),
    ):
        share = static_weight / total_static
        parts.append(f"{analysis.module_name(mod_idx)}={share * 100.0:.1f}%")
    return ", ".join(parts)


def write_report(analysis: Analysis, manifest: dict, timing_path: Path | None, out: TextIO) -> None:
    unit = analysis.time_unit
    print("# grhsim module attribution report", file=out)
    print(file=out)
    print(f"- manifest: `{manifest['path']}`", file=out)
    if manifest.get("model"):
        print(f"- model: `{manifest['model']}`", file=out)
    if timing_path is not None:
        print(f"- timing: `{timing_path}`", file=out)
    print(f"- NNLS backend: **{analysis.nnls_backend}**", file=out)
    print(
        f"- supernodes: {analysis.total_supernodes} in manifest, {len(analysis.fired_supernodes)} fired, "
        f"{len(analysis.unfired_ordinals)} never fired (excluded from fit)",
        file=out,
    )
    print(f"- total fired {unit}: {analysis.total_fired_cycles}", file=out)
    print(file=out)

    warnings = confidence_warnings(analysis)
    if warnings:
        print("## Warnings", file=out)
        print(file=out)
        for warning in warnings:
            print(f"**WARNING** {warning}", file=out)
            print(file=out)

    print("## Cost model calibration (NNLS)", file=out)
    print(file=out)
    print("| kind | base |", file=out)
    print("|---|---:|", file=out)
    for kind, base in zip(analysis.kind_table, analysis.base_by_kind):
        print(f"| {kind} | {base:.6f} |", file=out)
    print(file=out)
    r2_all_text = "n/a" if analysis.r2_all is None else f"{analysis.r2_all:.4f}"
    r2_single_text = "n/a" if analysis.r2_single_origin is None else f"{analysis.r2_single_origin:.4f}"
    print(f"- R^2 over all fired supernodes: **{r2_all_text}** (threshold {R2_CONFIDENCE_THRESHOLD})", file=out)
    print(
        f"- R^2 over single-origin holdout subset ({analysis.single_origin_count} supernodes): **{r2_single_text}**",
        file=out,
    )
    print(f"- relative |error| quantiles (all fired): {format_quantiles(analysis.relerr_all, analysis.quantile_points)}", file=out)
    print(
        f"- relative |error| quantiles (single-origin): {format_quantiles(analysis.relerr_single, analysis.quantile_points)}",
        file=out,
    )
    print(file=out)

    print("## Conservation check (equal view)", file=out)
    print(file=out)
    total_equal = sum(analysis.equal_cycles.values())
    status = "OK" if analysis.conservation_ok else "VIOLATED"
    print(f"- sum of attributed {unit}: {total_equal:.1f}", file=out)
    print(f"- sum of fired {unit}: {analysis.total_fired_cycles}", file=out)
    print(
        f"- relative gap: {analysis.conservation_relative_gap * 100.0:.6f}% "
        f"(tolerance {CONSERVATION_TOLERANCE * 100.0:.0f}%) -> **{status}**",
        file=out,
    )
    print(file=out)

    print(f"## Ranking robustness (top {analysis.top})", file=out)
    print(file=out)
    tau_status = "OK" if analysis.tau_ok else "BELOW THRESHOLD"
    print(
        f"- Kendall tau(equal, dominant) over union of both top-{analysis.top} lists: **{analysis.tau:.4f}** "
        f"({analysis.tau_concordant} concordant / {analysis.tau_discordant} discordant pairs, "
        f"threshold {TAU_CONFIDENCE_THRESHOLD}) -> {tau_status}",
        file=out,
    )
    print(file=out)

    total = analysis.total_fired_cycles
    views = (
        ("equal", analysis.equal_cycles),
        ("dominant", analysis.dominant_cycles),
        ("glue", analysis.glue_cycles),
    )
    for view_name, view_cycles in views:
        print(f"## Top modules — {view_name} view (leaf depth)", file=out)
        print(file=out)
        print(f"| rank | module | {unit} | pct_of_total |", file=out)
        print("|---:|---|---:|---:|", file=out)
        ranked = sorted(view_cycles.items(), key=lambda item: (-item[1], item[0]))[: analysis.top]
        for rank, (module, cycles) in enumerate(ranked, start=1):
            pct = 100.0 * cycles / total if total else 0.0
            print(f"| {rank} | {module} | {cycles:.1f} | {pct:.4f} |", file=out)
        print(file=out)

    for depth in sorted(analysis.rollup_depths):
        print(f"## Top modules — equal view, rollup depth {depth}", file=out)
        print(file=out)
        print(f"| rank | module | {unit}_equal | pct_of_total |", file=out)
        print("|---:|---|---:|---:|", file=out)
        roll: dict[str, float] = defaultdict(float)
        for module, cycles in analysis.equal_cycles.items():
            roll[truncate_path(module, depth)] += cycles
        for rank, (module, cycles) in enumerate(sorted(roll.items(), key=lambda item: (-item[1], item[0]))[: analysis.top], start=1):
            pct = 100.0 * cycles / total if total else 0.0
            print(f"| {rank} | {module} | {cycles:.1f} | {pct:.4f} |", file=out)
        print(file=out)

    print(f"## Top 10 hottest supernodes (by fired {unit})", file=out)
    print(file=out)
    print(f"| supernode | phase(s) | fires | {unit} | t_s | fitted t_s | module mix (static weight share) |", file=out)
    print("|---:|---|---:|---:|---:|---:|---|", file=out)
    hottest = sorted(analysis.fired_supernodes, key=lambda sn: (-sn["cycles"], sn["ordinal"]))[:10]
    for sn in hottest:
        mix = module_mix_text(analysis, sn)
        print(
            f"| {sn['ordinal']} | {','.join(sn['phases'])} | {sn['fires']} | {sn['cycles']} | "
            f"{sn['t_s']:.1f} | {sn['predicted_t_s']:.1f} | {mix} |",
            file=out,
        )
    print(file=out)


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------


def build_selftest_inputs():
    """Fabricated manifest + timing with known ground truth.

    3 modules (u_top$u_a, u_top$u_b, u_top$u_c), 3 kinds with ground-truth
    base[kind] from SELFTEST_BASE, 8 supernodes (one multi-origin). Module B
    carries kAdd-heavy wide ops and provably dominates total cycles. Timing
    rows are exact: cycles = fires * t_s with t_s = sum_i w_i, so the NNLS fit
    recovers the ground truth.
    """
    module_b = f"u_top$u_b{SELFTEST_SUFFIX}"
    module_table = [
        f"u_top$u_a{SELFTEST_SUFFIX}",
        module_b,
        f"u_top$u_c{SELFTEST_SUFFIX}",
    ]
    kind_table = list(SELFTEST_BASE)
    kind_idx = {kind: i for i, kind in enumerate(kind_table)}

    def group(kind, width, origins, count):
        return {"kind_idx": kind_idx[kind], "width": width, "origins": origins, "count": count}

    A, B, C = 0, 1, 2
    # (groups, fires, fire count); t_s = sum count*base*widthFactor, cycles = fires*t_s.
    specs = [
        # 0: module A only, light kAnd ops
        ([group("kAnd", 8, [A], 4), group("kMux", 32, [A], 1)], 100),
        # 1: module B only, kAdd-heavy
        ([group("kAdd", 64, [B], 6), group("kMux", 32, [B], 2)], 100),
        # 2: module B only, wide ops (widthFactor 2.0 and 4.0)
        ([group("kAdd", 128, [B], 3), group("kMux", 256, [B], 1)], 50),
        # 3: module C only
        ([group("kAnd", 16, [C], 3), group("kAdd", 32, [C], 1)], 100),
        # 4: multi-origin supernode shared by A and B (equal split); the
        #    dominant view must still rank B first overall
        ([group("kAdd", 64, [A, B], 4), group("kMux", 32, [B], 2)], 20),
        # 5: module B only, very wide ops (per-limb regime >256)
        ([group("kAdd", 512, [B], 2)], 40),
        # 6: never fired (no timing row)
        ([group("kAnd", 8, [C], 2)], 0),
        # 7: module A only, moderate
        ([group("kMux", 64, [A], 3)], 30),
    ]
    supernodes = []
    timing_rows = []
    for ordinal, (groups, fires) in enumerate(specs):
        supernodes.append(
            {
                "ordinal": ordinal,
                "category": "NonSink",
                "phase": "General",
                "op_count": sum(g["count"] for g in groups),
                "groups": groups,
            }
        )
        if fires > 0:
            t_s = sum(
                g["count"] * SELFTEST_BASE[kind_table[g["kind_idx"]]] * width_factor(g["width"], DEFAULT_WIDTH_MODEL)
                for g in groups
            )
            cycles = int(round(fires * t_s))
            timing_rows.append((ordinal, "General", fires, cycles))
    manifest = {
        "path": Path("<selftest>"),
        "model": "selftest",
        "module_table": module_table,
        "kind_table": kind_table,
        "groups_by_ordinal": {sn["ordinal"]: [
            (g["kind_idx"], g["width"], tuple(g["origins"]), g["count"]) for g in sn["groups"]
        ] for sn in supernodes},
    }
    timing = {(ordinal, phase): (fires, cycles) for ordinal, phase, fires, cycles in timing_rows}
    return manifest, timing, module_b


def run_selftest(out: TextIO) -> int:
    manifest, timing, module_b = build_selftest_inputs()
    analysis = analyze(manifest, timing, DEFAULT_WIDTH_MODEL, DEFAULT_ROLLUP_DEPTHS, DEFAULT_TOP)

    checks = []

    def check(name, ok, detail):
        checks.append((name, ok, detail))

    check(
        "conservation (equal view, <=1%)",
        analysis.conservation_ok,
        f"attributed={sum(analysis.equal_cycles.values()):.1f} fired={analysis.total_fired_cycles} "
        f"gap={analysis.conservation_relative_gap * 100.0:.6f}%",
    )
    for view_name, cycles in (("equal", analysis.equal_cycles), ("dominant", analysis.dominant_cycles), ("glue", analysis.glue_cycles)):
        ranked = sorted(cycles.items(), key=lambda item: (-item[1], item[0]))
        top_module = ranked[0][0] if ranked else None
        check(f"module B ranks #1 in {view_name} view", top_module == module_b, f"top={top_module}")
    check(
        f"kendall tau >= {SELFTEST_TAU_THRESHOLD}",
        analysis.tau >= SELFTEST_TAU_THRESHOLD,
        f"tau={analysis.tau:.4f}",
    )
    recovered = {kind: base for kind, base in zip(analysis.kind_table, analysis.base_by_kind)}
    fit_close = all(
        abs(recovered[kind] - truth) <= SELFTEST_TOLERANCE * max(1.0, truth)
        for kind, truth in SELFTEST_BASE.items()
    )
    check(
        "NNLS recovers ground-truth base[kind]",
        fit_close,
        "recovered={" + ", ".join(f"{k}={recovered[k]:.6f} (truth {SELFTEST_BASE[k]})" for k in analysis.kind_table) + "}",
    )
    check(
        "R^2 == 1.0 on exact fabricated data",
        analysis.r2_all is not None and abs(analysis.r2_all - 1.0) <= 1e-9,
        f"r2_all={analysis.r2_all}",
    )
    check(
        "never-fired supernode excluded from fit and counted",
        analysis.unfired_ordinals == [6] and len(analysis.fired_supernodes) == 7,
        f"unfired={analysis.unfired_ordinals}",
    )
    check(
        "multi-origin supernode split between A and B in equal view",
        analysis.equal_cycles.get(f"u_top$u_a{SELFTEST_SUFFIX}", 0.0) > 0.0
        and analysis.equal_cycles.get(module_b, 0.0) > analysis.equal_cycles.get(f"u_top$u_a{SELFTEST_SUFFIX}", 0.0),
        f"equal A={analysis.equal_cycles.get(f'u_top$u_a{SELFTEST_SUFFIX}', 0.0):.1f} "
        f"B={analysis.equal_cycles.get(module_b, 0.0):.1f}",
    )
    check(
        "glue view routes multi-origin share to __cross_module__",
        analysis.glue_cycles.get(CROSS_MODULE, 0.0) > 0.0,
        f"__cross_module__={analysis.glue_cycles.get(CROSS_MODULE, 0.0):.1f}",
    )
    module_a = f"u_top$u_a{SELFTEST_SUFFIX}"
    module_c = f"u_top$u_c{SELFTEST_SUFFIX}"
    check(
        "equal-view cycles match analytic ground truth",
        abs(analysis.equal_cycles.get(module_a, 0.0) - 2920.0) <= 1.0
        and abs(analysis.equal_cycles.get(module_b, 0.0) - 11420.0) <= 1.0
        and abs(analysis.equal_cycles.get(module_c, 0.0) - 1400.0) <= 1.0,
        f"A={analysis.equal_cycles.get(module_a, 0.0):.1f} (expect 2920) "
        f"B={analysis.equal_cycles.get(module_b, 0.0):.1f} (expect 11420) "
        f"C={analysis.equal_cycles.get(module_c, 0.0):.1f} (expect 1400)",
    )
    check(
        "dominant view assigns whole multi-origin supernode to B",
        abs(analysis.dominant_cycles.get(module_b, 0.0) - 11620.0) <= 1.0,
        f"B={analysis.dominant_cycles.get(module_b, 0.0):.1f} (expect 11620)",
    )
    check(
        "glue __cross_module__ matches analytic share",
        abs(analysis.glue_cycles.get(CROSS_MODULE, 0.0) - 400.0) <= 1.0,
        f"__cross_module__={analysis.glue_cycles.get(CROSS_MODULE, 0.0):.4f} (expect 400.0)",
    )

    print("grhsim_module_attribution --selftest", file=out)
    print(f"NNLS backend: {analysis.nnls_backend}", file=out)
    print(f"fired supernodes: {len(analysis.fired_supernodes)} (1 never-fired excluded)", file=out)
    print(f"total fired cycles: {analysis.total_fired_cycles}", file=out)
    for name, ok, detail in checks:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}: {detail}", file=out)
    failed = [name for name, ok, _ in checks if not ok]
    if failed:
        print(f"selftest FAILED: {len(failed)} check(s) failed", file=out)
        return 1
    print(f"selftest OK: {len(checks)} checks passed", file=out)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_rollup_depths(text: str) -> tuple[int, ...]:
    depths = []
    for piece in text.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            depth = int(piece)
        except ValueError:
            fail(f"invalid --rollup-depths entry: {piece!r}")
        if depth <= 0:
            fail(f"--rollup-depths entries must be positive: {depth}")
        depths.append(depth)
    if not depths:
        fail("--rollup-depths must name at least one depth")
    return tuple(sorted(set(depths)))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Attribute grhsim supernode runtime cycles to RTL module paths "
        "(manifest join timing TSV, plan section 6).",
    )
    parser.add_argument("--manifest", type=Path, help="supernode-origin manifest JSON (grhsim-supernode-origin-manifest/v1)")
    parser.add_argument("--timing", type=Path, help="runtime timing TSV: supernode_id<TAB>phase<TAB>fires<TAB>cycles (or nanoseconds)")
    parser.add_argument("--out-tsv", type=Path, help="write the module attribution TSV here")
    parser.add_argument("--report", type=Path, help="write the markdown report here")
    parser.add_argument("--width-model", type=Path, help="JSON file overriding the widthFactor bucket table")
    parser.add_argument(
        "--rollup-depths",
        default=",".join(str(d) for d in DEFAULT_ROLLUP_DEPTHS),
        help="comma-separated rollup depths for '$'-joined module paths (default: 1,2,3)",
    )
    parser.add_argument("--top", type=int, default=DEFAULT_TOP, help="top-N modules per view (default: 30)")
    parser.add_argument("--selftest", action="store_true", help="run the built-in fabricated example and exit")
    args = parser.parse_args(argv)

    try:
        if args.selftest:
            return run_selftest(sys.stdout)
        missing = [flag for flag, value in (("--manifest", args.manifest), ("--timing", args.timing), ("--out-tsv", args.out_tsv), ("--report", args.report)) if value is None]
        if missing:
            parser.error("required without --selftest: " + ", ".join(missing))
        if args.top <= 0:
            parser.error("--top must be positive")
        rollup_depths = parse_rollup_depths(args.rollup_depths)
        width_model = load_width_model(args.width_model)
        manifest = load_manifest(args.manifest)
        timing = read_timing(args.timing)
        analysis = analyze(manifest, timing, width_model, rollup_depths, args.top)

        args.out_tsv.parent.mkdir(parents=True, exist_ok=True)
        with args.out_tsv.open("w", encoding="utf-8", newline="") as out:
            write_tsv(analysis, out)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("w", encoding="utf-8") as out:
            write_report(analysis, manifest, args.timing, out)

        print(f"NNLS backend: {analysis.nnls_backend}")
        print(
            f"supernodes: {analysis.total_supernodes} total, {len(analysis.fired_supernodes)} fired, "
            f"{len(analysis.unfired_ordinals)} never fired (excluded from fit)"
        )
        r2_text = "n/a" if analysis.r2_all is None else f"{analysis.r2_all:.4f}"
        print(f"R^2 (all fired): {r2_text}; Kendall tau top-{args.top}: {analysis.tau:.4f}")
        print(
            f"conservation: attributed={sum(analysis.equal_cycles.values()):.1f} "
            f"fired={analysis.total_fired_cycles} gap={analysis.conservation_relative_gap * 100.0:.6f}% "
            f"({'OK' if analysis.conservation_ok else 'VIOLATED'})"
        )
        for warning in confidence_warnings(analysis):
            print(f"WARNING: {warning}", file=sys.stderr)
        print(f"wrote {args.out_tsv} and {args.report}")
        return 0
    except AttributionError as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
