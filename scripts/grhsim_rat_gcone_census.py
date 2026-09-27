#!/usr/bin/env python3
"""NO00022 M-gcone census: row-private write-cone dynamic execs of target RAT families.

Pre-registered anchor metric of pdocs/NO00022-grhsim-ir-writenet-factor-*.md:

  M-gcone = deduplicated row-private write-cone op execs/cycle of the target
  register families, deterministic caliber:
    sum over distinct private cone ops of body(unit(op)) / cycles
  where body(unit) is the in-simulation deterministic body-fire counter of the
  op's compute supernode ([grhsim-dyn] sn rows of a dyn run log) and
  cycles = 100001 for the NO00019 archive runs.

Caliber (identical for the baseline and the post-transform re-measurement):
  * target families are selected by state-name pattern
    ``$<rat>$<arch_table|spec_table|difftest_table>_<row>$`` restricted to the
    ``--target-families`` list (the census-proven convertible set);
  * per row state, the write cone is the FULL backward cone of the regWrite
    data operand (walk stops naturally at operand-less ops such as
    state.read/input.read/constant);
  * an op is row-private iff it appears in exactly one row cone of its family
    (row fanout == 1);
  * the metric dedups private ops across all target families.

The script also reports, per family, the read-side consumer op-kind histogram
of the per-row state.read results (census deliverable "read-side consumer
class") and the cross-row shared cone execs (the allocation network proper,
explicitly not a target).

Gates:
  G1 every target family is present with the expected row count
     (--expect-families JSON, e.g. {"fpRat/arch_table": 34, ...}); when a
     family expectation is 0 the family must be absent (post-transform
     re-measurement caliber);
  G2 every target row state has exactly one regWrite and family row indices
     are consecutive (step 1, any base — the pass groups from the base row);
  G3 every cone op has a compute-unit mapping (unmapped ops would price at
     zero and silently corrupt the metric);
  G4 the dyn log contributed at least one sn row and cycles > 0;
  G5 two script runs over the same inputs are byte identical (checked by the
     caller comparing summary.json/summary.md).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SN_LINE = re.compile(r"^\[grhsim-dyn] sn (\d+) act=(\d+) body=(\d+) grp=(\d+) chg=(\d+)$")
FAMILY_NAME = re.compile(r"\$(\w+)\$(arch_table|spec_table|difftest_table)_(\d+)$")

DEFAULT_TARGET_FAMILIES = [
    "fpRat/arch_table",
    "fpRat/difftest_table",
    "vecRat/arch_table",
    "vecRat/difftest_table",
]


def log(msg):
    print(f"[grhsim-rat-gcone-census] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Model access (pure functions, unit-testable)
# ---------------------------------------------------------------------------


def parse_state_family(name):
    """Return (rat, table, row) for RAT table row state names, else None."""
    match = FAMILY_NAME.search(name)
    if not match:
        return None
    return match.group(1), match.group(2), int(match.group(3))


def build_op_index(model):
    """Index operations/states: kinds, operands, results, refs, producers."""
    strings = model["strings"]
    aux = {
        "op_kind": {},
        "op_operands": {},
        "op_results": {},
        "op_refs": {},
        "producer_of": {},
        "state_writes": defaultdict(list),
        "state_reads": defaultdict(list),
        "state_name": {},
    }
    for op in model["operations"]:
        oid = op[0]
        kind = strings[op[1] - 1]
        operands, results, refs = op[4], op[5], op[6]
        aux["op_kind"][oid] = kind
        aux["op_operands"][oid] = operands
        aux["op_results"][oid] = results
        aux["op_refs"][oid] = refs
        for value in results:
            aux["producer_of"][value] = oid
        if refs and refs[0][0] == "state":
            if kind == "core.state.regWrite":
                aux["state_writes"][refs[0][1]].append(oid)
            elif kind == "core.state.read":
                aux["state_reads"][refs[0][1]].append(oid)
    for state in model["states"]:
        aux["state_name"][state[0]] = strings[state[1] - 1]
    return aux


def build_unit_of_op(model):
    """Map every op of a compute supernode (partition kind 3) subtree."""
    payload = model["mappings"][0][-1]
    partitions = {part[0]: part for part in payload[2]}
    unit_of_op = {}
    for pid, part in partitions.items():
        if part[2] != 3:
            continue
        stack = [pid]
        while stack:
            node = partitions[stack.pop()]
            stack.extend(node[4])
            for op_id in node[5]:
                unit_of_op[op_id] = pid
    return unit_of_op


def load_body_fires(run_path):
    """Parse [grhsim-dyn] sn rows -> {unit: body fires}."""
    body = {}
    with open(run_path) as handle:
        for line in handle:
            match = SN_LINE.match(line)
            if match:
                body[int(match.group(1))] = int(match.group(3))
    return body


def row_write_cone(data_value, producer_of, op_operands):
    """Full backward cone of a regWrite data operand: set of producer op ids."""
    cone = set()
    stack = [data_value]
    while stack:
        value = stack.pop()
        producer = producer_of.get(value)
        if producer is None or producer in cone:
            continue
        cone.add(producer)
        stack.extend(op_operands[producer])
    return cone


def split_row_fanout(row_cones):
    """Split a family's per-row cones into private (fanout 1) / shared ops."""
    fanout = Counter()
    for cone in row_cones:
        for op in cone:
            fanout[op] += 1
    private = {op for op, count in fanout.items() if count == 1}
    shared = {op for op, count in fanout.items() if count > 1}
    return private, shared


def price_ops(ops, unit_of_op, body):
    """Closed-form dynamic execs: sum of body fires of each op's unit."""
    execs = 0
    unmapped = []
    for op in ops:
        unit = unit_of_op.get(op)
        if unit is None or unit not in body:
            unmapped.append(op)
            continue
        execs += body.get(unit, 0)
    return execs, sorted(unmapped)


def replacement_memories(model, aux, unit_of_op, body, expected):
    """Validate recovered arrays by retained source origins, then price their cones.

    This is separate from M-gcone: whole array cones include shared allocation
    logic that was deliberately excluded from the row-private baseline.
    """
    strings = model["strings"]
    origins = {origin[0]: origin for origin in model.get("origins", [])}
    types = {row[0]: row for row in model["types"]}
    writes = defaultdict(list)
    reads = Counter()
    for op in model["operations"]:
        kind = aux["op_kind"][op[0]]
        refs = op[6]
        if not refs or refs[0][0] != "state":
            continue
        if kind in ("core.state.memWrite", "core.state.memWriteSeq", "core.state.memFill"):
            writes[refs[0][1]].append(op)
        elif kind == "core.state.memRead":
            reads[refs[0][1]] += 1
    found = defaultdict(list)
    all_cones = set()
    for state in model["states"]:
        origin = origins.get(state[3]) if len(state) > 3 else None
        if not origin or not origin[2]:
            continue
        parsed = parse_state_family(strings[origin[2] - 1])
        if not parsed:
            continue
        family = f"{parsed[0]}/{parsed[1]}"
        if family not in expected:
            continue
        typ = types[state[2]]
        if typ[2] != "array":
            continue
        cone = set()
        kinds = Counter()
        triples = 0
        for op in writes[state[0]]:
            kind = aux["op_kind"][op[0]]
            kinds[kind] += 1
            event_count = len(op[6]) - 1
            data_operands = op[4][:-event_count] if event_count else op[4]
            if kind == "core.state.memWriteSeq":
                if len(data_operands) % 3:
                    raise ValueError("invalid memWriteSeq triple count")
                triples += len(data_operands) // 3
            for operand in data_operands:
                cone |= row_write_cone(operand, aux["producer_of"], aux["op_operands"])
        execs, unmapped = price_ops(cone, unit_of_op, body)
        found[family].append({
            "name": aux["state_name"][state[0]], "source_row": parsed[2],
            "elements": typ[7], "writes": dict(sorted(kinds.items())),
            "sequence_triples": triples, "mem_reads": reads[state[0]],
            "whole_cone_ops": len(cone), "whole_cone_execs": execs,
            "unmapped_cone_ops": unmapped,
        })
        all_cones |= cone
    failures = {}
    for family, count in expected.items():
        rows = found.get(family, [])
        if (len(rows) != 1 or rows[0]["elements"] != count or
                rows[0]["writes"] != {"core.state.memWriteSeq": 1} or
                rows[0]["sequence_triples"] < count or not rows[0]["mem_reads"] or
                rows[0]["unmapped_cone_ops"]):
            failures[family] = rows
    execs, unmapped = price_ops(all_cones, unit_of_op, body)
    return {"families": dict(found), "whole_cone_ops": len(all_cones),
            "whole_cone_execs": execs, "unmapped_cone_ops": unmapped}, failures


def read_consumer_kinds(state, aux, consumers_of):
    """Op-kind Counter of the consumers of this row state's state.reads."""
    histogram = Counter()
    for read_op in aux["state_reads"].get(state, []):
        for result in aux["op_results"][read_op]:
            for consumer in consumers_of.get(result, ()):
                histogram[aux["op_kind"][consumer]] += 1
    return histogram


# ---------------------------------------------------------------------------
# Metric assembly
# ---------------------------------------------------------------------------


def collect_families(aux, target_families):
    """Group target-family row states: family -> {row: state id}."""
    wanted = set(target_families)
    families = defaultdict(dict)
    for sid, name in aux["state_name"].items():
        parsed = parse_state_family(name)
        if not parsed:
            continue
        rat, table, row = parsed
        if f"{rat}/{table}" in wanted:
            families[f"{rat}/{table}"][row] = sid
    return families


def measure_families(families, aux, unit_of_op, body):
    """Per-family cones, fanout split, pricing; plus grand private dedup."""
    consumers_of = defaultdict(list)
    for oid, operands in aux["op_operands"].items():
        for value in operands:
            consumers_of[value].append(oid)

    per_family = {}
    target_private = set()
    target_shared = set()
    unmapped_private = []
    multi_writer_rows = []
    for family in sorted(families):
        rows = families[family]
        row_cones = []
        per_row = []
        for row in sorted(rows):
            sid = rows[row]
            writes = aux["state_writes"].get(sid, [])
            if len(writes) != 1:
                multi_writer_rows.append((family, row, len(writes)))
                continue
            operands = aux["op_operands"][writes[0]]
            cone = row_write_cone(operands[1], aux["producer_of"], aux["op_operands"])
            row_cones.append(cone)
            per_row.append({"row": row, "state": sid, "cone_ops": len(cone)})
        private, shared = split_row_fanout(row_cones)
        private_execs, priv_unmapped = price_ops(private, unit_of_op, body)
        shared_execs, shared_unmapped = price_ops(shared, unit_of_op, body)
        consumers = Counter()
        for row in sorted(rows):
            consumers.update(read_consumer_kinds(rows[row], aux, consumers_of))
        per_family[family] = {
            "rows": len(rows),
            "row_indices": sorted(rows),
            "per_row_cone_ops": per_row,
            "private_ops": len(private),
            "private_execs": private_execs,
            "shared_ops": len(shared),
            "shared_execs": shared_execs,
            "unmapped_private_ops": priv_unmapped,
            "unmapped_shared_ops": shared_unmapped,
            "read_consumer_kinds": dict(sorted(consumers.items())),
        }
        target_private |= private
        target_shared |= shared
        unmapped_private.extend(priv_unmapped)

    total_private_execs, total_priv_unmapped = price_ops(target_private, unit_of_op, body)
    shared_only = target_shared - target_private
    shared_execs, _ = price_ops(shared_only, unit_of_op, body)
    return {
        "per_family": per_family,
        "multi_writer_rows": multi_writer_rows,
        "target_private_ops": len(target_private),
        "target_private_execs": total_private_execs,
        "target_shared_only_ops": len(shared_only),
        "target_shared_only_execs": shared_execs,
        "unmapped_private_ops": sorted(set(unmapped_private) | set(total_priv_unmapped)),
    }


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def fmt_int(value):
    return f"{value:,}"


def render_summary_md(summary):
    cycles = summary["inputs"]["cycles"]
    lines = [
        "# NO00022 M-gcone census summary",
        "",
        "## Gates",
        "",
        "| gate | result | detail |",
        "|---|---|---|",
    ]
    for name in sorted(summary["gates"]):
        ok, detail = summary["gates"][name]
        lines.append(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
    lines += [
        "",
        "## M-gcone (row-private write-cone dynamic execs)",
        "",
        "| family | rows | private ops | private execs/cycle | shared ops | shared execs/cycle |",
        "|---|---|---|---|---|---|",
    ]
    metric = summary["metrics"]["M-gcone"]
    for family, row in sorted(metric["families"].items()):
        lines.append(
            f"| {family} | {row['rows']} | {fmt_int(row['private_ops'])} "
            f"| {row['private_execs'] / cycles:,.1f} | {fmt_int(row['shared_ops'])} "
            f"| {row['shared_execs'] / cycles:,.1f} |")
    lines.append(
        f"| **target dedup** | {metric['total_rows']} | {fmt_int(metric['private_ops'])} "
        f"| **{metric['private_execs'] / cycles:,.1f}** | {fmt_int(metric['shared_only_ops'])} "
        f"| {metric['shared_only_execs'] / cycles:,.1f} |")
    lines += [
        "",
        "Target dedup = row-private ops deduplicated across all target families",
        "(M-gcone). Shared-only = ops shared by >=2 rows of a family, excluding",
        "any op that is row-private in another target family.",
        "",
        "## Read-side consumer kinds (per family)",
        "",
        "| family | consumer kinds |",
        "|---|---|",
    ]
    for family, row in sorted(metric["families"].items()):
        kinds = ", ".join(f"{kind} x{count}"
                          for kind, count in sorted(row["read_consumer_kinds"].items()))
        lines.append(f"| {family} | {kinds} |")
    if "replacement_memories" in summary:
        replacements = summary["replacement_memories"]
        lines += ["", "## Recovered arrays (includes shared allocation logic)", "",
                  "| family | array | rows | sequence triples | reads | whole cone ops | whole cone execs/cycle |",
                  "|---|---|---|---|---|---|---|"]
        for family, rows in sorted(replacements["families"].items()):
            for row in rows:
                lines.append(f"| {family} | {row['name']} | {row['elements']} | "
                             f"{row['sequence_triples']} | {row['mem_reads']} | "
                             f"{row['whole_cone_ops']:,} | {row['whole_cone_execs'] / cycles:,.1f} |")
        lines += ["", f"Deduplicated whole array cones: {replacements['whole_cone_ops']:,} ops; "
                  f"{replacements['whole_cone_execs'] / cycles:,.1f} execs/cycle. "
                  "This includes shared logic and is not the row-private M-gcone metric."]
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="production checkpoint JSON")
    parser.add_argument("--run", required=True, help="dyn run log with [grhsim-dyn] sn rows")
    parser.add_argument("--output", required=True, help="output directory")
    parser.add_argument("--cycles", type=int, default=100001)
    parser.add_argument("--target-families", type=json.loads, default=None,
                        help="JSON list of '<rat>/<table>' family keys "
                             f"(default: {DEFAULT_TARGET_FAMILIES})")
    parser.add_argument("--expect-families", type=json.loads, default=None,
                        help="JSON object {'<rat>/<table>': row count} for G1")
    parser.add_argument("--expect-memories", type=json.loads, default=None,
                        help="verify replacement arrays by retained origins; JSON family-to-row-count map")
    args = parser.parse_args(argv)

    target_families = args.target_families or DEFAULT_TARGET_FAMILIES
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    log(f"loading model {args.model}")
    model = json.loads(Path(args.model).read_bytes())
    aux = build_op_index(model)
    unit_of_op = build_unit_of_op(model)
    log(f"model: ops={len(aux['op_kind']):,} states={len(aux['state_name']):,} "
        f"mapped ops={len(unit_of_op):,}")

    body = load_body_fires(args.run)
    log(f"dyn: sn units={len(body):,}")

    families = collect_families(aux, target_families)
    log("target families: " + ", ".join(
        f"{family} rows={len(families[family])}" for family in sorted(families)))
    measured = measure_families(families, aux, unit_of_op, body)

    gates = {}
    replacements = None
    if args.expect_memories:
        replacements, failures = replacement_memories(model, aux, unit_of_op, body, args.expect_memories)
        gates["G6_replacement_memories"] = (not failures, failures)
    if args.expect_families is not None:
        diffs = {}
        for family, expected in sorted(args.expect_families.items()):
            actual = len(families.get(family, {}))
            if actual != expected:
                diffs[family] = [actual, expected]
        gates["G1_target_families"] = (not diffs, diffs if diffs else
                                       {family: len(families.get(family, {}))
                                        for family in sorted(args.expect_families)})
    bad_rows = []
    for family, row in measured["per_family"].items():
        indices = row["row_indices"]
        if indices != list(range(indices[0], indices[0] + row["rows"])):
            bad_rows.append(family)
    gates["G2_row_indices"] = (not bad_rows, bad_rows)
    gates["G2_single_writer"] = (not measured["multi_writer_rows"],
                                 measured["multi_writer_rows"][:5])
    gates["G3_unit_coverage"] = (not measured["unmapped_private_ops"],
                                 measured["unmapped_private_ops"][:5])
    gates["G4_dyn_rows"] = (bool(body) and args.cycles > 0,
                            [len(body), args.cycles])

    cycles = args.cycles
    families_md = {
        family: {
            "rows": row["rows"],
            "private_ops": row["private_ops"],
            "private_execs": row["private_execs"],
            "shared_ops": row["shared_ops"],
            "shared_execs": row["shared_execs"],
            "read_consumer_kinds": row["read_consumer_kinds"],
            "unmapped_private_ops": len(row["unmapped_private_ops"]),
            "unmapped_shared_ops": len(row["unmapped_shared_ops"]),
        }
        for family, row in sorted(measured["per_family"].items())
    }
    summary = {
        "inputs": {
            "model": str(args.model),
            "run": str(args.run),
            "cycles": cycles,
            "target_families": sorted(target_families),
            "expect_families": args.expect_families,
        },
        "gates": gates,
        "metrics": {
            "M-gcone": {
                "families": families_md,
                "total_rows": sum(row["rows"] for row in families_md.values()),
                "private_ops": measured["target_private_ops"],
                "private_execs": measured["target_private_execs"],
                "shared_only_ops": measured["target_shared_only_ops"],
                "shared_only_execs": measured["target_shared_only_execs"],
            },
        },
    }
    if replacements is not None:
        summary["inputs"]["expect_memories"] = args.expect_memories
        summary["replacement_memories"] = replacements

    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "summary.md").write_text(render_summary_md(summary), encoding="utf-8")
    failed = [name for name, (ok, _detail) in gates.items() if not ok]
    log(f"M-gcone private execs/cycle: {measured['target_private_execs'] / cycles:,.1f} "
        f"({measured['target_private_ops']:,} ops)")
    log(f"gates: {'all PASS' if not failed else 'FAILED ' + ','.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
