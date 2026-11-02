"""Check frozen-library pass comparisons and report measured fixture timings."""

import argparse
import json
import re
from pathlib import Path


def rounds(work):
    log = work.parent / "logs" / (work.name + ".log")
    return [re.sub(r"\b(?:elapsed|fold-share|mux|state-merge|dce|used-bits|topo)-ms=\d+\s*", "", line)
            for line in log.read_text().splitlines() if line.startswith("grhsim-simplify: round")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", nargs=2, type=Path, action="append", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    results = []
    for before, after in args.pair:
        old, new = [json.loads((work / "report.json").read_text()) for work in (before, after)]
        if old["fixture_sha256"] != new["fixture_sha256"] or rounds(before) != rounds(after):
            raise RuntimeError(f"{after}: fixture or simplify iteration results differ")
        old_library, new_library = [next(entry for entry in report["loaded_libraries"]
                                        if Path(entry["path"]).name == "libwolvrix-lib.so")
                                    for report in (old, new)]
        if old_library["sha256"] == new_library["sha256"]:
            raise RuntimeError(f"{after}: same native library used for both runs")
        stages = []
        for previous, current in zip(old["stages"], new["stages"], strict=True):
            for key in ("pass", "sha256", "operations", "values", "diagnostics"):
                if previous[key] != current[key]:
                    raise RuntimeError(f"{after}: {current['pass']} {key} differs")
            row = {"pass": current["pass"], "before_s": previous["wall_s"],
                   "after_s": current["wall_s"],
                   "reduction_percent": 100 * (1 - current["wall_s"] / previous["wall_s"]),
                   "output_sha256": current["sha256"]}
            stages.append(row)
            print(f"{after.name}: {row['pass']} {row['before_s']:.6f}s -> "
                  f"{row['after_s']:.6f}s ({row['reduction_percent']:+.2f}% less time)")
        results.append({"before": str(before.resolve()), "after": str(after.resolve()),
                        "before_library": old_library, "after_library": new_library,
                        "rounds": rounds(after), "stages": stages})
    root = Path(__file__).resolve().parents[1]
    if not args.report.resolve().is_relative_to(root / "ptmp"):
        parser.error("report must be under repository ptmp")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"scope": "single samples on generated fixtures; no whole-chip claim",
                                      "comparisons": results}, indent=2) + "\n")


if __name__ == "__main__":
    main()
