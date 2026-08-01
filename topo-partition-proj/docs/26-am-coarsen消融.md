# 26 第二步开局：AM coarsen 消融——coarsen 在 AM 图上是负资产（2026-07-31）

第二步（划分算法能力）第一个实验：把 doc 17 的 gsim coarsen 消融移植到
AM。**结论：与 gsim 完全相反——coarsen 在 E3 的 AM 图上同时劣化
cost、runtime、代码体积，是 lose-lose 的负资产；no-coarsen 的生产调度
质量已贴着规范化 DP 的地板（+0.1%），AM 与 gsim 的划分差距是图本身
而不是算法。**

## 1. 实验设置

E3（T2 L1+L2 后的）AM 图，生产调度同一配置（capacity 128、
dp-segment-penalty 1、dp-coarsen-budget 0）仅切换
`--disable-coarsening`；功能门 = CoreMark 50k NEMU difftest +
独占串行 host time。

## 2. 全指标对比（生产调度，E3 图）

| 指标 | coarsen（现默认） | no-coarsen | Δ |
|---|---:|---:|---:|
| incoming_copy_cost | 5,938,405 | 5,486,693 | **−7.6%** |
| dag_edges | 293,499 | 254,546 | −13.3% |
| ccvp | 2,805,545 | 2,455,889 | −12.5% |
| blocks | 29,073 | 34,326 | +18% |
| detectors | 1,690,168 | 1,255,466 | **−25.7%** |
| activation_edges | 2,479,405 | 2,138,463 | −13.7% |
| scheduled_instructions | 7,310,248 | 6,440,846 | −11.9% |
| storage_bytes | 375,742,365 | 343,970,527 | −8.5% |
| emit 源体积 | 2.1 GB | 1.5 GB | −29% |
| emu 二进制 | 175 MB | 155 MB | −11% |
| **50k host time（独占）** | **515.4 s** | **431.6 s** | **−16.3%** |
| difftest（instrCnt/cycleCnt） | 73,580/49,996 过 | 73,580/49,996 过 | 一致 |

对照 gsim（doc 16/17）：coarsen 对 cost 中性（1,306,149 vs
1,300,813，−0.4%）但 runtime +2.49x——coarsen 是 gsim 的核心优势；
AM 的 coarsen 则全面为负。

## 3. 三个结论

1. **AM 生产默认（enableCoarsening=true）是负资产**，建议翻转为
  no-coarsen（见 §5 待决）。E0 基线 575.5 s → E3 no-coarsen 431.6 s，
  累计 −25.0%（T2 图清理 −10% × no-coarsen −16.3%）。
2. **AM 的划分算法已到地板**：no-coarsen 生产调度 5,486,693 vs 规范化
  DP（canonical Kahn + 段 DP）5,480,531，仅 +0.1%。与 gsim 的 cost 差
  （4.21x）不是算法能消化的——doc 23 的乘数链归因（图性质）在划分
  维度闭环。
3. **runtime 差（≈19x）与 cost 差（4.21x）的落差是下一个问题**：
  gsim 50k 22.9 s vs AM-no-coarsen 431.6 s——cost 只解释 4.21x，其余
  在检测器/激活模型、存储拷贝与 emit 结构（AM 每轮 126 万 detector、
  6.44M scheduled 指令的评估模型）。这是第二步的下一实验方向。

## 4. 产物

- 离线：`/tmp/e3_nocoarsen_block_assignment.jsonl`（生产划分导出，
  cost/ccvp/dag_edges 见 §2）；E3 coarsen 数字在
  `exp/dataset/xs_full_20260731_l1l2/`。
- emu：`build/xs/grhsim-am-e3-nocoarsen/`（emit + grhsim-compile/emu）。
- 复现：emit 命令 = `grhsim-am-lower-json <E3 post-stats.json> SimTop
  --emit <dir> --blocks-per-source 2048 --max-source-bytes 4194304
  --max-instructions-per-block 128 --dp-segment-penalty 1
  --dp-coarsen-budget 0 --disable-coarsening`；difftest 同 doc 11 §5。

## 5. 待决

- **生产默认翻转**：`ActivityScheduleOptions.enableCoarsening`
  true→false（或 XS 流水显式 `--disable-coarsening`）。证据见 §2 全表；
  涉及生产行为变化，由所有者拍板。注意 doc 11 的 λ=4 实验（496.3 s）
  本身就是 no-coarsen 变体，本结果与它同向且更干净。
