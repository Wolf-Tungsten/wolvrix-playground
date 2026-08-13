#!/usr/bin/env python3
"""NO0012 wide-chain bit-segment provenance prototype (v2).

Reads the NO0012-extended instruction-graph jsonl (res/ops/lsb/gnode fields).

For every atom containing wide (>= --min-width) data instructions, model each
value as a list of bit segments. A segment is either:
  ("root", var, lsb, width)   -- bits copied verbatim from a root variable
                                 (one not defined by a chain instruction in
                                 this atom: external bases, scalar elems)
  ("op", opcode, lsb, width, [child segments...]) -- per-bit elementwise op
                                 (and/or/xor/not/mux/assign) evaluated on
                                 child segments at the same bit offset

Chain instructions handled:
  concat        : segment list concatenation (result bit i from operand list)
  slice_static  : segment list window extraction by [lsb, lsb+width)
  assign/not/and/or/xor with wide operands: bitwise per-offset (all operand
                  segment lists must align bit-for-bit)
  mux with 1-bit cond: per-offset mux of the two data operands

A value "escapes" when it is used by an instruction outside the atom or by a
non-chain instruction inside the atom; escaped values must be materialized.
Cost model: old = sum of result words over wide chain instrs; new = for each
escaped value, one rebuild = its word count once (+ negligible scalar ops).

Verdict per atom: full match / partial (with refusal reason).
"""
import argparse
import json
from collections import defaultdict

CHAIN_BITWISE = {"and", "or", "xor", "not", "assign"}
W = 64

def words(nbits):
    return (nbits + W - 1) // W

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--min-width", type=int, default=4096)
    ap.add_argument("--dump-atom", type=int, default=0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    nodes = {}
    var_def = {}
    var_uses = defaultdict(list)
    with open(args.jsonl) as f:
        for line in f:
            if '"record":"node"' not in line:
                continue
            r = json.loads(line)
            nid = r["id"]
            nodes[nid] = r
            for v in r.get("res", []):
                var_def[v] = nid
            for ov in r.get("ops", []):
                var_uses[ov[0]].append(nid)

    atoms = defaultdict(list)
    for nid, r in nodes.items():
        atoms[r["atom"]].append(nid)

    report = []
    stats = defaultdict(int)
    for atom, members in atoms.items():
        # chain instructions: concat / slice_static / bitwise / mux with a
        # wide result or any wide operand
        chain = {}
        for nid in members:
            r = nodes[nid]
            op = r["opcode"]
            wide_res = r["width"] >= args.min_width
            wide_op = any(ow >= args.min_width for _, ow in r.get("ops", []))
            if not (wide_res or wide_op):
                continue
            if op in ("concat", "slice_static") or op in CHAIN_BITWISE or op == "mux":
                chain[nid] = r
            else:
                # wide value involved in a non-chain op -> its operands escape
                pass
        if not chain:
            continue
        stats["atoms_with_wide"] += 1

        prov = {}   # var -> segment list
        ok = True
        reason = ""
        old_words = 0
        for nid in sorted(chain):
            r = nodes[nid]
            if len(r["res"]) != 1:
                ok = False; reason = "multi-result"; break
            resv = r["res"][0]
            resw = r["width"]
            old_words += words(resw)
            op = r["opcode"]

            def segs_of(v, w):
                if v in prov:
                    return prov[v]
                return [("root", v, 0, w)]

            if op == "concat":
                segs = []
                for ov, ow in r["ops"]:
                    segs.extend(segs_of(ov, ow))
                total = sum(s[3] for s in segs)
                if total < resw:
                    segs.append(("zero", 0, 0, resw - total))
                prov[resv] = segs
            elif op == "slice_static":
                lsb = r.get("lsb")
                if lsb is None or len(r["ops"]) != 1:
                    ok = False; reason = "slice attrs"; break
                ov, ow = r["ops"][0]
                src = segs_of(ov, ow)
                out = []
                pos = 0
                want_lo, want_hi = lsb, lsb + resw
                for s in src:
                    slo, shi = pos, pos + s[3]
                    pos = shi
                    lo, hi = max(slo, want_lo), min(shi, want_hi)
                    if lo >= hi:
                        continue
                    if s[0] == "root":
                        out.append(("root", s[1], s[2] + (lo - slo), hi - lo))
                    elif s[0] == "op":
                        out.append(("op", s[1], s[2] + (lo - slo), hi - lo, s[4]))
                    else:
                        out.append(("zero", 0, 0, hi - lo))
                if sum(s[3] for s in out) != resw:
                    ok = False; reason = "slice coverage"; break
                prov[resv] = out
            elif op in CHAIN_BITWISE:
                opss = r["ops"]
                lists = [segs_of(ov, ow) for ov, ow in opss]
                # require exact bit alignment across operand segment lists
                aligned = True
                for other in lists[1:]:
                    if [(s[3]) for s in other] != [s[3] for s in lists[0]]:
                        aligned = False; break
                if not aligned:
                    ok = False; reason = f"bitwise segment misalignment"; break
                out = []
                for i, s in enumerate(lists[0]):
                    children = [tuple(l[i]) for l in lists]
                    out.append(("op", op, s[2], s[3], children))
                prov[resv] = out
            elif op == "mux":
                if len(r["ops"]) != 3 or r["ops"][0][1] != 1:
                    ok = False; reason = "mux cond width"; break
                cond = r["ops"][0][0]
                lt = segs_of(*r["ops"][1])
                lf = segs_of(*r["ops"][2])
                if [s[3] for s in lt] != [s[3] for s in lf]:
                    ok = False; reason = "mux segment misalignment"; break
                out = []
                for i, s in enumerate(lt):
                    out.append(("op", "mux", s[2], s[3],
                                [("root", cond, 0, 1), tuple(s), tuple(lf[i])]))
                prov[resv] = out
        if not ok:
            stats["reject"] += 1
            report.append({"atom": atom, "gnode": chain[sorted(chain)[0]].get("gnode"),
                           "match": False, "reason": reason,
                           "members": len(members), "chain": len(chain)})
            continue

        # escapes: chain-produced var used by any instruction not in chain
        chainvars = set(prov.keys())
        escaped = set()
        for v in chainvars:
            for u in var_uses.get(v, []):
                if u not in chain:
                    escaped.add(v); break
        new_words = 0
        for v in escaped:
            new_words += words(sum(s[3] for s in prov[v]))
        stats["matched_atoms"] += 1
        stats["old_words"] += old_words
        stats["new_words"] += new_words
        entry = {"atom": atom,
                 "gnode": nodes[sorted(chain)[0]].get("gnode"),
                 "match": True, "members": len(members), "chain": len(chain),
                 "old_words": old_words, "new_words": new_words,
                 "escaped": len(escaped)}
        report.append(entry)
        if args.dump_atom == atom:
            for v in sorted(prov):
                print(f"  var {v} segs={prov[v][:6]}{'...' if len(prov[v])>6 else ''}")

    out = {"stats": dict(stats),
           "report": sorted(report, key=lambda x: -x.get("old_words", 0))[:300]}
    text = json.dumps(out, indent=1)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
    print(json.dumps(out["stats"], indent=1))
    for e in out["report"][:15]:
        print(e)

if __name__ == "__main__":
    main()
