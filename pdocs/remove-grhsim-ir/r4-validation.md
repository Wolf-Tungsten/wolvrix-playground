# R4：虚拟分区与 sink 调度验收

日期：2026-10-24。本文记录 R4.1–R4.4 当时的执行与契约检查；该阶段未执行新 C++ emitter。后续 R5/R6 已有实现和局部执行证据，但完整兼容、整机和性能门禁尚未完成，当前状态见 [实施进度](PROGRESS.md)。

## 交付与职责

全部变换使用普通 PassManager 和一个展开后的 GRH top Graph。`grh-to-grhsim` 与无分区优化保持原职责，不提前创建分区。新增文件路径均相对 `wolvrix/`：

| 步骤 | 实现 | 产出 |
| --- | --- | --- |
| R4.1 | `lib/transform/grhsim/split-event-and-output.cpp` | `event-output-split`：General/Event/Output 属性、实际锥移动/复制、端口重接、时隙历史 |
| R4.2 | `lib/transform/grhsim/split-nonsink-and-sink.cpp` | `nonsink-sink-split`：General 三区域、small/large 状态策略、单 writer 私有纯锥 |
| R4.3 | `lib/transform/grhsim/partition-nonsink.cpp` | `nonsink-partitioned`：活动度 node/超节点、完整文本 owner、可选一轮 boundary clone |
| R4.4 | `lib/transform/grhsim/partition-sink.cpp` | `sink-partitioned`：clock/gate/priority 分组；首次在 session 发布 SinkSchedule |

公开 pass 头文件位于 `include/transform/grhsim/`，接口、选项及默认值见 [正式变换规范](../../wolvrix/docs/transform/grhsim-transforms.md)。`ops.hpp/ops.cpp` 增加方言自己的 `grhsim.history-write` 和阶段/跨区/拓扑校验；基础 GRH 写口与普通 simplify 没有增加仿真模式。

归属的唯一事实来源是 `grhsim.partition` string-vector 属性。节点/超节点 key 初始由 anchor symbol 生成，之后作为属性文本保留；rename、freeze、load 不通过裸 ID 或重新解析 symbol 计算归属。所有解析后引用按 DesignStamp 失效并重建。各 pass 的需求、成本、成员和依赖表只在调用内使用。

SinkSchedule 的正式契约位于 [sink-schedule.hpp](../../wolvrix/include/transform/grhsim/sink-schedule.hpp)：groups 的 fire/guard、General 的有序采样/写 next runs、大状态的快照提交 runs，以及必要的 nonsink 数据/effect 前驱。它不保存 op 语义、CPU 布局、全部 nonsink 执行图或 chunk。slot 按实例/top/config 隔离，发布在最终图校验后；消费者必须通过 `requireSinkSchedule`。

## 执行对照

[grhsim_partition_fixture.hpp](../../wolvrix/tests/transform/grhsim_partition_fixture.hpp) 使用无分区 converted 图作为参考，与分区后的图逐次执行对照。candidate interpreter 读取实际叶 owner，按数据/effect DAG 执行 General，使用实际 SinkSchedule 的 writer 顺序及依赖，分别处理 small next、large 参数快照/提交、publish、Output 和 output-end 历史。

每个场景在同一对象上初始化三次；输入序列含无变化 eval、禁用写入、越界地址和多 round。比较输出、原声明状态投影、投影状态变化轨迹与有序 effects。只折叠连续无变化的投影 round，effects 不折叠。调用结果的 General/Event/Output 采样边界及最终 Event pulse 在 interpreter 中单独保持，Output 不重新检测边沿。

| 检查项 | 用例/断言 |
| --- | --- |
| 首次提取 | 动态地址 `readArray` 原锥同时供 Event、General、Output 使用，形成三份 read/address 计算但共用原状态；检测器数量不增加 |
| 时隙 | free monitor 的条件/参数历史，事件 strobe 的 eval 内粘滞 fire，收敛后的参数读取及统一 output-end 提交 |
| 状态分类 | 小数组仍 small、512-bit 大标量为 large；按总逻辑字节数和阈值选择，改变阈值要求前一 checkpoint |
| 活动度 | node/超节点工作量限制、输入/Event pulse 边界成本；交换两个事件输入的高活动权重会改变相邻 node 的最优合并 |
| clone | 共享 not 复制到不同叶 owner，来源保留；禁用 clone 生效，后续 simplify 不跨叶合回 |
| 调度顺序 | 多时钟、相同 clock 组重复 run、同状态多个 writer、mask/whole/indexed/fill 覆盖；按原 writerOrder 展平不重排，显式同优先级按声明顺序，rename/freeze 不改变胜出的写入 |
| 采样 | large 参数在 General 采样；二维数组的整体 fill、单维部分写、二维掩码写、动态/越界读及 latch 多 round 对照 |
| effects | DPI/random 的单原调用与 held sample；task/random 混合顺序；普通 producer 后追加仍不改变独立调用顺序；sink 依赖含 effect-order 前驱 |
| pulse | 最后一轮 Event pulse 作为输出时保留其值，不因 Output 再求值而丢失 |
| 完整类型 | 四态 X 值和 Logic/Real/String history 通过 verifier/JSON/restart；这些组合只作 IR 验证，不使用 TwoState interpreter 冒充执行验收 |

四个 pass 都支持同配置重跑；测试检查 JSON 内容和 revision 保持不变，sink pass 重新发布完整调度。更改 state/activity/sink 配置分别从对应的前一完成 checkpoint 重启。分区前与 R4.1–R4.3 后 session 都没有新计划产物。

## 负例与生命周期

由 [虚拟分区测试](../../wolvrix/tests/transform/test_grhsim_virtual_partitions.cpp)和 [sink 调度测试](../../wolvrix/tests/transform/test_grhsim_sink_schedule.cpp)检查：

- 越序调用、非法/缺失 owner、父容器直接持有 op、普通 Output→General 边以及分区参数混入 chunk 预算被拒绝。
- op DAG 合法但叶分区/超节点收缩成环的 owner 被拒绝，拓扑校验包含 effect-order arcs。
- 负活动度（含 Event 输入）或 uint64 成本溢出在改图前拒绝，不能留下部分 owner。
- 缺 writer/reordered run 的 forged schedule 被拒绝；sink 组混合优先级或 local/hoisted guard 被拒绝，孤立 sink 组不能被消费。
- 缺失 session、错 session、错 slot 类型、clone/load 新实例、改图、freeze 重编号、rename、symbol 转交均不能使用旧 resolved schedule。
- 部分归属或改变配置导致 sink pass 失败后，旧 complete slot 已删除；恢复图或清空 session 后可以重建。重复相同配置不修改图。
- 隔离 dryrun 使用 clone 和独立 session；即使复制旧 slot，它也不能替代新实例的调度。source 图、revision 与 session 保持可用。
- 同一 session 可以保留不同 design 的有效调度，重建一份不会覆盖另一份。

## 命令与证据

全部通过项目 Make target 执行；日志/临时目录在 `ptmp/`，测试产物在 CMake 配置的 `wolvrix/build/artifacts/`：

| 命令 | 结果 | 日志 |
| --- | --- | --- |
| `WOLF_ENV_SOURCED=1 make test_grhsim_virtual_partitions test_grhsim_transforms` | R4/变换 3/3，R1–R3 4/4 通过 | [r4-focused-final.log](../../ptmp/remove-grhsim-ir/r4-focused-final.log) |
| `WOLF_ENV_SOURCED=1 make test_grhsim_virtual_partitions` | checkpoint/观测导出、幂等、等优先级及成本拒绝，3/3 通过 | [r4-priority-final.log](../../ptmp/remove-grhsim-ir/r4-priority-final.log) |
| `WOLF_ENV_SOURCED=1 make test_wolvrix` | 最终公共回归 73/73 通过，含最后增加的 writer rename/freeze 断言 | [r4-complete-public.log](../../ptmp/remove-grhsim-ir/r4-complete-public.log) |

最终公共回归覆盖全部本阶段代码和测试，之后只更新文档。`test_grhsim_virtual_partitions` 与 `test_grhsim_sink_schedule` 两个 Make 入口都运行两个 R4 套件和变换套件。较早的 [r4-public-final.log](../../ptmp/remove-grhsim-ir/r4-public-final.log) 和 [r4-artifacts-final.log](../../ptmp/remove-grhsim-ir/r4-artifacts-final.log)保留为过程证据，不替代最终结果。

可直接检查各阶段的统一 GRH：

- [converted 参考](../../wolvrix/build/artifacts/grhsim-partitions/virtual/event-output-reference.json)
- [Event/Output 提取](../../wolvrix/build/artifacts/grhsim-partitions/virtual/event-output-candidate.json)
- [General 三区域](../../wolvrix/build/artifacts/grhsim-partitions/virtual/nonsink-sink-candidate.json)
- [nonsink 活动度分区](../../wolvrix/build/artifacts/grhsim-partitions/virtual/nonsink-partitioned.json)
- [sink 分区](../../wolvrix/build/artifacts/grhsim-partitions/virtual/sink-schedule-candidate.json)与 [load 后重建](../../wolvrix/build/artifacts/grhsim-partitions/virtual/sink-restart-candidate.json)

每次执行对照还导出 reference/candidate checkpoint 和包含输入、输出、状态、round、effects 的逐次日志，例如 [动态读口与时隙](../../wolvrix/build/artifacts/grhsim-partitions/virtual/event-output.log)、[交错 writer](../../wolvrix/build/artifacts/grhsim-partitions/sink/ordered-snapshots.log)、[二维数组/latch](../../wolvrix/build/artifacts/grhsim-partitions/sink/partial-array-latch.log)、[混合 effects](../../wolvrix/build/artifacts/grhsim-partitions/sink/mixed-effects.log)、[等优先级 rename/freeze](../../wolvrix/build/artifacts/grhsim-partitions/sink/equal-priority-freeze.log)。这些是测试运行产物，不提交生成文件。

## 与旧 C++ 的证据边界

R4 实现按 effect/sample identity 采用 `grhsim.effectPolicy=single-original-call`；原调用在 General 执行，跨区消费者使用 held sample。冻结 dpi_bit_abi 旧模型在 General/Output 各调用一次，两次调用的原日志完整保留。2026-10-25 用户已明确选择 [单个原调用语义](20261025-single-call-decision.md)；[基线记录](baseline-and-capabilities.md#r4r5-的旧-dpi-行为差异)说明精确验收范围。

R4 阶段没有生成或执行新 C++ 模型，未宣称旧→新调用次数等价。后续 R5 实际 C++ 比较已暴露 DPI 次数、顺序和触发差异；精确的 Output 重复调用去除及原图独立调用顺序已有[用户决定](20261025-single-call-decision.md)，触发错误已修复，其他差异仍须逐项验证。R5 继续补齐完整 ABI、混合 effects、初始化、FST/profile、全部函数 chunk/chunkFrame 与运行时激活，R6 完成整机和性能对照。chunk 参数与本阶段的任何虚拟归属/调度配置无关。
