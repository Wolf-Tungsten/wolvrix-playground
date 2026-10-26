"""Map a plain Verilator ROB waveform onto the aggregate replay records."""

import argparse
from collections import defaultdict
import csv
import json
import mmap
from pathlib import Path
import re
import struct


def validate_reference(path, expected_cycles):
    text = path.read_text(errors="replace")
    endpoint = f"[CYCLE_LIMIT] cycles={expected_cycles} max_cycles={expected_cycles}"
    if endpoint not in text or "EXCEEDING CYCLE/INSTR LIMIT" not in text:
        raise RuntimeError("reference did not complete the requested cycle window")
    if re.search(r"Assertion failed|HIT BAD TRAP|\bABORT\b|DIFFTEST.*MISMATCH", text, re.I):
        raise RuntimeError("reference log contains an assertion or difftest failure")
    return {"cycle_limit": expected_cycles,
            "commit_records": len(re.findall(r"\[\d+\] commit cycle \d+", text))}


def constant_zero_reason(name):
    if re.fullmatch(r"io_enq_req_[0-7]_bits_replayInst", name):
        return "Bundles.scala: EnqRobUop.connectEnqRobUop assigns replayInst := false.B"
    if re.fullmatch(r"io_exuWriteback_(?:[0-8]|1[3-9]|20|21)_bits_debug_(?:isMMIO|isNCIO|isPerfCnt|paddr)", name):
        return "ExeUnit.scala initializes non-memory debug to zero; absent CSR isPerfCnt is false"
    if re.fullmatch(r"io_exuWriteback_(?:12|13|17|18|19|21|22|23)_bits_data", name):
        return "plain reference specializes unused writeback data to zero (debug_exuData update branches)"
    if re.fullmatch(r"io_writeback_(?:13|20|21|22|23)_bits_exceptionVec_\d+", name):
        return "Bundles.scala: fromExuOutput zero-fills unsupported exception bits; remaining bits are traced"
    return None


def check_constant_prefix(path, leaves, in_words, out_words):
    """Additional evidence from the independent aggregate port tap prefix."""
    stride = 8 * (1 + in_words + out_words)
    with path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        magic, cycles, ni, no = struct.unpack_from("<8sQII", data)
        if (magic, ni, no) != (b"RobTrc01", in_words, out_words):
            raise RuntimeError("constant-check trace layout differs")
        for leaf in leaves:
            for cycle in range(cycles):
                pos = 24 + cycle * stride + 8 * (1 + leaf["offset"])
                if any(struct.unpack_from("<" + "Q" * leaf["words"], data, pos)):
                    raise RuntimeError(f"nonzero proposed constant: {leaf['name']} at {cycle}")
    return cycles


def computational_input_uses(model_dir):
    """Ignore initialization, accessors and disabled ENABLE_LOG diagnostics."""
    uses = defaultdict(set)
    paths = sorted(model_dir.glob("Rob*.cpp"))
    if not paths:
        raise RuntimeError(f"no generated gsim sources in {model_dir}")
    for path in paths:
        method = ""
        log_depth = 0
        for line in path.read_text().splitlines():
            if re.match(r"\s*#ifdef ENABLE_LOG", line):
                log_depth = 1
                continue
            if log_depth:
                if re.match(r"\s*#if", line):
                    log_depth += 1
                elif re.match(r"\s*#endif", line):
                    log_depth -= 1
                continue
            match = re.match(r".*\bSRob::(\w+)\(", line)
            if match:
                method = match[1]
            if not (method.startswith("subStep") or method == "step"):
                continue
            for match in re.finditer(r"\b(io__DOT__[\w$]+)((?:\[[^\]]+\])*)", line):
                indices = re.findall(r"\[([^\]]+)\]", match[2])
                key = tuple(int(i) for i in indices) if all(i.isdigit() for i in indices) else None
                uses[match[1]].add(key)
    return uses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signals", type=Path, required=True)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--pairing", type=Path, required=True)
    parser.add_argument("--gsim-dir", type=Path, required=True)
    parser.add_argument("--mask", type=Path, required=True)
    parser.add_argument("--constant-check", type=Path)
    parser.add_argument("--reference-log", type=Path)
    parser.add_argument("--cycles", type=int, default=100000)
    args = parser.parse_args()
    layout = json.loads(args.layout.read_text())
    signals = {}
    for line in args.signals.read_text().splitlines():
        match = re.match(r"\s*(\d+)\s+(\d+)\s+(.+)$", line)
        if not match:
            continue
        path = match[3]
        if ".rob." not in path:
            continue
        name = path.split(".rob.", 1)[1]
        if "." not in name:
            signals[name] = (int(match[1]), int(match[2]))
    pairing = {row["logical_name"]: row for row in csv.DictReader(
        args.pairing.open(), delimiter="\t")}
    uses = computational_input_uses(args.gsim_dir)
    audit = {"mapped": [], "dead_inputs": [], "constant_inputs": [],
             "unobserved_outputs": [], "zero_extended": [], "missing": []}
    if args.reference_log:
        audit["reference"] = validate_reference(args.reference_log, args.cycles)
    mask = [0] * layout["out_words"]
    rows = []
    for role, group in (("input", layout["inputs"]), ("output", layout["outputs"])):
        for leaf in group:
            name = leaf.get("trace_signal", leaf["name"])
            bit = leaf.get("trace_bit_offset", 0)
            found = signals.get(name)
            if leaf["name"] in signals:
                found = signals[leaf["name"]]
                bit = 0
            if not found:
                if role == "output":
                    audit["unobserved_outputs"].append(leaf)
                    continue
                pair = pairing[leaf["name"]]
                accessor = pair["gsim_accessor"]
                index = tuple(int(i) for i in pair["gsim_elem"].split("_")) if pair["gsim_elem"] != "-" else ()
                refs = uses.get(accessor, set())
                if accessor != "-" and None not in refs and index not in refs:
                    audit["dead_inputs"].append({**leaf, "accessor": accessor, "index": index,
                                                "proof": "no computational read in generated gsim model"})
                    continue
                reason = constant_zero_reason(leaf["name"])
                if role == "input" and reason:
                    audit["constant_inputs"].append({**leaf, "proof": reason})
                    continue
                audit["missing"].append({"role": role, **leaf})
                continue
            handle, width = found
            if bit < 0 or bit + leaf["width"] > width:
                raise RuntimeError(f"slice outside FST signal: {leaf['name']}")
            offset = leaf["offset"]
            if offset is not None:
                offset += 1 if role == "input" else 1 + layout["in_words"]
            rows.append((handle, bit, leaf["width"], -1 if offset is None else offset,
                         leaf["words"], leaf["name"]))
            if role == "output":
                mask[leaf["offset"]:leaf["offset"] + leaf["words"]] = [1] * leaf["words"]
            audit["mapped"].append({"name": leaf["name"], "signal": name,
                                    "handle": handle, "bit": bit, "source_width": width})
    for name, offset in (("clock", -2), ("reset", 0)):
        handle, width = signals[name]
        rows.append((handle, 0, width, offset, 1, name))
    args.audit.write_text(json.dumps(audit, indent=2) + "\n")
    if args.constant_check:
        audit["constant_check_cycles"] = check_constant_prefix(
            args.constant_check, audit["constant_inputs"], layout["in_words"], layout["out_words"])
        args.audit.write_text(json.dumps(audit, indent=2) + "\n")
    print(" ".join(f"{key}={len(value)}" for key, value in audit.items() if isinstance(value, list)))
    for leaf in audit["missing"][:30]:
        print(f"missing {leaf['role']} {leaf['name']} width={leaf['width']} "
              f"gsim_live={leaf.get('gsim_live')} excluded={leaf.get('excluded')}")
    if audit["missing"]:
        raise RuntimeError("unresolved live input ports")
    args.mask.write_bytes(struct.pack("<" + "Q" * len(mask), *mask))
    args.out.write_text(f"{layout['in_words']} {layout['out_words']}\n" +
                        "".join("\t".join(map(str, row)) + "\n" for row in rows))


if __name__ == "__main__":
    main()
