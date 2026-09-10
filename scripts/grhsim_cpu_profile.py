#!/usr/bin/env python3
"""Summarize flat PCs from a 64-bit little-endian gperftools CPU profile."""

import argparse
from bisect import bisect_right
from collections import Counter
from pathlib import Path
import re
import struct
import subprocess


def read_profile(data):
    if len(data) < 40:
        raise ValueError("truncated profile header")
    count, depth, version, period, padding = struct.unpack_from("<5Q", data)
    if (count, depth, version, padding) != (0, 3, 0, 0) or period == 0:
        raise ValueError("expected 64-bit little-endian gperftools v0 profile")
    pos, records = 40, []
    while True:
        if pos + 16 > len(data):
            raise ValueError("missing profile terminator")
        count, depth = struct.unpack_from("<2Q", data, pos)
        pos += 16
        if depth < 1 or depth > 1024 or pos + depth * 8 > len(data):
            raise ValueError("invalid stack depth or truncated record")
        pcs = struct.unpack_from(f"<{depth}Q", data, pos)
        pos += depth * 8
        if count == 0 and pcs == (0,):
            break
        if count == 0 or pcs[0] == 0:
            raise ValueError("empty sample record")
        records.append((count, pcs[0]))
    maps = []
    for line in data[pos:].decode("utf-8").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(
            r"([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+([0-9a-f]+)\s+\S+\s+\d+\s*(.*)", line
        )
        if not match:
            raise ValueError(f"invalid mapping: {line}")
        start, end, flags, offset, name = match.groups()
        maps.append((int(start, 16), int(end, 16), flags, int(offset, 16), name))
    if not records or not maps:
        raise ValueError("profile lacks samples or mappings")
    return period, records, maps


def symbols(binary):
    # This mapping rule is deliberately restricted to matching ELF LOAD offsets.
    segments = subprocess.check_output(["readelf", "-lW", str(binary)], text=True)
    loads = re.findall(r"^\s*LOAD\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)", segments, re.M)
    if not loads or any(int(offset, 16) != int(addr, 16) for offset, addr in loads):
        raise ValueError("unsupported ELF LOAD virtual/file offset relationship")
    output = subprocess.check_output(["nm", "-n", "-S", "-C", "--defined-only", str(binary)], text=True)
    result = {}
    for line in output.splitlines():
        match = re.fullmatch(r"([0-9a-f]+)\s+([0-9a-f]+)\s+[TtWw]\s+(.+)", line)
        if match:
            start, size, name = match.groups()
            if int(size, 16):
                result.setdefault(int(start, 16), (int(size, 16), name))
    if not result:
        raise ValueError("no native function symbols")
    return result


def task_phases(model):
    text = model.read_text()
    match = re.search(r"void \w+::eval\(\)\{(.*?)void \w+::dump_runtime_profile", text, re.S)
    if not match:
        raise ValueError("no generated evaluator/profile boundaries")
    parts = match[1].split("cpu_profile_tick(cpu_profile_data.compute_ns);")
    if len(parts) != 2:
        raise ValueError("expected one contiguous compute phase")
    commit = parts[1].split("cpu_profile_tick(cpu_profile_data.commit_ns);")
    if len(commit) != 2:
        raise ValueError("expected one contiguous commit phase")
    phases = {}
    for phase, body in (("compute_task", parts[0]), ("commit_task", commit[0])):
        for task in re.findall(r"cpu_task_(\d+)\(\);", body):
            if int(task) in phases:
                raise ValueError("duplicate scheduled task")
            phases[int(task)] = phase
    files = {int(p.stem.rsplit("_", 1)[1]) for p in model.parent.glob("*_task_*.cpp")}
    if set(phases) != files or not files:
        raise ValueError("schedule/task-file coverage mismatch")
    return phases


def summarize(profile, binary, model, expected_samples, top):
    period, records, maps = read_profile(profile.read_bytes())
    total = sum(count for count, _ in records)
    if total != expected_samples:
        raise ValueError(f"sample total {total} != profiler diagnostic {expected_samples}")
    native = symbols(binary)
    starts = sorted(native)
    phases = task_phases(model)
    functions, categories, pcs_by_symbol = Counter(), Counter(), {}
    main_maps = [m for m in maps if m[4] and Path(m[4]).resolve() == binary.resolve()]
    if not main_maps or len({m[0] - m[3] for m in main_maps}) != 1:
        raise ValueError("missing or inconsistent executable mapping")
    base = main_maps[0][0] - main_maps[0][3]
    for count, pc in records:
        mapping = next((m for m in maps if m[0] <= pc < m[1]), None)
        name, category = "[unmapped]", "unmapped"
        if mapping in main_maps:
            address = pc - base
            index = bisect_right(starts, address) - 1
            name, category = "[main unresolved]", "main_unresolved"
            if index >= 0:
                start = starts[index]
                size, symbol = native[start]
                if address < start + size:
                    name, category = symbol, "main_other"
                    task = re.fullmatch(r"\w+::cpu_task_(\d+)\(\)", name)
                    if task:
                        category = phases[int(task[1])]
                    elif name.endswith("::eval()"):
                        category = "evaluator"
                    elif name.endswith("::cpu_publish()"):
                        category = "publication"
                    pcs_by_symbol.setdefault(name, Counter())[address - start] += count
        elif mapping:
            name = "[external] " + (mapping[4] or "anonymous")
            category = "external"
        functions[name] += count
        categories[category] += count
    if sum(functions.values()) != total or sum(categories.values()) != total:
        raise ValueError("sample accounting mismatch")
    print(f"samples={total} records={len(records)} period_us={period} nominal_cpu_s={total * period / 1e6:.6f}")
    print(f"task_coverage={len(phases)} phase_tasks={dict(Counter(phases.values()))}")
    print("category samples percent")
    for name, count in categories.most_common():
        print(f"{name} {count} {count / total * 100:.6f}")
    print("function samples percent")
    for name, count in functions.most_common(top):
        print(f"{count} {count / total * 100:.6f} {name}")
        offsets = pcs_by_symbol.get(name, Counter()).most_common(5)
        if offsets:
            print("  top_offsets " + " ".join(f"+0x{offset:x}:{n}" for offset, n in offsets))
    for phase in ("compute_task", "commit_task"):
        rows = [(name, count) for name, count in functions.most_common()
                if (m := re.fullmatch(r"\w+::cpu_task_(\d+)\(\)", name))
                and phases[int(m[1])] == phase]
        print(f"{phase} sampled_tasks={len(rows)} top10_samples={sum(n for _, n in rows[:10])}")
        for name, count in rows[:10]:
            print(f"  {count} {count / total * 100:.6f} {name}")
    print("PASS: profile terminator, mappings, ELF layout, task coverage, symbol bounds, sample totals")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--expected-samples", type=int, required=True)
    parser.add_argument("--top", type=int, default=25)
    args = parser.parse_args()
    summarize(args.profile, args.binary, args.model, args.expected_samples, args.top)
