"""Emit an archived mapped GrhSIM checkpoint for diagnostic candidate screening."""

import argparse
from pathlib import Path

import wolvrix

from wolvrix_xs_grhsim_ir import CPU_MAPPING_PIPELINE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--flow", type=Path, required=True)
    parser.add_argument("--pack-bit-registers", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--remap", action="store_true", help="rebuild CPU mapping without a semantic transform")
    parser.add_argument("--bitwise-muxes", action="store_true")
    parser.add_argument("--mux-chain-fold", action="store_true")
    parser.add_argument("--dynamic-stats", action="store_true",
                        help="emit diagnostic dynamic counters into the model (screening builds only)")
    parser.add_argument("--commit-compact-walk", action="store_true",
                        help="emit uniform u64 direct-commit pflag bytes as branch-free change scans")
    parser.add_argument("--commit-mem-walk", action="store_true",
                        help="hoist shared snapshot guards of commit memWrite runs and cache their boundary enables")
    parser.add_argument("--used-bits", action="store_true",
                        help="run grhsim.used-bits (dead-cone elimination + width narrowing), then remap")
    parser.add_argument("--max-op-in-compute-supernode", type=int,
                        help="override the compute supernode op cap during remapping")
    parser.add_argument("--cpu-target-batch-count", type=int, default=0)
    args = parser.parse_args()
    if args.cpu_target_batch_count < 0:
        parser.error("cpu target batch count must be nonnegative")
    if args.max_op_in_compute_supernode is not None and args.max_op_in_compute_supernode <= 0:
        parser.error("max op in compute supernode must be positive")
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
            if name == "cpu.st.pack-emit-functions":
                options["target_batch_count"] = args.cpu_target_batch_count
            if name == "cpu.st.merge-compute-supernodes" and args.max_op_in_compute_supernode is not None:
                options["max_op_in_compute_supernode"] = args.max_op_in_compute_supernode
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
        if args.used_bits:
            actions += [lambda: session.run_grhsim_pass("grhsim.used-bits", model="grhsim.main")]
            actions += [
                lambda name=name: session.run_grhsim_pass(name, model="grhsim.main", **mapping_options(name))
                for name in CPU_MAPPING_PIPELINE
            ]
        emit_options = {"model": "grhsim.main", "output": str(flow / "model")}
        if args.dynamic_stats:
            emit_options["dynamic_stats"] = True
        if args.commit_compact_walk:
            emit_options["commit_compact_walk"] = True
        if args.commit_mem_walk:
            emit_options["commit_mem_walk"] = True
        for action in actions + [
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
