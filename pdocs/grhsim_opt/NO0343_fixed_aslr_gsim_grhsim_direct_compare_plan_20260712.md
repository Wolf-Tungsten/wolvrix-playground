# NO0343 Fixed-ASLR GSim / GrhSIM direct compare plan

日期：2026-07-12

## 1. 目的与比较对象

[NO0342](./NO0342_fixed_aslr_no0286_no0300_runtime_gate_20260712.md) 证明 NO0300 在受控地址下相对
NO0286 加速 `4.75%`，且历史随机 PIE 基址显著混淆了版本方向。本轮用相同 fixed-ASLR 口径重新测量
same-FIR GSim 与当前 NO0300 GrhSIM 的差距，避免继续引用 [NO0281](./NO0281_same_fir_gsim_grhsim_frontend_counter_compare_20260711.md)
中未固定 load base 的 `2.67x cycles / 2.38x instructions`。

比较对象为：

```text
GSim  = build/xs_gsim_no0255_current_20260710/gsim/gsim-compile/emu
GrhSIM = build/xs_grhsim_no0300_ordered_affine_fresh_20260712/grhsim/grhsim-compile/emu
```

两者输入 FIR SHA256 均为 `461755d7531724b6e26e1601f45db3344dc8c5c8e099b8f162d7e1b638eee877`，
且二进制均为 x86-64 PIE。GSim SHA256 为
`1b3b4ec741cdd0b2f131e6b384979743e82625f85e7e341bcb988a0607fdbf60`；NO0300 SHA256 见
[NO0300](./NO0300_ordered_memory_write_affine_loop_fresh_gate_20260712.md)。

## 2. 运行口径

执行 GSim / GrhSIM / GSim 的 CoreMark 50k A/B/A：

- 每条命令先 `source env.sh`；
- 外层使用 `setarch "$(uname -m)" -R`；
- 固定 `numactl --membind=1`、`taskset -c 138`；
- workload、NEMU difftest、`-b 0 -e 0 -C 50000` 完全一致；
- 每轮前检查全机 load、CPU138 及 SMT sibling CPU330；
- 先用 GSim `-C 100` 校验五事件均可 `100.00%` 调度；
- 正式五事件为 host cycles、instructions、frontend empty slots、cmask6 cycles 和 backend stall slots。

事件列表：

```text
cycles:u
instructions:u
de_no_dispatch_per_slot.no_ops_from_frontend:u
cpu/de_no_dispatch_per_slot.no_ops_from_frontend,cmask=0x6/u
de_no_dispatch_per_slot.backend_stalls:u
```

## 3. 功能与稳定性门禁

GSim 两轮应分别得到：

```text
Guest cycle spent = 50001
instrCnt / cycleCnt = 73584 / 49998
terminal PC = 0x8000131e
```

GrhSIM 应得到：

```text
Guest cycle spent = 50001
instrCnt / cycleCnt = 73580 / 49996
terminal PC = 0x80001312
```

三轮不得出现 mismatch/assertion/abort，五项 PMU 必须全部 `100.00%` 调度。两次 GSim host cycles
spread 门限为 `1%`；超门限时先检查负载并补跑 GSim，不形成 simulator ratio。

## 4. 输出与判定

以两次 GSim 均值比较 NO0300 GrhSIM，并报告：

1. Host time、cycles、instructions 和 GrhSIM/GSim ratio；
2. frontend empty、cmask6、backend stalls 的绝对 ratio 与 per-cycle ratio；
3. 用 GSim CPI 对 excess cycles 做 extra-instruction / remaining-CPI 算术分解；
4. fixed GSim 相对 NO0281 历史数据的变化，判断 GSim 是否也对 load base 高度敏感；
5. 根据最大剩余项选择下一步 generated C++/dynamic profile 对照，不从旧随机地址 counter 直接延伸。

## 5. 预定产物

```text
build/logs/xs_perf/no0343/gsim_event_preflight_emu.log
build/logs/xs_perf/no0343/gsim_event_preflight_perf.csv
build/logs/xs_perf/no0343/fixed_gsim1_emu.log
build/logs/xs_perf/no0343/fixed_gsim1_perf.csv
build/logs/xs_perf/no0343/fixed_grhsim_emu.log
build/logs/xs_perf/no0343/fixed_grhsim_perf.csv
build/logs/xs_perf/no0343/fixed_gsim2_emu.log
build/logs/xs_perf/no0343/fixed_gsim2_perf.csv
```
