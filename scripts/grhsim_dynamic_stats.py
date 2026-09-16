"""Join a [grhsim-dyn] counter dump with the model's static structure."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re


KIND_LINE = re.compile(r"^\[grhsim-dyn] kind (\S+) wr=(\d+) ch=(\d+) silent=(\d+)$")
SN_LINE = re.compile(r"^\[grhsim-dyn] sn (\d+) act=(\d+) body=(\d+) grp=(\d+) chg=(\d+)$")
COMMIT_LINE = re.compile(r"^\[grhsim-dyn] commit (\d+) ent=(\d+)$")
TOTALS_LINE = re.compile(r"^\[grhsim-dyn] totals (.*)$")
PHASE_LINE = re.compile(r"^\[grhsim-cpu-phase] evals=(\d+) rounds=(\d+)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True, help="emu log containing [grhsim-dyn] lines")
    parser.add_argument("--model", type=Path, required=True, help="mapped xiangshan_grhsim_ir.json")
    args = parser.parse_args()
    text = args.log.read_text(errors="replace")
    kinds, units, commits, totals, evals, rounds = {}, {}, {}, {}, None, None
    for line in text.splitlines():
        if match := KIND_LINE.match(line):
            kinds[match[1]] = tuple(map(int, match.groups()[1:]))
        elif match := SN_LINE.match(line):
            units[int(match[1])] = tuple(map(int, match.groups()[1:]))
        elif match := COMMIT_LINE.match(line):
            commits[int(match[1])] = int(match[2])
        elif match := TOTALS_LINE.match(line):
            totals = dict((key, int(value)) for key, value in re.findall(r"(\w+)=(\d+)", match[1]))
        elif match := PHASE_LINE.match(line):
            evals, rounds = int(match[1]), int(match[2])
    if evals is None or not totals:
        raise ValueError("log lacks phase or totals counters")
    model = json.loads(args.model.read_bytes())
    ops, strings = model["operations"], model["strings"]
    payload = model["mappings"][0][-1]
    partitions = {part[0]: part for part in payload[2]}
    schedule = payload[4]
    task_exec, task_partition = {}, {}
    for _numa in schedule[0]:
        for core in _numa[1]:
            for task in core[1]:
                task_exec[task[0]] = task[3]
                task_partition[task[0]] = task[1]

    def subtree_ops(root):
        result = []
        stack = [root]
        while stack:
            part = partitions[stack.pop()]
            result.extend(part[5])
            stack.extend(part[4])
        return result

    # Static op kind counts per compute supernode (partition id).
    unit_kinds, unit_ops = {}, {}
    for pid, part in partitions.items():
        if part[2] != 3:
            continue
        members = subtree_ops(pid)
        unit_ops[pid] = len(members)
        unit_kinds[pid] = Counter(strings[ops[op - 1][1] - 1] for op in members)

    dyn_exec = Counter()
    total_act = total_body = total_chg = 0
    productive = []
    buckets = Counter()
    bucket_ops = Counter()
    for pid, (act, body, grp, chg) in units.items():
        total_act += act
        total_body += body
        total_chg += chg
        if act:
            productive.append(chg / act)
        if act == rounds:
            bucket = "every_round"
        elif act == evals:
            bucket = "every_eval"
        elif act > evals:
            bucket = "multi_round"  # participates in convergence rounds beyond the first
        elif act * 2 == rounds:
            bucket = "every_eval_alt"
        else:
            bucket = "other"
        buckets[bucket] += 1
        bucket_ops[bucket] += body * unit_ops.get(pid, 0)
        for name, count in unit_kinds.get(pid, {}).items():
            dyn_exec[name] += count * body
    commit_entries = sum(commits.values())
    print(f"evals={evals} rounds={rounds} rounds_per_eval={rounds / evals:.4f}")
    print(f"supernode activations={total_act} bodies={total_body} "
          f"quiescence_skipped={total_act - total_body} ({100 * (1 - total_body / max(total_act, 1)):.2f}%)")
    print(f"productive group calls: grp_fire/grp_pub={totals['grp_fire']}/{totals['grp_pub']} "
          f"({100 * totals['grp_fire'] / max(totals['grp_pub'], 1):.2f}%)")
    print(f"supernode chg/act mean={100 * sum(productive) / max(len(productive), 1):.2f}% over {len(productive)} units")
    total_body_ops = sum(bucket_ops.values())
    for bucket, count in buckets.items():
        print(f"bucket {bucket}: units={count} dyn_ops={bucket_ops[bucket]} "
              f"({100.0 * bucket_ops[bucket] / max(total_body_ops, 1):.2f}%)")
    print(f"commit entries={commit_entries} port_eval={totals['port_eval']} port_fire={totals['port_fire']} "
          f"fire/eval={100 * totals['port_fire'] / max(totals['port_eval'], 1):.2f}%")
    print(f"stable_skips={totals['cm_stable']} inactive_samples={totals['cm_inactive']}")
    print(f"input checks={totals['in_chk']} changes={totals['in_chg']}")
    print(f"publish calls={totals['pub_calls']} pending={totals['pub_pending']} "
          f"changes={totals['pub_changes']} pending/call={totals['pub_pending'] / max(totals['pub_calls'], 1):.2f}")
    print("\n== dynamic compute op executions by kind (body-weighted; top 30) ==")
    total_exec = sum(dyn_exec.values())
    print(f"total_dynamic_compute_ops={total_exec} per_eval={total_exec / evals:.1f}")
    for name, count in dyn_exec.most_common(30):
        print(f"{count:>14} {100.0 * count / max(total_exec, 1):7.3f}% {name}")
    print("\n== boundary write activity by kind ==")
    total_wr = sum(v[0] for v in kinds.values())
    total_ch = sum(v[1] for v in kinds.values())
    total_silent = sum(v[2] for v in kinds.values())
    print(f"total writes={total_wr} changes={total_ch} ({100 * total_ch / max(total_wr, 1):.2f}%) silent={total_silent}")
    for name, (wr, ch, silent) in sorted(kinds.items(), key=lambda item: -item[1][0])[:30]:
        print(f"{wr:>14} ch={ch:>14} ({100 * ch / max(wr, 1):6.2f}%) silent={silent:>12} {name}")
    print("\n== top supernodes by activations ==")
    for pid, (act, body, grp, chg) in sorted(units.items(), key=lambda item: -item[1][0])[:15]:
        print(f"unit={pid} ops={unit_ops.get(pid, 0)} act={act} body={body} chg={chg} "
              f"chg/act={100 * chg / max(act, 1):.1f}% dyn_ops={body * unit_ops.get(pid, 0)}")
    round_kinds = Counter()
    for pid, (act, body, grp, chg) in units.items():
        if act == rounds:
            for name, count in unit_kinds.get(pid, {}).items():
                round_kinds[name] += count * body
    if round_kinds:
        print("\n== every-round units: dynamic op mix ==")
        total_round = sum(round_kinds.values())
        for name, count in round_kinds.most_common(12):
            print(f"{count:>14} {100.0 * count / total_round:7.3f}% {name}")


if __name__ == "__main__":
    main()
