#!/usr/bin/env python3
"""Inspect exact Rob exports, with FIRRTL-derived aggregate register identities."""

import argparse
from collections import Counter, defaultdict
import csv
import gc
import hashlib
import json
import math
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))
from grhsim_declared_pack_census import declared_names
from grhsim_gsim_module_compare import (GRHSIM_KIND_BUCKETS, bucket_of_gsim_op,
                                        distribution, normalize_name)
from grhsim_paired_cone_diff import (GrhSignatures, GsimSignatures, Signatures,
                                    load_grhsim_final, load_gsim)
from grhsim_residual_write_cones import cone, tree_summary

INSTANCE = "cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$rob"
GSIM_INSTANCE = "cpu__DOT__l_soc__DOT__core_with_l2__DOT__core__DOT__backend__DOT__inner__DOT__ctrlBlock__DOT__rob"


def log(message):
    print(message, flush=True)


def write_tsv(path, rows, fields=None):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fields or list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_type(tokens, pos=0):
    if tokens[pos] == "{":
        fields = []
        pos += 1
        while tokens[pos] != "}":
            if tokens[pos] == "flip":
                pos += 1
            name = tokens[pos]
            assert tokens[pos + 1] == ":"
            typ, pos = parse_type(tokens, pos + 2)
            fields.append((name, typ))
            if tokens[pos] == ",":
                pos += 1
        typ = ("bundle", fields)
        pos += 1
    else:
        kind = tokens[pos]
        pos += 1
        width = 1
        if tokens[pos] == "<":
            width = int(tokens[pos + 1])
            assert tokens[pos + 2] == ">"
            pos += 3
        typ = ("ground", kind, width)
    while tokens[pos] == "[":
        typ = ("vector", typ, int(tokens[pos + 1]))
        assert tokens[pos + 2] == "]"
        pos += 3
    return typ, pos


def type_leaves(typ, sv_parts, fields, indices=(), dimensions=(), canonical=""):
    if typ[0] == "bundle":
        for name, child in typ[1]:
            yield from type_leaves(child, sv_parts + [name], fields + [name], indices,
                                   dimensions, canonical + "." + name)
    elif typ[0] == "vector":
        for index in range(typ[2]):
            yield from type_leaves(typ[1], sv_parts + [str(index)], fields,
                                   indices + (index,), dimensions + (typ[2],),
                                   canonical + f"[{index}]")
    else:
        yield sv_parts, fields, indices, dimensions, canonical, typ[2]


def register_schema(fixture):
    manifest = json.loads((fixture / "manifest.json").read_text())
    definitions = defaultdict(list)
    current = None
    mod_re = re.compile(r"^  module (\S+) :")
    reg_re = re.compile(r"^\s+reg(?:reset)? (\S+) : (.*)")
    for line in (fixture / "Rob.fir").open():
        m = mod_re.match(line)
        if m:
            current = m[1]
        m = reg_re.match(line)
        if m:
            tokens = re.findall(r"[A-Za-z_][\w$]*|\d+|[{}<>\[\]:,]", m[2])
            typ, _ = parse_type(tokens)
            definitions[current].append((m[1], typ))
    module_children = {r["module"]: r["instances"] for r in manifest["firrtl_modules"]}
    entries = {}
    instances = [("", "Rob")]
    while instances:
        path, module = instances.pop()
        for name, typ in definitions[module]:
            for sv, fields, indices, dims, canonical, width in type_leaves(typ, [name], [name], canonical=name):
                sv_name = (path + "$" if path else "") + "_".join(sv)
                base = (path.replace("$", "__DOT__") + "__DOT__" if path else "") + "__DOT__".join(fields)
                gname = base + "".join(f"_{idx}" for idx in indices)
                if sv_name in entries:
                    raise ValueError(f"schema name collision: {sv_name}")
                entries[sv_name] = {"canonical": (path + "." if path else "") + canonical,
                                    "module": path, "field": ".".join(fields), "width": width,
                                    "gsim": gname, "gsim_array": base, "dimensions": list(dims),
                                    "indices": list(indices)}
        instances.extend(((path + "$" if path else "") + inst, child)
                         for inst, child in module_children[module])
    log(f"FIRRTL schema: {len(entries)} scalar register leaves")
    return entries


def gsim_summary(path):
    log(f"summarizing {path}")
    model = json.loads(path.read_bytes())
    registers = {}
    node_types, kinds = Counter(), Counter()
    rhs_kinds = Counter()
    for node in model["nodes"]:
        node_types[node["type"]] += 1
        if node["type"] == "NODE_REG_SRC":
            registers[node["name"]] = {"width": node["width"], "dimensions": node.get("dimension", [])}
        for tree in node.get("assignTrees") or []:
            kinds.update(row["op"] for row in tree["nodes"])
        rhs_kinds.update(tree_summary(node.get("assignTrees") or [])["rhs_kinds"])
    bits = sum(row["width"] * math.prod(row["dimensions"]) for row in registers.values())
    summary = {"nodes": len(model["nodes"]), "node_types": dict(node_types), "stored_enodes": sum(kinds.values()),
               "stored_kinds": dict(kinds), "rhs_enodes": sum(rhs_kinds.values()), "rhs_kinds": dict(rhs_kinds),
               "register_nodes": len(registers), "register_scalar_elements": sum(math.prod(r["dimensions"]) for r in registers.values()),
               "register_storage_bits": bits, "array_register_nodes": sum(bool(r["dimensions"]) for r in registers.values())}
    del model
    gc.collect()
    return summary, registers


def grhsim_summary(path):
    log(f"summarizing {path}")
    model = json.loads(path.read_bytes())
    strings, types = model["strings"], {t[0]: t for t in model["types"]}
    declared = declared_names(model)
    registers, arrays = {}, {}
    event_states = 0
    for state in model["states"]:
        name, typ = strings[state[1] - 1], types[state[2]]
        if typ[2] == "array":
            arrays[name] = typ
        elif name.startswith("__event_"):
            event_states += 1
        else:
            registers[name] = {"id": state[0], "width": typ[3], "declared": name in declared}
    kinds = Counter(strings[op[1] - 1] for op in model["operations"])
    summary = {"ops": len(model["operations"]), "values": len(model["values"]),
               "kinds": dict(kinds), "states": len(model["states"]),
               "register_states": len(registers), "register_bits": sum(r["width"] for r in registers.values()),
               "array_states": len(arrays), "event_states": event_states,
               "declared_registers": sum(r["declared"] for r in registers.values()),
               "declared_register_bits": sum(r["width"] for r in registers.values() if r["declared"]),
               "types": list(types.values())}
    del model, strings, declared
    gc.collect()
    return summary, registers, arrays


def classify(name, width, schema, gregs, normal_index):
    exact = normal_index.get(normalize_name(name), [])
    same = [gn for gn in exact if gregs[gn]["width"] == width and not gregs[gn]["dimensions"]]
    if len(same) == 1:
        return "exact_name", same[0], ""
    entry = schema.get(name)
    if entry:
        row = gregs.get(entry["gsim"])
        if row is not None and not row["dimensions"]:
            return ("aggregate_index_order" if row["width"] == width else "width_changed"), entry["gsim"], entry["canonical"]
        row = gregs.get(entry["gsim_array"])
        if row and row["dimensions"] == entry["dimensions"] and row["dimensions"]:
            return ("gsim_array_element" if row["width"] == width else "array_width_changed"), entry["gsim_array"], entry["canonical"]
        # gsim splitNodes records the inclusive [high:low] range after '$'.
        chunk_re = re.compile(re.escape(entry["gsim"]) + r"\$(\d+)_(\d+)$")
        chunks = []
        for gn, row in gregs.items():
            match = chunk_re.fullmatch(gn)
            if match and not row["dimensions"]:
                hi, lo = int(match[1]), int(match[2])
                if row["width"] != hi - lo + 1:
                    raise ValueError(f"invalid split range: {gn}")
                chunks.append((lo, hi, gn))
        if chunks:
            chunks.sort()
            if chunks[0][0] == 0 and chunks[-1][1] == width - 1 and all(
                    a[1] + 1 == b[0] for a, b in zip(chunks, chunks[1:])):
                return "gsim_bit_chunks", ";".join(c[2] for c in chunks), entry["canonical"]
    if exact:
        return "width_or_shape_changed", ";".join(exact), ""
    return "no_schema_match", "", entry["canonical"] if entry else ""


def match_registers(rregs, gregs, schema, output, label):
    normal_index = defaultdict(list)
    for name in gregs:
        normal_index[normalize_name(name)].append(name)
    rows, pairs = [], []
    for name, reg in sorted(rregs.items()):
        if not reg["declared"]:
            continue
        reason, gn, canonical = classify(name, reg["width"], schema, gregs, normal_index)
        rows.append({"grhsim": name, "width": reg["width"], "status": reason, "gsim": gn,
                     "canonical": canonical, "gsim_width": gregs.get(gn, {}).get("width", ""),
                     "gsim_dimensions": json.dumps(gregs.get(gn, {}).get("dimensions", []))})
        if reason in ("exact_name", "aggregate_index_order"):
            pairs.append({"grhsim": name, "gsim": gn, "width": reg["width"], "key": canonical or name})
    if len({p["gsim"] for p in pairs}) != len(pairs):
        raise ValueError("FIRRTL-derived scalar pairing is not one-to-one")
    write_tsv(output / f"{label}_registers.tsv", rows)
    summary = {"count": len(rows), "bits": sum(r["width"] for r in rows),
               "counts": dict(Counter(r["status"] for r in rows)),
               "bits_by_status": {s: sum(r["width"] for r in rows if r["status"] == s)
                                  for s in sorted({r["status"] for r in rows})}}
    return summary, pairs


def whole_design_unpaired(schema, output):
    """Read exported node headers only, to explain the original instance census."""
    path = REPO / "ptmp/no00020_gsim_module_compare_20260926/gsim-export/SimTop_PreCoarsen.json"
    prefix = GSIM_INSTANCE + "__DOT__"
    registers = {}
    marker = ', "assignTrees":'
    log("reading whole-design gsim register headers")
    for line in path.open():
        if line.startswith('    {"id":') and '"type": "NODE_REG_SRC"' in line and prefix in line:
            header = json.loads(line.split(marker, 1)[0] + "}")
            if header["name"].startswith(prefix):
                registers[header["name"][len(prefix):]] = {"width": header["width"], "dimensions": header["dimension"]}
    normal_index = defaultdict(list)
    for name in registers:
        normal_index[normalize_name(name)].append(name)
    rows = []
    original = REPO / "ptmp/grhsim_unpaired_registers_20260928/unpaired_registers.tsv"
    for row in csv.DictReader(original.open(), delimiter="\t"):
        if row["module_path"] != INSTANCE:
            continue
        name, width = row["register_path"][len(INSTANCE) + 1:], int(row["width_bits"])
        status, gn, canonical = classify(name, width, schema, registers, normal_index)
        rows.append({"register_path": row["register_path"], "local_name": name, "width": width,
                     "status": status, "gsim": prefix + gn if gn else "", "canonical": canonical,
                     "gsim_width": registers.get(gn, {}).get("width", ""),
                     "gsim_dimensions": json.dumps(registers.get(gn, {}).get("dimensions", []))})
    assert len(rows) == 1537
    write_tsv(output / "original_1537_reclassified.tsv", rows)
    families = defaultdict(list)
    for row in rows:
        families[re.sub(r"\d+", "#", row["local_name"]), row["status"]].append(row)
    family_rows = [{"family": k[0], "status": k[1], "count": len(v), "bits": sum(r["width"] for r in v),
                    "example_grhsim": v[0]["local_name"], "example_gsim": v[0]["gsim"]}
                   for k, v in families.items()]
    family_rows.sort(key=lambda r: (-r["count"], r["family"]))
    write_tsv(output / "original_1537_families.tsv", family_rows)
    return {"count": len(rows), "bits": sum(r["width"] for r in rows),
            "counts": dict(Counter(r["status"] for r in rows)), "families": family_rows}


def compare_cones(model_path, graph_path, pairs, output):
    log("building scalar register update-cone comparisons")
    grh, graph = load_grhsim_final(model_path), load_gsim(graph_path)
    keys_g = {p["gsim"]: i for i, p in enumerate(pairs)}
    keys_r = {p["grhsim"]: i for i, p in enumerate(pairs)}
    pool = Signatures()
    ge, se = GrhSignatures(grh, keys_r, pool), GsimSignatures(graph, keys_g, pool)
    sid_of = {name: sid for sid, name in enumerate(grh["state_name"]) if sid}
    write_ops = defaultdict(list)
    for oid, op in grh["operations"].items():
        if grh["kinds"][oid] == "core.state.regWrite":
            write_ops[op[6][0][1]].append(oid)
    dst_of = {name: dst for name, _w, dst in graph.reg_src}
    rows, samples = [], []
    r_union, g_union = set(), set()
    total = Counter()
    # Include the full schema-matched scalar population; memory reads stay opaque.
    for index, pair in enumerate(pairs):
        name = pair["grhsim"]
        roots = grh["writes"].get(sid_of[name], [])
        groot = se.root(dst_of.get(pair["gsim"]))
        if not roots or groot is None:
            total["unlinked"] += 1
            continue
        rops, _ = cone(roots, grh["producer"], grh["operations"], grh["kinds"])
        update_roots = [v for oid in write_ops[sid_of[name]] for v in grh["operations"][oid][4][:3]]
        update_ops, _ = cone(update_roots, grh["producer"], grh["operations"], grh["kinds"])
        se.sig(groot)
        glocs = se.cone(groot)
        rmap = {oid: ge.sig(oid) for oid in rops}
        rsigs = set(rmap.values())
        gsigs = {se.memo[loc] for loc in glocs}
        shared = rsigs & gsigs
        rk = Counter(grh["kinds"][o] for o in rops)
        gk = Counter(graph.op_names[se.row(loc)[0]] for loc in glocs)
        r_compute = sum(v for k, v in rk.items() if k.startswith("core.compute.") and k != "core.compute.constant")
        update_compute = sum(grh["kinds"][o].startswith("core.compute.")
                             and grh["kinds"][o] != "core.compute.constant" for o in update_ops)
        g_compute = sum(v for k, v in gk.items() if k not in ("OP_EMPTY", "OP_INT"))
        row = {"grhsim": name, "gsim": pair["gsim"], "width": pair["width"],
               "grhsim_cone_ops": len(rops), "gsim_cone_enodes": len(glocs),
               "grhsim_compute": r_compute, "gsim_compute": g_compute,
               "grhsim_update_ops": len(update_ops), "grhsim_update_compute": update_compute,
               "grhsim_distinct_signatures": len(rsigs), "gsim_distinct_signatures": len(gsigs),
               "shared_signatures": len(shared), "grhsim_kinds": json.dumps(dict(rk), sort_keys=True),
               "gsim_kinds": json.dumps(dict(gk), sort_keys=True)}
        rows.append(row)
        r_union.update(rops)
        g_union.update(glocs)
        total.update(pairs=1, grhsim_signatures=len(rsigs), gsim_signatures=len(gsigs), shared=len(shared))
        if name in {"robEntries_0_needFlush", "robEntries_0_commitType", "robEntries_0_realDestSize",
                    "robEntries_0_traceBlockInPipe_itype", "io_rabCommits_REG_info_0_ldest"}:
            detail = {**pair, "grhsim_root": [pool.explain(ge.sig(grh["producer"][r]), 5) for r in roots],
                      "gsim_root": pool.explain(se.memo[groot], 5), "counts": row}
            samples.append(detail)
            # Export the actual operations and resolved names for review.
            ops = []
            for oid in sorted(update_ops):
                op = grh["operations"][oid]
                ops.append({"id": oid, "kind": grh["kinds"][oid], "in_next_value_cone": oid in rops,
                            "operands": op[4], "results": op[5],
                            "operand_names": [grh["value_name"][v] for v in op[4]],
                            "result_widths": [grh["value_width"][v] for v in op[5]],
                            "result_names": [grh["value_name"][v] for v in op[5]],
                            "object_refs": [{"kind": kind, "id": ref,
                                             "name": grh["state_name"][ref] if kind == "state" else
                                             grh["inputs"][ref - 1] if kind == "input" else ""}
                                            for kind, ref in op[6]],
                            "attributes": {grh["strings"][p[0] - 1]: p[2] for p in op[7]}})
            writes = [{"id": oid, "operands": grh["operations"][oid][4],
                       "operand_names": [grh["value_name"][v] for v in grh["operations"][oid][4]],
                       "operand_producers": [grh["producer"][v] for v in grh["operations"][oid][4]],
                       "operand_convention": ["updateCond", "nextValue", "mask", "events..."]}
                      for oid in write_ops[sid_of[name]]]
            (output / f"cone_{name}.json").write_text(json.dumps({"pair": pair, "grhsim_writes": writes, "grhsim_ops": ops,
                "gsim_nodes": {n: graph.nodes[n] for n in sorted({loc[0] for loc in glocs} | {groot[0]})},
                "gsim_opcode_names": graph.op_names}, indent=1) + "\n")
        if (index + 1) % 500 == 0:
            log(f"compared {index + 1}/{len(pairs)} register cones")
    rows.sort(key=lambda r: (-r["grhsim_compute"], r["grhsim"]))
    write_tsv(output / "paired_update_cones.tsv", rows)
    (output / "sample_update_trees.json").write_text(json.dumps(samples, indent=2) + "\n")
    result = {"totals": dict(total), "grhsim_cone_ops_union": len(r_union), "gsim_enodes_union": len(g_union),
              "grhsim_compute_distribution": distribution(sorted(r["grhsim_compute"] for r in rows)),
              "grhsim_update_compute_distribution": distribution(sorted(r["grhsim_update_compute"] for r in rows)),
              "gsim_compute_distribution": distribution(sorted(r["gsim_compute"] for r in rows)),
              "grhsim_kinds_union": dict(Counter(grh["kinds"][o] for o in r_union)),
              "gsim_kinds_union": dict(Counter(graph.op_names[se.row(loc)[0]] for loc in g_union)),
              "samples": samples,
              "limitations": "Structural signatures only; memories are side-specific opaque leaves. No equivalence or timing conclusion."}
    del grh, graph, ge, se, pool
    gc.collect()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--cones-only", action="store_true")
    args = parser.parse_args()
    output = args.work / "analysis"
    output.mkdir(exist_ok=True)
    if args.report_only:
        render_report(args.fixture, args.work)
        return
    if args.cones_only:
        result = json.loads((output / "summary.json").read_text())
        pairs = [{"grhsim": r["grhsim"], "gsim": r["gsim"], "width": int(r["width"]),
                  "key": r["canonical"] or r["grhsim"]}
                 for r in csv.DictReader((output / "final_registers.tsv").open(), delimiter="\t")
                 if r["status"] in ("exact_name", "aggregate_index_order")]
        result["cones"] = compare_cones(args.work / "grhsim/final.json",
                                       args.work / "gsim/Rob_PreCoarsen.json", pairs, output)
        (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
        render_report(args.fixture, args.work)
        return
    schema = register_schema(args.fixture)
    original = whole_design_unpaired(schema, output)
    log(f"original 1537 reclassified: {original['counts']}")
    gpath = args.work / "gsim/Rob_PreCoarsen.json"
    gsummary, gregs = gsim_summary(gpath)
    rpost, pre_regs, _ = grhsim_summary(args.work / "grhsim/post_lower.json")
    rfinal, rregs, arrays = grhsim_summary(args.work / "grhsim/final.json")
    post_pairing, _ = match_registers(pre_regs, gregs, schema, output, "post_lower")
    final_pairing, pairs = match_registers(rregs, gregs, schema, output, "final")
    buckets = defaultdict(lambda: Counter())
    for kind, count in gsummary["rhs_kinds"].items():
        buckets[bucket_of_gsim_op(kind)]["gsim_rhs_enodes"] += count
    for label, summary in (("grhsim_post_lower_ops", rpost), ("grhsim_final_ops", rfinal)):
        for kind, count in summary["kinds"].items():
            buckets[GRHSIM_KIND_BUCKETS.get(kind, "other")][label] += count
    write_tsv(output / "op_buckets.tsv", [{"bucket": k, **{c: v[c] for c in
        ("gsim_rhs_enodes", "grhsim_post_lower_ops", "grhsim_final_ops")}} for k, v in sorted(buckets.items())])
    log(f"standalone final pairing: {final_pairing['counts']}")
    result = {"original_unpaired": original, "gsim": gsummary, "grhsim_post_lower": rpost,
              "grhsim_final": rfinal, "post_lower_pairing": post_pairing, "final_pairing": final_pairing}
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    result["cones"] = compare_cones(args.work / "grhsim/final.json", gpath, pairs, output)
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    render_report(args.fixture, args.work)
    log(f"analysis written to {output}")


def render_report(fixture, work):
    output = work / "analysis"
    result = json.loads((output / "summary.json").read_text())
    gs, post, final = result["gsim"], result["grhsim_post_lower"], result["grhsim_final"]
    cones = result["cones"]
    print(json.dumps({"original": result["original_unpaired"]["counts"],
                      "final_pairing": result["final_pairing"],
                      "samples": [{"name": s["grhsim"], "grhsim_root": s["grhsim_root"][0]["op"],
                                   "gsim_root": s["gsim_root"]["op"],
                                   "grhsim_compute": s["counts"]["grhsim_compute"],
                                   "gsim_compute": s["counts"]["gsim_compute"]} for s in cones["samples"]]}, indent=2))
    report = ["# 实际 XiangShan ROB：gsim / GrhSIM IR 微观结构对比", "",
              f"目标实例：`{INSTANCE}`。独立顶层为 `Rob`，包含全部子模块。", "",
              "## 提取与导出", "",
              "`Rob.fir` 为 SimTop.fir 的依赖闭包，10 个 FIRRTL 模块；`rtl/` 为 12 个生成 SV 模块及原有 assert.v DPI 声明。模块正文按字节复制，来源、偏移及 SHA256 见 manifest.json。", "",
              "FIRRTL 去掉了全设计 annotation，电路名改为 Rob；gsim 实际输入 `ptmp/xs-components-rob/Rob_resolved.fir` 只将 Rob 顶层抽象 Reset 解析为 UInt<1>，与 SV 同步复位一致。未修改寄存器数据逻辑。", "",
              "```bash", "make -C testcase/xs-components rob-ir", "make -C testcase/xs-components rob-compare", "```", "",
              "原始导出与分析文件均在 `ptmp/xs-components-rob/`：", "",
              "- `gsim/Rob_0InferAllWidth.json`：gsim 推导位宽后、优化前。",
              "- `gsim/Rob_PreCoarsen.json`：gsim 全部语义优化后、分图前，含 assignTree。",
              "- `grhsim/post_lower.json`：独立 GrhSIM IR lower 后。",
              "- `grhsim/pre_partition.json`：GrhSIM 语义优化后、第二轮 CPU mapping 前。",
              "- `grhsim/final.json`：最终 IR；与 roundtrip.json 逐字节一致。", "",
              "GrhSIM 使用当前 CPU 管线，开启 row-constant-fill、OR-write-merge、migrate-boundary-ops、demonitor-redundant。整机动态 profile 的 ID 不适用于独立模型，因此未使用两个依赖 profile 的调度优化；这两个优化不改寄存器与计算语义。", "",
              "## 原先 1,537 个未配对项", "",
              "逐项使用 FIRRTL 寄存器的 bundle/vector 类型恢复路径；只在类型声明给出的合法索引范围内重排，保留原始位宽检查。", "",
              "| 对应形式 | 原未配对个数 |", "|---|---:|"]
    meanings = {"aggregate_index_order": "字段/数组索引顺序不同的标量寄存器",
                "gsim_array_element": "gsim 保留数组节点，可定位到具体数组元素",
                "gsim_bit_chunks": "gsim 拆成多个 bit chunk，连续完整覆盖原寄存器",
                "no_schema_match": "尚未定位"}
    for status, count in result["original_unpaired"]["counts"].items():
        report.append(f"| {meanings.get(status, status)} | {count:,} |")
    report += ["", "具体例子：`robEntries_351_needFlush` ↔ `robEntries__DOT__needFlush_351`。四个 352 行字段（commitType、needFlush、realDestSize、traceBlockInPipe.itype）共 1,408 个；这部分是匹配器的名称顺序盲点。`robDeqGroup_0_debug_pc` 对应 gsim 的 `robDeqGroup__DOT__debug_pc` 数组元素 0。`robBanksRaddrThisLine[43:0]` 对应 44 个 1 位 chunk。", "",
               "原整机逐项证据：`analysis/original_1537_reclassified.tsv`；按字段计数：`analysis/original_1537_families.tsv`。这些是来源对应关系，未作逐周期等价证明。", "",
               "## 独立模型的结构", "",
               "独立端口未施加整机常量，且保留子模块，因此下列计数不等同于整机中 ROB 本层的 1,596 个 declared state。gsim REG_SRC 的 width 是元素位宽；带 dimension 的数组须乘元素个数。", "",
               "| 指标 | gsim PreCoarsen | GrhSIM post-lower | GrhSIM final |", "|---|---:|---:|---:|",
               f"| 节点 / ops | {gs['nodes']:,} nodes | {post['ops']:,} ops | {final['ops']:,} ops |",
               f"| REG_SRC / 非事件 logic states | {gs['register_nodes']:,} | {post['register_states']:,} | {final['register_states']:,} |",
               f"| REG_SRC 数组 / array states | {gs['array_register_nodes']:,} | {post['array_states']:,} | {final['array_states']:,} |",
               f"| 事件簿记 states | 无对应单独节点 | {post['event_states']:,} | {final['event_states']:,} |", "",
               "REG_SRC 与 GrhSIM logic/array 的拆分策略不同，不能将节点数直接视作存储量或运行代价。gsim 数组 REG_SRC 计入上一行，GrhSIM array 则不计入 logic states。", "",
               "| 运算类别 | gsim RHS enodes | GrhSIM post-lower ops | GrhSIM final ops |", "|---|---:|---:|---:|"]
    for row in csv.DictReader((output / "op_buckets.tsv").open(), delimiter="\t"):
        if row["bucket"] in {"bitwise_logic", "mux_control", "slice_index", "memory", "compare", "aggregate_concat", "arithmetic"}:
            report.append(f"| {row['bucket']} | {int(row['gsim_rhs_enodes']):,} | {int(row['grhsim_post_lower_ops']):,} | {int(row['grhsim_final_ops']):,} |")
    report += ["", "gsim RHS enodes 只统计每棵赋值树 root 可达节点，排除序列化 lvalue；GrhSIM 按唯一 op 计数。两种表示的共享粒度仍不同，表格描述静态形态，不是执行次数。", "",
               "## 配对寄存器的更新锥", "",
               f"依据完整 FIRRTL 路径及一致位宽，独立模型严格对应 {cones['totals']['pairs']:,} 对标量寄存器。保留数组的对应项、位宽不同项和 bit chunk 不混入一对一标量更新锥。", "",
               "更新锥穿过组合别名，在 state/input/memory read 截止。计算节点数排除常量和读取叶。主表的 GrhSIM 更新锥合并 regWrite 的 updateCond、nextValue、mask 三个操作数的反向锥；gsim 取 REG_DST 的全部 RHS 树。两侧均不计时钟/事件检测；TSV 还单列 GrhSIM nextValue 锥，便于区分数据选择与独立写条件。", "",
               "| 指标 | gsim | GrhSIM |", "|---|---:|---:|"]
    for key in ("median", "p90", "mean"):
        report.append(f"| 每对计算节点 {key} | {cones['gsim_compute_distribution'][key]:.2f} | {cones['grhsim_update_compute_distribution'][key]:.2f} |")
    report += ["", "| 寄存器样例 | gsim 计算节点 | GrhSIM 计算节点 |", "|---|---:|---:|"]
    for sample in cones["samples"]:
        row = sample["counts"]
        report.append(f"| `{sample['grhsim']}` | {row['gsim_compute']} | {row['grhsim_update_compute']} |")
    report += ["", "完整逐对计数及 op-kind 分布在 `analysis/paired_update_cones.tsv`。五个样例的解码操作、操作数、state 引用与 gsim 表达树在 `analysis/cone_*.json`；截断表达树在 `analysis/sample_update_trees.json`。", "",
               "### 具体形态差异", "",
               "1. **写条件与数据选择分离**：`commitType[0]` 的 gsim 根是带条件的 OP_WHEN，数据为 8 路 `(enqOH_i ? commitType_i : 0)` 的 OR。GrhSIM nextValue 根直接是 OR，写条件在 regWrite.updateCond；全更新锥将其加回统计。", "",
               "2. **有序条件赋值与掩码合并**：`needFlush[0]` 在 gsim 中是两棵 OP_WHEN 组成的有序赋值序列；GrhSIM 把数据优先级写成单个 bitSelect 的 mask/true/false 计算，再由 regWrite 写回。bitSelect 的三个操作数分别是掩码、选中位的新值、未选中位的值。", "",
               "3. **条件赋值折叠**：`traceBlockInPipe.itype[0]` 的 gsim 两棵条件树分别写入 enq 数据和常量 5；GrhSIM 用 mux 选择 OR 数据网络或常量 5，再用独立写条件控制更新。", "",
               "4. **标量数组与恢复后的存储**：`io_rabCommits_REG_info_0_ldest` 两侧都保留了 352 路候选数据选择网络（各 705 mux、703 OR）；GrhSIM 的表数据来自 352 个 memRead，gsim 使用寄存器数组索引叶。该样例的主要差异在叶的存储表示和切片方式，主体选择网络并未消失。", "",
               "结构签名只用于追踪相同表示；内存读保留为两侧独立叶，且本轮未规范化所有输入 bundle/vector 顺序，因此签名相交比例是保守的表示指标，不是等价率。", "",
               "本轮没有进行运行时间基准。独立模型的静态形态结果不能直接推导整机性能。", ""]
    (fixture / "README.md").write_text("\n".join(report))


if __name__ == "__main__":
    main()
