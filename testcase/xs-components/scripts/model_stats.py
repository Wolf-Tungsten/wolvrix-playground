#!/usr/bin/env python3

import sys


MESSAGE = (
    "model_stats.py is obsolete: the old xs-components model statistics "
    "definitions were removed and must not be used."
)


def main() -> int:
    print(MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
