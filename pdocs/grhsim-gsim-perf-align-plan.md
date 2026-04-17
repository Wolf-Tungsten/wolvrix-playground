# GrhSIM 向 GSim 性能形态对齐计划

## Goal Description

在不破坏 `grhsim` 现有执行语义的前提下，围绕 emitter 和运行时数据组织做一轮结构性重构，使生成代码在静态形态和热路径行为上更接近 `gsim`，重点改善以下三类问题：

- 单个 active supernode / 活跃 word 处理段过重
- emitted cpp 拆分过细，编译和链接成本偏高
- `value_*_slots_[]` 式池化访问过多，抑制编译器优化

本轮计划围绕三条主线推进：

1. 收缩 supernode 的最大 op 数，降低单个 supernode body 的复杂度
2. 让 `grhsim` 的生成形态从外露的 `eval_batch_*` 直接收敛到更简单的 `subStep` 模式，并调整 file packing 让 emitted cpp 粒度更接近 `gsim`
3. 学习 `gsim` 的 value 组织方式，减少 slot，优先使用局部变量和明确命名的持久 typed value

## Acceptance Criteria

Following TDD philosophy, each criterion includes positive and negative tests for deterministic verification.

- AC-1: supernode 收缩改动必须以“降低 `grhsim` 自身 supernode body 复杂度”为目标，而不是继续使用 `grhsim op` 对 `gsim node` 的错误直接对齐口径。
  - Positive Tests (expected to PASS):
    - 计划和实现文档中明确写明 `grhsim op` 与 `gsim node` 语义不一致，不再用两者直接推导“数量应一致”。
    - emitter 支持调低 supernode 最大 op 后重新 emit，`activity_schedule_supernode_stats.json` 中的 `ops_per_supernode.mean` 或 `median` 出现下降趋势。
    - 重新 emit 后，热点活跃 word 处理段对应的单文件代码体积或单段 `// op` 数量出现下降趋势。
  - Negative Tests (expected to FAIL):
    - 任何实现或文档继续把 “`grhsim` supernode 数必须和 `gsim` 相同” 当成正确性或性能验收标准。
    - 在没有降低 body 复杂度的情况下，只靠调参让 supernode 数看起来更接近 `gsim`，但 emitted body 体积和 perf 无改善。

- AC-2: `grhsim` 的代码生成接口必须收敛到 `subStep` 模式，active-word 仅保留为内部调度粒度，不再对外暴露“一个 active-word 一个 `eval_batch_*` 函数”的形态；同时 emitted cpp 的 file packing 必须明显收敛，并保持现有 runtime active-word 调度语义不被破坏。
  - Positive Tests (expected to PASS):
    - emit 之后，`grhsim_emit` 中的 emitted `*.cpp` 文件数明显低于当前基线。
    - 生成代码中出现 `subStepN()` 式函数分块，而不是大规模外露的 `eval_batch_*` 函数集合。
    - `subStepN()` 成为主要的外部执行块；active-word 处理段仅作为其内部实现细节存在。
    - 一个 emitted cpp 中包含多个 active-word 处理段或多个 `subStep` body，文件拆分粒度更接近 `gsim`。
    - 运行时仍然按现有 active-word 机制调度，已有单元测试和至少一轮 HDLBits `grhsim` 回归通过。
  - Negative Tests (expected to FAIL):
    - 只是改文件名、后处理拼接或简单重命名，但 emit 逻辑本质上仍是一 active-word 一函数一文件。
    - 为了减少 emitted cpp 文件数或引入 `subStep` 形态而擅自改变 runtime active-word 调度语义，导致行为回归。

- AC-3: value storage 必须向“局部变量 + 持久 typed value”的混合模型演进，显著减少非必要的 `slot` 访问。
  - Positive Tests (expected to PASS):
    - supernode 内 temporary value 默认优先以局部变量形式发射，不再无条件 materialize 到 `value_*_slots_[]`。
    - 只有跨 supernode、跨周期或必须持久保存的 value 才保留为明确命名的持久 typed value。
    - 重新 emit 后，`value_*_slots_[]` 的静态访问量出现下降趋势。
    - 对典型热点 batch 的 `perf` 或静态代码检查显示，索引访存和中转变量数量下降。
  - Negative Tests (expected to FAIL):
    - 继续新增 `slot` 分类或扩大 slot 池规模，而不减少热路径中的 slot round-trip。
    - 把所有 value 一刀切升成顶层持久成员，导致头文件和代码体积失控，且无语义边界控制。

- AC-4: 本轮重构必须维持 `grhsim` 现有语义边界，不能跨越 side-effect / commit / event 保护边界错误去物化或合并。
  - Positive Tests (expected to PASS):
    - 现有 `ctest` 中与 `emit-grhsim-cpp`、`hdlbits grhsim` 相关的回归保持通过。
    - 对至少一个 XiangShan emit/build 流程能成功完成 emit，并输出新的规模统计。
    - 语义敏感对象如 `state` / `memory` / `shadow` / `evt_edge` 仍然维持独立管理，不被错误并入普通 temporary value 路径。
  - Negative Tests (expected to FAIL):
    - 为了降低 slot 数量而错误跨越 commit、write、event-edge 边界，导致已知行为回归。
    - 改动后无法重新 emit 或关键回归直接失败。

## Path Boundaries

Path boundaries define the acceptable range of implementation quality and choices.

### Upper Bound (Maximum Acceptable Scope)

实现完成以下内容：

- supernode 最大 op 可调，并在新的 emit 形态下重新找到更合理的复杂度区间
- file packing 从“一 batch 一 cpp”改为“多 batch / 多 body 一 cpp”
- supernode 内 temporary value 默认局部化，跨边界 value 明确转成持久 typed value
- `value_*_slots_[]` 静态访问量、emitted cpp 文件数、热点 `subStep` / 活跃 word 处理段体积都出现可观下降
- 对 XiangShan 路径完成一轮 emit + build + perf 复测，记录趋势变化

### Lower Bound (Minimum Acceptable Scope)

至少完成以下内容：

- 明确修正 supernode 调优目标，不再使用错误的 `op/node` 对齐口径
- 实现 `subStep` 模式和 emitted cpp file packing 收敛，减少 emitted cpp 文件数
- 在一个可证明的 emitter 子集内，把 same-supernode temporary value 改为局部变量优先，减少一部分 `slot` 访问
- 保持现有回归通过，并输出一轮新的静态规模统计

### Allowed Choices

- Can use:
  - 逐阶段重构 emitter
  - 保持 runtime active-word 调度语义，先改 `subStep` 生成形态和 file packing
  - 采用“局部变量 + 持久 typed value + 独立 state/memory/shadow/evt_edge”的混合模型
  - 使用现有 `pdocs/grhsim-perf-opt.md` 中的静态规模和 perf 口径做复测
- Cannot use:
  - 把 `grhsim op` 和 `gsim node` 当作一一对应的优化目标
  - 通过后处理脚本简单拼接 cpp 文件来替代 emitter 层 file packing 改造
  - 为追求少 slot 而跨越 side-effect / commit / event 边界错误重排
  - 一刀切把所有 value 都提升为顶层持久成员

## Feasibility Hints and Suggestions

> **Note**: This section is for reference and understanding only. These are conceptual suggestions, not prescriptive requirements.

### Conceptual Approach

建议按“先生成形态、再存储形态、最后再调 supernode 复杂度”的顺序推进：

1. 先做 `subStep` 生成形态和 file packing
   - 保留现有 runtime active-word 编号和调度语义
   - 让 emitter 对外只生成 `subStepN()`
   - active-word 处理段下沉为 `subStep` 内部实现细节
   - 再把多个 `subStep` body 放进更少的 cpp 文件
2. 再做 value storage 重构
   - same-supernode temporary value 优先局部化
   - 跨 supernode / 跨周期 / 必须持久的 value 变成明确命名的持久 typed value
   - `state` / `memory` / `shadow` / `evt_edge` 维持独立通道
3. 最后重新调 supernode 最大 op
   - 在新的 emit/storage 形态下重新测 body 复杂度
   - 以 `grhsim` 自身的 emitted op、slot 访问、热点 `subStep` 体积和 perf 结果为依据

### Relevant References

- [pdocs/grhsim-perf-opt.md](/workspace/gaoruihao-dev-gpu/wolvrix-playground/pdocs/grhsim-perf-opt.md) - 当前静态规模、激活写回、slot 访问和优化方向记录
- [wolvrix/lib/emit/grhsim_cpp.cpp](/workspace/gaoruihao-dev-gpu/wolvrix-playground/wolvrix/lib/emit/grhsim_cpp.cpp) - `grhsim` emitter 主实现
- [build/xs/grhsim/grhsim_emit/grhsim_SimTop.hpp](/workspace/gaoruihao-dev-gpu/wolvrix-playground/build/xs/grhsim/grhsim_emit/grhsim_SimTop.hpp) - 当前 `grhsim` emitted runtime 结构
- [tmp/gsim/src/cppEmitter.cpp](/workspace/gaoruihao-dev-gpu/wolvrix-playground/tmp/gsim/src/cppEmitter.cpp) - `gsim` emitter 参考实现
- [tmp/gsim_default_xiangshan/default-xiangshan/model/SimTop.h](/workspace/gaoruihao-dev-gpu/wolvrix-playground/tmp/gsim_default_xiangshan/default-xiangshan/model/SimTop.h) - `gsim` generated value/member 组织方式参考

## Dependencies and Sequence

### Milestones

1. Milestone 1: 固化目标口径并引入 `subStep` 模式
   - Phase A: 修正文档和代码注释中的目标表述，明确不再用 `grhsim op` 对齐 `gsim node`
   - Phase B: 在 emitter 中引入 `subStepN()` 生成模式，对外隐藏 `eval_batch_*`，让多个 active-word 处理段收敛到更少的函数块
   - Phase C: 在 `subStep` 基础上进一步做 file packing，让多个 `subStep` 共享一个 emitted cpp
   - Phase D: 回归 emit、统计 emitted cpp 文件数、`subStep` 数和单文件体积变化
2. Milestone 2: 重构 value storage
   - Phase A: 划清 temporary value、持久 value、state/memory/shadow/evt_edge 的边界
   - Phase B: same-supernode temporary value 局部化
   - Phase C: 引入明确命名的持久 typed value，替代部分 `slot`
   - Phase D: 复测 `value_*_slots_[]` 静态访问量和热点 `subStep` 代码形态
3. Milestone 3: 重新调 supernode 复杂度并复测 perf
   - Phase A: 在新形态下重新调 supernode 最大 op
   - Phase B: 重新 emit XiangShan，记录 supernode 统计、emitted op 和 `subStep` 体积
   - Phase C: build + perf 复测，观察热点 `subStep` 占比和单次 `eval` 耗时趋势

## Task Breakdown

Each task must include exactly one routing tag:
- `coding`: implemented by Claude
- `analyze`: executed via Codex (`/humanize:ask-codex`)

| Task ID | Description | Target AC | Tag (`coding`/`analyze`) | Depends On |
|---------|-------------|-----------|----------------------------|------------|
| task1 | 梳理 `grhsim` 当前 active-word、`eval_batch_*`、文件拆分三者之间的关系，明确哪些部分应下沉为 `subStep` 内部实现细节 | AC-2 | analyze | - |
| task2 | 设计并实现 `subStepN()` 生成模式，在不改变 runtime active-word 调度语义的前提下让 `subStep` 成为唯一主要外露执行块 | AC-2 | coding | task1 |
| task3 | 在 `subStep` 基础上实现新的 file packing 方案，减少 emitted cpp 文件数 | AC-2 | coding | task2 |
| task4 | 对新的 `subStep` + file packing 方案做 emit 回归和静态规模统计，确认函数数、文件数和体积趋势 | AC-2, AC-4 | analyze | task3 |
| task5 | 梳理 `slot`、temporary value、持久 value、state/memory/shadow/evt_edge 的现有边界与依赖规则 | AC-3, AC-4 | analyze | task4 |
| task6 | 在 emitter 中实现 same-supernode temporary value 局部化的第一阶段重构 | AC-3, AC-4 | coding | task5 |
| task7 | 为跨 supernode / 跨周期 value 建立明确命名的持久 typed value 发射路径，替代部分 `slot` | AC-3, AC-4 | coding | task6 |
| task8 | 复测 `value_*_slots_[]` 访问量、热点 `subStep` 形态和构建行为，确认去 slot 化趋势 | AC-3, AC-4 | analyze | task7 |
| task9 | 在新 emit/storage 形态下重新调 supernode 最大 op，并复测 body 复杂度与 perf 趋势 | AC-1, AC-4 | coding | task8 |
| task10 | 汇总新的 emit 统计、perf 结果和风险，更新性能文档 | AC-1, AC-2, AC-3, AC-4 | coding | task9 |

## Claude-Codex Deliberation

### Agreements

- 当前 `grhsim` 的主要性能问题不在外层活动调度框架，而在 supernode body 过重、file packing 过细和 slot 访问过多。
- `grhsim` 的 value storage 需要向 `gsim` 靠近，但不能简单地“一切都顶层化”。
- `grhsim` 应收敛到 `gsim` 风格的 `subStep` 生成形态；active-word 保留为内部调度粒度，但不再继续外露成大量 `eval_batch_*` 函数。
- file packing 应优先作用于 emitted cpp 粒度，而不是先改变 runtime active-word 调度语义。

### Resolved Disagreements

- supernode 对齐目标：
  - 早期表述接近“让 `grhsim` supernode 数与 `gsim` 对齐”
  - 经过静态分析后，确定 `grhsim op` 与 `gsim node` 语义不一致，不能继续使用该目标
  - 最终采用的表述是：收缩 `grhsim` 自身 supernode body 复杂度，并在新 emit/storage 形态下重新寻找合适区间

### Convergence Status

- Final Status: `converged`

## Pending User Decisions

- 无

## Implementation Notes

### Code Style Requirements

- Implementation code and comments must NOT contain plan-specific terminology such as "AC-", "Milestone", "Step", "Phase", or similar workflow markers
- These terms are for plan documentation only, not for the resulting codebase
- Use descriptive, domain-appropriate naming in code instead

## Output File Convention

This template is used to produce the main output file (e.g., `plan.md`).

### Translated Language Variant

When `alternative_plan_language` resolves to a supported language name through merged config loading, a translated variant of the output file is also written after the main file. Humanize loads config from merged layers in this order: default config, optional user config, then optional project config; `alternative_plan_language` may be set at any of those layers. The variant filename is constructed by inserting `_<code>` (the ISO 639-1 code from the built-in mapping table) immediately before the file extension:

- `plan.md` becomes `plan_<code>.md` (e.g. `plan_zh.md` for Chinese, `plan_ko.md` for Korean)
- `docs/my-plan.md` becomes `docs/my-plan_<code>.md`
- `output` (no extension) becomes `output_<code>`

The translated variant file contains a full translation of the main plan file's current content in the configured language. All identifiers (`AC-*`, task IDs, file paths, API names, command flags) remain unchanged, as they are language-neutral.

When `alternative_plan_language` is empty, absent, set to `"English"`, or set to an unsupported language, no translated variant is written. Humanize does not auto-create `.humanize/config.json` when no project config file is present.
