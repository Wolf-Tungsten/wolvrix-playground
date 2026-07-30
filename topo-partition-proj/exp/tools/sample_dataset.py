#!/usr/bin/env python3

"""Generate one round of training regions (docs/04 Phase 0 task 3, D4).

Usage:

    sample_dataset.py <instruction_graph.jsonl> <out_dir> [--count N] [--seed S]

Writes region_XXXX.npz files + manifest.json (with the coverage report) into
<out_dir>, and prints the coverage summary checked by the M0 gate.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.graph import load_graph  # noqa: E402
from harness.sampler import Sampler, SamplerConfig, save_dataset  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph")
    parser.add_argument("out_dir")
    parser.add_argument("--count", type=int, default=512)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    started = time.time()
    graph = load_graph(args.graph)
    sampler = Sampler(graph, SamplerConfig())
    print(
        f"[sample] graph: {graph.instructions} nodes, rare nodes {sampler.rare_nodes.size}, "
        f"holdout topo [{sampler.holdout_start}, {sampler.holdout_end})"
    )
    regions, report = sampler.sample_round(args.count, seed=args.seed)
    save_dataset(regions, report, args.out_dir)
    cov = report["coverage"]
    print(f"[sample] {cov['region_count']} regions -> {args.out_dir} "
          f"in {time.time() - started:.1f}s")
    print(f"[sample] method split: {cov['method_split']}")
    print(f"[sample] internal size: {cov['internal_size']}")
    print(f"[sample] rare-region fraction: {cov['rare_region_frac']:.3f} "
          f"({cov['rare_region_count']} regions)")
    print(f"[sample] opcode types covered: {cov['opcode_types_covered']}"
          f"/{cov['opcode_types_in_graph']}")
    print(f"[sample] union internal nodes: {cov['union_internal_nodes']} "
          f"({cov['union_internal_frac_of_graph']:.1%} of graph)")
    print(f"[sample] halo size: {cov['halo_size']}")
    print(f"[sample] holdout violations: {cov['holdout_violations']}")
    print(f"[sample] regions with capped hub fanout: {cov['regions_with_halo_cap']}")
    print(f"[sample] uncovered ops: {cov['uncovered_ops']}")
    (Path(args.out_dir) / "coverage.json").write_text(
        json.dumps(cov, indent=1, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
