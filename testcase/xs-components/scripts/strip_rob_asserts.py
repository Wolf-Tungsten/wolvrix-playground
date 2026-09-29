#!/usr/bin/env python3
"""Neuter assertion *reporting* in the generated gsim/GrhSIM Rob models.

Standalone random-stimulus benchmarking trips the XiangShan difftest
assertions on nearly every cycle. Both models then pay for report
formatting and I/O (gsim: fprintf per gAssert; GrhSIM: std::string
construction per fwrite/xs_assert_v2 call site), which never happens in
legal-stimulus reference runs and would dominate the measured cycle time.

This script keeps every assertion *predicate* but drops the report path:

- gsim: rewrite the single `gAssert` macro definition in <gsim-dir>/Rob.h
  to `do { if (!(cond)) { } } while (0)`, retiring all 1089 call sites.
- GrhSIM: delete `if (cond) { ... }` statements in <grhsim-dir>/*.cpp whose
  entire body is assertion reporting, i.e. either
      ::xs_assert_v2(...);
  or
      const std::array<grhsim_task_arg,N> cpu_args{{...}};
      cpu_system_task("fwrite", cpu_args);
  Blocks containing anything else (state writes, other tasks) are kept.

Idempotent: re-running after a successful strip is a no-op.
"""

import argparse
import re
import sys
from pathlib import Path

GASSERT_DEFINE = (
    '#define gAssert(cond, ...) do {if (!(cond)) {fprintf(stderr, "\\33[1;31m");'
    'fprintf(stderr, __VA_ARGS__);fprintf(stderr, "\\33[0m\\n");assert(cond);}} while (0)'
)
GASSERT_NEUTERED = "#define gAssert(cond, ...) do {if (!(cond)) { }} while (0)"

STMT_RES = [
    re.compile(r"::xs_assert_v2\(.*?\);", re.DOTALL),
    re.compile(r"const std::array<grhsim_task_arg,\d+> cpu_args\{\{.*?\}\};", re.DOTALL),
    re.compile(r'cpu_system_task\("fwrite",cpu_args\);'),
]

COMMENT_RES = [
    re.compile(r"//[^\n]*"),
    re.compile(r"/\*.*?\*/", re.DOTALL),
]

ASSERT_MARKERS = ("xs_assert_v2", "Assertion failed")


def is_pure_assert_report(inner: str) -> bool:
    """True when every statement in `inner` is assertion reporting.

    Reporting statements may sit in anonymous `{ ... }` blocks (gate-merge
    wrapping) and carry generated `// cpu_*` comments; both are inert.
    """
    if not any(marker in inner for marker in ASSERT_MARKERS):
        return False
    rest = inner
    for pattern in STMT_RES:
        rest = pattern.sub("", rest)
    for pattern in COMMENT_RES:
        rest = pattern.sub("", rest)
    return rest.replace("{", "").replace("}", "").strip() == ""


def strip_gsim(model_dir: Path) -> str:
    header = model_dir / "Rob.h"
    text = header.read_text(encoding="utf-8")
    if GASSERT_NEUTERED in text:
        return "gAssert already neutered"
    if GASSERT_DEFINE not in text:
        raise RuntimeError(f"gAssert define not found in {header}")
    header.write_text(text.replace(GASSERT_DEFINE, GASSERT_NEUTERED, 1), encoding="utf-8")
    return "gAssert reporting neutered in Rob.h"


def match_balanced(text: str, start: int, open_ch: str, close_ch: int) -> int:
    """Return the index just past the balanced close for text[start]==open_ch."""
    assert text[start] == open_ch
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise RuntimeError("unbalanced delimiter")


def strip_grhsim_file(path: Path) -> tuple[int, int]:
    """Delete pure assertion-report if-blocks. Returns (removed, kept_markers)."""
    text = path.read_text(encoding="utf-8")
    if not any(marker in text for marker in ASSERT_MARKERS):
        return (0, 0)
    spans: list[tuple[int, int]] = []
    kept = 0
    for match in re.finditer(r"\bif\s*\(", text):
        cond_open = text.index("(", match.start())
        cond_end = match_balanced(text, cond_open, "(", ")")
        pos = cond_end
        while pos < len(text) and text[pos] in " \t\r\n":
            pos += 1
        if pos >= len(text) or text[pos] != "{":
            continue
        block_end = match_balanced(text, pos, "{", "}")
        inner = text[pos + 1 : block_end - 1]
        if not any(marker in inner for marker in ASSERT_MARKERS):
            continue
        # Never delete an if that has an else branch: the else would dangle.
        tail = text[block_end:]
        stripped = COMMENT_RES[0].sub("", tail[: tail.find("\n") if "\n" in tail else len(tail)])
        if stripped.lstrip().startswith("else"):
            kept += 1
            continue
        if is_pure_assert_report(inner):
            spans.append((match.start(), block_end))
        else:
            kept += 1
    if not spans:
        return (0, kept)
    out = []
    prev = 0
    for begin, end in spans:
        out.append(text[prev:begin])
        prev = end
    out.append(text[prev:])
    path.write_text("".join(out), encoding="utf-8")
    return (len(spans), kept)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gsim-dir", type=Path, required=True)
    parser.add_argument("--grhsim-dir", type=Path, required=True)
    args = parser.parse_args()

    print(f"[strip-robs-asserts] gsim: {strip_gsim(args.gsim_dir)}")

    total_removed = 0
    total_kept = 0
    touched = 0
    for path in sorted(args.grhsim_dir.glob("*.cpp")):
        removed, kept = strip_grhsim_file(path)
        total_removed += removed
        total_kept += kept
        if removed:
            touched += 1
    print(
        f"[strip-robs-asserts] grhsim: removed {total_removed} report blocks "
        f"across {touched} files; kept {total_kept} mixed blocks"
    )
    if total_kept:
        print("[strip-robs-asserts] WARNING: mixed blocks kept, inspect manually", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
