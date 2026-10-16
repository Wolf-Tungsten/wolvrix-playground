#!/usr/bin/env python3
"""Measure register-write recovery on the generated aggregate ROB SV."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path

import wolvrix


def attr(op: dict, name: str, default=None):
    value = op.get("attrs", {}).get(name, {})
    return value.get("v", value.get("vs", default))


def census(path: Path) -> dict:
    with path.open() as stream:
        design = json.load(stream)
    graph = next(g for g in design["graphs"] if g["symbol"] == "Rob")
    definitions = {value: op for op in graph["ops"] for value in op["out"]}
    arrays = {
        op["sym"]: Counter()
        for op in graph["ops"]
        if op["kind"] == "kRegister" and attr(op, "shape")
    }

    def is_constant(value: str) -> bool:
        for _ in range(128):
            op = definitions.get(value)
            if not op:
                return False
            if op["kind"] in ("kAssign", "kConcat") and len(op["in"]) == 1:
                value = op["in"][0]
                continue
            return op["kind"] == "kConstant"
        return False

    for op in graph["ops"]:
        symbol = attr(op, "regSymbol")
        if symbol not in arrays:
            continue
        kind = op["kind"]
        if kind == "kRegisterReadArrayPort":
            key = "static_reads" if is_constant(op["in"][0]) else "dynamic_reads"
        elif kind == "kRegisterWriteArrayPort":
            key = "static_writes" if is_constant(op["in"][1]) else "dynamic_writes"
        elif kind == "kRegisterWritePort":
            key = "whole_writes"
        else:
            continue
        arrays[symbol][key] += 1
    return {
        "operations": len(graph["ops"]),
        "arrays": {symbol: dict(counts) for symbol, counts in arrays.items()},
    }


def generated_dependencies(sv: Path) -> list[Path]:
    # CIRCT's generated instance declarations are at two-space indentation.
    # Pass the dependency closure as primary files so all modules share the
    # compilation unit containing XiangShan's global DPI declarations.
    pattern = re.compile(r"^  ([A-Za-z_][A-Za-z0-9_$]*)\s+[A-Za-z_][A-Za-z0-9_$]*\s*\(", re.MULTILINE)
    files = [sv.resolve()]
    seen = set(files)
    for source in files:
        for match in pattern.finditer(source.read_text()):
            child = source.parent / f"{match[1]}.sv"
            if child.is_file() and child not in seen:
                seen.add(child)
                files.append(child)
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sv", type=Path, default=Path("build/xs/rtl-aggr/rtl/Rob.sv"))
    parser.add_argument("--assert-v", type=Path,
                        default=Path("testcase/xiangshan/difftest/src/test/vsrc/common/assert.v"))
    parser.add_argument("--out", type=Path, default=Path("ptmp/rob-register-write"))
    parser.add_argument("--baseline", type=Path, help="reuse a previous baseline GRH snapshot")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    before = args.baseline or args.out / "before.json"
    after = args.out / "after.json"
    with wolvrix.Session() as session:
        verbose = bool(os.environ.get("WOLVRIX_MUXFOLD_DEBUG"))
        session.log_level = "info" if verbose else "warn"
        session.diagnostics_print_min_level = "error"
        if args.baseline:
            session.read_json_file(str(before), out_design="rob")
        else:
            print(f"Reading {args.sv}", flush=True)
            sources = [args.assert_v.resolve(), *generated_dependencies(args.sv)]
            (args.out / "rob.f").write_text("\n".join(map(str, sources)) + "\n")
            session.read_sv(
                None, out_design="rob",
                slang_args=["-f", str(args.out / "rob.f"), "--top", "Rob"],
            )
            session.run_pass("xmr-resolve", design="rob")
            session.run_pass("mux-tree-fold", design="rob")
            session.run_pass("grh.verify", design="rob")
            session.store_json(design="rob", output=str(before), top=["Rob"])
        print("Normalizing and folding guarded writes", flush=True)
        normalized = session.run_pass("register-write-normalize", design="rob", semantics="2state")
        folded = session.run_pass("mux-tree-fold", design="rob", guarded_writes="2state")
        if verbose:
            session.print_diagnostics(normalized + folded, min_level="info")
        session.run_pass("grh.verify", design="rob")
        session.store_json(design="rob", output=str(after), top=["Rob"])
    counts = {"before": census(before), "after": census(after)}
    (args.out / "census.json").write_text(json.dumps(counts, indent=2) + "\n")
    for stage, result in counts.items():
        print(stage, "ROB operations:", result["operations"])
        print(stage, "debug_exuData:", result["arrays"].get("debug_exuData"))
    for symbol, result in counts["after"]["arrays"].items():
        previous = counts["before"]["arrays"][symbol]
        if result.get("static_writes", 0) + result.get("dynamic_writes", 0) > \
                previous.get("static_writes", 0) + previous.get("dynamic_writes", 0):
            raise RuntimeError(f"{symbol}: write ports increased")
    debug = counts["after"]["arrays"]["debug_exuData"]
    if debug.get("static_reads", 0) or debug.get("static_writes", 0):
        raise RuntimeError("debug_exuData still has expanded accesses; see census.json")
    if debug.get("dynamic_reads") != 8 or debug.get("dynamic_writes") != 24:
        raise RuntimeError("debug_exuData functional accesses were not recovered")


if __name__ == "__main__":
    main()
