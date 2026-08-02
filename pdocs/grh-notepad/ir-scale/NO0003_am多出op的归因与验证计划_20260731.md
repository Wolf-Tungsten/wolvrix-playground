# 18 AM 相对 GSim 打平图多出 Op 的归因：第一刀结果与验证计划（2026-07-31）

承接 [`15-am与gsim打平dag规模对比`](15-am与gsim打平dag规模对比.md)（规模差）
与 [`16-同一规范化dp下am与gsim打平cost对比`](16-同一规范化dp下am与gsim打平cost对比.md)
（同一规范化 DP 下 cost 仍差 4.55x，差距来自图本身性质）。"两步分析"的第一步：
**gsim 图结构优势的来源归因**，首问是"AM 多出来的 op 到底是什么"。
第二步（划分算法能力对比）在第一步结论落地后启动，接口见 §5。

## 1. 口径与前提

- 数据：AM 图 `exp/dataset/xs_full_20260730/`；gsim 打平图
  `exp/dataset/xs_gsim_flatten_20260731/`。两份 JSONL 同格式（doc 14），
  均含 `op/opcode/width/state_write`，可按 op 直接对齐。
- 同一 RTL 构建：AM 侧 post-stats JSON 中 op 的 `loc` 全部指向
  `build/xs/rtl/rtl/*.sv`（2026-07-03 生成），gsim 侧输入是同目录的
  `SimTop.fir`——**设计版本漂移的混淆可排除**；差异只来自 IR 路径
  （firtool 产出的 SV → wolvrix ingest vs 原始 Chisel FIR → gsim）。
- 规模差精确化（doc 15 复述）：节点 4,669,495 vs 3,043,902（**1.53x**）、
  def_use 边 1.85x、位宽总量 1.79x、external_read 2.43x。"多近 1 倍"
  对边基本成立，对节点是 +53%。

## 2. 第一刀：op 直方图归因（已完成）

工具：`exp/tools/op_shape_compare.py`（新写，流式扫描两份 JSONL，按
opcode 统计节点数/位宽和/def_use 出入边/external_read/state_write，
再按语义桶对齐两套 op 命名；分桶沿用 `scripts/compare_ir_shapes.py`
的桶定义）。结果存档 `exp/dataset/op_shape_compare_20260731.json`。

| 桶 | AM 节点 | gsim 节点 | Δ节点 | AM du_out | gsim du_out | Δ边 | AM 位宽(M) | gsim 位宽(M) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| logic（and/or/xor/not/reduce/logic_*） | 2,276,722 | 910,486 | **+1,366,236** | 4,103,484 | 1,555,044 | **+2,548,440** | 20.90 | 5.18 |
| wire（assign / REF / NONE） | 233,525 | 69,336 | +164,189 | 759,011 | 90,333 | +668,678 | 5.13 | 1.14 |
| state（reg.write / REG_UPDATE） | 212,039 | 148,956 | +63,083 | 0 | 0 | 0 | 0.00 | 2.99 |
| mem（mem.* / OP_*_MEM） | 56,272 | 5,426 | +50,846 | 87,180 | 7,170 | +80,010 | 0.24 | 0.16 |
| mux（mux / OP_MUX+OP_WHEN） | 781,529 | 737,356 | +44,173 | 943,565 | 794,159 | +149,406 | 8.54 | 7.78 |
| concat（concat/replicate / OP_CAT） | 323,937 | 286,379 | +37,558 | 426,264 | 370,835 | +55,429 | 13.32 | 5.70 |
| slice | 323,339 | 295,559 | +27,780 | 679,037 | 615,524 | +63,513 | 4.36 | 1.81 |
| cmp | 322,371 | 311,905 | +10,466 | 534,548 | 539,541 | −4,993 | 0.32 | 0.31 |
| special（system.task/dpi/changed.* / ASSERT 等） | 14,176 | 6,334 | +7,842 | 289,951 | 18 | +289,933 | 0.00 | 0.01 |
| arith | 117,184 | 122,959 | −5,775 | 168,523 | 167,556 | +967 | 2.55 | 2.65 |
| cast（/ OP_PAD/CVT/AS*） | 0 | 40,613 | −40,613 | 0 | 48,234 | −48,234 | 0.00 | 1.15 |
| shift | 8,401 | 108,274 | −99,873 | 40,035 | 149,906 | −109,871 | 1.95 | 3.21 |
| **合计** | **4,669,495** | **3,043,902** | **+1,625,593** | **8,031,598** | **4,340,605** | **+3,690,993** | **57.32** | **32.09** |

三个层次的头结论：

1. **节点差的 84% 是 logic 族**（and/or/xor/not/reduce + SV 的
   `logic_and/or/not`）：AM 2.28M vs gsim 0.91M，**2.50x**。
2. **把 logic 族剔掉后，两边 compute op 几乎相等**：AM 1.88M vs
   gsim 1.90M（0.99x）。也就是说 gsim 的 op 数量优势几乎完全是
   "logic 族更精简"，不是全面性的粒度差异。
3. 边差同构：logic +2.55M（69%）、wire +0.67M（18%）、`changed.pos`
   事件扇出 +0.29M（8%，412 个节点扇出 29 万条边，AM 显式建模
   posedge 检测）。位宽差 62% 由 logic 族贡献。

次要观察：

- wire：AM `assign` 233.5k vs gsim `REF` 69.2k（3.4x）——gsim
  `aliasAnalysis` 消别名，AM 保留显式连线节点。
- mem：`mem.read` 49.3k vs `OP_READ_MEM` 3.4k——AM 的存储读端口
  建模远比 gsim 碎（存储不是 gsim 节点，doc 14 §2）。
- gsim 反向多出的项：shift（OP_CAT 的 emitter 降阶为 shift+or，doc 13）
  与 cast（OP_PAD/BITS_NOSHIFT 等 FIR 位宽降阶产物）——这些是 gsim
  图里的"廉价本地 op"，不影响其 cost 优势。
- 极端比例：`not` 族 AM 210k vs gsim `OP_NOT` 5.3k（40x）；`and` 族
  1.19M vs 388k（3.1x）；`or` 族 845k vs 473k（1.8x）。同一族内
  倍数差异大，提示不只是"少跑了一遍 CSE"那么简单。

## 3. 机制假设

- **H1 优化流水差异（主嫌疑）**：gsim 在 graphPartition 前依次跑
  `exprOpt / constantAnalysis / aliasAnalysis / patternDetect /
  commonExpr`，并夹 4 次 `removeDeadNodes`
  （`reference/gsim/src/main.cpp:365-408`）；wolvrix GrhSIM 流水只有
  `simplify ×2`（2state），GRH 级 CSE `redundant-elim`
  （`wolvrix/lib/transform/redundant_elim.cpp`）**存在但未接入**
  `scripts/wolvrix_xs_grhsim.py:679` 的 pre_sched_pipeline。
  注意 AM 输入的 SV 已经过 firtool 优化，logic 仍多 2.5 倍——说明
  gsim 自身优化（尤其 commonExpr）削得很狠，或另有结构性机制。
- **H2 ingest/降阶惯用法差异**：同一语义在两条 IR 中展开成不同数量的
  logic op（guard/enable 条件逐赋值复制、reset 分支形态、`!`/`&&`
  的处理方式）。`not` 族 40x 这种极端比例更像惯用法差异而非 CSE。
- **H3 建模口径项（非语义优势）**：state（+63k，reg.write 逐端口建模
  vs REG_UPDATE）、mem（+51k）、wire（+164k）、changed.pos 扇出
  （+290k 边）。这些是"表示法"差异，清算后才是可比的 compute 图。
- **H4 验证/断言逻辑口径（待排除）**：system.task 7.2k + dpi.call 6.5k
  vs OP_ASSERT 6.2k 数量接近，但其 guard 逻辑的展开方式可能不同。

## 4. 验证与推进计划（任务列表）

按"先定量、后定性、先排除口径、后确认机制"排序：

- **T1 gsim 逐 pass 贡献量化**：用 `--dump-stats-json` 逐阶段导出
  enode_op_types，对比 `exprOpt / constantAnalysis / aliasAnalysis /
  patternDetect / commonExpr / removeDeadNodes` 各 pass 前后按桶的
  算子数变化。产物：pass × 桶的贡献表。判据：若 commonExpr 单 pass
  消掉的 logic 算子量级 ≈1M，H1 主因地位基本坐实。
- **T2 AM 接入 `redundant-elim` 重导重测（决定性实验）**：在
  `scripts/wolvrix_xs_grhsim.py` pre_sched_pipeline 补挂
  `redundant-elim`（或写小驱动对 post-stats JSON 单跑该 pass），
  重走 lower-json + topo-proj 导出，重跑 `op_shape_compare.py`。
  产物：CSE 前后 AM 侧按桶 op 数 + 与 gsim 的差表。判据：剩余 logic
  差 <20 万 → H1 确认；消不动 → 转向 H2。
- **T3 模块级归因**：AM 侧用 post-stats JSON 自带 `loc`（文件=模块）
  /`sym` 分层名做每模块 op 桶统计（3GB JSON 流式扫描即可，无需改
  导出器）；gsim 侧用 JSONL 的 `name`（`__DOT__` 分隔）。按模块名
  join，出 top-20 Δlogic 模块表。产物：模块 × 桶差表。
- **T4 惯用法采样比对**：在 T3 的 top 差模块中各抽若干表达式，人工
  比对两侧 op 形态，落实 2-3 种具体的复制/展开惯用法（候选：guard
  扇出复制、reset 条件内联、`!x` 的降阶形态、断言 guard）。产物：
  带计数的惯用案例。
- **T5 口径清算表**：把 H3 各项（state/mem/wire/changed.pos）折算
  后给出"可比 compute op"口径的节点/边对比，作为第一步的最终
  归因表。产物：一张清算表 + 一句话归因结论。
- **T6（可选）表示归一化重对比**：对两份图压缩 wire 链（assign/REF
  union-find）后重数节点/边，验证 wire 口径对 15/16 号文档结论的
  影响。

## 5. 完成标准与对第二步的接口

第一步收口标准：

1. Δ1.63M 节点的分解表，每项有归属桶 + 机制标签（优化缺失 / 惯用法
   / 建模口径 / 设计内容），logic 族的 +1.37M 必须有 T1/T2 的定量
   证据支撑；
2. Δ3.69M def_use 边与 Δ1.32M external_read 的同口径分解；
3. T5 可比口径下 AM 图相对 gsim 图的"净"规模差与净 cost 差预估。

对第二步（划分算法能力）的接口：若 T2 确认 CSE 类优化能削平 logic
差，则在"CSE 后的 AM 图"上重跑 doc 16 的同一规范化 DP 对比——
4.55x 的 cost 差还剩多少，直接分离"图质量"与"划分算法"各自的贡献，
这正是第二步的输入基线。

## 备注

- 对比工具：`topo-partition-proj/exp/tools/op_shape_compare.py`
  （`op_shape_compare.py <am.jsonl> <gsim.jsonl> --out-json r.json`，
  全量约 2 分钟）；首份结果 `exp/dataset/op_shape_compare_20260731.json`。
- AM 侧模块级信息源：`build/xs/grhsim-am/wolvrix_xs_post_stats.json`
  （3GB，op 带 `sym`/`loc`，loc.file 即模块级 SV 文件）。
- gsim 侧模块级信息源：`xs_gsim_flatten_20260731/instruction_graph.jsonl`
  节点记录的 `name` 字段。
