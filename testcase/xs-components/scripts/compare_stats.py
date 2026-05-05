#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="ascii"))


def top_map(data: dict) -> dict[str, tuple[int, float]]:
    return {item["mnemonic"]: (int(item["count"]), float(item["percent"])) for item in data["top"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gsim", required=True)
    parser.add_argument("--grhsim", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    gsim = load(Path(args.gsim))
    grhsim = load(Path(args.grhsim))
    g = top_map(gsim)
    r = top_map(grhsim)
    mnemonics = sorted(set(g) | set(r))
    deltas = []
    for mnemonic in mnemonics:
        gc, gp = g.get(mnemonic, (0, 0.0))
        rc, rp = r.get(mnemonic, (0, 0.0))
        deltas.append(
            {
                "mnemonic": mnemonic,
                "gsim_count": gc,
                "gsim_percent": gp,
                "grhsim_count": rc,
                "grhsim_percent": rp,
                "percent_delta_grhsim_minus_gsim": rp - gp,
                "abs_percent_delta": abs(rp - gp),
            }
        )
    deltas.sort(key=lambda item: item["abs_percent_delta"], reverse=True)
    payload = {
        "gsim_instruction_total": gsim["instruction_total"],
        "grhsim_instruction_total": grhsim["instruction_total"],
        "grhsim_to_gsim_ratio": (
            grhsim["instruction_total"] / gsim["instruction_total"]
            if gsim["instruction_total"]
            else None
        ),
        "top_percent_deltas": deltas[:50],
    }
    out_path = Path(args.out)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="ascii")

    print(
        "instruction totals: "
        f"gsim={payload['gsim_instruction_total']} "
        f"grhsim={payload['grhsim_instruction_total']} "
        f"ratio={payload['grhsim_to_gsim_ratio']:.3f}"
    )
    print("largest percent deltas:")
    for item in deltas[:20]:
        print(
            f"{item['percent_delta_grhsim_minus_gsim']:+8.4f}pp "
            f"gsim={item['gsim_count']:8d}/{item['gsim_percent']:7.3f}% "
            f"grhsim={item['grhsim_count']:8d}/{item['grhsim_percent']:7.3f}% "
            f"{item['mnemonic']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
