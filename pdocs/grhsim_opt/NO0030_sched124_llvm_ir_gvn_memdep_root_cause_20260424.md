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

使用方式：

- 在 batch / supernode 切分时，对这些高成本模式做配额
- 避免把一批“表面行数不长、但 IR 非常恶劣”的节点继续塞进同一个 `eval_batch`

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

