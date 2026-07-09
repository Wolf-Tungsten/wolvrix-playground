#!/usr/bin/env python3

import sys


MESSAGE = (
    "grhsim_opt_metrics.py is obsolete: the old GrhSIM optimization metrics "
    "definitions were removed and must not be used."
)


def main() -> int:
    print(MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
