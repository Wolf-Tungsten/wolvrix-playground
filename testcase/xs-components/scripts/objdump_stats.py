#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path


INSN_RE = re.compile(r"^\s*[0-9a-fA-F]+:\s+(?:[0-9a-fA-F]{2}\s+)+\s*([A-Za-z_.][A-Za-z0-9_.]*)")
SECTION_RE = re.compile(r"^\s*\d+\s+(\S+)\s+([0-9a-fA-F]+)\s+")


def text_size(path: Path, objdump: str) -> int:
    proc = subprocess.run([objdump, "-h", str(path)], check=True, text=True, stdout=subprocess.PIPE)
    total = 0
    for line in proc.stdout.splitlines():
        match = SECTION_RE.match(line)
        if match and (match.group(1) == ".text" or match.group(1).startswith(".text.")):
            total += int(match.group(2), 16)
    return total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--objdump", default="objdump")
    parser.add_argument("objects", nargs="+")
    args = parser.parse_args()

    counts: Counter[str] = Counter()
    text_bytes = 0
    for item in args.objects:
        path = Path(item)
        text_bytes += text_size(path, args.objdump)
        proc = subprocess.run([args.objdump, "-d", str(path)], check=True, text=True, stdout=subprocess.PIPE)
        for line in proc.stdout.splitlines():
            match = INSN_RE.match(line)
            if match:
                counts[match.group(1)] += 1

    payload = {
        "label": args.label,
        "objects": args.objects,
        "instruction_total": sum(counts.values()),
        "text_size_bytes": text_bytes,
        "mnemonics": dict(sorted(counts.items())),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="ascii")
    print(f"{args.label}: instructions={payload['instruction_total']} text_size_bytes={text_bytes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
