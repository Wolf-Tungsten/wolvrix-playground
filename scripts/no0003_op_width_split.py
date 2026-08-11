#!/usr/bin/env python3
"""Split exec.json op counts by output-value width class (<=64b vs >64b).

emit-cost NO0003: quantify how much of the exporter's op inflation vs gsim's
internal flat graph comes from wide-value (>64b) word-expansion lowering.
"""

import json
import re
import sys
from collections import Counter

VALUE_REC = re.compile(r'\{"sym": "(gsim\.[a-z]+\.\d+)", "w": (\d+)')
OP_REC = re.compile(r'\{"sym": "gsim\.expr\.\d+", "kind": "([A-Za-z0-9_]+)".*?"out": \["(gsim\.[^"]+)"\]')


def main() -> int:
    path = sys.argv[1]
    widths = {}
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = VALUE_REC.search(line)
            if match:
                widths[match.group(1)] = int(match.group(2))
    narrow = Counter()
    wide = Counter()
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = OP_REC.search(line)
            if not match:
                continue
            kind, out = match.group(1), match.group(2)
            if widths.get(out, 0) > 64:
                wide[kind] += 1
            else:
                narrow[kind] += 1
    print(json.dumps({
        "narrow_ops": dict(narrow.most_common(12)),
        "wide_ops": dict(wide.most_common(12)),
        "narrow_total": sum(narrow.values()),
        "wide_total": sum(wide.values()),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
