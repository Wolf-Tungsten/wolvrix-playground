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


def grhsim_graph_stats(model: dict) -> tuple[int, int]:
    # PhaseSchedule is the terminal stage of the six-phase CPU mapping.
    cpu = next((mapping[4] for mapping in model["mappings"]
                if len(mapping) > 4 and mapping[4] and mapping[4][0] == 15), None)
    if cpu is None:
        raise ValueError("GrhSIM IR has no six-phase CPU schedule")

    parts = {part[0]: part for part in cpu[2]}
    root = parts[cpu[1]]
    general = next((parts[child] for child in root[4] if parts[child][3] == 4), None)
    if general is None:
        raise ValueError("GrhSIM IR has no General phase")

    supernodes = {supernode for function in general[4]
                  for supernode in parts[function][4] if parts[supernode][2] == 3}
    op_owner = {op: supernode for supernode in supernodes
                for node in parts[supernode][4] for op in parts[node][5]}
    value_owner = {value: op_owner[op[0]] for op in model["operations"]
                   if op[0] in op_owner for value in op[5]}
    edges = {(value_owner[source], target)
             for source, targets, _ in cpu[4][2]
             if source in value_owner
             for target in targets if target in supernodes and target != value_owner[source]}
    return len(supernodes), len(edges)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--scale", required=True)
    parser.add_argument("--gsim-graph-stats", required=True)
    parser.add_argument("--grhsim-ir", required=True)
    parser.add_argument("--gsim-instruction-stats", required=True)
    parser.add_argument("--grhsim-instruction-stats", required=True)
    parser.add_argument("--bench-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    gsim_graph = load(args.gsim_graph_stats)
    grhsim_supernodes, grhsim_edges = grhsim_graph_stats(load(args.grhsim_ir))
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
            "supernodes": grhsim_supernodes,
            "supernode_edges": grhsim_edges,
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
