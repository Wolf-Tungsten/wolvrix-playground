#!/usr/bin/env bash

set -euo pipefail

REAL_CXX="${GRHSIM_REAL_CXX:-/home/gaoruihao/download/LLVM-21.1.8-Linux-X64/bin/clang++}"
LOG_PATH="${GRHSIM_COMPILE_TIME_LOG:-}"

src=""
obj=""
next_is_src=0
next_is_obj=0

for arg in "$@"; do
    if [[ "$next_is_src" -eq 1 ]]; then
        src="$arg"
        next_is_src=0
        continue
    fi
    if [[ "$next_is_obj" -eq 1 ]]; then
        obj="$arg"
        next_is_obj=0
        continue
    fi
    case "$arg" in
        -c)
            next_is_src=1
            ;;
        -o)
            next_is_obj=1
            ;;
    esac
done

start_ns="$(date +%s%N)"
if "$REAL_CXX" "$@"; then
    status=0
else
    status=$?
fi
end_ns="$(date +%s%N)"

if [[ -n "$LOG_PATH" ]]; then
    elapsed_ns=$((end_ns - start_ns))
    mkdir -p "$(dirname "$LOG_PATH")"
    exec 9>>"${LOG_PATH}.lock"
    flock 9
    if [[ ! -s "$LOG_PATH" ]]; then
        printf 'elapsed_seconds\telapsed_ns\tstatus\tsrc\tobj\tcompiler\n' >>"$LOG_PATH"
    fi
    elapsed_seconds="$(python3 - "$elapsed_ns" <<'PY'
import sys
print(f"{int(sys.argv[1]) / 1_000_000_000:.6f}")
PY
)"
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$elapsed_seconds" \
        "$elapsed_ns" \
        "$status" \
        "$src" \
        "$obj" \
        "$REAL_CXX" >>"$LOG_PATH"
    flock -u 9
fi

exit "$status"
