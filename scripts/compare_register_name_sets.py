#!/usr/bin/env python3

import argparse
import json
from collections import Counter, defaultdict
import itertools
from pathlib import Path
import re


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def extract_gsim_regsrc(path: Path) -> set[str]:
    payload = load_json(path)
    return {node["name"] for node in payload["nodes"] if node.get("type") == "NODE_REG_SRC"}


def extract_grh_register_names(path: Path, kind: str) -> set[str]:
    payload = load_json(path)
    names: set[str] = set()
    for graph in payload["graphs"]:
        for op in graph["ops"]:
            if op.get("kind") != kind:
                continue
            if kind == "kRegister":
                names.add(op["sym"])
                continue
            reg = op.get("attrs", {}).get("regSymbol", {}).get("v")
            if reg is not None:
                names.add(reg)
    return names


def top_prefixes(values: set[str], count: int) -> list[tuple[str, int]]:
    prefix_counts: Counter[str] = Counter()
    for value in values:
        parts = value.split("$")
        prefix_counts["$".join(parts[:3])] += 1
    return prefix_counts.most_common(count)


def normalize_name(value: str) -> str:
    return re.sub(r"_+", "_", value.replace("$", "_"))


def build_normalized_index(values: set[str]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = defaultdict(set)
    for value in values:
        index[normalize_name(value)].add(value)
    return index


def top_normalized_prefixes(values: set[str], count: int) -> list[tuple[str, int]]:
    prefix_counts: Counter[str] = Counter()
    for value in values:
        parts = value.split("_")
        prefix_counts["_".join(parts[:3])] += 1
    return prefix_counts.most_common(count)


def strip_numeric_tokens_key(value: str) -> str:
    parts = [part for part in value.split("_") if part and not part.isdigit()]
    return "_".join(parts)


def numeric_tokens(value: str) -> tuple[str, ...]:
    return tuple(part for part in value.split("_") if part.isdigit())


def numeric_elide_variants(value: str, max_removed: int = 3) -> set[str]:
    parts = value.split("_")
    numeric_positions = [i for i, part in enumerate(parts) if part.isdigit()]
    variants: set[str] = set()
    limit = min(max_removed, len(numeric_positions))
    for removed_count in range(1, limit + 1):
        for removed_positions in itertools.combinations(numeric_positions, removed_count):
            variants.add("_".join(part for i, part in enumerate(parts) if i not in removed_positions))
    variants.discard(value)
    variants.discard("")
    return variants


def aggregate_base(value: str) -> str | None:
    match = re.match(r"^(.*)__[^_]+$", value)
    return match.group(1) if match else None


def build_longest_prefix_matches(bases: set[str], values: set[str]) -> dict[str, set[str]]:
    base_to_children: dict[str, set[str]] = defaultdict(set)
    for value in values:
        parts = value.split("_")
        best_base: str | None = None
        for i in range(1, len(parts)):
            candidate = "_".join(parts[:i])
            if candidate not in bases:
                continue
            if best_base is None or len(candidate) > len(best_base):
                best_base = candidate
        if best_base is not None:
            base_to_children[best_base].add(value)
    return base_to_children


def sample_pairs(base_to_targets: dict[str, set[str]], limit: int) -> list[dict[str, object]]:
    pairs: list[dict[str, object]] = []
    ranked = sorted(base_to_targets.items(), key=lambda item: (-len(item[1]), item[0]))
    for base, targets_set in ranked[:limit]:
        targets = sorted(targets_set)
        pairs.append({
            "base": base,
            "targetCount": len(targets),
            "sampleTargets": targets[: min(5, len(targets))],
        })
    return pairs


def analyze_match(gsim: set[str], grh: set[str], top: int) -> dict[str, object]:
    gsim_index = build_normalized_index(gsim)
    grh_index = build_normalized_index(grh)

    gsim_keys = set(gsim_index)
    grh_keys = set(grh_index)
    raw_intersection = gsim & grh
    exact_keys = gsim_keys & grh_keys
    exact_extra_keys = {key for key in exact_keys if gsim_index[key] != grh_index[key]}

    remaining_gsim = gsim_keys - exact_keys
    remaining_grh = grh_keys - exact_keys

    aggregate_gsim_to_grh: dict[str, set[str]] = defaultdict(set)
    aggregate_grh_keys: set[str] = set()
    for key in sorted(remaining_gsim):
        base = aggregate_base(key)
        if base is None or base not in remaining_grh:
            continue
        aggregate_gsim_to_grh[base].add(key)
        aggregate_grh_keys.add(base)
    aggregate_gsim_keys = set().union(*aggregate_gsim_to_grh.values()) if aggregate_gsim_to_grh else set()
    remaining_gsim -= aggregate_gsim_keys
    remaining_grh -= aggregate_grh_keys

    prefix_children = build_longest_prefix_matches(remaining_gsim, remaining_grh)
    prefix_refine_1to1: dict[str, set[str]] = {}
    prefix_expand_1toN: dict[str, set[str]] = {}
    for key, children in prefix_children.items():
        if len(children) == 1:
            prefix_refine_1to1[key] = set(children)
        else:
            prefix_expand_1toN[key] = set(children)
    prefix_refine_keys = set(prefix_refine_1to1)
    prefix_expand_keys = set(prefix_expand_1toN)
    prefix_refine_targets = set().union(*prefix_refine_1to1.values()) if prefix_refine_1to1 else set()
    prefix_expand_targets = set().union(*prefix_expand_1toN.values()) if prefix_expand_1toN else set()
    remaining_gsim -= prefix_refine_keys | prefix_expand_keys
    remaining_grh -= prefix_refine_targets | prefix_expand_targets

    stripped_gsim_index = build_normalized_index({strip_numeric_tokens_key(key) for key in remaining_gsim})
    stripped_grh_index = build_normalized_index({strip_numeric_tokens_key(key) for key in remaining_grh})
    stripped_keys = (set(stripped_gsim_index) & set(stripped_grh_index)) - {""}

    gsim_by_stripped: dict[str, set[str]] = defaultdict(set)
    grh_by_stripped: dict[str, set[str]] = defaultdict(set)
    for key in remaining_gsim:
        stripped = strip_numeric_tokens_key(key)
        if stripped:
            gsim_by_stripped[stripped].add(key)
    for key in remaining_grh:
        stripped = strip_numeric_tokens_key(key)
        if stripped:
            grh_by_stripped[stripped].add(key)

    numeric_permute_1to1: dict[str, set[str]] = {}
    numeric_permute_NtoN: dict[str, set[str]] = {}
    numeric_expand_gsim_to_grh: dict[str, set[str]] = {}
    numeric_permute_gsim_keys: set[str] = set()
    numeric_permute_grh_keys: set[str] = set()
    numeric_permute_grouped_gsim_keys: set[str] = set()
    numeric_permute_grouped_grh_keys: set[str] = set()
    numeric_expand_gsim_keys: set[str] = set()
    numeric_expand_grh_keys: set[str] = set()
    for stripped in sorted(stripped_keys):
        gsim_group = gsim_by_stripped[stripped]
        grh_group = grh_by_stripped[stripped]
        if len(gsim_group) == 1 and len(grh_group) == 1:
            gsim_key = next(iter(gsim_group))
            grh_key = next(iter(grh_group))
            if gsim_key != grh_key and sorted(numeric_tokens(gsim_key)) == sorted(numeric_tokens(grh_key)):
                numeric_permute_1to1[gsim_key] = {grh_key}
                numeric_permute_gsim_keys.add(gsim_key)
                numeric_permute_grh_keys.add(grh_key)
            continue
        if len(gsim_group) > 1 and len(gsim_group) == len(grh_group):
            gsim_numeric_signatures = Counter(tuple(sorted(numeric_tokens(key))) for key in gsim_group)
            grh_numeric_signatures = Counter(tuple(sorted(numeric_tokens(key))) for key in grh_group)
            if gsim_numeric_signatures == grh_numeric_signatures:
                numeric_permute_NtoN[stripped] = set(grh_group)
                numeric_permute_grouped_gsim_keys.update(gsim_group)
                numeric_permute_grouped_grh_keys.update(grh_group)
                continue
        if len(gsim_group) == 1 and len(grh_group) > 1:
            gsim_key = next(iter(gsim_group))
            numeric_expand_gsim_to_grh[gsim_key] = set(grh_group)
            numeric_expand_gsim_keys.add(gsim_key)
            numeric_expand_grh_keys.update(grh_group)

    remaining_gsim -= numeric_permute_gsim_keys | numeric_permute_grouped_gsim_keys | numeric_expand_gsim_keys
    remaining_grh -= numeric_permute_grh_keys | numeric_permute_grouped_grh_keys | numeric_expand_grh_keys

    numeric_elide_gsim_to_grh: dict[str, set[str]] = defaultdict(set)
    for grh_key in sorted(remaining_grh):
        candidates = numeric_elide_variants(grh_key)
        matches = [candidate for candidate in candidates if candidate in remaining_gsim]
        if not matches:
            continue
        best = max(matches, key=lambda item: (len(item.split("_")), len(item), item))
        numeric_elide_gsim_to_grh[best].add(grh_key)
    numeric_elide_gsim_keys = set(numeric_elide_gsim_to_grh)
    numeric_elide_grh_keys = set().union(*numeric_elide_gsim_to_grh.values()) if numeric_elide_gsim_to_grh else set()
    remaining_gsim -= numeric_elide_gsim_keys
    remaining_grh -= numeric_elide_grh_keys

    generated_grh_keys = {key for key in remaining_grh if key.startswith("_op_")}
    remaining_grh -= generated_grh_keys

    prefix_expand_delta = len(prefix_expand_targets) - len(prefix_expand_keys)
    aggregate_delta = len(aggregate_grh_keys) - len(aggregate_gsim_keys)
    numeric_expand_delta = len(numeric_expand_grh_keys) - len(numeric_expand_gsim_keys)
    numeric_elide_delta = len(numeric_elide_grh_keys) - len(numeric_elide_gsim_keys)
    generated_delta = len(generated_grh_keys)
    residual_delta = len(remaining_grh) - len(remaining_gsim)

    analysis = {
        "counts": {
            "gsimRawCount": len(gsim),
            "grhRawCount": len(grh),
            "rawGapGrhMinusGsim": len(grh) - len(gsim),
            "gsimNormalizedKeyCount": len(gsim_keys),
            "grhNormalizedKeyCount": len(grh_keys),
            "normalizedGapGrhMinusGsim": len(grh_keys) - len(gsim_keys),
            "rawExactCount": len(raw_intersection),
            "normalizedExactKeyCount": len(exact_keys),
            "normalizedExactButRawDifferentKeyCount": len(exact_extra_keys),
        },
        "categories": {
            "exactNormalized1to1": {
                "gsimKeys": len(exact_keys),
                "grhKeys": len(exact_keys),
                "netGapContribution": 0,
            },
            "aggregateGsimFieldToGrhBaseNto1": {
                "gsimKeys": len(aggregate_gsim_keys),
                "grhKeys": len(aggregate_grh_keys),
                "netGapContribution": aggregate_delta,
                "sampleGroups": sample_pairs(aggregate_gsim_to_grh, top),
            },
            "prefixRefine1to1": {
                "gsimKeys": len(prefix_refine_keys),
                "grhKeys": len(prefix_refine_targets),
                "netGapContribution": 0,
                "sampleGroups": sample_pairs(prefix_refine_1to1, top),
            },
            "prefixExpand1toN": {
                "gsimKeys": len(prefix_expand_keys),
                "grhKeys": len(prefix_expand_targets),
                "netGapContribution": prefix_expand_delta,
                "childCountHistogram": Counter(len(values) for values in prefix_expand_1toN.values()),
                "sampleGroups": sample_pairs(prefix_expand_1toN, top),
            },
            "numericTokenPermutation1to1": {
                "gsimKeys": len(numeric_permute_gsim_keys),
                "grhKeys": len(numeric_permute_grh_keys),
                "netGapContribution": 0,
                "sampleGroups": sample_pairs(numeric_permute_1to1, top),
            },
            "numericTokenPermutationNtoN": {
                "gsimKeys": len(numeric_permute_grouped_gsim_keys),
                "grhKeys": len(numeric_permute_grouped_grh_keys),
                "netGapContribution": 0,
                "sampleGroups": sample_pairs(numeric_permute_NtoN, top),
            },
            "numericIndexExpand1toN": {
                "gsimKeys": len(numeric_expand_gsim_keys),
                "grhKeys": len(numeric_expand_grh_keys),
                "netGapContribution": numeric_expand_delta,
                "childCountHistogram": Counter(len(values) for values in numeric_expand_gsim_to_grh.values()),
                "sampleGroups": sample_pairs(numeric_expand_gsim_to_grh, top),
            },
            "numericElideToExistingGsim1toN": {
                "gsimKeys": len(numeric_elide_gsim_keys),
                "grhKeys": len(numeric_elide_grh_keys),
                "netGapContribution": numeric_elide_delta,
                "childCountHistogram": Counter(len(values) for values in numeric_elide_gsim_to_grh.values()),
                "sampleGroups": sample_pairs(numeric_elide_gsim_to_grh, top),
            },
            "generatedGrhOpNames": {
                "gsimKeys": 0,
                "grhKeys": len(generated_grh_keys),
                "netGapContribution": generated_delta,
                "sampleKeys": sorted(generated_grh_keys)[:top],
            },
            "residualUnclassified": {
                "gsimKeys": len(remaining_gsim),
                "grhKeys": len(remaining_grh),
                "netGapContribution": residual_delta,
                "topGsimPrefixes": top_normalized_prefixes(remaining_gsim, top),
                "topGrhPrefixes": top_normalized_prefixes(remaining_grh, top),
                "sampleGsimKeys": sorted(remaining_gsim)[:top],
                "sampleGrhKeys": sorted(remaining_grh)[:top],
            },
        },
        "topOnlyRawPrefixes": {
            "gsim": top_prefixes(gsim - grh, top),
            "grh": top_prefixes(grh - gsim, top),
        },
    }
    return analysis


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gsim-json", required=True, type=Path)
    parser.add_argument("--grh-json", required=True, type=Path)
    parser.add_argument("--grh-kind", default="kRegisterReadPort",
                        choices=["kRegister", "kRegisterReadPort", "kRegisterWritePort"])
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    gsim = extract_gsim_regsrc(args.gsim_json)
    grh = extract_grh_register_names(args.grh_json, args.grh_kind)
    analysis = analyze_match(gsim, grh, args.top)
    analysis["inputs"] = {
        "gsimJson": str(args.gsim_json),
        "grhJson": str(args.grh_json),
        "grhKind": args.grh_kind,
    }

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        with args.json_out.open("w", encoding="utf-8") as handle:
            json.dump(analysis, handle, indent=2, sort_keys=True)

    counts = analysis["counts"]
    categories = analysis["categories"]
    print(f"gsim_raw_count={counts['gsimRawCount']}")
    print(f"grh_raw_count={counts['grhRawCount']} kind={args.grh_kind}")
    print(f"raw_gap_grh_minus_gsim={counts['rawGapGrhMinusGsim']}")
    print(f"normalized_exact_keys={counts['normalizedExactKeyCount']}")
    print(f"normalized_exact_but_raw_different_keys={counts['normalizedExactButRawDifferentKeyCount']}")
    print(
        "prefix_expand_1toN="
        + json.dumps(
            {
                "gsim_keys": categories["prefixExpand1toN"]["gsimKeys"],
                "grh_keys": categories["prefixExpand1toN"]["grhKeys"],
                "net_gap": categories["prefixExpand1toN"]["netGapContribution"],
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    print(
        "aggregate_gsim_field_to_grh_base_Nto1="
        + json.dumps(
            {
                "gsim_keys": categories["aggregateGsimFieldToGrhBaseNto1"]["gsimKeys"],
                "grh_keys": categories["aggregateGsimFieldToGrhBaseNto1"]["grhKeys"],
                "net_gap": categories["aggregateGsimFieldToGrhBaseNto1"]["netGapContribution"],
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    print(
        "generated_grh_op_names="
        + json.dumps(
            {
                "grh_keys": categories["generatedGrhOpNames"]["grhKeys"],
                "net_gap": categories["generatedGrhOpNames"]["netGapContribution"],
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    print(
        "numeric_token_permutation_1to1="
        + json.dumps(
            {
                "gsim_keys": categories["numericTokenPermutation1to1"]["gsimKeys"],
                "grh_keys": categories["numericTokenPermutation1to1"]["grhKeys"],
                "net_gap": categories["numericTokenPermutation1to1"]["netGapContribution"],
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    print(
        "numeric_token_permutation_NtoN="
        + json.dumps(
            {
                "gsim_keys": categories["numericTokenPermutationNtoN"]["gsimKeys"],
                "grh_keys": categories["numericTokenPermutationNtoN"]["grhKeys"],
                "net_gap": categories["numericTokenPermutationNtoN"]["netGapContribution"],
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    print(
        "numeric_index_expand_1toN="
        + json.dumps(
            {
                "gsim_keys": categories["numericIndexExpand1toN"]["gsimKeys"],
                "grh_keys": categories["numericIndexExpand1toN"]["grhKeys"],
                "net_gap": categories["numericIndexExpand1toN"]["netGapContribution"],
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    print(
        "numeric_elide_to_existing_gsim_1toN="
        + json.dumps(
            {
                "gsim_keys": categories["numericElideToExistingGsim1toN"]["gsimKeys"],
                "grh_keys": categories["numericElideToExistingGsim1toN"]["grhKeys"],
                "net_gap": categories["numericElideToExistingGsim1toN"]["netGapContribution"],
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    print(
        "residual_unclassified="
        + json.dumps(
            {
                "gsim_keys": categories["residualUnclassified"]["gsimKeys"],
                "grh_keys": categories["residualUnclassified"]["grhKeys"],
                "net_gap": categories["residualUnclassified"]["netGapContribution"],
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
