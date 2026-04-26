# NO0030 `sched_124` LLVM IR / `GVN` + `MemoryDependence` Root Cause 与优化计划

## 背景

在 `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_124.cpp` 的单文件构建实验中，即使已经启用 `PCH`，该文件仍然表现出显著异常的编译时长。

前置实验已经确认：

- 单独在快照目录构建 `grhsim_SimTop_sched_124.o`，`clang++` 可稳定复现长时间卡住。
- `gdb attach` 到正在运行的 `clang++` 后，栈顶不在前端，也不在目标码生成，而是在 LLVM 优化流水线内部。

## 实验设置

实验快照目录：

- `/home/gaoruihao/wksp/wolvrix-playground/tmp/grhsim_sched124_snapshot_20260424`

关键步骤：

1. 复制 `grhsim_SimTop_sched_124.cpp`、`grhsim_SimTop.hpp`、`grhsim_SimTop_runtime.hpp`、`Makefile`
2. 在该目录中直接用 `clang++` 构建 `grhsim_SimTop_sched_124.o`
3. 使用 `gdb` attach 到正在运行的 `clang++`
4. 额外导出 raw LLVM IR：
   - `clang++ -emit-llvm -S -Xclang -disable-llvm-passes`

生成产物：

- raw IR: `/home/gaoruihao/wksp/wolvrix-playground/tmp/grhsim_sched124_snapshot_20260424/grhsim_SimTop_sched_124.raw.ll`
- isolated function IR: `/home/gaoruihao/wksp/wolvrix-playground/tmp/grhsim_sched124_snapshot_20260424/eval_batch_124.raw.ll`

## 直接结论

`sched_124.cpp` 的主要编译瓶颈不在：

- 头文件解析
- `PCH` 生成
- 后端 instruction selection / register allocation

而在：

- `eval_batch_124` 对应的超大 LLVM IR
- `GVNPass`
- `MemoryDependenceResults`
- `TypeBasedAAResult::alias`

也就是：`GVN` 在做冗余消除时，对海量内存读写和别名关系反复查询，最终被 `MemoryDependence + AA` 打爆。

## `gdb` 栈观察

对运行中的 `clang++` attach 后，主线程调用链核心如下：

```text
llvm::TypeBasedAAResult::alias
llvm::AAResults::getModRefInfo
llvm::MemoryDependenceResults::getNonLocalPointerDepFromBB
llvm::GVNPass::processBlock
llvm::GVNPass::iterateOnFunction
llvm::GVNPass::runImpl
```

这说明当前卡点已经非常具体：

- 当前正在跑 `GVNPass`
- `GVN` 的热路径落在 `MemoryDependence`
- `MemoryDependence` 的热路径又落在 `TypeBasedAA::alias`

## raw IR 结构画像

目标函数签名：

```llvm
define dso_local { i64, i64 } @_ZN13GrhSIM_SimTop14eval_batch_124Ev(...)
```

对 isolated `eval_batch_124.raw.ll` 的结构统计如下：

- IR 行数：`148617`
- `alloca`：`4951`
- `load`：`21416`
- `store`：`13603`
- `call`：`17835`
- label / CFG 节点量级：`6599`
- `getelementptr`：`16276`
- `icmp`：`6661`
- `or`：`6913`
- `phi`：`975`
- `llvm.lifetime.start`：`4923`
- `llvm.lifetime.end`：`4923`
- `std::array<...>::operator[]` 调用：`6045`
- lambda / closure `clEv` 调用：`100`

这已经不是“函数有点大”，而是“单个函数内部存在极高密度的局部内存对象、局部生命周期、数组下标调用和闭包调用”。

## 最关键的两个发现

### 1. `eval_batch_124` raw IR 中仍然存在大量 lambda thunk

在 raw IR 中仍能看到如下符号：

- `@"_ZZN13GrhSIM_SimTop14eval_batch_124EvENK3$_0clEv"`
- `@"_ZZN13GrhSIM_SimTop14eval_batch_124EvENK4$_48clEv"`
- 以及同类 `$_N::clEv` 闭包函数

统计结果：

- lambda / closure 调用总数：`100`

这说明至少在 `sched_124.cpp` 对应路径中，生成代码里仍残留了一批 lambda 风格的中间包装。它们直接带来：

- 更多 `call`
- 更多临时对象
- 更多 memory effect 边界
- 更重的 `GVN + MemoryDependence` 成本

### 2. `std::array::operator[]` 调用和短命局部对象过多

raw IR 中存在大量这样的模式：

```llvm
alloca
llvm.lifetime.start
call @_ZNSt5arrayIhLm10722EEixEm
load / store
llvm.lifetime.end
```

统计结果：

- `std::array<...>::operator[]` 调用：`6045`
- `alloca`：`4951`
- `lifetime.start/end`：各 `4923`

这类模式的坏处是：

- 产生了大量局部地址对象
- 让 LLVM 必须保守处理更多内存访问关系
- `GVN` 在尝试证明两次 load/store 是否可合并时，要频繁落入 `MemoryDependence`
- `MemoryDependence` 再进一步落入 alias analysis

## 根因归纳

`sched_124.cpp` 的编译拖尾，本质上是以下几类因素叠加：

1. `eval_batch_124` 被 emit 成一个极大的单函数
2. 函数内部残留 lambda thunk / closure call
3. 大量 `std::array::operator[]` 形式的下标访问没有被提前降成更直接的地址表达式
4. 过多短命局部变量导致 `alloca + lifetime` 泛滥
5. 前面 loop simplify / full-unroll / SROA 进一步放大 IR 规模
6. 最终在 `GVNPass` 阶段被 `MemoryDependence + TBAA alias` 拖死

因此，这个问题不能简单理解成“文本太长”或“文件太大”，而是：

- emit 生成的 C++ 语义形态本身就会诱导出高成本 IR

## 优化计划

### 计划 A：彻底清理 `sched` 主路径中的 lambda / closure

目标：

- 对 `sched` 主路径，尤其是大 concat / wide words / sink payload 路径，不再生成 `$_N::clEv`

具体方向：

- 检查 `grhsim_cpp` 中仍会输出 `([&]() { ... }())` 的路径
- 对宽位拼接、切片、临时 words 转换路径，改成直接表达式或直接写目标
- 对仅为了生成局部 `std::array` 的包装逻辑，改为显式局部变量或直接展开赋值

预期收益：

- 降低 `call` 数量
- 降低 memory side effect 边界
- 减少 `GVN` / inliner / CGSCC 的工作量

### 计划 B：减少 `std::array::operator[]` 调用，改成更直接的地址访问

目标：

- 避免在热点 `eval_batch_xxx` 中反复走 `std::array::operator[]`

具体方向：

- 对固定成员数组访问，优先直接降成裸 `getelementptr` 等价的成员地址模式
- 对 `supernode_active_curr_` 等热点数组，避免每次都通过包装调用访问
- 对宽 value words 写入，尽量使用已经命名好的本地目标引用，而不是 repeated `ix()` call

预期收益：

- 降低 `call` 密度
- 减少 `MemoryDependence` 需要追踪的 memory access graph
- 给 `GVN` 更简单的别名关系

### 计划 C：减少短生命周期局部对象的生成

目标：

- 压低 `alloca` / `lifetime.start/end` 数量

具体方向：

- 能直接内联成 SSA 的标量表达式不要先 materialize 成局部
- 能直接写成员目标的宽位结果不要先形成独立临时 `std::array`
- 避免为短小局部包一层 closure object / aggregate temp

预期收益：

- 缩小 IR
- 降低 SROA 和后续 memory optimization 的输入复杂度

### 计划 D：控制单个 `eval_batch_xxx` 的“IR 复杂度”而不只看文本长度

目标：

- 未来切分批次时，不只看 `.cpp` 文件大小或源代码行数
- 要纳入更贴近 LLVM 成本的 emit 指标

建议新增估算指标：

- `operator[]` 调用数
- lambda thunk 数
- 宽位 helper / aggregate temp 数
- store/load 估计数
- 局部变量 / temporary words 数

## `only_982_983` 单特征剔除实验

为了避免继续在完整 `sched_124.cpp` 上盲猜，这一轮改用一个更聚焦的单文件病例：

- 基线文件：
  - `/home/gaoruihao/wksp/wolvrix-playground/tmp/grhsim_sched124_snapshot_20260424/grhsim_SimTop_sched_124_only_982_983.cpp`
- 它只保留 `eval_batch_124()` 中的 `active word 982` 和 `active word 983`
- 其他 word 全部剔除，`checkedFlagWords` 改成 `2u`

### 实验方法

控制变量方式如下：

- 每次只剔除一类 `grhsim` 语义特征
- 其他代码保持不变
- 所有版本都使用同一条命令直接编译，不经过 `make` 重新生成 `PCH`

统一编译命令：

```bash
clang++ -std=c++20 -O3 -I. -include-pch grhsim_SimTop.hpp.pch -c <variant>.cpp -o <variant>.o
```

时间统计方式：

- `/usr/bin/time -f 'elapsed_sec=%e user_sec=%U sys_sec=%S maxrss_kb=%M status=%x'`
- `timeout 180`

### 特征剔除方式

对应副本都放在：

- `/home/gaoruihao/wksp/wolvrix-playground/tmp/grhsim_sched124_snapshot_20260424`

本轮共做了 6 个单特征剔除版本：

1. `no_classify_edge`
   - 文件：
     - `grhsim_SimTop_sched_124_only_982_983_no_classify_edge.cpp`
   - 方式：
     - `#define grhsim_classify_edge(...) (grhsim_event_edge_kind::none)`
2. `no_trunc_u64`
   - 文件：
     - `grhsim_SimTop_sched_124_only_982_983_no_trunc_u64.cpp`
   - 方式：
     - `#define grhsim_trunc_u64(value, width) (static_cast<std::uint64_t>(value))`
3. `no_concat_cast`
   - 文件：
     - `grhsim_SimTop_sched_124_only_982_983_no_concat_cast.cpp`
   - 方式：
     - 将 `grhsim_cast_words` / `grhsim_concat_words` 重定向到返回零数组的 wrapper
4. `no_assign_words`
   - 文件：
     - `grhsim_SimTop_sched_124_only_982_983_no_assign_words.cpp`
   - 方式：
     - `#define grhsim_assign_words(...) false`
5. `no_reduce_xor`
   - 文件：
     - `grhsim_SimTop_sched_124_only_982_983_no_reduce_xor.cpp`
   - 方式：
     - `#define grhsim_reduce_xor_words(...) false`
6. `no_wide_assign`
   - 文件：
     - `grhsim_SimTop_sched_124_only_982_983_no_wide_assign.cpp`
   - 方式：
     - 仅对 `width >= 128` 的 `grhsim_assign_words` 返回 `false`
     - 小宽度 `assign_words` 仍走原实现

### 编译时间结果

基线：

- `grhsim_SimTop_sched_124_only_982_983.cpp`
- `elapsed_sec=110.71`

结果表：

| 版本 | 剔除特征 | elapsed_sec | 相对基线 |
| --- | --- | ---: | ---: |
| baseline | 无 | 110.71 | +0.00s |
| no_classify_edge | `grhsim_classify_edge` | 108.65 | -2.06s |
| no_trunc_u64 | `grhsim_trunc_u64` | 121.19 | +10.48s |
| no_concat_cast | `grhsim_concat_words` + `grhsim_cast_words` | 115.15 | +4.44s |
| no_assign_words | `grhsim_assign_words` | 113.79 | +3.08s |
| no_reduce_xor | `grhsim_reduce_xor_words` | 111.14 | +0.43s |
| no_wide_assign | 仅移除 `>=128-bit` `assign_words` | 109.81 | -0.90s |

### 初步结论

这组结果有一个很重要的信号：

- 在 `only_982_983` 这个聚焦病例里，单独剔除某一种 `grhsim` helper 语义，并没有带来决定性下降
- `classify_edge` 和“超宽 `assign_words`”去掉后只有轻微改善，分别约 `2.06s` 和 `0.90s`
- `reduce_xor_words` 几乎无影响
- 更反常的是：
  - 去掉 `trunc_u64`
  - 去掉 `concat/cast`
  - 去掉全部 `assign_words`
  反而让编译时间变慢了

因此，当前更稳的结论不是“某一个 helper 家族单点打爆 clang”，而是：

- `982` 和 `983` 放在一起时，整体表达式形态、控制流、宽位对象和 bit-level 逻辑共同形成了一个对 LLVM 非常不友好的组合
- 单独摘掉某一类 `grhsim` helper，不足以显著缓解这个坏路径
- 后续如果继续实验，更值得做的是：
  - 按区域/子结构剥离
  - 而不是继续按单个 helper 名称做更细颗粒度试验

### `982 -> 983` 跨 word 数据传递观察

针对“是否是 `word 982` 产出的数据被 `word 983` 长链消费”这个假设，又做了一轮更直接的检查：

- 先枚举 `word 982` 中所有写回的持久 `value_*` 成员
- 再在 `word 983` 范围内搜索这些名字是否被再次引用
- 结果是：`0` 个命中

也就是说，在这个 `only_982_983` 抽取病例里，没有看到显式的：

- `word 982` 写 `value_x`
- `word 983` 再读同一个 `value_x`

最接近“跨 word 传递”的，只是两边都在处理同一个 `dataStorage` 语义域，但它们承担的是不同子结构：

- `word 982` 主要是 `bankedData_1..7` 的 `ClockGate`、`rdata`、`io_r_resp_data_0` 聚合写回
  - 例如 `value_4821408_...bankedData_1_io_r_resp_data_0_` 的写回在 `grhsim_SimTop_sched_124_only_982_983.cpp:246-251`
  - `bankedData_1` 的四个 `ClockGate_Q` 写回在 `grhsim_SimTop_sched_124_only_982_983.cpp:379-427`
- `word 983` 的热点则主要落在 `DataSel` 的 `72/66/65-bit` 拼接与赋值，以及两个超宽写回
  - `DataSel` 的 concat/assign/reduce_xor 密集区在 `grhsim_SimTop_sched_124_only_982_983.cpp:1961-2135`
  - `320-bit` / `273-bit` 写回在 `grhsim_SimTop_sched_124_only_982_983.cpp:3087-3100`

因此，当前更像是：

- `982` 提供了大量规则、重复、位级的 `bankedData` 读路径
- `983` 又叠加了一团单独就很不友好的 `DataSel` / 宽位写回逻辑
- 两者放进同一个编译单元后，`GVN` 在整个函数级别一起处理，复杂度才被放大

而不是：

- `982` 和 `983` 之间存在一条很长、很具体的显式数据依赖链

### `983` 区域级剔除实验

在确认 `982 -> 983` 之间不存在显式持久值长链之后，又按区域对 `983` 本身做了一轮更直接的消融。

这次不再做全局 helper 宏替换，而是直接复制 `only_982_983` 基线文件，再把 `983` 中指定代码区段替换成“零化目标成员”的简单块，尽量只回答一个问题：

- 这段代码本身如果不在同一个 TU 里，编译时间会不会明显下降？

统一基线仍然是：

- `grhsim_SimTop_sched_124_only_982_983.cpp`
- `elapsed_sec=110.71`

本轮副本：

1. `grhsim_SimTop_sched_124_only_982_983_no_983_datasel_region.cpp`
   - 直接替换 `983` 里的 `DataSel` 密集区
   - 原区段主要对应：
     - `72-bit` `DataSel__err_T / err_T_2`
     - `66/65-bit` concat + assign
     - `reduce_xor_words`
     - 相关若干 `16/64-bit` 拼装写回
   - 原文件位置：
     - `grhsim_SimTop_sched_124_only_982_983.cpp:1961-2135`
2. `grhsim_SimTop_sched_124_only_982_983_no_983_wide_writeback_region.cpp`
   - 直接替换 `983` 里的两个超宽写回块
   - 原文件位置：
     - `grhsim_SimTop_sched_124_only_982_983.cpp:3087-3100`
3. `grhsim_SimTop_sched_124_only_982_983_no_983_datasel_and_wide_writeback_region.cpp`
   - 同时替换上述两块

编译结果：

| 版本 | 剔除区域 | elapsed_sec | 相对基线 |
| --- | --- | ---: | ---: |
| baseline | 无 | 110.71 | +0.00s |
| no_983_datasel_region | `983` 的 `DataSel 72/66/65-bit` 密集区 | 108.69 | -2.02s |
| no_983_wide_writeback_region | `983` 的 `320/273-bit` 宽写回区 | 110.53 | -0.18s |
| no_983_datasel_and_wide_writeback_region | 同时移除上述两块 | 112.24 | +1.53s |

这一轮的信号比单 helper 剔除更直接：

- 单独移除 `983` 的 `DataSel` 密集区，只带来约 `2s` 的改善
- 单独移除 `983` 的 `320/273-bit` 宽写回区，几乎没有变化
- 把这两块一起移除，甚至还略慢

因此，当前可以进一步收敛为：

- `983` 里“最显眼”的 `DataSel` 宽拼接区，不是主导瓶颈
- `983` 里最显眼的 `320/273-bit` 写回区，也不是主导瓶颈
- 即使把这两块一起拿掉，`only_982_983` 的编译时间仍然基本不动

这说明真正让 `982 + 983` 变坏的，更可能是：

- `983` 其余大量普通位运算 / 切片 / 小宽度拼装
- 与 `982` 大量 `bankedData` 读路径共同存在于同一个函数时形成的整体 IR 形态

而不是：

- `983` 中某一小段肉眼最“宽”的代码块单独打爆了 LLVM

### `983` supernode 二分实验

在确认 `983` 里最显眼的两个“宽块”都不是主因之后，继续直接按 `word 983` 的 supernode 边界做二分。

`word 983` 一共包含 8 个 supernode：

- 前半：
  - `7277`
  - `7278`
  - `26803`
  - `26811`
- 后半：
  - `7188`
  - `7205`
  - `7233`
  - `7261`

做法：

- 每次保留其中一半 supernode
- 其余 supernode 整块替换为只清掉 `activeWordFlags` 对应 bit 的空块
- `982` 保持不变
- 仍使用同一条 `clang++ -include-pch -c` 命令计时

第一层二分结果：

| 版本 | 保留的 `983` supernode | elapsed_sec |
| --- | --- | ---: |
| baseline | `7277+7278+26803+26811+7188+7205+7233+7261` | 110.71 |
| `983_front_half` | `7277+7278+26803+26811` | 48.17 |
| `983_back_half` | `7188+7205+7233+7261` | 77.47 |

这个结果说明：

- `983` 的主要坏度明显偏后半
- 但前半也不是完全零成本
- 把 `983` 后半去掉后，时间直接从 `110.71s` 掉到 `48.17s`

于是继续只对后半再二分：

| 版本 | 保留的 `983` supernode | elapsed_sec |
| --- | --- | ---: |
| `983_mid_front` | `7188+7205` | 47.89 |
| `983_mid_back` | `7233+7261` | 59.30 |

这一层的信号更强：

- `7188+7205` 与 `983_front_half` 几乎同速
- 说明 `983` 前半 4 个 supernode 带来的额外成本很小
- `983` 的主要增量进一步收敛到最后两个 supernode：`7233+7261`

再把 `7233` 和 `7261` 分开：

| 版本 | 保留的 `983` supernode | elapsed_sec |
| --- | --- | ---: |
| `983_keep_7233` | `7233` | 44.50 |
| `983_keep_7261` | `7261` | 35.10 |
| `983_mid_back` | `7233+7261` | 59.30 |

当前可以据此收敛为：

- `983` 的主要高成本区间已经缩到 `7233+7261`
- 其中并不是某一个单独 supernode 独占绝大部分成本
- 更像是：
  - `7233` 和 `7261` 放在一起时存在额外的组合效应
  - 再叠加 `982` 的大块 `bankedData` 逻辑后，整体编译时间被进一步放大

所以，`983` 的下一轮如果还要继续缩，不应该再盲切整段 `DataSel` 或“宽写回”，而应该直接围绕：

- `Supernode 7233`
- `Supernode 7261`

做更细一级的子区域剔除。

### `7233` 子区域剔除实验

上一轮已经把 `983` 的主要增量收敛到：

- `7233 + 7261`

其中：

- `7233` 单独保留：`44.50s`
- `7261` 单独保留：`35.10s`
- `7233 + 7261` 一起保留：`59.30s`

因此，这一轮固定 `7261` 不动，只把 `7233` 本身拆成前后两段，继续看哪一段在贡献额外成本。

#### `7233` 的两段划分

按代码结构，先粗分成：

1. 前段：
   - `ms_9..14` 的
     - `probeack & execute`
     - `grantack`
     - `no_schedule_REG`
   - `ms_14 io_tasks_sink_c_bits_bufIdx`
   - `ms_15 nest_c_set_match`
2. 后段：
   - `ms_9..14` 的
     - `writerelease`
     - `triggerprefetch`
     - `prefetchack`
     - `transferput`
     - 最终 `no_schedule` 输出写回
   - `ms_10..15 meta_self_prefetch`

实验副本：

- `grhsim_SimTop_sched_124_only_982_983_983_7233_prefix_plus_7261.cpp`
  - 只保留 `7233` 前段 + `7261`
- `grhsim_SimTop_sched_124_only_982_983_983_7233_suffix_plus_7261.cpp`
  - 只保留 `7233` 后段 + `7261`

编译结果：

| 版本 | 保留内容 | elapsed_sec |
| --- | --- | ---: |
| `983_mid_back` | `7233 + 7261` | 59.30 |
| `7233_prefix_plus_7261` | `7233` 前段 + `7261` | 33.92 |
| `7233_suffix_plus_7261` | `7233` 后段 + `7261` | 34.90 |

这个结果非常关键：

- 不管保留 `7233` 前段还是后段，只要另一半去掉，时间都会掉回到大约 `35s`
- 这个量级几乎贴近 `7261` 单独保留时的 `35.10s`

因此，当前可以进一步收敛为：

- `7233` 的坏度并不集中在某一个单独子段
- 真正额外的那一截成本，来自 `7233` 前后两段同时存在时的组合效应
- 再把这个完整的 `7233` 与 `7261` 放在一起，编译时间就被继续抬高到 `59.30s`

换句话说，现在已经能更明确地说：

- 问题不是 `7233` 里的某几条“最宽”语句
- 也不是 `7233` 前段或后段其中之一单独打爆 LLVM
- 而是 `7233` 这个 supernode 内部那条长布尔状态链，当前后两段连成一个完整依赖链时，会形成明显更差的 IR 形态

这和前面 `982 + 983` 的总体观察是吻合的：

- 不是某个孤立 helper
- 也不是某个孤立宽位块
- 而是“长状态链 + 重复位级逻辑 + bankedData 读路径”共同存在时的组合坏例。

使用方式：

- 在 batch / supernode 切分时，对这些高成本模式做配额
- 避免把一批“表面行数不长、但 IR 非常恶劣”的节点继续塞进同一个 `eval_batch`

#### `7233` 语义簇剔除实验

前后半段实验说明：`7233` 的坏度不是集中在单个前半段或后半段，而是完整拼起来后才明显变坏。为了把这个“组合坏度”再落到可命名的 C++/IR 特征上，再按语义把 `7233` 拆成两类：

1. `meta_self_prefetch` 簇
   - `ms_10..14 meta_self_prefetch` 更新
2. `tail chain` 簇
   - `ms_9..14` 的
     - `triggerprefetch`
     - `prefetchack`
     - `transferput`
     - 最终 `no_schedule` 写回

实验副本：

- `grhsim_SimTop_sched_124_only_982_983_983_no_7233_meta_plus_7261.cpp`
  - 仅剔除 `7233` 的 `meta_self_prefetch` 簇，保留 `7261`
- `grhsim_SimTop_sched_124_only_982_983_983_no_7233_tail_chain_plus_7261.cpp`
  - 仅剔除 `7233` 的 `triggerprefetch/prefetchack/transferput/no_schedule` tail chain，保留 `7261`
- `grhsim_SimTop_sched_124_only_982_983_983_no_7233_meta_tail_plus_7261.cpp`
  - 同时剔除上述两簇，保留 `7261`

编译结果：

| 版本 | 剔除内容 | elapsed_sec |
| --- | --- | ---: |
| `983_mid_back` | 无，保留 `7233 + 7261` | 59.30 |
| `no_7233_meta_plus_7261` | 仅删 `meta_self_prefetch` | 48.19 |
| `no_7233_tail_chain_plus_7261` | 仅删 tail chain | 43.57 |
| `no_7233_meta_tail_plus_7261` | 同时删两簇 | 38.22 |
| `983_keep_7261` | 整个 `7233` 全删，仅保留 `7261` | 35.10 |

这个结果继续把问题收敛了：

- `7233` 的额外成本并不是平均分布在整段里，而是主要集中在两个语义簇上
- 其中 `tail chain` 的单独贡献更大：`59.30s -> 43.57s`
- `meta_self_prefetch` 也有独立贡献：`59.30s -> 48.19s`
- 两簇同时删掉后，时间降到 `38.22s`，已经非常接近 `7261 only = 35.10s`

因此可以给出当前最实证的中间结论：

- `7233 + 7261` 这组坏例里，`7233` 真正显著抬高 GVN 成本的，主要就是
  - `meta_self_prefetch` 更新链
  - `triggerprefetch -> prefetchack -> transferput -> no_schedule` 这条尾链
- 除去这两簇后，`7233` 剩余部分只带来很小的额外开销
- 所以后续如果要继续做更细一级 IR 对照，优先级应该落在这两簇与 `7261` 放在同一编译单元时产生的 IR 形态，而不是再回去盲切整段 `7233`

#### raw IR / GVN 对照

为了确认上面的 wall time 结论不是偶然，再把这些变体分别吐成 raw LLVM IR，并对同一个 `eval_batch_124` 做规模统计；同时用 `-ftime-report=per-pass-run` 观察 `GVNPass #5`。

说明：

- raw IR 使用 `-emit-llvm -S -Xclang -disable-llvm-passes`
- GVN 时间使用 `-ftime-report=per-pass-run`
- 由于 `-ftime-report` 会带来额外开销，所以这里看的是相对趋势，不和前面的裸编译 wall time 混用

raw IR 统计结果（`eval_batch_124`）：

| 版本 | raw inst | bb | call | load | store | icmp | gep | `array::ix` call |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `983_mid_back` | 8211 | 491 | 1062 | 1355 | 682 | 605 | 900 | 178 |
| `no_7233_meta_plus_7261` | 7966 | 466 | 1042 | 1315 | 662 | 585 | 865 | 168 |
| `no_7233_tail_chain_plus_7261` | 7737 | 479 | 1014 | 1283 | 646 | 557 | 852 | 166 |
| `no_7233_meta_tail_plus_7261` | 7492 | 454 | 994 | 1243 | 626 | 537 | 817 | 156 |
| `983_keep_7261` | 7012 | 447 | 933 | 1179 | 593 | 476 | 775 | 153 |

几个直接结论：

- `tail chain` 单删时，raw IR 缩减比 `meta_self_prefetch` 更明显
  - `inst`: `8211 -> 7737`，而 `meta` 只降到 `7966`
  - `load/store/gep/call`: `tail` 的降幅也都更大
- `meta_self_prefetch` 更像是“附加增量”，而 `tail chain` 更像主要放大器
- 双删后，`eval_batch_124` raw IR 已经明显逼近 `7261 only`

GVN 对照结果：

| 版本 | `GVNPass #5` wall clock (s) | `-ftime-report` 总 wall clock (s) |
| --- | ---: | ---: |
| `983_mid_back` | 53.78 | 59.63 |
| `no_7233_meta_plus_7261` | 49.11 | 55.00 |
| `no_7233_tail_chain_plus_7261` | 33.53 | 39.43 |
| `no_7233_meta_tail_plus_7261` | 32.56 | 38.34 |
| `983_keep_7261` | 39.32 | 45.15 |

这个趋势和前面的 C++ 层实证是对齐的：

- `7233 + 7261` 的主要瓶颈仍然稳定落在 `GVNPass #5`
- 删 `meta_self_prefetch` 只能小幅缓解 GVN
- 删 `tail chain` 会显著降低 GVN 时间
- 双删后，GVN 时间进一步降到 `32.56s`

因此，这一轮已经可以把“问题点”从泛泛的“7233 很坏”继续收敛成更具体的 IR 结论：

- 真正把 GVN 撑大的，首先是 `7233` 里那条 `triggerprefetch -> prefetchack -> transferput -> no_schedule` 尾链
- `meta_self_prefetch` 也会继续抬高 GVN，但它更像次级增量
- 两者叠加后，再与 `7261` 同处一个 `eval_batch_124`，就会形成当前这个稳定可复现的 GVN 坏例

#### 对照到 C++ 代码

把上面的结论直接落回 `grhsim_SimTop_sched_124_only_982_983_983_mid_back.cpp`，可以把坏例拆成 4 段来看：

1. `7233` 前置布尔归约链
   - 行 `1796..1891`
   - 这一段主要是 `ms_9..14` 的
     - `probeack & execute`
     - `grantack`
     - `no_schedule_REG`
     - `s_writerelease`
   - 代码形态是 6 路平行的 `const auto local_value = ...` 布尔链
   - 它本身不是主爆点，但为后面的 tail chain 提供了长依赖前缀

2. `7233 meta_self_prefetch`
   - 行 `1893..1941`
   - 5 个重复的
     - `const auto next_value = cond ? dirResult.self_prefetch : meta_reg_self_prefetch`
     - `if (value != next_value) { supernode_active_curr_[...] |= ...; value = next_value; }`
   - 它会制造额外的 conditional store 和 `supernode_active_curr_[]` 更新，但从实验看只是次级增量

3. `7233 tail chain`
   - 行 `1949..2043`
   - 这是当前最关键的 C++ 坏例，对应 6 路 `ms_9..14`
     - `triggerprefetch`
     - `prefetchack`
     - 最终 `no_schedule` 更新
   - 每一路都长成同一个模板：
     - 先做一串 `const auto local_value = bool_expr`
     - 再进 `if (value_x != next_value) { supernode_active_curr_[...] |= ...; supernode_active_curr_[...] |= ...; value_x = next_value; }`
   - 这一段的特征是：
     - 深布尔链
     - 多个短命局部值
     - 高频 `supernode_active_curr_[idx] |= mask`
     - 重复的 compare-then-store 写回模板
   - 这正是目前在 raw IR 里看到的大量
     - `load/icmp/br`
     - `array::ix`
     - `load/or/store`
     - state writeback
     片段的主要来源

4. `7261` 的放大器部分
   - 行 `2086..2147`
     - `dataStorage_bankedData_0` 的 4-bank 读路径
     - `rmode_d0` / `ren_d0` / `RW0_rdata` / `io_r_resp_data_0`
   - 行 `2174..2233`
     - `ms_15 meta_self_prefetch`
     - `ms_15 triggerprefetch -> prefetchack -> no_schedule`
     - bankedData 汇总写回
   - `7261` 单独保留不会打爆，但它提供了另一批相似的
     - 布尔门控
     - banked load mux
     - `if (value != next_value)` 写回
     - `supernode_active_curr_[]` 更新
   - 所以当 `7233 tail chain` 还在时，二者会在同一个 `eval_batch_124` 里叠出更差的 memory-dependence 图

可以把当前最可疑的 C++ 写法直接总结为：

- 大量线性展开的 `const auto local_value_* = bool_expr`
- 大量 `if (value != next_value) { ... value = next_value; }`
- 大量 `supernode_active_curr_[idx] |= mask`
- 上述三者在同一个 supernode/word 里按 4 路或 6 路重复展开

这也解释了为什么这不是“某一条最宽语句”的问题，而是某种特定 emit 模式的问题。

#### 优化后 IR 仍然对齐

再看优化后的 LLVM IR（`-O3 -emit-llvm -S`），结论没有反转：

| 版本 | optimized inst | bb | load | store | icmp | gep |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `983_mid_back` | 2753 | 144 | 575 | 262 | 353 | 598 |
| `no_7233_tail_chain_plus_7261` | 2457 | 132 | 507 | 243 | 297 | 530 |

所以，`7233 tail chain` 不是只在 raw IR 阶段“看起来很大”；即使经过主要优化之后，它依然主导了 `eval_batch_124` 的函数体规模。

#### 针对 C++ 写法的定点 rewrite 实验

前面的分析已经把坏例收敛到 `7233 tail chain`。下一步不是再做删除式消融，而是直接对这段 C++ 写法做定点改写，看哪一类写法真的影响编译时间。

基线：

- `983_mid_back`：`59.30s`

##### 实验 1：只聚合 `supernode_active_curr_[] |=`

改法：

- 只改 `7233 tail chain` 里的 `supernode_active_curr_[1730/1749/2509] |= ...`
- 先在局部 `std::uint8_t` accumulator 里做 OR
- 末尾再一次性写回 `supernode_active_curr_`

结果：

- `mid_back_accum_tail_writes`：`60.07s`

结论：

- 没有改善，基本可以判定：
  - 仅仅减少几次 `supernode_active_curr_[]` 写回
  - 不是主要矛盾

##### 实验 2：只改 `if (value != next_value)` 模板

改法：

- 仍然只改 `7233 tail chain`
- 把
  - `if (value != next_value) { ...; value = next_value; }`
  改成
  - `const auto changed = (value != next_value);`
  - `if (changed) { ... }`
  - `value = next_value;`

结果：

- `mid_back_tail_uncond_store`：`68.66s`

结论：

- 明显更差
- 说明“把条件判断和写回拆开”不会缓解 LLVM，反而会让 IR 更难看

##### 实验 3：把 6 路手工展开改成小循环

改法：

- 仍然只改 `7233 tail chain`
- 把 `ms_9..14` 的 6 路
  - `triggerprefetch`
  - `prefetchack`
  - `no_schedule`
  手工展开代码，改成：
  - 局部数组
  - 一个 `for (lane=0; lane<6; ++lane)` 循环

编译结果：

- `mid_back_tail_loop`：`58.59s`

raw IR / GVN：

| 版本 | raw inst | bb | call | load | store | icmp | gep | `GVNPass #5` wall clock (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `983_mid_back` | 8211 | 491 | 1062 | 1355 | 682 | 605 | 900 | 53.78 |
| `mid_back_tail_loop` | 8098 | 486 | 1037 | 1340 | 676 | 597 | 917 | 51.91 |

结论：

- loop 化只带来了很弱的改善
- `GVNPass #5` 的确下降了一点：`53.78s -> 51.91s`
- 但幅度远小于删除整个 tail chain 时的改善：`53.78s -> 33.53s`

所以，这一轮可以得到一个更细的判断：

- 问题不只是 `operator[]` 写回次数
- 也不只是 `if (value != next_value)` 这个小模板
- 更像是：
  - 这 6 路 tail chain 本身承载的布尔依赖内容
  - 再加上手工展开后的整体 IR 形状
  共同造成了 GVN 的坏例

换句话说：

- “轻微改写模板”基本无效，甚至可能更差
- “改变整体展开形状”有一点帮助，但还不够
- 目前最强信号仍然是：
  - 直接删掉 `7233 tail chain`
  - 或从 emit 源头避免生成这类 6 路长布尔链的 fully-unrolled compare/update 模式

#### 为什么 `sched_123` 更大却更快

用户提出了一个关键反例：

- `sched_123.cpp` 明显比当前这些实验文件更大
- 但编译速度却快得多

这说明前面那几轮只盯着“局部模板改写”是不够的，必须把 `sched_123` 拉进同一套指标里比较。

##### 基线对照

源码行数：

| 文件 | 行数 |
| --- | ---: |
| `grhsim_SimTop_sched_123.cpp` | 32214 |
| `983_mid_back.cpp` | 2249 |

编译时间：

| 文件 | elapsed_sec |
| --- | ---: |
| `sched_123` | 13.76 |
| `983_mid_back` | 59.30 |

GVN：

| 文件 | 主要 GVNPass wall clock (s) | `-ftime-report` 总 wall clock (s) |
| --- | ---: | ---: |
| `sched_123` | 5.88 |
| `983_mid_back` | 53.78 | 59.63 |

注意这里 `sched_123` 的热点是 `GVNPass #68`，而不是 `#5`；但核心结论不变：`sched_123` 的 GVN 负担远小于 `983_mid_back`。

##### `sched_123` 在 LLVM 眼里其实也很大

raw IR（`eval_batch_123`）：

| 版本 | raw inst | bb | call | load | store | icmp | gep | `array::ix` call |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `sched_123` | 139386 | 6437 | 18302 | 22360 | 14009 | 6702 | 16969 | 6311 |
| `983_mid_back` | 8211 | 491 | 1062 | 1355 | 682 | 605 | 900 | 178 |

optimized IR：

| 版本 | opt inst | bb | load | store | icmp | gep | conditional branches |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `sched_123` | 56018 | 4770 | 11678 | 8540 | 4406 | 11584 | 2349 |
| `983_mid_back` | 2753 | 144 | 575 | 262 | 353 | 598 | 76 |

所以，真正的结论不是“`sched_123` 更小”，而是：

- `sched_123` 在 LLVM 眼里其实大得多
- 但它保留了大量 CFG，坏度被摊薄了
- `983_mid_back` 则是小体积、高密度、高坏度的坏例

最醒目的对比是：

- `sched_123` 的 GVN 时间 / 1000 条 raw IR 指令：约 `0.042s`
- `983_mid_back` 的 GVN 时间 / 1000 条 raw IR 指令：约 `6.55s`

也就是说，`983_mid_back` 的“坏度密度”比 `sched_123` 高两个数量级。

##### `sched_123` 里最像坏例的 supernode

在 `sched_123` 中搜索与当前坏例最像的语义组合：

- `triggerprefetch / prefetchack / no_schedule`
- `meta_self_prefetch`
- `dataStorage_bankedData ... RW0_ren_d0 / rmode_d0`

只找到一个最像的 supernode：

- `Supernode 7115`
- 位置：`14568..14758`

它的特征是：

- 含 bankedData 4-bank 读路径
- 含 `ms_15 meta_self_prefetch`
- 含 `ms_15 triggerprefetch -> prefetchack -> no_schedule`

但它只有单 lane：

- `triggerprefetch`：1 次
- `prefetchack`：1 次
- `if (value != next_value)`：5 个

而不是像 `7233` 那样同时带 `ms_9..14` 的 6 路 tail chain。

##### lane 乘法效应实验

为了验证这个差异，我把 `983_mid_back` 的 `7233 tail chain` 改成只保留 `ms_14` 一条 lane，其余 5 条 lane 全删，`7261` 保持不动。

结果：

| 版本 | 说明 | elapsed_sec | `GVNPass #5` wall clock (s) |
| --- | --- | ---: | ---: |
| `983_mid_back` | `7233` 保留 `ms_9..14` 全 6 lane + `7261` | 59.30 | 53.78 |
| `tail_only_ms14` | `7233 tail` 只保留 `ms_14` 单 lane + `7261` | 41.95 | 41.67 |

raw IR：

| 版本 | raw inst | bb | call | load | store | icmp | gep |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `983_mid_back` | 8211 | 491 | 1062 | 1355 | 682 | 605 | 900 |
| `tail_only_ms14` | 7816 | 481 | 1022 | 1295 | 652 | 565 | 860 |

这组结果非常关键：

- 只把 `7233 tail chain` 从 6 lane 降到 1 lane，就已经把编译时间从 `59.30s` 拉到 `41.95s`
- `GVNPass #5` 也同步从 `53.78s` 降到 `41.67s`
- 这说明真正显著的因素之一，不是文件大小，也不是某个孤立模板，而是 `7233 tail chain` 的 lane 乘法效应

因此，当前对“为什么 `sched_123` 更大却更快”的最好解释是：

- `sched_123` 虽然总量大，但相似模式大多以单 lane 或较低乘法展开
- 而 `983_mid_back` 把
  - `7233` 的 6-lane tail chain
  - 和 `7261` 的 bankedData + `ms_15` tail/update
  压在同一个 `eval_batch_124` 里
- 真正打爆 GVN 的，是这类高乘法展开的局部坏度，而不是 TU 总长度

### `982` 为什么组合起来会变重

在把 `982` 从 `983` 中拆开之后，又继续对 `982` 本身做了一轮更直接的组合实验。

先把 `982` 的 8 个 supernode 分别提成单文件：

- `7265`
- `7267`
- `7268`
- `7269`
- `7272`
- `7274`
- `7275`
- `7276`

结果非常整齐：

| supernode | elapsed_sec |
| --- | ---: |
| `7265` | `5.91s` |
| `7267` | `5.89s` |
| `7268` | `5.91s` |
| `7269` | `6.03s` |
| `7272` | `5.92s` |
| `7274` | `5.96s` |
| `7275` | `5.95s` |
| `7276` | `5.94s` |

这说明：

- `982` 不是“某一个特别坏的 supernode”在单点打爆编译
- 单个 supernode 的成本都接近固定外壳成本
- 真正的坏度来自多个高度同构的 supernode 被放进同一个 `eval_batch_124`

为了验证这一点，又做了 `1 / 2 / 4 / 8` 个 supernode 的阶梯组合实验：

- `n1`: `7265`
- `n2`: `7265 + 7267`
- `n4`: `7265 + 7267 + 7268 + 7269`
- `n8`: `982` 的全部 8 个 supernode

总编译时间：

| 版本 | supernode 数 | elapsed_sec |
| --- | ---: | ---: |
| `n1` | `1` | `5.94s` |
| `n2` | `2` | `7.84s` |
| `n4` | `4` | `10.95s` |
| `n8` | `8` | `27.11s` |

`-ftime-report=per-pass-run` 显示，真正爆炸的是 `GVNPass #5`：

| 版本 | `GVNPass #5` wall clock (s) |
| --- | ---: |
| `n1` | `0.2478` |
| `n2` | `1.1777` |
| `n4` | `4.9763` |
| `n8` | `23.8669` |

而 `LLVM IR generation` 基本稳定在同一水平：

| 版本 | `LLVM IR generation` wall clock (s) |
| --- | ---: |
| `n1` | `5.3429` |
| `n2` | `5.3245` |
| `n4` | `5.3178` |
| `n8` | `5.3241` |

这组结果的含义很明确：

- C++/IR 的“生成成本”并没有随 supernode 数量同步爆炸
- 真正恶化的是优化阶段，尤其是 `GVNPass #5`
- `GVNPass #5` 在 `1 -> 2 -> 4 -> 8` 的翻倍过程中，时间大致按 `4x` 级别放大
- 因而当前最合理的判断是：`982` 在 LLVM 里表现出接近平方复杂度的组合坏度

更具体地说，这一轮实证支持下面这个解释：

- `982` 的 8 个 supernode 在语义结构上高度同构
- 每个 supernode 都带一套近似重复的 `bankedData` / `ClockGate` / `rdata` / 写回链
- 当这些重复块被并排放进同一个 `eval_batch_124` 时，`GVN + MemoryDependence + AA` 需要处理的“可比较关系”数目开始接近平方增长
- 所以 `982` 的问题不是文本大小，也不是某个单点坏例，而是“同构 supernode 密集堆叠后在同一个函数里触发了超线性优化成本”

### `979` 和 `982` 的累积曲线对照

为了确认 `982` 的异常增长是否只是“大 word 的普遍现象”，又从原始 `sched_123.cpp` 中提取了 `eval_batch_123()` 里最大的 active word：

- `word 979`
- 原始范围约为 `grhsim_SimTop_sched_123.cpp:19674-24644`
- 单独提取文件：`grhsim_SimTop_sched_123_only_979.cpp`

它单独编译只需要：

- `6.09s`

接着，对 `979` 和 `982` 都按 supernode 的自然顺序做了 `1 / 2 / 3 / 4 / 5 / 6 / 7 / 8` 个 supernode 的累积保留实验。

#### 总编译时间对照

| 累积 supernode 数 | `979` elapsed_sec | `982` elapsed_sec |
| --- | ---: | ---: |
| `1` | `5.71s` | `5.89s` |
| `2` | `5.70s` | `7.04s` |
| `3` | `5.80s` | `8.53s` |
| `4` | `5.86s` | `10.91s` |
| `5` | `5.89s` | `14.93s` |
| `6` | `6.00s` | `19.12s` |
| `7` | `6.04s` | `22.68s` |
| `8` | `6.11s` | `27.05s` |

#### 相对 `n1` 的增量对照

| 累积 supernode 数 | `979` 相对 `n1` 增量 | `982` 相对 `n1` 增量 |
| --- | ---: | ---: |
| `1` | `+0.00s` | `+0.00s` |
| `2` | `-0.01s` | `+1.15s` |
| `3` | `+0.09s` | `+2.64s` |
| `4` | `+0.15s` | `+5.02s` |
| `5` | `+0.18s` | `+9.04s` |
| `6` | `+0.29s` | `+13.23s` |
| `7` | `+0.33s` | `+16.79s` |
| `8` | `+0.40s` | `+21.16s` |

这组对照把差异说明得很直接：

- `979` 的曲线几乎是平的
- 即使从 `1` 个 supernode 累积到 `8` 个，总时间也只增加了 `0.40s`
- `982` 则完全不同，从 `n5` 开始明显变陡
- 到 `n8` 时，`982` 已经比自己的 `n1` 多出 `21.16s`

因此，这一轮可以把结论再收紧一步：

- “大 word 里有多个 supernode”这件事本身并不会自动导致编译爆炸
- `sched_123` 的最大 word `979` 就是反例：它很大，但累积曲线基本平坦
- 真正异常的是 `982` 这种特定语义形态：多个高度同构的 supernode 在同一个 `eval_batch_124` 里叠加后，触发了明显更坏的 LLVM 优化复杂度

也就是说，当前观察到的差异已经不是“规模问题”，而是更具体的“结构问题”：

- `979`：大，但组合稳定
- `982`：单点不重，但组合后快速恶化

后续如果要继续往下挖，重点不该再放在“再找更大的 word”，而应该落到：

- `979` 和 `982` 在 supernode 内部数据流形态上的具体差异
- 为什么 `979` 的多个 supernode 并排后没有让 `GVN` 关系数激增
- 而 `982` 会在大约 `5` 个 supernode 之后进入明显更坏的区间

#### `-ftime-report` 对照：差异确实落在 `GVNPass #5`

为了把上面的“曲线差异”精确落到 LLVM pass，又分别对：

- `979_n8`
- `982_n8`

跑了一次 `-ftime-report=per-pass-run`。

结果如下：

| 版本 | total wall clock | `Optimizer` wall clock | `LLVM IR generation` wall clock | `GVNPass #5` wall clock |
| --- | ---: | ---: | ---: | ---: |
| `979_n8` | `5.9261s` | `0.4220s` | `5.2634s` | `0.2925s` |
| `982_n8` | `31.4751s` | `26.0228s` | `5.2694s` | `25.6348s` |

这组结果把差异钉得很死：

- 两者的 `LLVM IR generation` 几乎一样
  - `979_n8`: `5.2634s`
  - `982_n8`: `5.2694s`
- 前端时间也都很小，不是瓶颈
- 真正的差异几乎全部在 `Optimizer`
- 而 `Optimizer` 的主要差异，又几乎全部落在 `GVNPass #5`

也就是说：

- `979_n8` 的“8 个 supernode 并排”并没有把 LLVM 优化器打坏
- `982_n8` 的问题也不是“IR 生成更慢”
- `982_n8` 真正异常的地方，就是在 `GVNPass #5` 上出现了数量级更高的成本

因此，到这一步可以把结论表述得更精确：

- `979` 和 `982` 的差异，已经可以明确归因到 LLVM 优化阶段，而不是前端或 IR 生成阶段
- 更具体地说，这个差异几乎完全落在 `GVNPass #5`
- 所以 `982` 的异常不是“代码多一些”，而是它那组 supernode 叠在一起后，恰好构造出了一个让 `GVN + MemoryDependence + AA` 极度不友好的 IR 形态

#### `982` 这一组 supernode，到底和 `979` 在 C++ 形态上差在哪

前面的实验已经说明：

- `982` 的 8 个 supernode 组合起来会快速变坏
- `979` 的 8 个 supernode 组合起来几乎不变

于是又直接对两组“单个 supernode 提取文件”做了一轮 C++ 结构统计，比较的不是编译时间，而是：

- `next_value` 的类型宽度
- `local_value` 的类型宽度
- bitwise / trunc / shift 这类操作形态
- `bankedData / ClockGate / RW0_*` 这类 memory-like 语义关键词
- `ms_*` 这类状态机信号关键词

按“每个 supernode 的平均值”汇总如下：

| 指标 | `982` 每个 supernode 平均 | `979` 每个 supernode 平均 |
| --- | ---: | ---: |
| 源码行数 | `268.88` | `678.00` |
| `next_value: bool` | `4.00` | `39.12` |
| `next_value: uint32_t` | `0.12` | `0.25` |
| `next_value: uint64_t` | `0.88` | `1.00` |
| `local_value: bool` | `20.00` | `15.75` |
| `local_value: uint8_t` | `0.00` | `5.25` |
| `local_value: uint32_t` | `1.62` | `3.25` |
| `local_value: uint64_t` | `11.38` | `0.00` |
| `if (value != next_value)` | `5.00` | `43.62` |
| `grhsim_trunc_u64(...)` | `4.00` | `11.38` |
| `<<` | `0.00` | `3.25` |
| `>>` | `0.00` | `9.50` |
| `bankedData` | `66.00` | `0.00` |
| `ClockGate` | `24.00` | `0.00` |
| `RW0_rdata` | `16.00` | `0.00` |
| `RW0_ren` | `4.00` | `0.00` |
| `RW0_rmode` | `4.00` | `0.00` |
| `dataEccArray` | `6.00` | `0.00` |
| `ms_*` | `0.00` | `132.62` |

这张表很说明问题：

- `979` 单个 supernode 明显更大，行数是 `982` 的约 `2.5x`
- `979` 的 bitwise / trunc / shift 更多，`if (value != next_value)` 也多得多
- 但是 `979` 基本不碰 `bankedData / ClockGate / RW0_*`
- `982` 则几乎完全相反：单体更短，但明显是 memory-like 读路径

也就是说，两组差异不在“谁的位运算更多”：

- 真正更重位运算、更重状态写回的是 `979`
- 真正更像 memory-read / mux / banking 读路径的是 `982`

这和编译行为结合起来后，可以得出一个更具体的判断：

- `979` 每个 supernode 都是“状态机更新块”
  - 大量 `ms_*` 控制位
  - 大量 `if (value != next_value)` 写回
  - 大量窄位 `bool / uint8_t / uint32_t` 局部
  - 这类代码虽然长，但更像“算完就写”，优化器不需要在多个 supernode 之间反复推理复杂 memory-dependence
- `982` 每个 supernode 都是“bankedData 读路径块”
  - 固定的 `ClockGate + RW0_rmode + RW0_ren + RW0_rdata` 模板
  - 大量 `uint64_t` 局部值
  - 很少真正的最终写回点
  - 这类代码在多个 supernode 并排后，会给 `GVN + MemoryDependence + AA` 留下一大片高度相似、可互相比较的 load/mux 图

所以，到这一步已经可以把“为什么 `982` 组合起来坏、`979` 不坏”进一步落回到 C++ 代码层面：

- 不是因为 `982` 更大
- 不是因为 `982` 的位运算更多
- 而是因为 `982` 的每个 supernode 都长得像同一种 memory-like 读路径模板
- 当这类模板在同一个 `eval_batch_124` 中重复 8 次时，LLVM 在 `GVNPass #5` 中要处理的候选关系急剧增加
- `979` 虽然更长，但本质上是状态机更新代码，不会触发同等级别的 `GVN` 爆炸

#### 继续收敛：`982` 里到底是哪一层 memory-like 数据流最坏

在确认 `982` 的共同语义是“重复的 memory-like 读路径模板”之后，又继续对 `982_n8` 做了几轮更强的定点消融，目的是区分：

- `RW0_rmode / RW0_ren / RW0_rdata` 入口模板
- `io_r_resp_data_0` 响应层
- `ren_vec ? resp : zero` 选择层

一共对比了 5 个版本：

| 版本 | 改动 | total | `Optimizer` | `GVN` hotspot |
| --- | --- | ---: | ---: | ---: |
| `982_n8` | 原版 | `31.48s` | `26.02s` | `GVNPass #5 = 25.63s` |
| `982_n8_ablate_memory_read` | 去掉 `RW0_rmode/ren/rdata` 入口模板 | `26.82s` | `21.33s` | `GVNPass #3 = 20.96s` |
| `982_n8_flatten_ren_vec` | 保留响应层，只打平 `ren_vec ? resp : zero` | `24.58s` | `19.75s` | `GVNPass #5 = 19.36s` |
| `982_n8_zero_resp` | 所有 `io_r_resp_data_0` 全置零 | `23.14s` | `15.55s` | `GVNPass #5 = 15.21s` |
| `982_n8_keep_bankedData1_resp` | 只保留 `bankedData_1` 响应，其余组置零 | `21.30s` | `15.59s` | `GVNPass #5 = 15.25s` |
| `982_n8_delete_memory_network` | 把 `RW0_* -> RW0_rdata -> io_r_resp_data_0 -> ren_vec` 整套网络全部常量化 | `13.23s` | `7.77s` | `GVNPass #3 = 7.39s` |

这组结果把层级关系说明得比较清楚：

1. `RW0_rmode / RW0_ren / RW0_rdata` 入口模板确实有贡献，但不是最大头
   - `GVN` 只从 `25.63s` 降到 `20.96s`
2. `ren_vec ? resp : zero` 选择层也是放大器
   - 单独打平之后，`GVN` 降到 `19.36s`
3. 真正更重的是 `io_r_resp_data_0` 这一整层响应网络
   - 把 response 层直接置零，`GVN` 进一步降到 `15.21s`
4. 更关键的是“多组并排”，而不是“单组存在”
   - `zero_resp` 和 `keep_bankedData1_resp` 几乎一样
   - 说明保留一组 `bankedData_1` 响应，几乎不额外增加成本
   - 真正把 `GVN` 撑大的，是多组 `bankedData / dataEcc` response 网络并排后的组合效应
5. 如果把整套 `RW0_* -> RW0_rdata -> io_r_resp_data_0 -> ren_vec` 网络一起删掉，编译时间会进一步大幅下降
   - total: `31.48s -> 13.23s`
   - `Optimizer`: `26.02s -> 7.77s`
   - `GVN`: `25.63s -> 7.39s`
   - 这说明前面识别出的那套 memory-like 响应网络，确实是 `982` 的主坏点之一，而且影响是决定性的

这里还需要和 `979` 做一个直接对照，否则容易误解成“任何大 word 里都有类似网络，只是 `982` 更敏感”。实际不是这样。

对 `979_n8` 和 `982_n8` 的关键词统计如下：

| 指标 | `979_n8` | `982_n8` |
| --- | ---: | ---: |
| `RW0_rmode` | `0` | `32` |
| `RW0_ren` | `0` | `32` |
| `RW0_rdata` | `0` | `128` |
| `io_r_resp_data_0` | `0` | `160` |
| `ren_vec ? ... : ...` | `0` | `32` |
| `bankedData` | `0` | `528` |
| `dataEccArray` | `0` | `48` |
| `_ms_` | `1061` | `0` |
| `if (value != next_value)` | `349` | `40` |

这张表非常关键，因为它说明：

- `979` 根本没有这套 `RW0_* -> io_r_resp_data_0 -> ren_vec mux` 响应网络
- 所以上面那些 `zero_resp` / `flatten_ren_vec` / `keep_bankedData1_resp` 实验，虽然只在 `982` 上做，但并不是“缺少参照物”
- 参照物恰恰是：`979` 这组“编译稳定的大 word”里，本来就不存在这套结构

换句话说：

- `979` 的大头是 `_ms_*` 状态机更新和大量 `if (value != next_value)` 写回
- `982` 的大头则是 `bankedData / dataEcc` 响应网络
- 因此，前面那几轮对 `982` 的定点消融，其实已经天然是在和 `979` 做结构对照：
  - `979` 没有这套响应网络，所以它不会触发同类 `GVN` 爆炸
  - `982` 有，而且是多组并排出现，所以才表现出异常的 `GVNPass #5`

因此，到这一步可以把 `982` 的坏点再收敛一层：

- 主坏点不是单独的 `RW0_rmode / RW0_ren / RW0_rdata`
- 也不只是后面的 `ren_vec` 选择层
- 更核心的是多组 `bankedData / dataEcc` 的 `io_r_resp_data_0` 响应网络并排出现
- `ren_vec` 选择层是次一级放大器，但不是最大头

换句话说，当前最可信的结构解释是：

- `982` 在 LLVM 里坏，不是因为某条单独 mux 写法
- 而是因为“多组高度同构的 banked response 子图”被一起放进了同一个 `eval_batch_124`
- 这些子图彼此高度相似，又通过后续选择/合流继续扇出，因此 `GVN + MemoryDependence + AA` 的候选关系数急剧增加

### 继续消融：`delete_memory_network` 剩余的 `13s` 到底在哪

在 `grhsim_SimTop_sched_124_only_982_n8_delete_memory_network.cpp` 里继续看残留结构，会发现还剩两类非常重复的骨架：

1. 每个 bank 的 `ClockGate_Q` 写回块
   - 典型 C++ 形态就是：
   - `if (value_..._ClockGate_Q_ != next_value) { event_edge_slots_[...] = grhsim_classify_edge(...); supernode_active_curr_[...] |= ...; value_..._ClockGate_Q_ = next_value; }`
   - 具体例子可见 `tmp/sched124_extracts/grhsim_SimTop_sched_124_only_982_n8_delete_memory_network.cpp` 中 `177-199`、`379-401` 这一类重复块
2. 聚合后的 `_bankedData_*_io_r_resp_data_0_` / `_dataEccArray_0_io_r_resp_data_0_` 写回块

针对这两类残留结构，又做了 7 个控制变量实验：

| 版本 | 改动 | total | `Optimizer` | `GVN` hotspot |
| --- | --- | ---: | ---: | ---: |
| `982_n8_delete_memory_network` | `RW0_* -> RW0_rdata -> io_r_resp_data_0 -> ren_vec` 已删 | `13.23s` | `7.77s` | `GVNPass #3 = 7.39s` |
| `982_n8_delete_memory_network_ablate_agg_resp_writeback` | 只删聚合 `io_r_resp_data_0` 写回 | `12.82s` | `7.32s` | `GVNPass #3 = 6.97s` |
| `982_n8_delete_memory_network_ablate_clockgate_fanout` | 只删 `ClockGate_Q` 块里的 `supernode_active_curr_` 扇出 | `13.21s` | `7.78s` | `GVNPass #3 = 7.21s` |
| `982_n8_delete_memory_network_const_clockgate_event_edge` | 保留 `event_edge_slots_[]` store，但把 `grhsim_classify_edge(old,new)` 改成常量参数 | `13.12s` | `7.68s` | `GVNPass #3 = 7.28s` |
| `982_n8_delete_memory_network_call_clockgate_event_edge` | 保留 `grhsim_classify_edge(false,false)` 调用，但不再写 `event_edge_slots_[]` | `5.51s` | `0.06s` | `GVNPass #3 = 0.01s` |
| `982_n8_delete_memory_network_ablate_clockgate_event_edge` | 直接删掉 `ClockGate_Q` 块里的 `event_edge_slots_[]` 写入 | `5.52s` | `0.06s` | `GVNPass #2 = 0.01s` |
| `982_n8_delete_memory_network_ablate_clockgate_q` | 整个 `ClockGate_Q` 写回块都删掉 | `5.47s` | `0.04s` | `GVNPass #2 = 0.00s` |

这组结果非常关键，因为它把剩余瓶颈继续钉到了更细的 C++ 写法上：

1. 聚合 `io_r_resp_data_0` 写回不是主矛盾
   - `13.23s -> 12.82s`
   - 只降了 `0.4s` 左右，说明 `delete_memory_network` 之后，残留聚合写回已经不是主要热点
2. `ClockGate_Q` 里的 `supernode_active_curr_` 扇出也不是主矛盾
   - `13.23s -> 13.21s`
   - 几乎没有变化
3. 真正决定性的是 `ClockGate_Q` 条件块里的 `event_edge_slots_[]` 写入
   - 只要不再往 `event_edge_slots_[]` 里写，total 立刻掉到 `5.5s` 左右
   - `Optimizer` 也从 `7.77s` 直接掉到 `0.04s ~ 0.06s`
   - 这时已经基本回到了 `979_n8` 的量级（`5.93s`）
4. 这还说明，重的不是 `grhsim_classify_edge(old,new)` 这个调用本身
   - 因为把参数改成常量后，编译时间几乎不变：`13.23s -> 13.12s`
   - 但保留调用、只去掉 `event_edge_slots_[]` store，编译时间就立刻掉到 `5.51s`
   - 所以问题主要不是函数调用，也不是 `old/new` 依赖链，而是“在这 32 个 `ClockGate_Q` 条件块里，对同一个 `event_edge_slots_[]` 数组做条件写入”

因此，当前 `982` 的 root cause 可以进一步收敛成：

- 第一层坏点：`RW0_* -> RW0_rdata -> io_r_resp_data_0 -> ren_vec` 这套 memory-like response 网络，把 `31.48s` 压到 `13.23s`
- 第二层坏点：残留的 `ClockGate_Q` 写回块里，对 `event_edge_slots_[]` 的条件 store，把 `13.23s` 继续压到 `5.5s`
- 其中真正敏感的 C++ 形态不是“普通的 if + state update”，也不是 `supernode_active_curr_` 扇出，而是：
  - 大量重复的
  - `if (old != next) event_edge_slots_[i] = ...;`
  - 并排出现在同一个编译单元、同一个大函数里

这解释了为什么：

- `979` 虽然整体更大，但没有这两层特定结构组合，所以 `GVNPass #5/#3` 不会炸
- `982` 在删掉 memory network 之后，仍然会剩下一个很“尖锐”的 `ClockGate_Q + event_edge_slots_[]` 模式
- 一旦把这类 `event_edge_slots_[]` 条件写入拿掉，`982` 就重新回到正常编译时间区间

## 实施顺序建议

优先级建议如下：

1. 先清理 `sched` 主路径中的 lambda / closure 残留
2. 再把热点 `std::array::operator[]` 访问改成更直接的地址访问
3. 再压缩短命局部对象和 temporary words
4. 最后把“IR 复杂度估算”接入 batch 切分策略

原因：

- 前两项直接对应这次 IR 和 `gdb` 观察到的最强信号
- 后两项属于继续放大收益、避免回归

## 当前判断

当前 `sched_124.cpp` 的编译拖尾已经可以定性为：

- 不是 `PCH` 失效
- 不是单纯文件长度问题
- 不是某个后端 codegen pass 的偶发异常
- 而是 emit 生成的 C++ 结构，使 `eval_batch_124` 在 LLVM IR 层面表现为一个极高 memory-dependence 成本的超大函数

后续优化应优先直接面向：

- lambda 清理
- `operator[]` 清理
- temporary object 清理
- batch IR complexity 控制

## `comb-lane-pack` 在 XiangShan `storage-frontier` 上的最新验证

这一轮不再用手写脚本，而是直接通过现成的：

- `scripts/wolvrix_xs_grhsim.py`

在 `pre-sched` 阶段跑 `comb-lane-pack`，并导出 report：

- report: `build/xs/grhsim/comb_lane_pack_report_xs.json`
- post-stats: `build/xs/grhsim/wolvrix_xs_post_stats.json`

实测结果：

- `read_sv`: `88.16s`
- `comb-lane-pack`: `262.86s`
- summary: `groups=4161 roots=55863 packed-width=2750614`

### report 可观测性补强

这次给 `comb-lane-pack` report 增加了以下字段，便于直接对照到真实 storage-frontier：

- `root_source`
- `anchor_kind`
- `anchor_symbols`
- `storage_target_symbols`

这样现在已经可以直接从 report 中看到：

- 是 `kRegisterWritePort` 还是 `kMemoryWritePort`
- 每组对应的 write-port 锚点
- 每组最终写到哪个 `regSymbol` / `memSymbol`

### 已确认抓到的热点

report 已经明确抓到 `bankedData` 相关的 storage-frontier，典型例子包括：

1. `cpu$l_soc$l3cacheOpt$slices_2$dataStorage$bankedData_[0-7]$banks_[0-3]$array_0_ext$RW0_addr`
2. 它们对应的
   - `cpu$l_soc$l3cacheOpt$slices_2$dataStorage$bankedData_[0-7]$banks_[0-3]$array_0_ext$_RW0_raddr_d0`

也就是说，当前 pass 确实已经能识别并合并这类：

- 4-bank 并排
- 14-bit `RW0_addr`
- 前置 `Mux`
- 写回到 `_RW0_raddr_d0`

这一层 storage-frontier 模式。

### 没有抓到的关键坏例

但是，和 `sched_124` / `982` 更相关的那批 memory-write 坏例，当前 pass 还没有真正命中。

以 `slices_2$dataStorage$bankedData_0` 为例，在 `wolvrix_xs_post_stats.json` 中可见：

1. `kMemoryWritePort` 的 data operand 不是每个 bank 各自独立的一棵 comb tree，而是共享同一个：
   - `cpu$l_soc$l3cacheOpt$slices_2$dataStorage$bankedData_0$io_w_req_bits_data_0`
2. 这个 value 本身只是：
   - `kRegisterReadPort`
   - 即纯叶子，不是当前 `comb-lane-pack` 支持的 internal comb DAG
3. 与之并排出现的 `_ClockGate_Q / _ClockGate_1_Q / _ClockGate_2_Q / _ClockGate_3_Q`
   - 只是 `kAssign(ClockGate$Q)` 形式的 1-bit clock leaf 包装
   - 它们并不在当前 pass 的 `storage data root` 选择范围内

因此，对 `sched_124` 当前最敏感的这类模式：

- 大量重复的
- `if (old != next) event_edge_slots_[i] = ...;`
- 并排出现在同一个编译单元、同一个大函数里

`comb-lane-pack` 目前**不能**直接处理，原因不是“没看到 storage-frontier”，而是：

1. `RW0_wdata` 在这组路径里本来就是 leaf register read，不存在可压缩的 comb tree
2. 真正重复的是 write-site 自身的并排结构
3. 尤其是 `_ClockGate_Q` 驱动下的大量条件 `event_edge_slots_[]` 写入

### 当前结论

所以，这一轮验证后的结论是：

1. `comb-lane-pack` 已经能处理一部分真实 XiangShan storage-frontier
   - 例如 `RW0_addr -> _RW0_raddr_d0`
2. 但它还不能解决 `sched_124` 最致命的那一类 `ClockGate_Q + event_edge_slots_[]` 写回模式
3. `sched_124` 真正的修复方向，仍然需要进一步面向：
   - write-site 聚合
   - 或更早阶段把这类 memory-like replicated write skeleton 变得更可共享
