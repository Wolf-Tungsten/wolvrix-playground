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

## r001/t2/s01 布局修复重测与宽态炸开（2026-08-15，action A0004）

- **compile_timeout 再现**（e00007，c1 affinity+init修复）：init 宽池 store 按
  offset 升序修复（emit 核验 violations=0）**未**恢复编译——runtime.o 单 TU
  ≥27min 被杀。文本取证：id/affinity 两版 init() 宽池 store 多重集相同、
  零值-run 结构统计等价（62k vs 60k run），唯一结构差 = id 全局单次升序扫描
  vs affinity 被 158k 条标量 store 切成 1,237 个 run。**继续修顺序无解**。
- **本质发现**：init() 182 万行中 98.2% 宽池 store / 93.5% 标量 store 是
  字面量 0 死 store（memset/fill(0) 已覆盖，emitter 按构造可知）。init()
  体量是所有候选编译预算的结构性风险（id 布局也要 ~10min）。方向：
  `--init-zero-elision` 发射期消死 store（1.82M→~4 万行），是布局假设
  获得运行时证据的前置。
- **证伪**（e00008，c2 wide-state-explode）：272.7s（-0.13%，亚噪声）。
  ABTB 族命中炸开（emit 实证：4,875 处元素直读 + 3,072 处单元素 RMW）但
  持平——NO0018 切片内联已吸收该族主要成本，NO0017 §5 锚点是 NO0018 前的账；
  残余提取机械在关键路径外。覆盖窄（274/~33.5K）非主因。**宽态炸开轴关闭**；
  b83570 全宽写退化风险实证可忽略。
- x0 三大残余轴（跨 chunk 往返 / 状态 gather / 适配胶）+ 表示轴全部关闭或
  降级；11x 差距重心移向运行时结构成本（调度器/事件/commit）与弱正组合。
- 测量环境：rep 期 loadavg 1.0-1.6 成常态，亚 1% 效应低于协议分辨极限；
  c2 的 +0.13% winner adoption 是机械规则产物，不代表机制收益。

## r001 第 1 轮跨轨迹小结（2026-08-15，action A0005）

- **静态 emit 单旋钮空间已扫完，收益饱和于 ~1%/个**：第 1 轮 6 候选覆盖
  chunk 形状/分支/适配胶/布局/表示五轴，无一阶（≥5%）收益；弱正两个
  （branchy-mux -0.74%、resize-elision -0.95%）机制正交可组合。
- **主失败模式是编译预算门而非功能门**（2/6 compile_timeout、0 功能失败）。
  `--init-zero-elision`（消 init() 字面量 0 死 store，1.82M→~4 万行）是
  元杠杆：全部候选的编译预算改善 + 布局轴运行时证据的前置。
- **块间机械（调度器/活动字扫描/事件/commit）是唯一未被单变量触探的大轴**：
  实测 11.06x vs 匹配对纸面 ~4.14x 的缺口指向这里；第 2 轮应形成首个
  可证伪假设（可离线复用 pdocs block 级 profile，如 b83400 61.9G 未分解账）。
- 亚噪声 adoption 纪律：winner 机械规则会收编 <CV 的读数（e00008 +0.13%），
  action 笔记须标注「噪声级 adoption 非机制收益」；<0.5% 的 winner 读数存疑。
