#!/usr/bin/env python3
"""Stream-scan a gsim executable-GRH v2 JSON (exec.json) and report graph stats.

Counts, in a single pass:
- value records by sym prefix: gsim.v.* / gsim.reg.* (anchor values bound to a
  gsim node) vs gsim.tmp.* (assignTree-internal temporaries created by the
  exporter's flattening) vs anything else;
- operation records by kind (kMux, kAdd, ...);
- values carrying a gsim.node_id attr (true node anchors).

Used by emit-cost NO0003 to verify that the --flatten-nodes export lands on a
fully-flattened graph: anchor count ~= gsim node count, gsim.tmp count ~= 0.
"""

import json
import re
import sys
from collections import Counter

VALUE_SYM = re.compile(r'\{"sym": "(gsim\.[a-z_]+)\.')
# NO0004 fix: op records exist under non-expr syms too (gsim.assign.* kAssign,
# gsim.reg.* kRegister, ...). Classify every record carrying a "kind" field,
# not just gsim.expr.* ones; the old expr-only filter undercounted kAssign by
# ~58k on the XS flatten v2 export.
OP_KIND = re.compile(r'"kind": "([A-Za-z0-9_]+)"')
NODE_ID_ATTR = re.compile(r'"gsim\.node_id"')
OUT_SYM = re.compile(r'"out": \["(gsim\.[a-z]+)\.')


def scan(path: str) -> dict:
    value_prefix = Counter()
    op_kind = Counter()
    op_kind_anchor = Counter()  # ops carrying a gsim.node_id attr (node-bound)
    op_kind_glue = Counter()  # ops without gsim.node_id (exporter-introduced)
    op_out_prefix = Counter()  # (kind, first-out sym prefix)
    values = 0
    values_with_node_id = 0
    ops = 0
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = VALUE_SYM.search(line)
            if not match:
                continue
            prefix = match.group(1)
            value_prefix[prefix] += 1
            kind = OP_KIND.search(line)
            has_node_id = NODE_ID_ATTR.search(line) is not None
            if kind:
                ops += 1
                op_kind[kind.group(1)] += 1
                if has_node_id:
                    op_kind_anchor[kind.group(1)] += 1
                else:
                    op_kind_glue[kind.group(1)] += 1
                out = OUT_SYM.search(line)
                if out:
                    op_out_prefix[f"{kind.group(1)}->{out.group(1)}"] += 1
            if prefix == "gsim.expr":
                continue
            values += 1
            if has_node_id:
                values_with_node_id += 1
    return {
        "file": path,
        "values": values,
        "values_with_node_id": values_with_node_id,
        "value_prefix": dict(value_prefix.most_common()),
        "ops": ops,
        "op_kind": dict(op_kind.most_common()),
        "op_kind_anchor": dict(op_kind_anchor.most_common()),
        "op_kind_glue": dict(op_kind_glue.most_common()),
        "op_out_prefix": dict(op_out_prefix.most_common()),
    }


def main() -> int:
    results = [scan(path) for path in sys.argv[1:]]
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
