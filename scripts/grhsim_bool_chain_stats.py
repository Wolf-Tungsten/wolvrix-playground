"""Count serial one-bit Boolean chains in generated GrhSIM C++ translation units.

A chain is a maximal run of statements whose result feeds exactly one next
statement with the same binary operator. Branches and joins break the run.
Length is the number of binary operators, not the number of input terms.
Explicit normalized bool assignments (cpu_vN / cpu_f.vN) and their inlined
cpu_value boundary-store roots are counted. Wide and other inlined expressions,
init, and dump are reported separately.
"""

from __future__ import annotations

import argparse
from array import array
from collections import Counter, defaultdict
import csv
import heapq
import json
from pathlib import Path
import re
import sys


FUNCTION_RE = re.compile(r"^(?:void|bool) GrhSIM_SimTop::([^ (]+)\(")
BOOL_RE = re.compile(
    r"^\s*(?:const bool cpu_v|cpu_f\.v)(\d+)="
    r"static_cast<bool>\(\(\((.+)\)&UINT64_C\(0x1\)\)\);$"
)
TERMINAL_RE = re.compile(
    r"^\s*const (?:auto &|auto |bool )cpu_value="
    r"static_cast<bool>\(\(\((.+)\)&UINT64_C\(0x1\)\)\);$"
)
VALUE_RE = re.compile(r"(?:cpu_v|cpu_f\.v)(\d+)\Z")
TU_RE = re.compile(r"grhsim_SimTop_tu(\d+)\.cpp\Z")
OPERATORS = {"|": 1, "&": 2, "^": 3, "||": 4, "&&": 5}
OPERATOR_NAMES = {value: key for key, value in OPERATORS.items()}
PHASE_NAMES = ("other", "input", "event", "general", "large_sink", "publish", "output", "init", "dump")
PHASE_IDS = {name: i for i, name in enumerate(PHASE_NAMES)}
BUCKETS = ((2, 3), (4, 7), (8, 15), (16, 31), (32, 63),
           (64, 127), (128, 255), (256, 511), (512, None))


def phase_of(function: str) -> int:
    if function.startswith("pInput"):
        return PHASE_IDS["input"]
    if function.startswith("pEvent"):
        return PHASE_IDS["event"]
    if function.startswith(("pGeneral", "sn_")):
        return PHASE_IDS["general"]
    if function.startswith("pLargeSink"):
        return PHASE_IDS["large_sink"]
    if function.startswith("pPublish"):
        return PHASE_IDS["publish"]
    if function.startswith("pOutput"):
        return PHASE_IDS["output"]
    if function == "init" or function.startswith("cpu_init_"):
        return PHASE_IDS["init"]
    if function == "dumpState" or function.startswith("cpu_dump_"):
        return PHASE_IDS["dump"]
    return PHASE_IDS["other"]


def split_binary(body: str) -> tuple[str, str, str] | None:
    depth = 0
    found: list[tuple[int, str]] = []
    i = 0
    while i < len(body):
        char = body[i]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth < 0:
                return None
        elif depth == 0 and char in "&|^":
            operator = body[i:i + 2] if body[i:i + 2] in ("&&", "||") else char
            found.append((i, operator))
            i += len(operator) - 1
        i += 1
    if depth or len(found) != 1:
        return None
    offset, operator = found[0]
    lhs = body[:offset].strip()
    rhs = body[offset + len(operator):].strip()
    return (lhs, operator, rhs) if lhs and rhs else None


def value_id(atom: str) -> int:
    match = VALUE_RE.fullmatch(atom)
    return int(match[1]) if match else 0


def length_bucket(length: int) -> str:
    for low, high in BUCKETS:
        if high is None or length <= high:
            return f"{low}+" if high is None else f"{low}-{high}"
    raise AssertionError(length)


class Census:
    def __init__(self) -> None:
        self.kind = bytearray(1)
        self.phase = bytearray(1)
        self.lhs = array("I", [0])
        self.rhs = array("I", [0])
        self.file = array("H", [0])
        self.line = array("I", [0])
        self.order = array("I")
        self.terminals: list[tuple[int, int, int, int, int, int]] = []
        self.op_counts: dict[str, Counter[str]] = defaultdict(Counter)
        self.normalized_assignments = Counter()
        self.nonbinary_assignments = Counter()
        self.function_counts = Counter()
        self.file_paths: list[Path] = [Path("")]

    def _grow(self, index: int) -> None:
        if index < len(self.kind):
            return
        target = max(index + 1, len(self.kind) * 2)
        extra = target - len(self.kind)
        self.kind.extend(bytes(extra))
        self.phase.extend(bytes(extra))
        self.lhs.extend(array("I", [0]) * extra)
        self.rhs.extend(array("I", [0]) * extra)
        self.file.extend(array("H", [0]) * extra)
        self.line.extend(array("I", [0]) * extra)

    def scan_stream(self, stream, file_index: int) -> None:
        phase = PHASE_IDS["other"]
        for line_number, line in enumerate(stream, 1):
            function = FUNCTION_RE.match(line)
            if function:
                phase = phase_of(function[1])
                self.function_counts[PHASE_NAMES[phase]] += 1
                continue
            if "static_cast<bool>(((" not in line:
                continue
            match = BOOL_RE.match(line)
            terminal = TERMINAL_RE.match(line) if not match else None
            if not match and not terminal:
                continue
            phase_name = PHASE_NAMES[phase]
            self.normalized_assignments[phase_name] += 1
            parts = split_binary(match[2] if match else terminal[1])
            if not parts:
                self.nonbinary_assignments[phase_name] += 1
                continue
            left, operator, right = parts
            self.op_counts[phase_name][operator] += 1
            if terminal:
                self.terminals.append((phase, OPERATORS[operator], value_id(left),
                                       value_id(right), file_index, line_number))
                continue
            result = int(match[1])
            self._grow(result)
            if self.kind[result]:
                raise ValueError(f"duplicate bool value v{result} at {self.file_paths[file_index]}:{line_number}")
            self.kind[result] = OPERATORS[operator]
            self.phase[result] = phase
            self.lhs[result] = value_id(left)
            self.rhs[result] = value_id(right)
            self.file[result] = file_index
            self.line[result] = line_number
            self.order.append(result)

    def chains(self):
        count = len(self.kind)
        link = array("I", [0]) * count
        same_uses = bytearray(count)
        for result in self.order:
            kind = self.kind[result]
            phase = self.phase[result]
            operands = (self.lhs[result], self.rhs[result])
            parents = [operand for operand in operands
                       if operand < count and self.kind[operand] == kind and self.phase[operand] == phase]
            for parent in set(parents):
                same_uses[parent] = min(2, same_uses[parent] + 1)
            if len(parents) == 1:
                link[result] = parents[0]
        terminal_parents = []
        for phase, kind, left, right, _, _ in self.terminals:
            operands = (left, right)
            parents = [operand for operand in operands
                       if operand < count and self.kind[operand] == kind and self.phase[operand] == phase]
            for parent in set(parents):
                same_uses[parent] = min(2, same_uses[parent] + 1)
            terminal_parents.append(parents[0] if len(parents) == 1 else 0)

        length = array("I", [0]) * count
        continued = bytearray(count)
        all_and_terms = bytearray(count)
        and_kind = OPERATORS["&"]
        for result in self.order:
            pending = []
            current = result
            while current and not length[current]:
                pending.append(current)
                parent = link[current]
                current = parent if parent and same_uses[parent] == 1 else 0
                if len(pending) > count:
                    raise ValueError("cycle in generated bool assignments")
            while pending:
                node = pending.pop()
                parent = link[node]
                left, right = self.lhs[node], self.rhs[node]
                if parent and same_uses[parent] == 1:
                    length[node] = length[parent] + 1
                    continued[parent] = 1
                    other = right if left == parent else left
                    all_and_terms[node] = (all_and_terms[parent] and other < count
                                           and self.kind[other] == and_kind
                                           and self.phase[other] == self.phase[node])
                else:
                    length[node] = 1
                    all_and_terms[node] = (left < count and right < count
                                           and self.kind[left] == and_kind
                                           and self.kind[right] == and_kind
                                           and self.phase[left] == self.phase[node]
                                           and self.phase[right] == self.phase[node])

        for parent in terminal_parents:
            if parent and same_uses[parent] == 1:
                continued[parent] = 1

        for result in self.order:
            if not continued[result] and length[result] >= 2:
                yield {
                    "phase": PHASE_NAMES[self.phase[result]],
                    "operator": OPERATOR_NAMES[self.kind[result]],
                    "length": length[result],
                    "and_terms": bool(all_and_terms[result]) if self.kind[result] == OPERATORS["|"] else False,
                    "value": result,
                    "file": str(self.file_paths[self.file[result]]),
                    "line": self.line[result],
                }
        for terminal, parent in zip(self.terminals, terminal_parents):
            phase, kind, left, right, file_index, line_number = terminal
            if parent and same_uses[parent] == 1:
                chain_length = length[parent] + 1
                other = right if left == parent else left
                and_terms = (bool(all_and_terms[parent]) and other < count
                             and self.kind[other] == and_kind and self.phase[other] == phase)
            else:
                chain_length = 1
                and_terms = (left < count and right < count
                             and self.kind[left] == and_kind and self.kind[right] == and_kind
                             and self.phase[left] == phase and self.phase[right] == phase)
            if chain_length >= 2:
                yield {
                    "phase": PHASE_NAMES[phase],
                    "operator": OPERATOR_NAMES[kind],
                    "length": chain_length,
                    "and_terms": bool(and_terms) if kind == OPERATORS["|"] else False,
                    "value": "",
                    "file": str(self.file_paths[file_index]),
                    "line": line_number,
                }


def summarize(census: Census, long_csv: Path | None = None) -> dict:
    histograms: dict[str, dict[str, Counter[int]]] = defaultdict(lambda: defaultdict(Counter))
    all_and_histograms: dict[str, Counter[int]] = defaultdict(Counter)
    top: list[tuple[int, int, dict]] = []
    long_rows = 0
    output = None
    if long_csv:
        long_csv.parent.mkdir(parents=True, exist_ok=True)
        output = long_csv.open("w", newline="", encoding="utf-8")
        writer = csv.DictWriter(output, fieldnames=("phase", "operator", "length", "and_terms", "value", "file", "line"))
        writer.writeheader()
    top_seen = 0
    try:
        for chain in census.chains():
            phase, operator, length = chain["phase"], chain["operator"], chain["length"]
            histograms[phase][operator][length] += 1
            if chain["and_terms"]:
                all_and_histograms[phase][length] += 1
            top_seen += 1
            item = (length, top_seen, chain)
            if len(top) < 30:
                heapq.heappush(top, item)
            elif item[:2] > top[0][:2]:
                heapq.heapreplace(top, item)
            if length >= 16:
                long_rows += 1
                if output:
                    writer.writerow(chain)
    finally:
        if output:
            output.close()

    phases = {}
    for phase in PHASE_NAMES:
        operators = {}
        for operator in OPERATORS:
            hist = histograms[phase][operator]
            operators[operator] = {
                "ops": census.op_counts[phase][operator],
                "chains_ge2": sum(hist.values()),
                "chains_ge16": sum(n for length, n in hist.items() if length >= 16),
                "chains_ge32": sum(n for length, n in hist.items() if length >= 32),
                "max_length": max(hist, default=0),
                "histogram": {str(length): hist[length] for length in sorted(hist)},
                "buckets": {length_bucket(low): sum(n for length, n in hist.items()
                                                  if length >= low and (high is None or length <= high))
                            for low, high in BUCKETS},
            }
        and_hist = all_and_histograms[phase]
        phases[phase] = {
            "functions": census.function_counts[phase],
            "normalized_bool_assignments": census.normalized_assignments[phase],
            "nonbinary_assignments": census.nonbinary_assignments[phase],
            "operators": operators,
            "or_of_and": {
                "chains_ge2": sum(and_hist.values()),
                "chains_ge16": sum(n for length, n in and_hist.items() if length >= 16),
                "max_length": max(and_hist, default=0),
                "histogram": {str(length): and_hist[length] for length in sorted(and_hist)},
            },
        }
    return {
        "definition": "Maximal serial single-operator runs of explicit normalized one-bit cpu_v/cpu_f.v assignments; length counts binary operations; fanout and joins break runs.",
        "long_csv_min_length": 16,
        "long_csv_rows": long_rows,
        "parsed_binary_ops": len(census.order) + len(census.terminals),
        "named_binary_ops": len(census.order),
        "boundary_terminal_binary_ops": len(census.terminals),
        "phases": phases,
        "top_chains": [item[2] for item in sorted(top, reverse=True)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--long-csv", type=Path)
    args = parser.parse_args()
    files = sorted(args.model_dir.glob("grhsim_SimTop_tu*.cpp"),
                   key=lambda path: int(TU_RE.fullmatch(path.name)[1]))
    if not files:
        parser.error("model directory has no grhsim_SimTop_tu*.cpp files")
    census = Census()
    census.file_paths.extend(files)
    for index, path in enumerate(files, 1):
        with path.open("r", encoding="utf-8", errors="replace", buffering=1 << 20) as stream:
            census.scan_stream(stream, index)
        if index % 100 == 0:
            print(f"scanned {index}/{len(files)} files, {len(census.order)} bool binary ops", file=sys.stderr, flush=True)
    report = summarize(census, args.long_csv)
    report["model_dir"] = str(args.model_dir)
    report["cpp_files"] = len(files)
    report["cpp_bytes"] = sum(path.stat().st_size for path in files)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(f"files={len(files)} parsed_binary_ops={report['parsed_binary_ops']} long_chains_ge16={report['long_csv_rows']}")
    for phase in PHASE_NAMES:
        row = report["phases"][phase]
        operators = row["operators"]
        long_count = sum(item["chains_ge16"] for item in operators.values())
        max_length = max(item["max_length"] for item in operators.values())
        print(f"{phase:>10}  OR={operators['|']['chains_ge2']:>7}  AND={operators['&']['chains_ge2']:>7}  "
              f"XOR={operators['^']['chains_ge2']:>7}  >=16={long_count:>6}  max={max_length:>4}  "
              f"OR-of-AND={row['or_of_and']['chains_ge2']:>6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
