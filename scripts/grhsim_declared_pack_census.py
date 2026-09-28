#!/usr/bin/env python3
"""Static census of same-origin declared-signal families (NO00026).

Universe: logic states of the post-lower dump whose names appear in its
declaredSymbols list (`__event_*` edge bookkeeping is excluded as a second
net; those names are not declared to begin with). declaredSymbols entries
are 1-based string-table indices in current dumps; plain string entries are
accepted as a fallback. Families cluster by (module path, stem), where the
stem is the bare name (last `$` component) with trailing `_<digits>`
segments stripped repeatedly (NO00020 chunk-strip rule); a stem that would
strip to empty keeps the last non-empty prefix. Name clustering is a
diagnostic anchor inside the declared provenance set, never an optimization
trigger.

Metrics (pre-registered in pdocs/NO00026-*.md):

  M-fam   family sizes, widths, bit share of the universe, and the
          production form of each member: standalone (same-name state in
          the final checkpoint), packed (listed in the pack-members TSV),
          memified (named as first_state in the reg-to-mem TSV; the TSV
          names only one representative state per merged memory, so this
          bucket undercounts non-first members), or other.
  M-align per packed word: members, families, modules; single-family word
          ratios (count- and member-bit-weighted); family-to-word
          dispersion.
  M-iso   family-internal update-cone isomorphism: for each member's single
          regWrite, the enable/data/mask cone (Model.local named-boundary
          truncation) is normalized into a signature: a topological
          (kind, result widths) sequence with operand references, where
          leaf labels are symbolic -- `self` for the member's own state,
          `fam[k]` for the k-th family member (members sorted by name),
          `name` for any other named reference, `const` for constants.
          Isomorphic = equal signatures.
  M-ctrl  control-signature subfamilies: Model.group_key (event operands,
          edge polarity, history initials, target initial) plus enable/mask
          operand identity. The post-lower dump has no schedule, so no
          quiescence-projection bit is included (approximation vs the
          NO00025 M-controls caliber).
  M-dyn   dynamic share of candidate families (isomorphic, >=2 members):
          production-side cones in the final checkpoint. Standalone
          members contribute their own regWrite cone; members packed in a
          word entirely owned by the family contribute the packed word's
          cone once; families in mixed words or with members of other
          forms are bucketed separately. Union-priced across families with
          unit_index body counters (all_local caliber, NO00025 M-bit).
          upper_bound is the sensitivity ceiling: mixed-bucket words are
          over-attributed as whole-word cones and incomplete-bucket
          families contribute their measurable members; memified members
          stay excluded (their cost lives in the memory access machine).

Cross-checks against production packing: pack-bit-registers groups words
by control signature only (pass/pack_bit_registers.cpp; data cones are
not part of the pack key), so packed words mixing several M-iso classes
are expected -- reported as informational statistics, not violations.
M-ctrl stays a hard gate: all signed members of one packed word must
share one control signature. Violations are attributed by re-checking
with structural enable/mask cone signatures (the post-lower dump predates
canonicalize-compute, so structurally identical enables may still carry
distinct value ids there). G3 can deterministically sample families and
re-judge isomorphism with an independent ordered-bijection matcher
(--sample-verify).

Closures (raise on violation): family bits + singleton bits + rejected
bits == universe bits; form counts sum to the universe member count; the
dynamic arm reuses check_dynamic (two runs key-equal, body x sites ==
runtime totals). Reports are deterministic: sorted keys, no timestamps,
no absolute paths.

All inputs are read-side tolerant: a missing optional file marks the
corresponding metric arm unavailable with a reason; a present but
malformed file is an error.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import gc
import hashlib
import json
import math
from pathlib import Path
import random
import re

from grhsim_bit_update_census import Model, check_dynamic
from grhsim_residual_write_cones import unit_index

CHUNK_TAIL = re.compile(r"_\d+$")
EVENT_PREFIX = "__event_"
PACK_HEADER = ["packed_state", "bit_index", "member_name", "init_bit"]
SIZE_BUCKETS = ("2", "3-4", "5-8", "9-16", "17-64", "65+")
SAMPLE_CONE_LIMIT = 200
CTRL_GATE_COMPONENTS = ("events", "edges", "history_initials", "target_initial",
                        "enable_cone", "mask_cone")
ISO_INFO_NOTE = ("informational only: pack-bit-registers groups words by control "
                 "signature (lib/grhsim/pass/pack_bit_registers.cpp); member data "
                 "cones are not part of the pack key, so mixed M-iso classes within "
                 "one word are expected and are not violations")
UPPER_BOUND_NOTE = ("safe upper bound: mixed-bucket words are over-attributed as "
                    "whole-word cones and incomplete-bucket families contribute "
                    "their measurable members; memified/other-form members are "
                    "excluded (their cost lives in the memory access machine)")
CTRL_NOTE = ("signature = Model.group_key (event operands, edge polarity, history "
             "initials, target initial) plus enable/mask operand identity; the "
             "post-lower dump carries no schedule, so no quiescence-projection bit "
             "is included (approximation vs the NO00025 M-controls caliber)")
FORM_NOTE = ("memified matches only the reg-to-mem TSV first_state column, which "
             "names one representative state per merged memory; non-first members "
             "of merged memories fall into other/standalone buckets")


def stem_of(bare):
    """Strip trailing `_<digits>` segments; never return an empty stem."""
    stem = bare
    while True:
        stripped = CHUNK_TAIL.sub("", stem)
        if not stripped or stripped == stem:
            return stem
        stem = stripped


def family_key(name):
    module, _, bare = name.rpartition("$")
    return module, stem_of(bare)


def size_bucket(n):
    for limit, label in ((2, "2"), (4, "3-4"), (8, "5-8"), (16, "9-16"), (64, "17-64")):
        if n <= limit:
            return label
    return "65+"


def percentile(ordered, q):
    """Nearest-rank percentile of an ascending list; deterministic integers."""
    if not ordered:
        return None
    return ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))]


def distribution(values):
    ordered = sorted(values)
    return {"count": len(ordered), "sum": sum(ordered), "median": percentile(ordered, 0.5),
            "p90": percentile(ordered, 0.9), "max": ordered[-1] if ordered else None}


def unavailable(reason):
    return {"available": False, "reason": reason}


def fam_label(fam):
    return f"{fam['module']}${fam['stem']}" if fam["module"] else fam["stem"]


def declared_names(model):
    raw = model.get("declaredSymbols")
    if raw is None:
        raise ValueError("post-lower dump lacks declaredSymbols")
    strings = model["strings"]
    names = set()
    for entry in raw:
        if isinstance(entry, int):
            if not 1 <= entry <= len(strings):
                raise ValueError(f"declaredSymbols index {entry} out of range")
            names.add(strings[entry - 1])
        elif isinstance(entry, str):
            names.add(entry)
        else:
            raise ValueError(f"unexpected declaredSymbols entry: {entry!r}")
    return names


def build_universe(model):
    declared = declared_names(model)
    strings = model["strings"]
    types = {t[0]: t for t in model["types"]}
    members = {}
    rejects, reject_bits, reject_samples = Counter(), Counter(), defaultdict(list)
    logic_hit, nonlogic_hit = set(), set()
    bits = 0
    for state in model["states"]:
        sid, name_idx, tid = state[0], state[1], state[2]
        name = strings[name_idx - 1] if name_idx else ""
        if name.startswith(EVENT_PREFIX) or name not in declared:
            continue
        typ = types[tid]
        if typ[2] != "logic":
            nonlogic_hit.add(name)
            continue
        logic_hit.add(name)
        bits += typ[3]
        if name in members:
            rejects["duplicate_state_name"] += 1
            reject_bits["duplicate_state_name"] += typ[3]
            if len(reject_samples["duplicate_state_name"]) < 10:
                reject_samples["duplicate_state_name"].append(name)
            continue
        module, stem = family_key(name)
        members[name] = {"sid": sid, "name": name, "width": typ[3],
                         "module": module, "stem": stem}
    return {"members": members, "bits": bits,
            "member_bits": sum(m["width"] for m in members.values()),
            "declared_total": len(declared),
            "declared_without_logic_state": len(declared - logic_hit),
            "declared_non_logic_states": len(nonlogic_hit),
            "rejected": {k: {"count": rejects[k], "bits": reject_bits[k],
                             "samples": reject_samples[k]} for k in sorted(rejects)}}


def read_pack_members(path):
    words = defaultdict(list)
    with path.open(newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader, None)
        if header != PACK_HEADER:
            raise ValueError(f"unexpected pack-members header: {header}")
        for lineno, row in enumerate(reader, 2):
            if len(row) != 4:
                raise ValueError(f"malformed pack-members row {lineno}: {row}")
            word, bit, member, init = row
            words[word].append((int(bit), member, init))
    for rows in words.values():
        rows.sort()
    return dict(words)


def read_reg_to_mem(path):
    names = set()
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames or "first_state" not in reader.fieldnames:
            raise ValueError("reg-to-mem TSV lacks the first_state column")
        for row in reader:
            if row.get("first_state"):
                names.add(row["first_state"])
    return names


def classify_forms(member_names, final_names, packed_names, reg2mem_names):
    forms = {}
    for name in sorted(member_names):
        if packed_names is not None and name in packed_names:
            forms[name] = "packed"
        elif final_names is not None and name in final_names:
            forms[name] = "standalone"
        elif reg2mem_names is not None and name in reg2mem_names:
            forms[name] = "memified"
        elif packed_names is None or final_names is None or reg2mem_names is None:
            forms[name] = "unavailable_form"
        else:
            forms[name] = "other"
    return forms


def summarize_forms(members, forms, missing):
    counts, bits = Counter(), Counter()
    for name, form in forms.items():
        counts[form] += 1
        bits[form] += members[name]["width"]
    others = sorted(name for name, form in forms.items() if form == "other")
    return {"available": not missing,
            "missing_inputs": sorted(missing),
            "counts": {k: counts[k] for k in sorted(counts)},
            "bits": {k: bits[k] for k in sorted(bits)},
            "other_samples": others[:10],
            "note": FORM_NOTE}


def m_align(words, universe):
    members = universe["members"]
    rows, family_words = [], defaultdict(set)
    nondeclared_rows = 0
    for word, entries in sorted(words.items()):
        fams, mods, nondeclared = set(), set(), 0
        for _, member, _ in entries:
            rec = members.get(member)
            if rec is None:
                nondeclared += 1
                continue
            fams.add((rec["module"], rec["stem"]))
            mods.add(rec["module"])
            family_words[(rec["module"], rec["stem"])].add(word)
        nondeclared_rows += nondeclared
        rows.append({"word": word, "members": len(entries), "families": len(fams),
                     "modules": len(mods), "nondeclared_members": nondeclared,
                     "single_family": len(fams) == 1 and nondeclared == 0})
    single = [row for row in rows if row["single_family"]]
    total_members = sum(row["members"] for row in rows)
    single_bits = sum(row["members"] for row in single)
    dispersion = sorted(len(words_of) for words_of in family_words.values())
    report = {"available": True, "word_count": len(rows), "member_rows": total_members,
              "members_not_in_universe": nondeclared_rows,
              "single_family_words": len(single),
              "single_family_word_ratio": len(single) / len(rows) if rows else None,
              "single_family_bit_ratio": single_bits / total_members if total_members else None,
              "word_size": distribution([row["members"] for row in rows]),
              "families_per_word": distribution([row["families"] for row in rows]),
              "modules_per_word": distribution([row["modules"] for row in rows]),
              "words_with_nondeclared_members": sum(1 for row in rows if row["nondeclared_members"]),
              "families_with_packed_members": len(family_words),
              "family_word_dispersion": distribution(dispersion),
              "families_split_across_words": sum(1 for n in dispersion if n > 1)}
    return report


def leaf_label(view, value, self_name, ordinals):
    oid = view.producer[value]
    kind = view.kind(oid)
    if kind == "core.state.read":
        refs = [obj for tag, obj in view.ops[oid][6] if tag == "state"]
        name = view.text(view.states[refs[0]][1]) if refs else view.text(view.values[value][2])
        if name == self_name:
            return ["self"]
        if name in ordinals:
            return ["fam", ordinals[name]]
        return ["name", name]
    if kind == "core.compute.constant":
        return ["const", str(view.params(oid).get("constValue"))]
    return ["name", view.text(view.values[value][2])]


def cone_signature(view, roots, self_name, ordinals):
    """Normalized cone signature: id-free topological op sequence plus leaf labels."""
    local, _ = view.local(roots)
    order, seen = [], set()
    stack = [(root, False) for root in roots]
    while stack:
        value, expanded = stack.pop()
        oid = view.producer[value]
        if oid not in local or oid in seen:
            continue
        if not expanded:
            stack.append((value, True))
            for arg in view.ops[oid][4]:
                stack.append((arg, False))
            continue
        seen.add(oid)
        order.append(oid)
    index = {oid: i for i, oid in enumerate(order)}

    def ref(value):
        oid = view.producer[value]
        if oid in index:
            return ["op", index[oid]]
        return ["leaf", leaf_label(view, value, self_name, ordinals)]

    entries = []
    for oid in order:
        op = view.ops[oid]
        entries.append([view.kind(oid), [view.width(v) for v in op[5]],
                        [ref(arg) for arg in op[4]]])
    return {"ops": entries, "roots": [ref(root) for root in roots]}


def update_signature(view, sid, self_name, ordinals):
    writers = view.writes.get(sid, [])
    if not writers:
        return None, "no_writer"
    if len(writers) != 1:
        return None, "multiple_writers"
    return cone_signature(view, view.ops[writers[0]][4][:3], self_name, ordinals), "ok"


def control_signature(view, sid):
    writers = view.writes.get(sid, [])
    if not writers:
        return None, "no_writer"
    if len(writers) != 1:
        return None, "multiple_writers"
    oid = writers[0]
    key, reason = view.group_key(sid, oid)
    if key is None:
        return None, reason
    args = view.ops[oid][4]
    return {"group": key, "enable": args[0], "mask": args[2]}, "eligible"


def signature_digest(signature):
    payload = json.dumps(signature, separators=(",", ":"), sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


def m_iso(view, fam_sets):
    rows, member_digests, candidates = [], {}, []
    reasons_all = Counter()
    by_size = {bucket: {"families": 0, "isomorphic": 0} for bucket in SIZE_BUCKETS}
    iso_members = 0
    for key, members in fam_sets.items():
        ordinals = {m["name"]: i for i, m in enumerate(members)}
        digests, reasons = {}, Counter()
        for m in members:
            sig, reason = update_signature(view, m["sid"], m["name"], ordinals)
            if sig is None:
                reasons[reason] += 1
                dig = None
            else:
                dig = signature_digest(sig)
                digests[m["name"]] = dig
            member_digests[m["name"]] = dig
        classes = len(set(digests.values()))
        isomorphic = classes == 1 and not reasons
        row = {"module": key[0], "stem": key[1], "members": len(members),
               "bits": sum(m["width"] for m in members),
               "signature_classes": classes, "isomorphic": isomorphic}
        if reasons:
            row["unsigned"] = dict(sorted(reasons.items()))
        rows.append(row)
        reasons_all.update(reasons)
        bucket = by_size[size_bucket(len(members))]
        bucket["families"] += 1
        bucket["isomorphic"] += int(isomorphic)
        if isomorphic:
            iso_members += len(members)
            candidates.append({"module": key[0], "stem": key[1], "bits": row["bits"],
                               "members": [m["name"] for m in members]})
    total = len(rows)
    isomorphic = sum(int(r["isomorphic"]) for r in rows)
    total_members = sum(r["members"] for r in rows)
    report = {"family_count": total, "isomorphic_families": isomorphic,
              "isomorphic_family_ratio": isomorphic / total if total else None,
              "family_members": total_members, "isomorphic_members": iso_members,
              "isomorphic_member_ratio": iso_members / total_members if total_members else None,
              "by_size": by_size, "unsigned_reasons": dict(sorted(reasons_all.items())),
              "families": rows}
    return report, member_digests, candidates


def m_ctrl(view, fam_sets):
    rows, member_digests, mergeable = [], {}, {}
    rejected_all = Counter()
    sub_counts, eligible = [], 0
    sub_total = merge_sub_total = merge_members_total = merge_bits_total = 0
    for key, members in fam_sets.items():
        digests, reasons = {}, Counter()
        for m in members:
            sig, reason = control_signature(view, m["sid"])
            if sig is None:
                reasons[reason] += 1
                dig = None
            else:
                dig = signature_digest(sig)
                digests[m["name"]] = dig
                eligible += 1
            member_digests[m["name"]] = dig
        subs = Counter(digests.values())
        good = {dig for dig, n in subs.items() if n >= 2}
        merged = sorted(name for name, dig in digests.items() if dig in good)
        merged_bits = sum(m["width"] for m in members if m["name"] in set(merged))
        row = {"module": key[0], "stem": key[1], "members": len(members),
               "subfamilies": len(subs), "mergeable_subfamilies": len(good),
               "mergeable_members": len(merged), "mergeable_bits": merged_bits}
        if reasons:
            row["rejected"] = dict(sorted(reasons.items()))
        rows.append(row)
        mergeable[key] = merged
        sub_counts.append(len(subs))
        rejected_all.update(reasons)
        sub_total += len(subs)
        merge_sub_total += len(good)
        merge_members_total += len(merged)
        merge_bits_total += merged_bits
    report = {"note": CTRL_NOTE, "eligible_members": eligible,
              "rejected": dict(sorted(rejected_all.items())),
              "subfamilies": sub_total, "mergeable_subfamilies": merge_sub_total,
              "mergeable_members": merge_members_total, "mergeable_bits": merge_bits_total,
              "subfamilies_per_family": distribution(sub_counts),
              "families": rows}
    return report, member_digests, mergeable


def pack_cross_check(words, member_digests):
    """Words whose signed members do not all share one signature.

    Returns (report, violating_words); the caller decides whether the
    comparison is a hard gate (M-ctrl) or informational (M-iso).
    """
    eligible = mismatches = 0
    samples, violating = [], []
    for word, entries in sorted(words.items()):
        found = defaultdict(list)
        for _, member, _ in entries:
            dig = member_digests.get(member)
            if dig is not None:
                found[dig].append(member)
        if sum(len(members) for members in found.values()) < 2:
            continue
        eligible += 1
        if len(found) > 1:
            mismatches += 1
            violating.append(word)
            if len(samples) < 10:
                samples.append({"word": word, "classes": {dig: sorted(ms)[:5]
                                                          for dig, ms in sorted(found.items())}})
    report = {"available": True, "words_total": len(words), "words_checked": eligible,
              "mismatches": mismatches, "mismatch_samples": samples}
    return report, violating


def structural_control_signature(view, sid, self_name, ordinals):
    """Control signature with enable/mask value identity replaced by the
    structural digest of their cones (post-lower predates canonicalize-compute,
    so identical enable logic may still carry distinct value ids there)."""
    writers = view.writes.get(sid, [])
    if not writers:
        return None, "no_writer"
    if len(writers) != 1:
        return None, "multiple_writers"
    oid = writers[0]
    key, reason = view.group_key(sid, oid)
    if key is None:
        return None, reason
    args = view.ops[oid][4]
    return {"group": key,
            "enable": cone_signature(view, [args[0]], self_name, ordinals),
            "mask": cone_signature(view, [args[2]], self_name, ordinals)}, "eligible"


def explain_ctrl_violations(view, words, violating_words, fam_sets, member_digests):
    """Re-judge violating words under structural enable/mask signatures."""
    member_info = {}
    for members in fam_sets.values():
        ordinals = {m["name"]: i for i, m in enumerate(members)}
        for m in members:
            member_info[m["name"]] = (m["sid"], ordinals)
    explained = 0
    component_diffs = Counter()
    samples = []
    for word in sorted(violating_words):
        signed = []
        for _, member, _ in words[word]:
            if member_digests.get(member) is None or member not in member_info:
                continue
            sid, ordinals = member_info[member]
            sig, _ = structural_control_signature(view, sid, member, ordinals)
            signed.append((member, sig))
        if len({signature_digest(sig) for _, sig in signed}) <= 1:
            explained += 1
            continue

        def components(sig):
            group = sig["group"]
            return {"events": group[0], "edges": group[1], "history_initials": group[2],
                    "target_initial": group[3],
                    "enable_cone": signature_digest(sig["enable"]),
                    "mask_cone": signature_digest(sig["mask"])}

        per_member = [(member, components(sig)) for member, sig in signed]
        differing = [c for c in CTRL_GATE_COMPONENTS
                     if len({json.dumps(pm[1][c], sort_keys=True) for pm in per_member}) > 1]
        component_diffs.update(differing)
        if len(samples) < 10:
            samples.append({"word": word, "components_differing": differing,
                            "members": sorted(member for member, _ in per_member)})
    return {"explained_by_structural_unification": explained,
            "residual_violations": len(violating_words) - explained,
            "residual_component_diffs": dict(sorted(component_diffs.items())),
            "residual_samples": samples}


def dynamic_arm(final_model, fires, cycles, candidates, forms, words, universe,
                mergeable, top_n):
    view = Model(final_model)
    units, owners = unit_index(final_model)
    if set(fires) != units:
        raise ValueError("body-counter coverage mismatch")
    execs = {oid: fires[uid] for oid, uid in owners.items()}

    def price(ops):
        missing = ops - execs.keys()
        if missing:
            raise ValueError(f"{len(missing)} cone ops lack body counters")
        return sum(execs[oid] for oid in ops)

    state_ids = {}
    for state in final_model["states"]:
        state_ids.setdefault(view.text(state[1]), state[0])
    word_of, word_family = {}, {}
    if words is not None:
        for word, entries in words.items():
            keys, complete = set(), True
            for _, member, _ in entries:
                rec = universe["members"].get(member)
                if rec is None:
                    complete = False
                else:
                    keys.add((rec["module"], rec["stem"]))
                word_of[member] = word
            word_family[word] = next(iter(keys)) if complete and len(keys) == 1 else None

    def write_cone(sid):
        writers = view.writes.get(sid, [])
        if len(writers) != 1:
            return None
        local, _ = view.local(view.ops[writers[0]][4][:3])
        return local

    measured, mixed, incomplete = [], [], []
    incomplete_reasons = Counter()
    union, upper_union = set(), set()
    upper_mixed_words, upper_incomplete_cones, unattributable = set(), 0, 0
    for fam in candidates:
        key = (fam["module"], fam["stem"])
        member_forms = [forms[name] for name in fam["members"]]
        is_mixed = any(form == "packed" and word_family.get(word_of[name]) != key
                       for name, form in zip(fam["members"], member_forms))
        blocking = Counter(form for form in member_forms if form not in ("standalone", "packed"))
        ops, cones, word_cones, failed = set(), {}, {}, False
        for name, form in zip(fam["members"], member_forms):
            if form == "standalone":
                cone = write_cone(state_ids[name])
            elif form == "packed":
                word = word_of[name]
                if word not in word_cones:
                    word_cones[word] = (write_cone(state_ids[word])
                                        if word in state_ids else None)
                cone = word_cones[word]
            else:
                unattributable += 1
                continue
            if cone is None:
                failed = True
                continue
            ops |= cone
            cones[name] = cone
        upper_union |= ops
        if is_mixed:
            upper_mixed_words.update(w for w, cone in word_cones.items() if cone is not None)
            mixed.append(fam)
            continue
        if blocking or failed:
            upper_incomplete_cones += len(cones)
            incomplete_reasons.update(blocking)
            if failed:
                incomplete_reasons["member_without_single_final_writer"] += 1
            incomplete.append(fam)
            continue
        measured.append({"family": fam, "ops": ops, "cones": cones})
        union |= ops
    total_execs = sum(execs.values())
    union_execs = price(union)
    upper_execs = price(upper_union)
    sub_union, sub_members = set(), 0
    for entry in measured:
        wanted = set(mergeable.get((entry["family"]["module"], entry["family"]["stem"]), ()))
        for name in entry["family"]["members"]:
            if name in wanted:
                sub_members += 1
                sub_union |= entry["cones"][name]
    sub_execs = price(sub_union)
    rows = []
    for entry in measured:
        fam, ops = entry["family"], entry["ops"]
        rows.append({"module": fam["module"], "stem": fam["stem"],
                     "members": len(fam["members"]), "bits": fam["bits"],
                     "ops": len(ops), "execs": price(ops)})
    rows.sort(key=lambda r: (-r["execs"], r["module"], r["stem"]))
    for row in rows:
        row["execs_per_cycle"] = row["execs"] / cycles
        row["compute_share"] = row["execs"] / total_execs if total_execs else None
    return {"available": True, "cycles": cycles, "candidate_families": len(candidates),
            "measured_families": len(measured),
            "mixed_families": {"count": len(mixed), "bits": sum(f["bits"] for f in mixed),
                               "samples": [fam_label(f) for f in mixed[:10]]},
            "incomplete_families": {"count": len(incomplete),
                                    "bits": sum(f["bits"] for f in incomplete),
                                    "member_form_reasons": dict(sorted(incomplete_reasons.items()))},
            "union_ops": len(union), "union_execs": union_execs,
            "union_execs_per_cycle": union_execs / cycles,
            "compute_execs": total_execs, "compute_execs_per_cycle": total_execs / cycles,
            "compute_share": union_execs / total_execs if total_execs else None,
            "ctrl_mergeable_members": sub_members,
            "ctrl_mergeable_union_execs": sub_execs,
            "ctrl_mergeable_per_cycle": sub_execs / cycles,
            "ctrl_mergeable_share_of_union": sub_execs / union_execs if union_execs else None,
            "upper_bound": {"union_ops": len(upper_union), "union_execs": upper_execs,
                            "union_execs_per_cycle": upper_execs / cycles,
                            "compute_share": upper_execs / total_execs if total_execs else None,
                            "mixed_family_word_cones": len(upper_mixed_words),
                            "incomplete_family_member_cones": upper_incomplete_cones,
                            "unattributable_members": unattributable,
                            "note": UPPER_BOUND_NOTE},
            "top_families": rows[:top_n],
            "note": "per-family execs may overlap across families; union rows are deduplicated"}


def cones_match(view, name_a, roots_a, local_a, name_b, roots_b, local_b, ordinals):
    """Ordered bijection match between two cones (independent of the digest path).

    Operand order is significant, mirroring the cone_signature caliber; leaf
    labels are compared pointwise; internal ops must map bijectively.
    """
    if len(local_a) != len(local_b):
        return False
    map_ab, map_ba = {}, {}

    def match(va, vb):
        pa, pb = view.producer[va], view.producer[vb]
        internal_a, internal_b = pa in local_a, pb in local_b
        if internal_a != internal_b:
            return False
        if not internal_a:
            return (leaf_label(view, va, name_a, ordinals) ==
                    leaf_label(view, vb, name_b, ordinals))
        if pa in map_ab:
            return map_ab[pa] == pb
        if pb in map_ba:
            return False
        op_a, op_b = view.ops[pa], view.ops[pb]
        if (view.kind(pa) != view.kind(pb) or len(op_a[4]) != len(op_b[4]) or
                [view.width(v) for v in op_a[5]] != [view.width(v) for v in op_b[5]]):
            return False
        map_ab[pa] = pb
        map_ba[pb] = pa
        return all(match(x, y) for x, y in zip(op_a[4], op_b[4]))

    return all(match(va, vb) for va, vb in zip(roots_a, roots_b))


def verify_family_isomorphism(view, members):
    """Independent G3 checker: explicit ordered matching, no signature digests."""
    ordinals = {m["name"]: i for i, m in enumerate(members)}
    graphs = []
    for m in members:
        writers = view.writes.get(m["sid"], [])
        if len(writers) != 1:
            return False
        roots = view.ops[writers[0]][4][:3]
        local, _ = view.local(roots)
        graphs.append((m["name"], roots, local))
    name0, roots0, local0 = graphs[0]
    return all(cones_match(view, name0, roots0, local0, name, roots, local, ordinals)
               for name, roots, local in graphs[1:])


def sample_verify_isomorphism(view, fam_sets, iso_rows, sample_n, seed):
    """G3: re-judge a deterministic sample of families with the matcher."""
    if sample_n <= 0:
        return {"enabled": False}
    iso_keys = sorted((r["module"], r["stem"]) for r in iso_rows if r["isomorphic"])
    non_keys = sorted((r["module"], r["stem"]) for r in iso_rows if not r["isomorphic"])
    rng = random.Random(seed)
    each = sample_n // 2
    picked = ([(key, True) for key in rng.sample(iso_keys, min(each, len(iso_keys)))] +
              [(key, False) for key in rng.sample(non_keys, min(each, len(non_keys)))])
    agreements = disagreements = skipped = 0
    samples = []
    for key, expected in picked:
        members = fam_sets[key]
        writers = view.writes.get(members[0]["sid"], [])
        cone_size = None
        if len(writers) == 1:
            local, _ = view.local(view.ops[writers[0]][4][:3])
            cone_size = len(local)
        if cone_size is not None and cone_size > SAMPLE_CONE_LIMIT:
            skipped += 1
            continue
        verdict = verify_family_isomorphism(view, members)
        if verdict == expected:
            agreements += 1
        else:
            disagreements += 1
            if len(samples) < 10:
                samples.append({"family": {"module": key[0], "stem": key[1]},
                                "m_iso": expected, "verifier": verdict})
    checked = agreements + disagreements
    return {"enabled": True, "seed": seed, "requested": sample_n,
            "sampled_isomorphic": sum(1 for _, expected in picked if expected),
            "sampled_nonisomorphic": sum(1 for _, expected in picked if not expected),
            "skipped_large_cones": skipped, "agreements": agreements,
            "disagreements": disagreements,
            "agreement_rate": agreements / checked if checked else None,
            "disagreement_samples": samples}


def fmt_ratio(value):
    return "n/a" if value is None else f"{value:.4f}"


def render(report):
    u = report["universe"]
    fam = report["m_fam"]
    lines = ["# Declared pack census", "",
             f"Universe: {u['states']} declared logic states, {u['bits']} bits; "
             f"rejected: {u['rejected']}; declared symbols without logic state: "
             f"{u['declared_without_logic_state']}", "",
             "## M-fam same-origin families", "",
             f"Families: {fam['family_count']} ({fam['family_members']} members, "
             f"{fam['family_bits']} bits); singletons: {fam['singleton_count']} "
             f"({fam['singleton_bits']} bits); family bit share of universe: "
             f"{fmt_ratio(fam['family_bit_ratio'])}",
             f"Member distribution: {fam['member_distribution']}",
             f"Forms: {fam['forms']['counts']} (missing inputs: "
             f"{fam['forms']['missing_inputs']})", "",
             "| Family | Members | Bits | Forms |", "|---|---:|---:|---|"]
    top = sorted(fam["families"], key=lambda r: (-r["bits"], r["module"], r["stem"]))[:10]
    for row in top:
        lines.append(f"| {fam_label(row)} | {row['members']} | {row['bits']} | {row['forms']} |")
    align = report["m_align"]
    lines += ["", "## M-align packing alignment", ""]
    if align["available"]:
        lines += [f"Words: {align['word_count']} ({align['member_rows']} member rows); "
                  f"single-family words: {align['single_family_words']} "
                  f"(count ratio {fmt_ratio(align['single_family_word_ratio'])}, "
                  f"bit ratio {fmt_ratio(align['single_family_bit_ratio'])}); "
                  f"families split across words: {align['families_split_across_words']}"]
    else:
        lines.append(f"Unavailable: {align['reason']}")
    iso, ctrl = report["m_iso"], report["m_ctrl"]
    lines += ["", "## M-iso update-cone isomorphism", "",
              f"Isomorphic families: {iso['isomorphic_families']}/{iso['family_count']} "
              f"(members {iso['isomorphic_members']}/{iso['family_members']}); "
              f"unsigned reasons: {iso['unsigned_reasons']}",
              "", "## M-ctrl control-signature subfamilies", "",
              f"Mergeable subfamilies: {ctrl['mergeable_subfamilies']} "
              f"({ctrl['mergeable_members']} members, {ctrl['mergeable_bits']} bits); "
              f"mergeable by production form: {ctrl['mergeable_by_form']['members']}; "
              f"rejected: {ctrl['rejected']}", f"Note: {ctrl['note']}"]
    info, gate = report["m_align_iso_info"], report["m_align_ctrl_gate"]
    if info["available"]:
        lines.append(f"M-iso pack cross-check (informational): "
                     f"{info['mixed_signature_words']} mixed-signature words of "
                     f"{info['words_checked']} checked")
    else:
        lines.append(f"M-iso pack cross-check unavailable: {info['reason']}")
    if gate["available"]:
        explain = gate["explanation"]
        lines.append(f"M-ctrl pack cross-check (gate): {gate['violations']} violating words "
                     f"of {gate['words_checked']} checked; explained by structural "
                     f"unification: {explain['explained_by_structural_unification']}; "
                     f"residual: {explain['residual_violations']} "
                     f"{explain['residual_component_diffs']}")
    else:
        lines.append(f"M-ctrl pack cross-check unavailable: {gate['reason']}")
    sample = report["g3_sample_verify"]
    if sample["enabled"]:
        lines.append(f"G3 sample verify (seed {sample['seed']}): agreement "
                     f"{fmt_ratio(sample['agreement_rate'])} over {sample['agreements'] + sample['disagreements']} "
                     f"families ({sample['disagreements']} disagreements, "
                     f"{sample['skipped_large_cones']} skipped large cones)")
    dyn = report["m_dyn"]
    lines += ["", "## M-dyn dynamic share", ""]
    if dyn["available"]:
        lines += [f"Candidate families: {dyn['candidate_families']}; measured: "
                  f"{dyn['measured_families']}; mixed-word bucket: "
                  f"{dyn['mixed_families']['count']}; incomplete bucket: "
                  f"{dyn['incomplete_families']['count']}",
                  f"Union execs/cycle: {dyn['union_execs_per_cycle']:.6f} "
                  f"(compute share {fmt_ratio(dyn['compute_share'])}); "
                  f"M-ctrl mergeable sub-share: {dyn['ctrl_mergeable_per_cycle']:.6f}",
                  f"Upper bound (mixed words over-attributed as whole-word cones): "
                  f"{dyn['upper_bound']['union_execs_per_cycle']:.6f} execs/cycle "
                  f"(compute share {fmt_ratio(dyn['upper_bound']['compute_share'])})",
                  "", "| Family | Members | Execs/cycle | Compute share |",
                  "|---|---:|---:|---:|"]
        for row in dyn["top_families"][:10]:
            lines.append(f"| {fam_label(row)} | {row['members']} | "
                         f"{row['execs_per_cycle']:.6f} | {fmt_ratio(row['compute_share'])} |")
    else:
        lines.append(f"Unavailable: {dyn['reason']}")
    lines += ["", "## Closures", "", f"{report['closures']}"]
    return "\n".join(lines) + "\n"


def run(args):
    root = Path(__file__).resolve().parents[1]
    if not args.out_dir.resolve().is_relative_to(root / "ptmp"):
        raise ValueError("out-dir must be under repository ptmp")
    print("Loading post-lower dump", flush=True)
    post = json.loads(args.post_lower_json.read_bytes())
    view = Model(post)
    universe = build_universe(post)
    grouped = defaultdict(list)
    for rec in universe["members"].values():
        grouped[(rec["module"], rec["stem"])].append(rec)
    fam_sets = {key: sorted(members, key=lambda r: r["name"])
                for key, members in sorted(grouped.items()) if len(members) >= 2}
    singletons = sorted((rec for key, members in grouped.items() if len(members) == 1
                         for rec in members), key=lambda r: r["name"])
    print(f"Universe: {len(universe['members'])} states, {len(fam_sets)} families, "
          f"{len(singletons)} singletons", flush=True)
    print("Computing update-cone signatures (M-iso)", flush=True)
    iso_report, iso_member, candidates = m_iso(view, fam_sets)
    print("Computing control signatures (M-ctrl)", flush=True)
    ctrl_report, ctrl_member, mergeable = m_ctrl(view, fam_sets)
    sample_report = sample_verify_isomorphism(view, fam_sets, iso_report["families"],
                                              args.sample_verify, args.sample_seed)
    words = None
    if args.pack_members is not None and args.pack_members.is_file():
        print("Reading pack-members TSV", flush=True)
        words = read_pack_members(args.pack_members)
    reg2mem = None
    if args.reg_to_mem is not None and args.reg_to_mem.is_file():
        print("Reading reg-to-mem TSV", flush=True)
        reg2mem = read_reg_to_mem(args.reg_to_mem)
    missing = {"pack-members TSV": words is None, "reg-to-mem TSV": reg2mem is None}
    align_report = (m_align(words, universe) if words is not None else
                    unavailable("pack-members TSV not provided or missing"))
    if words is not None:
        raw, _ = pack_cross_check(words, iso_member)
        iso_info = {"available": True, "words_total": raw["words_total"],
                    "words_checked": raw["words_checked"],
                    "mixed_signature_words": raw["mismatches"],
                    "samples": raw["mismatch_samples"], "note": ISO_INFO_NOTE}
        raw, violating = pack_cross_check(words, ctrl_member)
        ctrl_gate = {"available": True, "words_total": raw["words_total"],
                     "words_checked": raw["words_checked"],
                     "violations": raw["mismatches"],
                     "violation_samples": raw["mismatch_samples"],
                     "explanation": explain_ctrl_violations(view, words, violating,
                                                            fam_sets, ctrl_member)}
    else:
        iso_info = unavailable("pack-members TSV not provided or missing")
        ctrl_gate = unavailable("pack-members TSV not provided or missing")
    packed_names = ({member for rows in words.values() for _, member, _ in rows}
                    if words is not None else None)
    del post, view
    gc.collect()
    final_model, final_names = None, None
    if args.final_json is not None and args.final_json.is_file():
        print("Loading final checkpoint", flush=True)
        final_model = json.loads(args.final_json.read_bytes())
        final_names = {final_model["strings"][s[1] - 1] if s[1] else ""
                       for s in final_model["states"]}
    missing["final checkpoint"] = final_names is None
    forms = classify_forms(universe["members"], final_names, packed_names, reg2mem)
    form_summary = summarize_forms(universe["members"], forms,
                                   {k for k, v in missing.items() if v})
    merge_form_counts, merge_form_bits = Counter(), Counter()
    for names in mergeable.values():
        for name in names:
            merge_form_counts[forms[name]] += 1
            merge_form_bits[forms[name]] += universe["members"][name]["width"]
    ctrl_report["mergeable_by_form"] = {"members": dict(sorted(merge_form_counts.items())),
                                        "bits": dict(sorted(merge_form_bits.items()))}
    fam_rows = []
    for key, members in fam_sets.items():
        widths = Counter(m["width"] for m in members)
        fam_rows.append({"module": key[0], "stem": key[1], "members": len(members),
                         "bits": sum(m["width"] for m in members),
                         "widths": dict(sorted(widths.items())),
                         "forms": dict(sorted(Counter(forms[m["name"]]
                                                    for m in members).items()))})
    sizes = [row["members"] for row in fam_rows]
    fam_bits = sum(row["bits"] for row in fam_rows)
    singleton_bits = sum(rec["width"] for rec in singletons)
    m_fam = {"family_count": len(fam_rows), "families": fam_rows,
             "singleton_count": len(singletons), "singleton_bits": singleton_bits,
             "family_members": sum(sizes), "family_bits": fam_bits,
             "universe_bits": universe["bits"],
             "family_bit_ratio": fam_bits / universe["bits"] if universe["bits"] else None,
             "member_distribution": distribution(sizes),
             "width_distribution": {}, "forms": form_summary}
    widths_all = defaultdict(lambda: [0, 0])
    for row in fam_rows:
        for width, count in row["widths"].items():
            widths_all[width][0] += count
            widths_all[width][1] += count * width
    m_fam["width_distribution"] = {w: {"members": widths_all[w][0], "bits": widths_all[w][1]}
                                   for w in sorted(widths_all)}
    runs_given = args.run1 is not None or args.run2 is not None
    if runs_given and (args.run1 is None or args.run2 is None):
        raise ValueError("dynamic arm requires both --run1 and --run2")
    gate, dyn_report = None, unavailable("run logs not provided (--run1/--run2)")
    if runs_given:
        if final_model is None:
            raise ValueError("dynamic arm requires --final-json")
        for path in (args.run1, args.run2):
            if not path.is_file():
                raise ValueError(f"run log missing: {path}")
        source_dir = args.final_json.parent / "model"
        if not source_dir.is_dir():
            raise ValueError(f"counter site source directory missing: {source_dir}")
        print("Checking dynamic closures (G4)", flush=True)
        fires, cycles, gate = check_dynamic(final_model, args.run1, args.run2, source_dir)
        print("Pricing candidate family cones (M-dyn)", flush=True)
        dyn_report = dynamic_arm(final_model, fires, cycles, candidates, forms, words,
                                 universe, mergeable, args.top_n)
    rejected_bits = sum(r["bits"] for r in universe["rejected"].values())
    form_total = sum(form_summary["counts"].values())
    closures = {"family_bits": fam_bits, "singleton_bits": singleton_bits,
                "rejected_bits": rejected_bits, "universe_bits": universe["bits"],
                "bit_closure": fam_bits + singleton_bits + rejected_bits == universe["bits"],
                "form_counts_total": form_total,
                "universe_members": len(universe["members"]),
                "form_closure": form_total == len(universe["members"])}
    if not closures["bit_closure"]:
        raise ValueError("family/singleton/rejected bit closure failed")
    if not closures["form_closure"]:
        raise ValueError("form classification closure failed")
    universe_public = {k: v for k, v in universe.items() if k != "members"}
    universe_public["states"] = len(universe["members"])
    report = {"schema": 1,
              "inputs": {"post_lower": args.post_lower_json.name,
                         "final": args.final_json.name if args.final_json else None,
                         "pack_members": args.pack_members.name if args.pack_members else None,
                         "reg_to_mem": args.reg_to_mem.name if args.reg_to_mem else None,
                         "run1": args.run1.name if args.run1 else None,
                         "run2": args.run2.name if args.run2 else None},
              "universe": universe_public, "closures": closures, "m_fam": m_fam,
              "m_align": align_report, "m_align_iso_info": iso_info,
              "m_align_ctrl_gate": ctrl_gate, "m_iso": iso_report, "m_ctrl": ctrl_report,
              "m_dyn": dyn_report, "dynamic_gate": gate,
              "g3_sample_verify": sample_report}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n")
    (args.out_dir / "summary.md").write_text(render(report))
    print(render(report), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--post-lower-json", type=Path, required=True,
                        help="raw post-lower dump (before packing), with declaredSymbols")
    parser.add_argument("--final-json", type=Path,
                        help="final checkpoint of the same design (carries the schedule)")
    parser.add_argument("--pack-members", type=Path,
                        help="diagnostic TSV: packed_state/bit_index/member_name/init_bit")
    parser.add_argument("--reg-to-mem", type=Path, help="flow reg_to_mem.tsv")
    parser.add_argument("--run1", type=Path, help="first dynamic run log")
    parser.add_argument("--run2", type=Path, help="second dynamic run log")
    parser.add_argument("--top-n", type=int, default=25,
                        help="M-dyn family ranking size (default 25)")
    parser.add_argument("--sample-verify", type=int, default=0,
                        help="G3: independently re-judge N sampled families (0=off)")
    parser.add_argument("--sample-seed", type=int, default=20260928,
                        help="deterministic sampling seed for --sample-verify")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
