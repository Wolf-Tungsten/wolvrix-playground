"""Census implication-based absorption opportunities in 1-bit boolean op trees.

SV priority lowering (case / if-else path guards) accumulates negations of branch
conditions into large conjunction/disjunction trees. Many of those leaves are
locally redundant:

- in an and-tree, a negated leaf `not(A)` is absorbed by a positive leaf `B`
  when B implies not(A) (e.g. B = eq(x, C1), A = eq(x, C2), C1 != C2);
- in an and/or-tree, a positive leaf `L` is absorbed by another positive leaf
  `B` when B implies L (e.g. L is an or/and-tree containing B, or ne(x, C2)
  conflicting with B = eq(x, C1));
- in an or-tree, `or(B, not(A))` with A implying B is a tautology;
- duplicate leaves.

These are local boolean identities, valid in every consumer context (chain
conditions, write-port update conditions, plain logic). The implication engine
is structural: same-control distinct-constant eq patterns (the decoder idiom,
constants stored as SV literal strings) plus and/or-tree containment.

Leaves are counted twice: as "virtual" (whole-tree flattening; upper bound for
analysis) and as "exclusive" (reachable from the root through single-use
same-kind ops; the subset an in-place rewrite can actually remove without
cloning shared subtrees).
"""

import argparse
from array import array
from collections import Counter
import json
import re

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
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    with open(args.model, "rb") as handle:
        model = json.load(handle)
    ops = model["operations"]
    values = model["values"]
    types = {t[0]: t for t in model["types"]}
    strings = model["strings"]
    names = [strings[op[1] - 1] for op in ops]

    def is_1bit_2s(value):
        t = types[values[value - 1][1]]
        return t[2] == "logic" and t[3] == 1 and t[5] == "2-state"

    producer = array("I", [0]) * (len(values) + 1)
    uses = array("I", [0]) * (len(values) + 1)
    for op in ops:
        if op[5]:
            producer[op[5][0]] = op[0]
        for operand in op[4]:
            uses[operand] += 1

    interior = set()
    consumers = {}
    for op in ops:
        name = names[op[0] - 1]
        for operand in op[4]:
            src = producer[operand]
            if not src:
                continue
            src_name = names[src - 1]
            if src_name in AND_NAMES or src_name in OR_NAMES or src_name in NOT_NAMES:
                consumers.setdefault(operand, []).append(op[0])
            if (name in AND_NAMES and src_name in AND_NAMES) or \
               (name in OR_NAMES and src_name in OR_NAMES):
                interior.add(operand)

    def const_int(op_id):
        if not op_id or names[op_id - 1] != "core.compute.constant":
            return None
        for entry in ops[op_id - 1][7]:
            if len(entry) != 3:
                continue
            if entry[1] == "int" and 0 <= entry[2] < (1 << 64):
                return entry[2]
            if entry[1] == "string" and isinstance(entry[2], str):
                parsed = parse_sv_literal(entry[2])
                if parsed is not None and 0 <= parsed < (1 << 64):
                    return parsed
        return None

    def logic_width(value):
        t = types[values[value - 1][1]]
        return t[3] if t[2] == "logic" else 0

    def cmp_pattern(value, op_names=("core.compute.eq",)):
        """cmp(control, C) or cmp(and(control, M), V) -> (control, mask, val)."""
        op_id = producer[value]
        if not op_id or names[op_id - 1] not in op_names:
            return None
        operands = ops[op_id - 1][4]
        if len(operands) != 2:
            return None
        for side in (0, 1):
            const_val = const_int(producer[operands[side]])
            if const_val is None:
                continue
            other = operands[1 - side]
            width = logic_width(other)
            if width == 0 or width > 64:
                return None
            full = (1 << width) - 1
            other_op = producer[other]
            if other_op and names[other_op - 1] in AND_NAMES:
                and_operands = ops[other_op - 1][4]
                if len(and_operands) != 2:
                    return None
                for a_side in (0, 1):
                    mask_val = const_int(producer[and_operands[a_side]])
                    if mask_val is not None:
                        return (and_operands[1 - a_side], mask_val & full, const_val & full)
            return (other, full, const_val & full)
        return None

    def not_payload(value):
        op_id = producer[value]
        if op_id and names[op_id - 1] in NOT_NAMES and len(ops[op_id - 1][4]) == 1:
            return ops[op_id - 1][4][0]
        return None

    def flatten_virtual(root, kinds, limit=4096):
        """All leaves of the tree (through same-kind ops, sharing-agnostic)."""
        leaves = []
        stack = [root]
        while stack:
            value = stack.pop()
            if len(leaves) > limit:
                return None
            op_id = producer[value]
            if op_id and names[op_id - 1] in kinds and len(ops[op_id - 1][4]) == 2:
                stack.append(ops[op_id - 1][4][0])
                stack.append(ops[op_id - 1][4][1])
            else:
                leaves.append(value)
        return leaves

    def flatten_exclusive(root, kinds, limit=4096):
        """Leaves reachable from root through single-use same-kind ops."""
        leaves = []
        stack = [root]
        while stack:
            value = stack.pop()
            if len(leaves) > limit:
                return None
            op_id = producer[value]
            if (value != root and uses[value] != 1):
                leaves.append(value)
                continue
            if op_id and names[op_id - 1] in kinds and len(ops[op_id - 1][4]) == 2:
                stack.append(ops[op_id - 1][4][0])
                stack.append(ops[op_id - 1][4][1])
            else:
                leaves.append(value)
        return leaves

    def contradicts(pat_a, pat_b):
        return (pat_a[0] == pat_b[0] and
                (pat_a[1] & pat_b[1] & (pat_a[2] ^ pat_b[2])) != 0)

    def leaf_contradicts_patterns(value, patterns_by_control):
        """value (eq pattern, or and-tree containing one) contradicts a stored
        positive pattern."""
        pat = cmp_pattern(value)
        if pat is not None:
            for other in patterns_by_control.get(pat[0], ()):
                if contradicts(pat, other):
                    return True
            return False
        # and-tree containing a contradicting eq leaf
        leaves = flatten_virtual(value, AND_NAMES, limit=64)
        if leaves and len(leaves) > 1:
            for sub in leaves:
                pat = cmp_pattern(sub)
                if pat is None:
                    continue
                for other in patterns_by_control.get(pat[0], ()):
                    if contradicts(pat, other):
                        return True
        return False

    def implies_not(pos_patterns_by_control, neg_payload):
        or_leaves = flatten_virtual(neg_payload, OR_NAMES, limit=64)
        if not or_leaves:
            return False
        return all(leaf_contradicts_patterns(leaf, pos_patterns_by_control)
                   for leaf in or_leaves)

    def implies(pos_leaf, target):
        if pos_leaf == target:
            return True
        op_id = producer[target]
        name = names[op_id - 1] if op_id else None
        if name in OR_NAMES:
            leaves = flatten_virtual(target, OR_NAMES, limit=64)
            return bool(leaves) and any(implies(pos_leaf, leaf) for leaf in leaves)
        if name in AND_NAMES:
            leaves = flatten_virtual(target, AND_NAMES, limit=64)
            return bool(leaves) and any(leaf == pos_leaf for leaf in leaves)
        if name == "core.compute.ne":
            pat_b = cmp_pattern(pos_leaf)
            pat_t = cmp_pattern(target, op_names=("core.compute.ne",))
            return pat_b is not None and pat_t is not None and \
                pat_t[0] == pat_b[0] and (pat_b[1] & (pat_b[2] ^ pat_t[2])) != 0
        return False

    stats = Counter()
    context = Counter()

    for op in ops:
        name = names[op[0] - 1]
        if name not in AND_NAMES and name not in OR_NAMES:
            continue
        if len(op[5]) != 1 or not is_1bit_2s(op[5][0]):
            continue
        root = op[5][0]
        if root in interior:
            stats["interior_skipped"] += 1
            continue
        is_and = name in AND_NAMES
        kinds = AND_NAMES if is_and else OR_NAMES
        leaves = flatten_virtual(root, kinds)
        if leaves is None:
            stats["tree_too_deep"] += 1
            continue
        stats["and_trees" if is_and else "or_trees"] += 1
        stats["leaves_total"] += len(leaves)
        excl = flatten_exclusive(root, kinds)
        excl_set = set(excl) if excl else set()
        stats["excl_leaves_total"] += len(excl or [])

        uniq = set(leaves)
        stats["dup_leaves"] += len(leaves) - len(uniq)
        pos = [v for v in uniq if not_payload(v) is None]
        neg = [(v, not_payload(v)) for v in uniq if not_payload(v) is not None]
        pos_patterns = {}
        for v in pos:
            pat = cmp_pattern(v)
            if pat is not None:
                pos_patterns.setdefault(pat[0], []).append(pat)

        tree_removed = 0
        if is_and:
            for not_leaf, payload in neg:
                if pos_patterns and implies_not(pos_patterns, payload):
                    stats["not_leaves_removable_virtual"] += 1
                    tree_removed += 1
                    if not_leaf in excl_set:
                        stats["not_leaves_removable_excl"] += 1
        for leaf in pos:
            if any(b != leaf and implies(b, leaf) for b in pos):
                stats["pos_leaves_removable_virtual"] += 1
                tree_removed += 1
                if leaf in excl_set:
                    stats["pos_leaves_removable_excl"] += 1
        if not is_and:
            for not_leaf, payload in neg:
                if any(implies(payload, b) for b in pos):
                    stats["or_tautology"] += 1
                    tree_removed += 1
        if tree_removed:
            stats["affected_trees"] += 1
            for c in consumers.get(root, []):
                context[names[c - 1]] += 1

    print("== absorption census (virtual vs exclusive) ==")
    for key in sorted(stats):
        print(f"{stats[key]:10d}  {key}")
    print("== affected root consumer kinds ==")
    for key, count in sorted(context.items(), key=lambda kv: -kv[1])[:15]:
        print(f"{count:10d}  {key}")
    op_mix = Counter(names)
    print("== context ==")
    print(f"ops={len(ops)} values={len(values)} states={len(model['states'])}")
    for key in ("core.compute.and", "core.compute.or", "core.compute.not",
                "core.compute.logicNot", "core.compute.mux", "core.compute.eq"):
        print(f"{op_mix.get(key, 0):10d}  {key}")


if __name__ == "__main__":
    main()
