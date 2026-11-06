#!/usr/bin/env python3
"""Generate a partitioned ordinary GRH checkpoint and its single-thread C++ model."""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import shlex
import sys
import time
from pathlib import Path

import wolvrix

from grhsim_flow import FlowOptions, checked, emit_cpp, finish_simulation_graph, store_checkpoint, validate_environment


GRH_PIPELINE: list[tuple[str, dict]] = [
    ("xmr-resolve", {}),
    # Stage-07 编译期主修复：firtool preserve-aggregate 把字段级动态访问展开成
    # 常量索引 mux 树/逐元素写译码/pad 拼接读；在图最小的模块级阶段逆向折叠回
    # 动态数组访问，显著缩小后续 pass（尤其 simplify）与 emit 的图规模。
    # 先折叠已有的简单链，再在完整写组上提取保持分支，恢复剩余多写口译码。
    ("mux-tree-fold", {}),
    ("register-write-normalize", {"semantics": "2state"}),
    ("mux-tree-fold", {"guarded_writes": "2state"}),
    ("memory-read-retime", {}),
    ("multidriven-guard", {}),
    ("blackbox-guard", {}),
    ("latch-transparent-read", {}),
    ("hier-flatten", {}),
    ("comb-loop-elim", {"fail_on_true_loop": True}),
    # Stage-07 hardening: verify shape/op invariants before and after the
    # simplify fixed point (cheap, ~4s on XiangShan) instead of discovering
    # geometry violations deep inside const-fold or at the grhsim boundary.
    ("grh.verify", {}),
    ("simplify", {"semantics": "2state"}),
    ("grh.verify", {}),
    ("memory-init-check", {}),
]

# The default pipeline keeps the full lowering and cleanup sequence.  A
# bring-up run can omit the optional graph-size reduction passes so that a
# frozen full-chip input reaches flatten/emit within the producer's hard
# wall-clock budget.  This profile is intentionally opt-in; it is for proving
# end-to-end behavior before spending time on instruction-count tuning.
GRH_BRINGUP_PIPELINE: list[tuple[str, dict]] = [
    ("xmr-resolve", {}),
    ("multidriven-guard", {}),
    ("blackbox-guard", {}),
    ("latch-transparent-read", {}),
    ("hier-flatten", {}),
    ("comb-loop-elim", {"fail_on_true_loop": True}),
    # grh-to-grhsim performs full verification before and after conversion.
    ("memory-init-check", {}),
]


def grh_pipeline() -> list[tuple[str, dict]]:
    profile = os.environ.get("XS_GRHSIM_PIPELINE_PROFILE", "full").strip().lower()
    if profile == "full":
        return GRH_PIPELINE
    if profile == "bringup":
        return GRH_BRINGUP_PIPELINE
    raise ValueError(f"XS_GRHSIM_PIPELINE_PROFILE must be 'full' or 'bringup', got {profile!r}")


def read_source_pipeline(session, request: dict, pipeline: list[tuple[str, dict]], *,
                         out_design: str = "design.main"):
    """Read sources and return diagnostics, remaining passes, and prefix evidence."""
    prefix = GRH_PIPELINE[:8]
    if pipeline[:len(prefix)] != prefix:
        return session.read_sources(**request, out_design=out_design), pipeline, None
    try:
        diagnostics = session.read_sources(**request, out_design=out_design, pipeline="grh-pre-flatten")
    except TypeError as error:
        # Historical native libraries reject the added keyword before starting
        # ingest. Preserve those comparison/replay callers' original route.
        message = str(error)
        if "'pipeline'" not in message or "keyword" not in message or not any(
                word in message for word in ("invalid", "unexpected")):
            raise
        return session.read_sources(**request, out_design=out_design), pipeline, None
    report = dict(session.get(out_design + ".prefix"))
    if not any(str(entry.get("kind", "")).lower() == "error" for entry in diagnostics):
        if [row["pass"] for row in report["stages"]] != [name for name, _ in prefix]:
            raise RuntimeError("ingest prefix report does not match the production pass order")
    report["ingest_diagnostics"] = diagnostics[:report["ingest_diagnostic_count"]]
    report["pipeline"] = [{"pass": name, "options": options, "keep_declared_symbols": True}
                          for name, options in prefix]
    return diagnostics, pipeline[len(prefix):], report


def env_int(name: str, default: int, *, minimum: int = 0, maximum: int = 2147483647) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be in [{minimum},{maximum}], got {raw!r}")
    return value


def sink_guard_min_size() -> int:
    return env_int("XS_GRHSIM_SINK_GUARD_MIN", 0)


def segment_penalty() -> int:
    return env_int("XS_GRHSIM_SEGMENT_PENALTY", 1)


def semantic_nodes() -> bool:
    return bool(env_int("XS_GRHSIM_SEMANTIC_NODES", 0, maximum=1))


def recover_masked_or_enabled() -> bool:
    return bool(env_int("XS_GRHSIM_MASKED_OR", 1, maximum=1))


def default_flow_options() -> FlowOptions:
    validate_environment()
    return FlowOptions(
        firrtl_node_cse=os.environ.get("XS_GRHSIM_FIRRTL_NODE_CSE", "gsim"),
        firrtl_nodes=os.environ.get("XS_GRHSIM_FIRRTL_NODES", "auto"),
        cost_model=os.environ.get("XS_GRHSIM_COST_MODEL", "legacy"),
        enable_guard_min_size=sink_guard_min_size(),
        segment_penalty=segment_penalty(),
        semantic_nodes=semantic_nodes(),
        max_supernode_nodes=env_int("XS_GRHSIM_MAX_SUPERNODE_NODES", 128, minimum=1),
        recover_masked_or=recover_masked_or_enabled(),
    )


def log(message: str) -> None:
    print(f"[wolvrix-xs-grhsim] {message}", file=sys.stderr, flush=True)


def require_ok(diagnostics: list[dict], action: str) -> None:
    checked(diagnostics, action)


def timed(action: str, callback):
    start = time.perf_counter()
    log(f"{action} start")
    result = callback()
    log(f"{action} done {round((time.perf_counter() - start) * 1000)}ms")
    return result


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    try:
        validate_environment()
    except ValueError as error:
        parser.error(str(error))
    parser.add_argument("filelist")
    parser.add_argument("top")
    parser.add_argument("flat_grh_json")
    parser.add_argument("grhsim_json", help="ordinary GRH JSON containing grhsim dialect ops")
    parser.add_argument("roundtrip_json")
    parser.add_argument("read_args_file")
    parser.add_argument("log_level", nargs="?", default="info")
    parser.add_argument("--sources-manifest", type=Path,
                        help="mixed FIRRTL/SV read_sources request; bypass the SV filelist")
    parser.add_argument("--resume-from-flat-grh", action="store_true")
    parser.add_argument("--roundtrip-verify", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--store-grh-checkpoints", action=argparse.BooleanOptionalAction, default=True,
                        help="write automatic flat/final GRH JSON checkpoints; explicit dumps remain independent")
    parser.add_argument("--keep-origins", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--emit-cpp-dir", type=Path)
    parser.add_argument("--overwrite-emit-cpp", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--emit-waveform", action="store_true")
    parser.add_argument("--readable-names", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--source-comments", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--readable-dump", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--readable-frames", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--mem-write-activate", choices=["on-change", "on-write"], default="on-write")
    parser.add_argument("--mem-enable-bitmap", choices=["on", "off"], default="on")
    parser.add_argument("--max-function-lines", type=int, default=1024,
                        help="actual line limit for every emitted function, including dispatchers")
    parser.add_argument("--max-tu-bytes", type=int, default=1024 * 1024)
    parser.add_argument("--max-output-file-bytes", type=int, default=4 * 1024**3,
                        help="maximum bytes in one generated file (positive uint64)")
    parser.add_argument("--max-round", type=int, default=100000)
    parser.add_argument("--mem-min-bytes", type=int)
    parser.add_argument("--clone-shared-compute", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--clone-shared-compute-max-clones", type=int, default=250000)
    parser.add_argument("--clone-shared-compute-lossy-compare", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--simplify", action=argparse.BooleanOptionalAction, default=True,
                        help="run grhsim-simplify before and after optional transforms and partitioning")
    parser.add_argument("--simplify-max-rounds", type=int, default=8,
                        help="maximum rewrite rounds for each grhsim-simplify pass")
    parser.add_argument("--phase-simplify", action=argparse.BooleanOptionalAction, default=True,
                        help="simplify within each complete leaf after activity partitioning")
    parser.add_argument("--recover-masked-or", action=argparse.BooleanOptionalAction,
                        default=recover_masked_or_enabled())
    parser.add_argument("--masked-or-min-terms", type=int, default=16)
    parser.add_argument("--firrtl-node-cse", choices=["off", "gsim"],
                        default=os.environ.get("XS_GRHSIM_FIRRTL_NODE_CSE", "gsim"))
    parser.add_argument("--masked-or-report", type=Path)
    parser.add_argument("--firrtl-nodes", choices=["off", "prefer", "auto"], default=os.environ.get("XS_GRHSIM_FIRRTL_NODES", "auto"))
    parser.add_argument("--cost-model", choices=["legacy", "bytes"], default=os.environ.get("XS_GRHSIM_COST_MODEL", "legacy"))
    parser.add_argument("--nonsink-report")
    parser.add_argument("--pack-bit-registers", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--pack-bit-registers-report", type=Path)
    parser.add_argument("--dump-post-conversion-json", type=Path)
    parser.add_argument("--dump-pre-simplify-json", type=Path)
    parser.add_argument("--dump-pre-partition-json", type=Path,
                        help="optimized, unpartitioned converted graph")
    parser.add_argument("--checkpoint-dir", type=Path, help="store each completed graph stage")
    parser.add_argument("--max-supernode-nodes", type=int, help="maximum unified nodes per supernode")
    parser.add_argument("--sink-enable-guard-min-size", type=int)
    args = parser.parse_args(argv)
    if not args.store_grh_checkpoints:
        if args.emit_cpp_dir is None:
            parser.error("--no-store-grh-checkpoints requires --emit-cpp-dir")
        if args.roundtrip_verify:
            parser.error("--no-store-grh-checkpoints requires --no-roundtrip-verify")
    if not args.keep_origins:
        parser.error("--no-keep-origins is retired; unified GRH retains origins through conversion")
    if not 0 < args.max_output_file_bytes < 2**64:
        parser.error("--max-output-file-bytes must be a positive uint64")
    for name, minimum in (("max_function_lines", 8), ("max_tu_bytes", 1), ("max_round", 1),
                          ("mem_min_bytes", 0), ("max_supernode_nodes", 1),
                          ("sink_enable_guard_min_size", 0), ("clone_shared_compute_max_clones", 1),
                          ("masked_or_min_terms", 2), ("simplify_max_rounds", 1)):
        value = getattr(args, name)
        if value is not None and not minimum <= value <= 2147483647:
            parser.error(f"--{name.replace('_', '-')} must be in [{minimum},2147483647]")
    return args


def read_slang_args(filelist: Path, top: str, read_args_file: Path) -> list[str]:
    if not filelist.is_file():
        raise RuntimeError(f"filelist not found: {filelist}")
    if not read_args_file.is_file():
        raise RuntimeError(f"read args file not found: {read_args_file}")
    result = ["-f", str(filelist), "--top", top]
    for line in read_args_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            result.extend(shlex.split(line))
    return result


def read_source_manifest(path: Path, top: str) -> dict:
    """Resolve explicit inputs without collecting generated FIRRTL-to-SV files."""
    path = path.resolve()
    request = json.loads(path.read_text(encoding="utf-8"))
    allowed = {"schema", "sources", "tops", "input_root", "slang_args",
               "firrtl_options", "external_bindings"}
    if not isinstance(request, dict) or set(request) - allowed:
        raise ValueError("invalid mixed sources manifest fields")
    if request.pop("schema", None) != "wolvrix.xs.firrtl-inputs.v1":
        raise ValueError("unsupported mixed sources manifest schema")
    sources = request.get("sources")
    if not isinstance(sources, list) or not sources or not any(
            source.get("language") == "firrtl" for source in sources if isinstance(source, dict)):
        raise ValueError("mixed sources manifest requires a FIRRTL source")
    root = Path(request.get("input_root", "."))
    if not root.is_absolute():
        root = path.parent / root
    request["input_root"] = str(root.resolve())
    for source in sources:
        if not isinstance(source, dict) or source.get("language") not in ("firrtl", "sv"):
            raise ValueError("invalid mixed source language")
        source_path = Path(source["path"])
        if not source_path.is_absolute():
            source_path = root / source_path
        if not source_path.is_file():
            raise ValueError(f"mixed input not found: {source_path}")
        source["path"] = str(source_path.resolve())
    if request.setdefault("tops", [top]) != [top]:
        raise ValueError("mixed sources manifest top differs from selected top")
    return request


def main() -> int:
    args = parse_args()
    options = default_flow_options()
    options.simplify = args.simplify
    options.simplify_max_rounds = args.simplify_max_rounds
    options.pack_bit_registers = args.pack_bit_registers
    options.recover_masked_or = args.recover_masked_or
    options.masked_or_min_terms = args.masked_or_min_terms
    options.firrtl_node_cse = args.firrtl_node_cse
    options.firrtl_nodes = args.firrtl_nodes
    options.cost_model = args.cost_model
    options.nonsink_report = args.nonsink_report
    options.partition_simplify = args.phase_simplify
    options.clone_shared = args.clone_shared_compute
    options.max_clones = args.clone_shared_compute_max_clones
    options.clone_lossy_compare = args.clone_shared_compute_lossy_compare
    for name in ("mem_min_bytes", "max_supernode_nodes"):
        if getattr(args, name) is not None:
            setattr(options, name, getattr(args, name))
    if args.sink_enable_guard_min_size is not None:
        options.enable_guard_min_size = args.sink_enable_guard_min_size
    for argument, field in ((args.pack_bit_registers_report, "pack_report"),
                            (args.masked_or_report, "masked_or_report")):
        if argument:
            argument.resolve().parent.mkdir(parents=True, exist_ok=True)
            setattr(options, field, str(argument.resolve()))
    pipeline = grh_pipeline()
    log("pipeline profile=" + os.environ.get("XS_GRHSIM_PIPELINE_PROFILE", "full"))
    log("configuration " + json.dumps(vars(options), sort_keys=True))
    flat_path = Path(args.flat_grh_json).resolve()
    final_path = Path(args.grhsim_json).resolve()
    roundtrip_path = Path(args.roundtrip_json).resolve()
    started = time.perf_counter()
    from grhsim_provenance import capture_generation, write_identity
    mixed_request = read_source_manifest(args.sources_manifest, args.top) if args.sources_manifest else None
    inputs = {"filelist": args.filelist, "read_args": args.read_args_file}
    if mixed_request:
        inputs = {"sources_manifest": args.sources_manifest}
        inputs.update({f"source_{i}": source["path"] for i, source in enumerate(mixed_request["sources"])})
        for i, name in enumerate(mixed_request.get("firrtl_options", {}).get("annotation_files", [])):
            inputs[f"annotation_{i}"] = Path(mixed_request["input_root"]) / name
    identity = capture_generation("flat-grh-resume" if args.resume_from_flat_grh else
                                  "original-firrtl-mixed" if mixed_request else "original-sv",
        inputs=({"flat_grh": flat_path} if args.resume_from_flat_grh else inputs),
        configuration={"arguments": vars(args), "flow": vars(options)})
    write_identity(final_path.with_name(final_path.stem + ".generation-identity.json"), identity)
    with wolvrix.Session() as session:
        session.log_level = args.log_level
        session.diagnostics_raise_min_level = "none"
        if args.resume_from_flat_grh:
            checked(timed("load flat GRH", lambda: session.read_json_file(str(flat_path), out_design="design.main")), "load flat GRH")
        else:
            if mixed_request:
                diagnostics, pipeline, prefix_report = timed("ingest FIRRTL/mixed RTL", lambda:
                    read_source_pipeline(session, mixed_request, pipeline))
                if prefix_report is not None:
                    report_path = flat_path.with_name(flat_path.stem + ".prefix-report.json")
                    report_path.parent.mkdir(parents=True, exist_ok=True)
                    report_path.write_text(json.dumps(prefix_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                    identity["ingest_prefix_report"] = str(report_path)
                    identity["ingest_pipeline"] = "grh-pre-flatten"
                    log("production pre-flatten prefix wall_s=" + str(prefix_report["prefix_wall_s"]))
                checked(diagnostics, "ingest FIRRTL/mixed RTL")
            else:
                slang_args = read_slang_args(Path(args.filelist).resolve(), args.top, Path(args.read_args_file).resolve())
                checked(timed("ingest RTL", lambda: session.read_sv(None, out_design="design.main", slang_args=slang_args)), "ingest RTL")
            identity["ingest_dependencies"] = session.graph_metadata(
                design="design.main", top=args.top)["metadata"].get("ingest.dependencies", [])
            write_identity(final_path.with_name(final_path.stem + ".generation-identity.json"), identity)
            for name, pass_options in pipeline:
                if name == "simplify" and args.dump_pre_simplify_json:
                    store_checkpoint(session, args.dump_pre_simplify_json.resolve(), design="design.main", top=args.top)
                checked(timed(f"GRH pass {name}", lambda name=name, opts=pass_options: session.run_pass(
                    name, design="design.main", keep_declared_symbols=True, **opts)), name)
            if args.store_grh_checkpoints:
                store_checkpoint(session, flat_path, design="design.main", top=args.top)
        converted_count = 0

        def checkpoint(stage):
            nonlocal converted_count
            if stage == "converted":
                converted_count += 1
                if converted_count == 1 and args.dump_post_conversion_json:
                    store_checkpoint(session, args.dump_post_conversion_json.resolve(), design="design.main", top=args.top)
                if converted_count == 2 and args.dump_pre_partition_json:
                    store_checkpoint(session, args.dump_pre_partition_json.resolve(), design="design.main", top=args.top)
            if args.checkpoint_dir:
                store_checkpoint(session, args.checkpoint_dir.resolve() / f"{stage}.json", design="design.main", top=args.top)

        finish_simulation_graph(session, design="design.main", top=args.top, options=options, checkpoint=checkpoint)
        if args.store_grh_checkpoints:
            store_checkpoint(session, final_path, design="design.main", top=args.top)
        if args.emit_cpp_dir:
            timed("emit grhsim-cpu-st-cpp", lambda: emit_cpp(
                session, design="design.main", top=args.top, output=args.emit_cpp_dir,
                generation_identity=identity,
                overwrite=args.overwrite_emit_cpp, max_function_lines=args.max_function_lines,
                max_tu_bytes=args.max_tu_bytes, max_round=args.max_round, waveform=args.emit_waveform,
                max_output_file_bytes=args.max_output_file_bytes,
                readable_names=args.readable_names, source_comments=args.source_comments,
                readable_dump=args.readable_dump, readable_frames=args.readable_frames,
                mem_write_activate=args.mem_write_activate, mem_enable_bitmap=args.mem_enable_bitmap == "on"))
    if args.roundtrip_verify:
        with wolvrix.Session() as session:
            session.diagnostics_raise_min_level = "none"
            checked(session.read_json_file(str(final_path), out_design="design.main"), "load ordinary GRH checkpoint")
            # A fresh session cannot reuse resolved IDs from the producer.
            finish_simulation_graph(session, design="design.main", top=args.top)
            store_checkpoint(session, roundtrip_path, design="design.main", top=args.top)
        if not filecmp.cmp(final_path, roundtrip_path, shallow=False):
            raise RuntimeError("GRH store/load/schedule-rebuild/store changed stable JSON bytes")
        log("ordinary GRH round trip and SinkSchedule rebuild verified")
    log(f"total done {round((time.perf_counter() - started) * 1000)}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
