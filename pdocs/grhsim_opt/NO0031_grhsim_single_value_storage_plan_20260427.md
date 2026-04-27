# NO0031 GrhSIM Single Value Storage Plan

> 归档编号：`NO0031`。目录顺序见 [`README.md`](./README.md)。

这份文档用于收敛一轮新的 `grhsim` value storage 方向：不再继续围绕“一个 value 一个成员变量”做 emitter 侧展开优化，而是回到“单一连续 value storage”的模型，同时明确 declared symbol、对齐、局部性和宽值处理的边界。

本文档只讨论 `logic value` 的布局策略：

- `real` / `string` 不纳入本轮主路径
- `state` / `state shadow` / `memory write shadow` 不在这轮一起改
- 目标是先把 `sched` 里最重的 materialized value 路径收敛

## 1. 背景

过去几轮 `grhsim-cpp` 优化，基本都建立在“把 materialized value 展开成独立成员变量”的前提上：

- 按 value 拆成员
- 按 schedule batch / word helper 切分
- 再对重复模式 batch 继续做 helper 粒度调整

目前已经得到比较稳定的结论：

- 运行时性能没有拿到稳定收益
- C++ 编译体量和优化难度显著上升
- `clang++ -O3` 的主要瓶颈已经转移到超大 `sched` 编译单元上的中端优化，而不是 emit 自身

因此，`value` 存储模型应回到“单一连续存储”，而不是继续维持“一个 value 一个成员变量”的展开方式。

## 2. 目标

新的 `value` 存储模型需要同时满足：

1. 不再为了 declared symbol 保留稳定字段名或对象成员。
2. 所有 materialized logic value 放进一个连续数组，而不是按位宽分桶成多个数组。
3. 小位宽 value 很多，但也存在 `>64` bit 的宽 value。
4. 兼顾运行时局部性、访存对齐和 emit 侧实现复杂度。
5. 让生成代码更接近“常量 offset 的数组访问”，而不是“数百万个不同的成员名”。

## 3. 宽度分布与现状

### 3.1 GrhSIM / XiangShan 的总体 logic width 分布

当前 XiangShan post-transform GRH 中，logic result 的总体分布已经统计过：

- 总 logic result：`5,119,863`
- `>64` bit：`42,461`，占比 `0.83%`

也就是说，宽值存在，但只占极薄尾部。

### 3.2 当前 GrhSIM materialized value 分布

当前生成头文件 [../../build/xs/grhsim/grhsim_emit/grhsim_SimTop.hpp](../../build/xs/grhsim/grhsim_emit/grhsim_SimTop.hpp) 中，materialized value 一共 `1,771,993` 个，按存储类型统计为：

- `std::uint8_t`：`1,544,146`
- `std::uint16_t`：`52,542`
- `std::uint32_t`：`17,786`
- `std::uint64_t`：`138,688`
- `std::array<std::uint64_t, N>` 宽值：`18,831`

对应宽值占比：

- materialized value 总数：`1,771,993`
- 宽值数：`18,831`
- 宽值占比：`1.06%`

这里最关键的观察不是“宽值多”，而是：

- materialized value 数量本身很大
- 且其中绝大多数其实是窄值

### 3.3 GSim 持久成员分布

对 [../../tmp/gsim_default_xiangshan/default-xiangshan/model/SimTop.h](../../tmp/gsim_default_xiangshan/default-xiangshan/model/SimTop.h) 做同口径统计后：

- 持久声明总数：`333,758`
- `>64` bit 声明数：`2,777`
- 宽值占比：`0.83%`

decl-level 宽度 bucket 为：

- `1`：`218,873`
- `2-8`：`77,233`
- `9-16`：`16,837`
- `17-32`：`8,113`
- `33-64`：`9,925`
- `>64`：`2,777`

这说明 `gsim` 和 `grhsim` 在“宽值只占薄尾”这件事上是对齐的。

### 3.4 GSim 的真正差异

`gsim` 和当前 `grhsim` 的核心差异不在“宽值比例”，而在“持久化 value 的数量级”：

- `grhsim` materialized value：`1,771,993`
- `gsim` 持久成员声明：`333,758`

前者约为后者的 `5.3x`。

同时，`gsim` 的 `.cpp` 中大量使用 `_BitInt(N)` 做局部宽运算，典型分布包括：

- `_BitInt(128)`：`28,132`
- `_BitInt(192)`：`4,176`
- `_BitInt(256)`：`3,335`
- `_BitInt(320)`：`1,062`
- `_BitInt(512)`：`349`

这说明 `gsim` 的风格更接近：

- 持久存储尽量保持窄 / 直接
- 宽计算在局部表达式中临时拉宽

这正好支持这轮 `grhsim` 回退方向：问题不在“要不要支持宽值”，而在“不该把海量中间 value 继续做成分散成员”。

## 4. 结论

推荐方案是：

- 使用一个统一的 `value_storage_`
- 底层类型采用 `std::array<std::byte, kValueStorageBytes>`
- 整个数组按 `8` 字节对齐
- 每个 value 按自身宽度选择 `4` 或 `8` 字节对齐
- 不按位宽建多个 slot array，也不保留 `value_u8_slots_ / value_u16_slots_ / value_words_N_slots_` 这类分桶结构

推荐的 per-value 布局规则如下：

| value 宽度 | 对齐 | 占用 |
| --- | ---: | ---: |
| `1..32` | `4` bytes | `4` bytes |
| `33..64` | `8` bytes | `8` bytes |
| `>64` | `8` bytes | `8 * ceil(width / 64)` bytes |

也就是说，新的模型不是“全部按 64-bit slot 放”，而是：

- 窄值统一落到 `u32 class`
- 中等宽度值落到 `u64 class`
- 宽值落到连续 `u64 words`

三者共享同一个 byte array，只是 offset / alignment 规则不同。

## 5. 为什么不选“全部 64-bit slot”

这条路最简单，但不是最优折中。

如果所有 logic value 都直接占一个 `uint64_t`：

- `1/2/3/4/5/6/7/8/9/16/32` bit value 都会被抬升到 `8` bytes
- 主流窄值的占用大约翻倍
- `value_storage_` footprint 会被显著拉大
- 更差的 cache density 会直接伤害运行时局部性

按当前 `grhsim` 头文件里的 materialized value 分布粗算：

- 若采用 `<=32 -> 4 bytes`、`33..64 -> 8 bytes`、`>64 -> words`，总 value storage 约 `8.54 MB`
- 若所有标量 value 都强行用 `64-bit slot`，约 `15.00 MB`

也就是说：

- `all-64` 相比 `4/8/words` 大约 `1.756x`

这部分膨胀换来的不是更好的优化，而更可能只是更大的 working set。

## 6. 为什么不选“按真实位宽极限打包”

另一端是把 `1 bit` 放 1 bit、`5 bit` 放 1 byte、`9 bit` 放 2 byte、`17 bit` 放 3 byte 之类的极致压缩。

这也不合适：

- emit 侧会引入大量 bit addressing / partial-byte 处理
- 访问表达式会复杂很多
- 宽值和窄值混排后的对齐更难保证
- 编译器更难把这些访问归约成简单 load/store

我们的目标不是做最小内存镜像，而是生成更稳定、更容易被编译器处理的仿真代码。

所以，“按真实位宽极限打包”太细。

## 7. 为什么推荐“32-bit floor + 64-bit word tail”

这个方案的平衡点最好：

- 对 `<=32` bit value：
  - 统一用 `4` bytes
  - 既避免了 `1/2 byte` 级别碎片，也避免了 `8 byte` 级别浪费
- 对 `33..64` bit value：
  - 统一用 `8` bytes
  - 可以直接作为 `u64` 标量访问
- 对 `>64` bit value：
  - 直接落成 `u64 words`
  - 与现有 wide helper 的自然粒度一致

这意味着运行时最常见的三种访问分别是：

- `u32` scalar load/store
- `u64` scalar load/store
- `u64*` word buffer load/store

访问种类少，代码形态稳定，而且全部可以由常量 offset 驱动。

## 8. 对齐约束

`4` 字节槽不会天然导致非对齐访存，前提是布局规则按“访问类型对齐”来做，而不是简单把不同 value 紧挨着堆放。

具体约束应是：

- `<=32` bit value：按 `std::uint32_t` 访问，`offset` 必须是 `4` 的倍数
- `33..64` bit value：按 `std::uint64_t` 访问，`offset` 必须是 `8` 的倍数
- `>64` bit value：按 `std::uint64_t[]` 访问，起始 `offset` 也必须是 `8` 的倍数
- 整个 `value_storage_` 本身 `alignas(std::uint64_t)`

混排时的逻辑应是：

```cpp
offset = alignTo(offset, 4); // 放 u32
offset += 4;

offset = alignTo(offset, 8); // 放 u64 或 words
offset += 8;
```

因此：

- `4` 字节槽本身不会导致非对齐 `u32` 访存
- `u32` 后面接 `u64` 时，中间只会插 padding，不会生成未对齐 `u64` 访问

## 9. Declared Symbol 策略

这里建议明确改掉过去的设计约束：

- 不再因为一个 value 对应 declared symbol，就默认把它当成“需要保名、保字段、保可见性”的对象
- 不再让 declared symbol 参与 value layout
- 不再让 declared symbol 决定 materialization 的保留边界

declared symbol 只保留两种用途：

1. 可选的 debug sidecar
2. 可选的 waveform/filter 输入

而且这两者都不应反向约束主存储布局。

更具体地说：

- 默认 emit 路径下，`valueRef(...)` 应直接变成“数组基址 + 常量 offset”
- 如果需要做调试映射，额外输出 sidecar 文件即可，例如：
  - `symbol -> offset`
  - `symbol -> width`
  - `symbol -> storage kind`

这样 debug 信息还在，但不会再污染热路径的 C++ 结构。

## 10. 存储顺序

不按 declared symbol 顺序，也不按位宽顺序。

推荐顺序是：

1. 先按 schedule hotness 排
2. 再按首次出现 batch 排
3. 再按触达次数排
4. 最后以 graph order 打平

这和当前 emitter 已经在做的 `batch-hot` 重排方向一致，但新的目标不是生成更漂亮的成员名，而是让：

- 同一个 batch 里频繁一起访问的 value 彼此更近
- 跨 batch 的冷 value 自然后移
- layout 由执行局部性决定，而不是由源级 symbol 名字决定

一旦回到数组存储，layout 次序本身就会成为主要局部性控制手段。

## 11. 建议的数据结构

核心存储建议如下：

```cpp
alignas(std::uint64_t) std::array<std::byte, kValueStorageBytes> value_storage_{};
```

每个 materialized logic value 只保留 metadata：

- `offset`
- `width`
- `isSigned`
- `storageClass`
  - `u32`
  - `u64`
  - `words`
- `wordCount`（仅 `words` 使用）

不再保留：

- 独立成员字段名
- declared symbol 驱动的 field name
- 宽度分桶后的数组字段名

## 12. 建议的访问接口

推荐 emit 成以下三类访问：

```cpp
grhsim_value_u32(value_storage_, kOffset)
grhsim_value_u64(value_storage_, kOffset)
grhsim_value_words(value_storage_, kOffset)
```

返回形式建议是：

- `u32`: `std::uint32_t &`
- `u64`: `std::uint64_t &`
- `words`: `std::uint64_t *`

这样有两个直接收益：

1. 标量值不再需要一堆 `bool/u8/u16/u32/u64` 类型分叉
2. 宽值可以自然改成 pointer + word-count 风格，减少 `std::array<N>` 模板膨胀

## 13. 宽值处理建议

宽值仍然放在同一个 `value_storage_` 里，但访问接口不要再强依赖 `std::array<std::uint64_t, N>`。

推荐宽值 helper 统一转成 buffer 风格：

```cpp
grhsim_add_words(lhsPtr, lhsWords, rhsPtr, rhsWords, width, outPtr, outWords);
grhsim_shl_words(srcPtr, srcWords, amount, width, outPtr, outWords);
grhsim_slice_words(srcPtr, srcWords, lsb, width, outPtr, outWords);
```

这样做有三点价值：

- 和单一 byte-array 存储天然匹配
- 消掉一部分 `std::array<N>` 模板实例
- 对重复 pattern 的超节点而言，IR 也会更规整

## 14. 与 typed slot array 方案的区别

这次方案和以前的 `value_u8_slots_ / value_u16_slots_ / value_words_N_slots_` 不是一回事。

typed slot array 的问题在于：

- 它虽然减少了独立字段，但仍然把 value 按类型拆散到了多个数组
- 相邻使用的 value 可能因为位宽不同而跑到不同数组
- layout 的主导因素变成“类型”，不是“访问局部性”

这次新方案强调的是：

- 一个 value storage
- 一个热度排序
- 一套 offset metadata

类型只影响单个 value 的对齐和占用，不决定它属于哪个池。

## 15. 实施建议

建议按下面顺序改，而不是一次性大改所有对象：

1. 先只改 materialized logic value
2. 保持 state / state shadow / memory write 现状不动
3. 让 `valueRef(...)` 先完成从“字段名”到“offset accessor”的切换
4. 再把宽值表达式从 `std::array<N>` 逐步切到 buffer helper
5. 最后再决定是否把 `real` / `string` 也继续收敛

这样风险最小，因为当前编译热点主要在 `sched` 的 value 逻辑，而不是 `state` 容器本身。

## 16. 最终建议

本轮 `grhsim` value 存储回退方案，建议采用：

- 单一 `value_storage_`
- 全局 `8` 字节对齐
- `<=32` bit value 使用 `4` 字节槽
- `33..64` bit value 使用 `8` 字节槽
- `>64` bit value 使用 `8` 字节对齐的 `u64 words`
- layout 完全按 batch-hot / graph-order 决定
- 默认路径不再刻意保留 declared symbol
- debug / waveform 需要的 symbol 信息转移到 sidecar 或显式选择逻辑

一句话概括：

不是回到“按类型分桶的 slot array”，也不是继续“一个 value 一个成员”，而是回到“一个数组”，但这个数组应当是面向局部性和编译器可处理性的变长布局。
