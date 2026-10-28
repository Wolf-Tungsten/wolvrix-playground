#!/usr/bin/env python3
"""Locate sampled PCs in retained machine code; instruction buckets are descriptive."""

import argparse
from bisect import bisect_right
from collections import Counter, deque
import json
from pathlib import Path
import re
import subprocess

from grhsim_cpu_profile import read_profile, six_phase_category, symbols


def instruction(line):
    match = re.match(r"\s*([0-9a-f]+):\s+([a-z][a-z0-9.]*)\s*(.*?)\s*$", line)
    if not match:
        return None
    address, mnemonic, operands = match.groups()
    return int(address, 16), mnemonic, operands


def bucket(mnemonic, operands):
    if mnemonic.startswith("ret"):
        return "return"
    if mnemonic.startswith("call"):
        return "call"
    if mnemonic.startswith("j") or mnemonic.startswith("loop"):
        return "branch"
    if mnemonic.startswith("nop") or mnemonic == "data16":
        return "padding"
    if mnemonic.startswith(("push", "pop")) or mnemonic == "leave":
        return "stack"
    if mnemonic.startswith("lea"):
        return "address_arithmetic"
    if mnemonic.startswith(("mov", "vmov", "kmov")):
        return "memory_move" if "(" in operands else "register_move"
    if mnemonic.startswith(("rep", "stos")):
        return "string_operation"
    if mnemonic.startswith(("cmp", "test", "vptest", "kortest", "ucom")):
        return "test_compare"
    return "other_memory" if "(" in operands else "other_register"


def register_name(value):
    match = re.fullmatch(r"%([a-z0-9]+)", value.strip())
    if not match:
        return None
    name = match[1]
    for full, aliases in {"rax": ("rax", "eax", "ax", "al", "ah"),
                          "rbx": ("rbx", "ebx", "bx", "bl", "bh"),
                          "rcx": ("rcx", "ecx", "cx", "cl", "ch"),
                          "rdx": ("rdx", "edx", "dx", "dl", "dh"),
                          "rdi": ("rdi", "edi", "di", "dil"),
                          "rsi": ("rsi", "esi", "si", "sil"),
                          "rbp": ("rbp", "ebp", "bp", "bpl"),
                          "rsp": ("rsp", "esp", "sp", "spl")}.items():
        if name in aliases:
            return full
    match = re.fullmatch(r"(r\d+)[dwb]?", name)
    return match[1] if match else name


def operands(text):
    result, begin, depth = [], 0, 0
    text = text.split("#", 1)[0]
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            result.append(text[begin:index].strip())
            begin = index + 1
    result.append(text[begin:].strip())
    return result


def full_register_write(value):
    # A byte/word destination leaves unknown upper register bits. A 32-bit
    # write clears the upper bits; a 64-bit write defines the full register.
    return bool(re.fullmatch(r"%(?:e(?:ax|bx|cx|dx|di|si|bp|sp)|r(?:ax|bx|cx|dx|di|si|bp|sp|\d+)|r\d+d)", value))


def constant_block_scan(name, instructions, samples, fields):
    """Track scalar constant loads within one basic block, using stable aliases."""
    writes, calls, targets = {}, False, set()
    for index, (_, opcode, text) in enumerate(instructions):
        args = operands(text)
        if opcode.startswith("call"):
            calls = True
        if opcode.startswith("j"):
            match = re.match(r"([0-9a-f]+)\b", text)
            if match:
                targets.add(int(match[1], 16))
        if not opcode.startswith(("j", "ret", "call", "cmp", "test", "push", "nop", "pop")):
            destination = register_name(args[-1])
            if destination:
                writes.setdefault(destination, []).append(index)
    aliases = {"rdi": -1} if not calls and "rdi" not in writes else {}
    initial = {"rdi"}
    for index, (_, opcode, text) in enumerate(instructions):
        if opcode.startswith(("j", "call", "ret")):
            break
        args = operands(text)
        if opcode == "mov" and len(args) == 2:
            source, destination = register_name(args[0]), register_name(args[1])
            if source in initial and destination in {"rbx", "rbp", "r12", "r13", "r14", "r15"} and writes.get(destination) == [index]:
                aliases[destination] = index
                initial.add(destination)
    known, constant_flags, rows = {}, set(), []
    for index, (pc, opcode, text) in enumerate(instructions):
        if pc in targets:
            known, constant_flags = {}, set()
        args = operands(text)
        registers = {register_name("%" + item) for item in re.findall(r"%([a-z0-9]+)", text.split("#", 1)[0])}
        source_fields = set().union(*(known[reg] for reg in registers if reg in known))
        direct = None
        for argument_index, argument in enumerate(args):
            match = re.fullmatch(r"(0x[0-9a-f]+|[0-9]+)?\(%(r\w+)\)", argument)
            if not match or match[2] not in aliases or index <= aliases[match[2]]:
                continue
            if opcode.startswith(("lea", "pop", "push")) or (opcode.startswith("mov") and argument_index == len(args) - 1):
                continue
            direct = fields.get(int(match[1], 0) if match[1] else 0)
            if direct:
                break
        category = None
        if opcode.startswith("j") and opcode != "jmp" and constant_flags:
            category, source_fields = "constant_condition_branch", constant_flags
        elif source_fields and not direct:
            if opcode.startswith(("cmp", "test")):
                category = "constant_register_compare"
            elif opcode.startswith(("shl", "shr", "sar", "sal", "shlx", "shrx", "sarx")):
                category = "constant_register_shift"
            elif opcode.startswith("lea"):
                category = "constant_register_address"
            elif "(" in text:
                category = "constant_register_memory_operand"
            else:
                category = "constant_register_other"
        count = samples.get(pc, 0)
        if count and category:
            rows.append({"symbol": name, "pc": hex(pc), "samples": count, "category": category,
                         "instruction": opcode + " " + text, "source_fields": sorted(source_fields)})
        if opcode.startswith(("cmp", "test")):
            all_constant = all(argument.startswith("$") or register_name(argument) in known for argument in args)
            constant_flags = source_fields if all_constant else set()
        elif not opcode.startswith(("mov", "lea", "j", "nop", "push", "pop")):
            constant_flags = set()
        if opcode.startswith(("j", "call", "ret")):
            known, constant_flags = {}, set()
            continue
        if opcode.startswith(("cmp", "test", "push", "nop")):
            continue
        destination = register_name(args[-1])
        if destination:
            known.pop(destination, None)
            if direct and opcode.startswith("mov") and len(args) == 2 and "(" in args[0] and full_register_write(args[-1]):
                known[destination] = {direct}
    return rows


def constant_neighborhoods(path, names, summary):
    """Associate existing direct-load evidence with sampled next instructions.

    This deliberately makes no claim that the instruction or its entire sampled
    cost disappears. It does not propagate across branches or register writes.
    """
    report = json.loads(path.read_text())
    direct_pcs = {int(row["pc"], 16) for row in report["matches"]}
    rows = {}
    for source in report["matches"]:
        if not re.fullmatch(r"bool|std::u?int(?:8|16|32|64)_t", source["field"]["type"]):
            continue
        opcode, operands = source["instruction"].split(" ", 1)
        if not opcode.startswith("mov"):
            continue
        tracked = register_name(operands.rsplit(",", 1)[-1])
        if tracked is None or not full_register_write(operands.rsplit(",", 1)[-1].strip()):
            continue
        symbol = source["function"]
        start, _ = names[symbol]
        pending_compare = False
        for line in source["next"]:
            item = instruction(line)
            if item is None:
                break
            pc, mnemonic, arguments = item
            registers = {register_name("%" + name) for name in re.findall(r"%([a-z0-9]+)", arguments)}
            category = None
            if mnemonic.startswith("j"):
                if pending_compare and mnemonic != "jmp":
                    category = "branch_after_constant_register_compare"
            elif mnemonic.startswith(("cmp", "test")) and tracked in registers:
                category = "constant_register_compare"
                pending_compare = True
            else:
                pending_compare = False
                if tracked in registers:
                    category = "constant_register_memory_operand" if "(" in arguments else "constant_register_operand"
            count = summary["offsets"].get(symbol, {}).get(str(pc - start), 0)
            if category and count and pc not in direct_pcs:
                row = rows.setdefault(pc, {"symbol": symbol, "offset": pc - start,
                                          "samples": count, "category": category,
                                          "instruction": f"{mnemonic} {arguments}", "source_fields": []})
                if source["field"]["field"] not in row["source_fields"]:
                    row["source_fields"].append(source["field"]["field"])
            if mnemonic.startswith(("j", "call", "ret")):
                break
            if not mnemonic.startswith(("cmp", "test", "push", "nop")):
                destination = register_name(arguments.rsplit(",", 1)[-1])
                if destination == tracked:
                    break
    counts = Counter()
    for row in rows.values():
        counts[row["category"]] += row["samples"]
    return {"samples_excluding_direct_reads": sum(row["samples"] for row in rows.values()),
            "categories": dict(counts), "pcs": sorted(rows.values(), key=lambda row: -row["samples"]),
            "caution": "Only next four linear instructions after an already sampled scalar constant load; no CFG proof, no verified candidate coverage, no eliminated-cost estimate."}


def describe(args):
    summary = json.loads(args.summary.read_text())
    native = symbols(args.binary)
    names = {name: (start, size) for start, (size, name) in native.items()}
    focus = re.compile(args.focus_symbol) if args.focus_symbol else None
    sampled = {}
    selected_names = set()
    for name, offsets in summary["offsets"].items():
        if focus and not focus.search(name):
            continue
        selected_names.add(name)
        if name not in names:
            raise ValueError(f"sampled symbol absent: {name}")
        start, size = names[name]
        for offset, count in offsets.items():
            offset = int(offset)
            if not 0 <= offset < size:
                raise ValueError(f"sample outside symbol: {name}+{offset}")
            sampled[start + offset] = (name, count)
    found, categories, mnemonics, rows = set(), {}, Counter(), []
    control_rows = []
    constant_fields = {}
    if args.constant_control_scan:
        if not args.constant_report or args.skip_disassembly:
            raise ValueError("constant control scan needs a constant report and disassembly")
        for row in json.loads(args.constant_report.read_text())["matches"]:
            if re.fullmatch(r"bool|std::u?int(?:8|16|32|64)_t", row["field"]["type"]):
                constant_fields[row["field"]["begin"]] = row["field"]["field"]
    previous = deque(maxlen=4)
    spans = []
    if focus:
        for start, size in sorted(names[name] for name in summary["offsets"] if focus.search(name)):
            if spans and start <= spans[-1][1] + 1024:
                spans[-1][1] = max(spans[-1][1], start + size)
            else:
                spans.append([start, start + size])
        if not spans:
            raise ValueError("focus expression matched no sampled symbols")
    else:
        spans = [(None, None)]
    for start, end in ([] if args.skip_disassembly else spans):
        command = ["objdump", "-d", "-C", "--no-show-raw-insn"]
        if start is not None:
            command += [f"--start-address={start}", f"--stop-address={end}"]
        command.append(str(args.binary))
        with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as process:
            current, instructions = None, []
            for line in process.stdout:
                item = instruction(line)
                if item is None:
                    if match := re.fullmatch(r"[0-9a-f]+ <(.+)>:\n", line):
                        if args.constant_control_scan and current in selected_names:
                            base = names[current][0]
                            counts = {base + int(offset): count for offset, count in summary["offsets"][current].items()}
                            for row in constant_block_scan(current, instructions, counts, constant_fields):
                                row["offset"] = int(row["pc"], 16) - base
                                control_rows.append(row)
                        current, instructions = match[1], []
                        previous.clear()
                    continue
                address, mnemonic, operands = item
                if args.constant_control_scan:
                    instructions.append(item)
                if address in sampled:
                    name, count = sampled[address]
                    found.add(address)
                    kind, phase = bucket(mnemonic, operands), six_phase_category(name)
                    categories.setdefault(phase, Counter())[kind] += count
                    mnemonics[mnemonic] += count
                    rows.append({"symbol": name, "offset": address - names[name][0],
                                 "samples": count, "phase": phase, "bucket": kind,
                                 "instruction": f"{mnemonic} {operands}",
                                 "previous": list(previous)})
                previous.append(f"{address:x}: {mnemonic} {operands}")
            if args.constant_control_scan and current in selected_names:
                base = names[current][0]
                counts = {base + int(offset): count for offset, count in summary["offsets"][current].items()}
                for row in constant_block_scan(current, instructions, counts, constant_fields):
                    row["offset"] = int(row["pc"], 16) - base
                    control_rows.append(row)
            if process.wait():
                raise ValueError("objdump failed")
    result = {"samples": summary["samples"], "matched_samples": sum(row["samples"] for row in rows),
              "focus_symbol": args.focus_symbol,
              "disassembly_performed": not args.skip_disassembly,
              "selected_samples": sum(count for _, count in sampled.values()),
              "unmatched_samples": sum(count for address, (_, count) in sampled.items() if address not in found),
              "category_buckets": categories, "mnemonics": dict(mnemonics.most_common()),
              "top_pcs": sorted(rows, key=lambda row: -row["samples"])[:args.top],
              "caution": "Sampled PC buckets are observed locations, not eliminated cost or causation; call-return attribution and sampling skid matter."}
    if args.constant_report:
        result["constant_control_neighborhoods"] = constant_neighborhoods(args.constant_report, names, summary)
    if args.constant_control_scan:
        counts = Counter()
        for row in control_rows:
            counts[row["category"]] += row["samples"]
        result["constant_control_scan"] = {
            "known_scalar_fields": len(constant_fields), "samples": sum(row["samples"] for row in control_rows),
            "categories": dict(counts), "pcs": sorted(control_rows, key=lambda row: -row["samples"]),
            "caution": "Basic-block associations from observed scalar fields only; no cross-block propagation, publication-prefix coverage or eliminated-cost claim. Stores/data loads retain work even when their operands become constant."
        }
    if args.profile:
        _, records, maps = read_profile(args.profile.read_bytes(), keep_stacks=True)
        mappings = [row for row in maps if "x" in row[2] and row[4] and Path(row[4]).resolve() == args.binary.resolve()]
        bases = {row[0] - row[3] for row in mappings}
        if len(bases) != 1 or sum(count for count, _ in records) != summary["samples"]:
            raise ValueError("raw profile mapping or total mismatch")
        base = next(iter(bases))
        starts = sorted(native)
        depths, external_callers, external_model_callers, model_inclusive = Counter(), Counter(), Counter(), Counter()
        model_descendant_calls = Counter()
        for count, stack in records:
            depths[len(stack)] += count
            external = not any(start <= stack[0] < end for start, end, _, _, _ in mappings)
            first_main, first_model, model_offset, leaf_name = None, None, None, None
            for pc in stack:
                if not any(start <= pc < end for start, end, _, _, _ in mappings):
                    continue
                address = pc - base
                index = bisect_right(starts, address) - 1
                if index >= 0:
                    start = starts[index]
                    size, name = native[start]
                    if address < start + size:
                        if first_main is None:
                            first_main = name
                            if pc == stack[0]:
                                leaf_name = name
                        if name.startswith("GrhSIM_SimTop::"):
                            first_model = name
                            model_offset = address - start
                            break
            if first_model:
                model_inclusive[first_model] += count
            if external and first_main:
                external_callers[first_main] += count
            if external and first_model:
                external_model_callers[first_model] += count
            if first_model and (external or leaf_name != first_model) and (not focus or focus.search(first_model)):
                model_descendant_calls[(first_model, model_offset, first_main, leaf_name)] += count
        result.update(stack_depths=dict(depths.most_common()),
                      external_main_callers=dict(external_callers.most_common()),
                      external_model_callers=dict(external_model_callers.most_common()),
                      nearest_model_frame=dict(model_inclusive.most_common()))
        result["model_descendant_calls"] = [
            {"model_symbol": key[0], "return_offset": key[1],
             "nearest_main_symbol": key[2], "native_leaf_symbol": key[3], "samples": count}
            for key, count in model_descendant_calls.most_common()
        ]
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key not in (
        "top_pcs", "external_main_callers", "external_model_callers", "nearest_model_frame", "model_descendant_calls", "constant_control_neighborhoods", "constant_control_scan")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--top", type=int, default=100)
    parser.add_argument("--focus-symbol", help="Regex selecting sampled native symbols and descendant stack call sites")
    parser.add_argument("--constant-report", type=Path, help="Existing direct constant-PC audit for local control-neighborhood associations")
    parser.add_argument("--skip-disassembly", action="store_true", help="Read symbols/stacks/existing constant neighborhoods without redisassembling native text")
    parser.add_argument("--constant-control-scan", action="store_true", help="Associate sampled PCs with scalar constant loads in the same basic block")
    describe(parser.parse_args())
