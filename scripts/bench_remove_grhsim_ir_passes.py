"""Time native simulation passes on an isolated ordinary GRH checkpoint."""

import argparse
import json
import time
from pathlib import Path

import wolvrix

from grhsim_flow import checked, run_pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--passes", nargs="+", default=["grhsim-simplify"])
    parser.add_argument("--rounds", type=int, default=8)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "ptmp/remove-grhsim-ir"
    if not args.report.resolve().is_relative_to(root) or args.rounds < 1:
        parser.error("report must be under ptmp/remove-grhsim-ir; rounds must be positive")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    timings = []
    with wolvrix.Session() as session:
        session.log_level = "info"
        session.diagnostics_raise_min_level = "none"
        start = time.perf_counter()
        checked(session.read_json_file(str(args.model.resolve()), out_design="design.main"), "load checkpoint")
        timings.append({"pass": "load", "wall_s": time.perf_counter() - start})
        metadata = session.graph_metadata(design="design.main")
        top = metadata["symbol"]
        passes = list(args.passes)
        if "grhsim.stage" not in metadata["metadata"]:
            passes.insert(0, "grh-to-grhsim")
        for name in passes:
            options = ({"logic_domain": "2state"} if name == "grh-to-grhsim" else
                       {"max_rounds": args.rounds} if name == "grhsim-simplify" else {})
            start = time.perf_counter()
            run_pass(session, name, design="design.main", top=top, **options)
            timings.append({"pass": name, "wall_s": time.perf_counter() - start})
            args.report.write_text(json.dumps({"model": str(args.model.resolve()),
                "scope": "checkpoint screening only; not SV-to-emu acceptance",
                "timings": timings}, indent=2) + "\n")
    print(json.dumps(timings), flush=True)


if __name__ == "__main__":
    main()
