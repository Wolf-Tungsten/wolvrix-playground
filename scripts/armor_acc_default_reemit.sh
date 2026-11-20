#!/usr/bin/env bash
set -euo pipefail
ulimit -s unlimited
repo=$(cd "$(dirname "$0")/.." && pwd)
previous="$repo/build/armor-acc-default-v1"
here="$previous/perf-regression"
mkdir -p "$here"
xs=$(cd "$repo/../wolvrix-playground-new-xiangshan" && pwd)
frozen=$xs/build/xs/parent-default-single-20261114-v1
cd "$repo"
unset WOLVRIX_XS_GRHSIM_ACCUMULATE_BANK
export PYTHONPATH="$previous/tools/python" LD_LIBRARY_PATH="$previous/tools" NOOP_HOME="$xs/testcase/xiangshan"
export WOLVRIX_XS_GRHSIM_PRE_REG_TO_MEM_JSON="$previous/xs/model/wolvrix_xs_pre_reg_to_mem.json"
WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON=1 /usr/bin/python3 scripts/wolvrix_xs_grhsim.py "$frozen/input.f" SimTop "$here/default-reemit/model" "" "$frozen/read_args.txt" info > "$here/default-emit.log" 2>&1
