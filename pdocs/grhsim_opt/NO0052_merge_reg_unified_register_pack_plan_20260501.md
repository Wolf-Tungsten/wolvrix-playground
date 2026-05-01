# NO0052 `merge_reg` 统一寄存器合并 Pass 方案

## 1. 背景

当前围绕“打散寄存器收回”的工作已经分成几条相近但分散的路线：

- `scalar-memory-pack`：把按 index 展开的 scalar register 恢复成 memory-like 状态。
- `record-slot-repack`：把同一 slot 的多个 field 重新打包成更宽的 row / record。
- 新发现的 `AXI4IntrGenerator.REG_*`：不是 memory-like 动态访问，而是长移位链，适合合并成一个宽寄存器。

这些路线的共同点是：

- 输入都先从一组 `kRegister` 出发。
- 都需要自然数排序，而不能用纯字典序，否则 `REG_35` 会插在 `REG_349` 和 `REG_350` 之间。
- 都要证明 rewrite 能减少 port 数、状态节点数或 emit/runtime 成本。
- 都需要输出完整 merged / residual 列表，方便逐个排查。

因此推荐新增一个上层 pass：

- pass 名称：`merge_reg`
- 定位：统一的 register cluster discovery + 多 strategy rewrite 框架
- 现有 `scalar-memory-pack` 可作为其中一个 strategy，而不是继续单独扩成所有形态的总入口。

## 2. 核心结论

`merge_reg` 不应等同于“凡是名字连续就合并”。它应该先统一找候选 cluster，再按访问形态选择具体 rewrite strategy。

第一批 strategy 建议包括：

| Strategy | 输入形态 | 输出形态 | 主要收益 |
| --- | --- | --- | --- |
| `ScalarToMemory` | `N` 个等宽 scalar register，读侧 concat/dynamic slice，写侧 point/fill | `kMemory` + read/write/fill ports | 减少 register 数，把 dynamic indexed read/write 收回成 memory 端口 |
| `RecordSlotToWideMemory` | 多个 field family 共享 slot index | 更宽 row 的 `kMemory` | 减少 memory 数和多 field 端口，改善 slot locality |
| `ShiftChainToWideRegister` | `REG_i <= REG_{i-1}` 长链，同 clock/reset/write event | 1 个宽 `kRegister` + slice taps | 把大量 register read/write ports 降成少量宽端口 |
| `ParallelLaneToWideRegister` | 多个 scalar bit/field 总是并行读写 | 1 个宽 `kRegister` | 把静态 lane fanout 从多端口改成宽读 + slice |

其中 `cpu$l_simMMIO$intrGen$REG_*` 属于 `ShiftChainToWideRegister`，不是 `ScalarToMemory`。

## 3. Pass 分层设计

### 3.1 Stage A: Register Inventory

先构建全图寄存器清单，输出稳定的基础视图：

- register symbol
- width / signedness / value type
- source location
- read ports
- write ports
- event operands / event edge
- all read-value users
- all write-data defining cone root

这一步同时生成调试产物：

- `merge_reg_all_registers_sorted.txt`
- `merge_reg_merged_registers.txt`
- `merge_reg_residual_registers.txt`
- `merge_reg_rewrite_plans.json`
- `merge_reg_reject_summary.json`

排序必须使用自然数排序：

- `REG_9 < REG_10 < REG_35 < REG_345`
- `field_2_value < field_10_value`

纯字典序只允许作为 tie-breaker，不能作为 index 顺序。

### 3.2 Stage B: Cluster Discovery

cluster discovery 只负责提出候选，不负责决定 rewrite。

候选来源：

- 名字分解：公共前缀 + 一个或多个 numeric index + 公共后缀。
- location 邻近：声明行号连续或近似连续。
- access 同构：read/write port 数量、event edge、width 等一致。
- 已有 report/resume 信息：复用前一次排序和 residual 列表，避免每个 strategy 重复扫全图。

候选 cluster 的最小数据结构：

```text
RegisterCluster {
  cluster_id
  members: [RegisterMember]
  index_axes: [axis0, axis1, ...]
  natural_order
  common_width
  common_event_signature
  read_summary
  write_summary
}
```

这里名字只用于形成候选。最终是否 rewrite 必须由 strategy 用图结构证明。

### 3.3 Stage C: Strategy Analysis

每个 strategy 读取同一个 `RegisterCluster`，返回：

```text
RewritePlan {
  strategy
  members
  new_state_shape
  read_port_delta
  write_port_delta
  operation_delta_estimate
  required_ir_ops
  safety_proof_summary
  reject_reason
}
```

统一收益门槛：

- 若不能减少 read/write port，默认不 rewrite。
- 若 port 不变但能显著减少 state declaration / emit 代码量，必须显式标记为 secondary benefit。
- 若只是把 `N` 个 register read 换成 `N` 个常量地址 memory read，拒绝。
- 若会增加端口数，除非后续 strategy 能继续合并，否则拒绝。

### 3.4 Stage D: Conflict Resolution

同一 register 只能被一个 final plan 拥有。

冲突处理顺序建议：

1. 优先选择 `read_port_delta + write_port_delta` 最大的 plan。
2. port delta 相同，优先选择覆盖 member 更多的 plan。
3. 覆盖相同，优先选择 IR 更简单的 plan：wide register 优先于 wide memory，wide memory 优先于多个 memory。
4. 若两个 plan 有交叉但不能包含，全部拒绝并输出 conflict report，避免部分 rewrite 破坏后续排查。

### 3.5 Stage E: Rewrite And Reports

rewrite 后必须输出 per-strategy 统计：

- candidate clusters / members
- accepted clusters / members
- rejected clusters / members
- read/write port before/after
- register count before/after
- memory count before/after
- top reject reasons
- merged member full list

报告格式要和当前 `scalar_memory_pack_merged_registers.txt` 对齐，方便继续用 `comm` / `rg` 做集合差。

## 4. Strategy 设计

### 4.1 `ScalarToMemory`

这是当前 `scalar-memory-pack` 的归宿。

适用条件：

- cluster members 等宽、同 signedness、同 event signature。
- 读侧能证明是“把 rows 拼成 aggregate，再按 index 取 row”。
- 写侧能证明是 point update / fill / mixed point-fill。
- dynamic read 能把多个 scalar read port 收敛成少量 `kMemoryReadPort`。

拒绝条件：

- 每个 member 只是被直接读一次，且没有共享 indexed read。
- rewrite 后仍然需要为每个 member 生成一个常量地址 read port。
- 写侧条件无法归一到 row index 或 fill 语义。

`cpu$l_simMMIO$fixer$flight_*` 一类 direct-read + OR-reduction 不应由此 strategy 接收，因为它不能减少 read port。

### 4.2 `RecordSlotToWideMemory`

目标是把同一 slot 的多个 field memory 合并成宽 row memory。

典型输入：

```text
slot_0_pc, slot_1_pc, ...
slot_0_exceptionVec_0, slot_1_exceptionVec_0, ...
slot_0_valid, slot_1_valid, ...
```

推荐输出：

```text
mem_slot_record[slot] = {pc, exceptionVec_0, valid, ...}
```

适用条件：

- 多个 field family 共享同一个 slot index axis。
- 读写地址或 lane enable 能在 slot 维度对齐。
- field 间 event signature 兼容。
- 每个 field 可映射到宽 row 的固定 bit range。

收益：

- 减少 memory 数。
- 合并同 slot 多 field read/write。
- 降低 generated code 中分散 state 访问。

保守限制：

- 第一版只支持同 clock/event 的 fields。
- 第一版不跨 module / instance 边界。
- 若 field 写入优先级不同，必须先能统一成同序 priority plan，否则拒绝。

### 4.3 `ShiftChainToWideRegister`

目标是吃掉 `REG_i <= REG_{i-1}` 这种长移位链。

`AXI4IntrGenerator` 里的形态：

```verilog
REG <= _w_fire_T & (|nodeIn_w_bits_data);
REG_1 <= REG;
REG_2 <= REG_1;
...
REG_999 <= REG_998;
```

可改写成：

```verilog
REG_vec <= {REG_vec[N-1:0], new_bit};
```

在 GRH 中，对应为：

- 1 个宽 `kRegister`
- 1 个 `kRegisterReadPort`
- 1 个 `kRegisterWritePort`
- 若外部仍需要 `REG_i` 的值，用 constant slice 从宽 read value 取 bit

接受条件：

- members 按自然数顺序形成连续链。
- `write(REG_i)` 的 data 来自 `read(REG_{i-1})`，首项来自同一外部 input。
- reset/fill 值同构，通常是全 0。
- clock / event edge / updateCond 完全一致。
- read value 除了进入下一项 write cone，可以有额外 tap，但 tap 必须能替换为 slice。

收益判断：

- 原始：约 `N` 个 register read ports + `N` 个 register write ports。
- 改写：1 个 wide register read port + 1 个 wide register write port + `N` 个 cheap slice。
- 因此这是明确减少 port 的 rewrite。

拒绝条件：

- 链中有断点、反向边、跳步边。
- 某些 member 有额外独立写源。
- 某些 member event signature 不一致。
- 某些 read user 需要 symbol identity，而不能被 slice 替代。

### 4.4 `ParallelLaneToWideRegister`

目标是吃掉“静态并行 lane”而不是 shift chain。

适用形态：

- 一组 1-bit 或小宽度 register 总是一起读。
- 写侧也是同一 event 下并行更新。
- 没有 dynamic row address，不适合 memory。
- 合并后能用一个宽 read + slices 替代多个 read ports。

这类 strategy 适合作为 `ShiftChainToWideRegister` 之后的第二阶段，因为它更容易误伤独立状态，必须依赖更强的读写同构证明。

## 5. IR 与 Emitter 要求

### 5.1 宽寄存器路径

现有 `kRegister` 已有 `width`，理论上可以直接表达宽寄存器。

需要确认并补齐：

- constant slice 对宽 register read value 的表达是否稳定。
- concat 构造 next wide value 的 emitter 是否不会展开成大量临时状态。
- debug / declared symbol 保留策略：原 scalar symbol 若仍需可见，只能作为 alias/slice，不应继续作为真实 state。

### 5.2 Memory 路径

`ScalarToMemory` 继续依赖：

- `kMemory`
- `kMemoryReadPort`
- `kMemoryWritePort`
- `kMemoryFillPort`，若已有实现则复用；若未完整落地，需要按 `NO0047` 的语义补齐。

`RecordSlotToWideMemory` 需要额外确认：

- memory row width 可以承载 packed record。
- partial field write 可以表达为 mask write，或拆成多个 write port。
- read side field extraction 可以用 slice 表达。

第一版不建议新增复杂 IR。优先用已有 wide value + slice + mask write 组合表达。

## 6. 与现有 Pass 的关系

推荐迁移路径：

1. 保留现有 `scalar-memory-pack` pass 名称和 CLI，避免打断当前 probe。
2. 新增内部公共库：`RegisterClusterAnalyzer` / `MergeRegPlanner`。
3. 让 `scalar-memory-pack` 先调用公共 discovery，再只启用 `ScalarToMemory` strategy。
4. 新增 `merge-reg` pass，默认启用多个 strategy。
5. probe 脚本逐步从 `xs_scalar_memory_pack_probe.py` 扩展为 `xs_merge_reg_probe.py`，但保留旧脚本作为兼容入口。

这样能避免一次性大重构，同时保证排序、report、resume checkpoint 不再重复实现。

## 7. Probe 与恢复点

`merge_reg` probe 应继承当前已验证有效的流程：

- 默认不跑昂贵 stats。
- 支持 `--with-stats` 显式打开。
- 支持 `--resume-checkpoint-json` 从 `after_flatten_simplify.json` 恢复。
- 每个 strategy 输出独立 report。
- 总 report 输出统一 merged/residual 列表。

推荐输出目录结构：

```text
build/xs/merge_reg_resume_nostats_YYYYMMDD/
  merge_reg_all_registers_sorted.txt
  merge_reg_merged_registers.txt
  merge_reg_residual_registers.txt
  merge_reg_plans.json
  merge_reg_reject_summary.json
  strategy_scalar_to_memory_merged.txt
  strategy_shift_chain_to_wide_register_merged.txt
  strategy_record_slot_to_wide_memory_merged.txt
```

## 8. 风险与防线

主要风险：

- 名字连续但语义不连续。
- 宽寄存器合并后破坏 declared symbol / debug symbol 预期。
- memory strategy 和 wide-register strategy 对同一 cluster 抢 ownership。
- port 数没有下降，只是把问题从 register port 搬到 memory port。
- rewrite 后 generated code 变大，抵消 state 数减少收益。

防线：

- 名字只做候选，图结构做最终判据。
- 每个 plan 必须写出 port delta。
- 默认拒绝无 port 收益的 rewrite。
- 每个 strategy 先支持 dry-run / report-only。
- replay 先只用 `after_flatten_simplify.json`，不反复跑 full stats。
- 对 `intrGen.REG_*`、`fixer.flight_*`、`tage usefulCtrs` 分别建立 targeted regression。

## 9. 第一阶段实施建议

第一阶段目标不要直接“一口吃所有寄存器合并”，而是把框架搭稳。

建议顺序：

1. 抽出自然数排序和 register inventory，生成 `all/merged/residual` 三类列表。
2. 把现有 `scalar-memory-pack` 改成一个 `ScalarToMemory` strategy，但保持行为不变。
3. 新增 report-only 的 `ShiftChainToWideRegister` analyzer，先验证 `cpu$l_simMMIO$intrGen$REG_*` 能完整识别。
4. 实现 `ShiftChainToWideRegister` rewrite，用局部单测覆盖 `REG_i <= REG_{i-1}`、reset、extra tap。
5. 在 XiangShan checkpoint 上 replay，不跑 stats，比较 register/readport/writeport 数。
6. 再考虑把 `record-slot-repack` 纳入 `RecordSlotToWideMemory` strategy。

验收口径：

- 对 `intrGen.REG_*`：应减少约 `N-1` 个 register read ports 和 `N-1` 个 write ports。
- 对 `fixer.flight_*`：应保持 reject，并给出“direct read does not reduce ports”原因。
- 对既有 `scalar-memory-pack`：rewritten members 不应回退。
- 所有 merged full list 可复现，且 residual 差集可直接用文本工具排查。

## 10. 当前推荐决策

推荐创建 `merge_reg`，但不要把所有逻辑硬塞进当前 `scalar-memory-pack`。

理由：

- `ScalarToMemory` 和 `ShiftChainToWideRegister` 的收益模型不同。
- 前者恢复 array/memory access，后者恢复 packed/vector state。
- 二者共享 discovery、排序、report、checkpoint，但 rewrite IR 完全不同。
- 统一在 `merge_reg` 顶层做 ownership 和收益裁决，能避免后续多个 pass 互相抢同一组 register。

因此下一步最小闭环是：

- 公共 cluster inventory + natural sort
- `ScalarToMemory` strategy 兼容现状
- `ShiftChainToWideRegister` strategy 定向拿下 `AXI4IntrGenerator.REG_*`

## 11. 增量实现记录 2026-05-01

已落地一个 `merge-reg` MVP：

- 新增 pass：`merge-reg`
- 新增源码：
  - `wolvrix/include/transform/merge_reg.hpp`
  - `wolvrix/lib/transform/merge_reg.cpp`
  - `wolvrix/tests/transform/test_merge_reg.cpp`
- 已接入：
  - `wolvrix/lib/core/transform.cpp`
  - `wolvrix/CMakeLists.txt`

当前实现范围：

- 已实现 `ShiftChainToWideRegister` strategy。
- 已实现 register inventory 的最小子集：register symbol、width、signedness、initValue、read/write ports。
- 已实现 trailing numeric index 的自然数排序。
- 已支持 `REG` + `REG_1...` 这类 base + indexed family，也支持 `REG_9, REG_10...` 这类非零起点连续 family。
- 已支持把旧 scalar read value 替换为 wide register read 的 `kSliceStatic`。
- 已支持把原各 member 的 write-data / mask 按自然数顺序 concat 后写入一个宽 `kRegisterWritePort`。

保守接受条件：

- 每个 member 只能有 1 个 `kRegisterReadPort` 和 1 个 `kRegisterWritePort`。
- member width、signedness、updateCond、event operands、`eventEdge` 必须一致。
- 若存在 initValue，当前只接受全 0 初始化。
- 必须能证明第 `i` 个 member 的 write-data cone 引用第 `i-1` 个 member 的 read value。
- 最小 chain 长度当前为 4，用于避免小规模偶然模式误合并。

明确未完成：

- 尚未把现有 `scalar-memory-pack` 迁移成 `ScalarToMemory` strategy；当前它仍是独立 pass。
- 尚未把 `record-slot-repack` 迁移成 `RecordSlotToWideMemory` strategy。
- 尚未输出 `merge_reg_all_registers_sorted.txt` / merged / residual report。
- 尚未跑 XiangShan checkpoint replay 验证 `AXI4IntrGenerator.REG_*` 的真实命中量。

已验证：

```bash
cmake --build wolvrix/build --target transform-merge-reg
ctest --test-dir wolvrix/build --output-on-failure -R transform-merge-reg
ctest --test-dir wolvrix/build --output-on-failure -R 'transform-(pass-manager|merge-reg|scalar-memory-pack)'
```

测试覆盖：

- `REG_9 -> REG_10 -> REG_11 -> REG_12` 能按自然数顺序识别并合并成 1 个宽 register/read/write。
- 外部 tap 会被替换成 wide read 的 `kSliceStatic`。
- self-hold direct-read family 不会被合并。

下一步建议：

1. 给 `merge-reg` 增加 report-only / merged-list 输出，格式对齐当前 `scalar_memory_pack_merged_registers.txt`。
2. 用现有 `after_flatten_simplify.json` replay `merge-reg`，确认 `cpu$l_simMMIO$intrGen$REG_*` 的真实命中量和 read/write port delta。
3. 再决定是否把 `merge-reg` 串到 XiangShan grhsim 默认 pipeline 中；在 replay 前不建议默认启用。
