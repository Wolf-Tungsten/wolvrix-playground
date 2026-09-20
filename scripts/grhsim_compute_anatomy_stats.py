"""Decompose generated compute-task sources into instruction-shape categories.

Scans grhsim_SimTop_task_*.cpp files and classifies every emitted statement line
inside task bodies into skeleton / input-read / local-compute / boundary-writeback
(tracked vs plain) / fanout (flags/pflags/self-rearm) / memory-registration /
wide-value helper buckets, so the dynamic instruction budget of an eval can be
estimated against activation counts.
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

RE_TASK = re.compile(r"grhsim_SimTop_task_(\d+)\.cpp$")
RULES = [
    ("dpi_decl", re.compile(r'extern "C"|v_difftest|xs_assert|flash_|sd_|jtag_|difftest_')),
    ("cached_read", re.compile(r"const auto cpu_cached_")),
    ("writeback_tracked", re.compile(r"cpu_changed_\d+\|=")),
    ("fanout_flags_or", re.compile(r"cpu_flags\[\d+\] \|= \(static_cast<std::uint8_t>\(-static_cast<std::uint8_t>\(cpu_changed_")),
    ("fanout_pflags_or", re.compile(r"cpu_pflags\[\d+\] \|= \(static_cast<std::uint8_t>\(-static_cast<std::uint8_t>\(cpu_changed_")),
    ("self_rearm_or", re.compile(r"cpu_active_word \|= \(static_cast<std::uint8_t>\(-static_cast<std::uint8_t>\(cpu_changed_")),
    ("changed_decl", re.compile(r"bool cpu_changed_\d+=false")),
    ("read_offset_reg", re.compile(r"cpu_read_offsets\[")),
    ("unit_guard", re.compile(r"if\(cpu_active_word&")),
    ("task_skeleton", re.compile(r"cpu_active_word=cpu_flags|cpu_flags\[\d+\]=0;|cpu_flags\[\d+\]\|=cpu_active_word")),
    ("writeback_plain", re.compile(r"cpu_at<[^>]*>\(cpu_bnd_,\d+\)=")),
    ("local_zero", re.compile(r"std::byte cpu_local\[(\d+)\]\{\}")),
    ("concat_insert", re.compile(r"grhsim_insert_(scalar_)?words\(cpu_concat")),
    ("concat_fill", re.compile(r"cpu_concat\.fill\(0\)|&cpu_concat=")),
    ("wide_word_op", re.compile(r"grhsim_(or|and|xor|not|mux|add|sub|shl|shr|compare)_words|cpu_at<std::array<std::uint64_t")),
    ("gate_merge", re.compile(r"cpu_gate_merge")),
    ("local_write", re.compile(r"cpu_at<[^>]*>\(cpu_local,")),
    ("mem_libcall", re.compile(r"std::mem(cpy|cmp|move)")),
    ("helper_call", re.compile(r"cpu_(write_cell|stage_cell|write_scalar|helper|mem_read|mem_copy|publish|direct_state_changed|word8|at_wide|wide_)")),
    ("event_hist", re.compile(r"cpu_edge_snapshot|cpu_cached_event|_hist")),
    ("pure_expr", re.compile(r"grhsim_(trunc|cast|compare|memo|memcpy|memcmp|replicate)")),
]


def classify(line):
    for name, rx in RULES:
        if rx.search(line):
            return name
    return "other"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    files = {}
    for path in args.model_dir.glob("grhsim_SimTop_task_*.cpp"):
        m = RE_TASK.match(path.name)
        if m:
            files[int(m.group(1))] = path

    groups = {"compute": lambda t: t < 4200, "commit": lambda t: t >= 4200}
    out = {}
    others = Counter()
    for group, pred in groups.items():
        stats = Counter()
        local_bytes = 0
        unit_count = 0
        task_count = 0
        for tid, path in sorted(files.items()):
            if not pred(tid):
                continue
            task_count += 1
            for line in path.read_text().splitlines():
                s = line.strip()
                if not s or s.startswith("#include"):
                    continue
                cat = classify(s)
                stats[cat] += 1
                if cat == "local_zero":
                    local_bytes += int(RE_TASK.search("") is None and 0 or int(re.search(r"\[(\d+)\]", s).group(1)))
                if cat == "unit_guard":
                    unit_count += 1
                if cat == "other" and group == "compute":
                    others[re.sub(r"\d+", "N", s[:70])] += 1
        out[group] = {
            "tasks": task_count,
            "units": unit_count,
            "local_zero_bytes": local_bytes,
            "lines": dict(stats.most_common()),
        }
    out["compute_other_top"] = dict(others.most_common(30))
    args.output.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
