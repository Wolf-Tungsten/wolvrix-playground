#!/usr/bin/env python3
"""Classify branch-generating constructs in generated compute-task sources."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess

from grhsim_cpu_profile import task_phases


TASK_RE = re.compile(r"\w+::cpu_task_(\d+)\(\)")


def extract_condition(text, start):
    """Return the balanced-paren condition text of an if(/for( starting at start."""
    assert text[start] == "("
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:index]
    return text[start + 1:]


def classify(line, marker, condition, keyword):
    probe = condition[:120]
    if keyword == "for":
        return "loop"
    if "cpu_active_word" in probe.split("&")[0].split(")")[0] or probe.startswith("cpu_active_word"):
        return "task_entry_active_word"
    if "cpu_quiescence_skip" in marker:
        return "quiescence_guard"
    if "cpu_stable_history_scan" in line or "cpu_stable_history_skip" in marker:
        return "stable_history_skip"
    if "cpu_inactive_edge_sample" in marker:
        return "inactive_edge_guard"
    if "cpu_pflags" in probe or "cpu_armed" in probe:
        return "port_arm_gate"
    if "cpu_dsample" in line or probe.startswith("cpu_current!=cpu_value"):
        return "change_detect_writeback"
    if "std::memchr" in probe:
        return "stable_history_skip"
    if "cpu_edge_snapshot_" in probe or "cpu_event_snapshot_" in probe:
        return "edge_gate"
    if "cpu_cevent_" in probe or "(false ||" in probe or "(true ||" in probe:
        return "cevent_gate"
    return "other"


def normalize_pattern(condition):
    text = re.sub(r"0x[0-9a-fA-F]+", "#", condition)
    text = re.sub(r"\d+", "#", text)
    return text[:70]


def native_task_counts(binary_path, phases, cache_path):
    counts = {}
    if cache_path and Path(cache_path).exists():
        data = json.loads(Path(cache_path).read_text())
        return {int(k): v for k, v in data["tasks"].items()}
    task = None
    command = ["objdump", "-d", "-C", "--no-show-raw-insn", str(binary_path)]
    branch_target = re.compile(r"^\s+([0-9a-f]+):\s+(\S+)\s+([0-9a-f]+)\s")
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as process:
        for line in process.stdout:
            symbol = re.match(r"^[0-9a-f]+ <(.+)>:$", line)
            if symbol:
                match = TASK_RE.fullmatch(symbol[1])
                task = int(match[1]) if match else None
                if task is not None:
                    counts.setdefault(task, Counter())
                continue
            instruction = re.match(r"^\s+([0-9a-f]+):\s+(\S+)", line)
            if not instruction or task is None:
                continue
            counts[task]["instructions"] += 1
            mnemonic = instruction[2]
            if mnemonic.startswith("j") and mnemonic not in ("jmp", "jmpq"):
                counts[task]["conditional_jumps"] += 1
                target = branch_target.match(line)
                if target and int(target[3], 16) < int(target[1], 16):
                    counts[task]["backward_cj"] += 1
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
    return counts


def nnls(rows, target, n_features, iterations=2000, tolerance=1e-10):
    """Small non-negative least squares via cyclic coordinate descent."""
    coefs = [0.0] * n_features
    columns = [[row[j] for row in rows] for j in range(n_features)]
    col_norms = [sum(v * v for v in col) for col in columns]
    pred = [0.0] * len(rows)
    for _ in range(iterations):
        max_delta = 0.0
        for j in range(n_features):
            if col_norms[j] == 0:
                continue
            col = columns[j]
            old = coefs[j]
            numerator = old * col_norms[j]
            for i in range(len(rows)):
                numerator += col[i] * (target[i] - pred[i])
            new = max(0.0, numerator / col_norms[j])
            delta = new - old
            if delta:
                for i in range(len(rows)):
                    pred[i] += delta * col[i]
                coefs[j] = new
                max_delta = max(max_delta, abs(delta))
        if max_delta < tolerance:
            break
    return coefs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--binary", type=Path, default=None)
    parser.add_argument("--native-cache", type=Path, default=None)
    parser.add_argument("--other-top", type=int, default=25)
    parser.add_argument("--focus-tasks", type=str, default="")
    args = parser.parse_args()

    phases = task_phases(args.model_dir / "grhsim_SimTop.cpp")
    compute_ids = sorted(task for task, phase in phases.items() if phase == "compute_task")
    print(f"compute_tasks={len(compute_ids)}")

    classes = Counter()
    class_ops = Counter()
    other_patterns = Counter()
    ternaries = 0
    per_task = {}
    branch_token = re.compile(r"\b(if|for)\s*\(")
    for task in compute_ids:
        path = args.model_dir / f"grhsim_SimTop_task_{task}.cpp"
        task_classes = Counter()
        for line in path.read_text().splitlines():
            if not line or line.startswith('extern "C"') or line.startswith("#include"):
                continue
            marker = ""
            if "//" in line:
                marker = line[line.index("//"):]
            code = line.split("//", 1)[0]
            tern = code.count("?")
            ternaries += tern
            task_classes["ternary_residual"] += tern
            task_classes["wide_array_ops"] += code.count("std::array<") + len(
                re.findall(r"grhsim_\w*words\w*|\bmemcpy\b|\bmemmove\b|\bmemset\b", code))
            for match in branch_token.finditer(code):
                keyword = match.group(1)
                open_paren = code.index("(", match.end() - 1)
                condition = extract_condition(code, open_paren)
                klass = classify(line, marker, condition, keyword)
                ops = condition.count("&&") + condition.count("||")
                classes[klass] += 1
                class_ops[klass] += 1 + ops
                task_classes[klass] += 1
                if klass == "other":
                    other_patterns[normalize_pattern(condition)] += 1
        per_task[task] = task_classes

    total_constructs = sum(classes.values()) + ternaries
    total_weight = sum(class_ops.values()) + ternaries
    print(f"source_branch_constructs={total_constructs} operator_weighted={total_weight}")
    print("\nclass constructs pct_constructs weighted pct_weight")
    all_classes = Counter(classes)
    all_classes["ternary_residual"] = ternaries
    all_weights = Counter(class_ops)
    all_weights["ternary_residual"] = ternaries
    for klass, count in all_weights.most_common():
        share = all_classes[klass] / total_constructs * 100
        wshare = all_weights[klass] / total_weight * 100
        print(f"{klass} {all_classes[klass]} {share:.2f} {all_weights[klass]} {wshare:.2f}")

    print(f"\n== top {args.other_top} 'other' condition patterns ==")
    for pattern, n in other_patterns.most_common(args.other_top):
        print(f"{n} {pattern}")

    if args.binary:
        counts = native_task_counts(args.binary, phases, args.native_cache)
        native_total = sum(counts[t]["conditional_jumps"] for t in compute_ids)
        native_instr = sum(counts[t]["instructions"] for t in compute_ids)
        print(f"\nnative_compute_conditional_jumps={native_total} native_compute_instructions={native_instr}")
        print(f"native/source_constructs ratio={native_total / total_constructs:.3f} "
              f"native/weighted ratio={native_total / total_weight:.3f}")

        feature_classes = sorted(all_classes) + ["wide_array_ops"]
        rows = []
        target = []
        backward_total = 0
        for task in compute_ids:
            row = [per_task[task][klass] for klass in feature_classes]
            rows.append(row)
            target.append(counts[task]["conditional_jumps"])
            backward_total += counts[task].get("backward_cj", 0)
        print(f"native_backward_conditional_jumps={backward_total} "
              f"({backward_total / native_total * 100:.2f}% of compute cj; "
              f"compute has zero source-level for/while loops, so back-edges come from inlined helper loops)")
        coefs = nnls(rows, target, len(feature_classes))
        feature_totals = {klass: all_classes[klass] for klass in all_classes}
        feature_totals["wide_array_ops"] = sum(per_task[t]["wide_array_ops"] for t in compute_ids)
        residual_sq = 0
        mean_y = sum(target) / len(target)
        tot_sq = sum((y - mean_y) ** 2 for y in target)
        for row, y in zip(rows, target):
            pred = sum(c * x for c, x in zip(coefs, row))
            residual_sq += (y - pred) ** 2
        r_squared = 1 - residual_sq / max(tot_sq, 1e-9)
        print("\n== NNLS calibration: native conditional jumps per source construct ==")
        for klass, coef in zip(feature_classes, coefs):
            est_total = coef * feature_totals[klass]
            print(f"{klass} coef={coef:.3f} constructs={feature_totals[klass]} "
                  f"est_native={est_total:.0f} est_share={est_total / native_total * 100:.2f}%")
        print(f"NNLS R2={r_squared:.4f} "
              f"(sum est={sum(c * feature_totals[k] for c, k in zip(coefs, feature_classes)):.0f} "
              f"vs native {native_total})")

        focus = [int(x) for x in args.focus_tasks.split(",") if x.strip()]
        if focus:
            print("\n== focus tasks: source classes vs native conditional jumps ==")
            print("task native_cj backward_cj " + " ".join(feature_classes))
            for task in focus:
                row = " ".join(str(per_task[task][klass]) for klass in feature_classes)
                print(f"{task} {counts[task]['conditional_jumps']} "
                      f"{counts[task].get('backward_cj', 0)} {row}")

        cevent_ops_avg = (all_weights["cevent_gate"] / max(all_classes["cevent_gate"], 1))
        residuals = []
        for task in compute_ids:
            row = per_task[task]
            explained = (row["task_entry_active_word"]
                         + cevent_ops_avg * row["cevent_gate"]
                         + row["quiescence_guard"] + row["change_detect_writeback"]
                         + 2.0 * row["other"])
            forward = counts[task]["conditional_jumps"] - counts[task].get("backward_cj", 0)
            residuals.append((forward - explained, task, forward,
                              row["cevent_gate"], row["ternary_residual"],
                              row["wide_array_ops"], counts[task]["instructions"]))
        residuals.sort(reverse=True)
        print(f"\n== top residual tasks (forward_cj beyond entry+{cevent_ops_avg:.2f}xcevent+guards) ==")
        print("residual task forward_cj cevent ternary wide_array_ops native_instr")
        for residual, task, forward, cevent, tern, wide, instr in residuals[:15]:
            print(f"{residual:.0f} {task} {forward} {cevent} {tern} {wide} {instr}")
        total_residual = sum(max(r[0], 0.0) for r in residuals)
        print(f"total_positive_residual={total_residual:.0f} "
              f"({total_residual / native_total * 100:.2f}% of compute cj)")


if __name__ == "__main__":
    main()
