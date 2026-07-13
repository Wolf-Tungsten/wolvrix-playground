# NO0338 PIE/ASLR performance runbook correction

日期：2026-07-12

## 1. 触发证据

执行 [NO0334](./NO0334_no0300_sched_object_order_plan_20260712.md) 的 numeric baseline1 时，同一个未修改
NO0300 emu 得到：

```text
Host time   = 77,079 ms
host cycles = 282,125,014,789
instructions = 172,879,701,008
```

instructions 与历史 NO0300 基本 byte-for-byte 一致，但 cycles 相对 [NO0317](./NO0317_no0286_no0300_frontend_latency_itlb_gate_20260712.md)
的同一 binary 下降 `8.466%`，相对 [NO0328](./NO0328_no0286_no0300_l2_instruction_pmu_gate_20260712.md)
下降 `9.104%`。cmask6/cycle 相对 NO0317 也下降 `5.504%`。目标 CPU 空闲、四事件均为 `100%`，机器负载
不足以解释同 binary 的该幅度变化。

## 2. 根因风险

`readelf` 确认 emu 为 PIE：

```text
Type: DYN (Position-Independent Executable file)
```

系统 `/proc/sys/kernel/randomize_va_space = 2`，此前所有 fixed-CPU perf 命令都没有禁用 ASLR。NO0333 已证明
GrhSIM 超大 batch 对 native address bits 高度敏感；随机 PIE load base 会继续改变 page 以上的 branch predictor、
op-cache 或其他 frontend address mapping。old/new/old 中两次 old 接近，只能证明那两次 old 恰好稳定，不能
证明 version-correlated load address 已被隔离。

本机 `setarch "$(uname -m)" -R true` 成功，因此没有理由继续保留该变量。

## 3. 修正口径

后续所有 GrhSIM/GSim 性能运行在既有 CPU/NUMA prefix 外再增加：

```text
setarch "$(uname -m)" -R
```

即由同一 personality 关闭 ASLR后再启动 `numactl/taskset/perf/emu`。进入正式门禁前先连续启动两次短仿真，
从 `/proc/<pid>/maps` 验证 emu executable mappings 完全一致。

NO0334 已完成的 `numeric1` 仅作为发现 ASLR 风险的无效探针，不进入 bit-reversal 统计；bit-reversal 正式运行
尚未开始。修正后从 numeric / bit-reversal / numeric 全部重跑，不能混用 numeric1。

## 4. 历史结论影响

1. generated code、动态工作、功能和事件接线类结论不受影响。
2. 同一 A/B/A 内 baseline spread 很小的历史性能数据仍有参考价值，但具体幅度和 code-layout 因果解释需要
   fixed-ASLR 复核。
3. NO0333 的 4 KiB 结果在 fixed-ASLR 复测前标记为 provisional；不能继续据此设计默认 layout。
4. 当前最先完成 NO0334 的 fixed-ASLR 门禁；它使用同一 NO0300 object set，能直接量化物理顺序而不混入
   old/new graph 差异。

## 5. 无效探针产物

```text
build/logs/xs_perf/no0334/numeric1_emu.log
build/logs/xs_perf/no0334/numeric1_perf.csv
```
