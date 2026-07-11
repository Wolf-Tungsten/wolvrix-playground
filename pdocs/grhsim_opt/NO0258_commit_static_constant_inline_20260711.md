# Commit 静态常量直嵌与 CoreMark 50k 复测

日期：2026-07-11

关联：[NO0256](./NO0256_full_mask_register_commit_specialization_20260710.md)、[NO0257](./NO0257_current_machine_gsim_grhsim_coremark50k_20260710.md)

状态：实现和功能验证完成；当前完整 XiangShan 50k 数据未证明 runtime 收益。

## 目的

commit sink 的输入若是编译期静态常量，旧路径仍可能仅因这条 commit use 为该 value
建立 source supernode、跨 supernode fanout 和 persistent phase-crossing slot，随后在
commit 阶段再读出同一个常量。本轮将这类不携带轮次语义的常量直接写入 commit 生成
表达式，消除无意义的数据传播和存储。

这里的目标是减少 materialization，不改变 write enable、edge guard、changed check、
state update 或 reader activation 的语义。

## 语义边界

本记录定义的“立即静态 commit 常量”同时满足：

1. value 的直接 defining op 是 `kConstant`，且具有 `constValue`；
2. value 被 commit sink 直接使用；
3. 该 operand 不是该 sink 的 event operand。

适用的 sink 包括 `kRegisterWritePort`、`kLatchWritePort`、
`kMemoryWritePort` 和 `kMemoryFillPort`。覆盖 condition、data、mask、address
及 fill data 等普通 write operand。

event operand 是刻意保留的例外。即使它的值是常量，也仍保留 source ownership、
commit dependency 和 event fanout；event 的作用不仅是逻辑数值，还定义本轮边沿/触发
语义，不能因其数值静态而把这条依赖删除。本轮不做递归常量折叠，也不把由其他表达式
计算出的常量结果视为立即静态常量。

## 实现

### Commit emitter

`grhsim_cpp.cpp` 增加 `staticConstantValueExpr()`，并由下列 commit 专用 helper
优先取字面量：

```text
resolvedCommitValueExpr()
truthyCommitLogicValueExpr()
commitWordsExprForValue()
```

write-port 生成统一经这些 helper 读取普通 operand。静态常量因此直接生成例如
`UINT64_C(15)`，而非 `grhsim_value_*_slot`。commit-only 的非 event 常量不再因
该 use 请求 `kPersistentCommitOperand` 或 `kPersistentPhaseCrossing`；动态值、
非直接常量和 event 值仍走原有的 materialization/调度语义。

### Activity schedule

`activity_schedule.cpp` 显式识别各类 sink 的 event operand 起点：

```text
register/latch write: operand 3
memory write:         operand 4
memory fill:          operand 2
```

commit root 构建把非 event 的立即静态常量记录为 immediate input，但该 commit use
不再为其建立 source-owner compute supernode。最终 DAG/value-fanout 扫描也跳过这类
`kConstant -> commit` 边；event constant 不跳过。这样 schedule 的
`compute_commit_value_pairs`、`constant_activation_edges` 和 persistent storage
都只反映真实的跨边界数据。

调度规则已同步写入 `wolvrix/docs/emit/grhsim-scheduling.md`。

## 单测与生成代码检查

通过的 CTest target：

```text
transform-activity-schedule
emit-grhsim-cpp
emit-grhsim-cpp-memory-fill
```

其中 activity-schedule 回归覆盖两种关键情形：

| case | 预期 |
| --- | --- |
| 普通 static constant -> commit | 无 source compute supernode、无 value fanout、`compute_commit_value_pairs` 不计入该边 |
| static constant event operand | 保留 source supernode 和 commit fanout |

emitter fixture 使用 partial mask `8'h0F`，断言 commit batch 中出现
`UINT64_C(15)`，不存在旧的 constant slot alias，state-init 也不再为该字面量建
持久存储。harness 同时验证 partial-mask 写入结果仍为 `14`，防止把 mask 语义误改成
全掩码写入。

## XiangShan Fresh Build

最终模型使用独立输出目录，避免与旧模型共享 object 或 generated C++：

```text
build/xs/grhsim_commit_const_inline_clean/grhsim_emit
build/xs/grhsim_commit_const_inline_clean/grhsim-compile/emu
```

流程读取已有的 pre-reg-to-mem JSON 作为上游输入，但重新执行 `reg-to-mem`、
activity schedule、C++ emit 和 emu link。最终日志中有：

```text
[EXIT] xs_wolf_grhsim_emit 0
+ LD .../grhsim-compile/emu
```

新 emu 的 `.text` 为 `104937107` bytes；保存的旧 emu 为 `110913903` bytes，
代码段减少 `5976796` bytes，即 `5.39%`。该尺寸变化只作为当前工作区的生成物观察，
不单独证明 runtime 收益。

## CoreMark 50k

所有 run 固定在 CPU 0，关闭 waveform、runtime profile、commit trace 和 progress，
执行：

```text
taskset -c 0 ./emu \
  -i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin \
  --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so \
  -b 0 -e 0 -C 50000
```

按 `old -> new -> old -> new` 顺序运行。每次均无 difftest mismatch，且最终进度完全
一致：`Guest cycle spent = 50001`、`instrCnt = 73580`、`cycleCnt = 49996`。

| binary | host time | wall time |
| --- | ---: | ---: |
| old run 1 | `308573ms` | `308.58s` |
| new run 1 | `273163ms` | `273.17s` |
| old run 2 | `269941ms` | `269.95s` |
| new run 2 | `273982ms` | `273.99s` |

new 的两次差异只有 `0.30%`，均值为 `273572.5ms`（`182.77 cycles/s`）。old run 1
明显慢于后续稳定窗口，不能把两个 old 样本直接平均后宣称收益；该平均会错误得出
`5.42%` 的加速。

以相邻稳定窗口的 old run 2 为基线：

```text
new / old = 273572.5 / 269941 = 1.01345x
```

即 new 平均慢 `1.345%`。本轮的 runtime gate 结论是：功能正确，但没有可归因、可复现
的 XiangShan CoreMark 50k 加速。

运行日志：

```text
build/logs/xs/xs_wolf_grhsim_commit_const_inline_old_50k_20260710.log
build/logs/xs/xs_wolf_grhsim_commit_const_inline_new_50k_20260710.log
build/logs/xs/xs_wolf_grhsim_commit_const_inline_old_r2_50k_20260711.log
build/logs/xs/xs_wolf_grhsim_commit_const_inline_new_r2_50k_20260711.log
```

## 归因限制与后续

这不是常量直嵌的严格隔离 A/B：同一工作区还包含另一路
`activity_schedule` coarsening 改动。旧模型的结构为 `72368` supernodes、
`703270` DAG edges、`2446334` boundary activation edges；新模型为 `48947`、
`523587`、`2134975`。两者结构已经显著不同，不能把本记录的完整模型 runtime
差异归因给静态常量直嵌本身。

若需得到该优化的独立性能结论，应在临时 worktree 使用同一 FIR 和同一 build
参数，分别构建：基线、仅常量直嵌、仅 coarsening、两者组合，并按交错顺序重复 50k。
在此之前，本优化保留为语义正确的 materialization/edge 清理，不作为 runtime
提速依据。
