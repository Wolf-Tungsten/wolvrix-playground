# insights — TES 累积机制洞察与失败模式（append-only）

Φ 的跨 step 记忆之一。每条 = 日期 + 来源（eval/action/pdocs 编号）+ 一句话结论。
只追加；修正以「勘误」条目追加。

## 起点知识（2026-08-14，系统初始化时录入，来源 pdocs/grh-notepad/emit-cost）

- NO0018：宽状态切片读内联 + 常量掩码写逐词展开后 Host 324.0s（3-rep 中位，taskset -c 12）；
  反汇编证实切片调用病灶清除；残余 = 跨 chunk uint64 数组槽 store→load 往返、
  194MB 模型对象上的状态 gather、2.87x instr/atom 适配胶；匹配对加权 4.14x。
- NO0016：数组 store→load 往返寄存器分配失败是窄值主成本（0.29 vs 3.86 cycles/op）；
  存储宽度本身证伪（Stage A 持平）；融合 mux 分支误预测是残留嫌疑。
- NO0017：宽状态切片路径曾是最大病灶（85 块持 compute 账 30.8%）——已被 NO0018 清除，
  但 top-2 巨块 b38653/b77703 成本仍高（已非切片调用）。
- NO0013 F2：独立 concat 去零换 replace 为负优化先例（已回撤）——同类「拆散融合」
  假设需谨慎。
- NO0002：分区形状对运行时证伪（465.8s vs 464.6s 持平）——不要从分区拓扑找收益。
- 测量纪律：绑核 + 3-rep 中位 + CV<5%；构建负载与计时分离；计数/计时分离；
  ASLR/PIE 布局可污染对比（NO0338+）；跨构建 join 用稳定 node-id 集合（NO0017）。

## r001 基线与系统校准（2026-08-14，action A0001）

- 双基线（同协议、绑核串行、3-rep 中位）：AM y0（a88e7a2）= **273.1s**（CV 0.39%）；
  gsim target（build/xs/gsim-flat/emu，7-31 构建）= **24.7s**（CV 1.5%）。**差距 11.06x**，
  远大于 emit-cost 系列预期的 ~4x——纸面匹配对加权只覆盖了部分运行时成本。
- golden 计数窗重标定：gsim 与 am 两种 emu 在 50k 周期窗的停止点有确定性小差
  （gsim 73584/49998 vs am 73580/49996），两者均过 nemu 在线逐指令核对。功能门 =
  nemu 零 mismatch + 计数窗（73584/49998 ±16/±8），不再是精确相等。
- evaluator 修复：相对名 emu 直接 exec 会 127（execvp 不搜 cwd）——候选评估一律用
  绝对路径。该 bug 在首轮基线即暴露，修复后零复发。
- 评估耗时实测（ccache 热）：compile_s 1062s = wolvrix 0.4s + ctest ~2.5min +
  emit 62s + emu_build 842s；单候选全评估 ~32min。emu_build 占大头且 emit 全量重写
  .cpp 导致无法增量——后续若要压评估时延，emit 端「内容不变不重写」是最大杠杆。
- 冷 ccache 首轮：compile_s 1299s（放宽的 90min 预算内），wolvrix 全量构建 107s。

## 任务定义修订（2026-08-14，用户指令）

- brief.md 新增「优化哲学（变更面纪律）」：GRH IR 冻结；grhsim AM IR 为主要优化面；
  优化手段应尽量体现为显式 AM pass（有名字、可开关、可归因）；emit 规则变更须随候选
  同步文档。自 r001 的 t0/s01 起生效，约束后续全部候选。

## r001/t0/s01 双探针（2026-08-14，action A0002）

- **证伪**：`--block-chunk-instructions 12000`（基线 3000）→ 279.2s（+2.2% 真实回退）。
  跨 chunk uint64 槽 store→load 往返在当前块尺寸/编译器行为下**非一阶可收成本**；
  chunk 尺寸轴关闭（3000 维持），且对编译预算中性（emu_build 822s vs 842s）。
- **弱正效应**：`--branchy-mux`（标量 mux 全量 if/else）→ 271.1s（-0.74%，winner，
  已入 t0/main）。分支轴未被否决，推翻「全 cmov 即最优」隐含假设；但 <1% 非一阶，
  定位是后续 pass 的组成选项而非独立方向。附带 emu_build 789s（-6%，NO0001 B2 初衷）。
- 11x 差距两轴归因一否一微正 → 残余重心向 NO0018 另两项集中：**194MB 模型对象
  状态 gather** 与 **2.87x instr/atom 适配胶**。下一步主攻状态布局/gather。
- 候选设计教训：lower-json CLI `mergeWhenMinGroup` 默认 1（<2 关停 coarsen 归组），
  设计旋钮候选前必须核实 CLI 默认值与开关语义，避免「与基线等价」的伪候选；
  emitter mux-run 融合（planMuxFusionRuns）无开关。
