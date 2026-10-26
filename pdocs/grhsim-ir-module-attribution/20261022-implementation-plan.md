# 模块级仿真耗时归因 — 实施规划

日期：2026-10-22
状态：实施中（M1/M2/M3/M4/M6 已完成，M5 探针开发中，M7 基础设施就绪）

## 0. 实施期新确认的事实

- XS 流程 GRH 管线顺序（`scripts/wolvrix_xs_grhsim_ir.py:17-39`）：`hier-flatten` 之后仅 `comb-loop-elim` → `grh.verify` → `simplify` → `grh.verify` → `memory-init-check`。GRH 侧合成点审计范围 = comb_loop_elim + simplify 展开的全部子 pass（含 const_fold / redundant_elim 的不动点迭代）。
- grhsim `SimOp.parameters` 经 parameterPool 追加存储（`model.cpp:354-358`，**无值去重**——原判断有误；重复 `origin_modules` 会产生重复 Parameter 项）。但 comb_pack 等 pass 本身就会把单来源 op 打包成多来源 op，重复不可避免；且模块路径字符串经 StringInterner 共享，实际体积问题只在线性参数数组长度。结论：v1 不做参数级去重，XS 实测体积后再议。
- emu 构建入口 `xs_wolf_grhsim_ir_build_emu`（`Makefile:1512-1525`），`GRHSIM_MODEL_CXXFLAGS` 透传处即 `-DWOLVRIX_GRHSIM_SN_TIMING` 挂载点（镜像 `WOLVRIX_GRHSIM_PERF`，`Makefile:70-72`）。

## 1. 背景与目标

grhsim IR 仿真的性能分析长期停留在两种粒度：(a) 采样/计数器给出的超节点级热点（如 `sn_12277__op_12795` 占 17.33%，见 `pdocs/perf-optimization/20261018-preserve-aggregate-grhsim-performance-journey.md`）；(b) 设计级的整体口径对比（V3-M3 基线 2.60× 回归等）。超节点热点无法回答"这部分时间属于哪个 RTL 模块"，因而无法与 SV/Chisel 语义对照做微观优化。

本方案的核心思路（提出者：用户）：

1. GRH IR flatten 时起，给每个 op 挂"原始所属模块路径"属性；
2. 变换过程中按语义保持传递（op 被合并/共享时取所有来源的并集）；
3. grhsim IR 保留该属性；
4. 在 P_general 阶段导出每个超节点的 op 来源模块清单（manifest）；
5. 对每个超节点做运行时耗时插桩，定位热点；
6. 得到模块级耗时归因，支撑微观分析优化。

本文档补全的关键设计点：**当超节点内 op 来源于多个模块时，耗时如何分摊（§6）**，以及**单个超节点 op 来源构成的实证验证方法（§7）**。

## 2. 总体方案概览

```
GRH ingest
   │（模块路径在层次结构中已知）
   ▼
hier_flatten / instance_inline  ── 打标 originModules = {实例路径}        [M1]
   │
   ▼
GRH transform passes            ── 语义保持传递：clone 免费 / merge 取并集 /
                                   合成 op 继承主来源 / CSE 签名排除        [M1]
   │
   ▼
store/load (JSON)               ── 通用属性机制天然往返                    [M2]
   ▼
lowerGrhToGrhSim                ── 属性 → SimOp parameter origin_modules   [M3]
   ▼
grhsim Stage A/B passes         ── 参数保持审计（comb-pack 等合并点并集）   [M3]
   ▼
Stage C (C1..C8)                ── 超节点在 C2/C2.5 定型
   │
   ├─► manifest 导出：每超节点 op 来源清单（脚本优先，C++ pass 兜底）       [M4]
   │      └─► 来源构成实证分析（纯度分布/熵/假设检验）                      [M4, §7]
   │
   └─► emit-cpp ── 生成代码中 sn_<ordinal>() 调用点包计时探针              [M5]
                        │  WOLVRIX_GRHSIM_SN_TIMING, rdtscp 累加
                        ▼
              运行时 TSV：(supernode_id, phase, fires, cycles)
                        │
                        ▼
              归因分析脚本：manifest ⨝ timing → 代价模型标定
              → 多来源分摊 → 模块级排名报告（多视角对照 + 层级 rollup）     [M6, §6]
                        │
                        ▼
              端到端验证：正确性门槛 + 开销口径 + 100k CoreMark 首份报告    [M7, §8]
```

## 3. 现状关键事实（调研结论）

### 3.1 GRH IR 侧

- op 属性机制**已存在且够用**：`AttributeValue` 支持 `std::vector<std::string>`（`wolvrix/include/core/grh.hpp:100-108`），`Graph::setAttr/eraseAttr`（`wolvrix/lib/core/grh.cpp:2009-2031`），store/load 通用序列化往返（`store.cpp:978+`、`load.cpp:707-719`），verifier 不拒绝未知属性。
- flatten 打标点： `hier_flatten.cpp:972-982` 的 op clone 循环（实例路径前缀由 `makeHierName` 在 `:383` 构造，`$` 连接，如 `u_cpu$u_alu`）；顶层图 op 不重建，需在 `HierFlattenPass::run` 补一轮打标；flatten 自合成 op（`:304-308`、`:552-557`）无来源 op。次要点：`instance_inline.cpp:698-706`。
- **无统一 op 构建助手**：全部 pass 走 `Graph::createOperation`（`grh.cpp:3488-3503`）+ 逐个 addOperand/setAttr，16 个文件约 45 个创建点。中央钩子无法知道来源，必须逐点审计。
- **合并点只有两类**：`redundant_elim.cpp` 的 CSE（`OpSignature` `:101-154` 含全部属性，`:288-291`；合并于 `:1294-1299`）和 `const_fold.cpp` 的 ConstantPool（`:792-836`）。
- 已有"携带式标注"先例是 SrcLoc（`makeTransformSrcLoc`，`transform.hpp:96-104`），但它是单槽位、合并时只保留 canonical——本方案需要的并集语义目前没有任何属性实现。

### 3.2 grhsim IR 侧

- 模型：`GrhSimModel`（`wolvrix/include/grhsim/ir/model.hpp:803`），`SimOp`（`:321-332`）**无属性字段**，但有自由往返的 parameters 列表（`event_acts` 先例，`cpu_phase_common.hpp:41`）。
- "P_general" = 六阶段中的 General 相（`SimPhase`，`model.hpp:312`）；超节点 = `CpuPartition{kind=Supernode}`（`model.hpp:353,402-446`），成员 op = 其子 Node 分区的 `ops` 展平（`generalSupernodeOf`，`cpu_phase_common.hpp:171-179`）。
- 超节点在 C2 `mergeGeneralSupernodes`（`cpu_partition.cpp:535`）定型，C2.5 `clone-shared-boundaries` 仅原地插入 clone（`attachClone`，`cpu_clone_shared.cpp:207`），序数稳定。
- 超节点序数是全局稳定键：生成代码函数名 `sn_<ordinal>`（`cpu_phase_emit.cpp:5360`）、`nonSinkActiveFlag` 位索引、TU 计划块偏移共用同一序数空间。
- 分区间树与 op 列表会序列化进 grhsim JSON（`json.cpp:698-746`），因此 manifest 可以**纯 Python 从 `store_grhsim()` checkpoint 导出**，零 C++ 改动（首选）；若分区 op 列表序列化不全，再加一个 analysis pass 兜底。

### 3.3 运行时/基建侧

- 生成代码主循环：`eval() → pEvent/pGeneral/pLargeSink → pPublish`（`cpu_phase_emit.cpp:6363-6384`）；超节点派发点在 `scanRange`（`:5865-5968`）与 `emitSinkCall`（`:5906-5934`），与活动守卫紧密交织（clear-on-fire、提升守卫成组覆盖）。
- 已有编译期计数器 `WOLVRIX_GRHSIM_PERF` / `GRHSIM_PERF_COUNT`（`:5387-5432`），Makefile 已透传（`Makefile:70-72,1524`）；`dump_runtime_profile()` 当前是**有意保留的空 stub**（`:5416-5417`），XS harness 在 `EMU_RUNTIME_PROFILE=1` 时会调用它——新插桩可零 harness 改动搭车。
- 生成代码中目前没有任何 chrono/rdtsc；`cpu.st.emit-cpp --perf <off|eval>` 是保留的 no-op 选项（`:6903,6920-6922`），是加新模式的天然位置。
- 已有 TSV 键约定：`(supernode_id, phase)`（`scripts/grhsim_runtime_profile_compare.py`），新 TSV 沿用。
- `grhsim_batch_profile_compare.py` 的 `eval_*_batch_N` 符号已过时于当前 `sn_<ordinal>` 命名，需重定向（顺带修正）。
- 正确性门槛：commit trace 必须逐位一致（238535/99996 端点、231,568 commits），计时只读不影响调度，但必须实测验证。

## 4. 属性定义与 flatten 打标（M1 详设）

**属性名**：`originModules`，类型 `std::vector<std::string>`，语义 = "该 op 的计算逻辑最初书写于哪些模块实例路径"（def-site 语义，**不含数据依赖**——若沿操作数传播会 transitive 爆炸，明确拒绝）。

路径编码：`makeHierName` 的 `$` 连接实例路径（如 `u_core$u_exu$u_alu`），顶层模块用其自身名。层级路径天然支持任意深度 rollup（§6.5）。

打标规则（`hier_flatten.cpp`）：

| op 类别 | 打标 |
|---|---|
| 从子模块 clone 的 op（`:972-982`） | 已有 `originModules` 时前置当前 prefix；否则 `= {prefix}` |
| 顶层图原有 op（`run` 中补循环） | `= {topName}` |
| flatten 自合成 assign（`:304-308`、`:552-557`） | `= {prefix}`（它因该实例而存在） |
| `instance_inline.cpp:698-706` | 同上，prefix 取 `ResolvedTarget::prefix` |

体积优化（v1 从简，XS 上实测后再定）：绝大多数 op 单来源，值为单元素 vector；JSON 字符串不 intern，100k+ op 下体积增长可接受（预计数十 MB 级），若超标再做图级字符串表 + `vector<int64_t>` 索引编码。

## 5. 变换期传递规则（M1 详设，语义保持）

| 变换情形 | 规则 | 落点 |
|---|---|---|
| 整体 clone（copyWrite/copyAttrs/repcut/activity_schedule 等 6 处） | 免费传递，无需改动 | 已复制全部 attrs |
| CSE 合并（redundant_elim） | (a) 将 `originModules` **排除出** `OpSignature` 相等性与哈希（否则层次不同的等价 op 全部无法 CSE，flatten 后严重 deopt）；(b) 合并时 canonical op 的属性 = 两者并集 | `redundant_elim.cpp:101-154,288-291,1294` |
| 常量池复用（const_fold） | 池化常量被复用时取并集（常量本身无语义来源，退化处理） | `const_fold.cpp:792-836` |
| pass 合成新 op（约 45 处） | 继承"主来源 op"（被折叠/被替换的那个 op）的 `originModules`；提供 helper `inheritOrigin(graph, newOp, srcOps...)`（多源时并集） | 16 个 transform 文件逐点审计 |
| 全新逻辑（无来源 op，如 pass 自造 guard/常量） | 空列表，计入覆盖率分母 | — |

传递正确性不变式（写入测试）：
- I1：flatten 后 100% op 非空（除白名单合成类）；
- I2：任一 transform pass 后，非空覆盖率 ≥ 99%（lint 指标，M4 脚本可算）；
- I3：合并后并集 ⊆ 两操作数来源之和（单元测试构造两模块同名等价 op 验证）。

**grhsim Stage A/B pass 的同等审计（M3 范围）**：`comb-pack`、`pack-bit-registers`、`simplify`、`select-state-stores` 等会合并/重写 SimOp，origin parameter 需在合并点取并集。这与 GRH 侧规则相同，审计量预计小于 GRH 侧。

## 6. 多来源超节点的耗时分摊模型（核心设计）

### 6.1 问题形式化

超节点 s：实测总周期数 `C_s`、触发次数 `f_s`（单次成本 `t_s = C_s / f_s`）。成员 op 集合 `{i}`，op i 的静态权重 `w_i`、来源模块集合 `M_i`。模块 m 的归因增量：

```
A(m) += C_s · ( Σ_{i: m∈M_i} w_i / |M_i| ) / ( Σ_i w_i )
```

即：op 的权重先在其多个来源间均分（§6.3 讨论替代规则），再按权重占比切分超节点总耗时。全部模块的归因之和恒等于 Σ C_s（守恒，可与总仿真时间对账）。

### 6.2 静态代价模型 w_i 与其**实测标定**（本方案的关键增量）

不用拍脑袋的固定权重，而是从测量数据反标定：

1. 模型形式：`w_i = base[kind_i] × widthFactor(width_i)`。宽度因子按桶分段（1 / ≤8 / ≤32 / ≤64 / ≤128 / ≤256 / >256），两状态宽 op 是单个 `_BitInt` 原生表达式（见 bitint 文档），成本近似线性于 limb 数，`widthFactor` 用 `CEIL(w/64)` 做初值。
2. 标定：每个超节点给出一条线性方程 `Σ_i w_i ≈ t_s`。XS 规模下有上万个超节点、仅数十个未知系数（op kind 数 × 少量宽度桶修正），构成超定方程组，用**非负最小二乘（NNLS）**拟合 `base[kind]`。注意用 `t_s`（单次成本）而非 `C_s`，避免触发频率差异污染。
3. 验证：用**单来源超节点**做留出验证集——它们的分摊结果必须是 100% 归属单模块，拟合残差直接给出代价模型误差估计（报告 R² 与分位残差）。若 R² 过低（如 <0.7），退化为按 kind 分桶的加权中位数模型，并在报告中标注置信度降级。

**实施期修正（M7 实测）**：(a) NNLS 必须**行归一**——rdtscp cycles 与 op 权重计数跨数量级，法方程被大超节点主导会退化为 base 全 0（R² 天文负数）；每行与其 target 同除以静态权重和后拟合恢复（base 物理单位不变，归因仅用相对比例）。(b) 退化 fallback 时分子 op_weight 与分母必须同用 static（effective_base=1），否则该超节点 cycles 凭空消失导致守恒漏（实测漏 54%）。两处修复后 R²≈0.47、守恒 0、tau≈0.997。

### 6.3 多来源 op 的内部分摊规则

默认均分（`1/|M_i|`）。同时实现三种替代视图，报告并排输出：

| 视图 | 规则 | 用途 |
|---|---|---|
| equal（默认） | 均分 | 无偏基线 |
| dominant-owner | 超节点整体归权重最大的模块 | 粗粒度但抗模型误差 |
| glue-bucket | 多来源 op 的份额计入合成类别 `__cross_module__` | 量化"模块间粘合逻辑"本身的开销 |

**稳健性判据**：若三种视图下 top-N 模块排名一致（用 Kendall τ ≥ 0.8 判定），则结论对分摊模型不敏感，可直接采信；若不一致，以 equal 为主并在报告中披露分歧模块。

### 6.4 与已知热点的预期对照

V3-M3 文档指出 `{posedge clock}` 单签名 sink 聚簇（88.5k op）每拍整体触发——这类超节点必然高度多来源，正是分摊模型存在意义的场景；而 `sn_12277`（17.33%，aggregate whole-value shuffle）应归因到数组/聚合密集的特定模块。首份报告必须能复现并解释这两个已知案例（§8 验收项）。

### 6.5 层级 rollup

路径层级化使报告可按任意深度聚合：叶子模块（精确到 ALU）、子系统（`u_core$u_exu`）、顶层划分。这是与 SV/Chisel 语义对照的接口——Chisel 模块名在 SV 层次中保留，rollup 到对应深度即可回答"Rob 占百分之几"这类问题。报告默认输出 2-3 个深度层级。

### 6.6 地面真值标定工具（可选，v2）

实验性 emit 开关：在超节点内部按来源分组插更细的探针（只读、不改变执行顺序——超节点内本就是数据流直序）。开销大，仅在小 case（hdlbits/xs-components）上拟合验证 `base[kind]`，作为 NNLS 标定的交叉验证。

## 7. 单超节点来源构成的实证验证（M4，先于插桩）

在写任何插桩代码之前，先用 manifest 做静态构成分析，验证方案前提并指导分摊模型：

**分析脚本** `scripts/grhsim_supernode_origin_stats.py`（跟随 `grhsim_algebra_residue_stats.py` 的 `--model` JSON 约定）输出：

- 每超节点：distinct 模块数、`max_module_share`（最大来源的 op 占比）、香农熵；按超节点类别（NonSink / SmallSinkEscape / SmallSinkEvent）分层；
- 全设计聚合：单来源超节点占比（个数加权 / op 数加权 / 静态权重加权三种口径）；
- top-K 最"混"超节点清单。

**待检验假设**：
- H1：NonSink 计算超节点大多单来源或近单来源（逻辑局部性；C2 合并沿数据流进行，数据流多在模块内）；
- H2：sink 类超节点（尤其 `{posedge clock}` 大聚簇）高度多来源——热点归因的难点与价值集中于此；
- H3：op 数加权的多来源占比显著低于直觉——即大多数超节点"纯"，少数大超节点"混"。

若 H1/H3 成立，分摊模型只影响少数超节点，整体归因对模型误差更不敏感；若 H1 不成立（普遍混杂），则需优先投入 §6.6 的地面真值标定。

## 8. 里程碑（文件级清单）

### M1 — GRH 打标与传递
- `wolvrix/lib/transform/hier_flatten.cpp`（`:972-982` 打标、`:304-308`/`:552-557` 合成 op、`run` 顶层循环）、`instance_inline.cpp:698-706`；
- `redundant_elim.cpp`：签名排除 + `:1294` 并集；`const_fold.cpp` 常量池并集；
- 16 个 transform 文件约 45 处合成点审计 + `inheritOrigin` helper；
- 测试：`wolvrix/tests/transform/` 新增 flatten 打标、CSE 并集、常量池并集三用例；I1-I3 不变式。

### M2 — 序列化往返
- 通用机制天然支持；仅加 store→load→store 属性保持测试（含 XS 脚本的 byte-stable 口径不回归）。

### M3 — grhsim 承载与 Stage A/B 审计
- `grh_to_grhsim.cpp`：`originModules` → SimOp parameter `origin_modules`。已确认可行：`ParameterValue` 支持 `std::vector<std::string>`（`model.hpp:63-71`），convert 本就**全量复制 GRH op attrs**（`grh_to_grhsim.cpp:682-687` 经 `normalizedParameterName` + `copyAttribute` 直通），故 M3 仅在 `normalizedParameterName` 增加 `originModules → origin_modules` 改名一行，无第二键重复风险；零 JSON schema 改动；
- grhsim 侧 origin 处理 helper：`simplify_internal.hpp/cpp` 新增 `kOriginModulesParameter` / `originModulesOf` / `unionOriginModules`（有序去重并集，空集省略参数）/ `inheritOriginModules`（原地改写保留来源参数）；`compact()`/`replaceOperation`/`extractCone` 已证实天然保留 parameters；
- op 创建点落点（`addOperation`/`replaceOperation` 普查）：**并集** —— `comb_pack.cpp`（PackedBuilder 按树位从 lane defs 取并集；lane slice 继承 packed root；lane 匹配签名**排除** `origin_modules`，否则跨模块同构 lane 无法打包——与 GRH 侧 CSE 签名排除同理）、`mux_chain_fold.cpp`（fold 段内全部 mux 并集）、`recover_masked_or.cpp`（root 继承被折叠 OR/term 树的并集 + term AND 链继承 term 并集；matcher 的 `parameters().empty()` 一律放宽为 provenance-only，否则带 origin 的 op 会被静默拒配）；**继承** —— `cpu_clone_shared.cpp`（clone 复制来源参数）、`used_bits.cpp`（rebuild/boundary/adapt 一律继承来源 op 或来源 value producer；state write 复制全参数天然保留；read 显式继承）、`const_fold.cpp`（fold 后常量保留 origin；`constantOf`/`evaluate` 忽略 origin 参数）、`bitwise_predicates.cpp`/`bitwise_muxes.cpp`（in-place 改写保留 origin）、`canonicalize_compute.cpp`（CSE 键与 identity 简化**排除** origin；concatRange fold 保留）；**显式省略** —— `lower_edge_detect.cpp` edgeDet（event_acts 先例，行为参数永不进 emit）、`migrate_timeslot_tasks.cpp` 时槽守卫逻辑（监测 glue，继承会虚增任务来源）、`comb_pack.cpp` replicate 掩码（每 mux lane 一份、与并集重复；slice/concat 全量覆盖）、`pack_bit_registers.cpp`（writer 参数约束为仅 `event_edges`，带 origin 的 writer 保守拒配——v1 有意不处理，写入覆盖 caveats）、`select_state_stores`/`split_phases`/`extract_output_cones`/build-*（重分类/重分区或参数透传，无需改动）；
- 测试：`test_grhsim_ir.cpp` 新增 `runOriginModulesConvertTest`（convert 改名 + 无属性 op 无参数 + JSON store→load→store 字节稳定）与 `runOriginModulesCombPackTest`（4 lane × 2 模块打包并集 + slice 继承）；
- 覆盖率 lint：`store_grhsim()` checkpoint 上非空率 ≥ 99%（M4 脚本统计）。

### M4 — manifest 导出 + 来源构成实证
- 首选：`scripts/grhsim_supernode_origin_stats.py` 直接解析 grhsim JSON（分区树 + op 参数），输出 manifest JSON + §7 纯度报告；在 hdlbits（小）与 XiangShan（大）上各跑一份；
- 兜底：分区 op 列表序列化不全时，新增 analysis pass（参照 `registerCpuPartitionPasses`，`cpu_partition.cpp:1030`）；
- 产出 §7 假设检验结论，决定 §6.6 是否提前。

### M5 — 运行时插桩
- `cpu_phase_emit.cpp`：`scanRange`/`emitSinkCall`（及 `pLargeSink_c` 可选）调用点包 `GRHSIM_SN_TIME_BEGIN/END(ordinal)` 宏；探针必须在每超节点调用点内侧、提升守卫内侧（只计真实触发）；clear-on-fire 语义不受影响；
- 计时宏设计原则：**与现有 `GRHSIM_PERF_COUNT` 完全同构**（头样板 `:5387-5392` 处定义宏，`:5429-5432` 旁加计数成员），不引入新类/新函数边界/堆分配；`sn_<ord>` 的函数边界与 inlining 形态在两种构建间保持一致，样本可归因到生成符号；
- 探针：`rdtscp` 差值累加进 `std::array<uint64_t, supernodeCount_>` 双数组（cycles + fires，成员名 `sn_time_` 前缀需注册进重名校验 `:4977-5015`）；`-DWOLVRIX_GRHSIM_SN_TIMING=1` 时每超节点调用点仅 +2 指令级读时戳 +2 数组累加；
- `dump_runtime_profile()` 实现 TSV 输出（header `supernode_id phase fires cycles`），路径取 env `WOLVRIX_GRHSIM_SN_PROFILE`，搭车 `EMU_RUNTIME_PROFILE=1`；phase 值用 `General`（LargeSink 探针留宏位，v2 启用）；
- 编译开关 `WOLVRIX_GRHSIM_SN_TIMING` 透传（已完成：Makefile:70-76 声明/export、:1524 XS emu CXXFLAGS、:1217 hdlbits grhsim 流程；验证默认 0 时命令行仅多一个 `-D...=0`）；
- 顺带把 `grhsim_batch_profile_compare.py` 符号重定向到 `sn_<ordinal>`（低优先级，可延后）；
- 开销 A/B：`make benchmark_grhsim_ir` 口径，目标开销 ≤ 3% 并写入记录。

### M6 — 归因分析脚本
- `scripts/grhsim_module_attribution.py`：manifest ⨝ timing TSV → NNLS 标定（先查 scipy 可用性，不可用则 numpy 投影梯度实现）→ §6.1 分摊 → 三视图报告 + 层级 rollup + 守恒对账（Σ A(m) ≈ Σ C_s，偏差 <1%）；
- 输出 `module_attribution.tsv` + markdown 排名报告（每模块：self cycles、占比、累计、纯度统计、其内 top 超节点）。

### M7 — 端到端验证与首份报告
- 正确性：ctest、hdlbits 162、xs-bugcase 25、插桩开启下 commit trace 逐位一致（238535/99996、231,568 commits）；
- 口径：按 `pdocs/perf-optimization/README.md` 标准跑 100k CoreMark，插桩开/关双口径；
- 验收：报告复现 `sn_12277`≈17% 并给出模块归属；解释 `{posedge clock}` sink 聚簇的模块构成；Σ 守恒对账通过；
- 在本目录写测量记录（遵循 perf-optimization/TEMPLATE）。

#### M7 执行序列（实施期定稿）

1. `make xs_wolf_grhsim_ir`（全量重生成：新打标/承载代码经 py_install 自动生效；脚本含 store→load→store 字节稳定 gate；产出新 grhsim JSON + 生成 C++）；
2. 默认构建 `make xs_wolf_grhsim_ir_build_emu` 并**计时**（对照 ≤15 min 约束与 773 s 基线；默认 SN_TIMING=0 必须无显著变化）；
3. 短时 difftest 运行确认端点（commit trace 逐位一致）；
4. `WOLVRIX_GRHSIM_SN_TIMING=1 make xs_wolf_grhsim_ir_build_emu` 重建并计时（探针档编译开销量化）；
5. `EMU_RUNTIME_PROFILE=1 WOLVRIX_GRHSIM_SN_PROFILE=<tsv> make run_xs_wolf_grhsim_ir_emu`（100k CoreMark；harness 已确认 emu.cpp:101/361 会调 set/dump_runtime_profile）；
6. `make analyze_grhsim_supernode_origins`（4.8GB JSON，注意内存）→ H1/H2/H3 假设检验；
7. `make analyze_grhsim_module_attribution`（manifest ⨝ TSV）→ 首份模块归因报告；
8. 归因交叉验证：与采样画像对照（`sn_12277`≈17.33% 应复现并给出模块归属；`general_supernode` 78.08% 的模块构成；`{posedge clock}` sink 聚簇归因）；
9. 插桩运行时开销 A/B（`benchmark_grhsim_ir.py` 口径，目标 ≤3%）；
10. 写测量记录到本目录。

## 9. 编译耗时约束（≤15 min）基线

- 参照口径：`_BitInt` 修复后 XS emu 生成代码 wall compile 约 773 s（`pdocs/perf-optimization/20261006-101609-bitint-wide-value.md`），余量约 2 分钟。15 min 上限比当前基线宽，但任何显著增大生成代码/降低编译器可优化性的改动都会吃光余量。
- 本方案的生成代码形态纪律：
  1. 属性与 manifest 只存在于 IR 与旁车文件，**绝不进入生成的 C++**；
  2. 计时探针仅在 `-DWOLVRIX_GRHSIM_SN_TIMING` 下生效，默认（生产/PGO 口径）零代码、零开销；
  3. 探针粒度为超节点调用点（每点两句 rdtscp + 两处数组累加），不做 op 级探针、不引入新函数边界、不改 inlining 形态；
  4. 计数存储为编译期定长 `std::array`，无堆分配、无每调用日志。
- 验证：M7 分别以开关两档跑 `make xs_wolf_grhsim_ir_build_emu` 计时，并与 773 s 基线对比记录。

## 10. 风险与开放问题

- R1（高）：`originModules` 混入 CSE 签名导致 flatten 后 deopt —— M1 必须签名排除，验收：XS flatten 后 op 数与基线一致。
- R2（中）：属性内存/JSON 体积 —— XS 实测，超标则字符串表索引编码（v1.1）。
- R3（中）：45+ 处合成点审计遗漏 → 覆盖率 lint（I2）兜底，遗漏 op 以空列表落入 `__unknown__` 桶，不影响守恒。
- R4（中）：rdtscp 对微超节点的相对开销扭曲排名 —— 累计式计数 + 开销 A/B；必要时出"粗粒度 chunk 计时"对照口径。
- R5（中）：若 sink 大聚簇占比过高，分摊模型误差主导结论 —— 三视图稳健性判据 + §6.6 标定工具。
- R6（低）：grhsim JSON positional schema 对新增 parameter 的兼容（`compact()` 丢映射的交互）—— M3 用 byte-stable 口径守住。
- OQ1：def-site 语义是否足以支撑 Chisel 级对照？（数据依赖语义已拒绝，若后续需要"谁驱动了这个计算"视角，需另立 lineage 属性，不在本方案。）
- OQ2：LargeSink/publish 相是否纳入 v1？默认只做 P_general，LargeSink 探针留好宏位。
