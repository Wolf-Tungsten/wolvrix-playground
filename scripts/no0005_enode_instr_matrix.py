#!/usr/bin/env python3
"""NO0005: build the full gsim-enode-type x AM-instr-type mapping matrix.

Inputs:
  1. gsim flatten-graph enode census (row totals):
     build/logs/no0003/gsim_topo_flat_v2_out/SimTop_supernode_stats.json
  2. Instrumented export attribution (measured enode -> exec-GRH op counts):
     build/logs/no0005/gsim_flat_export/SimTop.exec.json.enode_matrix.json
  3. AM pre-opt import QC opcode mix (column totals):
     build/logs/no0004_am_import_qc.log

Row closure:  census(row) == visits-coverage check; attributed ops per row are
reported per AM column with an explicit zero-op remainder (enodes that lowered
to no operation: passthrough REFs, dedup'd constants, ...).
Column closure: sum over enode rows + AM-only rows (coerce/result_bridge/
pre_commit assigns, changed.*) == AM pre-opt census per opcode.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CENSUS = ROOT / "build/logs/no0003/gsim_topo_flat_v2_out/SimTop_supernode_stats.json"
MATRIX = ROOT / "build/logs/no0005/gsim_flat_export/SimTop.exec.json.enode_matrix.json"
AM_QC = ROOT / "build/logs/no0004_am_import_qc.log"

# exec-GRH kind -> AM opcode (None = does not materialize as an AM instruction)
KIND_TO_AM = {
    "kAssign": "assign",
    "kAdd": "add",
    "kSub": "sub",
    "kMul": "mul",
    "kDiv": "div",
    "kAnd": "and",
    "kOr": "or",
    "kXor": "xor",
    "kNot": "not",
    "kEq": "eq",
    "kNe": "ne",
    "kLt": "lt",
    "kLe": "le",
    "kGt": "gt",
    "kGe": "ge",
    "kShl": "shl",
    "kLShr": "lshr",
    "kAShr": "ashr",
    "kMux": "mux",
    "kConcat": "concat",
    "kSliceStatic": "slice_static",
    "kSliceDynamic": "slice_dynamic",
    "kReduceAnd": "reduce_and",
    "kReduceOr": "reduce_or",
    "kReduceXor": "reduce_xor",
    "kMemoryReadPort": "mem.read",
    "kMemoryWritePort": "mem.write.c+cm",
    "kRegisterWritePort": "reg.write+m",
    "kSystemTask": "system.task",
    "kDpicCall": "dpi.call",
    "kConstant": None,          # constant variables, not instructions
    "kRegister": None,          # state declaration
    "kMemory": None,            # state declaration
    "kRegisterReadPort": None,  # variable reference in AM (operand)
    "kDpicImport": None,        # import declaration
}

# AM opcodes present pre-opt that have no exec-GRH/enode source (AM lowering adds)
AM_ONLY = {
    "changed.pos": None,  # clock edge detectors (fill from AM census)
    "changed.neg": None,
}


def load_am_mix():
    text = AM_QC.read_text()
    m = re.search(r"opcode_mix\[([^\]]+)\]", text)
    if not m:
        raise SystemExit("opcode_mix not found in AM QC log")
    mix = {}
    for tok in m.group(1).split():
        k, v = tok.split("=")
        mix[k] = int(v)
    m2 = re.search(r"assign sites: from_grh=(\d+) pre_commit=(\d+) coerce=(\d+) result_bridge=(\d+)", text)
    sites = {k: int(v) for k, v in zip(("from_grh", "pre_commit", "coerce", "result_bridge"), m2.groups())}
    return mix, sites


def main():
    census = json.loads(CENSUS.read_text())
    matrix = json.loads(MATRIX.read_text())
    am_mix, assign_sites = load_am_mix()

    # merge variant-split opcodes for closure against the exec-level attribution
    am_merged = dict(am_mix)
    am_merged["mem.write.c+cm"] = am_mix.get("mem.write.c", 0) + am_mix.get("mem.write.cm", 0)
    for k in ("mem.write.c", "mem.write.cm"):
        am_merged.pop(k, None)
    am_merged["reg.write+m"] = am_mix.get("reg.write", 0) + am_mix.get("reg.write.m", 0)
    for k in ("reg.write", "reg.write.m"):
        am_merged.pop(k, None)

    rows = {"REF": census["enode_node_ref_count"]}
    rows.update(census["enode_op_types"])
    ops_attr = matrix["ops"]          # enode key -> exec kind -> count
    visits = matrix["visits"]         # enode key -> lowered-enode visits

    # ---- per-row, per-column counts -------------------------------------
    # columns: AM opcodes (ordered by merged AM census size) + pseudo columns
    am_cols = [c for c, _ in sorted(am_merged.items(), key=lambda kv: -kv[1])]
    pseudo_cols = ["const.var", "state.decl", "operand.ref"]
    nonenode = ops_attr.get("<non-enode>", {})

    def kind_to_col(kind):
        if kind not in KIND_TO_AM:
            raise SystemExit(f"unmapped exec kind: {kind}")
        am = KIND_TO_AM[kind]
        if am == "mem.write.c+cm":
            return "mem.write.c+cm"
        if am == "reg.write+m":
            return "reg.write+m"
        if am is None:
            return {"kConstant": "const.var", "kRegister": "state.decl",
                    "kMemory": "state.decl", "kRegisterReadPort": "operand.ref",
                    "kDpicImport": "state.decl"}[kind]
        return am

    table = {}   # row -> col -> count
    for key, kinds in ops_attr.items():
        if key == "<non-enode>":
            continue
        for kind, n in kinds.items():
            col = kind_to_col(kind)
            table.setdefault(key, {})[col] = table.setdefault(key, {}).get(col, 0) + n

    # non-enode bucket -> named synthetic rows
    synth_rows = {}
    for kind, n in nonenode.items():
        col = kind_to_col(kind)
        bucket = synth_rows.setdefault("<non-enode>", {})
        bucket[col] = bucket.get(col, 0) + n

    # ---- column closure --------------------------------------------------
    col_sum = {c: 0 for c in am_cols}
    col_sum["mem.write.c+cm"] = 0
    col_sum["reg.write+m"] = 0
    for r in table.values():
        for c, n in r.items():
            if c in col_sum:
                col_sum[c] += n
    for c, n in synth_rows.get("<non-enode>", {}).items():
        if c in col_sum:
            col_sum[c] += n

    # AM-only additions
    am_only_rows = {
        "<am-lowering:coerce>": {"assign": assign_sites["coerce"]},
        "<am-lowering:result_bridge>": {"assign": assign_sites["result_bridge"]},
        "<am-lowering:pre_commit>": {"assign": assign_sites["pre_commit"]},
        "<am-lowering:changed>": {"changed.pos": am_mix.get("changed.pos", 0),
                                  "changed.neg": am_mix.get("changed.neg", 0)},
    }

    print("== column closure (enode rows + <non-enode> + AM-only vs AM census) ==")
    combined = dict(col_sum)
    for r in am_only_rows.values():
        for c, n in r.items():
            combined[c] = combined.get(c, 0) + n

    worst = []
    for c in sorted(set(list(combined) + list(am_merged))):
        got = combined.get(c, 0)
        want = am_merged.get(c, 0)
        resid = got - want
        flag = "" if resid == 0 else "  <-- RESIDUAL"
        print(f"  {c:16s} matrix={got:>10,}  am={want:>10,}  resid={resid:>+8,}{flag}")
        if resid:
            worst.append((c, resid))

    # ---- row closure / coverage ------------------------------------------
    print("\n== row coverage (census vs exporter visits) ==")
    total_census = sum(rows.values())
    total_visits = sum(visits.get(k, 0) for k in rows)
    print(f"  census total = {total_census:,}   visits total = {total_visits:,}")
    for key in sorted(rows, key=lambda k: -rows[k]):
        v = visits.get(key, 0)
        c = rows[key]
        opsum = sum(table.get(key, {}).values())
        print(f"  {key:18s} census={c:>10,}  visits={v:>10,}  ops={opsum:>10,}  "
              f"ops/enode={opsum / c:6.3f}")

    # ---- full matrix markdown --------------------------------------------
    all_cols = [c for c in am_cols if any(c == k for r in table.values() for k in r)]
    extra_cols = ["mem.write.c+cm", "reg.write+m", "const.var", "state.decl", "operand.ref"]
    cols = all_cols + [c for c in extra_cols if c not in all_cols and
                       (any(c in r for r in table.values()) or c in synth_rows.get("<non-enode>", {}))]
    lines = []
    header = "| gsim enode | 普查 | visits | " + " | ".join(cols) + " |"
    sep = "|" + "---|" * (3 + len(cols))
    lines.append(header)
    lines.append(sep)
    for key in sorted(rows, key=lambda k: -rows[k]):
        r = table.get(key, {})
        cells = [f"{r[c]:,}" if c in r else "" for c in cols]
        lines.append(f"| {key} | {rows[key]:,} | {visits.get(key, 0):,} | " + " | ".join(cells) + " |")
    for skey, r in list(synth_rows.items()) + list(am_only_rows.items()):
        cells = [f"{r[c]:,}" if c in r else "" for c in cols]
        lines.append(f"| {skey} | — | — | " + " | ".join(cells) + " |")
    Path("build/logs/no0005/enode_instr_matrix.md").write_text("\n".join(lines) + "\n")
    print(f"\nmatrix markdown -> build/logs/no0005/enode_instr_matrix.md "
          f"({len(lines) - 2} rows x {len(cols)} cols)")

    # ---- segment decomposition (for NO0005 §5) ---------------------------
    print("\n== segment decomposition ==")
    ref_ops = sum(table.get("REF", {}).values())
    int_ops = sum(table.get("OP_INT", {}).values()) + sum(table.get("OP_INDEX_INT", {}).values())
    compute_keys = [k for k in table if k not in ("REF", "OP_INT", "OP_INDEX_INT")]
    comp_ops = sum(sum(table[k].values()) for k in compute_keys)
    nonenode_ops = sum(synth_rows.get("<non-enode>", {}).values())
    am_only_ops = sum(sum(r.values()) for r in am_only_rows.values())
    n_ref = rows["REF"]
    n_const = rows["OP_INT"] + rows["OP_INDEX_INT"]
    n_comp = total_census - n_ref - n_const
    print(f"  REF        enodes={n_ref:>11,} -> ops={ref_ops:>10,}  ratio={ref_ops / n_ref:6.3f}")
    print(f"  const      enodes={n_const:>11,} -> ops={int_ops:>10,}  ratio={int_ops / n_const:6.3f}")
    print(f"  compute    enodes={n_comp:>11,} -> ops={comp_ops:>10,}  ratio={comp_ops / n_comp:6.3f}")
    print(f"  <non-enode>                -> ops={nonenode_ops:>10,}")
    print(f"  <am-only>                  -> ops={am_only_ops:>10,}")
    grand = ref_ops + int_ops + comp_ops + nonenode_ops
    print(f"  exec op total = {grand:,}   AM instr pre-opt = {sum(am_mix.values()):,}")
    print(f"  AM instr = exec {grand:,} - non-instr kinds + AM-only {am_only_ops:,}")

    # top expansion rows: ops-per-enode above 1.0, by absolute excess
    print("\n== top expansion rows (ops beyond 1:1, census base) ==")
    excess = []
    for k in compute_keys + ["REF"]:
        o = sum(table[k].values())
        c = rows.get(k, 0)
        if c > 0 and o > c:
            excess.append((k, o - c, o, c))
    for k, ex, o, c in sorted(excess, key=lambda t: -t[1])[:15]:
        print(f"  {k:18s} census={c:>9,}  ops={o:>9,}  excess={ex:>9,}  ops/enode={o / c:5.2f}")

    # machine-readable dump for the doc
    out = {
        "rows": rows, "visits": visits, "table": table,
        "synth_rows": {**synth_rows, **am_only_rows},
        "column_closure": {c: {"matrix": combined.get(c, 0), "am": am_merged.get(c, 0)}
                           for c in sorted(set(list(combined) + list(am_merged)))},
    }
    Path("build/logs/no0005/enode_instr_matrix.json").write_text(json.dumps(out, indent=1))
    if worst:
        print(f"\nWARNING: {len(worst)} column residuals non-zero")
    return 0


if __name__ == "__main__":
    sys.exit(main())
