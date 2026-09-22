#!/usr/bin/env python3
"""Classify grhsim_cast_u64 sites in generated cpp by (srcW, dstW, signed).

Elidable under the canonical-form invariant: srcSigned == false and srcW <= dstW.
"""
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
files = sorted(root.glob("*.cpp"))

total = 0
elidable = 0
signed_src = 0
truncating = 0  # dstW < srcW
malformed = 0
width_pairs = {}

# Fast path: cast args are "expr,srcW,dstW,bool" where srcW/dstW are decimal
# literals and bool is true/false. The expr can contain commas inside nested
# parens, so anchor on the trailing ",d+,d+,(true|false))" pattern.
tail = re.compile(r",(\d+),(\d+),(true|false)\)\n?$")

for path in files:
    with path.open() as fh:
        for line in fh:
            start = 0
            while True:
                idx = line.find("grhsim_cast_u64(", start)
                if idx < 0:
                    break
                total += 1
                # scan balanced parens from idx
                depth = 0
                j = idx + len("grhsim_cast_u64(") - 1
                end = -1
                while j < len(line):
                    ch = line[j]
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                        if depth == 0:
                            end = j
                            break
                    j += 1
                if end < 0:
                    # call spans lines (should not happen in emitted code)
                    malformed += 1
                    start = idx + 1
                    continue
                call = line[idx:end + 1]
                m = tail.search(call)
                if not m:
                    malformed += 1
                else:
                    src_w, dst_w, sgn = int(m.group(1)), int(m.group(2)), m.group(3) == "true"
                    if sgn:
                        signed_src += 1
                    elif dst_w < src_w:
                        truncating += 1
                    else:
                        elidable += 1
                        key = (src_w, dst_w)
                        width_pairs[key] = width_pairs.get(key, 0) + 1
                start = end + 1 if end > idx else idx + 1

print(f"files={len(files)}")
print(f"total_cast={total}")
print(f"elidable_unsigned_widening_or_same={elidable} ({elidable / max(total, 1) * 100:.2f}%)")
print(f"signed_source_kept={signed_src}")
print(f"truncating_kept={truncating}")
print(f"malformed={malformed}")
top = sorted(width_pairs.items(), key=lambda kv: -kv[1])[:15]
for (s, d), n in top:
    print(f"  pair srcW={s} dstW={d}: {n}")
