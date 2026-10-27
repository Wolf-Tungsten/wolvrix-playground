"""Census generated nonsink publication syntax without reading code-map.json.

Each TU is read once. Publication bodies extracted into chunk helpers are
followed through their same-owner call graph. Counts describe emitted syntax,
not executed work or the dataflow of deferred dirty flags.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


FUNCTION = re.compile(r"^void \w+::(\w+)\([^\n]*\)\n\{\n", re.M)
NONSINK = re.compile(r"sn_(\d+)(?:_chunk(\d+))?$")
PUBLICATION = re.compile(r"^(\s*)if \((\w*BoundaryStore\.\w+) != .+\) \{$")
ACTIVATION = re.compile(r"\b(activeCurrent|activeNext)\[(\d+)\] \|= UINT8_C\((\d+)\);")
CALL = re.compile(r"\b(sn_\d+(?:_chunk\d+)?)\([^;]*\);")
WRITE = re.compile(r"\b(\w*BoundaryStore\.\w+)(?:\[[^;=]*\])*\s*=(?!=)")


def merge_masks(destination, source):
    for key, mask in source.items():
        destination[key] = destination.get(key, 0) | mask


def empty_body():
    return {"masks": {}, "or_sites": 0, "calls": [], "writes": set()}


def parse_function(name, body, source_file, line):
    result = {**empty_body(), "name": name, "file": source_file, "line": line,
              "publications": [], "unrecognized": []}
    active = []
    for text in body.splitlines():
        if active and text == active[-1][0] + "}":
            active.pop()
        publication = PUBLICATION.fullmatch(text)
        if publication:
            record = {**empty_body(), "destination": publication[2]}
            result["publications"].append(record)
            active.append((publication[1], record))
        elif text.lstrip().startswith("if (") and "BoundaryStore." in text and " != " in text:
            result["unrecognized"].append(text.strip())
        if text.lstrip().startswith("if "):
            # A comparison reads the destination; it does not write it.
            continue
        targets = [result] + [record for _, record in active]
        if "BoundaryStore." in text and "=" in text:
            writes = WRITE.findall(text)
            for target in targets:
                target["writes"].update(writes)
        if "|=" in text and ("activeCurrent[" in text or "activeNext[" in text):
            matches = list(ACTIVATION.finditer(text))
            if not matches:
                result["unrecognized"].append(text.strip())
            for match in matches:
                key, mask = (match[1], int(match[2])), int(match[3])
                for target in targets:
                    target["masks"][key] = target["masks"].get(key, 0) | mask
                    target["or_sites"] += 1
        if "sn_" in text and "(" in text:
            calls = CALL.findall(text)
            for target in targets:
                target["calls"].extend(calls)
    if active:
        raise ValueError(f"unterminated publication in {name}")
    return result


def duplicate_count(signatures):
    return sum(count - 1 for signature, count in signatures.items() if signature)


def owner_census(owner, functions):
    closure_cache, pending = {}, set()

    def closure(name):
        if name in closure_cache:
            return closure_cache[name]
        if name in pending or name not in functions:
            raise ValueError(f"missing or recursive nonsink helper {name}")
        pending.add(name)
        function = functions[name]
        result = {"masks": dict(function["masks"]), "or_sites": function["or_sites"],
                  "writes": set(function["writes"])}
        for called in function["calls"]:
            if int(NONSINK.fullmatch(called)[1]) != owner:
                raise ValueError(f"cross-owner helper call {name} -> {called}")
            child = closure(called)
            merge_masks(result["masks"], child["masks"])
            result["or_sites"] += child["or_sites"]
            result["writes"].update(child["writes"])
        pending.remove(name)
        closure_cache[name] = result
        return result

    counters, owner_signatures, owner_masks = Counter(), Counter(), {}
    chunks = []
    for name, function in functions.items():
        if function["unrecognized"]:
            raise ValueError(f"unsupported publication/activation syntax in {name}: "
                             f"{function['unrecognized'][:2]}")
        closure(name)
        counts, signatures = Counter(), Counter()
        counts["publication_compare_blocks"] = len(function["publications"])
        counts["activation_or_sites"] = function["or_sites"]
        counts["distinct_chunk_bitmap_bytes"] = len(function["masks"])
        merge_masks(owner_masks, function["masks"])
        for publication in function["publications"]:
            masks, writes = dict(publication["masks"]), set(publication["writes"])
            or_sites = publication["or_sites"]
            for called in publication["calls"]:
                child = closure(called)
                merge_masks(masks, child["masks"])
                writes.update(child["writes"])
                or_sites += child["or_sites"]
            if publication["destination"] not in writes:
                raise ValueError(f"comparison is not a validated boundary copy in {name}: "
                                 f"{publication['destination']}")
            signature = tuple((array, byte, mask) for (array, byte), mask in sorted(masks.items()))
            signatures[signature] += 1
            counts["activation_or_sites_reachable_from_comparisons"] += or_sites
            counts["publication_comparisons_with_extracted_helpers"] += bool(publication["calls"])
            if not signature:
                counts["compare_blocks_without_inline_or_called_activation"] += 1
                counts["such_blocks_writing_small_payload_boundary"] += any(
                    key.startswith("smallSinkPayloadBoundaryStore.") for key in writes)
                counts["such_blocks_writing_small_enable_boundary"] += any(
                    key.startswith("smallSinkEnableBoundaryStore.") for key in writes)
        counts["duplicate_nonempty_publication_signatures_same_chunk"] = duplicate_count(signatures)
        owner_signatures.update(signatures)
        counters.update(counts)
        chunks.append({"name": name, "file": function["file"], "line": function["line"], **counts})
    counters["functions_including_chunks"] = len(functions)
    counters["distinct_owner_bitmap_bytes"] = len(owner_masks)
    counters["duplicate_nonempty_publication_signatures_same_owner"] = duplicate_count(owner_signatures)
    counters["nonempty_publication_signatures_same_owner"] = sum(bool(key) for key in owner_signatures)
    return {"owner": owner, **counters}, chunks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    model = args.model.resolve()
    manifest_bytes = (model / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    expected_functions = {row["name"] for row in manifest["functions"] if NONSINK.fullmatch(row["name"])}
    metadata = {"nonsink_owners": len(manifest["nonsink_functions"]),
                "nonsink_operations": sum(len(row["operation_symbols"]) for row in manifest["nonsink_functions"]),
                "functions_including_chunks": len(expected_functions),
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest()}
    sources = list(manifest["sources"])
    del manifest, manifest_bytes
    identity_path = model / "generation-identity.json"
    identity_bytes = identity_path.read_bytes() if identity_path.is_file() else None
    identity = json.loads(identity_bytes) if identity_bytes else {}
    expected_files = identity.get("generated", {}).get("files", {})
    if expected_files.get("manifest.json", {}).get("sha256") not in (None, metadata["manifest_sha256"]):
        raise ValueError("manifest differs from generation identity")
    owners, chunks, seen = [], [], set()
    current_owner, functions = None, {}
    counters = Counter()
    cpp_hashes = {}
    for source in sources:
        if not source.endswith(".cpp"):
            continue
        raw = (model / source).read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        if expected_files.get(source, {}).get("sha256") not in (None, checksum):
            raise ValueError(f"generated TU differs from identity: {source}")
        cpp_hashes[source] = checksum
        counters["tu_files_read"] += 1
        counters["tu_bytes_read"] += len(raw)
        text = raw.decode()
        del raw
        for match in FUNCTION.finditer(text):
            nonsink = NONSINK.fullmatch(match[1])
            if not nonsink:
                continue
            owner = int(nonsink[1])
            if owner != current_owner and functions:
                row, rows = owner_census(current_owner, functions)
                owners.append(row); chunks.extend(rows)
                functions = {}
            current_owner = owner
            if match[1] in seen:
                raise ValueError(f"duplicate generated function {match[1]}")
            seen.add(match[1])
            end = text.find("\n}\n", match.end())
            if end < 0:
                raise ValueError(f"unterminated generated function {match[1]}")
            body = text[match.end():end]
            counters["nonsink_body_text_bytes"] += len(body.encode())
            functions[match[1]] = parse_function(match[1], body, source, text.count("\n", 0, match.start()) + 1)
    if functions:
        row, rows = owner_census(current_owner, functions)
        owners.append(row); chunks.extend(rows)
    if seen != expected_functions or len({row["owner"] for row in owners}) != metadata["nonsink_owners"]:
        raise ValueError("nonsink source coverage differs from manifest")
    for row in owners:
        counters.update({key: value for key, value in row.items() if key != "owner"})
    counters["activation_or_sites_outside_comparison_closure"] = (
        counters["activation_or_sites"] - counters["activation_or_sites_reachable_from_comparisons"])
    result = {
        "schema": "wolvrix.grhsim.nonsink-publication-static-census.v1",
        "model": str(model), "manifest": metadata,
        "generation_identity_sha256": hashlib.sha256(identity_bytes).hexdigest() if identity_bytes else None,
        "generated_tu_hashes_match_identity": bool(expected_files),
        "generated_tu_hashes": cpp_hashes,
        "coverage": {"manifest_function_set_matched": True, "unvalidated_comparisons": 0,
                     "unsupported_publication_or_activation_lines": 0,
                     "same_owner_helper_calls_resolved": True},
        "totals": dict(counters),
        "interpretation": {
            "same_chunk": "Comparison location defines the chunk, including any extracted copy/activation helpers.",
            "signature": "Complete union of (activeCurrent/activeNext, byte, mask), including called same-owner chunks.",
            "duplicate": "Nonempty signatures after their first occurrence, separately per chunk and per owner.",
            "empty_signature_is_semantic_zero_fanout": counters["activation_or_sites_outside_comparison_closure"] == 0,
            "limitations": [
                "Static syntax counts are not execution counts or costs; code-map and runtime profiles are not loaded.",
                "Only named BoundaryStore destination != source branches with a validated destination copy count as publications.",
                "Deferred dirty flags can activate outside a comparison body; the empty-signature count then does not mean zero semantic fanout.",
                "Function/chunk boundaries can change with naming, frame layout and the function line budget.",
            ],
        },
        "owners": owners, "chunks": chunks,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("schema", "model", "manifest", "coverage", "totals", "interpretation")}, indent=2))


if __name__ == "__main__":
    main()
