#!/usr/bin/env python3

import argparse
import json
from collections import Counter
from pathlib import Path


GSIM_OP_BUCKETS = {
    "OP_MUX": "mux_control",
    "OP_WHEN": "mux_control",
    "OP_ADD": "arithmetic",
    "OP_SUB": "arithmetic",
    "OP_MUL": "arithmetic",
    "OP_DIV": "arithmetic",
    "OP_REM": "arithmetic",
    "OP_NEG": "arithmetic",
    "OP_CVT": "cast_width",
    "OP_LT": "compare",
    "OP_LEQ": "compare",
    "OP_GT": "compare",
    "OP_GEQ": "compare",
    "OP_EQ": "compare",
    "OP_NEQ": "compare",
    "OP_AND": "bitwise_logic",
    "OP_OR": "bitwise_logic",
    "OP_XOR": "bitwise_logic",
    "OP_NOT": "bitwise_logic",
    "OP_ANDR": "bitwise_logic",
    "OP_ORR": "bitwise_logic",
    "OP_XORR": "bitwise_logic",
    "OP_DSHL": "shift",
    "OP_DSHR": "shift",
    "OP_SHL": "shift",
    "OP_SHR": "shift",
    "OP_HEAD": "slice_index",
    "OP_TAIL": "slice_index",
    "OP_BITS": "slice_index",
    "OP_BITS_NOSHIFT": "slice_index",
    "OP_INDEX_INT": "slice_index",
    "OP_INDEX": "slice_index",
    "OP_CAT": "aggregate_concat",
    "OP_GROUP": "aggregate_concat",
    "OP_ASUINT": "cast_width",
    "OP_ASSINT": "cast_width",
    "OP_ASCLOCK": "cast_width",
    "OP_ASASYNCRESET": "cast_width",
    "OP_PAD": "cast_width",
    "OP_SEXT": "cast_width",
    "OP_READ_MEM": "memory",
    "OP_WRITE_MEM": "memory",
    "OP_INFER_MEM": "memory",
    "OP_PRINTF": "special",
    "OP_ASSERT": "special",
    "OP_EXIT": "special",
    "OP_EXT_FUNC": "special",
    "OP_INVALID": "special",
    "OP_RESET": "special",
    "OP_STMT_SEQ": "statement",
    "OP_STMT_WHEN": "statement",
    "OP_STMT_NODE": "statement",
    "OP_INT": "const",
}

GRH_OP_BUCKETS = {
    "kConstant": "const",
    "kAdd": "arithmetic",
    "kSub": "arithmetic",
    "kMul": "arithmetic",
    "kDiv": "arithmetic",
    "kMod": "arithmetic",
    "kEq": "compare",
    "kNe": "compare",
    "kCaseEq": "compare",
    "kCaseNe": "compare",
    "kWildcardEq": "compare",
    "kWildcardNe": "compare",
    "kLt": "compare",
    "kLe": "compare",
    "kGt": "compare",
    "kGe": "compare",
    "kAnd": "bitwise_logic",
    "kOr": "bitwise_logic",
    "kXor": "bitwise_logic",
    "kXnor": "bitwise_logic",
    "kNot": "bitwise_logic",
    "kLogicAnd": "bitwise_logic",
    "kLogicOr": "bitwise_logic",
    "kLogicNot": "bitwise_logic",
    "kReduceAnd": "bitwise_logic",
    "kReduceOr": "bitwise_logic",
    "kReduceXor": "bitwise_logic",
    "kReduceNor": "bitwise_logic",
    "kReduceNand": "bitwise_logic",
    "kReduceXnor": "bitwise_logic",
    "kShl": "shift",
    "kLShr": "shift",
    "kAShr": "shift",
    "kMux": "mux_control",
    "kAssign": "statement",
    "kConcat": "aggregate_concat",
    "kReplicate": "aggregate_concat",
    "kSliceStatic": "slice_index",
    "kSliceDynamic": "slice_index",
    "kSliceArray": "slice_index",
    "kLatch": "stateful_decl",
    "kLatchReadPort": "stateful_port",
    "kLatchWritePort": "stateful_port",
    "kRegister": "stateful_decl",
    "kRegisterReadPort": "stateful_port",
    "kRegisterWritePort": "stateful_port",
    "kMemory": "stateful_decl",
    "kMemoryReadPort": "stateful_port",
    "kMemoryWritePort": "stateful_port",
    "kInstance": "hierarchy_call",
    "kBlackbox": "hierarchy_call",
    "kSystemFunction": "hierarchy_call",
    "kSystemTask": "hierarchy_call",
    "kDpicImport": "hierarchy_call",
    "kDpicCall": "hierarchy_call",
    "kXMRRead": "hierarchy_call",
    "kXMRWrite": "hierarchy_call",
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def bucketize(raw: dict[str, int], mapping: dict[str, str], extra_name: str | None = None, extra_count: int = 0) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for name, count in raw.items():
        counter[mapping.get(name, "other")] += int(count)
    if extra_name and extra_count:
        counter[extra_name] += int(extra_count)
    return dict(sorted(counter.items()))


def summarize_gsim(payload: dict) -> dict:
    expnodes = payload.get("expnodes", {})
    op_types = {str(k): int(v) for k, v in expnodes.get("op_types", {}).items()}
    return {
        "graph": str(payload.get("graph", "")),
        "supernode_count": int(payload.get("supernode_count", 0)),
        "node_count": int(payload.get("node_count", 0)),
        "edge_count": int(payload.get("edge_count", 0)),
        "dep_edge_count": int(payload.get("dep_edge_count", 0)),
        "node_types": {str(k): int(v) for k, v in payload.get("node_types", {}).items()},
        "node_status": {str(k): int(v) for k, v in payload.get("node_status", {}).items()},
        "tree_slots": {str(k): int(v) for k, v in payload.get("tree_slots", {}).items()},
        "expnode_unique_count": int(expnodes.get("unique_count", 0)),
        "expnode_edge_count": int(expnodes.get("edge_count", 0)),
        "expnode_node_ref_count": int(expnodes.get("node_ref_count", 0)),
        "expnode_int_const_count": int(expnodes.get("int_const_count", 0)),
        "expnode_op_types": op_types,
        "expnode_buckets": bucketize(
            op_types,
            GSIM_OP_BUCKETS,
            extra_name="node_ref",
            extra_count=int(expnodes.get("node_ref_count", 0)),
        ),
        "expnode_node_ref_target_types": {
            str(k): int(v) for k, v in expnodes.get("node_ref_target_types", {}).items()
        },
    }


def summarize_grh_design(payload: dict) -> dict:
    graphs = payload.get("graphs", [])
    graph_symbols: list[str] = []
    op_kinds: Counter[str] = Counter()
    value_count = 0
    operation_count = 0
    input_ports = 0
    output_ports = 0
    inout_ports = 0
    for graph in graphs:
        graph_symbols.append(str(graph.get("symbol", "")))
        vals = graph.get("vals", [])
        ops = graph.get("ops", [])
        value_count += len(vals)
        operation_count += len(ops)
        ports = graph.get("ports", {})
        input_ports += len(ports.get("in", []))
        output_ports += len(ports.get("out", []))
        inout_ports += len(ports.get("inout", []))
        for op in ops:
            op_kinds[str(op.get("kind", "unknown"))] += 1
    return {
        "kind": "grh_design_json",
        "graph_count": len(graphs),
        "graph_symbols": graph_symbols,
        "top_graphs": [str(x) for x in payload.get("tops", [])],
        "value_count": value_count,
        "operation_count": operation_count,
        "port_count": {
            "in": input_ports,
            "out": output_ports,
            "inout": inout_ports,
        },
        "operation_kinds": dict(sorted(op_kinds.items())),
        "operation_buckets": bucketize(dict(op_kinds), GRH_OP_BUCKETS),
    }


def summarize_grh_stats(payload: dict) -> dict:
    op_kinds = {str(k): int(v) for k, v in payload.get("operation_kinds", {}).items()}
    return {
        "kind": "grh_stats_json",
        "graph_count": int(payload.get("graph_count", 0)),
        "value_count": int(payload.get("value_count", 0)),
        "operation_count": int(payload.get("operation_count", 0)),
        "operation_kinds": op_kinds,
        "operation_buckets": bucketize(op_kinds, GRH_OP_BUCKETS),
    }


def summarize_grh(payload: dict) -> dict:
    if "graphs" in payload:
        return summarize_grh_design(payload)
    return summarize_grh_stats(payload)


def ratio(lhs: int, rhs: int) -> str:
    if rhs == 0:
        return "n/a"
    return f"{lhs / rhs:.4f}x"


def top_items(data: dict[str, int], limit: int) -> list[tuple[str, int]]:
    return sorted(data.items(), key=lambda item: (-item[1], item[0]))[:limit]


def render_report(gsim: dict, grh: dict, *, top_n: int) -> str:
    lines: list[str] = []
    lines.append("IR Shape Comparison")
    lines.append(f"GSim graph: {gsim['graph'] or '<unknown>'}")
    lines.append(
        "GSim node_count={} expnode_unique_count={} node_ref_count={} int_const_count={}".format(
            gsim["node_count"],
            gsim["expnode_unique_count"],
            gsim["expnode_node_ref_count"],
            gsim["expnode_int_const_count"],
        )
    )
    lines.append(
        "GRH graph_count={} operation_count={} value_count={}".format(
            grh["graph_count"],
            grh["operation_count"],
            grh["value_count"],
        )
    )
    lines.append(
        "Ratios: gsim.node/grh.op={} gsim.expnode/grh.op={} gsim.nodeRef/grh.val={} gsim.node/(grh.op+grh.val)={}".format(
            ratio(gsim["node_count"], grh["operation_count"]),
            ratio(gsim["expnode_unique_count"], grh["operation_count"]),
            ratio(gsim["expnode_node_ref_count"], grh["value_count"]),
            ratio(gsim["node_count"], grh["operation_count"] + grh["value_count"]),
        )
    )
    lines.append("")
    lines.append("Shape Notes")
    lines.append("- GSim is a two-layer IR: named Node objects carry scheduling edges, while expression detail lives in ENode trees.")
    lines.append("- GRH is a flat op-value graph: state declarations/read/write ports and combinational logic are all explicit operations with def-use links through values.")
    lines.append("- A large gsim.node vs grh.operation gap usually means FIRRTL-side named lvalues/state ports are coarser than GRH's op partitioning; a large gsim.expnode vs grh.operation gap points to heavier tree-shaped expression materialization.")
    lines.append("")
    lines.append("Top GSim Node Types")
    for name, count in top_items(gsim["node_types"], top_n):
        lines.append(f"- {name}: {count}")
    lines.append("")
    lines.append("Top GSim ExpNode Ops")
    for name, count in top_items(gsim["expnode_op_types"], top_n):
        lines.append(f"- {name}: {count}")
    lines.append("")
    lines.append("GSim ExpNode Buckets")
    for name, count in top_items(gsim["expnode_buckets"], top_n):
        lines.append(f"- {name}: {count}")
    lines.append("")
    lines.append("Top GRH Operation Kinds")
    for name, count in top_items(grh["operation_kinds"], top_n):
        lines.append(f"- {name}: {count}")
    lines.append("")
    lines.append("GRH Operation Buckets")
    for name, count in top_items(grh["operation_buckets"], top_n):
        lines.append(f"- {name}: {count}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gsim-stats", required=True, type=Path)
    parser.add_argument("--grh", required=True, type=Path, help="GRH design json or stats json")
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--top-n", type=int, default=12)
    args = parser.parse_args()

    gsim = summarize_gsim(load_json(args.gsim_stats))
    grh = summarize_grh(load_json(args.grh))
    comparison = {
        "gsim": gsim,
        "grh": grh,
        "ratios": {
            "gsim_node_over_grh_operation": ratio(gsim["node_count"], grh["operation_count"]),
            "gsim_expnode_over_grh_operation": ratio(gsim["expnode_unique_count"], grh["operation_count"]),
            "gsim_node_ref_over_grh_value": ratio(gsim["expnode_node_ref_count"], grh["value_count"]),
            "gsim_node_over_grh_value_plus_operation": ratio(
                gsim["node_count"],
                grh["operation_count"] + grh["value_count"],
            ),
        },
    }
    if args.out_json:
        args.out_json.write_text(json.dumps(comparison, indent=2, sort_keys=True), encoding="utf-8")
    print(render_report(gsim, grh, top_n=args.top_n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
