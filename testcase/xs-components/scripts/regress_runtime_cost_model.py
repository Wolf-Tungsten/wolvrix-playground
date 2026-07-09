#!/usr/bin/env python3

import sys


MESSAGE = (
    "regress_runtime_cost_model.py is obsolete: the old runtime profile cost "
    "model inputs were removed and must not be used."
)


def main() -> int:
    print(MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
