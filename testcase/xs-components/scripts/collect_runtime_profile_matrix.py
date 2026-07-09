#!/usr/bin/env python3

import sys


MESSAGE = (
    "collect_runtime_profile_matrix.py is obsolete: the old GSim/GrhSIM "
    "runtime profile TSV definitions were removed and must not be used."
)


def main() -> int:
    print(MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
