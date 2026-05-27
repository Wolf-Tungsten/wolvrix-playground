#!/usr/bin/env python3

import argparse
import re
from pathlib import Path


PORTS = [
    ("in0", "GSIM_IO_IN0_WIDTH"),
    ("in1", "GSIM_IO_IN1_WIDTH"),
    ("in2", "GSIM_IO_IN2_WIDTH"),
    ("in3", "GSIM_IO_IN3_WIDTH"),
    ("in4", "GSIM_IO_IN4_WIDTH"),
    ("in5", "GSIM_IO_IN5_WIDTH"),
    ("ctrl", "GSIM_IO_CTRL_WIDTH"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--header", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    text = args.header.read_text(encoding="utf-8")
    pattern = re.compile(r"\bio\$\$(?P<port>in[0-5]|ctrl)\s*;\s*//\s*width\s*=\s*(?P<width>\d+)")
    widths = {port: "64" for port, _ in PORTS}
    for match in pattern.finditer(text):
        widths[match.group("port")] = match.group("width")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["#pragma once", ""]
    for port, macro in PORTS:
        lines.append(f"#define {macro} {widths[port]}")
    lines.append("")
    args.out.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
