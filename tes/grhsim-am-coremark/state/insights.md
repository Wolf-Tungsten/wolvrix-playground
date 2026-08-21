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

## r001/t0/s02 init 消除与弱正组合（2026-08-15，action A0006）

- **元杠杆落地**：`--init-zero-elision`（8087d74，tes/r001/t0/s02-c1）发射期
  消除 init() 字面量 0 死 store（宽 1.63M + 窄 147.8k，非零集合三元组比对
  零偏差）→ init() 1.82M→4.2 万行，runtime.o 单 TU 572s→14.7s（-97%），
  emu_build 789→347s（-56%）；全程 compile_s 仅 -11%（ctest/emit/wolvrix
  固定 ~740s 稀释）。**亲和布局两次 compile_timeout 的直接根因已除**，
  布局/表示类候选此后以该分支为底座。运行时中性成立（274.4s vs 271.1s，
  在 ±1.5% 噪声带内）。
- **弱正可加性证伪**（e00010）：branchy-mux+resize-elision 组合 273.3s
  （+0.06%），相对两单因子（-0.74%/-0.95%）收益全消——~1% 级 emit 微调
  及其组合路线到头，勿再为此消耗评估预算。
- **测量纪律重要更正**：rep1 的 loadavg_before≈15 是 evaluator 自身
  emu_build（-j16）刚结束的 1-min loadavg 滞后尾部，不是外部干扰——
  构建进程在 rep 期间已退出。interference 判定须结合进程级证据（ps），
  勿仅凭 loadavg。同代码三次评估 run-to-run 全距 ±1.5%（269.0-277.5），
  winner 裁决对 <2% 分差保持存疑。
- **evaluator 修复**（A0006 入）：parse_run_log 对 append 式 rep 日志取
  首匹配 → 重测同 eval-id 读到旧段；已改 last-match 并单测验证。
  （继 A0001 相对路径修复后第二个评估器 bug。）

## r001/t1/s02 块间机械双探针（2026-08-15，action A0007）

- **证伪（e00011）**：`--branchless-activation`（激活合并去分支化、恒写活动字）→
  289.2s（+6.9% vs t1 主线，CV 0.12%）显著回退。条件激活写是承力设计：安静组
  条件分支高度可预测，恒写引入 ~4.8G 次额外共享 store 污染活动字 cache 行
  （扫描侧每轮重读）。**激活写去分支化轴关闭；后续 emit_args 永不携带该旋钮。**
- **证伪（e00012）**：`--am-skip-preset-activation`（commit-act.b 再激活块摘除
  preset 激活）→ difftest_fail（instrCnt=0 死锁）。被 commit act.b 再激活的
  compute 块 round-1 输出馈给同轮 commit 消费者，preset→act.b 双激活是承力
  结构；「跳轮」类手术需边级消费者分析才可在更小集合重试。b83400 61.6G
  未分解账保持未决，回到块内分解路线。
- 机械裁决新边界：显著回退（+6.9%）的 ok 候选也会被 finish-step 机械合入
  主线；本次无害仅因变更新增默认 off 开关（emit 不携带即逐字节等价）。
  默认 on 变更若显著回退，finish-step 前须人工拦截。
- 运行时结构新事实（探索确认）：eval 100,102 次/全程、1.5 round/eval、
  5,862 块触发/round、激活合并静态 455K 站点/动态 4.77G 次、纯扫描机械上界
  1-1.5%、commit 相 23.75%（每 eval 2,970 commit 块全触发，激活侧全 ChangedAny）。
  11.06x 缺口重心进一步指向每轮求值总量与 commit 写站 compare 机械。

## r001/t2/s02 写站空转实测与守卫块门控（2026-08-15，action A0008）

- **写站空转坐实（离线插桩，difftest 过）**：`--commit-station-stats` 实测
  commit 写站 compare 7.32G 次/全程、真写 194M、**idle=97.35%**——A0007
  的「commit 写站 compare 机械」嫌疑物证成立。插桩版 Host +27%（站点
  密度旁证）。
- **证伪（e00013）**：`--commit-station-gating`（生产者朝代门控）协议中位
  +13.5%（CV 41.7% 噪声日；rep5 274.8s≈基线、机制量级估算≈中性，真值
  最可能 ±1% 内，不达采纳线）。死因是**静态覆盖仅 6%**（10,524/176,682
  写站）：绝大多数写站的 next 锥在 commit 块内部，生产者不是 compute
  块。**朝代门控路线关闭**；正确机制指向「commit 内锥状态输入快照检测」
  （复用 ST00010 检测器分组），收益上限 = commit 相 23.75% 的大部。
- **确认（e00014，winner，已入 t2/main，新晋 best_overall -269731）**：
  `--guard-event-gating`（纯 fatal/fwrite 守卫块按 changedResults_ 事件槽
  整块门控）269.7s（-1.10%，CV 0.88% 干净窗口）。命中 b83400（7,001
  atoms）+ b26518（1,327 atoms）；negedge 半数触发的整块守卫重估被消除。
  收益低于 2% 预期：b83400 的 61.9G 账是 NO0018 前旧账，现已被摊薄
  （反推当前全账 ~18G）。**守卫门控轴关闭（同族无更多巨块）**。
- 实施教训：b83400 的 769/7,001 atom 是同事件门控 `$fwrite`/`$display`，
  「fatal-only」规则会漏判整块（首轮 gated=0）——守卫族判定必须覆盖
  fwrite/finish。门控 seen 槽须按「原子执行单元」（run）分配，跨 chunk
  同组写站按组分配会首次 eval 丢写（c1b-fix 实证）。
- 测量纪律：共享机同居负载可造成 CV 41.7% 的噪声日（e00013 rep 全距
  274.8-652.4s）与 CV 0.88% 的干净窗口（e00014）并存；>2% 效应可裁决，
  <1% 效应已超协议分辨极限。评估应挑干净窗口；noisy 结果的 rep 级证据
  （loadavg_before × 离群形态）必须写进 action 笔记再裁决。

## r001 第 2 轮跨轨迹小结（2026-08-15，action A0009）

- run best 曲线 = y0 273.103s → round 1 270.502s → round 2 269.731s；累计
  仅改善 **1.23%**，仍为 gsim 的 **10.93x**，AM/gsim 绝对差距只关闭
  **1.36%**。第 2 轮 6 候选仍无一阶（≥5%）收益。
- **~1% emit 微调路线关闭**：branchy-mux + resize-elision 组合 273.3s，
  两个单因子弱正不可加且回到 y0；亚 1% 规则堆叠低于当前协议分辨率，
  不再占用正式 eval。
- **粗粒度块间摘除路线关闭**：激活合并恒写化 +6.9%（共享活动字 store
  污染），整类 commit 再激活块省略 preset 直接 difftest 死锁。活动字条件写
  与 preset->act.b 双轮语义是承力结构；后续调度手术必须有边/锥级证明。
- **commit compare 空转是当前唯一动态大数锚点**：7.32G compare、97.35%
  idle、commit 相占 Host 23.75%。生产者朝代门控失败源于静态覆盖仅 6%，
  正确候选形态是「commit 内锥状态输入快照检测」；正式 eval 前先离线量化
  状态读集合、检测开销和可跳过锥覆盖，收益门槛 ≥3%。
- init-zero-elision 确认编译元杠杆：runtime.o 572s→14.7s（-97%）、
  emu_build -56%，本轮 0 compile_timeout；状态布局的编译障碍已解除，但
  affinity 仍无运行时裁决，若重测须先有 ≥3% 的离线覆盖依据。
- 守卫事件门控 e00014 干净获得 -1.10%，但只命中 b83400+b26518，同族已尽；
  与 e00013 CV 41.7% 噪声日并列说明机械 winner != 机制 winner，<1% 分差
  不可作为方向证据。
- 第 3 轮升级门槛：停止亚 1% emit 微调、守卫特例和无边级证明的整轮跳过；
  若完整一轮仍无 ≥3% 干净收益，在 round-3 summary 请求用户裁决继续
  commit 内锥/调度 AM pass，或提前 restart 做更大粒度结构变换。

## r001/t0/s03 source-part 守卫与宽态首触布局（2026-08-16，action A0010）

- **首次获得干净一阶收益**：`--source-part-activity-guard`（e00015）= 247.458s
  （CV 0.82%，vs t0 tip e00010 **-9.44%**），17/17 ctest 与 3 rep difftest 全过；
  334 个静态 part 调用（compute 248 / commit 86）以精确 64-bit activity 区间预检，
  静默时跳过函数调用及逐 byte 扫描。source-part 空扫描由“固定小开销”升级为
  2.87x instr/atom 适配胶中的实质病灶，winner 已入 t0/main。
- **状态 locality 轴确认**：`--wide-storage-first-touch`（e00016）= 257.443s
  （CV 1.15%，vs e00010 **-5.79%**），同样全过功能门。419,243 个宽变量中
  191,955 个按 scheduled Block 首触排序；首 cache-line 161,680→151,616
  （-6.22%）、触及跨度 24,304,307→8,347,000 words（-65.66%）、page
  17,661→16,303（-7.69%）。此前布局轴只有 compile_timeout，本次首次取得
  运行时证据；未中选不等于机制证伪。
- 两候选共享 branchy-mux + resize-elision + init-zero-elision，compile_s
  603.7/590.9s 且均远低于 2400s；init-zero-elision 已把布局实验从编译门中解放。
  c1 比 c2 快 3.88%，说明当前负载上跳过静默控制流比只改善宽状态局部性更有杠杆。
- 新 best_overall = e00015 247.458s：较 AM y0 273.103s 改善 **9.39%**，仍为
  gsim 24.688s 的 **10.02x**，绝对差距关闭 **10.32%**。未来 t0 优先检验 guard
  + first-touch 组合，但不得预设收益可加；细化 source-part 前先量化动态 guard
  命中/扫描长度。下一 t1 action 仍须保持轨迹独立，不注入本节结果。

## r001/t1/s03 亲和布局重测与标量 helper 内联（2026-08-16，action A0011）

- **编译门再否决（e00017）**：`stateLayout=affinity` 将 1,663,331 个字面量
  宽池 store 按物理 offset 排序后，103MB runtime TU 能在约 26min 独立编译，
  但正式全流水线仍于 2399.1s `compile_timeout`（ctest 17/17 和 emit 已过，
  emu_build 1611.0s 未完成）。“单 TU 可终止”不等于满足 40min 协议门；
  t1 内关闭当前 affinity + 百万级显式 init store 路线，但未获得局部性的
  运行时否定证据。
- **首个跨 TU helper 一阶收益（e00018）**：将窄标量 slice/逻辑与算术移位/
  signed helper 改为生成 header 内 `constexpr`，Host 中位 **244.278s**（CV 1.62%），
  较 t1 tip 270.502s **-9.69%**，3 rep difftest 与 17/17 ctest 全过。至少
  531,194 个静态 slice/逻辑移位调用构成了之前未识别的一阶适配胶；
  AM schedule 工作量不变，收益来自 C++ 调用边界与常量传播。
- 内联边界须保持选择性：e00018 compile_s 2006.3s，距 2400s 仅 393.7s。
  宽值/数组/除法/取模 helper 继续 outlined；后续扩张必须同时给出热点覆盖和
  生成代码/编译预算证据。
- 新 best_overall = e00018 244.278s：较 AM y0 改善 **10.55%**，仍为 gsim 的
  **9.89x**，绝对差距关闭 **11.60%**。后续 t1 必须继承
  `--resize-elision --inline-scalar-helpers`；下一 t2 action 保持轨迹独立。

## r001/t2/s03 commit 输入门控与亲和布局消零（2026-08-17，action A0012）

- **commit 输入门控部分确认（e00019，winner）**：追踪 commit next 锥外部叶，
  compute 生产块执行或 ST00013 状态真写时传播块级 dirty，稳定时跳过幂等写
  后缀。静态覆盖 2,922/2,973 commit 块、162,422/176,682 写站（91.9%）、
  440,821 条指令；Host 264.466s（vs t2 tip **-1.95%**，CV 0.74%），未达
  3% 目标但越过 1.5% 证伪线。240,198 条 dirty 边/55,320 个生产块的运行时
  store 是主要抵消项；下一次只应在动态 gate skip/传播计数证明净收益 ≥3%
  后做高收益块稀疏化。
- **affinity 首次取得运行时弱正证据（e00020）**：`init-zero-elision` 消除
  147,822 个窄 store 与 1,633,254 个宽 word store，`init()` 压到约 4.2 万行，
  全流水线 compile_s=1036.1s，彻底越过此前 affinity 的 40min 编译障碍；
  亲和布局 Host 265.243s（vs t2 tip **-1.66%**，CV 1.20%），低于 2% 假设
  阈值但非持平/恶化。结论是静态全局 affinity **弱正、未充分确认**；原样
  重测价值低，未来先用 cache/page/Block 地址跨度证据缩小到具体状态族。
- c1/c2 中位仅差 777ms（0.29%，低于协议机制分辨率）；e00019 入 t2/main 是
  TES 确定性裁决，不代表 commit 门控显著优于 affinity。两候选 17/17 ctest、
  6 rep difftest 全过，全部计数 73,580/49,996。
- t2 best 269.731s -> 264.466s（累计 vs AM y0 **-3.16%**），仍为 gsim
  **10.71x**。第 3 轮 t0/t1/t2 已齐平，下一 action 做 round-summary；届时才
  允许跨轨迹比较本轮机制，不能回写本 step 的候选来源。

## r001 第 3 轮跨轨迹小结（2026-08-17，action A0013）

- run best 曲线 = y0 273.103s -> round 1 270.502s -> round 2 269.731s ->
  round 3 **244.278s**；累计改善 **10.55%**，仍为 gsim 的 **9.89x**，
  AM/gsim 绝对差距关闭 **11.60%**。本轮 5 个计时候选 CV 0.74%-1.62%，
  ctest/difftest 全过；另 1 个候选被编译预算门否决。
- **C++ 适配层成为首个重复出现的一阶成本中心**：source-part activity guard
  跳过静默调用/逐 byte 扫描（-9.44%），selective scalar helper inline 消除
  至少 531K 个跨 TU 调用并暴露常量传播（-9.69%）。两者均不减少 AM schedule
  工作量，收益来自生成代码与运行时适配结构；跨轨迹尚未组合，不能相加。
- **状态 locality 收敛到访问顺序驱动的定向布局**：wide first-touch 以跨度
  -65.66%/page -7.69% 换得 Host -5.79%；全局 primary-Block affinity 仅
  -1.66%。布局轴有效，但粗粒度 affinity 原样重测价值低。
- **运行时与编译复杂度成为双目标**：affinity + 百万显式 init store 于
  2399.1s timeout，init-zero-elision 后同类路径 compile_s=1036.1s；最强
  e00018 又因 helper header 扩张达到 2006.3s，只剩 393.7s 裕量。后续候选
  必须同时证明运行时覆盖与 2400s 编译余量。
- **commit 门控的静态覆盖陷阱**：91.9% 写站覆盖只转化为 -1.95%，因为
  240,198 条 dirty 边传播 store 抵消收益。未来只做带动态 open/skip、传播
  次数与净跳过工作证据的 sparse gate，不再以覆盖率作为收益代理。
- 第 3 轮已满足 >=3% 干净收益的继续条件，暂不调整 C/L/K 或提前 restart；
  r001 继续保持轨迹独立。跨轨迹机制组合只在 restart 使用，下一轮仍坚持
  离线覆盖/成本模型和 >=3% 正式评估门槛。

## r001/t0/s04 word 守卫与首触组合（2026-08-18，action A0014）

- **source-word 二级守卫取得本 run 当前最强单步细化**：e00022 在 e00015 的
  source-part guard 内按 64-block `activeWords_` word 增加精确 owned-mask guard，
  Host 中位 **230.568s**（CV 0.66%，vs e00015 **-6.83%**）；17/17 ctest 与
  3 rep difftest 全过。完整模型生成 1,637 个 word guard/334 个 source 文件，
  证明活跃 part 内部的空 word 逐 byte 扫描仍是一阶适配成本。
- **guard 与 first-touch 可加**：e00021 将 wide-storage-first-touch 叠加到
  e00015，得到 239.354s（CV 0.27%，vs e00015 **-3.27%**），达到假设门；
  locality 增量低于 first-touch 单独的 -5.79%，但未被扫描剪枝吞没。c1 未中选
  不代表布局证伪，未来可与 e00022 组合正式检验，不能直接相加现有读数。
- c2 比 c1 快 3.67%，机械与机制裁决一致，e00022 已入 t0/main。新 best 相对
  AM y0 累计 **-15.57%**，仍为 gsim 的 **9.34x**，绝对差距关闭 **17.12%**；
  t0 完成 4/8，run 使用 22/48 eval。
- activity 稀疏性已显出 part -> word -> byte 的层级结构：约 5,862/86,381 块
  每 round 活跃时，打开一个 part 不代表其中各 word 有效。下一次细化必须先离线
  统计 word guard open/skip 与有效 byte 分布，再决定连续空 word summary；精确
  partial mask、同 word relay 和跨轮 `act.b` 语义保持不可妥协。
- evaluator 基础设施修复：不同候选 worktree 仍使用隔离 wbuild（CMakeCache 绑定
  绝对源码路径），但 FetchContent URL 改从 `wolvrix/build` 的现有本地 clone
  读取，wolvrix 构建接入共享 `build/tes/ccache`。e00021/e00022 全新目录的离线
  configure 分别只需 4.5s/4.4s；新 build 不再意味着重新联网获取依赖。

## r001/t1/s04 resize 胶与标量常量内联（2026-08-18，action A0015）

- **同宽 signed/unsigned resize 扩张证伪（e00023）**：在已有
  `--resize-elision --inline-scalar-helpers` 上扩展同宽 signed/unsigned 胶消除，
  Host 中位 **256.419s**（CV 0.90%），较 t1 主线 e00018 **+4.97%**；17/17
  ctest、3 rep difftest 全过，compile_s=1586.4s。静态站点减少没有转化为运行时
  收益，且生成代码/优化交互可能造成布局回退；该独立扩张关闭。
- **只读标量常量内联弱正（e00024，winner）**：不可写且 <=64 bit 的
  `InitKind::Constant` 读取发射为掩码字面量，地址、init 写入和输入写入仍走
  backing storage；Host 中位 **241.348s**（CV 1.49%），较 e00018 **-1.20%**，
  compile_s=1036.3s，17/17 ctest 与 3 rep difftest 全过。方向稳定但未达 3% 一阶
  门，后续先量化动态常量命中率与代码体积，不扩大 inline 边界。
- 新 t1 best = e00024 241.348s（较 AM y0 **-11.63%**，gsim 比 **9.78x**）；
  run best 仍为 e00022 230.568s。下一 action 轮转到 t2/s04，轨迹继续独立。
- **依赖复用规则固化**：A0015 两个新 eval 各自保留 worktree 绑定的 wbuild/emu_build
  隔离，仅复用 `wolvrix/build` 的 FetchContent 本地 clone 与 `build/tes/ccache`；
  CMake configure 约 4.4/4.6s 且无联网。长期操作约定已写入任务
  [`playbook.md`](../playbook.md)「构建与依赖复用」，后续按 evaluator 执行即可。

## r001/t2/s04 稀疏 commit 门控与宽态炸开（2026-08-18，action A0016）

- **全局 dirty-edge 阈值证伪**：e00025 的 `min_work_per_edge=4` 拒绝全部
  2,922 个 commit gate（dirty edges 240,198，最终 gated=0），Host 270.956s，
  较 e00019 回退 2.45%。commit 内锥的动态 skip 不能用单一静态边数阈值近似；未来
  若重访，先做逐 gate 的 open/skip 与实际跳过指令统计。
- **宽态炸开与 commit gating 组合证伪**：e00026 炸开 274 状态/16,818 元素，
  将 commit gating 缩为 2,165 gate、87,298 dirty edges、59,160 writes，但 Host
  271.282s（较 e00019 **+2.58%**）。传播边减少没有转成收益，覆盖下降与生成代码
  布局成本共同抵消；静态 edge 数不是运行时净收益代理。
- 两候选均 17/17 ctest、3 rep difftest 全过且 compile_s=1007.5/1152.6s；
  e00025 初次 ctest 失败仅为测试夹具误开稀疏属性，修复后同一 eval-id 重跑并通过，
  没有把失败运行当作性能数据。按 step 内规则 e00025 进入 t2/main，但 t2 best
  仍为 e00019；第 4 轮三轨迹齐平，下一 action 为 round-summary。
- **离线依赖复用再次实证**：e00025/e00026 独立 wbuild/emu_build 的首次 CMake
  configure 为 4.8/4.6s，FetchContent 从 `wolvrix/build` 本地 clone、C++ 使用
  `build/tes/ccache`，全程无联网。后续执行直接遵守任务 playbook，不再新建依赖
  树或反复询问复用规则。

## r001 第 4 轮跨轨迹小结（2026-08-18，action A0017）

- **本轮 run best 再降 5.61%**：e00022 的 source-word activity guard 将
  round 3 best e00018 的 244.278s 降至 **230.568s**（CV 0.66%），相对 AM y0
  累计改善 15.57%，但仍为 gsim 的 9.34x。e00021 的 source-part guard +
  wide first-touch 为 239.354s（-3.27%），证明定向 locality 与扫描剪枝可加；
  两者已有正证据，但组合仍需单独评估。
- **activity 稀疏性应继续按层级细化**：part -> word -> byte 的结果由 e00015/
  e00022 重复确认，word 层仍有一阶收益。后续先统计每个 guard 的 open/skip、
  有效 byte 和状态跨度，再考虑 word guard + first-touch 组合，不能直接相加历史
  百分比。
- **t1 只剩次一阶余量**：e00024 的只读标量常量内联较 e00018 改善 1.20%，
  e00023 的 signed/unsigned resize 扩张回退 4.97%；静态站点减少不是运行时代理，
  helper 扩张还会消耗编译预算。保留常量内联，关闭 resize 扩张。
- **t2 commit 路线收敛为关闭**：e00019 的 91.9% 写站覆盖只带来 1.95%；
  e00025 全局阈值拒绝全部 gate，e00026 将 dirty edges 降至 87,298 仍回退。
  后续除非有逐 gate 动态 open/skip、传播 store 和实际跳过指令的净收益证据，
  不再正式评估静态稀疏代理或 wide-state explode 组合。
- 六个本轮候选均过 17/17 ctest、3 rep difftest 和 2400s 编译门，CV 0.27%-1.49%；
  依赖复用规则继续有效。第 4 轮已齐平，下一 action 是 `r001/t0/s05`，不调整
  C/L/K、不提前 restart，且保持轨迹独立。

## r001/t0/s05 word guard + first-touch 组合与 word snapshot（2026-08-18，action A0018）

- **组合确认并刷新 run best（e00027）**：在 e00022 的 source-part/source-word
  activity guard 上启用 `--wide-storage-first-touch`，Host 中位 **222.654s**
  （222.654/222.542/223.460，CV 0.22%），较 e00022 230.568s **-3.43%**；
  17/17 ctest、3 rep 在线 difftest 和 2400s 编译门均通过，compile_s=606.3s。
  419,243 个宽存储变量中 191,955 个被 Block 触及；候选布局将 static
  block-first cache-line 161,680->151,616、触及跨度
  24,304,307->8,347,000 words、page 17,661->16,303。word 层扫描剪枝后，
  定向宽状态 locality 仍有独立的一阶余量。
- **局部 word activity snapshot 证伪（e00028）**：`--source-word-activity-snapshot`
  每个 source part 将 owned activity word 一次载入局部 `wordFlags`，同 word 未扫描
  的 `act.f` 留在局部，跨 word/part、已消费 byte 与 `act.b` 仍写全局活动字；partial
  mask 与 full-evaluation bypass 均由 emitter 测试覆盖。它的 235.610s
  （232.455/235.610/236.299，CV 0.87%）较 e00022 **+2.19%**、较 e00027
  **+5.82%**，虽然 17/17 ctest、3 rep difftest 均通过且 compile_s=507.6s。
  因此不要把全局 activity word 访存量当作独立热成本代理：word guard 已收掉空扫描，
  局部 snapshot 带来的 `wordFlags` 数据/控制依赖反而退化。
- t0/s05 winner 为 e00027，已进入 `tes/r001/t0/main`。run best 从 230.568s
  到 222.654s，较 AM y0 累计 **-18.47%**，仍为 gsim 24.688s 的 **9.02x**，
  AM/gsim 绝对差距关闭 **20.31%**。t0 现为 5/8，run 已使用 28/48 eval；下一
  action 按轮转为 t1/s05，当前 run 不把 t0 结论注入 t1 proposal。
- 依赖复用约定继续按任务 `playbook.md` 的“构建与依赖复用”执行：独立 eval
  目录只隔离 CMake cache/对象，FetchContent 本地 clone 与共享 ccache 不变；e00028
  的 CMake configure 在离线本地 clone 条件下为 1.8s。该规则已固定，不再把新
  `wbuild` 误解为需要联网下载。

## r001/t1/s05 标量 helper 与常量存储消除（2026-08-19，action A0019）

- **除法 helper 内联为稳定弱正（e00029）**：在 t1/s04 的
  `--resize-elision --inline-scalar-helpers --inline-scalar-constants` 基础上，
  `--inline-scalar-divmod-helpers` 将窄标量 `divide_value` / `modulo_value` 移入
  生成 header。固定 exec-GRH 只有 1,267 个 divide、0 个 modulo 静态站点；Host
  中位 **237.380s**（237.667/237.380/237.256，CV 0.09%），较 t1 e00024
  241.348s **-1.64%**。17/17 ctest、3 rep difftest 全过，compile_s=1039.3s；
  该方向收益低于 3% 一阶门但没有编译膨胀，作为可复用旋钮保留。
- **常量 backing storage 消除取得一阶收益（e00030，winner）**：新增
  `--inline-scalar-constant-storage-elision`，只在字面量内联且 escape/pin 分析
  确认无地址/状态需求时删除窄常量 `v<K>` 成员和 `init()` store。生成 header
  成员文本由 1,263,224 减至 1,253,782，常量 init store 由 158,069 减至
  148,627，runtime 源文件由 107,319,040 bytes 减至 106,652,747 bytes（减少
  666,293 bytes）。Host 中位 **230.447s**（230.520/230.447/226.051，CV
  1.12%），较 t1 e00024 **-4.52%**；17/17 ctest、3 rep difftest 全过，
  compile_s=1032.7s。状态布局/初始化是继常量读取内联后仍可独立收取的成本，
  但删除规则必须继续由 escape/pin 防线约束。
- 两候选均在 2400s 编译预算内，正式 reps 串行绑核且无插桩；六次计数均为
  `instrCnt=73580`、`cycleCnt=49996`，nemu 无 mismatch。`finish-step` 已将
  e00030 合入 `tes/r001/t1/main`，t1 best 更新为 230.447s；本步结论只使用
  t1 轨迹节点，未把其他轨迹实测结论注入归因。
- **依赖复用规则继续固定**：e00029/e00030 各自保留 worktree 绑定的
  `wbuild`/`emu_build`，FetchContent 依赖由 evaluator 重定向到
  `wolvrix/build` 本地 clone，C++ 使用共享 `build/tes/ccache`；受限网络下
  configure、编译和评估均未联网。该约定已记录在任务 `playbook.md` 与 README，
  后续 action 直接遵守，不再重复创建依赖树或提醒联网。

## r001/t2/s05 commit dirty 位图与 producer-change 门控（2026-08-19，action A0020）

- **位图压缩未能收回 dirty 传播成本（e00031，mechanical winner）**：
  `--commit-input-packed-dirty` 将 2,922 个 gate 的 dirty storage 压为 46 个
  `uint64_t` word，并按 producer 的同 word 目标合并 OR mask；静态 dirty edge
  仍为 240,198。Host 中位 **265.250s**（265.250/259.742/266.972，CV 1.43%），
  较 t2 历史 best e00019 的 264.466s **+0.30%**。17/17 ctest、3 rep difftest
  与 compile_s=1184.8s 均通过；差量小于本次 CV，不能证明回退，但也没有正收益
  证据。bit test/clear 和 OR mask 的额外热路径至少没有被 byte-store 合并可靠抵消。
- **producer 输出快照方向明确回退（e00032）**：
  `--commit-input-producer-change` 对 20,476 个窄 producer block 建立输出快照，
  只在真实变化时传播 dirty。它覆盖 2,512 个 gate、103,125 条 dirty edge，却需要
  67,117 个 snapshot 槽；生成模型总文本比 e00031 多约 4.69 MB。Host 中位
  **285.552s**（285.552/284.147/285.900，CV 0.33%），较 e00019 **+7.98%**；
  17/17 ctest、3 rep difftest 和 compile_s=1175.3s 均通过。静态覆盖缩小不等于
  动态净收益；这个明确回退与 producer snapshot compare/update 的普遍开销超过
  省下传播的解释一致，但没有把静态规模当作动态因果证明。
- `finish-step` 按 step 内最高分把 e00031 合入 `tes/r001/t2/main`，但 t2 best
  仍是 e00019。除非先有逐 producer/gate 的动态执行、真实变更率和跳过工作量证据，
  t2 不再正式评估 commit-input 位图压缩或 producer snapshot 的同类细化；这一结论
  只记录在 t2 轨迹，不作为当前 run 的跨轨迹组合依据。

## r001 第 5 轮跨轨迹小结（2026-08-19，action A0021）

- run best 曲线 = y0 273.103s -> r1 270.502s -> r2 269.731s -> r3 244.278s ->
  r4 230.568s -> r5 **222.654s**（e00027）；累计 **-18.47%**，仍为 gsim 的
  **9.02x**，AM/gsim 绝对差距关闭 **20.31%**；本轮 -3.43% 满足 >=3% 继续条件，
  不调整 C/L/K、不提前 restart。evals 32/48，三轨迹各余 3 步。
- **activity 扫描剪枝 x 定向状态 locality 是 run 内最强可叠加轴**：e00027
  （word guard + first-touch，-3.43%）与 e00021（part guard + first-touch，
  -3.27%）一致确认两级剪枝都不吞没定向布局收益。
- **常量生命周期 read -> storage 各层独立可收**：e00024 读取内联 -1.20% 后，
  e00030 backing storage/init store 删除再收 **-4.52%**（本轮最大单步）；e00029
  divmod 内联 -1.64%（CV 0.09%）为稳定弱正旋钮。状态对象瘦身是 t1 继 helper
  调用边界后的第二个一阶池。
- **t0/t1 经正交机制收敛到相近数量级**（222.7s vs 230.4s）：扫描剪枝+布局 vs
  helper/常量内联+状态瘦身，均只动生成 C++ 适配层；是 restart 跨轨迹组合的明确
  材料（当前 run 不组合）。
- **t2 commit-input gating 静态/准静态细化全部关闭**：e00025/e00026/e00031/
  e00032 四连未改善 e00019；覆盖、静态边数、位图压缩、producer 侧真变化过滤
  都不是动态净收益代理。重开条件 = 逐 gate 动态 open/skip、传播 store 与实际
  跳过工作量的净收益证据；可重访形态是 commit 内锥输入侧快照检测（读侧，区别于
  e00032 的 producer 写侧），正式评估前必须离线量化且门槛 >=3%。
- **word 局部 snapshot 证伪**（e00028，+2.19%）：全局 activity word 访存量不是
  独立热成本代理；扫描路径进一步本地化须先有离线 open/skip 与有效 byte 分布证据。
- **机械 winner 边界**：e00031（+0.30%，亚 CV）入 t2/main，无害前提是
  packed-dirty 默认 off；t2/main 现携带两个未证实默认 off 实现（sparse 阈值、
  packed dirty），t2/s06 emit_args 不得携带它们除非有动态净收益证据。

## r001/t0/s06 concat 插入内联与窄态首触（2026-08-19，action A0022）

- **宽拼接调用边界确认一阶（e00033，winner）**：`--concat-insert-inline` 将
  单字退化拼接（静态 72,747/129,506 站点、动态 9.59 亿次 outlined 调用）从
  `insert_words`/`replace_window_words` 改为内联 splice（满字对齐退化为直接
  word store，882 处全 store 化的 `zero_words` 前导消除），Host 中位
  **216.481s**（CV 0.35%），较 e00027 **-2.78%**；17/17 ctest、3 rep difftest
  全过，compile_s=618.4s。残余 56,759 个跨 word insert 站点（动态 ~6.8 亿次）
  是同类下一层候选，正式评估前须先离线核动态权重。
- **窄态首触布局证伪并关闭（e00034）**：`--narrow-storage-first-touch` 把
  911,882/1,263,224 个 touched 窄成员压实（span -27.8%、pages -14.9%），
  Host 反而 **229.850s（+3.23%**，CV 1.20%），emu_build 282s->964.5s。窄态
  VariableId 序已与创建/数据流局部性对齐（热块成员 id 稠密，如 b83400 的
  7,001 个 guard 值），且 touched 占 72% 使「热点子集」假设不成立；
  **窄态布局轴关闭**，排序变体不再重试。
- **离线 runtime-profile recon 落地**（recon-t0s06，e00027 同代码 +19% 插桩
  开销）：eval 100,102 次 / 150,154 rounds；compute 73.7% / commit 26.2%；
  activations 4.77G 与 A0007 持平；块周期 top-122=50%、top-3230=80%，b83400
  单块 5.34%（469K cyc/exec）；全部 2,973 个 commit 块每 eval 全触发。
   cumulative block-execs 不能反映 per-round word 开闭（1,348/1,350 word
  全开过），scan 侧进一步细化必须先做 per-round 插桩。
- t0 best 216.481s（较 AM y0 **-20.73%**，gsim 比 **8.77x**，绝对差距关闭
  **22.76%**）；t0 完成 6/8，run 使用 34/48 eval。

## r001/t1/s06 宽 helper 内联与宽常量 rodata 迁移（2026-08-19，action A0023）

- **宽 helper 内联轴关闭（e00035，机械 winner）**：`--inline-wide-helpers` 把
  zero/assign/assign_from_scalar/insert/replace_window/slice_words 六个宽 word
  helper（t1 tip 静态 ~23.5 万调用站点，其中 insert_words 61.7% 为 ≤64bit 退化）
  移入生成头文件内联，Host 中位 228.935s（CV 0.41%），较 e00030 仅 **-0.66%**，
  未达 3% 假设门：宽值层的跨 TU 调用边界非一阶成本，e00018 的 -9.69% 收益定位
  在窄标量层。emu_build 697.5→1757.5s（b38653 所在单 TU `blocks_18_part_5.cpp`
  内联 8,279 个宽 helper 后单 TU ~28min 成长极点），compile_s=2091.2s 距 2400s
  预算仅 ~309s 裕量；编译代价与收益严重不成比例，后续 t1 候选不携带该旋钮。
  knob 默认 off、emit 不携带即逐字节等价，机械合入无害（同 e00011 先例）。
- **宽常量迁移运行时关闭、编译侧兑现（e00036）**：`--wide-constant-rodata` 将
  25,654 个不可写宽标量常量（1,643,970 words，占可变宽池 6.8%）迁入零初始化
  常量池，init() 宽字面量 store 1,663,331→19,361 行，块代码 56,797 处读取
  重定向；Host 中位 232.901s（CV 1.16%）较 e00030 **+1.06%** 小幅回退（reps
  229.1/232.9/234.3 递增有漂移迹象），6.8% 池收缩未转成收益，宽常量运行时轴
  关闭。但 emu_build 697.5→230.0s（**-67%**）是显著编译杠杆，该 knob 默认 off，
  可作未来编译门紧张候选的减压选项。
- t1 best 228.935s（较 AM y0 **-16.16%**，gsim 比 **9.27x**，绝对差距关闭
  17.87%）；t1 完成 6/8，run 使用 36/48 eval。t1 两个一阶轴（C++ 调用边界、
  常量/状态瘦身）在宽值层均关闭，残余余量需要 per-block runtime-profile recon
  （t1 tip 代码、离线非计时）定位下一个一阶池；不建议继续堆叠亚 1% emit 微调。

## r001/t2/s06 读侧快照离线证伪、组合中性与安慰剂漂移（2026-08-19，action A0024）

- **commit 内锥读侧快照检测静态定量关闭**：实现 `--commit-input-snapshot-gating`
  （afa419c，默认 off，文档 §3.2.13）后离线量化——沿用 dirty 制度筛选（64 叶/
  W>=2L）时真设计 gated=0；放宽到读侧校准（256 叶/W>=L）也仅 gated=1,246、
  保护 8,842 指令/3,058 写站（e00019 保护面的 ~2%），被接受门 W/L 均值 ~1.39；
  807 个 unsafe 块（宽/非标量叶）持有 116,998 写。大叶数是 commit 锥宽的结构
  属性，读侧按值比较的成本随叶数线性、收益上限 ~1.9% 写站 < 3% 门槛，按 A0021
  纪律未进正式评估，该轴以定量证据关闭；动态 stats recon 未做（静态已封顶）。
- **安慰剂对照暴露跨日漂移 ~2.6%**：c2 的 `--tree-atom-fold-max-instr 8` 在
  gsim node-aligned 调度下惰性（emit 日志 `optimize skipped (gsim node-aligned)`），
  e00038 生成代码与 e00019 逐字节一致（1,714,748,225 bytes，仅 .pch 差），
  成为意外安慰剂：e00019 代码 8-17 测 264.466s、8-19 重测 257.629s（-2.58%）。
  刻度：同代码跨日漂移 >2.5% 协议内 CV；凡对照点不同日且名义差 <3% 的裁决
  一律存疑（e00019 自身的 -1.95% 也是跨日读数，restart 前需同日重测校准）。
- **勘误 e00037 登记 insight**：其中「确认 -2.71% 越假设门」为跨日名义差，
  同日对照（vs e00038 安慰剂）为 **-0.13%**——affinity+消零+commit 门控组合
  相对门控单机制亚噪声中性，组合可加性在现协议分辨率下不可裁。
- e00037 按 step 内分数机械 winner（0.13% 噪声级）入 t2/main；t2/main 此后携带
  `--init-zero-elision --state-layout affinity`：运行时中性，但 emu_build
  845s→296s（-65%）、compile_s 623.9s，t2 评估时延与编译预算裕量显著改善；
  回撤路径 = emit_args 摘除两旋钮（代码默认 off 逐字节等价）。
- atom 粒度轴不能经 `--tree-atom-fold-max-instr` 触达（node-aligned 跳过整个
  optimize 管线）；要探 atom 粒度须先解除 node-aligned 对齐（属另一实验条件）。
- evals 38/48，t2 余 2 步；下一 action = 第 6 轮 round-summary。

## r001 第 6 轮跨轨迹小结（2026-08-19，action A0025）

- run best 曲线 = y0 273.103s -> r1 270.502s -> r2 269.731s -> r3 244.278s ->
  r4 230.568s -> r5 222.654s -> r6 **216.481s**（e00033）；累计 **-20.73%**，
  仍为 gsim 的 **8.77x**，AM/gsim 绝对差距关闭 **22.79%**；本轮名义 -2.78%。
  evals 38/48，三轨迹各余 2 步。
- **本轮三条轨迹均无干净 >=3% 收益，触发继续/restart 用户裁决条件**：t0 名义
  -2.78% 但对照跨日存疑、t1 -0.66% 机械 winner、t2 同日对照 -0.13% 中性。
  预算余 10 eval，跑完剩余 3x2xK=2 需 12——r001 已无法在预算内走满 8 步。
- **同代码跨日漂移 ~2.6%（e00038 安慰剂实证）大于协议内 CV**：凡对照点不同日
  且名义差 <3% 的裁决一律存疑；e00033（-2.78% vs 8-18 的 e00027）与 e00019
  自身的 -1.95% 均属此类，restart 定 y0 前必须同日重测校准。
- **本轮关闭的轴**：宽 helper 内联（e00035，-0.66% + 编译 2.5x 恶化）、宽常量
  运行时（e00036，+1.06%）、窄态首触布局（e00034，+3.23% 反转——id 序本已
  对齐局部性）、commit 内锥读侧快照（静态封顶 ~2% 保护面 < 3% 门）、atom 粒度
  旋钮（node-aligned 下惰性不可触达）。t2 自 e00019 起 7 候选无同日干净改善。
- **编译杠杆工具箱成型**（均默认 off、与运行时收益可分离）：init 消零
  （runtime.o -97%）、wide-constant-rodata（emu_build -67%）、affinity+消零
  （emu_build -65%）；t1 已逼近编译门（2091/2400s），后续候选应主动携带减压。
- **restart 备选 y0 材料**：t0 扫描剪枝+宽态首触+concat 内联 x t1 窄标量
  helper/常量内联+常量存储消除，机制正交且只动生成 C++ 适配层；当前 run 保持
  轨迹独立不组合。

## r001/t0/s07 拼接 unroll 与窄标量 helper 内联（2026-08-19，action A0026）

- **窄标量 helper 调用边界是 t0 最大一阶适配胶（e00040，winner）**：
  `--inline-scalar-helpers` 把 `slice_value`/`shift_left`/`shift_right`/
  `arithmetic_shift_right`/`signed_value`（静态 534K 站、站点×块execs 加权动态
  **22.5 亿次** outlined 调用，slice_value 独占 19.35 亿）移入生成头文件
  `constexpr`，Host 中位 **194.792s**（CV 0.45%），较 e00033 **-10.02%**，
  为 run 最大单步；17/17 ctest、3 rep difftest 全过，compile_s=603.3s、
  emu_build 264.7s **无编译膨胀**。t0 的 C++ 适配层调用边界已三层确认：
  扫描调用（part/word guard）、宽拼接写 splice、窄标量算值 helper。
- **跨 word 拼接 unroll 弱正未确认（e00039）**：`--concat-insert-unroll`
  三形（对齐满字直存 2,525 站、窄跨 word 双语句 7,029 站、≤8word 宽 unroll
  37,679 站；残余 insert_words 56,763→10,379）Host 中位 **212.386s**
  （CV 0.64%），较 e00033 **-1.89%**，低于 2% 假设门、高于 1% 证伪线。
  e00033 收掉单字退化层后残余 splice 调用边界降为二阶（多 word 站点单次
  调用已摊薄边界开销）。旋钮默认 off 留存，可与新 base 叠加复测；
  遗留 867 站 width=64&shift≠0 未覆盖（Case B 可放宽至 width<=64）。
- **离线方法**：perf 被 kernel 禁（paranoid=4 含软事件）后改用
  recon 块execs × emit 文本站点动态加权盘点 helper 调用池——`extract_word`/
  `concat_value`（31.9/40.9 亿次）已是头文件 constexpr 非候选；备查池：
  commit 写侧 `*_detect` 族 6.4 亿、`index_words` 3.66 亿、`slice_words`
  2.39 亿、`divide/modulo_value` 1.27 亿。`zero_words` 前导消除推广被离线
  否决（残余前导所在语句组全部仍含 outlined 调用，可消组为 0）。
- t0 best 194.792s（较 AM y0 **-28.67%**，gsim 比 **7.89x**，绝对差距关闭
  **31.52%**）；t0 完成 7/8，run 使用 40/48 eval。两候选与 e00033 同日
  测量，不涉 A0024 的跨日漂移刻度。

## r001/t1/s07 死宽态消除与 divmod 复测（2026-08-19，action A0027）

- **死宽态消除确认有效但非一阶（e00041，winner）**：`--dead-wide-storage-elision`
  将宽池 24,304,307→**8,347,000 words**（**-65.66%**，约 122MB 死变量移除，
  活集 word 数与既有块触及跨度统计 8,347,000 精确互证），Host 中位
  **224.038s**（CV 1.53%），较 e00035 **-2.14%**、较 knob-off 等价基线 e00030
  **-2.78%**——低于 3% 假设门但显著过 1% 证伪线。死 word 从不被访问，收益全部
  来自活集压实后的 gather/TLB 局部性；收益 ≪ 池收缩比例，t1 热块工作集远小于
  活集（recon：top 86 块 = 50% 周期）。附带 emu_build 697.5→220.3s（**-68%**），
  compile_s 570.9s，t1 编译预算裕量充裕。
- **divmod 内联在瘦身后基线上反转关闭（e00042）**：e00029 曾在 e00024 基线
  -1.64%（CV 0.09%），本步在 e00030 之后复测为 **232.107s（+1.38% vs e00035，
  CV 0.16% 极干净）**——弱正旋钮的收益依赖基线布局，基线变化可翻转符号；
  同类「未中选弱正旋钮复测」须按新基线重证，不可继承旧读数。
- **t1 tip recon 数据**（recon-t1s07，插桩 +25%）：commit 相占块周期 **33.5%**
  （t1 无任何门控/剪枝机制），b83400 单块 6.70%（586,807 cyc/exec）、b38653
  2.50%（1.38M cyc/exec）；1,350 个 activity word 全部开过。窄标量成员
  1,253,782 中 499,636（39.9%，约 4MB）从未被生成代码命名——窄层死成员消除
  是 s08 的收尾型候选材料。
- **emitter 实现要点**：escape 分析对所有宽变量无条件 kEscapeGlobal，不能用作
  宽活性依据；活性须从全量指令 operands/results + 端口 + declared label 构建
  （蕴含 dynblend/window plan 点名）。死宽变量 offset 置哨兵，init store 跳过；
  旋钮 off 逐字节等价。
- evals 42/48，三轨迹各余 1 步，预算恰好 3x1xK=2；下一 action 按轮转为 t2/s07。

## r001/t2/s07 动态 gate 白名单与热度加权布局（2026-08-20，action A0028）

- **commit gating 细化轴以动态证据彻底关闭（e00043 证伪）**：按 A0021 唯一认可的
  重开形态，先 recon 插桩（`--commit-input-gate-stats`）实测逐 gate open/skip，
  按 skips×保护指令 ≥ 评估次数×dirty边 的净收益规则仅保留 **151/2,922** gate
  （dirty 传播边 240,198→130,433，保留 66.8% 动态跳过工作），Host 中位 257.411s
  （CV 1.16%）较 e00037 **+0.04%** 亚噪声持平。剪掉 46% 传播边无任何影响：
  传播 store 与门控跳过同为二阶，且「传播边抵消 e00019 收益」的模型本身建立在
  跨日读数上（A0024 安慰剂刻度 ~2.6%）。t2 commit 轴 7 变体（门控/稀疏阈值/
  宽态炸开组合/位图/producer 快照/读侧快照/动态白名单）全部以证据关闭。
- **热度加权 affinity 未确认、轴关闭（e00044）**：t2 自有 recon（880.3M block
  execs，top 5,742 块=50%、单块最高仅 0.02%，86,342 簇全热）导出的簇降序重排，
  Host 中位 255.105s（CV 0.95%），较 e00037 名义 -0.85%（跨日不可裁）、同日较
  c1 -0.90%；低于 2% 假设门。热度分布平坦 ⇒ 热工作集≈全模型，重排无可压缩空间；
  布局类收益上限 ~1-2% 收敛确认。
- e00044 按同日 0.90% 噪声级机械 winner 入 t2/main（`--state-layout-hotness`
  默认 off，emit 不携带即逐字节等价，回撤零成本）；t2 best 仍为 e00019。
- 两候选 17/17 ctest、3 rep difftest 全过，compile_s 473.2/564.6s（affinity+消零
  编译杠杆保持）； recon 产物 `evals/recon-t2s07c{1,2}/`（gate_stats.txt、
  commit_gate_map.json、block_execs.txt）保留供审计。
- **t2 自 e00019 起 9 候选无同日干净改善**；evals 44/48，三轨迹各余 1 步（共需
  6 eval > 余 4）。t2/s08 建议同日校准型候选（安慰剂重测/默认 off 说明性候选），
  把预算让给 restart 前的同日重测需求（A0025 纪律），不再开无证据新机制。

## r001 第 7 轮跨轨迹小结（2026-08-20，action A0029）

- run best 曲线 = y0 273.103s -> r1 270.502s -> r2 269.731s -> r3 244.278s ->
  r4 230.568s -> r5 222.654s -> r6 216.481s -> r7 **194.792s**（e00040）；
  累计 **-28.67%**，仍为 gsim 的 **7.89x**，AM/gsim 绝对差距关闭 **31.52%**。
  evals 44/48，三轨迹各 7/8 步；余 4 eval < 走满 s08 所需 6，r001 将在预算
  耗尽处提前收口转 run-summary。
- **C++ 适配层调用边界轴跨轨迹独立复证，收敛为最强机制族**：t1 e00018 与
  t0 e00040 对同一窄标量 helper 内联机制分别同日干净测得 -9.69%/-10.02%；
  叠加 t0 的扫描调用剪枝与宽拼接 splice，「只消适配胶、不动调度工作量」
  已三层确认，是 restart y0 组合材料中证据最强部分。
- **本轮关闭的轴**：commit gating 细化以动态证据彻底关闭（e00043：剪掉 46%
  传播边 Host 不变，传播 store 与门控跳过同为二阶；t2 共 7 变体全关）；
  热度加权 affinity 布局（e00044，热度分布平坦注定上限 ~1-2%）；divmod
  内联在新基线复测反转（e00042 +1.38% vs e00029 旧基线 -1.64%）——
  **弱正旋钮收益依赖基线布局，基线变化可翻转符号，旧读数不可继承**。
- **布局类收益上限收敛确认**：first-touch（-3~-6%）> 死宽态消除（-2.1%）>
  affinity/热度重排（≤1% 未确认）；热工作集≈全模型时重排无可压缩空间。
- 第 6 轮触发的「继续 vs 提前 restart」裁决由本轮 t0 同日干净 -10.02% 解除，
  按纪律继续至预算耗尽；restart 与否留给 run-summary 后用户裁决（auto=false）。
  s08 建议：t0 优先（残余 splice 复测/recon 剩余 outlined 池），t1 窄层死成员
  消除收尾，t2 同日校准型候选（为 restart 定 y0 的同日重测留证据）。

## r001/t1/s08 窄层死成员消除与同日安慰剂（2026-08-20，action A0031）

- **窄层死成员消除确认（e00047，winner，t1 末步）**：`--dead-narrow-storage-elision`
  （共享活性扫描：全量 instruction operands/results + 端口 + declared label）消除
  **350,989** 个从未被引用的窄成员（1,253,782→902,793，窄区 -28.0%，~2.68MB；
  低于 recon 文本口径的 499,636/39.9%，emitter 活性判定更保守），Host 中位
  **218.976s**（CV 0.94%），较同日安慰剂 e00048 **-1.36%**（越 1% 假设门），
  17/17 ctest、3 rep difftest 全过，compile_s=530.0s（emu_build 195.5s，再 -13%）。
  死态消除族三层收益与体积同向缩放（122MB→-2.78%、2.68MB→-1.36%），状态瘦身轴
  在 t1 收敛关闭。off 逐字节等价（332 文件 diff 为零），已入 t1/main。
- **同夜安慰剂给出新漂移刻度（e00048）**：t1 tip 原样重测 221.998s（CV 0.92%），
  较约 4 小时前的 e00041（224.038s）仅 -0.91%——**同夜漂移 <1%，跨日（A0024）
  ~2.6%**；restart 定 y0 的同日校准，t1 侧锚点已备（e00048），t0 侧尚缺。
- t1 走满 8/8，t1 best 218.976s（较 AM y0 -19.82%，gsim 比 8.87x）；**evals
  48/48 预算耗尽，t2/s08 不发生，r001 提前收口转 run-summary**。

## r001/t2/s08 同日校准双锚点与预算口径勘误（2026-08-20，action A0032）

- **勘误 A0029/A0031 预算算术**：`counters.evals` 含 2 个基线 eval（e00001/e00002），
  对 N=C·L·K=48 的候选预算比较时应先减 2。t1/s08 完成时 48 = 2 基线 + 46 候选，
  余量恰为 2 = K，t2/s08（e00049/e00050）合法且跑完后候选恰好 48/48——r001 全部
  24 步无遗漏走满，「t2/s08 不发生、提前收口」的结论作废。
- **t2/main 同日锚点落地（e00049，winner）**：现行配置（guard-event-gating +
  commit-input-gating + init-zero-elision + affinity，摘除 hotness）254.533s
  （CV 0.25% 极干净），较同日 e00044 仅 -0.22%——hotness 回撤零成本实证；restart
  定 y0 的同日校准 t1 侧（e00048）、t2 侧（e00049）已备，t0 侧仍缺。
- **e00019 配置同日重测不可裁（e00050）**：261.114s（CV 1.22%，rep 窗内上行
  ~2%），同日较 e00049 +2.52%，但与 08-19 同配置对 e00037/e00038 的同日 -0.13%
  矛盾——两轮同日实验在同一配置对上互相矛盾，即「affinity+消零运行时效应 ≤
  布局/漂移噪声底」的直接证据；e00019 的 t2 best 地位与 affinity 收益均不可裁，
  restart y0 不得依赖这两个读数。跨日漂移带宽实测 ±1.3~2.6%（e00019 配置三点：
  264.5 08-17 / 257.6 08-19 / 261.1 08-20），与 A0024 刻度一致。
- **编译杠杆再复证**：同 tip 代码无消零 emu_build 854.3s vs 消零+affinity
  287.4s（-66%），compile_s 1185.7 vs 619.2s，与运行时收益无关地成立。
- t2 走满 8/8，t2 best 名义 254.533s（较 AM y0 -6.80%，gsim 比 10.31x——三条
  轨迹中最弱，commit 轴全关后收益垫底）；evals 50/50（含 2 基线），候选 48/48
  耗尽，下一 action = run-summary。

## r001 run-summary：run 收口与 restart 建议（2026-08-20，action A0033）

- **r001 收口**：24/24 步走满、候选 48/48 耗尽（+2 基线 = 50 eval）。
  best_overall **194.242s**（e00045，commit `9c0a89db`，t0/main tip），较 AM y0
  **-28.89%**，仍为 gsim **7.87x**，AM/gsim 绝对差距关闭 **31.75%**。轨迹 best：
  t0 194.2 / t1 219.0 / t2 254.5（秒）。候选健康度：ok 44 / compile_timeout 3 /
  difftest_fail 1。详见 `runs/r001/summary.md`。
- **三族正交一阶机制（restart y0 组合材料）**：适配层窄标量 helper 内联（-9.69%
  × -10.02% 跨轨迹复证）；activity 扫描剪枝 × wide first-touch（-9.44/-6.83/
  -3.43% 可加链）；常量/死态瘦身族（-1.20/-4.52/-2.78/-1.36%，随体积收敛关闭）。
  t2 commit 轴 7 变体全关；e00019 与 affinity 收益不可裁，不作 restart 依据。
- **restart 建议（auto=false，待用户确认）**：y0 = t0/main tip `9c0a89db`，叠加
  t1 常量族四旋钮；建议 C/L/K = 2/8/2（N=32），K=2 一席常态化同日校准。t0 tip
  同日锚点缺失由 r002 run-init 基线天然覆盖，勿在 r001 尾巴补测。
- **方法论刻度（后续 run 继承）**：同夜漂移 <1%、跨日 ~2.6% > 协议 CV；跨日
  名义差 <3% 的裁决存疑；弱正旋钮旧读数不可继承（基线依赖反转）；同日安慰剂/
  锚点常态化。编译杠杆（init 消零/rodata/dead-wide）compile_s ~1200s→~600s。

## brief.md 变更记录：r002 纪律调整（2026-08-20，用户指示）

- **变更面纪律改写（brief.md「优化哲学」）**：GRH IR 冻结不变；grhsim AM 与
  调度/分区/布局算法层均由「灵活调整」升级为「**可激进改动**」（允许推翻既有
  形态另起炉灶）；新增「改进尽可能显式化」（激进重构也须落为可命名、可开关、
  可归因的显式 pass/算法阶段）与「**突破性、原创性导向**」（不以 ~1% 级旋钮
  微调占用正式评估预算）。
- **路线调整（同次指示）**：gsim 基线改用 **master**（本机已建
  `build/xs/gsim/gsim-compile/emu`，50k coremark difftest 通过，
  73584/49998）；AM 路线改为 **wolvrix 自解析 SV**（`make
  xs_wolf_grhsim_am_emit`，不再依赖 gsim 导出的 exec-GRH），本机首跑
  difftest 通过（73580/49996，Host 402.7s，本机首个参考点）。
- **本机环境修复**：重建 `build/dependency/root`（bison/flex/libfl/gmp/zstd/
  zlib deb 解包）；wolvrix/build 重 configure（旧缓存无 grhsim-am-lower-json
  target）；Makefile 目标需先 `source env.sh`。
- **编译并核放宽（2026-08-20，用户指示）**：`config.json eval.vm_build_jobs`
  16 → **128**（本机 384 核 / 1.5TB RAM）；wolvrix 构建本就不设限
  （`-j os.cpu_count()`）。只影响编译墙钟，计时 reps 仍串行绑核
  （core=12）不受影响。

## r002 run-init：新机器 restart + clang 工具链 + rep 绑核并行协议（2026-08-20，action A0034）

- **restart 落地（用户确认）**：y0 = r001 best `9c0a89db`（用户已并入其主线分支
  `grh/tes-grhsim-am`，r001 的 tes/* 分支由用户自行清理）；C/L/K = **2/8/2**
  （N=32，按 r001 summary 建议）。输入切换为 wolvrix 自解析 post-stats JSON
  （sha256 `cbd78c0b…3246`，r002 起正式取代 gsim 导出 exec-GRH）。
- **新机器（AMD EPYC 9654，2×96C/384T，1.5TB）**：绝对时延全面上移，r001 绝对
  读数自此仅作历史——AM y0 本机 **619.019s**（旧机 273.1s）；gsim 本机
  **46.792s**（旧机 24.7s）。起跑差距 11.06x → **13.23x**：AM 侧对新机器
  （单核性能/内存子系统）比 gsim 更敏感。
- **工具链 clang 固化（用户指示）**：clang 21.1.8（PATH 经 `~/.bashrc`）。
  evaluator 的 wolvrix cmake 本就固定 clang/clang++；difftest Makefile 在 PATH
  有 clang 时自动选 clang++——r002 起全链路（wolvrix 构建 + emu 构建）均为
  clang -O3。gsim emu 与 post-stats JSON 已先于本 action 在本机重建（见前条
  「r002 纪律调整」）。
- **协议变更：rep 绑核并行（用户指示，2026-08-20）**：3 rep 由逐 rep 串行改为
  批内并行，各绑一个独立物理核（config `eval.rep_cores` = 12/13/14，同属
  socket 0、非 SMT 兄弟）；干扰守卫改为每批次起跑前检查；评估间仍全局 LOCK
  严格串行。protocol.md / RULES.md / config.json 已同步。
  - 刻度：并行批对内存敏感负载有均匀抬升——AM 同代码单跑 539.2s（首跑串行
    rep1，协议切换中止现场）vs 批内 619.0s（**+14.8%**）；gsim 单跑 39.6s
    （e99901）vs 批内 46.8s（**+18.1%**）。两侧同协议测量，比值裁决不受影响；
    批内 CV 极紧（~0.0%）。
  - 墙钟收益：rep 阶段 ~3x 提速（AM 每 eval 省 ~20min）。
  - 配置漂移勘误：r002 manifest 冻结的 eval 段无 `rep_cores`（init-run 先于
    协议变更数小时），以 config.json 现值为准，特此登记。
- **基线登记**：AM e00001 = **619.019s**（compile_s 622.3s = cmake/cache 命中
  + ctest 221s + emit 63.5s + emu_build 增量 334.4s；17/17 ctest、3 rep
  difftest 全过 73580/49996）；gsim e00002 = **46.792s**（73584/49998）。
  e00001 首跑因协议切换主动中止（留下 539.2s 单跑对照），同 eval-id 重跑覆盖，
  result.json 为并行协议版本。
- **起点判断**：13.23x 起跑差距大于 r001（11.06x）；y0 已含 r001 全部代码级
  winner，t1 常量族四旋钮叠加是两轨迹共同的近期组合材料；本机 compile_s
  ~622s ≪ 2400s 预算（注：本次 wolvrix 构建为 cache 命中，冷 wbuild 候选会
  更高，r001 口径下仍裕量充足）。

## r002/t0/s01 机制链迁移、调度点一阶效应与基线污染红旗（2026-08-20，action A0035）

- **winner（e00003，已入 t0/main）**：gsim-aligned 默认调度点 + r001 t0 winner
  9 旋钮链 = **362.869s**（CV 0.0%，17/17 ctest、3 rep difftest 全过）。
  t0 的有效 emit_args 此后 = CLI 默认调度点 + 9 旋钮（branchy-mux /
  resize-elision / init-zero-elision / source-part+word-activity-guard /
  wide-storage-first-touch / concat-insert-inline / inline-scalar-helpers /
  concat-insert-unroll）。
- **2×2 因子分解（同下午窗口，互可比）**：config 调度 +~0 = 452.803s
  （e00004 重测）；config +9 旋钮 = 388.896s（旋钮链 -14.1%）；
  gsim-aligned +~0 = 378.365s（调度 -16.4%）；gsim-aligned +9 旋钮 =
  362.869s（旋钮在其上仅 -4.1%）。gsim-aligned 调度本身已消除大部分适配
  胶——**调度点是一阶变量，分区/调度轴在 r002 重新打开**（旧图 NO0002
  「分区形状中性」不适用于 wolvrix 自解析新输入）。
- **死态瘦身族证伪**：新输入图死宽池仅 6,535 变量 / 34,284 words（占池
  0.46%；r001 旧图 66%），死态已被 ingest/normalize 消化；
  `--dead-wide-storage-elision`（重实现，0f17059，默认 off 逐字节等价，
  含单测与文档）运行时无对象，族内（dead-narrow/常量存储）勿再投入。
- **基线污染红旗**：e00001（619.019s，晨 11:54-12:04）与同配置语义下午
  参照（452.803s）差 27%，机制上不可能（0.46% 池收缩 + init store 消除），
  生成代码 diff 实证仅池 offset 平移——**晨间基线处于慢机器态，AM/gsim
  基线比值与全部 vs 基线 ratio 暂不可裁，待重锚**。批内并行 CV≈0 不能
  检测整批均匀污染；A0034 的「并行批 +14.8%/+18.1% 抬升」刻度混入机器态
  变化嫌疑，需重估。
- **测量/操作教训**：evaluator `--emit-args` 是整体替换（override 则 config
  全丢），r002 起候选必须显式携带目标调度点全参数（r001 无此问题因 r001
  config emit_args 恰为 CLI 默认值）；`--emit-args` 值以 `-` 开头时须用
  `--emit-args=<值>` 等号形式（argparse 拒绝前导 `--` 的分离值）。
- **勘误**：e00003 首轮 ledger 记录的 insight「机制链迁移确认 -41.38%」
  归因错误（混入调度点差异）；record-eval 无 replace 路径，正确分解以
  A0035 笔记与本条为准。

## r002/t1/s01 常量内联重实现与双态环境混杂刻画（2026-08-20，action A0036）

- **inline-scalar-constants 重实现落地、同频裁决中性（e00006，winner）**：
  只读窄标量常量（≤64bit、InitKind::Constant）读取发射为掩码字面量
  （12,795 变量 / 711,978 站点，off 逐字节等价、17/17 ctest、文档同步），
  ledger 分数 443.899s 为快窗口抽签非机制收益；**验证同频 3.7GHz 三点**
  c2 564.8s vs c1 574.2/601.7s（-1.6%/-6.1%，构建噪声 ±4% 带上沿）——
  机制中性，t1 常量/状态瘦身族（含 A0035 死态证伪）在新输入图上整体
  关闭，与 t0 独立互证。t1/main tip = c8b4a2c（config 调度 + 3 旋钮）。
- **×1.3-1.4 双态环境混杂定量刻画（本 run 最大测量危害）**：计时读数
  分快簇 ~425-450s / 慢簇 ~565-615s，20-40min 尺度翻转；1Hz 频率轨迹
  证伪 CPU 频率（计时批次全程恒定 3.7GHz，低速仅编译期），同居进程
  排除，同态批间 ±4% 为独立构建/链接布局噪声；残余指向 THP/NUMA
  页放置 per-process 运气（未取证）。**现协议只能分辨 ≥30% 效应**；
  批内并行 CV≈0 无检出能力。
- **刻度勘误**：e00001(619.0) vs e00004(452.8) 的 27% 与 A0034「并行批
  抬升 +14.8%/+18.1%」均为双态抽签误读（非晨间窗口、非并行抬升）；
  基线与全部 ratio 维持不可裁。A0035「晨间慢窗口」叙事由本条取代。
- **协议升级建议（提请用户）**：rep 期记录机器态（freq + smaps_rollup
  THP + numa_maps）；每候选 2 批次跨窗口或同窗参照 emu 归一；基线重锚。
  频率/机器态只读监视模式（1Hz 轮询）与计时纪律兼容，可复用。

## r002 第 1 轮跨轨迹小结（2026-08-20，action A0037）

- **常量/状态瘦身族在新输入图上整体关闭（跨轨迹收敛互证）**：t0 死宽池仅
  0.46%（e00004 证伪，wolvrix 自解析已消化死态）× t1 inline-scalar-constants
  同频 3.7GHz 对照中性（e00006，c2 564.8s vs c1 574.2/601.7s 在 ±4% 构建噪声
  带内）。r001 第三族机制不迁移，族内（dead-wide/dead-narrow/常量存储/常量
  读取）勿再投入。
- **调度点是一阶变量，分区/调度轴在 r002 重开（发散）**：t0 2×2 因子分解
  （同下午窗口）——config+~0 452.803s / config+9旋钮 388.896s（-14.1%）/
  gsim-aligned+~0 378.365s（调度单变量 -16.4%）/ gsim-aligned+9旋钮
  362.869s（旋钮增量仅 -4.1%）。gsim-aligned 调度已吸收大部分适配胶；
  旧图 NO0002「分区形状中性」不适用于 wolvrix 自解析新输入。round 1 best
  = e00003 362.869s（对同窗 config 参照 -19.86%）。
- **vs 基线全部 ratio 维持不可裁**：e00001/e00002 测于慢机器态（双态
  ×1.3-1.4 混杂，A0036 刻画），AM/gsim 差距 13.23x 与各候选 vs 基线百分比
  均待基线重锚；可裁口径一律用同窗参照。
- **候选设计纪律（协议升级裁决前）**：现协议只可分辨 ≥30% 效应；机制假设按
  该量级构造，亚 10% 机制不占正式评估；每 step 内候选互为同窗对照，不引用
  跨窗口读数；批内 CV≈0 不具备整批污染检出能力。
- 协议升级（rep 期机器态记录 / 跨窗口双批或同窗参照归一 / 基线重锚）仍待
  用户裁决；C/L/K 不变，evals 6/32。

## r002/t0/s02 recon 驱动双候选：宽站 detect 快速路径大胜、守卫聚簇证伪（2026-08-20，action A0038）

- **离线 recon 落地（recon-t0s02）**：复用 e00003 wbuild + `--runtime-profile`
  重 emit（gsim-aligned + 9 旋钮），emu_build 1531s、插桩单跑 391.6s（金标过）。
  新图画像：eval 100,102 次、**rounds 恒定 2.00/eval**（changed marks 恰 2/eval
  = clock prev 检测器自更新驱动 round 2）；compute 67.6% / commit **32.4%**；
  top-56 块 = 50% cycles。**commit 池集中**：43 个每 eval 触发的 commit 巨块独占
  **31.7%**（b93159：8,464 atoms、870 窄站 + 1,313 宽站、5.91%、411k cyc/exec）；
  **守卫池**：b90656/90657（各 ~7,000 atom system.task 条件评估）合计 **9.2%**、
  per-atom ~50cyc。round-2 动态面 ≈ ~50k 桶 11.6%（~200k 桶仅 1 块）——
  「消 round/下降沿」类机制上界 ≈ 扫描余量，不候选。
- **确认且超假设（e00007，winner，已入 t0/main）**：`--wide-detect-fast-path`
  （ecb4c3f）——assign_words_detect 同宽无符号扩展站点（全部 4,103 站点）改
  memcmp 答 idle + memcpy 退化 + 末词掩码纪律；反汇编实证通用循环未被向量化
  （每词 ~12-15 标量指令）。Host **261.543s**（CV 0.0%，门全过，compile_s
  1863.9s），较 t0 tip 名义 **-27.9%**。同窗逻辑控制：c1/c2 同窗差 27.1%，若归
  因机器态翻转则 c2（9.2% 池）也须 -25%，物理不可能——机制成立，非抽签。
  观测超先验（-15~20%），溢出部分待同 tip 重测锚定。
- **证伪（e00008）**：`--guard-operand-cluster`（d9f56be）聚簇 6,574 个守卫
  enable 变量到连续声明区，358.456s 亚分辨持平——守卫块 per-atom ~50cyc
  **不是散射数据 miss 主导**；残余嫌疑 = 巨函数体的 i-cache/分支前端成本。
  守卫池只剩「事件槽整块门控」（e00014 机制在新图 9.2% 集中池上重估）与
  瘦身两路；布局路线对守卫关闭。
- **测量纪律**：两候选计时窗 freq trace 全程 3.70GHz 恒定（自终止只读采样，
  产物 evals/e0000{7,8}/freq_trace.txt）；emu_build 双侧 1512.9s 持平
  （compile_s ~1860s，预算余量 ~540s，扩张型候选需盯）。
- evals 8/32；t0 best 261.543s；下一 action = t1/s02（轨迹独立）。

## r002/t1/s02 二级活动摘要扫描与同窗安慰剂（2026-08-21，action A0039）

- **t1 自有 recon 落地（recon-t1s02）**：config 调度 + 3 旋钮插桩单跑 610.992s
  （金标过）。画像：rounds 恒定 2.00/eval；compute 70.3%/commit 29.7%；**43 个
  每 eval 触发的 commit 巨块独占 29.0%**（b119387：8,464 atoms、398k
  ticks/exec，内部 = 宽站 detect + 窄站 wrNext_ 混合的寄存器堆写口阵列）；
  **b116236 单块 12.63%**（24,324 atoms、~48 cycles/atom，同一 4096-bit 宽值
  的逐 bit extract_word 锥，前端/i-cache 绑定）；top-41 块 = 50%。扫描骨架：
  30,324 byte-chunk prologue/round 无条件执行，compute 相墙钟与块体 tick 折时
  缺口 ~50%（chunk 直线码推算仅 ~4s，主体未归因：i-cache 流式/分支行为/插桩）。
  教训：块级 dump 需运行时同设 `EMU_RUNTIME_PROFILE=1` + `EMU_AM_BLOCK_EXECS`。
- **机械 winner（e00009，已入 t1/main）**：`--activity-summary-scan`（9d464f3）
  ——二级活动摘要位图镜像 activeWords_（每处全局激活同址 OR 摘要 bit，扫描按
  摘要探针跳过静默 word，drain 自清，off 逐字节等价，含语义 harness 单测与文档）。
  414.867s（CV 0.0%，门全过，compile_s 693.3s，emu_build 339.3s 无膨胀）；
  2,076 探针 + 576,615 镜像站点。**机制量级不可裁**：同窗安慰剂 e00010
  （t1 tip 原样）574.637s 锚定本窗=慢态（与 e00006 同频慢态 564.8s +1.7% 一致），
  c1 同窗名义 -27.8%，但双态翻转（c1 抽快态/c2 抽慢态）可吸收全部分差；
  c1 读数低于快态带下沿 ~425s → 机制方向为正、量级 2%~28% 不可裁。
  t1/s03 首务 = 同态锚点（安慰剂或同批重测）把 c1 钉进单一态带。
- **安慰剂席位纪律再验证**：无 c2 时 c1 会被误记为 -6.5%（对 e00006 ledger
  快窗）或 -26.6%（对同频慢态），两种误读均被 c2 的「本窗=慢态」锚定排除。
- evals 10/32；第 2 轮已齐平（t0 2/8、t1 2/8），下一 action = 第 2 轮 round-summary。

## r002 第 2 轮跨轨迹小结（2026-08-21，action A0040）

- run best 曲线 = y0 619.019（慢态污染）-> r1 362.869 -> r2 **261.543s**
  （e00007，t0/main）；vs 基线/gsim 全部 ratio 维持不可裁（基线重锚待用户
  裁决）。evals 10/32，两轨迹各 2/8。
- **recon 驱动收敛为 r002 标准前置**：两轨迹本轮候选均出自自有
  `--runtime-profile` 插桩画像；两 recon 独立互证 rounds 恒定 2.00/eval
  （clock prev 检测器自更新驱动 round 2）、commit 相 ~30%、43 个每 eval
  触发的 commit 巨块独占 ~30% 块周期。「消 round」类机制上界 ≈ 扫描余量
  （round-2 动态面 ~11.6%），两轨迹均不候选。
- **r001 两大机制族在新输入图各获首个一阶量级候选**：t0 commit 宽站 detect
  memcmp/memcpy 快速路径（e00007，名义 -27.9%，同窗逻辑控制排除双态抽签，
  机制确认；观测超 ≥8% 先验，溢出待同 tip 重测锚定）；t1 二级活动摘要扫描
  （e00009，对同窗安慰剂名义 -27.8%，但双态翻转可吸收——方向为正、量级
  2%~28% 不可裁，机械 winner 入 t1/main，t1/s03 首务同态锚定）。
- **守卫池布局路线关闭**：e00008 守卫 enable 聚簇（6,574 变量实证命中）
  亚分辨持平——9.2% 守卫池 per-atom ~50cyc 非散射 miss 主导，残余嫌疑 =
  巨函数体 i-cache/分支前端；守卫池只剩事件槽整块门控与瘦身两路。
- **同窗对照是双态环境下的唯一裁决器**：批内 CV≈0 无整批污染检出能力；
  逻辑控制（c1/c2 同窗差远超机制池占比即排除机器态）与安慰剂锚定本轮各
  验证一次。计时窗 freq trace 只读采样（A0038 落地）继续作为标配。

## r002/t0/s03 守卫 run 门控证伪与 e00007 归因 overturn（2026-08-21，action A0041）

- **e00007 归因 overturn（三重证据）**：recon-t0s03（t0 tip + 10 旋钮插桩，
  金标过）块 tick 703.7G 与 e00003 等价物 696.3G 持平（b93159 412k cyc/exec
  不变、插桩 Host 395.5 vs 391.6s）；同窗安慰剂 e00012 回读 **363.444s =
  261.543×1.389 精确落双态带**。`wide-detect-fast-path` 机制亚分辨中性：
  宽站 detect 成本由数据侧 miss 主导（~49 TSC tick/atom），省指令无效。
  **t0 tip 真值 ≈363s（常态窗）**；ledger best 261.543s 为快态抽签读数，
  此后不作比较基准。教训：双态 ×1.39 是对整个运行时的乘子，可完美伪装成
  大机制收益；A0038 式「池大小」逻辑控制对此型混杂无效；>15% 名义单步
  收益必须同窗锚点 corroborate。
- **证伪（e00011）**：`--guard-run-event-gating`（723c94e，run 级推广 r001
  f45f75d；engagement runs=5 atoms=9007，命中 b90656/90657）370.498s，
  同窗较安慰剂 **+1.94%**——守卫块激活与门开 round 重合（每 eval ~1 次
  exec），无空闲重估可跳。**守卫池门控轴（整块/run 级）关闭**；残余解释 =
  必要激活轮内 i-cache 流式，只剩 atom 代码瘦身一路。commit 相「省指令」轴
  同步关闭（fast path 中性 + miss 主导互证）。
- **新图守卫块结构事实**：b90656/90657 混合 Pending 模式 sd_read DPI
  （pendingHostEvents_ 锁存跨 eval）+ 检测器 + act.b 激活，整块门控永不合格；
  `changedResults_[0]` = clock posedge 检测结果。commit b93131 族（28×~12k
  atom）= 动态索引位 RMW 阵列（每 atom 重算 index_words），与 b93159 静态
  窄站阵列（共享单 enable）结构不同。
- **构建墙钟双态分裂观察**：e00011 emu_build 341.9s vs e00012 1512.7s（近同
  体量 4.4x），与 A0038（1513s）/A0039（340s）分裂一致；compile_s 余量评估
  取保守侧。evals 12/32；下一 action 按轮转为 t1/s03。

## r002/t1/s03 task 体 outline 确认与同态锚定（2026-08-21，action A0042）

- **确认（e00013，winner，已入 t1/main）**：`--task-body-outline`（b9a888c）
  ——无参 fwrite 冷体坍缩为共享 `task_write_const` helper（5,937 站）、DPI
  String 输入免 per-site `std::string` 拷贝（6,412→0），off 逐字节等价，
  含 host 变体单测与文档。Host 中位 **375.670s**（CV 0.07%，17/17 ctest、
  3 rep difftest 全过 73580/49996，compile_s 702.1s），对同窗安慰剂 e00014
  （421.673s，CV 0.0%）**同态 -10.91%** 确认，越 5% 假设门；双态 ×1.3-1.4
  方向相反无法吸收。静态实证：b116236 所在 TU .o text **3.56MB→0.89MB
  （-75%，4.0x）**，全模型 blocks text 仅 -2.6%——收益集中在单块，与池分布
  一致。机制 = A0041 关闭守卫门控轴后预言的「atom 代码瘦身」在 t1 内嵌守卫
  池（b116236 持全模型 87.8% TaskFormatter 站）上的确认。fwrite outline 与
  DPI 免拷贝同旋钮未分离归因。
- **安慰剂锚定达成 s03 首务**：e00014 把 t1 tip 钉进快态带
  **414.867/421.673s 双样本**；e00009（activity-summary-scan）量级维持
  不可裁（s02 窗态翻转可吸收其名义 -27.8%），其地位由 e00013 同窗对照
  间接巩固（c1 读数低于全部 tip 快态读数）。t1 后续裁决只信同窗锚点。
- t1 best 375.670s（vs 基线 ratio 仍因基线慢态污染不可裁）；evals 14/32；
  t1 emit_args 链追加 task-body-outline。t0/t1 各 3/8 齐平，下一 action =
  第 3 轮 round-summary。

## r002 第 3 轮 round-summary（2026-08-21，action A0043）

- **ledger best 本身可以是抽签读数**：e00007（261.543s）经 recon tick 持平 +
  插桩 Host 持平 + 同窗安慰剂回读 363.444s（= 261.543×1.389 精确落带）三重
  证据 overturn——双态 ×1.39 是对整个运行时的乘子，可完美伪装成大机制收益，
  「池大小」式逻辑控制对此型混杂无效。**>15% 名义单步收益默认存疑，必须同窗
  锚点 corroborate**；ledger 跨窗读数不参与裁决。
- **同窗安慰剂/锚点席位常态化**：本轮 4 候选中 2 席为安慰剂，且正是这两席
  产出本轮最重要的两个裁决（e00007 overturn、t1 tip 快态带双样本锚定
  414.867/421.673s）。r002 已三次靠同窗锚点避免误归因，双态环境下应作为
  每 step 固定席位。
- **守卫池机制轴收敛为单轴**：t0 证伪整块/run 级门控（激活与门开 round 重合，
  无空闲重估可跳）后，t1 确认其预言的残余路线——atom 代码瘦身
  （task-body-outline 同态 -10.91%，b116236 TU text -75%）。守卫池形态互补：
  整块守卫（t0 b90656/90657）门控关闭、瘦身未试；内嵌 task atom（t1 b116236）
  门控不可用、瘦身确认。
- **r002 已关闭轴清单**：常量/状态瘦身族（round 1）、守卫布局聚簇（round 2）、
  守卫池门控与 commit 相省指令类（round 3）。候选空间向 compute 相（67% tick
  未触探）与数据侧机制集中。
- **e00009（activity-summary-scan）量级永久不可裁**：s02 窗态翻转可吸收其名义
  -27.8%，接受为「方向为正、量级未知」的携带旋钮，不再补裁决。
- 真值口径：t0 tip ≈363s（常态窗锚定）、t1 tip 375.670s（快态窗，同态
  -10.91% 确认）；跨轨迹绝对比分无意义。evals 14/32。

## r002/t0/s04 sys-task-body-outline 同窗确认 -5.91%（2026-08-21，action A0044）

- **确认（e00015，winner，已入 t0/main）**：`--sys-task-body-outline`（e43ff4d，
  默认 off 逐字节等价，含 emitter 单测与文档）——全部 7,235 个非 final fwrite 站的
  TaskFormatter 构造/append/ostream 输出抽为 noinline 成员函数，块内热路径只剩
  preamble + fire 求值 + 窄标量实参物化 + 调用。Host 中位 **339.654s**（CV 0.0%，
  17/17 ctest、3 rep difftest 全过，compile_s 974.1s），同窗安慰剂 e00016
  （t0 tip 原样）**361.053s** 锚定本窗=常态（与 e00012 的 363.444s 跨窗 -0.66%
  一致）→ **同态 -5.91%**，越 4% 假设门，双态 ×1.39 方向/量级均无法吸收。
- **静态实证**：TaskFormatter 内联站 7,235→0；b90656/90657 所在 TU .o text
  -50.3%/-47.7%；全模型 blocks .o text 96.34MB→88.74MB（-7.9%）；emu_build
  1520.5s→621.6s（构建墙钟双态分裂前例在，量级不归因）。机制 = A0041 关闭守卫
  门控轴后预言的「atom 代码瘦身」在 t0 整块守卫池（b90656/90657，9.3%）上的确认；
  收益约为池占比的六成 → outline 收掉的是前端流式部分，残余为 fire 求值与真实
  触发的 task 体。与 t1 task-body-outline 同族独立实现（t0 证据链：recon-t0s02/
  s03 + A0041，命名该路径在先）。
- **离线四分画像（recon-t0s03 解析，t0 后续候选的池地图）**：commit 32.8% /
  守卫 task 12.5%（纯 task 守卫 9.3%）/ 纯宽数组 array 块 4.35%（成本集中于
  b69159/69157/69158 的 22528-bit mux/broadcast 流扫）/ 窄标量 compute 长尾
  50.4%（b93085/b83835 实为比较归约树块非 task 块）。assign_words 宽拷贝覆盖
  9.5% 块周期但多为 1-8 word 窄拷贝，非主要矛盾。
- 真值口径更新：**t0 tip ≈339.7s（常态窗）**；t0 有效 emit_args = 10 旋钮 +
  sys-task-body-outline。evals 16/32；下一 action 按轮转为 t1/s04。

## r002/t1/s04 gsim-aligned 调度点迁移同窗确认 -8.44%（2026-08-21，action A0045）

- **确认（e00017，winner，已入 t1/main）**：调度点单变量——摘除 config 调度点
  全参数回落 CLI 默认 gsim-aligned 点（15 atoms/block、dpCoarsen 7000/0、
  mergeWhen off），t1 旋钮链（resize-elision/inline-scalar-helpers/
  inline-scalar-constants/activity-summary-scan/task-body-outline）不变
  （--allow-empty 旋钮类 commit 520b017）。Host 中位 **368.963s**（CV 0.0%，
  17/17 ctest、3 rep difftest 全过，compile_s ~700s），同窗安慰剂 e00018
  （t1 tip 原样 + e00013 全参数）**402.978s** → **-8.44%**，越 6% 假设门。
  静态实证：blocks .o text 94.0MB vs 98.2MB（-4.3%），源 811MB vs 840MB。
- **调度点一阶效应跨轨迹收敛**：t0 单变量 -16.4%（A0035）× t1 携带图 -8.44%
  互证，调度/块组织轴是 r002 新输入图最稳定一阶变量；两轨迹自此同调度点基。
  t1 5 旋钮与调度点正交性高于 t0 9 旋钮链（后者多为适配胶族被调度吸收）。
- **t1 有效 emit_args = CLI 默认调度点 + 5 旋钮**（不传调度参数）；t1 tip 真值
  口径 ≈369s（本窗）。vs 基线 ratio 仍不可裁。
- evals 18/32；t0/t1 各 4/8 齐平，下一 action = 第 4 轮 round-summary。
  t1 后续：旧 recon 基于 config 调度点已变形，建议新 recon 重画像后再触
  compute 相残余缺口与 commit 相 b119387 数据侧。

## r002 第 4 轮 round-summary（2026-08-21，action A0046）

- **守卫池瘦身路线跨轨迹闭环**：t0 sys-task-body-outline（整块守卫 b90656/90657，
  TU text -50%，同态 -5.91%）与 t1 task-body-outline（内嵌 task atom 块 b116236，
  TU text -75%，同态 -10.91%）是同族机制在两种守卫形态上的独立确认——A0041 关闭
  门控轴后预言的「atom 代码瘦身」在两侧形态全部落袋。收益约为池占比的六成：
  outline 收掉的是前端流式部分，残余 = fire 求值与真实触发的 task 体。守卫池轴
  开放部分兑现完毕，关闭。
- **调度点一阶效应跨轨迹互证**：t0 单变量 -16.4%（A0035）× t1 携带图 -8.44%
  （e00017 vs 安慰剂 e00018）——调度/块组织轴是 r002 新输入图最稳定一阶变量。
  两轨迹自此同调度点基（gsim-aligned CLI 默认）；t1 有效 emit_args = CLI 默认
  调度点 + 5 旋钮。调度点轴收益落袋后关闭（再动属重新抽签）。
- **安慰剂锚点连续两轮 2/4 席、产出全部裁决基准**：本轮 e00016/e00018 是两
  winner 确认的唯一可靠基准；跨窗读数不参与裁决已是硬纪律。
- **真值口径**：t0 tip ≈339.7s（常态窗，较上轮 363.4s 实质 -6.5%）、t1 tip
  ≈369.0s（本窗）。ledger 名义 best 261.543s 维持抽签读数地位、不作基准。
  evals 18/32，行程过半；vs 基线 ratio 仍全部不可裁（基线重锚待用户裁决）。
- **候选空间分化但同向**：t0 下一阶池 = 窄标量 compute 长尾 50.4%
  （b93085/b83835 比较归约树块）+ commit 相 32.8%；t1 = compute 残余缺口 +
  commit 相 b119387（寄存器堆写口阵列 29%）。两侧省指令轴均已关闭，共同开放
  方向 = 数据侧机制与 compute 相本体；两轨迹均需先跑新 recon 再设计候选
  （t0 recon-t0s04 刷新 outline 后池地图；t1 旧 recon 基于 config 调度点已变形）。

## r002/t0/s05 wide-mux-chain-fuse 同窗 -2.19%（2026-08-21，action A0047）

- **方向确认、量级未越门（e00019，winner，已入 t0/main）**：`--wide-mux-chain-fuse`
  （61b5fd6，默认 off 逐字节等价，emitter 侧计划 + 单测 + 文档）——broadcast(64 位
  源)→mux(elemWidth==64) 跨 atom 严格相邻链融合为单 pass
  `array_mux_bcast_chain64_words`，基座单用 broadcast 折叠、中间 352-word 数组全部
  不物化。Host 中位 **335.129s**（CV 0.0%，17/17 ctest、3 rep difftest 全过，
  compile_s 979.8s），同窗安慰剂 e00020 **342.632s** → **-2.19%**（假设门 ≥3%、
  证伪线 <1.5%，落中间带）。engagement chains=156 levels=247 blocks=74；22528 宽
  链全融合（bcast 106→3、mux 117→18）；.o 总字节持平——纯访存流收益。捕获率约
  池的 46%（池 4.74%），未越门嫌疑：融合后每 word 仍逐层重放选择（~70-90 ALU
  ops/word），中间数组区原本 L2 驻留。待 recon-t0s05 验证 b69159 族残余 cyc/exec。
- **测量学新证据：同代码跨窗漂移 ±5% 级**——e43ff4d 原样三读数 339.654（s04 c1
  窗）/361.053（s04 安慰剂同窗）/342.632（s05 安慰剂窗）：双态 ×1.39 之外存在
  连续漂移分量。同窗锚点是唯一裁决基准的纪律进一步巩固；t0 tip 真值口径改为
  「本窗锚点 342.632s、tip 本窗 335.129s」，跨窗历史读数仅作参照。
- **recon 操作教训**：插桩单跑需同时设 `EMU_RUNTIME_PROFILE=1`（difftest emu.cpp
  读取，启用 profile）与 `EMU_AM_BLOCK_EXECS=<path>`（生成代码读取，落盘
  block_execs）；缺前者则插桩编译进二进制但不计数。
- **recon-t0s04（outline 后池地图）**：总 tick 703.7G→655.1G（-6.9%）；守卫池
  65.3G/9.28%→38.3G/5.84%（outline 插桩侧独立确认，-41%）；commit 33.8%（b93159
  40.5G 居首）/ compute 长尾 52.8% / 守卫残余 5.84%；b69159 族 15.4G 持平。
- t0 有效 emit_args = 11 旋钮 + `--wide-mux-chain-fuse`（+sys-task-body-outline
  等全链须显式携带）。evals 20/32；下一 action 按轮转为 t1/s05。

## r002/t1/s05 commit 写点无分支化证伪与新调度点池地图（2026-08-21，action A0048）

- **证伪（e00021）**：`--commit-write-branchless`（01078eb，ST00013 写点检测
  内层分支改条件移动 + flag OR 累积，off 259 文件 cmp 全等，含单测与文档）
  365.427s，同窗安慰剂 e00022（t1 tip 520b017 原样 + 5 旋钮）**359.269s**
  → **+1.71% 回退**。静态形态确切成立（`if (wrNext_` 141,169→0，b93159
  chunk 反汇编由 mov+and+cmp+jne 跳远冷路径变为 movdqu+pand SSE 向量化
  直线码）但运行时为负：**内层分支误预测不是 b93159 族主导成本**，恒写使
  未变更槽 cache line 无条件 dirty（commit 相每 eval ~1.4MB 目的流写回流量
  增加）。**commit 写点检测分支结构轴关闭**；与 t0 A0041「数据侧 miss 主导、
  省指令无效」互证并外推到窄站写口阵列——commit 相省指令/分支结构类整体
  关闭，残余开放方向只剩纯数据侧（且受 194MB 流扫带宽约束）。
- **recon-t1s05（CLI 默认调度点首池地图，插桩 Host 399.554s，金标过）**：
  总 702.1G tick；rounds 恒定 2.00/eval 第三次互证。commit 31.8%（43 个
  per-eval commit 块 31.1%；b93159 5.47%、383k cyc/exec ≈ 45cyc/atom，源/目
  变量连续声明 = unit-stride 流）/ compute 68.2%（守卫整块残余 3.75%、
  b93085 2.0%、b83835 1.3%、b69159 族 2.25%、长尾 52.4%）。**compute 相
  墙钟/tick 缺口 ~104s（墙钟 303.9s vs tick 折时 199.4s，26%）= t1 最大
  无名池**（扫描/激活簿记/调派胶，activity-summary-scan 携带下仍存）——
  需归因 recon 分解后再候选，不宜盲试。
- **测量学**：同代码跨窗漂移样本 +1（520b017+5 旋钮：s04 窗 368.963s vs
  s05 窗 359.269s，-2.6%）；本窗为 t1 最快窗口。t1 tip 真值口径 = 本窗
  锚点 **359.269s**（e00022）。
- t1 tip = `f167ae7`（内容 = 520b017），t1 有效 emit_args = CLI 默认调度点
  + 5 旋钮（commit-write-branchless 不携带）。evals 22/32；t0/t1 各 5/8
  齐平，下一 action = 第 5 轮 round-summary。

## r002 第 5 轮 round-summary（2026-08-21，action A0049）

- **commit 相「省指令/分支结构」类跨轨迹整体关闭**：t1 commit-write-branchless
  静态形态确切成立（分支消除 + SSE 向量化、`if (wrNext_` 141,169→0）却同窗
  +1.71% 回退——误预测非 b93159 族主导成本，恒写使未变更槽 cache line 无条件
  dirty（commit 相每 eval ~1.4MB 目的流写回流量增加）。与 t0 A0041 宽站 detect
  「数据侧 miss 主导」互证并外推到窄站写口阵列；commit 相残余开放方向只剩纯
  数据侧（布局/预取类），且受 194MB 流扫带宽约束（预取移动 miss 不消除流量）。
- **宽数组流扫族在 r002 兑现第一份运行时收益**：t0 wide-mux-chain-fuse 同窗
  -2.19%（中间带，捕获池 ~46%），纯访存流收益（.o 持平）。t1 未携带该机制
  （池 2.25%），是跨轨迹机制迁移的下一个自然试验点。
- **测量学：同代码跨窗漂移升格为 ±5% 级连续分量**（e43ff4d 原样三读数
  339.654/361.053/342.632s，超出双态 ×1.39 框架）——机器态含连续漂移，
  纪律从「双态对冲」升级为「任意跨窗读数一律不裁，含相邻窗口」；锚点席位
  连续第三轮 2/4 并产出全部裁决基准。
- **t1 发现全 run 最大无名池**：compute 相墙钟/tick 缺口 ~104s（26%，扫描骨架
  + 激活簿记 + 调派胶，activity-summary-scan 携带下仍存）——下一阶必须先归因
  recon 再设计机制，不宜盲候选。
- **真值口径**：t0 tip 本窗 335.129s（锚 342.632s）、t1 tip 本窗 359.269s；
  vs 基线 ratio 仍不可裁。evals 22/32（余 10 vs 剩余 12 席，末段或需单候选）。

## r002/t0/s06 commit-row-merge 证伪与 fuse 后池地图（2026-08-21，action A0050）

- **证伪（e00023）**：`--commit-row-merge`（96429a6，commit Block 严格相邻同
  key（内存目标/动态地址/行内 word）MemoryWrite(Cond)Mask run ≥3 融合为单次
  index+单 load+单 store，off 260 文件 cmp 全等，oracle 等价单测）338.247s，
  同窗安慰剂 e00024（t0 tip 61b5fd6 原样 + 12 旋钮）**327.602s** → **+3.25%
  回退**。engagement runs=120/events=3084/blocks=35（b93131 族 1702 站点全
  并入）。归因：融合以单一 `cur` 串行链替换 N 个可流水的独立 STLF 行往返，
  关键路径变长 + `any` 条件 store 新分支。**commit 相「省往返/省指令」类连续
  两次静态成立动态为负（t1 A0048 +1.71% × t0 本步 +3.25%），行合并/流量合并
  类并入关闭清单**；b93131 族 15.8G（2.47%）标记行合并不可触。
- **recon-t0s05（fuse 后池地图，插桩 Host 363.735s，金标过）**：总 655.1G→
  640.7G（-2.20%，与 e00019 同窗 -2.19% 精确互证）。**b69159 族残余崩塌：
  153k→24k / 77k→12k / 78k→14k cyc/exec，族 15.4G→2.5G，按 A0047 判据链轴
  关闭**。compute 65.4% / commit 34.6%。**t0 侧首次定量 dispatch 骨架无名池：
  compute 墙钟 269.3s vs 块 tick 折时 174.5s ≈ 95s/26%**（与 t1 ~104s 同族，
  激活簿记 3.7G 次/eval 首要嫌疑，需归因 recon 后再候选）。
- **测量学**：安慰剂 327.602s = t0 历史最快（快窗）；同代码跨窗漂移样本 +1
  （61b5fd6：335.129→327.602，-2.2%）。t0 tip 真值口径 = 本窗锚点 **327.602s**
  （e00024）。t0 tip = ab20b29（内容 = 61b5fd6），t0 有效 emit_args = 12 旋钮。
  evals 24/32（余 8 vs 剩余 10 席，末段需单候选 step）。
- 弃选记录：replicate-1bit→掩码 emit 规则被微基准证伪（clang -O2 已把 ≤54 级
  concat 链折叠为 test+cmove 5 指令），未占用评估预算。

## r002/t1/s06 wide-mux-chain-fuse 跨轨迹迁移同窗 -1.17% 确认（2026-08-21，action A0051）

- **确认（e00025，winner，已入 t1/main）**：t0 A0047 机制（61b5fd6）cherry-pick
  迁移到 t1 链（`4471846`，9 处冲突手工解决、剔除 t0 独有 wideDetectFastPath/
  sysTaskBodyOutline 伴生代码，解后 diff 与原 patch 精确同形 +854/-4）。Host
  中位 **364.464s**（CV 0.0%，17/17 ctest、3 rep difftest 全过，compile_s
  686.7s），同窗安慰剂 e00026（t1 tip 原样 + 5 旋钮）**368.763s** → **-1.17%**，
  越 1.0% 假设门（池 2.25% × t0 捕获率 ~46% 外推 ≈1.0%，量级精确命中）。
  engagement 与 t0 逐数一致（chains=156/levels=247/blocks=74），emit 源总量
  持平（-2.2KB）——纯访存流收益形态复现。
- **首个可定量跨轨迹迁移的机制族**：宽链融合收益/池比两轨迹一致（~46% 捕获
  率），效应量可按池占比外推；b69159 族链轴在 t1 侧同步关闭（残余为 ALU 重放
  非访存）。与 commit 相省指令类连续证伪对照，进一步印证「数据侧流量消除有效、
  省指令/分支结构无效」判据。
- **测量学**：同代码跨窗漂移样本 +1（t1 tip：s05 窗 359.269s → s06 窗
  368.763s，+2.6%，方向反转）——±5% 级连续漂移第五样本点。t1 tip 真值口径 =
  本窗锚点 **368.763s**（e00026）、含 fuse tip 本窗 **364.464s**（e00025）。
- t1 tip = `4471846`，t1 有效 emit_args = CLI 默认调度点 + 5 旋钮 +
  `--wide-mux-chain-fuse`。evals 26/32（余 6 vs 剩余 10 席，末段单候选定局）；
  下一 action 按轮转为第 6 轮 round-summary。

## r002 第 6 轮 round-summary（2026-08-21，action A0052）

- **宽链融合 = r002 首个可定量跨轨迹迁移机制族**：t0 -2.19%（池 4.74%）× t1
  -1.17%（池 2.25%），收益/池比两轨迹一致（~46% 捕获率），外推量级精确命中；
  engagement 逐数一致、emit 源持平（纯访存流形态复现）。b69159 族链轴两轨迹
  同步关闭。
- **commit 相「省指令/省往返」类跨轨迹三次证伪、整体关闭**：t0 commit-row-merge
  静态确切成立（off 260 文件 cmp 全等 + oracle 等价）却 +3.25% × t1
  commit-write-branchless +1.71% × t0 宽站 detect 内联 +2.80% 互证——commit 相
  残余成本是 194MB 状态对象的数据侧 miss/带宽本体，省指令/分支结构/行合并三类
  全部入关闭清单；只剩纯数据侧布局方向且受流扫带宽约束。
- **两轨迹下一阶开放池同向：dispatch 骨架无名池**（t0 ~95s/26% × t1 ~104s/26%，
  compute 墙钟 vs 块 tick 折时缺口，激活簿记 3.7G 次/eval 首要嫌疑）——全 run
  最大单池，纪律 = 先归因 recon 分解（扫描骨架/激活簿记/调派胶）再设计机制。
- **测量学**：锚点席位连续第四轮 2/4；同代码跨窗漂移样本累计五点（t0 tip
  -2.2%/-4.4% 快向、t1 tip -2.6%/+2.6% 双向）。t0 真值口径 = 本窗锚点
  **327.602s**（e00024，快窗、t0 历史最快——跨窗误读为新 best 的反例）；
  t1 含 fuse tip 本窗 **364.464s**（e00025，锚 368.763s）。
- **末段座位裁决**：evals 26/32（余 6 vs 8 席缺口 2）——s07 两轨迹保持机制+
  锚点 2 候选（用 4）；s08 只余 2 evals = 一条轨迹的完整 step，归属由 s07 收口
  时按 recon/池证据裁定，另一轨迹 s08 无评估空转。锚点席位四轮证据确立，不砍。
- **待用户**：基线重锚仍悬置（A0036 起）；run-summary 的 vs 基线 ratio 将以
  「不可裁」表述，除非追加预算重锚。

## r002/t0/s07 scan-branch-hints 同窗确认 -11.41%（2026-08-21，action A0053）

- **确认（e00027，winner，已入 t0/main）**：`--scan-branch-hints`（b9a671a，
  默认 off 逐字节等价，emitter 单测 + 文档）——compute/commit 扫描函数每 byte
  序言测试与逐块活动位测试加 `__builtin_expect(..., 0)`，clang 块重排把冷块体
  移出 fall-through 检查链。Host 中位 **301.081s**（CV 0.0%，17/17 ctest、
  3 rep difftest 全过，compile_s 980.1s），同窗安慰剂 e00028（t0 tip 原样 +
  12 旋钮）**339.849s** → **-11.41%**，越 4% 假设门近 3 倍；c1 读数低于 t0
  全部历史读数（含快窗 327.602s），双态/漂移无法吸收。**r002 单步最大确认收益**。
- **dispatch 骨架无名池归因落槌（recon-t0s06，perf 32k 样本 @ 生产 emu）**：
  eval_scan_* 自时间 50.38% / block_chunk 28.57% / helper 18.28% /
  eval_commit 0.94% / **eval() 自身 ≈0%**。激活簿记在块 rdtsc 窗内、
  has_active_blocks 范围检查可忽略——无名池 = **eval_scan_* 内跳过链**（扣块体
  ≈75-80s = Host 22-24%，rdtsc 侧 70-75s 互证），病因 = 每块位测试与 ~945B
  块体交错的大步长取指流（反汇编 `test;je +0x4a9` 佐证 ~14cyc/站）。
- **捕获 ~50%**：-11.41% = 38.77s ≈ 池 75-80s 的一半（紧凑链消远跳取指主项，
  残余 = 活跃 byte 冷区位测试 + 块体本体）。「数据侧/前端流式主导、省指令无效」
  判据的正向逆用例证：不省指令（.o text -0.15% 持平）、只改取指流形态即赢。
- **静态实证**：off 260 文件 cmp 全等；提示总数 105,479（runtime.cpp 零）；
  objdump 确认 fall-through ~13B/站紧凑链 + 冷区分层外置；构建墙钟中性
  （emu_build 624.1 vs 624.2s）。
- **测量学**：跨窗漂移样本 +1（t0 tip：327.602→339.849s，+3.7% 慢向，第六
  样本点）；锚点席位连续第五轮产出唯一裁决基准。t0 tip = `b9a671a`，t0 有效
  emit_args = 12 旋钮 + `--scan-branch-hints`；真值口径 = 本窗锚点 339.849s、
  含 hints tip 本窗 301.081s。evals 28/32（余 4）；下一 action 按轮转为
  t1/s07，scan-branch-hints 跨轨迹迁移（t1 骨架池 ~104s × ~50% ≈ 5-7% 外推）
  为自然首选；s08 归属由 t1/s07 收口裁定。

## r002/t1/s07 scan-branch-hints 跨轨迹迁移同窗确认 -5.69%（2026-08-21，action A0054）

- **确认（e00029，winner，已入 t1/main）**：t0 A0053 机制（b9a671a）cherry-pick
  迁移到 t1 链（`74b6d1e`，2 处冲突手工解决、剔除 t0 独有 sysTaskOutline 伴生
  代码，解后 diff 与原 patch 同形 +261/-19）。Host 中位 **322.762s**（CV 0.0%，
  17/17 ctest、3 rep difftest 全过，compile_s 690.4s），同窗安慰剂 e00030
  （t1 tip 原样 + 6 旋钮）**342.230s** → **-5.69%**，越 4% 假设门、落 5-7%
  外推区间。静态：提示 105,485 处（t0 105,479 逐数互证扫描链同构），runtime.cpp
  零。捕获 ~23%（t1 池被 activity-summary-scan 预压，较 t0 ~50% 薄）。
- **跨轨迹迁移二连中**：宽链融合（池比外推）× scan-branch-hints（捕获率外推
  区间命中）——「数据侧/前端流式主导、省指令无效」判据正向逆用第二次成立；
  dispatch 骨架跳过链亚池两轨迹各兑现约半，骨架轴接近关闭，s08 开放方向回到
  compute 长尾本体与 commit 相纯数据侧（布局/预取，受 194MB 流扫带宽约束）。
- **测量学**：同代码跨窗漂移样本 +1（第七点：t1 tip `4471846` 原样 s06 窗
  364.464s → s07 窗 342.230s，-6.1% 快向，本窗为 t1 历史最快窗）。t1 真值
  口径 = 本窗锚点 **342.230s**（e00030）、含 hints tip 本窗 **322.762s**
  （e00029，t1 全部历史最低读数）。
- t1 tip = `74b6d1e`，t1 有效 emit_args = CLI 默认调度点 + 5 旋钮 +
  `--wide-mux-chain-fuse` + `--scan-branch-hints`。evals 30/32（余 2 = 恰好
  一条轨迹的完整 s08：机制 + 锚点）；t0/t1 各 7/8 齐平，下一 action = 第 7 轮
  round-summary，由它裁定 s08 归属。

## r002 第 7 轮 round-summary（2026-08-21，action A0055）

- **dispatch 骨架跳过链亚池两轨迹同步兑现约半，骨架轴接近关闭**：t0
  scan-branch-hints 同窗 -11.41%（捕获 ≈ 池 75-80s 的 ~50%）× t1 迁移同窗
  -5.69%（捕获 ~23%，t1 池被 activity-summary-scan 预压故更薄）——同一病因
  （位测试/~945B 块体交错的大步长取指流）、同一机制（`__builtin_expect(...,0)`
  冷块外置纯布局注解），跨轨迹量级 = 池厚度 × 捕获率可外推。残余骨架（活跃
  byte 冷区位测试 + 块体本体 + 激活簿记 + 调派胶）进一步压缩需 hinted 二进制
  新 perf recon 定量后再候选，不宜盲试。
- **跨轨迹迁移二连中**：宽链融合（收益/池比 ~46% 双侧一致）× scan-branch-hints
  （捕获率外推区间命中）——r002 两个可定量迁移机制族均为「不省指令、改数据/
  取指流形态」类。迁移方法论：cherry-pick + 剔除源轨迹独有伴生代码 + 同窗
  锚点裁决 + engagement/提示数逐数互证（本轮 105,479 × 105,485）。
- **「数据侧/前端流式主导、省指令无效」判据正向逆用第二次成立**：
  scan-branch-hints 不省一条指令（.o text -0.15% 持平）即拿下 r002 单步最大
  确认收益（-11.41%）；该判据目前是 run 内预测力最强的机制筛选器。
- **残余开放池两轨迹同向归拢**：compute 相长尾本体（t0 52.8% × t1 52.4%）与
  commit 相纯数据侧（布局/预取，受 194MB 流扫带宽约束）；骨架/守卫/调度点/
  链融合各轴均已兑现或关闭。
- **测量学**：锚点席位连续第六轮 2/4；跨窗漂移样本累计七点且本轮双窗反向
  （t0 +3.7% 慢向 × t1 -6.1% 快向）——漂移无方向偏好、±6% 级，「任何跨窗
  读数一律不裁」纪律无可替代。真值口径：t0 tip 本窗 **301.081s**（e00027，
  锚 339.849s）、t1 tip 本窗 **322.762s**（e00029，锚 342.230s），均为各自
  全部历史最低读数。
- **s08 归属裁定（A0052 提请）**：余 2 evals = 一条轨迹完整 step，**给 t1**——
  t1 池地图最陈旧（recon-t1s05 早于 fuse+hints 两个已落机制，run-summary
  restart 建议需刷新证据）+ t1 compute 长尾 ≈169s 为全 run 最大残余池 +
  绝对水位落后头空间大；纪律 = recon-t1s07（hinted 生产 emu perf）先行、机制
  候选 + 锚点。t0/s08 无评估空转（预算约束，非机制结论）。evals 30/32。
- **待用户**：基线重锚仍悬置（A0036 起）；run-summary 的 vs 基线 ratio 将以
  「不可裁」表述，除非追加预算重锚。
