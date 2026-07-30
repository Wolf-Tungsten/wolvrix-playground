#!/usr/bin/env python3

"""Run the CPU gather/SpMM inference floor benchmark (docs/04 Phase 0 task 5).

Usage:

    run_gnn_bench.py <instruction_graph.jsonl> [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.gnn_bench import format_report, run_bench  # noqa: E402
from harness.graph import load_graph  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph")
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    graph = load_graph(args.graph)
    started = time.time()
    result = run_bench(graph)
    report = format_report(result)
    print(f"[bench] {report}")
    print(f"[bench] measured in {time.time() - started:.1f}s")
    payload = {
        "nodes": result.nodes,
        "edges": result.edges,
        "dims": result.dims,
        "gather_s": result.gather_s,
        "spmm_s": result.spmm_s,
        "matmul_s": result.matmul_s,
        "gather_gbs": result.gather_gbs,
        "layer_s": {str(dim): result.layer_s(dim) for dim in result.dims},
        "model_2layer_s": {str(dim): result.model_s(dim, 2) for dim in result.dims},
        "model_3layer_s": {str(dim): result.model_s(dim, 3) for dim in result.dims},
    }
    if args.json:
        Path(args.json).write_text(json.dumps(payload, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
