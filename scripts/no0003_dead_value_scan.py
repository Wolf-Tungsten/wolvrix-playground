#!/usr/bin/env python3
"""Stream-scan an exec.json v2 and count producer values never consumed.

Two passes over the file:
  pass 1: collect producer syms from "out": [...] (and value records);
  pass 2: collect consumer syms from "in": [...] lines of op records.
Reports produced-but-never-consumed counts split by anchor (gsim.v/reg) vs
tmp (gsim.tmp), for emit-cost NO0003's DCE attribution.
"""

import json
import re
import sys

OUT_SYMS = re.compile(r'"out": \[([^\]]*)\]')
IN_SYMS = re.compile(r'"in": \[([^\]]*)\]')
SYM = re.compile(r'"(gsim\.[^"]+)"')
REG_SYMBOL = re.compile(r'"regSymbol": "(gsim\.[^"]+)"')
VALUE_REC = re.compile(r'\{"sym": "(gsim\.[a-z]+\.\d+)", "w":')
OUT_PORT = re.compile(r'"out": true')


def split(line: str):
    out_match = OUT_SYMS.search(line)
    in_match = IN_SYMS.search(line)
    outs = SYM.findall(out_match.group(1)) if out_match else []
    ins = SYM.findall(in_match.group(1)) if in_match else []
    return outs, ins


def klass(sym: str) -> str:
    if sym.startswith("gsim.tmp."):
        return "tmp"
    if sym.startswith("gsim.v.") or sym.startswith("gsim.reg."):
        return "anchor"
    return sym.split(".")[1] if "." in sym else "other"


def main() -> int:
    path = sys.argv[1]
    produced = {}
    consumed = set()
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            # top-level output ports leave the design: count as consumed
            value_match = VALUE_REC.search(line)
            if value_match and OUT_PORT.search(line):
                consumed.add(value_match.group(1))
            reg_match = REG_SYMBOL.search(line)
            if reg_match:
                consumed.add(reg_match.group(1))
            if '"out":' not in line:
                continue
            outs, ins = split(line)
            for sym in outs:
                produced[sym] = klass(sym)
            for sym in ins:
                consumed.add(sym)
    dead = {}
    for sym, cls in produced.items():
        if sym not in consumed:
            dead[cls] = dead.get(cls, 0) + 1
    print(json.dumps({
        "file": path,
        "produced": len(produced),
        "consumed_distinct": len(consumed),
        "dead_by_class": dead,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
