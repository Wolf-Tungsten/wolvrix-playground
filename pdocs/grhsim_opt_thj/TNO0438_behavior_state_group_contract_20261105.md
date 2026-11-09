# TNO0438：数组语义到 kBehaviorStateGroup 的局部实现与契约验证（2026-11-05）

## 范围与基线

承接 [TNO0437](./TNO0437_behavior_commit_rat_s3_measurement_20261105.md)。按用户批准的范围，
本轮只完成局部闭环，不重启完整香山性能、不补 A/A、不扩展其他 intrinsic。
上一轮完整 S3 的普通模型平均回退 +5.267686% 与未完成 A/A 的事实保持不变。

本轮增加实验性 `kBehaviorStateGroup`，目的是降低数组更新的真实运行开销。
默认硬件路径和普通行为模型路径不改变。新的测试不依赖上一轮 raw fixture 的 −98.65% 数字。

## 上轮收尾检查

`mill -i xiangshan.test.compile` 通过；新增的两项生成期拒绝检查已执行：

- excluded commit source 在 commit-rat 模式下拒绝生成。
- `--reset-gen` 分级复位在 commit-rat 模式下拒绝生成。

修正了 guard fixture 传入不存在的 `enabled` 命名参数的问题。当前 Difftest 的 `enabled`
是内部常量，不能把它称为另一个已测试的可关闭参数；测试实际覆盖公开的 `excluded` 路径。
产物在 `wolvrix/build/artifacts/behavior-state-group/guards/`。这些检查不改变 v10 有效配置的 RTL。

## Chisel 数组接口与绑定

作者继续只写 `array/read/snapshot/update`。内部记录数组名、长度、位宽、字面量初始化、
动态读地址以及按调用顺序排列的 `valid/index/data`；不要求逐行声明寄存器或优先选择网络。
同拍所有 RHS 使用旧状态，后调用的有效更新覆盖同地址先前更新，reset 优先。

`SimulationModels.withMode(..., lowering="grouped")` 保留数组语义并生成版本化模块。
Chisel 内部的 transport 是带完整 inline SV 的 BlackBox，SV 可独立生成普通 GRH，
不是不透明状态调用。模型模块与 manifest 共用同一份语义描述。

manifest v2 的 `binding` 明确列出模块、端口方向/位宽、数组、初始化、update/read 序号和
完整 fallback body 的 SHA256。模型 ID/version、capability、检查字段、时钟/复位和 commit
boundary 继续保留。旧的 `Data.toString` 字段仅用于诊断，绑定不读取这些字符串。

根脚本新增 `--behavior-state-lowering ordinary|grouped`，默认 ordinary。
grouped 必须从 RTL fresh 导入，在 hierarchy flatten 之前验证实际模块端口及源文件中的 SV body，
再替换该模块 body。manifest 本身也要能重建同一份 canonical SV，不能修改 update 顺序后仍用旧 hash。
缺失/不完整 binding、版本/位宽/源码不符均报错；禁止用 resume bypass 绕过验证。
普通模式对同一 SV 使用现有 frontend 和优化流程。

v1 限定同步单时钟上升沿、observer-only、1–64 位 UInt、完整元素写入、字面量初始化和
2 的幂行数，总行数最多 65,536。这里不是通用行为语言或多时钟模型。

## GRH 与运行时实现

一个 `kBehaviorStateGroup` 是一个 commit sink。operands 为：

```text
[group_enable, sync_reset, valid0, index0, data0, ..., validN, indexN, dataN, clock]
```

一个私有 `kMemory` 提供 backing storage；组拥有全部写入，不能与普通 writer 或第二个组共写。
数组在 backing store 中按顺序排列，最大元素位宽作为存储 word 宽度。读取继续使用显式
`kMemoryReadPort` 和必要 slice，因此调度器能看见输入、旧状态、时钟与读消费者。
不是再为每个字段增加同义的 Register 节点。

GrhSIM 在一个 commit body 中：

1. 按顺序检查有效更新，将最终数据暂存到 pending；位图和 touched 列表去重地址。
2. 所有 RHS 求值后才修改 backing state，保持旧状态语义。
3. 只比较 touched 行的最终值，只为净变化激活现有 reader 集合。

pending/touched 不做整组旧状态复制；当前仍有逐条 valid 检查，复杂度不因只声明一个节点就变成 O(1)。
已有 event guard 保证同一边沿只提交一次。reset 触碰所有行，普通更新仅触碰有效目标行。
SystemVerilog emitter 可把分组节点展开回同步 reset 和有序非阻塞赋值。

本地 observer ownership 检查拒绝组观察结果反馈到普通状态写入、DPI/XMR write；允许组间依赖
和顶层检查输出。完整 S3 的 debug delay/checker domain 尚未接入这一所有权契约。

## 验证结果

所有产物在 `wolvrix/build/artifacts/behavior-state-group/`：

| 验证 | 结果与产物 |
|---|---|
| 两个 32 行数组，64/9 位 | `simple-final/`，H/O/G 各 3 seeds × 10,000 周期，通过独立数组参考 |
| 520 路 RAT | `rat-final/`，H/O/G 各 3 seeds × 10,000 周期，通过 int/FP/vector/v0 初始化、索引及映射参考 |
| 复位、无写、多写、重复地址、写回原值 | 两种 fixture 通过 |
| 旧状态读取 | 小 fixture 同拍跨数组 RHS；双实例同边沿交换旧值，均通过 |
| 重复 eval/同高电平输入变化 | 无重复 commit，所有状态参考一致 |
| SV 回退重新导入 | `contracts-v2/roundtrip/`，10,000 周期通过 |
| 相同 RTL 模块的两个实例 | `contracts-v2/twins/`，1,000 周期交错边沿 + 100 次同边沿跨组交换，无状态共享 |
| manifest 拒绝检查 | version/missing-binding/port-width/update-order/initializer/source-hash/observer 七项通过 |
| native GRH 拒绝检查 | version/width/ordinary feedback/alias writer 四项通过，核对预期错误原因 |
| resume 绕过拒绝 | `simple-final/resume-rejection/`，缺少 fresh authenticated import 时拒绝 |
| 最终值不变的激活 | `simple-v2/G-diagnostic/net-zero.log`：100 commits、200 updates、100 touched rows、0 净变化、0 reader 重求值 |
| 既有相关测试 | `emit-grhsim-cpp-memory-fill`、`emit-grhsim-guard-activity` 通过；未跑全量回归 |

开发中发现并修复 ownership 遍历持有临时 `Value` 的 users span，可能导致 invalid OperationId/崩溃。
`contracts-v1` 中 native-feedback 曾因此以错误原因拒绝，不能计为该 guard 的有效证据。
`contracts-v2` 对错误内容作断言，使用修复后的工具重新通过。最终 H/O/G 与计时使用修复后的同一份冻结库。

## 文件入口与复现

- 高层 API：`testcase/xiangshan/utility/src/main/scala/utility/BehaviorModels.scala`。
- Typed binding import：`wolvrix/app/pybind/wolvrix/behavior_state.py`。
- IR 契约：`wolvrix/include/core/behavior_state_group.hpp`；activity/DCE/C++/SV emitter 均识别组。
- fixture：`testcase/chisel-intrinsic/BehaviorStateGroupStudy.scala`。
- 构建/参考/绑定/诊断/测量/汇总：`scripts/behavior_state_group_*.py`。

```bash
python3 scripts/behavior_state_group_study.py --fixture rat --output <new-dir>
python3 scripts/behavior_state_group_check.py --fixture rat --output <new-dir>
python3 scripts/behavior_state_group_validate.py --fixture <simple-dir> --output <new-contract-dir>
# 诊断另建目录，不使用其 binary 计时
python3 scripts/behavior_state_group_diagnostics.py --fixture <new-dir> --rat
# 所有构建结束后，在 node030、CPU 区域空闲时：
python3 scripts/behavior_state_group_measure.py --fixture <new-dir> --rat --output <new-timing-dir>
```

本轮性能与下一阶段门槛见 [TNO0439](./TNO0439_behavior_state_group_local_performance_20261105.md)。
