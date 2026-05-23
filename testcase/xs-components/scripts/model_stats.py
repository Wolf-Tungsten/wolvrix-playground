#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="ascii"))


def get_int(data: dict, *keys: str) -> int | None:
    for key in keys:
        if key in data and data[key] is not None:
            return int(data[key])
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--scale", required=True)
    parser.add_argument("--gsim-graph-stats", required=True)
    parser.add_argument("--grhsim-graph-stats", required=True)
    parser.add_argument("--gsim-instruction-stats", required=True)
    parser.add_argument("--grhsim-instruction-stats", required=True)
    parser.add_argument("--bench-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    gsim_graph = load(args.gsim_graph_stats)
    grhsim_graph = load(args.grhsim_graph_stats)
    gsim_insn = load(args.gsim_instruction_stats)
    grhsim_insn = load(args.grhsim_instruction_stats)

    bench = {}
    for line in Path(args.bench_log).read_text(encoding="ascii").splitlines():
        if not line.startswith("[BENCH]"):
            continue
        fields = {}
        for token in line.split()[1:]:
            key, value = token.split("=", 1)
            fields[key] = value
        bench[fields["model"]] = fields

    payload = {
        "case": args.case,
        "kind": args.kind,
        "scale": args.scale,
        "gsim": {
            "supernodes": get_int(gsim_graph, "emitted_supernode_count", "supernode_count"),
            "supernode_edges": get_int(gsim_graph, "emitted_supernode_edge_count", "supernode_edge_count", "dag_edges"),
            "instruction_count": int(gsim_insn["instruction_total"]),
            "text_size_bytes": int(gsim_insn["text_size_bytes"]),
            "bench_ms": float(bench.get("gsim", {}).get("ms", "nan")),
            "vectors_per_s": float(bench.get("gsim", {}).get("vectors_per_s", "nan")),
        },
        "grhsim": {
            "supernodes": get_int(grhsim_graph, "supernodes", "supernode_count"),
            "supernode_edges": get_int(grhsim_graph, "dag_edges", "supernode_edge_count"),
            "instruction_count": int(grhsim_insn["instruction_total"]),
            "text_size_bytes": int(grhsim_insn["text_size_bytes"]),
            "bench_ms": float(bench.get("grhsim", {}).get("ms", "nan")),
            "vectors_per_s": float(bench.get("grhsim", {}).get("vectors_per_s", "nan")),
        },
    }
    payload["ratios"] = {
        "bench_ms_grhsim_to_gsim": payload["grhsim"]["bench_ms"] / payload["gsim"]["bench_ms"],
        "instruction_count_grhsim_to_gsim": payload["grhsim"]["instruction_count"] / payload["gsim"]["instruction_count"],
        "text_size_bytes_grhsim_to_gsim": payload["grhsim"]["text_size_bytes"] / payload["gsim"]["text_size_bytes"],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="ascii")
    print(f"{args.case}: bench_ms gsim={payload['gsim']['bench_ms']:.3f} grhsim={payload['grhsim']['bench_ms']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
