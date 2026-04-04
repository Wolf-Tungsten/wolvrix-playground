# 剥离逻辑与调试支持 Pass 规划（top_ext / top_int 拆分）

## 目标
- 对**所有顶层模块**逐一执行相同的拆分流程。
- 将 `kDPICall`（及关联的 `kDPIImport`）、`kSystemTask`、层次结构操作（`kInstance`、`kBlackbox`）迁移到 `*_ext` 模块。
- 将原始顶层模块重命名为 `*_int`，并在其端口上补齐必要的输入/输出以维持数据流等价。
- 生成新的顶层模块（保留原名），内部实例化 `*_ext` 和 `*_int` 并连接所有 value，确保与原设计等价。

## 非目标
- 不改变 IR 的语义规则、不引入新的优化。
- 不改变非顶层模块的层级结构与端口形态（仅作为被 `*_int` 实例化时的原样逻辑）。

## 术语与范围
- **顶层模块**：Design 中**明确标注为 top** 的模块（参考 GRH IR 说明）。
- **剥离操作**：`kDPICall`、关联的 `kDPIImport`、`kSystemTask`、以及层次结构操作 `kInstance` / `kBlackbox`。
- **常量提取**：若剥离操作的**输入操作数**来自常量（`kConstant`），则该常量也会被搬运/克隆到 `*_ext`。

## 命名与冲突规则
- 设原顶层模块名为 `top`。
- `top_int`：原 `top` 改名得到；若冲突则按 `top_int_1`, `top_int_2`... 递增。
- `top_ext`：新建模块名；若冲突则按 `top_ext_1`, `top_ext_2`... 递增。
- 新顶层模块名保持为 `top`。

## 总体流程（单个顶层模块）

### 1) 识别与分组
- 枚举 `top` 中的所有 op，收集剥离操作集合 `S_strip`。
- 对每个 `kDPICall`，收集其关联的 `kDPIImport`（符号或 op），加入 `S_strip`。
- 对 `S_strip` 中每个 op 的**直接输入操作数**：
  - 若来自 `kConstant`，记录为 `S_const`。
  - 其它输入记录为 **边界输入**（boundary-in）。

> 注：仅要求“输入操作数上的常量一并提取”，因此常量**只按直接输入收集**；若未来发现需求扩大为传递闭包，则在这里扩展。

### 2) 构建 top_ext
- 新建模块 `top_ext`，并在其中创建/克隆：
  - `S_strip` 中的操作。
  - `S_const` 中的常量（若常量在 `top` 中仍被其他逻辑使用，保留原常量并在 `top_ext` 中**克隆**一份）。
- 为所有 **boundary-in** 创建 `top_ext` 输入端口。
- 为所有剥离操作产生的结果值创建 `top_ext` 输出端口（仅当结果在 `top` 中仍被使用或驱动端口时）。
- 记录 value 映射：
  - `orig_value` -> `top_ext` 输入端口 value（用于驱动剥离 op 的输入）。
  - `strip_result` -> `top_ext` 输出端口 value（用于回传给 `top_int` 或顶层端口）。

### 3) 生成 top_int
- 将原 `top` 重命名为 `top_int`。
- 从 `top_int` 中移除 `S_strip` 与其“仅服务于剥离逻辑”的常量（`S_const` 中已无人使用者）。
- 在 `top_int` 中新增端口以维持数据流：
  - 对 **boundary-in** 的 value，在 `top_int` 增加**输出端口**，用于把值送给 `top_ext`。
  - 对剥离 op 的结果值，在 `top_int` 增加**输入端口**，用于接收 `top_ext` 的输出。
- `top_int` 保留原始 `top` 端口集合（即使某些端口在剥离后不再使用），以避免破坏外部接口。

### 4) 创建新 top 并连线
- 新建模块 `top`（与原名字一致），端口与**改造前**的 `top` 完全一致。
- 在 `top` 内部：
  - 例化 `top_int` 与 `top_ext`。
  - 连接原有顶层端口与 `top_int` 端口（保持等价）。
  - 根据边界映射连接 `top_int` 与 `top_ext`：
    - `top_int` 输出端口 -> `top_ext` 输入端口（boundary-in）
    - `top_ext` 输出端口 -> `top_int` 输入端口（剥离结果）
  - 若 `top_ext` 端口直接来自顶层端口（例如剥离 op 直接使用顶层输入），可直接连接 `top` 端口到 `top_ext`。

## 端口与 value 对齐规则
- 端口方向由数据流决定，**不**以 op 类型决定。
- 多结果 op：为每个结果值创建独立输出端口。
- 端口命名建议保持可追踪性：`ext_in_<orig>` / `ext_out_<orig>` / `int_out_<orig>` / `int_in_<orig>`（最终以实现中已有命名规范为准）。

## 诊断与日志建议
- 每个顶层模块：统计剥离 op 数量、剥离常量数、新增端口数。
- 冲突命名时输出一次提示，方便定位拓扑变更。
- 若发现未能解析的层次结构 op，输出 warning 并列出 op 类型。

## 风险与注意事项
- 关联 `kDPIImport` 的绑定关系必须保持一致，避免丢失 import 元数据。
- 常量的“搬运 vs 克隆”需谨慎：若常量仍被 `top_int` 使用，必须在 `top_ext` 中克隆。
- 新 `top` 的端口顺序与属性需与原 `top` 完全一致，避免外部接口不兼容。
- 层次结构操作范围固定为 `kInstance` / `kBlackbox`，避免遗漏或过度剥离。

## 落地步骤
1. 明确“层次结构操作”范围为 `kInstance` / `kBlackbox` 并对照 GRH 规格与实现。
2. 实现剥离集合收集与常量提取逻辑。
3. 构建 `top_ext`、改名生成 `top_int`、创建新 `top` 并连线。
4. 加入最小化回归用例（含 DPI/SystemTask/层次结构 op 与常量输入）。
