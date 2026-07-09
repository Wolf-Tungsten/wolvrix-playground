#!/usr/bin/env python3

import sys


MESSAGE = (
    "xs_no0076_stats.py is obsolete: the old GSim/GrhSIM static statistics "
    "definitions were removed and must not be used."
)


def main() -> int:
    print(MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
