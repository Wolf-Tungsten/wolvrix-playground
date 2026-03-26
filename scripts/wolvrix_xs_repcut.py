#!/usr/bin/env python3

import json
import os
import sys
import time
from pathlib import Path

from _wolvrix_import import load_wolvrix

wolvrix = load_wolvrix()


def log(message: str) -> None:
    sys.stderr.write(f"[wolvrix-xs-repcut] {message}\n")
    sys.stderr.flush()


def _build_repcut_args(
    work_dir: Path,
    *,
    include_imbalance_factor: bool = True,
    include_work_dir: bool = True,
    include_partitioner: bool = True,
    include_mtkahypar_tuning: bool = True,
    include_keep_intermediate_files: bool = True,
) -> list[str]:
    args = [
        "-path",
        REPCUT_PATH,
        "-partition-count",
        REPCUT_PARTITION_COUNT,
    ]
    if include_imbalance_factor:
        args.extend(["-imbalance-factor", REPCUT_IMBALANCE_FACTOR])
    if include_work_dir:
        args.extend(["-work-dir", str(work_dir)])
    if include_partitioner:
        args.extend(["-partitioner", REPCUT_PARTITIONER])
    if include_mtkahypar_tuning:
        args.extend(
            [
                "-mtkahypar-preset",
                REPCUT_MTKAHYPAR_PRESET,
                "-mtkahypar-threads",
                REPCUT_MTKAHYPAR_THREADS,
            ]
        )
    if include_keep_intermediate_files and REPCUT_KEEP_INTERMEDIATE_FILES:
        args.append("-keep-intermediate-files")
    return args


def _run_repcut_with_compat(
    design,
    work_dir: Path,
    *,
    diagnostics: str,
    log_level: str,
    print_diagnostics_level: str,
    raise_diagnostics_level: str,
) -> tuple[bool, list[dict]]:
    profiles: list[tuple[str, dict[str, bool]]] = [
        (
            "current",
            {
                "include_imbalance_factor": True,
                "include_work_dir": True,
                "include_partitioner": True,
                "include_mtkahypar_tuning": True,
                "include_keep_intermediate_files": True,
            },
        ),
        (
            "no-keep-intermediate-files",
            {
                "include_imbalance_factor": True,
                "include_work_dir": True,
                "include_partitioner": True,
                "include_mtkahypar_tuning": True,
                "include_keep_intermediate_files": False,
            },
        ),
        (
            "no-mtkahypar-tuning",
            {
                "include_imbalance_factor": True,
                "include_work_dir": True,
                "include_partitioner": True,
                "include_mtkahypar_tuning": False,
                "include_keep_intermediate_files": False,
            },
        ),
        (
            "no-partitioner",
            {
                "include_imbalance_factor": True,
                "include_work_dir": True,
                "include_partitioner": False,
                "include_mtkahypar_tuning": False,
                "include_keep_intermediate_files": False,
            },
        ),
        (
            "base-without-work-dir",
            {
                "include_imbalance_factor": True,
                "include_work_dir": False,
                "include_partitioner": False,
                "include_mtkahypar_tuning": False,
                "include_keep_intermediate_files": False,
            },
        ),
        (
            "base-only",
            {
                "include_imbalance_factor": False,
                "include_work_dir": False,
                "include_partitioner": False,
                "include_mtkahypar_tuning": False,
                "include_keep_intermediate_files": False,
            },
        ),
    ]

    last_unknown_option_error: ValueError | None = None
    for profile_name, flags in profiles:
        repcut_args = _build_repcut_args(work_dir, **flags)
        try:
            changed, repcut_diags = design.run_pass(
                "repcut",
                args=repcut_args,
                diagnostics=diagnostics,
                log_level=log_level,
                print_diagnostics_level=print_diagnostics_level,
                raise_diagnostics_level=raise_diagnostics_level,
            )
            log(f"pass repcut args profile={profile_name} argc={len(repcut_args)}")
            if profile_name != "current":
                log(f"pass repcut compatibility fallback selected profile={profile_name}")
            return changed, repcut_diags
        except ValueError as ex:
            if "unknown repcut option" not in str(ex):
                raise
            last_unknown_option_error = ex
            log(f"pass repcut args profile={profile_name} rejected: {ex}")

    if last_unknown_option_error is not None:
        raise last_unknown_option_error
    raise RuntimeError("repcut compatibility fallback exhausted without a terminal result")


def _extract_repcut_stats_diag(diags: list[dict]) -> dict | None:
    for diag in diags or []:
        text = str(diag.get("text", ""))
        if "\"pass\":\"repcut\"" not in text:
            continue
        begin = text.find("{")
        if begin < 0:
            continue
        try:
            payload = json.loads(text[begin:])
        except json.JSONDecodeError:
            continue
        if payload.get("pass") == "repcut":
            return payload
    return None


def _write_partition_features_fallback(work_dir: Path, payload: dict) -> Path | None:
    graph = str(payload.get("graph", "")).strip()
    k = payload.get("partition_count_requested")
    records = payload.get("partition_static_features")
    if not graph or k is None or not isinstance(records, list):
        return None
    out_path = work_dir / f"{graph}_repcut_k{k}.partition_features.jsonl"
    with out_path.open("w", encoding="utf-8") as handle:
        summary = {
            "record_type": "partition_static_feature_summary",
            "schema_version": 1,
            "graph": graph,
            "stem": f"{graph}_repcut_k{k}",
            "partition_count": payload.get("partition_count_observed", len(records)),
            "cross_value_count": payload.get("cross_values_total", 0),
        }
        handle.write(json.dumps(summary, ensure_ascii=True) + "\n")
        for record in records:
            row = {"record_type": "partition_static_features", "schema_version": 1}
            row.update(record)
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")
    return out_path


_SINK_OP_KINDS = {
    "kRegisterWritePort",
    "kLatchWritePort",
    "kMemoryWritePort",
    "kSystemTask",
}
_SOURCE_OP_KINDS = {"kConstant", "kRegisterReadPort", "kLatchReadPort"}
_COMB_OP_KINDS = {
    "kConstant",
    "kAdd",
    "kSub",
    "kMul",
    "kDiv",
    "kMod",
    "kEq",
    "kNe",
    "kCaseEq",
    "kCaseNe",
    "kWildcardEq",
    "kWildcardNe",
    "kLt",
    "kLe",
    "kGt",
    "kGe",
    "kAnd",
    "kOr",
    "kXor",
    "kXnor",
    "kNot",
    "kLogicAnd",
    "kLogicOr",
    "kLogicNot",
    "kReduceAnd",
    "kReduceOr",
    "kReduceXor",
    "kReduceNor",
    "kReduceNand",
    "kReduceXnor",
    "kShl",
    "kLShr",
    "kAShr",
    "kMux",
    "kAssign",
    "kConcat",
    "kReplicate",
    "kSliceStatic",
    "kSliceDynamic",
    "kSliceArray",
    "kMemoryReadPort",
}
_WIDTH_BUCKETS = [
    ("w1", 1, 1),
    ("w2_8", 2, 8),
    ("w9_16", 9, 16),
    ("w17_32", 17, 32),
    ("w33_64", 33, 64),
    ("w65_128", 65, 128),
    ("w129_256", 129, 256),
    ("w257_plus", 257, None),
]


def _width_to_word_count(width: int) -> int:
    return 1 if width <= 0 else (width + 63) // 64


def _width_bucket_name(width: int) -> str:
    for name, lower, upper in _WIDTH_BUCKETS:
        if width < lower:
            continue
        if upper is None or width <= upper:
            return name
    return "w257_plus"


def _op_has_events(op: dict) -> bool:
    attrs = op.get("attrs") or {}
    event_edge = attrs.get("eventEdge")
    if isinstance(event_edge, dict):
        values = event_edge.get("vs")
        return bool(values)
    if isinstance(event_edge, list):
        return bool(event_edge)
    return False


def _is_comb_op(op: dict) -> bool:
    if _op_has_events(op):
        return False
    kind = str(op.get("kind", ""))
    if kind == "kSystemFunction":
        attrs = op.get("attrs") or {}
        side_effects = attrs.get("hasSideEffects")
        if isinstance(side_effects, dict):
            value = side_effects.get("v")
            return not bool(value)
        return True
    return kind in _COMB_OP_KINDS


def _attr_bool(op: dict, key: str) -> bool:
    attrs = op.get("attrs") or {}
    value = attrs.get(key)
    if isinstance(value, dict):
        return bool(value.get("v"))
    return bool(value)


def _is_dpic_call_with_return(op: dict) -> bool:
    return str(op.get("kind", "")) == "kDpicCall" and _attr_bool(op, "hasReturn")


def _is_system_task_with_return(op: dict) -> bool:
    return str(op.get("kind", "")) == "kSystemTask" and _attr_bool(op, "hasReturn")


def _is_sink_op(op: dict) -> bool:
    kind = str(op.get("kind", ""))
    if kind == "kDpicCall":
        return not _is_dpic_call_with_return(op)
    if kind == "kSystemTask":
        return not _is_system_task_with_return(op)
    return kind in _SINK_OP_KINDS


def _iter_graph_objects(json_path: Path):
    decoder = json.JSONDecoder()
    in_graphs = False
    object_level = 0
    array_level = 0
    in_string = False
    escape = False
    current: list[str] = []
    with json_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not in_graphs:
                if '"graphs": [' in line:
                    in_graphs = True
                continue
            for ch in line:
                if object_level == 0:
                    if in_string:
                        if escape:
                            escape = False
                        elif ch == "\\":
                            escape = True
                        elif ch == '"':
                            in_string = False
                        continue
                    if ch == '"':
                        in_string = True
                        continue
                    if ch == "[":
                        array_level += 1
                        continue
                    if ch == "]":
                        if array_level == 0:
                            return
                        array_level -= 1
                        if array_level == 0:
                            return
                        continue
                    if ch != "{":
                        continue
                    object_level = 1
                    current = ["{"]
                    continue

                current.append(ch)
                if in_string:
                    if escape:
                        escape = False
                    elif ch == "\\":
                        escape = True
                    elif ch == '"':
                        in_string = False
                    continue

                if ch == '"':
                    in_string = True
                    continue
                if ch == "{":
                    object_level += 1
                    continue
                if ch == "}":
                    object_level -= 1
                    if object_level == 0:
                        yield decoder.decode("".join(current))
                        current = []


def _build_partition_feature_record(graph_obj: dict, part_id: int, graph_name: str, stem: str, weight: int) -> dict:
    vals = graph_obj.get("vals") or []
    ops = graph_obj.get("ops") or []
    ports = graph_obj.get("ports") or {}
    value_by_sym = {str(v.get("sym", "")): v for v in vals}

    op_count = len(ops)
    comb_op_count = 0
    sink_op_count = 0
    source_op_count = 0
    operand_count = 0
    result_count = 0
    operand_word_count = 0
    result_word_count = 0
    fanout_count = 0
    max_op_width = 1
    op_kind_counts: dict[str, int] = {}
    width_bucket_counts = {name: 0 for name, _, _ in _WIDTH_BUCKETS}

    for value in vals:
        fanout_count += len(value.get("users") or [])

    for op in ops:
        kind = str(op.get("kind", ""))
        op_kind_counts[kind] = op_kind_counts.get(kind, 0) + 1
        if _is_comb_op(op):
            comb_op_count += 1
        if _is_sink_op(op):
            sink_op_count += 1
        if kind in _SOURCE_OP_KINDS:
            source_op_count += 1

        operands = op.get("in") or []
        results = op.get("out") or []
        operand_count += len(operands)
        result_count += len(results)

        op_width = 1
        for sym in operands:
            value = value_by_sym.get(str(sym))
            if value is None:
                continue
            width = int(value.get("w", 1) or 1)
            operand_word_count += _width_to_word_count(width)
            op_width = max(op_width, width)
        for sym in results:
            value = value_by_sym.get(str(sym))
            if value is None:
                continue
            width = int(value.get("w", 1) or 1)
            result_word_count += _width_to_word_count(width)
            op_width = max(op_width, width)
        max_op_width = max(max_op_width, op_width)
        width_bucket_counts[_width_bucket_name(op_width)] += 1

    in_ports = ports.get("in") or []
    out_ports = ports.get("out") or []
    cross_in_word_count = 0
    cross_out_word_count = 0
    for port in in_ports:
        value = value_by_sym.get(str(port.get("val", "")))
        if value is not None:
            cross_in_word_count += _width_to_word_count(int(value.get("w", 1) or 1))
    for port in out_ports:
        value = value_by_sym.get(str(port.get("val", "")))
        if value is not None:
            cross_out_word_count += _width_to_word_count(int(value.get("w", 1) or 1))

    return {
        "record_type": "partition_static_features",
        "schema_version": 1,
        "graph": graph_name,
        "stem": stem,
        "part_id": part_id,
        "part_name": f"part_{part_id}",
        "partition_graph_name": str(graph_obj.get("symbol", "")),
        "op_count": op_count,
        "comb_op_count": comb_op_count,
        "sink_op_count": sink_op_count,
        "source_op_count": source_op_count,
        "phase_a_node_count": op_count,
        "non_phase_a_op_count": 0,
        "operand_count": operand_count,
        "result_count": result_count,
        "operand_word_count": operand_word_count,
        "result_word_count": result_word_count,
        "fanout_count": fanout_count,
        "estimated_node_weight_sum": weight,
        "hyper_partition_weight": weight,
        "cross_in_value_count": len(in_ports),
        "cross_out_value_count": len(out_ports),
        "cross_in_word_count": cross_in_word_count,
        "cross_out_word_count": cross_out_word_count,
        "max_op_width": max_op_width,
        "width_bucket_counts": width_bucket_counts,
        "op_kind_counts": dict(sorted(op_kind_counts.items())),
    }


def _write_partition_features_from_final_json(
    final_json_path: Path,
    work_dir: Path,
    payload: dict,
) -> Path | None:
    graph = str(payload.get("graph", "")).strip()
    k = payload.get("partition_count_requested")
    part_stats = payload.get("partition_graph_stats")
    if not graph or k is None or not isinstance(part_stats, list) or not final_json_path.exists():
        return None

    wanted: dict[str, dict] = {}
    for part in part_stats:
        if not isinstance(part, dict):
            continue
        part_graph_name = str(part.get("graph", "")).strip()
        if not part_graph_name:
            continue
        wanted[part_graph_name] = part

    if not wanted:
        return None

    records_by_id: dict[int, dict] = {}
    stem = f"{graph}_repcut_k{k}"
    for graph_obj in _iter_graph_objects(final_json_path):
        symbol = str(graph_obj.get("symbol", "")).strip()
        part = wanted.get(symbol)
        if part is None:
            continue
        part_id = int(part.get("index", len(records_by_id)))
        weight = int(part.get("weight", 0) or 0)
        records_by_id[part_id] = _build_partition_feature_record(graph_obj, part_id, graph, stem, weight)
        if len(records_by_id) == len(wanted):
            break

    if not records_by_id:
        return None

    out_path = work_dir / f"{stem}.partition_features.jsonl"
    with out_path.open("w", encoding="utf-8") as handle:
        summary = {
            "record_type": "partition_static_feature_summary",
            "schema_version": 1,
            "graph": graph,
            "stem": stem,
            "partition_count": payload.get("partition_count_observed", len(records_by_id)),
            "cross_value_count": payload.get("cross_values_total", 0),
        }
        handle.write(json.dumps(summary, ensure_ascii=True) + "\n")
        for part_id in sorted(records_by_id):
            handle.write(json.dumps(records_by_id[part_id], ensure_ascii=True) + "\n")
    return out_path

# pass targets (edit here if top symbol changes)
TOP_MODULE_PATH = "SimTop"
REPCUT_PATH = TOP_MODULE_PATH

# repcut parameters (edit here)
REPCUT_PARTITION_COUNT = "32"
REPCUT_IMBALANCE_FACTOR = "0.015"
REPCUT_PARTITIONER = "mt-kahypar"
REPCUT_MTKAHYPAR_PRESET = "quality"
REPCUT_MTKAHYPAR_THREADS = "0"
REPCUT_KEEP_INTERMEDIATE_FILES = True

if len(sys.argv) < 4:
    raise RuntimeError(
        "usage: wolvrix_xs_repcut.py <json_in> <json_out> <work_dir> [log_level] [package_out_dir]"
    )

json_in = Path(sys.argv[1])
json_out = Path(sys.argv[2])
repcut_work_dir = Path(sys.argv[3])
log_level = sys.argv[4] if len(sys.argv) > 4 else "info"
package_out_dir = Path(sys.argv[5]) if len(sys.argv) > 5 else None

if not json_in.exists():
    raise RuntimeError(f"input json not found: {json_in}")

total_start = time.perf_counter()

start = time.perf_counter()
log(f"read_json start {json_in}")
design = wolvrix.read_json(str(json_in))
log(f"read_json done {int((time.perf_counter() - start) * 1000)}ms")

start = time.perf_counter()
log(f"pass repcut start path={REPCUT_PATH}")
repcut_work_dir.mkdir(parents=True, exist_ok=True)
_, repcut_diags = _run_repcut_with_compat(
    design,
    repcut_work_dir,
    diagnostics="info",
    log_level=log_level,
    print_diagnostics_level="info",
    raise_diagnostics_level="error",
)
log(f"pass repcut done {int((time.perf_counter() - start) * 1000)}ms")

repcut_stats = _extract_repcut_stats_diag(repcut_diags)
if repcut_stats is not None:
    feature_path = repcut_work_dir / f"{repcut_stats['graph']}_repcut_k{repcut_stats['partition_count_requested']}.partition_features.jsonl"
    if not feature_path.exists():
        fallback_path = _write_partition_features_fallback(repcut_work_dir, repcut_stats)
        if fallback_path is not None:
            log(f"repcut partition features fallback export {fallback_path}")

start = time.perf_counter()
log(f"write_json start {json_out}")
json_out.parent.mkdir(parents=True, exist_ok=True)
design.write_json(str(json_out))
log(f"write_json done {int((time.perf_counter() - start) * 1000)}ms")

if repcut_stats is not None:
    feature_path = repcut_work_dir / f"{repcut_stats['graph']}_repcut_k{repcut_stats['partition_count_requested']}.partition_features.jsonl"
    if not feature_path.exists():
        fallback_path = _write_partition_features_from_final_json(json_out, repcut_work_dir, repcut_stats)
        if fallback_path is not None:
            log(f"repcut partition features json fallback export {fallback_path}")
        else:
            log(f"repcut partition features export missing after write_json: expected {feature_path}")

start = time.perf_counter()
log("read_json start (roundtrip)")
design = wolvrix.read_json(str(json_out))
log(f"read_json done (roundtrip) {int((time.perf_counter() - start) * 1000)}ms")

start = time.perf_counter()
sv_out_arg = json_out.with_suffix(".sv")
sv_out_dir = sv_out_arg.with_suffix("") if sv_out_arg.suffix == ".sv" else sv_out_arg
log(f"write_sv start {sv_out_dir}")
design.write_sv(str(sv_out_dir), top=[TOP_MODULE_PATH], split_modules=True)
log(f"write_sv done {int((time.perf_counter() - start) * 1000)}ms")

if package_out_dir is not None:
    start = time.perf_counter()
    log(f"write_verilator_repcut_package start {package_out_dir}")
    package_out_dir.mkdir(parents=True, exist_ok=True)
    design.write_verilator_repcut_package(str(package_out_dir), top=[TOP_MODULE_PATH])
    log(f"write_verilator_repcut_package done {int((time.perf_counter() - start) * 1000)}ms")

log(f"total done {int((time.perf_counter() - total_start) * 1000)}ms")
