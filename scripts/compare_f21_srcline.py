"""Compare F21 v13/v14 GRH checkpoints while ignoring operation attributes.

The source-line change is expected to alter only ``ops[].attrs``.  This
streaming comparator keeps no graph records in memory: it compares the value
and operation record streams in order, reports the first structural mismatches,
and hashes the attribute-free record streams for an independent closure check.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import resource
import time
from collections import Counter
from pathlib import Path


def _records(path: Path):
    section = ""
    with path.open("r", encoding="utf-8", errors="replace", buffering=1024 * 1024) as stream:
        for line_number, line in enumerate(stream, start=1):
            stripped = line.lstrip()
            if stripped.startswith('"vals":'):
                section = "vals"
                continue
            if stripped.startswith('"ops":'):
                section = "ops"
                continue
            if section not in {"vals", "ops"} or not stripped.startswith('{"id":'):
                continue
            try:
                record = json.loads(stripped.rstrip().rstrip(","))
            except json.JSONDecodeError:
                continue
            yield section, record, line_number


def _without_attrs(record: dict) -> dict:
    return {key: value for key, value in record.items() if key != "attrs"}


def _canonical(record: dict) -> bytes:
    return json.dumps(_without_attrs(record), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compare_stage(v13: Path, v14: Path) -> dict:
    counts = {"v13": Counter(), "v14": Counter()}
    digests = {"v13": hashlib.sha256(), "v14": hashlib.sha256()}
    mismatch_count = 0
    attrs_only = 0
    first_mismatches: list[dict] = []
    left = _records(v13)
    right = _records(v14)
    index = 0
    for pair in itertools.zip_longest(left, right):
        index += 1
        left_record = pair[0]
        right_record = pair[1]
        if left_record is not None:
            section, record, line_number = left_record
            counts["v13"][section] += 1
            canonical = _canonical(record)
            digests["v13"].update(section.encode("ascii") + b"\0" + canonical + b"\n")
        if right_record is not None:
            right_section, right_value, right_line = right_record
            counts["v14"][right_section] += 1
            right_canonical = _canonical(right_value)
            digests["v14"].update(right_section.encode("ascii") + b"\0" + right_canonical + b"\n")
        if left_record is None or right_record is None:
            mismatch_count += 1
            if len(first_mismatches) < 20:
                first_mismatches.append({
                    "index": index,
                    "reason": "record stream length differs",
                    "v13": left_record,
                    "v14": right_record,
                })
            continue
        section, record, line_number = left_record
        right_section, right_value, right_line = right_record
        left_structural = _without_attrs(record)
        right_structural = _without_attrs(right_value)
        if section != right_section or left_structural != right_structural:
            mismatch_count += 1
            if len(first_mismatches) < 20:
                first_mismatches.append({
                    "index": index,
                    "reason": "attribute-free record differs",
                    "v13_section": section,
                    "v14_section": right_section,
                    "v13_line": line_number,
                    "v14_line": right_line,
                    "v13_id": record.get("id"),
                    "v14_id": right_value.get("id"),
                    "v13": left_structural,
                    "v14": right_structural,
                })
        elif record != right_value:
            attrs_only += 1
    return {
        "v13": {"path": str(v13), "bytes": v13.stat().st_size,
                "records": dict(sorted(counts["v13"].items())),
                "structural_sha256": digests["v13"].hexdigest()},
        "v14": {"path": str(v14), "bytes": v14.stat().st_size,
                "records": dict(sorted(counts["v14"].items())),
                "structural_sha256": digests["v14"].hexdigest()},
        "structural_mismatches": mismatch_count,
        "attribute_only_differences": attrs_only,
        "first_mismatches": first_mismatches,
        "structurally_equal": mismatch_count == 0 and counts["v13"] == counts["v14"] and
        digests["v13"].digest() == digests["v14"].digest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v13-post-split", required=True, type=Path)
    parser.add_argument("--v14-post-split", required=True, type=Path)
    parser.add_argument("--v13-post-dce", required=True, type=Path)
    parser.add_argument("--v14-post-dce", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    result = {
        "schema": "wolvrix.f21.srcline-structural-compare.v1",
        "stages": {
            "post_split": compare_stage(args.v13_post_split, args.v14_post_split),
            "post_dce": compare_stage(args.v13_post_dce, args.v14_post_dce),
        },
        "performance": {
            "elapsed_seconds": time.monotonic() - started,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
    }
    result["structurally_equal"] = all(
        stage["structurally_equal"] for stage in result["stages"].values())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "structurally_equal": result["structurally_equal"],
        "post_split": result["stages"]["post_split"]["structurally_equal"],
        "post_dce": result["stages"]["post_dce"]["structurally_equal"],
        "elapsed_seconds": result["performance"]["elapsed_seconds"],
        "max_rss_kib": result["performance"]["max_rss_kib"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
