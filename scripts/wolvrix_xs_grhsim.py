#!/usr/bin/env python3

import argparse
import json
import os
import shlex
import sys
import time
import traceback
from pathlib import Path

import wolvrix
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
    post_reg_to_mem_json = Path(
        os.environ.get(
            "WOLVRIX_XS_GRHSIM_POST_REG_TO_MEM_JSON",
            str(cpp_out_dir / "wolvrix_xs_post_reg_to_mem.json"),
        )
    ).resolve()
    pre_reg_to_mem_json = Path(
        os.environ.get(
            "WOLVRIX_XS_GRHSIM_PRE_REG_TO_MEM_JSON",
            str(cpp_out_dir / "wolvrix_xs_pre_reg_to_mem.json"),
        )
    ).resolve()
    resume_from_post_reg_to_mem_json = env_flag("WOLVRIX_XS_GRHSIM_RESUME_FROM_POST_REG_TO_MEM_JSON")
    resume_from_pre_reg_to_mem_json = env_flag("WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON")
    enable_mem_to_reg = env_flag("WOLVRIX_XS_GRHSIM_ENABLE_MEM_TO_REG", default=False)
    mem_to_reg_row_limit = env_int("WOLVRIX_XS_GRHSIM_MEM_TO_REG_ROW_LIMIT", 64)
    max_op_in_compute_supernode = env_int("WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE", 108)
    max_op_in_compute_node = env_int("WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_NODE", max_op_in_compute_supernode)
    split_oversize_compute_nodes = env_flag("WOLVRIX_XS_GRHSIM_SPLIT_OVERSIZE_COMPUTE_NODES", default=True)
    split_oversize_compute_node_max_ops = env_int(
        "WOLVRIX_XS_GRHSIM_SPLIT_OVERSIZE_COMPUTE_NODE_MAX_OPS",
        max_op_in_compute_supernode,
    )
    max_op_in_commit_supernode = env_int("WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE", 4096)
    commit_guard_event_buckets = env_flag("WOLVRIX_XS_GRHSIM_COMMIT_GUARD_EVENT_BUCKETS", default=True)
    sched_batch_max_ops = env_int("WOLVRIX_XS_GRHSIM_SCHED_BATCH_MAX_OPS", 2048)
    sched_batch_max_estimated_lines = env_int("WOLVRIX_XS_GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES", 8192)
    sched_batch_target_count = env_int("WOLVRIX_XS_GRHSIM_SCHED_BATCH_TARGET_COUNT", 64)
    sched_batches_per_cpp = env_int("WOLVRIX_XS_GRHSIM_SCHED_BATCHES_PER_CPP", 1)
    emit_parallelism = env_int("WOLVRIX_XS_GRHSIM_EMIT_PARALLELISM", 4)
    emit_runtime_stats = env_flag("WOLVRIX_XS_GRHSIM_EMIT_RUNTIME_STATS", default=False)
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
    reg_to_mem_intent = env_flag("WOLVRIX_XS_GRHSIM_REG_TO_MEM_INTENT", default=True)
    declared_value_compute_node_boundary = env_flag(
        "WOLVRIX_XS_GRHSIM_DECLARED_VALUE_COMPUTE_NODE_BOUNDARY",
        default=False,
    )
    comb_lane_pack_report = os.environ.get(
        "WOLVRIX_XS_GRHSIM_COMB_LANE_PACK_REPORT",
        str(cpp_out_dir.parent / "comb_lane_pack_report_xs.json"),
    )

    total_start = time.perf_counter()
    if resume_from_post_reg_to_mem_json and resume_from_pre_reg_to_mem_json:
        raise RuntimeError(
            "choose only one resume point: "
            "WOLVRIX_XS_GRHSIM_RESUME_FROM_POST_REG_TO_MEM_JSON or "
            "WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON"
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
        f"emit_runtime_stats={emit_runtime_stats} "
        f"storage_ref_aliases={storage_ref_aliases_setting}"
        f"{'' if storage_ref_aliases_env_was_set else '(xs_default)'} "
        f"export_compute_dag={export_compute_dag_path if export_compute_dag_path is not None else 'off'} "
        f"waveform={args.waveform} perf={args.perf} "
        f"simplify_keep_declared_symbols={simplify_keep_declared_symbols} "
        f"skip_comb_lane_pack={skip_comb_lane_pack} "
        f"pre_reg_to_mem_json={pre_reg_to_mem_json} "
        f"resume_from_pre_reg_to_mem_json={resume_from_pre_reg_to_mem_json} "
        f"post_reg_to_mem_json={post_reg_to_mem_json} "
        f"resume_from_post_reg_to_mem_json={resume_from_post_reg_to_mem_json} "
        f"reg_to_mem_intent={reg_to_mem_intent} "
        f"declared_value_compute_node_boundary={declared_value_compute_node_boundary}"
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
            ("comb-loop-elim", {}),
            ("simplify", {"semantics": "2state"}),
            ("simplify", {"semantics": "2state"}),
            ("memory-init-check", {}),
        ]
        reg_to_mem_kwargs: dict = {}
        if not reg_to_mem_intent:
            reg_to_mem_kwargs["intent"] = False
        reg_to_mem_pipeline: list[tuple[str, dict]] = [
            ("reg-to-mem", reg_to_mem_kwargs),
        ]
        if not skip_comb_lane_pack:
            pre_sched_pipeline.insert(
                6,
                (
                    "comb-lane-pack",
                    {
                        "enable_declared_roots": False,
                        "out_comb_lane_pack_report": "comb-lane-pack.reports",
                    },
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
                },
            ),
        ]
        if export_compute_dag_path is not None:
            post_sched_pipeline[0][1]["export_compute_dag"] = str(export_compute_dag_path)
        log(config_message)

        if resume_from_post_reg_to_mem_json:
            if not post_reg_to_mem_json.exists():
                raise RuntimeError(f"post-reg-to-mem json not found: {post_reg_to_mem_json}")
            start = time.perf_counter()
            log(f"read_json_file post-reg-to-mem start {post_reg_to_mem_json}")
            diags = sess.read_json_file(str(post_reg_to_mem_json), out_design="design.main")
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
                log(f"pass {pass_name} done {int((time.perf_counter() - start) * 1000)}ms")
            write_design_json(
                sess,
                "design.main",
                top_name,
                post_reg_to_mem_json,
                "write_post_reg_to_mem_json",
            )

        if stop_after_pre_sched:
            log("stop after pre-sched enabled")
            log(f"total done {int((time.perf_counter() - total_start) * 1000)}ms")
            return 0

        for pass_name, pass_kwargs in post_sched_pipeline:
            start = time.perf_counter()
            log(f"pass {pass_name} start")
            diags = sess.run_pass(pass_name, design="design.main", **pass_kwargs)
            require_ok(diags, f"pass {pass_name}")
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
            emit_runtime_stats=emit_runtime_stats,
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
