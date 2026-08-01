#!/usr/bin/env python3

"""T3 module-level attribution (docs/18 §4 T3, run on the T2-E1 datasets):
per-module op-bucket statistics for the AM (GRH post-stats JSON) and gsim
(flatten instruction_graph.jsonl) sides, joined into a module x bucket diff
table (top-20 Δlogic 模块表).

- AM side: stream the pretty-printed GRH JSON; each op line carries
  `"kind"` (bucket) and `"loc".file` (one .sv file per module => module
  type; ~95.6% coverage, the rest lands in `(no_loc)`). Note: intermediate
  values are anonymous `_val_N`, so sym-based region attribution does NOT
  work on this side — the module axis is the attribution.
- gsim side: stream the flatten JSONL node records (`opcode`, `name` with
  `__DOT__` instance path); the leaf module type is resolved by walking the
  SimTop.fir `inst x of Module` declarations (region axis also available
  here, one-sided).
- The fir parse also yields each module's instance path(s), used to
  annotate the top-20 table with region context.

Bucket names follow docs/18 §2 (logic/wire/state/mem/mux/concat/slice/cmp/
special/arith/cast/shift/const/other).

Usage:

    module_attr_compare.py --grh-json <post_stats.json> \
        --gsim-jsonl <instruction_graph.jsonl> --fir <SimTop.fir> \
        --out <module_attr.json> [--region-depth 6]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict, deque
from pathlib import Path

# ---------------------------------------------------------------------------
# Bucket mappings (docs/18 §2 names; GRH kinds from scripts/compare_ir_shapes.py)
# ---------------------------------------------------------------------------

GRH_KIND_BUCKET = {
    "kConstant": "const",
    "kAdd": "arith", "kSub": "arith", "kMul": "arith", "kDiv": "arith", "kMod": "arith",
    "kEq": "cmp", "kNe": "cmp", "kCaseEq": "cmp", "kCaseNe": "cmp",
    "kWildcardEq": "cmp", "kWildcardNe": "cmp",
    "kLt": "cmp", "kLe": "cmp", "kGt": "cmp", "kGe": "cmp",
    "kAnd": "logic", "kOr": "logic", "kXor": "logic", "kXnor": "logic", "kNot": "logic",
    "kLogicAnd": "logic", "kLogicOr": "logic", "kLogicNot": "logic",
    "kReduceAnd": "logic", "kReduceOr": "logic", "kReduceXor": "logic",
    "kReduceNor": "logic", "kReduceNand": "logic", "kReduceXnor": "logic",
    "kShl": "shift", "kLShr": "shift", "kAShr": "shift",
    "kMux": "mux",
    "kAssign": "wire",
    "kConcat": "concat", "kReplicate": "concat",
    "kSliceStatic": "slice", "kSliceDynamic": "slice", "kSliceArray": "slice",
    "kLatch": "state", "kRegister": "state", "kMemory": "state",
    "kLatchReadPort": "state", "kLatchWritePort": "state",
    "kRegisterReadPort": "state", "kRegisterWritePort": "state",
    "kMemoryReadPort": "state", "kMemoryWritePort": "state",
    "kInstance": "special", "kBlackbox": "special",
    "kSystemFunction": "special", "kSystemTask": "special",
    "kDpicImport": "special", "kDpicCall": "special",
    "kXMRRead": "special", "kXMRWrite": "special",
}

GSIM_OP_BUCKET = {
    "OP_MUX": "mux", "OP_WHEN": "mux",
    "OP_ADD": "arith", "OP_SUB": "arith", "OP_MUL": "arith", "OP_DIV": "arith",
    "OP_REM": "arith", "OP_NEG": "arith",
    "OP_CVT": "cast", "OP_ASUINT": "cast", "OP_ASSINT": "cast",
    "OP_ASCLOCK": "cast", "OP_ASASYNCRESET": "cast", "OP_PAD": "cast", "OP_SEXT": "cast",
    "OP_LT": "cmp", "OP_LEQ": "cmp", "OP_GT": "cmp", "OP_GEQ": "cmp",
    "OP_EQ": "cmp", "OP_NEQ": "cmp",
    "OP_AND": "logic", "OP_OR": "logic", "OP_XOR": "logic", "OP_NOT": "logic",
    "OP_ANDR": "logic", "OP_ORR": "logic", "OP_XORR": "logic", "OP_XNOR": "logic",
    "OP_DSHL": "shift", "OP_DSHR": "shift", "OP_SHL": "shift", "OP_SHR": "shift",
    "OP_HEAD": "slice", "OP_TAIL": "slice", "OP_BITS": "slice",
    "OP_BITS_NOSHIFT": "slice", "OP_INDEX_INT": "slice", "OP_INDEX": "slice",
    "OP_CAT": "concat", "OP_GROUP": "concat",
    "OP_READ_MEM": "mem", "OP_WRITE_MEM": "mem", "OP_INFER_MEM": "mem",
    "OP_PRINTF": "special", "OP_ASSERT": "special", "OP_EXIT": "special",
    "OP_EXT_FUNC": "special", "OP_INVALID": "special", "OP_RESET": "special",
    "OP_STMT_SEQ": "other", "OP_STMT_WHEN": "other", "OP_STMT_NODE": "other",
    "OP_INT": "const", "CONST_INT": "const",
    "REF": "wire", "NONE": "wire", "INPUT": "wire",
    "REG_UPDATE": "state",
}

BUCKETS = ("logic", "mux", "concat", "slice", "cmp", "arith", "shift", "cast",
           "wire", "state", "mem", "special", "const", "other")

# ---------------------------------------------------------------------------
# Phase A: SimTop.fir instance -> module map + module instance paths
# ---------------------------------------------------------------------------

MODULE_RE = re.compile(r"^\s*(?:public\s+)?(?:module|extmodule)\s+(\w+)")
INST_RE = re.compile(r"^\s*inst\s+(\w+)\s+of\s+(\w+)")


def parse_fir(path: Path):
    inst_of: dict[tuple[str, str], str] = {}
    inst_by_parent: dict[str, list[tuple[str, str]]] = defaultdict(list)
    current = ""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if "inst " in line:
                match = INST_RE.match(line)
                if match:
                    inst_of[(current, match.group(1))] = match.group(2)
                    inst_by_parent[current].append((match.group(1), match.group(2)))
                    continue
            if "module" in line:
                match = MODULE_RE.match(line)
                if match:
                    current = match.group(1)
    return inst_of, inst_by_parent


def build_module_paths(inst_by_parent: dict[str, list[tuple[str, str]]],
                       top: str = "SimTop", per_module_cap: int = 64):
    """BFS the instance tree; module -> list of instance paths (capped)."""
    paths: dict[str, list[tuple[str, ...]]] = {top: [()]}
    truncated: dict[str, int] = {}
    queue = deque([top])
    while queue:
        module = queue.popleft()
        for inst_name, child in inst_by_parent.get(module, ()):  # (inst, child module)
            base = paths.get(module)
            if base is None:
                continue
            bucket = paths.setdefault(child, [])
            room = per_module_cap - len(bucket)
            if room <= 0:
                truncated[child] = truncated.get(child, 0) + 1
                continue
            for prefix in base[:room]:
                bucket.append(prefix + (inst_name,))
            queue.append(child)
    return paths, truncated


def normalize_gsim_segments(raw_segments: list[str]) -> list[str]:
    """gsim keeps real `inner` instances; drop them for region keys (the
    wolvrix side inlines them as `inner_x`)."""
    return [seg for seg in raw_segments if seg != "inner"]


def region_key(segments, depth: int) -> str:
    segments = list(segments)
    if not segments:
        return "(top)"
    return "/".join(segments[:depth])


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def new_bucket_counter() -> dict[str, int]:
    return {bucket: 0 for bucket in BUCKETS}


def bump(table: dict[str, dict[str, int]], key: str, bucket: str, width: int) -> None:
    slot = table.get(key)
    if slot is None:
        slot = new_bucket_counter()
        slot["width"] = 0
        table[key] = slot
    slot[bucket] += 1
    slot["width"] += width


# ---------------------------------------------------------------------------
# Phase B: gsim flatten JSONL
# ---------------------------------------------------------------------------

def scan_gsim(path: Path, inst_of: dict[tuple[str, str], str], region_depth: int):
    modules: dict[str, dict[str, int]] = {}
    regions: dict[str, dict[str, int]] = {}
    opcodes: dict[str, dict[str, int]] = {}
    totals = new_bucket_counter()
    totals["width"] = 0
    nodes = 0
    resolve_full = 0
    resolve_partial = 0
    partial_modules: dict[str, int] = defaultdict(int)

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if '"record":"node"' not in line:
                continue
            rec = json.loads(line)
            nodes += 1
            opcode = str(rec["opcode"])
            bucket = GSIM_OP_BUCKET.get(opcode, "other")
            width = int(rec.get("width", 0))
            name = str(rec.get("name", ""))
            raw_segments = [seg for seg in name.split("__DOT__") if seg]
            instance_path = raw_segments[:-1]  # drop signal/temp segment
            module = "SimTop"
            resolved = True
            for segment in instance_path:
                nxt = inst_of.get((module, segment))
                if nxt is None:
                    resolved = False
                    break
                module = nxt
            if resolved:
                resolve_full += 1
            else:
                resolve_partial += 1
                partial_modules[module] += 1
            bump(modules, module, bucket, width)
            bump(regions, region_key(normalize_gsim_segments(instance_path), region_depth),
                 bucket, width)
            slot = opcodes.setdefault(module, {})
            slot[opcode] = slot.get(opcode, 0) + 1
            totals[bucket] += 1
            totals["width"] += width

    stats = {
        "nodes": nodes,
        "resolve_full": resolve_full,
        "resolve_partial": resolve_partial,
        "partial_top_modules": sorted(partial_modules.items(), key=lambda kv: -kv[1])[:20],
    }
    return modules, regions, totals, stats, opcodes


# ---------------------------------------------------------------------------
# Phase C: GRH post-stats JSON (pretty printed; one op per line)
# ---------------------------------------------------------------------------

KIND_RE = re.compile(r'"kind": "(\w+)"')
FILE_RE = re.compile(r'"file": "([^"]+)"')
WIDTH_RE = re.compile(r'"width": \{"t": "int", "v": (\d+)\}')


def scan_grh(path: Path):
    modules: dict[str, dict[str, int]] = {}
    opcodes: dict[str, dict[str, int]] = {}
    totals = new_bucket_counter()
    totals["width"] = 0
    ops = 0
    with_loc = 0

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if '"kind": "' not in line:
                continue
            ops += 1
            kind_match = KIND_RE.search(line)
            kind = kind_match.group(1) if kind_match else ""
            bucket = GRH_KIND_BUCKET.get(kind, "other")
            width = 0
            width_match = WIDTH_RE.search(line)
            if width_match:
                width = int(width_match.group(1))
            file_match = FILE_RE.search(line)
            if file_match:
                with_loc += 1
                module = Path(file_match.group(1)).stem
            else:
                module = "(no_loc)"
            bump(modules, module, bucket, width)
            slot = opcodes.setdefault(module, {})
            slot[kind] = slot.get(kind, 0) + 1
            totals[bucket] += 1
            totals["width"] += width

    stats = {"ops": ops, "with_loc": with_loc}
    return modules, totals, stats, opcodes


# ---------------------------------------------------------------------------
# Phase D: join + report
# ---------------------------------------------------------------------------


def merge_join(am: dict[str, dict[str, int]], gs: dict[str, dict[str, int]]):
    rows = []
    for key in sorted(set(am) | set(gs)):
        a = am.get(key, {})
        b = gs.get(key, {})
        row = {"name": key}
        for bucket in BUCKETS:
            row[f"am_{bucket}"] = a.get(bucket, 0)
            row[f"gs_{bucket}"] = b.get(bucket, 0)
        row["am_total"] = sum(a.get(bucket, 0) for bucket in BUCKETS)
        row["gs_total"] = sum(b.get(bucket, 0) for bucket in BUCKETS)
        row["delta_logic"] = row["am_logic"] - row["gs_logic"]
        row["delta_total"] = row["am_total"] - row["gs_total"]
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grh-json", type=Path, required=True)
    parser.add_argument("--gsim-jsonl", type=Path, required=True)
    parser.add_argument("--fir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--region-depth", type=int, default=6)
    args = parser.parse_args()

    started = time.time()
    print(f"[A] parse fir {args.fir} ...", flush=True)
    inst_of, inst_by_parent = parse_fir(args.fir)
    module_paths, paths_truncated = build_module_paths(inst_by_parent)
    print(f"[A] inst map entries={len(inst_of)} modules={len(module_paths)} "
          f"({time.time()-started:.0f}s)", flush=True)

    print(f"[B] scan gsim {args.gsim_jsonl} ...", flush=True)
    gs_modules, gs_regions, gs_totals, gs_stats, gs_opcodes = scan_gsim(
        args.gsim_jsonl, inst_of, args.region_depth)
    print(f"[B] nodes={gs_stats['nodes']} resolved={gs_stats['resolve_full']} "
          f"partial={gs_stats['resolve_partial']} ({time.time()-started:.0f}s)", flush=True)

    print(f"[C] scan grh {args.grh_json} ...", flush=True)
    am_modules, am_totals, am_stats, am_opcodes = scan_grh(args.grh_json)
    print(f"[C] ops={am_stats['ops']} with_loc={am_stats['with_loc']} "
          f"({time.time()-started:.0f}s)", flush=True)

    module_rows = merge_join(am_modules, gs_modules)
    module_rows.sort(key=lambda r: -abs(r["delta_logic"]))
    region_rows = []
    for key, counts in gs_regions.items():
        row = {"name": key}
        for bucket in BUCKETS:
            row[f"gs_{bucket}"] = counts.get(bucket, 0)
        row["gs_total"] = sum(counts.get(bucket, 0) for bucket in BUCKETS)
        region_rows.append(row)
    region_rows.sort(key=lambda r: -r["gs_logic"])

    def paths_for(module: str) -> dict:
        plist = module_paths.get(module, [])
        rendered = ["/".join(normalize_gsim_segments(p)) or "(top)" for p in plist[:3]]
        return {"count": len(plist) + paths_truncated.get(module, 0),
                "examples": rendered}

    def paths_for(module: str) -> dict:
        plist = module_paths.get(module, [])
        rendered = ["/".join(normalize_gsim_segments(p)) or "(top)" for p in plist[:3]]
        return {"count": len(plist) + paths_truncated.get(module, 0),
                "examples": rendered}

    def canon_op(name: str) -> str:
        if name.startswith("OP_"):
            return name[3:].lower()
        if name.startswith("k") and len(name) > 1 and name[1].isupper():
            return re.sub(r"(?<!^)(?=[A-Z])", "_", name[1:]).lower()
        return name.lower()

    top_annotated = []
    for row in module_rows[:60]:
        annotated = dict(row)
        annotated["instance_paths"] = paths_for(row["name"])
        am_ops = am_opcodes.get(row["name"], {})
        gs_ops = gs_opcodes.get(row["name"], {})
        canon: dict[str, list[int]] = {}
        for op, count in am_ops.items():
            slot = canon.setdefault(canon_op(op), [0, 0])
            slot[0] += count
        for op, count in gs_ops.items():
            slot = canon.setdefault(canon_op(op), [0, 0])
            slot[1] += count
        opcode_delta = sorted(
            ({"op": op, "am": pair[0], "gs": pair[1], "delta": pair[0] - pair[1]}
             for op, pair in canon.items()),
            key=lambda r: -abs(r["delta"]),
        )[:12]
        annotated["opcode_delta"] = opcode_delta
        top_annotated.append(annotated)

    report = {
        "inputs": {
            "grh_json": str(args.grh_json),
            "gsim_jsonl": str(args.gsim_jsonl),
            "fir": str(args.fir),
            "region_depth": args.region_depth,
        },
        "am": {"stats": am_stats, "totals": am_totals},
        "gsim": {"stats": gs_stats, "totals": gs_totals},
        "modules_top_delta_logic": top_annotated,
        "gsim_regions_top_logic": region_rows[:60],
        "elapsed_seconds": round(time.time() - started, 1),
    }
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"[D] wrote {args.out}", flush=True)

    print("\n== AM totals ==")
    print({k: v for k, v in am_totals.items() if v})
    print("== gsim totals ==")
    print({k: v for k, v in gs_totals.items() if v})
    print("\n== top-20 modules by |Δlogic| ==")
    print(f"{'module':36s} {'am_logic':>9s} {'gs_logic':>9s} {'Δlogic':>9s} "
          f"{'am_tot':>9s} {'gs_tot':>9s}  instance paths")
    for row in top_annotated[:20]:
        paths = row["instance_paths"]
        hint = f"x{paths['count']}: {paths['examples'][0]}" if paths["examples"] else "-"
        print(f"{row['name'][:36]:36s} {row['am_logic']:>9,} {row['gs_logic']:>9,} "
              f"{row['delta_logic']:>+9,} {row['am_total']:>9,} {row['gs_total']:>9,}  "
              f"{hint[:70]}")
    print("\n== top-20 gsim regions by logic (one-sided) ==")
    for row in region_rows[:20]:
        print(f"{row['name'][:64]:64s} {row['gs_logic']:>9,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
