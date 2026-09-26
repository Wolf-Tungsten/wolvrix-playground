#!/usr/bin/env python3
"""NO00020 module-level semantic comparison of unpartitioned gsim IR vs GrhSIM IR.

Compares two "pre-partition" IR dumps of the same XiangShan design:

  * gsim side: SimTop_PreCoarsen.json -- full graph export after all gsim
    optimization passes, before graphPartition(). Node records carry
    name/type/width plus assignTrees of ENodes (children are integer ids
    into the tree's flat "nodes" array; OP_EMPTY leaves reference other
    nodes by name, OP_INT leaves carry strVal constants).
  * GrhSIM side: grhsim_pre_partition.json -- wolvrix.grhsim.v1 compact
    checkpoint after all semantic passes, before cpu.st.split-phase
    (production shape; G1b proves the second CPU mapping pass does not
    change the op multiset).

Metrics (pre-registered in pdocs/NO00020-*.md, HYPOTHESIS section):

  M-name     Register anchor matching: gsim NODE_REG_SRC nodes vs GrhSIM
             register-class states (logic-type states EXCLUDING `__event_*`
             edge-trigger bookkeeping states, which have no design-register
             counterpart on either side; the including-events caliber is
             reported alongside for reference). Names are normalized with
             normalize_name() (`__DOT__` -> `_`, `$` -> `_`, collapse
             repeated `_`). Matching runs in two phases:
               1. exact normalized-key equality (groups of any arity);
               2. chunk-strip fallback for still-unmatched keys: strip one
                  trailing `_<digits>` segment (gsim splitNodes chunk suffix
                  / firtool aggregate scalarization suffix) and match on the
                  base key (an unsuffixed exact key joins its own base).
             Reported: bit-weighted coverage on BOTH sides (matched
             register bits / total register bits of that side) and
             reason-bucketed unmatched remainders.
  M-opcount  Per-module count table. Module of a gsim node/ENode: the
             node's name minus its last `__DOT__` segment (ENodes belong
             to the node whose assignTree contains them; counted per
             serialized tree occurrence). Module of a GrhSIM op:
               1. module of its first named result value;
               2. else module of its first objectRef state/input/output;
               3. else the forward-propagated owner of its results;
               4. else module of its first named operand;
               5. else the "(anonymous)" bucket.
             Owner propagation: a named value owns its own module; an
             unnamed value inherits the merged owner of everything it
             flows into without crossing another named value (unique
             module -> that module; several -> "(mixed)"; none ->
             "(dead)"). Result-less state-write sinks (regWrite/memWrite/
             output.write ...) contribute the written object's module;
             result-less side-effect ops (printf/dpi without written
             object) contribute nothing. Pass-generated top-level
             aggregates are bucketed separately on every rule above (see
             module_of_state_name): `__event_*` edge bookkeeping ->
             "(events)", `packed_bits_<digits>` (pack-bit-registers
             products) -> "(packed)", `__reg_to_mem_<digits>` (reg-to-mem
             products) -> "(reg-to-mem)". These are GrhSIM-IR-only
             artifacts with no gsim counterpart (cf. the M-name anchor
             caliber); left in "(top)" they swamp it (185K event
             regWrites, ~400K packed-merge bitwise ops, ~60K reg-to-mem
             memory ops).
             "Named" value = name is non-empty and not a generated
             temporary (`_val_<digits>`, `packed_bits_<digits>`, `_op_*`);
             results of core.state.read/core.input.read/core.state.memRead
             count as named boundaries via their referenced object.
             Module of a GrhSIM value follows the same owner rule.
             Module keys are normalized with normalize_name() so the two
             sides join textually. Closure check: per-module rows sum to
             the global totals on both sides.
  M-kinddelta
             Op composition under a joint bucket taxonomy. gsim ENode ops
             map through compare_ir_shapes.GSIM_OP_BUCKETS (OP_EMPTY ->
             "node_ref"); GrhSIM op kinds map through
             GRHSIM_KIND_BUCKETS below onto the same taxonomy. Reported
             globally and for the Top-N modules by total absolute bucket
             delta; per bucket "ops GrhSIM has in excess" ordering.
  M-cone     For paired register groups (from M-name): gsim cone = ENode
             count of the register's update tree = the assignTrees of the
             NODE_REG_DST node linked from the NODE_REG_SRC's own
             assignTree root reference (fallbacks bucketed). GrhSIM cone
             = number of distinct producer ops in the backward cone of the
             regWrite nextValue operand (operands[1] of
             core.state.regWrite), truncated at named-boundary values
             (named values and state.read/input.read/memRead results are
             not expanded; they count as boundary leaves, mirroring
             gsim's OP_EMPTY node-ref leaves). Reported: per-group cone
             sizes, ratio distribution (median/p90/mean) and outliers.

Gates (pre-registered):
  G1a  Export closure: gsim parsed node records == expected graph node
       count (non-memory) with all assignTree child ids in range; GrhSIM
       `counts` section == actual array lengths (incl. operand/result/
       objectRef totals and per-op id density).
  G1b  Dump-point representativeness: op-kind multiset of the
       pre-partition dump == that of the same run's final checkpoint.
  G1c  Reproducibility: final checkpoints byte-compare equal (report
       sha256 pairwise); on mismatch a structured diff localizes the
       first differing array/rows and classifies the cause.
  G2   Determinism: the script run twice on identical inputs produces
       byte-identical reports. Evaluated by re-running with
       --g2-reference pointing at the first run's report; the comparison
       excludes the gates.G2 subtree itself.
  G3   Anchor validity: M-name bit-weighted coverage >= 80% on both
       sides.
  G4   Memory/IO anchors: gsim NODE_MEMORY nodes vs GrhSIM array-type
       states, and gsim NODE_INP/NODE_OUT vs GrhSIM inputs/outputs,
       matched with the M-name rules; every unpaired item is attributed
       to an enumerable reason class. GrhSIM memory names are first
       unwrapped from the firtool `..._ext$Memory` wrapper (suffix
       `_ext$Memory` stripped, yielding e.g. `...__DOT__ram`) before
       normalization; reg-to-mem pass products (`__reg_to_mem_*`) and
       edge-event bookkeeping states are pre-attributed reason classes.

Outputs (written to --out-dir):
  module_compare_report.json  machine-readable report (deterministic:
                              sorted keys, no timestamps, no output paths)
  module_compare_summary.md   human-readable summary

Inputs
  --gsim-json       gsim PreCoarsen export JSON
  --grhsim-pre      GrhSIM pre-partition dump JSON (analysis subject)
  --grhsim-final    final production checkpoint of the same run (G1b/G1c)
  --grhsim-full     final checkpoint of the complete-SV route (G1c)
  --grhsim-archive  NO00015 archived final checkpoint (G1c)
  --out-dir         output directory
  --top-n           rows in per-module tables (default 25)
  --gsim-expect-nodes  expected non-memory node count from the export log
  --g2-reference    previous run's report for the G2 byte comparison
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_ir_shapes import GSIM_OP_BUCKETS  # noqa: E402

TOP_MODULE = "(top)"
MIXED_MODULE = "(mixed)"
DEAD_MODULE = "(dead)"
ANON_MODULE = "(anonymous)"
EVENTS_MODULE = "(events)"
PACKED_MODULE = "(packed)"
REG2MEM_MODULE = "(reg-to-mem)"

# GrhSIM op kind -> joint bucket taxonomy (gsim side uses GSIM_OP_BUCKETS
# with OP_EMPTY mapped to "node_ref").
GRHSIM_KIND_BUCKETS = {
    "core.compute.and": "bitwise_logic",
    "core.compute.or": "bitwise_logic",
    "core.compute.xor": "bitwise_logic",
    "core.compute.not": "bitwise_logic",
    "core.compute.logicAnd": "bitwise_logic",
    "core.compute.logicOr": "bitwise_logic",
    "core.compute.logicNot": "bitwise_logic",
    "core.compute.reduceAnd": "bitwise_logic",
    "core.compute.reduceOr": "bitwise_logic",
    "core.compute.reduceXor": "bitwise_logic",
    "core.compute.reduceNor": "bitwise_logic",
    "core.compute.reduceNand": "bitwise_logic",
    "core.compute.reduceXnor": "bitwise_logic",
    "core.compute.add": "arithmetic",
    "core.compute.sub": "arithmetic",
    "core.compute.mul": "arithmetic",
    "core.compute.div": "arithmetic",
    "core.compute.mod": "arithmetic",
    "core.compute.eq": "compare",
    "core.compute.ne": "compare",
    "core.compute.lt": "compare",
    "core.compute.le": "compare",
    "core.compute.gt": "compare",
    "core.compute.ge": "compare",
    "core.compute.mux": "mux_control",
    "core.compute.prioritySelect": "mux_control",
    "core.compute.shl": "shift",
    "core.compute.lshr": "shift",
    "core.compute.ashr": "shift",
    "core.compute.sliceStatic": "slice_index",
    "core.compute.sliceDynamic": "slice_index",
    "core.compute.bitSelect": "slice_index",
    "core.compute.sliceArray": "slice_index",
    "core.compute.concat": "aggregate_concat",
    "core.compute.replicate": "aggregate_concat",
    "core.compute.constant": "const",
    "core.compute.assign": "statement",
    "core.state.read": "state_reg_access",
    "core.state.regWrite": "state_reg_access",
    "core.state.latchWrite": "state_reg_access",
    "core.state.memRead": "memory",
    "core.state.memWrite": "memory",
    "core.state.memWriteSeq": "memory",
    "core.state.memFill": "memory",
    "core.state.memAssign": "memory",
    "core.input.read": "io",
    "core.output.write": "io",
    "core.dpi.call": "special",
    "core.system.task": "special",
}

BUCKET_ORDER = [
    "node_ref", "const", "arithmetic", "compare", "bitwise_logic",
    "mux_control", "shift", "slice_index", "aggregate_concat", "cast_width",
    "statement", "memory", "state_reg_access", "io", "special", "other",
]

REG_WRITE_KIND = "core.state.regWrite"
STATE_READ_KINDS = {"core.state.read", "core.input.read", "core.state.memRead"}
MODULE_KIND_SEP = "\x01"

_CHUNK_SUFFIX = re.compile(r"_\d+$")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Name normalization and module keys
# ---------------------------------------------------------------------------

def normalize_name(name):
    """Join both sides' separators: `__DOT__` -> `_`, `$` -> `_`, collapse."""
    return re.sub(r"_+", "_", name.replace("__DOT__", "_").replace("$", "_"))


def strip_chunk_suffix(key):
    """Strip one trailing `_<digits>` segment; None when there is none."""
    match = _CHUNK_SUFFIX.search(key)
    if not match:
        return None
    base = key[: match.start()]
    return base or None


def module_of_path(name, sep):
    """Instance-path prefix of a hierarchical name (normalized)."""
    if sep in name:
        return normalize_name(name.rsplit(sep, 1)[0])
    return TOP_MODULE


def module_of_state_name(name):
    """Module key of a GrhSIM state (or state-backed value) name.

    Pass-generated top-level aggregates get their own buckets instead of
    "(top)": `__event_*` edge bookkeeping -> EVENTS_MODULE,
    `packed_bits_<digits>` (pack-bit-registers products) -> PACKED_MODULE,
    `__reg_to_mem_<digits>` (reg-to-mem products) -> REG2MEM_MODULE.
    Everything else follows the instance-path rule."""
    if name.startswith("__event_"):
        return EVENTS_MODULE
    if name.startswith("packed_bits_") and name[12:].isdigit():
        return PACKED_MODULE
    if name.startswith("__reg_to_mem_"):
        return REG2MEM_MODULE
    return module_of_path(name, "$")


def is_generated_value_name(name):
    """Generated temporaries: empty, `_val_<digits>`, `packed_bits_<digits>`,
    GRH ingest op-local names (`_op_...`)."""
    if not name:
        return True
    if name.startswith("_val_") and name[5:].isdigit():
        return True
    if name.startswith("packed_bits_") and name[12:].isdigit():
        return True
    if name.startswith("_op_"):
        return True
    return False


def strip_mem_wrapper(name):
    """firtool memory wrapper: `<base>_ext$Memory` -> `<base>` so the
    GrhSIM array name joins the gsim NODE_MEMORY path."""
    if name.endswith("$Memory"):
        head = name[: -len("$Memory")]
        if head.endswith("_ext"):
            return head[: -len("_ext")]
    return name


# ---------------------------------------------------------------------------
# Anchor matching (M-name, G4)
# ---------------------------------------------------------------------------

def build_key_index(items):
    """items: list of (name, width). Returns {normalized key: [item...]}."""
    index = defaultdict(list)
    for name, width in items:
        index[normalize_name(name)].append((name, width))
    return index


def match_anchor_sets(gsim_items, grh_items):
    """Two-phase anchor matching. Returns match groups plus unmatched rest.

    A group: {"key", "kind", "gsim": [(name, width)...], "grhsim": [...]}.
    kind "exact" = identical normalized keys; "chunk_strip" = bases equal
    after stripping one trailing `_<digits>` from every member key.
    """
    gsim_index = build_key_index(gsim_items)
    grh_index = build_key_index(grh_items)
    gsim_keys = set(gsim_index)
    grh_keys = set(grh_index)
    groups = []
    for key in sorted(gsim_keys & grh_keys):
        groups.append({"key": key, "kind": "exact",
                       "gsim": sorted(gsim_index[key]),
                       "grhsim": sorted(grh_index[key])})
    rest_gsim = {k: v for k, v in gsim_index.items() if k not in grh_keys}
    rest_grh = {k: v for k, v in grh_index.items() if k not in gsim_keys}

    def base_groups(rest):
        bases = defaultdict(list)
        for key, members in rest.items():
            base = strip_chunk_suffix(key)
            if base is not None:
                bases[base].append((key, members))
        return bases

    gsim_bases = base_groups(rest_gsim)
    grh_bases = base_groups(rest_grh)
    used_gsim, used_grh = set(), set()
    # candidate bases: any stripped base present on either side
    for base in sorted(set(gsim_bases) | set(grh_bases)):
        g_members = [m for _key, ms in gsim_bases.get(base, ()) for m in ms]
        r_members = [m for _key, ms in grh_bases.get(base, ()) for m in ms]
        # an exact unsuffixed key on the other side joins as a member
        if base in rest_gsim and base not in {k for k, _ms in gsim_bases.get(base, ())}:
            g_members += rest_gsim[base]
        if base in rest_grh and base not in {k for k, _ms in grh_bases.get(base, ())}:
            r_members += rest_grh[base]
        if not g_members or not r_members:
            continue
        for key, _ms in gsim_bases.get(base, ()):
            used_gsim.add(key)
        for key, _ms in grh_bases.get(base, ()):
            used_grh.add(key)
        if base in rest_gsim:
            used_gsim.add(base)
        if base in rest_grh:
            used_grh.add(base)
        groups.append({"key": base, "kind": "chunk_strip",
                       "gsim": sorted(g_members), "grhsim": sorted(r_members)})
    unmatched_gsim = {k: v for k, v in rest_gsim.items() if k not in used_gsim}
    unmatched_grh = {k: v for k, v in rest_grh.items() if k not in used_grh}
    return groups, unmatched_gsim, unmatched_grh


def bits_of(members):
    return sum(width for _name, width in members)


def match_report(groups, unmatched_gsim, unmatched_grh, gsim_total_bits,
                 grh_total_bits, other_side_gsim_keys=None,
                 other_side_grh_keys=None, sample_limit=15):
    """Bit-weighted coverage and reason-bucketed remainders."""
    gsim_matched_bits = sum(bits_of(g["gsim"]) for g in groups)
    grh_matched_bits = sum(bits_of(g["grhsim"]) for g in groups)
    gsim_matched_count = sum(len(g["gsim"]) for g in groups)
    grh_matched_count = sum(len(g["grhsim"]) for g in groups)

    def classify(key, other_keys):
        if "_RANDOM" in key:
            return "firtool_randomize_artifact"
        if "NEXT" in key:
            return "next_value_node"
        if "_bore" in key or "xmr" in key.lower():
            return "probe_signal"
        if "MPORT" in key:
            return "memory_port_node"
        if "PRINTF" in key or "assert" in key.lower():
            return "printf_assert_node"
        if other_keys is not None:
            base = strip_chunk_suffix(key)
            parts = key.split("_")
            for cut in range(len(parts) - 1, 0, -1):
                prefix = "_".join(parts[:cut])
                if prefix in other_keys or (base and base in other_keys):
                    return "renamed_or_split_within_module"
            return "module_path_absent_on_other_side"
        return "unclassified"

    def bucketize(unmatched, other_keys):
        buckets = defaultdict(lambda: {"count": 0, "bits": 0, "samples": []})
        for key in sorted(unmatched):
            members = unmatched[key]
            reason = classify(key, other_keys)
            bucket = buckets[reason]
            bucket["count"] += len(members)
            bucket["bits"] += bits_of(members)
            if len(bucket["samples"]) < sample_limit:
                bucket["samples"].append(sorted(members)[0][0])
        return {reason: buckets[reason] for reason in sorted(buckets)}

    return {
        "matched": {
            "groups": len(groups),
            "exactGroups": sum(1 for g in groups if g["kind"] == "exact"),
            "chunkStripGroups": sum(1 for g in groups if g["kind"] == "chunk_strip"),
            "gsimCount": gsim_matched_count,
            "grhsimCount": grh_matched_count,
            "gsimBits": gsim_matched_bits,
            "grhsimBits": grh_matched_bits,
        },
        "coverage": {
            "gsimBits": gsim_matched_bits / gsim_total_bits if gsim_total_bits else 0.0,
            "grhsimBits": grh_matched_bits / grh_total_bits if grh_total_bits else 0.0,
        },
        "totals": {
            "gsimBits": gsim_total_bits,
            "grhsimBits": grh_total_bits,
        },
        "unmatched": {
            "gsim": bucketize(unmatched_gsim, other_side_grh_keys),
            "grhsim": bucketize(unmatched_grh, other_side_gsim_keys),
        },
    }


# ---------------------------------------------------------------------------
# Bucket taxonomy (M-kinddelta)
# ---------------------------------------------------------------------------

def bucket_of_gsim_op(op):
    if op == "OP_EMPTY":
        return "node_ref"
    return GSIM_OP_BUCKETS.get(op, "other")


def bucket_of_grhsim_kind(kind):
    return GRHSIM_KIND_BUCKETS.get(kind, "other")


def ordered_bucket_counts(counter):
    out = {}
    for bucket in BUCKET_ORDER:
        if counter.get(bucket):
            out[bucket] = counter[bucket]
    for bucket in sorted(counter):
        if bucket not in out and counter[bucket]:
            out[bucket] = counter[bucket]
    return out


# ---------------------------------------------------------------------------
# Cone metrics (M-cone)
# ---------------------------------------------------------------------------

def grhsim_cone_size(start_vid, producer_of, op_operands, boundary):
    """Distinct producer ops in the backward cone, truncated at boundaries.

    boundary(vid) -> bool: named value or state.read/input.read/memRead
    result. Boundary values are not expanded and their producers are not
    counted; they are counted as leaves (gsim OP_EMPTY analog).
    Returns (cone_ops, boundary_leaves).
    """
    seen = set()
    leaves = 0
    stack = [start_vid]
    while stack:
        vid = stack.pop()
        if boundary(vid):
            leaves += 1
            continue
        producer = producer_of.get(vid)
        if producer is None:
            leaves += 1
            continue
        if producer in seen:
            continue
        seen.add(producer)
        stack.extend(op_operands[producer])
    return len(seen), leaves


def percentile(sorted_values, pct):
    """Nearest-rank percentile; sorted_values non-empty."""
    if not sorted_values:
        return None
    rank = max(1, round(pct * len(sorted_values) / 100.0))
    return sorted_values[min(rank, len(sorted_values)) - 1]


def distribution(values):
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "min": ordered[0],
        "p10": percentile(ordered, 10),
        "median": percentile(ordered, 50),
        "p90": percentile(ordered, 90),
        "p99": percentile(ordered, 99),
        "max": ordered[-1],
        "mean": sum(ordered) / len(ordered),
    }


# ---------------------------------------------------------------------------
# GrhSIM module attribution (M-opcount)
# ---------------------------------------------------------------------------

def merge_owners(lhs, rhs):
    """DEAD_MODULE (and the no-contribution None/"") is the identity (a
    dead-end or side-effect-only consumer does not change ownership);
    differing real modules merge to MIXED_MODULE."""
    if not rhs or rhs == DEAD_MODULE:
        return lhs
    if not lhs or lhs == DEAD_MODULE or lhs == rhs:
        return rhs
    return MIXED_MODULE


def propagate_value_owners(n_values, named_module_of, consumers_of, op_results,
                           sink_module_of=None):
    """Forward owner propagation over unnamed values (see module docstring).

    named_module_of(vid) -> module string or None for named values.
    consumers_of(vid) -> iterable of op positions consuming vid.
    op_results(pos) -> result value ids of an op.
    sink_module_of(pos) -> module for result-less sink ops (state writes):
        a value consumed by a regWrite/memWrite inherits the written state's
        module, mirroring gsim where the REG_DST tree belongs to the
        register's own module. None for side-effect-only ops (printf/dpi).
    Returns list owner[vid] (module, MIXED_MODULE or DEAD_MODULE).
    """
    in_progress = object()
    owner = [None] * (n_values + 1)
    for start in range(1, n_values + 1):
        if owner[start] is not None:
            continue
        stack = [(start, False)]
        while stack:
            vid, expanded = stack.pop()
            current = owner[vid]
            if current is not None and current is not in_progress:
                continue
            named = named_module_of(vid)
            if named is not None:
                owner[vid] = named
                continue
            if not expanded:
                owner[vid] = in_progress
                stack.append((vid, True))
                for pos in consumers_of(vid):
                    for res in op_results(pos):
                        if owner[res] is None:
                            stack.append((res, False))
            else:
                acc = DEAD_MODULE
                for pos in consumers_of(vid):
                    results = op_results(pos)
                    if not results and sink_module_of is not None:
                        sink = sink_module_of(pos)
                        if sink is not None:
                            acc = merge_owners(acc, sink)
                    for res in results:
                        res_owner = owner[res]
                        if res_owner is None or res_owner is in_progress:
                            res_owner = DEAD_MODULE
                        acc = merge_owners(acc, res_owner)
                owner[vid] = acc
    return owner


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def check_grhsim_counts(model):
    """G1a (GrhSIM half): counts section vs actual payload sizes."""
    checks = {}
    counts = model["counts"]
    arrays = {
        "strings": len(model["strings"]),
        "dialects": len(model["dialects"]),
        "types": len(model["types"]),
        "origins": len(model["origins"]),
        "inputs": len(model["inputs"]),
        "outputs": len(model["outputs"]),
        "states": len(model["states"]),
        "functions": len(model["functions"]),
        "interface_ports": len(model["interface"]),
        "values": len(model["values"]),
        "operations": len(model["operations"]),
        "mappings": len(model["mappings"]),
    }
    for key, actual in sorted(arrays.items()):
        checks[key] = {"expected": counts.get(key), "actual": actual,
                       "ok": counts.get(key) == actual}
    operands = sum(len(op[4]) for op in model["operations"])
    results = sum(len(op[5]) for op in model["operations"])
    refs = sum(len(op[6]) for op in model["operations"])
    checks["operands"] = {"expected": counts.get("operands"), "actual": operands,
                          "ok": counts.get("operands") == operands}
    checks["results"] = {"expected": counts.get("results"), "actual": results,
                         "ok": counts.get("results") == results}
    checks["object_refs"] = {"expected": counts.get("object_refs"), "actual": refs,
                             "ok": counts.get("object_refs") == refs}
    dense_states = all(row[0] == i + 1 for i, row in enumerate(model["states"]))
    dense_values = all(row[0] == i + 1 for i, row in enumerate(model["values"]))
    dense_ops = all(row[0] == i + 1 for i, row in enumerate(model["operations"]))
    checks["dense_ids"] = {"states": dense_states, "values": dense_values,
                           "operations": dense_ops,
                           "ok": dense_states and dense_values and dense_ops}
    ok = all(entry.get("ok", False) for entry in checks.values())
    return ok, checks


def op_kind_counter(model):
    strings = model["strings"]
    counter = Counter()
    for op in model["operations"]:
        counter[strings[op[1] - 1]] += 1
    return counter


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 26), b""):
            digest.update(chunk)
    return digest.hexdigest()


DIFF_ARRAY_ORDER = [
    "strings", "types", "origins", "inputs", "outputs", "states",
    "functions", "interface", "values", "operations", "init", "mappings",
]


def diff_row_samples(rows_a, rows_b, limit=3, width=220):
    samples = []
    for row_a, row_b in zip(rows_a, rows_b):
        if row_a == row_b:
            continue
        samples.append({"a": repr(row_a)[:width], "b": repr(row_b)[:width]})
        if len(samples) >= limit:
            break
    return samples


def diff_checkpoints(model_a, model_b, sample_limit=3):
    """Structured diff of two GrhSIM checkpoints: counts, then per-array
    first-difference localization with samples, plus origin-only tests on
    values/operations/states (rows equal once origin fields are dropped)."""
    report = {"countsEqual": model_a["counts"] == model_b["counts"],
              "arrays": {}}
    for key in DIFF_ARRAY_ORDER:
        rows_a = model_a.get(key)
        rows_b = model_b.get(key)
        if rows_a is None or rows_b is None:
            continue
        entry = {"lenA": len(rows_a), "lenB": len(rows_b),
                 "equal": rows_a == rows_b}
        if not entry["equal"] and len(rows_a) == len(rows_b):
            first = next(i for i in range(len(rows_a)) if rows_a[i] != rows_b[i])
            entry["firstDiffIndex"] = first
            entry["diffRowCount"] = sum(1 for x, y in zip(rows_a, rows_b) if x != y)
            entry["samples"] = diff_row_samples(rows_a[first:first + 4000],
                                                rows_b[first:first + 4000],
                                                limit=sample_limit)
        report["arrays"][key] = entry

    def origin_only(key, origin_field):
        rows_a, rows_b = model_a[key], model_b[key]
        if len(rows_a) != len(rows_b):
            return None
        stripped_diff = 0
        for row_a, row_b in zip(rows_a, rows_b):
            if row_a[:origin_field] + row_a[origin_field + 1:] != \
               row_b[:origin_field] + row_b[origin_field + 1:]:
                stripped_diff += 1
        return stripped_diff

    report["nonOriginDiffRows"] = {
        "states": origin_only("states", 3),
        "values": origin_only("values", 3),
        "operations": origin_only("operations", 3),
    }
    differing = [key for key in DIFF_ARRAY_ORDER
                 if key in report["arrays"] and not report["arrays"][key]["equal"]]
    report["differingArrays"] = differing
    non_origin = report["nonOriginDiffRows"]
    strings_differ = not report["arrays"].get("strings", {}).get("equal", True)
    if not differing:
        report["classification"] = "identical_payload"
    elif strings_differ:
        # String-id fields downstream are meaningless once the shared string
        # table drifts; report the table itself as the primary difference.
        report["classification"] = "string_table_content_drift"
    elif all(value == 0 for value in non_origin.values() if value is not None):
        report["classification"] = "origin_or_string_embedding_only"
    else:
        report["classification"] = "structural_payload_drift"
    return report


# ---------------------------------------------------------------------------
# gsim side loading and reduction
# ---------------------------------------------------------------------------

def analyze_gsim(path, expect_nodes):
    """Single pass over the gsim PreCoarsen export. Returns a compact
    summary dict; the raw multi-GB JSON tree is released by the caller."""
    log(f"gsim: loading {path}")
    payload = json.loads(Path(path).read_bytes())
    nodes = payload["nodes"]
    log(f"gsim: parsed {len(nodes)} node records")

    summary = {
        "nodeCount": len(nodes),
        "typeCounts": Counter(),
        "moduleNodeCounts": Counter(),
        "moduleEnodeCounts": Counter(),
        "moduleOpCounts": Counter(),       # (module, enode op) -> n
        "globalOpCounts": Counter(),
        "totalEnodes": 0,
        "regSrc": [],                      # (name, width, dst_name|None)
        "regDstEnodes": {},                # dst name -> enode count
        "memories": [],                    # NODE_MEMORY names
        "inputs": [],
        "outputs": [],
        "treeChecks": {"badChildRef": 0, "badRootRef": 0, "trees": 0},
        "regSrcLink": Counter(),
    }
    interned_modules = {}

    def module_key(raw):
        key = interned_modules.get(raw)
        if key is None:
            key = module_of_path(raw, "__DOT__")
            interned_modules[raw] = key
        return key

    for node in nodes:
        name = node["name"]
        ntype = node["type"]
        summary["typeCounts"][ntype] += 1
        module = module_key(name)
        summary["moduleNodeCounts"][module] += 1
        enode_count = 0
        dst_ref = None
        for tree in node.get("assignTrees") or ():
            flat = tree["nodes"]
            enode_count += len(flat)
            summary["treeChecks"]["trees"] += 1
            root = tree.get("root", -1)
            if not 0 <= root < len(flat):
                summary["treeChecks"]["badRootRef"] += 1
            for enode in flat:
                op = enode["op"]
                summary["globalOpCounts"][op] += 1
                summary["moduleOpCounts"][(module, op)] += 1
                for child in enode.get("children") or ():
                    if not 0 <= child < len(flat):
                        summary["treeChecks"]["badChildRef"] += 1
            if ntype == "NODE_REG_SRC" and dst_ref is None and 0 <= root < len(flat):
                ref = flat[root].get("node")
                if isinstance(ref, str) and ref and ref != name:
                    dst_ref = ref
        summary["moduleEnodeCounts"][module] += enode_count
        summary["totalEnodes"] += enode_count
        if ntype == "NODE_REG_SRC":
            summary["regSrc"].append((name, node.get("width", 0), dst_ref))
        elif ntype == "NODE_REG_DST":
            summary["regDstEnodes"][name] = summary["regDstEnodes"].get(name, 0) + enode_count
        elif ntype == "NODE_MEMORY":
            summary["memories"].append(name)
        elif ntype == "NODE_INP":
            summary["inputs"].append(name)
        elif ntype == "NODE_OUT":
            summary["outputs"].append(name)
    del payload, nodes

    summary["typeCounts"] = dict(sorted(summary["typeCounts"].items()))
    non_memory = summary["nodeCount"] - summary["typeCounts"].get("NODE_MEMORY", 0)
    summary["nonMemoryNodeCount"] = non_memory
    summary["closure"] = {
        "expectNodes": expect_nodes,
        "nonMemoryOk": non_memory == expect_nodes,
        "moduleNodeSum": sum(summary["moduleNodeCounts"].values()),
        "moduleEnodeSum": sum(summary["moduleEnodeCounts"].values()),
        "globalOpSum": sum(summary["globalOpCounts"].values()),
    }
    summary["closure"]["nodesOk"] = summary["closure"]["moduleNodeSum"] == summary["nodeCount"]
    summary["closure"]["enodesOk"] = (
        summary["closure"]["moduleEnodeSum"] == summary["totalEnodes"]
        == summary["closure"]["globalOpSum"])
    summary["closure"]["treeRefsOk"] = (
        summary["treeChecks"]["badChildRef"] == 0
        and summary["treeChecks"]["badRootRef"] == 0)
    return summary


def gsim_reg_cones(summary):
    """Map REG_SRC name -> update-expression ENode count via its REG_DST."""
    cones = {}
    link = Counter()
    for name, _width, dst in summary["regSrc"]:
        if dst is None:
            link["no_dst_ref"] += 1
            continue
        cone = summary["regDstEnodes"].get(dst)
        if cone is None:
            link["dst_missing"] += 1
            continue
        cones[name] = cone
        link["dst_linked"] += 1
    return cones, link


# ---------------------------------------------------------------------------
# GrhSIM side loading and reduction
# ---------------------------------------------------------------------------

def analyze_grhsim(path):
    """Single pass over the GrhSIM pre-partition dump. Returns a compact
    summary dict; the raw JSON tree is released inside."""
    log(f"grhsim: loading {path}")
    model = json.loads(Path(path).read_bytes())
    strings = model["strings"]
    types = {row[0]: row for row in model["types"]}
    log(f"grhsim: parsed states={len(model['states'])} values={len(model['values'])} "
        f"ops={len(model['operations'])}")

    counts_ok, counts_checks = check_grhsim_counts(model)

    state_name = [""] * (len(model["states"]) + 1)
    state_width = [0] * (len(model["states"]) + 1)
    state_is_array = [False] * (len(model["states"]) + 1)
    for row in model["states"]:
        sid, name_idx, type_idx = row[0], row[1], row[2]
        trow = types[type_idx]
        state_name[sid] = strings[name_idx - 1]
        state_is_array[sid] = trow[2] == "array"
        state_width[sid] = trow[3] if trow[2] == "logic" else 0

    n_values = len(model["values"])
    value_name = [""] * (n_values + 1)
    for row in model["values"]:
        value_name[row[0]] = strings[row[2] - 1] if row[2] else ""

    n_ops = len(model["operations"])
    op_kind = [""] * (n_ops + 1)
    op_operands = [None] * (n_ops + 1)
    op_results = [None] * (n_ops + 1)
    op_refs = [None] * (n_ops + 1)
    producer_of = {}
    for pos, op in enumerate(model["operations"]):
        oid = op[0]
        op_kind[oid] = strings[op[1] - 1]
        op_operands[oid] = op[4]
        op_results[oid] = op[5]
        op_refs[oid] = op[6]
        for res in op[5]:
            producer_of[res] = oid

    inputs = [strings[row[1] - 1] for row in model["inputs"]]
    outputs = [strings[row[1] - 1] for row in model["outputs"]]
    model_counts = model["counts"]
    del model

    # Named-boundary classification of values.
    value_named_module = [None] * (n_values + 1)
    other_patterns = Counter()
    for vid in range(1, n_values + 1):
        name = value_name[vid]
        if not is_generated_value_name(name):
            value_named_module[vid] = module_of_state_name(name)
            if "$" not in name:
                other_patterns[re.sub(r"\d+", "N", name)] += 1
    io_names = {index + 1: name for index, name in enumerate(inputs)}
    for pos in range(1, n_ops + 1):
        if op_kind[pos] in STATE_READ_KINDS:
            for res in op_results[pos]:
                if value_named_module[res] is None:
                    ref = op_refs[pos][0] if op_refs[pos] else None
                    target_module = None
                    if isinstance(ref, list) and len(ref) >= 2 and isinstance(ref[1], int):
                        if ref[0] == "state" and 0 < ref[1] < len(state_name):
                            target_module = module_of_state_name(state_name[ref[1]])
                        elif ref[0] == "input" and ref[1] in io_names:
                            target_module = module_of_path(io_names[ref[1]], "$")
                    if target_module is None:
                        target_module = module_of_path(value_name[res], "$")
                    value_named_module[res] = target_module

    # consumers map for owner propagation
    log("grhsim: building consumers map")
    consumers_of = defaultdict(list)
    for pos in range(1, n_ops + 1):
        for operand in op_operands[pos]:
            consumers_of[operand].append(pos)

    io_names.update({index + 1: name for index, name in enumerate(outputs)})

    def sink_module_of(pos):
        """Module of a result-less op's written object (state writes, output
        writes); pass-artifact states bucket via module_of_state_name."""
        for ref in op_refs[pos] or ():
            if not isinstance(ref, list) or len(ref) < 2 or not isinstance(ref[1], int):
                continue
            if ref[0] == "state" and 0 < ref[1] < len(state_name):
                return module_of_state_name(state_name[ref[1]])
            if ref[0] in ("input", "output") and ref[1] in io_names:
                return module_of_path(io_names[ref[1]], "$")
        return None

    log("grhsim: propagating value owners")
    owner = propagate_value_owners(
        n_values,
        lambda vid: value_named_module[vid],
        lambda vid: consumers_of.get(vid, ()),
        lambda pos: op_results[pos],
        sink_module_of=sink_module_of,
    )

    # Per-module op/value counts and kind census.
    log("grhsim: assigning op modules")
    module_op_counts = Counter()
    module_value_counts = Counter()
    module_kind_counts = Counter()   # (module, kind) -> n
    global_kind_counts = Counter()
    anon_kind_counts = Counter()
    for pos in range(1, n_ops + 1):
        kind = op_kind[pos]
        global_kind_counts[kind] += 1
        module = None
        for res in op_results[pos]:
            named = value_named_module[res]
            if named is not None:
                module = named
                break
        if module is None:
            for ref in op_refs[pos] or ():
                if isinstance(ref, list) and len(ref) >= 2 and ref[0] == "state" \
                        and isinstance(ref[1], int) and 0 < ref[1] < len(state_name):
                    module = module_of_state_name(state_name[ref[1]])
                    break
        if module is None:
            for res in op_results[pos]:
                module = owner[res]
                if module:
                    break
        if module is None or module == DEAD_MODULE:
            for operand in op_operands[pos]:
                named = value_named_module[operand]
                if named is not None:
                    module = named
                    break
        if not module:
            module = ANON_MODULE
            anon_kind_counts[kind] += 1
        module_op_counts[module] += 1
        module_kind_counts[(module, kind)] += 1

    for vid in range(1, n_values + 1):
        named = value_named_module[vid]
        module_value_counts[named if named is not None else owner[vid] or ANON_MODULE] += 1

    # Register cones from regWrite nextValue operands.
    log("grhsim: computing register cones")
    boundary_set = bytearray(n_values + 1)
    for vid in range(1, n_values + 1):
        if value_named_module[vid] is not None:
            boundary_set[vid] = 1
    state_cones = {}
    cone_link = Counter()
    for pos in range(1, n_ops + 1):
        if op_kind[pos] != REG_WRITE_KIND:
            continue
        refs = op_refs[pos] or ()
        sid = None
        for ref in refs:
            if isinstance(ref, list) and len(ref) >= 2 and ref[0] == "state" \
                    and isinstance(ref[1], int):
                sid = ref[1]
                break
        if sid is None or not (0 < sid < len(state_name)):
            cone_link["no_state_ref"] += 1
            continue
        operands = op_operands[pos]
        if len(operands) < 2:
            cone_link["no_next_operand"] += 1
            continue
        cone, leaves = grhsim_cone_size(
            operands[1], producer_of, op_operands, lambda vid: boundary_set[vid])
        if sid in state_cones:
            cone_link["duplicate_writer"] += 1
            prev_ops, prev_leaves = state_cones[sid]
            state_cones[sid] = (prev_ops + cone, prev_leaves + leaves)
        else:
            state_cones[sid] = (cone, leaves)
            cone_link["ok"] += 1

    summary = {
        "countsOk": counts_ok,
        "countsChecks": counts_checks,
        "counts": model_counts,
        "inputs": inputs,
        "outputs": outputs,
        "logicStates": [(state_name[sid], state_width[sid])
                        for sid in range(1, len(state_name)) if not state_is_array[sid]],
        # 寄存器类锚点: logic-type states excluding __event_ edge bookkeeping
        "registerStates": [(state_name[sid], state_width[sid])
                           for sid in range(1, len(state_name))
                           if not state_is_array[sid]
                           and not state_name[sid].startswith("__event_")],
        "eventStateCount": sum(1 for sid in range(1, len(state_name))
                               if not state_is_array[sid]
                               and state_name[sid].startswith("__event_")),
        "eventStateBits": sum(state_width[sid] for sid in range(1, len(state_name))
                              if not state_is_array[sid]
                              and state_name[sid].startswith("__event_")),
        "arrayStates": [state_name[sid] for sid in range(1, len(state_name))
                        if state_is_array[sid]],
        "stateCones": {state_name[sid]: state_cones[sid] for sid in state_cones},
        "coneLink": dict(cone_link),
        "moduleOpCounts": dict(module_op_counts),
        "moduleValueCounts": dict(module_value_counts),
        "moduleKindCounts": {module + MODULE_KIND_SEP + kind: count
                             for (module, kind), count in module_kind_counts.items()},
        "globalKindCounts": dict(global_kind_counts),
        "anonymousOpKinds": dict(anon_kind_counts),
        "otherValueNamePatterns": dict(other_patterns.most_common(40)),
        "valueOwnerStats": dict(Counter(
            "named" if value_named_module[vid] is not None
            else (owner[vid] or ANON_MODULE) for vid in range(1, n_values + 1))),
        "totalOps": n_ops,
        "totalValues": n_values,
    }
    return summary


# ---------------------------------------------------------------------------
# Metric assembly
# ---------------------------------------------------------------------------

def assemble_opcount(gsim, grhsim, top_n):
    modules = sorted(set(gsim["moduleNodeCounts"]) | set(grhsim["moduleOpCounts"]))
    rows = []
    for module in modules:
        g_nodes = gsim["moduleNodeCounts"].get(module, 0)
        g_enodes = gsim["moduleEnodeCounts"].get(module, 0)
        r_ops = grhsim["moduleOpCounts"].get(module, 0)
        r_values = grhsim["moduleValueCounts"].get(module, 0)
        rows.append({
            "module": module,
            "gsimNodes": g_nodes,
            "gsimEnodes": g_enodes,
            "grhsimOps": r_ops,
            "grhsimValues": r_values,
            "enodePerOp": round(g_enodes / r_ops, 4) if r_ops else None,
            "opDelta": r_ops - g_enodes,
        })
    by_delta = sorted(rows, key=lambda row: (-abs(row["opDelta"]), row["module"]))
    closure = {
        "gsimNodes": sum(row["gsimNodes"] for row in rows) == gsim["nodeCount"],
        "gsimEnodes": sum(row["gsimEnodes"] for row in rows) == gsim["totalEnodes"],
        "grhsimOps": sum(row["grhsimOps"] for row in rows) == grhsim["totalOps"],
        "grhsimValues": sum(row["grhsimValues"] for row in rows) == grhsim["totalValues"],
    }
    return {
        "moduleCount": len(rows),
        "closure": closure,
        "closureOk": all(closure.values()),
        "totals": {
            "gsimNodes": gsim["nodeCount"],
            "gsimEnodes": gsim["totalEnodes"],
            "grhsimOps": grhsim["totalOps"],
            "grhsimValues": grhsim["totalValues"],
            "enodePerOp": round(gsim["totalEnodes"] / grhsim["totalOps"], 4)
            if grhsim["totalOps"] else None,
        },
        "topByAbsDelta": by_delta[:top_n],
        "topByGrhsimOps": sorted(rows, key=lambda row: (-row["grhsimOps"], row["module"]))[:top_n],
    }


def assemble_kinddelta(gsim, grhsim, top_n):
    gsim_buckets = Counter()
    for op, count in gsim["globalOpCounts"].items():
        gsim_buckets[bucket_of_gsim_op(op)] += count
    grh_buckets = Counter()
    for kind, count in grhsim["globalKindCounts"].items():
        grh_buckets[bucket_of_grhsim_kind(kind)] += count
    table = []
    for bucket in BUCKET_ORDER:
        g = gsim_buckets.get(bucket, 0)
        r = grh_buckets.get(bucket, 0)
        if g or r:
            table.append({"bucket": bucket, "gsim": g, "grhsim": r,
                          "grhsimMinusGsim": r - g})
    unmapped_gsim = sorted(op for op in gsim["globalOpCounts"]
                           if bucket_of_gsim_op(op) == "other")
    unmapped_grh = sorted(kind for kind in grhsim["globalKindCounts"]
                          if bucket_of_grhsim_kind(kind) == "other")

    # Per-module deltas: gsim (module, op) + grhsim (module, kind) -> buckets.
    module_delta = defaultdict(Counter)
    for (module, op), count in gsim["moduleOpCounts"].items():
        module_delta[module][bucket_of_gsim_op(op)] -= count
    for key, count in grhsim["moduleKindCounts"].items():
        module, kind = key.split(MODULE_KIND_SEP, 1)
        module_delta[module][bucket_of_grhsim_kind(kind)] += count
    module_scores = sorted(
        ((sum(abs(v) for v in counter.values()), module) for module, counter in module_delta.items()),
        key=lambda item: (-item[0], item[1]))
    top_modules = []
    for _score, module in module_scores[:top_n]:
        counter = module_delta[module]
        top_modules.append({
            "module": module,
            "absDelta": sum(abs(v) for v in counter.values()),
            "buckets": {bucket: counter[bucket] for bucket in BUCKET_ORDER if counter.get(bucket)},
        })
    excess_order = sorted(table, key=lambda row: (-row["grhsimMinusGsim"], row["bucket"]))
    return {
        "global": table,
        "excessOrder": [{"bucket": row["bucket"], "grhsimMinusGsim": row["grhsimMinusGsim"]}
                        for row in excess_order],
        "unmappedGsimOps": unmapped_gsim,
        "unmappedGrhsimKinds": unmapped_grh,
        "topModules": top_modules,
    }


def assemble_cone(groups, gsim_cones, grh_state_cones, top_n):
    rows = []
    misses = Counter()
    for group in groups:
        g_total = 0
        g_ok = True
        for name, _width in group["gsim"]:
            cone = gsim_cones.get(name)
            if cone is None:
                misses["gsim_cone_missing"] += 1
                g_ok = False
                break
            g_total += cone
        if not g_ok:
            continue
        r_total = 0
        r_leaves = 0
        r_ok = True
        for name, _width in group["grhsim"]:
            cone = grh_state_cones.get(name)
            if cone is None:
                misses["grhsim_cone_missing"] += 1
                r_ok = False
                break
            r_total += cone[0]
            r_leaves += cone[1]
        if not r_ok:
            continue
        rows.append({"key": group["key"], "kind": group["kind"],
                     "gsimCone": g_total, "grhsimCone": r_total,
                     "grhsimBoundaryLeaves": r_leaves,
                     "gsimMembers": len(group["gsim"]),
                     "grhsimMembers": len(group["grhsim"])})
    ratios = [row["grhsimCone"] / row["gsimCone"] for row in rows if row["gsimCone"] > 0]
    sizes_gsim = [row["gsimCone"] for row in rows]
    sizes_grh = [row["grhsimCone"] for row in rows]
    outliers = sorted((row for row in rows if row["gsimCone"] > 0),
                      key=lambda row: (-(row["grhsimCone"] / row["gsimCone"]), row["key"]))[:top_n]
    return {
        "pairs": len(rows),
        "misses": dict(misses),
        "gsimConeSize": distribution(sizes_gsim),
        "grhsimConeSize": distribution(sizes_grh),
        "ratioGrhsimOverGsim": distribution([round(r, 6) for r in ratios]),
        "outliers": outliers,
    }


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def render_summary(report):
    lines = []
    gates = report["gates"]
    lines.append("# NO00020 gsim vs GrhSIM unpartitioned IR module comparison")
    lines.append("")
    lines.append("## Gates")
    for gid in ["G1a", "G1b", "G1c", "G2", "G3", "G4"]:
        gate = gates[gid]
        verdict = {True: "PASS", False: "FAIL", None: "N/A"}[gate["pass"]]
        lines.append(f"- {gid}: {verdict} — {gate['summary']}")
    lines.append("")
    m_name = report["metrics"]["M-name"]
    lines.append("## M-name (register anchors)")
    cov = m_name["coverage"]
    lines.append(f"- bit-weighted coverage: gsim {cov['gsimBits'] * 100:.2f}% "
                 f"({m_name['matched']['gsimBits']}/{m_name['totals']['gsimBits']} bits), "
                 f"grhsim {cov['grhsimBits'] * 100:.2f}% "
                 f"({m_name['matched']['grhsimBits']}/{m_name['totals']['grhsimBits']} bits)")
    lines.append(f"- matched groups: {m_name['matched']['groups']} "
                 f"(exact {m_name['matched']['exactGroups']}, "
                 f"chunk-strip {m_name['matched']['chunkStripGroups']}); "
                 f"gsim regs {m_name['matched']['gsimCount']}, grhsim states "
                 f"{m_name['matched']['grhsimCount']}")
    lines.append("- unmatched buckets (gsim side): " +
                 ", ".join(f"{k}={v['count']}" for k, v in m_name["unmatched"]["gsim"].items()))
    lines.append("- unmatched buckets (grhsim side): " +
                 ", ".join(f"{k}={v['count']}" for k, v in m_name["unmatched"]["grhsim"].items()))
    lines.append("")
    m_opc = report["metrics"]["M-opcount"]
    lines.append("## M-opcount (per-module totals)")
    totals = m_opc["totals"]
    lines.append(f"- gsim nodes {totals['gsimNodes']}, gsim enodes {totals['gsimEnodes']}, "
                 f"grhsim ops {totals['grhsimOps']}, grhsim values {totals['grhsimValues']}, "
                 f"enode/op {totals['enodePerOp']}")
    lines.append(f"- modules: {m_opc['moduleCount']}, closure ok: {m_opc['closureOk']}")
    lines.append("- top modules by |op delta|:")
    for row in m_opc["topByAbsDelta"][:10]:
        lines.append(f"  - {row['module']}: gsim_enodes={row['gsimEnodes']} "
                     f"grhsim_ops={row['grhsimOps']} delta={row['opDelta']}")
    lines.append("")
    m_kd = report["metrics"]["M-kinddelta"]
    lines.append("## M-kinddelta (bucket composition)")
    for row in m_kd["global"]:
        lines.append(f"- {row['bucket']}: gsim={row['gsim']} grhsim={row['grhsim']} "
                     f"delta={row['grhsimMinusGsim']}")
    lines.append("")
    m_cone = report["metrics"]["M-cone"]
    lines.append("## M-cone (register update expression size)")
    lines.append(f"- paired groups: {m_cone['pairs']}, misses: {m_cone['misses']}")
    ratio = m_cone["ratioGrhsimOverGsim"]
    if ratio.get("n"):
        lines.append(f"- grhsim/gsim cone ratio: median={ratio['median']:.4f} "
                     f"p90={ratio['p90']:.4f} mean={ratio['mean']:.4f}")
    lines.append(f"- gsim cone sizes: {m_cone['gsimConeSize']}")
    lines.append(f"- grhsim cone sizes: {m_cone['grhsimConeSize']}")
    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gsim-json", type=Path, required=True)
    parser.add_argument("--grhsim-pre", type=Path, required=True)
    parser.add_argument("--grhsim-final", type=Path, required=True)
    parser.add_argument("--grhsim-full", type=Path, required=True)
    parser.add_argument("--grhsim-archive", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--top-n", type=int, default=25)
    parser.add_argument("--gsim-expect-nodes", type=int, default=2708079)
    parser.add_argument("--g2-reference", type=Path)
    args = parser.parse_args(argv)

    t0 = time.time()
    # ---- Phase A: gsim ----
    gsim = analyze_gsim(args.gsim_json, args.gsim_expect_nodes)
    gsim_cones, gsim_cone_link = gsim_reg_cones(gsim)
    log(f"gsim: reduced in {time.time() - t0:.1f}s; reg cone links {dict(gsim_cone_link)}")

    # ---- Phase B: GrhSIM pre-partition ----
    grhsim = analyze_grhsim(args.grhsim_pre)
    log(f"grhsim: reduced; cone link {grhsim['coneLink']}")

    # ---- M-name ----
    # 锚点口径: GrhSIM 寄存器类 states = logic-type 且非 __event_ 边沿簿记
    # (event states are excluded from the anchor set; both calibers reported).
    gsim_regs = [(name, width) for name, width, _dst in gsim["regSrc"]]
    groups, unmatched_gsim, unmatched_grh = match_anchor_sets(
        gsim_regs, grhsim["registerStates"])
    gsim_total_bits = sum(width for _name, width in gsim_regs)
    grh_total_bits = sum(width for _name, width in grhsim["registerStates"])
    m_name = match_report(
        groups, unmatched_gsim, unmatched_grh, gsim_total_bits, grh_total_bits,
        other_side_gsim_keys={normalize_name(n) for n, _w in gsim_regs},
        other_side_grh_keys={normalize_name(n) for n, _w in grhsim["registerStates"]})
    m_name["gsimRegCount"] = len(gsim_regs)
    m_name["grhsimRegisterStateCount"] = len(grhsim["registerStates"])
    m_name["grhsimEventStatesExcluded"] = {
        "count": grhsim["eventStateCount"], "bits": grhsim["eventStateBits"]}
    # reference caliber including event states in the denominator
    logic_groups, _lg, _lr = match_anchor_sets(gsim_regs, grhsim["logicStates"])
    logic_total = sum(width for _name, width in grhsim["logicStates"])
    m_name["referenceCaliberIncludingEventStates"] = {
        "grhsimBitsTotal": logic_total,
        "grhsimBitsMatched": sum(bits_of(g["grhsim"]) for g in logic_groups),
        "grhsimCoverage": (sum(bits_of(g["grhsim"]) for g in logic_groups) / logic_total
                           if logic_total else 0.0),
    }
    log(f"M-name: coverage gsim={m_name['coverage']['gsimBits']:.4f} "
        f"grhsim={m_name['coverage']['grhsimBits']:.4f}")

    # ---- G4 anchors ----
    mem_groups, mem_un_g, mem_un_r = match_anchor_sets(
        [(name, 1) for name in gsim["memories"]],
        [(strip_mem_wrapper(name), 1) for name in grhsim["arrayStates"]])
    io_gsim = [(name, 1) for name in gsim["inputs"] + gsim["outputs"]]
    io_grh = [(name, 1) for name in grhsim["inputs"] + grhsim["outputs"]]
    io_groups, io_un_g, io_un_r = match_anchor_sets(io_gsim, io_grh)

    def g4_items(unmatched, side):
        return [{"side": side, "name": members[0][0]}
                for _key, members in sorted(unmatched.items())]

    g4 = {
        "memory": {
            "gsimCount": len(gsim["memories"]),
            "grhsimCount": len(grhsim["arrayStates"]),
            "pairedGroups": len(mem_groups),
            "unpaired": g4_items(mem_un_g, "gsim") + g4_items(mem_un_r, "grhsim"),
        },
        "io": {
            "gsim": sorted(gsim["inputs"] + gsim["outputs"]),
            "grhsim": sorted(grhsim["inputs"] + grhsim["outputs"]),
            "pairedGroups": len(io_groups),
            "unpaired": g4_items(io_un_g, "gsim") + g4_items(io_un_r, "grhsim"),
        },
    }

    def attribute_g4(unpaired, other_side_names):
        normalized_others = sorted({normalize_name(name) for name in other_side_names})
        attributed = []
        for item in unpaired:
            key = normalize_name(item["name"])
            reason = "renamed_or_split"
            stripped = key.lstrip("_")
            if "_RANDOM" in key:
                reason = "firtool_randomize_artifact"
            elif stripped.startswith("reg_to_mem_"):
                reason = "grhsim_reg_to_mem_pass_product"
            elif stripped.startswith("event_"):
                reason = "edge_event_bookkeeping"
            elif not any(key.startswith(other + "_") or other.startswith(key + "_")
                         for other in normalized_others):
                reason = "no_name_overlap_on_other_side"
            attributed.append({**item, "reason": reason})
        return attributed

    g4["memory"]["grhsimWrapperRule"] = "strip trailing `_ext$Memory` (firtool memory wrapper)"
    g4["memory"]["attributedUnpaired"] = attribute_g4(
        g4["memory"]["unpaired"],
        list(gsim["memories"]) + [strip_mem_wrapper(n) for n in grhsim["arrayStates"]])
    g4["io"]["attributedUnpaired"] = attribute_g4(
        g4["io"]["unpaired"],
        [n for n, _w in io_gsim] + [n for n, _w in io_grh])
    g4_pass = all(item.get("reason") for item in g4["memory"]["attributedUnpaired"]) \
        and all(item.get("reason") for item in g4["io"]["attributedUnpaired"])

    # ---- M-opcount / M-kinddelta / M-cone ----
    log("assembling M-opcount / M-kinddelta / M-cone")
    m_opcount = assemble_opcount(gsim, grhsim, args.top_n)
    m_kinddelta = assemble_kinddelta(gsim, grhsim, args.top_n)
    m_cone = assemble_cone(groups, gsim_cones, grhsim["stateCones"], args.top_n)

    # ---- G1b: pre-partition vs final op-kind multiset ----
    log("G1b: loading final checkpoint")
    final_model = json.loads(args.grhsim_final.read_bytes())
    final_kinds = op_kind_counter(final_model)
    pre_kinds = Counter(grhsim["globalKindCounts"])
    g1b_diff = {kind: [pre_kinds.get(kind, 0), final_kinds.get(kind, 0)]
                for kind in sorted(set(pre_kinds) | set(final_kinds))
                if pre_kinds.get(kind, 0) != final_kinds.get(kind, 0)}
    g1b_pass = not g1b_diff

    # ---- G1c: byte compare + structured diff ----
    log("G1c: hashing checkpoints")
    hashes = {
        "final": sha256_of(args.grhsim_final),
        "full": sha256_of(args.grhsim_full),
        "archive": sha256_of(args.grhsim_archive),
    }
    g1c = {"sha256": hashes,
           "byteEqual": {
               "final_vs_full": hashes["final"] == hashes["full"],
               "final_vs_archive": hashes["final"] == hashes["archive"],
               "full_vs_archive": hashes["full"] == hashes["archive"],
           }}
    diffs = {}
    if not g1c["byteEqual"]["final_vs_full"]:
        log("G1c: structured diff final vs full")
        full_model = json.loads(args.grhsim_full.read_bytes())
        diffs["final_vs_full"] = diff_checkpoints(final_model, full_model)
        del full_model
    if not g1c["byteEqual"]["final_vs_archive"]:
        log("G1c: structured diff final vs archive")
        archive_model = json.loads(args.grhsim_archive.read_bytes())
        diffs["final_vs_archive"] = diff_checkpoints(final_model, archive_model)
        del archive_model
    del final_model
    g1c["structuredDiff"] = diffs
    g1c_pass = all(g1c["byteEqual"].values())

    # ---- Gates ----
    gsim_closure = gsim["closure"]
    g1a_pass = (gsim_closure["nonMemoryOk"] and gsim_closure["nodesOk"]
                and gsim_closure["enodesOk"] and gsim_closure["treeRefsOk"]
                and grhsim["countsOk"])
    cov = m_name["coverage"]
    g3_pass = cov["gsimBits"] >= 0.8 and cov["grhsimBits"] >= 0.8
    gates = {
        "G1a": {"pass": g1a_pass,
                "summary": f"gsim nodes {gsim['nonMemoryNodeCount']}=={gsim_closure['expectNodes']} "
                           f"(+{gsim['typeCounts'].get('NODE_MEMORY', 0)} memory), "
                           f"tree refs ok={gsim_closure['treeRefsOk']}, grhsim counts ok={grhsim['countsOk']}",
                "gsim": gsim_closure,
                "grhsim": grhsim["countsChecks"]},
        "G1b": {"pass": g1b_pass,
                "summary": f"pre-partition vs final op-kind multiset diff: {len(g1b_diff)} kinds",
                "kindDiffs": g1b_diff},
        "G1c": {"pass": g1c_pass,
                "summary": "byte equality: " + ", ".join(
                    f"{pair}={equal}" for pair, equal in g1c["byteEqual"].items()),
                "sha256": hashes,
                "structuredDiff": {pair: {
                    "countsEqual": diff["countsEqual"],
                    "differingArrays": diff["differingArrays"],
                    "nonOriginDiffRows": diff["nonOriginDiffRows"],
                    "classification": diff["classification"],
                    "arrayDetails": diff["arrays"],
                } for pair, diff in diffs.items()}},
        "G2": {"pass": None,
               "summary": "run twice with --g2-reference on the second run; "
                          "byte comparison of the report excluding gates.G2"},
        "G3": {"pass": g3_pass,
               "summary": f"bit-weighted coverage gsim={cov['gsimBits'] * 100:.2f}% "
                          f"grhsim={cov['grhsimBits'] * 100:.2f}% (threshold 80%)"},
        "G4": {"pass": g4_pass,
               "summary": f"memory paired groups={g4['memory']['pairedGroups']} "
                          f"(gsim {g4['memory']['gsimCount']}, grhsim {g4['memory']['grhsimCount']}), "
                          f"io paired groups={g4['io']['pairedGroups']}, "
                          f"unpaired items all attributed={g4_pass}",
               "memory": g4["memory"],
               "io": g4["io"]},
    }

    report = {
        "inputs": {
            "gsimJson": args.gsim_json.name,
            "grhsimPre": args.grhsim_pre.name,
            "grhsimFinal": args.grhsim_final.name,
            "grhsimFull": args.grhsim_full.name,
            "grhsimArchive": str(args.grhsim_archive),
        },
        "metrics": {
            "M-name": m_name,
            "M-opcount": m_opcount,
            "M-kinddelta": m_kinddelta,
            "M-cone": m_cone,
        },
        "grhsimExtra": {
            "anonymousOpKinds": grhsim["anonymousOpKinds"],
            "valueOwnerStats": grhsim["valueOwnerStats"],
            "otherValueNamePatterns": grhsim["otherValueNamePatterns"],
            "coneLink": grhsim["coneLink"],
        },
        "gsimExtra": {
            "typeCounts": gsim["typeCounts"],
            "treeChecks": gsim["treeChecks"],
            "regConeLink": dict(gsim_cone_link),
        },
        "gates": gates,
    }

    # ---- G2: optional byte comparison against a previous report ----
    if args.g2_reference is not None:
        reference = json.loads(args.g2_reference.read_bytes())

        def strip_g2(payload):
            clone = dict(payload)
            clone_gates = dict(clone["gates"])
            clone_gates.pop("G2", None)
            clone["gates"] = clone_gates
            return clone

        current_bytes = json.dumps(strip_g2(report), indent=1, sort_keys=True)
        reference_bytes = json.dumps(strip_g2(reference), indent=1, sort_keys=True)
        report["gates"]["G2"] = {
            "pass": current_bytes == reference_bytes,
            "summary": f"report (excluding gates.G2) byte-equal to "
                       f"{args.g2_reference.name}: {current_bytes == reference_bytes}",
        }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.out_dir / "module_compare_report.json"
    summary_path = args.out_dir / "module_compare_summary.md"
    report_path.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n",
                           encoding="utf-8")
    summary_path.write_text(render_summary(report), encoding="utf-8")
    log(f"wrote {report_path} and {summary_path} in {time.time() - t0:.1f}s")
    print(render_summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
