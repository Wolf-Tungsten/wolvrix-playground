"""Census per-unit fanout-OR and boundary-writeback structure in generated tasks.

For every compute unit block (if(cpu_active_word&N){...}) collects:
  - fanout OR lines: target array (cpu_flags/cpu_pflags/cpu_active_word), byte index
  - writeback lines: fanout class (cpu_changed_K), value form (local reuse vs fresh
    expr), boundary offset, scalar type
Reports duplicate-target statistics that decide same-byte fanout combining and
class-size statistics that decide packed writeback profitability.
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

RE_TASK = re.compile(r"grhsim_SimTop_task_(\d+)\.cpp$")
RE_UNIT = re.compile(r"if\(cpu_active_word&(\d+)\)\{")
RE_FANOUT = re.compile(
    r"(cpu_flags|cpu_pflags|cpu_active_word)\[?(\d*)\]? ?\|= \(static_cast<std::uint8_t>\(-static_cast<std::uint8_t>\(cpu_changed_(\d+)\)\) & (\d+)\)")
RE_WB = re.compile(
    r"\{const auto cpu_value=(.*);cpu_changed_(\d+)\|=\(cpu_at<([a-zA-Z0-9_:]+)>\(cpu_bnd_,(\d+)\)!=cpu_value\);cpu_at<[a-zA-Z0-9_:]+>\(cpu_bnd_,\d+\)=cpu_value;\}")
RE_WB_PLAIN = re.compile(r"cpu_at<([a-zA-Z0-9_:]+)>\(cpu_bnd_,(\d+)\)=(.*);$")
RE_LOCAL_REF = re.compile(r"^cpu_at<[^>]*>\(cpu_local,\d+\)$")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    units = 0
    fanout_per_unit = Counter()
    byte_dup = Counter()  # extra ORs beyond first per (unit,array,byte)
    class_sizes = Counter()  # outputs per (unit,class)
    class_type = Counter()
    wb_value_local = 0
    wb_value_expr = 0
    wb_total = 0
    class_contig = Counter()  # whether class boundary offsets are contiguous ascending
    class_offsets_span = Counter()

    for path in sorted(args.model_dir.glob("grhsim_SimTop_task_*.cpp")):
        tid = int(RE_TASK.match(path.name).group(1))
        if tid >= 4200:
            continue
        text = path.read_text()
        # split into unit blocks
        for um in RE_UNIT.finditer(text):
            start = um.end()
            # find matching closing via brace counting from start-1
            depth = 1
            i = start
            while depth > 0 and i < len(text):
                ch = text[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                i += 1
            block = text[start:i]
            units += 1
            targets = []
            classes = {}
            for line in block.splitlines():
                fm = RE_FANOUT.search(line)
                if fm:
                    arr, idx, chg, mask = fm.groups()
                    key = f"{arr}[{idx}]" if arr != "cpu_active_word" else "self"
                    targets.append((key, int(chg)))
                    continue
                wm = RE_WB.search(line)
                if wm:
                    expr, chg, ty, off = wm.groups()
                    wb_total += 1
                    if RE_LOCAL_REF.match(expr.strip()):
                        wb_value_local += 1
                    else:
                        wb_value_expr += 1
                    classes.setdefault(int(chg), []).append((ty, int(off)))
            fanout_per_unit[len(targets)] += 1
            seen = Counter(t[0] for t in targets)
            for key, cnt in seen.items():
                if cnt > 1:
                    byte_dup[cnt] += 1
            for chg, outs in classes.items():
                class_sizes[len(outs)] += 1
                for ty, _ in outs:
                    class_type[ty] += 1
                offs = [o for _, o in outs]
                if len(offs) > 1:
                    span = max(offs) - min(offs) + 1
                    class_contig["contig" if span == len(offs) else "sparse"] += 1
                    class_offsets_span[min(span, 64)] += 1

    out = {
        "units": units,
        "writebacks": wb_total,
        "wb_value_local_ref": wb_value_local,
        "wb_value_fresh_expr": wb_value_expr,
        "fanout_per_unit_hist": dict(sorted(fanout_per_unit.items())),
        "fanout_dup_per_byte_hist": dict(sorted(byte_dup.items())),
        "class_size_hist": dict(sorted(class_sizes.items())),
        "class_type": dict(class_type.most_common()),
        "class_contiguity": dict(class_contig),
        "class_span_hist_le64": dict(sorted(class_offsets_span.items())),
    }
    args.output.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
