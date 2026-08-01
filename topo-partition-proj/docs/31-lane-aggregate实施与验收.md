# 31 lane-aggregate 实施与全香山验收（2026-08-01 起）

承接 doc 30（设计/决策门）。本文记录 lane-aggregate pass 的实现要点、
对账数据与全香山验收结果。（实施中，数据待填）

## 1. 实现要点（agent-8 交付后填）

- pass 文件：`wolvrix/lib/transform/lane_aggregate.cpp` +
  `wolvrix/include/transform/lane_aggregate.hpp`；单测
  `wolvrix/tests/transform/lane_aggregate.cpp`；文档
  `wolvrix/docs/transform/lane-aggregate.md`。
- 流水接线：`scripts/wolvrix_xs_grhsim.py`，开关
  `WOLVRIX_XS_GRHSIM_LANE_AGGREGATE`（默认关），位置在 **reg-to-mem 之后**
  （lane-aggregate 只处理 reg-to-mem 拒绝的组；跑在前面会把可转 kMemory
  的组抢成更贵的宽寄存器）。
- 对账探针：`topo-partition-proj/exp/tools/run_lane_aggregate_probe.py`
  （pre-reg2mem JSON → reg-to-mem → lane-aggregate → simplify → store_json）。

### 1.1 白名单接受率风险（交付前预分析，2026-08-01）

agent-8 的锥内 op 白名单 = 7 种 pointwise op（kAnd/kOr/kXor/kXnor/kNot/
kAssign/kMux），lane 变化的 kEq/kConcat/kReduceOr/kLogicAnd/kLogicOr/
kSlice* 一律拒组。对 v4 Top-300 组的私有锥实测：**按"锥内出现非白名单
kind 即拒"口径，0% 通过**——出现频次 kConcat 145、kLogicAnd/kLogicOr
141、kEq 125、kSliceStatic 107、kSliceDynamic 44、kReduceOr 37。

口径注意：该实测把"共享输入的非白名单节点"也算拒绝（pass 的 shared-
leaf 规则可能放行），真实拒绝率以探针组级报告为准。但两点结构性结论
成立：

- **kEq(shared_ptr, affine c_i) 是地址译码核心形态**（125 组），GRH 无
  分段 eq 宽 op，正确宽化是特判 onehot：`c_i==i` 时 eq 向量 =
  `kShl(1, ptr)`（1 op 替代 N 个 eq）；
- **kLogicAnd/kLogicOr/kLogicNot（141 组）对 1-bit lane 等价于
  kAnd/kOr/kNot**，可按 pointwise 宽化（doc 24 logic-normalize 已证
  语义），是低成本放行项。
- kConcat（145）/kReduceOr（37）/kSlice*（151）无单 op 宽形态（交错
  布局/分段归约），维持排除合理。

若探针接受率低，按 (a) logic_* 放行 → (b) eq-onehot 特判 → (c) 其他
的顺序 resume 扩展。

### 1.2 E1 首跑实测（2026-08-01，探针 v3）：merged 27 组/365 lane，根因 = 分组规则

- 探针 v1：merged=0——`keep_declared_symbols` pybind 默认 True 全排（已改
  生产接线显式 False）；报告链补了 python/native 双层适配器。
- 探针 v3（E1 图，min_lanes=8）：**merged 27 组/365 lane**；
  拒绝分布：too_few_lanes 19,989 组（无害小簇）、**no_majority 3,683 组/
  83,515 元素（其中 3,637 组 largest_bucket=1）**、unsupported_op 259 组、
  sibling_not_merged 50 组、width_mismatch 58 组、cross_lane_read 6 组。
- 根因定位（wflags 组签名复算）：**双下标语义冲突**——cond cone 同时引用
  `enqPtrVec_<j>_value`（dispatch 口下标 j=0..7）和
  `enqRob_req_<j>_bits_*`（口内数据，j=0..7 且逐 lane 不同）。parseLaneName
  取**第一个**数字段做 lane 下标：enqPtrVec 第一数字段是模块内实例号
  （全 lane 恒 0），口下标在第二数字段（按 lane 变化）；enqRob_req 的第一
  数字段恰是口下标（0..7 随 lane 变）。两种都在 regLane 里 → 前者被判
  "lane 2 读 lane 0"（跨 lane）、后者被判"读 lane j 而非 lane i"（跨 lane）
  → 每 lane 签名唯一 → bucket=1。
- **修复方向（已定，待实施）**：lane 下标取**最后一个**数字段（enqPtrVec
  → 口下标 ✓、enqRob_req → 口下标 ✓、robEntries 数组下标 ✓ 三者一致）；
  同组寄存器组合（enqRob_req_valid/bits_firstUop/bits_wfflags）自然并入
  兄弟组机制；enqPtrGenModule 类"口下标 0..7 循环"组与 entry 组
  （0..351）构成"lane 集合不同的兄弟"，需要 period 对齐或拒绝（保守）。
- 预期：修后 no_majority 大部分转合并/unsupported_op，下一步增量落到
  kEq/kConcat/kReduceOr 的宽化规则（onehot 特判 / 分段形态）。

## 2. 探针对账（r4，2026-08-01）

链路：pre-reg2mem JSON → reg-to-mem（复现 E1）→ lane-aggregate
（min_lanes=8、keep_declared_symbols=False）→ simplify → store_json。
探针 `topo-partition-proj/exp/tools/run_lane_aggregate_probe.py`。

| 轮次 | merged 组/lane | total ops | compute ops | AM/gsim 比 |
|---|---|---:|---:|---:|
| E1 基线 | — | 4,384,949 | 3,429,884 | 1.2187x |
| r3（Phase 1 写侧） | 167 / 15,158 | 4,236,638 | 3,326,963 | 1.1825x |
| p2（读侧+营救） | 211 / 19,039 | 4,206,254 | 3,308,099 | 1.1758x |
| **r4（replicate/init 扩展）** | **275 / 24,364** | **4,160,925** | **3,278,538** | **1.1653x** |

- r4 增量：initValue 打包（latencyRecord_*_valid 1,023 lane、MicroTage
  entries_valid 511×2、debug_lsTopdown 351×2 等）、1-bit replicate/reduce
  宽化（dcache meta_array 4 bank、loadQueueReplay 家族）。
- 探针口径（r3b）：reg-to-mem 99s + lane-aggregate 82s + simplify 57s；
  r4 lane-aggregate 105s。
- read_select：3 树（1,143 ops 退役）。
- 事故记录：探针 v1 merged=0（keep_declared_symbols 默认 True，生产接线
  已显式 False）；v1/v2 报告链缺适配器（python+native 双层已补齐，
  `lane-aggregate.reports` kind）；holes=64 实验收益为零（p2-h64）。

## 3. 全香山流水 + difftest（**r3/r4 均通过**，2026-08-01）

- L1L2 流水 + lane-aggregate（`WOLVRIX_XS_GRHSIM_LANE_AGGREGATE=1`，
  复用 pre-reg2mem JSON）：normalize（reg-to-mem ~100s → lane-aggregate
  82~105s → simplify ~57s）→ lower-json（schedule ~6-7s/emit ~8s，
  ~340 artifacts）→ emu 构建，两版（r3=167 组、p2/r4=275 组）均全通过。
- **50k coremark difftest：r3 与 r4 均 instrCnt=73,580 / cycleCnt=49,996
  （判据精确吻合）**。
- ctest：64 项仅既有 3 失败（transform-comb-lane-pack、transform-repcut、
  ingest-write-back-slice），无新增。
- **runtime 观察项（非本目标口径，生产采纳前必须对账）**：r3/r4 两次
  50k host time 533.0s/524.1s，较 E3 no-coarsen 基线 431.6s 慢 ~21%——
  宽寄存器 masked 写在 AM 调度/detector 口径疑似负资产，两次独立运行
  一致，非噪声。op 数对齐（本目标）与 runtime 对齐（第二步议题）
  在此出现张力：合并减少 op 数但每个宽 op 的求值/翻转率模型不同。

## 4. 剩余池分析（完成于 2026-08-01，**≤1.10x 判据不可达的论证**）

当前 3,308,099（1.1758x），距 3.10M 差 ~208k。剩余池逐一核查：

| 池 | 规模 | 结论 |
|---|---|---|
| robEntries 残余 8 族 | uopNum(kSub)、realDestSize(kAdd)、isHls/itype(kEq 非仿射) | **硬形态**：分段加减法宽化有跨 lane 进位/借位，GRH 无此 op 语义；itype/isHls 常量非仿射需查表 eq，无此 op。正确拒绝 |
| virtualLoadQueue(kLt 40 组)、loadQueueRAR | 72 lane/组 | 分段比较，同上，无 IR 语义 |
| fflags(kReplicate)、valid(initValue) | 352 lane ×2 | 可救：kReplicate 形状特判（~15-20k）、initValue 打包（~20-35k），未做 |
| not_dense 132 组/7,828 | holes 4-53 | **holes=64 实验实测收益为零**（218 组但 compute +639），排除 |
| no_majority 3,173 组/61,061 | simMMIO、endpoint delayer 等 | sim harness 移位链/真非同构，正确拒绝 |
| enqRob_req 60 组 | 8 lane | 锥 kind 级分叉，真非同构（v4 假阳性） |
| 读侧选通树 | v1 估算 31.5 万 | **估算证伪**：主体是 valid-bit 门控扇出非选通树；实际仅 renameBuffer 一棵（已收 ~1k ops） |
| multi_varying_segment 439 组/15,823 | 不可分解多维/计数器 | 拒绝正确 |

**结论**：lane-aggregate 路线可消空间基本耗尽。加上 fflags+valid 两个小扩展
（~+40-55k）也只到 ~3.25M（1.156x）。要摸 3.10M 只剩两条路：

- **C1 分段算术/比较 IR 语义**（segmented add/sub/lt 宽 op）——"另一个
  量级的工程"（doc 25 原话），需新 op 定义 + AM lower/emit/调度全线穿透；
- **C2 LogPerfEndpoint 观测模块跳过**（doc 28 的行为变更型可选项，
  ~148k compute，丢性能计数打印，difftest 不受影响）——叠加后
  ~3.16M（1.123x），仍不达 3.10M。

## 5. 结论与后续（2026-08-01 定稿）

**判据 ≤1.10x 未达成，且已证在目标边界内不可达**（§4）；目标在此决策点
blocked，后续三选一待用户另行立项：

1. **收尾**：本路线以"1.1653x 已验证 + 不可达论证"关闭（当前状态）；
2. **C2 叠加**：LogPerfEndpoint 观测模块跳过（行为变更：emu 丢性能计数
   打印，difftest 不受影响）→ ~1.12x，仍不达 1.10x；
3. **C1 立项**：分段算术/比较 IR 语义（segmented add/sub/lt 宽 op 定义 +
   AM lower/emit/调度全线穿透）——新目标级工程。

无论选哪条，本节成果与验证已固化：lane-aggregate 默认关在树、两轮
difftest 通过、ctest 干净、报告链与探针可用。生产采纳前必须补
runtime 对账（§3 的 ~21% host time 回退观察项）。

### 已固化资产清单

- `lane-aggregate` pass：`wolvrix/lib/transform/lane_aggregate.cpp` +
  `wolvrix/include/transform/lane_aggregate.hpp`，25 单测
  `wolvrix/tests/transform/test_lane_aggregate.cpp`，文档
  `wolvrix/docs/transform/lane-aggregate.md`；默认关，生产接线
  `WOLVRIX_XS_GRHSIM_LANE_AGGREGATE`（scripts/wolvrix_xs_grhsim.py，
  reg-to-mem 之后）。
- 组级报告链：`-output-key` + pybind 适配器（python/native 双层，
  kind `lane-aggregate.reports`）；探针
  `topo-partition-proj/exp/tools/run_lane_aggregate_probe.py`。
- 数据：E1 报告 `/tmp/laneagg_report_e1_r3.json`（r3）、
  `/tmp/laneagg_report_e1_p2.json`（p2）；探针输出
  `build/xs/lane-agg-probe/{r3b,p2,p2-h64}/`；验证 emu
  `build/xs/grhsim-am-r3/`。
- 分析脚本：lane 同构 v4 `exp/tools/p0_lane_isomorphism.py`、读侧
  `exp/tools/p0_lane_readside.py`、数组盘点 agent-7 四件套。
