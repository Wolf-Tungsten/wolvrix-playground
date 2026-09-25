#!/usr/bin/env python3
"""NO00013 pre-registered semantic gates for zero-new-edge boundary-op migration.

Compares an old (baseline) mapped checkpoint against a new (migrated) one and,
when diagnostic run logs are provided, checks the dynamic counter dominance
rules. Gates (all must PASS):

1. model-section-neutral   every top-level checkpoint key except "mappings" is
                           JSON-equal between old and new (semantics untouched)
2. boundary-shrink-closed  no new Boundary values; every flipped value lands in
                           PartitionLocal; non-flipped values keep their slot kind
3. op-membership-closed    supernodes match old<->new by op-set signature
                           (ops minus migrated ops, disjoint hence unambiguous);
                           every unmigrated op stays in its matched unit; every
                           migrated op lands in the matched common consumer unit
4. sn-rows-dominated       per-unit [grhsim-dyn] sn act/body/grp/chg <= baseline;
                           migration target units must not fire more than the
                           baseline (grp <= baseline). Targets may fire LESS: a
                           migrated op whose operand is a boundary value produced
                           inside the target removes the target's self-retrigger
                           round trip through the donor (same value propagation in
                           one invocation instead of two), so residual grp deltas
                           are reported, not gated
5. kind-rows-dominated     per-kind wr/ch <= baseline
6. mshrink                 (baseline Σwr - new Σwr) >= shrink-frac * baseline Σwr
                           (Σwr over [grhsim-dyn] kind rows; default 1.4%)
7. determinism+endpoint    run1/run2 [grhsim-vchg]/[grhsim-dyn] streams identical;
                           endpoint fields equal and match the pre-registered
                           baseline endpoint (instrCnt=240349 cycleCnt=99996
                           guest=100001 pc=0x80000c0c)

Gates 1-3 always run; 4-6 need --baseline-run and --run1; 7 needs --run1/--run2.
"""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import sys

KIND_SUPER = 3
STORAGE_BOUNDARY = 2
STORAGE_PARTITION_LOCAL = 1

ANSI = re.compile(r"\x1b\[[0-9;]*m")
VCHG_LINE = re.compile(r"^\[grhsim-vchg] v (\d+) wr=(\d+) ch=(\d+)$")
SN_LINE = re.compile(r"^\[grhsim-dyn] sn (\d+) act=(\d+) body=(\d+) grp=(\d+) chg=(\d+)$")
KIND_LINE = re.compile(r"^\[grhsim-dyn] kind (\S+) wr=(\d+) ch=(\d+) silent=(\d+)$")
PC_LINE = re.compile(r"EXCEEDING CYCLE/INSTR LIMIT at pc = (0x[0-9a-f]+)")
INSTR_LINE = re.compile(r"instrCnt = ([\d,]+), cycleCnt = ([\d,]+)")
GUEST_LINE = re.compile(r"Guest cycle spent: ([\d,]+)")

EXPECTED_ENDPOINT = {"pc": "0x80000c0c", "instr": 240349, "cycle": 99996, "guest": 100001}


class MappingInfo:
    def __init__(self, model):
        payload = model["mappings"][0][-1]
        self.partitions = {p[0]: p for p in payload[2]}
        value_slots = payload[3][3]
        self.slot_kind = {vid: slot[1] for vid, slot in enumerate(value_slots, start=1)}
        self.producer = {}
        self.consumers = defaultdict(list)
        for op in model["operations"]:
            oid, operands, results = op[0], op[4], op[5]
            for v in results:
                self.producer[v] = oid
            for v in operands:
                self.consumers[v].append(oid)
        self.unit_ops = {}
        self.unit_of_op = {}
        for pid, part in self.partitions.items():
            if part[2] != KIND_SUPER:
                continue
            ops = []
            stack = [pid]
            while stack:
                node = self.partitions[stack.pop()]
                stack.extend(node[4])
                ops.extend(node[5])
            self.unit_ops[pid] = frozenset(ops)
            for oid in ops:
                self.unit_of_op[oid] = pid

    @property
    def boundary(self):
        return {v for v, kind in self.slot_kind.items() if kind == STORAGE_BOUNDARY}


class Gate:
    def __init__(self, name):
        self.name = name
        self.ok = True
        self.detail = []

    def check(self, cond, msg):
        if not cond:
            self.ok = False
            self.detail.append(msg)

    def note(self, msg):
        self.detail.append(msg)

    def row(self):
        return {"gate": self.name, "ok": self.ok, "detail": self.detail}


def gate_model_neutral(old_model, new_model):
    g = Gate("1.model-section-neutral")
    old_keys = {k for k in old_model if k != "mappings"}
    new_keys = {k for k in new_model if k != "mappings"}
    g.check(old_keys == new_keys, f"top-level key sets differ: {old_keys ^ new_keys}")
    for key in sorted(old_keys & new_keys):
        g.check(old_model[key] == new_model[key], f"section '{key}' differs")
    return g


def analyze_migration(old, new):
    """Shared derivation: flipped values, migrated ops, supernode matching."""
    flipped = {}
    for v in old.boundary:
        new_kind = new.slot_kind.get(v)
        if new_kind != STORAGE_BOUNDARY:
            flipped[v] = new_kind
    moved_ops = {}
    for v in flipped:
        xop = old.producer.get(v, 0)
        moved_ops[xop] = v
    # Supernode signature matching: op sets minus migrated ops are disjoint and
    # nonempty on both sides, so signatures are unique.
    old_key_of = {}
    old_by_key = {}
    for pid, ops in old.unit_ops.items():
        key = frozenset(ops - moved_ops.keys())
        old_key_of[pid] = key
        old_by_key.setdefault(key, []).append(pid)
    new_to_old = {}
    ambiguous = []
    for pid, ops in new.unit_ops.items():
        key = frozenset(ops - moved_ops.keys())
        owners = old_by_key.get(key, [])
        if len(owners) != 1:
            ambiguous.append((pid, len(owners)))
        else:
            new_to_old[pid] = owners[0]
    old_to_new = {o: n for n, o in new_to_old.items()}
    return flipped, moved_ops, new_to_old, old_to_new, ambiguous


def gate_boundary_closed(old, new, flipped):
    g = Gate("2.boundary-shrink-closed")
    new_boundary = new.boundary
    grew = sorted(new_boundary - old.boundary)
    g.check(not grew, f"{len(grew)} values became Boundary (e.g. {grew[:5]})")
    bad_kind = {v: k for v, k in flipped.items() if k != STORAGE_PARTITION_LOCAL}
    g.check(not bad_kind, f"{len(bad_kind)} flipped values are not PartitionLocal: {dict(list(bad_kind.items())[:5])}")
    drift = [v for v in old.slot_kind
             if v not in flipped and new.slot_kind.get(v) != old.slot_kind[v]]
    g.check(not drift, f"{len(drift)} non-migrated values changed slot kind (e.g. {drift[:5]})")
    g.note(f"migrated values: {len(flipped)}")
    return g


def gate_membership(old, new, flipped, moved_ops, new_to_old, old_to_new, ambiguous):
    g = Gate("3.op-membership-closed")
    g.check(not ambiguous, f"{len(ambiguous)} new supernodes without a unique old signature: {ambiguous[:5]}")
    missing_old = [pid for pid in old.unit_ops if pid not in old_to_new]
    g.check(not missing_old, f"{len(missing_old)} old supernodes have no new counterpart: {missing_old[:5]}")
    if ambiguous or missing_old:
        return g
    target_of = {}
    mismatched_consumers = []
    for xop, v in moved_ops.items():
        units = {old.unit_of_op.get(c, 0) for c in old.consumers.get(v, [])}
        units.discard(old.unit_of_op.get(xop, 0))
        if len(units) != 1:
            mismatched_consumers.append((xop, sorted(units)))
        else:
            target_of[xop] = next(iter(units))
    g.check(not mismatched_consumers,
            f"{len(mismatched_consumers)} migrated values lack a single consumer unit: {mismatched_consumers[:5]}")
    wrong_move = []
    wrong_stay = []
    for oid, old_unit in old.unit_of_op.items():
        new_unit = new.unit_of_op.get(oid, 0)
        mapped = new_to_old.get(new_unit)
        if oid in moved_ops:
            if mapped == target_of.get(oid):
                continue
            # A flipped value can also become local to its producer's own unit
            # when its last external consumer migrates in (bonus flip): the
            # producer stays and every consumer lands in the producer's unit.
            v = moved_ops[oid]
            if mapped == old_unit and old.consumers.get(v) and all(
                    new_to_old.get(new.unit_of_op.get(c, 0)) == old_unit
                    for c in old.consumers[v]):
                continue
            wrong_move.append((oid, old_unit, mapped, target_of.get(oid)))
        elif mapped != old_unit:
            wrong_stay.append((oid, old_unit, mapped))
    g.check(not wrong_move, f"{len(wrong_move)} migrated ops landed in the wrong unit: {wrong_move[:5]}")
    g.check(not wrong_stay, f"{len(wrong_stay)} unmigrated ops changed unit: {wrong_stay[:5]}")
    g.note(f"migrated ops: {len(moved_ops)}; donors: "
           f"{len({old.unit_of_op[o] for o in moved_ops})}; targets: {len(set(target_of.values()))}")
    return g


def parse_log_lines(path):
    for line in Path(path).read_text(errors="replace").splitlines():
        yield ANSI.sub("", line).strip()


def parse_sn(path):
    rows = {}
    for line in parse_log_lines(path):
        m = SN_LINE.match(line)
        if m:
            rows[int(m.group(1))] = tuple(int(m.group(i)) for i in range(2, 6))
    return rows


def parse_kinds(path):
    rows = {}
    for line in parse_log_lines(path):
        m = KIND_LINE.match(line)
        if m:
            rows[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    return rows


def key_stream(path):
    return [line for line in parse_log_lines(path)
            if line.startswith("[grhsim-vchg]") or line.startswith("[grhsim-dyn]")]


def parse_endpoint(path):
    endpoint = {}
    for line in parse_log_lines(path):
        m = PC_LINE.search(line)
        if m:
            endpoint["pc"] = m.group(1)
        m = INSTR_LINE.search(line)
        if m:
            endpoint["instr"] = int(m.group(1).replace(",", ""))
            endpoint["cycle"] = int(m.group(2).replace(",", ""))
        m = GUEST_LINE.search(line)
        if m:
            endpoint["guest"] = int(m.group(1).replace(",", ""))
    return endpoint


def gate_sn_dominated(baseline_run, run1, old_to_new, targets):
    g = Gate("4.sn-rows-dominated")
    base = parse_sn(baseline_run)
    new = parse_sn(run1)
    g.check(bool(base), "baseline log has no sn rows")
    g.check(bool(new), "new run log has no sn rows")
    violations, target_drift = [], []
    for old_pid, brow in base.items():
        nrow = new.get(old_to_new.get(old_pid, -1), (0, 0, 0, 0))
        if any(n > b for n, b in zip(nrow, brow)):
            violations.append((old_pid, brow, nrow))
        if old_pid in targets:
            if nrow[2] > brow[2]:
                violations.append((old_pid, ("grp", brow[2]), ("grp", nrow[2])))
            elif nrow[2] != brow[2]:
                target_drift.append((old_pid, brow[2], nrow[2]))
    g.check(not violations, f"{len(violations)} units exceed baseline counters: {violations[:5]}")
    g.note(f"units compared: {len(base)}; targets: {len(targets)}; "
           f"targets with reduced grp (self-retrigger removal): {len(target_drift)} "
           f"max delta {max((b - n for _, b, n in target_drift), default=0)} "
           f"drifts {target_drift[:20]}")
    return g


def gate_kind_dominated(baseline_run, run1):
    g = Gate("5.kind-rows-dominated")
    base = parse_kinds(baseline_run)
    new = parse_kinds(run1)
    g.check(bool(base), "baseline log has no kind rows")
    g.check(bool(new), "new run log has no kind rows")
    violations = [(k, base.get(k), row) for k, row in new.items()
                  if k not in base or row[0] > base[k][0] or row[1] > base[k][1]]
    g.check(not violations, f"{len(violations)} kinds exceed baseline wr/ch: {violations[:5]}")
    return g, base, new


def gate_mshrink(base_kinds, new_kinds, shrink_frac, cycles):
    g = Gate("6.mshrink")
    base_wr = sum(row[0] for row in base_kinds.values())
    new_wr = sum(row[0] for row in new_kinds.values())
    shrink = base_wr - new_wr
    need = shrink_frac * base_wr
    g.check(shrink >= need,
            f"Σwr shrink {shrink} ({shrink / cycles:.1f}/cyc) below gate {need:.0f} ({shrink_frac:.2%})")
    g.note(f"baseline Σwr={base_wr} new Σwr={new_wr} shrink={shrink} "
           f"({shrink / cycles:.1f}/cyc, {shrink / base_wr:.2%})")
    return g


def gate_determinism(run1, run2):
    g = Gate("7.determinism-endpoint")
    s1, s2 = key_stream(run1), key_stream(run2)
    g.check(s1 == s2, "run1/run2 [grhsim-vchg]+[grhsim-dyn] streams differ")
    g.check(bool(s1), "run1 log has no diagnostic key lines")
    e1, e2 = parse_endpoint(run1), parse_endpoint(run2)
    g.check(e1 == e2, f"endpoint differs between runs: {e1} vs {e2}")
    g.check(e1 == EXPECTED_ENDPOINT, f"endpoint {e1} != pre-registered {EXPECTED_ENDPOINT}")
    return g


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-model", type=Path, required=True)
    parser.add_argument("--new-model", type=Path, required=True)
    parser.add_argument("--baseline-run", type=Path)
    parser.add_argument("--run1", type=Path)
    parser.add_argument("--run2", type=Path)
    parser.add_argument("--shrink-frac", type=float, default=0.014)
    parser.add_argument("--cycles", type=int, default=100001)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    old_model = json.loads(args.old_model.read_bytes())
    new_model = json.loads(args.new_model.read_bytes())
    old = MappingInfo(old_model)
    new = MappingInfo(new_model)

    gates = [gate_model_neutral(old_model, new_model)]
    flipped, moved_ops, new_to_old, old_to_new, ambiguous = analyze_migration(old, new)
    gates.append(gate_boundary_closed(old, new, flipped))
    gates.append(gate_membership(old, new, flipped, moved_ops, new_to_old, old_to_new, ambiguous))

    if args.baseline_run and args.run1:
        targets = set()
        for xop in moved_ops:
            units = {old.unit_of_op.get(c, 0) for c in old.consumers.get(moved_ops[xop], [])}
            units.discard(old.unit_of_op.get(xop, 0))
            targets |= units
        gates.append(gate_sn_dominated(args.baseline_run, args.run1, old_to_new, targets))
        kind_gate, base_kinds, new_kinds = gate_kind_dominated(args.baseline_run, args.run1)
        gates.append(kind_gate)
        if base_kinds and new_kinds:
            gates.append(gate_mshrink(base_kinds, new_kinds, args.shrink_frac, args.cycles))
    if args.run1 and args.run2:
        gates.append(gate_determinism(args.run1, args.run2))

    ok = all(g.ok for g in gates)
    lines = ["# NO00013 migration gates", ""]
    for g in gates:
        lines.append(f"- [{'PASS' if g.ok else 'FAIL'}] {g.name}")
        for detail in g.detail:
            lines.append(f"    - {detail}")
    lines.append("")
    lines.append(f"VERDICT: {'ALL GATES PASS' if ok else 'GATE FAILURE'}")
    text = "\n".join(lines) + "\n"
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "gates.md").write_text(text)
    (args.output / "gates.json").write_text(json.dumps(
        {"ok": ok, "gates": [g.row() for g in gates]}, indent=1))
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
