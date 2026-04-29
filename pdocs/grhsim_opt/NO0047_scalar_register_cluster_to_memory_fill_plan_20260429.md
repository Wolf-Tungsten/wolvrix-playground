# NO0047 Scalar Register Cluster -> Memory + Fill Pass 设计稿

## 1. 背景与结论

在 `frontend.inner_bpu$tage.tables_1.usefulCtrs[*][*][*]` 这个案例里，当前输入给 `wolvrix ingest` 的 `SV` 已经不是“一个数组寄存器 + 索引读写”的形态，而是：

- 大量离散标量寄存器，例如 `usefulCtrs_0_1_0_value` 到 `usefulCtrs_0_1_511_value`
- 读侧通过显式 `concat` 把这些标量重新拼回聚合向量
- 写侧通过 `if (setIdx == i)` 逐元素命中
- reset / `io_resetUseful` 通过显式枚举把整组元素逐个清零

这意味着：

1. 在 `ingest` 阶段做“恢复 memory”不是好思路。
2. 更合理的路径是在 `transform` 阶段新增一个识别与重写 pass。
3. 现有 `GRH IR` 已能表达“memory + 单点读 + 单点写”，但不能紧凑表达“同一 memory 的整组 fill/reset”。
4. 因此需要新增一个一等 IR 节点，例如 `kMemoryFillPort`，而不是把 `kMemoryWritePort` 改成“地址和 mask 可选”。

本文给出该方案的推荐设计。

## 2. 直接证据

### 2.1 当前 `SV` 早已打散

在 [build/xs/rtl/rtl/TageTable_1.sv](/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/rtl/rtl/TageTable_1.sv:851) 中，这组状态已经是标量寄存器声明，而不是一个整体数组状态：

- `reg [1:0] usefulCtrs_0_1_0_value;`
- `reg [1:0] usefulCtrs_0_1_1_value;`
- ...
- `reg [1:0] usefulCtrs_0_1_511_value;`

读侧通过显式 `concat` 重建聚合视图，见 [build/xs/rtl/rtl/TageTable_1.sv:5568](/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/rtl/rtl/TageTable_1.sv:5568)。

写侧通过显式逐元素条件赋值实现，见：

- [build/xs/rtl/rtl/TageTable_1.sv:18449](/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/rtl/rtl/TageTable_1.sv:18449)
- [build/xs/rtl/rtl/TageTable_1.sv:18452](/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/rtl/rtl/TageTable_1.sv:18452)
- [build/xs/rtl/rtl/TageTable_1.sv:19982](/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/rtl/rtl/TageTable_1.sv:19982)

reset / `io_resetUseful` 也已经是逐元素清零，见：

- [build/xs/rtl/rtl/TageTable_1.sv:8711](/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/rtl/rtl/TageTable_1.sv:8711)
- [build/xs/rtl/rtl/TageTable_1.sv:9226](/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/rtl/rtl/TageTable_1.sv:9226)
- [build/xs/rtl/rtl/TageTable_1.sv:12812](/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/rtl/rtl/TageTable_1.sv:12812)
- [build/xs/rtl/rtl/TageTable_1.sv:13326](/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/rtl/rtl/TageTable_1.sv:13326)

### 2.2 当前 `GRH IR` 能力边界

现有 `GRH` 已定义：

- `kMemory`
- `kMemoryReadPort`
- `kMemoryWritePort`
- `kSliceArray`

见 [wolvrix/include/core/grh.hpp](/workspace/gaoruihao-dev-gpu/wolvrix-playground/wolvrix/include/core/grh.hpp:25)。

`ingest` 对 memory 的 lowering 也已经存在：

- memory declaration: [wolvrix/lib/core/ingest.cpp:13636](/workspace/gaoruihao-dev-gpu/wolvrix-playground/wolvrix/lib/core/ingest.cpp:13636)
- memory read: [wolvrix/lib/core/ingest.cpp:13748](/workspace/gaoruihao-dev-gpu/wolvrix-playground/wolvrix/lib/core/ingest.cpp:13748)
- memory write: [wolvrix/lib/core/ingest.cpp:13795](/workspace/gaoruihao-dev-gpu/wolvrix-playground/wolvrix/lib/core/ingest.cpp:13795)

但当前 memory write 语义是“单地址写”：

- `updateCond`
- `addr`
- `data`
- `mask`

见 `system_verilog` emitter 校验与生成逻辑：

- [wolvrix/lib/emit/system_verilog.cpp:4698](/workspace/gaoruihao-dev-gpu/wolvrix-playground/wolvrix/lib/emit/system_verilog.cpp:4698)
- [wolvrix/lib/emit/system_verilog.cpp:4728](/workspace/gaoruihao-dev-gpu/wolvrix-playground/wolvrix/lib/emit/system_verilog.cpp:4728)

因此它不能自然承载“整组 fill/reset”。

### 2.3 `ingest` 当前也不支持整组 memory 写

当前 memory write lowering 明确要求地址切片存在，并且不支持多切片 bulk 语义：

- `Memory write missing address slices`
- `Multi-slice memory write is unsupported`

见：

- [wolvrix/lib/core/ingest.cpp:12513](/workspace/gaoruihao-dev-gpu/wolvrix-playground/wolvrix/lib/core/ingest.cpp:12513)
- [wolvrix/lib/core/ingest.cpp:12819](/workspace/gaoruihao-dev-gpu/wolvrix-playground/wolvrix/lib/core/ingest.cpp:12819)

## 3. 为什么不建议在 ingest 阶段做

### 3.1 输入已经丢失了“原始数组边界”

`ingest` 看到的是打散后的 `SV`。它无法天然区分：

- “这一串标量本来是一个数组状态”
- “这一串标量原本就是独立状态，只是名字碰巧很像”

如果在 `ingest` 里试图强行恢复，会把高层语义猜测和底层语法 lowering 混在一起，调试难度很高。

### 3.2 `transform` 更容易利用全局图信息做保守判断

在 `transform` 阶段，可以同时观察：

- 状态声明
- 全部 read users
- 全部 write users
- reset/fill 路径
- DPI / XMR / blackbox 等旁路使用

这时才能做“只在足够安全时合并”的保守变换。

### 3.3 更符合现有代码结构

现有仓库已经把语义重写型逻辑放在 `wolvrix/lib/transform/`：

- `mem_to_reg`
- `memory_read_retime`
- `simplify`
- `slice_index_const`

见 [wolvrix/lib/core/transform.cpp](/workspace/gaoruihao-dev-gpu/wolvrix-playground/wolvrix/lib/core/transform.cpp:1) 和 [wolvrix/lib/transform/](/workspace/gaoruihao-dev-gpu/wolvrix-playground/wolvrix/lib/transform/README.md)。

因此“把打散标量状态恢复成 memory 抽象”更适合作为一个独立 transform pass。

## 4. 推荐 IR 扩展

### 4.1 保留 `kMemoryWritePort`

不建议把 `kMemoryWritePort` 改成“地址和 mask 可选”。原因是这会把两类明显不同的语义混进一个 op：

- 单地址写
- 整组 fill

这样会污染：

- validator
- emitter
- 后续 pass 的匹配逻辑

### 4.2 新增 `kMemoryFillPort`

推荐新增：

- `kMemoryFillPort`

建议语义：

- target: `memSymbol`
- operands: `updateCond`, `data`, `event operands...`
- attrs: `eventEdge`, `memSymbol`

语义定义：

> 在对应事件触发时，若 `updateCond == 1`，则将目标 memory 的全部 row 填为同一个 `data` 值。

这个语义正好对应：

- `reset` 整组清零
- `io_resetUseful` 整组清零
- 未来其他“整组置固定值”的 memory-like 状态

### 4.3 与现有 op 的关系

- `kMemoryReadPort`: 单点读
- `kMemoryWritePort`: 单点写
- `kMemoryFillPort`: 全量同值写

三者职责清晰，不重叠。

## 5. 推荐 pass 目标

推荐新增一个 pass，例如：

- `scalar_memory_pack`
- 或 `reg_cluster_to_memory`

输入：

- 一组离散 `kRegister`
- 其配套的 `kRegisterReadPort`
- 其配套的 `kRegisterWritePort`

输出：

- 一个 `kMemory`
- 若干 `kMemoryReadPort`
- 若干 `kMemoryWritePort`
- 若干 `kMemoryFillPort`

## 6. 识别模式：不能只看 `concat + slice`

只看 `concat + slice` 只能识别读侧，远不足以证明“这是一组可安全合并的 memory-like 状态”。完整匹配应至少包含三层。

### 6.1 状态簇识别

先找候选标量寄存器簇，要求：

- 宽度一致
- signedness / valueType 一致
- clock / reset event edge 一致
- 名字可分解为“公共前缀 + 连续索引”
- 索引空间连续且完整

名字只能作为候选种子，不能作为最终判据。

### 6.2 读侧识别

需要识别“这些标量被当数组读”：

- `N` 个 `kRegisterReadPort`
- 结果进入 `kConcat` 或 concat tree
- 后续被 `kSliceDynamic` / `kSliceArray` / 等价线性化索引消费
- slice width 恰好等于单元素宽度

在 `tage usefulCtrs` case 中，当前 read side 就满足这一特征。

### 6.3 写侧识别

需要识别“这些标量被当数组单点写”：

- `N` 个 `kRegisterWritePort`
- 指向同一候选簇
- 事件边一致
- mask 一致，通常是全 1
- `updateCond_i` 共享一个公共 write guard，并附带 `index == i`
- `nextValue_i` 共享一个公共 write data

概念上等价于：

```text
if (writeCond && index == i)
  state[i] = writeData;
```

### 6.4 fill/reset 侧识别

还需要单独识别“整组统一写”：

- 全部元素都有一条共同来源的 `fillCond`
- 被写入的数据相同，常见是 `0`
- 与单点写共享同一事件边

概念上等价于：

```text
if (fillCond)
  for all i: state[i] = fillData;
```

这一步正是 `kMemoryFillPort` 的来源。

## 7. 对 `tage usefulCtrs` 的重写映射

以 `frontend.inner_bpu$tage.tables_1.usefulCtrs[0][1][*]` 为例，可重写为：

### 7.1 状态声明

原来：

- `512` 个 `kRegister`
- 每个宽度 `2`

重写后：

- `1` 个 `kMemory`
- `row = 512`
- `width = 2`

### 7.2 读侧

原来：

- `512` 个 `kRegisterReadPort`
- `concat`
- 再从聚合值中做 slice/index

重写后：

- 直接把索引线性化为 `addr`
- 用 `kMemoryReadPort(addr)` 得到 2-bit 元素值

### 7.3 单点写侧

原来：

- `512` 个 `kRegisterWritePort`
- `setIdx == i` 时命中第 `i` 个元素

重写后：

- `1` 个 `kMemoryWritePort(writeCond, setIdx, writeData, fullMask, ...)`

对于 `2-bit` 元素，`mask` 仍保留，以兼容现有 memory write 语义。

### 7.4 reset/fill 侧

原来：

- `512` 个 `kRegisterWritePort`
- `reset` 或 `io_resetUseful` 时全部写 `0`

重写后：

- `1` 个 `kMemoryFillPort(resetCond, 2'h0, ...)`
- `1` 个 `kMemoryFillPort(io_resetUseful, 2'h0, ...)`

如果两者 guard 已在更高层合并，也可以进一步归并成一条。

## 8. 正确性约束

该 pass 必须是保守变换。推荐只在以下条件全部满足时才触发。

### 8.1 状态结构约束

- 所有成员寄存器类型完全一致
- 索引空间完整，无缺口
- 没有额外 bit-slice 写把单元素再拆开

### 8.2 读约束

- 没有簇外读口以“独立标量状态”身份使用这些寄存器
- 或者这些簇外读口也都能同步重写为 memory read

### 8.3 写约束

- 没有多写源冲突
- 没有不同事件边的写口混入同一簇
- 单点写的 `index -> member` 对应关系必须能精确恢复

### 8.4 fill/write 关系约束

关键问题不是“是否同时存在 fill 和单点写”，而是**同一事件沿上的优先级是否可证明**。

推荐第一版采用保守策略：

- 只有当 pass 能证明 `fillCond` 与 `pointWriteCond` 互斥，或能证明某一方严格优先时，才允许合并

对于 `tage usefulCtrs`，`reset` / `io_resetUseful` 在 `if / else` 结构中优先于普通单点写，因此理论上是可证明的。

### 8.5 旁路使用约束

出现以下任意情况时应放弃合并：

- DPI 直接引用单成员
- XMR 直接引用单成员
- blackbox port 直接接单成员
- 名字保持对外可见且后续流程依赖单成员名

## 9. emitter 需要的改动

### 9.1 `system_verilog` emitter

新增 `kMemoryFillPort` 后，`system_verilog` emitter 需要支持在顺序块中发射：

```systemverilog
if (fillCond) begin
  for (int __i = 0; __i < ROWS; __i = __i + 1)
    mem[__i] <= fillData;
end
```

或发射为等价展开形式。推荐优先使用 `for`，可读性更高。

### 9.2 `grhsim_cpp` emitter

`grhsim` 侧需要新增 memory fill commit 路径。一个直观实现是：

- commit 阶段识别 `kMemoryFillPort`
- 生成一个 row loop
- 对目标 memory 的每一行执行相同数据写入

这一路径与当前 `kMemoryWritePort` 的单地址 commit 明确区分。

## 10. pass 与现有优化方向的关系

这个 pass 和当前 `grhsim` 性能问题高度相关：

- 它能把读侧“海量 `register read -> concat -> slice`”还原成直接 memory read
- 它能把写侧“海量 `setIdx == i` 的单成员写”还原成单地址 memory write
- 它能把 reset / `io_resetUseful` 的整组清零还原成单条 fill op

因此它和以下已有方向相互补强，而不是替代：

- `NO0018` state-read tail absorb
- `NO0029` sink event cluster
- `NO0034` sink activation narrowing
- `NO0046` `tage` 展开归因结论

## 11. 推荐实施顺序

### 11.0 推荐插入位置

推荐把该 pass 放在：

- `xmr-resolve` 之后
- `memory-read-retime` 之前

理由如下：

1. `xmr-resolve` 之后，跨层次引用已经被正规化为显式端口和实例连接，便于保守判断某一簇离散寄存器是否已经被模块边界观察到。如果某些成员在这一步之后已经进入 port / instance 连接，则该簇应直接跳过，不再尝试合并。
2. `memory-read-retime` 之前，IR 仍保留更接近原始结构的 memory-like 读写关系。`memory-read-retime` 会把一类 `kMemoryReadPort` 重写成“地址寄存器 + 数据寄存器”的 retimed 结构，这会进一步打散图形态，不利于识别原本规整的“离散寄存器阵列”模式。
3. 该位置天然适合按 graph 独立并行处理。大多数可合并簇都应该局限在单个 module graph 内；若跨 graph 暴露，则通常意味着它已经被 hierarchy / boundary 观察到，应保守放弃。

因此，第一版实现建议采用如下 pass 顺序：

```text
xmr-resolve
-> scalar-memory-pack
-> memory-read-retime
```

如果后续发现少量 trivial 形态在该位置还不够规整，优先选择在 `scalar-memory-pack` 内部加入轻量 canonicalization，而不是把整个 pass 后移到更多优化之后。

## 12. 当前实现状态

截至 `2026-04-29`，代码侧已经落了一版保守实现，和最初“先恢复成常地址 memory port”的过渡思路不同，当前实现直接瞄准有优化价值的动态访问形态。

### 12.1 已实现能力

- 新增 `kMemoryFillPort`
- 新增 `scalar-memory-pack` pass，并接入 transform framework
- `grhsim_cpp` / `system_verilog` emitter 均已支持 `kMemoryFillPort`
- `activity_schedule` 回归已确认 `kMemoryFillPort` 会作为 commit/sink supernode 参与调度
- pass 目前只接受精确读模式：
  - 一组 `kRegisterReadPort`
  - 进入单个 `kConcat` 或纯 `concat tree`
  - 根 `concat` 结果被 `kSliceArray` 或 `kSliceDynamic` 消费
  - 对 `kSliceDynamic`，当前支持：
    - `idx * elemWidth`
    - `idx << log2(elemWidth)`
    - 上述形式再叠加整元素偏移，例如 `idx * elemWidth + K`
    - `N-1-idx` 这类反向索引及其与整元素偏移的保守组合
  - `sliceWidth == elementWidth`
- pass 会把上述读模式直接改写成动态地址 `kMemoryReadPort`
- 写侧会把
  - `baseCond && (idx == i)` 形式的逐元素 `kRegisterWritePort`
  - 收敛成一个动态地址 `kMemoryWritePort`
- fill/reset 侧会把
  - 同条件、同数据、同事件边、全掩码的整簇逐元素写
  - 收敛成一个 `kMemoryFillPort`

### 12.2 当前刻意保守的边界

这版没有尝试覆盖所有“看起来像 memory”的读写写法，而是只做窄而稳的识别：

- 不处理更一般的 `concat tree` 共享子树 / 多根复用
- 不处理 `kSliceDynamic` 上更一般的线性表达式，只支持按元素宽度 stride 的保守子集
- 不处理部分元素缺失、索引不连续、非零起始索引
- 不处理非全掩码的 fill
- 不处理多种读聚合视图共享同一簇的复杂情况

也就是说，这版的目标不是“一次吃掉所有 scalarized memory”，而是先把 `frontend.inner_bpu$tage.tables_1.usefulCtrs` 这类最典型、最有收益的形态稳定打通。

### 阶段 A：IR 扩展

- 在 [wolvrix/include/core/grh.hpp](/workspace/gaoruihao-dev-gpu/wolvrix-playground/wolvrix/include/core/grh.hpp:25) 新增 `kMemoryFillPort`
- 补齐 JSON/store/load/打印/validator 支持

### 阶段 B：emitter 支持

- `system_verilog` emitter 支持 `kMemoryFillPort`
- `grhsim_cpp` emitter 支持 `kMemoryFillPort`

### 阶段 C：transform pass

- 新增 `scalar_memory_pack` pass
- 第一版只支持最明确的一类模式：
  - 同宽度
  - 同 event
  - 连续索引
  - 读侧 concat+slice
  - 写侧单点命中
  - fill 为统一常量

### 阶段 D：在 `tage usefulCtrs` 上做 case 验证

验收目标：

- `kRegister` / `kRegisterReadPort` / `kRegisterWritePort` 数量显著下降
- 出现对应的 `kMemory` / `kMemoryReadPort` / `kMemoryWritePort` / `kMemoryFillPort`
- `grhsim` 生成代码中不再出现 `512` 条 `setIdx == i` 的离散写口

## 12. 最终建议

本轮建议采用以下结论作为后续实现基线：

1. 不在 `ingest` 阶段恢复这类 memory-like 状态。
2. 在 `transform` 阶段新增一个保守的“离散寄存器簇 -> memory”重写 pass。
3. 新增 `kMemoryFillPort`，不要把 `kMemoryWritePort` 改成地址/掩码可选。
4. 匹配条件必须同时覆盖状态簇、读侧、单点写侧、fill/reset 侧，不能只看 `concat + slice`。
5. 第一版只做最明确、最安全的 case，优先在 `frontend.inner_bpu$tage.tables_1.usefulCtrs` 上验证。

这条路线既保留了 `grhsim` 当前“单点写只更新真正命中的元素”的优点，又能把读侧与 reset/fill 侧从海量离散状态中解放出来，是当前最合理的实现方向。
