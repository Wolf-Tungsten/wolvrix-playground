#!/usr/bin/env bash
# Emit one XiangShan model from the default pre-reg-to-mem checkpoint with the
# tools build of build/armor-dispatch-v1.  Extra NAME=VALUE arguments are
# exported to the generator, so one option can be switched per variant.
# usage: armor_dispatch_emit.sh <variant> [NAME=VALUE ...]
set -euo pipefail
ulimit -s unlimited
repo=$(cd "$(dirname "$0")/.." && pwd)
out="$repo/build/armor-dispatch-v1"
variant=$1; shift
xs=$(cd "$repo/../wolvrix-playground-new-xiangshan" && pwd)
frozen=$xs/build/xs/parent-default-single-20261114-v1
cd "$repo"
unset WOLVRIX_XS_GRHSIM_ACCUMULATE_BANK
# This experiment varies eager evaluation at emission and cmov at compilation.
export WOLVRIX_GRHSIM_LOGIC_EAGER_OPERAND_CHARS=0 WOLVRIX_GRHSIM_KEEP_X86_MEMORY_CMOV=0
for setting in "$@"; do export "$setting"; done
export PYTHONPATH="$out/tools/python" LD_LIBRARY_PATH="$out/tools" NOOP_HOME="$xs/testcase/xiangshan"
export WOLVRIX_XS_GRHSIM_PRE_REG_TO_MEM_JSON="$repo/build/armor-acc-default-v1/xs/model/wolvrix_xs_pre_reg_to_mem.json"
mkdir -p "$out/$variant"
printf '%s\n' "$@" > "$out/$variant/emit-settings.txt"
WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON=1 /usr/bin/python3 scripts/wolvrix_xs_grhsim.py "$frozen/input.f" SimTop "$out/$variant/model" "" "$frozen/read_args.txt" info > "$out/$variant/emit.log" 2>&1
