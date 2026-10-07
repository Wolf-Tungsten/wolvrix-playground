"""Emit an archived mapped GrhSIM checkpoint for diagnostic candidate screening."""

import argparse
from pathlib import Path

import wolvrix

from wolvrix_xs_grhsim_ir import CPU_MAPPING_PIPELINE, mem_enable_bitmap

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--flow", type=Path, required=True)
    parser.add_argument("--pack-bit-registers", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--remap", action="store_true", help="rebuild CPU mapping without a semantic transform")
    parser.add_argument("--bitwise-muxes", action="store_true")
    parser.add_argument("--mux-chain-fold", action="store_true")

    parser.add_argument("--used-bits", action="store_true",
                        help="run grhsim.used-bits (dead-cone elimination + width narrowing), then remap")

    parser.add_argument("--canonicalize-compute", action="store_true",
                        help="run grhsim.canonicalize-compute (incl. concat-of-slices folds), then remap")
    parser.add_argument("--max-op-in-compute-supernode", type=int,
                        help="override the compute supernode op cap during remapping")
    parser.add_argument("--segment-penalty", type=int,
                        help="override the DP segment penalty during remapping")
    parser.add_argument("--sink-enable-guard-min-size", type=int,
                        help="override the sink enable-guard group size during remapping")
    parser.add_argument("--helper-max-estimated-lines", type=int,
                        help="override the helper chunk line cap during remapping")
    parser.add_argument("--semantic-nodes", type=int,
                        help="override semantic node formation (0/1) during remapping")
    parser.add_argument("--semantic-node-max-op", type=int,
                        help="cap semantic-mode cone absorption size (0 = uncapped)")
    parser.add_argument("--coarsen-max-op", type=int,
                        help="override the coarsen merge weight cap during remapping "
                             "(0 = follow the supernode cap)")
    parser.add_argument("--cpu-target-batch-count", type=int, default=0)
    args = parser.parse_args()
    if args.cpu_target_batch_count < 0:
        parser.error("cpu target batch count must be nonnegative")
    if args.max_op_in_compute_supernode is not None and args.max_op_in_compute_supernode <= 0:
        parser.error("max op in compute supernode must be positive")
    if args.segment_penalty is not None and args.segment_penalty < 0:
        parser.error("segment penalty must be nonnegative")
    if args.sink_enable_guard_min_size is not None and args.sink_enable_guard_min_size < 0:
        parser.error("sink enable guard min size must be nonnegative")
    if args.helper_max_estimated_lines is not None and args.helper_max_estimated_lines <= 0:
        parser.error("helper max estimated lines must be positive")
    if args.semantic_nodes is not None and args.semantic_nodes not in (0, 1):
        parser.error("semantic nodes must be 0 or 1")
    if args.semantic_node_max_op is not None and args.semantic_node_max_op < 0:
        parser.error("semantic node max op must be nonnegative")
    if args.coarsen_max_op is not None and args.coarsen_max_op < 0:
        parser.error("coarsen max op must be nonnegative")
    root = Path(__file__).resolve().parents[1]
    flow = args.flow.resolve()
    if not flow.is_relative_to(root / "ptmp") or (flow / "model").exists():
        parser.error("flow must be under ptmp with no existing model output")
    flow.mkdir(parents=True, exist_ok=True)
    with wolvrix.Session() as session:
        session.diagnostics_raise_min_level = "none"
        diagnostics = session.load_grhsim(str(args.model.resolve()), out_model="grhsim.main")
        for entry in diagnostics:
            print(entry, flush=True)
        if any(str(entry.get("kind", "")).lower() == "error" for entry in diagnostics):
            raise RuntimeError("checkpoint load failed")

        def mapping_options(name):
            options = {}
            if name == "cpu.st.pack-general-functions":
                options["target_batch_count"] = args.cpu_target_batch_count
                if args.helper_max_estimated_lines is not None:
                    options["helper_max_estimated_lines"] = args.helper_max_estimated_lines
            if name == "cpu.st.build-general-nodes":
                if args.semantic_nodes is not None:
                    options["semantic_nodes"] = args.semantic_nodes
                if args.semantic_node_max_op is not None:
                    options["semantic_node_max_op"] = args.semantic_node_max_op
            if name == "cpu.st.merge-general-supernodes":
                if args.max_op_in_compute_supernode is not None:
                    options["max_op_in_compute_supernode"] = args.max_op_in_compute_supernode
                if args.segment_penalty is not None:
                    options["segment_penalty"] = args.segment_penalty
                if args.sink_enable_guard_min_size is not None:
                    options["sink_enable_guard_min_size"] = args.sink_enable_guard_min_size
                if args.coarsen_max_op is not None:
                    options["coarsen_max_op"] = args.coarsen_max_op
            return options

        if args.pack_bit_registers:
            actions = [
                lambda: session.run_grhsim_pass("grhsim.pack-bit-registers", model="grhsim.main"),
            ] + [
                lambda name=name: session.run_grhsim_pass(name, model="grhsim.main", **mapping_options(name))
                for name in CPU_MAPPING_PIPELINE
            ]
        else:
            actions = []
        if args.remap and not args.pack_bit_registers:
            actions = [
                lambda name=name: session.run_grhsim_pass(name, model="grhsim.main", **mapping_options(name))
                for name in CPU_MAPPING_PIPELINE
            ]
        if args.bitwise_muxes:
            actions += [lambda: session.run_grhsim_pass("grhsim.bitwise-muxes", model="grhsim.main")]
            actions += [
                lambda name=name: session.run_grhsim_pass(name, model="grhsim.main", **mapping_options(name))
                for name in CPU_MAPPING_PIPELINE
            ]
        if args.mux_chain_fold:
            actions += [lambda: session.run_grhsim_pass("grhsim.mux-chain-fold", model="grhsim.main")]
            actions += [
                lambda name=name: session.run_grhsim_pass(name, model="grhsim.main", **mapping_options(name))
                for name in CPU_MAPPING_PIPELINE
            ]
        if args.canonicalize_compute:
            actions += [lambda: session.run_grhsim_pass("grhsim.canonicalize-compute", model="grhsim.main")]
            actions += [
                lambda name=name: session.run_grhsim_pass(name, model="grhsim.main", **mapping_options(name))
                for name in CPU_MAPPING_PIPELINE
            ]
        if args.used_bits:
            actions += [lambda: session.run_grhsim_pass("grhsim.used-bits", model="grhsim.main")]
            actions += [
                lambda name=name: session.run_grhsim_pass(name, model="grhsim.main", **mapping_options(name))
                for name in CPU_MAPPING_PIPELINE
            ]
        emit_options = {"model": "grhsim.main", "output": str(flow / "model"),
                        "mem_enable_bitmap": mem_enable_bitmap()}
        for action in actions + [
            # C8 replans deterministically when the checkpoint already carries
            # a TU plan, so it is safe to run unconditionally before emit.
            lambda: session.run_grhsim_pass("cpu.st.plan-translation-units", model="grhsim.main"),
            lambda: session.run_grhsim_pass("cpu.st.emit-cpp", **emit_options),
            lambda: session.store_grhsim(model="grhsim.main", output=str(flow / "xiangshan_grhsim_ir.json")),
        ]:
            diagnostics = action()
            for entry in diagnostics:
                print(entry, flush=True)
            if any(str(entry.get("kind", "")).lower() == "error" for entry in diagnostics):
                raise RuntimeError("checkpoint transform/emit failed")
    print("CHECKPOINT SCREENING ONLY: this timing does not qualify as full SV generation", flush=True)

if __name__ == "__main__":
    main()
