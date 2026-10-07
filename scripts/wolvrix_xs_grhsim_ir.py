#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import shlex
import sys
import time
from pathlib import Path

import wolvrix


GRH_PIPELINE: list[tuple[str, dict]] = [
    ("xmr-resolve", {}),
    ("memory-read-retime", {}),
    ("multidriven-guard", {}),
    ("blackbox-guard", {}),
    ("latch-transparent-read", {}),
    ("hier-flatten", {}),
    ("comb-loop-elim", {}),
    ("simplify", {"semantics": "2state"}),
    ("memory-init-check", {}),
]

CPU_MAPPING_PIPELINE = [
    # Final CPU mapping (M5d-6, C segment): build-general-nodes initializes
    # the one mapping from the sealed phase attribution (the semantic
    # grhsim.split-phases is B5 above) and forms the General nodes;
    # merge-general-supernodes fixes the supernode ordinals in partition
    # order (resolution 2); clone-shared-boundaries (V3-M3, C2.5) reclones
    # cheap bijective shared compute against the REAL supernode boundaries —
    # the C-segment landing of the removed B7 predictive pass — then
    # layout/activation-map/mem-plan run at the supernode stage;
    # pack-general-functions only records supernode intervals for the emit
    # functions; build-phase-schedule closes the layout/schedule.
    # M5d-7 (C8): plan-translation-units appends the emit TU plan; emit-cpp
    # then writes one size-bounded .cpp per unit. Runs exactly once; the old
    # pipeline's "mapping -> semantic rewrite -> mapping" round trip is
    # abolished (M5d-5).
    "cpu.st.build-general-nodes",
    "cpu.st.merge-general-supernodes",
    "cpu.st.clone-shared-boundaries",
    "cpu.st.layout-named-stores",
    "cpu.st.build-event-activation-map",
    "cpu.st.build-mem-write-plan",
    "cpu.st.pack-general-functions",
    "cpu.st.build-phase-schedule",
    "cpu.st.plan-translation-units",
]


def sink_guard_min_size() -> int:
    # A1 sink enable-guard subdivision knob (same env-switch pattern as
    # XS_WOLF_GRHSIM_IR_PHASE_SIMPLIFY, read here so both this flow and the
    # HDLBits entry pick it up through CPU_PIPELINE): minimum shared-enable
    # group size for cpu.st.merge-general-supernodes to carve out a
    # guard-gated SinkEvent supernode. Default 0 (disabled): the A/B on XS
    # measured +0.5% host time (recorded in
    # pdocs/perf-optimization/20261004-113053-sink-enable-guard.md); set a positive
    # integer (e.g. "8") to enable the subdivision.
    raw = os.environ.get("XS_WOLF_GRHSIM_IR_SINK_GUARD_MIN", "0").strip()
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(
            f"XS_WOLF_GRHSIM_IR_SINK_GUARD_MIN must be a nonnegative integer, got {raw!r}"
        ) from None
    if value < 0:
        raise RuntimeError(
            f"XS_WOLF_GRHSIM_IR_SINK_GUARD_MIN must be a nonnegative integer, got {raw!r}"
        )
    return value

def segment_penalty() -> int:
    # DP segmentation penalty knob (cpu.st.merge-general-supernodes
    # --segment-penalty): per-segment cost in the boundary-minimizing DP.
    # Default 1 (legacy uniform objective: distinct incoming activation
    # values + 1 per segment); larger values bias toward fewer, larger
    # non-sink supernodes (boundary-reduction exploration).
    raw = os.environ.get("XS_WOLF_GRHSIM_IR_SEGMENT_PENALTY", "1").strip()
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(
            f"XS_WOLF_GRHSIM_IR_SEGMENT_PENALTY must be a nonnegative integer, got {raw!r}"
        ) from None
    if value < 0:
        raise RuntimeError(
            f"XS_WOLF_GRHSIM_IR_SEGMENT_PENALTY must be a nonnegative integer, got {raw!r}"
        )
    return value

def semantic_nodes() -> int:
    # S1 semantic node formation knob (cpu.st.build-general-nodes
    # --semantic-nodes): 1 = declared signals (DeclProvenance Value slices)
    # anchor their own nodes and the 128-op node size cap is dropped, so node
    # shape follows declaration boundaries; 0 (default) = legacy cone
    # absorption with the size cap. Boundary-reduction exploration, see
    # pdocs/perf-optimization/20261005-170704-nonsink-semantic-partition-plan.md.
    raw = os.environ.get("XS_WOLF_GRHSIM_IR_SEMANTIC_NODES", "0").strip()
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(
            f"XS_WOLF_GRHSIM_IR_SEMANTIC_NODES must be 0 or 1, got {raw!r}"
        ) from None
    if value not in (0, 1):
        raise RuntimeError(
            f"XS_WOLF_GRHSIM_IR_SEMANTIC_NODES must be 0 or 1, got {raw!r}"
        )
    return value

def semantic_node_max_op() -> int:
    # Semantic-mode cone cap knob (cpu.st.build-general-nodes
    # --semantic-node-max-op): in semantic node mode, bound the op count a
    # node may reach through cone absorption. 0 (default) = uncapped (pure
    # S1); positive values bound giant declared cones for compile-time
    # control. Same plan doc as XS_WOLF_GRHSIM_IR_SEMANTIC_NODES.
    raw = os.environ.get("XS_WOLF_GRHSIM_IR_SEMANTIC_NODE_MAX_OP", "0").strip()
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(
            f"XS_WOLF_GRHSIM_IR_SEMANTIC_NODE_MAX_OP must be a nonnegative integer, got {raw!r}"
        ) from None
    if value < 0:
        raise RuntimeError(
            f"XS_WOLF_GRHSIM_IR_SEMANTIC_NODE_MAX_OP must be a nonnegative integer, got {raw!r}"
        )
    return value

def coarsen_max_op() -> int:
    # S2 coarsen merge weight cap knob (cpu.st.merge-general-supernodes
    # --coarsen-max-op): cap on the combined op weight of a merged coarsen
    # cluster. 0 (default) = follow --max-op-in-compute-supernode (legacy);
    # a large value (e.g. 1000000000) effectively lifts the cap. Same plan
    # doc as XS_WOLF_GRHSIM_IR_SEMANTIC_NODES.
    raw = os.environ.get("XS_WOLF_GRHSIM_IR_COARSEN_MAX_OP", "0").strip()
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(
            f"XS_WOLF_GRHSIM_IR_COARSEN_MAX_OP must be a nonnegative integer, got {raw!r}"
        ) from None
    if value < 0:
        raise RuntimeError(
            f"XS_WOLF_GRHSIM_IR_COARSEN_MAX_OP must be a nonnegative integer, got {raw!r}"
        )
    return value


def mem_enable_bitmap() -> str:
    # P_mem enable shadow-bitmap knob (cpu.st.emit-cpp --mem-enable-bitmap):
    # dense per-port enable bits mirrored from their boundary fields replace the
    # per-round scattered boundary reads in the P_mem write-port scan. Default
    # on; set XS_WOLF_GRHSIM_IR_MEM_ENABLE_BITMAP=0 to fall back to the plain
    # per-port boundary reads.
    raw = os.environ.get("XS_WOLF_GRHSIM_IR_MEM_ENABLE_BITMAP", "1").strip()
    if raw in ("0", "off"):
        return "off"
    if raw in ("1", "on"):
        return "on"
    raise RuntimeError(
        f"XS_WOLF_GRHSIM_IR_MEM_ENABLE_BITMAP must be 0/1/on/off, got {raw!r}"
    )


CPU_SEMANTIC_PIPELINE = [
    # Whole-graph stage-A pipeline (M5d-3): normalize first so pattern
    # matching sees canonical input, recover scalarized tables, pack
    # isomorphic comb lanes and bit registers while raw event_edges are still
    # present, then run the unified whole-graph simplify to a fixed point.
    # select-state-stores (M5d-4, A7) closes stage A with the semantic store
    # classification. Boundary-aware shared-compute cloning never runs in the
    # semantic stages: it lives in the C segment as cpu.st.clone-shared-boundaries
    # (V3-M3, after merge-general-supernodes).
    ("grhsim.canonicalize-compute", {}),
    ("grhsim.reg-to-mem", {}),
    ("grhsim.comb-pack", {}),
    ("grhsim.pack-bit-registers", {}),
    ("grhsim.simplify", {"scope": "whole"}),
    ("grhsim.select-state-stores", {}),
]

CPU_PARTITION_PIPELINE = [
    # Partition stage B (M5d-5), still pure semantic layer (no CPU mapping):
    # B1-B4 lower the event/output/timeslot structure, B5 completes the
    # class-aware phase attribution (P_event/P_general/P_output partitions +
    # P_mem write duty), B6 simplifies each partition separately, and B8
    # seals the semantic layer. V3-M3: the predictive B7
    # (grhsim.clone-shared-compute) is gone — boundary-aware cloning moved
    # into the mapping stage as cpu.st.clone-shared-boundaries (C2.5), where
    # real supernode boundaries replace the prediction. After the seal only
    # registered C-segment micro-adjustment passes may touch the semantics.
    ("grhsim.classify-event-inputs", {}),
    ("grhsim.lower-edge-detect", {}),
    ("grhsim.extract-output-cones", {}),
    ("grhsim.migrate-timeslot-tasks", {}),
    ("grhsim.split-phases", {}),
    ("grhsim.simplify", {"scope": "phase"}),
    ("grhsim.verify", {"seal": "semantic"}),
]

def _cpu_mapping_options(name: str) -> dict:
    # Default-valued knobs stay unpassed so older wolvrix builds (which
    # reject unknown options) keep working; the skipped values equal the
    # engines' built-in defaults in every case.
    options = {}
    if name == "cpu.st.build-general-nodes":
        if value := semantic_nodes():
            options["semantic_nodes"] = value
        if value := semantic_node_max_op():
            options["semantic_node_max_op"] = value
    if name == "cpu.st.merge-general-supernodes":
        if (value := sink_guard_min_size()) != 0:
            options["sink_enable_guard_min_size"] = value
        if (value := segment_penalty()) != 1:
            options["segment_penalty"] = value
        if value := coarsen_max_op():
            options["coarsen_max_op"] = value
    return options

CPU_PIPELINE = (
    CPU_SEMANTIC_PIPELINE + CPU_PARTITION_PIPELINE
    + [
        (name, _cpu_mapping_options(name))
        for name in CPU_MAPPING_PIPELINE
    ]
)


def log(message: str) -> None:
    sys.stderr.write(f"[wolvrix-xs-grhsim-ir] {message}\n")
    sys.stderr.flush()


def has_error(diagnostics: list[dict]) -> bool:
    return any(str(item.get("kind", "")).lower() == "error" for item in diagnostics)


def require_ok(diagnostics: list[dict], action: str) -> None:
    if has_error(diagnostics):
        raise RuntimeError(f"{action} failed")


def timed(action: str, callback):
    start = time.perf_counter()
    log(f"{action} start")
    result = callback()
    log(f"{action} done {int((time.perf_counter() - start) * 1000)}ms")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and round-trip the independent XiangShan GrhSIM IR checkpoint"
    )
    parser.add_argument("filelist")
    parser.add_argument("top")
    parser.add_argument("flat_grh_json")
    parser.add_argument("grhsim_json")
    parser.add_argument("roundtrip_json")
    parser.add_argument("read_args_file")
    parser.add_argument("log_level", nargs="?", default="info")
    parser.add_argument("--resume-from-flat-grh", action="store_true")
    parser.add_argument("--keep-origins", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--emit-cpp-dir", type=Path)
    parser.add_argument("--emit-waveform", action="store_true",
                        help="emit the CPU model with FST waveform capture for declared symbols "
                             "(cpu.st.emit-cpp --waveform declared-symbols)")
    parser.add_argument("--cpu-target-batch-count", type=int)
    parser.add_argument("--cpu-helper-max-estimated-lines", type=int,
                        help="C6 per-function helper-chunk cap; huge values disable supernode chunking")
    parser.add_argument("--cpu-chunk-max-estimated-lines", type=int,
                        help="M5d-7 C8: per-function estimated-lines cap for the emit TU plan")
    parser.add_argument("--cpu-unit-max-estimated-lines", type=int,
                        help="M5d-7 C8: per-translation-unit estimated-lines cap for the emit TU plan")
    parser.add_argument("--disable-reg-to-mem", action="store_true")
    parser.add_argument("--comb-pack", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--comb-pack-report", type=Path,
                        help="diagnostic (M5d-3): dump the group list TSV from grhsim.comb-pack")
    parser.add_argument("--select-state-stores", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--state-store-report", type=Path,
                        help="diagnostic (M5d-4): dump the per-state store class TSV from "
                             "grhsim.select-state-stores")
    parser.add_argument("--mem-min-bytes", type=int,
                        help="minimum linear byte size for the mem store class "
                             "(grhsim.select-state-stores; smaller arrays stay in regLatch)")
    parser.add_argument("--clone-shared-compute", action=argparse.BooleanOptionalAction, default=True,
                        help="reclone cheap bijective shared compute against real supernode boundaries (cpu.st.clone-shared-boundaries, V3-M3)")
    parser.add_argument("--clone-shared-compute-max-clones", type=int, default=250000)
    parser.add_argument("--phase-simplify", action=argparse.BooleanOptionalAction, default=True,
                        help="run the B6 per-partition simplify (grhsim.simplify --scope phase) "
                             "after grhsim.split-phases")
    parser.add_argument("--bitwise-predicates", action=argparse.BooleanOptionalAction, default=True,
                        help="deprecated no-op (M5d-5): bitwise-predicates runs inside "
                             "grhsim.simplify and no longer has a standalone pipeline step")
    parser.add_argument("--pack-bit-registers", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--disable-pack-bit-registers", action="store_true",
                        help="drop only grhsim.pack-bit-registers from the pipeline, keeping every "
                             "other semantic pass (isolated A/B arm, NO00021)")
    parser.add_argument("--used-bits", action=argparse.BooleanOptionalAction, default=True,
                        help="deprecated no-op (M5d-5): used-bits runs inside grhsim.simplify "
                             "and no longer has a standalone pipeline step")
    parser.add_argument("--dump-post-lower-json", type=Path,
                        help="diagnostic (NO00020): also store the GrhSIM model right after grhsim.verify, before any semantic/mapping pass")
    parser.add_argument("--dump-pre-partition-json", type=Path,
                        help="diagnostic (NO00020): also store the GrhSIM model after the sealed "
                             "semantic pipeline (B8), right before the single cpu.st.build-general-nodes "
                             "mapping run")
    parser.add_argument("--max-op-in-compute-supernode", type=int,
                        help="override the compute supernode op cap (activity granularity)")
    parser.add_argument("--sink-enable-guard-min-size", type=int,
                        help="override the A1 sink enable-guard group threshold "
                             "(default: XS_WOLF_GRHSIM_IR_SINK_GUARD_MIN or 8; 0 disables)")
    parser.add_argument("--reg-to-mem-report", type=Path)
    parser.add_argument("--pack-bit-registers-report", type=Path,
                        help="diagnostic (NO00026): dump the packed_bits member list TSV from grhsim.pack-bit-registers")
    parser.add_argument("--reg-to-mem-or-write-merge", action=argparse.BooleanOptionalAction, default=True,
                        help="recover decoded OR-of-zero-mux writes with shared same-address data merging")
    parser.add_argument("--reg-to-mem-row-constant-fill", action=argparse.BooleanOptionalAction, default=True,
                        help="let grhsim.reg-to-mem merge write families whose fill branch data is a "
                             "per-row constant, expanding the fill to static-address sequence triples")
    args = parser.parse_args()
    if args.cpu_target_batch_count is not None and args.cpu_target_batch_count < 0:
        parser.error("--cpu-target-batch-count must be nonnegative")
    for caps in ("cpu_chunk_max_estimated_lines", "cpu_unit_max_estimated_lines"):
        if getattr(args, caps) is not None and getattr(args, caps) <= 0:
            parser.error(f"--{caps.replace('_', '-')} must be positive")
    if args.max_op_in_compute_supernode is not None and args.max_op_in_compute_supernode <= 0:
        parser.error("--max-op-in-compute-supernode must be positive")
    if args.sink_enable_guard_min_size is not None and args.sink_enable_guard_min_size < 0:
        parser.error("--sink-enable-guard-min-size must be nonnegative")
    if args.clone_shared_compute_max_clones <= 0:
        parser.error("--clone-shared-compute-max-clones must be positive")
    if args.mem_min_bytes is not None and args.mem_min_bytes < 0:
        parser.error("--mem-min-bytes must be nonnegative")
    return args


def read_slang_args(filelist: Path, top: str, read_args_file: Path) -> list[str]:
    if not filelist.is_file():
        raise RuntimeError(f"filelist not found: {filelist}")
    if not read_args_file.is_file():
        raise RuntimeError(f"read args file not found: {read_args_file}")
    result = ["-f", str(filelist), "--top", top]
    for line in read_args_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            result.extend(shlex.split(line))
    return result


def main() -> int:
    args = parse_args()
    filelist = Path(args.filelist).resolve()
    flat_grh_json = Path(args.flat_grh_json).resolve()
    grhsim_json = Path(args.grhsim_json).resolve()
    roundtrip_json = Path(args.roundtrip_json).resolve()
    read_args_file = Path(args.read_args_file).resolve()
    emit_cpp_dir = args.emit_cpp_dir.resolve() if args.emit_cpp_dir else None

    for path in (flat_grh_json, grhsim_json, roundtrip_json):
        path.parent.mkdir(parents=True, exist_ok=True)

    total_start = time.perf_counter()
    with wolvrix.Session() as session:
        session.log_level = args.log_level
        session.diagnostics_raise_min_level = "none"

        if args.resume_from_flat_grh:
            if not flat_grh_json.is_file():
                raise RuntimeError(f"flat GRH checkpoint not found: {flat_grh_json}")
            diagnostics = timed(
                f"load flat GRH {flat_grh_json}",
                lambda: session.read_json_file(str(flat_grh_json), out_design="design.main"),
            )
            require_ok(diagnostics, "load flat GRH")
        else:
            read_args = read_slang_args(filelist, args.top, read_args_file)
            diagnostics = timed(
                "ingest XiangShan RTL",
                lambda: session.read_sv(None, out_design="design.main", slang_args=read_args),
            )
            require_ok(diagnostics, "ingest XiangShan RTL")
            for pass_name, pass_options in GRH_PIPELINE:
                # Declared-symbol retention must stay on through the whole GRH
                # pipeline: the lowered declProvenance association depends on it.
                options_with_retention = {"keep_declared_symbols": True, **pass_options}
                diagnostics = timed(
                    f"GRH pass {pass_name}",
                    lambda name=pass_name, options=options_with_retention: session.run_pass(
                        name, design="design.main", **options
                    ),
                )
                require_ok(diagnostics, f"GRH pass {pass_name}")
            diagnostics = timed(
                f"store flat GRH checkpoint {flat_grh_json}",
                lambda: session.store_json(
                    design="design.main", output=str(flat_grh_json), top=[args.top]
                ),
            )
            require_ok(diagnostics, "store flat GRH checkpoint")

        diagnostics = timed(
            "lower GRH to independent GrhSIM IR",
            lambda: session.lower_grhsim(
                design="design.main",
                out_model="grhsim.main",
                top=args.top,
                logic_domain="2-state",
                keep_origins=args.keep_origins,
                keep_declared_symbols=True,
                consume=True,
            ),
        )
        require_ok(diagnostics, "lower GRH to GrhSIM IR")
        diagnostics = timed(
            "GrhSIM verify pass",
            lambda: session.run_grhsim_pass("grhsim.verify", model="grhsim.main"),
        )
        require_ok(diagnostics, "GrhSIM verify pass")
        if args.dump_post_lower_json is not None:
            dump_path = args.dump_post_lower_json.resolve()
            dump_path.parent.mkdir(parents=True, exist_ok=True)
            diagnostics = timed(
                f"store post-lower GrhSIM dump {dump_path}",
                lambda: session.store_grhsim(model="grhsim.main", output=str(dump_path)),
            )
            require_ok(diagnostics, "store post-lower GrhSIM dump")
        pipeline = [
            (name, options) for name, options in CPU_PIPELINE
            if not (name == "grhsim.pack-bit-registers"
                    and (not args.pack_bit_registers or args.disable_pack_bit_registers))
            and not (name == "grhsim.comb-pack" and not args.comb_pack)
            and not (name == "grhsim.select-state-stores" and not args.select_state_stores)
            and not (name == "grhsim.reg-to-mem" and args.disable_reg_to_mem)
            and not (name == "cpu.st.clone-shared-boundaries" and not args.clone_shared_compute)
            and not (name == "grhsim.simplify" and options.get("scope") == "phase"
                     and not args.phase_simplify)
        ]
        for pass_name, base_options in pipeline:
            pass_options = dict(base_options)
            if pass_name == "cpu.st.clone-shared-boundaries":
                pass_options["max-clones"] = args.clone_shared_compute_max_clones
            if pass_name == "grhsim.reg-to-mem" and args.reg_to_mem_report:
                args.reg_to_mem_report.parent.mkdir(parents=True, exist_ok=True)
                pass_options["report"] = str(args.reg_to_mem_report.resolve())
            if pass_name == "grhsim.reg-to-mem":
                pass_options["enable_row_constant_fill"] = args.reg_to_mem_row_constant_fill
                pass_options["enable_or_write_merge"] = args.reg_to_mem_or_write_merge
            if pass_name == "grhsim.comb-pack" and args.comb_pack_report:
                args.comb_pack_report.parent.mkdir(parents=True, exist_ok=True)
                pass_options["report"] = str(args.comb_pack_report.resolve())
            if pass_name == "grhsim.select-state-stores":
                if args.mem_min_bytes is not None:
                    pass_options["mem-min-bytes"] = args.mem_min_bytes
                if args.state_store_report:
                    args.state_store_report.parent.mkdir(parents=True, exist_ok=True)
                    pass_options["report"] = str(args.state_store_report.resolve())
            if pass_name == "grhsim.pack-bit-registers" and args.pack_bit_registers_report:
                args.pack_bit_registers_report.parent.mkdir(parents=True, exist_ok=True)
                pass_options["report"] = str(args.pack_bit_registers_report.resolve())
            if pass_name == "cpu.st.pack-general-functions":
                if args.cpu_target_batch_count is not None:
                    pass_options["target_batch_count"] = args.cpu_target_batch_count
                if args.cpu_helper_max_estimated_lines is not None:
                    pass_options["helper_max_estimated_lines"] = args.cpu_helper_max_estimated_lines
            if pass_name == "cpu.st.plan-translation-units":
                if args.cpu_chunk_max_estimated_lines is not None:
                    pass_options["chunk_max_estimated_lines"] = args.cpu_chunk_max_estimated_lines
                if args.cpu_unit_max_estimated_lines is not None:
                    pass_options["unit_max_estimated_lines"] = args.cpu_unit_max_estimated_lines
            if pass_name == "cpu.st.merge-general-supernodes" and args.max_op_in_compute_supernode is not None:
                pass_options["max_op_in_compute_supernode"] = args.max_op_in_compute_supernode
            if pass_name == "cpu.st.merge-general-supernodes" and args.sink_enable_guard_min_size is not None:
                pass_options["sink_enable_guard_min_size"] = args.sink_enable_guard_min_size
            if pass_name == "cpu.st.build-general-nodes" and args.dump_pre_partition_json is not None:
                dump_path = args.dump_pre_partition_json.resolve()
                dump_path.parent.mkdir(parents=True, exist_ok=True)
                diagnostics = timed(
                    f"store pre-partition GrhSIM dump {dump_path}",
                    lambda: session.store_grhsim(model="grhsim.main", output=str(dump_path)),
                )
                require_ok(diagnostics, "store pre-partition GrhSIM dump")
            diagnostics = timed(
                f"GrhSIM CPU pass {pass_name}" + (f" {pass_options}" if pass_options else ""),
                lambda name=pass_name, options=pass_options: session.run_grhsim_pass(name, model="grhsim.main", **options),
            )
            require_ok(diagnostics, f"GrhSIM CPU pass {pass_name}")
            # Keep pass hit counters (candidates/transformed/rejections/...)
            # visible in the flow log; M5d-3 checkpoints consume these.
            session.print_diagnostics(diagnostics, min_level="info")
        if emit_cpp_dir is not None:
            emit_options = {
                "model": "grhsim.main",
                "output": str(emit_cpp_dir),
                "mem_enable_bitmap": mem_enable_bitmap(),
            }
            if args.emit_waveform:
                emit_options["waveform"] = "declared-symbols"
            diagnostics = timed(
                f"emit CPU C++ model {emit_cpp_dir}",
                lambda: session.run_grhsim_pass("cpu.st.emit-cpp", **emit_options),
            )
            require_ok(diagnostics, "emit CPU C++ model")
            session.print_diagnostics(diagnostics, min_level="info")
        diagnostics = timed(
            f"store GrhSIM checkpoint {grhsim_json}",
            lambda: session.store_grhsim(model="grhsim.main", output=str(grhsim_json)),
        )
        require_ok(diagnostics, "store GrhSIM checkpoint")

    with wolvrix.Session() as fresh_session:
        fresh_session.diagnostics_raise_min_level = "none"
        diagnostics = timed(
            f"load GrhSIM checkpoint in fresh session {grhsim_json}",
            lambda: fresh_session.load_grhsim(str(grhsim_json), out_model="grhsim.roundtrip"),
        )
        require_ok(diagnostics, "load GrhSIM checkpoint")
        diagnostics = timed(
            f"store GrhSIM round-trip {roundtrip_json}",
            lambda: fresh_session.store_grhsim(
                model="grhsim.roundtrip", output=str(roundtrip_json)
            ),
        )
        require_ok(diagnostics, "store GrhSIM round-trip")

    if grhsim_json.read_bytes() != roundtrip_json.read_bytes():
        raise RuntimeError("GrhSIM store/load/store changed stable JSON bytes")
    log(f"stable round-trip verified: {grhsim_json} == {roundtrip_json}")
    log(f"total done {int((time.perf_counter() - total_start) * 1000)}ms")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        log(f"fatal: {error}")
        raise
