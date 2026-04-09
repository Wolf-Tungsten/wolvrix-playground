# GrhSIM 计划

当下需要进行一次深入的重构，重新梳理eval的调度逻辑，实现和 verilator 等成熟仿真工具一致的调度逻辑。

## 调度模型整理

- 不需要把event和数据分开，统一是为活动度的变动信号，activity-schedule 不需要再分析 event terms，cpp emit 的 supernode 调度也不需要再维护event + activity 两重判断逻辑，每个 supernode 只需要维护一个活动位
- activity-schedule 分析超节点之间依赖关系时，把带event的信号当成普通信号分析，依赖关系分析不需要区分 event 和 data 信号
- activity-schedule 要记录从声明性节点（如 kRegister）到源节点（如 kRegisterReadPort）之间的数据传递关系
- 带有 event 的节点（如 kRegisterWritePort、kDPICall）要能识别事件信号是否触发，比如，要记录上次求解时的事件信号状态，以便判断本次是否需要求解
- eval 的调度逻辑改成这样：
    - 分为两个阶段 propagate 和 commit
    - propagate 阶段按拓扑序求解所有 supernode
        - 在发生 value 更新时按需激活受影响的后续 supernode
        - 每个 supernode 求解时复位自己的活动位
        - kRegisterWritePort、kMemoryWritePort、kLatchWritePort 的求解结果要延迟到 commit 阶段才能更新到 kRegister、kMemory、kLatch 中
    - commit 阶段应用状态更新，并判断是否达到稳定点
        - 把 kRegisterWritePort、kMemoryWritePort、kLatchWritePort 的结果更新到 kRegister、kMemory、kLatch 中
        - 如果 kRegister、kLatch 的值发生变化，则要把它们所有对应读端口所在的 supernode 标记为活动的
    - 稳定点的判断条件是：没有任何 supernode 被标记为活动的了
    - 如果仍然有 supernode 被标记为活动的了，那么就继续进入 propagate 阶段
- 首次执行前，将所有 supernode 标记为活动的，以确保第一次 eval 能获取 init 的结果

上面的原则可以整理成下面几条更明确的实现规则：

1. 静态依赖图统一建模，不再维护 event/data 两套调度逻辑

   activity-schedule 只维护 supernode 之间的普通依赖关系。带有 event 语义的输入信号在建图时仍然按普通输入处理，因此 supernode 运行时只需要一个 `active bit`。

2. event 的语义保留在节点本地，而不是体现在全局调度图里

   对 `kRegisterWritePort`、`kMemoryWritePort`、`kLatchWritePort`、`kDPICall` 这类带 event 语义的节点，需要记录上一次求解时相关 event 信号的状态。本次执行时，节点自行判断 event 是否触发，例如是否出现 `posedge` / `negedge`，再决定是否产生有效结果。

3. 声明性状态节点与其读端口之间的关系要显式记录

   例如要记录 `kRegister -> kRegisterReadPort`、`kLatch -> kLatchReadPort` 的数据传递关系。这样在 commit 阶段状态值真的发生变化后，才能精确地重新激活所有依赖这些读端口的 supernode。

4. eval 拆分为 `propagate` 和 `commit` 两阶段循环

   `propagate` 阶段：

   - 按拓扑序执行所有当前 active 的 supernode
   - supernode 执行时先清掉自己的活动位
   - 如果某个普通输出值发生变化，则按需激活其后继 supernode
   - `kRegisterWritePort`、`kMemoryWritePort`、`kLatchWritePort` 只能产出“待提交结果”，不能直接修改 `kRegister`、`kMemory`、`kLatch`

   `commit` 阶段：

   - 把待提交结果真正写回 `kRegister`、`kMemory`、`kLatch`
   - 如果 `kRegister` 或 `kLatch` 的值发生变化，就把所有对应读端口所在的 supernode 标记为 active
   - 稳定点条件为：commit 结束后，没有任何 supernode 仍然是 active
   - 如果还有 active supernode，则继续进入下一轮 `propagate`

5. 首次 eval 前需要全量激活

   在第一次执行前，把所有 supernode 都标记为 active。这样才能保证 init 值、初始组合逻辑结果、以及首次 event 检查都被完整计算出来。

## 举例说明

考虑下面这个最小例子：

```verilog
logic clk, a, b, c, q, d, y;

assign d = a & b;
always_ff @(posedge clk) q <= d;
assign y = q | c;
```

可以拆成 3 个 supernode：

- `S1`：计算 `d = a & b`
- `S2`：计算 `kRegisterWritePort(q)`，输入是 `clk` 和 `d`
- `S3`：通过 `kRegisterReadPort(q)` 读取 `q`，再计算 `y = q | c`

依赖关系如下：

- `S1 -> S2`，因为 `d` 是 `q` 写端口的输入
- `clk -> S2`，虽然 `clk` 带 event 语义，但静态分析时仍按普通依赖处理
- `kRegister(q) -> kRegisterReadPort(q) -> S3`，这条关系需要显式记录，供 commit 后回激活

假设初始状态为：

```text
clk = 0, a = 1, b = 1, c = 0, q = 0
```

并且第一次 `eval` 前，所有 supernode 都已经被标记为 active。

### 第一次 eval

第一轮 `propagate`：

- `S1` 执行，得到 `d = 1`
- `S2` 执行，检查到 `clk` 当前为 0，没有 `posedge`，因此不产生对 `q` 的有效写入
- `S3` 执行，读取 `q = 0`，得到 `y = 0`

第一轮 `commit`：

- 没有待提交的状态写入
- 没有新的 supernode 被重新激活
- 系统达到稳定点，第一次 `eval` 结束

### 外部把 `clk` 从 0 改为 1 后再次 eval

第一轮 `propagate`：

- `S2` 因为 `clk` 变化而被激活
- `S2` 对比上次 event 状态 `clk = 0` 与本次 `clk = 1`，识别到 `posedge`
- 因此 `S2` 生成一个待提交结果：`q := d = 1`
- 注意，这一阶段还不能立刻把 `q` 改成 1

第一轮 `commit`：

- 把待提交结果写回 `kRegister(q)`，因此 `q: 0 -> 1`
- 因为 `q` 发生变化，激活所有依赖 `kRegisterReadPort(q)` 的 supernode，也就是 `S3`
- 此时仍然存在 active supernode，因此尚未稳定

第二轮 `propagate`：

- `S3` 重新执行，读取到新的 `q = 1`
- 得到 `y = 1 | 0 = 1`

第二轮 `commit`：

- 没有新的状态写入
- 没有 supernode 继续保持 active
- 系统达到稳定点，本次 `eval` 结束

这个例子体现了两个关键点：

- `q` 的状态更新必须延迟到 `commit` 阶段
- 状态更新后不是整图重跑，而是只回激活依赖对应读端口的 supernode

再看一个补充场景：如果此时 `clk` 保持为 1，只把 `a` 从 1 改成 0，那么：

- `S1` 会把 `d` 从 1 算成 0
- `S2` 会因为输入 `d` 变化而重新执行
- 但 `S2` 检查 event 后发现这次没有新的 `posedge`
- 因此不会产生新的 `q := 0` 提交
- 最终 `q` 仍保持为 1

这说明：带 event 语义的节点在静态依赖图里按普通依赖建模，但是否真的生效，仍由节点在运行时基于 event 状态自行判断。

