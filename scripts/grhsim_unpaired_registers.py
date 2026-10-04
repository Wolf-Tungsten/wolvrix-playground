#!/usr/bin/env python3
"""Export declared logic states absent from the NO00027 strict register pairs.

Matching uses all non-event logic states, so filtering to declaredSymbols does
not hide normalization collisions. Array states are excluded. Reason labels
describe name/width matching failures, not why the circuit was transformed.
"""

import argparse
from collections import Counter, defaultdict
import csv
import gc
import hashlib
import json
from pathlib import Path

from grhsim_declared_pack_census import declared_names
from grhsim_gsim_module_compare import log, match_anchor_sets, normalize_name
from grhsim_paired_cone_diff import member_pairs


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_verified(path, expected_hash):
    log(f"loading {path}")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    require(digest == expected_hash, f"input hash differs from reference: {path}")
    return json.loads(raw)


def write_tsv(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("model", "gsim", "reference", "output"):
        parser.add_argument(f"--{arg}", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    require(args.output.resolve().is_relative_to(root / "ptmp"), "output must be under ptmp")
    args.output.mkdir(parents=True, exist_ok=True)
    reference = json.loads((args.reference / "summary.json").read_text())
    expected = reference["metrics"]["M-pair"]
    hashes = reference["gates"]["G1a"]["hashes"]

    model = load_verified(args.model, hashes["grhsim_final"])
    declared = declared_names(model)
    strings = model["strings"]
    types = {row[0]: row for row in model["types"]}
    states = []
    declared_arrays = 0
    for row in model["states"]:
        sid, name_idx, type_idx = row[:3]
        name, typ = strings[name_idx - 1], types[type_idx]
        if typ[2] == "array":
            declared_arrays += name in declared
            continue
        require(typ[2] == "logic", f"unexpected state type: {typ[2]}")
        if not name.startswith("__event_"):
            states.append((sid, name, typ[3]))
    ritems = [(name, width) for _sid, name, width in states]
    declared_states = [(sid, name, width) for sid, name, width in states if name in declared]
    require(len({name for _sid, name, _width in states}) == len(states), "duplicate state names")
    del model, strings, types, declared
    gc.collect()
    log(f"loaded {len(declared_states)} declared registers; loading gsim register names")

    graph = load_verified(args.gsim, hashes["gsim_json"])
    gitems = [(node["name"], node["width"]) for node in graph["nodes"]
              if node["type"] == "NODE_REG_SRC"]
    del graph
    gc.collect()
    log(f"loaded {len(gitems)} gsim registers; recomputing strict pairs")
    groups, _ug, _ur = match_anchor_sets(gitems, ritems)
    pairs, _gkeys, rkeys, _remainder = member_pairs(groups)
    paired_bits = sum(p["width"] for p in pairs)
    require(len(pairs) == expected["pairs"], "strict pair count differs from reference")
    require(paired_bits == expected["paired_bits"], "paired bits differ from reference")
    require(sum(w for _n, w in ritems) == expected["grhsim_total_bits"], "GrhSIM bits differ")
    require(sum(w for _n, w in gitems) == expected["gsim_total_bits"], "gsim bits differ")
    with (args.reference / "pairs.tsv").open(encoding="utf-8", newline="") as stream:
        archived = [(row["key"], int(row["width"]))
                    for row in csv.DictReader(stream, delimiter="\t")]
    require([(p["key"], p["width"]) for p in pairs] == archived,
            "strict pairs differ from archived pairs.tsv")

    gindex = defaultdict(list)
    for name, width in gitems:
        gindex[normalize_name(name)].append((name, width))
    rcounts = Counter((normalize_name(name), width) for name, width in ritems)
    gcounts = Counter((normalize_name(name), width) for name, width in gitems)
    independent = {name for name, width in ritems
                   if rcounts[normalize_name(name), width] == 1
                   and gcounts[normalize_name(name), width] == 1}
    require(independent == set(rkeys), "independent exact-name/width join differs")

    matched = [(sid, name, width) for sid, name, width in declared_states if name in rkeys]
    require(len(matched) == expected["grhsim_paired_declared"], "declared pair count differs")
    reasons = {
        "no_register_name_match": "gsim REG_SRC has no equal normalized full name",
        "width_mismatch": "gsim REG_SRC has the same normalized full name but a different width",
        "normalized_name_collision": "name and width match, but multiple candidates prevent a unique pair",
    }
    rows = []
    module_total = Counter()
    for sid, name, width in declared_states:
        module = name.rsplit("$", 1)[0] if "$" in name else "(top)"
        module_total[module] += 1
        if name in rkeys:
            continue
        key = normalize_name(name)
        candidates = sorted(gindex.get(key, []))
        if not candidates:
            reason = "no_register_name_match"
        elif not any(w == width for _n, w in candidates):
            reason = "width_mismatch"
        else:
            reason = "normalized_name_collision"
        rows.append({
            "index": 0, "state_id": sid, "module_path": module,
            "register_path": name, "width_bits": width, "reason": reason,
            "normalized_name": key,
            "gsim_same_name_candidates": json.dumps(
                [{"name": n, "width_bits": w} for n, w in candidates], separators=(",", ":")),
        })
    rows.sort(key=lambda row: (row["module_path"], row["register_path"], row["state_id"]))
    for index, row in enumerate(rows, 1):
        row["index"] = index
    module_rows = defaultdict(list)
    for row in rows:
        module_rows[row["module_path"]].append(row)
    modules = []
    for module, members in module_rows.items():
        counts = Counter(row["reason"] for row in members)
        modules.append({
            "module_path": module, "unpaired_register_count": len(members),
            "declared_register_count": module_total[module],
            "unpaired_percent": f"{100 * len(members) / module_total[module]:.4f}",
            "unpaired_bits": sum(row["width_bits"] for row in members),
            **{reason: counts[reason] for reason in reasons},
        })
    modules.sort(key=lambda row: (-row["unpaired_register_count"], row["module_path"]))
    detail_path = args.output / "unpaired_registers.tsv"
    module_path = args.output / "unpaired_registers_by_module.tsv"
    write_tsv(detail_path, ["index", "state_id", "module_path", "register_path", "width_bits",
                            "reason", "normalized_name", "gsim_same_name_candidates"], rows)
    write_tsv(module_path, ["module_path", "unpaired_register_count", "declared_register_count",
                           "unpaired_percent", "unpaired_bits", *reasons], modules)

    with detail_path.open(encoding="utf-8", newline="") as stream:
        written = list(csv.DictReader(stream, delimiter="\t"))
    require(len(written) + len(matched) == len(declared_states), "register counts do not close")
    require({row["register_path"] for row in written}
            == {n for _sid, n, _w in declared_states} - set(rkeys), "TSV names do not close")
    total_bits = sum(w for _s, _n, w in declared_states)
    matched_bits = sum(w for _s, _n, w in matched)
    unpaired_bits = sum(int(row["width_bits"]) for row in written)
    require(unpaired_bits + matched_bits == total_bits, "register bits do not close")
    require(sum(row["unpaired_register_count"] for row in modules) == len(written),
            "module counts do not close")
    summary = {
        "scope": "declared logic states in optimized GrhSIM IR; arrays and event bookkeeping excluded",
        "inputs": {"model": str(args.model), "gsim": str(args.gsim),
                   "reference": str(args.reference), "verified_sha256": hashes},
        "declared_register_count": len(declared_states), "declared_register_bits": total_bits,
        "paired_register_count": len(matched), "paired_register_bits": matched_bits,
        "unpaired_register_count": len(written), "unpaired_register_bits": unpaired_bits,
        "excluded_declared_array_states": declared_arrays,
        "modules_with_unpaired_registers": len(modules),
        "reason_counts": dict(Counter(row["reason"] for row in rows)),
        "reason_definitions": reasons,
        "checks": {"input_hashes": True, "archived_pairs": True, "independent_join": True,
                   "tsv_counts_names_bits": True, "module_counts": True},
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    log(f"wrote {len(written)} unpaired registers ({unpaired_bits} bits), {len(modules)} modules")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
