#!/usr/bin/env bash
set -euo pipefail
ulimit -s unlimited
repo=$(cd "$(dirname "$0")/.." && pwd)
previous="$repo/build/armor-acc-default-v1"
here="$previous/perf-regression"
mkdir -p "$here"
tools_dir="$previous/tools"
xs=$(cd "$repo/../wolvrix-playground-new-xiangshan" && pwd)
frozen=$xs/build/xs/parent-default-single-20261114-v1
export PYTHONPATH="$tools_dir/python" LD_LIBRARY_PATH="$tools_dir" NOOP_HOME="$xs/testcase/xiangshan"
export WOLVRIX_XS_GRHSIM_ACCUMULATE_BANK=0
export WOLVRIX_XS_GRHSIM_PRE_REG_TO_MEM_JSON="$here/off-pre-reg-to-mem.json"
cd "$xs"
WOLVRIX_XS_GRHSIM_STOP_AFTER_PRE_SCHED=1 /usr/bin/python3 "$repo/scripts/wolvrix_xs_grhsim.py" "$frozen/input.f" SimTop "$here/frontend/model" "" "$frozen/read_args.txt" info > "$here/off-frontend.log" 2>&1
cd "$repo"
WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON=1 /usr/bin/python3 scripts/wolvrix_xs_grhsim.py "$frozen/input.f" SimTop "$here/off/model" "" "$frozen/read_args.txt" info > "$here/off-emit.log" 2>&1
/usr/bin/python3 "$repo/scripts/armor_acc_default_verify.py" perf-regression/off > "$here/off-build-verify.log" 2>&1
