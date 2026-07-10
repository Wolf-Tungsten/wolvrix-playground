#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("stats", nargs="+")
    args = parser.parse_args()

    rows = []
    for item in args.stats:
        data = json.loads(Path(item).read_text(encoding="ascii"))
        rows.append(
            {
                "case": data["case"],
                "kind": data["kind"],
                "scale": data["scale"],
                "gsim_ms": data["gsim"]["bench_ms"],
                "grhsim_ms": data["grhsim"]["bench_ms"],
                "bench_ms_grhsim_to_gsim": data["ratios"]["bench_ms_grhsim_to_gsim"],
                "gsim_supernodes": data["gsim"]["supernodes"],
                "grhsim_supernodes": data["grhsim"]["supernodes"],
                "gsim_instructions": data["gsim"]["instruction_count"],
                "grhsim_instructions": data["grhsim"]["instruction_count"],
                "instruction_count_grhsim_to_gsim": data["ratios"]["instruction_count_grhsim_to_gsim"],
                "gsim_text_bytes": data["gsim"]["text_size_bytes"],
                "grhsim_text_bytes": data["grhsim"]["text_size_bytes"],
            }
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="ascii", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
