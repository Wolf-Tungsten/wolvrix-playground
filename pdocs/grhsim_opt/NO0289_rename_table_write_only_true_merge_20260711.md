# NO0289 RenameTable write-only true-merge structure gate

日期：2026-07-11

## 1. 背景

[NO0288](./NO0288_rename_table_write_only_array_gap_20260711.md) 将 `compute39` 的热点定位到 RenameTable difftest shadow table：GSim 保留数组及 indexed write，GrhSIM 则把三组表拆成标量寄存器和逐行地址判断。现有 reg-to-mem discovery 依赖 concat/slice read anchor，因此看不到这类只有独立标量读、但写侧具有完整行译码结构的数组。

本阶段补充严格的 write-side discovery，并先以 synthetic 与 SimTop pre-sched 结构 gate 验证，不在本记录中宣称 runtime 收益。

## 2. 实现

`wolvrix/lib/transform/reg_to_mem.cpp` 新增 decoded-write storage discovery：

- 只检查单一 write operation、且 update OR 中至少有 64 个可识别 priority alternatives 的标量 register。
- 每个可识别 alternative 必须译码到同一 logical row；候选按元素宽度、mask、event、地址与冲突集合分组。
- discovery 只负责找候选。row-by-row data、mask、event、common guard、priority conflict 和 reset 仍由原有 consolidated matcher 完整核对，任何不一致均 fail closed。
- 支持连续 logical rows 映射到带前缀空洞的 storage。`vecRat[1..31]` 因而映射到 depth 32、row offset 1，而不是错误压缩到 depth 31。
- 生成 write port 时统一加入 `offset <= addr < offset + rows` domain guard。
- 地址宽度足够但常量值超出候选 storage depth 的 equality 不再被误判为 row selector。例如 synthetic 中 `ReduceAnd(commitSize)` 对应的 `commitSize == 511` 会保留为 common guard。
- packed reset 覆盖带 leading offset 的 storage 时，显式给空缺低行补零；这使 `vecRat` 的 row 0 保持原语义。

## 3. Synthetic gate

`wolvrix/tests/transform/test_reg_to_mem_pass.cpp` 新增 write-only decoded storage 用例：

- 正例使用 65 个 priority writers、4 个 logical rows `1..4`，没有 concat/slice read anchor。
- 正例要求生成一个 depth-5 memory、4 个 read ports、65 个 write ports和一个 fill；每个 write 都具有上下界 guard，packed reset 的 row 0 明确补零。
- writer 0 带超出 storage domain 的 9-bit equality，验证它不会被误识别为 row selector。
- 63-writer 对照低于保守阈值，必须继续保留 scalar registers。

验收命令：

```bash
source env.sh
cmake --build wolvrix/build -j8 --target transform-reg-to-mem
ctest --test-dir wolvrix/build -R '^transform-reg-to-mem$' --output-on-failure
```

结果：通过，CTest 用时 `0.15 s`。

## 4. SimTop pre-sched 结构 gate

从既有 pre-reg-to-mem JSON 恢复，执行新的 reg-to-mem 后在 pre-sched 停止：

```text
single_write_regs=286013
wide_update_regs=96
matched_rows=95
families=3
max_family_rows=32
```

三组新增 true-merge 结果如下：

| storage | scalar rows | depth / offset | write families | reset | 结果 |
| --- | ---: | ---: | ---: | --- | --- |
| `fpRat.difftest_table` | 32 | `32 / 0` | 511 | packed | rewritten |
| `intRat.difftest_table` | 32 | `32 / 0` | 511 | per-row | rewritten |
| `vecRat.difftest_table` | 31 | `32 / 1` | 520 | packed | rewritten |

`true_groups` 从此前的 `832` 增至 `835`，其余 `3483` 个候选仍跳过。该结果证明三组目标 scalar tables 已恢复为 indexed memory 结构；write-family 数量来自当前 GRH 的实际 consolidated matcher，不把它与 NO0288 中 GSim 源码静态计数强行视为一一相等。

## 5. 构建期开销

本次 profile 中 reg-to-mem 总耗时为 `151.636 s`，此前同一 SimTop 检查点约为 `54 s`。新增主要成本为：

| 阶段 | 耗时 |
| --- | ---: |
| discovery anchors（包含 write-side discovery） | `52.257 s` |
| regular/consolidated write match | `55.609 s` |
| rewrite true groups | `38.254 s` |

这是生成 emu 前的一次性编译期开销，不是仿真 runtime 成本，但后续需要单独优化。目前先生成 fresh emu，以功能正确性和 SimTop runtime 是否获益决定该方向是否值得保留。

## 6. 产物

- 结构 gate 日志：`build/logs/xs/xs_wolf_grhsim_build_no0289_write_only_all_three_fixed_stop_after_20260711.log`
- 结构 gate build：`build/xs_grhsim_no0289_write_only_all_three_fixed_stop_after_20260711/grhsim`
- 输入检查点：`build/xs_grhsim_event_order_src_20260710/grhsim/wolvrix_xs_pre_reg_to_mem.json`

## 7. 下一步

1. 从同一 pre-reg-to-mem JSON 完成 fresh emit/compile。
2. 运行 SimTop 10k/50k difftest 功能回归。
3. 对比 fresh generated C++，确认目标逐行判断被 indexed memory access 替换。
4. 检查机器负载后，以固定 CPU 做 old/new/old 50k runtime gate；若宿主负载不稳，必须同步重跑 baseline。
