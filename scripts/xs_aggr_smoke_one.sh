#!/usr/bin/env bash
# S4 阶段性 smoke：逐文件子进程隔离 ingest + grh.verify（崩溃不传染）。
# 用法: scripts/xs_aggr_smoke_one.sh <file.sv>
# 分类: OK / FAIL / CRASH / SKIP（unknown module 跨文件依赖、xs_assert 宏依赖）
set -u
f="$1"
out=$(python3 -c "
import wolvrix, sys
sess = wolvrix.Session()
try:
    sess.read_sv('$f')
    sess.run_pass('grh.verify', design='design.main')
    print('ZYGO_OK')
except Exception as e:
    print('ZYGO_FAIL', str(e).splitlines()[0][:200])
" 2>&1)
rc=$?
if [ $rc -ne 0 ]; then
    echo "CRASH $f (rc=$rc)"
elif echo "$out" | grep -q "unknown module"; then
    echo "SKIP $f"
elif echo "$out" | grep -q "xs_assert"; then
    echo "SKIP $f"
elif echo "$out" | grep -q "ZYGO_OK"; then
    echo "OK   $f"
else
    msg=$(echo "$out" | grep "ZYGO_FAIL" | head -1 | sed 's/^ZYGO_FAIL //')
    echo "FAIL $f: $msg"
fi
exit 0
