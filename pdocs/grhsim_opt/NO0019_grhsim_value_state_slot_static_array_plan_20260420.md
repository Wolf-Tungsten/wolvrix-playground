# NO0019 GrhSIM Value/State Slot Static-Array Plan

> 归档编号：`NO0019`。目录顺序见 [`README.md`](./README.md)。

这份计划用于约束一轮明确的 `grhsim` emitter 改造：让生成头文件中的 `value` / `state` slot 改为 `std::array` 固定大小存储，不再依赖 `std::vector` 的运行期分配。目标不是改变 `grhsim` 语义，而是把“slot 总量在 emit 时已知”的那部分 persistent storage 直接固化进生成类型里，去掉额外的堆分配与 `.assign(...)` 初始化。

## 1. 当前实现

当前 `grhsim` 头文件生成逻辑在 [`../../wolvrix/lib/emit/grhsim_cpp.cpp`](../../wolvrix/lib/emit/grhsim_cpp.cpp) 中把以下几类 slot 声明成 `std::vector`：

- `value_*_slots_`
- `state_logic_*_slots_`
- `state_mem_*_slots_`

对应初始化逻辑也依赖 `std::vector::assign(...)`：

- `value` slot 在 `kValues` init chunk 中统一 `.assign(...)`
- `state` slot 在 `kStateStorage` / `kStates` init chunk 中先分配，再按状态对象补初值

其中最需要注意的一点是：

- `value` slot 和 `register/latch state` slot 的“slot 数量”在 emit 结束时已经完全确定
- `memory state` 也是静态对象；只是当前 emitter 复用了“按元素类型 / wordCount 分桶”的共享布局，所以现在才写成 `std::vector<std::vector<T>>`

## 2. 目标与边界

本轮目标：

- 生成头文件中的 `value` slot 改为 `std::array`
- 生成头文件中的 `state` slot 改为 `std::array`
- `init()` 仍保留“重置到初始状态”的语义，但不再靠 `vector.assign(...)` 完成 slot 分配

本轮不追求：

- 改写 `waveform_handles_`、`deferred_system_task_texts_` 这类运行时可变容器
- 改变 `grhsim` 的调度、求值、波形或系统任务语义

边界说明：

- 这里的“编译时分配”指 slot 大小被编码进生成类型，例如 `std::array<T, N>`
- `GrhSIMModel` 在 XiangShan difftest 里仍然是 `new GrhSIMModel`，因此这些数组会作为对象内嵌成员跟随整个模型对象一次性分配，而不是落在线程栈上
- 这个改动的直接收益是去掉 slot 级别的额外堆分配，不是把整个模型从堆迁回栈
- `event_edge_slots_` 当前虽然也写成 `std::vector`，但 `eventEdgeSlotCount` 在 emit 时已固定，因此它本质上也可以静态化；这里只是先把范围收敛到用户明确点名的 `value/state slot`
- `state_shadow_*` / `memory_write_*` scratch slot 的计数同样在 emit 时固定，因此它们也可以静态化；它们和 `memory state` 的区别是：它们只需要“slot 数固定”，不需要表达“每个 memory 的 rowCount 可变”

## 3. 结构约束与关键判断

### 3.1 `value` / `register` / `latch` slot 可以直接静态化

这几类 slot 当前已经按固定桶计数：

- scalar value：按 `bool/u8/u16/u32/u64` 计数
- wide value：按 `wordCount` 计数
- scalar logic state：按 `bool/u8/u16/u32/u64` 计数
- wide logic state：按 `wordCount` 计数

因此它们可以直接从：

```cpp
std::vector<std::uint32_t> value_u32_slots_;
std::vector<std::array<std::uint64_t, 3>> state_logic_words_3_slots_;
```

改成：

```cpp
std::array<std::uint32_t, kValueU32SlotCount> value_u32_slots_{};
std::array<std::array<std::uint64_t, 3>, kStateLogicWords3SlotCount> state_logic_words_3_slots_{};
```

### 3.2 `memory state` 不能只做“vector -> array”字面替换

当前 memory bucket 只有“元素类型 / wordCount”两个维度：

- `state_mem_u8_slots_`
- `state_mem_words_3_slots_`

但同一个 bucket 内不同 memory 可能有不同 `rowCount`。因此下面这种直接替换是不可行的：

```cpp
std::array<std::array<std::uint8_t, ???>, slotCount> state_mem_u8_slots_;
```

因为 `???` 在同一个桶里不唯一。

所以 memory state 必须先重做分桶键，再谈 `std::array`。

### 3.3 `state_shadow_*` / `memory_write_*` 可以一起静态化

这两类 scratch slot 没有 `memory state` 的 rowCount 异构问题。

它们当前的计数分别来自：

- `stateShadowTouchedCount`
- `stateShadowScalarSlotCounts`
- `stateShadowWideSlotCountsByWords`
- `memoryWriteTouchedCount`
- `memoryWriteAddrCount`
- `memoryWriteDataScalarSlotCounts`
- `memoryWriteDataWideSlotCountsByWords`
- `memoryWriteMaskScalarSlotCounts`
- `memoryWriteMaskWideSlotCountsByWords`

这些值在 emit 阶段都已经确定，因此以下字段都可以改成 `std::array`：

- `state_shadow_touched_slots_`
- `state_shadow_*_slots_`
- `memory_write_touched_slots_`
- `memory_write_addr_slots_`
- `memory_write_data_*_slots_`
- `memory_write_mask_*_slots_`

也就是说，真正有结构障碍的是 `state_mem_*`，不是 `state_shadow_*` 或 `memory_write_*`。

## 4. 推荐方案

采用“每个 memory 一个独立成员变量”的静态数组方案，不再尝试让多个 memory 共享同一个 bucket 字段。

原因：

- 这是对现有 emitter 侵入最小的路线
- `stateRef(state)` 仍可以保持“返回一个可直接 `[...]` 索引的状态对象”
- memory read / write / init 的大部分代码都能沿用现有表达式形态
- 风险明显低于“共享 bucket + row-aware key”或“单独维护大扁平数组 + offset/stride metadata”

### 4.1 memory state 直接按符号独立建字段

不再保留当前这种共享 bucket：

- `state_mem_u8_slots_`
- `state_mem_words_3_slots_`

改为每个 memory 一个固定成员，例如：

```cpp
std::array<std::uint8_t, 128> state_mem_idx_mem_{};
std::array<std::array<std::uint64_t, 3>, 64> state_mem_wide_mem_{};
```

这样 `stateRef(state)` 仍然可以返回：

```cpp
state_mem_idx_mem_
```

后续读写代码继续使用 `stateRef(state)[row]` 即可。

### 4.2 `StateDecl::cppType` 同步改成静态数组类型

当前 memory state 的 `cppType` 是：

```cpp
std::vector<T>
```

计划改为：

```cpp
std::array<T, rowCount>
```

wide memory 则是：

```cpp
std::array<std::array<std::uint64_t, wordCount>, rowCount>
```

这样以下逻辑都可以自然复用：

- `state.cppType.size()` 相关的代码生成字节估算
- scalar write 路径里基于 `state.cppType` 的 `static_cast`
- 各类 `const auto state_shadow_base = ...` 的现有表达式结构

### 4.3 这条路线下不再需要 memory bucket key 重构

因为每个 memory 自己持有一个字段，所以不需要再引入：

- `MemoryScalarSlotKey { kind, rowCount }`
- `MemoryWideSlotKey { wordCount, rowCount }`

memory state 的关键工作变成：

- 为每个 memory 生成稳定字段名
- `stateRef(state)` 直接返回这个字段名
- 初始化时直接对该字段做零值重置和初值回填

## 5. 分步实施计划

### Step 1. 收敛数据模型与命名 helper

先把 state storage 拆成两类处理：

- `register/latch/value/shadow/write/event-edge` 继续走“按 slot count 聚合字段”
- `memory state` 改成“按 symbol 独立字段”

同时补对应 helper：

- 为每个 memory 生成稳定字段名，比如 `state_mem_<sanitized_symbol>_`
- `StateDecl` 对 memory 记录自己的字段名
- `stateRef(state)` 对 memory 直接返回该字段名

这一层完成后，应先保证 emitter 的内部模型能正确表达“memory-by-symbol field”。

### Step 2. 先改 `value` / `register` / `latch` slot

先处理最简单、收益最直接的部分：

- `valueScalarSlotCounts`
- `valueWideSlotCountsByWords`
- `valueRealSlotCount`
- `valueStringSlotCount`
- `stateLogicScalarSlotCounts`
- `stateLogicWideSlotCountsByWords`
- `stateShadowTouchedCount`
- `stateShadowScalarSlotCounts`
- `stateShadowWideSlotCountsByWords`
- `memoryWriteTouchedCount`
- `memoryWriteAddrCount`
- `memoryWriteDataScalarSlotCounts`
- `memoryWriteDataWideSlotCountsByWords`
- `memoryWriteMaskScalarSlotCounts`
- `memoryWriteMaskWideSlotCountsByWords`

具体改动：

- 头文件字段改成 `std::array`
- `kValues` / `kStateStorage` init chunk 不再 `.assign(...)`
- `kStateShadows` / `kWrites` init chunk 不再 `.assign(...)`
- 保留显式 reset，但改成 `field = {};`

这一阶段不碰 `memory state`，但应把所有“计数已固定的 slot storage”一次性去 `vector` 化做通。

### Step 3. 改 memory state 声明与初始化

再处理 `state_mem_*`：

- `StateDecl` 建模时记录每个 memory 的独立字段名
- 头文件按 memory 输出 `std::array<...>`
- `state.cppType` 改成静态数组类型

同时把 `kStateStorage` / `kStates` 的初始化改掉：

- 不再为 memory state 先 `.assign(rowCount, ...)`
- 改成对整个静态数组做零值重置，然后再按 `initValue` / `readmemh` 补具体行

### Step 4. 保持 `init()` reset 语义不变

即使字段已经写成：

```cpp
std::array<..., N> slots_{};
```

也不要只依赖构造时的默认初始化。`init()` 仍然要把模型恢复到干净初值。

因此需要把当前所有和 slot reset 相关的 `.assign(...)` 改成等价的静态数组 reset：

- `field = {};`
- 对 memory state 按行覆写初值

这一步的目的不是“再分配”，而是“复位”。

### Step 5. 更新 emitter 单测

`wolvrix/tests/emit/test_emit_grhsim_cpp.cpp` 需要同步更新，至少覆盖：

- 头文件中 `value_*_slots_` 不再出现 `std::vector`
- 头文件中 `state_logic_*_slots_` 不再出现 `std::vector`
- 头文件中 memory state 不再出现 `std::vector<std::vector<...>>`
- 头文件中 `state_shadow_*` / `memory_write_*` 不再出现 `std::vector`
- state init 代码中不再出现对应 slot 的 `.assign(...)`
- memory state 直接以“每个 memory 一个成员变量”的形式出现，并且类型里带有 `rowCount`

建议新增两类断言：

- 正向断言：出现 `std::array<...>`
- 反向断言：对 `value/state` slot 声明文本不再出现 `std::vector<`

### Step 6. 做小模型与 XiangShan 两级验证

验证分两层：

1. emitter 单测 / 小模型生成验证
2. XiangShan `grhsim` emit + compile smoke

推荐顺序：

1. `ctest --test-dir wolvrix/build --output-on-failure -R emit_grhsim_cpp`
2. `make xs_wolf_grhsim_emit RUN_ID=<array-slot-smoke>`
3. 如编译链允许，再做一轮 `run_xs_wolf_grhsim_emu` bounded smoke

### 2026-04-20 实测结果

本轮实现完成后，实际验证按下面顺序执行：

1. `cmake --build wolvrix/build -j4 --target emit-grhsim-cpp`
2. `wolvrix/build/bin/emit-grhsim-cpp`
3. `make -j16 xs_wolf_grhsim_emu RUN_ID=20260420_codex_array_slots_reemit_50k_fix1`
4. `make -j16 run_xs_wolf_grhsim_emu RUN_ID=20260420_codex_array_slots_reemit_50k_fix2_run XS_SIM_MAX_CYCLE=50000 XS_COMMIT_TRACE=0 XS_PROGRESS_EVERY_CYCLES=5000`

其中第 3 步重新 emit 后暴露过一次 codegen bug：压缩 scalar state write 在 supernode local inline 场景下错误引用了未物化的 `local_value_*`。修复后重新 emit/build 通过，第 4 步 50k 运行完整结束。

50k CoreMark 结果如下：

- 日志：`build/logs/xs/xs_wolf_grhsim_20260420_codex_array_slots_reemit_50k_fix2_run.log`
- 结束原因：`EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80001312`
- `instrCnt = 73580`
- `cycleCnt = 49996`
- `IPC = 1.471718`
- `Host time spent = 582354ms`
- 主口径 `cycles/s = Guest cycle spent / Host time spent = 50001 / 582.354s = 85.86 cycles/s`
- 若按最终摘要里的 `cycleCnt / Host time spent` 计算，则约为 `85.85 cycles/s`
- 若按最后一条 `EMU_PROGRESS` 的 `model_cycles / host_ms` 计算，则约为 `85.86 cycles/s`

从这轮实测看，这次优化的收益主要体现在“去掉固定 slot 的额外堆分配和 `assign(...)` 初始化路径”，而不是显著提升 XiangShan `grhsim` 的整体运行吞吐。至少在当前这组 50k CoreMark bounded run 上，`cycles/s` 仍然只有约 `85.86`，可以认为性能几乎没有提升。

这说明当前热点大概率不在这些 fixed slot container 的分配/复位成本上，后续若要继续追求 runtime 提升，应优先回到调度、求值、difftest 交互和日志/trace 开销上继续分析，而不是假设“把 `vector` 改成 `array`”本身会带来明显加速。

这说明本轮 `std::array` 静态化改造在 XiangShan `grhsim` 上已经至少满足：

- 重新 emit 成功
- C++ 编译成功
- bounded 50k 运行成功
- 未出现新的 emit 产物编译失败

## 6. 验收标准

完成后应满足以下结果：

- 生成头文件里的 `value` / `state` slot 声明不再使用 `std::vector`
- 生成头文件里的 `state_shadow_*` / `memory_write_*` scratch slot 声明不再使用 `std::vector`
- `value` / `state` slot 的 reset 路径不再使用 `.assign(...)`
- `state_shadow_*` / `memory_write_*` 的 reset 路径不再使用 `.assign(...)`
- memory state 仍保持现有按 `row` 读写与初始化语义
- `wolvrix/tests/emit/test_emit_grhsim_cpp.cpp` 通过
- XiangShan `grhsim` 至少能完成 emit 和 C++ 编译

建议额外记录两个观测值：

- 生成头文件中 `sizeof(GrhSIMModel)` 的数量级
- emit 后编译时间与峰值内存是否出现不可接受回退

因为这次改动的目标是“拿几十 MB 换掉 slot 级动态分配”，如果最终把编译器或链接器压垮，就需要再收敛策略。

## 7. 主要风险

### 风险 1：memory state 字段命名和引用改造不完整

既然每个 memory 都单独建字段，那么 `stateRef(state)`、memory read/write emit、memory init emit 必须全部切到新的字段来源；如果还有残留的 bucket helper，生成代码会直接错。

### 风险 2：测试只看声明，不看 reset 代码

如果只把头文件从 `vector` 改成 `array`，但 `init()` 里仍残留 `.assign(...)`，生成代码会直接编译失败。测试必须同时覆盖“声明 + 初始化”两部分。

### 风险 3：对象尺寸变大后出现隐藏拷贝

`std::array` 把真实数据放进对象本体后，任何无意的拷贝都会更昂贵。实现时应顺手检查生成类是否存在不必要的拷贝路径；如果有，建议显式禁用 copy。

### 风险 4：把“去 vector 化”误扩散到真正需要动态容量的运行时容器

波形句柄、系统任务缓冲这些容器的容量或生命周期特征和 value/state slot 不同，不应该在同一轮里混改。`event_edge_slots_` 不属于这一类；它是否一起静态化，取决于这轮改造是否要顺手覆盖固定大小的 event-edge scratch storage。

## 8. 建议的提交拆分

为了降低 review 和回归成本，建议拆成三段提交：

1. `refactor`: emitter 内部数据模型与 helper 重构，先为 row-aware memory bucket 铺路
2. `feat`: `value` / `state` slot 生成改成 `std::array`
3. `test`: 单测断言与 smoke 验证补齐

这样即使中途发现 XiangShan 编译体积或 compile-time 有明显副作用，也容易定位到底是“建模问题”还是“静态数组化本身”的问题。
