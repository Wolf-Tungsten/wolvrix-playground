#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


SECTION_RE = re.compile(r"^\s*\d+\s+(\S+)\s+([0-9a-fA-F]+)\s+")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="ascii"))


def text_size_bytes(paths: list[Path], objdump: str) -> int:
    total = 0
    for path in paths:
        proc = subprocess.run(
            [objdump, "-h", str(path)],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for line in proc.stdout.splitlines():
            match = SECTION_RE.match(line)
            if not match:
                continue
            name, size_hex = match.groups()
            if name == ".text" or name.startswith(".text."):
                total += int(size_hex, 16)
    return total


def maybe_get(data: dict, *keys: str) -> int | None:
    for key in keys:
        if key in data:
            value = data[key]
            return int(value) if value is not None else None
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gsim-graph-stats", required=True)
    parser.add_argument("--grhsim-graph-stats", required=True)
    parser.add_argument("--gsim-instruction-stats", required=True)
    parser.add_argument("--grhsim-instruction-stats", required=True)
    parser.add_argument("--gsim-objects", nargs="+", required=True)
    parser.add_argument("--grhsim-objects", nargs="+", required=True)
    parser.add_argument("--objdump", default="objdump")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    gsim_graph = load_json(Path(args.gsim_graph_stats))
    grhsim_graph = load_json(Path(args.grhsim_graph_stats))
    gsim_instruction = load_json(Path(args.gsim_instruction_stats))
    grhsim_instruction = load_json(Path(args.grhsim_instruction_stats))

    payload = {
        "gsim": {
            "supernodes": maybe_get(gsim_graph, "emitted_supernode_count", "supernode_count"),
            "supernode_edges": maybe_get(gsim_graph, "emitted_supernode_edge_count", "supernode_edge_count", "dag_edges"),
            "instruction_count": int(gsim_instruction["instruction_total"]),
            "text_size_bytes": text_size_bytes([Path(item) for item in args.gsim_objects], args.objdump),
            "graph_stats": str(Path(args.gsim_graph_stats)),
            "objects": args.gsim_objects,
        },
        "grhsim": {
            "supernodes": maybe_get(grhsim_graph, "supernodes", "supernode_count"),
            "supernode_edges": maybe_get(grhsim_graph, "dag_edges", "supernode_edge_count"),
            "instruction_count": int(grhsim_instruction["instruction_total"]),
            "text_size_bytes": text_size_bytes([Path(item) for item in args.grhsim_objects], args.objdump),
            "graph_stats": str(Path(args.grhsim_graph_stats)),
            "objects": args.grhsim_objects,
        },
    }
    gsim = payload["gsim"]
    grhsim = payload["grhsim"]
    payload["ratios"] = {
        "supernodes_grhsim_to_gsim": (
            grhsim["supernodes"] / gsim["supernodes"] if gsim["supernodes"] else None
        ),
        "supernode_edges_grhsim_to_gsim": (
            grhsim["supernode_edges"] / gsim["supernode_edges"] if gsim["supernode_edges"] else None
        ),
        "instruction_count_grhsim_to_gsim": (
            grhsim["instruction_count"] / gsim["instruction_count"] if gsim["instruction_count"] else None
        ),
        "text_size_bytes_grhsim_to_gsim": (
            grhsim["text_size_bytes"] / gsim["text_size_bytes"] if gsim["text_size_bytes"] else None
        ),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="ascii")

    print("model stats:")
    for label in ("gsim", "grhsim"):
        item = payload[label]
        print(
            f"{label:6s} "
            f"supernodes={item['supernodes']} "
            f"supernode_edges={item['supernode_edges']} "
            f"instructions={item['instruction_count']} "
            f"text_size_bytes={item['text_size_bytes']}"
        )
    print("ratios grhsim/gsim:")
    for key, value in payload["ratios"].items():
        print(f"  {key}={value:.6f}" if value is not None else f"  {key}=null")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
