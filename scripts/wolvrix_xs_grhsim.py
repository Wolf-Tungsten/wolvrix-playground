#!/usr/bin/env python3

import argparse
import json
import os
import shlex
import statistics
import sys
import time
import traceback
from pathlib import Path

import wolvrix
from wolvrix.adapters.stats import StatsValue
from wolvrix import _wolvrix as _native


def parse_tokens(value: str) -> list[str]:
    if not value:
        return []
    return shlex.split(value)


def log(message: str) -> None:
    sys.stderr.write(f"[wolvrix-xs-grhsim] {message}\n")
    sys.stderr.flush()


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    return int(value.strip())


def env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    return float(value.strip())


def write_stats_json(sess: wolvrix.Session, key: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "wolvrix_xs_stats.json"
    value = sess.get(key)
    if not isinstance(value, StatsValue):
        raise TypeError(f"session key is not stats: {key}")
    value.write_json(str(out_path))
    log(f"stats json written {out_path}")


def summarize_compute_ops_from_post_stats(post_stats_json: Path, top_name: str) -> dict[str, int] | None:
    if not post_stats_json.exists():
        return None
    data = json.loads(post_stats_json.read_text(encoding="utf-8"))
    for graph in data.get("graphs", []):
        if graph.get("symbol") != top_name:
            continue
        ops = graph.get("ops")
        if ops is None:
            ops = graph.get("operations", [])
        source_kinds = {"kConstant", "kRegisterReadPort", "kLatchReadPort", "kArrayReadAllPort"}
        sink_kinds = {"kRegisterWritePort", "kLatchWritePort", "kMemoryWritePort", "kMemoryFillPort", "kArrayWritePort"}
        decl_kinds = {"kRegister", "kMemory", "kLatch", "kDpicImport"}
        hier_kinds = {"kInstance", "kBlackbox", "kXMRRead", "kXMRWrite"}
        array_kinds = {
            "kArrayMux",
            "kArrayReduceOr",
            "kArrayReduceAnd",
            "kArrayReduceXor",
            "kArrayBroadcast",
            "kArrayLaneConst",
            "kArrayOnehot",
            "kArrayReduceLanesOr",
            "kArrayReduceLanesAnd",
            "kArrayReduceLanesXor",
        }
        total_ops = len(ops)
        source_ops = sum(1 for op in ops if op.get("kind") in source_kinds)
        sink_ops = sum(1 for op in ops if op.get("kind") in sink_kinds)
        declaration_ops = sum(1 for op in ops if op.get("kind") in decl_kinds)
        hierarchy_ops = sum(1 for op in ops if op.get("kind") in hier_kinds)
        array_ops = sum(1 for op in ops if op.get("kind") in array_kinds)
        compute_ops = total_ops - source_ops - sink_ops - declaration_ops - hierarchy_ops - array_ops
        return {
            "top_total_ops": total_ops,
            "top_compute_ops": compute_ops,
            "top_source_ops": source_ops,
            "top_sink_ops": sink_ops,
            "top_declaration_ops": declaration_ops,
            "top_hierarchy_ops": hierarchy_ops,
            "top_array_ops": array_ops,
            "top_values": len(graph.get("vals", [])),
        }
    return None


def write_design_json(sess: wolvrix.Session, design: str, top_name: str, out_path: Path, label: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    log(f"{label} start {out_path}")
    sess.store_json(design=design, output=str(out_path), top=[top_name])
    log(f"{label} done {int((time.perf_counter() - start) * 1000)}ms")

def has_error_diagnostic(diags: list[dict]) -> bool:
    return any(str(item.get("kind", "")).lower() == "error" for item in diags)


def require_ok(diags: list[dict], label: str) -> None:
    if has_error_diagnostic(diags):
        raise RuntimeError(f"{label} failed")


def percentile(sorted_values: list[int], num: int, den: int) -> int:
    if not sorted_values:
        return 0
    idx = (len(sorted_values) - 1) * num // den
    return sorted_values[idx]


def summarize_sizes(values: list[int]) -> dict[str, int | float]:
    values = sorted(values)
    return {
        "min": values[0] if values else 0,
        "mean": statistics.fmean(values) if values else 0.0,
        "median": statistics.median(values) if values else 0,
        "p90": percentile(values, 90, 100),
        "p99": percentile(values, 99, 100),
        "max": values[-1] if values else 0,
    }


def supernode_kind_code(value) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    if text == "compute":
        return 0
    if text == "commit":
        return 1
    return int(text)


def write_supernode_stats(sess: wolvrix.Session, key: str, out_dir: Path) -> None:
    key_prefix = key.rsplit("supernode_to_ops", 1)[0]
    summary_key = key_prefix + "summary_stats"
    try:
        summary_text = _native.session_export(sess._capsule, key=summary_key, view="text")
    except Exception:
        summary_text = None

    raw = _native.session_export(sess._capsule, key=key, view="python")
    supernode_to_ops = [list(map(int, ops)) for ops in raw]
    dag_key = key.rsplit("supernode_to_ops", 1)[0] + "dag"
    dag_raw = _native.session_export(sess._capsule, key=dag_key, view="python")
    dag = [list(map(int, succs)) for succs in dag_raw]
    supernode_kind_key = key.rsplit("supernode_to_ops", 1)[0] + "supernode_kind"
    supernode_kind_raw = _native.session_export(sess._capsule, key=supernode_kind_key, view="python")
    supernode_kinds = [supernode_kind_code(kind) for kind in supernode_kind_raw]
    compute_sizes = [len(ops) for ops, kind in zip(supernode_to_ops, supernode_kinds) if kind == 0]
    commit_sizes = [len(ops) for ops, kind in zip(supernode_to_ops, supernode_kinds) if kind == 1]
    if summary_text:
        summary = json.loads(summary_text)
        sizes = sorted(len(ops) for ops in supernode_to_ops)
        out_degrees = sorted(len(succs) for succs in dag)
        summary["ops_per_supernode"] = summarize_sizes(sizes)
        summary["compute_ops_per_supernode"] = summarize_sizes(compute_sizes)
        summary["commit_ops_per_supernode"] = summarize_sizes(commit_sizes)
        summary["out_degree_per_supernode"] = summarize_sizes(out_degrees)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "activity_schedule_supernode_stats.json"
        out_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        log(
            "activity-schedule supernode stats "
            f"supernodes={summary['supernodes']} "
            f"compute_supernodes={summary['compute_supernodes']} "
            f"commit_supernodes={summary['commit_supernodes']} "
            f"dag_edges={summary['dag_edges']} "
            f"boundary_values={summary['boundary_values']} "
            f"boundary_activation_edges={summary['boundary_activation_edges']} "
            f"compute_compute_value_pairs={summary['compute_compute_value_pairs']} "
            f"compute_commit_value_pairs={summary['compute_commit_value_pairs']} "
            f"state_read_activation_edges={summary.get('state_read_activation_edges', 0)} "
            f"memory_read_activation_edges={summary.get('memory_read_activation_edges', 0)} "
            f"constant_activation_edges={summary.get('constant_activation_edges', 0)} "
            f"other_compute_activation_edges={summary.get('other_compute_activation_edges', 0)} "
            f"ops_mean={summary['ops_per_supernode']['mean']:.3f} "
            f"ops_median={summary['ops_per_supernode']['median']} "
            f"ops_p90={summary['ops_per_supernode']['p90']} "
            f"ops_p99={summary['ops_per_supernode']['p99']} "
            f"ops_max={summary['ops_per_supernode']['max']} "
            f"compute_ops_p99={summary['compute_ops_per_supernode']['p99']} "
            f"compute_ops_max={summary['compute_ops_per_supernode']['max']} "
            f"commit_ops_max={summary['commit_ops_per_supernode']['max']} "
            f"outdeg_mean={summary['out_degree_per_supernode']['mean']:.3f} "
            f"outdeg_p99={summary['out_degree_per_supernode']['p99']} "
            f"outdeg_max={summary['out_degree_per_supernode']['max']}"
        )
        log(f"activity-schedule supernode stats written {out_path}")
        return

    value_fanout_key = key.rsplit("supernode_to_ops", 1)[0] + "value_fanout"
    value_fanout_raw = _native.session_export(sess._capsule, key=value_fanout_key, view="python")
    value_fanout = [list(map(int, fanout)) for fanout in value_fanout_raw]
    sizes = sorted(len(ops) for ops in supernode_to_ops)
    edge_count = sum(len(succs) for succs in dag)
    out_degrees = sorted(len(succs) for succs in dag)
    compute_supernodes = sum(1 for kind in supernode_kinds if kind == 0)
    commit_supernodes = sum(1 for kind in supernode_kinds if kind == 1)
    boundary_values = 0
    boundary_activation_edges = 0
    compute_compute_value_pairs = 0
    compute_commit_value_pairs = 0
    state_read_activation_edges = 0
    memory_read_activation_edges = 0
    constant_activation_edges = 0
    other_compute_activation_edges = 0
    for fanout in value_fanout:
        if not fanout:
            continue
        boundary_values += 1
        boundary_activation_edges += len(fanout)
        for target_supernode in fanout:
            if 0 <= target_supernode < len(supernode_kinds):
                if supernode_kinds[target_supernode] == 0:
                    compute_compute_value_pairs += 1
                elif supernode_kinds[target_supernode] == 1:
                    compute_commit_value_pairs += 1
    if sizes:
        summary = {
            "supernodes": len(sizes),
            "compute_supernodes": compute_supernodes,
            "commit_supernodes": commit_supernodes,
            "ops_per_supernode": {
                "min": sizes[0],
                "mean": statistics.fmean(sizes),
                "median": statistics.median(sizes),
                "p90": percentile(sizes, 90, 100),
                "p99": percentile(sizes, 99, 100),
                "max": sizes[-1],
            },
            "compute_ops_per_supernode": summarize_sizes(compute_sizes),
            "commit_ops_per_supernode": summarize_sizes(commit_sizes),
            "dag_edges": edge_count,
            "boundary_values": boundary_values,
            "boundary_activation_edges": boundary_activation_edges,
            "compute_compute_value_pairs": compute_compute_value_pairs,
            "compute_commit_value_pairs": compute_commit_value_pairs,
            "state_read_activation_edges": state_read_activation_edges,
            "memory_read_activation_edges": memory_read_activation_edges,
            "constant_activation_edges": constant_activation_edges,
            "other_compute_activation_edges": other_compute_activation_edges,
            "out_degree_per_supernode": {
                "min": out_degrees[0],
                "mean": statistics.fmean(out_degrees),
                "median": statistics.median(out_degrees),
                "p90": percentile(out_degrees, 90, 100),
                "p99": percentile(out_degrees, 99, 100),
                "max": out_degrees[-1],
            },
        }
    else:
        summary = {
            "supernodes": 0,
            "compute_supernodes": 0,
            "commit_supernodes": 0,
            "ops_per_supernode": {
                "min": 0,
                "mean": 0.0,
                "median": 0,
                "p90": 0,
                "p99": 0,
                "max": 0,
            },
            "compute_ops_per_supernode": summarize_sizes([]),
            "commit_ops_per_supernode": summarize_sizes([]),
            "dag_edges": 0,
            "boundary_values": 0,
            "boundary_activation_edges": 0,
            "compute_compute_value_pairs": 0,
            "compute_commit_value_pairs": 0,
            "state_read_activation_edges": 0,
            "memory_read_activation_edges": 0,
            "constant_activation_edges": 0,
            "other_compute_activation_edges": 0,
            "out_degree_per_supernode": {
                "min": 0,
                "mean": 0.0,
                "median": 0,
                "p90": 0,
                "p99": 0,
                "max": 0,
            },
        }
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "activity_schedule_supernode_stats.json"
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    log(
        "activity-schedule supernode stats "
        f"supernodes={summary['supernodes']} "
        f"compute_supernodes={summary['compute_supernodes']} "
        f"commit_supernodes={summary['commit_supernodes']} "
        f"dag_edges={summary['dag_edges']} "
        f"boundary_values={summary['boundary_values']} "
        f"boundary_activation_edges={summary['boundary_activation_edges']} "
        f"compute_compute_value_pairs={summary['compute_compute_value_pairs']} "
        f"compute_commit_value_pairs={summary['compute_commit_value_pairs']} "
        f"state_read_activation_edges={summary.get('state_read_activation_edges', 0)} "
        f"memory_read_activation_edges={summary.get('memory_read_activation_edges', 0)} "
        f"constant_activation_edges={summary.get('constant_activation_edges', 0)} "
        f"other_compute_activation_edges={summary.get('other_compute_activation_edges', 0)} "
        f"ops_mean={summary['ops_per_supernode']['mean']:.3f} "
        f"ops_median={summary['ops_per_supernode']['median']} "
        f"ops_p90={summary['ops_per_supernode']['p90']} "
        f"ops_p99={summary['ops_per_supernode']['p99']} "
        f"ops_max={summary['ops_per_supernode']['max']} "
        f"compute_ops_p99={summary['compute_ops_per_supernode']['p99']} "
        f"compute_ops_max={summary['compute_ops_per_supernode']['max']} "
        f"commit_ops_max={summary['commit_ops_per_supernode']['max']} "
        f"outdeg_mean={summary['out_degree_per_supernode']['mean']:.3f} "
        f"outdeg_p99={summary['out_degree_per_supernode']['p99']} "
        f"outdeg_max={summary['out_degree_per_supernode']['max']}"
    )
    log(f"activity-schedule supernode stats written {out_path}")


def write_comb_lane_pack_report(sess: wolvrix.Session, key: str, out_path: Path) -> None:
    raw = _native.session_export(sess._capsule, key=key, view="python")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8")
    log(f"comb-lane-pack report written {out_path} groups={len(raw)}")


# GSim's canonical writer keeps metadata before graphs and tops at the end.
GSIM_PRECOARSEN_HEADER_LIMIT = 4 * 1024 * 1024
GSIM_PRECOARSEN_TAIL_LIMIT = 1024 * 1024
GSIM_PRECOARSEN_GRAPHS_MARKER = '\n  "graphs": ['
GSIM_PRECOARSEN_GRAPH_SYMBOL_MARKER = '\n    {\n      "symbol": '
GSIM_PRECOARSEN_TOPS_MARKER = b'\n  "tops": '
GSIM_EXECUTABLE_GRH_FORMAT = "gsim.executable-grh.v2"
GSIM_EXECUTABLE_GRH_STAGE = "pre-coarsen"
GSIM_EXECUTABLE_GRH_BOUNDARY = "PreCoarsen"
GSIM_EXECUTABLE_GRH_PROFILES = {
    "full-fidelity",
    "xiangshan-gsim-coremark-stub",
}
GSIM_EXECUTABLE_GRH_STUB_PROFILE = "xiangshan-gsim-coremark-stub"


def read_gsim_design_envelope(
    path: Path,
    artifact_name: str,
) -> tuple[dict, str, list[str]]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            header = stream.read(GSIM_PRECOARSEN_HEADER_LIMIT)
        file_size = path.stat().st_size
        with path.open("rb") as stream:
            stream.seek(max(0, file_size - GSIM_PRECOARSEN_TAIL_LIMIT))
            tail = stream.read()
    except (OSError, UnicodeError) as ex:
        raise RuntimeError(f"failed to read {artifact_name} {path}: {ex}") from ex

    graphs_pos = header.find(GSIM_PRECOARSEN_GRAPHS_MARKER)
    if graphs_pos < 0:
        raise RuntimeError(
            f"{artifact_name} header is missing its graphs array or exceeds "
            f"{GSIM_PRECOARSEN_HEADER_LIMIT} bytes"
        )
    root_header = header[:graphs_pos].rstrip()
    if not root_header.endswith(","):
        raise RuntimeError(f"{artifact_name} header is malformed before graphs")

    try:
        data = json.loads(root_header[:-1] + "\n}")
        symbol_pos = header.find(GSIM_PRECOARSEN_GRAPH_SYMBOL_MARKER, graphs_pos)
        if symbol_pos < 0:
            raise RuntimeError(f"{artifact_name} is missing its first graph symbol")
        symbol_pos += len(GSIM_PRECOARSEN_GRAPH_SYMBOL_MARKER)
        graph_symbol, _ = json.JSONDecoder().raw_decode(header, symbol_pos)
        tops_pos = tail.rfind(GSIM_PRECOARSEN_TOPS_MARKER)
        if tops_pos < 0:
            raise RuntimeError(f"{artifact_name} is missing its tops array")
        tops_pos += len(GSIM_PRECOARSEN_TOPS_MARKER)
        tops, _ = json.JSONDecoder().raw_decode(tail[tops_pos:].decode("utf-8"))
    except (json.JSONDecodeError, UnicodeError) as ex:
        raise RuntimeError(f"invalid {artifact_name} envelope {path}: {ex}") from ex

    if not isinstance(data, dict):
        raise RuntimeError(f"{artifact_name} root must be an object")
    if not isinstance(graph_symbol, str) or not graph_symbol:
        raise RuntimeError(f"{artifact_name} graph symbol must be a non-empty string")
    if not isinstance(tops, list) or not all(isinstance(top, str) for top in tops):
        raise RuntimeError(f"{artifact_name} tops must be an array of strings")
    return data, graph_symbol, tops


def read_gsim_precoarsen_projection_envelope(path: Path) -> tuple[dict, str, list[str]]:
    return read_gsim_design_envelope(path, "GSim pre-coarsen projection")


def validate_gsim_precoarsen_projection(path: Path, top_name: str) -> None:
    data, graph_symbol, tops = read_gsim_precoarsen_projection_envelope(path)

    if data.get("format") != "gsim.precoarsen-graph.v1":
        raise RuntimeError(
            "GSim pre-coarsen projection has unsupported format; "
            "expected gsim.precoarsen-graph.v1"
        )
    if data.get("stage") != "pre-coarsen":
        raise RuntimeError("GSim pre-coarsen projection must be exported at stage pre-coarsen")
    if data.get("analysisOnly") is not True:
        raise RuntimeError("GSim pre-coarsen projection must declare analysisOnly=true")

    gsim = data.get("gsim")
    if not isinstance(gsim, dict):
        raise RuntimeError("GSim pre-coarsen projection is missing its gsim metadata")
    if (
        gsim.get("format") != "gsim.precoarsen-graph.v1"
        or gsim.get("stage") != "pre-coarsen"
        or gsim.get("boundary") != "PreCoarsen"
        or gsim.get("analysisOnly") is not True
    ):
        raise RuntimeError("GSim pre-coarsen projection has inconsistent gsim metadata")

    if graph_symbol != top_name:
        raise RuntimeError(
            f"GSim pre-coarsen projection does not contain requested top graph: {top_name}"
        )
    if top_name not in tops:
        raise RuntimeError(
            f"GSim pre-coarsen projection does not mark requested graph as top: {top_name}"
        )


def validate_gsim_executable_grh(path: Path, top_name: str) -> str:
    data, graph_symbol, tops = read_gsim_design_envelope(path, "GSim executable GRH")

    if data.get("format") != GSIM_EXECUTABLE_GRH_FORMAT:
        raise RuntimeError(
            f"GSim executable GRH has unsupported format; expected {GSIM_EXECUTABLE_GRH_FORMAT}"
        )
    if data.get("stage") != GSIM_EXECUTABLE_GRH_STAGE:
        raise RuntimeError(
            f"GSim executable GRH must be exported at stage {GSIM_EXECUTABLE_GRH_STAGE}"
        )
    if data.get("boundary") != GSIM_EXECUTABLE_GRH_BOUNDARY:
        raise RuntimeError(
            f"GSim executable GRH must declare boundary {GSIM_EXECUTABLE_GRH_BOUNDARY}"
        )
    if data.get("analysisOnly") is not False:
        raise RuntimeError("GSim executable GRH must declare analysisOnly=false")

    execution_profile = data.get("executionProfile")
    if (
        not isinstance(execution_profile, str)
        or execution_profile not in GSIM_EXECUTABLE_GRH_PROFILES
    ):
        allowed_profiles = ", ".join(sorted(GSIM_EXECUTABLE_GRH_PROFILES))
        raise RuntimeError(
            "GSim executable GRH must declare an allowed executionProfile; "
            f"expected one of: {allowed_profiles}"
        )

    gsim = data.get("gsim")
    if not isinstance(gsim, dict):
        raise RuntimeError("GSim executable GRH is missing its gsim metadata")
    if (
        gsim.get("format") != data["format"]
        or gsim.get("stage") != data["stage"]
        or gsim.get("boundary") != GSIM_EXECUTABLE_GRH_BOUNDARY
        or gsim.get("analysisOnly") is not data["analysisOnly"]
        or gsim.get("executionProfile") != execution_profile
    ):
        raise RuntimeError(
            "GSim executable GRH has inconsistent gsim "
            "format/stage/boundary/analysisOnly/executionProfile metadata"
        )

    if graph_symbol != top_name:
        raise RuntimeError(
            f"GSim executable GRH first graph is {graph_symbol!r}, expected requested top {top_name!r}"
        )
    if top_name not in tops:
        raise RuntimeError(f"GSim executable GRH does not mark requested graph as top: {top_name}")
    return execution_profile


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("filelist")
    parser.add_argument("top")
    parser.add_argument("cpp_out_dir")
    parser.add_argument("json_out")
    parser.add_argument("read_args_file")
    parser.add_argument("log_level", nargs="?", default="info")
    parser.add_argument("--waveform", choices=["off", "declared-symbols"], default="off")
    parser.add_argument("--perf", choices=["off", "eval"], default="off")
    parser.add_argument("--import-gsim-precoarsen", default=None)
    parser.add_argument("--import-gsim-executable-grh", default=None)
    args = parser.parse_args()

    filelist = args.filelist
    top_name = args.top
    cpp_out_dir = Path(args.cpp_out_dir).resolve()
    json_out = args.json_out
    read_args_file = args.read_args_file
    log_level = args.log_level
    gsim_precoarsen_import = (
        args.import_gsim_precoarsen
        or os.environ.get("WOLVRIX_XS_GRHSIM_IMPORT_GSIM_PRECOARSEN", "")
    ).strip()
    gsim_precoarsen_path = Path(gsim_precoarsen_import).resolve() if gsim_precoarsen_import else None
    gsim_executable_grh_import = (
        args.import_gsim_executable_grh
        or os.environ.get("WOLVRIX_XS_GRHSIM_IMPORT_GSIM_EXECUTABLE_GRH", "")
    ).strip()
    gsim_executable_grh_path = (
        Path(gsim_executable_grh_import).resolve() if gsim_executable_grh_import else None
    )
    gsim_executable_grh_profile: str | None = None
    gsim_import_path = gsim_precoarsen_path or gsim_executable_grh_path
    post_stats_json = Path(
        os.environ.get(
            "WOLVRIX_XS_GRHSIM_POST_STATS_JSON",
            str(cpp_out_dir / "wolvrix_xs_post_stats.json"),
        )
    ).resolve()
    pre_reg_to_mem_json = Path(
        os.environ.get(
            "WOLVRIX_XS_GRHSIM_PRE_REG_TO_MEM_JSON",
            str(cpp_out_dir / "wolvrix_xs_pre_reg_to_mem.json"),
        )
    ).resolve()
    resume_from_stats_json = env_flag("WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON")
    resume_from_pre_reg_to_mem_json = env_flag("WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON")
    enable_stats = env_flag("WOLVRIX_XS_GRHSIM_ENABLE_STATS", default=False)
    enable_mem_to_reg = env_flag("WOLVRIX_XS_GRHSIM_ENABLE_MEM_TO_REG", default=False)
    mem_to_reg_row_limit = env_int("WOLVRIX_XS_GRHSIM_MEM_TO_REG_ROW_LIMIT", 64)
    max_op_in_compute_supernode = env_int("WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE", 108)
    max_op_in_compute_node = env_int("WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_NODE", max_op_in_compute_supernode)
    split_oversize_compute_nodes = env_flag("WOLVRIX_XS_GRHSIM_SPLIT_OVERSIZE_COMPUTE_NODES", default=False)
    split_oversize_compute_node_max_ops = env_int(
        "WOLVRIX_XS_GRHSIM_SPLIT_OVERSIZE_COMPUTE_NODE_MAX_OPS",
        max_op_in_compute_supernode,
    )
    max_op_in_commit_supernode = env_int("WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE", 4096)
    commit_guard_event_buckets = env_flag("WOLVRIX_XS_GRHSIM_COMMIT_GUARD_EVENT_BUCKETS", default=True)
    sched_batch_max_ops = env_int("WOLVRIX_XS_GRHSIM_SCHED_BATCH_MAX_OPS", 2048)
    sched_batch_max_estimated_lines = env_int("WOLVRIX_XS_GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES", 8192)
    sched_batch_target_count = env_int("WOLVRIX_XS_GRHSIM_SCHED_BATCH_TARGET_COUNT", 256)
    sched_batches_per_cpp = env_int("WOLVRIX_XS_GRHSIM_SCHED_BATCHES_PER_CPP", 1)
    emit_parallelism = env_int("WOLVRIX_XS_GRHSIM_EMIT_PARALLELISM", 4)
    storage_ref_aliases_env_was_set = "WOLVRIX_GRHSIM_STORAGE_REF_ALIASES" in os.environ
    if not storage_ref_aliases_env_was_set:
        os.environ["WOLVRIX_GRHSIM_STORAGE_REF_ALIASES"] = "0"
    storage_ref_aliases_setting = os.environ["WOLVRIX_GRHSIM_STORAGE_REF_ALIASES"]
    stop_after_pre_sched = env_flag("WOLVRIX_XS_GRHSIM_STOP_AFTER_PRE_SCHED", default=False)
    stop_after_activity_schedule = env_flag("WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE", default=False)
    export_compute_dag = os.environ.get("WOLVRIX_XS_GRHSIM_EXPORT_COMPUTE_DAG", "").strip()
    export_compute_dag_path = Path(export_compute_dag).resolve() if export_compute_dag else None
    simplify_keep_declared_symbols = env_flag("WOLVRIX_XS_GRHSIM_SIMPLIFY_KEEP_DECLARED_SYMBOLS", default=False)
    skip_comb_lane_pack = env_flag("WOLVRIX_XS_GRHSIM_SKIP_COMB_LANE_PACK", default=False)
    lane_aggregate = env_flag("WOLVRIX_XS_GRHSIM_LANE_AGGREGATE", default=True)
    lane_aggregate_min_lanes = env_int("WOLVRIX_XS_GRHSIM_LANE_AGGREGATE_MIN_LANES", 4)
    lane_aggregate_array = env_flag("WOLVRIX_XS_GRHSIM_LANE_AGGREGATE_ARRAY", default=True)
    comb_lane_pack_array = env_flag("WOLVRIX_XS_GRHSIM_COMB_LANE_PACK_ARRAY", default=True)
    reg_to_mem_intent = env_flag("WOLVRIX_XS_GRHSIM_REG_TO_MEM_INTENT", default=True)
    reg_to_mem_ordered_writes = env_flag(
        "WOLVRIX_XS_GRHSIM_REG_TO_MEM_ORDERED_WRITES",
        default=True,
    )
    reg_to_mem_decoded_write_storage = env_flag(
        "WOLVRIX_XS_GRHSIM_REG_TO_MEM_DECODED_WRITE_STORAGE",
        default=True,
    )
    post_reg2mem_simplify = env_flag("WOLVRIX_XS_GRHSIM_POST_REG2MEM_SIMPLIFY", default=True)
    logic_normalize = env_flag("WOLVRIX_XS_GRHSIM_LOGIC_NORMALIZE", default=False)
    declared_value_compute_node_boundary = env_flag(
        "WOLVRIX_XS_GRHSIM_DECLARED_VALUE_COMPUTE_NODE_BOUNDARY",
        default=False,
    )
    final_topo_policy = os.environ.get(
        "WOLVRIX_XS_GRHSIM_FINAL_TOPO_POLICY",
        "level-id",
    ).strip()
    comb_lane_pack_report = os.environ.get(
        "WOLVRIX_XS_GRHSIM_COMB_LANE_PACK_REPORT",
        str(cpp_out_dir.parent / "comb_lane_pack_report_xs.json"),
    )

    total_start = time.perf_counter()
    if resume_from_stats_json and resume_from_pre_reg_to_mem_json:
        raise RuntimeError(
            "choose only one resume point: "
            "WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON or "
            "WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON"
        )
    if gsim_precoarsen_path is not None and gsim_executable_grh_path is not None:
        raise RuntimeError(
            "choose only one GSim import: --import-gsim-precoarsen or "
            "--import-gsim-executable-grh"
        )
    if gsim_precoarsen_path is not None:
        if resume_from_stats_json or resume_from_pre_reg_to_mem_json:
            raise RuntimeError(
                "GSim pre-coarsen import cannot be combined with an existing GrhSIM resume point"
            )
        if stop_after_pre_sched:
            raise RuntimeError("GSim pre-coarsen import requires activity-schedule to run")
        if not stop_after_activity_schedule:
            raise RuntimeError(
                "GSim pre-coarsen import is analysis-only; "
                "set WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE=1"
            )
        if not gsim_precoarsen_path.is_file():
            raise RuntimeError(f"GSim pre-coarsen projection not found: {gsim_precoarsen_path}")
        validate_gsim_precoarsen_projection(gsim_precoarsen_path, top_name)
    if gsim_executable_grh_path is not None:
        if resume_from_stats_json or resume_from_pre_reg_to_mem_json:
            raise RuntimeError(
                "GSim executable GRH import cannot be combined with an existing GrhSIM resume point"
            )
        if stop_after_pre_sched:
            raise RuntimeError("GSim executable GRH import requires activity-schedule to run")
        if not gsim_executable_grh_path.is_file():
            raise RuntimeError(f"GSim executable GRH not found: {gsim_executable_grh_path}")
        gsim_executable_grh_profile = validate_gsim_executable_grh(
            gsim_executable_grh_path,
            top_name,
        )
        log(f"GSim executable GRH execution profile={gsim_executable_grh_profile}")
        if gsim_executable_grh_profile == GSIM_EXECUTABLE_GRH_STUB_PROFILE:
            log(
                "WARNING: explicit xiangshan-gsim-coremark-stub profile selected; "
                "SimJTAG and PrintCommitIDModule use compatibility stubs"
            )

    config_message = (
        "activity-schedule max_op_in_compute_supernode="
        f"{max_op_in_compute_supernode} "
        f"max_op_in_compute_node={max_op_in_compute_node} "
        f"split_oversize_compute_nodes={split_oversize_compute_nodes} "
        f"split_oversize_compute_node_max_ops={split_oversize_compute_node_max_ops} "
        f"max_op_in_commit_supernode={max_op_in_commit_supernode} "
        f"commit_guard_event_buckets={commit_guard_event_buckets} "
        f"sched_batch_max_ops={sched_batch_max_ops} "
        f"sched_batch_max_estimated_lines={sched_batch_max_estimated_lines} "
        f"sched_batch_target_count={sched_batch_target_count} "
        f"sched_batches_per_cpp={sched_batches_per_cpp} "
        f"emit_parallelism={emit_parallelism} "
        f"storage_ref_aliases={storage_ref_aliases_setting}"
        f"{'' if storage_ref_aliases_env_was_set else '(xs_default)'} "
        f"export_compute_dag={export_compute_dag_path if export_compute_dag_path is not None else 'off'} "
        f"waveform={args.waveform} perf={args.perf} "
        f"simplify_keep_declared_symbols={simplify_keep_declared_symbols} "
        f"skip_comb_lane_pack={skip_comb_lane_pack} "
        f"pre_reg_to_mem_json={pre_reg_to_mem_json} "
        f"resume_from_pre_reg_to_mem_json={resume_from_pre_reg_to_mem_json} "
        f"enable_stats={enable_stats} "
        f"post_stats_json={post_stats_json} "
        f"resume_from_stats_json={resume_from_stats_json} "
        f"gsim_precoarsen_import={gsim_precoarsen_path if gsim_precoarsen_path is not None else 'off'} "
        "gsim_executable_grh_import="
        f"{gsim_executable_grh_path if gsim_executable_grh_path is not None else 'off'} "
        "gsim_executable_grh_profile="
        f"{gsim_executable_grh_profile if gsim_executable_grh_profile is not None else 'off'} "
        f"reg_to_mem_intent={reg_to_mem_intent} "
        f"reg_to_mem_ordered_writes={reg_to_mem_ordered_writes} "
        f"reg_to_mem_decoded_write_storage={reg_to_mem_decoded_write_storage} "
        f"post_reg2mem_simplify={post_reg2mem_simplify} "
        f"logic_normalize={logic_normalize} "
        f"declared_value_compute_node_boundary={declared_value_compute_node_boundary} "
        f"final_topo_policy={final_topo_policy}"
    )

    read_args: list[str] = ["-f", filelist, "--top", top_name]

    if gsim_import_path is None and read_args_file:
        path = Path(read_args_file)
        if not path.exists():
            raise RuntimeError(f"read args file not found: {read_args_file}")
        for line in path.read_text(encoding="utf-8").splitlines():
            token = line.strip()
            if token:
                read_args.extend(parse_tokens(token))

    cpp_out_dir.mkdir(parents=True, exist_ok=True)

    with wolvrix.Session() as sess:
        sess.log_level = log_level
        sess.diagnostics_raise_min_level = "none"
        pre_sched_pipeline: list[tuple[str, dict]] = [
            ("xmr-resolve", {}),
            ("memory-read-retime", {}),
            ("multidriven-guard", {}),
            ("blackbox-guard", {}),
            ("latch-transparent-read", {}),
            ("hier-flatten", {}),
            ("comb-loop-elim", {}),
        ]
        if logic_normalize:
            pre_sched_pipeline.append(("logic-normalize", {}))
        pre_sched_pipeline += [
            ("simplify", {"semantics": "2state"}),
            ("simplify", {"semantics": "2state"}),
            ("memory-init-check", {}),
        ]
        reg_to_mem_kwargs: dict = {}
        if not reg_to_mem_intent:
            reg_to_mem_kwargs["intent"] = False
        reg_to_mem_kwargs["ordered_writes"] = reg_to_mem_ordered_writes
        reg_to_mem_kwargs["decoded_write_storage"] = reg_to_mem_decoded_write_storage
        reg_to_mem_pipeline: list[tuple[str, dict]] = [("reg-to-mem", reg_to_mem_kwargs)]
        if lane_aggregate:
            # lane-aggregate 处理 reg-to-mem 拒绝的 lane 组（v4 的 901,408 就是在
            # post-reg2mem 图上统计的）；必须在 reg-to-mem 之后，否则会抢走
            # reg-to-mem 本可转成 kMemory 的组（宽寄存器比 memory op 更贵）。
            lane_aggregate_kwargs: dict = {"min_lanes": lane_aggregate_min_lanes,
                                           "keep_declared_symbols": False}
            if lane_aggregate_array:
                # 数组语义产出（NO0017 设计）：kMemory + kArray* 形态，
                # 打包/守卫开销移出 compute 口径；默认 wide 不变。
                lane_aggregate_kwargs["output_mode"] = "array"
            reg_to_mem_pipeline.append(
                ("lane-aggregate", lane_aggregate_kwargs)
            )
            log(f"lane-aggregate enabled min_lanes={lane_aggregate_min_lanes}"
                f" output_mode={'array' if lane_aggregate_array else 'wide'}")
        if post_reg2mem_simplify:
            reg_to_mem_pipeline.append(("simplify", {"semantics": "2state"}))
        if enable_stats:
            reg_to_mem_pipeline.append(("stats", {"out_stats": "stats.main"}))
        if not skip_comb_lane_pack:
            comb_lane_pack_kwargs: dict = {
                "enable_declared_roots": False,
                "out_comb_lane_pack_report": "comb-lane-pack.reports",
            }
            if comb_lane_pack_array:
                # mux 打包产 kArrayMux/kArrayBroadcast（数组语义，compute 口径外）
                comb_lane_pack_kwargs["output_mode"] = "array"
            pre_sched_pipeline.insert(
                6,
                (
                    "comb-lane-pack",
                    comb_lane_pack_kwargs,
                ),
            )
        else:
            log("comb-lane-pack disabled for this run")
        if enable_mem_to_reg:
            pre_sched_pipeline.insert(2, ("mem-to-reg", {"row_limit": mem_to_reg_row_limit}))
            log(f"mem-to-reg enabled row_limit={mem_to_reg_row_limit}")
        else:
            log("mem-to-reg disabled for GrhSIM flow")
        post_sched_pipeline: list[tuple[str, dict]] = [
            (
                "activity-schedule",
                {
                    "path": top_name,
                    "max_op_in_compute_supernode": max_op_in_compute_supernode,
                    "max_op_in_compute_node": max_op_in_compute_node,
                    "split_oversize_compute_nodes": split_oversize_compute_nodes,
                    "split_oversize_compute_node_max_ops": split_oversize_compute_node_max_ops,
                    "max_op_in_commit_supernode": max_op_in_commit_supernode,
                    "commit_guard_event_buckets": commit_guard_event_buckets,
                    "declared_value_compute_node_boundary": declared_value_compute_node_boundary,
                    "final_topo_policy": final_topo_policy,
                },
            ),
        ]
        if export_compute_dag_path is not None:
            post_sched_pipeline[0][1]["export_compute_dag"] = str(export_compute_dag_path)
        log(config_message)

        if gsim_precoarsen_path is not None:
            start = time.perf_counter()
            log(f"read_gsim_precoarsen_json start {gsim_precoarsen_path}")
            diags = sess.read_json_file(str(gsim_precoarsen_path), out_design="design.main")
            require_ok(diags, "read_gsim_precoarsen_json")
            log(f"read_gsim_precoarsen_json done {int((time.perf_counter() - start) * 1000)}ms")
            log("GSim pre-coarsen import skips reg-to-mem and stats before activity-schedule")
        elif gsim_executable_grh_path is not None:
            start = time.perf_counter()
            log(f"read_gsim_executable_grh start {gsim_executable_grh_path}")
            diags = sess.read_json_file(str(gsim_executable_grh_path), out_design="design.main")
            require_ok(diags, "read_gsim_executable_grh")
            log(f"read_gsim_executable_grh done {int((time.perf_counter() - start) * 1000)}ms")
            log(
                "GSim executable GRH import skips pre-schedule normalization, "
                "reg-to-mem, and stats"
            )
        elif resume_from_stats_json:
            if not post_stats_json.exists():
                raise RuntimeError(f"post-stats json not found: {post_stats_json}")
            start = time.perf_counter()
            log(f"read_json_file start {post_stats_json}")
            diags = sess.read_json_file(str(post_stats_json), out_design="design.main")
            require_ok(diags, "read_json_file")
            log(f"read_json_file done {int((time.perf_counter() - start) * 1000)}ms")
        else:
            if resume_from_pre_reg_to_mem_json:
                if not pre_reg_to_mem_json.exists():
                    raise RuntimeError(f"pre-reg-to-mem json not found: {pre_reg_to_mem_json}")
                start = time.perf_counter()
                log(f"read_json_file pre-reg-to-mem start {pre_reg_to_mem_json}")
                diags = sess.read_json_file(str(pre_reg_to_mem_json), out_design="design.main")
                require_ok(diags, "read_json_file pre-reg-to-mem")
                log(f"read_json_file pre-reg-to-mem done {int((time.perf_counter() - start) * 1000)}ms")
            else:
                start = time.perf_counter()
                log("read_sv start")
                diags = sess.read_sv(
                    None,
                    out_design="design.main",
                    slang_args=read_args,
                )
                require_ok(diags, "read_sv")
                log(f"read_sv done {int((time.perf_counter() - start) * 1000)}ms")

                for pass_name, pass_kwargs in pre_sched_pipeline:
                    start = time.perf_counter()
                    log(f"pass {pass_name} start")
                    run_pass_kwargs = dict(pass_kwargs)
                    if pass_name == "simplify":
                        run_pass_kwargs["keep_declared_symbols"] = simplify_keep_declared_symbols
                    diags = sess.run_pass(pass_name, design="design.main", **run_pass_kwargs)
                    require_ok(diags, f"pass {pass_name}")
                    if pass_name == "comb-lane-pack":
                        write_comb_lane_pack_report(sess, "comb-lane-pack.reports", Path(comb_lane_pack_report))
                    log(f"pass {pass_name} done {int((time.perf_counter() - start) * 1000)}ms")
                write_design_json(
                    sess,
                    "design.main",
                    top_name,
                    pre_reg_to_mem_json,
                    "write_pre_reg_to_mem_json",
                )

            for pass_name, pass_kwargs in reg_to_mem_pipeline:
                start = time.perf_counter()
                log(f"pass {pass_name} start")
                diags = sess.run_pass(pass_name, design="design.main", **pass_kwargs)
                require_ok(diags, f"pass {pass_name}")
                if pass_name == "stats":
                    write_stats_json(sess, "stats.main", cpp_out_dir)
                    write_design_json(sess, "design.main", top_name, post_stats_json, "write_post_stats_json")
                    compute_summary = summarize_compute_ops_from_post_stats(post_stats_json, top_name)
                    if compute_summary is not None:
                        summary_path = cpp_out_dir / "wolvrix_xs_post_stats_summary.json"
                        summary_path.write_text(
                            json.dumps(compute_summary, indent=2, sort_keys=True),
                            encoding="utf-8",
                        )
                        log(
                            "post-stats summary "
                            f"top_total_ops={compute_summary['top_total_ops']} "
                            f"top_compute_ops={compute_summary['top_compute_ops']} "
                            f"top_declaration_ops={compute_summary['top_declaration_ops']} "
                            f"top_hierarchy_ops={compute_summary['top_hierarchy_ops']} "
                            f"top_array_ops={compute_summary['top_array_ops']} "
                            f"top_values={compute_summary['top_values']}"
                        )
                        log(f"post-stats summary written {summary_path}")
                log(f"pass {pass_name} done {int((time.perf_counter() - start) * 1000)}ms")

        if (lane_aggregate_array or comb_lane_pack_array) and not stop_after_pre_sched:
            # 数组语义产物（kArray*）在 legacy grhsim emit 前降解回标准形态
            # （post stats 已在上面写出，保留 array 形态供 AM lower-json；
            # array-lower 为语义等价展开，见 docs/transform/array-lower.md）。
            start = time.perf_counter()
            log("pass array-lower start")
            diags = sess.run_pass("array-lower", design="design.main")
            require_ok(diags, "pass array-lower")
            log(f"pass array-lower done {int((time.perf_counter() - start) * 1000)}ms")

        if stop_after_pre_sched:
            log("stop after pre-sched enabled")
            log(f"total done {int((time.perf_counter() - total_start) * 1000)}ms")
            return 0

        for pass_name, pass_kwargs in post_sched_pipeline:
            start = time.perf_counter()
            log(f"pass {pass_name} start")
            diags = sess.run_pass(pass_name, design="design.main", **pass_kwargs)
            require_ok(diags, f"pass {pass_name}")
            if pass_name == "activity-schedule":
                write_supernode_stats(sess, f"{top_name}.activity_schedule.supernode_to_ops", cpp_out_dir)
            log(f"pass {pass_name} done {int((time.perf_counter() - start) * 1000)}ms")

        if stop_after_activity_schedule:
            log("stop after activity-schedule enabled")
            log(f"total done {int((time.perf_counter() - total_start) * 1000)}ms")
            return 0

        if json_out:
            log(f"skip write_json after activity-schedule {json_out}")

        start = time.perf_counter()
        log(f"write_grhsim_cpp start {cpp_out_dir}")
        diags = sess.emit_grhsim_cpp(
            design="design.main",
            output=str(cpp_out_dir),
            top=[top_name],
            sched_batch_max_ops=sched_batch_max_ops,
            sched_batch_max_estimated_lines=sched_batch_max_estimated_lines,
            sched_batch_target_count=sched_batch_target_count,
            sched_batches_per_cpp=sched_batches_per_cpp,
            emit_parallelism=emit_parallelism,
            waveform=args.waveform,
            perf=args.perf,
        )
        require_ok(diags, "emit_grhsim_cpp")
        log(f"write_grhsim_cpp done {int((time.perf_counter() - start) * 1000)}ms")

        log(f"total done {int((time.perf_counter() - total_start) * 1000)}ms")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as ex:
        log(f"FAIL: {ex}")
        traceback.print_exc(file=sys.stderr)
        raise SystemExit(1)
