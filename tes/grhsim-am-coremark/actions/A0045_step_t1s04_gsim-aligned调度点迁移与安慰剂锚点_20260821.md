# A0045 step r002/t1/s04：gsim-aligned 调度点迁移确认（同窗 -8.44%）与安慰剂锚点

- task: grhsim-am-coremark  run: r002  trajectory: t1  step: 4/8  K=2
- 日期：2026-08-21（06:00-06:50 +0800）
- proposal: `tes/grhsim-am-coremark/proposals/r002-t1-s04.md`（Φ 选中 e00013/e00006）

## 候选设计与结果对比

| cand | eval | 假设（一句话） | 结果 | 裁决 |
|---|---|---|---|---|
| c1 | e00017 | 调度点单变量：摘除 config 调度点全参数回落 CLI 默认 gsim-aligned 点（15 atoms/block、dpCoarsen 7000/0、mergeWhen off），t1 旋钮链（resize-elision/inline-scalar-helpers/inline-scalar-constants/activity-summary-scan/task-body-outline）不变；compute 相 ~50% 未归因缺口（recon-t1s02）若为块组织/i-cache 流式主导则同窗降 ≥6%；<2% 判调度轴对 t1 关闭 | **ok 368.963s**（CV 0.0%，17/17 ctest、3 rep difftest 73580/49996，compile_s ~700s：wbuild 55.5 + emit 60.7 + emu_build 330.0） | **winner** |
| c2 | e00018 | 同窗安慰剂锚点：t1 tip b9a888c 原样重测、emit_args 与 e00013 相同（config 调度点 + 5 旋钮）；无机制假设 | ok 402.978s（CV 0.0%，门全过，emu_build 333.5s） | 锚点席位 |

- **同窗裁决：c1 较安慰剂 -8.44%（402.978→368.963），越 6% 假设门 → 确认。**
  双态 ×1.3-1.4 是整窗乘子，同窗对照免疫；批内 CV≈0 双方一致，无整批污染迹象。
- finish-step：winner=e00017 已合入 `tes/r002/t1/main`（c1 commit `520b017`，
  `--allow-empty` 旋钮类说明性 commit，代码与 tip 逐字节相同，差异全在 emit_args）。
- **t1 有效 emit_args 自此 = CLI 默认（gsim-aligned）调度点 + 5 旋钮**
  （`--resize-elision --inline-scalar-helpers --inline-scalar-constants
  --activity-summary-scan --task-body-outline`，不传任何调度参数）。后续 t1 step
  候选 emit-args 以此为准继承。

## 机制分析

- **调度点一阶效应在 t1 携带图复现**：t0/s01 的 2×2 曾测得 gsim-aligned 单变量
  -16.4%（config+~0 452.8s → 378.4s）；本 step 在 t1（config 调度 + 5 旋钮携带图）
  上同窗确认 -8.44%。跨轨迹收敛：调度/块组织轴是 r002 新输入图上最稳定的
  一阶变量，两轨迹现已对齐到同一调度点。
- **静态实证**：blocks .o text 94.02MB（c1）vs 98.24MB（c2，-4.3%），生成源
  811MB vs 840MB（-3.4%）——gsim-aligned 点（更大块 + coarsen + merge off）
  产生的块组织更省代码体积，与「compute 相缺口 = i-cache 流式/分支前端」的
  recon-t1s02 嫌疑方向一致；但 -8.44% 运行时收益大于 -4.3% 静态体积收缩，
  残余部分疑为块边界/扫描面组织差异（调用边界数量随块变大而减少），未分离归因。
- **t1 与 t0 的旋钮吸收形态不同**：t0 上 gsim-aligned 调度吸收了大部分适配胶
  （旋钮链在其上仅再收 -4.1%）；t1 的 5 旋钮链在 config 调度上收完后，调度点
  仍单独贡献 -8.44%——t1 旋钮（常量内联/摘要扫描/task outline）与调度点机制
  正交性高于 t0 的 9 旋钮链（后者多为适配胶族）。
- **窗态注记**：安慰剂 e00018=402.978s 较同 tip 前两次快态带读数
  （e00013=375.670、e00014=421.673）均不同，跨窗漂移再次实证；t1 tip 真值口径
  更新为 **≈369s（c1 代码等价态，本窗）/ config 调度态 ≈403s（本窗）**，
  旧读数不参与裁决。vs 基线 ratio 仍因基线慢态污染不可裁。

## 对 Φ 下一步的建议

1. **t1 候选空间回到 compute 相本体与 commit 相数据侧**：调度点对齐后 t1/t0
   同基（同调度点、不同旋钮族），compute 相 ~50% 缺口的「块组织」解释已部分
   兑现，残余缺口（recon-t1s02 的墙钟/tick 折时缺口）建议以新 recon（t1 tip +
   gsim-aligned 点）重新画像后再设计候选——旧 recon 基于 config 调度点，池地图
   可能已变形。
2. **commit 相 b119387（寄存器堆写口阵列，29% 池）在新调度点下的形态**是 t1
   最大未触探池；省指令轴已关闭（A0041），数据侧/写合并方向待 recon 定量。
3. 维持每 step 一席同窗锚点；本 step 双候选墙钟各 ~13min（并行 rep 协议），
   评估吞吐良好。

## 操作记录

- c1 提交 `520b017`（tes/r002/t1/s04-c1，--allow-empty）；c2 提交 `02a4509`
  （tes/r002/t1/s04-c2，--allow-empty）。
- 评估命令按任务 playbook：c1 `--emit-args` 仅 5 旋钮旗标（等号形式传参）；
  c2 显式携带 config 调度点全 13 参数 + 5 旋钮（与 e00013 逐字一致）。
- evals 18/32；t0/t1 各 4/8 齐平，下一 action 预期 = 第 4 轮 round-summary。
