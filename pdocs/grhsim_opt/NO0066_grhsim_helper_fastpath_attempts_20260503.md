# NO0066 GrhSIM Helper Fast Path 尝试记录（当前无效或收益不足）

> 归档编号：NO0066。目录顺序见 [README.md](./README.md)。

本文记录 2026-05-03 这轮围绕 grhsim emitted helper 的三类 fast path 尝试，重点固化已经完成实现、通过 emitter 验证、并做过 XiangShan coremark 50k 复测的结果。

结论先行：

- 这轮 helper 级优化目前不能视为有效优化主线。
- 前两类尝试在当前代码状态下造成回退。
- 第三类尝试能回收一部分回退，但总体仍慢于现有更优基线。
- 后续若继续做 helper 级优化，不能再把“把 helper 本体写得更短”当作充分条件，而要优先用整机热路径数据确认真实瓶颈。

## 1. 目的

本轮工作的原始目标是针对先前静态 helper 对比里最可疑的几类模式做小范围 emitter/runtime 优化，并回答两个问题：

1. 这些 helper fast path 在 XiangShan coremark 50k 上是否能稳定保持功能正确。
2. 它们是否能带来可见的整机运行速度收益。

本轮尝试不涉及新的 transform pass，也不改变 activity-schedule 或 merge-reg 策略；只改 grhsim C++ emitter/runtime 的 helper 发射与 helper 实现。

## 2. 口径与基线

### 2.1 统一复测口径

所有性能结果统一使用：

- XiangShan `grhsim`
- `coremark-2-iteration.bin`
- `XS_SIM_MAX_CYCLE=50000`
- 直接读取 `emu` 日志中的 `Host time spent`

复测命令口径：

```bash
make run_xs_wolf_grhsim_emu RUN_ID=<id> XS_SIM_MAX_CYCLE=50000 XS_WAVEFORM=0 XS_WAVEFORM_FULL=0 XS_COMMIT_TRACE=0 XS_LOG_BEGIN=0 XS_LOG_END=0
```

### 2.2 参考日志

本轮对照时主要使用以下已存在日志：

- 当前两策略版本的参考快照：
  - [NO0065](./NO0065_xs_grhsim_two_strategy_coremark_50k_20260503.md)
  - 对应运行日志：`build/logs/xs/xs_wolf_grhsim_20260503_110204.log`
- 近期较优日志：
  - `build/logs/xs/xs_wolf_grhsim_direct_dispatch_50k_20260503.log`
  - `build/logs/xs/xs_wolf_grhsim_remove_batch_stats_50k_20260503.log`

### 2.3 参考数值

| 名称 | Host time spent | 备注 |
| --- | ---: | --- |
| `NO0065 / general_20260503_110204` | `379910 ms` | 当前两策略版本的 50k 参考快照 |
| `direct_dispatch_50k_20260503` | `377754 ms` | 近期更优的旧日志 |
| `remove_batch_stats_50k_20260503` | `371964 ms` | 近期最优旧日志之一 |

## 3. 尝试一：标量 concat / 1-bit dynamic slice / masked write 原地化

### 3.1 改动内容

第一轮实现包含三部分：

1. 标量 concat 直出表达式。
   - 不再把 `<=64 bit` 的 scalar concat 优先发射成 `grhsim_pack_bits_u64` 或 `grhsim_concat_uniform_scalars_u64`。
   - 改为直接生成按位宽拼接表达式。
2. 1-bit dynamic slice fast path。
   - 对宽值到 `1 bit` 的 dynamic slice 直接发射为 `grhsim_get_bit_words + grhsim_index_words`。
3. 宽位 masked write 去掉 double-copy。
   - 原路径：`grhsim_merge_words_masked(...) + grhsim_assign_words(...)`
   - 新路径：`grhsim_apply_masked_words_inplace(...)`
   - 同时把 `grhsim_assign_words` 改为 `const& src + live words 原地比较/更新`

### 3.2 验证结果

emitter 测试通过：

- `emit-grhsim-cpp`
- `emit-grhsim-cpp-memory-fill`

重新 emit、重编 `emu` 后，运行日志：

- `build/logs/xs/xs_wolf_grhsim_scalar_fastpath_20260503_test.log`

运行尾部关键结果：

```text
Core-0 instrCnt = 22,484, cycleCnt = 49,996, IPC = 0.449716
Host time spent: 387,141ms
```

### 3.3 结论

这轮尝试在功能上成立，但性能上回退：

| 对比对象 | delta |
| --- | ---: |
| 相对 `379910 ms` | `+7231 ms` / `+1.90%` |
| 相对 `377754 ms` | `+9387 ms` / `+2.48%` |
| 相对 `371964 ms` | `+15177 ms` / `+4.08%` |

因此，第一轮组合优化不能视为有效结果。

## 4. 尝试二：宽值到标量的小宽度切片改为单 word helper

### 4.1 背景

在第一轮之后继续检查生成代码，发现大量热点并不是 `1-bit slice`，而是这种模式：

```cpp
grhsim_slice_words<1>(..., start, small_width)[0]
```

这类结果虽然落在单个 word 中，但 emitter 仍先构造 `std::array<std::uint64_t, 1>`，再取 `[0]`。因此第二轮引入新的 runtime helper：

```cpp
grhsim_slice_u64_words(...)
```

并把以下场景全部改成直接发射到该 helper：

- `SliceStatic`
- `SliceDynamic`
- `SliceArray`

前提是：

- 结果是标量
- 结果宽度 `<= 64`

### 4.2 emitter 覆盖确认

重新 emit 后统计：

```text
slice_u64_words_count=107328
slice_words_1_count=0
```

这说明“宽值到标量的小宽度切片”这一类发射已经整体切换到新 helper，不是只覆盖到少量样例。

从生成代码中也能直接看到替换，例如：

```cpp
static_cast<std::uint64_t>(grhsim_slice_u64_words((grhsim_value_slot_888856), static_cast<std::size_t>(320), 64))
static_cast<std::uint16_t>(grhsim_slice_u64_words((grhsim_value_slot_6504952), grhsim_value_slot_1137696, 128, 9))
```

### 4.3 验证结果

emitter 测试仍全部通过。

重新 emit、重编 `emu` 后，运行日志：

- `build/logs/xs/xs_wolf_grhsim_scalar_slice_u64_20260503_test.log`

运行尾部关键结果：

```text
Core-0 instrCnt = 22,484, cycleCnt = 49,996, IPC = 0.449716
Host time spent: 385,094ms
```

### 4.4 结论

第二轮相对第一轮有小幅恢复，但总体仍不够：

| 对比对象 | delta |
| --- | ---: |
| 相对上一轮 `387141 ms` | `-2047 ms` / `-0.53%` |
| 相对 `379910 ms` | `+5184 ms` / `+1.36%` |
| 相对 `377754 ms` | `+7340 ms` / `+1.94%` |
| 相对 `371964 ms` | `+13130 ms` / `+3.53%` |

也就是说：

- `grhsim_slice_u64_words` 的方向是对的，至少能把第一轮的部分回退收回来。
- 但它仍不足以把当前版本带回已有较优基线。
- 因此从整机角度看，这轮优化仍然只能归类为“收益不足”。

## 5. 当前对这三类 helper 优化的判断

### 5.1 已确认的问题

1. helper 本体更短，不等价于整机更快。
2. 宽位 masked write 的 `inplace` 改写在当前版本里没有体现出净收益，反而与其它变更组合后出现了整机回退。
3. scalar concat 和 1-bit dynamic slice 的 fast path 虽然能清掉一些显眼 helper 调用，但覆盖面不足以改变主要 runtime 热点。
4. 单 word slice fast path 的覆盖面已经很大，但收益仍只够回收局部回退，说明主瓶颈不再主要停留在这一层 helper 包装。

### 5.2 当前不能下的结论

以下结论目前都不能成立：

- “主要瓶颈就是 `grhsim_pack_bits_u64` / `grhsim_concat_uniform_scalars_u64`”
- “主要瓶颈就是 `grhsim_merge_words_masked + grhsim_assign_words` 双拷贝”
- “主要瓶颈就是 `grhsim_slice_words<1>[0]` 这个包装形态”

更准确的说法是：

- 它们都属于值得清理的局部低效点。
- 但在当前 XiangShan `grhsim` 整机 runtime 里，它们不是足以单独决定 50k host time 的主导瓶颈。

## 6. 当前代码状态说明

截至本文记录时，这些实现仍在工作树中，尚未被证明值得长期保留，也尚未被正式撤回。

因此本文的定位是：

- 先把已做尝试、测量口径和结果固化，避免重复试错。
- 后续如果要继续沿这条线推进，应先基于新的 perf/采样结果决定是否保留、拆分或回滚这些改动。

## 7. 对后续工作的约束

基于当前结果，后续建议遵循以下约束：

1. helper 级 emitter 优化必须先配整机热路径证据，再决定继续扩大投入。
2. 如果后续继续清理 helper 形态，应优先把改动拆成更小的 AB 实验，避免一次混合多种机制后难以归因。
3. 下一阶段更合理的方向，不是继续凭静态 helper 直觉猜热点，而是直接对当前 `emu` 做 perf / 采样，把剩余最重的 runtime 热点排出来。

## 8. 最终结论

截至 2026-05-03，这轮 helper fast path 尝试的结论如下：

- 尝试一：无效，产生回退。
- 尝试二：方向正确但收益不足，仍慢于现有更优基线。
- 因此，当前不应把这条 helper fast path 线视为已经验证成功的主优化路径。

后续若继续优化 `grhsim` runtime，helper 级改写应降为从属工作项，优先级低于对整机真实热点的再归因。