# A0002 — step r001/t0/s01：chunk 尺寸与 branchy-mux 双探针

日期：2026-08-14。action 类型：step（trajectory t0, step 1, K=2）。
proposal：`tes/grhsim-am-coremark/proposals/r001-t0-s01.md`（Φ 选中 e00001）。

## 候选设计与可证伪假设

本 step 是搜索的第一步，定位为**归因性探针**（A0001 建议：11.06x 的量级差靠
盲调收敛不了，先量化两条主导嫌疑轴）。两个候选机制互异，均为纯 emit 旋钮
（brief「工作面」明示允许；GRH IR 未触碰，无代码改动，候选分支各留
`--allow-empty` 说明 commit）。

### c1 `--block-chunk-instructions 12000`（基线 3000）— 访存消歧/局部性轴

- 分支 `tes/r001/t0/s01-c1`（commit `9764584`），worktree
  `build/tes/grhsim-am-coremark/src/e00003-t0-s01c1`，eval e00003。
- **假设**：chunk 增大 4x 后更多窄值落入 chunk 内标量化（寄存器分配），
  跨 chunk uint64 数组槽 store→load 往返减少，Host 中位下降 ≥3%；
  若持平/恶化 → 该残余在当前块尺寸下非一阶（或寄存器压力/编译器 spills 抵消）。
- 先验：NO0016 微基准数组往返 3.86 vs 寄存器 0.29 cycles/op（13x）；
  NO0018 收口点名残余 = 跨 chunk uint64 槽往返（b38653 余 1,626 槽）+
  194MB 模型对象状态 gather。

### c2 `--branchy-mux`（基线 off）— 前端分支预测 vs 数据依赖轴

- 分支 `tes/r001/t0/s01-c2`（commit `1bae6a4`），worktree
  `build/tes/grhsim-am-coremark/src/e00004-t0-s01c2`，eval e00004。
- emit-args：`--block-chunk-instructions 3000 --branchy-mux`。
- **假设**：基线下标量 mux 全部走三元式（NO0018 反汇编证实 b38653 chunk_0
  全 cmov）；本候选全量改 if/else 分支。若显著恶化 → 量化数据相关分支
  误预测成本，永久关闭分支方向（NO0016「融合 mux 分支误预测」残留嫌疑裁决）；
  若持平/改善 → NO0018 的局部结论不能全局推广，分支轴有收益空间。
- **设计修正记录**：原设计为 `--merge-when-min-group 5→20`，调研发现
  lower-json CLI 默认 `mergeWhenMinGroup=1`（<2 即关停 coarsen 归组，
  flatten 图上该 sweep 本已实质死亡），5→20 与基线等价 = 伪候选；
  emitter 块级 mux-run 融合（planMuxFusionRuns）无开关。故改为 branchy-mux——
  同一嫌疑轴上真实改变发射形态的探针。

## 结果

| eval | 候选 | status | compile_s | Host 中位 | vs y0 273.1s | vs gsim 24.7s |
|---|---|---|---|---|---|---|
| e00003 | c1 chunk12000 | ok | 1257s（emu_build 822s） | **279.2s**（274.2/281.7/279.2，CV 1.4%） | **+2.2% 回退** | 11.31x |
| e00004 | c2 branchy-mux | ok | 1223s（emu_build 789s） | **271.1s**（274.5/270.1/271.1，CV 0.9%） | **-0.74% 改善（winner）** | 10.98x |

功能门：e00003/e00004 全部 rep 均 difftest_ok、instrCnt=73,580 / cycleCnt=49,996
（金标窗内）。

## 机制分析与裁决

**c1 证伪（访存消歧/局部性轴）**：chunk 3000→12000 非但不快反而 +2.2%
（两侧 CV 均 <1.5%，回退为真实效应非噪声）。含义：NO0018 点名的
「跨 chunk uint64 槽 store→load 往返」在当前块尺寸/编译器行为下**不是
一阶可收成本**——chunk 内标量化增多带来的寄存器/I-cache/编译器 spill
压力抵消并略超往返节省。chunk 尺寸轴关闭，3000 维持默认。附带观察：
emu_build 822s 与基线 842s 持平（更大 TU 的编译变慢被更少 TU 数抵消），
chunk 尺寸对编译预算中性。

**c2 弱正效应（分支预测轴）**：branchy-mux 使标量 mux 全量 if/else 化后
271.1s（-0.74%，两侧 CV 0.39%/0.85%）。**分支轴未被否决**——if/else 至少
中性、可能微弱有利，推翻了「全 cmov 即最优」的隐含假设；但 <1% 不是一阶
收益，branchy-mux 更适合作为后续优化 pass 的组成选项而非独立优化方向。
附带收益：emu_build 789s（-6%），符合 NO0001 B2 切小基本块利编译的初衷。

**winner = c2**（271.1s > c1 279.2s > y0 273.1s 方向），已合入
`tes/r001/t0/main`（best_overall 更新为 -271095）。t0 轨迹步进 1/8。

**两轴归因小结**：step 1 两条嫌疑轴一否一微正——跨 chunk 往返与分支方向
都不是 11x 差距的一阶来源。残余画像重心进一步向 NO0018 的另两项集中：
**194MB 模型对象状态 gather**（值散布导致的 cache/TLB 压力）与
**2.87x instr/atom 适配胶**（每 atom 的固定发射胶成本）。

## 对 Φ 下一步的建议

1. **主攻状态 gather**：v-var 散布在 194MB 模型对象上，块函数每次激活
   gather 状态读/写。方向：状态布局优化（按访问亲和性重排 v-var 成员，
   将热块共访的状态聚到同页/同 cache line 组）——显式 AM 层 pass
   （如 `am-state-layout`），符合「优化显式化为 pass」纪律。
2. **适配胶量化**：2.87x instr/atom 的胶是什么构成（类型适配/宽度扩展/
   符号扩展？），能否在 AM IR 层统一消除一类（如 slice/zero-extend 归一）。
3. branchy-mux 保留为可选项（微弱正效应 + 编译更快），暂不进主线默认。
4. 已关闭方向备忘：chunk 尺寸（3000 维持）、merge-when 归组（CLI 默认
   1 即关停，且 emitter 融合无旋钮）、分区形状（NO0002）。
