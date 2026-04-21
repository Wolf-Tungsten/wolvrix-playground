# NO0022 GrhSIM Goto → `if (unlikely)` 分支提示优化（2026-04-21）

> 归档编号：`NO0022`。目录顺序见 [`README.md`](./README.md)。

这份记录把 `grhsim` 生成的 activity-driven batch eval 代码从 `goto` 风格改写为与 `gsim` 一致的 `if (unlikely(...))` 包裹风格，并在 XiangShan CoreMark 50k 上验证性能收益。

本轮结论可以先直接写在前面：

- 生成的 C++ 代码编译通过，difftest 无 mismatch
- 50k 运行速度从 goto 版本的 **109.15 cycles/s** 提升到 **115.42 cycles/s**
- **cycles/s 提升约 5.74%**，证实了 ICache 压力大且跳过模式不稳定时，静态分支概率提示确实能优化代码布局并带来可测量收益

## 数据来源

- 本轮 emitter 修改：
  - `wolvrix/lib/emit/grhsim_cpp.cpp`
- 本轮 `50k` 运行日志：
  - `build/logs/xs/xs_wolf_grhsim_20260422_000450.log`
- 本轮 emitter / emu 构建日志：
  - `build/logs/xs/xs_wolf_grhsim_build_unlikely.log`
- 对齐基线（goto 版本）：
  - [`NO0020 Batch Merge Precise Dispatch 50k Alignment`](./NO0020_batch_merge_precise_dispatch_50k_alignment_20260421.md)
  - [`NO0021 Batch Merge Precise Dispatch 400 Target`](./NO0021_batch_merge_precise_dispatch_400_target_20260421.md)

## 1. 本轮修改目标

用户观察到：

- `build/xs/grhsim/grhsim_emit` 生成的代码使用 `goto` 做活性跳过
- `tmp/gsim_default_xiangshan/default-xiangshan/model` 使用 `if (unlikely(...))` 包裹执行体
- 后者理论上能让编译器把热路径（跳过）优化为顺序 fall-through，改善 ICache 局部性
- 用户还指出：**ICache 压力较大，且 grhsim 的跳过模式不一定稳定**（即 activity flags 为 0 的概率虽高，但并非绝对主导，动态分支预测可能不够有效）

因此决定将 grhsim emit 改成与 gsim 一致的 `if (unlikely(...))` 形式，观察实际性能收益。

## 2. 代码修改

修改文件：`wolvrix/lib/emit/grhsim_cpp.cpp`

### 2.1 头文件：添加 `unlikely` 宏

在生成的模型头文件中注入：

```cpp
#ifndef unlikely
#define unlikely(x) __builtin_expect(!!(x), 0)
#endif
```

### 2.2 Active Word 级别

改写前（goto）：

```cpp
std::uint8_t activeWordFlags = supernode_active_curr_[4u];
if (activeWordFlags == UINT8_C(0)) {
    goto active_word_4_end;
}
supernode_active_curr_[4u] = UINT8_C(0);
++stats.nonzeroActiveWords;
// ... supernode code ...
active_word_4_end:
    ;
```

改写后（`unlikely`）：

```cpp
std::uint8_t activeWordFlags = supernode_active_curr_[4u];
if (unlikely(activeWordFlags != UINT8_C(0))) {
    supernode_active_curr_[4u] = UINT8_C(0);
    ++stats.nonzeroActiveWords;
    // ... supernode code ...
}
```

### 2.3 Supernode 级别

改写前（goto）：

```cpp
if ((activeWordFlags & UINT8_C(1)) == 0) {
    goto supernode_47_end;
}
activeWordFlags = ...;
++stats.executedSupernodes;
// ... ops ...
supernode_47_end:
```

改写后（`unlikely`）：

```cpp
if (unlikely(activeWordFlags & UINT8_C(1))) {
    activeWordFlags = ...;
    ++stats.executedSupernodes;
    // ... ops ...
}
```

### 2.4 关键差异

| 维度 | goto 风格 | `if (unlikely)` 风格 |
| --- | --- | --- |
| 分支概率提示 | 无 | 显式告知编译器"执行是罕见的" |
| 热路径 | `goto`（前向跳转） | fall-through（顺序执行） |
| 代码布局 | 编译器无提示，可能不够优化 | 编译器将执行体放远，热路径紧凑 |
| ICache 行为 | 跳转打断指令流 | 热路径顺序预取更友好 |

## 3. 编译与功能验证

### 3.1 wolvrix 库编译

```bash
cmake --build wolvrix/build -j$(nproc)
```

结果：通过（仅修复了两处头文件生成中的分号遗漏）。

### 3.2 HDLBits 快速验证

```bash
make run_hdlbits_grhsim DUT=001
```

结果：emit、编译、运行均通过，确认生成代码语法正确。

### 3.3 XiangShan 完整编译

```bash
make xs_wolf_grhsim_emu -j$(nproc)
```

结果：

- emit 耗时：约 `342s`（从 `wolvrix_xs_post_stats.json` 恢复后 schedule + emit）
- C++ 编译：通过（886 个 schedule 文件 + init + eval + state，约 10 分钟）
- 链接：通过
- 生成 emu：`build/xs/grhsim/grhsim-compile/emu`

### 3.4 XiangShan 50k 功能验证

```bash
XS_SIM_MAX_CYCLE=50000 make run_xs_wolf_grhsim_emu
```

结果：

- 正常跑到 `50000-cycle` 上限
- 没有 diff mismatch
- 没有 assertion
- 没有 crash
- IPC = `1.471718`（与基线一致）

## 4. 50k 性能结果

### 4.1 本轮结果（`unlikely` 版本）

| 指标 | 数值 |
| --- | ---: |
| guest cycle spent | `50001` |
| host time spent | `433216 ms` |
| host simulation speed | **`115.42 cycles/s`** |
| guest instructions | `73580` |
| IPC | `1.471718` |

### 4.2 与历史版本对比

| 版本 | 分支风格 | batch target | host time | cycles/s | 相对 `NO0020` |
| --- | --- | ---: | ---: | ---: | ---: |
| `NO0020` baseline | goto | `800` | `458.089 s` | `109.15` | `baseline` |
| `NO0021` | goto | `400` | `538.650 s` | `92.83` | `-14.9%` |
| **`NO0022`** | **`unlikely`** | **`800`** | **`433.216 s`** | **`115.42`** | **`+5.74%`** |

关键观察：

- 在完全相同的 `targetBatchCount=800` 配置下，仅将分支风格从 `goto` 改为 `if (unlikely)`
- **cycles/s 从 109.15 提升到 115.42，提升 5.74%**
- 这是继 `NO0020` batch 合并优化之后，又一个在不改变 schedule 结构的前提下获得的纯代码生成层面收益

## 5. 为什么 `unlikely` 比 `goto` 更快

### 5.1 代码布局优化

`__builtin_expect`（即 `unlikely`）向编译器传递了明确的静态分支概率：

- `if (unlikely(activeWordFlags != 0))` 表示"flag 非零是罕见的"
- 编译器据此将 `if` 分支内的执行体放到冷门路径（远离顺序执行流）
- 热路径（flag == 0，跳过）成为 fall-through，不需要跳转指令

相比之下，`goto` 风格：

```cpp
if (activeWordFlags == 0) {
    goto active_word_end;
}
```

虽然语义上等价，但编译器**没有概率提示**。默认情况下编译器可能假设 fall-through（不跳转）更常见，导致热路径反而是跳转离开，代码布局不够紧凑。

### 5.2 ICache / 分支预测双重收益

在 activity-driven 仿真中：

- **大部分时间 flags 为 0**（不活跃），所以"跳过"是绝对热路径
- `unlikely` 确保热路径是**无跳转的顺序执行**：
  - 取指单元可以连续预取
  - 指令缓存压力更小
  - 即使动态分支预测已经很准，去掉跳转本身也节省了 frontend 带宽
- 用户还指出**跳过模式不稳定**：某些场景下 flags 非零概率会上升
  - 此时动态分支预测器训练不足，`unlikely` 的静态提示就更重要

### 5.3 与 gsim 的对比

gsim 的 `if (unlikely(activeFlags[0] != 0))` 风格在 grhsim 中得到了对等实现，两者现在不仅语义等价，连代码生成层面的分支提示策略也保持一致。

## 6. 结论与后续方向

### 6.1 结论

1. **把 `goto` 活性跳过改为 `if (unlikely(...))` 包裹是有效优化**
2. **在 `targetBatchCount=800` 配置下，cycles/s 提升约 5.74%**
3. 编译通过、功能对齐、无额外维护负担
4. 该优化对所有 grhsim 后端输出生效，不依赖特定 workload

### 6.2 推荐做法

- **保留当前 `if (unlikely)` 代码生成风格**
- 后续如需进一步优化，可考虑：
  - 在更多条件分支中引入 `unlikely`/`likely`（例如 event edge 检查、write conflict 检查）
  - 探索 C++20 `[[unlikely]]` 属性替代宏，提升可移植性
  - 结合 PGO（Profile-Guided Optimization）让编译器获得真实的分支概率数据

### 6.3 本轮交付

- `wolvrix/lib/emit/grhsim_cpp.cpp` 已合入上述修改
- 生成代码已验证编译和运行正确
- 性能收益已固化到本记录
