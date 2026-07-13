# NO0362 SimTop direct state-read fixed-ASLR runtime plan

日期：2026-07-12

## 1. 目的与假设

[NO0361](./NO0361_simtop_direct_state_read_50k_functional_gate_20260712.md) 已证明 direct state-read 与 NO0300
在 CoreMark 50k 的五个检查点和最终指令轨迹严格一致；非受控 raw time 方向为 `-7.89%`，但不构成性能结论。
本轮用 [NO0344](./NO0344_fixed_aslr_gsim_grhsim_direct_compare_gate_20260712.md) 的 fixed-ASLR PMU 口径测量
真实收益。

比较对象：

```text
baseline:
  build/xs_grhsim_no0300_ordered_affine_fresh_20260712/grhsim/grhsim-compile/emu
direct:
  build/xs_grhsim_no0357_direct_state_read_20260712/grhsim/grhsim-compile/emu
```

两者 activity schedule 完全相同。direct 只改写 75,830 个严格 single-writer state reads 的 activation frontier
与 read expression，删除 source-read compare/store/changed/alias-OR 工作。因此主要假设是 host instructions 下降，且该下降
转化为 host cycles 收益；backend stall density 是否同步改善作为次级判据。

## 2. 受控运行口径

执行 NO0300 / direct / NO0300 的 CoreMark 50k A/B/A：

- 每条命令先执行 `source env.sh`；
- 使用 `setarch "$(uname -m)" -R` 固定 PIE load base；
- 使用 `numactl --membind=1` 和 `taskset -c 138` 固定 NUMA node 1 与 CPU138；
- 同时监控 CPU138 的 SMT sibling CPU330；
- 固定 seed 0、CoreMark image、NEMU difftest、`-b 0 -e 0 -C 50000`；
- unset `EMU_RUNTIME_PROFILE`，设置 `EMU_PROGRESS_EVERY_CYCLES=0`；
- 三轮串行，运行前检查全机 load、目标核空闲率和其他 emu/编译任务；若负载升高则等待并重新检查，仍使用两侧
  baseline 夹测，不引用历史单点替代。

正式事件组与 NO0344 相同：

```text
cycles:u
instructions:u
de_no_dispatch_per_slot.no_ops_from_frontend:u
cpu/de_no_dispatch_per_slot.no_ops_from_frontend,cmask=0x6/u
de_no_dispatch_per_slot.backend_stalls:u
```

先对 direct emu 做 100-cycle PMU 接线 preflight，五事件必须全部 `100.00%` 调度后才进入正式 A/B/A。

## 3. 功能与稳定性门禁

三轮都必须满足：

```text
exit code          0
Guest cycles       50001
cycleCnt           49996
instrCnt           73580
terminal PC        0x80001312
```

不得出现 mismatch、assertion、abort、fatal/error 或 `input_fullpass_blocked`。两次 NO0300 的 host cycles spread
必须 `<=1%`，五项 PMU 必须均为 `100.00%` 调度；任一门禁失败时不形成 direct/baseline ratio。

## 4. 输出与判定

以两次 NO0300 均值计算 direct 的：

1. host time、cycles、instructions 的绝对与相对变化；
2. host IPC，以及 frontend empty、cmask6、backend stalls 的绝对和 per-cycle 变化；
3. instructions 降幅对 cycles 降幅的解释程度；
4. 相对 NO0344 的 GSim 均值重新计算 GrhSIM/GSim cycles、instructions gap，回答本次优化恢复了多少；
5. 若收益显著，保留默认关闭开关并继续用 profile 定位剩余 extra instructions；若收益不显著或回退，则结合 PMU
   density 和 generated code 检查 direct consumer activation 是否把扫描成本转移到更差的随机访问。

## 5. 预定产物

```text
build/logs/xs_perf/no0362/direct_event_preflight_emu.log
build/logs/xs_perf/no0362/direct_event_preflight_perf.csv
build/logs/xs_perf/no0362/fixed_baseline1_emu.log
build/logs/xs_perf/no0362/fixed_baseline1_perf.csv
build/logs/xs_perf/no0362/fixed_direct_emu.log
build/logs/xs_perf/no0362/fixed_direct_perf.csv
build/logs/xs_perf/no0362/fixed_baseline2_emu.log
build/logs/xs_perf/no0362/fixed_baseline2_perf.csv
```
