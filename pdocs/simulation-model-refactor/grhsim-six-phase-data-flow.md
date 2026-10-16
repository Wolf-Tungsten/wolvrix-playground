# GrhSIM CPU 后端六阶段数据流

日期：2026-10-13
范围：当前 GrhSIM CPU 后端生成模型的运行时 `eval()` 流程。

本文记录六个运行时阶段之间如何传递数据，以及这些数据在静态 mapping 和生成 C++ 中对应的结构。这里的“六阶段”是运行时的 `P_input / P_event / P_general / P_large_sink / P_publish / P_output`。CPU 后端编译期的 mapping 目前是 C1–C8，二者不是同一组阶段。第 1–6 节描述 2026-10-13 工作树中的实现，第 7–8 节分别记录架构要求与 aggregate 支持边界；工作树尚有未提交改动，不能把它们当作已发布能力。

早期整体架构背景见 [`grhsim-ir-architecture.md`](grhsim-ir-architecture.md)；其中仍使用旧命名，当前阶段与 store 名称以本文和源码为准。本文聚焦“阶段之间传什么、写到哪里、由谁唤醒谁”。

## 1. 总体执行顺序

一次 `eval()` 固定外部输入，然后反复执行 round，直到 `P_publish` 判定不动点：

```text
eval()
  P_input()
  for round = 1 .. MAX_ROUND:
    P_event()
    P_general()
    P_large_sink()
    if P_publish(): break
  P_output()
```

数据流可以概括为：

```text
外部输入
  ↓
inputStore
  ↓ inputFanout
nonSinkActiveFlag
  ↓
P_general 的 nonSink 超节点
  ├─→ nonSinkBoundaryStore ──computeSupernodeFanout──→ nonSinkActiveFlag / nonSinkActiveFlagNext
  ├─→ smallSinkEnableBoundaryStore + smallSinkPayloadBoundaryStore ──→ smallSink 超节点
  └─→ largeSinkEnableBoundaryStore + largeSinkPayloadBoundaryStore ──→ P_large_sink

smallSink 超节点 → smallSinkStoreNext ──commitStateFanout──→ nonSinkActiveFlagNext

P_event:
  prevEventStore → edgeDet → eventActStore
                               ├─ eventActivation → nonSinkActiveFlag
                               └─ timeslotTriggers → timeslotTriggerFlag

P_large_sink:
  memWritePlan → largeSinkStore → large-state readers → nonSinkActiveFlagNext

P_publish:
  smallSinkStoreNext → smallSinkStore
  nonSinkActiveFlagNext → nonSinkActiveFlag

P_output:
  最终 stores + timeslotTriggerFlag → 输出端口 / 时隙任务
```

`SimOp::phase` 只给有操作的四个相位赋值：`Event`、`General`、`LargeSink`、`Output`；`P_input` 和 `P_publish` 是 emitter 生成的驱动阶段，没有对应的 `SimOp`。定义见 [`model.hpp`](../../wolvrix/include/grhsim/ir/model.hpp)。

## 2. 运行时 store

`cpu.st.layout-named-stores` 把模型对象映射到 12 类具名 store。`CpuNamedStoreKind` 和字段描述见 [`model.hpp`](../../wolvrix/include/grhsim/ir/model.hpp:449)。

| 运行时结构 | 内容 | 主要生产者/消费者 | 语义 |
| --- | --- | --- | --- |
| `smallSinkStore` | 小型状态的当前值，标量或数组均可 | P_general 读；P_publish 写 | 当前 round 可见的状态 |
| `smallSinkStoreNext` | 小型状态的下一值；由 emitter 生成，复用 small-sink 布局 | smallSink 超节点写；P_publish 读 | NBA 缓冲，写入不会立即改变当前读值 |
| `largeSinkStore` | 大型状态的当前值，标量或数组均可 | P_general 读；P_large_sink 写 | P_large_sink 原地提交，不参与整块 publish |
| `inputStore` | 外部输入端口的上次采样值 | P_input 写；事件锥和各消费者读 | 输入变化检测与传播源 |
| `nonSinkBoundaryStore` | nonSink 超节点间传递的 value | P_general 写、读 | 值变化触发 `computeSupernodeFanout` |
| `smallSinkEnableBoundaryStore` | nonSink 到 smallSink 写操作的使能 | P_general 写；smallSink 超节点读 | 使能 bitmap 支持连续区段跳过 |
| `smallSinkPayloadBoundaryStore` | smallSink 写操作的数据、mask、地址等 | P_general 写；smallSink 超节点读 | 仅在使能命中时使用的 payload |
| `largeSinkEnableBoundaryStore` | nonSink 到 P_large_sink 写操作的使能 | P_general 写；P_large_sink 读 | 使能 bitmap 支持连续区段跳过 |
| `largeSinkPayloadBoundaryStore` | 大型状态写操作的数据、mask、地址等 | P_general 写；P_large_sink 读 | 仅在使能命中时使用的 payload |
| `prevEventStore` | 每个 `(event, edge)` 聚类的上一事件值 | P_event 读写 | 跨 round 保存边沿历史 |
| `eventActStore` | 每个事件聚类一个 bit，按字节打包 | P_event 写；P_general/P_large_sink/P_output 读 | 当前 round 的边沿脉冲；每轮 P_event 先清零 |
| `timeslotTriggerFlag` | 带事件的 `$monitor/$strobe` 等时隙任务的触发记录 | P_event 写；P_output 读写 | 跨 round、但只在本次 eval 内粘滞 |
| `activeFlags` | `nonSinkActiveFlag` 与 `nonSinkActiveFlagNext` 两组 u64 位图 | 各阶段读写 | 每个 nonSink 超节点一 bit，按 current/next 传递激活 |

`smallSinkStoreNext` 不是单独的 `CpuNamedStoreKind`，而是生成代码中与 `smallSinkStore` 同布局的下一状态副本。使能 store 可附带 `enabledWords` bitmap；写入按低到高优先级执行，使后声明的高优先级写自然覆盖重叠位。这些是执行辅助结构，不增加 IR 的 named store 类别。

## 3. 六个阶段逐一说明

### 3.1 `P_input`：外部输入进入 `inputStore`

`P_input` 遍历模型的输入端口，把外部 C++ 成员值与 `inputStore` 中的旧值比较。输入发生变化时：

1. 更新对应 `inputStore` 字段；
2. 根据 `inputFanout` 置位目标 General nonSink 超节点的 `nonSinkActiveFlag`；
3. 如果该输入影响输出锥，则设置输出 dirty 标志。

`inputFanout` 的键是 `core.input.read` 产生的 `ValueId`，值是拥有该输入读操作的超节点列表。标记为 `event_only` 的输入不进入 `inputFanout`，由 `P_event` 负责驱动。

带 shape 的输入端口和 `inputStore` 字段都保留原有多维形状，`P_input` 逐元素比较和复制。没有变化的输入不会触发 fanout。

实现入口见 [`pInputBody`](../../wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp:4860)，fanout 构造见 [`cpu_schedule.cpp`](../../wolvrix/lib/grhsim/backend/cpu_schedule.cpp)。

### 3.2 `P_event`：事件锥、边沿历史和事件激活

`P_event` 执行 B2 复制出的事件逻辑锥。每个 `core.event.edgeDet`：

1. 读取事件当前值和 `prevEventStore` 中的历史值；
2. 根据 `posedge`、`negedge` 或 `both` 判定边沿；
3. 命中时设置 `eventActStore[act]`；
4. 无论是否命中，都把当前值写回 `prevEventStore`。

命中的 `act` 通过 `eventActivation` 查表。每个 `CpuEventActivation` 保存一个 `act` 和一组 `supernodeWords`，其中 bit `i` 对应 C2 固定的 General 超节点序号 `i`。命中后，这些位直接 OR 进 `nonSinkActiveFlag`，从而唤醒带事件且有返回值的 nonSink 超节点。

带事件的时隙任务还通过 `timeslotTriggers` 把 `act` 映射到 `timeslotTriggerFlag`。该 flag 必须跨越后续 round，因为 `eventActStore` 会在下一轮被覆盖。

事件阶段不通过 active flag 激活 smallSink 超节点：`SmallSinkEvent` 在 General 调用点直接读取自己的 `eventActStore` 签名，`SmallSinkEscape` 每轮无条件进入扫描。

`edgeDet` 的事件值限定为无 shape 的 1 位 logic，见第 8.2 节。实现见 [`cpu_phase_emit.cpp`](../../wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp) 和 [`verifier.cpp`](../../wolvrix/lib/grhsim/ir/verifier.cpp:1440)。

### 3.3 `P_general`：传播 nonSink 值并执行 smallSink 写入

`P_general` 按 C2 生成的超节点序号扫描。超节点的点火规则由 `CpuSupernodeCategory` 决定：

- **NonSink**：检查 `nonSinkActiveFlag[i]`，命中后清除该 bit 并执行超节点；
- **SmallSinkEvent**：在调用点检查该超节点的 `eventActStore` 事件签名，以及必要的共享 enable；
- **SmallSinkEscape**：每个 round 进入扫描，用于电平敏感 latch/ClockGate enable 等语义。

超节点内部的数据通常是 C++ 局部变量；跨 nonSink 超节点的结果由 `nonSinkBoundaryStore` 承接。该 store 的 value 发生真实变化时，使用 `computeSupernodeFanout` 激活消费者：

- 消费者序号大于当前超节点：置 `nonSinkActiveFlag`，本 round 继续执行；
- 消费者序号小于等于当前超节点：置 `nonSinkActiveFlagNext`，下一 round 执行。

nonSink 产生的写参数按用途进入 small/large 两套 enable/payload boundary store。smallSink 超节点按照“低到高优先级 → eventAct → enable”顺序扫描，`smallSinkEnableBoundaryStore` 的 `enabledWords` 可跳过整段无使能写入；命中后再读取 `smallSinkPayloadBoundaryStore`。小状态的 `write/writeArray/fill/latchWrite` 写入 `smallSinkStoreNext`；当前状态与 next 状态分开，真实变化通过 `commitStateFanout` 置位读者的 `nonSinkActiveFlagNext`。后声明的高优先级写覆盖同一位。

因此本阶段形成三条不同的输出通道：

```text
nonSink value 变化 → nonSinkBoundaryStore → computeSupernodeFanout
小状态变化 → smallSinkStoreNext → commitStateFanout
大型状态写参数 → largeSinkEnableBoundaryStore / largeSinkPayloadBoundaryStore
```

实现入口见 [`pGeneralBody`](../../wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp:4924)，扫描和点火规则见 [`scanRange`](../../wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp:4513)。

### 3.4 `P_large_sink`：按写计划提交大型状态

`P_large_sink` 不扫描普通 General 超节点，而是遍历 C5 产生的 `memWritePlan`。虽然结构名仍含 `Mem`，目标状态可为大型标量或数组。每个 `CpuMemWritePlanEntry` 包含：

- `writeOp`：对应的 LargeSink 相写操作；
- `priority`：同一 state 内的声明顺序；后声明的写优先级更高；
- `eventFree`：是否没有事件门控；
- `readers`：该大型状态的 General 相读者及其地址匹配信息。

写入步骤是：

1. 按 `priority` 从高到低调度，在同一优先级内按 `eventActStore` 签名聚类；
2. 在事件聚类内检查 `largeSinkEnableBoundaryStore` 的使能位，对连续无使能区段批量跳过；
3. 对命中的写入读取 `largeSinkPayloadBoundaryStore` 中的地址、数据、mask 等参数，按低到高优先级写入 `largeSinkStore`；后声明的高优先级位覆盖低优先级写入；
4. 对写入 cell 做变化检测；
5. 变化后根据 `CpuMemReader::staticRow` 精确或保守地置位读者的 `nonSinkActiveFlagNext`。

完全常量、全 rank 的数组索引会折叠成 `staticRow`，只有对应行变化才激活读者；动态索引、部分索引和整体数组读都按动态读者处理。

`P_large_sink` 放在 `P_general` 之后是为了保持 read-before-write：同一 round 的 General 读只能看到本轮开始时的 `largeSinkStore`，写入在本轮末段统一生效。

实现见 [`pLargeSinkBody`](../../wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp:4932)，写计划构造见 [`buildSixPhaseMemWritePlan`](../../wolvrix/lib/grhsim/backend/cpu_schedule.cpp:79)。

### 3.5 `P_publish`：提交 NBA 状态并决定是否继续 round

`P_publish` 没有 IR op，是固定的运行时驱动：

1. 检查 `nonSinkActiveFlagNext` 是否全零；
2. 将 `nonSinkActiveFlagNext` OR 入 `nonSinkActiveFlag`，然后清零 next；
3. 执行 `memcpy(smallSinkStore, smallSinkStoreNext)`；
4. 返回 fixed-point 结果。

如果 next 激活位全为零，说明本轮没有新的小状态、边界 value 或大状态读者需要继续传播，round loop 结束。`largeSinkStore` 已在 `P_large_sink` 原地提交，不需要在这里复制。

实现见 [`pPublishBody`](../../wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp:4940)。

### 3.6 `P_output`：收敛后的输出和时隙任务

`P_output` 在 round loop 结束后执行一次：

- 执行 Output 相位的输出锥，将结果写入外部输出端口；
- 消费 `timeslotTriggerFlag`，执行带事件的 `$monitor/$strobe` 等时隙任务并清除 flag；
- 执行无事件时隙任务的历史变化判断；
- 提交为输出阶段暂存的 `latchWrite`。

输出锥可以使用最终的 `smallSinkStore`、`largeSinkStore` 和所需的输入/边界 store。当前 emitter 还可以使用 `cpu_anyOutChange_` 跳过本次没有输出相关变化的输出锥扫描，但不改变阶段顺序。Output 相位暂存的 `latchWrite` 会在输出锥之后提交到对应 small/large 状态。

## 4. 阶段之间使用的静态 mapping 结构

运行时阶段不传递 `GrhSimModel` 对象；C1–C8 先把模型关系编译成静态表，emitter 再将这些表展开为 C++ 字段访问和函数调用。

| 结构 | 作用 |
| --- | --- |
| `SimOp::phase` | 标记 op 属于 Event、General、LargeSink 或 Output |
| `CpuPartitionTree` | 保存 phase branch、General 超节点、超节点序号、`eventActs` 和 smallSink 分类 |
| `CpuDataLayout` | 保存 CPU 物理类型和 12 类 named store |
| `CpuStoreField` | 把 `StateId` 或 `ValueId` 关联到具体 store 字段、偏移和辅助编号 |
| `CpuFanoutEntry<ValueId>` | `inputFanout` 或 `computeSupernodeFanout` 的一条 value→超节点边 |
| `CpuFanoutEntry<StateId>` | `commitStateFanout` 的一条 state→读者超节点边 |
| `CpuEventActivation` | `event act → nonSink 超节点位图` |
| `CpuMemWritePlanEntry` | `LargeSink 写 op → 优先级、事件属性、大状态读者表`；沿用旧结构名 |
| `CpuTimeslotTrigger` | `event act → timeslot flag` |
| `CpuSchedulePlan` | 保存 task 顺序和上述所有 fanout/plan 表 |
| `CpuBackendMapping` | 汇总 partition tree、data layout、schedule 和最终 TU 计划 |

其中 `CpuSchedulePlan` 的单核任务顺序固定为：

```text
P_event (AlwaysScanCommit)
  → P_general 的各 DataGated EmitFunction
  → P_large_sink (AlwaysScanCommit)
  → P_output (EvalEnd，round loop 外)
```

定义见 [`CpuSchedulePlan`](../../wolvrix/include/grhsim/ir/model.hpp:600)，构造见 [`cpu_schedule.cpp`](../../wolvrix/lib/grhsim/backend/cpu_schedule.cpp)。

## 5. 关键不变量

1. `nonSinkActiveFlag` 是当前 round 的消费队列，`nonSinkActiveFlagNext` 是跨 round 的传播队列。
2. `smallSinkStoreNext` 的写入在 `P_publish` 之前对本轮读不可见，保证 NBA。
3. `largeSinkStore` 在 `P_large_sink` 更新，保证 General 相位的大状态读先于本轮写。
4. `eventActStore` 是 round 级脉冲，`prevEventStore` 是跨 round 历史，`timeslotTriggerFlag` 是 eval 级粘滞记录。
5. `P_event` 的静态激活表、三个 fanout 表和大状态写计划只激活 nonSink General 超节点；smallSink 超节点依赖事件签名或逃逸规则。
6. P_publish 开始时 current 激活位应已被 P_general 消费；因此 `nonSinkActiveFlagNext` 全零可以作为 fixed-point 判定。
7. 小/大状态写都以优先级为最外层顺序；同一优先级内才允许复用事件 guard 和 enable bitmap 检查。

## 6. 参考实现

- 六阶段的早期架构背景（使用旧命名）：[`grhsim-ir-architecture.md`](grhsim-ir-architecture.md:144)
- CPU mapping 数据结构：[`wolvrix/include/grhsim/ir/model.hpp`](../../wolvrix/include/grhsim/ir/model.hpp:309)
- Fanout、事件激活和 large-sink 写计划：[`wolvrix/lib/grhsim/backend/cpu_schedule.cpp`](../../wolvrix/lib/grhsim/backend/cpu_schedule.cpp)
- 运行时 emitter：[`wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp`](../../wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp)
- CPU 单线程阶段调度的早期规范（使用旧命名）：[`wolvrix/docs/grhsim_ir/flows/cpu-st.md`](../../wolvrix/docs/grhsim_ir/flows/cpu-st.md)

## 7. 架构改造要求

以下记录提出改造时的目标命名、数据边界和调度规则。当前工作树已实现其中多项；本节作为后续维护与评审约束，不代表这些改动已经发布或全部验证完成。

### 7.1 按状态规模重命名 sink store

旧实现中的 `regLatchStore`、`regLatchStoreNext` 和 `memStore` 名称保留了 reg/mem 分类含义。目标是统一按状态存储规模命名：

- `regLatchStore` → `smallSinkStore`；
- `regLatchStoreNext` → `smallSinkStoreNext`；
- `memStore` → `largeSinkStore`。

这里不再把状态语义区分为“寄存器”和“memory”。两类 store 都是 sink 状态存储，区别只在于大小和提交策略：小状态使用 current/next 双缓冲，大状态在独立的 large-sink 阶段原地提交。

### 7.2 拆分 `boundaryValueStore` 的多重语义

旧 `boundaryValueStore` 同时承载外部输入、nonSink 之间的边界值，以及向 sink 写操作传递的 enable/payload 参数，语义重叠，要求拆成以下独立 store：

1. **`inputStore`**

   只保存外部输入端口值。`P_input` 负责将外部端口值写入这里，并根据输入 fanout 激活 nonSink 超节点。

2. **`nonSinkBoundaryStore`**

   只保存 nonSink 超节点之间跨边界传递的计算结果。它负责 nonSink 间的变化检测和数据传播，对应 `computeSupernodeFanout`。

3. **`smallSinkEnableBoundaryStore`**

   保存 nonSink 超节点传给 smallSink 超节点的使能位。smallSink 超节点内部使用该 store 做连续区段的批量使能检测和跳过。

4. **`smallSinkPayloadBoundaryStore`**

   保存 nonSink 超节点传给 smallSink 超节点的 payload，例如输入数据、mask、地址等。enable 与 payload 分离，避免批量跳过检查时读取和处理完整 payload。

5. **`largeSinkEnableBoundaryStore`**

   保存 nonSink 超节点传给 `P_large_sink` 阶段的大型状态写使能位。

6. **`largeSinkPayloadBoundaryStore`**

   保存 `P_large_sink` 阶段所需的 payload，例如写入数据、mask、地址和其他写参数。

对应的阶段和命名也需要同步调整：

- 旧 `SinkEvent` / `SinkEscape` 等 sink 超节点命名中的普通 sink，应改称 **smallSink 超节点**；
- 旧 `P_mem` 阶段应改称 **`P_large_sink`**；
- `P_large_sink` 的输入只来自 `largeSinkEnableBoundaryStore` 和 `largeSinkPayloadBoundaryStore`。

### 7.3 明确 nonSink 激活位图命名

旧 `dataActiveFlag` / `dataActiveFlagNext` 的命名没有体现这些位图只服务于 nonSink 超节点。要求改为：

- `dataActiveFlag` → `nonSinkActiveFlag`；
- `dataActiveFlagNext` → `nonSinkActiveFlagNext`。

这里保留 current/next 两组位图的双缓冲关系：current 位图供当前 round 消费，next 位图承载本轮产生的跨 round 激活。

### 7.4 Enable boundary 用于批量跳过

`smallSinkEnableBoundaryStore` 和 `largeSinkEnableBoundaryStore` 不只是普通边界值存储，还应成为两个批量跳过路径的专用输入：

- **smallSink 超节点**：根据 `smallSinkEnableBoundaryStore` 对连续使能区段进行批量检测；整段无使能时跳过 payload 读取和超节点内部执行；
- **`P_large_sink`**：根据 `largeSinkEnableBoundaryStore` 对连续大型状态写区段进行批量检测；整段无使能时跳过地址、数据、mask 处理和 `largeSinkStore` 写入。

因此，enable store 的布局应支持按连续区段或 bitmap word 扫描，payload store 则保持与实际写操作对应的字段布局。两者的拆分目标是让“是否需要执行”的判断不必触碰大块 payload 数据。

### 7.5 目标数据流

改造后的主要运行时数据流应趋向于：

```text
外部端口
  → inputStore
  → nonSinkActiveFlag
  → nonSink 超节点
      ├─→ nonSinkBoundaryStore
      ├─→ smallSinkEnableBoundaryStore
      ├─→ smallSinkPayloadBoundaryStore
      ├─→ largeSinkEnableBoundaryStore
      └─→ largeSinkPayloadBoundaryStore

smallSink 超节点:
  smallSinkEnableBoundaryStore + smallSinkPayloadBoundaryStore
  → smallSinkStoreNext
  → P_publish
  → smallSinkStore

P_large_sink:
  largeSinkEnableBoundaryStore + largeSinkPayloadBoundaryStore
  → largeSinkStore
  → nonSinkActiveFlagNext
```

### 7.6 Sink 写入按“低到高优先级 → eventAct → enable”三级聚类

原先 smallSink 写入和 large sink 写入主要按 `eventAct` 聚类，会把不同写入优先级混在同一个事件簇中。现在按声明优先级从低到高执行，后声明写自然覆盖先声明写，以下顺序仍是必须维持的架构约束。

smallSink 超节点和 `P_large_sink` 的写入调度都应采用以下层次：

```text
优先级（最高层）
  └─ eventAct 聚类
       └─ enable 批量跳过
            └─ 具体写入操作
```

调度规则为：

1. 先选出当前最低优先级的写入集合；
2. 在该优先级内部按 `eventAct` 签名或 `eventAct` 集合聚类；
3. 对每个 `eventAct` 聚类使用对应的 enable boundary 做连续区段或 bitmap word 批量检测；
4. 只有 enable 检测命中的区段才读取 payload 并执行具体写入；
5. 当前优先级的所有 `eventAct` 聚类完成后，进入下一个更高优先级；重复上述过程直到所有优先级处理完毕。

同状态多个 event-free 写可能每轮先改变再恢复原值。此时不能因中间值反复唤醒 General
读者：smallSink 在 publish 前比较已有 current/next；largeSink 只记录被实际改动行的
首次旧值，在全部写完后与最终行值比较，再清空记录。此记录仅用于这类状态的收敛判定，
写入优先级仍由执行顺序保证。

这条规则同时适用于：

- smallSink 超节点内部对 `smallSinkStoreNext` 的写入；
- `P_large_sink` 对 `largeSinkStore` 的写入。

因此，写计划不能只有“按 eventAct 分组”的扁平列表，而应显式保留三级结构，或者保留能够确定性重建该结构的字段：

```text
priority bucket
  → eventAct bucket
      → enable-run / bitmap-word bucket
          → write payload entries
```

优先级层必须位于最外层，不能为了合并 `eventAct` guard 或 enable bitmap 而跨优先级合并。相同优先级内部可以共享事件判断，相同事件聚类内部可以共享 enable 批量检测，但这些优化都不能改变优先级之间的先后顺序。

写计划还必须继续保留 small/large 两条状态提交路径的差异：smallSink 写入最终进入 `smallSinkStoreNext`，由 `P_publish` 提交；large sink 写入最终进入 `largeSinkStore`，由 `P_large_sink` 原地提交。两条路径共享三级调度原则，但不共享最终状态提交位置。

## 8. GrhSIM IR aggregate 支持复核（2026-10-13）

这里的 aggregate 指同质逻辑数组：GrhSIM IR 用总位宽 `width` 和行主序 `shape`
表示它；异构 struct/union 在 GRH ingest 中按字段拆分，GrhSIM 本身不保留字段树。
以下结论基于当前工作树中的 lowering、verifier、CPU mapping 与 C++ emitter，尚非发布状态。

### 8.1 当前工作树的实现状态

| 路径 | 复核结果 |
| --- | --- |
| 类型与 JSON | `core.logic` 保存 `width + shape`，JSON v3 保留 shape；verifier 检查维度为正、乘积可表示且整除总位宽。 |
| GRH lowering | 端口、普通 value 和数组状态携带 shape；`readArray/writeArray/sliceArray` 保留多索引和剩余维度。扁平基值的多索引不被猜测为某个 shape。 |
| 两态 CPU emit | 物理状态字段、boundary 字段、端口和局部 shaped value 以嵌套 `std::array` emit。例如 `shape=[3,4]` 的 8 位元素为 `std::array<std::array<std::uint8_t,4>,3>`；部分运算仍显式打包成总位宽值再拆回数组。整体读写、部分/全秩索引、mask、fill、宽元素及 FST 逐元素注册已有实现路径。 |
| 状态分类 | 当前 GrhSIM emit 对 logic 标量和数组按状态存储规模进入 smallSink 或 largeSink；小状态通过 next buffer 提交，大状态在 `P_large_sink` 原地提交。非 logic 状态目前不能进入 largeSink，见 8.4。 |
| 静态 reader 唤醒 | `staticRow` 现在按全部维度折叠，首维为 0 时不会提前结束。`shape=[2,3]` 的 `[0][2]` 对应 row 2、`[1][0]` 对应 row 3；动态/部分索引仍采用保守唤醒。 |
| 索引契约 | `readArray/writeArray/sliceArray` 的结果或写入数据必须保留索引后的剩余 shape，index 和写使能必须是无 shape 的标量 logic；整状态读写仍允许等总位宽的 packed 值作为结构视图转换。 |
| 初始化 | 数组 `core.init.const` 使用一个总位宽 literal string，verifier 和 CPU emitter 均按此契约处理，再逐元素拆入多维存储。 |
| 边界与写入调度 | 数组 value 跟随第 2 节的独立 store 保留 shape；small/large 两条写入路径均按低到高优先级、事件签名、使能区段的顺序处理，后声明写覆盖重叠位。 |

对应实现主要在 [`cpu_layout.cpp`](../../wolvrix/lib/grhsim/backend/cpu_layout.cpp)、
[`cpu_schedule.cpp`](../../wolvrix/lib/grhsim/backend/cpu_schedule.cpp)、
[`verifier.cpp`](../../wolvrix/lib/grhsim/ir/verifier.cpp) 和
[`cpu_phase_emit.cpp`](../../wolvrix/lib/grhsim/backend/cpu_phase_emit.cpp)；
数组与拒绝路径用例见 [`test_cpu_phase_emit.cpp`](../../wolvrix/tests/grhsim/test_cpu_phase_emit.cpp)。

### 8.2 明确要求与不支持范围

以下四条是本次补充的硬性口径（2026-10-14），用于后续实现和评审；即使局部代码已有实现也不能放宽：

1. **多维数组也要以多维数组形式 emit。** `shape` 的 rank 和每维边界必须在生成的数组声明、状态/边界字段、端口及 shaped 局部值中保留；不能把数组永久降为 `product(shape)` 长度的一维数组，再仅靠 stride 恢复其结构。总位宽运算中的内部打包/拆包不得替代多维数组的声明与存储。
2. **`core.event.edgeDet` 只能处理 1 位 logic。** 事件 operand 必须是无 shape 的一位 logic；宽于 1 位或即使总宽为 1 但带 shape 的值都直接拒绝。不要为 aggregate 加全宽边沿、“全零到非零”边沿或其他扩展语义。
3. **四态 aggregate 的 GrhSIM emit 一律不支持。** IR/JSON 可以表示该类型，不意味着任何 GrhSIM emit 路径可以生成运行时代码；emit 遇到四态 aggregate 必须明确拒绝，不添加四态数组执行路径。
4. **DPI aggregate 参数/返回值 ABI 未实现（P1），标记为不支持。** input/output/inout 参数和返回值只要带 aggregate shape，就直接拒绝；不得假定扁平总位宽 ABI、逐元素 ABI 或隐式转换。`dpiType` 当前已有相应诊断，但这不表示 ABI 已完成。

当前 verifier 对第 2 条已作无 shape、宽度为 1 的校验，emitter 对第 3 条和第 4 条已有拒绝路径；这些检查仍应作为长期契约保留。第 1 条的现有实现保留了嵌套声明，但涉及 packed 运算的具体生成代码还应在回归中核对，不能只检查 IR 的 shape 元数据。

### 8.3 验收检查点

- 检查 `shape=[2,3]` 的状态、输入/输出、boundary 与局部值是否均保留 `[2][3]` 结构，并核对部分索引及 FST 逐元素地址。
- 核对 `[0][2]`、`[1][0]` 的静态 reader 唤醒、动态 reader 唤醒，以及同一状态上跨优先级、跨 eventAct 的写入顺序和 enable 批量跳过。
- 保留 `edgeDet` shaped/宽值、四态 aggregate emit、DPI aggregate 各方向参数与返回值的拒绝回归。
- 用总位宽 literal 的 `core.init.const` 检查多维初值的行主序拆分。

### 8.4 当前实现边界

- “按大小区分”是 sink store 的目标语义，但当前分类器只把 logic 状态按 `memMinBytes` 阈值划入 `largeSink`；非 logic 状态即使字节数达到阈值也不会进入该类。
- verifier 当前拒绝把非 logic 状态标记为 `largeSink`。因此，非 logic 状态的 large-sink 写入、优先级调度和 ABI 不能从现有实现推断为已支持能力；若后续要扩大到这类状态，需要单独定义布局、写入和提交语义。
