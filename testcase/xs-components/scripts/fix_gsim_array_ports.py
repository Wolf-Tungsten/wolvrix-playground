#!/usr/bin/env python3
"""Fix gsim-generated broken top-level port accessors.

Two defect classes are rewritten in place (idempotent):

1. Array ports: gsim emits scalar bodies for top-level ports that remain
   arrays (e.g. ``uint8_t io__DOT__enq__DOT__req__DOT__valid[8]`` gets
   ``set_...(uint8_t val) { if (arr != val) { arr = val; ... } }``), which
   does not compile. They become pointer-based per-element accessors:

       void set_name(const uint8_t *val) {
         for (unsigned i = 0; i < N; ++i) {
           if (name[idx(i)] != val[i]) {
             name[idx(i)] = val[i];
             <original activation-flag updates>
           }
         }
       }
       void get_name(uint8_t *out) {
         for (unsigned i = 0; i < N; ++i) { out[i] = name[idx(i)]; }
       }

   The activation-flag block from the original body is preserved verbatim so
   the delta-driven semantics stay identical to the scalar form.

2. Dead input ports: gsim removes the storage member of an unused top-level
   input but still emits a scalar ``set_`` referencing it. The body becomes
   ``(void)val;`` (the port is dead inside the model, so ignoring writes is
   semantically exact).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CTYPE = r"(?:unsigned _BitInt\(\d+\)|uint8_t|uint16_t|uint32_t|uint64_t)"


def log(message: str) -> None:
    sys.stderr.write(f"[fix-gsim-array-ports] {message}\n")


def flat_index(dims: list[int], flat: str) -> str:
    """C++ subscript expression for the flat element index of a member."""
    if len(dims) == 1:
        return f"[{flat}]"
    expr = ""
    stride = 1
    for dim in reversed(dims[1:]):
        stride *= dim
    parts = []
    remaining = flat
    for i, dim in enumerate(dims):
        if i == len(dims) - 1:
            parts.append(f"[{remaining}]")
        else:
            parts.append(f"[{remaining} / {stride}]")
            remaining = f"({remaining}) % {stride}"
            stride //= dims[i + 1] if i + 1 < len(dims) else 1
    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True, help="gsim model output directory")
    parser.add_argument("--top", required=True)
    args = parser.parse_args()

    model_dir = Path(args.dir)
    header_path = model_dir / f"{args.top}.h"
    header = header_path.read_text(encoding="utf-8")

    # name -> (ctype, dims) for every member declaration with a width comment.
    members: dict[str, tuple[str, tuple[int, ...]]] = {}
    member_re = re.compile(rf"^({CTYPE}) (\w+)((?:\[\d+\])*) *; // width = \d+", re.MULTILINE)
    for match in member_re.finditer(header):
        dims = tuple(int(d) for d in re.findall(r"\[(\d+)\]", match.group(3)))
        members[match.group(2)] = (match.group(1), dims)

    scalar_set_re = re.compile(rf"^void set_(\w+)\(({CTYPE}) val\);$", re.MULTILINE)
    ptr_set_re = re.compile(rf"^void set_(\w+)\(const ({CTYPE}) \*val\);$", re.MULTILINE)
    scalar_get_re = re.compile(rf"^({CTYPE}) get_(\w+)\(\);$", re.MULTILINE)
    ptr_get_re = re.compile(rf"^void get_(\w+)\(({CTYPE}) \*out\);$", re.MULTILINE)

    scalar_sets = {m.group(1): m.group(2) for m in scalar_set_re.finditer(header)}
    ptr_sets = {m.group(1): m.group(2) for m in ptr_set_re.finditer(header)}
    scalar_gets = {m.group(2): m.group(1) for m in scalar_get_re.finditer(header)}
    ptr_gets = {m.group(1): m.group(2) for m in ptr_get_re.finditer(header)}

    # --- class 1: array ports still in scalar form -------------------------
    set_array = sorted(
        (n for n in scalar_sets if n in members and members[n][1]), key=len, reverse=True
    )
    get_array = sorted(
        (n for n in scalar_gets if n in members and members[n][1]), key=len, reverse=True
    )
    # --- class 2: scalar set_ whose member vanished ------------------------
    dead_sets = sorted(
        (n for n in scalar_sets if n not in members and n not in ("clock", "reset")),
        key=len,
        reverse=True,
    )
    log(
        f"array set_ to patch: {len(set_array)}, array get_ to patch: {len(get_array)}, "
        f"dead set_ to stub: {len(dead_sets)} (already pointer-form: {len(ptr_sets)} set, {len(ptr_gets)} get)"
    )
    if not set_array and not get_array and not dead_sets:
        log("nothing to patch")
        return 0

    for name in set_array:
        ctype = scalar_sets[name]
        header = header.replace(
            f"void set_{name}({ctype} val);", f"void set_{name}(const {ctype} *val);"
        )
    for name in get_array:
        ctype = scalar_gets[name]
        header = header.replace(f"{ctype} get_{name}();", f"void get_{name}({ctype} *out);")
    header_path.write_text(header, encoding="utf-8")

    cls = f"S{args.top}"
    patched_defs = 0
    missing_defs: list[str] = []

    set_jobs = [(n, scalar_sets[n], "array") for n in set_array]
    set_jobs += [(n, scalar_sets[n], "dead") for n in dead_sets]
    if set_jobs:
        alt = "|".join(re.escape(n) for n, _, _ in set_jobs)
        set_def_re = re.compile(
            rf"void {cls}::set_({alt})\(({CTYPE}) val\) \{{\n"
            rf"  if \(\1 != val\) \{{ \n"
            rf"    \1 = val;\n"
            rf"(.*?)"
            rf"  \}}\n"
            rf"\}}",
            re.DOTALL,
        )
        kind_by_name = {n: k for n, _, k in set_jobs}
        found: set[str] = set()

        def rewrite_set(match: re.Match) -> str:
            nonlocal patched_defs
            name, ctype, flags = match.group(1), match.group(2), match.group(3)
            found.add(name)
            patched_defs += 1
            if kind_by_name[name] == "dead":
                return f"void {cls}::set_{name}({ctype} val) {{\n  (void)val;\n}}"
            dims = list(members[name][1])
            total = 1
            for d in dims:
                total *= d
            sub = flat_index(dims, "i")
            return (
                f"void {cls}::set_{name}(const {ctype} *val) {{\n"
                f"  for (unsigned i = 0; i < {total}u; ++i) {{\n"
                f"    if ({name}{sub} != val[i]) {{ \n"
                f"      {name}{sub} = val[i];\n"
                f"{flags}"
                f"    }}\n"
                f"  }}\n"
                f"}}"
            )

        for cpp_path in sorted(model_dir.glob(f"{args.top}*.cpp")):
            text = cpp_path.read_text(encoding="utf-8")
            new_text, count = set_def_re.subn(rewrite_set, text)
            if count:
                cpp_path.write_text(new_text, encoding="utf-8")
        for name, ctype, kind in set_jobs:
            if name in found:
                continue
            if kind == "dead":
                stub = f"void {cls}::set_{name}({ctype} val) {{\n  (void)val;\n}}"
                if any(stub in p.read_text(encoding="utf-8") for p in model_dir.glob(f"{args.top}*.cpp")):
                    continue
            missing_defs.append(name)

    if get_array:
        alt = "|".join(re.escape(n) for n in get_array)
        get_def_re = re.compile(
            rf"({CTYPE}) {cls}::get_({alt})\(\) \{{\n"
            rf"  return (.*?);\n"
            rf"\}}",
            re.DOTALL,
        )
        found = set()

        def rewrite_get(match: re.Match) -> str:
            nonlocal patched_defs
            ctype, name, expr = match.group(1), match.group(2), match.group(3)
            found.add(name)
            patched_defs += 1
            dims = list(members[name][1])
            total = 1
            for d in dims:
                total *= d
            sub = flat_index(dims, "i")
            if expr.strip() == name:
                assign = f"out[i] = {name}{sub};"
            else:
                assign = f"out[i] = static_cast<{ctype}>({expr});"
            return (
                f"void {cls}::get_{name}({ctype} *out) {{\n"
                f"  for (unsigned i = 0; i < {total}u; ++i) {{ {assign} }}\n"
                f"}}"
            )

        for cpp_path in sorted(model_dir.glob(f"{args.top}*.cpp")):
            text = cpp_path.read_text(encoding="utf-8")
            new_text, count = get_def_re.subn(rewrite_get, text)
            if count:
                cpp_path.write_text(new_text, encoding="utf-8")
        missing_defs.extend(n for n in get_array if n not in found)

    log(f"patched {patched_defs} accessor definitions")
    if missing_defs:
        log(f"WARNING: {len(missing_defs)} accessor definitions not found: {missing_defs[:8]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
