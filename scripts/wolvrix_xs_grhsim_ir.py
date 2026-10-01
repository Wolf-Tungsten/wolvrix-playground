#!/usr/bin/env python3

from __future__ import annotations

import argparse
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
    # order (resolution 2); layout/bitmaps/mem-plan run at the supernode
    # stage; pack-general-functions only records supernode intervals for the
    # emit functions; build-phase-schedule closes the mapping. Runs exactly
    # once; the old pipeline's "mapping -> semantic rewrite -> mapping" round
    # trip is abolished (M5d-5).
    "cpu.st.build-general-nodes",
    "cpu.st.merge-general-supernodes",
    "cpu.st.layout-named-stores",
    "cpu.st.build-event-bitmaps",
    "cpu.st.build-mem-write-plan",
    "cpu.st.pack-general-functions",
    "cpu.st.build-phase-schedule",
]

CPU_SEMANTIC_PIPELINE = [
    # Whole-graph stage-A pipeline (M5d-3): normalize first so pattern
    # matching sees canonical input, recover scalarized tables, pack
    # isomorphic comb lanes and bit registers while raw event_edges are still
    # present, then run the unified whole-graph simplify to a fixed point.
    # select-state-stores (M5d-4, A7) closes stage A with the semantic store
    # classification. clone-shared-compute no longer runs here: it is B7 in
    # the partition stage, after the last CSE-bearing simplify (M5d-5).
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
    # P_mem write duty), B6 simplifies each partition separately, B7 reclones
    # shared compute only where it eliminates a predicted supernode boundary,
    # and B8 seals the semantic layer (no semantic rewrite may follow).
    ("grhsim.classify-event-inputs", {}),
    ("grhsim.lower-edge-detect", {}),
    ("grhsim.extract-output-cones", {}),
    ("grhsim.migrate-timeslot-tasks", {}),
    ("grhsim.split-phases", {}),
    ("grhsim.simplify", {"scope": "phase"}),
    ("grhsim.clone-shared-compute", {}),
    ("grhsim.verify", {"seal": "semantic"}),
]

CPU_PIPELINE = (
    CPU_SEMANTIC_PIPELINE + CPU_PARTITION_PIPELINE
    + [(name, {}) for name in CPU_MAPPING_PIPELINE]
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
    parser.add_argument("--cpu-target-batch-count", type=int)
    parser.add_argument("--disable-reg-to-mem", action="store_true")
    parser.add_argument("--comb-pack", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--comb-pack-report", type=Path,
                        help="diagnostic (M5d-3): dump the group list TSV from grhsim.comb-pack")
    parser.add_argument("--select-state-stores", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--state-store-report", type=Path,
                        help="diagnostic (M5d-4): dump the per-state store class TSV from "
                             "grhsim.select-state-stores")
    parser.add_argument("--mem-min-bytes", type=int,
                        help="minimum linear byte size for the mem store class "
                             "(grhsim.select-state-stores; smaller arrays stay in regLatch)")
    parser.add_argument("--clone-shared-compute", action=argparse.BooleanOptionalAction, default=True)
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
    parser.add_argument("--reg-to-mem-report", type=Path)
    parser.add_argument("--pack-bit-registers-report", type=Path,
                        help="diagnostic (NO00026): dump the packed_bits member list TSV from grhsim.pack-bit-registers")
    parser.add_argument("--reg-to-mem-or-write-merge", action="store_true",
                        help="recover decoded OR-of-zero-mux writes with shared same-address data merging")
    parser.add_argument("--reg-to-mem-row-constant-fill", action="store_true",
                        help="let grhsim.reg-to-mem merge write families whose fill branch data is a "
                             "per-row constant, expanding the fill to static-address sequence triples "
                             "(off by default: NO00022 candidate mechanism)")
    args = parser.parse_args()
    if args.cpu_target_batch_count is not None and args.cpu_target_batch_count < 0:
        parser.error("--cpu-target-batch-count must be nonnegative")
    if args.max_op_in_compute_supernode is not None and args.max_op_in_compute_supernode <= 0:
        parser.error("--max-op-in-compute-supernode must be positive")
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
            and not (name == "grhsim.clone-shared-compute" and not args.clone_shared_compute)
            and not (name == "grhsim.simplify" and options.get("scope") == "phase"
                     and not args.phase_simplify)
        ]
        for pass_name, base_options in pipeline:
            pass_options = dict(base_options)
            if pass_name == "grhsim.clone-shared-compute":
                pass_options["max-clones"] = args.clone_shared_compute_max_clones
            if pass_name == "grhsim.reg-to-mem" and args.reg_to_mem_report:
                args.reg_to_mem_report.parent.mkdir(parents=True, exist_ok=True)
                pass_options["report"] = str(args.reg_to_mem_report.resolve())
            if pass_name == "grhsim.reg-to-mem" and args.reg_to_mem_row_constant_fill:
                pass_options["enable_row_constant_fill"] = True
            if pass_name == "grhsim.reg-to-mem" and args.reg_to_mem_or_write_merge:
                pass_options["enable_or_write_merge"] = True
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
            if pass_name == "cpu.st.pack-general-functions" and args.cpu_target_batch_count is not None:
                pass_options["target_batch_count"] = args.cpu_target_batch_count
            if pass_name == "cpu.st.merge-general-supernodes" and args.max_op_in_compute_supernode is not None:
                pass_options["max_op_in_compute_supernode"] = args.max_op_in_compute_supernode
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
            }
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
