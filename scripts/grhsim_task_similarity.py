#!/usr/bin/env python3
"""Cluster generated compute-task bodies by normalized-text similarity for fusion potential."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess

from grhsim_cpu_profile import task_phases


TASK_RE = re.compile(r"\w+::cpu_task_(\d+)\(\)")
FUNC_RE = re.compile(r"^void \w+::cpu_task_(\d+)\(\)\{$", re.M)
COMMENT_RE = re.compile(r"//[^\n]*")
NUMBER_RE = re.compile(r"0x[0-9a-fA-F]+|\d+")
SPACE_RE = re.compile(r"\s+")
STATEMENT_SPLIT_RE = re.compile(r"(?<=[;{}])\s+")


def normalize_body(text):
    body = COMMENT_RE.sub("", text)
    body = NUMBER_RE.sub("#", body)
    return SPACE_RE.sub(" ", body).strip()


def statement_shingles(normalized, width=3):
    statements = [s for s in STATEMENT_SPLIT_RE.split(normalized) if s]
    if len(statements) < width:
        return {hash(normalized)} if normalized else set()
    return {hash(tuple(statements[index:index + width]))
            for index in range(len(statements) - width + 1)}


def bottom_k(sketch_source, k):
    return sorted(sketch_source)[:k]


def native_task_data(binary_path, phases, cache_path):
    if cache_path and Path(cache_path).exists():
        data = json.loads(Path(cache_path).read_text())
        return ({int(k): v for k, v in data["tasks"].items()},
                {int(k): v for k, v in data.get("sizes", {}).items()})
    counts = {}
    task = None
    command = ["objdump", "-d", "-C", "--no-show-raw-insn", str(binary_path)]
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as process:
        for line in process.stdout:
            symbol = re.match(r"^[0-9a-f]+ <(.+)>:$", line)
            if symbol:
                match = TASK_RE.fullmatch(symbol[1])
                task = int(match[1]) if match else None
                if task is not None:
                    counts.setdefault(task, Counter())
                continue
            instruction = re.match(r"^\s+[0-9a-f]+:\s+(\S+)", line)
            if not instruction or task is None:
                continue
            counts[task]["instructions"] += 1
            mnemonic = instruction[2]
            if mnemonic.startswith("j") and mnemonic not in ("jmp", "jmpq"):
                counts[task]["conditional_jumps"] += 1
        if process.wait():
            raise RuntimeError("objdump failed")
    sizes = {}
    output = subprocess.check_output(["nm", "-n", "-S", "-C", "--defined-only", str(binary_path)], text=True)
    for line in output.splitlines():
        match = re.fullmatch(r"([0-9a-f]+)\s+([0-9a-f]+)\s+[TtWw]\s+(.+)", line)
        if match:
            task_match = TASK_RE.fullmatch(match[3])
            if task_match:
                sizes[int(task_match[1])] = int(match[2], 16)
    if set(counts) != set(phases):
        raise ValueError("native task coverage differs from generated schedule")
    if cache_path:
        Path(cache_path).write_text(json.dumps({
            "binary": str(binary_path),
            "tasks": {str(k): dict(v) for k, v in counts.items()},
            "sizes": {str(k): v for k, v in sizes.items()}}))
    return counts, sizes


def family_report(name, families, counts, sizes, const_sites, total_instr, total_bytes):
    multi = [members for members in families if len(members) >= 2]
    covered_tasks = sum(len(m) for m in multi)
    saved_instr = 0
    saved_bytes = 0
    covered_instr = 0
    table_bytes = 0
    rows = []
    for members in multi:
        instrs = [counts[m]["instructions"] for m in members]
        byte_sizes = [sizes.get(m, 0) for m in members]
        current_instr = sum(instrs)
        fused_instr = max(instrs)
        saved_instr += current_instr - fused_instr
        saved_bytes += sum(byte_sizes) - max(byte_sizes)
        covered_instr += current_instr
        consts = sum(const_sites[m] for m in members)
        table_bytes += consts * 8
        rows.append((current_instr - fused_instr, len(members), fused_instr, members))
    rows.sort(reverse=True)
    print(f"\n== {name} ==")
    print(f"families_with_2plus={len(multi)} tasks_covered={covered_tasks} "
          f"instr_covered={covered_instr} ({covered_instr / total_instr * 100:.2f}% of compute instr)")
    print(f"saved_instr={saved_instr} ({saved_instr / total_instr * 100:.2f}% of compute instr) "
          f"saved_bytes={saved_bytes} ({saved_bytes / total_bytes * 100:.3f}% of ELF text) "
          f"param_table_bytes~{table_bytes}")
    print("top families by saved instructions:")
    for saved, n_members, fused, members in rows[:15]:
        print(f"  saved={saved} members={n_members} fused_instr={fused} "
              f"members_sample={sorted(members)[:8]}")
    return saved_instr, saved_bytes, covered_instr, multi, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--native-cache", type=Path, default=None)
    parser.add_argument("--sketch", type=int, default=64)
    parser.add_argument("--threshold", type=float, default=0.9)
    parser.add_argument("--candidate-overlap", type=int, default=40)
    parser.add_argument("--df-cap", type=int, default=300)
    parser.add_argument("--hot-tasks", type=str, default="",
                    help="comma separated task ids to locate in families")
    args = parser.parse_args()

    phases = task_phases(args.model_dir / "grhsim_SimTop.cpp")
    compute_ids = sorted(task for task, phase in phases.items() if phase == "compute_task")
    print(f"compute_tasks={len(compute_ids)}")

    normalized = {}
    const_sites = {}
    exact_groups = defaultdict(list)
    sketches = {}
    for task in compute_ids:
        text = (args.model_dir / f"grhsim_SimTop_task_{task}.cpp").read_text()
        match = FUNC_RE.search(text)
        if not match:
            raise ValueError(f"no function body in task {task}")
        body = text[match.end():]
        norm = normalize_body(body)
        normalized[task] = norm
        const_sites[task] = len(NUMBER_RE.findall(body))
        exact_groups[hashlib.md5(norm.encode()).hexdigest()].append(task)
        shingles = statement_shingles(norm)
        sketches[task] = bottom_k(sorted(shingles), args.sketch)

    counts, sizes = native_task_data(args.binary, phases, args.native_cache)
    total_instr = sum(counts[t]["instructions"] for t in compute_ids)
    total_bytes = int(subprocess.check_output(
        ["size", str(args.binary)], text=True).splitlines()[1].split()[0])
    print(f"compute_native_instructions={total_instr} elf_text_bytes={total_bytes}")

    exact_families = [sorted(members) for members in exact_groups.values() if len(members) >= 2]
    exact_saved, exact_saved_bytes, exact_covered, exact_multi, _ = family_report(
        "exact normalized-identity families", exact_families, counts, sizes, const_sites,
        total_instr, total_bytes)

    index = defaultdict(list)
    for task, sketch in sketches.items():
        for value in set(sketch):
            index[value].append(task)
    pair_overlap = Counter()
    for value, tasks in index.items():
        if len(tasks) < 2 or len(tasks) > args.df_cap:
            continue
        for i in range(len(tasks)):
            for j in range(i + 1, len(tasks)):
                pair_overlap[(tasks[i], tasks[j])] += 1
    candidates = [pair for pair, overlap in pair_overlap.items()
                  if overlap >= args.candidate_overlap]
    print(f"\nnear-dup candidates={len(candidates)} (sketch overlap>={args.candidate_overlap})")

    shingle_cache = {}
    parent = {task: task for task in compute_ids}

    def find(task):
        while parent[task] != task:
            parent[task] = parent[parent[task]]
            task = parent[task]
        return task

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    accepted_pairs = 0
    for a, b in candidates:
        for task in (a, b):
            if task not in shingle_cache:
                shingle_cache[task] = statement_shingles(normalized[task])
        sa, sb = shingle_cache[a], shingle_cache[b]
        inter = len(sa & sb)
        union_size = len(sa) + len(sb) - inter
        if not union_size:
            continue
        jaccard = inter / union_size
        if jaccard >= args.threshold:
            union(a, b)
            accepted_pairs += 1
    near_groups = defaultdict(list)
    for task in compute_ids:
        near_groups[find(task)].append(task)
    # Families already exact-identical stay visible; report union-find families beyond singletons.
    near_families = [sorted(members) for members in near_groups.values() if len(members) >= 2]
    print(f"accepted_pairs_jaccard>={args.threshold}: {accepted_pairs}")
    near_saved, near_saved_bytes, near_covered, near_multi, _ = family_report(
        f">={args.threshold:.0%} statement-shingle similarity families",
        near_families, counts, sizes, const_sites, total_instr, total_bytes)

    hot = [int(x) for x in args.hot_tasks.split(",") if x.strip()]
    if hot:
        print("\n== hot task family membership ==")
        exact_of = {m: fam for fam in exact_multi for m in fam}
        near_of = {m: fam for fam in near_multi for m in fam}
        for task in hot:
            ef = exact_of.get(task)
            nf = near_of.get(task)
            print(f"task {task}: exact_family={'none' if ef is None else f'size={len(ef)}'} "
                  f"near_family={'none' if nf is None else f'size={len(nf)}'}")

    mean_const = sum(const_sites.values()) / len(const_sites)
    fused_members = [m for fam in near_multi for m in fam]
    fused_const = sum(const_sites[m] for m in fused_members)
    print(f"\nconst_sites_per_task mean={mean_const:.1f} "
          f"fused_family_tasks={len(fused_members)} fused_const_sites={fused_const}")
    print("indirect-cost note: each fused body replaces immediate offsets with table loads; "
          "added dynamic loads per eval <= sum of const sites of active fused tasks, "
          "while static text drops by saved_bytes above.")


if __name__ == "__main__":
    main()
