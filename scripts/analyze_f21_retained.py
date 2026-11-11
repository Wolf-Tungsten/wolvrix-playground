"""Classify direct GRH associations for Nodes removed only by GSIM."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from grhsim_f21_dce_compare import SEMANTIC_IDS, load_nodes, module_name, parse_semantic_tree


OP_KIND = re.compile(r'"kind": "([^"]+)"')
STATE_KINDS = {
    "kRegister", "kLatch", "kRegisterReadPort", "kRegisterReadArrayPort", "kLatchReadPort",
    "kRegisterWritePort", "kRegisterWriteMaskPort", "kRegisterWriteArrayPort",
    "kRegisterWriteArrayMaskPort", "kRegisterFillPort", "kLatchWritePort",
}
EFFECT_KINDS = {
    "kInstance", "kBlackbox", "kSystemFunction", "kSystemTask", "kDpicImport", "kDpicCall", "kXMRWrite",
}


def read_names(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8") as stream:
        return {line.rstrip("\n") for line in stream if line.rstrip("\n")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grh", required=True, type=Path)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--unmatched", required=True, type=Path)
    parser.add_argument("--grh-survivors", required=True, type=Path)
    parser.add_argument("--gsim-survivors", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    names, name_to_id = load_nodes(args.candidates, args.unmatched)
    retained = read_names(args.grh_survivors) - read_names(args.gsim_survivors)
    if not retained:
        raise ValueError("empty GSIM-only deletion set")
    sid_to_gid, _guards, tree_stats = parse_semantic_tree(args.grh, name_to_id)
    declared = set()
    in_declared = False
    value_ports = Counter()
    op_kinds = Counter()
    categories = Counter()
    modules = defaultdict(Counter)
    examples = defaultdict(list)
    with args.grh.open("r", encoding="utf-8") as stream:
        for line in stream:
            stripped = line.strip()
            if stripped.startswith('"declaredSymbols": ['):
                payload = stripped.split(":", 1)[1].strip().rstrip(",")
                if payload != "[":
                    declared.update(json.loads(payload))
                    in_declared = False
                else:
                    in_declared = True
                continue
            if in_declared:
                if stripped.startswith("]"):
                    in_declared = False
                else:
                    declared.add(json.loads(stripped.rstrip(",")))
                continue
            if line.startswith('      "vals":'):
                section = "vals"
                continue
            if line.startswith('      "ops":'):
                section = "ops"
                continue
            if not line.startswith('        {"id":'):
                continue
            match = SEMANTIC_IDS.search(line)
            if match is None or not match.group(1):
                continue
            all_groups = set()
            for item in match.group(1).split(","):
                semantic_id = int(item)
                if semantic_id >= len(sid_to_gid):
                    raise ValueError(f"SemanticId {semantic_id} exceeds tree size")
                gid = sid_to_gid[semantic_id]
                if 0 < gid <= len(names):
                    all_groups.add(names[gid - 1])
            groups = all_groups & retained
            if not groups:
                continue
            if section == "vals":
                port = ('"in": true' in line or '"out": true' in line or '"inout": true' in line)
                for name in groups:
                    categories["with_multi_source_value" if len(all_groups) > 1 else "with_single_source_value"] += 1
                    if port:
                        categories["with_port"] += 1
                        value_ports[name] += 1
                        modules["with_port"][module_name(name)] += 1
                        if len(examples["with_port"]) < 20:
                            examples["with_port"].append(name)
                    else:
                        categories["with_value"] += 1
                continue
            if section != "ops":
                continue
            kind_match = OP_KIND.search(line)
            if kind_match is None:
                raise ValueError("operation without kind")
            kind = kind_match.group(1)
            for name in groups:
                categories["with_multi_source_op" if len(all_groups) > 1 else "with_single_source_op"] += 1
                op_kinds[kind] += 1
                modules[f"op:{kind}"][module_name(name)] += 1
                if len(examples[f"op:{kind}"]) < 10:
                    examples[f"op:{kind}"].append(name)
                if kind in STATE_KINDS:
                    categories["with_state_op"] += 1
                    modules["with_state_op"][module_name(name)] += 1
                    if len(examples["with_state_op"]) < 20:
                        examples["with_state_op"].append(name)
                elif kind in EFFECT_KINDS:
                    categories["with_effect_op"] += 1
                    modules["with_effect_op"][module_name(name)] += 1
                    if len(examples["with_effect_op"]) < 20:
                        examples["with_effect_op"].append(name)
                else:
                    categories["with_comb_op"] += 1

    for name in retained:
        if name in declared:
            categories["with_declared_symbol"] += 1
            modules["with_declared_symbol"][module_name(name)] += 1
            if len(examples["with_declared_symbol"]) < 20:
                examples["with_declared_symbol"].append(name)
    categories["total_gsim_only_removed"] = len(retained)
    report = {
        "schema": "wolvrix.f21.retained-associations.v1",
        "note": "Direct value/op associations, not a new liveness or root-causality proof. Categories overlap.",
        "tree": tree_stats,
        "categories": dict(sorted(categories.items())),
        "op_kind_associations": dict(sorted(op_kinds.items())),
        "top_modules": {key: values.most_common(20) for key, values in sorted(modules.items())},
        "examples": dict(sorted(examples.items())),
    }
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"categories": report["categories"], "op_kind_associations": report["op_kind_associations"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
