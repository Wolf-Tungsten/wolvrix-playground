"""Measure SinkSchedule rebuild from a completed ordinary GRH checkpoint."""

import argparse
import json
from pathlib import Path
import resource
import time

import wolvrix

from grhsim_flow import FlowOptions, checked, finish_simulation_graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not args.report.resolve().is_relative_to(root / "ptmp/remove-grhsim-ir"):
        parser.error("report must be under ptmp/remove-grhsim-ir")
    start = time.perf_counter()
    with wolvrix.Session() as session:
        session.diagnostics_raise_min_level = "none"
        checked(session.read_json_file(str(args.model.resolve()), out_design="design.main"), "load checkpoint")
        info = session.graph_metadata(design="design.main")
        top, metadata = info["symbol"], info["metadata"]
        if metadata.get("grhsim.stage") != "sink-partitioned":
            parser.error("probe requires the final sink-partitioned checkpoint")
        loaded = time.perf_counter()
        finish_simulation_graph(session, design="design.main", top=top,
                                options=FlowOptions.from_metadata(metadata))
        rebuilt = time.perf_counter()
    result = {"schema": "wolvrix.remove-grhsim-ir.sink-probe.v1", "model": str(args.model),
              "load_seconds": loaded - start, "rebuild_seconds": rebuilt - loaded,
              "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "scope": "checkpoint rebuild diagnostic, not full SV generation or formal A/B"}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
