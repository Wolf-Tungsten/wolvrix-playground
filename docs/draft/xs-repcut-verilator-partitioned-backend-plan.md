# XiangShan RepCut Verilator 分区后端规格草案

## 1. 问题

当前 `make run_xs_repcut` 已经生成一套 post-repcut 设计，核心模块包括：

- `SimTop`
- `SimTop_debug_part`
- `SimTop_logic_part_repcut_part*`

现有 `difftest` 的 Verilator 后端仍按单一 `VSimTop` 工作。目标是在不改变当前 repcut RTL 结构的前提下，把现有 `debug_part` 与 `part_*` 作为独立 Verilator 单元运行，并由 host 侧 C++ 实现统一调度。

## 2. 既有语义假设

本方案建立在以下前提上，并且后续实现不再重新证明这些前提：

- `strip-debug` 是正确的。
- `repcut` 是正确的。
- 当前 post-repcut `SimTop` wrapper 的求值语义满足：
  - 每次顶层 wrapper eval 一次。
  - wrapper 内部每个子模块在该次求值中仅 eval 一次。

换句话说，`emitVerilatorRepCutPackage` 的任务是把这个既有语义搬运到 host 侧 C++ runtime，而不是重新定义或修正它。

## 3. 结构边界

后续实现必须使用当前已有的 post-repcut 结构作为唯一 RTL 输入边界。

允许使用的现有单元：

- `SimTop_debug_part`
- `SimTop_logic_part_repcut_part*`

不允许新增的 RTL 结构：

- 新 wrapper module
- 新 group module
- 新的 `group_*.sv`
- 对当前 repcut 结果做第二次 RTL 重组

host 侧允许新增：

- 一种新的 `emit`

名称固定为：

- `emitVerilatorRepCutPackage`

## 4. 扩展点约束

整个方案只允许增加一个新入口，即：

- `emitVerilatorRepCutPackage`

这个新入口必须满足以下条件：

1. 一次性读取当前 post-repcut design。
2. 一次性生成外部运行所需全部工件。
3. 不再依赖第二个生成步骤。

这里的“全部工件”至少包括：

- 单元连接描述
- C++ runtime wrapper 源码
- 各单元 Verilator 编译 Makefile
- 顶层构建入口

`emitVerilatorRepCutPackage` 必须直接输出完整 package。

## 5. 输入

输入固定为当前 post-repcut design。

`emitVerilatorRepCutPackage` 的职责是：

1. 读取当前 post-repcut design。
2. 直接执行当前 SV 发射能力。
3. 识别当前已有单元。
4. 导出当前已有连线关系。
5. 直接生成完整外部 package。

建议直接从以下之一读取：

- `xs_wolf_repcut.json`
- 内存中的 design 对象

不允许把 `SimTop.sv` 文本解析作为主要信息来源。

建议 `emitVerilatorRepCutPackage` 的调用语义为：

- 输入：post-repcut design
- 输出：一个完整 package 目录

也就是说，它不是“只吐一类文件”的 emit，而是“面向 Verilator partitioned backend 的完整工程包 emit”。

这里要明确组合关系：

- `emitVerilatorRepCutPackage` 不是“先跑旧的 SV emit，再额外打一个包”。
- `emitVerilatorRepCutPackage` 自身就包含当前 SV 发射职责。
- 对外只产出一份 SV，这份 SV 直接放在输出 package 中。

## 6. 输出包

新入口应输出一个完整目录，例如：

- `build/xs/repcut-partitioned/package`

该目录至少包含以下文件：

```text
package/
  sv/
    SimTop.sv
    SimTop_debug_part.sv
    SimTop_logic_part_repcut_part0.sv
    SimTop_logic_part_repcut_part1.sv
  manifest.json
  Makefile
  units.mk
  partitioned_wrapper.h
  partitioned_wrapper.cpp
  verilate/
    debug_part.f
    part_0.f
    part_1.f
```

允许输出：

- `sv/*.sv`
- `manifest.json`
- `.h/.cpp`
- `Makefile`
- `.mk`
- `.f`

不允许输出：

- 新 RTL wrapper
- 新组合后的 SV 模块
- package 外再复制第二份等价 SV

输出包里的 `sv/` 目录就是后续所有构建的唯一 SV 来源。

## 6.1 组合方式

`emitVerilatorRepCutPackage` 与当前 SV 发射能力的组合方式不是串联，而是包含关系。

正确关系应写成：

- `emitVerilatorRepCutPackage = sv emit + manifest + C++ wrapper + Makefile`

错误关系是：

- `sv emit -> 生成一份 sv`
- `emitVerilatorRepCutPackage -> 再复制一份 sv + 其他文件`

后者会引入两套 SV 副本，不允许。

## 6.2 目录语义

建议 package 目录中的各部分语义如下：

- `sv/`
  - 当前 design 唯一一份 emitted SV
- `manifest.json`
  - 对 `sv/` 中这些模块与 `SimTop` 内部实例关系的结构化描述
- `partitioned_wrapper.h/.cpp`
  - 直接消费 `manifest.json` 所描述的现有单元，不再生成新的 RTL
- `verilate/*.f`
  - 指向 `sv/` 中现有单元的 Verilator 文件列表
- `Makefile` / `units.mk`
  - 直接以 `sv/` 为输入构建全部单元与最终后端

## 6.3 Verilator 文件列表示意

例如：

- `verilate/part_0.f` 内应直接引用 `sv/SimTop_logic_part_repcut_part0.sv`
- `verilate/debug_part.f` 内应直接引用 `sv/SimTop_debug_part.sv`

如果某个单元编译需要额外公共文件，也应引用 package 内的 `sv/` 内容，而不是外部目录。

## 6.4 emit 组织方式

`emitVerilatorRepCutPackage` 不应实现成一份完全独立、重新复制一遍 SV 发射逻辑的特殊路径。

这里的实现约束是：

- wolvrix 的 emit 需要组织成一组不同类型的 emit
- emit 之间共享公共基础设施
- `emitVerilatorRepCutPackage` 复用现有 SV 发射能力
- 不能平行复制一份新的 SV emit 代码

建议的代码组织方向：

- 公共 emit 基类，或公共 emit 组件
- 共享的 SV 发射逻辑
- `emitVerilatorRepCutPackage` 在共享 SV 发射逻辑之上补充 package 工件输出

如果按继承组织，建议：

- 基类负责公共发射流程与共享工具
- 派生 emit 负责各自附加工件

这里的目的只有一个：

- 避免重复代码

不允许出现的实现形态：

- 现有 SV emit 一套代码
- `emitVerilatorRepCutPackage` 再抄一套几乎一样的 SV emit 代码

## 7. `manifest.json` 内容

`manifest.json` 只描述当前已有单元和当前已有连线。

### 7.1 顶层信息

必须包含：

- `top_module`
- 顶层输入列表
- 顶层输出列表

这里不应额外要求单一 `clock_port` / `reset_port` 字段。

原因是 post-repcut 设计可能存在：

- 多个 clock
- 多个 reset
- 非标准命名的时序控制输入

因此第一版 package manifest 只保留“顶层输入列表/顶层输出列表”这一层结构事实；是否把其中哪些输入当作 clock 或 reset，由上层 runtime / emulator 配置决定，而不是由 manifest 强加单一语义。

### 7.2 单元列表

每个单元必须至少记录：

- `instance_name`
- `module_name`
- `source_sv`

单元直接对应当前 `SimTop` wrapper 内的实例，例如：

- `debug_part`
- `part_0`
- `part_1`

### 7.3 端口列表

每个单元端口必须至少记录：

- `name`
- `direction`
- `width`
- `signed`

### 7.4 连线列表

每条边界连线必须至少记录：

- `signal`
- `width`
- `signed`
- `driver`
- `sinks`
- `kind`

`kind` 建议限制为以下四类：

1. `top_to_unit`
2. `unit_to_unit`
3. `unit_to_top`
4. `const_to_unit`

### 7.5 串行求值顺序

必须包含：

- `serial_eval_order`

该字段用于第一版串行基线运行。

### 7.6 可选并行提示

可选包含：

- `parallel_batches`

该字段只表示对现有单元的运行时并行批次建议，不表示任何新的 RTL 结构。

## 8. C++ 输出内容

新入口必须直接生成可编译的 C++ wrapper。

建议文件：

- `partitioned_wrapper.h`
- `partitioned_wrapper.cpp`

其职责是实现一个新的 `Simulator` 子类，例如：

- `PartitionedVerilatorSim`

该类必须完成：

1. 持有所有现有单元的 Verilated 对象。
2. 保存跨单元信号缓存。
3. 按 `serial_eval_order` 做串行基线求值。
4. 可选按 `parallel_batches` 做运行时并行。
5. 对外提供与当前 `VerilatorSim` 等价的接口。

这里新增的是 C++ wrapper，不是 RTL wrapper。

## 9. Makefile 输出内容

新入口必须直接生成可用的构建描述。

### 8.1 单元 Verilator 编译规则

需要覆盖：

- `debug_part`
- `part_*`

每个单元独立编译。

### 8.2 C++ wrapper 编译规则

需要把：

- `partitioned_wrapper.cpp`
- `difftest` 现有 C++ 代码
- 每个单元的 Verilator 输出

链接为一个可执行后端。

### 8.3 顶层目标

至少需要：

- 一个构建目标
- 一个运行目标

## 10. 单元编译规则

每个当前已有单元独立执行 Verilator。

示意：

```bash
verilator --cc SimTop_logic_part_repcut_part0.sv \
  --top-module SimTop_logic_part_repcut_part0 \
  --prefix VSimTop_logic_part_repcut_part0 \
  --Mdir build/xs/repcut-partitioned/verilated/part_0
```

要求：

- 每个单元使用单线程 Verilator
- 不依赖 Verilator `--threads`

## 11. 运行时语义

第一版运行时必须先做串行正确性基线。

对一个 `step()`，处理流程应为：

1. 写入当前拍顶层输入。
2. 按 `serial_eval_order` 逐个处理单元。
3. 对当前单元散播输入。
4. 调用该单元 `eval()`。
5. 回收该单元输出到边界缓存。
6. 必要时更新顶层输出缓存。

该流程必须先与当前 monolithic `VSimTop` 对齐。

## 12. 输入散播

单元输入来源只允许来自以下几类：

1. 顶层输入
2. 常量
3. 其他单元已发布到边界缓存的输出

运行时不允许做名字反射式查找。

应由新入口直接生成静态散播代码。

## 13. 输出回收

单元输出回收目标只允许来自以下几类：

1. 边界缓存
2. 顶层输出缓存

每条边界信号必须满足：

- 恰好一个驱动者
- 零个或多个消费者

多驱动必须在生成阶段报错。

## 14. `difftest` 接口

新的 C++ wrapper 必须对齐当前 `Simulator` 接口，至少包括：

- `set_clock`
- `set_reset`
- `step`
- `get_difftest_exit`
- `get_difftest_step`
- UART 相关访问接口

如需处理 finish 状态，建议扩展：

- `got_finish()`

由 `PartitionedVerilatorSim` 统一聚合各单元状态。

## 15. 时钟语义

上层 `Emulator::single_cycle()` 的外部语义保持不变：

1. `set_clock(1)`
2. `step()`
3. `step_uart()`
4. `set_clock(0)`
5. `step()`

因此 `PartitionedVerilatorSim::step()` 的语义应为：

- 在当前时钟电平下完成一次完整多单元求值

## 16. 并行语义

并行只允许作为串行基线跑通后的运行时优化。

允许的并行单位：

- 当前已有单元

不允许的并行前提：

- 先生成新的 RTL grouping
- 先重写现有 wrapper

如果启用 `parallel_batches`，规则是：

- 批次内部单元并行执行
- 批次之间使用 barrier
- 前一批次输出全部发布后，下一批次才能开始

`debug_part` 第一版建议固定在主线程执行。

## 17. 实施顺序

### P0

实现唯一入口，直接产出完整 package。

### P1

各现有单元独立 Verilate。

### P2

生成并编译 `PartitionedVerilatorSim`，按 `serial_eval_order` 运行。

### P3

在串行结果稳定后，再启用 `parallel_batches`。

## 18. 验收

### 18.1 结构验收

必须满足：

- 只新增 `emitVerilatorRepCutPackage`
- 没有新增 RTL wrapper
- 没有新增 `group_*.sv`
- 没有第二阶段生成工具

### 18.2 构建验收

唯一入口输出的 package 可以直接构建。

### 18.3 正确性验收

先在串行模式下对齐当前 monolithic repcut emu：

- `difftest_step`
- `difftest_exit`
- UART 输出
- trap code

并行不作为第一验收条件。
