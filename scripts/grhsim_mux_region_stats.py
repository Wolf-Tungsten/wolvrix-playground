"""Census case-guard decomposition coverage for muxRegion formation.

Each SV case-derived prioritySelect condition vector has, by ingest construction
(wolvrix/lib/core/ingest.cpp:2100-2185), the form

    cond_i = and(C, m_i, not(m_0 | ... | m_{i-1}))

where C is the conjunction of outer path guards common to every arm, m_i is the
case item match, and the negated or-chain is the priority prefix. In control-flow
form (layered if-else) the priority prefix is provided by the nesting itself, so
the ladder only needs `if (C) { if (m_0) ... else if (m_1) ... }` — first-true(m
given C) equals first-true(cond) unconditionally (guard_i = C ∧ m_i ∧ ¬prior_i;
first true m_k under C makes prior_k false and guard_k = C ∧ m_k true, while all
earlier guards have m_j false).

Decomposition per condition vector:
- C = leaf intersection of all cond and-trees (hoisted as the enclosing if);
- m_i = a positive leaf of cond_i whose negation appears in every later cond
  (priority signature) and whose negations appear in every earlier cond of
  vector position >0;
- K_i = leftover positive junk leaves after dropping priority-negation leaves
  and locally absorbed leaves (leaf implied by m_i or by C);
- arms with empty K_i are strippable (ladder condition = m_i ∧ (C hoisted));
  arms with junk keep their original condition verbatim.

Reports fully/partially decomposable vectors and stripped condition counts.
"""

import argparse
from array import array
from collections import Counter
import json
import re
from pathlib import Path

AND_NAMES = {"core.compute.and", "core.compute.logicAnd"}
OR_NAMES = {"core.compute.or", "core.compute.logicOr"}
NOT_NAMES = {"core.compute.not", "core.compute.logicNot"}
LITERAL_RE = re.compile(r"\s*(?:(\d+)\s*)?'\s*[sS]?([bBoOdDhH])\s*([0-9a-fA-F_xXzZ?]+)\s*")


def parse_sv_literal(text):
    match = LITERAL_RE.fullmatch(text)
    if match:
        base = {"b": 2, "o": 8, "d": 10, "h": 16}[match.group(2).lower()]
        digits = match.group(3).replace("_", "")
        if any(c in digits.lower() for c in "xz?"):
            return None
        try:
            return int(digits, base)
        except ValueError:
            return None
    if re.fullmatch(r"\d[\d_]*", text):
        return int(text.replace("_", ""))
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    model = json.loads(args.model.read_bytes())
    ops, values, strings = model["operations"], model["values"], model["strings"]
    types = {t[0]: t for t in model["types"]}
    names = [strings[op[1] - 1] for op in ops]

    producer = array("I", [0]) * (len(values) + 1)
    uses = array("I", [0]) * (len(values) + 1)
    for op in ops:
        if op[5]:
            producer[op[5][0]] = op[0]
        for operand in op[4]:
            uses[operand] += 1

    def and_operands(value):
        op_id = producer[value]
        if op_id and names[op_id - 1] in AND_NAMES and len(ops[op_id - 1][4]) == 2:
            return ops[op_id - 1][4]
        return None

    def not_payload(value):
        op_id = producer[value]
        if op_id and names[op_id - 1] in NOT_NAMES and len(ops[op_id - 1][4]) == 1:
            return ops[op_id - 1][4][0]
        return None

    def leaves_of(root, limit=128):
        leaves = []
        stack = [root]
        while stack:
            value = stack.pop()
            if len(leaves) > limit:
                return None
            operands = and_operands(value)
            if operands is not None:
                stack.extend(operands)
            else:
                leaves.append(value)
        return leaves

    def const_int_op(op_id):
        if not op_id or names[op_id - 1] != "core.compute.constant":
            return None
        for entry in ops[op_id - 1][7]:
            if len(entry) == 3 and entry[1] == "int" and 0 <= entry[2] < (1 << 64):
                return entry[2]
            if len(entry) == 3 and entry[1] == "string" and isinstance(entry[2], str):
                parsed = parse_sv_literal(entry[2])
                if parsed is not None and 0 <= parsed < (1 << 64):
                    return parsed
        return None

    def eq_pattern(value):
        op_id = producer[value]
        if not op_id or names[op_id - 1] != "core.compute.eq":
            return None
        operands = ops[op_id - 1][4]
        if len(operands) != 2:
            return None
        for side in (0, 1):
            const_val = const_int_op(producer[operands[side]])
            if const_val is None:
                continue
            other = operands[1 - side]
            t = types[values[other - 1][1]]
            width = t[3] if t[2] == "logic" else 0
            if width == 0 or width > 64:
                return None
            return (other, (1 << width) - 1, const_val & ((1 << width) - 1))
        return None

    def implies_local(leaf, target):
        """leaf implies target (target or-tree contains leaf, or same value,
        or ne(control,C2) contradicted by leaf = eq(control,C1))."""
        if leaf == target:
            return True
        op_id = producer[target]
        if op_id and names[op_id - 1] in OR_NAMES and len(ops[op_id - 1][4]) == 2:
            stack = [target]
            while stack:
                value = stack.pop()
                tid = producer[value]
                if tid and names[tid - 1] in OR_NAMES and len(ops[tid - 1][4]) == 2:
                    stack.extend(ops[tid - 1][4])
                elif value == leaf:
                    return True
            return False
        if op_id and names[op_id - 1] == "core.compute.ne":
            pat_leaf = eq_pattern(leaf)
            operands = ops[op_id - 1][4]
            if pat_leaf is not None and len(operands) == 2:
                for side in (0, 1):
                    const_val = const_int_op(producer[operands[side]])
                    if const_val is None:
                        continue
                    other = operands[1 - side]
                    t = types[values[other - 1][1]]
                    width = t[3] if t[2] == "logic" else 0
                    if width == 0 or width > 64:
                        return False
                    if other == pat_leaf[0] and \
                            (pat_leaf[1] & (pat_leaf[2] ^ (const_val & ((1 << width) - 1)))) != 0:
                        return True
        return False

    stats = Counter()
    groups = {}
    for op in ops:
        if names[op[0] - 1] != "core.compute.prioritySelect":
            continue
        n = (len(op[4]) - 1) // 2
        conds = tuple(op[4][:n])
        groups.setdefault(conds, []).append(op)

    stats["psel_total"] = sum(len(v) for v in groups.values())
    stats["cond_vectors"] = len(groups)

    for conds in groups:
        n = len(conds)
        if n < 2:
            stats["n_lt_2"] += 1
            continue
        leaf_sets = []
        ok = True
        for cond in conds:
            leaves = leaves_of(cond)
            if leaves is None:
                ok = False
                break
            leaf_sets.append(set(leaves))
        if not ok:
            stats["too_deep"] += 1
            continue
        stats["vectors_examined"] += 1
        common = set.intersection(*leaf_sets)
        # match identification: positive leaf in cond_i (not common), whose
        # negation appears in every later cond
        matches = {}
        decomp_ok = True
        for i in range(n):
            candidates = []
            for leaf in leaf_sets[i] - common:
                if not_payload(leaf) is not None:
                    continue
                if all(any(not_payload(x) == leaf for x in leaf_sets[j]) for j in range(i + 1, n)):
                    candidates.append(leaf)
            if len(candidates) == 1:
                matches[i] = candidates[0]
            elif len(candidates) == 0:
                decomp_ok = False
                break
            else:
                decomp_ok = False
                break
        if not decomp_ok:
            stats["no_distinct_match"] += 1
            continue
        # verify priority structure: cond_i (i>=1) contains negations of all
        # earlier matches
        priority_ok = all(
            all(any(not_payload(x) == matches[j] for x in leaf_sets[i]) for j in range(i))
            for i in range(1, n))
        if not priority_ok:
            stats["priority_signature_broken"] += 1
            continue
        stats["vectors_decomposable"] += 1
        # junk after removing common, match, and priority-negation leaves;
        # absorb junk implied by the match or by a common leaf
        fully = True
        for i in range(n):
            junk = set()
            for leaf in leaf_sets[i]:
                if leaf in common or leaf == matches[i]:
                    continue
                payload = not_payload(leaf)
                if payload is not None and payload in {matches[j] for j in range(i)}:
                    continue  # priority negation
                junk.add(leaf)
            junk = {leaf for leaf in junk
                    if not implies_local(matches[i], leaf) and
                    not any(implies_local(c, leaf) for c in common)}
            if junk:
                fully = False
                stats["conds_kept_verbatim"] += 1
            else:
                stats["conds_stripped"] += 1
        if fully:
            stats["vectors_fully_stripped"] += 1

    print("== case-guard decomposition census ==")
    for key in sorted(stats):
        print(f"{stats[key]:10d}  {key}")


if __name__ == "__main__":
    main()
