#!/usr/bin/env python3
"""Diagnose commit-side event-history states for direct-sampling feasibility (candidate E).

Replicates the emitter-side planning (planSharedHistories / planComputeSharedHistories /
planHistoryBatches candidate accounting / planDirectSampling) on a GrhSIM IR checkpoint
that carries the final cpu mapping (partition tree + data layout + schedule), validates
the replication against the emitted cpu.st.emit-cpp counters, then decomposes the
commit-side physical history states (the "541") and certifies how many of them satisfy
the compute-side-style conservative conditions adapted to commit tasks:

  C1 closure: every objectRef reference to the state (incl. alias preimages) is a
     trailing history sample position of an evented write op inside ONE commit task;
  C2 same event value at every sample site, edge in {posedge, negedge};
  C3 1-bit two-state logic, state type == event type;
  C4 fanout: commitStateFanout row is exactly one arm target, the task's own domain;
  C5 event storage kind == Boundary and not a state-read alias;
  (informational) projected flag, const init.

Usage: grhsim_commit_history_stats.py --model <xiangshan_grhsim_ir.json>
"""
import argparse
import collections
import json
import sys
import time

WRITE_OPS = {"core.state.regWrite", "core.state.memWrite", "core.state.memFill",
             "core.state.memWriteSeq"}
SYS_OPS = {"core.system.task", "core.dpi.call"}


def parse_sv_int(text):
    """Canonicalize a small SV integer literal to an int (1-bit histories only need 0/1)."""
    t = text.strip()
    if t in ("x", "X", "z", "Z", "'x", "'X", "'z", "'Z", "'0"):
        return 0
    if t == "'1":
        return 1
    if "'" in t:
        _, rest = t.split("'", 1)
        base = rest[0]
        digits = rest[1:].replace("_", "")
        return int(digits, {"h": 16, "H": 16, "d": 10, "D": 10, "b": 2, "B": 2, "o": 8, "O": 8}[base])
    return int(t.replace("_", ""), 10)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
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
    n_states = len(states)

    payload = None
    for mapping in model["mappings"]:
        if len(mapping) > 4 and mapping[4]:
            payload = mapping[4]
    assert payload, "no cpu mapping payload"
    partitions = {p[0]: p for p in payload[2]}
    layout = payload[3]
    schedule = payload[4]

    # ---- layout ----
    layout_types = {t[0]: t for t in layout[1]}          # id -> [id,kind,width,elem,count,size,align]
    state_slot = {}                                       # state id -> (offset, cpuTypeId)
    for entry in layout[2]:                               # [objKind, objIndex, [type,kind,owner,offset]]
        if entry[0] == 2:                                 # ObjectKind: Input=0, Output=1, State=2, Function=3
            state_slot[entry[1]] = (entry[2][3], entry[2][0])
    value_kind = [0] * (len(values) + 1)                  # CpuStorageKind: Object=0, PartitionLocal=1, Boundary=2
    for i, slot in enumerate(layout[3]):
        value_kind[i + 1] = slot[1]
    arm_offset = {}                                       # domain partition -> arm offset
    word_offset = {}
    for slot in layout[5]:                                # [kind, owner, value, edge, offset]
        if slot[0] == 1:
            arm_offset[slot[1]] = slot[4]
        elif slot[0] == 0:
            word_offset[slot[1]] = slot[4]
    active_off = {}
    active_mask = {}
    for p in payload[2]:
        if len(p) > 7 and p[7] and p[7][0]:
            active_off[p[0]] = word_offset[p[1]]
            active_mask[p[0]] = 1 << (p[7][0][0] % 8)

    # ---- schedule ----
    tasks = schedule[0][0][1][0][1]                       # [[id, partition, waitsFor, execution], ...]
    fanout = {}                                           # state id -> (activate list, arm list)
    for row in schedule[3]:
        fanout[row[0]] = (row[1], row[2])
    proj_size = schedule[7]
    proj_words = schedule[8]

    def projected(sid):
        return sid < proj_size and bool(proj_words[sid >> 6] >> (sid & 63) & 1)

    # ---- types ----
    def state_type_id(sid):
        return states[sid - 1][2]

    def is_1bit_2state(type_id):
        t = types[type_id - 1]
        return t[2] == "logic" and t[3] == 1 and not t[4] and t[5] == "2-state"

    # ---- init records ----
    initializers = collections.Counter()
    const_init = {}                                       # state id -> canonical int value
    for record in model["init"]:
        sid = record[0]
        steps = record[1]
        initializers[sid] += 1
        if len(steps) != 1:
            continue
        kind = strings[steps[0][0]]
        if kind != "core.init.const":
            continue
        for prm in steps[0][1]:
            if strings[prm[0]] == "value":
                try:
                    const_init[sid] = parse_sv_int(prm[2])
                except (ValueError, KeyError, IndexError):
                    pass

    # ---- global state reference counting (objectRefPool) ----
    references = collections.Counter()
    ref_sites = collections.defaultdict(list)             # sid -> [(opid, is_history_position)]
    op_edges = {}                                         # opid -> (edges list, events list, history ref indices)
    for op in ops:
        opid = op[0]
        refs = op[6] or []
        edges = None
        for prm in op[7] or []:
            if strings[prm[0]] == "event_edges":
                edges = prm[2]
        n_hist = len(edges) if edges else 0
        if n_hist:
            op_edges[opid] = (edges, (op[4] or [])[-n_hist:], len(refs) - n_hist)
        for i, r in enumerate(refs):
            if r[0] != "state":
                continue
            references[r[1]] += 1
            ref_sites[r[1]].append((opid, n_hist and i >= len(refs) - n_hist))

    # ---- compute owners (for read-alias replication) ----
    compute_owner = {}
    for task in tasks:
        if task[3] != 0:
            continue
        for word in partitions[task[1]][4]:
            for unit in partitions[word][4]:
                for node in partitions[unit][4]:
                    for opid in partitions[node][5] or []:
                        compute_owner[opid] = unit

    snapshot = [False] * (len(values) + 1)
    for op in ops:
        if not compute_owner.get(op[0]):
            for v in op[4] or []:
                snapshot[v] = True
    for p in payload[2]:
        if p[6]:
            for ev in p[6][1]:
                snapshot[ev[0]] = True
    read_alias = [0] * (len(values) + 1)
    for op in ops:
        if strings[op[1]] != "core.state.read" or not compute_owner.get(op[0]):
            continue
        result = (op[5] or [0])[0]
        source = (op[6] or [[None, 0]])[0][1]
        if (projected(source) and not snapshot[result] and
                types[values[result - 1][1] - 1][2] == "logic" and
                values[result - 1][1] == state_type_id(source)):
            read_alias[result] = source

    # ---- per-task sample scans ----
    task_info = []                                        # per commit task dict
    history_task = collections.defaultdict(list)          # sid -> [(task_id, event, edge)]
    compute_sites = collections.defaultdict(list)         # sid -> [(unit, event)]  (planDirectSampling style)
    for task in tasks:
        task_id, part, _, execution = task
        function = partitions[part]
        parent = partitions[function[1]]
        is_commit = execution != 0
        if is_commit:
            domain = parent[0] if parent[2] == 2 else 0
            gate = parent[6] if parent[2] == 2 else None
            samples = collections.defaultdict(lambda: {"event": 0, "refs": 0, "consistent": True})
            order = []
            for unit in function[4]:
                for opid in partitions[unit][5] or []:
                    op = ops[opid - 1]
                    name = strings[op[1]]
                    if name not in WRITE_OPS:
                        continue
                    info = op_edges.get(opid)
                    if not info:
                        continue
                    edges, events, hbase = info
                    refs = op[6]
                    for i in range(len(edges)):
                        sid = refs[hbase + i][1]
                        ent = samples[sid]
                        if ent["refs"] == 0:
                            ent["event"] = events[i]
                            order.append(sid)
                        ent["refs"] += 1
                        ent["consistent"] &= (ent["event"] == events[i] and
                                              edges[i] in ("posedge", "negedge"))
                        history_task[sid].append((task_id, events[i], edges[i]))
            task_info.append({"task": task_id, "execution": execution, "domain": domain,
                              "gate_events": [ev[0] for ev in gate[1]] if gate else [],
                              "units": list(function[4]),
                              "samples": samples, "order": order})
        else:
            produced = set()
            unit_ops = collections.defaultdict(list)
            for word in function[4]:
                for unit in partitions[word][4]:
                    for node in partitions[unit][4]:
                        for opid in partitions[node][5] or []:
                            unit_ops[unit].append(opid)
                            for r in ops[opid - 1][5] or []:
                                produced.add((unit, r))
            for unit, opids in unit_ops.items():
                for opid in opids:
                    op = ops[opid - 1]
                    name = strings[op[1]]
                    if name not in SYS_OPS:
                        continue
                    info = op_edges.get(opid)
                    if not info:
                        continue
                    edges, events, hbase = info
                    refs = op[6]
                    for i in range(len(edges)):
                        if refs[hbase + i][0] != "state":
                            continue
                        compute_sites[refs[hbase + i][1]].append((unit, events[i]))
            task_info.append({"task": task_id, "execution": execution, "compute_units": unit_ops,
                              "produced": produced})

    # ---- replicate planSharedHistories (commit-side sharing) ----
    aliases = {}                                          # sid -> representative sid
    shared_tasks = 0
    share_ineligible = collections.Counter()              # per (task, sid) first failing check
    ineligible_states = set()
    representatives = set()
    for info in task_info:
        if info["execution"] == 0 or not info.get("domain"):
            continue
        if not partitions[info["domain"]][6]:
            continue
        dom = info["domain"]
        rep_for_key = {}
        task_aliases = 0
        for sid in info["order"]:
            if sid in aliases:
                continue
            smp = info["samples"][sid]
            row = fanout.get(sid, ([], []))
            reason = None
            if not smp["consistent"]:
                reason = "inconsistent_event_or_edge"
            elif references[sid] != smp["refs"]:
                reason = "external_references"
            elif initializers[sid] != 1 or sid not in const_init:
                reason = "no_const_init"
            elif not projected(sid):
                reason = "not_projected"
            elif len(row[0]) != 0 or len(row[1]) != 1 or row[1][0] != dom:
                reason = "fanout_not_self_arm"
            elif read_alias[smp["event"]]:
                reason = "event_read_alias"
            elif value_kind[smp["event"]] != 2:
                reason = "event_not_boundary"
            elif state_type_id(sid) != values[smp["event"] - 1][1]:
                reason = "type_mismatch"
            elif not is_1bit_2state(state_type_id(sid)):
                reason = "not_1bit_2state"
            if reason:
                share_ineligible[reason] += 1
                ineligible_states.add(sid)
                continue
            key = (smp["event"], state_type_id(sid), const_init[sid])
            if key in rep_for_key:
                aliases[sid] = rep_for_key[key]
                task_aliases += 1
            else:
                rep_for_key[key] = sid
                representatives.add(sid)
        if task_aliases:
            shared_tasks += 1

    # ---- replicate planHistoryBatches accounting (commit-side candidate stats) ----
    candidates = 0
    private_rejected = 0
    layout_rejected = 0
    for info in task_info:
        if info["execution"] == 0 or not info.get("domain"):
            continue
        if not partitions[info["domain"]][6]:
            continue
        dom = info["domain"]
        for unit in info["units"]:
            for opid in partitions[unit][5] or []:
                op = ops[opid - 1]
                info2 = op_edges.get(opid)
                if not info2:
                    continue
                edges, events, hbase = info2
                refs = op[6]
                for i in range(len(edges)):
                    candidates += 1
                    sid = refs[hbase + i][1]
                    if references[sid] != 1:
                        private_rejected += 1
                        continue
                    if sid in aliases:
                        continue
                    row = fanout.get(sid, ([], []))
                    slot = state_slot.get(sid, (0, 0))
                    if (not is_1bit_2state(state_type_id(sid)) or
                            state_type_id(sid) != values[events[i] - 1][1] or
                            layout_types[slot[1]][5] != 1 or not projected(sid) or
                            len(row[0]) != 0 or len(row[1]) != 1 or row[1][0] != dom):
                        layout_rejected += 1

    # ---- replicate planComputeSharedHistories + planDirectSampling (validation) ----
    compute_aliases = {}
    compute_alias_units = 0
    for info in task_info:
        if info["execution"] != 0:
            continue
        for unit in info["compute_units"]:
            rep_for_key = {}
            unit_aliases = 0
            for node in partitions[unit][4]:
                for opid in partitions[node][5] or []:
                    op = ops[opid - 1]
                    name = strings[op[1]]
                    if name not in SYS_OPS:
                        continue
                    info2 = op_edges.get(opid)
                    if not info2:
                        continue
                    edges, events, hbase = info2
                    refs = op[6]
                    for i in range(len(edges)):
                        if refs[hbase + i][0] != "state":
                            continue
                        sid = refs[hbase + i][1]
                        row = fanout.get(sid, ([], []))
                        slot = state_slot.get(sid, (0, 0))
                        if (sid in compute_aliases or references[sid] != 1 or
                                initializers[sid] != 1 or sid not in const_init or
                                not projected(sid) or len(row[0]) + len(row[1]) < 1 or
                                state_type_id(sid) != values[events[i] - 1][1] or
                                layout_types[slot[1]][5] != 1):
                            continue
                        key = (events[i], state_type_id(sid), const_init[sid])
                        if key not in rep_for_key:
                            rep_for_key[key] = sid
                            continue
                        first = rep_for_key[key]
                        row_a = fanout.get(first, ([], []))
                        if row_a != row:
                            continue
                        compute_aliases[sid] = first
                        unit_aliases += 1
            if unit_aliases:
                compute_alias_units += 1

    preimage = collections.defaultdict(list)
    for sid, rep in aliases.items():
        preimage[rep].append(sid)
    for sid, rep in compute_aliases.items():
        preimage[rep].append(sid)

    # Alias-resolved sample-site attribution (the emitter resolves refs through
    # historyAliases_ before attributing a sample site to a physical state).
    resolved_history_task = collections.defaultdict(list)   # physical sid -> [(task, event, edge)]
    for sid, sites in history_task.items():
        resolved_history_task[aliases.get(sid, sid)].extend(sites)
    resolved_compute_sites = collections.defaultdict(list)  # physical sid -> [(unit, event)]
    for sid, sites in compute_sites.items():
        resolved_compute_sites[compute_aliases.get(sid, sid)].extend(sites)

    unit_produced = {}
    for info in task_info:
        if info["execution"] == 0:
            for unit in info["compute_units"]:
                unit_produced[unit] = {r for u, r in info["produced"] if u == unit}
    direct_ok = 0
    direct_units = set()
    direct_reject = collections.Counter()
    for sid, sites in resolved_compute_sites.items():
        if sid in compute_aliases:
            continue
        total = references[sid] + sum(references[p] for p in preimage[sid])
        if total != len(sites):
            continue
        unit0, event0 = sites[0]
        if not all(u == unit0 for u, _ in sites):
            direct_reject["multi_unit"] += 1
            continue
        if not all(e == event0 for _, e in sites):
            direct_reject["multi_event"] += 1
            continue
        if not is_1bit_2state(state_type_id(sid)):
            direct_reject["not_1bit"] += 1
            continue
        row = fanout.get(sid, ([], []))
        want_off, want_mask = active_off.get(unit0), active_mask.get(unit0)
        self_only = (len(row[1]) == 0 and len(row[0]) == 1 and
                     active_off.get(row[0][0]) == want_off and active_mask.get(row[0][0]) == want_mask)
        if not self_only:
            direct_reject["fanout_not_self"] += 1
            continue
        if event0 in unit_produced.get(unit0, set()) or (not read_alias[event0] and value_kind[event0] != 2):
            direct_reject["event_not_invariant"] += 1
            continue
        direct_ok += 1
        direct_units.add(unit0)

    print("== validation vs cpu.st.emit-cpp counters ==")
    print(f"history_candidates      {candidates}  (emit 182485)")
    print(f"history_private_rejected {private_rejected}  (emit 632)")
    print(f"history_layout_rejected {layout_rejected}  (emit 0)")
    print(f"history_shared_states   {len(aliases)}  (emit 181628)")
    print(f"history_shared_tasks    {shared_tasks}  (emit 471)")
    print(f"compute_history_aliases {len(compute_aliases)}  (emit 13425)")
    print(f"compute_alias_units     {compute_alias_units}  (emit 303)")
    print(f"direct_sample_states    {direct_ok}  (emit 311)")
    print(f"direct_sample_units     {len(direct_units)}  (emit 311)")
    print(f"direct rejects (compute side): {dict(direct_reject)}")

    # ---- commit-side physical history decomposition ----
    commit_physical = set()
    for sid in history_task:
        if sid not in aliases:
            commit_physical.add(sid)
    compute_physical = set()
    for sid in compute_sites:
        if sid not in compute_aliases:
            compute_physical.add(sid)
    both = commit_physical & compute_physical
    print("\n== physical history accounting ==")
    print(f"commit-side physical histories:  {len(commit_physical)} (report says 541)")
    print(f"compute-side physical histories: {len(compute_physical)} (report says 338)")
    print(f"referenced by both sides:        {len(both)}")
    print(f"representatives among commit-side: {len(representatives & commit_physical)}")
    print(f"share-ineligible among commit-side: {len(ineligible_states & commit_physical)}")
    print(f"share-ineligible reasons (per state): {dict(share_ineligible)}")

    # ---- commit-side direct-sampling certification ----
    task_by_id = {info["task"]: info for info in task_info}
    raw_both_sides = set(history_task) & set(compute_sites)
    print(f"states sampled on both sides (raw): {len(raw_both_sides)}")
    cert_pass = []
    cert_reject = collections.Counter()
    reject_examples = collections.defaultdict(list)
    for sid in sorted(commit_physical):
        sites = resolved_history_task[sid]              # [(task, event, edge)] incl. preimage sites
        tasks_seen = {t for t, _, _ in sites}
        events_seen = {e for _, e, _ in sites}
        non_sample_refs = 0
        for raw in [sid] + preimage[sid]:
            non_sample_refs += sum(1 for opid, is_hist in ref_sites[raw] if not is_hist)
        total = references[sid] + sum(references[p] for p in preimage[sid])
        reason = None
        if non_sample_refs:
            reason = "data_or_guard_refs_outside_samples"
        elif total != len(sites):
            reason = "refs_beyond_commit_samples"        # e.g. compute-side sample sites too
        elif len(tasks_seen) != 1:
            reason = "multi_task"
        elif len(events_seen) != 1:
            reason = "multi_event"
        elif not all(e in ("posedge", "negedge") for _, _, e in sites):
            reason = "edge_kind"
        elif not is_1bit_2state(state_type_id(sid)):
            reason = "not_1bit_2state"
        else:
            task_id = next(iter(tasks_seen))
            event = next(iter(events_seen))
            tinfo = task_by_id[task_id]
            row = fanout.get(sid, ([], []))
            if len(row[0]) != 0 or len(row[1]) != 1 or row[1][0] != tinfo["domain"]:
                reason = "fanout_not_self_arm"
            elif read_alias[event]:
                reason = "event_read_alias"
            elif value_kind[event] != 2:
                reason = "event_not_boundary"
            elif state_type_id(sid) != values[event - 1][1]:
                reason = "type_mismatch"
        if reason:
            cert_reject[reason] += 1
            if len(reject_examples[reason]) < 5:
                name = strings[states[sid - 1][1]] if states[sid - 1][1] else "?"
                reject_examples[reason].append(f"{sid}:{name[:80]}")
        else:
            cert_pass.append(sid)
    print("\n== commit-side direct-sampling certification (C1..C5) ==")
    print(f"certifiable: {len(cert_pass)} / {len(commit_physical)}")
    for reason, count in cert_reject.most_common():
        print(f"  reject {reason}: {count}  e.g. {reject_examples[reason]}")
    proj_pass = sum(1 for sid in cert_pass if projected(sid))
    print(f"  of certifiable, projected: {proj_pass}; const-init: "
          f"{sum(1 for sid in cert_pass if sid in const_init)}")
    multi_ref = sum(1 for sid in cert_pass if len(resolved_history_task[sid]) > 1)
    total_sites = sum(len(resolved_history_task[sid]) for sid in cert_pass)
    multi_ref_states = sum(1 for sid in cert_pass if references[sid] > 1)
    print(f"  certifiable with >1 resolved sample site: {multi_ref} (of which own refs>1: {multi_ref_states}); "
          f"total resolved sample sites: {total_sites}")

    # ---- per-task structure for benefit estimation ----
    rep_by_task = collections.Counter()
    event_of_rep = {}
    for sid in commit_physical:
        for task_id in {t for t, _, _ in resolved_history_task[sid]}:
            rep_by_task[task_id] += 1
        sites_seen = resolved_history_task[sid]
        if sites_seen:
            event_of_rep[sid] = sites_seen[0][1]
    print("\n== commit task structure (physical histories per task) ==")
    histo = collections.Counter(rep_by_task[t] for t in rep_by_task)
    print(f"tasks holding physical histories: {len(rep_by_task)}; reps-per-task histogram: {dict(sorted(histo.items()))}")
    exec_counts = collections.Counter(info["execution"] for info in task_info)
    print(f"tasks by execution (0=compute,1=domainGated,2=alwaysScan): {dict(exec_counts)}")

    # classify representatives by sampled event value id (proxy for clock identity)
    reps_by_event = collections.Counter(event_of_rep[sid] for sid in commit_physical)
    def vname(v):
        nm = values[v - 1][2]
        return strings[nm] if nm else f"#{v}"
    print("top events by physical representatives (event: reps):")
    for ev, cnt in reps_by_event.most_common(12):
        print(f"   {vname(ev)[:100]}: {cnt}")
    top_event = reps_by_event.most_common(1)[0][0]
    tasks_on_top = {t for sid in commit_physical if event_of_rep[sid] == top_event
                    for t, _, _ in resolved_history_task[sid]}
    print(f"hottest event {vname(top_event)[:80]}: {reps_by_event[top_event]} reps across {len(tasks_on_top)} tasks")
    gate_top = sum(1 for info in task_info
                   if info["execution"] != 0 and top_event in info["gate_events"])
    print(f"commit tasks with hottest event in domain gate: {gate_top}")
    # sites per task (guard/scan workload stays; stage calls track distinct reps)
    sites_by_task = collections.Counter()
    for sid in commit_physical:
        per_task = collections.Counter(t for t, _, _ in resolved_history_task[sid])
        for t, cnt in per_task.items():
            sites_by_task[t] += cnt
    top = sorted(((sites_by_task[t], rep_by_task[t], t) for t in rep_by_task), reverse=True)[:8]
    print("top tasks by resolved sample sites (sites, distinct reps, task):")
    for row in top:
        print(f"   sites={row[0]} reps={row[1]} task={row[2]}")
    # reps on tasks sampling the two hottest events vs the tail
    hot2 = {e for e, _ in reps_by_event.most_common(2)}
    reps_hot = sum(1 for sid in commit_physical if event_of_rep[sid] in hot2)
    tasks_hot = len({t for sid in commit_physical if event_of_rep[sid] in hot2
                     for t, _, _ in resolved_history_task[sid]})
    print(f"reps sampling the two hottest events: {reps_hot} on {tasks_hot} tasks; "
          f"tail: {len(commit_physical) - reps_hot} reps on {len(rep_by_task) - tasks_hot} tasks")

    # ---- event provenance: trace each sampled event to its producer ----
    def_op = {}
    for op in ops:
        for r in op[5] or []:
            def_op[r] = op[0]
    input_names = {}
    for inp in model["inputs"]:
        input_names[inp[0]] = strings[inp[1]] if inp[1] else f"input#{inp[0]}"

    def provenance(v, depth=0):
        """(class, detail): main-clock / reset / gated / other."""
        seen = set()
        chain = []
        while v and v not in seen and len(chain) < 8:
            seen.add(v)
            opid = def_op.get(v)
            if not opid:
                break
            op = ops[opid - 1]
            kind = strings[op[1]]
            chain.append(kind)
            if kind == "core.input.read":
                ref = (op[6] or [[None, 0]])[0]
                return ("input:" + input_names.get(ref[1], "?"), chain)
            if kind in ("core.compute.assign", "core.compute.bitSelect", "core.compute.concat"):
                v = (op[4] or [0])[0]
                continue
            return ("derived:" + kind, chain)
        return ("other", chain)

    prov_counts = collections.Counter()
    for sid in commit_physical:
        prov, _ = provenance(event_of_rep[sid])
        prov_counts[prov.split(":")[0]] += 1
    print("event provenance classes (reps):", dict(prov_counts))
    for ev, cnt in reps_by_event.most_common(4):
        prov, chain = provenance(ev)
        print(f"   event {vname(ev)[:60]} reps={cnt} provenance={prov} chain={chain[:5]}")
    print(f"\n[done] {time.time()-t0:.1f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
