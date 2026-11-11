"""Trace selected retained GRH Nodes to roots without declared-symbol anchors."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from array import array
from collections import Counter, defaultdict, deque
from pathlib import Path

from grhsim_f21_dce_compare import (
    OPERANDS,
    RECORD_ID,
    RESULTS,
    SEMANTIC_IDS,
    int_array,
    load_nodes,
    parse_semantic_tree,
)

OP_KIND = re.compile(r'"kind": "([^"]+)"')
OP_SYMBOL = re.compile(r'"sym": ("(?:\\.|[^"\\])*")')
EFFECT_KIND = re.compile(r'"firrtl\.effectKind": \{"t": "string", "v": ("(?:\\.|[^"\\])*")\}')
REG_SYMBOL = re.compile(r'"(?:reg|latch)Symbol": \{"t": "string", "v": ("(?:\\.|[^"\\])*")\}')
UNSET32 = 0xFFFFFFFF
UNSET64 = 0xFFFFFFFFFFFFFFFF
BOUNDARY_KINDS = {
    "kInstance", "kBlackbox", "kSystemFunction", "kSystemTask",
    "kDpicImport", "kDpicCall", "kXMRWrite",
}
STATE_DECL_KINDS = {"kRegister", "kLatch"}
STATE_READ_KINDS = {"kRegisterReadPort", "kRegisterReadArrayPort", "kLatchReadPort"}
STATE_WRITE_KINDS = {
    "kRegisterWritePort", "kRegisterWriteMaskPort", "kRegisterWriteArrayPort",
    "kRegisterWriteArrayMaskPort", "kRegisterFillPort", "kLatchWritePort",
}
KIND_CODES = {name: index for index, name in enumerate(sorted(
    BOUNDARY_KINDS | STATE_DECL_KINDS | STATE_READ_KINDS | STATE_WRITE_KINDS |
    {"kAssign", "kConstant", "kOther"}
), start=1)}
KIND_NAMES = {index: name for name, index in KIND_CODES.items()}
KIND_NAMES[0] = "missing"


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def op_token(op_id: int) -> int:
    return (op_id << 1) | 1


def value_token(value_id: int) -> int:
    return value_id << 1


def trace_grh(source: Path, candidates: Path, unmatched: Path, names_path: Path,
              out: Path, max_path: int, summary_only: bool = False,
              direct_state_symbols: bool = False) -> dict:
    names, name_to_id = load_nodes(candidates, unmatched)
    targets = [line.rstrip("\n") for line in names_path.read_text().splitlines() if line.rstrip("\n")]
    if direct_state_symbols:
        for name in targets:
            if name not in name_to_id:
                name_to_id[name] = len(names)
                names.append(name)
    missing = sorted(set(targets) - set(names))
    if missing:
        raise ValueError(f"trace targets are outside candidates: {missing[:3]}")
    target_gids = {name_to_id[name] + 1: name for name in targets}
    direct_state_targets = set(targets) if direct_state_symbols else set()
    sid_to_gid, _guards, tree_stats = parse_semantic_tree(source, name_to_id)
    op_kinds = array("B")
    op_offsets = array("I", [0])
    operands = array("I")
    def_op = array("I")
    op_parents = array("Q")
    value_parents = array("Q")
    op_families: dict[int, str] = {}
    family_roots: dict[str, list[int]] = {}
    root_ops: set[int] = set()
    root_labels: dict[int, str] = {}
    root_values: set[int] = set()
    target_tokens: dict[int, list[str]] = {}
    state_array_targets: set[str] = set()
    slice_array_targets: set[str] = set()
    section = ""
    operation_records = 0
    value_records = 0

    def add_target(token: int, groups: set[int], kind: str | None = None) -> None:
        for gid in groups & target_gids.keys():
            name = target_gids[gid]
            target_tokens.setdefault(token, []).append(name)
            if kind == "kRegisterReadArrayPort":
                state_array_targets.add(name)
            elif kind == "kSliceArray":
                slice_array_targets.add(name)

    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.startswith('      "vals":'):
                section = "vals"
                continue
            if line.startswith('      "ops":'):
                section = "ops"
                continue
            if not section or not line.startswith('        {"id":'):
                continue
            record_id = int(RECORD_ID.match(line[8:]).group(1))
            semantic_ids = int_array(SEMANTIC_IDS, line) or []
            groups = {sid_to_gid[sid] for sid in semantic_ids if sid_to_gid[sid]}
            if section == "vals":
                while record_id >= len(def_op):
                    def_op.append(UNSET32)
                    value_parents.append(UNSET64)
                add_target(value_token(record_id), groups)
                if ('"in": true' in line or '"out": true' in line or '"inout": true' in line):
                    root_values.add(record_id)
                value_records += 1
                continue
            while record_id >= len(op_kinds):
                op_kinds.append(0)
                op_parents.append(UNSET64)
            kind_match = OP_KIND.search(line)
            if kind_match is None:
                raise ValueError(f"operation {record_id} lacks kind")
            kind = kind_match.group(1)
            op_kinds[record_id] = KIND_CODES.get(kind, KIND_CODES["kOther"])
            op_offsets.append(len(operands))
            inputs = int_array(OPERANDS, line)
            if inputs is None:
                raise ValueError(f"operation {record_id} lacks operands")
            operands.extend(inputs)
            results = int_array(RESULTS, line)
            if results is None:
                raise ValueError(f"operation {record_id} lacks results")
            for value in results:
                if value < len(def_op):
                    def_op[value] = record_id
            add_target(op_token(record_id), groups, kind)
            if kind in BOUNDARY_KINDS:
                root_ops.add(record_id)
                label = kind
                if kind == "kSystemTask":
                    effect_match = EFFECT_KIND.search(line)
                    effect = json.loads(effect_match.group(1)) if effect_match else "unspecified"
                    label = f"{kind}:{effect}"
                root_labels[record_id] = label
            if kind in STATE_DECL_KINDS | STATE_READ_KINDS | STATE_WRITE_KINDS:
                symbol_match = (OP_SYMBOL.search(line) if kind in STATE_DECL_KINDS
                                else REG_SYMBOL.search(line))
                if symbol_match is not None:
                    family = json.loads(symbol_match.group(1))
                    op_families[record_id] = family
                    if family in direct_state_targets and kind in STATE_READ_KINDS:
                        target_tokens.setdefault(op_token(record_id), []).append(family)
                    if kind in STATE_DECL_KINDS | STATE_WRITE_KINDS:
                        family_roots.setdefault(family, []).append(record_id)
            operation_records += 1
    op_offsets.append(len(operands))
    if operation_records + 1 != len(op_kinds) or len(op_offsets) != len(op_kinds) + 1:
        raise ValueError("operation IDs are not contiguous in the stored graph")
    missing_targets = sorted(set(targets) - {name for rows in target_tokens.values() for name in rows})
    if missing_targets:
        raise ValueError(f"trace targets have no direct op/value association: {missing_targets[:3]}")
    log(f"trace graph: values={value_records}, ops={operation_records}, operands={len(operands)}, "
        f"target entities={len(target_tokens)}")

    pending = deque()
    for value in sorted(root_values):
        token = value_token(value)
        value_parents[value] = token
        pending.append(token)
    for op in sorted(root_ops):
        token = op_token(op)
        op_parents[op] = token
        pending.append(token)
    found: dict[str, int] = {}

    def discover(token: int) -> None:
        for name in target_tokens.get(token, []):
            found.setdefault(name, token)

    for token in pending:
        discover(token)
    while pending and len(found) < len(targets):
        token = pending.popleft()
        if token & 1:
            op = token >> 1
            family = op_families.get(op)
            if family is not None:
                for other in family_roots.get(family, []):
                    if op_parents[other] == UNSET64:
                        other_token = op_token(other)
                        op_parents[other] = token
                        pending.append(other_token)
                        discover(other_token)
            for index in range(op_offsets[op], op_offsets[op + 1]):
                value = operands[index]
                if value < len(value_parents) and value_parents[value] == UNSET64:
                    value_parents[value] = token
                    value_token_id = value_token(value)
                    pending.append(value_token_id)
                    discover(value_token_id)
        else:
            value = token >> 1
            op = def_op[value] if value < len(def_op) else UNSET32
            if op != UNSET32 and op < len(op_parents) and op_parents[op] == UNSET64:
                op_parents[op] = token
                op_token_id = op_token(op)
                pending.append(op_token_id)
                discover(op_token_id)
    unresolved = sorted(set(targets) - found.keys())
    if unresolved:
        raise ValueError(f"no root path for {unresolved[:3]}")
    log(f"all {len(targets)} targets reached roots; remaining worklist={len(pending)}")

    if summary_only:
        group_roots: dict[str, Counter] = defaultdict(Counter)
        examples: dict[tuple[str, str], list[str]] = defaultdict(list)
        for name, start in found.items():
            token = start
            while True:
                parent = op_parents[token >> 1] if token & 1 else value_parents[token >> 1]
                if parent == token:
                    break
                if parent == UNSET64:
                    raise AssertionError(f"broken parent chain for {name}")
                token = parent
            if name in state_array_targets:
                group = "state_array"
            elif name in slice_array_targets or "clock" in name or "Clock" in name:
                group = "clock_or_residual_array"
            else:
                group = "other"
            root = root_labels[token >> 1] if token & 1 else "port"
            group_roots[group][root] += 1
            if len(examples[(group, root)]) < 10:
                examples[(group, root)].append(name)
        groups = {}
        for group, roots in sorted(group_roots.items()):
            groups[group] = {
                "count": sum(roots.values()),
                "roots": dict(sorted(roots.items())),
                "examples": {root: examples[(group, root)] for root in sorted(roots)},
            }
        report = {
            "schema": "wolvrix.f21.root-summary.v1",
            "mode": "port/effect roots and state-family propagation; declared-symbol anchors disabled",
            "rootSelection": "one first-discovered root per target; not unique root-causality proof",
            "directGroupPriority": ["kRegisterReadArrayPort", "kSliceArray or clock/Clock in name", "other"],
            "input": str(source),
            "tree": tree_stats,
            "entities": {"values": value_records, "ops": operation_records, "operands": len(operands)},
            "roots": {"ports": len(root_values), "boundary_ops": len(root_ops)},
            "summary": {"total": len(targets), "groups": groups},
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        log(f"wrote root summary to {out}")
        return report

    path_tokens: dict[str, list[int]] = {}
    path_ops: set[int] = set()
    path_values: set[int] = set()
    for name, start in found.items():
        path = []
        token = start
        while True:
            path.append(token)
            if token & 1:
                path_ops.add(token >> 1)
                parent = op_parents[token >> 1]
            else:
                path_values.add(token >> 1)
                parent = value_parents[token >> 1]
            if parent == token:
                break
            if parent == UNSET64:
                raise AssertionError(f"broken parent chain for {name}")
            token = parent
        path_tokens[name] = path

    labels: dict[tuple[str, int], dict] = {}
    section = ""
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.startswith('      "vals":'):
                section = "vals"
                continue
            if line.startswith('      "ops":'):
                section = "ops"
                continue
            if not section or not line.startswith('        {"id":'):
                continue
            record_id = int(RECORD_ID.match(line[8:]).group(1))
            wanted = ((section == "ops" and record_id in path_ops) or
                      (section == "vals" and record_id in path_values))
            if not wanted:
                continue
            semantic_ids = int_array(SEMANTIC_IDS, line) or []
            paths = sorted({names[sid_to_gid[sid] - 1] for sid in semantic_ids
                            if 0 < sid_to_gid[sid] <= len(names)})
            symbol_match = OP_SYMBOL.search(line)
            entity_kind = "op" if section == "ops" else "value"
            labels[(entity_kind, record_id)] = {
                "symbol": json.loads(symbol_match.group(1)) if symbol_match else None,
                "semanticPaths": paths[:8],
                "semanticIds": semantic_ids[:8],
            }
            kind_match = OP_KIND.search(line)
            if kind_match is not None:
                labels[(entity_kind, record_id)]["kind"] = kind_match.group(1)
                storage_match = REG_SYMBOL.search(line)
                if storage_match is not None:
                    labels[(entity_kind, record_id)]["storageSymbol"] = json.loads(storage_match.group(1))

    report_paths = {}
    for name, path in path_tokens.items():
        rows = []
        root_token = path[-1]
        root_op = root_token >> 1 if root_token & 1 else None
        root_kind = KIND_NAMES[op_kinds[root_op]] if root_op is not None else "port"
        root_label = (root_labels.get(root_op, root_kind)
                      if root_op is not None else "port")
        for position, token in enumerate(path):
            if position >= max_path and position != len(path) - 1:
                continue
            entity = token >> 1
            section = "op" if token & 1 else "value"
            row = {"entity": section, "id": entity}
            if token & 1:
                row["kind"] = KIND_NAMES[op_kinds[entity]]
            row.update(labels.get((section, entity), {}))
            if token == root_token:
                row["root"] = root_kind
                row["rootLabel"] = root_label
            rows.append(row)
        report_paths[name] = {
            "root": root_kind,
            "rootLabel": root_label,
            "entities": len(path),
            "truncated": len(path) > max_path + 1,
            "path": rows,
        }
    report = {
        "schema": "wolvrix.f21.root-trace.v1",
        "mode": "port/effect roots and state-family propagation; declared-symbol anchors disabled",
        "input": str(source),
        "tree": tree_stats,
        "entities": {"values": value_records, "ops": operation_records, "operands": len(operands)},
        "roots": {"ports": len(root_values), "boundary_ops": len(root_ops)},
        "targets": report_paths,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log(f"wrote root traces to {out}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grh", required=True, type=Path)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--unmatched", required=True, type=Path)
    parser.add_argument("--names", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--max-path", type=int, default=80)
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--direct-state-symbols", action="store_true")
    args = parser.parse_args()
    trace_grh(args.grh, args.candidates, args.unmatched, args.names, args.out, args.max_path,
              summary_only=args.summary_only, direct_state_symbols=args.direct_state_symbols)


if __name__ == "__main__":
    main()
