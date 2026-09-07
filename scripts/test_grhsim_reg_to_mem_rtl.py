from __future__ import annotations

import argparse
import csv
from pathlib import Path

import wolvrix

from wolvrix_xs_grhsim_ir import CPU_PIPELINE, GRH_PIPELINE, require_ok


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    # Each invocation has its own output directory, preserving earlier test artifacts.
    report = args.output / "candidates.tsv"
    with wolvrix.Session() as session:
        session.diagnostics_raise_min_level = "none"
        require_ok(session.read_sv(str(args.source), out_design="design.main",
                                  slang_args=["--top", "reg_to_mem_tables"]), "read table RTL")
        for name, options in GRH_PIPELINE:
            require_ok(session.run_pass(name, design="design.main", **options), name)
        require_ok(session.lower_grhsim(design="design.main", out_model="grhsim.main",
                                       top="reg_to_mem_tables", logic_domain="2-state",
                                       keep_origins=False, consume=True), "lower table RTL")
        for name in CPU_PIPELINE:
            # Small fixtures exercise transformations regardless of their runtime
            # profitability; production flow retains default cost selection.
            options = {"report": str(report), "enable_cost_selection": False} if name == "grhsim.reg-to-mem" else {}
            require_ok(session.run_grhsim_pass(name, model="grhsim.main", **options), name)
        require_ok(session.store_grhsim(model="grhsim.main", output=str(args.output / "model.json")), "store table IR")
        require_ok(session.run_grhsim_pass("cpu.st.emit-cpp", model="grhsim.main",
                                          output=str(args.output / "model")), "emit table C++")
    with report.open() as stream:
        groups = list(csv.DictReader(stream, delimiter="\t"))
    for field in ("phr", "useful", "ftq", "rename_entry"):
        if not any(row["status"] == "merged" and field in row["first_state"] for row in groups):
            raise RuntimeError(f"no committed write recovery for {field}; inspect {report}")


if __name__ == "__main__":
    main()
