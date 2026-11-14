"""Compare already exported full-graph F29 exchange databases and journals."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from export_f29_full_split_exchange import (
    comparison_boundaries, evolution_summary, public_compare, verify_grh_continuity,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "ptmp"):
        parser.error("output must be under repository ptmp/")
    summary = json.loads((output / "summary.json").read_text())
    grh_split = summary["grh_verification"]["grh-split"]
    grh_comb = summary["grh_verification"].get("grh-comb")
    boundaries = comparison_boundaries(grh_split, summary["gsim_verification"], grh_comb)
    continuity = None
    if grh_comb:
        continuity = verify_grh_continuity(
            output / "grh-comb.sqlite", output / "grh-split.sqlite", grh_comb, grh_split)
    result = public_compare(output / "grh-split.sqlite", output / "gsim-split.sqlite")
    result["semantic_boundaries"] = boundaries
    summary["semantic_boundaries"] = boundaries
    if continuity:
        result["grh_continuity"] = continuity
        summary["grh_continuity"] = continuity
    result["evolution"] = {
        "grh_split": evolution_summary(output / "grh-split/evolution.tsv"),
        "gsim_split": evolution_summary(output / "gsim-split/evolution.tsv"),
    }
    if grh_comb:
        result["evolution"]["grh_comb"] = evolution_summary(output / "grh-comb/evolution.tsv")
    summary["comparison"] = result
    summary["evolution_summary"] = result["evolution"]
    summary["comparison_report_complete"] = True
    (output / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
