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
    parser.add_argument("--cpu-target-batch-count", type=int, default=0)
    args = parser.parse_args()
    if args.cpu_target_batch_count < 0:
        parser.error("cpu target batch count must be nonnegative")
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
        if args.pack_bit_registers:
            actions = [
                lambda: session.run_grhsim_pass("grhsim.pack-bit-registers", model="grhsim.main"),
            ] + [
                lambda name=name: session.run_grhsim_pass(name, model="grhsim.main", **(
                    {"target_batch_count": args.cpu_target_batch_count} if name == "cpu.st.pack-emit-functions" else {}))
                for name in CPU_MAPPING_PIPELINE
            ]
        else:
            actions = []
        for action in actions + [
            lambda: session.run_grhsim_pass("cpu.st.emit-cpp", model="grhsim.main", output=str(flow / "model")),
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
