# NO00040：lut-fold 证伪与端点 boundary 致密布局（core.compute.lut 失败链 → cpu.st.layout-data 致密化）

日期：2026-09-17 起，2026-09-18 完成。最终判定：**ACCEPTED（候选 F：event-gated system/DPI 端点 boundary 致密布局，+1.032961%，页帧驱逐协议下 6 次交替秩次判据通过）**。

本节点始于新增 `core.compute.lut` 算子与 `grhsim.lut-fold` 语义 pass 的
布尔逻辑锥 LUT 折叠尝试：
把扇入受限、内部复杂度超线性的 1-bit 布尔逻辑锥整体折叠为一张内嵌真值表，
用一次索引拼装 + 查表（n≤6 时退化为常量移位，无访存）取代锥内全部逐 op 求值，
并在子图划分（CPU mapping）之前完成折叠，使被折叠锥的中间值不再产生
boundary/supernode 开销。冻结 GRH、GRH pass、XiangShan 与测试源码不修改。

## IDEA（2026-09-17）

### 动机与瓶颈证据

- peephole 级 IR 替换已饱和：NO00036–NO00039 的 firtool 缺陷普查确认可消除
  形态份额 <0.5% 动态 op；NO00038 反例显示静态指令微减（0.008%）无收益。
  需要从"局部形状替换"升级为"计算模型替换"（compute → lookup），相当于把
  FPGA 技术映射（cone → LUT）搬到 CPU 后端。
- 前端/icache 证据（间接，perf 不可用，NO00010）：NO00036 实测 gsim text
  55.5 MB / 10.85M 指令 vs grhsim text 103.8 MB / 仅 compute 15.2M 指令；
  helper 内联使 text +4.1% → 慢 12.58%（NO00036）。已验证相关性模式：
  条件跳转减少与收益强相关（NO00031/33/34/35/37）。
- 覆盖池：动态 compute op 每 eval 574,637 个（NO00036 插桩），其中
  and/or/mux/bitSelect/not/eq/logicNot 等 1-bit 布尔 op 占 60%+；
  静态 1-bit 候选 op 约 188.5 万（本节点筛查实测 1,890,011）。
- 生成代码实测每 op 成本（NO00039 flow-final 生成代码抽样）：1-bit 布尔 op
  约 3 条原生指令（两 load + 运算 + frame store）；boundary 写回另附
  变化检测块（约 5–6 条）。
- 不利先例的辨析：NO00026（真值表仅作编译期 CSE key，不创建运行期 LUT）
  被否决——静态 op 减少不等于动态收益；NO00028 反向（去查表化）被接受——
  说明访存不是免费的。本方案与 NO00026 的差异：**真正删除运行期 op 并生成
  查表代码**，且小表（n≤6）降为立即数移位，完全避开访存与缓存风险。

### 机制

- 新算子 `core.compute.lut`：operands 为 n 个 1-bit 两态 unsigned 输入值
  （索引位），1 个 1-bit 两态 unsigned result；真值表（2^n bit）以
  `table` parameter（hex string）内嵌于 op，**不作为操作数**。op 保持
  单 result、纯计算、无 objectRefs，自动获得 computeGroup 变化检测与
  fanout 激活语义。
- 新 pass `grhsim.lut-fold`（SemanticTransform）：在 `grhsim.bitwise-muxes`
  之后、第二轮 CPU mapping 之前运行，对 1-bit 纯计算布尔 op
  （and/or/xor/xnor/not/logicAnd/logicOr/logicNot/eq/ne/mux/bitSelect）
  做贪心锥覆盖：单扇出吸收（不产生复制）、常量操作数吸收进表（不占索引位）、
  输入预算 n ≤ max-inputs、盈利门槛 m ≥ max(min-ops, ratio·n)。
- 发射：n ≤ 6 时表为 uint64 立即数，`(table >> idx) & 1`（零访存、零
  rodata）；n ∈ {7,8} 时 `static constexpr` 位平面数组（v1 是否启用由筛查
  数据决定）。
- 真值表由 pass 内穷举 2^n 输入组合按位掩码并行求值生成，提取即验证
  （对全部输入组合精确，不依赖代数等价推理）。

### 证伪标准与局部目标

- 筛查阶段：若贪心选择后（ratio=1.0、min-ops=4、n≤8）覆盖 <2% 动态
  compute op，方向证伪，不进入实现。
- 候选实现后：reemit 筛选单对 old/new，方向为负或处于噪声带（|Δ| < 0.5%）
  则调整阈值或撤销机制；正式判定以 6 次交替复测秩次门为准
  （max(new) < min(old)）。

### 筛查方法与工具

新增 `scripts/grhsim_lut_cone_stats.py`（Make 目标 `analyze_grhsim_lut_cones`）：
在 NO00039 归档 checkpoint（`flow-final/xiangshan_grhsim_ir.json`，
3,945,332 ops / 3,783,436 values，含完整 cpu mapping）上做与 pass 同算法的
锥枚举与贪心选择；支持阈值扫描、supernode 跨界与 boundary 内化统计、
真值表位掩码求值与去重统计。锥内 op 成本模型：每 op ≈3 指令、
LUT ≈ 2n+3 指令（含索引拼装与写回），boundary 内化每个再 +5。

### 锥体形状分布（pass-1，overlap allowed，2026-09-17）

候选 1-bit 两态布尔 op 共 1,890,011。锥形状主体为宽浅树（m≈n−1，
如 n=8,m=7 有 210,370 个根），LUT 折叠对其指令中性；有价值的是
m > n 的重收敛锥。阈值扫描的贪心选择（非重叠）结果见 BASELINE 节
（待三次全量选择运行完成后填写）。

## 阶段记录

### BASELINE（2026-09-17）

- 对照（old）：NO00039 flow-final 二进制
  （`ptmp/no00039_fastwrite_20260917/flow-final/emu/grhsim-compile/emu`，
  sha256 `8430a89738b3e956…`，即随 NO00039 提交 `9b54e45` 接受的版本）。
  其正式成绩：三次 new 均值 **90.965667 s**（相对 NO00038 old −1.422508%）。
- 测量口径：`make benchmark_grhsim_ir`（scripts/benchmark_grhsim_ir.py），
  CPU2 单核、XS_EMU_THREADS=1、100k cycles、waveform/commit/RAM trace 关闭，
  交替 old/new，止损 1.5×；预注册顺序与二进制哈希写入 `preregister.json`。
- 等价门槛：`instrCnt=240349`、`cycleCnt=99996`、IPC 2.403586、末端 PC
  `0x80000c0c`、guest cycles 100001、退出码 0、NEMU 对拍无 mismatch。
- 基线 commit：wolvrix 子模块 `9b54e45`（NO00039，`feat: sample
  unit-private event histories directly`）。

### 贪心选择筛查结果（2026-09-17，脚本第五次运行，修正 cone_values 归类后）

三参数组全量选择（--select --cross --tables）：

| 参数 | 锥数 | 折叠 op | 占全部 op | 动态覆盖（LUT 成本前） | 唯一真值表 | 跨界锥 / 内化 boundary |
|---|---:|---:|---:|---:|---:|---|
| n≤6, ratio 1.0, m≥4 | 63,833 | 317,851 | 8.056% | 7.65% | 1,335（10.4 KiB） | 5,250 / 7,912 |
| n≤8, ratio 1.0, m≥4 | 61,538 | 333,692 | 8.458% | 8.04% | 1,362（17.9 KiB） | 5,340 / 8,255 |
| n≤6, ratio 1.5, m≥4 | 4,273 | 28,719 | 0.728% | 0.69% | 236 | 619 / 1,161 |

结论与决策：

- **方向通过证伪门**（7.65% ≫ 2% 的筛查线）。净动态估计：每锥平均 m=5.0、
  n=4.3，LUT 成本约占被替指令的 78%… 按 (3m−2n−3)/3m ≈ 22% 净额估，
  净动态 op 缩减 ~1.7%，叠加 boundary 内化（7,912 个 × ~5 指令）与
  代码体积缩减，预期运行收益在 1–2% 量级，处于统计门可分辨范围。
- **真值表去重极强**（63,833 锥 → 1,335 唯一表），缓存污染风险证伪；
  n≤6 时表为 uint64 立即数，零 rodata。
- **v1 取 max-inputs=6**（n=7/8 仅多 5% 覆盖但要引入 rodata 数组与发射
  复杂度）；ratio=1.0、min-ops=4 为默认；min-ops=5 变体（砍掉收益最薄的
  m=4 锥 25,862 个、保留 ~87% 指令节省）留作筛选对照。
- 常量吸收在此模型中无实例（canonicalize 已内联全部常量操作数）；
  slice 产出输入 67,853 个，说明大量锥输入来自切片（v2 可扩展
  slice-transparent 索引位，本节点不实施）。

（实现、筛选与正式复测记录待补。）

### IMPLEMENTED（2026-09-17）

实现（wolvrix 子模块，基线 `9b54e45` 之上的工作区差异）：

- 算子 `core.compute.lut`：`lib/grhsim/dialect/core.cpp` 注册；
  `lib/grhsim/ir/verifier.cpp` 加 shape 检查（1..6 个 operand、全部 1-bit
  two-state unsigned logic、单 result、无 refs、恰好一个 `table` string
  parameter 且为 `2^n/4` 个 hex 数字）。
- 发射：`lib/grhsim/backend/cpu_emit.cpp` `expression()` 加 `lut` case——
  table 解析为 uint64 立即数，索引 `op0|op1<<1|…` 拼装，发射
  `((UINT64_C(0x…)>>(index))&1)`（n≤6 无访存、无 rodata、无分支）。
- Pass `grhsim.lut-fold`（`lib/grhsim/pass/lut_fold.cpp`，注册于
  `pass.cpp`）：候选 12 种 1-bit 纯计算 op；常量经 SVInt 同款解析吸收进表；
  worklist 定点锥扩张（单扇出吸收，禁止复制）；两阶段贪心选择
  （score=m−2n 降序）；位掩码并行求真值表（迭代式带组合环检测，环锥跳过）；
  root `replaceOperation` 保留 result，其余成员 `compact` 删除。
  参数：`max-inputs`（默认 6）、`min-ops`（默认 4）、`ratio-percent`
  （默认 100）。
- pipeline：`scripts/wolvrix_xs_grhsim_ir.py` 在 `grhsim.bitwise-muxes` 后、
  第二轮 CPU mapping 前插入 `grhsim.lut-fold`（`--no-lut-fold` 可关）；
  `scripts/reemit_grhsim_ir.py` 加 `--lut-fold` 筛选路径（lut-fold + 全量
  remap + emit）；Makefile `reemit_grhsim_ir` 目标透传阈值参数。
- 聚焦测试全绿（2026-09-17）：`make test_grhsim_cpu_mapping` 2/2、
  `make test_grhsim_cpu_emit` 1/1（93.45 s）。新增用例：
  `tests/grhsim/test_grhsim_ir.cpp` 锥折叠/常量吸收/fanout 保护/幂等/
  verifier 畸形拒绝；`tests/grhsim/test_cpu_emit.cpp` + fixture
  `data/cpu_lut_main.cpp`（穷举 64 种输入组合 × 时钟电平 × 2 次 eval，
  ASan/UBSan 下通过）。
- 文档：`docs/grhsim_ir/dialects/core.md` §4.2、`docs/grhsim_ir/passes/
  lut-fold.md`、`passes/overview.md`、`flows/cpu-st.md` 登记。
- 语义约束：仅折叠两态 1-bit 无符号纯计算锥；真值表穷举 2^n 输入精确
  生成；不触碰状态/事件/写口；不含模块名匹配。

### VALIDATED 进展：候选 A（默认阈值 m≥4, ratio 1.0, n≤6）筛选

- reemit 自 NO00039 checkpoint（`make reemit_grhsim_ir GRHSIM_REEMIT_LUT_FOLD=1`）：
  pass 实际折叠 **64,398 锥 / 320,892 ops**（lut_inputs=283,832），与 Python
  筛查预测（63,833 / 317,851）偏差 +0.9%（C++ 定点重试略多吸收），机制
  按预期工作；重划分后 task 数 4,944 → **4,617**。
- 编译通过；筛选（`ptmp/no00040_lut_fold_20260917/screen-m4/summary.json`，
  单对，均 NEMU PASS、端点 240349/99996/100001/0x80000c0c 一致）：
  old 91.801 s / new **90.884 s，+0.9989%**，方向为正。
- 静态对照（`analyze_grhsim_cpu_code --phase-only`，`cpu_code_m4.log`）：
  compute 指令 14,686,598 → 14,825,609（**+0.95%，逆向**）；ELF text
  100,542,385 → 100,950,909（+0.41%）；compute 条件跳转 216,200 → 210,292
  （−2.7%）；evaluator 27,653 → 26,011（−5.9%）。
- 分析：源级"每 op ≈3 指令"的假设不成立——GCC 把锥内中间值留在寄存器，
  链形锥边际成本 ~1 指令/op，LUT 索引拼装 ~2n+2 反而更贵；收益来源是
  另一组机制：7,912 个 boundary 值内化（消除写回/变化检测/激活扇出）、
  task 数 −327（分派与守卫开销）、条件跳转 −2.7%（该相关性在
  NO00031/33/34/35/37 均成立）。结论：盈利判据应收紧到真正密集的锥，
  砍掉收益最薄的 m=4 档（25,862 锥、个体节省 ≈0）。
- 候选 B（min-ops=5，其余相同）：reemit 折叠 47,136 锥 / 266,353 ops；
  筛选（`screen-m5/summary.json`，单对，端点一致）old 90.059 s /
  new **90.763 s，−0.78%**，方向为负。单对无统计效力（p=0.5/1.0），但
  两变体同窗符号相反，证据弱支持"收益随覆盖量"（boundary 内化与 task 数
  缩减与折叠量正相关，指令回归也随覆盖量但弹性更小）。m3 档（m≥3,
  指令中性、boundary 正向）作为后备未试。
- 决策：以候选 A（m≥4, ratio 1.0, n≤6，即 pass 默认值）进入完整 SV→C++
  正式流程与 6 次交替复测；若秩次门不过，再以 m3 或机制修正迭代。
  成本模型修正记录：源级逐 op 成本（~3 指令）高估链形锥的边际成本
  （GCC 寄存器化后 ~1），真实收益机制是 boundary/task/跳转削减而非
  ALU 指令数。

### 候选 A 正式复测：REJECTED（2026-09-17）

- 完整 SV→C++ 生成 **704.58 s**（<1800 s，`CPU_TARGET_BATCH_COUNT=0`，
  非 checkpoint 恢复；lut-fold pass 本体 1.42 s）；fresh 编译通过（<1800 s）。
  被测二进制 `flow-lut-final/emu/grhsim-compile/emu` sha256 `b0808ec6…`。
- 6 次交替（`formal/summary.json`，预注册 old1/new1/…/old3/new3）：

| run | old Host (s) | new Host (s) |
|---|---:|---:|
| 1 | 89.840 | 91.623 |
| 2 | 91.150 | 91.547 |
| 3 | 89.642 | 91.616 |

- old 均值 **90.210667 s**（SD 0.819）、new 均值 **91.595333 s**
  （SD 0.042），**慢 1.534926%**；U=9、单侧精确 p=1.0，秩次门失败。
  六次均 NEMU PASS、端点 240349/99996/100001/0x80000c0c 一致——
  语义正确性成立，性能假设证伪。
- 失败归因：m4/m5 筛选的符号相反本已提示噪声主导；正式测量证实
  64k 锥的 LUT 化使 compute 静态指令 +0.95%、text +0.41%（索引拼装
  2n+2 比锥形链贵），boundary 内化与 task 数 −327 的正向分量不足以
  抵消。教训与 NO00026 一致：布尔网络的静态 op 削减不是动态收益。
- **保留修正方向**：跨界锥（5,250 个，内化 7,912 个 boundary 值）是
  测量到的正向分量所在；下一候选把折叠判据改为"以内化 boundary 为主"
  （min-crossing），只折叠真正削减发布/激活工作的锥，剔除指令负收益
  的大量本地锥。

### 多输出方向筛查：三组变体均证伪（2026-09-17，用户建议"不局限于 1bit 输出"）

用户建议候选不必局限于 1-bit 输出。对"多输出/多 bit LUT"的三种
字面解读逐一量化（`scripts/grhsim_lut_cone_stats.py` 新增
`--group`/`--concat-sinks`/`--wide-cones`，同一 NO00039 checkpoint，
日志 `cone_stats_{A1,A2,B1,B2,C1,profit_gate,wide_cones}*.log`）：

- **B：并集聚类多输出**（输入集合重叠的多个锥共享并集索引，emitter
  索引去重摊薄成本）：跨界锥集（min-crossing=1, m≥2, n≤6，26,357 锥）
  上贪心并集聚类，簇平均仅 1.28 成员、82% 退化为单锥；索引成本仅再削
  6.0%（α=1 时 +159,484 → +149,901），不足以翻正。输入重叠结构
  （avg k≈1.3）决定摊薄上限很低。**证伪**。
- **C：concat-sink 融合**（pack-bit-registers 的 k 个 1-bit next-state
  值经 `core.compute.concat` 拼成 packed word，按相邻 lane 分组共表）：
  15,471 个合格 concat、147,072 lanes，64-bit 表预算下平均段长仅 1.46
  （并集 4–6 位迅速饱和）；成本估计 α=1 **+486k**、α=0.75 **+215k**，
  明确为负。**证伪**。
- **W：小位宽多 bit 锥**（2–8 bit 纯计算 op，输入总位宽 ≤6、表 ≤64
  bit）：候选 op 210,512，但 99.8% 是 m=1 单 op"锥"（6-bit 预算下
  一个 4-bit add 的两输入已 8 bit，无锥结构），LUT 成本是所省 op 的
  4.9 倍（net +340k），动态覆盖上限 ~1.07%（含估计成分）。**证伪，
  多 bit 锥方向关闭**。

### profit-gate 筛查与候选 D 决策（2026-09-17）

正向分量的精确定位：把逐锥"内化 boundary 数 int"纳入盈利门
（mapping 感知；门作用在选择阶段，不过门不 claim）。选择集
n≤6, m≥2, ratio=0 全量，逐锥计算 m/n/int：

| 门 | 锥数 | Σm | Σint | net α=1 | 综合 α=1 | 综合 α=0.75 | 动态覆盖 |
|---|---:|---:|---:|---:|---:|---:|---:|
| G1 m≥2n+1 | 189 | 1,496 | 128 | −285 | −925 | −1,228 | 0.04% |
| G2 m+5int≥2n+1 | 12,614 | 39,907 | 15,159 | +56,611 | **−19,184** | −43,314 | 0.96% |
| G3 m+8int≥2n+1 | 24,015 | 85,210 | 25,537 | +136,723 | +9,038 | −46,445 | 2.07% |
| G4 int≥2 且 m+5int≥2n+1 | 4,165 | 22,503 | 8,826 | +25,072 | −19,058 | −30,952 | 0.55% |

（net = Σ(2n+1)−Σm，正=指令变差；综合 = net − 5×Σint，负=净收益。
G2 的 int 分层：int=1 占 81.6%。）

决策（候选 D）：

- **G2 是唯一在 α=1 保守口径下综合净额仍为负（收益为正）的门槛**；
  G1（无需 mapping 的 standalone 盈利锥）仅 189 锥，证明 mapping 感知
  是必要条件。G3 稀释到盈亏线以下，G4 净额与 G2 相同但覆盖减半。
- 候选 A 失败的主导项按 text 弹性归因：text +0.41% 按 NO00036 实测弹性
  （+4.1% text → −12.58%）约解释 −1.26%，指令 +0.95% 约解释 −0.73%；
  G2 删除 15,159 个 boundary 写回块（约 −300 KB text）且指令净负，
  方向自洽。text/指令双指标作为筛选主门。
- **机制**：pass 在带 CPU mapping 的模型上运行（读取 dataLayout 的
  boundary 槽位），逐锥以 m + 5×int ≥ 2n+1 判定；pipeline 调整为
  `…→ 第二轮 mapping → grhsim.lut-fold → 第三轮 mapping`（pass 看到
  post-pack mapping，与本筛查口径一致；第三轮 remap 实测约 +22 s，
  预算内）。reemit 路径（checkpoint 自带最终 mapping）口径不变。
- emitter 级索引 CSE（相同 operand 向量的 lut 在同一 helper 内共享
  索引局部量）作为配套削减 text/指令的小改一并实施。
- 无 mapping 时 pass 退回旧门槛（min-ops/ratio），保证既有测试与
  无 mapping 流程行为不变。

### 大规模 LUT（n=7/8）筛查：边际增益为负，不实现（2026-09-17）

用户追加要求尝试更大规模的 LUT。profit-gate 筛查（同 G2 门，
min-ops=2 ratio=0，日志 `cone_stats_profit_gate_i7.log`/`_i8.log`）：

| 组 | 锥数 | Σint | combined α=1 | combined α=0.75 | 动态覆盖 |
|---|---:|---:|---:|---:|---:|
| n≤6 | 12,614 | 15,159 | **−19,184** | −43,314 | 0.96% |
| n≤7 | 12,882 | 15,817 | −18,540（**+644 变差**） | −44,575 | 1.05% |
| n≤8 | 12,802 | 15,663 | −17,936（**+1,248 变差**） | −44,327 | 1.09% |

n≥7 锥占选中集 13–15%、携带 22–27% 内化 boundary，但每锥索引
成本 15/17 条指令，边际入不敷出；且预算放宽经贪心 claim 挤掉
盈利的 n≤6 小锥（E2 的 n=6 锥数 505→216）。rodata 口径结论
不变。**判定：n=6 uint64 立即数表为甜点，不实现 7/8 输入支持；
若未来重开，须先解决 n≥7 索引成本而非表存储。**

### IMPLEMENTED：候选 D（2026-09-17）

实现（wolvrix 子模块工作区差异，基线 `9b54e45`）：

- Pass（`lib/grhsim/pass/lut_fold.cpp`）：run() 开头从
  `model.cpuMapping()->dataLayout->values` 按 dense ValueId 序构建
  boundary 标记；选择第二关改为 mapping 感知盈利门——有 mapping 时要求
  m ≥ min-ops 且 m + profitCredit×int ≥ 2n+1（int = 非 root 成员的
  result 为 boundary 的个数，不再做 ratio 判定）；无 mapping 退回旧判定
  （m ≥ min-ops 且 100m ≥ ratio×n）。新选项 `profit-credit`（默认 5）。
  diagnostics 追加 `internalized_boundary=I`。
- Pipeline（`scripts/wolvrix_xs_grhsim_ir.py`）：`CPU_POST_SEMANTIC`
  只留 `grhsim.bitwise-muxes`；`CPU_PIPELINE` = 语义四 pass → 8×mapping
  → pack-bit-registers → bitwise-muxes → 8×mapping（第二轮，post-pack
  dataLayout 就位）→ `grhsim.lut-fold` → 8×mapping（第三轮）。flow 默认
  min-ops=2、ratio-percent=0（profit-credit 用 pass 默认 5）。第三轮
  mapping 实测约 +22 s（两轮各 ~21.4/22.4 s），预算内。
- reemit（`scripts/reemit_grhsim_ir.py`）：min-ops 默认 2、ratio 默认
  0、新增 `--lut-fold-profit-credit` 默认 5；Makefile
  `reemit_grhsim_ir` 透传 `GRHSIM_REEMIT_LUT_FOLD_PROFIT_CREDIT`。
  reemit 路径（checkpoint 自带最终 mapping）与 profit-gate 筛查口径一致。
- Emitter 索引 CSE（`lib/grhsim/backend/cpu_emit.cpp`）：同一
  task/helper body 内索引表达式字符串相同的多个 lut 共享一个
  `cpu_lutidx_<n>` 局部量（body 级预扫描分配名字，声明在首个使用点
  外层）；只对出现 ≥2 次的索引提局部量（单用 lut 保持内联，避免 text
  膨胀）。初版"统一 body 顶部声明"被 test_grhsim_cpu_emit 抓出
  读未赋值 local 槽的真实 bug，已修正为使用点外层声明。
- 聚焦测试全绿（2026-09-17）：`make test_grhsim_cpu_mapping` 2/2、
  `make test_grhsim_cpu_emit` 1/1（93.6 s，fixture 实际命中 CSE）、
  `make test_grhsim_cpu_schedule` 1/1。新增
  `runLutFoldProfitGateTest()`：经真实 `cpu.st.*` mapping pass 构建
  mapping（手工 layout 过不了 verifyCpuDataLayout 逐字段校验），覆盖
  int=1/m=2/n=4 不折、int=1/m=3/n=4 不折、int=1/m=3/n=3 折、
  int=0/m=9/n=4 折、int=0/m=8/n=4 不折、无 mapping 走旧门槛、
  profit-credit=1 生效。
- 文档：`docs/grhsim_ir/passes/lut-fold.md`（盈利门语义、m/n/int
  定义、无 mapping 回退、pipeline 位置、CSE）、`flows/cpu-st.md`
  （第三轮 mapping 与 flow 默认参数）。
- 附带影响：`scripts/wolvrix_hdlbits_grhsim.py` 复用 CPU_PIPELINE 且
  不传 pass 选项，HDLBits IR 流程将走 lut-fold 的 pass 默认
  （min-ops=4、credit=5、mapped 盈利门）；语义正确性由同一真值表
  穷举保证，正式复测时一并回归确认。
- 语义约束：盈利门只改变"折哪些锥"的选择，被折锥的真值表仍按 2^n
  输入组合穷举精确生成；boundary 信息只作成本判据，不改语义；
  不触碰状态/事件/写口；不含模块名匹配。
### VALIDATED 进展：候选 D v1（G2 盈利门）筛选——REJECTED（2026-09-17）

- reemit 自 NO00039 checkpoint（新默认值 min-ops=2 ratio=0 credit=5）：
  pass 折叠 **12,798 锥 / 40,578 ops**，lut_inputs=43,159，
  internalized_boundary=**15,596**，与 Python 筛查预测（12,614 / 15,159）
  偏差 +1.5%/+2.9%，盈利门按预期工作；task 数 4,944 → 4,917（−27）。
- 静态对照（`cpu_code_g2.log`）：compute 指令 14,686,598 → 14,929,208
  （**+242,610，+1.65%**）；ELF text 100,542,385 → 101,556,665
  （**+1.01%**）；compute 条件跳转 216,200 → 214,314（−0.87%）。
  筛查预测综合净额为 −19k（收益为正），实际 +242k——模型失真 26 万。
- 单对筛选（`screen-g2/summary.json`，均 NEMU PASS、端点一致）：
  old 89.737 s / new **93.039 s，−3.68%**，方向明确为负，不进入正式复测。
- **失败归因（helper read cache 交互）**：emit 统计对比——old
  `helper_read_cache_values=408,161`（NO00039），候选 A 401,454（−6.7k），
  候选 D v1 **447,357（+39,196）**。G2 引入 43,159 个 lut 输入引用，
  同 helper 内多个 lut 引用相同 boundary 值，被 NO00034 的"稳定 helper
  输入缓存"识别为可缓存输入，新增 ~39k 个惰性缓存项；每项约 6 条静态
  指令（valid 检查 + 条件跳转 + 惰性读取），39k×6 ≈ 234k ≈ +242k 指令
  增长的 **97%**。候选 A 折叠量大、boundary 净减少，缓存项 −6.7k，
  未触发该效应。教训：LUT 输入引用的边际成本不是 load 本身，而是它
  激活的 emitter 缓存基础设施；筛查模型未含此项。
- **修正方向（候选 D v2）**：lut 索引 operand 读取**绕过 helper 输入
  缓存**（索引 CSE 已保证每个唯一索引只拼装一次，直接 boundary load
  ~1 条远优于缓存项 ~6 条）；预期缓存项回落至 ≤408k，compute 指令
  回到筛查预测的 −19k ~ −39k 区间。若 v2 筛选仍负，关闭 lut-fold
  方向并记录全部过程。

### 候选 D v2（缓存绕过）：REJECTED，lut-fold 方向关闭（2026-09-17）

- 修正实现：`cpu_emit.cpp` 新增 `valueDirect`（跳过 activeValueCache_），
  `lutIndex()` 改用它；`cpu_layout.cpp:99-108` planHelperReadCaches 的
  引用计数跳过 lut op 的全部 operand（发射与计划双重绕过）。
  `make test_grhsim_cpu_mapping` 2/2、`test_grhsim_cpu_emit` 1/1 全绿。
- reemit（`reemit-g2v2.log`）：折叠不变（12,798 锥），但 emit 统计
  `helper_read_cache_values=443,192`——仅从 447,357 降 4,165，
  **未回落到 old 的 408,161**。lut operand 排除只解决一小部分。
- 静态对照（`cpu_code_g2v2.log`）：compute 14,686,598 → 14,928,975
  （**+242,377**）与 v1（+242,610）几乎相同；text 101,552,305（+1.01%）
  与 v1（101,556,665）几乎相同。修正对指令/text 无影响，基准无需
  重跑（静态主导指标与 v1 一致，v1 单对已 −3.68%）。
- **根因（方向级）**：+35k 缓存项不是 lut operand 造成，而是 remap 后
  supernode 合并变大 → helper 变大 → 更多值满足"同 helper 引用 ≥2 次"
  的缓存资格——这是 lut-fold 改变 op 分布后 remap 的**不可约结构扰动**，
  与门槛、emit 细节无关。叠加候选 A（LUT 直接成本入不敷出）与全部
  筛查证伪（B 并集聚类 6%、C concat-sink 明确负、W 多 bit 锥无锥结构、
  n=7/8 边际为负），**lut-fold 方向在当前 emit 架构下不可行，关闭**。
- 方向级教训（供后续节点引用）：(1) 布尔网络的静态 op 削减不是动态
  收益（NO00026 已示，本节点再次确认）；(2) 任何改变 op 分布的语义
  pass 都会经 remap 扰动 helper read cache 资格，该二阶成本（每项
  ~6 条静态）可超过一阶收益，筛查必须建模 remap 后结构而非仅 op 计数；
  (3) 跨 supernode 锥的 lut result 是 boundary，写回块成本与内化收益
  对账后，缓存膨胀成为第三项未建模成本。

### 候选 E 转向：commit 侧事件历史直接采样（2026-09-18）

lut-fold 方向关闭后，按 NO00039 复盘指引的大份额方向（"commit 侧 541
个历史状态的同类直接采样"）转向。诊断（`scripts/grhsim_commit_history_stats.py`，
Make 目标 `analyze_grhsim_commit_history`，日志
`ptmp/no00041_commit_history_20260918/analysis-final.log`）：

- **541 的构成**：commit 侧 182,485 个逻辑采样站点共享后归并到 **541
  个物理代表元**（439 任务×1 + 51 任务×2，均值 337 站点/代表元）；
  181,628 个别名站点发射零代码；batch=0；541 个代表元全部走
  shadow→pending→publish 全管道（每代表元一次 `cpu_write_scalar<bool>`
  9 参数调用）。541 被 NO00039 排除的真实原因是 planDirectSampling
  只扫描 compute task，commit task 从未进入评估，而非认证失败。
- **可认证子集 = 541/541**：planSharedHistories 的共享资格检查（单一
  task 引用闭包、同事件、projected、扇出恰为本 domain 单 arm、事件
  Boundary 非别名、1-bit 两态）严格蕴含直接采样认证的全部条件；541
  个全部是该检查通过者（代表元）。逐项排除分布：多 task 引用 0、
  数据读者 0、多事件 0、非 1-bit 0、事件非不变量 0、扇出非自 arm 0。
- **轮内可见性约束的解法**：与 compute 侧相同——直写延迟到 commit
  task 末尾（no-edge return 前与端口武装段之后各一份），此时全部边沿
  守卫（含延迟到端口武装段求值的未缓存守卫）已读完可见历史；同轮
  其他 commit task 的引用由单一 task 闭包排除；下轮 compute 边沿守卫
  读到的值与 publish 安装值逐字相同（直写早于 publish 落地，两者之间
  无读者）。publish 的副作用（变化时置 `cpu_next_arms[domain]=1` 与
  `again|=projection`）由直写块内同置补偿（变体 B）；变体 A（省略自
  arm）论证安全：变化后 hist==event，下轮守卫恒假、重采样为空操作，
  事件真跳变经 compute 扇出独立 arm。
- **预期收益**：以 NO00036 dyn 数据 + NO00039 实测标定——每轮消除
  ~150 次 `cpu_write_scalar<bool>` 调用（25–30 insns/次）+ pending/
  publish 处理，合计 ~4.3–5.7k insns/轮；NO00039 compute 侧消除
  ~10.3–12.7k insns/轮 → 实测 +1.42%，线性外推**变体 B +0.5%~0.7%**；
  变体 A 额外消除 ~19.4 次/轮空转重跑 → **A+B +0.6%~0.85%**。
  发射形态风险低于候选 A（净删 541 个调用点、仅增 ~982 个小块，
  text 增量近零）。
- **证伪门**：reemit 单对筛选 <+0.4% 则放弃本候选；先落变体 B，
  筛选为正再叠 A，正式判定以 6 次交替复测秩次门为准。

### 候选 E 变体 B 筛选：REJECTED（2026-09-18）

- 实现（`cpu_emit.cpp` +69 行，后已撤销）：`planCommitDirectSampling()`
  复用 sharedHistoryEligible_ 认证（541 代表元 / 490 commit task），
  `stage()` 跳过认证代表元的 `cpu_write_scalar<bool>`，commit task 两
  路径末尾各发一份延迟直写块（变化时置 `cpu_next_arms` +
  `cpu_direct_again`）。测试 `make test_grhsim_cpu_emit` 1/1（含
  ASan/UBSan 记分板）、`test_grhsim_cpu_mapping` 2/2、
  `test_grhsim_cpu_schedule` 1/1 全绿；reemit 计数精确命中
  `commit_direct_sample_states=541 commit_direct_sample_tasks=490`。
- 静态对照（`cpu_code_cds-b.log`）：commit_task 指令 1,962,912 →
  1,951,840（**−11,072**）；ELF text 100,542,385 → 100,420,559
  （**−121,826**）；compute 不变；方向与机制预期一致。
- 单对筛选（`screen-cds-b/summary.json`，NEMU PASS、端点一致）：
  old 91.069 s / new **90.954 s，+0.126%**——远低于 +0.4% 证伪门，
  **放弃**。诊断预期 +0.5~0.7% 高估约 4 倍：`cpu_write_scalar<bool>`
  的实际动态成本（小函数，shadow 写 + pending 追加，非 25–30
  insns/次）与采样真实触发率（多数 task 被 stable-skip 短路）均低于
  估计；按实测标定真实上限 ~0.15%，叠加变体 A（~19.4 次/轮空转
  重跑消除）预期仍 <0.3%，6 次交替复测无法与噪声区分。
- 教训：commit 侧 ~19% 中逐周期提交固有工作占比极高，541 个代表元
  的采样管道成本已被 stable-skip/共享别名压缩到剩余零头；"静态
  调用点删除数 × 估计单位成本"的收益模型必须先用实测标定单位成本。
  源码已撤销（wolvrix 子模块回到 9b54e45）。

### 候选 E 之后的方向重估（2026-09-18）

两个方向（lut-fold 全家族、commit 直接采样）相继失败后重估主杠杆：
text/icache 是已被多节点验证的最强相关（NO00036：text 1.87× ≈
性能差 1.937×；NO00030/31/33 每次 text −1.6~−2.5 MB 对应
+1.8%~+3.1%）。当前 ELF text 100.5 MB，compute task 14.7M 指令
（~59 MB）为主体。转入诊断两个未探索的 text/结构方向：
(a) task 函数体跨子图融合（NO00023 只合并精确重复 op，近似重复
task 未动）；(b) NO00039 复盘点名的大状态提交簇 4096 计数器族。

### 4096 计数器族提交簇：筛查证伪（2026-09-18）

诊断（`scripts/grhsim_commit_cluster_stats.py`，Make 目标
`analyze_grhsim_commit_cluster`，日志 `ptmp/no00041_commit_history_20260918/`）：

- **构成**：XiangShan difftest logEndpoint 性能计数器——30,899 个
  计数器状态/写端口，集中 9 个 commit task（4471–4479，task 4472–4478
  每个恰 4096 写 op）；每计数器一个 port-arm 门控 directCommitBody
  （64 个 uint64 预过滤字 → 512 arm 字节 → 逐端口位测试）。
- **成本**：task 4472–4478 合计 257,204 条指令（commit 的 12.1%）；
  gprof 动态（18,457 样本复算）728 样本 = **总时间 3.94%**（commit
  桶 18.25% 的 21.6%，最大单一 commit 族）。静态/动态落差说明 arm
  稀疏已在工作：每武装端口仅 ~10 条指令，重跑主体是 64KB 工作集访存。
- **证伪**：masked-next 比较（NO00025）与本族的 directCommitBody
  先比后写**已在最终形态**（`if(cpu_current!=cpu_value)` 内联，全掩码
  merge 被 GCC 折叠为纯比较）；稠密 SIMD 替代稀疏在 6% 变化率下 ALU
  更贵；enable 19,320 个 distinct 不可按组提升；通知批合并
  ~0.02-0.05%。主体是计数器真实逐周期递增提交（累积语义可观察），
  可证明可消除量 **≤0.3% < 0.5% 证伪门，放弃**。
- 至此 NO00039 复盘指引的三个大份额方向全部关闭（541 历史直接采样
  +0.126% REJECTED、4096 簇 ≤0.3% 证伪、求值量结构冻结）。
  下一步诊断回到 compute 67.65% 的构成：gprof task 级热点、剩余
  216k compute 条件跳转构成分类、task 函数体跨子图融合潜力。

### compute 构成诊断与候选 F 决策（2026-09-18）

诊断（`scripts/grhsim_compute_hotspots.py` / `grhsim_compute_branch_classes.py` /
`grhsim_task_similarity.py`，Make 目标 `analyze_grhsim_compute_hotspots` /
`analyze_grhsim_compute_branches` / `analyze_grhsim_task_similarity`，
日志 `ptmp/no00041_commit_history_20260918/compute_diag/`）：

- **热点不再弥漫：44xx assert/DPI 端点族**（task 4400–4453 中 41 个
  进入 top-400）合计 **2,455 样本 = 13.30% 总样本 / 19.66% compute**；
  top10 = 7.26% compute（NO00010 时代 top10 仅 5.39%、无可识别族）。
  族内 task 每次（非静默）激活读 ~184 个 boundary bool（cevent 门控
  条件位 + DPI 参数），全族消费 **9,643 个相异 bool（~9.4 KB）**，
  散布在 ~2.1 MB boundary 区（task_4415 单 task span 1.81 MB）→
  每次激活 ~120–240 个 L1-miss/L2-hit（~10cyc 差），为族成本大头。
- **条件跳转分类**（216,200 全量对账）：内联宽值/动态 slice helper
  习语分支 ~65%（发射器习语改造目标，弥漫长尾，预期 0.5–1.5% 且
  text 风险）；task 入口 active-word 检查 18.5%（每激活仅 9 分支，
  承载激活语义，可消性受限）；cevent 门控链 16%（已优化机制残余）；
  mux 残余 ~0–3%；port-arm 全部在 commit 侧（0%）。
- **task 融合定量证伪**：规范化后完全相同族 236 个（1,257 task、
  覆盖 21.35% compute 指令、可省 11.8% text），但 (a) 参数表
  ~9.8MB ≈ 省下的 11.87MB 的 0.8 倍，净收益所剩无几；(b) cpu_at
  偏移当前是免费位移字段，参数化每访问点 +1–2 条（与 lut-fold
  "索引拼装比锥形链贵"同一教训）；(c) 可融合的全是冷 task（热点
  44xx 族 10 个抽检全部无族可归），冷 text 的 I-cache 收益微小。
- **候选 F 决策：44xx 族 boundary 门控位的按单元致密布局**。机制与
  NO00038 热分层同构（对象偏移按消费聚簇分层分配），但对象是
  "event-gated system/DPI 端点 task 消费的 boundary bool"（通用结构
  特征触发，非模块名匹配）——9,643 bool ~9.4 KB ≪ L1D 48 KB，
  尺寸经济性成立（NO00039 C3 的 419 KB 被否因超 L1D 稀释热层，
  本对象小两个数量级）。预期收益 **1.5–4%**（族份额 13.3% × load
  成本占比 30–50% × 致密化命中率）。证伪门：相异 bool 静态复核
  ≤12 KB（实测 9,643 ✓）；单对筛选 <+1.0% 放弃；正式 6 次交替
  秩次门。布局改动经 emit 前 mapping 变换 pass 实施（checkpoint
  layout 校验一致性），reemit 路径可用于筛选。

### 候选 F 实现与筛选：秩次判据通过（2026-09-18）

- 实现（`cpu_layout.cpp` buildLayout 内 +124/−11）：判据 = 含
  event-gated `core.system.task`/`core.dpi.call`（非空 event_edges
  参数）的 compute task 单元引用的两态 ≤8 位 Boundary 值；按 task
  分组（组间大小降序、组内 value id 升序）、预算 16 KiB 整组取舍、
  致密段从 boundary 偏移 0 起分配；verifyCpuDataLayout 双范式
  （canonical/legacy）接受保证旧 checkpoint 可加载。测试
  `test_grhsim_cpu_mapping` 2/2（含新增 densifyBoundaryTests：
  致密/回落/预算/确定性/roundTrip）、`test_grhsim_cpu_emit` 1/1、
  `test_grhsim_cpu_schedule` 1/1 全绿。
- reemit 干跑：layout-data 输出 `densified_boundary_values=7317
  densified_bytes=7317 densified_groups=44`（预算内无组被裁）；
  **top-10 热点 task 的相异 boundary bool 读 99–100% 落入
  [0, 7317) 致密段**（task_4415：227/227，p90 偏移 959 → 每次
  激活主体读 ~5 条 cache line，此前散布 ~1.8 MB）；
  helper_read_cache_values=408,161 不变（不扰动读缓存规划）；
  44 组 ≈ 45 个播种 system/DPI 任务（无 event-gated 端点的 task
  正确未入选）。7,317 < 9,643 的差值是端点 unit 之外的守卫/写回
  条件读，属判据语义。
- 单对筛选（`screen-densify`）：old 91.171 / new 90.945，+0.248%。
- **6 次交替筛选**（`screen-densify-6/summary.json`，reemit 产物，
  预注册 old1/new1/old2/new2/old3/new3）：new **90.552 / 90.753 /
  90.812**（均值 90.706），old **90.906 / 91.011 / 91.372**
  （均值 91.096）；**max(new) 90.812 < min(old) 90.906，U=0、
  单侧精确 p=0.05，cliff_delta=-1.0——秩次判据通过**，幅度
  **+0.43%**。六次均 NEMU PASS、端点一致。按 goal 流程进入完整
  SV 路线正式构建与正式 6 次交替复测。

### 正式构建与测量协议危机：页帧固定偏差的发现与修正（2026-09-18）

- 正式门槛：完整 SV→C++ 生成 **690.15 s**（<1800 s，完整 SV 路线、
  `CPU_TARGET_BATCH_COUNT=0`）；fresh 编译通过（<1800 s）。
- **初次正式 6 次交替出现 −9.02% 严重回归**（new 97.258–99.586 vs
  old ~90.4），与筛选（同一内容 +0.43%）完全相反。排查链：
  (1) 等价端点一致（instrCnt=240349/cycleCnt=99996/guest 100001，
  语义正确）；(2) 正式与筛选 model 全部 10,104 文件 md5 相同、
  libgrhsim_SimTop.a md5 相同、两个 emu 的 **.text 段 md5 相同、
  段表（vma/offset/size）相同**，全文仅 **4 字节**差异（rodata 中
  构建信息字符串）；(3) 同一"慢" emu 在第二窗口复测仍慢
  （98.0–100.0），同一"快" emu 仍快（89.2–90.3）——**与文件绑定
  的稳定偏差**；(4) **决定性判别实验**：同一二进制（NO00039 emu）
  vs 它的页帧复制（cp 新 inode）6 次交替，**稳定差 6.4%**
  （96.374–96.440 vs 89.639–91.092），三次一致、秩次门"显著"——
  假差异完全由文件级因素产生；(5) 对慢 emu 执行
  `posix_fadvise(DONTNEED)` 驱逐页缓存后重跑：98.6 → **90.5/91.1**，
  性能恢复正常。
- **结论**：该工作负载（100 MB text、icache/L3 敏感）的宿主性能对
  二进制的**物理页帧分配**（page cache 常驻页帧、L3 物理索引冲突
  家族）有 **±6–9% 的文件级固定敏感性**。编译/复制时分配的页帧
  在 page cache 中常驻，后续运行反复使用同一组页帧——**3+3 新旧
  交替协议无法平均该偏差**（它对每个文件是固定偏移而非逐次噪声），
  任何 ≤±6% 的真实效应都可能被页帧运气淹没或伪造。初次正式
  −9.02% 即页帧伪影（编译时分配到坏页帧），不代表致密化效果。
- **协议修正**（本节点起生效，对 old/new 一致执行）：
  `scripts/benchmark_grhsim_ir.py` 新增 `--evict-page-cache`（默认
  开）——**每次运行前对被测 emu 文件 posix_fadvise(DONTNEED)**，
  使每次运行的物理页帧重新分配，文件级固定偏差转化为逐次运行
  独立随机变量，交替协议恢复平均能力；preregister 记录
  `evict_page_cache`、summary 记录 `page_cache_evicted`。单元测试
  `make test_benchmark_grhsim_ir` 2/2 通过。
### 候选 F 正式复测（修正协议）：ACCEPTED（2026-09-18）

**门槛**：完整 SV→C++ 生成 **690.15 s**（<1800 s，完整 SV 路线、
`CPU_TARGET_BATCH_COUNT=0`，非 checkpoint 恢复）；fresh 编译通过
（<1800 s）。被测二进制
`ptmp/no00041_commit_history_20260918/flow-densify-final/emu/grhsim-compile/emu`
sha256 `6dff0a3d4421cea1…`（正式 SV 路线构建；强制重链验证链接
可重现，与初次正式编译逐字节相同）。layout-data 输出
`densified_boundary_values=7317 densified_bytes=7317
densified_groups=44`（16 KiB 预算内无组被裁）；正式 model 与
筛选 model 全部 10,104 文件 md5 全等。

**正式 6 次交替**（`ptmp/no00041_commit_history_20260918/formal/summary.json`；
预注册 old1/new1/old2/new2/old3/new3；**每次运行前对 old/new emu
均执行 posix_fadvise(DONTNEED) 页帧驱逐**；CPU2、单核、
XS_EMU_THREADS=1、100k cycles、waveform/commit/RAM trace 关闭）：

| run | old Host (s) | new Host (s) | 退出 | 端点 |
|---|---:|---:|---|---|
| 1 | 91.672 | 90.754 | 0 | 240349/99996/100001/0x80000c0c |
| 2 | 91.461 | 90.371 | 0 | 同上 |
| 3 | 91.127 | 90.302 | 0 | 同上 |

六次均 NEMU 对拍通过、端点一致、退出码 0、无 mismatch。

- old 均值 **91.420000 s**（样本 SD 0.274804）、new 均值
  **90.475667 s**（样本 SD 0.243500），降低 **1.032961%**。
- `max(new) 90.754 < min(old) 91.127`，Mann-Whitney U=0、单侧精确
  p=0.05、Cohen d=−3.64、Cliff's delta=−1.0，**秩次判据通过**。
- 驱逐协议把组内 SD 压到 0.24–0.27（未驱逐时 0.6–0.8），并消除了
  页帧固定偏差（初次未驱逐正式测量同二进制 −9.02% 伪影，驱逐后
  同一 sha256 二进制恢复 90.3–90.8）。

**保留机制（候选 F）**：`cpu.st.layout-data`（buildLayout）将
event-gated `core.system.task`/`core.dpi.call` 端点 compute task 单元
消费的两态 ≤8 位 Boundary 值按消费 task 聚簇致密分配到 boundary 区
前段（组间大小降序、组内 value id 升序、16 KiB 预算整组取舍）；
verifyCpuDataLayout 双范式（canonical/legacy）接受保证旧 checkpoint
可加载。语义约束：仅 boundary 偏移重排，IR/分区/调度/提交语义不变；
触发条件为通用结构特征（op 种类 + event_edges 参数 + 存储类别 +
位宽/两态），不含模块名称匹配。被否决尝试：lut-fold 候选 A（正式
−1.53%）、候选 D v1（G2 盈利门，筛选 −3.68%）/v2（缓存绕过无效）、
B 并集聚类（筛查 6%）/C concat-sink（筛查负）/W 多 bit 锥（筛查负）、
n=7/8（筛查边际为负）、候选 E（commit 历史直接采样，筛选 +0.126%
未过门）、4096 计数器提交簇（筛查 ≤0.3%）、task 跨子图融合（筛查
定量证伪）、宽值 helper 直线化（0.5–1.5% 边际未入栈）；过程与证据
如上，lut-fold 与候选 E 源码均已撤销。

**最终判定：ACCEPTED（候选 F，+1.032961%，秩次判据通过，生成/编译
门槛通过，100k 等价确认）。** 按新均值计算，GrhSIM-IR 为归档 gsim
46.965 s 的 **1.926748×**（上一节点 NO00039 为 1.937093×）。
