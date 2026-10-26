"""Resume an ordinary GRH checkpoint, rebuild SinkSchedule and emit C++."""

from __future__ import annotations

import argparse
import dataclasses
from pathlib import Path

import wolvrix

from grhsim_flow import FlowOptions, checked, emit_cpp, finish_simulation_graph, store_checkpoint, validate_environment
from grhsim_provenance import capture_generation, write_identity


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    try:
        validate_environment()
    except ValueError as error:
        parser.error(str(error))
    parser.add_argument("--model", type=Path, required=True, help="ordinary GRH JSON, at any completed stage")
    parser.add_argument("--flow", type=Path, required=True)
    parser.add_argument("--top", help="top graph; defaults to the unique top in the checkpoint")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--store-checkpoint", action="store_true",
                        help="write the resumed checkpoint even when the input is already sink-partitioned")
    parser.add_argument("--mem-write-activate", choices=["on-change", "on-write"], default="on-write")
    parser.add_argument("--mem-enable-bitmap", choices=["on", "off"], default="on")
    parser.add_argument("--emit-waveform", action="store_true")
    parser.add_argument("--execution-counters", action="store_true", help="diagnostic native operation/site counts; changes generated ABI")
    parser.add_argument("--max-function-lines", type=int, default=1024)
    parser.add_argument("--max-tu-bytes", type=int, default=1024 * 1024)
    parser.add_argument("--max-round", type=int, default=100000)
    parser.add_argument("--pack-bit-registers", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--recover-masked-or", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--masked-or-min-terms", type=int)
    parser.add_argument("--partition-simplify", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--max-node-work", type=int)
    parser.add_argument("--max-supernode-work", "--max-op-in-compute-supernode", type=int)
    parser.add_argument("--segment-penalty", type=int)
    parser.add_argument("--sink-enable-guard-min-size", type=int)
    parser.add_argument("--mem-min-bytes", type=int)
    parser.add_argument("--semantic-nodes", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--clone-shared", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--max-clones", type=int)
    parser.add_argument("--stop-after", choices=["converted", "event-output-split", "nonsink-sink-split",
                                                "nonsink-partitioned", "sink-partitioned"], default="sink-partitioned")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    flow = args.flow.resolve()
    if not any(flow.is_relative_to(base) and flow != base for base in (root / "ptmp", root / "build")):
        parser.error("flow must be a subdirectory of repository ptmp or build")
    if args.max_function_lines < 8 or args.max_tu_bytes < 1 or args.max_round < 1:
        parser.error("max-function-lines must be >=8; max-tu-bytes/max-round must be positive")
    return args


def main() -> int:
    args = parse_args()
    flow = args.flow.resolve()
    parser = argparse.ArgumentParser(description=__doc__)
    flow.mkdir(parents=True, exist_ok=True)
    identity = capture_generation("checkpoint-reemit", inputs={"checkpoint": args.model}, configuration=vars(args))
    write_identity(flow / "generation-identity.json", identity)
    with wolvrix.Session() as session:
        session.diagnostics_raise_min_level = "none"
        checked(session.read_json_file(str(args.model.resolve()), out_design="design.main"), "load ordinary GRH checkpoint")
        info = session.graph_metadata(design="design.main", top=args.top)
        top, metadata = info["symbol"], info["metadata"]
        options = FlowOptions.from_metadata(metadata)
        for field in dataclasses.fields(options):
            if hasattr(args, field.name) and getattr(args, field.name) is not None:
                setattr(options, field.name, getattr(args, field.name))
        if args.sink_enable_guard_min_size is not None:
            options.enable_guard_min_size = args.sink_enable_guard_min_size
        stage = metadata.get("grhsim.stage")
        if stage and stage != "converted" and any(
            getattr(args, name) is not None for name in
            ("pack_bit_registers", "recover_masked_or", "masked_or_min_terms")
        ):
            parser.error("Unpartitioned optimizations require the converted checkpoint")
        # Do not erase owners/clones or silently accept changed partition
        # settings on a later checkpoint. Resume from the stage that owns them.
        if stage in ("nonsink-partitioned", "sink-partitioned"):
            original = FlowOptions.from_metadata(metadata)
            if options.nonsink_options() != original.nonsink_options():
                parser.error("Changed activity options require the nonsink-sink-split checkpoint")
        if stage in ("nonsink-sink-split", "nonsink-partitioned", "sink-partitioned"):
            if options.mem_min_bytes != int(metadata["grhsim.memMinBytes"]):
                parser.error("Changed mem-min-bytes requires the event-output-split checkpoint")
        finish_simulation_graph(session, design="design.main", top=top, options=options, stop_after=args.stop_after)
        # A sink-partitioned checkpoint already contains the complete graph
        # state needed by the emitter.  Re-saving a multi-gigabyte JSON after
        # rebuilding its revision-local SinkSchedule only duplicates work and
        # can dominate a checkpoint re-emit.  Keep the old artifact-producing
        # behavior for earlier stages, and allow callers to request the
        # redundant write explicitly when they need a fresh checkpoint file.
        if stage != "sink-partitioned" or args.store_checkpoint:
            store_checkpoint(session, flow / "xiangshan_grhsim.json", design="design.main", top=top)
        if args.stop_after == "sink-partitioned":
            emit_cpp(session, design="design.main", top=top, output=flow / "model", overwrite=args.overwrite,
                     generation_identity=identity,
                     max_function_lines=args.max_function_lines, max_tu_bytes=args.max_tu_bytes,
                     max_round=args.max_round, waveform=args.emit_waveform, mem_write_activate=args.mem_write_activate,
                     mem_enable_bitmap=args.mem_enable_bitmap == "on", execution_counters=args.execution_counters)
    print("CHECKPOINT SCREENING ONLY: this timing does not qualify as full SV generation", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
