# TNO0436：DiffTest 语义级 commit/RAT adapter（2026-11-05）

## 目标与范围

用 `array/read/snapshot/update` 建模 debug 状态，通过实际 XiangShan 写回、ROB 提交与
DiffTest RAT 更新产生 canonical xrf/frf/vrf/commit_data。保持完整 S3 的 NEMU 检查、CSR、异常、
访存和 UART 事件；默认仍是 hardware，实验开关为 `--wolvrix-sim-models commit-rat`。
第一版只支持单核、完整 DiffTest、64 位 scalar/128 位 vector；缺少必要输入时 elaboration 失败。

## 中间版本失败与纠正

- v4 修正跨模块信号使用命名 wiring，Gateway schema 存放 Chisel 类型而非 Wire。
- v5 成功生成 RTL，但 520 个潜在微操作更新逐个展开造成 6299 条更新与深度超限。
- v6 把输入改成 8 个 `archWritePorts` 后完成 RTL/GRH/C++，NEMU 首条提交失败：
  commit_data=1，而 xrf.t0=0；v8 的映射改写仍同样失败。
- v9 RTL 成功，恢复后审计确认不能继续用于验收：`archWritePorts` 比 ROB DiffTest 边界更晚，
  且多微操作退休不能压缩成 8 个普通 RAB 写口；旁路还有同地址优先级反向问题。

以上产物保留在 `build/xs/behavior_commit_rat_20261105_v{4,5,6,7,8,9}`；失败运行不作为性能样本。

## 当前实现

1. DataPath 传出 integer/FP/vector/v0 物理寄存器的实际写口（含向量异常恢复写回）。
2. RenameTable 使用原 `diffCommits` 的完整微操作序列。通过平衡的 last-writer 选择，每个
   可观察架构索引最多输出一次更新；不替换成更晚的 `archWritePorts`。
3. 物理 shadow 用普通 memory 保存无 reset 的物理值；整数物理 0 恒为零。RAT 用数组，
   integer reset 为 0，FP/vector reset 为 identity；vector 合并索引宽度按实际 300 个 64-bit chunk 算为 9 位。
4. 架构数组是 `physical[RAT]` 的延迟观察快照。把 gather 放到延迟之前：
   `map(delay(P),delay(R)) == delay(map(P,R))`，减少整张物理 RF 的延迟存储。
5. commit data 的地址延迟为 `commitDelay-observationDelay`，先读物理状态再延迟数据，
   保持和原 Preprocess 相同的拍号。输出全部 16 个 vector commit chunk，单核 Gateway 按原规则省略 vec_commit_data。
6. 原 integer/FP/vector/v0 DiffTest 全表读出和 RAT diff table 只在行为模式移除；VL 路径仍保留。
   CSR、异常、访存等其他 Gateway 接口、delay、squash/skip 字段继续沿原路径。

observer-only 是 manifest 声明与 adapter 输出仅接 Gateway 的结构约束；当前没有声称实现
跨任意模型的静态无反馈证明。未新增 GRH OperationKind，generic backend 仍用标准状态调度。

## 验证

- `api-array-v2`：hardware/behavior 均为 591 operation，64 个 register，模型例子只需两个数组与两次 update。
- `array-contract-v1`：10,000 周期独立 C++ scoreboard，复位、重复写、后写覆盖、读取旧值、snapshot 隔离通过。
- `adapter-equivalence-v11`：直接更新端口版本对原 Delayer/Preprocess，3 seeds × 10,000 cycles 通过。
- `adapter-equivalence-v12`：加入与真实接线相同的 last-writer 合并，对独立维护的物理/RAT 状态及原
  Preprocess 比较，3 seeds × 10,000 cycles 通过。每个上升/下降采样点检查 xrf/frf/vrf、RAT、
  有效 commit_data/vec_commit_data；包含多提交、重复目的、别名、skip、无提交、reset 中写回。
- `mill xiangshan.test.compile` 通过。

fixture 原始产物在 `wolvrix/build/artifacts/behavior-model/`。
整机同源码 A/B 正在 `build/xs/behavior_commit_rat_20261105_v10` 构建，未完成 100k 功能门前不作性能结论。

## 专用状态节点

目前没有普通状态更新运行热点的证据，不新增 `kBehaviorStateGroup`。
后续只有专用分组在同语义 fixture 达到稳定约 5% 收益、且整机超过 A/A 噪声并保持完整 NEMU/trace 一致，
才有保留价值。不得把普通 GRH 成功生成当成速度已经足够或已经加速。

## 增量更新：整机结果与停止状态

同源码 v10 的完整 S3 功能及计时结果见 [TNO0437](./TNO0437_behavior_commit_rat_s3_measurement_20261105.md)：两组 100,000 周期 NEMU/trace 完全一致，8 对 walltime 平均回退 5.27%。A/A 只完成一对后按用户要求停止。
新增同步复位、commit capability 的两项拒绝检查尚未单独编译测试，具体冻结源码边界已在该报告注明。当前不增加专用 GRH 节点，也不更改 hardware 默认。
