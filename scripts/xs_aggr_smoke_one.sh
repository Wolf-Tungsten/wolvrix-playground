#!/usr/bin/env bash
# S4 阶段性 smoke：逐文件子进程隔离 ingest + grh.verify（崩溃不传染）。
# 用法: scripts/xs_aggr_smoke_one.sh <file.sv>
set -u
f="$1"
out=$(python3 -c "
import wolvrix, sys
sess = wolvrix.Session()
try:
    sess.read_sv('$f')
    sess.run_pass('grh.verify', design='design.main')
    print('OK')
except Exception as e:
    print('FAIL', str(e).splitlines()[0][:200])
" 2>&1)
rc=$?
if [ $rc -ne 0 ]; then
    echo "CRASH $f (rc=$rc)"
elif echo "$out" | grep -q "^OK$"; then
    echo "OK   $f"
else
    msg=$(echo "$out" | grep -v '^\[PY\]\|^Requirement\|^warning\|^  |' | grep -v "^$" | head -1)
    echo "FAIL $f: $msg"
fi
exit 0
