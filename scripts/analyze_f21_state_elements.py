"""Compare post-DCE GRH state-array retention with GSIM split members."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from array import array
from collections import Counter, defaultdict
from pathlib import Path

from grhsim_f21_dce_compare import OPERANDS, RECORD_ID, RESULTS, int_array, module_name


OP_KIND = re.compile(r'"kind": "([^"]+)"')
OP_SYMBOL = re.compile(r'"sym": ("(?:\\.|[^"\\])*")')
REG_SYMBOL = re.compile(r'"regSymbol": \{"t": "string", "v": ("(?:\\.|[^"\\])*")\}')
CONST_VALUE = re.compile(r'"constValue": \{"t": "string", "v": ("(?:\\.|[^"\\])*")\}')
CONST_LITERAL = re.compile(r"(\d+)?'([sS]?)([bBoOdDhH])([0-9a-fA-F]+)")
UNSET32 = 0xFFFFFFFF
STATE_PORT_KINDS = {
    "kRegisterReadPort", "kRegisterReadArrayPort", "kRegisterWritePort",
    "kRegisterWriteMaskPort", "kRegisterWriteArrayPort", "kRegisterWriteArrayMaskPort",
    "kRegisterFillPort",
}
READ_KINDS = {"kRegisterReadPort", "kRegisterReadArrayPort"}
ARRAY_WRITE_KINDS = {"kRegisterWriteArrayPort", "kRegisterWriteArrayMaskPort"}


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def parse_const_literal(text: str) -> int | None:
    compact = text.replace("_", "").replace(" ", "")
    match = CONST_LITERAL.fullmatch(compact)
    if match is None:
        return None
    base = match.group(3).lower()
    radix = {"b": 2, "o": 8, "d": 10, "h": 16}[base]
    digits = match.group(4)
    if base == "d" and not digits.isdecimal():
        return None
    try:
        return int(digits, radix)
    except ValueError:
        return None


def attr_value(attrs: dict, key: str, default=None):
    attr = attrs.get(key)
    if not isinstance(attr, dict):
        return default
    if "v" in attr:
        return attr["v"]
    if "vs" in attr:
        return attr["vs"]
    return default


def element_count(shape: list[int]) -> int:
    count = 1
    for dim in shape:
        if dim <= 0:
            raise ValueError(f"invalid state shape {shape}")
        count *= dim
    return count


def linear_index(shape: list[int], indices: list[int]) -> int:
    index = 0
    for dim, item in zip(shape, indices):
        index = index * dim + item
    return index


def expand_static_indices(shape: list[int], indices: list[int]) -> set[int]:
    selected = {linear_index(shape, indices)}
    for dim_index in range(len(indices), len(shape)):
        stride = element_count(shape[dim_index + 1:])
        selected = {base + offset * stride for base in selected for offset in range(shape[dim_index])}
    return selected


def collect_grh(source: Path):
    states: dict[str, dict] = {}
    ports: dict[str, list[dict]] = defaultdict(list)
    constants: dict[int, int] = {}
    assign_source = array("I")
    stats = Counter()
    section = ""
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.startswith('      "vals":'):
                section = "vals"
                continue
            if line.startswith('      "ops":'):
                section = "ops"
                continue
            if section != "ops" or not line.startswith('        {"id":'):
                continue
            stats["ops"] += 1
            kind_match = OP_KIND.search(line)
            if kind_match is None:
                raise ValueError("operation without kind")
            kind = kind_match.group(1)
            if kind == "kRegister":
                record = json.loads(line.strip().rstrip(","))
                shape = attr_value(record.get("attrs", {}), "shape", [])
                stats["registers"] += 1
                if not shape:
                    continue
                symbol = record["sym"]
                if symbol in states:
                    raise ValueError(f"duplicate array register symbol: {symbol}")
                width = attr_value(record.get("attrs", {}), "width")
                if not isinstance(width, int) or width <= 0:
                    raise ValueError(f"invalid width for array register {symbol}: {width}")
                states[symbol] = {
                    "symbol": symbol,
                    "shape": shape,
                    "width": width,
                    "elements": element_count(shape),
                }
                stats["array_registers"] += 1
                continue
            if kind in STATE_PORT_KINDS:
                symbol_match = REG_SYMBOL.search(line)
                if symbol_match is None:
                    raise ValueError(f"state port without regSymbol: {kind}")
                symbol = json.loads(symbol_match.group(1))
                inputs = int_array(OPERANDS, line)
                if inputs is None:
                    raise ValueError(f"state port without operands: {kind}")
                index_values = []
                if kind == "kRegisterReadArrayPort":
                    index_values = inputs
                elif kind in ARRAY_WRITE_KINDS:
                    record = json.loads(line.strip().rstrip(","))
                    event_edges = attr_value(record.get("attrs", {}), "eventEdge", [])
                    payload_count = 2 if kind == "kRegisterWriteArrayMaskPort" else 1
                    index_count = len(inputs) - len(event_edges) - payload_count - 1
                    if index_count <= 0:
                        raise ValueError(f"invalid array write operands for {symbol}: {len(inputs)}")
                    index_values = inputs[1:index_count + 1]
                ports[symbol].append({
                    "kind": kind,
                    "indices": index_values,
                    "op": int(RECORD_ID.match(line[8:]).group(1)),
                })
                stats[f"port:{kind}"] += 1
                continue
            if kind == "kAssign":
                inputs = int_array(OPERANDS, line)
                results = int_array(RESULTS, line)
                if inputs is None or results is None:
                    raise ValueError("assign without operands/results")
                if len(inputs) == 1 and len(results) == 1:
                    result = results[0]
                    if result >= len(assign_source):
                        assign_source.extend(array("I", [UNSET32]) * (result + 1 - len(assign_source)))
                    assign_source[result] = inputs[0]
                stats["assigns"] += 1
                continue
            if kind == "kConstant":
                literal_match = CONST_VALUE.search(line)
                results = int_array(RESULTS, line)
                if literal_match is None or results is None or len(results) != 1:
                    raise ValueError("invalid constant record")
                value = parse_const_literal(json.loads(literal_match.group(1)))
                if value is not None:
                    constants[results[0]] = value
                stats["constants"] += 1
    for symbol in list(states):
        states[symbol]["ports"] = ports.get(symbol, [])
        states[symbol]["static_read_indices"] = set()
        states[symbol]["static_write_indices"] = set()
        states[symbol]["read_forms"] = Counter()
        states[symbol]["write_forms"] = Counter()
        states[symbol]["write_kinds"] = Counter()
    stats["state_ports_without_array_decl"] = sum(
        len(rows) for symbol, rows in ports.items() if symbol not in states)
    log(f"GRH state scan: {dict(stats)}")
    return states, constants, assign_source, stats


def resolve_constant(value: int, constants: dict[int, int], assign_source: array) -> int | None:
    for _depth in range(64):
        constant = constants.get(value)
        if constant is not None:
            return constant
        if value >= len(assign_source) or assign_source[value] == UNSET32:
            return None
        value = assign_source[value]
    return None


def classify_access(family: dict, port: dict, constants: dict[int, int], assign_source: array):
    kind = port["kind"]
    is_read = kind in READ_KINDS
    if kind in {"kRegisterReadPort", "kRegisterWritePort", "kRegisterWriteMaskPort", "kRegisterFillPort"}:
        form = {
            "kRegisterReadPort": "whole_read",
            "kRegisterWritePort": "whole_write",
            "kRegisterWriteMaskPort": "whole_mask_write",
            "kRegisterFillPort": "fill_write",
        }[kind]
        family["read_forms" if is_read else "write_forms"][form] += 1
        if not is_read:
            family["write_kinds"][kind] += 1
        return
    shape = family["shape"]
    indices = port["indices"]
    values = [resolve_constant(value, constants, assign_source) for value in indices]
    if any(value is None for value in values):
        form = "dynamic"
        touched = set()
    elif len(values) > len(shape) or any(value >= dim for value, dim in zip(values, shape)):
        form = "out_of_bounds"
        touched = set()
    else:
        touched = expand_static_indices(shape, values)
        form = "static_leaf" if len(values) == len(shape) else "static_partial"
    family["read_forms" if is_read else "write_forms"][form] += 1
    if not is_read:
        family["write_kinds"][kind] += 1
    if form.startswith("static_"):
        family["static_read_indices" if is_read else "static_write_indices"].update(touched)


def load_split_map(source: Path, states: dict[str, dict]):
    grouped: dict[str, list[dict]] = defaultdict(list)
    stats = Counter()
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.lstrip().startswith('{"parentId":'):
                continue
            stats["entries"] += 1
            record = json.loads(line.strip().rstrip(","))
            if record["parentName"] not in states:
                continue
            grouped[record["parentName"]].append(record)
            stats["matched_entries"] += 1
    log(f"GSIM split-map scan: {dict(stats)}")
    return grouped, stats


def load_parent_types(source: Path, grouped: dict[str, list[dict]]):
    parent_to_name = {rows[0]["parentId"]: name for name, rows in grouped.items() if rows}
    found = {}
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip() == '"edges": [':
                break
            if not line.lstrip().startswith('{"id":'):
                continue
            record_id = int(RECORD_ID.match(line.lstrip()).group(1))
            name = parent_to_name.get(record_id)
            if name is None:
                continue
            record = json.loads(line.strip().rstrip(","))
            found[name] = record
    log(f"GSIM parent scan: matched={len(found)}/{len(grouped)}")
    return found


def load_gsim_survivors(source: Path, member_map: dict[int, tuple[str, int]]):
    alive: dict[str, set[int]] = defaultdict(set)
    stats = Counter()
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip() == '"edges": [':
                break
            if not line.lstrip().startswith('{"id":'):
                continue
            stats["dumped_nodes"] += 1
            record_id = int(RECORD_ID.match(line.lstrip()).group(1))
            member = member_map.get(record_id)
            if member is None:
                continue
            record = json.loads(line.strip().rstrip(","))
            if record["status"] == "VALID_NODE":
                name, index = member
                alive[name].add(index)
                stats["surviving_members"] += 1
                stats[f"member_type:{record['type']}"] += 1
    log(f"GSIM post-DCE member scan: {dict(stats)}")
    return alive, stats


def read_group(forms: Counter) -> str:
    if not forms:
        return "none"
    keys = set(forms)
    if keys == {"static_leaf"}:
        return "static_leaf"
    if keys <= {"static_leaf", "static_partial"}:
        return "static_partial"
    if "whole_read" in keys:
        return "whole_or_mixed"
    if keys <= {"dynamic", "static_leaf", "static_partial"}:
        return "dynamic_or_mixed"
    return "other_mixed"


def write_group(family: dict) -> str:
    kinds = set(family["write_kinds"])
    forms = set(family["write_forms"])
    if not kinds:
        return "none"
    if kinds == {"kRegisterWritePort"}:
        return "whole"
    if kinds == {"kRegisterWriteMaskPort"}:
        return "whole_mask"
    if kinds <= ARRAY_WRITE_KINDS:
        if forms == {"static_leaf"}:
            return "array_static_leaf"
        if forms <= {"static_leaf", "static_partial"}:
            return "array_static_partial"
        return "array_dynamic_or_mixed"
    if kinds == {"kRegisterFillPort"}:
        return "fill"
    return "mixed"


def survival_bucket(total: int, alive: int) -> str:
    if alive == 0:
        return "0%"
    if alive == total:
        return "100%"
    ratio = alive / total
    if ratio < 0.25:
        return "(0%,25%)"
    if ratio < 0.50:
        return "[25%,50%)"
    if ratio < 0.75:
        return "[50%,75%)"
    return "[75%,100%)"


def counter_dict(counter: Counter) -> dict:
    return dict(sorted(counter.items()))


def compare_state_elements(grh: Path, gsim_init: Path, gsim_split: Path,
                           gsim_after: Path, out: Path) -> dict:
    states, constants, assign_source, grh_stats = collect_grh(grh)
    grouped, split_stats = load_split_map(gsim_split, states)
    parents = load_parent_types(gsim_init, grouped)
    member_map: dict[int, tuple[str, int]] = {}
    matched: dict[str, list[dict]] = {}
    mapping_issues = Counter()
    issue_examples = defaultdict(list)
    for name, rows in grouped.items():
        elements = states[name]["elements"]
        indices = {row["memberIndex"] for row in rows}
        parent = parents.get(name)
        issue = None
        if len(rows) != elements or indices != set(range(elements)):
            issue = "member_count_or_index_mismatch"
        elif parent is None:
            issue = "missing_original_parent"
        elif parent["type"] != "NODE_REG_SRC":
            issue = "parent_not_reg_src"
        if issue is not None:
            mapping_issues[issue] += 1
            if len(issue_examples[issue]) < 20:
                issue_examples[issue].append(name)
            continue
        matched[name] = rows
        for row in rows:
            member_map[row["memberId"]] = (name, row["memberIndex"])
    alive, gsim_stats = load_gsim_survivors(gsim_after, member_map)

    families = []
    totals = Counter()
    buckets = defaultdict(Counter)
    patterns = defaultdict(Counter)
    read_patterns = defaultdict(Counter)
    modules = defaultdict(Counter)
    static_read_agreement = Counter()
    for name, rows in matched.items():
        family = states[name]
        for port in family["ports"]:
            classify_access(family, port, constants, assign_source)
        total = family["elements"]
        surviving = alive.get(name, set())
        gsim_alive = len(surviving)
        static_reads = family["static_read_indices"]
        reads = read_group(family["read_forms"])
        writes = write_group(family)
        pattern = f"{reads}__{writes}"
        if total % len(rows) != 0:
            raise AssertionError(f"invalid member geometry for {name}")
        element_width = family["width"] // total
        record = {
            "symbol": name,
            "module": module_name(name),
            "shape": family["shape"],
            "packedWidth": family["width"],
            "elementWidth": element_width,
            "elements": total,
            "grhRetainedElements": total,
            "gsimRetainedElements": gsim_alive,
            "coarseSurplusElements": total - gsim_alive,
            "coarseSurplusBits": (total - gsim_alive) * element_width,
            "gsimSurvivingIndices": sorted(surviving),
            "grhStaticReadElements": len(static_reads),
            "grhStaticReadIndices": sorted(static_reads),
            "readGroup": reads,
            "writeGroup": writes,
            "readForms": counter_dict(family["read_forms"]),
            "writeForms": counter_dict(family["write_forms"]),
            "writeKinds": counter_dict(family["write_kinds"]),
            "parentWidth": rows[0]["parentWidth"],
            "parentDimension": rows[0]["parentDimension"],
            "shapeExact": family["shape"] == rows[0]["parentDimension"],
        }
        families.append(record)
        totals["families"] += 1
        totals["elements"] += total
        totals["gsim_retained_elements"] += gsim_alive
        totals["coarse_surplus_elements"] += total - gsim_alive
        totals["bits"] += family["width"]
        totals["gsim_retained_bits"] += gsim_alive * element_width
        totals["coarse_surplus_bits"] += (total - gsim_alive) * element_width
        totals["static_read_elements"] += len(static_reads)
        totals["shape_exact_families"] += int(record["shapeExact"])
        if gsim_alive == 0:
            totals["gsim_all_removed_families"] += 1
        elif gsim_alive == total:
            totals["gsim_all_retained_families"] += 1
        else:
            totals["gsim_partially_retained_families"] += 1
        bucket = survival_bucket(total, gsim_alive)
        for key, value in (("families", 1), ("elements", total),
                           ("gsim_retained_elements", gsim_alive),
                           ("coarse_surplus_elements", total - gsim_alive)):
            buckets[bucket][key] += value
        for group, key in ((patterns, pattern), (read_patterns, reads)):
            group[key]["families"] += 1
            group[key]["elements"] += total
            group[key]["gsim_retained_elements"] += gsim_alive
            group[key]["coarse_surplus_elements"] += total - gsim_alive
        module = record["module"]
        modules[module]["families"] += 1
        modules[module]["elements"] += total
        modules[module]["gsim_retained_elements"] += gsim_alive
        modules[module]["coarse_surplus_elements"] += total - gsim_alive
        if reads == "static_leaf":
            if gsim_alive == len(static_reads):
                static_read_agreement["equal"] += 1
            elif gsim_alive < len(static_reads):
                static_read_agreement["gsim_fewer"] += 1
            else:
                static_read_agreement["gsim_more"] += 1

    families.sort(key=lambda row: (-row["coarseSurplusElements"], row["symbol"]))

    def ranked_groups(groups: dict[str, Counter], limit=40):
        return [
            {"name": name, **counter_dict(values)}
            for name, values in sorted(groups.items(),
                                       key=lambda item: (-item[1]["coarse_surplus_elements"], item[0]))[:limit]
        ]

    total_elements = totals["elements"]
    retained = totals["gsim_retained_elements"]
    report = {
        "schema": "wolvrix.f21.state-element-distribution.v1",
        "inputs": {
            "grh_post_dce": str(grh),
            "gsim_original_init": str(gsim_init),
            "gsim_split_map": str(gsim_split),
            "gsim_post_dce": str(gsim_after),
        },
        "semantics": {
            "grhRetainedElements": "All elements of each surviving aggregate kRegister; structural retention, not proven necessary.",
            "gsimRetainedElements": "VALID_NODE split members in the GSIM post-RemoveDeadNodes dump, mapped by memberId.",
            "coarseSurplusElements": "GrhSIM aggregate elements minus GSIM surviving members; an upper-bound representation gap, not a predicted safe DCE deletion count.",
            "grhStaticReadElements": "Unique leaf elements touched by statically resolved full or partial reads; dynamic reads are excluded.",
        },
        "totals": {
            **counter_dict(totals),
            "grh_array_registers": grh_stats["array_registers"],
            "split_parent_name_matches": len(grouped),
            "matched_state_families": len(matched),
            "gsim_retention_ratio": retained / total_elements if total_elements else 1.0,
            "coarse_surplus_ratio": (total_elements - retained) / total_elements if total_elements else 0.0,
        },
        "mapping": {
            "issues": counter_dict(mapping_issues),
            "issue_examples": dict(sorted(issue_examples.items())),
            "split_map": counter_dict(split_stats),
            "gsim_dump": counter_dict(gsim_stats),
        },
        "survival_distribution": ranked_groups(buckets),
        "read_write_patterns": ranked_groups(patterns),
        "read_patterns": ranked_groups(read_patterns),
        "static_leaf_read_agreement": counter_dict(static_read_agreement),
        "top_modules": [
            {"module": name, **counter_dict(values)}
            for name, values in sorted(modules.items(),
                                       key=lambda item: (-item[1]["coarse_surplus_elements"], item[0]))[:40]
        ],
        "top_families": families[:100],
        "families": families,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log(f"wrote state element report to {out}")
    return report


def collect_register_names(source: Path):
    aggregate = set()
    registers = set()
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.startswith('        {"id":') or '"kind": "kRegister"' not in line:
                continue
            record = json.loads(line.strip().rstrip(","))
            name = record["sym"]
            registers.add(name)
            if attr_value(record.get("attrs", {}), "shape", []):
                aggregate.add(name)
    log(f"post-split register scan: total={len(registers)}, aggregate={len(aggregate)}")
    return aggregate, registers


def compare_post_split_state_elements(grh_before: Path, grh_after: Path, gsim_init: Path,
                                      gsim_split: Path, gsim_after: Path, out: Path) -> dict:
    states, _constants, _aliases, _grh_stats = collect_grh(grh_before)
    after_aggregate, after_registers = collect_register_names(grh_after)
    grouped, split_stats = load_split_map(gsim_split, states)
    parents = load_parent_types(gsim_init, grouped)
    member_map: dict[int, tuple[str, int]] = {}
    matched: dict[str, list[dict]] = {}
    mapping_issues = Counter()
    issue_examples = defaultdict(list)
    for name, rows in grouped.items():
        elements = states[name]["elements"]
        indices = {row["memberIndex"] for row in rows}
        parent = parents.get(name)
        issue = None
        if len(rows) != elements or indices != set(range(elements)):
            issue = "member_count_or_index_mismatch"
        elif parent is None:
            issue = "missing_original_parent"
        elif parent["type"] != "NODE_REG_SRC":
            issue = "parent_not_reg_src"
        if issue is not None:
            mapping_issues[issue] += 1
            if len(issue_examples[issue]) < 20:
                issue_examples[issue].append(name)
            continue
        matched[name] = rows
        for row in rows:
            member_map[row["memberId"]] = (name, row["memberIndex"])
    gsim_alive, gsim_stats = load_gsim_survivors(gsim_after, member_map)

    totals = Counter()
    families = []
    modules = defaultdict(Counter)
    for name, rows in matched.items():
        total = states[name]["elements"]
        gsim_indices = gsim_alive.get(name, set())
        if name in after_aggregate:
            grh_indices = set(range(total))
            representation = "aggregate"
        else:
            grh_indices = {row["memberIndex"] for row in rows if row["memberName"] in after_registers}
            representation = "members"
        gsim_count = len(gsim_indices)
        grh_count = len(grh_indices)
        exact = grh_indices == gsim_indices
        surplus = max(grh_count - gsim_count, 0)
        fewer = max(gsim_count - grh_count, 0)
        element_width = states[name]["width"] // total
        record = {
            "symbol": name,
            "module": module_name(name),
            "shape": states[name]["shape"],
            "elementWidth": element_width,
            "elements": total,
            "representation": representation,
            "grhRetainedElements": grh_count,
            "gsimRetainedElements": gsim_count,
            "grhSurvivingIndices": sorted(grh_indices),
            "gsimSurvivingIndices": sorted(gsim_indices),
            "exactMemberSet": exact,
            "remainingSurplusElements": surplus,
            "grhFewerElements": fewer,
        }
        families.append(record)
        totals["families"] += 1
        totals["elements"] += total
        totals["grh_retained_elements"] += grh_count
        totals["gsim_retained_elements"] += gsim_count
        totals["grh_removed_elements"] += total - grh_count
        totals["gsim_removed_elements"] += total - gsim_count
        totals["remaining_surplus_elements"] += surplus
        totals["grh_fewer_elements"] += fewer
        totals["remaining_surplus_bits"] += surplus * element_width
        totals["grh_fewer_bits"] += fewer * element_width
        totals[f"representation:{representation}"] += 1
        totals["exact_families" if exact else "different_families"] += 1
        module = record["module"]
        modules[module]["families"] += 1
        modules[module]["elements"] += total
        modules[module]["grh_retained_elements"] += grh_count
        modules[module]["gsim_retained_elements"] += gsim_count
        modules[module]["remaining_surplus_elements"] += surplus
        modules[module]["grh_fewer_elements"] += fewer

    families.sort(key=lambda row: (-row["remainingSurplusElements"], row["grhFewerElements"], row["symbol"]))
    report = {
        "schema": "wolvrix.f21.post-split-state-element-distribution.v1",
        "inputs": {
            "grh_before": str(grh_before),
            "grh_after": str(grh_after),
            "gsim_original_init": str(gsim_init),
            "gsim_split_map": str(gsim_split),
            "gsim_post_dce": str(gsim_after),
        },
        "semantics": {
            "grhRetainedElements": "All elements of an unsplit aggregate, or surviving scalar member declarations after memberization.",
            "exactMemberSet": "Exact equality of GrhSIM and GSIM surviving member-index sets.",
            "remainingSurplusElements": "Nonnegative GrhSIM-minus-GSIM surviving member count, not a safe-deletion proof.",
            "grhFewerElements": "Nonnegative GSIM-minus-GrhSIM surviving member count.",
        },
        "totals": {
            **counter_dict(totals),
            "matched_state_families": len(matched),
            "grh_retention_ratio": totals["grh_retained_elements"] / totals["elements"] if totals["elements"] else 1.0,
            "gsim_retention_ratio": totals["gsim_retained_elements"] / totals["elements"] if totals["elements"] else 1.0,
        },
        "mapping": {
            "issues": counter_dict(mapping_issues),
            "issue_examples": dict(sorted(issue_examples.items())),
            "split_map": counter_dict(split_stats),
            "gsim_dump": counter_dict(gsim_stats),
        },
        "top_modules": [
            {"module": name, **counter_dict(values)}
            for name, values in sorted(modules.items(),
                                       key=lambda item: (-item[1]["remaining_surplus_elements"], item[0]))[:40]
        ],
        "top_families": families[:100],
        "families": families,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log(f"wrote post-split state element report to {out}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grh", required=True, type=Path)
    parser.add_argument("--grh-before", type=Path)
    parser.add_argument("--gsim-init", required=True, type=Path)
    parser.add_argument("--gsim-split-map", required=True, type=Path)
    parser.add_argument("--gsim-after", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.grh_before:
        report = compare_post_split_state_elements(args.grh_before, args.grh, args.gsim_init,
                                                   args.gsim_split_map, args.gsim_after, args.out)
    else:
        report = compare_state_elements(args.grh, args.gsim_init, args.gsim_split_map,
                                        args.gsim_after, args.out)
    print(json.dumps({"totals": report["totals"], "mapping_issues": report["mapping"]["issues"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
