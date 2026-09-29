#!/usr/bin/env python3
"""Diff two GrhSIM IR golden traces and report the first divergent eval.

Trace lines look like: `eval 12 a=00ff clk=1 q=0`.
Exit code 0 when the traces are identical; 1 on first divergence (with a
report naming the eval index and every differing port); 2 on usage/IO errors.
"""

import argparse
import sys
from pathlib import Path


def parse_line(line: str) -> tuple[str, dict[str, str]]:
    tokens = line.strip().split()
    head = " ".join(tokens[:2]) if len(tokens) >= 2 else (tokens[0] if tokens else "")
    ports: dict[str, str] = {}
    for item in tokens[2:] if len(tokens) >= 2 else []:
        name, _, value = item.partition("=")
        ports[name] = value
    return head, ports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("golden", type=Path)
    parser.add_argument("actual", type=Path)
    parser.add_argument("--max-report", type=int, default=16, help="max differing ports to print")
    args = parser.parse_args()

    golden_lines = args.golden.read_text(encoding="utf-8").splitlines()
    actual_lines = args.actual.read_text(encoding="utf-8").splitlines()

    common = min(len(golden_lines), len(actual_lines))
    for index in range(common):
        if golden_lines[index] == actual_lines[index]:
            continue
        g_head, g_ports = parse_line(golden_lines[index])
        a_head, a_ports = parse_line(actual_lines[index])
        print(f"[trace-diff] first divergence at line {index + 1} ({g_head} vs {a_head})")
        names = sorted(set(g_ports) | set(a_ports))
        reported = 0
        for name in names:
            g_value = g_ports.get(name, "<missing>")
            a_value = a_ports.get(name, "<missing>")
            if g_value == a_value:
                continue
            print(f"  {name}: golden={g_value} actual={a_value}")
            reported += 1
            if reported >= args.max_report:
                print(f"  ... ({len(names)} ports total, truncated)")
                break
        return 1

    if len(golden_lines) != len(actual_lines):
        print(
            f"[trace-diff] length mismatch: golden has {len(golden_lines)} evals, "
            f"actual has {len(actual_lines)} evals (first {common} identical)"
        )
        return 1

    print(f"[trace-diff] identical: {len(golden_lines)} evals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
