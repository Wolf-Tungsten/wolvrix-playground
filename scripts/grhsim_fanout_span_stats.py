"""Census per-(unit, group) fanout target byte spans for wide-OR combining.

Parses emitted task sources; for each fanout OR family keyed by
(array, cpu_changed_K) collects target byte offsets and measures consecutive
runs: a run of length L within one group can be emitted as one 16/32/64-bit
wide OR instead of L byte RMWs. Reports the instruction-saving pool.
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

RE_TASK = re.compile(r"grhsim_SimTop_task_(\d+)\.cpp$")
RE_UNIT = re.compile(r"if\(cpu_active_word&(\d+)\)\{")
RE_FANOUT = re.compile(
    r"(cpu_flags|cpu_pflags)\[(\d+)\] \|= \(static_cast<std::uint8_t>\(-static_cast<std::uint8_t>\(cpu_changed_(\d+)\)\) & (\d+)\)")


def runs_of(offsets):
    runs = []
    start = prev = None
    for off in sorted(offsets):
        if prev is None or off != prev + 1:
            if start is not None:
                runs.append(prev - start + 1)
            start = off
        prev = off
    if start is not None:
        runs.append(prev - start + 1)
    return runs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    group_stats = Counter()      # (array, run_length) -> count
    terms_total = 0
    groups_total = 0
    runs_total = 0
    est_now = 0   # ~3.5 instr per byte term (shl + or + RMW share)
    est_wide = 0  # neg per group + or per run-term + RMW per run

    for path in sorted(args.model_dir.glob("grhsim_SimTop_task_*.cpp")):
        tid = int(RE_TASK.match(path.name).group(1))
        if tid >= 4200:
            continue
        text = path.read_text()
        for um in RE_UNIT.finditer(text):
            start = um.end()
            depth, i = 1, start
            while depth > 0 and i < len(text):
                ch = text[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                i += 1
            block = text[start:i]
            groups = defaultdict(set)  # (array, chg) -> {offsets}
            for line in block.splitlines():
                fm = RE_FANOUT.search(line)
                if fm:
                    arr, off, chg, _mask = fm.groups()
                    groups[(arr, int(chg))].add(int(off))
            for (arr, chg), offs in groups.items():
                groups_total += 1
                terms_total += len(offs)
                est_now += 3 * len(offs)  # clang: shl+or per term + shared RMW ≈ 3
                rs = runs_of(offs)
                runs_total += len(rs)
                est_wide += 1 + len(rs) * 3  # one neg + per run load/or/store
                for length in rs:
                    group_stats[(arr, min(length, 8))] += 1

    out = {
        "groups": groups_total,
        "byte_terms": terms_total,
        "runs": runs_total,
        "run_len_hist": {f"{a}|{l}": c for (a, l), c in sorted(group_stats.items())},
        "est_instr_now": est_now,
        "est_instr_wide": est_wide,
        "est_saving_percent_of_fanout": round(100.0 * (est_now - est_wide) / max(est_now, 1), 2),
    }
    args.output.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
