#!/usr/bin/env python3
"""Analyze commit-side large write-port clusters (the "4096 counter family") in GrhSIM IR.

For every commit task (execution != ActivityDrivenCompute) in a checkpoint carrying the
final cpu mapping, decompose its state write ops (regWrite/memWrite/memFill/memWriteSeq):
  - op counts by kind, target state bytes, per-op commit form actually emitted;
  - target state families (same module path + base name), identifying >=1024-member
    clusters (the "4096" families);
  - data/enable operand value ids to judge whether per-port work is uniform
    (batchable) or genuinely distinct;
  - static emitted-call counts are cross-checked against the generated task sources
    separately (report prints per-task op counts only).

Usage: grhsim_commit_cluster_stats.py --model <xiangshan_grhsim_ir.json> [--top 20]
"""
import argparse
import collections
import json
import re
import sys
import time

WRITE_OPS = {"core.state.regWrite": "reg", "core.state.memWrite": "mem",
             "core.state.memFill": "fill", "core.state.memWriteSeq": "seq"}
IDX = re.compile(r"^(.*?)(?:_)?(\d+)$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()
    t0 = time.time()
    with open(args.model, "rb") as fh:
        model = json.load(fh)
    print(f"[load] {time.time()-t0:.1f}s", file=sys.stderr)

    strings = [None] + model["strings"]
    types = model["types"]
    states = model["states"]
    values = model["values"]
    ops = model["operations"]

    payload = None
    for mapping in model["mappings"]:
        if len(mapping) > 4 and mapping[4]:
            payload = mapping[4]
    partitions = {p[0]: p for p in payload[2]}
    schedule = payload[4]
    tasks = schedule[0][0][1][0][1]

    def state_name(sid):
        nm = states[sid - 1][1]
        return strings[nm] if nm else f"#{sid}"

    def state_type(sid):
        return types[states[sid - 1][2] - 1]

    def type_bytes(t):
        # t = [id, typeRef, kind, width, isSigned, domain, elemType, count]
        if t[2] == "array":
            elem = types[t[6] - 1]
            return type_bytes(elem) * t[7]
        return (t[3] + 7) // 8

    def value_name(v):
        nm = values[v - 1][2]
        return strings[nm] if nm else f"#{v}"

    # base family of a state name: drop trailing index of the last component
    def family_of(name):
        last = name.rsplit("$", 1)[-1]
        parent = name.rsplit("$", 1)[0] if "$" in name else ""
        m = IDX.match(last)
        if m and m.group(2) is not None and m.group(1):
            return parent + "$" + m.group(1) + "_*" if parent else m.group(1) + "_*"
        return name

    per_task = []
    family_stats = collections.defaultdict(lambda: {"ops": 0, "states": set(), "bytes": 0,
                                                    "tasks": set(), "kinds": collections.Counter(),
                                                    "data_vals": collections.Counter(),
                                                    "enable_vals": collections.Counter()})
    total_commit_ops = 0
    for task in tasks:
        task_id, part, _, execution = task
        if execution == 0:
            continue
        function = partitions[part]
        op_counts = collections.Counter()
        target_bytes = 0
        target_states = set()
        families = collections.Counter()
        for unit in function[4]:
            for opid in partitions[unit][5] or []:
                op = ops[opid - 1]
                kind = WRITE_OPS.get(strings[op[1]])
                if not kind:
                    continue
                op_counts[kind] += 1
                total_commit_ops += 1
                refs = op[6]
                sid = refs[0][1]
                target_states.add(sid)
                t = state_type(sid)
                tb = type_bytes(t)
                target_bytes += tb if kind == "reg" else 0
                fam = family_of(state_name(sid))
                families[fam] += 1
                fs = family_stats[fam]
                fs["ops"] += 1
                fs["states"].add(sid)
                fs["tasks"].add(task_id)
                fs["kinds"][kind] += 1
                # operand layout: reg=[en,data,mask,events..]; mem=[en,addr,data,mask,events..];
                # fill=[en,data,events..]; seq=triples...,events..
                n_edges = 0
                for prm in op[7] or []:
                    if strings[prm[0]] == "event_edges":
                        n_edges = len(prm[2])
                data_ops = (op[4] or [])[:len(op[4] or []) - n_edges] if n_edges else (op[4] or [])
                if len(data_ops) >= 2:
                    fs["enable_vals"][data_ops[0]] += 1
                    fs["data_vals"][data_ops[1] if kind != "mem" else data_ops[2]] += 1
        per_task.append({"task": task_id, "execution": execution, "ops": dict(op_counts),
                         "total": sum(op_counts.values()), "states": len(target_states),
                         "reg_bytes": target_bytes, "families": families})

    print(f"commit tasks: {len(per_task)}; total commit write ops: {total_commit_ops}")
    per_task.sort(key=lambda x: -x["total"])
    print(f"\n== top {args.top} commit tasks by write-op count ==")
    for info in per_task[:args.top]:
        fams = ", ".join(f"{f}x{c}" for f, c in info["families"].most_common(3))
        print(f"task={info['task']} exec={info['execution']} ops={info['total']} {info['ops']} "
              f"states={info['states']} families: {fams}")

    print(f"\n== state families by write-op count (>=256 ops) ==")
    rows = []
    for fam, fs in family_stats.items():
        if fs["ops"] < 256:
            continue
        rows.append((fs["ops"], fam, fs))
    rows.sort(reverse=True)
    for cnt, fam, fs in rows[:args.top]:
        sample = next(iter(fs["states"]))
        t = state_type(sample)
        tdesc = f"{t[2]}w{t[3]}" + (f"[{t[7]}]" if t[2] == "array" else "")
        top_data = [value_name(v)[:60] for v, _ in fs["data_vals"].most_common(3)]
        top_en = [value_name(v)[:60] for v, _ in fs["enable_vals"].most_common(3)]
        print(f"ops={cnt} states={len(fs['states'])} tasks={sorted(fs['tasks'])[:6]} kinds={dict(fs['kinds'])}")
        print(f"   family: {fam[:130]}")
        print(f"   elem type(sample): {tdesc}; distinct data vals={len(fs['data_vals'])} top={top_data}")
        print(f"   distinct enable vals={len(fs['enable_vals'])} top={top_en}")
    print(f"\n== prefix rollups ==")
    for prefix in ("logEndpoint$", "__reg_to_mem_", "packed_bits_", "cpu$l_simMMIO$intrGen$"):
        roll = {"ops": 0, "states": set(), "tasks": set(), "data": set(), "enable": set(), "kinds": collections.Counter()}
        for fam, fs in family_stats.items():
            if not fam.startswith(prefix):
                continue
            roll["ops"] += fs["ops"]
            roll["states"] |= fs["states"]
            roll["tasks"] |= fs["tasks"]
            roll["data"] |= set(fs["data_vals"])
            roll["enable"] |= set(fs["enable_vals"])
            roll["kinds"] += fs["kinds"]
        if roll["ops"]:
            print(f"{prefix}: ops={roll['ops']} states={len(roll['states'])} tasks={sorted(roll['tasks'])} "
                  f"kinds={dict(roll['kinds'])} distinct_data={len(roll['data'])} distinct_enable={len(roll['enable'])}")
    print(f"\n[done] {time.time()-t0:.1f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
