#!/usr/bin/env python3
"""NO00014 pre-registered semantic gates for redundant de-monitoring.

Compares an old (baseline, NO00013) mapped checkpoint against a new
(de-monitored) one and, when diagnostic run logs are provided, checks the
dynamic counter dominance rules. Gates (all must PASS):

1. model-section-neutral   every top-level checkpoint key except "mappings" is
                           JSON-equal between old and new (semantics untouched)
2. partition-layout-neutral partition tree and data layout are JSON-equal
                           (de-monitoring touches no op membership, no slot)
3. fanout-rows-subset      new computeSupernodeFanout == old minus exactly the
                           census eligible set (recomputed in-process); every
                           surviving row is unchanged; inputFanout /
                           commitStateFanout / roundSeeds / inputShadows /
                           quiescenceProjection are unchanged
4. sn-rows-dominated       per-unit [grhsim-dyn] sn act/body/grp/chg <= baseline
                           (units keep their partition ids: direct per-key
                           compare; shrink is the expected bonus, growth is an
                           implementation flaw)
5. kind-rows-dominated     per-kind wr/ch <= baseline
6. mshrink                 (baseline Σwr - new Σwr) >= shrink-frac * baseline Σwr
                           (Σwr over [grhsim-dyn] kind rows; default 1.2%)
7. determinism+endpoint    run1/run2 [grhsim-vchg]/[grhsim-dyn] streams identical;
                           endpoint fields equal and match the pre-registered
                           baseline endpoint (instrCnt=240349 cycleCnt=99996
                           guest=100001 pc=0x80000c0c)

Gates 1-3 always run; 4-6 need --baseline-run and --run1; 7 needs --run1/--run2.
"""

import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grhsim_demonitor_census as dc  # noqa: E402

ANSI = re.compile(r"\x1b\[[0-9;]*m")
SN_LINE = re.compile(r"^\[grhsim-dyn] sn (\d+) act=(\d+) body=(\d+) grp=(\d+) chg=(\d+)$")
KIND_LINE = re.compile(r"^\[grhsim-dyn] kind (\S+) wr=(\d+) ch=(\d+) silent=(\d+)$")
PC_LINE = re.compile(r"EXCEEDING CYCLE/INSTR LIMIT at pc = (0x[0-9a-f]+)")
INSTR_LINE = re.compile(r"instrCnt = ([\d,]+), cycleCnt = ([\d,]+)")
GUEST_LINE = re.compile(r"Guest cycle spent: ([\d,]+)")

EXPECTED_ENDPOINT = {"pc": "0x80000c0c", "instr": 240349, "cycle": 99996, "guest": 100001}


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


def schedule_of(model):
    return model["mappings"][0][-1][4]


def gate_model_neutral(old_model, new_model):
    g = Gate("1.model-section-neutral")
    old_keys = {k for k in old_model if k != "mappings"}
    new_keys = {k for k in new_model if k != "mappings"}
    g.check(old_keys == new_keys, f"top-level key sets differ: {old_keys ^ new_keys}")
    for key in sorted(old_keys & new_keys):
        g.check(old_model[key] == new_model[key], f"section '{key}' differs")
    return g


def gate_partition_layout_neutral(old_model, new_model):
    g = Gate("2.partition-layout-neutral")
    old_payload = old_model["mappings"][0][-1]
    new_payload = new_model["mappings"][0][-1]
    g.check(old_payload[0] == new_payload[0], "mapping stage differs")
    g.check(old_payload[1] == new_payload[1], "partition root differs")
    g.check(old_payload[2] == new_payload[2], "partition tree differs")
    g.check(old_payload[3] == new_payload[3], "data layout differs")
    return g


def gate_fanout_rows(old_model, new_model):
    g = Gate("3.fanout-rows-subset")
    old_sched = schedule_of(old_model)
    new_sched = schedule_of(new_model)
    g.check(old_sched[1] == new_sched[1], "inputFanout differs")
    g.check(old_sched[3] == new_sched[3], "commitStateFanout differs")
    g.check(old_sched[4] == new_sched[4], "roundSeeds differ")
    g.check(old_sched[5] == new_sched[5], "inputShadows differ")
    g.check(old_sched[6] == new_sched[6], "inputShadowBytes differ")
    g.check(old_sched[7:] == new_sched[7:][:len(old_sched[7:])],
            "quiescence projection differs")

    old_rows = {row[0]: row for row in old_sched[2]}
    new_rows = {row[0]: row for row in new_sched[2]}
    grew = sorted(set(new_rows) - set(old_rows))
    g.check(not grew, f"{len(grew)} new fanout rows appeared: {grew[:5]}")
    changed = [v for v in set(old_rows) & set(new_rows) if old_rows[v] != new_rows[v]]
    g.check(not changed, f"{len(changed)} surviving fanout rows changed: {changed[:5]}")
    removed = set(old_rows) - set(new_rows)

    view = dc.view_from_model(old_model)
    eligible, _, _, _, state_cover, _ = dc.census(view)
    expected = {e["v"] for e in eligible} | {e["v"] for e in state_cover}
    missing = sorted(expected - removed)
    extra = sorted(removed - expected)
    g.check(not missing, f"{len(missing)} eligible rows were NOT removed: {missing[:5]}")
    g.check(not extra, f"{len(extra)} removed rows are not eligible: {extra[:5]}")
    g.note(f"removed rows: {len(removed)}; census eligible: {len(expected)}; "
           f"remaining rows: {len(new_rows)}")
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


def gate_sn_dominated(baseline_run, run1):
    g = Gate("4.sn-rows-dominated")
    base = parse_sn(baseline_run)
    new = parse_sn(run1)
    g.check(bool(base), "baseline log has no sn rows")
    g.check(bool(new), "new run log has no sn rows")
    violations, shrinks = [], []
    for pid, brow in base.items():
        nrow = new.get(pid, (0, 0, 0, 0))
        if any(n > b for n, b in zip(nrow, brow)):
            violations.append((pid, brow, nrow))
        elif any(n < b for n, b in zip(nrow, brow)):
            shrinks.append((pid, brow, nrow))
    extra = sorted(set(new) - set(base))
    g.check(not extra, f"{len(extra)} new sn rows appeared: {extra[:5]}")
    g.check(not violations, f"{len(violations)} units exceed baseline counters: {violations[:5]}")
    g.note(f"units compared: {len(base)}; with reduced counters (redundant-round"
           f" removal): {len(shrinks)}; sample {shrinks[:10]}")
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
    parser.add_argument("--shrink-frac", type=float, default=0.012)
    parser.add_argument("--cycles", type=int, default=100001)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    old_model = json.loads(args.old_model.read_bytes())
    new_model = json.loads(args.new_model.read_bytes())

    gates = [gate_model_neutral(old_model, new_model),
             gate_partition_layout_neutral(old_model, new_model),
             gate_fanout_rows(old_model, new_model)]

    if args.baseline_run and args.run1:
        gates.append(gate_sn_dominated(args.baseline_run, args.run1))
        kind_gate, base_kinds, new_kinds = gate_kind_dominated(args.baseline_run, args.run1)
        gates.append(kind_gate)
        if base_kinds and new_kinds:
            gates.append(gate_mshrink(base_kinds, new_kinds, args.shrink_frac, args.cycles))
    if args.run1 and args.run2:
        gates.append(gate_determinism(args.run1, args.run2))

    ok = all(g.ok for g in gates)
    lines = ["# NO00014 de-monitor gates", ""]
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
