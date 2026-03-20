# instance-inline pass 实施草案（按层级路径单层内联）

## 1. 目标与范围

### 1.1 目标
新增一个 `transform` pass：`instance-inline`，用于对用户指定的**单个层级路径实例**执行内联。

示例：用户指定 `SimTop.u_dut.xyz`，pass 需要：
- 按路径在层次中定位到 `xyz` 对应的 `kInstance`；
- 将其引用的子模块 Graph 展开到当前父 Graph（实例化位置）；
- 仅展开这一层，不递归展开 `xyz` 内部的 `kInstance`。

### 1.2 非目标
- 不做全局扁平化（这不是 `hier-flatten` 的替代）。
- 不处理 `kBlackbox` 内联。
- 不自动选择目标实例（必须由用户显式指定）。
- 不递归展开子图中的内部 instance。

## 2. 前置条件与依赖

该 pass 建立在“XMR 已展开”基础上，运行前必须满足：
- 设计中不存在 `kXMRRead` / `kXMRWrite`。

建议在 pass 内做硬性检查（与 `hier-flatten` 类似）：
- 若发现 XMR op，直接报错并 `failed=true`：
  - `instance-inline requires xmr-resolve before inline`

推荐流水：
- `xmr-resolve` -> `instance-inline` -> 其它优化 pass（可选）

## 3. Pass 接口草案

## 3.1 名称
- `instance-inline`

### 3.2 参数
最小可用参数：
- `-path <hier_path>`（必填）
  - 示例：`-path SimTop.u_dut.xyz`
  - 也支持 `-path=SimTop.u_dut.xyz`

可选扩展（后续阶段）：
- 重复 `-path` 以一次内联多个实例。

## 4. 路径语义与定位规则

## 4.1 路径语义
采用绝对层级路径：
- 语法：`<rootGraph>.<inst1>.<inst2>...<targetInst>`
- 示例：`SimTop.u_dut.xyz`
  - `SimTop` 是 Graph 名
  - `u_dut` / `xyz` 是逐层 `instanceName`

## 4.2 定位算法
1. `split('.')` 得到 segments。
2. `segments.size() >= 2`，否则报错。
3. 用 `segments[0]` 在 `design.findGraph()` 定位 root graph。
4. 从 root graph 开始逐段查找 instance：
   - 在当前 graph 中按 `instanceName` 查找 `kInstance` op；
   - 中间 hop（非最后一段）必须能解析 `moduleName` 并找到 child graph；
   - 最后一段命中即 target instance。

## 4.3 失败条件
- root graph 不存在。
- 任意 hop 的 `instanceName` 不存在或不唯一。
- hop 的 `moduleName` 缺失，或 child graph 不存在。
- target op 不是 `kInstance`。

## 5. 一层内联语义定义

对 target instance `I`（位于父图 `G_parent`，引用子图 `G_child`）执行：

1. 在 `G_parent` 中删除 `I`（实现上建议 `eraseOpUnchecked`，见第 7 节）。
2. 将 `G_child` 的 op/value 克隆到 `G_parent`，并建立端口映射：
   - child 输入端口 value -> `I.operands` 对应值
   - child 输出端口 value -> `I.results` 对应值
   - child inout `{in,out,oe}` -> `I` 的 inout operand/result 映射
3. `G_child` 内部若有 `kInstance` / `kBlackbox`：
   - **按普通 op 克隆**，不继续展开。

这保证“只 inline 一层”。

## 6. IR 映射与重写细则

## 6.1 端口映射（必须严格校验）
设：
- `m = child.inputPorts().size()`
- `n = child.outputPorts().size()`
- `q = child.inoutPorts().size()`

则 target instance 必须满足：
- `operands.size() == m + q`
- `results.size() == n + 2*q`

映射关系：
- `child input[i]` -> `inst.operands[i]`
- `child inout[i].in` -> `inst.operands[m+i]`
- `child output[i]` -> `inst.results[i]`
- `child inout[i].out` -> `inst.results[n+i]`
- `child inout[i].oe` -> `inst.results[n+q+i]`

若存在 `inputPortName/outputPortName/inoutPortName` 属性，按名称对齐并校验数量；名称映射失败时报错。

## 6.2 Value 克隆
- child 端口 value 使用上述映射，复用父图已有 value。
- child 内部非端口 value：在父图新建 value，并记录 `childValue -> parentValue` 映射。
- 复制宽度、signed、type、srcLoc。

## 6.3 Operation 克隆
- 对 child 每个 op 创建等价新 op（kind 相同）。
- 操作数从 `valueMap` 重映射。
- 结果 value：
  - 若是端口映射到父图既有 value，则直接作为新 op result。
  - 若是内部值，则使用新建 value。
- 复制 `srcLoc` 与 attrs。

## 6.4 属性重写（关键）
对于引用“符号名”的 attr，需要进行 rename 回填，至少覆盖：
- `regSymbol`
- `memSymbol`
- `latchSymbol`
- `targetImportSymbol`

建议复用 `hier_flatten` 的两阶段策略：
- 第一阶段先拷贝 attrs；
- 若引用符号尚未生成，记入 `pendingAttrs`；
- 第二阶段根据 `opRename` 回填。

## 6.5 输出 alias 的处理
若 child 多个输出端口别名到同一 child value，而父图目标 results 是不同 value：
- 保留第一个映射结果；
- 对额外输出创建 `kAssign` 连接（源为已映射值，目标为该输出 value）。

避免出现“同一 value 多定义”冲突。

## 7. 实施流程（代码级）

## 7.1 数据结构建议

```cpp
struct InstancePathTarget {
  grh::Graph* rootGraph;
  std::vector<std::string> segments;
  std::vector<Hop> hops;      // parent graph + instance op + child graph
  grh::Graph* parentGraph;
  grh::OperationId targetInst;
  grh::Graph* childGraph;
};

using ValueMap = std::unordered_map<grh::ValueId, grh::ValueId, grh::ValueIdHash>;
```

## 7.2 执行阶段划分

### Phase A：Preflight（不改 IR）
- 全局 XMR 检查。
- 解析 `-path` 并定位 target。
- 校验 target instance 与 child graph 端口一致性。
- 准备端口映射与命名策略。

### Phase B：Rewrite（改 IR）
- `parentGraph.eraseOpUnchecked(targetInst)`，先移除旧定义，避免 result value 冲突。
- 克隆 child value/op 到 parent。
- 处理 `pendingAttrs`。
- 完成统计并 `changed=true`。

说明：
- 由于 `eraseOpUnchecked` 会先删目标 op，务必把所有可能失败的校验前置到 Phase A。

## 7.3 命名与冲突策略
- 新建内部 value/op 默认使用 `makeInternalValSym()` / `makeInternalOpSym()`。
- 对 stateful op（`kRegister/kMemory/kLatch`）或声明符号，建议使用层级前缀重命名：
  - 前缀来源：`<path_without_root>`，例如 `u_dut$xyz`。
- 通过 `internUniqueSymbol` 风格函数保证唯一性。

## 8. 代码落点

- 新增头文件：`wolvrix/lib/include/transform/instance_inline.hpp`
- 新增实现：`wolvrix/lib/transform/instance_inline.cpp`
- 注册入口：`wolvrix/lib/src/transform.cpp`
  - `availableTransformPasses()` 增加 `instance-inline`
  - `makePass()` 增加参数解析（`-path`）

后续补充正式文档：
- `wolvrix/docs/transform/instance-inline.md`

## 9. 诊断与统计

建议统计字段：
- `target_path_count`
- `target_resolved`
- `target_inlined`
- `ops_cloned`
- `values_cloned`
- `attrs_rewritten`
- `errors_path_not_found`
- `errors_port_mismatch`
- `errors_xmr_not_resolved`

诊断信息至少包含：
- `graph::op` 上下文
- 原始 `-path`
- 出错 hop（第几段 / 段名）

## 10. 测试计划

建议新增：`wolvrix/tests/transform/test_instance_inline_pass.cpp`

核心用例：
1. `inline_basic_one_level`
   - 路径 `SimTop.u_dut.xyz` 命中，验证 `xyz` 消失且子图 op 展开到 `u_dut` 所在父图。
2. `inline_non_recursive`
   - `xyz` 内部包含 `kInstance u_leaf`，inline 后 `u_leaf` 仍为 `kInstance`。
3. `inline_inout_mapping`
   - 验证 inout 的 `in/out/oe` 三路映射正确。
4. `inline_alias_output`
   - 子图多个输出别名同一 value，验证生成 `kAssign` 桥接。
5. `inline_path_not_found`
   - 路径中间段不存在，pass 报错。
6. `inline_xmr_guard`
   - 存在 XMR op 时，pass 直接失败。

## 11. 分阶段落地建议

### Phase 1（最小可用）
- 支持单个 `-path`。
- 支持普通 input/output 映射（无 inout 特殊 case 可先做，但建议一次做完）。
- 内部 `kInstance` 保留，不递归。

### Phase 2（完善兼容）
- 补全 inout、alias output、pending attrs 回填。
- 补全符号重命名与 declared symbol 保持策略。

### Phase 3（工程化）
- 增加多路径能力（可重复 `-path`）。
- 补全文档、统计、回归。

## 12. 关键伪代码

```cpp
PassResult InstanceInlinePass::run() {
  PassResult result;

  if (hasAnyXmr(design())) {
    error("instance-inline requires xmr-resolve before inline");
    result.failed = true;
    return result;
  }

  auto target = resolveTargetPath(design(), options_.path);
  if (!target.ok) {
    error(target.message);
    result.failed = true;
    return result;
  }

  // preflight: 校验端口/数量/模块一致性，不改 IR
  if (!validateTarget(*target)) {
    result.failed = true;
    return result;
  }

  auto& parent = *target->parentGraph;
  auto& child  = *target->childGraph;

  ValueMap portMap = buildPortMap(parent, child, target->targetInst);

  // 先删旧 instance，避免 outputs 已有 definingOp 冲突
  parent.eraseOpUnchecked(target->targetInst);

  RewriteState state;
  if (!cloneChildOneLevel(child, parent, portMap, state)) {
    result.failed = true;
    return result;
  }

  result.changed = true;
  return result;
}
```
