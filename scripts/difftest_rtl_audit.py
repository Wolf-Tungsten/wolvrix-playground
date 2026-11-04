#!/usr/bin/env python3
"""Summarize the generated XiangShan DiffTest observer RTL.

The audit intentionally works on generated artifacts instead of inferring cost
from the Scala source alone.  It correlates the DiffTest profile with the
packed gateway ports and the generated endpoint, so a candidate can be checked
before an expensive native model build.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path


def read_profile(root: Path) -> tuple[Path, dict]:
    candidates = [
        root / "chisel-home/build/generated-src/difftest_profile.json",
        root / "chisel-home/build/difftest_profile.json",
    ]
    for path in candidates:
        if path.is_file():
            return path, json.loads(path.read_text())
    raise FileNotFoundError("difftest_profile.json not found below " + str(root))


def gateway_widths(simtop: Path) -> dict[int, int]:
    if not simtop.is_file():
        return {}
    pattern = re.compile(
        r"wire\s+\[(?P<msb>\d+):0\]\s+_cpu_gatewayIn_packed_(?P<idx>\d+)_bore;"
    )
    return {
        int(match.group("idx")): int(match.group("msb")) + 1
        for match in pattern.finditer(simtop.read_text(errors="replace"))
    }


def count_endpoint_instances(endpoint: Path) -> tuple[collections.Counter, bool]:
    if not endpoint.is_file():
        return collections.Counter(), False
    text = endpoint.read_text(errors="replace")
    instances = collections.Counter(
        re.findall(r"\b(DummyDPICWrapper_[A-Za-z0-9_]+)\s+[A-Za-z0-9_]+\s*\(", text)
    )
    return instances, "PreprocessEndpoint" in text


def generated_counts(rtl: Path) -> dict:
    files = [path for path in rtl.iterdir() if path.is_file()] if rtl.is_dir() else []
    return {
        "rtl_files": len(files),
        "rtl_bytes": sum(path.stat().st_size for path in files),
        "diffext_files": sum(path.name.startswith("DiffExt") for path in files),
        "dummy_wrapper_types": sum(path.name.startswith("DummyDPICWrapper_") for path in files),
    }


def audit(root: Path) -> dict:
    profile_path, profile = read_profile(root)
    rtl = root / "rtl/rtl"
    simtop = rtl / "SimTop.sv"
    endpoint = rtl / "GatewayEndpoint.sv"
    preprocess_file = rtl / "PreprocessEndpoint.sv"
    widths = gateway_widths(simtop)
    wrapper_instances, preprocess = count_endpoint_instances(endpoint)
    bundles = profile.get("bundles", [])

    rows = []
    for index, bundle in enumerate(bundles):
        class_name = bundle.get("className", "").split(".")[-1]
        rows.append(
            {
                "index": index,
                "class": class_name,
                "class_args": bundle.get("classArgs", {}),
                "delay": bundle.get("delay", 0),
                "gateway_width": widths.get(index),
            }
        )

    classes = collections.Counter(row["class"] for row in rows)
    delays = collections.Counter(str(row["delay"]) for row in rows)
    delayed_rows = [row for row in rows if row["delay"] and row["gateway_width"] is not None]
    width_by_class = collections.defaultdict(list)
    for row in rows:
        if row["gateway_width"] is not None:
            width_by_class[row["class"]].append(row["gateway_width"])

    return {
        "artifact_root": str(root.resolve()),
        "profile": str(profile_path.resolve()),
        "interface_count": len(rows),
        "gateway_port_count": len(widths),
        "gateway_total_bits": sum(widths.values()),
        "gateway_max_bits": max(widths.values(), default=0),
        "classes": dict(classes),
        "delays": dict(delays),
        "nonzero_delay_count": sum(row["delay"] > 0 for row in rows),
        "endpoint": {
            "present": endpoint.is_file(),
            "bytes": endpoint.stat().st_size if endpoint.is_file() else 0,
            "preprocess_endpoint": preprocess,
            "preprocess_bytes": preprocess_file.stat().st_size if preprocess_file.is_file() else 0,
            "wrapper_instances": dict(wrapper_instances),
            "wrapper_instance_count": sum(wrapper_instances.values()),
        },
        "generated": generated_counts(rtl),
        "delay_bits_per_cycle": sum(row["gateway_width"] for row in delayed_rows),
        "delay_storage_bits": sum(row["delay"] * row["gateway_width"] for row in delayed_rows),
        "width_by_class": {key: values for key, values in sorted(width_by_class.items())},
        "interfaces": rows,
    }


def markdown(report: dict) -> str:
    lines = [
        "# DiffTest generated RTL audit",
        "",
        f"Artifact: `{report['artifact_root']}`",
        "",
        "| metric | value |",
        "| --- | ---: |",
        f"| DiffTest interfaces | {report['interface_count']} |",
        f"| packed gateway ports | {report['gateway_port_count']} |",
        f"| packed gateway bits | {report['gateway_total_bits']:,} |",
        f"| largest gateway port | {report['gateway_max_bits']:,} |",
        f"| nonzero delay interfaces | {report['nonzero_delay_count']} |",
        f"| GatewayEndpoint bytes | {report['endpoint']['bytes']:,} |",
        f"| PreprocessEndpoint present | {report['endpoint']['preprocess_endpoint']} |",
        f"| PreprocessEndpoint bytes | {report['endpoint']['preprocess_bytes']:,} |",
        f"| wrapper instances | {report['endpoint']['wrapper_instance_count']} |",
        f"| delayed bits per cycle | {report['delay_bits_per_cycle']:,} |",
        f"| delayed storage bits | {report['delay_storage_bits']:,} |",
        "",
        "## Bundle classes",
        "",
        "| class | count |",
        "| --- | ---: |",
    ]
    lines.extend(f"| `{name}` | {count} |" for name, count in sorted(report["classes"].items()))
    lines.extend([
        "",
        "## Delay distribution",
        "",
        "| cycles | count |",
        "| ---: | ---: |",
    ])
    lines.extend(f"| {delay} | {count} |" for delay, count in sorted(report["delays"].items(), key=lambda item: int(item[0])))
    lines.extend([
        "",
        "## Largest interfaces",
        "",
        "| index | class | width | delay | arguments |",
        "| ---: | --- | ---: | ---: | --- |",
    ])
    largest = sorted(
        (row for row in report["interfaces"] if row["gateway_width"] is not None),
        key=lambda row: row["gateway_width"],
        reverse=True,
    )[:12]
    for row in largest:
        args = json.dumps(row["class_args"], sort_keys=True, separators=(",", ":"))
        lines.append(
            f"| {row['index']} | `{row['class']}` | {row['gateway_width']:,} | "
            f"{row['delay']} | `{args}` |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(args.artifact.resolve())
    output = args.output.resolve() if args.output else args.artifact.resolve() / "difftest_rtl_audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    output.with_suffix(".md").write_text(markdown(report))
    print(json.dumps({key: report[key] for key in (
        "interface_count", "gateway_port_count", "gateway_total_bits", "gateway_max_bits",
        "nonzero_delay_count", "endpoint", "generated",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
