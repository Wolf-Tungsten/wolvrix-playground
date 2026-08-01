#!/usr/bin/env python3

"""P0 array ledger (docs/27): join the reg-to-mem group report
(/tmp/r2m_report_r1.json, group_id keyed) with the verbose group_progress /
edge_padded_group lines of the AM build log (first_reg/last_reg names) to
produce:

1. outcome x reject_reason distribution (groups/elements);
2. named groups table: array name, instance-path tail, element count/width,
   outcome, reject_reason;
3. unnamed groups clustered by (element_width, element_count, reject_reason).

Array name derivation: first_reg/last_reg look like
`cpu$l_soc$...$rob$robEntries_0_uopNum` ... `...$robEntries_351_uopNum`.
Common prefix of first/last up to the varying `_<idx>` run gives the array
base; the trailing `_<field>` after the index (if identical in first/last)
gives the field.

Usage:

    p0_array_ledger.py --report /tmp/r2m_report_r1.json \
        --log build/logs/xs/xs_wolf_grhsim_am_build_20260731_163842.log \
        [--json /tmp/p0_ledger.json]
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

GROUP_RE = re.compile(
    r"group=(?P<gid>\d+)/\d+ anchors=(?P<anchors>\d+) members=(?P<members>\d+) "
    r"element_width=(?P<width>\d+) storage_rows=(?P<rows>\d+) "
    r"row_offset=(?P<rowoff>\d+) decoded_write=(?P<decoded>\d+) "
    r"first_reg=(?P<first>\S+) last_reg=(?P<last>\S+)"
)
EDGE_RE = re.compile(
    r"edge_padded_group .* group=(?P<gid>\d+)/\d+ anchors=(?P<anchors>\d+) "
    r"members=(?P<members>\d+) true_merged=(?P<tm>\d) "
    r"first_reg=(?P<first>\S+) last_reg=(?P<last>\S+)"
)
IDX_RE = re.compile(r"_(\d+)")


def split_symbol(sym: str) -> tuple[str, str]:
    """Split `a$b$c$regName` -> (`a$b$c`, `regName`)."""
    if "$" in sym:
        path, _, name = sym.rpartition("$")
        return path, name
    return "", sym


def derive_array(first: str, last: str) -> tuple[str, str, str, int, int]:
    """Derive (array_path, base_name, field, lo_idx, hi_idx).

    array_path = instance path + base name (without the _<idx> part).
    """
    fpath, fname = split_symbol(first)
    lpath, lname = split_symbol(last)
    path = fpath if fpath == lpath else f"{fpath}|{lpath}"

    # Find the index run: first position where first/last disagree inside a _<digits> token.
    f_toks = list(IDX_RE.finditer(fname))
    l_toks = list(IDX_RE.finditer(lname))
    base = fname
    field = ""
    lo = hi = -1
    if f_toks and l_toks and len(f_toks) == len(l_toks):
        # Use the FIRST numeric run that differs between first and last as the element index.
        for fm, lm in zip(f_toks, l_toks):
            if fm.start() == lm.start() and fm.group(1) != lm.group(1):
                lo, hi = int(fm.group(1)), int(lm.group(1))
                base = fname[: fm.start()]
                field = fname[fm.end():]
                lfield = lname[lm.end():]
                if field != lfield:
                    field = field + "|" + lfield
                break
        else:
            # All index runs identical (single-element span?) — treat last run as index.
            fm = f_toks[-1]
            lo = hi = int(fm.group(1))
            base = fname[: fm.start()]
            field = fname[fm.end():]
    array_path = f"{path}${base}" if path else base
    return array_path, base, field, lo, hi


def path_tail(path: str, n: int = 4) -> str:
    parts = [p for p in path.split("$") if p]
    return "$".join(parts[-n:])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    report = json.loads(Path(args.report).read_text())
    groups = report["groups"]

    names: dict[int, dict] = {}
    for line in Path(args.log).open():
        if "first_reg=" not in line:
            continue
        m = GROUP_RE.search(line)
        if m:
            gid = int(m.group("gid"))
            names[gid] = {
                "members": int(m.group("members")),
                "width": int(m.group("width")),
                "decoded_write": int(m.group("decoded")),
                "first": m.group("first"),
                "last": m.group("last"),
            }
            continue
        m = EDGE_RE.search(line)
        if m:
            gid = int(m.group("gid"))
            names.setdefault(
                gid,
                {
                    "members": int(m.group("members")),
                    "width": -1,
                    "decoded_write": -1,
                    "first": m.group("first"),
                    "last": m.group("last"),
                },
            )

    # Ledger over all groups.
    by_outcome_reason: Counter = Counter()
    named_rows = []
    unnamed_clusters: dict[tuple, dict] = {}
    named_elements = 0
    unnamed_elements = 0
    array_agg: dict[tuple, dict] = {}

    for g in groups:
        gid = g["group_id"]
        key = (g["outcome"], g["reject_reason"])
        by_outcome_reason[key] += 1
        elems = g["element_count"]
        info = names.get(gid)
        exploded = g["outcome"] != "true_merged"
        if info:
            array_path, base, field, lo, hi = derive_array(info["first"], info["last"])
            row = {
                "group_id": gid,
                "array": array_path,
                "loc_tail": path_tail(array_path),
                "field": field,
                "lo": lo,
                "hi": hi,
                "elements": elems,
                "width": g["element_width"],
                "discovery": g["discovery"],
                "outcome": g["outcome"],
                "reject_reason": g["reject_reason"],
                "decoded_write": info["decoded_write"],
            }
            named_rows.append(row)
            named_elements += elems
            if exploded:
                agg = array_agg.setdefault(
                    array_path,
                    {
                        "array": array_path,
                        "loc_tail": path_tail(array_path),
                        "groups": 0,
                        "elements": 0,
                        "width": g["element_width"],
                        "reasons": Counter(),
                        "fields": set(),
                        "decoded_write": info["decoded_write"],
                    },
                )
                agg["groups"] += 1
                agg["elements"] += elems
                agg["reasons"][g["reject_reason"]] += 1
                if field:
                    agg["fields"].add(field)
        else:
            unnamed_elements += elems
            ckey = (g["element_width"], elems, g["outcome"], g["reject_reason"], g["discovery"])
            c = unnamed_clusters.setdefault(ckey, {"groups": 0, "elements": 0})
            c["groups"] += 1
            c["elements"] += elems

    named_rows.sort(key=lambda r: -r["elements"])
    exploded_rows = [r for r in named_rows if r["outcome"] != "true_merged"]
    merged_rows = [r for r in named_rows if r["outcome"] == "true_merged"]

    out = {
        "summary": report["summary"],
        "by_outcome_reason": {
            f"{k[0]}|{k[1]}": v for k, v in sorted(by_outcome_reason.items())
        },
        "named_groups": len(named_rows),
        "named_elements": named_elements,
        "unnamed_groups": len(groups) - len(named_rows),
        "unnamed_elements": unnamed_elements,
        "exploded_named_rows": exploded_rows,
        "merged_named_rows": merged_rows,
        "exploded_array_agg": sorted(
            (
                {**a, "reasons": dict(a["reasons"]), "fields": sorted(a["fields"])}
                for a in array_agg.values()
            ),
            key=lambda a: -a["elements"],
        ),
        "unnamed_clusters": [
            {
                "width": k[0],
                "element_count": k[1],
                "outcome": k[2],
                "reject_reason": k[3],
                "discovery": k[4],
                **v,
            }
            for k, v in sorted(
                unnamed_clusters.items(), key=lambda kv: -kv[1]["elements"]
            )
        ],
    }

    # Console digest.
    print("== outcome x reason (groups) ==")
    for k, v in sorted(by_outcome_reason.items(), key=lambda kv: -kv[1]):
        print(f"  {k[0]:>17} / {k[1] or '-':<24} {v}")
    print(f"named groups: {len(named_rows)} ({named_elements} elems), "
          f"unnamed: {len(groups)-len(named_rows)} ({unnamed_elements} elems)")
    print("== exploded named groups (top 40 by elements) ==")
    for r in exploded_rows[:40]:
        print(f"  g{r['group_id']:<5} {r['elements']:>6}x{r['width']:<4} "
              f"{r['reject_reason'] or '-':<22} {r['loc_tail']}{r['field']}")
    print("== exploded array agg (top 40 by elements) ==")
    for a in out["exploded_array_agg"][:40]:
        print(f"  {a['elements']:>7} elems {a['groups']:>3} groups w{a['width']:<4} "
              f"{a['loc_tail']} fields={len(a['fields'])} reasons={a['reasons']}")
    if args.json:
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False) + "\n")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
