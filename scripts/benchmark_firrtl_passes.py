"""Compare native flatten/simplify implementations with a fixed FIRRTL fixture."""

import argparse
import hashlib
import json
import select
import time
from pathlib import Path

import wolvrix
from grhsim_provenance import loaded_libraries


def checked(diagnostics, name):
    if any(str(entry.get("kind", "")).lower() == "error" for entry in diagnostics):
        raise RuntimeError(f"{name}: {diagnostics}")


def fixture(instances, terms, unique):
    lines = ["FIRRTL version 6.0.0", "circuit top :", "  module leaf :",
             "    input clk : Clock", "    input reset : UInt<1>",
             "    input a : UInt<32>", "    input b : UInt<32>",
             "    output y : UInt<32>",
             "    regreset q : UInt<32>, clk, reset, UInt<32>(1)",
             "    connect q, add(q, a)", "    node acc0 = q"]
    for i in range(terms):
        salt = i if unique else i % 8
        lines += [f"    node d{i} = xor(a, b)",
                  f"    node e{i} = or(d{i}, UInt<32>({salt}))",
                  f"    node f{i} = add(e{i}, UInt<32>({i + 1}))",
                  f"    node acc{i + 1} = xor(acc{i}, f{i})"]
    lines += [f"    connect y, acc{terms}", "  public module top :",
              "    input clk : Clock", "    input reset : UInt<1>",
              f"    input a : UInt<32>[{instances}]", "    input b : UInt<32>",
              f"    output y : UInt<32>[{instances}]"]
    for i in range(instances):
        name = f"repeated_instance_{i:04d}"
        lines += [f"    inst {name} of leaf", f"    connect {name}.clk, clk",
                  f"    connect {name}.reset, reset", f"    connect {name}.a, a[{i}]",
                  f"    connect {name}.b, b", f"    connect y[{i}], {name}.y"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--source", type=Path, help="shared fixture path for byte-identical source locations")
    parser.add_argument("--compare", type=Path, help="reference report whose graph hashes must match")
    parser.add_argument("--perf-control", type=Path)
    parser.add_argument("--perf-ack", type=Path)
    parser.add_argument("--profile-pass", default="grhsim-simplify")
    parser.add_argument("--instances", type=int, default=32)
    parser.add_argument("--terms", type=int, default=1024)
    parser.add_argument("--unique", action="store_true")
    parser.add_argument("--node-annotations", choices=("on", "off"), default="off")
    args = parser.parse_args()
    if bool(args.perf_control) != bool(args.perf_ack):
        parser.error("perf control and acknowledgement FIFOs must be supplied together")
    root = Path(__file__).resolve().parents[1]
    work = args.work.resolve()
    if not work.is_relative_to(root / "ptmp") or min(args.instances, args.terms) < 1:
        parser.error("work must be under repository ptmp; sizes must be positive")
    work.mkdir(parents=True, exist_ok=True)
    source = args.source.resolve() if args.source else work / "input.fir"
    if not source.is_relative_to(root / "ptmp"):
        parser.error("source must be under repository ptmp")
    content = fixture(args.instances, args.terms, args.unique)
    if source.exists() and source.read_text() != content:
        parser.error("existing fixture differs from requested configuration")
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(content)
    reference = json.loads(args.compare.read_text()) if args.compare else None
    report = {"fixture_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "source": str(source),
              "package": str(Path(wolvrix.__file__).resolve()),
              "loaded_libraries": loaded_libraries(),
              "configuration": {key: str(value) if isinstance(value, Path) else value
                                for key, value in vars(args).items()},
              "scope": "isolated fixture comparison; whole-chip generation retains its own 20-minute limit",
              "stages": []}
    def control(command):
        if not args.perf_control:
            return
        with args.perf_control.open("r+b", buffering=0) as commands, \
                args.perf_ack.open("r+b", buffering=0) as acknowledgements:
            commands.write((command + "\n").encode())
            if not select.select([acknowledgements], [], [], 10)[0] or \
                    acknowledgements.read(64).strip(b"\0\n") != b"ack":
                raise RuntimeError("perf control acknowledgement failed")
    with wolvrix.Session() as session:
        session.diagnostics_raise_min_level = "none"
        session.log_level = "info"
        started = time.perf_counter()
        checked(session.read_firrtl(str(source), firrtl_options={
            "node_annotations": args.node_annotations == "on"}), "ingest")
        report["ingest_s"] = time.perf_counter() - started
        for name, options in [("hier-flatten", {}), ("grh-to-grhsim", {"logic_domain": "2state"}),
                              ("grhsim-simplify", {})]:
            if name == args.profile_pass:
                control("enable")
            started = time.perf_counter()
            try:
                diagnostics = session.run_pass(name, design="design.main", **options)
                elapsed = time.perf_counter() - started
            finally:
                if name == args.profile_pass:
                    control("disable")
            checked(diagnostics, name)
            session.print_diagnostics(diagnostics, min_level="info")
            path = work / f"{name}.json"
            checked(session.store_json(design="design.main", top=["top"],
                output=str(path), mode="pretty-compact"), "store")
            data = path.read_bytes()
            graph = json.loads(data)["graphs"][0]
            row = {"pass": name, "wall_s": elapsed, "sha256": hashlib.sha256(data).hexdigest(),
                   "operations": len(graph["ops"]), "values": len(graph["vals"]),
                   "diagnostics": diagnostics}
            report["stages"].append(row)
            if reference:
                expected = next(stage for stage in reference["stages"] if stage["pass"] == name)
                for key in ("sha256", "operations", "values", "diagnostics"):
                    if row[key] != expected[key]:
                        raise RuntimeError(f"{name}: reference {key} differs")
            print(json.dumps({key: value for key, value in row.items() if key != "diagnostics"}), flush=True)
            (work / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
