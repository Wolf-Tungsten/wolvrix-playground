# Stage 07 — preserve-aggregate 端到端与 reg-to-mem 退役

- 日期：2026-10-08（2026-10-08 修订：comb-lane-pack 移除由评估项改为既定项）
- 状态：计划草案
- 依赖：stage-04（ingest 聚合保留）、stage-05（comb-loop-elim）、stage-06（grhsim 承接）
- 对应总目标：#10 终极目标

## 1. 目标

1. 建立 `firtool --preserve-aggregate` 的 XiangShan SV 生成链路，wolvrix 全流程
   （ingest → GRH passes → GrhSIM → CPU emit）直接消费，正确仿真。
2. reg-to-mem 从默认管线**完全退役**（不是默认关闭，是移除），仿真仍然正确。
3. 全部门禁恢复并清零历史豁免；性能不低于现行基线的约定阈值。

## 2. 现状事实

- XiangShan SV 生成：根 Makefile `xs_rtl`（Makefile:1334）→ `testcase/xiangshan/Makefile`，
  firtool 选项固定在 :79（`--firtool-opt "-O=release --disable-annotation-unknown
  --lowering-options=explicitBitcast,disallowLocalVariables,disallowPortDeclSharing,
  locationInfoStyle=none"`），**未开 preserve-aggregate**；`FIRTOOL=` 可指定二进制（:86）。
- `--preserve-aggregate` 在 circt firtool 存在（取值 none/1d/all）；已知限制：含 Clock
  字段的 struct 会报错（circt issue #8931）。XiangShan 当前 firtool 版本对
  `all` 档的兼容性**未实证**——这是本阶段第一个要回答的问题。
- 现有手写最小复现：`testcase/xs-bugcase/CASE_021`（Tage t2_setIdx preserve-aggregate
  形态）、`CASE_022`（indexed write）、`CASE_009`——可作为早期冒烟输入。
- `testcase/xs-components/Makefile:274-279` 已有 mill + firtool 的合成隔离用例流程
  （`DynArrayWrite.scala`、`CamMatchSynthLarge.scala` 等正是数组/聚合形态）。
- reg-to-mem 在 `CPU_SEMANTIC_PIPELINE`（`scripts/wolvrix_xs_grhsim_ir.py:170-185`）中，
  位于 canonicalize-compute 之后；它是现行性能的承重墙（关闭 +41%，
  `pdocs/perf-optimization/20261007-040954-reg-to-mem-off-negative.md`）——但那是
  "前端标量化"前提下的结论；数组保留后该前提消失，需重新测量。
- 验收门禁（继承 perf-optimization/README）：test_wolvrix、HDLBits IR 162、xs-bugcase 25、
  黄金 trace 161、XS CoreMark difftest（instrCnt=663,688 / cycleCnt=297,291）。

## 3. 执行计划

### 3.1 子阶段 7a — firtool 链路实证（纯调查，不改 wolvrix）

**已完成首轮（2026-10-08），结论与形态清单见
[20261008-preserve-aggregate-probe.md](20261008-preserve-aggregate-probe.md)。要点：**

1. ~~确认 `--preserve-aggregate` 支持矩阵~~ → 取值为 `none|1d-vec|vec|all`
   （firtool 1.135.0/1.144.0 一致；注意是 `1d-vec` 不是 `1d`）。
2. ~~XiangShan 全量 `all` 档可行性~~ → **一次通过**，未触发 Clock-struct（#8931）类错误；
   设计逻辑 100% packed 聚合 + unpacked Memory + 仿真 _RANDOM，无 unpacked 数组。
3. 形态清单（ingest 必须承接的全集）与对 stage-01/stage-04 的回灌结论：见探针报告
   §3/§4（packed 维全量进 shape、部分索引返回子数组、结构体字段路径等；
   注意报告 §4.1 的"分流"解释已被 §6 补充取代，以 stage-01/04 当前文本为准）。
4. 待补：mill 全链路（MFC_ARGS 注入）复核（进行中）；xs-components 合成用例变体；
   `=vec` 中间档的收益评估（比 `=all` 小约 43%，不保留 struct）。

### 3.2 子阶段 7b — Makefile 与管线接入

- `testcase/xiangshan/Makefile`：`--firtool-opt` 增加 preserve-aggregate 选项
  （建议做成变量如 `PRESERVE_AGGREGATE=all`，默认关，避免冲击现有 `xs_rtl` 用户）。
- 根 Makefile 新增目标族（遵循"一切走 Makefile"约束，先在 Makefile 加 target 再使用）：
  - `xs_rtl_aggregate`：生成 preserve-aggregate 版 SimTop.sv（独立 BUILD_DIR）。
  - `xs_wolf_grhsim_ir_aggregate(+_build_emu/_emu)`：复用 `scripts/wolvrix_xs_grhsim_ir.py`，
    通过参数切换 RTL 来源与管线。
- 管线变化（`scripts/wolvrix_xs_grhsim_ir.py`）：
  - `CPU_SEMANTIC_PIPELINE` 中 **移除 reg-to-mem**（aggregate 模式）。
  - ~~评估 comb-lane-pack 在 aggregate 模式下是否直接移除~~ **已定移除
    （2026-10-08）**：comb-lane-pack 退役（当前测试结果确认，见 stage-05 §8 Q1），
    代码删除执行于 stage-02；本阶段仅确认管线无残留注册点。
  - GRH 段管线（xmr-resolve → … → comb-loop-elim → simplify）不变，但 stage-05 的
    片段化默认开启。

### 3.3 子阶段 7c — reg-to-mem 退役

退役分三步，每步可独立验证：

1. **默认关**：aggregate 管线不含 reg-to-mem；legacy 管线保留（对照组）。
2. **移除出全部默认管线**：legacy 输入（标量化 SV）不再支持 XS 规模仿真——
   文档明确"legacy 链路降级为 HDLBits/小用例维护模式"。
3. **代码移除**：删除 `lib/grhsim/pass/reg_to_mem.cpp`、注册点、文档
   `docs/grhsim_ir/passes/reg-to-mem.md` 转为历史记录（划线保留结论，按
   perf-optimization 惯例"被推翻的结论划线不删"）；`benchmark_grhsim_reg_to_mem.py`
   等配套脚本归档或删除。

注意保留 reg-to-mem 文档中的**负结果知识**（为什么标量化前端必须配 reg-to-mem），
防止未来有人重造轮子。

### 3.4 子阶段 7d — 验收

- 正确性（全绿才算完成，不接受豁免）：
  - `make test_wolvrix`
  - `make run_all_hdlbits_grhsim_ir_tests`（162/162）
  - `make run_xs_bugcase_grhsim`（25/25；CASE_009/021/022 在 aggregate 链路上的表现
    单独核对）
  - `make check_sim_refactor_baseline`：trace 基线**重钉**（数组形态改变 op 序列是预期
    行为，逐条核对后 `capture_sim_refactor_baseline` 重新捕获，提交说明引用本计划）
  - XS CoreMark difftest：aggregate RTL + 无 reg-to-mem 管线，轨迹钉死
    instrCnt=663,688 / cycleCnt=297,291（与现行基线相同数值才算"正确仿真"）
- 性能：`make benchmark_grhsim_ir` A/B（旧链路 vs aggregate 链路）。
  目标：不劣于现行基线的 105%（容许 5% 内波动）；若显著更优，更新基线文档。
- 编译时间：记录 emit C++ 的 clang 编译时长（参照 bitint 经验的 30min 闸意识），
  数组保留预期减少 P_general 体积，若编译时间恶化需归因（发射形状问题回 stage-06）。

## 4. 文件级改动点

| 文件 | 改动 |
|------|------|
| `testcase/xiangshan/Makefile` | preserve-aggregate 选项变量化 |
| 根 `Makefile` | `xs_rtl_aggregate`、`xs_wolf_grhsim_ir_aggregate*` 目标族 |
| `scripts/wolvrix_xs_grhsim_ir.py` | aggregate 模式参数；CPU_SEMANTIC_PIPELINE 去 reg-to-mem |
| `wolvrix/lib/grhsim/pass/reg_to_mem.cpp` 等 | 7c-3 移除 |
| `wolvrix/docs/grhsim_ir/passes/reg-to-mem.md` | 转历史记录 |
| `pdocs/perf-optimization/README.md` | 门禁清单更新（aggregate 口径） |

## 5. 风险与缓解（本阶段特有）

| 风险 | 缓解 |
|------|------|
| firtool `all` 档对 XiangShan 不可用 | 7a 先实证；`1d` 档过渡方案；必要时给 circt 提 issue/绕行（struct 字段重排） |
| difftest 数值不一致且难以归因 | 保留 legacy 链路作为对照；按模块二分（`scripts/grhsim_gsim_module_compare.py` 可复用） |
| 性能回退超阈值 | 归因顺序：P_general 体积（数组 op 是否被逐元素展开）→ P_mem 激活率 → 变化检测次数；参照 perf-optimization 既有测量工具链 |
| reg-to-mem 移除后才发现某些 legacy 输入依赖它 | 7c-2 的文档声明 + 移除前全仓 grep 确认无默认管线残留 |

## 6. 完成定义（DoD）

- aggregate XiangShan 链路从 `make xs_rtl_aggregate` 到 difftest 全绿，无 reg-to-mem。
- 本目录各阶段文档的"开放问题"全部有结论（采纳/否决+理由）。
- `wolvrix/docs/` 规范文档与实现一致（grh-ir.md、grh-json-spec.md、grhsim_ir/*）。
- 豁免清单清零；perf-optimization README 门禁更新完毕。
