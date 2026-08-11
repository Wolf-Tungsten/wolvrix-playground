#!/usr/bin/env python3
"""Classify dead anchor values in an exec.json by node-name suffix pattern.

emit-cost NO0003 debug tool: the flat export has ~161k more dead anchors than
the tree export; group them by name suffix ($whold / $flat / $DUP / plain) and
print a few examples per class.
"""

import json
import re
import sys
from collections import Counter

OUT_SYMS = re.compile(r'"out": \[([^\]]*)\]')
IN_SYMS = re.compile(r'"in": \[([^\]]*)\]')
SYM = re.compile(r'"(gsim\.[^"]+)"')
VALUE_REC = re.compile(
    r'\{"sym": "(gsim\.v\.\d+)".*?"gsim\.node_name": \{"t": "string", "v": "([^"]+)"\}')
REG_SYMBOL = re.compile(r'"regSymbol": "(gsim\.[^"]+)"')
OUT_PORT = re.compile(r'"out": true')


def klass(name: str) -> str:
    if "$whold" in name:
        return "whold"
    if "$flat" in name:
        return "flat"
    if "$DUP" in name:
        return "dup"
    if "$" in name:
        return "other_sep"
    return "plain"


def main() -> int:
    path = sys.argv[1]
    names = {}
    consumed = set()
    produced = set()
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            value_match = VALUE_REC.search(line)
            if value_match:
                names[value_match.group(1)] = value_match.group(2)
                if OUT_PORT.search(line):
                    consumed.add(value_match.group(1))
            reg_match = REG_SYMBOL.search(line)
            if reg_match:
                consumed.add(reg_match.group(1))
            if '"out":' not in line:
                continue
            out_match = OUT_SYMS.search(line)
            in_match = IN_SYMS.search(line)
            if out_match:
                produced.update(SYM.findall(out_match.group(1)))
            if in_match:
                consumed.update(SYM.findall(in_match.group(1)))
    counts = Counter()
    examples = {}
    for sym in produced:
        if not sym.startswith("gsim.v.") or sym in consumed:
            continue
        name = names.get(sym, "?")
        cls = klass(name)
        counts[cls] += 1
        examples.setdefault(cls, []).append(name)
    print(json.dumps({"dead_anchor_by_name_class": dict(counts.most_common())}, indent=2))
    for cls, names_list in examples.items():
        print(f"--- {cls} ({len(names_list)}):")
        for name in names_list[:5]:
            print(f"    {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
