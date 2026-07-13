# NO0363 perf CSV cmask schedule parser correction

日期：2026-07-12

## 1. 问题

执行 [NO0362](./NO0362_simtop_direct_state_read_fixed_aslr_runtime_plan_20260712.md) 的 direct 100-cycle PMU
preflight 后，原始 CSV 明确显示五项事件都是 `100.00%` 调度，但首次 shell verifier 报告一项失败。

首次 verifier 假设 `perf stat -x,` 的 scheduling percentage 固定在 `$5`。该假设对普通事件成立，但以下 event
config 自身含逗号：

```text
cpu/de_no_dispatch_per_slot.no_ops_from_frontend,cmask=0x6/u
```

`perf` 的 CSV 输出不会引用或转义 event name 内的逗号，因此该行比普通事件多一列；`$5` 是 enabled time，
真正的 `100.00` 位于 `$6`。首次 `events=5 bad=1` 是 verifier false negative，不是 PMU multiplex 或运行失败。

## 2. 修正

调度百分比后固定还有两个空字段，因此改为从行尾读取：

```awk
pct = $(NF - 2)
```

显示 event name 时，若 `$4` 以 `cmask=` 开头，则把 `$3,$4` 重新拼接；计数始终读取 `$1`。修正后 NO0362
preflight 的结果为：

```text
cycles:u                                                       100.00
instructions:u                                                  100.00
de_no_dispatch_per_slot.no_ops_from_frontend:u                   100.00
cpu/de_no_dispatch_per_slot.no_ops_from_frontend,cmask=0x6/u    100.00
de_no_dispatch_per_slot.backend_stalls:u                         100.00
events=5 bad=0
```

## 3. 回归

同一修正 verifier 分别检查 NO0344 的历史 GrhSIM 五事件 CSV 与 NO0362 direct preflight：

```text
NO0344 fixed GrhSIM   events=5 bad=0
NO0362 preflight      events=5 bad=0
```

因此修正兼容已有可信结果，也没有放宽 `100.00%` 或五事件数量门禁。现有 preflight 数据有效，无需重跑；下一篇
独立记录其 PMU 接线与功能验收。
