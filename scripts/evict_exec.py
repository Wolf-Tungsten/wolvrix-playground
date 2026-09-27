"""Evict an emu's file pages, then replace this process with that emu."""

import os
from pathlib import Path
import sys

from benchmark_grhsim_ir import evict_page_cache


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: evict_exec.py EXECUTABLE [ARG ...]")
    executable = Path(sys.argv[1]).resolve(strict=True)
    if not evict_page_cache(executable):
        raise SystemExit(f"page-cache eviction failed: {executable}")
    print(f"[emu-cache] evicted {executable}", flush=True)
    os.execv(str(executable), [str(executable), *sys.argv[2:]])
