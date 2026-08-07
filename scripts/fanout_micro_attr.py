#!/usr/bin/env python3

"""XiangShan micro-attribution: why does the GRHSIM AM compute graph fan out
more than the gsim flattened graph? (supernode-align topic, NO0013 follow-up)

Inputs:
- AM side: build/xs/am-split-export/named.compute.jsonl (split export with
  names on ~440k nodes), def_use (src,dst)-deduped out-degree as in the B
  section of compute_partition_metrics.py.
- gsim side: topo-partition-proj/exp/dataset/xs_gsim_flat_prod_20260804/
  instruction_graph.jsonl (names on every node), state_write nodes excluded
  (compute-equivalent 口径, same as the 599,947 vs 252,832 baseline).

Sections written to build/xs/am-split-export/fanout_attr.json:
- task1_opcode: per-opcode producer counts by out-degree bucket
  (1/2/3/4-7/8-15/16+) and summed out-degree, both sides, with per-op excess
  (AM minus gsim) ranked by outdeg>=2 node-count difference.
- task2_hubs: top-50 producers per side (id/opcode/width/name/outdeg/module),
  and per-module summed out-degree (named nodes only).
- task3_patterns: pattern-class split of the outdeg>=2 excess (lowering
  slice/concat family, 1-bit control broadcast od>=16, reconvergence od 2-3,
  rest), the and vs logic_and special check, and the mem.read broadcast
  profile with consumer-op histograms for representative producers.
- task4_samename: 20 same-name node comparisons (AM outdeg>=3 named signals
  matched against gsim names normalized by __DOT__ -> $).

Run with the repo venv: .venv/bin/python.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "topo-partition-proj" / "exp"))
sys.path.insert(0, str(REPO / "scripts"))

from harness.graph import load_graph  # noqa: E402
from compute_partition_metrics import load_split_graph  # noqa: E402

AM_GRAPH = REPO / "build" / "xs" / "am-split-export" / "named.compute.jsonl"
GSIM_GRAPH = (
    REPO / "topo-partition-proj" / "exp" / "dataset"
    / "xs_gsim_flat_prod_20260804" / "instruction_graph.jsonl"
)
GSIM_NAMES_CACHE = REPO / "build" / "xs" / "am-split-export" / "gsim_names.npz"
OUT_JSON = REPO / "build" / "xs" / "am-split-export" / "fanout_attr.json"

BUCKETS = ["1", "2", "3", "4-7", "8-15", "16+"]

# gsim op -> canonical name (AM-style); AM ops are already canonical.
GSIM_OP_MAP = {
    "OP_MUX": "mux", "OP_ADD": "add", "OP_SUB": "sub", "OP_MUL": "mul",
    "OP_DIV": "div", "OP_LT": "lt", "OP_LEQ": "le", "OP_GT": "gt",
    "OP_GEQ": "ge", "OP_EQ": "eq", "OP_NEQ": "ne", "OP_DSHL": "shl_dyn",
    "OP_DSHR": "shr_dyn", "OP_AND": "and", "OP_OR": "or", "OP_XOR": "xor",
    "OP_CAT": "concat", "OP_ASUINT": "asuint", "OP_ASSINT": "assint",
    "OP_CVT": "cvt", "OP_NOT": "not", "OP_ANDR": "reduce_and",
    "OP_ORR": "reduce_or", "OP_XORR": "reduce_xor", "OP_PAD": "pad",
    "OP_SHL": "shl", "OP_SHR": "shr", "OP_HEAD": "slice", "OP_BITS": "slice",
    "OP_BITS_NOSHIFT": "slice", "OP_WHEN": "when", "OP_ASSERT": "assert",
    "OP_EXIT": "exit", "OP_GROUP": "group", "OP_READ_MEM": "mem.read",
    "OP_WRITE_MEM": "mem.write", "OP_SEXT": "sext", "OP_EXT_FUNC": "ext.func",
    "REF": "ref", "CONST_INT": "const", "INPUT": "input",
    "REG_UPDATE": "reg_update", "NONE": "none",
}

# module classification: first rule whose keyword appears in any $-segment
UNIT_RULES = [
    ("BPU", ("bpu",)), ("IFU", ("ifu",)), ("FTQ", ("ftq",)),
    ("ICache", ("icache", "instrUncache", "IPrefetch", "iprefetch")),
    ("Frontend", ("frontend",)),
    ("Ctrl", ("ctrlBlock", "ctrl")),
    ("ROB", ("rob",)),
    ("Rename/Dispatch", ("rename", "dispatch", "decode")),
    ("EXU", ("exu", "alu", "fpu", "mul", "div")),
    ("Backend", ("backend",)),
    ("LSU/Mem", ("memBlock", "lsu", "lsq", "loadQueue", "storeQueue",
                 "sbuffer", "dcache", "mmu", "l1d")),
    ("L2", ("l2top", "l2cache")),
    ("Difftest", ("endpoint", "difftest", "logEndpoint")),
    ("Periph", ("plic", "clint", "timer", "debugModule", "uart")),
    ("SoC", ("xbar", "socMisc", "axi4", "l_soc")),
]

# lowering side-effect op families (task 3c)
LOWERING_AM = {"slice_static", "slice_dynamic", "concat", "replicate"}
LOWERING_GSIM = {"slice", "concat", "pad", "sext"}


def module_of(name: str) -> str:
    if not name:
        return "(unnamed)"
    segments = name.split("$")
    for label, keywords in UNIT_RULES:
        for seg in segments:
            for kw in keywords:
                if kw in seg:
                    return label
    return "(other)"


def load_gsim_names() -> list[str]:
    if GSIM_NAMES_CACHE.exists() and GSIM_NAMES_CACHE.stat().st_mtime >= GSIM_GRAPH.stat().st_mtime:
        with np.load(GSIM_NAMES_CACHE, allow_pickle=False) as data:
            return json.loads(str(data["names"][0]))
    pat = re.compile(r'"name":"([^"]*)"')
    names: list[str] = []
    with open(GSIM_GRAPH) as stream:
        for line in stream:
            if '"gsim_type"' in line:
                names.append(pat.search(line).group(1))
    GSIM_NAMES_CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.savez(GSIM_NAMES_CACHE, names=np.array([json.dumps(names, ensure_ascii=False)]))
    return names


def dedup_edges(du_src: np.ndarray, du_dst: np.ndarray, keep_node: np.ndarray):
    """(src,dst)-deduped def_use edges with both endpoints kept."""
    keep = keep_node[du_src.astype(np.int64)] & keep_node[du_dst.astype(np.int64)]
    key = np.unique((du_src[keep].astype(np.int64) << 32) | du_dst[keep].astype(np.int64))
    return (key >> 32).astype(np.int64), (key & 0xFFFFFFFF).astype(np.int64)


def bucket_of(outdeg: np.ndarray) -> np.ndarray:
    b = np.zeros(outdeg.size, dtype=np.int8)  # 0: outdeg 0
    b[outdeg == 1] = 1
    b[outdeg == 2] = 2
    b[outdeg == 3] = 3
    b[(outdeg >= 4) & (outdeg <= 7)] = 4
    b[(outdeg >= 8) & (outdeg <= 15)] = 5
    b[outdeg >= 16] = 6
    return b


def op_stats(outdeg: np.ndarray, op: np.ndarray, canon_table: list[str],
             keep_node: np.ndarray) -> dict:
    """Per canonical op: bucket counts (1..16+), sum_outdeg, ge2 count."""
    buckets = bucket_of(outdeg)
    kept_ops = op[keep_node]
    kept_bk = buckets[keep_node]
    kept_od = outdeg[keep_node]
    stats: dict[str, dict] = {}
    for op_id in np.unique(kept_ops).tolist():
        sel = kept_ops == op_id
        bk = kept_bk[sel]
        row = {b: int((bk == i + 1).sum()) for i, b in enumerate(BUCKETS)}
        row["sum_outdeg"] = int(kept_od[sel].sum())
        row["ge2"] = int((bk >= 2).sum())
        stats[canon_table[op_id]] = row
    return stats


def op_nodes(op_arr: np.ndarray, canon_table: list[str], target: str) -> np.ndarray:
    ids = [i for i, nm in enumerate(canon_table) if nm == target]
    return np.nonzero(np.isin(op_arr, ids))[0]


def consumer_csr(us: np.ndarray, ud: np.ndarray, n: int):
    offsets = np.searchsorted(us, np.arange(n + 1, dtype=np.int64))
    return offsets, ud


def consumer_op_hist(node: int, offsets, ud, op_names_list, limit=6) -> str:
    cs = ud[offsets[node]:offsets[node + 1]]
    hist = Counter(op_names_list[c] for c in cs.tolist())
    total = max(len(cs), 1)
    return " ".join(f"{k}={v}({100.0 * v / total:.0f}%)" for k, v in hist.most_common(limit))


def main() -> int:
    am = load_split_graph(AM_GRAPH)
    am_names = am["names"] or [""] * int(am["global_id"].size)
    n_am = int(am["global_id"].size)
    gsim = load_graph(GSIM_GRAPH, use_cache=True, verbose=True)
    gsim_names = load_gsim_names()
    gsim_keep = ~gsim.state_write

    # canonical op names per node
    am_op_names = am["opcode_names"]
    am_canon = am_op_names  # already canonical
    gsim_canon_table = [GSIM_OP_MAP.get(nm, nm.lower()) for nm in gsim.opcode_names]
    # per-node canonical op names (for consumer histograms)
    am_node_op = [am_canon[o] for o in am["op"].tolist()]
    gs_node_op = [gsim_canon_table[o] for o in gsim.op.tolist()]

    am_us, am_ud = dedup_edges(am["du_src"], am["du_dst"], np.ones(n_am, dtype=bool))
    gs_us, gs_ud = dedup_edges(gsim.du_src, gsim.du_dst, gsim_keep)
    am_outdeg = np.bincount(am_us, minlength=n_am)
    gs_outdeg = np.bincount(gs_us, minlength=gsim.instructions)
    am_off, am_cons = consumer_csr(am_us, am_ud, n_am)
    gs_off, gs_cons = consumer_csr(gs_us, gs_ud, gsim.instructions)

    # ---- task 1: opcode-level decomposition --------------------------------
    am_stats = op_stats(am_outdeg, am["op"], am_canon, np.ones(n_am, dtype=bool))
    gs_stats = op_stats(gs_outdeg, gsim.op, gsim_canon_table, gsim_keep)
    all_ops = sorted(set(am_stats) | set(gs_stats))
    task1 = []
    for name in all_ops:
        a = am_stats.get(name, {})
        g = gs_stats.get(name, {})
        task1.append({
            "op": name,
            "am": a or None, "gsim": g or None,
            "ge2_excess": a.get("ge2", 0) - g.get("ge2", 0),
            "sum_outdeg_excess": a.get("sum_outdeg", 0) - g.get("sum_outdeg", 0),
        })
    task1.sort(key=lambda r: -r["ge2_excess"])
    print("== task1 opcode excess (by ge2 node count) ==")
    for row in task1[:15]:
        print(f"  {row['op']:16s} ge2 excess={row['ge2_excess']:+8d} "
              f"sumod excess={row['sum_outdeg_excess']:+9d} "
              f"am={row['am'] and row['am']['ge2']} gsim={row['gsim'] and row['gsim']['ge2']}")

    # ---- task 2: top-50 hubs + module attribution --------------------------
    def top50(outdeg, names, op_arr, canon_table):
        idx = np.argsort(-outdeg)[:50]
        rows = []
        for i in idx.tolist():
            rows.append({
                "id": int(i), "op": canon_table[op_arr[i]], "width": None,
                "name": names[i] or None, "outdeg": int(outdeg[i]),
                "module": module_of(names[i]),
            })
        return rows

    am_top = top50(am_outdeg, am_names, am["op"], am_canon)
    for row, i in zip(am_top, np.argsort(-am_outdeg)[:50].tolist()):
        row["width"] = int(am["width"][i])
        row["global_id"] = int(am["global_id"][i])
    gs_top = top50(gs_outdeg, gsim_names, gsim.op, gsim_canon_table)
    for row, i in zip(gs_top, np.argsort(-gs_outdeg)[:50].tolist()):
        row["width"] = int(gsim.width[i])
    # module attribution of named-node outdeg
    def module_table(outdeg, names):
        tab: dict[str, dict] = {}
        for i, nm in enumerate(names):
            if not nm:
                continue
            m = module_of(nm)
            row = tab.setdefault(m, {"nodes": 0, "sum_outdeg": 0, "ge2": 0})
            row["nodes"] += 1
            row["sum_outdeg"] += int(outdeg[i])
            row["ge2"] += int(outdeg[i] >= 2)
        return dict(sorted(tab.items(), key=lambda kv: -kv[1]["sum_outdeg"]))
    am_mod = module_table(am_outdeg, am_names)
    gs_mod = module_table(gs_outdeg, gsim_names)
    am_named_ge2 = sum(1 for i, nm in enumerate(am_names) if nm and am_outdeg[i] >= 2)
    print(f"== task2 modules (AM named ge2={am_named_ge2}, AM total ge2={int((am_outdeg >= 2).sum())}) ==")
    for m, row in list(am_mod.items())[:12]:
        print(f"  AM {m:16s} {row}")
    for m, row in list(gs_mod.items())[:12]:
        print(f"  GS {m:16s} {row}")

    # ---- task 3: pattern classes -------------------------------------------
    def pattern_split(outdeg, op_arr, canon_list, width_arr, lowering_ops):
        ge2 = outdeg >= 2
        canon_arr = np.array(canon_list, dtype=object)
        is_lower = ge2 & np.isin(canon_arr, list(lowering_ops))
        is_ctrl = ge2 & ~is_lower & (width_arr == 1) & (outdeg >= 16)
        is_reconv = ge2 & ~is_lower & ~is_ctrl & (outdeg <= 3)
        is_rest = ge2 & ~is_lower & ~is_ctrl & ~is_reconv
        out = {}
        for label, mask in (("lowering", is_lower), ("control_broadcast", is_ctrl),
                            ("reconvergence_2_3", is_reconv), ("rest", is_rest)):
            out[label] = {"nodes": int(mask.sum()), "sum_outdeg": int(outdeg[mask].sum())}
        out["total_ge2"] = {"nodes": int(ge2.sum()), "sum_outdeg": int(outdeg[ge2].sum())}
        return out

    am_pat = pattern_split(am_outdeg, am["op"], am_node_op, am["width"], LOWERING_AM)
    gs_pat = pattern_split(gs_outdeg, gsim.op, gs_node_op, gsim.width, LOWERING_GSIM)
    # and vs logic_and special check
    and_check = {
        "am_and": am_stats.get("and"), "am_logic_and": am_stats.get("logic_and"),
        "am_not": am_stats.get("not"), "am_logic_not": am_stats.get("logic_not"),
        "am_or": am_stats.get("or"), "am_logic_or": am_stats.get("logic_or"),
        "gsim_and": gs_stats.get("and"), "gsim_or": gs_stats.get("or"),
        "gsim_not": gs_stats.get("not"),
    }
    # mem.read broadcast profile + consumer ops
    am_memread = op_nodes(am["op"], am_canon, "mem.read")
    gs_memread = op_nodes(gsim.op, gsim_canon_table, "mem.read")
    memread_profile = {
        "am": {"nodes": int(am_memread.size),
               "buckets": {b: int((bucket_of(am_outdeg[am_memread]) == i + 1).sum())
                            for i, b in enumerate(BUCKETS)},
               "sum_outdeg": int(am_outdeg[am_memread].sum())},
        "gsim": {"nodes": int(gs_memread.size),
                 "buckets": {b: int((bucket_of(gs_outdeg[gs_memread]) == i + 1).sum())
                              for i, b in enumerate(BUCKETS)},
                 "sum_outdeg": int(gs_outdeg[gs_memread].sum())},
    }
    # representative high-fanout producers: top-2 named per focus op
    samples = []
    for target in ("and", "logic_and", "mem.read", "eq", "mux"):
        nodes = op_nodes(am["op"], am_canon, target)
        nodes = nodes[am_outdeg[nodes] >= 2]
        order = np.argsort(-am_outdeg[nodes])
        named_first = [i for i in order.tolist() if am_names[nodes[i]]] or order.tolist()
        for i in named_first[:2]:
            n = int(nodes[i])
            samples.append({
                "op": target, "global_id": int(am["global_id"][n]),
                "name": am_names[n] or None, "width": int(am["width"][n]),
                "outdeg": int(am_outdeg[n]), "module": module_of(am_names[n]),
                "consumer_ops": consumer_op_hist(n, am_off, am_cons, am_node_op),
            })
    print("== task3 patterns ==")
    print("  AM:", json.dumps(am_pat))
    print("  GS:", json.dumps(gs_pat))
    # event-detector side effect: how many outdeg-2 and/or-family producers have
    # a changed.pos/changed.neg consumer (AM execution model adds event taps)
    def event_tap_share(target):
        nodes = op_nodes(am["op"], am_canon, target)
        nodes = nodes[am_outdeg[nodes] == 2]
        tap = 0
        for n in nodes.tolist():
            cons = am_cons[am_off[n]:am_off[n + 1]]
            if any(am_canon[am["op"][c]] in ("changed.pos", "changed.neg") for c in cons.tolist()):
                tap += 1
        return {"outdeg2_nodes": int(nodes.size), "with_event_tap": tap}

    and_family_event_tap = {
        "and": event_tap_share("and"),
        "logic_and": event_tap_share("logic_and"),
        "or": event_tap_share("or"),
        "eq": event_tap_share("eq"),
    }
    # aggregate consumer-op histograms for the big excess cells
    def aggregate_consumer_hist(target, pred, limit=8):
        nodes = op_nodes(am["op"], am_canon, target)
        nodes = nodes[pred(am_outdeg[nodes])]
        hist: Counter = Counter()
        for n in nodes.tolist():
            cons = am_cons[am_off[n]:am_off[n + 1]]
            hist.update(am_node_op[c] for c in cons.tolist())
        total = max(sum(hist.values()), 1)
        return {"nodes": int(nodes.size),
                "consumers": {k: v for k, v in hist.most_common(limit)},
                "consumer_total": total}

    aggregate_consumers = {
        "logic_and@2": aggregate_consumer_hist("logic_and", lambda o: o == 2),
        "and@2": aggregate_consumer_hist("and", lambda o: o == 2),
        "and@4+": aggregate_consumer_hist("and", lambda o: o >= 4),
        "mux@2-3": aggregate_consumer_hist("mux", lambda o: (o >= 2) & (o <= 3)),
        "eq@2": aggregate_consumer_hist("eq", lambda o: o == 2),
        "mem.read@2": aggregate_consumer_hist("mem.read", lambda o: o == 2),
        "mem.read@4+": aggregate_consumer_hist("mem.read", lambda o: o >= 4),
        "assign@2+": aggregate_consumer_hist("assign", lambda o: o >= 2),
        "slice_static@2+": aggregate_consumer_hist("slice_static", lambda o: o >= 2),
    }
    print("  aggregate consumers:", json.dumps(aggregate_consumers))
    print("  event-tap check:", json.dumps(and_family_event_tap))
    print("  and-family:", json.dumps(and_check))
    print("  mem.read:", json.dumps(memread_profile))

    # ---- task 4: same-name comparison --------------------------------------
    # The two exports use different naming levels: AM keeps cleaned RTL signal
    # names (rob$canEnqueue_3), gsim keeps raw Chisel temporaries with extra
    # hierarchy levels (rob__DOT___canEnqueue_T_12). Match on a basename key:
    # last path segment, leading underscores stripped, trailing _N / _T / _T_N
    # suffixes stripped; require the key to be unique on BOTH sides.
    def base_key(name: str) -> str:
        seg = name.replace("__DOT__", "$").split("$")[-1]
        seg = seg.lstrip("_")
        while True:
            new = re.sub(r"_T(_\d+)?$", "", seg)
            new = re.sub(r"_\d+$", "", new)
            if new == seg:
                return seg
            seg = new

    def unique_index(names_list):
        first: dict[str, int] = {}
        count: Counter = Counter()
        for i, nm in enumerate(names_list):
            if not nm:
                continue
            k = base_key(nm)
            count[k] += 1
            first.setdefault(k, i)
        return {k: i for k, i in first.items() if count[k] == 1}

    gsim_index = unique_index(gsim_names)
    am_index = unique_index(am_names)
    named_ge3 = [i for i in range(n_am) if am_names[i] and am_outdeg[i] >= 3]
    named_ge3.sort(key=lambda i: -am_outdeg[i])
    # only nodes whose basename key is unique on BOTH sides are matchable
    matchable = [i for i in named_ge3
                 if base_key(am_names[i]) in gsim_index and base_key(am_names[i]) in am_index]
    mid = [i for i in matchable if 3 <= am_outdeg[i] <= 15]
    stride = max(len(mid) // 10, 1)
    sample = matchable[:10] + mid[::stride][:10]
    task4_meta = {"named_ge3_total": len(named_ge3), "matchable": len(matchable),
                  "match_rule": ("basename of path; strip leading '_' and trailing "
                                 "_N/_T/_T_N suffixes; key must be unique on both sides")}
    task4 = []
    verdicts = Counter()
    for i in sample:
        nm = am_names[i]
        gi = gsim_index[base_key(nm)]  # sample is drawn from the matchable pool
        am_cons_hist = consumer_op_hist(i, am_off, am_cons, am_node_op)
        row = {"name": nm, "am": {"global_id": int(am["global_id"][i]),
                                  "op": am_canon[am["op"][i]], "width": int(am["width"][i]),
                                  "outdeg": int(am_outdeg[i]), "consumer_ops": am_cons_hist}}
        row["gsim_name"] = gsim_names[gi]
        gs_hist = consumer_op_hist(gi, gs_off, gs_cons, gs_node_op)
        row["gsim"] = {"id": int(gi), "op": gs_node_op[gi],
                       "width": int(gsim.width[gi]), "outdeg": int(gs_outdeg[gi]),
                       "consumer_ops": gs_hist}
        r = am_outdeg[i] / max(gs_outdeg[gi], 1)
        row["verdict"] = ("am_looser" if r >= 1.5 else
                          "gsim_looser" if r <= 1 / 1.5 else "equivalent")
        verdicts[row["verdict"]] += 1
        task4.append(row)
    print("== task4 same-name verdicts ==", dict(verdicts),
          f"(matchable {task4_meta['matchable']}/{task4_meta['named_ge3_total']})")

    report = {
        "inputs": {"am_graph": str(AM_GRAPH), "gsim_graph": str(GSIM_GRAPH)},
        "caliber": ("def_use (src,dst)-deduped out-degree; gsim side excludes "
                    "state_write nodes; gsim names normalized __DOT__->$; gsim ops "
                    "mapped to AM-canonical names (OP_AND->and etc.)"),
        "task1_opcode": task1,
        "task2_hubs": {"am_top50": am_top, "gsim_top50": gs_top,
                        "am_modules": am_mod, "gsim_modules": gs_mod,
                        "am_named_ge2_nodes": am_named_ge2,
                        "am_total_ge2_nodes": int((am_outdeg >= 2).sum()),
                        "gsim_total_ge2_nodes": int((gs_outdeg >= 2).sum())},
        "task3_patterns": {"am": am_pat, "gsim": gs_pat,
                            "and_logic_and_check": and_check,
                            "event_tap_check": and_family_event_tap,
                            "aggregate_consumer_ops": aggregate_consumers,
                            "memread_profile": memread_profile,
                            "samples": samples},
        "task4_samename": {"meta": task4_meta, "verdicts": dict(verdicts), "rows": task4},
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[report] wrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
