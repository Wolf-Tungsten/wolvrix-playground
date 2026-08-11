#!/usr/bin/env python3
"""NO0002 three-level structural alignment report (gsim vs grhsim-am).

Consumes:
  --gsim-stats FILE   gsim Final_Stats.json (--dump-stats-json --dump-stages=Final)
  --am-log FILE       grhsim-am-lower-json schedule log (production schedule stats line)
  --am-blocks FILE    AM block_assignment.jsonl (per-block {"size","atoms"})

Prints the three-level aligned comparison:
  L1 enode vs instr, L2 node vs atom, L3 supernode vs compute block.
"""
from __future__ import annotations

import argparse
import json
import re


def parse_am_log(path: str) -> dict:
    text = open(path, encoding="utf-8", errors="replace").read()
    out = {}
    m = re.search(r"production schedule stats: ([^\n]+)", text)
    if not m:
        return out
    body = m.group(1)
    for key, value in re.findall(r"(\w+)=([0-9.]+)", body):
        out[key] = float(value) if "." in value else int(value)
    mix = re.search(r"opcode_mix\[([^\]]+)\]", body)
    if mix:
        out["opcode_mix"] = {
            k: int(v) for k, v in re.findall(r"([\w.]+)=(\d+)", mix.group(1))
        }
    return out


def vec_stats(path: str, field: str) -> dict:
    sizes = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec.get("record") == "block":
                sizes.append(int(rec[field]))
    sizes.sort()
    if not sizes:
        return {}

    def pct(num: float) -> int:
        return sizes[int((len(sizes) - 1) * num / 100.0)]

    return {
        "count": len(sizes),
        "sum": sum(sizes),
        "mean": round(sum(sizes) / len(sizes), 3),
        "p50": pct(50),
        "p90": pct(90),
        "p99": pct(99),
        "max": sizes[-1],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gsim-stats", required=True)
    ap.add_argument("--am-log", required=True)
    ap.add_argument("--am-blocks", required=True)
    args = ap.parse_args()

    gsim = json.load(open(args.gsim_stats))
    am = parse_am_log(args.am_log)

    print("=== L1: enode vs instr (static) ===")
    exp = gsim.get("expnodes", {})
    print(f"  gsim enodes: unique={exp.get('unique_count')} "
          f"node_ref={exp.get('node_ref_count')} "
          f"non_ref={exp.get('unique_count', 0) - exp.get('node_ref_count', 0)}")
    mix = am.get("opcode_mix", {})
    bookkeeping = sum(mix.get(k, 0) for k in
                      ("act.f", "act.b", "changed.any", "changed.pos", "changed.neg"))
    print(f"  AM instr: linear={am.get('linear_instructions')} "
          f"scheduled={am.get('scheduled_instructions')} bookkeeping={bookkeeping}")

    print("=== L2: node vs atom ===")
    ne = gsim.get("nodes_enodes", {})
    print(f"  gsim nodes_enodes: count={ne.get('count')} mean={ne.get('mean'):.3f} "
          f"p50={ne.get('median')} p90={ne.get('p90')} p99={ne.get('p99')} max={ne.get('max')}")
    print(f"  AM atoms={am.get('atoms')} instr/atom mean={am.get('mean', 0):.3f} "
          f"(atom_instr p50/p90/p99/max in log)")

    print("=== L3: supernode vs compute block ===")
    sm = gsim.get("supernodes_members", {})
    se = gsim.get("supernodes_enodes", {})
    print(f"  gsim supernodes: members count={sm.get('count')} mean={sm.get('mean'):.2f} "
          f"p50={sm.get('median')} p90={sm.get('p90')} p99={sm.get('p99')} max={sm.get('max')}")
    print(f"  gsim supernodes_enodes: mean={se.get('mean'):.2f} p50={se.get('median')} "
          f"p90={se.get('p90')} p99={se.get('p99')} max={se.get('max')}")
    for field in ("size", "atoms"):
        st = vec_stats(args.am_blocks, field)
        print(f"  AM block {field}: count={st.get('count')} mean={st.get('mean')} "
              f"p50={st.get('p50')} p90={st.get('p90')} p99={st.get('p99')} max={st.get('max')}")


if __name__ == "__main__":
    main()
