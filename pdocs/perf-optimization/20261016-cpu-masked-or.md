# CPU maskedOr：实现与首轮验证

本文记录首版的接口和测量。后续已扩展位视图、离散来源、超过 64 位和嵌套结构，
恢复区域为 4,217 个；当前结果见 [匹配扩展与验证](20261016-cpu-masked-or-matching.md)。

2026-10-16，已实现 `cpu.compute.maskedOr(mask, array)` 和
`cpu.st.recover-masked-or`。支持 N=2..64、W=1..64 的 unsigned/two-state 值，
精确定义为 `OR_i(mask[i] ? array[i] : 0)`。零命中为零，多命中按位 OR。
首版通过 `XS_WOLF_GRHSIM_IR_MASKED_OR=1` 显式开启，默认 0。

接口和匹配契约见 [CPU dialect](../../wolvrix/docs/grhsim_ir/dialects/cpu.md) 和
[恢复 pass](../../wolvrix/docs/grhsim_ir/passes/recover-masked-or.md)，设计取舍见
[mask/array 设计说明](../../wolvrix/docs/grhsim_ir/cpu-boolean-reduction-proposal.md)。

## 实现

恢复 pass 放在 B6 phase simplify 后、B8 semantic seal 前。逐 phase 识别完整数组
覆盖的 bit-AND、zero-else mux、replicate-mask AND 及其 OR 树，保留共享/声明观察点。
删除区域中无用的纯 producer 和读，随后重建 CPU mapping。

C++ 遍历 mask 的置位 bit，直接索引已有数组；布尔结果遇 true 可退出，多位结果合并
全部选中元素。General 的状态版本和 Output 的状态版本分别保持；已有 boundary/frame
快照不绕过。源存储的行 shape 不匹配时走 packed fallback。C1/C2 按 2N-1 计费，
避免融合后绕过 node/supernode 容量规则。

## 实际香山覆盖

输入：`build/xs/grhsim-ir-aggr-global-enhanced/xiangshan_grhsim_ir.json`，5,035,938 ops。
使用现有 checkpoint 恢复、封板、C1–C8 映射并生成 1,269 个 TU，输出在
`ptmp/masked-or-xs/`。本轮没有从 SV 重建，也没有运行完整香山程序。

| 指标 | 结果 |
| --- | ---: |
| 恢复区域 | 220 |
| Event / General / Output | 20 / 200 / 0 |
| 每个区域的 N / W | 48 / 1 |
| 总规约项 | 10,560 |
| 移除旧 op | 16,648 |
| 其中移除的 element read | 2,688 |
| 直接引用原状态数组的生成区域 | 220 |

后续的 [Chisel/FIRRTL 全局覆盖审计](20261016-xiangshan-mux1h-coverage.md) 确认：
这 220 个区域全部来自 TLBStorage.scala 的 perm/g_perm 两处 Mux1H。
当前配置有 72 处源码调用展开出 16～64 项选择器，首版仅覆盖其中两处。
同 TLB 的 2-bit 字段还因 rep=1 wrapper 和 singleton shape 漏匹配；
因此下文 C++ 长链数量的下降不能代表 Mux1H 全局覆盖率。

共享 element read 会保留，规约项数不能当作实际节省的读数。恢复后的 220 个区域
分布在 TU19（20）、TU38（91）、TU39（89）、TU67（20）。四个 TU 均用生成模型的
Makefile 完成 `-std=c++20 -O3 -fno-strict-aliasing` 编译。

原先 TU17 的 ITLB `perm.r` 长链现位于 TU19 约第 4000 行，生成代码直接引用
`smallSinkStore` 的 `hitVecReg` 和 `entries__DOT__perm__DOT__r`，无临时数组：

```cpp
std::uint64_t remaining = hitVecReg & UINT64_C(0xffffffffffff);
bool result = false;
while (remaining != 0) {
    const auto i = std::countr_zero(remaining);
    if (perm_r[i]) { result = true; break; }
    remaining &= remaining - 1;
}
```

沿用[原普查](20261016-xiangshan-boolean-chain-census.md)的口径重新扫描所有生成 TU：

| >=16 个二元运算的串行布尔链 | 原模型 | 恢复后 |
| --- | ---: | ---: |
| Event | 21 | 1 |
| General | 2,083 | 1,887 |
| Output | 4 | 4 |
| 总计 | 2,108 | 1,892 |

剩余 Event 最长 18，General 最长仍为 128。IR 区域和串行 C++ 链的计数规则不同，
且重映射会改变链边界；220 个区域不要求对应 220 条静态链的净减少。

## 微基准

AMD Ryzen 9 7950X3D，Clang 22.1.2，`-std=c++20 -O3 -DNDEBUG`。
`make bench_grhsim_masked_or` 比较完整展开、可由编译器重结合的 AND/OR 表达式与当前
稀疏扫描。1024 组运行时生成输入循环使用，每次计时 1,048,576 次调用，取 5 次中位数；
使用 compiler memory barrier 防止跨轮缓存调用结果，并在计时前逐组验证两种结果相同。
seed 为 20261016。数据为热数组；没有测完整设计的 cache/调度行为。

48 项、W=1：

| mask 命中数 | 数据 | 展开表达式 ns | 稀疏扫描 ns | 展开/稀疏 |
| --- | --- | ---: | ---: | ---: |
| 0 | 随机 0/1 | 7.929 | 0.958 | 8.28x |
| 1 | 随机 0/1 | 7.774 | 1.391 | 5.59x |
| 4 | 随机 0/1 | 7.700 | 1.771 | 4.35x |
| 48 | 随机 0/1 | 7.627 | 1.820 | 4.19x |
| 48 | 全零 | 7.557 | 19.592 | 0.39x |

W=8、N=48 的全选扫描约为原速度的 0.66 倍；W=64、N=64 全选约为 0.47 倍。
这些结果表明稀疏选择的局部收益，同时给出密集且难以提前结束时的回退风险。不能据此
宣布香山整机提速。多个 permission 共享一次 mask 遍历、密集 mask 策略及 packed
permission 布局留作后续按动态热点评估。

## 功能验证与复现

以下 Makefile targets 通过：

- `test_grhsim_masked_or`：匹配/拒绝、观察/共享前缀、幂等、JSON 往返、verifier，
  以及 8 个生成 C++ 程序，每个运行 1024 步并启用 UBSan；包含小规模穷举、multi-hit、
  48/64 边界、Event、General 旧值采样、Output、跨 helper/TU、输入/状态 shape 重解释，
  以及超过 64 位的 packed fallback。
- `test_grhsim_ir`、`test_grhsim_cpu_phase_emit`、`test_grhsim_cpu_phases`、
  `test_grhsim_cpu_stores`、`test_grhsim_whole_opt`、`test_grhsim_simplify`。
- `reemit_grhsim_ir` 在真实 XS checkpoint 和已恢复的小模型上均通过；组合使用
  recovery/remap 只构建一次 C1–C8。

复现真实模型：

```sh
make reemit_grhsim_ir \
  GRHSIM_REEMIT_MODEL=build/xs/grhsim-ir-aggr-global-enhanced/xiangshan_grhsim_ir.json \
  GRHSIM_REEMIT_FLOW=ptmp/masked-or-xs GRHSIM_REEMIT_MASKED_OR=1
```

关键产物：`ptmp/masked-or-xs.log`、`ptmp/masked-or-xs/masked-or.tsv`、
`ptmp/masked-or-xs-compile.log`、`ptmp/masked-or-xs/bool-chains.json`、
`ptmp/masked-or-bench/results.tsv`、`ptmp/masked-or-regressions.log`、
`ptmp/masked-or-view-regressions.log`、`ptmp/masked-or-final.log`、
`ptmp/masked-or-reemit-smoke.log`。

整机 A/B 应让 baseline 也经过相同 reemit/remap 流程，再比较相同程序、seed、周期和
编译/trace 选项。融合可能改变 General 边界过滤及激活次数；需测总时间和 phase 时间后，
再决定默认启用或进一步选择策略。
