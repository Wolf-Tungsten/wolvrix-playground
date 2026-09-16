"""Audit replicate op shapes: source width, rep count, and result width distribution."""

import argparse
from collections import Counter
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    model = json.loads(args.model.read_bytes())
    ops, values, types, strings = model["operations"], model["values"], model["types"], model["strings"]
    width = {t[0]: (t[3] if t[2] == "logic" else None) for t in types}
    shapes = Counter()
    word_shapes = Counter()
    for op in ops:
        if strings[op[1] - 1] != "core.compute.replicate" or len(op[4]) != 1 or len(op[5]) != 1:
            continue
        rep = None
        for entry in op[7]:
            if len(entry) == 3 and entry[1] == "int" and strings[entry[0] - 1] == "rep":
                rep = entry[2]
        src_w = width.get(values[op[4][0] - 1][1])
        dst_w = width.get(values[op[5][0] - 1][1])
        shapes[(src_w, rep, dst_w)] += 1
        words = (dst_w + 63) // 64 if dst_w else 0
        src_words = (src_w + 63) // 64 if src_w else 0
        word_shapes[(src_words, words)] += 1
    print("== (src_width, rep, dst_width) counts ==")
    for key, count in shapes.most_common(20):
        print(f"{count:>8} src={key[0]} rep={key[1]} dst={key[2]}")
    print("== (src_words, dst_words) counts ==")
    for key, count in word_shapes.most_common(12):
        print(f"{count:>8} {key[0]} -> {key[1]}")


if __name__ == "__main__":
    main()
