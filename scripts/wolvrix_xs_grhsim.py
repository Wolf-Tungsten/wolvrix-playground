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
        source_kinds = {"kConstant", "kRegisterReadPort", "kLatchReadPort"}
        sink_kinds = {"kRegisterWritePort", "kLatchWritePort", "kMemoryWritePort", "kMemoryFillPort"}
        decl_kinds = {"kRegister", "kMemory", "kLatch", "kDpicImport"}
        hier_kinds = {"kInstance", "kBlackbox", "kXMRRead", "kXMRWrite"}
        total_ops = len(ops)
        source_ops = sum(1 for op in ops if op.get("kind") in source_kinds)
        sink_ops = sum(1 for op in ops if op.get("kind") in sink_kinds)
        declaration_ops = sum(1 for op in ops if op.get("kind") in decl_kinds)
        hierarchy_ops = sum(1 for op in ops if op.get("kind") in hier_kinds)
        compute_ops = total_ops - source_ops - sink_ops - declaration_ops - hierarchy_ops
        return {
            "top_total_ops": total_ops,
            "top_compute_ops": compute_ops,
            "top_source_ops": source_ops,
            "top_sink_ops": sink_ops,
            "top_declaration_ops": declaration_ops,
            "top_hierarchy_ops": hierarchy_ops,
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


def write_supernode_stats(sess: wolvrix.Session, key: str, out_dir: Path) -> None:
    summary_key = key.rsplit("supernode_to_ops", 1)[0] + "summary_stats"
    try:
        summary_text = _native.session_export(sess._capsule, key=summary_key, view="text")
    except Exception:
        summary_text = None

    raw = _native.session_export(sess._capsule, key=key, view="python")
    supernode_to_ops = [list(map(int, ops)) for ops in raw]
    dag_key = key.rsplit("supernode_to_ops", 1)[0] + "dag"
    dag_raw = _native.session_export(sess._capsule, key=dag_key, view="python")
    dag = [list(map(int, succs)) for succs in dag_raw]
    if summary_text:
        summary = json.loads(summary_text)
        sizes = sorted(len(ops) for ops in supernode_to_ops)
        out_degrees = sorted(len(succs) for succs in dag)
        summary["ops_per_supernode"] = {
            "min": sizes[0] if sizes else 0,
            "mean": statistics.fmean(sizes) if sizes else 0.0,
            "median": statistics.median(sizes) if sizes else 0,
            "p90": percentile(sizes, 90, 100),
            "p99": percentile(sizes, 99, 100),
            "max": sizes[-1] if sizes else 0,
        }
        summary["out_degree_per_supernode"] = {
            "min": out_degrees[0] if out_degrees else 0,
            "mean": statistics.fmean(out_degrees) if out_degrees else 0.0,
            "median": statistics.median(out_degrees) if out_degrees else 0,
            "p90": percentile(out_degrees, 90, 100),
            "p99": percentile(out_degrees, 99, 100),
            "max": out_degrees[-1] if out_degrees else 0,
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
            f"outdeg_mean={summary['out_degree_per_supernode']['mean']:.3f} "
            f"outdeg_p99={summary['out_degree_per_supernode']['p99']} "
            f"outdeg_max={summary['out_degree_per_supernode']['max']}"
        )
        log(f"activity-schedule supernode stats written {out_path}")
        return

    supernode_kind_key = key.rsplit("supernode_to_ops", 1)[0] + "supernode_kind"
    supernode_kind_raw = _native.session_export(sess._capsule, key=supernode_kind_key, view="python")
    supernode_kinds = [int(kind) for kind in supernode_kind_raw]
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
    args = parser.parse_args()

    filelist = args.filelist
    top_name = args.top
    cpp_out_dir = Path(args.cpp_out_dir).resolve()
    json_out = args.json_out
    read_args_file = args.read_args_file
    log_level = args.log_level
    post_stats_json = Path(
        os.environ.get(
            "WOLVRIX_XS_GRHSIM_POST_STATS_JSON",
            str(cpp_out_dir / "wolvrix_xs_post_stats.json"),
        )
    ).resolve()
    resume_from_stats_json = env_flag("WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON")
    enable_mem_to_reg = env_flag("WOLVRIX_XS_GRHSIM_ENABLE_MEM_TO_REG", default=False)
    mem_to_reg_row_limit = env_int("WOLVRIX_XS_GRHSIM_MEM_TO_REG_ROW_LIMIT", 64)
    max_op_in_compute_supernode = env_int(
        "WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE",
        env_int("WOLVRIX_XS_GRHSIM_MAX_COMPUTE_NODE_IN_COMPUTE_SUPERNODE", 8),
    )
    max_op_in_compute_node = env_int("WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_NODE", 8192)
    max_value_in_compute_supernode = env_int("WOLVRIX_XS_GRHSIM_MAX_VALUE_IN_COMPUTE_SUPERNODE", 0)
    target_compute_supernodes = env_int("WOLVRIX_XS_GRHSIM_TARGET_COMPUTE_SUPERNODES", 0)
    max_value_in_compute_node = env_int("WOLVRIX_XS_GRHSIM_MAX_VALUE_IN_COMPUTE_NODE", 0)
    max_declared_value_in_compute_node = env_int("WOLVRIX_XS_GRHSIM_MAX_DECLARED_VALUE_IN_COMPUTE_NODE", 0)
    max_op_in_commit_supernode = env_int("WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE", 768)
    topo_order_model = os.environ.get("WOLVRIX_XS_GRHSIM_TOPO_ORDER_MODEL", "layer")
    local_shared_compute_max_fanout = env_int("WOLVRIX_XS_GRHSIM_LOCAL_SHARED_COMPUTE_MAX_FANOUT", 4)
    local_shared_compute_max_width = env_int("WOLVRIX_XS_GRHSIM_LOCAL_SHARED_COMPUTE_MAX_WIDTH", 256)
    enable_local_shared_compute = env_flag("WOLVRIX_XS_GRHSIM_ENABLE_LOCAL_SHARED_COMPUTE", default=False)
    essent_small_part_cutoff = env_int("WOLVRIX_XS_GRHSIM_ESSENT_SMALL_PART_CUTOFF", 20)
    essent_small_sibling_max_preds = env_int("WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_MAX_PREDS", 1)
    essent_small_sibling_candidate_budget = env_int(
        "WOLVRIX_XS_GRHSIM_ESSENT_SMALL_SIBLING_CANDIDATE_BUDGET", 250000
    )
    essent_small_overlap_candidate_budget = env_int(
        "WOLVRIX_XS_GRHSIM_ESSENT_SMALL_OVERLAP_CANDIDATE_BUDGET", 250000
    )
    split_oversize_compute_node_max_ops = env_int("WOLVRIX_XS_GRHSIM_SPLIT_OVERSIZE_COMPUTE_NODE_MAX_OPS", 0)
    essent_overlap_threshold1 = env_float("WOLVRIX_XS_GRHSIM_ESSENT_OVERLAP_THRESHOLD1", 0.5)
    essent_overlap_threshold2 = env_float("WOLVRIX_XS_GRHSIM_ESSENT_OVERLAP_THRESHOLD2", 0.25)
    essent_cycle_guard_max_visits = env_int("WOLVRIX_XS_GRHSIM_ESSENT_CYCLE_GUARD_MAX_VISITS", 4096)
    enable_essent_mffc_build = env_flag("WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_MFFC_BUILD", default=False)
    enable_essent_coarsen = env_flag("WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_COARSEN", default=False)
    enable_essent_single_parent_merge = env_flag(
        "WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SINGLE_PARENT_MERGE",
        default=True,
    )
    enable_essent_small_sibling_merge = env_flag(
        "WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_SIBLING_MERGE",
        default=True,
    )
    enable_essent_small_overlap_merge = env_flag(
        "WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_SMALL_OVERLAP_MERGE",
        default=True,
    )
    enable_essent_down_merge = env_flag("WOLVRIX_XS_GRHSIM_ENABLE_ESSENT_DOWN_MERGE", default=True)
    split_oversize_compute_nodes = env_flag("WOLVRIX_XS_GRHSIM_SPLIT_OVERSIZE_COMPUTE_NODES", default=False)
    dump_essent_dag_stats = env_flag("WOLVRIX_XS_GRHSIM_DUMP_ESSENT_DAG_STATS", default=True)
    sched_batch_max_ops = env_int("WOLVRIX_XS_GRHSIM_SCHED_BATCH_MAX_OPS", 2048)
    sched_batch_max_estimated_lines = env_int("WOLVRIX_XS_GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES", 8192)
    sched_batch_target_count = env_int("WOLVRIX_XS_GRHSIM_SCHED_BATCH_TARGET_COUNT", 64)
    sched_batches_per_cpp = env_int("WOLVRIX_XS_GRHSIM_SCHED_BATCHES_PER_CPP", 1)
    emit_parallelism = env_int("WOLVRIX_XS_GRHSIM_EMIT_PARALLELISM", 4)
    storage_ref_aliases_env_was_set = "WOLVRIX_GRHSIM_STORAGE_REF_ALIASES" in os.environ
    if not storage_ref_aliases_env_was_set:
        os.environ["WOLVRIX_GRHSIM_STORAGE_REF_ALIASES"] = "0"
    storage_ref_aliases_setting = os.environ["WOLVRIX_GRHSIM_STORAGE_REF_ALIASES"]
    stop_after_pre_sched = env_flag("WOLVRIX_XS_GRHSIM_STOP_AFTER_PRE_SCHED", default=False)
    stop_after_activity_schedule = env_flag("WOLVRIX_XS_GRHSIM_STOP_AFTER_ACTIVITY_SCHEDULE", default=False)
    simplify_keep_declared_symbols = env_flag("WOLVRIX_XS_GRHSIM_SIMPLIFY_KEEP_DECLARED_SYMBOLS", default=False)
    merge_reg_options = {
        "enable_scalar_to_memory": env_flag("WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_SCALAR_TO_MEMORY", default=True),
        "enable_indexed_bundle_entry_to_wide_register": env_flag(
            "WOLVRIX_XS_GRHSIM_MERGE_REG_ENABLE_INDEXED_BUNDLE_ENTRY_TO_WIDE_REGISTER",
            default=True,
        ),
    }
    comb_lane_pack_report = os.environ.get(
        "WOLVRIX_XS_GRHSIM_COMB_LANE_PACK_REPORT",
        str(cpp_out_dir.parent / "comb_lane_pack_report_xs.json"),
    )

    total_start = time.perf_counter()

    config_message = (
        "activity-schedule max_op_in_compute_supernode="
        f"{max_op_in_compute_supernode} "
        f"max_op_in_compute_node={max_op_in_compute_node} "
        f"max_value_in_compute_supernode={max_value_in_compute_supernode} "
        f"target_compute_supernodes={target_compute_supernodes} "
        f"max_value_in_compute_node={max_value_in_compute_node} "
        f"max_declared_value_in_compute_node={max_declared_value_in_compute_node} "
        f"max_op_in_commit_supernode={max_op_in_commit_supernode} "
        f"topo_order_model={topo_order_model} "
        f"local_shared_compute_max_fanout={local_shared_compute_max_fanout} "
        f"local_shared_compute_max_width={local_shared_compute_max_width} "
        f"enable_local_shared_compute={enable_local_shared_compute} "
        f"enable_essent_mffc_build={enable_essent_mffc_build} "
        f"enable_essent_coarsen={enable_essent_coarsen} "
        f"enable_essent_single_parent_merge={enable_essent_single_parent_merge} "
        f"enable_essent_small_sibling_merge={enable_essent_small_sibling_merge} "
        f"enable_essent_small_overlap_merge={enable_essent_small_overlap_merge} "
        f"enable_essent_down_merge={enable_essent_down_merge} "
        f"split_oversize_compute_nodes={split_oversize_compute_nodes} "
        f"essent_small_part_cutoff={essent_small_part_cutoff} "
        f"essent_small_sibling_max_preds={essent_small_sibling_max_preds} "
        f"essent_small_sibling_candidate_budget={essent_small_sibling_candidate_budget} "
        f"essent_small_overlap_candidate_budget={essent_small_overlap_candidate_budget} "
        f"split_oversize_compute_node_max_ops={split_oversize_compute_node_max_ops} "
        f"essent_overlap_threshold1={essent_overlap_threshold1} "
        f"essent_overlap_threshold2={essent_overlap_threshold2} "
        f"essent_cycle_guard_max_visits={essent_cycle_guard_max_visits} "
        f"sched_batch_max_ops={sched_batch_max_ops} "
        f"sched_batch_max_estimated_lines={sched_batch_max_estimated_lines} "
        f"sched_batch_target_count={sched_batch_target_count} "
        f"sched_batches_per_cpp={sched_batches_per_cpp} "
        f"emit_parallelism={emit_parallelism} "
        f"storage_ref_aliases={storage_ref_aliases_setting}"
        f"{'' if storage_ref_aliases_env_was_set else '(xs_default)'} "
        f"waveform={args.waveform} perf={args.perf} "
        f"simplify_keep_declared_symbols={simplify_keep_declared_symbols}"
    )

    read_args: list[str] = ["-f", filelist, "--top", top_name]

    if read_args_file:
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
            (
                "comb-lane-pack",
                {
                    "enable_declared_roots": False,
                    "out_comb_lane_pack_report": "comb-lane-pack.reports",
                },
            ),
            ("comb-loop-elim", {}),
            ("simplify", {"semantics": "2state"}),
            ("simplify", {"semantics": "2state"}),
            ("memory-init-check", {}),
            ("stats", {"out_stats": "stats.main"}),
        ]
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
                    "max_op_in_commit_supernode": max_op_in_commit_supernode,
                    "local_shared_compute_max_fanout": local_shared_compute_max_fanout,
                    "local_shared_compute_max_width": local_shared_compute_max_width,
                    "enable_local_shared_compute": enable_local_shared_compute,
                    "essent_small_part_cutoff": essent_small_part_cutoff,
                    "essent_small_sibling_max_preds": essent_small_sibling_max_preds,
                    "essent_small_sibling_candidate_budget": essent_small_sibling_candidate_budget,
                    "essent_small_overlap_candidate_budget": essent_small_overlap_candidate_budget,
                    "split_oversize_compute_node_max_ops": split_oversize_compute_node_max_ops,
                    "essent_overlap_threshold1": essent_overlap_threshold1,
                    "essent_overlap_threshold2": essent_overlap_threshold2,
                    "essent_cycle_guard_max_visits": essent_cycle_guard_max_visits,
                    "enable_essent_mffc_build": enable_essent_mffc_build,
                    "enable_essent_coarsen": enable_essent_coarsen,
                    "enable_essent_single_parent_merge": enable_essent_single_parent_merge,
                    "enable_essent_small_sibling_merge": enable_essent_small_sibling_merge,
                    "enable_essent_small_overlap_merge": enable_essent_small_overlap_merge,
                    "enable_essent_down_merge": enable_essent_down_merge,
                    "split_oversize_compute_nodes": split_oversize_compute_nodes,
                    "dump_essent_dag_stats": dump_essent_dag_stats,
                },
            ),
        ]
        log(config_message)

        if resume_from_stats_json:
            if not post_stats_json.exists():
                raise RuntimeError(f"post-stats json not found: {post_stats_json}")
            start = time.perf_counter()
            log(f"read_json_file start {post_stats_json}")
            diags = sess.read_json_file(str(post_stats_json), out_design="design.main")
            require_ok(diags, "read_json_file")
            log(f"read_json_file done {int((time.perf_counter() - start) * 1000)}ms")
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
                            f"top_values={compute_summary['top_values']}"
                        )
                        log(f"post-stats summary written {summary_path}")
                log(f"pass {pass_name} done {int((time.perf_counter() - start) * 1000)}ms")

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
