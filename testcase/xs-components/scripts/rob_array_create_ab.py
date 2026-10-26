#!/usr/bin/env python3
"""Isolated ROB arrayCreate evidence; invoked through rob-array-create-* make targets."""
import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
from collections import Counter
from pathlib import Path

TRACE_SHA = "cf8035e21cde579dbcf9ee0abced4f1b4c5d5c66260c9369689c225de83fddb1"
BASE_SHA = "70eebd9a99cff646a6335a777a6b123ce90f117e2e59a12d3e357741a58500c0"
CHECKSUM = "0x048c94f0d417ffac"
FIELDS = ("pdest", "rfWen", "fpWen")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(base, root):
    if base == root or base in root.parents or root in base.parents:
        raise RuntimeError("A/B directory must be separate from the preserved baseline")
    candidate = root / "candidate"
    candidate.mkdir(parents=True, exist_ok=True)
    (root / "baseline").mkdir(exist_ok=True)
    for name in ("rtl.f", "read_args.txt", "Rob_resolved.fir"):
        shutil.copy2(base / name, candidate / name)
    for name in ("gsim-model", "gsim-obj"):
        shutil.copytree(base / name, candidate / name, dirs_exist_ok=True)
    proof = {str(path): sha(path) for path in (
        base / "bench/rob_bench", base / "trace/rob_trace.bin", base / "trace/layout.json",
        base / "trace/fst_output_mask.bin", base / "rtl.f", base / "read_args.txt")}
    if proof[str(base / "bench/rob_bench")] != BASE_SHA:
        raise RuntimeError("preserved baseline executable changed")
    if proof[str(base / "trace/rob_trace.bin")] != TRACE_SHA:
        raise RuntimeError("CoreMark trace changed")
    (root / "inputs.json").write_text(json.dumps(proof, indent=2) + "\n")


def run_logged(command, log):
    with log.open("w") as stream:
        subprocess.run([str(x) for x in command], stdout=stream, stderr=subprocess.STDOUT, check=True)
    return log.read_text()


def compare_files(left, right):
    with left.open("rb") as a, right.open("rb") as b:
        header = a.read(24)
        if header != b.read(24) or len(header) != 24:
            raise RuntimeError("dump layout differs")
        magic, cycles, words = struct.unpack("<QQQ", header)
        if magic != 0x4152524159435231 or cycles != 100050 or words != 5491:
            raise RuntimeError("unexpected dump coverage")
        offset = 0
        while True:
            first, second = a.read(1024 * 1024), b.read(1024 * 1024)
            if first != second:
                index = next((i for i, (x, y) in enumerate(zip(first, second)) if x != y),
                             min(len(first), len(second)))
                byte = offset + index
                raise RuntimeError(f"old/new mismatch cycle={byte // (words * 8)} word={(byte // 8) % words}")
            if not first:
                break
            offset += len(first)
        if offset != cycles * words * 8:
            raise RuntimeError("truncated output dump")
    return {"cycles": cycles, "words_per_cycle": words, "exclusions": 0, "equal": True,
            "sha256": sha(left)}


def run(base, root, cpu, repeat):
    if repeat < 3:
        raise RuntimeError("at least three measured repeats required")
    trace = base / "trace/rob_trace.bin"
    mask = base / "trace/fst_output_mask.bin"
    candidate = root / "candidate"
    for arm in ("baseline", "candidate"):
        directory = root / arm
        run_logged(["taskset", "-c", cpu, directory / "dump_outputs", trace, directory / "all_outputs.bin"],
                   directory / "dump.log")
    comparison = compare_files(root / "baseline/all_outputs.bin", candidate / "all_outputs.bin")
    print("[ARRAY_CREATE_COMPARE] " + json.dumps(comparison), flush=True)
    run_logged(["taskset", "-c", cpu, candidate / "bench/rob_bench", "--trace", trace,
                "--trace-mask", mask, "--verify", "100050", "--vectors", "1", "--repeat", "1", "--model", "grhsim"],
               candidate / "verify_trace.log")
    results = {}
    for label, exe, model, directory in (
        ("gsim", base / "bench/rob_bench", "gsim", root / "baseline"),
        ("grhsim_old", base / "bench/rob_bench", "grhsim", root / "baseline"),
        ("grhsim_new", candidate / "bench/rob_bench", "grhsim", candidate)):
        text = run_logged(["taskset", "-c", cpu, exe, "--trace", trace, "--verify", "0",
                           "--repeat", str(repeat), "--model", model], directory / (label + ".log"))
        match = re.search(r"\[BENCH\].*?min_ms=([\d.]+) median_ms=([\d.]+).*?checksum=(\S+)", text)
        if not match or match[3] != CHECKSUM:
            raise RuntimeError(f"unexpected checksum/benchmark output for {label}")
        results[label] = {"min_ms": float(match[1]), "median_ms": float(match[2]), "checksum": match[3]}
        print(label + " " + json.dumps(results[label]), flush=True)
    if sha(base / "bench/rob_bench") != BASE_SHA or sha(trace) != TRACE_SHA:
        raise RuntimeError("baseline/trace modified during A/B")
    evidence = {"outputs": comparison, "cpu": cpu, "repeat": repeat, "warmup_per_arm": 1, "results": results,
                "candidate_binary_sha256": sha(candidate / "bench/rob_bench"),
                "new_over_old": results["grhsim_new"]["min_ms"] / results["grhsim_old"]["min_ms"],
                "new_over_gsim": results["grhsim_new"]["min_ms"] / results["gsim"]["min_ms"]}
    (root / "results.json").write_text(json.dumps(evidence, indent=2) + "\n")


def audit_ir(candidate):
    # The GRH store writes each op on its own line. Stream this 500 MB file
    # rather than retaining values, users and operations at the same time.
    count, targets = 0, []
    symbols = {"rab$_GEN_716__DOT__" + field for field in FIELDS}
    with (candidate / "emit_flat_grh.json").open() as stream:
        for line in stream:
            if '"kind": "kArrayCreate"' not in line:
                continue
            op = json.loads(line.strip().removesuffix(","))
            count += 1
            if symbols.intersection(op["out"]):
                targets.append({"op": op["sym"], "outputs": op["out"],
                                "operands": len(op["in"]), "source": op.get("loc")})
    if count == 0 or len(targets) != len(FIELDS):
        raise RuntimeError("raw SV ingest did not produce the target array constructors")
    with (candidate / "emit_grhsim.json").open() as stream:
        model = json.load(stream)
    strings = model["strings"]
    producers = {value: op for op in model["operations"] for value in op[5]}
    writes = {ref[1]: op for op in model["operations"]
              if strings[op[1] - 1] == "core.output.write"
              for ref in op[6] if ref[0] == "output"}
    outputs = []
    for port in model["outputs"]:
        if strings[port[1] - 1] not in {"io_diffCommits__DOT__info__DOT__" + f for f in FIELDS}:
            continue
        value, chain = writes[port[0]][4][0], []
        while True:
            op = producers[value]
            name = strings[op[1] - 1]
            chain.append({"value": value, "op": op[0], "kind": name,
                          "type": model["types"][model["values"][value - 1][1] - 1],
                          "operands": len(op[4])})
            if name != "core.compute.assign":
                break
            value = op[4][0]
        if chain[-1]["kind"] != "core.compute.arrayCreate" or chain[-1]["operands"] != 520:
            raise RuntimeError("target output still depends on a packed producer")
        outputs.append({"name": strings[port[1] - 1], "chain": chain})
    if len(outputs) != len(FIELDS):
        raise RuntimeError("missing target outputs")
    return {"grh_array_creates": count, "grh_targets": targets,
            "grhsim_array_creates": sum(strings[op[1] - 1] == "core.compute.arrayCreate"
                                        for op in model["operations"]),
            "outputs": outputs}


def audit_cpp(directory, destination):
    targets, packed, function_ints = {}, {}, {}
    for path in sorted((directory / "grhsim-model").glob("*")):
        if path.suffix not in (".cpp", ".hpp"):
            continue
        owner = ""
        for number, line in enumerate(path.read_text().splitlines(), 1):
            function = re.match(r"void GrhSIM_Rob::(\w+)\(", line)
            if function:
                owner = function[1]
            for width in re.findall(r"_BitInt\s*\(\s*(4160|520)\s*\)", line):
                packed[width] = packed.get(width, 0) + 1
            if not owner.startswith("pOutput_"):
                continue
            for width in re.findall(r"_BitInt\s*\(\s*(\d+)\s*\)", line):
                counts = function_ints.setdefault(owner, Counter())
                counts[width] += 1
            for field in FIELDS:
                if "this->io_diffCommits__DOT__info__DOT__" + field + "[" in line:
                    if field in targets:
                        raise RuntimeError("ambiguous target C++ store")
                    targets[field] = {"file": str(path), "line": number, "function": owner,
                                      "store": line.strip(), "source_sha256": sha(path)}
    if set(targets) != set(FIELDS):
        raise RuntimeError("target C++ output stores not found")
    functions = {target["function"] for target in targets.values()}
    binary = directory / "bench/rob_bench"
    symbols = subprocess.run(["nm", "-S", "--defined-only", str(binary)],
                             capture_output=True, text=True, check=True).stdout
    machine = {}
    for line in symbols.splitlines():
        columns = line.split()
        if len(columns) != 4 or not columns[3].startswith("_ZN10GrhSIM_Rob"):
            continue
        for function in functions:
            if str(len(function)) + function + "E" not in columns[3]:
                continue
            asm = run_logged(["objdump", "-d", "--no-show-raw-insn",
                              "--disassemble=" + columns[3], binary], destination / (function + ".asm"))
            allocations = re.findall(r"sub\s+\$0x([0-9a-f]+),%rsp", asm)
            machine[function] = {"code_bytes": int(columns[1], 16),
                                 "rsp_sub_bytes": [int(amount, 16) for amount in allocations],
                                 "instructions": len(re.findall(r"^\s*[0-9a-f]+:\s+\S+", asm, re.M))}
    if set(machine) != functions or any(item["instructions"] == 0 for item in machine.values()):
        raise RuntimeError("target machine code symbols not found")
    return {"outputs": targets, "total_width_bitint_mentions": packed,
            "target_function_bitint_mentions": {name: dict(function_ints.get(name, {})) for name in functions},
            "machine": machine}


def audit_profile(directory, functions):
    periods, samples = Counter(), Counter()
    with (directory / "samples.txt").open() as stream:
        for line in stream:
            columns = line.split()
            if len(columns) < 3:
                raise RuntimeError("unexpected perf script row")
            symbol = " ".join(columns[2:]).rsplit("+0x", 1)[0]
            periods[symbol] += int(columns[0])
            samples[symbol] += 1
    total = sum(periods.values())
    output = sum(period for symbol, period in periods.items() if symbol.startswith("GrhSIM_Rob::pOutput"))
    targets = {symbol: {"percent": 100 * periods[symbol] / total, "samples": samples[symbol]}
               for symbol in periods if any(symbol.startswith("GrhSIM_Rob::" + name + "(")
                                             for name in functions)}
    report = (directory / "report.txt").read_text()
    lost = re.search(r"# Total Lost Samples:\s*(\d+)", report)
    if not lost or CHECKSUM not in (directory / "run.log").read_text():
        raise RuntimeError("missing perf integrity evidence")
    return {"samples": sum(samples.values()), "period": total, "lost_samples": int(lost[1]),
            "all_output_percent": 100 * output / total, "targets": targets,
            "top_symbols": [{"symbol": symbol, "percent": 100 * period / total}
                            for symbol, period in periods.most_common(8)]}


def audit(base, root):
    evidence = root / "evidence"
    evidence.mkdir(exist_ok=True)
    ir = audit_ir(root / "candidate")
    cpp = {}
    for arm, directory in (("baseline", base), ("candidate", root / "candidate")):
        destination = evidence / arm
        destination.mkdir(exist_ok=True)
        cpp[arm] = audit_cpp(directory, destination)
    if (cpp["candidate"]["total_width_bitint_mentions"] or
            any(cpp["candidate"]["target_function_bitint_mentions"].values())):
        raise RuntimeError("target total-width integers remain in candidate sources")
    proofs = {str(path): sha(path) for path in (
        base / "bench/rob_bench", root / "candidate/bench/rob_bench",
        base / "trace/layout.json", base / "trace/fst_output_mask.bin",
        base / "rtl.f", base / "read_args.txt", root / "candidate/emit_flat_grh.json",
        root / "candidate/emit_grhsim.json", root / "candidate/emit_roundtrip.json",
        root / "candidate/bench/rob_bench.cpp", root / "candidate/grhsim_model_build.log")}
    for name in ("rtl.f", "read_args.txt", "Rob_resolved.fir", "bench/rob_bench.cpp"):
        if sha(base / name) != sha(root / "candidate" / name):
            raise RuntimeError("candidate input differs from baseline: " + name)
    for line in (base / "rtl.f").read_text().splitlines():
        proofs[line] = sha(Path(line))
    runs = {}
    for label, directory in (("gsim", root / "baseline"), ("grhsim_old", root / "baseline"),
                             ("grhsim_new", root / "candidate")):
        matches = re.findall(r"\[BENCH_RUN\].*?run=(\d+).*?ms=([\d.]+).*?checksum=(\S+)",
                             (directory / (label + ".log")).read_text())
        if len(matches) < 3 or any(checksum != CHECKSUM for _, _, checksum in matches):
            raise RuntimeError("missing measured runs or inconsistent checksums: " + label)
        runs[label] = [float(ms) for _, ms, _ in matches]
    profiles = {}
    for arm, directory in (("baseline", base / "exceptionvec-profile-20261023"),
                           ("candidate", root / "profile")):
        if (directory / "samples.txt").exists():
            profiles[arm] = audit_profile(directory, cpp[arm]["machine"])
    result = {"ir": ir, "cpp": cpp, "sources_sha256": proofs, "measured_runs_ms": runs,
              "profiles": profiles}
    (evidence / "audit.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"grh_array_creates": ir["grh_array_creates"],
                      "grhsim_array_creates": ir["grhsim_array_creates"],
                      "machine": {arm: data["machine"] for arm, data in cpp.items()},
                      "profiles": profiles}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "audit"))
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--cpu", default="0")
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    base, root = args.baseline.resolve(), args.work.resolve()
    if args.action == "prepare":
        prepare(base, root)
    elif args.action == "audit":
        audit(base, root)
    else:
        run(base, root, args.cpu, args.repeat)
