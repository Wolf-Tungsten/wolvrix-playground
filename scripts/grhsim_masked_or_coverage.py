"""Read-only audit of maskedOr recovery coverage in a phase-attributed IR."""

import argparse
from array import array
from collections import Counter, defaultdict
import csv
from functools import lru_cache
import json
from pathlib import Path
import re
import time


def literal(text):
    if isinstance(text, (bool, int)):
        return int(text)
    match = re.fullmatch(r"(?:\d+)?'[sS]?([bodhBODH])([0-9a-fA-F_]+)", text)
    if match:
        return int(match[2].replace("_", ""), {"b": 2, "o": 8, "d": 10, "h": 16}[match[1].lower()])
    try:
        return int(text, 10)
    except ValueError:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--baseline-report", type=Path, default=Path("ptmp/masked-or-xs/masked-or.tsv"))
    parser.add_argument("--output", type=Path, default=Path("ptmp/mux1h-census"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    print("loading IR JSON", flush=True)
    model = json.loads(args.model.read_bytes())
    print(f"loaded in {time.monotonic() - start:.1f}s", flush=True)
    strings = [""] + model["strings"]
    types = [None] + model["types"]
    states = [None] + model["states"]
    values = [None] + model["values"]
    ops = [None] + model["operations"]
    origins = [None] + model["origins"]
    with args.report.open() as stream:
        recovered = list(csv.DictReader(stream, delimiter="\t"))
    expected = {int(row["root_before_compact"]) for row in recovered}
    producer = array("I", [0]) * len(values)
    uses = array("I", [0]) * len(values)
    consumer = array("I", [0]) * len(values)
    observed = bytearray(len(values))
    for op in model["operations"]:
        for result in op[5]:
            producer[result] = op[0]
        for operand in op[4]:
            uses[operand] += 1
            consumer[operand] = op[0]
    for decl in model.get("declProvenance", []):
        for part in decl[3]:
            if part[1] == "value":
                observed[part[2]] = 1

    def source(value):
        return ops[producer[value]]

    def kind(op):
        return strings[op[1]] if op else ""

    def value_type(value):
        return types[values[value][1]]

    def simple_type(t):
        return t[2] == "logic" and not t[4] and t[5] == "2-state"

    def scalar(value, max_width=None):
        t = value_type(value)
        return simple_type(t) and not t[6] and t[3] > 0 and (max_width is None or t[3] <= max_width)

    def param(op, key):
        for name, _, value in op[7]:
            if strings[name] == key:
                return value
        return None

    @lru_cache(maxsize=None)
    def constant(value):
        op = source(value)
        if kind(op) != "core.compute.constant" or not scalar(value, 64):
            return None
        for name, tag, data in op[7]:
            if strings[name] in ("value", "constValue") and tag in ("bool", "int", "string"):
                result = literal(data)
                return result & ((1 << value_type(value)[3]) - 1) if result is not None else None
        return None

    def is_or(op, type_id, phase):
        return (op and kind(op) == "core.compute.or" and op[8] == phase
                and len(op[4]) == 2 and len(op[5]) == 1 and not op[6] and not op[7]
                and values[op[5][0]][1] == type_id
                and all(values[v][1] == type_id for v in op[4]))

    def mask_bit(value, phase):
        if not scalar(value, 1):
            return None, "selector_not_bit"
        op = source(value)
        if kind(op) != "core.compute.sliceStatic" or len(op[4]) != 1 or op[8] != phase or op[6]:
            return None, "selector_not_packed_mask_slice"
        lo, hi = param(op, "sliceStart"), param(op, "sliceEnd")
        mask = op[4][0]
        if lo is None or lo != hi or lo < 0 or not scalar(mask, 64) or value_type(mask)[3] < 2:
            return None, "packed_mask_type_or_range"
        if lo >= value_type(mask)[3] or source(mask)[8] != phase:
            return None, "packed_mask_type_or_range"
        return (mask, lo), None

    def element(value, phase):
        op = source(value)
        name = kind(op)
        if op[8] != phase:
            return None, "array_phase"
        if (name == "core.state.readArray" and len(op[4]) == 1 and len(op[6]) == 1
                and op[6][0][0] == "state" and not op[7]):
            sid = op[6][0][1]
            array_type = types[states[sid][2]]
            identity = ("state", sid)
            index = constant(op[4][0])
        elif (name == "core.compute.sliceArray" and len(op[4]) == 2 and not op[6] and not op[7]):
            identity = ("value", op[4][0])
            array_type = value_type(op[4][0])
            index = constant(op[4][1])
            if source(op[4][0])[8] != phase:
                return None, "array_phase"
        else:
            return None, "data_not_direct_array_element"
        t = value_type(value)
        shape = array_type[6]
        if not simple_type(array_type) or len(shape) != 1 or not 2 <= shape[0] <= 64:
            return None, "array_shape_or_size"
        if index is None or index >= shape[0] or not scalar(value, 64) or array_type[3] != shape[0] * t[3]:
            return None, "array_element_type_or_index"
        return (identity, index, shape[0]), None

    def leaf(value, phase, width):
        op = source(value)
        if kind(op) == "core.compute.replicate" and param(op, "rep") == 1:
            return None, "leaf_replicate1_wrapper"
        if op[8] != phase or op[6] or op[7]:
            return None, "leaf_metadata_or_phase"
        name = kind(op)
        inputs = op[4]

        def pair(selector, data):
            bit, reason = mask_bit(selector, phase)
            if reason:
                return None, reason
            row, reason = element(data, phase)
            if reason:
                return None, reason
            if bit[1] != row[1]:
                return None, "mask_array_index_mismatch"
            if value_type(data)[3] != width:
                return None, "data_width"
            return (bit[0], *row), None

        if name in ("core.compute.mux", "core.compute.bitSelect") and len(inputs) == 3 and constant(inputs[2]) == 0:
            return pair(inputs[0], inputs[1])
        if name != "core.compute.and" or len(inputs) != 2:
            return None, "not_masked_leaf"
        failures = []
        for side in (0, 1):
            selector = inputs[side]
            if width != 1:
                replicate = source(selector)
                if (kind(replicate) != "core.compute.replicate" or replicate[8] != phase
                        or len(replicate[4]) != 1 or param(replicate, "rep") != width):
                    failures.append("wide_mask_not_replicate")
                    continue
                selector = replicate[4][0]
            result, reason = pair(selector, inputs[1 - side])
            if result:
                return result, None
            failures.append(reason)
        # Prefer the more specific failure of the orientation with a mask slice.
        for reason in failures:
            if reason not in ("selector_not_bit", "selector_not_packed_mask_slice", "wide_mask_not_replicate"):
                return None, reason
        return None, failures[0]

    def tree_debug(value, depth=3):
        op = source(value)
        t = value_type(value)
        record = {"value": value, "op": producer[value], "kind": kind(op),
                  "width": t[3], "shape": t[6], "phase": op[8]}
        if op[6]:
            record["refs"] = [[name, index, strings[states[index][1]] if name == "state" else ""]
                              for name, index in op[6]]
        if op[7]:
            record["params"] = [[strings[name], tag, data] for name, tag, data in op[7]]
        if depth:
            record["operands"] = [tree_debug(v, depth - 1) for v in op[4][:3]]
        return record

    def location(op):
        if not op[3]:
            return ""
        origin = origins[op[3]]
        return f"{strings[origin[4]]}:{origin[5]}:{origin[6]}"

    # The expanded matcher emits its candidate decisions. Independently check
    # each recovered tree against the original IR, including singleton views,
    # wide masks/results and preserved shared/declared boundaries.
    candidate_path = Path(str(args.report) + ".candidates.tsv")
    if recovered and "mode" in recovered[0] and candidate_path.exists():
        def two_state(value):
            t = value_type(value)
            return t[2] == "logic" and t[5] == "2-state" and t[3] > 0

        def same_width(value, width):
            return two_state(value) and value_type(value)[3] == width

        def alias(value, phase):
            op = source(value)
            if op[8] != phase or len(op[4]) != 1 or op[6]:
                return None
            width = value_type(value)[3]
            if not same_width(op[4][0], width) or source(op[4][0])[8] != phase:
                return None
            name = kind(op)
            if (name == "core.compute.assign" and not op[7]
                    or name == "core.compute.replicate" and param(op, "rep") == 1
                    or name == "core.compute.sliceStatic" and param(op, "sliceStart") == 0
                    and param(op, "sliceEnd") == width - 1):
                return op[4][0]
            return None

        def strip(value, phase):
            while (base := alias(value, phase)) is not None:
                value = base
            return value

        def broad_or(op, width, phase):
            return (kind(op) == "core.compute.or" and op[8] == phase
                    and len(op[4]) == 2 and len(op[5]) == 1 and not op[6] and not op[7]
                    and all(same_width(v, width) for v in op[4] + op[5]))

        def zero(value):
            op = source(value)
            if kind(op) != "core.compute.constant" or not two_state(value):
                return False
            for name, tag, data in op[7]:
                if strings[name] in ("constValue", "value"):
                    if data == "'0":
                        return True
                    parsed = literal(data)
                    return parsed is not None and parsed & ((1 << value_type(value)[3]) - 1) == 0
            return False

        def masked(value, phase, width):
            op = source(strip(value, phase))
            if op[8] != phase or op[6] or op[7]:
                return False
            inputs = op[4]

            def pair(select, data):
                return (same_width(select, 1) and two_state(data) and value_type(data)[3] >= width
                        and source(select)[8] == phase and source(data)[8] == phase)

            if (kind(op) == "core.compute.mux" or kind(op) == "core.compute.bitSelect" and width == 1):
                return len(inputs) == 3 and zero(inputs[2]) and pair(inputs[0], inputs[1])
            if kind(op) != "core.compute.and" or len(inputs) != 2:
                return False
            for side in (0, 1):
                select = strip(inputs[side], phase)
                if width != 1:
                    expanded = source(select)
                    if expanded[8] != phase or expanded[6] or len(expanded[4]) != 1:
                        continue
                    base = expanded[4][0]
                    if value_type(select)[3] < width or not (kind(expanded) == "core.compute.replicate"
                            and param(expanded, "rep") == value_type(select)[3]
                            or kind(expanded) == "core.compute.assign" and value_type(base)[4]):
                        continue
                    select = base
                if pair(select, inputs[1 - side]):
                    return True
            if width > 1:
                stack, visited = list(inputs), set()
                while stack:
                    value = strip(stack.pop(), phase)
                    if value in visited:
                        continue
                    visited.add(value)
                    node = source(value)
                    args = node[4]
                    if node[8] != phase or node[6] or not two_state(value) or value_type(value)[3] < width:
                        continue
                    if len(args) == 1 and same_width(args[0], 1) and source(args[0])[8] == phase:
                        if (kind(node) == "core.compute.replicate" and param(node, "rep") == value_type(value)[3]
                                or kind(node) == "core.compute.assign" and value_type(args[0])[4]):
                            return True
                    if (kind(node) == "core.compute.and" and len(args) == 2 and not node[7]
                            and all(two_state(v) and value_type(v)[3] >= width and source(v)[8] == phase for v in args)):
                        stack.extend(args)
            return False

        def tree(op):
            root, phase = op[5][0], op[8]
            width = value_type(root)[3]
            stack, leaves, internal = [root], [], set()
            while stack:
                value = stack.pop()
                node = source(value)
                if value == root or not observed[value] and uses[value] == 1:
                    if broad_or(node, width, phase):
                        internal.add(node[0])
                        stack.extend(node[4])
                        continue
                    if (base := alias(value, phase)) is not None:
                        stack.append(base)
                        continue
                leaves.append(value)
            return leaves, internal

        with candidate_path.open() as stream:
            decisions = list(csv.DictReader(stream, delimiter="\t"))
        baseline = set()
        if args.baseline_report.exists():
            with args.baseline_report.open() as stream:
                baseline = {int(r["root_before_compact"]) for r in csv.DictReader(stream, delimiter="\t")}
        legacy_pool = set()
        legacy_path = Path("ptmp/mux1h-census/ir-long-roots.csv")
        if legacy_path.exists():
            with legacy_path.open() as stream:
                legacy_pool = {int(r["root"]) for r in csv.DictReader(stream)
                               if r["all_masked_leaves"] == "True" and int(r["width"]) <= 64
                               and 16 <= int(r["terms"]) <= 64}
        covered_baseline, covered_legacy = set(), set()
        by_file, by_phase, by_mode, lengths, widths, sources = (Counter() for _ in range(6))
        details = []
        for row in recovered:
            op = ops[int(row["root_before_compact"])]; width = int(row["element_width"])
            leaves, internal = tree(op)
            if len(leaves) != int(row["terms"]) or not all(masked(v, op[8], width) for v in leaves):
                raise RuntimeError(f"independent recovery check failed: {row}")
            covered_baseline |= internal & baseline
            covered_legacy |= internal & legacy_pool
            loc = location(op)
            by_file[loc.rsplit(":", 2)[0]] += 1
            by_phase[row["phase"]] += 1; by_mode[row["mode"]] += 1
            lengths[int(row["terms"])] += 1; widths[width] += 1
            sources[(int(row["select_sources"]), int(row["data_sources"]))] += 1
            details.append({**row, "location": loc,
                            "result_names": [strings[values[v][2]] for v in op[5]]})
        reasons, rejected_kinds = Counter(), Counter()
        rejected_examples = []
        example_counts = Counter()
        for row in decisions:
            op = ops[int(row["root_before_compact"])]; width = int(row["element_width"])
            leaves, _ = tree(op)
            bad = [v for v in leaves if not masked(v, op[8], width)]
            if len(leaves) != int(row["terms"]) or bool(bad) != (row["reason"] != "recovered"):
                raise RuntimeError(f"independent candidate check failed: {row}")
            reasons[row["reason"]] += 1
            for value in bad:
                rejected_kinds[kind(source(strip(value, op[8])))] += 1
            for value in bad:
                example_key = (width, kind(source(strip(value, op[8]))))
                if example_counts[example_key] < 2:
                    rejected_examples.append({**row, "location": location(op),
                                              "leaf": tree_debug(value, 3)})
                    example_counts[example_key] += 1
        if baseline - covered_baseline:
            raise RuntimeError(f"baseline regions lost: {sorted(baseline - covered_baseline)[:20]}")
        summary = {
            "input": str(args.model), "recovered_roots": len(recovered),
            "recovered_terms": sum(int(r["terms"]) for r in recovered),
            "baseline_regions_retained": len(covered_baseline),
            "legacy_masked_pool": {"total": len(legacy_pool), "covered": len(covered_legacy),
                                   "remaining": sorted(legacy_pool - covered_legacy)},
            "recovered_by_phase": dict(by_phase), "recovered_by_mode": dict(by_mode),
            "recovered_terms_histogram": dict(sorted(lengths.items())),
            "recovered_width_histogram": dict(sorted(widths.items())),
            "recovered_by_file": dict(by_file.most_common()),
            "long_roots_by_reason": dict(reasons), "unmatched_leaf_kinds": dict(rejected_kinds.most_common()),
            "source_counts": [{"selectors": a, "data": b, "regions": n} for (a, b), n in sources.most_common()],
            "recovered": details, "rejection_examples": rejected_examples,
        }
        (args.output / "ir-coverage.json").write_text(json.dumps(summary, indent=2) + "\n")
        with (args.output / "ir-recovered.csv").open("w") as stream:
            writer = csv.DictWriter(stream, fieldnames=details[0].keys())
            writer.writeheader(); writer.writerows(details)
        print(json.dumps({k: v for k, v in summary.items()
                          if k not in ("recovered", "rejection_examples", "source_counts", "recovered_by_file")}), flush=True)
        print(f"independently verified all recovered regions and candidate decisions in {time.monotonic() - start:.1f}s", flush=True)
        return

    candidates = Counter()
    long_reasons = Counter()
    long_by_phase = Counter()
    long_widths = Counter()
    length_hist = Counter()
    covered = set()
    samples = defaultdict(list)
    rows = []
    all_masked_hist = Counter()
    recovered_rows = []
    masked_reasons = Counter()
    for op in model["operations"]:
        if op[8] not in ("event", "general", "output") or len(op[5]) != 1:
            continue
        result = op[5][0]
        if not scalar(result):
            continue
        tid, phase = values[result][1], op[8]
        if not is_or(op, tid, phase):
            continue
        if not observed[result] and uses[result] == 1 and is_or(ops[consumer[result]], tid, phase):
            continue
        width = value_type(result)[3]
        candidates["all_widths"] += 1
        if width <= 64:
            candidates["width_le64"] += 1
        stack, leaves = [result], []
        while stack and len(leaves) <= 4096:
            value = stack.pop()
            current = source(value)
            if (value == result or not observed[value] and uses[value] == 1) and is_or(current, tid, phase):
                stack.extend(reversed(current[4]))
            else:
                leaves.append(value)
        count = len(leaves)
        length_hist[count if not stack else ">4096"] += 1
        if count < 16:
            continue
        long_widths[width] += 1
        long_by_phase[phase] += 1
        simple_masked = all(
            kind(source(v)) == "core.compute.and"
            or (kind(source(v)) in ("core.compute.mux", "core.compute.bitSelect")
                and len(source(v)[4]) == 3 and constant(source(v)[4][2]) == 0)
            for v in leaves)
        if simple_masked:
            all_masked_hist[(width, count)] += 1
        first = None
        selected = set()
        reason = None
        failed_leaf = None
        if width > 64:
            reason = "result_width_gt64"
        elif count > 64 or stack:
            reason = "terms_gt64"
        else:
            for value in leaves:
                current, reason = leaf(value, phase, width)
                failed_leaf = value
                if reason:
                    break
                if first and current[:2] != first[:2]:
                    reason = "different_mask_or_array"
                    break
                if current[2] in selected:
                    reason = "duplicate_index"
                    break
                first = current if first is None else first
                selected.add(current[2])
            if reason is None and (count != value_type(first[0])[3] or count != first[3]):
                reason = "incomplete_array_or_mask"
        reason = reason or "recovered"
        long_reasons[reason] += 1
        if simple_masked and width <= 64 and count <= 64 and not stack:
            masked_reasons[reason] += 1
        if reason == "recovered":
            covered.add(op[0])
        record = {"root": op[0], "phase": phase, "terms": count, "width": width,
                  "reason": reason, "all_masked_leaves": simple_masked, "location": location(op)}
        if first:
            record["mask_value"] = first[0]
            record["array_kind"], record["array_id"] = first[1]
            if first[1][0] == "state":
                record["array_name"] = strings[states[first[1][1]][1]]
        rows.append(record)
        focus_tlb = "TLBFA" in record["location"] and width > 1
        if len(samples[reason]) < 6 or focus_tlb:
            example = {**record, "first_leaves": [tree_debug(v) for v in leaves[:2]]}
            if failed_leaf:
                example["failed_leaf"] = tree_debug(failed_leaf)
            if focus_tlb and consumer[result]:
                parent = ops[consumer[result]]
                if parent[5]:
                    example["consumer"] = tree_debug(parent[5][0], 1)
            samples[reason].append(example)
        if op[0] in expected:
            recovered_rows.append({**record, "root_debug": tree_debug(result, 0),
                                   "mask_debug": tree_debug(first[0], 2) if first else None})
    if covered != expected:
        raise RuntimeError(f"pass report mismatch: extra={sorted(covered - expected)[:20]} missing={sorted(expected - covered)[:20]}")
    field_counts = Counter(row["array_name"] for row in recovered_rows)
    summary = {
        "input": str(args.model), "candidates": dict(candidates),
        "long_roots_by_reason": dict(long_reasons), "long_roots_by_phase": dict(long_by_phase),
        "masked_roots_16_64_by_reason": dict(masked_reasons),
        "long_roots_by_width": dict(sorted(long_widths.items())),
        "or_tree_terms": dict(sorted(length_hist.items(), key=lambda p: str(p[0]))),
        "or_of_masked_terms": [{"width": w, "terms": n, "roots": count}
                               for (w, n), count in sorted(all_masked_hist.items())],
        "recovered_roots": len(covered), "recovered_distinct_arrays": len(field_counts),
        "recovered_by_array": dict(field_counts),
        "recovered": recovered_rows, "reason_examples": dict(samples),
    }
    with (args.output / "ir-long-roots.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(key for row in rows for key in row)))
        writer.writeheader()
        writer.writerows(rows)
    (args.output / "ir-coverage.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items()
                      if k not in ("recovered", "reason_examples", "recovered_by_array", "or_tree_terms", "or_of_masked_terms")}), flush=True)
    print(f"finished in {time.monotonic() - start:.1f}s", flush=True)


if __name__ == "__main__":
    main()
