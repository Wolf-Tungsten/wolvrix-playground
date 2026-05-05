#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path


INSTRUCTION_RE = re.compile(r"^\s*[0-9a-fA-F]+:\s+([A-Za-z_.][A-Za-z0-9_.]*)")


def collect(paths: list[Path], objdump: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    for path in paths:
        proc = subprocess.run(
            [objdump, "-d", "-Mintel", "--no-show-raw-insn", str(path)],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for line in proc.stdout.splitlines():
            match = INSTRUCTION_RE.match(line)
            if match:
                counter[match.group(1)] += 1
    return counter


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--objdump", default="objdump")
    parser.add_argument("objects", nargs="+")
    args = parser.parse_args()

    paths = [Path(item) for item in args.objects]
    counter = collect(paths, args.objdump)
    total = sum(counter.values())
    top = [
        {
            "mnemonic": mnemonic,
            "count": count,
            "percent": (100.0 * count / total) if total else 0.0,
        }
        for mnemonic, count in counter.most_common(80)
    ]
    payload = {
        "label": args.label,
        "object_count": len(paths),
        "instruction_total": total,
        "top": top,
        "objects": [str(path) for path in paths],
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="ascii")

    print(f"{args.label}: objects={len(paths)} instructions={total}")
    for item in top[:20]:
        print(f"{item['count']:10d} {item['percent']:8.4f}% {item['mnemonic']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
