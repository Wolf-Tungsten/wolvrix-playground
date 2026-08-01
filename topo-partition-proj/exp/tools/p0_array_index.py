#!/usr/bin/env python3

"""P0 array inventory: stream a GRH stats/store JSON and build a compact op
index pickle (docs/27 tooling). Solidifies the /tmp/grh_op_index.pkl method
(docs/25 §4) with per-op metadata needed for array analysis.

Op lines in these JSONs are single-line objects inside each graph's "ops"
array, e.g.
  {"sym": "_op_12625", "kind": "kRegisterWritePort", "in": [...], "out": [],
   "attrs": {...}, "loc": {"file": ".../Rob.sv", ...}},

Output pickle: (ops, defs, meta)
  ops:  dict sym -> (kind, tuple(in), tuple(out))
  defs: dict value -> defining op sym
  meta: dict sym -> (loc_basename, target_symbol, width)
        loc_basename: loc.file basename ("" if none)
        target_symbol: regSymbol/memSymbol attr ("" if none)
        width: kRegister/kMemory width attr (0 otherwise)

Usage:

    p0_array_index.py <grh.json> <out.pkl>
"""

from __future__ import annotations

import json
import pickle
import sys
import time
from pathlib import Path


def main() -> int:
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    ops: dict[str, tuple] = {}
    defs: dict[str, str] = {}
    meta: dict[str, tuple] = {}
    started = time.time()
    n_lines = 0
    n_ops = 0
    dup = 0
    with src.open("r", encoding="utf-8") as fh:
        for line in fh:
            n_lines += 1
            if not line.startswith('        {"sym":'):
                continue
            line = line.rstrip()
            if line.endswith(","):
                line = line[:-1]
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            sym = rec.get("sym")
            kind = rec.get("kind")
            if not isinstance(sym, str) or not isinstance(kind, str):
                continue
            ins = rec.get("in") or ()
            outs = rec.get("out") or ()
            if sym in ops:
                dup += 1
            ops[sym] = (kind, tuple(ins), tuple(outs))
            attrs = rec.get("attrs") or {}
            loc = rec.get("loc") or {}
            target = ""
            for key in ("regSymbol", "memSymbol"):
                a = attrs.get(key)
                if isinstance(a, dict) and isinstance(a.get("v"), str):
                    target = a["v"]
                    break
            width = 0
            wa = attrs.get("width")
            if isinstance(wa, dict) and isinstance(wa.get("v"), int):
                width = wa["v"]
            meta[sym] = (str(loc.get("file", "")).rsplit("/", 1)[-1], target, width)
            for v in outs:
                defs[v] = sym
            n_ops += 1
            if n_ops % 1_000_000 == 0:
                print(f"  ... {n_ops} ops, {n_lines} lines, {time.time()-started:.0f}s", flush=True)
    payload = (ops, defs, meta)
    with dst.open("wb") as fh:
        pickle.dump(payload, fh, protocol=4)
    print(
        json.dumps(
            {
                "src": str(src),
                "ops": n_ops,
                "values": len(defs),
                "dups": dup,
                "seconds": round(time.time() - started, 1),
                "out": str(dst),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
