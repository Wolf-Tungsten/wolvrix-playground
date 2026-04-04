# `write_sv` 扩展修改计划

## 背景

当前 `write_sv(output, top=None)` 的 `top` 参数只参与 top graph 解析与校验：

- 若未提供 `top`，使用 `design.topGraphs()`
- 若提供了 `top`，校验对应 graph 是否存在
- 若解析后没有任何 top graph，则报错

但在 `EmitSystemVerilog::emitImpl(...)` 中，实际输出时仍然遍历整个 design 的全部 graph，因此：

- `top` 不能决定输出哪些模块
- 只要 `top` 名字合法，最终输出内容通常仍是全量模块

本次修改将把 `top` 变成真正的输出裁剪条件，并为 `write_sv` 增加“每个模块单独输出一个 `.sv` 文件”的选项。

## 目标

本次改动包含两个行为目标：

1. `top` 语义改为：只输出从指定 top graph 出发可达的模块集合。
2. 为 `write_sv` 增加 `split_modules` 选项，允许将每个输出模块单独写入一个 `.sv` 文件。

默认兼容性要求：

- `split_modules=False` 时仍保持单文件输出模式
- 未显式传入 `top` 时，仍以 `design.topGraphs()` 作为起点
- 输出集合从“全 design”收紧为“top 可达子图”

## 目标接口

建议将 Python 接口扩展为：

```python
design.write_sv(output, top=None, split_modules=False)
```

建议语义如下：

- `split_modules=False`
  - `output` 表示单个输出文件路径
  - 将所有可达模块按既有顺序写入同一个 `.sv` 文件
- `split_modules=True`
  - `output` 表示输出目录路径
  - 每个可达模块单独写入 `<module_name>.sv`

## 行为定义

### 1. top 可达模块集合

输出模块集合定义为：

- 以 `top` 指定的 graph 为起点；若 `top` 为空，则以 `design.topGraphs()` 为起点
- 遍历 graph 中的模块实例关系
- 收集所有可递归到达的 graph
- 最终仅输出该可达集合中的模块

这里的“可达”应基于 GRH 中的实例化关系，而不是字符串扫描或 emit 阶段的文本依赖。

### 2. top 参数的错误语义

以下情况保持报错：

- `top` 中存在找不到的 graph 名称
- 解析后 top 集合为空
- 遍历实例关系时遇到无法解析的目标 graph，若当前 emitter 已将其视为硬错误，则保持一致

### 3. split_modules 的路径语义

建议明确约束：

- `split_modules=False` 时，`output` 必须是目标文件路径
- `split_modules=True` 时，`output` 必须是目标目录路径

不建议在 `split_modules=True` 时自动猜测 `output` 是目录还是文件，因为这会让 API 行为变得模糊。若传入明显带 `.sv` 后缀的路径，建议直接报错。

### 4. 文件命名

分文件模式下建议使用 emitter 最终决定的模块名作为文件名：

```text
<emitted_module_name>.sv
```

原因：

- 与文件内 `module <name>` 保持一致
- 可复用现有 alias 选择与重名规避逻辑
- 不需要再引入额外的文件名映射规则

## 非目标

本次不做以下扩展：

- 不新增文件名模板、前缀、子目录分层等高级输出选项
- 不改变 `write_json` 或 `to_json` 的行为
- 不修改设计 IR，仅修改 emit 侧的输出选择与落盘方式

## 修改范围

### 1. Python API

文件：

- `wolvrix/app/pybind/wolvrix/__init__.py`

修改点：

- 为 `Design.write_sv(...)` 增加 `split_modules: bool = False`
- 将新参数传递给 native 层

### 2. pybind/native 入口

文件：

- `wolvrix/app/pybind/wolvrix_native.cpp`

修改点：

- 扩展 `py_write_sv(...)` 的 kwlist 与参数解析
- 将 `split_modules` 填入 `EmitOptions`
- 根据 `split_modules` 决定如何解释 `output`
  - 单文件模式：拆成 `outputDir + outputFilename`
  - 分文件模式：仅设置 `outputDir`
- 更新方法签名字符串说明

### 3. EmitOptions

文件：

- `wolvrix/include/core/emit.hpp`

修改点：

- 为 `EmitOptions` 增加布尔选项，例如 `splitModules = false`

### 4. Emit 侧输出集合裁剪

文件：

- `wolvrix/lib/core/emit.cpp`

修改点：

- 在 `Emit::emit(...)` 或 `EmitSystemVerilog::emitImpl(...)` 中引入“从 top graph 出发求可达 graph 集合”的逻辑
- 后续模块遍历不再直接使用整个 design 的 graph 集合，而是只遍历可达集合

建议实现方式：

- 新增一个 helper，输入为 `design + topGraphs`
- 通过 graph 内的实例 operation 找到被实例化模块
- 返回去重后的 `std::vector<const Graph*>` 或等价集合
- 再基于该集合做稳定排序，保持输出顺序可预测

### 5. Emit 侧落盘逻辑重构

文件：

- `wolvrix/lib/core/emit.cpp`

修改点：

- 将“单个 graph 输出为一个 module 文本”的逻辑抽成 helper
- 单文件模式：
  - 打开一个输出文件
  - 将可达集合中的模块依次写入
- 分文件模式：
  - 为每个可达模块单独打开一个输出文件
  - 每个文件只写一个 module
- `EmitResult.artifacts` 在分文件模式下记录全部产物路径

## 实现顺序

建议按以下顺序实施，降低回归风险：

1. 提炼 `EmitSystemVerilog` 中“输出单个 module”的逻辑，保证单文件模式仍可工作。
2. 引入“top 可达 graph 集合”计算，并先让单文件模式只输出可达模块。
3. 补齐单测，确认 `top` 已真正影响输出内容。
4. 增加 `split_modules` 参数与分文件落盘逻辑。
5. 增加分文件模式测试。
6. 更新 README 或相关说明文档。

## 测试计划

### 1. 保持现有测试通过

现有 emit 测试应继续通过，但其中依赖“全量输出”的测试如果存在，需要按新语义调整预期。

### 2. 新增 top 可达性测试

建议新增一个 emit 测试，构造如下设计：

- `top_a` 实例化 `mid`
- `mid` 实例化 `leaf`
- `orphan` 不被任何 top 引用

测试点：

- `top=["top_a"]` 时，输出包含 `top_a`、`mid`、`leaf`
- `top=["top_a"]` 时，输出不包含 `orphan`
- `top=["orphan"]` 时，只输出 `orphan`

### 3. 新增 split_modules 测试

建议新增一个 emit 测试，构造至少两个可达模块，并打开 `splitModules`。

测试点：

- `EmitResult.artifacts.size()` 等于输出模块数
- 每个 artifact 文件存在
- 每个文件只包含一个 `module ... endmodule`
- 文件名与实际 emitted module name 一致
- 不可达模块没有对应输出文件

### 4. Python 层冒烟检查

若仓库已有 Python 侧调用用例，建议补一个最小冒烟验证：

```python
design.write_sv("out.sv", top=["top_a"])
design.write_sv("out_dir", top=["top_a"], split_modules=True)
```

重点验证：

- 参数链路没有断
- 错误信息能正确透传

## 风险点

### 1. 可达性遍历依赖实例关系解析

如果当前 GRH 中的实例 operation 既可能引用 graph symbol，也可能引用 alias 或参数化实例名，需要先统一“如何从实例拿到目标 graph”这件事，否则可达性遍历容易漏模块。

### 2. top 语义变更是行为变化

即使不传 `top`，最终输出也会从“全量 design”收紧为“默认 top 可达子图”。如果某些脚本依赖当前“顺手把 orphan graph 也写出来”的行为，需要同步评估影响。

### 3. 分文件模式的 DPI / 公共依赖输出

若 emitter 存在“跨模块汇总”的输出内容，例如 DPI import 或公共声明，需要确认它们应：

- 复制到每个需要的模块文件中
- 还是只写入相关模块文件

原则上应以“单个 `.sv` 文件可独立承载该模块定义”为准，但不能引入重复定义冲突。

## 文档更新建议

实现完成后建议同步更新：

- `wolvrix/README.md`
- `wolvrix/app/pybind/wolvrix_native.cpp` 中的方法说明字符串

建议补充的用户示例：

```python
design.write_sv("build/out.sv", top=["Top"])
design.write_sv("build/sv_out", top=["Top"], split_modules=True)
```

并明确说明：

- `top` 会裁剪输出模块集合
- `split_modules=True` 时 `output` 是目录，不是文件

## 结论

本次修改应把 `write_sv` 从“只有 top 校验、始终全量输出”的行为，收敛为“按 top 可达子图输出”，并在此基础上增加可选的分模块落盘能力。推荐优先完成可达性裁剪，再叠加分文件输出，以便问题定位和回归验证都更清晰。
