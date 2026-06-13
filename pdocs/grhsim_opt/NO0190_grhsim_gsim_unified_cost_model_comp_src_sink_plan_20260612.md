# NO0190 GrhSIM / GSIM 统一成本模型：n_comp / n_src / n_sink 三变量对齐计划

记录日期：2026-06-12（2026-06-13 追加 §14 GSIM 实施、§15 GrhSIM 实施、§16 profile 开关与输出格式说明）
状态：**两侧均已实施并跑通 XiangShan CoreMark 50k**（emit/runtime 两文件对齐、编译安全、commit a_succ 修复生效）；数据分析与系数 `c_*` 回归另起 NOxxxx
关联：[`NO0189`](./NO0189_grhsim_gsim_supernode_cost_tsv_instrument_plan_20260611.md)（前身：source/compute/sink + a_succ 插桩与首轮实测）、[`NO0077`](./NO0077_xs_gsim_grhsim_runtime_profile_coremark_50k_20260509.md)、[`NO0087`](./NO0087_current_gsim_grhsim_quant_profile_perf_20260511.md)

---

## 1. 背景与目标

### 1.1 现有模型为何不准

[`NO0189`](./NO0189_grhsim_gsim_supernode_cost_tsv_instrument_plan_20260611.md) 落地的成本模型为：

```
T = Σ_{i=1..N} f(i) · ( E(i) + A_succ(i) )  +  N · A_exam
```

其中 `E(i)` 是**等权**的 op 总数（source+compute+sink 同权）。NO0189 §11.6 的实测暴露了核心问题：

| | 值 |
| --- | --- |
| op-count 模型（等权 E）预测的 grh/gsim 总工作量比 | **2.0×** |
| 实测墙钟 grh/gsim | **8.4×** |

缺口 ~4× 既非 `N·A_exam`（≤10%）也非负沿 eval（已计入 firing）。NO0189 §11.6 归因：**每个 op 的真实成本不均等，而等权 `E` 假设它们一样贵**——grhsim 的工作压在 sink（写口/store，10.8×）与 source（状态读/常量物化）上，而这两类比 ALU compute 贵得多。

结论：**`E(i)` 必须按 op 的成本属性拆开、各给一个回归系数**，而不是塞进一个等权标量。这要求先把「拆成哪几类」在 gsim / grhsim 两侧用**完全一致的口径**定义出来。

### 1.2 本计划的目标

升级后的目标模型形如（详见 §8.1）：

```
T = Σ_i f[i] · ( c_comp·n_comp[i] + c_src·n_src[i] + c_sink·n_sink[i] + c_const·n_const[i] + c_succ·a_succ[i] )
```

- `f[i]`：超节点 i 的**激活次数（原始累计计数，不归一化）**。
- `c_*`：每类 op 的单位成本系数，由回归拟合。
- **`N·A_exam` 项已移除**（NO0189 §11.5 实测占比 1.3%–9.6%，从模型删去）。
- **关键约束：同一套系数同时解释 gsim 与 grhsim**。这正是「对齐变量」的意义——只有当 `n_*` 在两侧语义一致、且各按真实执行计数（§1.3）时，单套系数才能成立，§11.6 里那 4× 的「每 op 更贵」才会以 `c_sink ≫ c_comp` 的形式被模型显式吸收，而不是留作无法解释的残差。

本计划**只负责第一步**：把 `n_comp[i]`、`n_src[i]`、`n_sink[i]`、`n_const[i]` 等变量在两个仿真器上**精确定义并对齐**，定下 `f[i]`/`a_succ[i]` 口径与最终 TSV schema（§8.2），给出 op→变量的完整映射、与 NO0189 现有口径的差异、以及落地改动清单。系数 `c_*` 的回归拟合本身属后续 `NOxxxx`。

> 本文是规划文档。`reference/gsim` 与 `wolvrix` 当前已有 NO0189 的 source/compute/sink 插桩；本计划描述如何把它**重定义/迁移**为对齐的 comp/src/sink，不是从零搭建。

### 1.3 建模第一性原则（贯穿全文）

这是一个**性能模型**，唯一标尺是**贴近真实执行**。由此定下不可动摇的原则：

> **`n_*` 必须如实数「每次 firing 时，该仿真器最终生成的代码真正执行的操作」。**

「对齐」的正确含义是：

- gsim 与 grhsim 共享**同一套 op→类别分类法**（什么算 comp / src / sink）；
- 共享**同一套单位成本系数** `c_comp / c_src / c_sink`（因为「读一次寄存器」「写一次内存」在两边是同一类机器动作，单位成本可比）；
- 但 `n_*` 的**计数各自如实反映本仿真器生成代码的实际执行量**，**不做任何为了「让两边数字看齐」的去重/规整**。

**两边计数本就应该不同**——这个差异正是模型要表达的性能信号，绝不能抹平。最典型的例子是 grhsim 的 **source clone**（§3.1）：grhsim 把每个状态读**逐使用点克隆**，运行时每个使用点真读一次；若按「同一寄存器算一份」去重（NO0189/旧 gsim 的做法），就把 source clone 引入的真实成本删掉了，模型必然失真（NO0189 §11.2 的 source 0.61× 假象即源于此）。

推论（覆盖 NO0189 与本计划早期草案的口径）：
- **不为对齐而去重**：寄存器读、内存读、常量等都按各仿真器实际执行的次数计，而非逻辑去重后的「distinct」数。
- **以「最终发射的 IR / 代码」为计数对象**：grhsim 数 **post-clone 的 `supernodeToOps`**（克隆已展开）；gsim 数其**最终生成代码真正执行的读写**。

---

## 2. 三变量统一定义（gsim / grhsim 共用）

| 变量 | 统一语义 | 直觉成本 |
| --- | --- | --- |
| **`n_comp[i]`** | 超节点 i 中**真正在 CPU 上做数据流计算**的 op 数：算术 / 逻辑 / 比较 / 移位 / 归约 / mux / 拼接 / 切片 等。**不含**任何状态访问，**不含**常量物化。 | 寄存器内 ALU，最便宜，近似等权。 |
| **`n_src[i]`** | 超节点 i 中**读取状态变量**的 op 数：寄存器读、内存读、latch 读。即「从大状态对象里 load 进来」的访问点。 | load + cache 行为，比 comp 贵。 |
| **`n_sink[i]`** | 超节点 i 中**写回/更新状态变量**的 op 数：寄存器写、内存写、内存 fill、latch 写。即「store 回大状态对象」的访问点。 | store + 变动检测，最贵（§11.6 主因）。 |

三类**互斥**。常量物化（grhsim `kConstant` / gsim `OP_INT`）**不属于这三类之一**——它既不是状态访问，也不是 ALU 计算（见 §6 的处理决策）。

> 与 NO0189 的命名差异：NO0189 用 source / compute / sink，其中 **source 含常量、compute 含内存读**。本计划改名为 comp / src / sink 并**重画边界**（见 §3），因此不是简单改名。

---

## 3. 与 NO0189 现有口径的差异（迁移核心）

这是落地时最容易出错的部分。新口径相对 NO0189 现有插桩有两处边界移动 + 常量剥离：

| op 类别 | NO0189 旧归类 | 本计划新归类 | 动作 |
| --- | --- | --- | --- |
| 寄存器读 / latch 读 | source | **src** | 保留（剔除常量后） |
| **内存读**（`kMemoryReadPort` / `OP_READ_MEM` / `NODE_READER`） | **compute** | **src** | **从 compute 移到 src** |
| 算术/逻辑/移位/mux/切片/拼接… | compute | **comp** | 保留（剔除内存读后） |
| 寄存器写 / 内存写 / fill / latch 写 | sink | **sink** | 不变 |
| **常量**（`kConstant` / `OP_INT`） | **source** | **三类之外** | **从 source 剥离**（见 §6） |

净变化：
1. **内存读 compute → src**：内存读是状态访问，按 §2 必须进 src。两侧都要改。
2. **常量从 src/source 剥离**：常量不是状态访问。两侧都要改。
3. comp = 旧 compute − 内存读；src = 旧 source − 常量 + 内存读；sink 不变。

### 3.1 source clone：决定 n_src / n_const 的计数单位（务必按真实执行计）

grhsim 在 activity-schedule 阶段有 **source clone**（`wolvrix/lib/transform/activity_schedule.cpp:3108` `cloneSourceUsesForCompute`）：对每个 Source op，**为它的每一个 compute 使用点克隆一份独立的 source op** 并改写该使用点的操作数（`++sourceClonesInComputeNodes`）。其分类口径见 `classifyActivityOp`（`activity_schedule.cpp:2972`）——

```
Source = kConstant, kRegisterReadPort, kLatchReadPort, kMemoryReadPort
```

即**寄存器读、内存读、latch 读、常量都会被逐使用点克隆**。运行时每个使用点真的各读 / 各物化一次，是 source clone 实打实引入的成本。

由 §1.3 的第一性原则，直接得出 grhsim 的计数单位：

- **n_src / n_const 按 post-clone 的 `supernodeToOps` 计，不去重**。每个 clone 都是流里一个独立的 Source-class op，自然 per-use 计入——这正是真实执行的 load / 物化数。
- 因此 NO0189 §7.1 / 本计划早期草案里「寄存器读对齐到 per-distinct」的说法**作废**：grhsim 本就 per-use，gsim 也必须数真实执行量（§5、§7），不得为「看齐」而 dedup。

> 关键提醒：`classifyActivityOp`（驱动真实代码形态，含 clone）把 `kMemoryReadPort` 归 **Source**，而 NO0189 用于 profile 计数的 `classifyRuntimeProfileOp`（`grhsim_cpp.cpp:2697`）把它错放进 **Compute**——两个分类器自相矛盾，profile 计数与发射代码对不上。修复方向见 §4：profile 计数应以 `classifyActivityOp` 为单一真相源。

---

## 4. GrhSIM 映射（OperationKind → 变量）

口径锚点：`wolvrix/lib/transform/activity_schedule.cpp:2972` `classifyActivityOp()`（**真相源**，驱动 source clone 与代码形态）、`wolvrix/lib/emit/grhsim_cpp.cpp:2697` `classifyRuntimeProfileOp()`（profile 计数，待与前者统一）、`grhsim_cpp.cpp:2722` `buildRuntimeProfileWeights()`，op 枚举 `wolvrix/include/core/grh.hpp:25`。

下表与 `classifyActivityOp` 完全一致（这正是 §1.3 要求的：计数口径跟随真实代码形态）：

| 变量 | OperationKind 成员 |
| --- | --- |
| **n_src** | `kRegisterReadPort`、`kLatchReadPort`、`kMemoryReadPort` |
| **n_sink** | `kRegisterWritePort`、`kLatchWritePort`、`kMemoryWritePort`、`kMemoryFillPort` |
| **n_comp** | 其余数据流 op：`kAdd kSub kMul kDiv kMod`、全部比较（`kEq kNe kCaseEq kCaseNe kWildcardEq kWildcardNe kLt kLe kGt kGe`）、位/逻辑（`kAnd kOr kXor kXnor kNot kLogicAnd kLogicOr kLogicNot`）、归约（`kReduce*`）、`kShl kLShr kAShr`、`kMux kAssign kConcat kReplicate kSliceStatic kSliceDynamic kSliceArray` |
| **常量（剥离）** | `kConstant`（在 `classifyActivityOp` 里属 Source，同样被逐用克隆）→ 见 §6（计入独立 `n_const`，不进三类） |
| **n_comp（含调用）** | `kDpicCall`、`kSystemFunction`、`kSystemTask` 归 **comp**（`classifyActivityOp` 本就 `default→Compute`）✅ |
| **不计（仿真阶段已消除）** | `kXMRRead` / `kXMRWrite`：仿真阶段已无 XMR，**不计入任何类** ✅ |
| **Ignored（不计）** | `kRegister kMemory kLatch kInstance kBlackbox kDpicImport`（= `classifyActivityOp` 的 Declaration/Hier 类） |

**计数对象**：遍历每个超节点 **post-clone 的 `schedule.supernodeToOps[i]`**，逐 op 用上表分类并累加——`source clone 已展开`，故 n_src / n_const 自然 per-use，无需也不应去重（§1.3、§3.1）。

**落地（两选一，推荐前者）**：
1. **让 profile 计数复用 `classifyActivityOp`**（单一真相源）。这样 `kMemoryReadPort→Source`、`kConstant→Source` 自动正确，只需在累加侧把 Source 再细分出 `n_const`（`kConstant`）与 `n_src`（reg/latch/mem read）两桶。**推荐**：消除 §3.1 指出的双分类器矛盾。
2. 退而求其次：就地改 `classifyRuntimeProfileOp` 的 `switch`——`kMemoryReadPort` 从 `default(Compute)` 移入 src；`kConstant` 移出 source 单列 `n_const`。但仍留两个分类器，需保证与 `classifyActivityOp` 永久一致，易漂移。

> grhsim 的 compute/commit 两行拆分（NO0189 §2）保持不变：本三变量是**逐行（per supernode-phase）**统计。纯 compute 行天然 `n_sink=0`、纯 commit 行天然 `n_comp≈0 / n_sink>0`，与 phase 拆分正交，不冲突。

---

## 5. GSIM 映射（如何表达 src / sink）

这正是需求里点名「在 GSIM 中该如何表达请你思考」的部分。GSIM 没有 grhsim 那种显式「读口/写口 op」，状态访问藏在 ENode 树的**叶子引用**和 supernode 的**成员节点类型**里，所以三类要从两个不同层面去数。

口径锚点：`reference/gsim/src/cppEmitter.cpp:62` `RuntimeProfileWeights`、`:71` `countRuntimeProfileOp`、`:87` `countRuntimeProfileConstInTree`、`:106` `collectRegReadRefs`、`:184` `countRuntimeProfileSupernode`；node 枚举 `reference/gsim/include/Node.h:14`；`OPType` `reference/gsim/include/ExpTree.h:11`。

### 5.1 n_comp（GSIM）

= 当前 `countRuntimeProfileOp` 口径的 ENode-op（非叶、非常量、非 index 的 opType 节点），**再剔除内存读 `OP_READ_MEM`**。

- 现有 `countRuntimeProfileOp`（`cppEmitter.cpp:71`）已跳过 `nodePtr` 叶子（含寄存器读引用）、`OP_INT`、`OP_INDEX/OP_INDEX_INT`、`OP_INVALID/OP_EMPTY`。
- **新增**：把 `OP_READ_MEM` 也从 comp 排除（移到 src，见 5.2）。即 `countRuntimeProfileOp` 对 `OP_READ_MEM` 返回 `false`。
- 寄存器读在 gsim 本就是带 `nodePtr` 的叶子，已不在 comp 内——无需处理。

### 5.2 n_src（GSIM）—— 三个来源

GSIM 的「读状态变量」分散在三处，需合并；按 §1.3，全部**数 gsim 生成代码真正执行的读，不去重**：

1. **寄存器读**：ENode 叶子 `nodePtr->type == NODE_REG_SRC`。**删掉** `collectRegReadRefs()`（`cppEmitter.cpp:106`）当前的「每超节点每寄存器去重」（`regReadSeen.size()`，`:203`，注释 `:104` 自承「Mirrors GRHSIM kRegisterReadPort... distinct」）——该去重是为「看齐 grhsim」而做，恰好抹掉了 grhsim source clone 的真实成本（§3.1），与 §1.3 冲突。改为 **per-occurrence**：数每个 `NODE_REG_SRC` 叶引用（已核实 gsim 无 hoist，见 §7.1）。
2. **内存读**：gsim 内存读建模为 `OP_READ_MEM` ENode（出现在表达式树里）/ 成员 `NODE_READER`、`NODE_READWRITER` 的读侧。**新增**统计，按实际执行读计（§7.2）。这部分今天**完全没进 src**（`OP_READ_MEM` 还错在 comp 里）。
3. **latch 读**：gsim 当前数据模型无独立 latch 读端口（NO0189 §11.1：latch/fill gsim 记 0）。记 0，待确认。

`n_src = 寄存器读 + 内存读 + latch读(0)`，均按实际执行计。**剔除常量**：现有 `sourceOps` 把 `OP_INT`（`countRuntimeProfileConstInTree`，`:87/164`）算进了 source，新口径拆到独立 `n_const`（§6），不进 src。

### 5.3 n_sink（GSIM）

= 当前 `sinkOps` 口径，**已对齐，无需改动**：按成员节点类型计（`cppEmitter.cpp:196-201`）——

- `NODE_REG_DST` → 寄存器写，+1（对 grhsim `kRegisterWritePort`）。
- `NODE_WRITER` → 内存写口，+1（对 `kMemoryWritePort`）。
- `NODE_READWRITER` → 读写口的写侧，+1。

latch 写 / 内存 fill：gsim 无对应，记 0（对 grhsim `kLatchWritePort` / `kMemoryFillPort`，记 0）。

### 5.4 GSIM 映射小结

| 变量 | GSIM 数据模型来源 | 计数单位 |
| --- | --- | --- |
| n_comp | 非叶、非常量、非 index、**非 OP_READ_MEM** 的 opType ENode | per-occurrence（沿用 `countRuntimeProfileOp`） |
| n_src | `NODE_REG_SRC` 叶引用 + 内存读（`OP_READ_MEM`） | **per-occurrence，不去重**（已核实 gsim 无 hoist，§7.1/7.2） |
| n_sink | `NODE_REG_DST` + `NODE_WRITER` + `NODE_READWRITER` 成员 | per member node |
| n_const | `OP_INT` ENode | per-occurrence |

---

## 6. 常量（constant）处理决策

常量（grhsim `kConstant` / gsim `OP_INT`）按 §2 不属于 comp/src/sink 任何一类。处理选项：

- **(A) 独立列 `n_const`，不进三变量【推荐】**：单独计数、单独导出，回归时给它自己的系数 `c_const`（或直接丢弃）。最干净，且保留信息给残差分析。物化宽 bitint 常量并非零成本，给独立系数让回归自己定它有多贵。
- (B) 折进 `n_comp`：把常量当成廉价 compute。简单，但污染 comp 的「纯 ALU」语义，且常量成本与 add/and 未必同量级。
- (C) 完全忽略：丢掉常量计数。最简单，但若常量物化确有成本会进残差。

**推荐 (A)**：新增 `n_const` 列，三变量保持纯净。这是与需求方需确认的决策点之一（§9）。

> grhsim `kConstant` 在 `classifyActivityOp` 里属 Source，**也被 source clone 逐用克隆**，故 grhsim `n_const` 天然 per-use（每个使用点各物化一份，正是真实成本）。gsim `OP_INT`（`countRuntimeProfileConstInTree`，`:87`）已是 per-occurrence。两侧都按「实际物化次数」计，口径一致。

---

## 7. 计数单位：按实际执行计（不为对齐而去重）

由 §1.3：计数单位的唯一标准是**贴近该仿真器生成代码的真实执行**，**不是**让两边数字看齐。NO0189 §11.1 之所以踩坑，部分正因为反过来「为对齐而 dedup」。下面把两类读的单位按这个原则定死，并列出唯一需核实的 codegen 细节。

### 7.1 寄存器读

- **grhsim**：经 source clone 后，`supernodeToOps` 里每个 `kRegisterReadPort` op 都是一次真实读（含逐用克隆）。按 op 流计数即 per-use，**不去重**。✓ 已是真实口径。
- **gsim**：**删除** `collectRegReadRefs` 的 per-distinct 去重（§5.2），改为 **per-occurrence**——每个 `NODE_REG_SRC` 叶引用计 1。
- **已核实（2026-06-12，结论：per-occurrence，无 hoist）**：
  - `allocNodeInfo(n)`（`instsGenerator.cpp:1448`）直接 `valStr = n->name`——寄存器读叶子的 valStr 就是存储变量名本身，引用即一次 load。
  - `ENode::compute()`（`:1458`）顶部 `if (computeInfo) return computeInfo;` 是**逐 ENode 对象**缓存，不跨「同一寄存器的不同叶子」去重；同一寄存器引用 K 次 = K 个独立叶 ENode = 寄存器名内联进 K 个父表达式 = **K 次读**。
  - 没有把寄存器读 hoist 到本地变量统一读一次的机制；故 gsim 生成代码确实 per-occurrence 读。
- 注意：这不是「让 gsim 去对齐 grhsim」。两边各按自己的真实执行计、都在「发射源码」层面 per-occurrence（grhsim source clone 造 K 个独立读 op，gsim 内联 K 次读，对称）；grhsim 因 clone 读得多、gsim 读得少，是**应当保留的真实差异**——模型用同一 `c_src` 正好把这差异表达成 grhsim 的更高 source 成本。宿主编译器对重复 `regname` load 的 CSE 两边同等，被 `c_src` 平均吸收。

### 7.2 内存读

- **grhsim**：`kMemoryReadPort` 在 `classifyActivityOp` 属 Source，**同样被 source clone 逐用克隆**；`supernodeToOps` 里每个内存读 op 都是真实读，按 op 流计数 per-use，不去重。
- **gsim**：数 gsim 生成代码真正执行的内存读 = **per-occurrence `OP_READ_MEM`**。gsim 把内存读建成 `NODE_READER` / `NODE_READWRITER` 节点，其 valTree 根唯一一个 `OP_READ_MEM`（`AST2Graph.cpp:708/1574`），读结果**物化进该 reader 节点自己的变量、每 firing 算一次**，消费者引用 reader 节点名而非重展开。故 `OP_READ_MEM` 出现数 = reader 节点求值数 = 实际内存读执行数（与 per-port `NODE_READER` ≈ 1:1）。
- 此处 grhsim 与 gsim 会**真实地不同**且应保留：grhsim 内存读是 Source、被 source clone **逐用克隆**（per-use 多次读）；gsim reader 节点**每 firing 物化一次**（per-port 一次读）。这是两个仿真器真实执行差异，由同一 `c_src` 表达成 grhsim 更高的内存读成本，符合 §1.3。
- sanity：抽样热内存，核对两侧读计数量级是否反映各自真实访问（不要求两边相等）。

### 7.3 phase 归属（仅 grhsim）

grhsim 边界 op 的 compute/commit phase 归属仍以 `isCommitPhaseOp`（`grhsim_cpp.cpp:2273`）+ `supernodeHasComputePart/CommitPart`（`:6533`）为准。三变量逐行统计时，写口落 commit 行、读/算落 compute 行，自然分离；但**内存读移入 src 后仍属 compute phase**（内存读不是 commit op），不要误判到 commit 行。

---

## 8. 升级后的成本公式与 TSV 变更

### 8.1 目标公式

```
T = Σ_i f[i]·( c_comp·n_comp[i] + c_src·n_src[i] + c_sink·n_sink[i] + c_const·n_const[i] + c_succ·a_succ[i] )
```

- `f[i]`：**超节点 i 的激活次数（整轮仿真累计的原始计数，不再除以总 eval/cycle 数）**。`Σ` 直接是整轮总工作量。
- `a_succ[i]`：超节点 i 中「为判断是否激活后继节点」而引入的变动检测比较次数。两种来源都要计（详见 §13.1）：
  - **compute 行**：op 结果值命中 `boundaryFanoutByValue` 的个数（现有口径，对应 `emitChangedValuePropagation` 的 `old!=new`）。
  - **commit 行**：有 reader 的写口（`state != next_value` 比较，驱动 `stateHeadSupernodesBySymbol` reader 激活）。**当前实现漏计此项，须修复。**
- **`N·A_exam` 项已移除**：NO0189 §11.5 实测全局激活扫描占比仅 1.3%–9.6%，作为模型项删去；若后续残差需要再议。
- `n_const` 为独立项，有自己的系数 `c_const`。
- 同一套 `c_*` 同时拟合 gsim 与 grhsim 两份 per-supernode 表。
- 期望：`c_sink > c_src > c_comp`，且拟合后 grh/gsim 的预测比贴近实测 8.4×（而非旧等权的 2×）。这是验证变量对齐是否「够用」的判据。

### 8.2 TSV schema（最终 8 列）

两侧各导出一份独立文件（`grhsim_supernode_cost.tsv` / `gsim_supernode_cost.tsv`），列完全一致：

```text
supernode_id  phase  f  n_comp  n_src  n_sink  n_const  a_succ
```

| 列 | 含义 |
| --- | --- |
| `supernode_id` | 稳定 id（grhsim `supernodeId` / gsim `cppId`） |
| `phase` | grhsim：`compute` / `commit`；gsim：`-` |
| `f` | 超节点激活次数（原始计数，§8.1） |
| `n_comp` | CPU 计算 op 数（含 DPI/system） |
| `n_src` | 状态读 op 数（reg/mem/latch read，per-occurrence） |
| `n_sink` | 状态写 op 数（reg/mem write、fill、latch write） |
| `n_const` | 常量物化数 |
| `a_succ` | 判断后继激活引入的比较/计算次数（grhsim commit 激活也计） |

**已删除的列 / 头**（无效或冗余）：

- `sim` 列：每份文件内恒为常量，文件名已承载，删。
- `f`（归一化 `fire_count/total_evals`）与单独的 `fire_count`：合并为单列 `f`（原始激活次数）。
- `e_total`：= `n_comp+n_src+n_sink`，可推导，删。
- grhsim 旧诊断 `e_source/e_compute/e_sink`、gsim 旧诊断 `e_node/e_ref_enode/e_nonref_enode`：被 n_* 取代，旧口径作废，删。
- 头注释 `# total_evals=<N>`：f 不再除它，删。
- 仅保留可选头注释 `# N_rows=<行数>` 作 sanity（不算列）。

**生产方式（emit 期输出 vs 运行期输出，刻意分开）**：`n_comp/n_src/n_sink/n_const/a_succ/phase` 是 **emit 期**结构量，`f` 是**运行期**动态量；二者本质不同，**分两个文件**，分析时按 `supernode_id` join（不强行合一）。
- **gsim**：emit 期 host 侧写 `<name>_supernode_static.tsv`（结构列，join 键 `supernode_id`）；运行期 `dump_runtime_profile()` 写 `<name>_supernode_fire.tsv`（`supernode_id f`）。静态列**不**烘进生成代码（避免 §10.3 的 N 条语句）。**已实施**（§14）。
- **grhsim**：同构两文件——emit 期写 `grhsim_supernode_static.tsv`（含 `phase`，join 键 `(supernode_id, phase)`），运行期写 `grhsim_supernode_fire.tsv`（`supernode_id phase f`）。NO0189 烘进生成代码的 `static constexpr` 静态表整体删除（§10.1）。**待实施**。

---

## 9. 决策点

全部已定（2026-06-12 与需求方确认）：

- **常量处理**：采用 §6 (A) 独立 `n_const` 列。✅
- **建模原则**：按真实执行计，不为对齐去重（§1.3）。✅
- **寄存器读 / 内存读单位**：grhsim 走 post-clone op 流（per-use，不去重）；gsim 删 dedup、按实际执行计；寄存器读与内存读 gsim 均 per-occurrence（`NODE_REG_SRC` 叶引用 / `OP_READ_MEM`）。✅
- **gsim 取值无 hoist → per-occurrence**：已核实（§7.1）。✅
- **XMR**：仿真阶段已无 XMR，`kXMRRead`/`kXMRWrite` **不计入任何类**。✅
- **DPI / system 调用**：`kDpicCall`/`kSystemFunction`/`kSystemTask` 归 **comp**。✅
- **latch / fill 的 gsim**：gsim 无对应建模，**记 0**。✅

无待决项，可直接据 §10 实施。

---

## 10. 实施改动点（确认决策后）

### 10.1 GrhSIM（`wolvrix/lib/emit/grhsim_cpp.cpp` / `lib/transform/activity_schedule.cpp`）

- **统一分类器（推荐，§4 落地方案 1）**：让 profile 计数复用 `classifyActivityOp`（`activity_schedule.cpp:2972`）为单一真相源；在累加侧把 Source 桶细分为 `n_src`（reg/latch/mem read）与 `n_const`（`kConstant`）。消除 `classifyRuntimeProfileOp` 与 `classifyActivityOp` 的矛盾（`kMemoryReadPort` 旧在 Compute）。
- 若暂不统一：就地改 `classifyRuntimeProfileOp`（`:2697`）——`kMemoryReadPort`→src、`kConstant`→独立 `Const`，并加注释要求与 `classifyActivityOp` 保持一致。
- `buildRuntimeProfileWeights`（`:2722`）：遍历 **post-clone** `supernodeToOps`（克隆已展开，per-use 自然正确），把 `runtimeProfileSource/ComputeOpsBySupernode` 重义为 `n_src/n_comp`，新增 `n_const`；sink 数组沿用。**不要加任何去重**。
- **`f`（原始激活次数）**：沿用 NO0189 的 per-phase 触发计数器 `runtime_profile_fire_compute_` / `runtime_profile_fire_commit_`（超节点 body 进入时自增），TSV **直接写原始计数**。**删除归一化相关**：不再需要 `eval_invocation_count_` / `total_evals`（f 不除它），相应生成与 init 清零可去。
- **`a_succ` 含 commit（已确诊漏计，修复见 §12.1）**：现统计只覆盖 compute 行（命中 `boundaryFanoutByValue`）；须在 `buildRuntimeProfileWeights` 补 commit 行——对有 reader 的写口（`stateHeadSupernodesBySymbol` 非空）各 +1。
- **删除无用中间统计变量（见 §12.2）**：`eval_invocation_count_`、`runtime_profile_active/compute/commit_supernodes_`、`runtime_profile_compute_nodes_` 及其 host 源 `runtimeProfileComputeNodesBySupernode`、edge 拆分计数与 `[GRHSIM_RUNTIME_PROFILE_EDGE]` printf。保留 `grhsim_classify_edge` 函数与 `boundaryFanoutByValue`。
- **emit 期 / 运行期两文件拆分（与 gsim §10.2 对齐）**：把静态列从生成代码移到 emit 期文件，与 gsim 同构。
  - **emit 期**：host 侧（`grhsim_cpp.cpp` emit 末尾）写 `grhsim_supernode_static.tsv`，列 `supernode_id phase n_comp n_src n_sink n_const a_succ`（per supernode-phase，每 supernode 出 compute / commit 两行）。**因此 NO0189 烘进生成代码的 `static constexpr` 静态表可整体删除**——生成代码不再带这些静态数组，更省编译。
  - **运行期**：`dump_runtime_profile()` 只写 `grhsim_supernode_fire.tsv`，列 `supernode_id phase f`（`runtime_profile_fire_compute_/commit_` 直接写原始计数；删归一化与 `eval_invocation_count_`/`total_evals`/旧聚合 printf）。
  - **join 键**：`(supernode_id, phase)`（grhsim 两行/supernode）；gsim 单行用 `supernode_id`。
- 测试 `wolvrix/tests/emit/test_emit_grhsim_cpp.cpp`：更新断言（内存读入 src、常量入 n_const、含 source clone 的多读计数、emit 期 static 文件列、运行期 fire 文件列 `supernode_id phase f`、**commit 行 a_succ 非空**、生成代码不再带静态表与已删统计变量）。

### 10.2 GSIM（`reference/gsim/src/cppEmitter.cpp`）—— 基于重置后基线，**编译时间安全**

> 背景：上一轮按旧计划改 gsim 后，生成 cpp 的编译时间从 5 分钟膨胀到 1 小时，已回滚。根因见 §10.3。本节按**重置后的当前基线**（commit `add stats emit`）重写步骤，并把「不膨胀编译」作为硬约束。

**重置后基线现状（与旧计划差异大，务必以此为准）**：
- `RuntimeProfileWeights`（`cppEmitter.cpp:62`）只有 `nodes / refENodes / nonRefENodes` 三字段；**没有** `sourceOps/sinkOps/ops`、**没有** `collectRegReadRefs`、**没有** per-supernode TSV / fireCount / a_succ。
- 静态权重经 3 个成员数组 `runtimeProfile{Node,RefENode,NonRefENode}Weight[superId]`（header 声明），在 init 里用 **每超节点 3 条赋值语句** `runtimeProfileXWeight[cppId] = ...;`（`:1185-1187`）填充 —— 这是 §10.3 的编译炸弹形状。
- dump 只打印一行聚合 `[GSIM_RUNTIME_PROFILE]`（`:1256`），无 per-supernode 输出。
- gsim 已有 **host 侧 emit 期文件写出** 的先例：`writeSupernodeStatsJson`（`:187`，`:1302` 调用，写 `OutputDir/<name>_supernode_stats.json`）—— 这正是编译安全的模式，本计划沿用它。

**关键架构决定（emit 期输出 vs 运行期输出，刻意分开）**

`n_*`/`a_succ` 是 **emit 期结构量**（gsim 编译时即知）；`f` 是**运行期动态量**。二者本质不同，**分两个文件**：emit 期由 host 写静态结构表，运行期由 `dump_runtime_profile()` 写 fire 表。分析时按 `supernode_id` join。这样既清晰区分两类数据，又天然避免把静态量塞进生成代码（§10.3 的编译炸弹）。

- **静态列**（`n_comp/n_src/n_sink/n_const/a_succ`）：host 侧 `writeSupernodeCostStaticTsv` emit 期写 `<name>_supernode_static.tsv`，**绝不**进生成代码。
- **运行期 `f`**：单数组 `runtimeProfileFireCount[superId]`，init 一个 `for` 循环清零，`genNodeStepStart` 的 `if (runtimeProfileEnabled)` 块内 `++`（每 body 一条，分布、廉价）。
- **运行期 dump** 写 `<name>_supernode_fire.tsv`（`supernode_id f`），env `GSIM_SUPERNODE_TSV` 覆盖路径。

> 注：const 数据表本身编译安全（实测 5×84714 int 仅 0.18s），但**还是分文件更对**——emit 期结构数据不该混进运行期 dump，分开既符合数据语义，也让生成代码最小。

**实施步骤**：

1. **host 侧计数（`RuntimeProfileWeights` 扩展，`cppEmitter.cpp:62`）**：在 `countRuntimeProfileTree/Node/Supernode`（`:68-125`）新增字段并实现 §5/§7 口径：
   - `comp`：非叶、非 `OP_INT`、非 `OP_INDEX/OP_INDEX_INT`、**非 `OP_READ_MEM`** 的 opType ENode（per-occurrence）。
   - `src`：`NODE_REG_SRC` 叶引用 **per-occurrence（不去重）** + `OP_READ_MEM` per-occurrence（§7.1/7.2，gsim 无 hoist 已核实）。
   - `sink`：成员节点 `NODE_REG_DST` + `NODE_WRITER` + `NODE_READWRITER`。
   - `constv`：`OP_INT` ENode per-occurrence。`aSucc`：`needActivate() && !isArray() && type != NODE_WRITER` 的成员数。`phase`：gsim 恒 `-`。
2. **emit 期静态文件**：`writeSupernodeCostStaticTsv` 遍历 `sortedSuper` 写 `<name>_supernode_static.tsv`（列 `supernode_id phase n_comp n_src n_sink n_const a_succ`），在 `cppEmitter` 末尾 `emitRuntimeProfile()` 门控下调用。
3. **生成代码运行期 f**：header 加 `uint64_t runtimeProfileFireCount[superId];`；init 加 `for` 循环清零；`genNodeStepStart` profile 块内加 `runtimeProfileFireCount[cppId]++;`；`dump_runtime_profile()` 用 `for` 循环写 `<name>_supernode_fire.tsv`。
4. **清理**：旧聚合 enode 三数组的「每超节点 3 赋值语句」（`:1185-1187`，§10.3 同形中间量）**不要在其上加列**；旧聚合 dump 保留不动。

### 10.3 编译时间炸弹根因（务必避免重犯）

- gsim 把 per-supernode 静态数据**烘进生成代码、且以「每超节点一条赋值语句」集中在一个 init 函数里**（`runtimeProfileXWeight[cppId]=val;`）。XiangShan 下 `superId ≈ 8.5 万`，基线 3 数组 = ~25.5 万条语句，编译 ~5 分钟。
- 单函数内语句数对编译时间是**超线性**（部分 pass 近二次）。上一轮加了 ~5–6 个同形静态数组（n_comp/src/sink/const/a_succ/fire），语句数 ~3 倍 → 编译 ~12 倍 → 1 小时。
- **铁律**：区分**数据**与**语句**。per-supernode 静态量可烘进生成代码，但**必须是 `static const` 大括号初始化数组（数据，进 .rodata，编译近线性；实测 5×84714 int 仅 0.18s）**，**绝不可**展开成「每超节点一条赋值/printf 语句」集中在一个函数里（语句数对编译超线性，正是 1 小时的根因）。生成代码里 per-supernode 的运行期新增只允许 **O(1) per body**（fire 自增）+ **O(N) 循环**（清零/dump）。grhsim 侧（§10.1）同此——其静态 `n_*` 用 `static constexpr` 数据表（grhsim 既有做法即 per-row brace-init 结构数组），不可展开成 N 条语句。

---

## 11. 验收（sanity check）

- 逐行 `n_comp + n_src + n_sink + n_const`（grhsim 再 + Ignored=0）= 该超节点对应口径的 op 总和，两侧各自自洽。
- **内存读迁移核对**：迁移后两侧 `n_comp` 应较 NO0189 的 `e_compute` 减少（少了内存读），`n_src` 应增加；差值 = 内存读计数，逐行可核。
- **常量剥离核对（grhsim）**：`n_src`（新）= NO0189 `e_source` − `n_const`，逐行可核。
- **source clone / 去重核对（关键，验证 §1.3 落地）**：gsim 删 dedup 后 `n_src` 应**较旧 per-distinct 口径上升**；grhsim `n_src` 应反映 source clone 后的 per-use 量级（与 `sourceClonesInComputeNodes` 统计量级一致）。**预期 grhsim `n_src` 明显大于 gsim**——若仍接近 0.6×，说明 dedup 未真正去掉或 clone 未计入，需复查。
- 抽样热超节点（参考 [`NO0189`](./NO0189_grhsim_gsim_supernode_cost_tsv_instrument_plan_20260611.md) §11.2 的热 sink/source），核对三变量与源码一致。
- **不要求两侧计数相等**：按 §1.3，两侧 `n_*` 反映各自真实执行量，差异是预期信号；sanity 只核「各自与本仿真器发射代码一致」，而非「两边数字看齐」。
- **schema 核对**：TSV 恰为 8 列 `supernode_id phase f n_comp n_src n_sink n_const a_succ`，无 `sim`/归一化 `f`/`e_*`/`total_evals`。
- **`f` 核对**：`f` 为原始累计计数（非比率）；抽样热超节点核对其量级与历史激活分布一致。
- **`a_succ` commit 核对**：grhsim `phase=commit` 行的 `a_succ` 应**非全 0**（修复后 commit 激活已计入，§13.1）；抽样一个写寄存器后驱动后继的热超节点核对 = 该超节点中有 reader 的写口数。
- 关闭 profile 时 TSV 不生成、runtime 无回退（沿用 NO0189 的 env/宏门控）。

---

## 12. commit a_succ 修复与中间统计变量清理

> 本次重构同时收口两件事：(1) 修正 commit 行 a_succ 漏计；(2) 删除重构后已无用、易误导的中间统计变量。**`boundaryFanoutByValue` 不在删除之列**——它是真实代码生成（变动检测发射）依赖的载荷结构，compute 行 a_succ 也从它派生。

### 12.1 commit a_succ 漏计与修复（已核实）

**现象**：当前 `runtimeProfileASuccBySupernode`（`grhsim_cpp.cpp:2764-2769`）只对每个 op 的 `op.results()` 检查是否命中 `boundaryFanoutByValue`。这套口径只覆盖 **compute 行**（计算值的 `old!=new`，由 `emitChangedValuePropagation` 发射）。

**commit 行被漏**：commit 写口的真实发射（scalar register `:11673`、内存 `:11600/11640`）形如

```cpp
const auto next_value = ...;
if (state != next_value) {        // commit 变动检测比较
    state = next_value;
    emitReaderActivations(...);    // 经 stateHeadSupernodesBySymbol 激活下游 reader
}
```

激活走的是 `stateHeadSupernodesBySymbol`（按 state symbol），写口 op **不产生进入 `boundaryFanoutByValue` 的结果值**，故现有统计对 commit 行恒计 0 —— **漏计**。

**修复**：在 `buildRuntimeProfileWeights` 内，对 commit phase 的写口 op 追加统计：

```text
若 isWritePortKind(op.kind())：
  查 model.writeByOp[opId] → write.symbol
  若 model.stateHeadSupernodesBySymbol[write.symbol] 非空（hasReaders）
    → ++a_succ[supernodeId]   // 该写口发射一处 old!=next 比较来驱动 reader 激活
```

- 依赖可用性已核实：`buildRuntimeProfileWeights` 在 `:13143` 调用，晚于 `writeByOp`(`:6466`)、`stateHeadSupernodesBySymbol`(`:6891`) 构建，可直接读。
- **决策点**：无 reader 的写口仍发射 `old!=next`（用于跳过冗余写），但不驱动后继激活 → 建议**不计入 a_succ**（它属 sink 的写优化，非「判断后继激活」）。即只数 `hasReaders` 的写口。
- 内存 fill 是按行循环比较（`any_row_changed`，`:11494`），形态不同；按「每写口一处变动检测构造」计 1，保持与 grhsim 一行一比较的语义一致（实施时确认）。

### 12.2 删除的中间统计变量（重构后无用 / 易误导）

下列变量在新模型（per-supernode TSV：f/n_comp/n_src/n_sink/n_const/a_succ）下已无用，且留着会误导后人，**随本次重构一并删除**：

| 变量（生成代码 / host） | 现用途 | 删除理由 |
| --- | --- | --- |
| ~~`eval_invocation_count_`~~ | —— | **更正：保留**。实现时核实它在 `model.emitPerf‖emitWaveform` 守护下，是 perf/waveform 计数器（`dump_waveform(eval_id)`、trace interval），**非** profiling 归一化分母；profile dump 早已写原始 `f`。故不删。 |
| `runtime_profile_active_supernodes_`（生成，`:11772/16919/17557/19488/19741`） | 旧聚合「活跃超节点数」 | per-supernode `Σf` 已替代；且仅喂旧聚合 printf 与 edge-delta |
| `runtime_profile_compute_supernodes_` / `_commit_supernodes_` / `_compute_nodes_`（生成，`:16920-16922/17558-17560`） | 旧聚合 printf | per-supernode TSV 已替代 |
| `runtimeProfileComputeNodesBySupernode`（host，`:2562/2727/2737`） | 仅喂 `runtime_profile_compute_nodes_` | 上行删后即死代码；且「compute 节点数」与 `n_comp`（op 数）语义混淆，易误导 |
| edge 拆分计数：`runtime_profile_{eval,rounds,active}_{pos,neg,other}_`、`_active_delta_`、`_active_start_`、`_clock_edge_`（生成，`:16930-16938/19272-19280/19488/19741`）+ `[GRHSIM_RUNTIME_PROFILE_EDGE]` printf（`:17566-17576`） | NO0189 §11.4 负沿/正沿一次性归因 | 一次性分析产物，非成本模型列，留着误导 |

**保留（不要误删）**：
- `runtime_profile_enabled_`（开关）。
- `runtime_profile_fire_compute_` / `runtime_profile_fire_commit_` → `f`。
- `runtimeProfileSource/Compute/SinkOpsBySupernode` → 重义为 `n_src`(剔 const)/`n_comp`/`n_sink`，新增 `n_const`。
- `runtimeProfileASuccBySupernode` → `a_succ`（按 §12.1 修复；进 emit 期 static 文件）。
- `runtimeProfileSource/Compute/Sink/ConstOpsBySupernode` → emit 期 static 文件的 `n_src/n_comp/n_sink/n_const`。
- **`grhsim_classify_edge` 函数**：真实事件边沿检测仍用，**只删 edge 计数器，不删此函数**。
- **`boundaryFanoutByValue`**：codegen 载荷，保留。

### 12.3 清理后的 sanity（已实现态，§15）

- 生成代码内 `grep runtime_profile_` 只应剩：`enabled_`、`fire_compute_/commit_`；profiling 的 `*_supernodes_`、`*_nodes_`、edge 拆分计数、EDGE printf 均已无（先前工作已删）。
- 运行期 dump 不再烘 7 字段静态 `kRows` 表（只剩最小 `(id,phase)` 表），静态列全在 emit 期 `grhsim_supernode_static.tsv`；fire 文件无 `# N_rows`/`# total_evals`。
- `eval_invocation_count_` 仍在（perf/waveform，非 profiling）。
- 编译无 unused 警告（host 侧 `runtimeProfileComputeNodesBySupernode` 等彻底移除，不是留着不赋值）。

---

## 13. 不在本计划范围

- 系数 `c_comp/c_src/c_sink/c_const/c_succ` 的回归拟合、两侧残差归因（另起 `NOxxxx`）。
- 本计划已定下 `f[i]`（原始激活次数）、`a_succ[i]`（含 grhsim commit 激活）口径，并移除 `A_exam` 项；这些不再是待议项。
- 任何 emitter 优化/重构（只读结构 + 改分类计数，不改调度与代码形态）。
- 默认 build 行为变更（插桩一律 env/宏门控，缺省关闭）。

---

## 14. GSIM 实施记录（2026-06-13）

按 §10.2 落地，全部改动在 `reference/gsim/src/cppEmitter.cpp`，**编译安全**（静态列走 emit 期文件，生成代码零新增 per-supernode 静态赋值语句）。

**改动**：
- `RuntimeProfileWeights`（`:62`）新增 `comp/src/sink/constv/aSucc` 字段。
- `countRuntimeProfileTree`：叶子 `nodePtr->type==NODE_REG_SRC` → `src`（per-occurrence，不去重）；非叶 `OP_INT`→`constv`、`OP_READ_MEM`→`src`、`OP_INVALID/EMPTY/INDEX/INDEX_INT` 跳过、其余→`comp`。
- `countRuntimeProfileNode`：成员 `NODE_REG_DST/NODE_WRITER/NODE_READWRITER`→`sink`；`needActivate() && !isArray() && type!=NODE_WRITER`→`aSucc`。
- 新增 host 函数 `writeSupernodeCostStaticTsv`（仿 `writeSupernodeStatsJson`），emit 期写 `<name>_supernode_static.tsv`（列 `supernode_id phase n_comp n_src n_sink n_const a_succ`，gsim `phase=-`），在 `writeSupernodeStatsJson` 调用后、`emitRuntimeProfile()` 门控下调用。
- 生成代码：header 加 `runtimeProfileFireCount[superId]`；init 加 `for` 循环清零（非每元素）；`genNodeStepStart` 的 `if (runtimeProfileEnabled)` 块内加 `runtimeProfileFireCount[cppId]++`；`dump_runtime_profile()` 用 `for` 循环写 `<name>_supernode_fire.tsv`（列 `supernode_id f`，env `GSIM_SUPERNODE_TSV` 覆盖路径，缺省 emit 目录）。
- **未触碰**旧聚合 enode profiler（3 数组 + `[GSIM_RUNTIME_PROFILE]`），故 XS 规模编译时间 = 基线（未在其上加列）。可选后续：按 §12.2 用 emit 期文件替换它以进一步提速。

**验证**（`test/repro-usefulreset.fir`）：
- `make build-gsim` 通过（增量 1.5s）。
- `GSIM_EMIT_RUNTIME_PROFILE=1` 生成：emit 期产出 `_supernode_static.tsv`，内容 `0 - 16 23 3 12 3`。
- 生成 cpp 编译 0.3s；最小 harness 运行后产出 `_supernode_fire.tsv`（`0 1`）。
- **内部一致性交叉校验**：聚合 `non_ref_enodes=28` == `n_comp(16)+n_const(12)`（此设计 `OP_READ_MEM=0`），证明 comp/const 拆分正确。
- 离线 join static+fire → 8 列 schema 与 §8.2 完全一致。
- `GSIM_EMIT_RUNTIME_PROFILE=0`：无 `_supernode_static.tsv`、生成代码无 `runtimeProfileFireCount`、默认模型编译通过——默认 build 无回退。
- **编译安全确认**：生成 cpp 中我方 `n_*` 的 per-supernode 静态赋值语句数 = 0（静态列全在文件里）。

**未做**（不在本次范围）：XiangShan 全规模重新生成与端到端 50k 跑（需较长 build；架构上编译时间 = 基线，因未新增任何 per-supernode 集中静态语句）。

> 2026-06-13 追加：gsim 已按需求方意见从「单文件」回退为 **emit 期 static 文件 + 运行期 fire 文件**两文件（区分 emit/runtime 输出）；XS 50k 实测产物见 `tmp/no0190_xs_grhsim_runtime_profile_20260612_143212/`（`SimTop_supernode_static.tsv` + `SimTop_supernode_fire.tsv`）。

---

## 15. GrhSIM 实施记录（2026-06-13）

代码：`wolvrix/lib/emit/grhsim_cpp.cpp`、测试 `wolvrix/tests/emit/test_emit_grhsim_cpp.cpp`。

**入场状态**：分类器（`Const` 类、`kMemoryReadPort→Source`、XMR→Ignored）、`n_const` 数组、**commit a_succ 修复**（写口有 reader 时 +1，`buildRuntimeProfileWeights` `:2768-2779`）已由先前工作就位（§7/§8/§12 大部已实现）。`eval_invocation_count_` 经核实属 perf/waveform，保留（§12.2 更正）。

**本次改动（§10.1 两文件拆分，与 gsim §10.2 对齐）**：
- **emit 期 static 文件**：orchestrator（`:13230` 一带，`buildRuntimeProfileWeights` `:13134` 之后）新增 host 写出 `outDir/grhsim_supernode_static.tsv`，列 `supernode_id phase n_comp n_src n_sink n_const a_succ`，遍历 `computeSupernodeIds`(phase=compute)+`commitSupernodeIds`(phase=commit)，取 `runtimeProfile{Compute,Source,Sink,Const,ASucc}OpsBySupernode`。**不进生成代码**。
- **运行期 fire 文件**：`dump_runtime_profile()` 删除原 7 字段 `kRows` 静态 constexpr 表，改为最小 `(supernodeId, computePhase)` 表 + 写 `grhsim_supernode_fire.tsv`，列 `supernode_id phase f`（`f` 取 `runtime_profile_fire_compute_/commit_`，原始计数）。env `WOLVRIX_GRHSIM_SUPERNODE_TSV` 改指 fire 文件，缺省 `outDir/grhsim_supernode_fire.tsv`。删 `# N_rows` 头。
- **join 键** `(supernode_id, phase)`。

**测试更新**：`test_emit_grhsim_cpp.cpp` 断言改为——生成 state.cpp 含 3 列 fire 头 `supernode_id\tphase\tf`、不含 8 列头/`# N_rows`/静态列；新增校验 emit 期 `grhsim_supernode_static.tsv`（7 列、含 compute/commit 行、commit 行 a_succ 非全 0）；运行期 fire TSV 为 3 列、含 compute+commit 行。

**验证（均通过）**：
- `cmake --build wolvrix/build --target emit-grhsim-cpp emit-grhsim-cpp-memory-fill`：编译通过。
- `ctest -R '^emit-grhsim-cpp$'`：**Passed**（60.7s；含实际 make 生成、编译、运行 harness、核对两文件）。
- `ctest -R '^emit-grhsim-cpp-memory-fill$'`：**Passed**（2.7s）。

XiangShan 全规模 grhsim 50k 实测：见 §16（与 gsim 同批跑完，两文件已对齐）。

---

## 16. 使用说明：开关 profile 与输出格式（2026-06-13）

> 数据分析（系数回归、两侧对比）不在本节，另起 `NOxxxx`。本节只记录怎么开 / 关 profile 与产物格式。

### 16.1 开关 profile

两阶段各一个开关，缺省全关（默认 build 无 profile 代码、无产物、无回退）：

| 阶段 | gsim | grhsim |
| --- | --- | --- |
| **emit（编译期生成 profile 代码 + 写 static 文件）** | env `GSIM_EMIT_RUNTIME_PROFILE=1` | env `GRHSIM_EMIT_RUNTIME_PROFILE=1`（等价 emit 选项 `emit_runtime_profile=1`） |
| **run（运行期开计数 + 写 fire 文件）** | env `EMU_RUNTIME_PROFILE=1` | env `EMU_RUNTIME_PROFILE=1` |
| **关闭** | 两个 env 都不设（或 `=0`） | 同左 |

注意：**run 阶段要生效，emit 阶段必须也开过**（fire 计数器与 dump 是 emit 期按开关生成的）。

### 16.2 输出文件与路径

每侧两份文件：emit 期写 **static**，run 结束 dump 写 **fire**。

| sim | static（emit 期，缺省路径） | fire（run 期，缺省路径） | fire 路径覆盖 env |
| --- | --- | --- | --- |
| gsim | `<outDir>/<name>_supernode_static.tsv` | `<outDir>/<name>_supernode_fire.tsv` | `GSIM_SUPERNODE_TSV` |
| grhsim | `<outDir>/grhsim_supernode_static.tsv` | `<outDir>/grhsim_supernode_fire.tsv` | `WOLVRIX_GRHSIM_SUPERNODE_TSV` |

`<outDir>` = 该模型的 emit 输出目录；`<name>` = 顶层模块名（XS 下 `SimTop`）。static 文件无 env 覆盖（emit 期固定写 outDir）。

### 16.3 输出格式（列与示例）

**static**（emit 期，结构列；TSV，制表符分隔）：

```text
supernode_id	phase	n_comp	n_src	n_sink	n_const	a_succ
```
- gsim 示例（`phase` 恒 `-`）：`0	-	5	10	0	5	5`
- grhsim 示例（每 supernode 分 compute / commit 行）：
  - `0	compute	8	24	0	30	46`
  - `72138	commit	0	0	4096	0	4096`

**fire**（run 期，动态激活计数）：

```text
# gsim：
supernode_id	f
0	1030

# grhsim（多 phase 列）：
supernode_id	phase	f
0	compute	19641
```

join 键：gsim `supernode_id`；grhsim `(supernode_id, phase)`。

### 16.4 XS CoreMark 50k 全流程命令（实跑示例）

```bash
source ./env.sh
# gsim
GSIM_EMIT_RUNTIME_PROFILE=1 make xs_gsim_emu XS_VM_BUILD_JOBS=32
EMU_RUNTIME_PROFILE=1 GSIM_SUPERNODE_TSV=<dir>/gsim_supernode_fire.tsv \
  make run_xs_gsim_emu XS_SIM_MAX_CYCLE=50000
# grhsim
GRHSIM_EMIT_RUNTIME_PROFILE=1 make xs_wolf_grhsim_emu XS_VM_BUILD_JOBS=32
EMU_RUNTIME_PROFILE=1 WOLVRIX_GRHSIM_SUPERNODE_TSV=<dir>/grhsim_supernode_fire.tsv \
  make run_xs_wolf_grhsim_emu XS_SIM_MAX_CYCLE=50000
```

static 文件在各自 emit 目录（gsim：`build/xs/gsim/gsim-compile/model/`；grhsim：`build/xs/grhsim/grhsim_emit/`），手动拷到收集目录即可。一次实跑产物见 `tmp/no0190_xs_gsim_grhsim_runtime_profile_20260613_131543/`（两侧各 static + fire 共 4 份 + 日志）。
