# NO0025 GrhSIM Packed Value Storage Plan

> 归档编号：`NO0025`。目录顺序见 [`README.md`](./README.md)。

这份计划用于约束一轮面向 `grhsim` 运行时性能的 emitter 优化：把当前按类型/宽度分桶展开成多个成员数组的 `value` storage，收敛成一套由 emitter 在生成期静态确定布局的 packed storage。目标是同时吸收两类诉求：

- 保留你提出的“连续地址空间 + offset 访问 + 提升局部性”的核心方向
- 避免把生成代码退化成大量宏、裸 `reinterpret_cast` 和难以维护的伪反射层

本文档明确限定优化范围：

- 只讨论 `grhsim-cpp` 生成运行时中的 `value` storage
- 不改 `wolvrix` IR / `GRH` 本体的数据结构
- 不改变 `grhsim` 的功能语义、调度语义和波形可观察行为

## 1. 背景

当前 `grhsim` 的 `value` storage 生成逻辑已经具备两个特征：

- `value` 在 emitter 中会按 `bool/u8/u16/u32/u64`、`wordCount`、`real`、`string` 等类别做 slot 分配
- 生成类中会把这些 slot 展开成很多独立成员数组，例如 `value_u32_slots_`、`value_words_3_slots_`、`value_real_slots_`

对应代码主要位于：

- [`../../wolvrix/lib/emit/grhsim_cpp.cpp`](../../wolvrix/lib/emit/grhsim_cpp.cpp)

其中：

- slot 引用表达式由 `logicSlotRefExpr(...)` 等 helper 拼接，当前模式是“桶名 + 下标”
- slot 分配时，`model.valueScalarSlotCounts` / `model.valueWideSlotCountsByWords` 等计数已经在 emit 阶段完全确定
- 生成头文件中最终会出现多组 `value_*_slots_` 成员数组

这带来三个现实问题：

1. 头文件成员过多，编译器前端负担偏重
2. 同一 supernode 热点路径访问的 `value` 可能分散在不同数组中，不利于局部性
3. emitter 当前更像“按存储类型优先布局”，而不是“按运行时访问时序优先布局”

## 2. 目标与非目标

### 2.1 目标

- 把逻辑 value storage 收敛到更少的底层存储对象，优先收敛成单一 packed arena
- 让每个可持久化 `value` 在 emitter 结束时拥有稳定的静态布局描述
- 让生成代码中的取值/写值表达式变成“layout metadata + typed accessor”
- 让布局顺序优先贴近 `grhsim` 的真实执行热点，而不是仅按类型分桶
- 降低生成头文件中的成员数量

### 2.2 非目标

- 不在这一轮把 `std::string` value 混入裸字节 arena
- 不改 `state storage`、`state_shadow_*`、`memory_write_*` 的布局策略，除非后续单独立项
- 不为了 arena 化而改 `ValueId.index`、`OperationId.index` 的语义
- 不引入“宏驱动的静态反射框架”

## 3. 当前实现判断

### 3.1 现有实现已经接近“静态布局”

虽然当前生成结果看起来是“多个数组成员”，但本质上很多信息已经是静态确定的：

- 每个 `value` 的存储类别在 emit 时已知
- 每个类别内的 slot 下标在 emit 时已知
- 访问表达式也不是运行时查表，而是生成期直接拼成字段引用

因此，这轮优化不是从零发明新机制，而是把“多桶静态布局”进一步收敛为“统一 packed 静态布局”。

### 3.2 直接使用宏 + 裸指针强转不是推荐路径

如果简单把当前模式改成：

```cpp
#define VALUE_AT(type, base, off) (*reinterpret_cast<type*>((base) + (off)))
```

再在生成代码里大量展开，会有几个问题：

- 对齐约束容易失控
- 对象生命周期不清晰，容易踩 UB
- 读代码时很难区分“layout metadata”与“真实值访问”
- 编译器未必比显式 `inline accessor` 更容易优化
- 一旦后续要在 layout 中插入新字段，宏形式很难做结构化演进

所以你的“地址 + 偏移 + 类型转换”思路可以保留，但要收敛到更稳的工程形态。

## 4. 推荐设计

推荐采用：

- `packed storage arena`
- `constexpr layout metadata`
- `inline typed accessor`

而不是：

- `大量分散成员数组`
- 或 `宏 + 裸指针强转`

### 4.1 底层存储对象

推荐在生成类中把 `value` storage 收敛为一组非常有限的底层对象：

- `alignas(kPackedValueAlign) std::array<std::byte, kPackedValueBytes> value_storage_{};`
- `std::array<double, kValueRealSlotCount> value_real_slots_{};`
- `std::array<std::string, kValueStringSlotCount> value_string_slots_{};`

其中：

- `Logic` 类 value 进入 `value_storage_`
- `Real` 和 `String` 暂时继续独立存储

这样既保留“连续地址空间”的目标，也避免把非平凡类型硬塞进字节 arena。

### 4.2 layout metadata

对每个进入 packed arena 的 value，在 emitter 中生成一条静态布局描述：

```cpp
struct PackedValueLayout {
    std::uint32_t offset = 0;
    std::uint16_t byteSize = 0;
    std::uint8_t scalarKind = 0;
    std::uint8_t wordCount = 0;
    bool isWide = false;
};
```

实际生成时不一定需要完整保留这组字段，可以按代码生成便利性裁剪；但语义上至少需要：

- `offset`
- `isWide`
- `scalar kind` 或 `wordCount`

### 4.3 accessor 形式

不建议用宏，建议 emitter 生成一组 `inline` helper，例如：

```cpp
inline std::uint32_t &value_u32_ref(std::size_t offset_words);
inline std::array<std::uint64_t, 3> &value_words_3_ref(std::size_t offset_bytes);
```

或者进一步统一成模板/重载：

```cpp
template <typename T>
inline T &packed_ref(std::size_t byteOffset);
```

wide logic value 则用专门 helper，避免在生成代码里出现复杂 cast。

### 4.4 访问表达式

当前 `model.valueFieldByValue` 保存的是一段字符串字段表达式。新模型下可以继续保留这一层抽象，但输出变成 accessor 调用，例如：

- 旧：`value_u32_slots_[17]`
- 新：`value_u32_ref(68)`

或：

- 旧：`value_words_3_slots_[5]`
- 新：`value_words_3_ref(120)`

这样 emitter 大部分现有代码仍然可以沿用“拿到一个 value 表达式字符串继续拼接”的工作流，不必全局重写。

## 5. 布局策略

### 5.1 不采用“纯类型桶优先”布局

如果 arena 内仍然完全按类型桶拼接：

- 先所有 `bool`
- 再所有 `u8`
- 再所有 `u16`
- 再所有 `u32`
- 再所有 `u64`
- 再所有 `words_N`

那么它虽然解决了头文件膨胀，但对热点局部性的改善会有限，因为一次 supernode 执行中相邻使用的 value 仍可能分散很远。

### 5.2 推荐“执行顺序优先、类型约束次之”的布局

推荐的布局主序不是 IR topo，而是更贴近 `grhsim` 的实际运行顺序：

1. 先按 `compute/commit` phase 划开
2. 在 phase 内按 supernode topo / batch 顺序扫描
3. 在同一热点窗口内，优先把共同出现的 persistent/local values 靠近放置
4. 在需要满足对齐和访问 helper 简化时，再按 scalar/wide 分小段

换句话说，布局目标应是：

- 让“会在同一批 `eval_batch_*` 中连续访问的值”尽量靠近

而不是：

- 让“相同 C++ 类型的值”绝对聚在一起

### 5.3 建议的分层布局

为了兼顾可维护性和局部性，建议本轮采用三层分区：

1. `compute local/persistent logic values`
2. `commit phase hot logic values`
3. `cold logic values`

其中：

- 第一层优先按 compute-phase supernode/batch 顺序布局
- 第二层优先按 commit-phase sink supernode 顺序布局
- 第三层收纳调试、波形、低频路径仍需保留的 logic value

如果第一轮实现希望更稳，可以先只做：

- `all persistent logic values` packed
- `local cheap scalar values` 暂不纳入

后续再继续扩展。

## 6. 与你原始思路的融合结论

你的原始方案里最有价值的部分有三点：

- 让 value 在更连续的地址空间中排列
- 访问路径收敛成 `base + offset + typed access`
- 明确把局部性当成首要目标，而不是只看“字段更优雅”

我建议保留这三点，但做如下约束：

- `base + offset + cast` 不直接暴露为全局宏，而是封装进 emitter 生成的 accessor
- 连续布局不直接绑定到“单纯 topo 序”，而是绑定到“grhsim 的 phase/batch 执行热点”
- 不把 `real/string` 强行塞进同一个 arena
- 不改 `ValueId` 编号语义，只新增 packed layout 元数据

这就是本计划的融合版结论：

> 用“生成期静态布局的 packed runtime storage”实现你想要的连续地址空间访问，但通过 `constexpr metadata + inline accessor` 控制风险和可维护性。

## 7. 实施步骤

### Step 1. 收敛 emitter 数据模型

在 `EmitModel` 中新增 packed 布局相关建模，至少包括：

- 每个 logic value 是否进入 packed arena
- packed arena 内的 `offset`
- 对应访问类别：`bool/u8/u16/u32/u64/words_N`
- 可选：所属热区/phase/batch

这一阶段不改代码生成，只把模型表达能力补齐。

### Step 2. 先做“类型安全 accessor + metadata”

先把当前分桶成员数组访问抽象成 accessor 风格，即使底层还是多数组也没关系。

目标是先完成这一步重构：

- emitter 不再直接散落拼接 `value_u32_slots_[i]`
- 统一通过 helper 生成 value ref 表达式

这样后续把底层从“多数组”切到“单 arena”时，只需要改 helper 输出，不必重写全局 emit 逻辑。

### Step 3. 引入 packed logic arena

把 logic value storage 真正改成：

- 单 arena
- 少量 accessor
- 少量 `constexpr` layout 常量

并保持：

- `real/string` 继续独立
- 当前外部接口和生成类行为不变

### Step 4. 引入热点优先布局

初版 arena 跑通后，再把当前“按桶编号分配”切到“按 phase/supernode/batch 热点分配”。

建议先以这组近似规则实现：

- 先遍历 `compute` supernode
- 再遍历 `commit` supernode
- 遇到首次需要持久化/命名的 logic value 时分配 packed offset
- 未被热点遍历覆盖但仍需要存储的 value 放到尾部 cold 区

### Step 5. 做对齐与零初始化收口

这一阶段需要把以下事项明确化：

- arena 总对齐
- 各 value 的 offset 对齐
- `init()` 中如何统一清零 packed logic arena
- 宽值的默认零值和当前 helper 语义保持一致

## 8. 风险与约束

### 8.1 对齐与 UB 风险

这是本方案最大的实现风险。

必须满足：

- arena 基址满足最大需要对齐
- 每个 value 的 `offset` 满足其访问类型对齐
- accessor 的类型转换只作用于已正确构造/可平凡存取的对象

本轮只把 trivially copyable 的 logic scalar / logic words 放入 arena，就是为了降低这部分风险。

### 8.2 调试可读性风险

当前生成类里的 `value_u32_slots_[17]` 可读性其实不错。换成 packed accessor 后，如果 helper 名字设计太差，调试体验会明显变坏。

因此要求：

- accessor 名字直接带类型语义
- 生成的 offset 尽量可读、稳定
- 必要时保留可选 debug 注释，标出 value symbol 和 packed offset

### 8.3 代码尺寸风险

如果为每个 `wordCount` 生成大量 accessor 模板实例，可能把代码尺寸问题从 header 成员数量转移到 helper 数量。

因此建议：

- scalar accessor 固定 5 类
- wide accessor 只对实际出现的 `wordCount` 生成
- 不为每个 value 单独生成 accessor

### 8.4 性能收益不一定自动出现

arena 化本身只提供潜在局部性收益，不保证一定快。

如果布局顺序不贴近真实热点，或者额外 helper 让编译器无法很好内联，收益可能有限甚至回退。所以本计划把“先 accessor 化，再 packed 化，再热点布局化”拆成独立步骤，便于逐轮验证。

## 9. 验证计划

每一阶段都需要做两类验证。

### 9.1 语义验证

- 重新 emit 并构建 `grhsim`
- 在 XiangShan `coremark` 上做 smoke run
- 对齐当前功能结果、波形关键输出和 `finish/stop/fatal` 行为

### 9.2 性能验证

至少沿用当前 `grhsim_opt` 目录已有口径，记录：

- fresh `emit -> build -> run`
- `50k cycle` 基准速度
- 需要时补 `30k smoke`
- 与最近稳定基线的相对变化

如果 packed arena 引入后：

- 编译时间显著下降
- 运行速度不回退

则说明第一阶段成功；如果运行速度有提升，再继续推进热点布局阶段。

## 10. 验收标准

本计划完成后，应满足：

- 生成类中的 logic value storage 不再展开成大量 `value_*_slots_` 独立成员数组
- `Logic` value 访问统一走 packed storage accessor
- `real/string` value 仍保持功能正确且不进入裸字节 arena
- emitter 内部不再直接散落拼接桶字段名，而是统一经由 value-ref helper
- XiangShan `grhsim` fresh rebuild 与 `50k` 运行结果功能正确
- 性能相对当前稳定基线不回退，或在文档中明确记录回退原因与下一步修正方向

## 11. 推荐落地顺序

如果只选一条最低风险路径，我建议按下面顺序推进：

1. 先把 `value` 引用收口到统一 helper
2. 再把 logic value 底层切到 packed arena
3. 最后再做按 phase/supernode/batch 的热点布局

原因很简单：

- 第一步主要是重构 emitter 组织形式，风险最低
- 第二步才真正改变底层存储
- 第三步才是性能导向的 aggressive 布局优化

这样即使中途需要止损，也能保留一套更干净的 emitter 抽象层，不会把代码推回到“字段字符串到处拼”的状态。

## 12. 扩展增补: 2026-04-23 最近一次性能结果

本节补充记录在“去掉运行期热路径日志、关闭 `grhsim` emitter 中 perf/activity-profile 生成与分支”之后，最近一次已经完整跑完的 XiangShan `grhsim` `coremark 50k` 结果。

### 12.1 本次测量口径

- fresh `emit -> build -> run`
- workload: `coremark-2-iteration.bin`
- run 参数: `XS_SIM_MAX_CYCLE=50000 XS_COMMIT_TRACE=0 XS_PROGRESS_EVERY_CYCLES=5000 WOLVRIX_GRHSIM_WAVEFORM=0`
- 说明: 这是最近一次完整跑完的结果；其中 `XS_PROGRESS_EVERY_CYCLES=5000` 仍会保留周期进度打印，因此这份数据应视为“最近可复现结果”，不是彻底去掉所有运行日志后的最终极限值

### 12.2 结果

- `Guest cycle spent = 50001`
- `Host time spent = 376628ms`
- `IPC = 1.471718`
- 折算速度: `132.759646 cycles/s`

### 12.3 与上一份基线对比

上一份基线:

- `Host time spent = 380942ms`
- `cycles/s = 131.256202`

本次相对基线:

- `Host time` 减少 `4314ms`
- 相对提升约 `1.132%`
- `cycles/s` 从 `131.256202` 提升到 `132.759646`

### 12.4 当前结论

- `DIFFTEST_STATE`
- `COMMIT_TRACE`
- `STORE_CHK`
- `STORE_REC`

上述几类热路径 spam 已从这次完成运行的 log 中消失。

当前能确认的是：

- 去掉这批运行期日志与 perf 相关分支后，`50k` 最近一次完整结果没有回退
- 在当前测量口径下，存在约 `1.13%` 的正向提升
- 后续如果要记录“纯净无进度日志”的最终口径，应再补一份 `XS_PROGRESS_EVERY_CYCLES=0` 的对照结果

### 12.5 2026-04-24 无 clean / 从 JSON 恢复口径

本节补充记录一次按你当前要求执行的 XiangShan `grhsim` 测量：

- 不执行 `clean`
- `emit` 阶段直接从已有 `build/xs/grhsim/wolvrix_xs_post_stats.json` 恢复
- 然后重新 `build emu`
- 最后运行 `coremark 50k`

本次 `emit` 确认走的是：

- `WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=1`
- `read_json_file start /workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/grhsim/wolvrix_xs_post_stats.json`

### 12.6 本次命令口径

- `make --no-print-directory xs_wolf_grhsim_emu RUN_ID=20260424_jsonresume_coremark50k WOLVRIX_GRHSIM_WAVEFORM=0`
- `make --no-print-directory run_xs_wolf_grhsim_emu RUN_ID=20260424_jsonresume_coremark50k XS_SIM_MAX_CYCLE=50000 XS_COMMIT_TRACE=0 XS_PROGRESS_EVERY_CYCLES=0 WOLVRIX_GRHSIM_WAVEFORM=0`

补充说明：

- 外层 `XS_PROGRESS_EVERY_CYCLES=0` 已关闭
- 运行期仍会看到 emu 内部的 `[CYCLE_LIMIT]` 里程碑打印，这是 XiangShan 运行器自身输出，不是此前那批 `grhsim` 热路径日志

### 12.7 本次结果

- `Guest cycle spent = 50001`
- `Host time spent = 386801ms`
- `IPC = 1.471718`
- 折算速度: `129.268022 cycles/s`

### 12.8 与 12.2 最近一次完整结果对比

12.2 的最近一次完整结果为：

- `Host time spent = 376628ms`
- `cycles/s = 132.759646`

本次相对 12.2：

- `Host time` 增加 `10173ms`
- `cycles/s` 从 `132.759646` 下降到 `129.268022`
- 相对变化约 `-2.63%`

### 12.9 备注

- 这次口径的重点是验证“无 clean、从已有 JSON 恢复、重新 build emu、直接跑 50k”这一链路是通的
- 从结果看，链路本身没有功能性问题，`IPC` 与 `Guest cycle spent` 仍稳定
- 但在当前这次实测中，纯 `XS_PROGRESS_EVERY_CYCLES=0` 口径并没有比 12.2 更快，反而慢了约 `2.63%`
- 因而后续评估 packed value arena 的收益时，应继续以多次重复跑或固定机器负载后的平均值为准，避免把单次波动误判为结构性提升或回退
