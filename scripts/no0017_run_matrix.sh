#!/usr/bin/env bash
# NO0017 run matrix: execute every built variant with the right env and save
# logs+artifacts under build/logs/no0017/<variant>/.
# Usage: scripts/no0017_run_matrix.sh [variant ...]  (default: all known)
set -u
REPO=/home/gaoruihao/wksp/wolvrix-playground
OUT=$REPO/build/logs/no0017
BIN=$REPO/testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
NEMU=$REPO/testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
CYCLES=${XS_SIM_MAX_CYCLE:-50000}
mkdir -p "$OUT"

run_one() {
    local name=$1 build_dir=$2; shift 2
    local extra_env=("$@")
    if [ ! -x "$REPO/build/xs/$build_dir/emu" ]; then
        echo "[SKIP] $name: $REPO/build/xs/$build_dir/emu missing"
        return 0
    fi
    local dir=$OUT/$name
    mkdir -p "$dir"
    echo "[RUN] $name (cycles=$CYCLES)"
    (cd "$REPO/build/xs/$build_dir" && \
        env EMU_PHASE_TIMING=1 "${extra_env[@]}" /usr/bin/time -v ./emu \
            -i "$BIN" --diff "$NEMU" -b 0 -e 0 -C "$CYCLES" \
            > "$dir/emu.log" 2> "$dir/time.log")
    local rc=$?
    echo "[DONE] $name rc=$rc"
    return $rc
}

variants=("$@")
if [ ${#variants[@]} -eq 0 ]; then
    variants=(gsim-baseline gsim-prof am-anchor am-trace am-fulleval am-cap1 am-cap5 am-cap100 am-gsim)
fi

rc_all=0
for v in "${variants[@]}"; do
    case "$v" in
        gsim-baseline)
            run_one gsim-baseline gsim ;;
        gsim-prof)
            run_one gsim-prof gsim-prof \
                EMU_RUNTIME_PROFILE=1 \
                GSIM_SUPERNODE_TSV="$OUT/gsim-prof/supernode_fire.tsv" ;;
        am-anchor)
            run_one am-anchor grhsim-am-no0017 \
                EMU_RUNTIME_PROFILE=1 ;;
        am-trace)
            run_one am-trace grhsim-am-no0017-trace \
                EMU_RUNTIME_PROFILE=1 \
                EMU_AM_BLOCK_EXECS="$OUT/am-trace/block_execs.txt" \
                EMU_AM_CHANGED_TRACE="$OUT/am-trace/changed_trace.bin" \
                EMU_AM_TRACE_BEGIN_EVAL=20000 EMU_AM_TRACE_END_EVAL=20100 ;;
        am-fulleval)
            run_one am-fulleval grhsim-am-no0017-fulleval \
                EMU_RUNTIME_PROFILE=1 \
                EMU_AM_BLOCK_EXECS="$OUT/am-fulleval/block_execs.txt" ;;
        am-cap1)
            run_one am-cap1 grhsim-am-no0017-cap1 \
                EMU_RUNTIME_PROFILE=1 \
                EMU_AM_BLOCK_EXECS="$OUT/am-cap1/block_execs.txt" ;;
        am-cap5)
            run_one am-cap5 grhsim-am-no0017-cap5 \
                EMU_RUNTIME_PROFILE=1 \
                EMU_AM_BLOCK_EXECS="$OUT/am-cap5/block_execs.txt" ;;
        am-cap100)
            run_one am-cap100 grhsim-am-no0017-cap100 \
                EMU_RUNTIME_PROFILE=1 \
                EMU_AM_BLOCK_EXECS="$OUT/am-cap100/block_execs.txt" ;;
        am-gsim)
            run_one am-gsim gsim-am-import/difftest \
                EMU_RUNTIME_PROFILE=1 \
                EMU_AM_BLOCK_EXECS="$OUT/am-gsim/block_execs.txt" ;;
        *)
            echo "[FAIL] unknown variant: $v"; rc_all=1 ;;
    esac
    [ $? -ne 0 ] && rc_all=1
done
exit $rc_all
