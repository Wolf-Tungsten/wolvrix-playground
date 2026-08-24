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

## r002/t0/s08 MemoryFill 使能门控证伪与批内双态首次直接检出（2026-08-21，action A0056）

- **测量学突破：双态 = per-process 抽签，批内可直接检出**。e00032 安慰剂并行首批
  3 rep（同批起跑、绑核 12/13/14）= 295.042/389.234/295.038s——同批混合快/慢态，
  证明双态非整窗翻转而与 A0036「THP/NUMA 页放置 per-process 运气」一致；此前批内
  CV≈0 只是三 rep 同态的运气。CV 12.35% 触发 5 rep 加测，混合 median（343.664s）
  是 artifact、不作裁决基准且会反转机械 winner（本步实例：finish-step 按记分板把
  证伪的 c1 快移入 t0/main，内容无害因旋钮默认 off 逐字节等价）。**协议升级提请：
  rep 级按快/慢簇分组裁决（簇内中位），弃用跨簇 median**。
- **证伪（e00031）**：`--memory-fill-enable-gate`（79719b2，off 逐字节等价实证、
  单测+文档）——mem.fill 折入 cond 门控逐元素 detect 扫描（engagement sites=191/
  elements=41748），321.922s（CV 0.0%）vs 同窗安慰剂快态簇 295.042s = **+9.1%
  回退**，假设（>=4% 降）任何读法下不成立。commit 相「条件门控省流量」首试即败，
  与 A0048/A0050 同向；commit 相开放方向进一步收窄至布局/预取（历届偏负）。
- **dispatch 骨架轴以直接证据关闭（recon-t0s07）**：hinted 生产 emu perf（27,921
  样本、Host 281.996s 快态窗、金标过）——eval_scan_* 自时间 46.61% 但 annotate
  热点全落在内联块体 ALU 上、跳过链 ~0%；helper 21.01%（slice_words_detect 5.49%
  居首）、块体外置 29.69%。eval_scan 高自时间 ≠ 骨架残余，其后解读一律先
  annotate 分类。
- t0 tip 真值口径 = 快态锚 **295.042s**（e00032 rep1/3，t0 历史最快）；t0 走完
  8/8，best 仍 e00007（抽签读数地位）。evals 32/32（含基线口径；候选 30/32，
  余 2 = t1/s08）；下一 action = t1/s08（A0055 裁定，recon 先行）。

## r002/t1/s08 concat 插入内联跨轨迹迁移同窗确认 -6.26%（2026-08-21，action A0057）

- **确认（e00033，winner，已入 t1/main）**：`--concat-insert-inline`（旋钮类
  --allow-empty d153d13）——t0 链 r001 起携带的 splice 内联机制首次迁入 t1 链：
  单字退化 concat/replicate/window-chain splice 从 outlined insert_words 动态
  循环调用改内联单语句。Host 中位 **338.367s**（CV 0.91%，17/17 ctest、3 rep
  difftest 全过，compile_s 799.9s），同窗安慰剂 e00034（t1 tip 原样 + 7 旋钮）
  **361.025s** → **-6.26%**，越 4% 假设门（c1 最差 rep 对锚仍 -4.8%）。
  engagement：insert_words 静态站点 276,059→15,326（-94.4%，残余为跨 word/
  动态 lsb 站）；.o 总量 115.3→105.6MB（-8.4%）；emu_build 364.2s 无膨胀。
- **跨轨迹迁移三连中**：宽链融合 × scan-branch-hints × concat-insert-inline
  ——「不省指令、改数据/取指流形态」判据第三次正向逆用；t1 链与 t0 链在
  splice 内联轴对齐（t1 有效 emit_args = CLI 默认调度点 + 5 旋钮 + fuse +
  hints + concat-insert-inline，8 项）。
- **recon-t1s07（hinted 生产 emu perf，45,319 样本，慢态窗 457.710s，金标过）**：
  eval_scan_* 44.35% / block_chunk 29.12% / helper 23.88% / eval_commit 1.03%。
  **dispatch 骨架轴 t1 侧 annotate 直接证据关闭**（eval_scan 热点全在内联块体
  ALU，跳过链 ~0%，同 recon-t0s07）。**helper 首位易主 insert_words 11.61%**
  （≈53s 慢态窗，annotate 成本摊在动态 helper 全身）——本步 c1 的池证据；
  inline 后 slice_words_detect 3.61% 将升 helper 首位。
- **测量学**：跨窗漂移样本 +1（第八点：t1 锚 342.230→361.025s，+5.5% 慢向）；
  本窗两候选批内 CV≈0 无混杂。t1 真值口径 = 本窗锚点 **361.025s**（e00034）、
  含 inline tip 本窗 **338.367s**（e00033）。
- t1 走完 8/8；evals 候选口径 32/32 全部用完。r003 候选材料：残余 15,326 跨
  word splice 站的 `--concat-insert-unroll` 单变量复测（t1 未携带，r001 弱正
  未确认）。下一 action = 第 8 轮 round-summary → run-summary。

## r002 收口（2026-08-21，action A0058 run-summary）

- run 总账：C=2/L=8/K=2，16/16 步走满，候选 evals 32/32 恰好耗尽（总 34 含
  基线）；32 候选全 ok，零 compile_timeout/difftest_fail。真值 best：t0 tip
  **295.042s**（快态簇锚）/ 301.081s（e00027 同窗确认）；t1 **322.762s**
  （e00029）。对 gsim ≈6.3-6.4x，目标未达成；基线慢态污染（e00001/e00002）
  致 vs 基线 ratio 全 run 不可裁，重锚待用户。
- 机制族遗产（restart y0 材料）：scan-branch-hints（t0 -11.41% × t1 -5.69%）、
  task body outline 族（t1 -10.91% × t0 -5.91%）、gsim-aligned 调度点
  （-16.4% × -8.44%）、wide-mux-chain-fuse（-2.19% × -1.17%）、
  concat-insert-inline 迁移（-6.26%）。跨轨迹迁移三连中，捕获率 ~46% 双侧
  一致，可作 r003 外推先验。
- 关闭清单新增：commit 相省指令/省往返/门控类整体（branchless +1.71%、
  row-merge +3.25%、fill-enable-gate +9.1%，数据侧 miss 主导）；守卫门控
  （整块/run 级）；守卫布局；死宽态（新图池 0.46%）。残余开放池 = compute
  长尾本体 ~52%（双侧）+ commit 相纯数据侧。
- 测量学遗产：双态抽签批内直接检出先例（同批 rep 295.0/389.2/295.0s → 混合
  median 是 artifact，可反转机械 winner）；跨窗连续漂移 ±5%（八点样本）；
  跨窗读数一律不裁、同窗安慰剂锚点是唯一裁决基准（连续六轮 2/4 席）。
  提请用户待决：rep 级簇分组裁决入 evaluator；基线重锚。
- restart 建议：y0 = t0 tip `79719b2d95b91da141c01c74814da25292c1170d`；
  C/L/K 维持 2/8/2；config restart.max=1 已消耗，r003 需用户放宽。

## r003 restart 启动前准备（2026-08-21，尚未 init-run）

- 用户授权完成 r003 启动前准备，但明确要求本次不实际开始。边界实证：未调用
  `tesctl init-run`，无 `runs/r003/`、无 `tes/r003/*` 分支、无 base worktree，
  `state/run.json` 仍是 completed r002，`tesctl next` 仍为 `run-closed`。
- restart 配置已按 A0058 建议准备：`restart.max` 1→2，默认搜索 C/L/K 从 3/8/2
  调整为 **2/8/2（N=32）**；两轨分工保持「compute 长尾本体」与「迁移验证 +
  commit 数据侧」，K=2 的另一席继续作为同窗安慰剂锚点。
- r003 测量协议已在 run 外升级：固定 **5 rep**，沿用物理核 12/13/14 分 3+2
  两批；排序后最大相邻比值 >=1.12 且两侧各 >=2 rep 时识别快/慢双簇，score
  取快簇中位，同时记录 raw median/CV、断点与两簇明细。阈值 1.12 高于 r002
  连续漂移上界约 6%，且可检出 e00032 排序样本的 343664/295042 = 1.165 断点。
  e00032 离线回放：旧跨簇 median 343.664s → 快簇 [295.038, 295.042] 中位
  **295.040s**；singleton 异常值因最小簇 2 不会被误认成模式。纯离线单测覆盖
  双簇、单簇、singleton、最大断点与固定 5 rep 的 3+2 批控制流。
- 基线重锚不在准备阶段偷跑：下次真正执行 run-init action 时，用相同新协议重新测
  AM y0 与 gsim target，避免复用 r002 晨间慢态污染的 619.019/46.792s。
- 启动锚点预检：wolvrix commit 与 `tes/r002/t0/main` 均指向
  `79719b2d95b91da141c01c74814da25292c1170d`；post-stats 输入仍为
  `cbd78c0b127dfb3bbbb005d06594242846a9d1cf35944de0720d7cf3031b3246`；
  `reference/gsim` / `testcase/xiangshan` pin 可读，gsim emu 存在且可执行。
- 下一次获准实际开始时的唯一入口：`python3 tes/tools/tesctl.py init-run
  --run-id r003 --base-commit 79719b2d95b91da141c01c74814da25292c1170d --C 2 --L 8 --K 2`，
  随后在同一个 run-init action 内完成输入指纹回填、AM/gsim 双基线、记录与收口。

## r003 错误启动清理与 y0 勘误（2026-08-22，尚未 init-run）

- 上一节准备方案由用户撤销：错误 r003 启动现场已清理，`state/run.json` 恢复为
  completed r002；r003 manifest、ledger 条目、action、目标仓库分支/worktree 与
  错误双基线产物均不保留。
- 用户最终指定 r002 台账最低点 **e00007 = 261.543s** 为 r003 y0。完整解 = commit
  `ecb4c3f3c6b26cd0aed3491a1a9444959a4a73fb` + 10 个 emit 开关；该 commit 已从
  `9c0a89db` fast-forward 合入 `grh/tes-grhsim-am`。调度器要求 restart 使用
  run-qualified `--base-eval r002/e00007`，防止只继承 commit 而丢失参数表型。
- r003 固定 **C=2/L=8/K=2（N=32）**。K=2 两席均用于 Φ 所选节点邻域内的实质
  机制候选，不设安慰剂；每个候选须给出“来源节点 → TES 反馈/病灶 → 局部改动 →
  可证伪预期”的连续链，避免无依据跳跃。
- TES 外历史失败只作先验，不进入 rejected/failed 集合，也不直接关闭方向；旧实现
  不充分、输入变化或机制补足均可在 TES 内重新评估。
- 测量固定 **3 rep**，核 12/13/14 单批并行，不扩增到 5 rep。eval-id 改为任务级
  单调序列；r001/r002 最大编号 e00050，r003 双基线预留 e00051/e00052，候选从
  e00053 继续。
- 下一次启动入口：`python3 tes/tools/tesctl.py init-run --run-id r003
  --base-eval r002/e00007 --C 2 --L 8 --K 2`；随后在同一个 run-init action 内完成
  输入指纹、AM/gsim 双基线、记录与收口。

## r003 正式启动（2026-08-22，action A0059 run-init）

- r003 已从用户指定的完整解 `r002/e00007` 正式启动：commit
  `ecb4c3f3c6b26cd0aed3491a1a9444959a4a73fb` + 10 个 emit 开关；C=2/L=8/K=2，
  固定 3 rep，K 两席均为实质候选。输入图 SHA-256 仍为
  `cbd78c0b127dfb3bbbb005d06594242846a9d1cf35944de0720d7cf3031b3246`。
- AM e00051 = **363.995s**（363998/363995/363995ms，CV 0，17/17 ctest、3 rep
  difftest 73580/49996 全过）；gsim e00052 = **45.864s**
  （45866/45864/45863ms，CV 0，3 rep difftest 73584/49998 全过）。r003 起跑差距
  = **7.936x**。
- e00051 比历史 e00007 的 261.543s 慢 39.17%，但与 r002/e00012 的同解慢态锚
  363.444s 仅差 +0.15%。这不改变用户指定的 y0 解身份；它证明 261.543s 不可作为
  r003 的基线时间，后续收益必须相对 e00051 的冻结口径解释。
- eval-id 已按任务级序列接续：双基线 e00051/e00052，下一候选从 e00053 开始。
  下一 action = r003/t0/s01；必须等下一次 goal 执行，不在本 run-init action 偷跑。

## r003/t0/s01 scan 分支提示与 system-task 冷体 outline（2026-08-22，action A0060）

- **机械 winner（e00054，已入 t0/main）**：`--sys-task-body-outline`，commit
  `b1f2c8d`，Host 247.560s（CV=0），较 e00051 名义 -31.99%；17/17 ctest 与
  3 rep difftest 全过，compile_s 1067.7s。`--scan-branch-hints` e00053 同样全门
  通过，334.687s（CV=0），较 e00051 名义 -8.05%，compile_s 1978.0s。
- **因果量级保留**：c1/c2 = 1.352x，落在 r002 已检出的 per-process 快慢态
  1.3-1.4x 带内；两候选跨窗口，批内 CV=0 不能排除整批同态抽签。因此 ledger
  与 finish-step 的 c2 winner 有效，但 c2 的 -31.99% 不能全归因于 outline，
  也不能据此断言 outline 比 scan hints 强 26.03%。
- 两机制均有 r002 同输入同窗先验（scan hints -11.41%、sys-task outline -5.91%），
  本次确认代码、开关和功能语义可迁移。t0 后续若 Φ 选中相关邻域，可检验
  outline 基座叠加 scan hints 的正交性；不得用原样重测占候选席位。
- t0 完成 1/8，TES eval 计数 4/32（含双基线）；下一 action = t1/s01，严格保持
  `cross_trajectory=false`，不向 t1 proposal 注入本 step 结果。

## r003/t1/s01 活动摘要与宽 mux 链融合（2026-08-22，action A0061）

- **机械 winner（e00056，已入 t1/main）**：`--wide-mux-chain-fuse`，commit
  `014c3ae`，Host 241.956s（CV 0.41%），较 e00051 名义 -33.53%；17/17 ctest、
  3 rep difftest 全过，compile_s 1986.6s。engagement = 156 chains / 247 levels /
  74 blocks，与 r002 两轨迹逐数一致；r002 同窗 -2.19%/-1.17% 仍是机制量级口径。
- `--activity-summary-scan` e00055 同样全门通过，270.003s（CV 0，名义 -25.82%），
  compile_s 1984.5s；生产模型中 `activitySummary_` 静态引用 512,153 处。由于
  e00051/e00055=1.348x 落历史快慢态带，且基座已有 source-word guard，当前读数
  不能隔离摘要纯收益，机械落败也不构成机制证伪。
- c2/c1 名义 -10.39% 仍跨窗口，明显大于 wide-mux 的 r002 同窗机制量级；winner
  与分数有效，纯因果强弱不可裁。两候选 compile_s 均约 1985s，只余约 17% 编译门
  空间，后续生成代码扩张须同时证明覆盖与编译余量。
- t1 完成 1/8，TES eval 计数 6/32（含双基线）；两轨迹第 1 轮齐平，下一 action =
  round-summary，本 step 不提前做跨轨迹比较。

## r003 第 1 轮跨轨迹小结（2026-08-22，action A0062）

- 两条轨迹各完成 s01，四个候选均 `status=ok` 且功能门全过。t0 winner
  e00054 `sys-task-body-outline` = **247.560s**，t1 winner e00056
  `wide-mux-chain-fuse` = **241.956s**；机械 winner 已分别进入 t0/t1 主线。
- 本轮收敛到同一筛选判据：改生成代码的取指/访存形态比省指令、门控更有希望。
  t0 的 system-task 冷体 outline 与 t1 的宽 mux 中间态消除命中不同池，不能把
  winner 的绝对排名当作机制强弱；两项均有 r002 同窗正向先验，可继续作为局部组合
  的开放方向。
- 测量学结论再次加固：e00051/e00055 = **1.348x**、e00053/e00054 = **1.352x**
  均落在历史 per-process 快慢态 1.3-1.4x 带内。跨窗口 -31.99%/-33.53% 和
  e00056/e00055 -10.39% 不可直接归因；后续仍以同窗锚点为唯一亚 10% 裁决口径。
- activity-summary 与既有 source-word guard 可能覆盖，重探前先补 open/skip 动态
  计数；wide-mux engagement 已逐数复现（156 chains/247 levels/74 blocks）。两项
  候选 compile_s 约 1985s，只剩约 17% 编译预算，后续生成代码扩张需受控。
- r003 目前 evals 6/32、t0/t1 各 1/8，AM/gsim ledger 比 5.276x 仍远离目标且
  仅作看板值。机制方向无需用户调整，下一状态机 action 为 `r003/t0/s02`；本轮
  汇总不改变跨轨迹独立纪律。

## r003/t1/s02 宽 mux 链 helper 双精修（2026-08-22，action A0064）

- `e00056` 生产形态定量：156 条融合链的长度分布为 151x1、1x4、4x23。c1
  `wideMuxChainPriorityResolve` 只改 5 条多级链，以高优先级 selector mask +
  unresolved 位枚举替代逐 lane 重放；e00059 = **257.235s**（CV 0），较 e00056
  名义 **+6.32%**，17/17 ctest 与 3-rep difftest 全过，compile_s=2002.4s。
  它未给出正收益证据：减少 selector 工作被 ctz 位枚举、控制依赖与分散 store
  抵消；跨窗口读数不把全部回退强归因于机制。
- c2 `wideMuxChainSingleLevelTile` 精确命中 151 条单级链，以每 64 lane 一次 selector
  load + bulk base copy/fill + set-bit 覆写替代 pointer arrays/level loop；e00060 =
  **358.271s**（CV 0），同样全门通过，compile_s=1983.2s。`e00060/e00059=1.393x`
  落已知 per-process 快慢态带，raw score 机械落败但不能隔离 tile 机制，也没有正收益证据。
- `finish-step` 按分数将 e00059 (`d28a44f`) 机械合入 t1/main；新开关默认 off，代码
  合入本身可回撤。t1 best 仍为 e00056 241.956s，全局 best 仍为 e00057 229.429s。
  宽链 helper 微结构下一次重开前，必须先量化多级链动态 block execs、selector 密度
  与生产二进制形态；静态 chain/level 数不足以支撑原样变体。

## r003 第 2 轮跨轨迹小结（2026-08-22，action A0065）

- 两轨迹各完成 s02，四候选均全门通过。t0 winner e00057
  `scan-branch-hints` = **229.429s**（较 e00054 名义 -7.32%，已刷新全局 best）；
  t1 winner e00059 `wide-mux-chain-priority-resolve` = **257.235s**（较 e00056
  名义 +6.32%，机械入主线但 t1 best 仍为 e00056 241.956s）。
- scan hints 的证据链继续收敛：r002 在 t0/t1 同窗分别确认 -11.41%/-5.69%，
  r003 在 outline 基座上再得名义 -7.32%；动态已定位的 dispatch 跳过链与前端
  取指流仍是可复用的正向机制族，但本轮跨窗口幅度不升级为新的因果量级。
- `sys-task-body-compact` e00058 较 outline 基座名义 +1.94%，未改善约 823 MB
  生成 C++ 或 compile_s；共享冷体调用/参数物化抵消体积缩减，当前形态暂关闭。
- 宽 mux helper 两个微结构均无正收益证据：priority-mask 仅命中 5 条多级链且
  名义回退；single-level tile 精确命中 151 条链，但 e00060/e00059 = **1.393x**
  落快慢态带。重开前必须先有动态 block execs、selector 密度和生产二进制形态，
  不再仅凭静态 chain/level 数设计变体。
- 批内 CV=0 再次不能排除整批快慢态；亚 10% 新机制继续要求同窗/同态证据。
  当前 t0/t1 各 2/8、evals 10/32、ledger best/gsim = **5.002x**。无需用户调整
  C/L/K；本轮小结不改变 run 内跨轨迹独立纪律。

## r003/t0/s03 活跃 byte ctz 与 task cold 段均无正收益（2026-08-22，action A0066）

- **机械 winner、机制证伪（e00061）**：`--scan-active-byte-ctz` 在 e00057 的
  outline + scan-hints 基座上，将活跃 byte 内逐 bit 线性测试替换为
  `ctz + switch`。功能门全过，Host **251.746s**（CV 0，compile_s 1068.4s），
  较 e00057 名义 +9.73%。生产形态为 11,887 个 ctz 派发点 / 93,599 个 case，
  最终 ELF `.text` **+2.48%**、`.rodata` **+7.67%**；控制依赖、jump table 与
  工作集增长未胜过 branch-hinted 线性测试。该原样形态关闭，e00057 扫描形态保留。
- **冷段落地但无正证据（e00062）**：7,235 个 outlined helper 全部加 `cold`，
  `runtime.o` 形成约 6.11MB `.text.unlikely`，最终 ELF `.text` **-2.66%**；说明
  section 分离真实发生。Host **300.215s**（CV 0，compile_s 1070.5s），较 e00057
  名义 +30.85%，未达收益门。`e00062/e00057=1.308x` 接近快慢态带，纯回退幅度
  不可裁，但“继续缩已 outline 冷体即可改善热路径”没有证据；与 e00058 compact
  负结果合并，task body 纯布局/体积精修暂关闭。
- `finish-step` 按 score 将 e00061 (`3706873`) 机械合入 t0/main；t0 与全局历史
  best 仍为 e00057 **229.429s**。t0 3/8、t1 2/8、evals 12/32。下一 action 为
  t1/s03；本结论不跨轨迹回流 proposal。

## r003/t1/s03 宽 mux selector 稀疏性与零 tile 旁路（2026-08-22，action A0067）

- 非计时 recon 定量 23-level 链：199,996 次调用 / 70,398,592 个输出 lane，全部
  selector 机会中仅 304,596 个置位（0.0188%），99.57% lane 最终取 base，且无
  tile 被 selector 全覆盖；e00059 对 unresolved base 逐位 ctz 的主要浪费由此坐实。
- c1 `wide-mux-chain-sparse-overlay` 先连续初始化 base、再只 scatter 置位 selector，
  语义与 5 条多级链覆盖成立；e00063 = 495.496s，但起跑 loadavg 49.50、CV 8.73%
  标 noisy，较 e00059 的名义回退不能作纯机制幅度，本窗无正收益证据。
- **机械 winner c2/e00064** `wide-mux-chain-zero-tile-bypass`：零 selector tile 直接
  连续复制/填充 base，非零 tile 保留 branchless replay；409.731s（CV 0、loadavg
  50.18），同高负载窗口较 c1 中位快 17.31%，5 个多级调用精确命中，已入 t1/main。
  但较历史 e00059 仍名义慢 59.28%，所以 t1 best 保持 e00056 241.956s。
- 两候选 17/17 ctest、全部 difftest 与编译门均过；c2 compile_s 2229.3s，仅余
  7.1% 编译预算。wide-mux 后续只在 c2 上先补 zero/active tile 动态计数，保持公共
  helper 与代码体量；priority-resolve/sparse-overlay 不原样重测。宿主 loadavg
  49-50 升格为本 action 测量红旗，下一 round-summary 需统一解释。

## r003 第 3 轮跨轨迹小结（2026-08-22，action A0068）

- 两轨迹各完成 s03，四候选均全门通过。t0 winner e00061
  `scan-active-byte-ctz` = **251.746s**（较 e00057 名义 +9.73%，机械入主线但
  机制证伪）；t1 winner e00064 `wide-mux-chain-zero-tile-bypass` =
  **409.731s**（高负载窗较 e00063 快 17.31%，机械入主线但绝对收益未确认）。
  t0/t1 历史 best 仍为 e00057 229.429s / e00056 241.956s。
- 稀疏控制的共同判据收紧：为 93,599 个 Block 建 `ctz + switch` 使 ELF `.text`
  +2.48%、`.rodata` +7.67%，未胜过 branch-hinted 线性测试；全局 sparse overlay
  也无正收益。只保留“零 tile 局部门控 + 连续 base 流”作待动态计数量化的方向，
  关闭全局枚举/散写原样实现。
- task cold 属性虽使 7,235 个 helper 形成约 6.11MB `.text.unlikely`、最终
  `.text` -2.66%，运行仍无正收益；结合 compact 负结果，保留 task-body outline
  主机制，关闭已移出冷体的纯布局/体积精修。
- e00063 起跑 loadavg 49.50 且 CV 8.73% noisy，e00064 loadavg 50.18；本轮 wide-mux
  只确认机械排名，不把慢窗绝对值或 17.31% 升级为机制量级。继续冻结 3-rep 协议，
  不补测、不扩增。当前 evals 14/32、best/gsim = **5.002x**；无需用户调整 C/L/K，
  round-summary 结论不回流当前 run 的 proposal。

## r003/t0/s04 ctz 直接树与 nibble 分层守卫（2026-08-22，action A0069）

- c1 `scan-active-byte-tree` 用三层直接条件树替换 e00061 的 ctz switch/jump table；
  生产命中 11,888 个派发点，ELF `.rodata` 较 e00061 -7.14%，但 `.text` +0.54%。
  e00065 = **409.869s**（CV 0，loadavg 50.13），全门通过、compile_s 1255.3s；
  本慢窗无正收益证据，机械 winner 已入 t0/main。
- c2 `scan-active-byte-nibble` 在 hinted 线性测试外增加低/高 4-bit 守卫，命中
  11,624/11,633 个组；ELF `.text` 较 e00061 -2.23%、仅比 e00057 +0.20%。
  e00066 = **412.826s**（412826/412825/521718ms，CV 14% noisy，loadavg 49.99），
  全门通过、compile_s 1200.8s；固定 3 rep 协议不扩增、不重跑。
- 两候选相对低负载 e00061 名义回退 62.81%/63.99%，但均落在与 e00064 相同的
  loadavg≈50、Host≈410s 慢窗，不能作为纯机制幅度。c1/c2 仅差 0.72% 且 c2 noisy，
  因果排名不可裁；两项均未达到预注册收益门。
- 扫描残余的 ctz-switch、direct-tree、nibble-guard 原样形态均关闭；保留 e00057
  branch-hinted 线性扫描。t0/global best 仍为 e00057 229.429s；当前 t0 4/8、
  t1 3/8、evals 16/32，下一 action 为 t1/s04。
- 勘误：e00065/e00066 首次 record-eval insight 的 compile_s 误写为
  1248.2/1192.8s；ledger 已追加 correction，正确值为 1255.3/1200.8s。

## r003/t1/s04 active tile 稀疏覆盖与固定层专化（2026-08-22，action A0070）

- **机械 winner、暂定正向（e00067）**：`--wide-mux-chain-active-tile-sparse` 在
  zero-tile 门控内先连续落 base，再按 level 只 scatter selector 置位 lane；生产精确
  命中 1x L4 + 4x L23 多级调用。Host **382.171s**（CV 0，compile_s 2136.2s），
  较 e00064 名义 -6.73%、越 3% 门；但起跑 loadavg 12.30 vs e00064 50.18，跨窗
  幅度不可作已确认因果。winner `1951404` 已入 t1/main，后续确认条件是动态
  zero/active tile 分解或低负载同窗证据，不原样重测。
- **固定层专化证伪（e00068）**：按实际 L4/L23 生成两个共享 helper，五个调用点均
  命中，数据流不变；Host **427.066s**（CV 0，compile_s 2049.4s），在与 e00064
  相近的高负载起点下回退 4.23%。clang 将 helper 从动态版 0x4de B 展开为
  0xc03 + 0x264f B，最终 ELF `.text` +11,624 B；循环控制收益未胜过前端/I-cache
  压力，原样方向关闭。
- 两候选 17/17 ctest、全部 difftest 与编译门均过。t1 best 仍为 e00056
  241.956s，全局 best 仍为 e00057 229.429s；t0/t1 各 4/8、evals 18/32，下一
  action 为第 4 轮 round-summary。

## r003 第 4 轮跨轨迹小结（2026-08-22，action A0071）

- **稀疏优化的可复用判据**：e00067 在 e00064 的 zero-tile 门控内保留连续 base
  流，只对 active tile 的 selector 置位 lane 做 scatter；它是本轮唯一越过预注册
  3% 门的形态（382.171s，名义 -6.73%）。e00065/e00066 继续压缩 active-byte
  控制测试却没有正收益证据，说明顺序访存/fall-through 外形比少几次 bit test 更
  重要。e00067 的跨负载读数仍为暂定正向，不能原样重测替代因果确认。
- **固定层专化关闭**：e00068 在与 e00064 接近的 loadavg≈50 窗口回退 4.23%，且
  L4/L23 helper 展开使 ELF `.text` 增 11,624 B；静态层数专化的循环控制收益不足以
  覆盖前端/I-cache 代价。后续 wide-mux 候选必须先证明动态覆盖与代码体量，不再仅凭
  链长度设计模板化 helper。
- **测量红旗延续**：e00065/e00066 处于约 410s 慢窗，e00066 固定 3 rep 内有
  521.718s 离群值；e00067 的 loadavg 12.30 与 e00064 的 50.18 不同。CV=0 不足以
  建立跨批可比性，继续冻结 3 rep 协议、不扩增、不补测，并把跨窗百分比限定为方向
  线索。
- r003 当前 t0/t1 各 4/8、evals 18/32，`best_overall` 仍为 e00057 229.429s，
  看板 best/gsim 约 5.002x。下一步维持 C/L/K 与轨迹独立；若再开 scanner 或
  wide-mux 邻域，先做非计时动态计数和同态锚点。跨轨迹结论不回流当前 run proposal。

## r003/t0/s05 前缀跳过与 task 触发提示均败于回归门（2026-08-22，action A0072）

- e00069 `scan-active-byte-prefix` 与 e00070 `sys-task-fire-hints` 均为
  `ctest_fail`，各自 16/17 grhsim tests 通过、`grhsim-am-cpp-emitter` 失败，未进入
  全模型 emit/emu/计时；`compile_s=316.3/309.5s`。功能门否决且非 interference，
  不修后覆盖、不重跑，t0 s05 无 winner、主线不移动。
- 两项生成形态都实际落地，失败点是候选自带文本断言：e00069 fixture 期待
  `UINT8_C(0x02)` 而 emitter 既有格式为 `UINT8_C(0x2)`；e00070 fixture 仍匹配
  未包 hint 的 `if (!onceCompleted...)`。因此只能归类为**回归契约失败、机制未测**，
  不能把 prefix-skip 或 outlined fire hint 记为性能负方向。
- 候选开发纪律升级：新增 emit 控制流规则在正式 evaluator 前必须用结构化不变量覆盖
  生成形态，避免把字面格式当语义；纠正版若未来重开，必须先过完整 17/17 且使用新
  commit，不能原样重放失败候选。当前 t0 5/8、t1 4/8、evals 20/32，历史 best
  仍为 e00057 229.429s；下一 action = `r003/t1/s05`。

## r003/t1/s05 非零 level 压缩与优先级去重（2026-08-22，action A0073）

- **机械 winner、局部正向（e00071）**：active-tile sparse 的首遍 union 同时形成
  <=64 层 nonzero bitmap，active tile 只重访实际非零 level；Host **339.910s**
  （CV 0.02%，compile_s 1876.0s），较 e00067 名义 -11.06%，全门通过并入 t1/main。
- c2/e00072 从高优先级逆序解析并用 resolved mask 保证重叠 selector lane 最多写一次，
  Host **356.780s**（CV 0，compile_s 1870.1s），较 e00067 名义 -6.64%，同样全门
  通过。两项都越预注册门，但相对 e00067 的幅度受起跑 loadavg 12.30 vs 本轮
  1.92/2.47 混杂，只记正向证据，不升级为纯机制量级。
- e00071/e00072 是紧邻低负载窗口，c1 比 c2 快 **4.73%**；结合 selector 总机会密度
  仅 0.0188%，证据支持“压缩非零 level 二次遍历”比“消除跨 level 重叠 lane 写”
  更有杠杆。后续先计数 active tile 非零 level 分布/重叠率，不原样重测两候选。
- t1 完成 5/8，历史 t1/global best 仍为 e00056 241.956s / e00057 229.429s；
  evals 22/32，下一 action 为第 5 轮 round-summary。

## r003 第 5 轮跨轨迹小结（2026-08-23，action A0074）

- t0/s05 的两个控制流候选均在 `grhsim-am-cpp-emitter` 回归断言处失败（16/17
  grhsim tests），没有 emit/emu/计时结果；应归类为生成契约失败、机制未测。后续
  emitter 控制流改动先覆盖结构化生成不变量，纠正版使用新提交，不原样重放。
- t1 的 active-tile sparse 继续细化为 union 时生成 <=64 层 nonzero bitmap：
  e00071 **339.910s** 胜 e00072 priority lane resolve 的 **356.780s**（紧邻低负载
  窗口快 4.73%）。这加强了“减少实际非零 level 重访”优于“去重重叠 lane 写”的
  方向判断，但因 e00071/e00072 与 e00067 起跑负载不同，跨窗幅度只记正向证据。
- 可复用判据：局部门控、连续 base 流和稀疏 level 重访是当前唯一仍有正向信号的
  wide-mux 形态；控制派发微优化、固定层 helper 展开和纯布局精修继续关闭。下一轮
  先做 active-tile 非零 level 分布/重叠率的非计时统计，再决定候选。

## r003/t0/s06 表型漏传勘误（2026-08-23，action A0075）

- e00073/e00074 虽均通过 17/17 ctest、3 rep difftest 和编译门，但两份
  `result.json.emit_args` 都只有冻结的基础 10 开关；prefix-skip 与 outlined fire
  hint 均未在生产模型启用。370.611s / 346.687s 是相同基础表型的重复读数，不能作为
  两机制的正负证据或相互排名。
- `finish-step` 已按 raw score 将 e00074 机械入 t0/main 并消耗 s06；提交中的规则默认
  off，历史 best e00057 229.429s 不变。ledger 以 correction 追加勘误，不修改原始
  ok/commit-marker，也不手改 run.json。
- **候选表型审计升级为硬前置**：代码类 default-off 属性也必须显式传完整父节点
  `emit_args` + 本候选开关。正式评估后、`record-eval` 前逐项核对 result emit_args；
  “commit 含实现”不能替代“生产表型已启用”。未来重开两个机制须使用新 step/eval，
  不得引用 e00073/e00074 分数。

## r003/t1/s06 mask 缓存与单级 direct 均证伪（2026-08-23，action A0076）

- c1/e00075 将 active-tile union 中的非零 mask/tval 紧凑缓存到两个 64 项栈数组，
  Host **363.823s**（CV 0，compile_s 1982.6s），较父节点 e00071 回退 7.03%。
  每调用 1 KiB 栈框与缓存写流未胜过二次 pointer-array 读取，当前形态关闭。
- c2/e00076 为 151 条单级融合链直接传 sel/tval，保留逐 word branchless blend，
  Host **354.543s**（CV 0，compile_s 1995.9s），较 e00071 回退 4.31%。它机械胜
  e00075 2.55% 并入 t1/main，但两者 loadavg 5.88/2.53 不同，不能把差值作纯机制
  收益；结合 e00060，单级 helper 微结构路线关闭。
- 两候选均通过 17/17 ctest、3 rep difftest，且完整 11 开关表型已审计。wide-mux
  下一次精修须先有单/多级动态调用权重与 active-tile 非零层分布，不再以静态链数或
  避免少量 pointer reload 作为收益代理。

## r003 第 6 轮跨轨迹小结（2026-08-23，action A0077）

- 本轮无新的有效正向性能证据：t0/e00073-e00074 因完整候选 `emit_args` 漏传而是
  同一基础表型的重复计时，t1/e00075-e00076 则分别慢于父节点 e00071 7.03%/4.31%。
  e00074/e00076 只是 raw-score 机械 winner，不是机制正向结论。
- **表型审计是候选可用性硬前置**：评估前明确写出完整父表型 + 候选开关，
  评估后、`record-eval` 前逐项核对 `result.json.emit_args`。未启用的 default-off 实现只能记
  “机制未测”，不得依 raw score 标正负。
- wide-mux helper 微结构中，固定栈缓存、避免少量 pointer reload、消除单元 ABI 和
  静态单级链数均已不足以作为收益代理。重开该邻域前必须有单/多级动态调用权重、
  active-tile 非零层分布或必需 base 写流的直接证据。

## r003/t0/s07 前缀跳过与 task 触发提示实测（2026-08-23，action A0078）

- A0075 的表型漏传已纠正：e00077/e00078 都显式携带 e00057 的 12 项完整父表型，
  再分别启用 `scan-active-byte-prefix` / `sys-task-fire-hints`；两份 13 开关
  `result.json.emit_args` 已审计，17/17 ctest、3 rep difftest 与编译门全过。
- e00077 prefix-skip = **312.027s**（CV 0，compile_s 1063.3s），e00078 fire-hint =
  **299.715s**（CV 0，compile_s 1069.3s）；c2 同 step 快 3.95% 并机械入 t0/main，
  但相对 e00057 分别名义回退 36.00%/30.63%，均未达到预注册收益门。
- e00077/e00057=1.360x、e00078/e00057=1.306x，恰落已知 1.3-1.4x 进程快慢态带；
  历史跨窗回退不可全归因于机制，c1/c2 排名也不是纯因果对照。可复用结论仅是两项
  当前均无正向证据；继续精修前必须先量化首活跃 bit/跳过测试数和 fwrite fire/参数
  准备动态权重，不再用静态站点数作收益代理。

## r003/t1/s07 selector 摘要复用与幂等写抑制（2026-08-23，action A0079）

- **A0076 表型勘误**：e00075/e00076 的 11 项 `emit_args` 缺少 active-tile sparse
  的硬依赖 `--wide-mux-chain-fuse`；emitter 实际未启用两个 wide-mux 候选机制。
  363.823s/354.543s 只是基础 10 开关重复计时，不得证伪 mask cache 或 single-level
  direct；原条目保持不改，以 ledger correction 与本节追加修正。
- e00079 round-local selector summary reuse = **359.866s**（CV 0，compile_s
  1990.6s），较完整 13 开关父节点 e00071 回退 **5.87%**。四条 23-level 生产调用
  确实共享 selector，仍不足以支付 vector 摘要维护、跨 tile 预扫描与 member 访问；
  重复 `23 x 6` mask 扫描不是一阶成本，当前共享摘要形态关闭。
- e00080 idempotent store suppression = **345.215s**（CV 0，compile_s 1983.1s），
  较 e00071 回退 **1.56%**；它同窗比 e00079 快 4.07% 并机械入 t1/main，但仍无
  父节点收益。99.57% lane 最终取 base 不等于目标词已稳定为 base，逐 lane compare/
  branch 未被省下的 store 抵消，当前形态关闭。
- 两项均用完整 13 开关表型，通过 17/17 ctest、3 rep difftest 与编译门。wide-mux
  再开前必须先量化 target 词实际变化率或 helper 动态 Host 权重，不再用静态 selector
  共享度、base lane 比例或 helper ABI 作为收益代理。

## r003 第 7 轮跨轨迹小结（2026-08-23，action A0080）

- 本轮四个候选全部通过功能门和编译门，但没有新增正向性能证据。t0/e00077-e00078
  均错过预注册收益门；t1/e00079-e00080 分别较有效父节点 e00071 回退 5.87%/1.56%。
  e00078/e00080 只是同 step raw-score winner，不是机制收益。
- 控制流与 wide-mux 两侧共同收敛到同一实验判据：静态站点数、selector 共享度、
  base lane 比例和少量 helper ABI 都不能作为收益代理。重开前必须量化首活跃 bit/
  实际跳过测试、fwrite fire/参数准备、target 词变化率或 helper 动态 Host 占比。
- `corr-e00075-e00076-phenotype` 已使 A0076/A0077 对 mask cache 和 single-level
  direct 的性能证伪失效：两次评估缺少 `--wide-mux-chain-fuse`，机制实际未启用。
  原记录按 append-only 规则保留，后续以 correction 与 A0079/A0080 勘误为准。
- 当前 t0/t1 各 7/8、evals 30/32，历史 best 仍为 e00057 229.429s，约为 gsim
  基线的 5.002x。C/L/K 在 run 内不调整；第 7 轮跨轨迹结论不回流 r003 proposal。

## r003/t0/s08 task 延迟取参与 byte 中性提示（2026-08-23，action A0081）

- e00081 `sys-task-lazy-member-args` 在 ctest 门失败（16/17，compile_s 383.7s），
  未进入生产 emit/计时。生成 fixture 确已把持久 handle/arguments 移入零参数冷 helper，
  但候选测试错误假定一个参数仍是 block-local；实现与局部性分类测试契约未闭合，不能
  取得性能证据，也不以同 eval-id 修复重跑。
- e00082 `scan-byte-neutral-hints` 用完整 14 开关表型全门通过：**327.672s**
  （CV 0，compile_s 1220.3s，3 rep 73580/49996），较 e00078 名义回退 9.33%。
  起跑 loadavg 50.77 vs e00078 的 5.30 使幅度受跨窗机器态混杂，但候选未达到
  -1.5% 收益门，故只有“无正向证据”的稳健结论。
- source-word guard 证明 word 中至少一位活跃，不证明每个 byte 的分支概率应中性；
  e00057 的 byte + Block 两级 cold hint 仍保留。拆层重开前须量化 active word 内
  非零 byte 分布并做同窗锚定；task 延迟取参重开前须用同时含持久/真实局部参数的
  最小 fixture 固化分类契约。
- e00082 是唯一 ok 而机械入 t0/main；新规则默认 off，合入不改变默认表型。t0 已
  完成 8/8，历史 t0/global best 仍为 e00057 229.429s。

## r003/t1/s08 mask 缓存与 direct 写回（2026-08-23，action A0082）

- e00083 首次以完整 13 开关生产表型真实启用 active-tile mask/value 紧凑缓存：
  **419.534s**（CV 0，compile_s 2063.6s，loadavg 50.53），全门通过且生成缓存命中；
  较 e00080 名义回退 21.53%。约 1 KiB 栈框和 union 缓存写流没有正向证据，当前
  mask/value 缓存形态关闭；A0076 对 e00075 的旧结论仍以“机制未启用”勘误为准。
- e00084 恢复连续 base copy/fill 与直接 sparse store，移除 e00080 的逐 lane target
  load/compare/branch：**378.064s**（CV 0，compile_s 2164.5s，loadavg 11.58），
  全门通过并机械入 t1/main。它较 e00083 名义快 9.89%，但 loadavg 不同；较低负载
  e00080 仍慢 9.52%，所以只确认 raw winner，不确认父节点收益。
- wide-mux 微结构已收敛：栈缓存、target 幂等比较、静态 selector 共享度和 base lane
  比例都不足以预测收益；再开前必须有 helper 动态 Host 权重或 target 实际变化率证据。
  t0/t1 均完成 8/8，历史 best 仍为 e00057 229.429s，下一 action 为 run-summary。

## r003 run-summary（2026-08-23，action A0083）

- r003 以 C=2/L=8/K=2 走满 16/16 步、32 个候选 eval（总 34，含双基线）。29 个
  候选 ok、3 个 ctest_fail；全部 ok 过 17/17 ctest、3 rep difftest 与编译门，
  e00063/e00066 noisy。e00073-e00076 中 4 个 ok 结果因候选开关/硬依赖漏传，按
  append-only correction 仅作无效机制测量。
- best_overall = t0/e00057 **229.429s**（commit `1563c3d837fc`），相对 AM y0
  363.995s 名义 -36.97%，但仍为 gsim 45.864s 的 **5.002x**；t1 best e00056
  241.956s。目标未达成，且两个 best 都在前两轮产生，后六轮无新增 best。
- restart 可继承材料只保留 t0 的 task-body outline + scan hints 与 t1 的
  wide-mux-chain-fuse；active-tile + nonzero-level 只记方向性正证据。scanner 派发、
  task 冷体精修、wide-mux cache/summary/store 微结构在没有动态 Host 权重、非零层
  分布或 target 变化率前不再重开。
- 进程快慢态约 1.3-1.4x、跨批 loadavg 差异与 noisy 样本继续证明 CV=0 不足以支持
  跨窗因果比较。229.429s/5.002x 是 ledger/看板口径，不宣称纯机制累计收益。
- **裁决：当前不建议 restart。** `restart.max=2` 已耗尽且 `auto=false`，搜索收益明显
  衰减；收口后停止。若用户另行扩预算并先修复 rep 级分簇/同窗锚定，预备 y0 为
  r003/e00057 `1563c3d...`，建议 C/L/K=2/4/2（N=16），候选须由非计时动态 profiling
  驱动。

## r004 协议修复冒烟：双态根因裁决（2026-08-23，r004-overhaul Task 1）

脚本 `scripts/tes_smoke_numa_cluster.py`（持 LOCK + emu 守卫，台账外不进 ledger）；
原始数据 `build/tes/grhsim-am-coremark/smoke-20260823-094505/` 与 `smoke-20260823-095136/`。

- **轮 1（gsim emu，49s 级，3 组×6 rep）**：A 现状 49.5-49.8s、B membind=0
  49.1-49.4s、C membind=1（错位）49.5-49.7s——全部单簇，双态未复现。gsim 默认
  页放置反而偏 N1（~12.9k/15k 页，对核 12-14 为远端）；同侧绑定仅 ~0.6%。
- **轮 2（AM emu e00057 二进制，273s 级，2 组×6 rep）**：A 272.9-273.3s、
  B 272.7s×6——同样单簇、批内无抽签。AM 默认页放置本就在 N0（~42.5k 页本地），
  membind 无变化（0.15%）。
- **裁决**：① THP 证伪（两轮全部 AnonHugePages=0）；② numactl membind 不是修复
  （两 emu 的默认放置已各居一端，绑定收益 ≤0.6%）→ Task 4 跳过；③ r002 A0056 的
  批内 per-process 抽签在本日 36 rep 中未复现；④ **跨窗漂移直接实证**：e00057 同一
  二进制今日 273.1s vs r003 台账 229.429s（×1.19）——窗口级状态差是主要成分，
  聚簇裁决（快簇中位）只能挡批内分裂，跨窗口径一律靠同窗比较 + retime + 重锚。
- 流程含义：r004 run-init 双基线重锚是硬前置；任何跨窗百分比在 action 笔记里
  不得直接相减（维持 r002/r003 纪律）。

## r004 协议升级落地清单（2026-08-23，r004-overhaul）

设计 `tes/DESIGN-r004-overhaul.md`，计划 `tes/PLAN-r004-overhaul.md`。

- **测量**：evaluator 聚簇裁决（快簇中位取代跨簇 median，落地 A0056 提请）+
  簇结构自适应 rep（双峰检出才加跑至 ≤9）+ 每 rep 1Hz 只读协变量采样 +
  `retime` 只补计时子命令。**r002 悬置的 rep 级簇分组裁决与基线重锚至此关闭**
  （重锚由 r004 run-init 执行 + round 2 round-summary retime 中段复核）。
- **调度**：recon 成为正式 action（staleness≥2 门，不占预算）；winner 按
  adjudicate_noise=3% 噪声带分类 outcome=win/neutral/loss/initial（best 只在真实
  进步更新，取代手记"机械 winner †"）；迁移席位合法化（step≥2、每 step 1 席、
  --migration-source 登记，RULES §4 修订）；候选表型审计门（tes-candidate.json
  硬前置，record-eval 不符拒登记）。
- **Φ**：neutral 节点以前驱分数参与归一化（防 artifact 峰值）；proposal 新增
  recon 证据段与动态权重硬要求。
- **结构**：r004 = C=6/L=4/K=2（N=48），y0=r003/e00057；restart.max 放宽至 3
  （用户批准 2026-08-23）。安慰剂席位退役，测量校准走协议动作。
- **停止规则**：r004 前 2 轮（24 候选）零确认收益（同窗/同簇口径）即停止搜索。

## 计时 rep 恢复串行（2026-08-23，用户指示）

- `grhsim-am-coremark` 的单步评价恢复为 rep 逐次串行：先按
  `rep_cores` 顺序绑核跑 3 次，取快簇中位；检出双峰时仍按每组
  3 次串行追加，最多 9 次。全局 LOCK、每 rep 起跑前 emu 干扰守卫、
  difftest 金标门和簇裁决口径不变。
- 原因：并行 rep 会相互争用宿主资源，使绝对 Host 时间比单 rep 系统性偏高；
  串行执行使每个样本表示独占负载，并保留跨核抽样。历史 proposal、manifest
  和 ledger 保留当时协议的快照语义，不回写。

## r004 run-init 前置阻塞（2026-08-23，A0084）

- 迁移后 config 指定的正式 gsim target
  `build/xs/gsim/gsim-compile/emu` 缺失；任务 playbook 规定 TES 不自行构建，
  因而 r004 未初始化、未产生 eval、未写 ledger。
- `build/xs/gsim-flat/gsim-compile/emu` 不是可替代副本：历史构建明确带
  `--flatten-nodes --supernode-max-size=16`，相对未打平正式基线性能慢 3.6%。
  功能等价不能推出 target 性能等价，禁止用改路径或软链绕过。
- 本次迁移后的 post-stats 输入 SHA-256 为
  `c82ed4542f58ba60b1d7b38c57a877ad7cc81898a5df019d72d7e885588b70c7`；
  正式 emu 恢复后，r004 run-init 应冻结这个新指纹并按串行 rep 协议重测双基线。

## r004 正式 gsim 恢复与双基线（2026-08-23，A0085）

- 标准生产 emu 已恢复到 `build/xs/gsim/gsim-compile/emu`：
  `--supernode-max-size=15`、无 `--flatten-nodes`、84,643 supernodes / 645,854
  DAG edges，SHA-256 `73e62bd16590a3dfb2a7d6dbe711be8843383f9fdfa28f8b20603996542a4418`。
  迁移后的 `zstd.h` 搜索路径问题用仓库本地 dependency root 续编解决；A0084 阻塞关闭。
- r004 以 r003/e00057（`1563c3d8`，完整 12 开关）为 y0，C=6/L=4/K=2；冻结新
  post-stats SHA `c82ed4542...b70c7`。AM e00085 串行三次为
  193.403/188.958/194.839s，中位 **193.403s**、CV 1.59%；gsim e00086 为
  22.720/22.608/23.100s，中位 **22.720s**、CV 1.13%。两侧均单簇、非 noisy，
  三次 difftest 全过（AM `73580/49996`，gsim `73584/49998`）。
- 本机同协议 AM/gsim = **8.512x**。迁移前 r003 的 5.002x 只保留历史快照语义，
  不与本次跨机器/跨窗口重锚直接相减；后续候选以 e00085/e00086 为唯一 r004 基准。

## r004/t0/s01 event 优先与 unsigned-div64（2026-08-23，A0087）

- e00087 对 b90656/b90657（recon 合计 **4.683%** cycles）的非 final system-task
  触发条件做 event/pending-first 短路，生产命中 7,236 个守卫；Host **191.726s**，
  较 e00085 名义 -0.87%。全门通过、单簇且非 noisy，但未越 3% 门。单纯重排纯读取
  谓词不是已确认收益；再开 task 守卫前先量化 event/fire 命中率或参数准备动态成本。
- e00088 将 b93085 中全部 **1,252** 个 64-bit unsigned Div 改为单次 RHS 加载、零除
  保护的原生 `/`，signed/窄宽度/Mod 保持 helper；Host **189.829s**，较 e00085
  名义 -1.85%、同窗较 e00087 -0.99%。它是 raw winner 并以 outcome=`initial` 入
  t0/main，但仍在 3% noise 带内，只记小幅正向信号，不宣称确认收益。
- 两项均用完整 13 开关表型通过 17/17 ctest、3 rep `73580/49996` difftest 和 2400s
  编译门（640.8/643.5s）。t0 后续应先 recon e00088，检查 b93085 cycles 是否随
  helper 边界消除而下降；没有新的动态分解前不继续 task 条件顺序或 division helper
  微结构精修。当前 best/gsim = **8.355x**，下一 action 为 t1/e00085 recon。

## r004/t2/s01 commit scratch 后延与 host-call predicate run（2026-08-23，action A0091）

- 本 action 从 `step-resume` 接续，只补 pending c2；c1/e00091 未重跑。e00091 将
  b93159/b93141 前缀 chunk 裁到只接收活跃 `byteFlags`，并把 2,742/4,227 个 scratch
  flag 清零移入事件门：**189.045s**，较 e00085 名义 -2.25%。e00092 将相邻完全
  同谓词的 outlined host call 融合为单一分支，生产形成 6,314 个 run、覆盖 12,827
  个成员：**188.662s**，名义 -2.45%、同窗较 c1 -0.20%。
- 两项均通过 17/17 ctest、三次 `73580/49996` difftest 与编译门，单簇且非 noisy。
  两者整体 Host 的预注册 1% 门均通过，但都处于 r004 的 3% 确认带内；c1 的 commit
  双峰 -15% 与 c2 的 task 双峰 -20% 尚无 post-change recon，不能宣称确认收益或
  用 0.20% raw 差值区分机制。
- `finish-step` 按 raw score 将 e00092 入 `tes/r004/t2/main`，outcome=`initial`；
  best_overall=e00092 **188.662s**，AM/gsim **8.304x**，预算 8/48。t2 再到期时先
  recon b90656/b90657 是否降权；在动态降幅确认前，不把 e00092 当 migration source。
- 下一 action 为 `t3/e00085 recon`；本 action 只预告，不启动。

## r004/t3/s01 幂次索引与宽 mux 链融合（2026-08-24，action A0093）

- e00093 将索引位宽精确覆盖 2 的幂深度的 memory read 专化为窄标量提取和掩码，
  生产六个 512-depth 热块的 3,072 个站点全部命中且无残留 `index_words`；Host
  **172.530s**，较 e00085 名义 -10.79%，17/17 ctest 与三次 `73580/49996`
  difftest 全过，单簇 CV 0.97%、非 noisy。它显著越过预注册 0.75% Host 门和 3%
  确认带，以 outcome=`initial` 入 t3/main 并刷新全局 best。
- e00094 精确融合相邻、sole-use、同块且至少 16 级的 64-bit lane
  `ArrayBroadcast -> ArrayMux` 链，生产命中 b69157/b69158/b69159 的 4 链/92 steps；
  Host **187.491s**，较 e00085 名义 -3.06%，同样全门通过、单簇 CV 0.97%。该机制
  有正向 Host 证据，但较 e00093 慢 8.67%，本 step 不合入主线。
- 两项的预注册池级降幅（memory-read -25%、宽链 -70%）都尚未由 post-change recon
  验证。尤其 e00093 的 10.79% Host 改善超过旧画像中 3.140% 的池权重，表明插桩
  cycles 占比是病灶定位信号而非严格收益上界；下次 t3 recon 应量化池权重变化与替代
  热点，再决定推广幂次深度或组合宽链，不能只按静态命中数外推。
- 当前 best_overall=e00093 **172.530s**，AM/gsim **7.594x**，预算 10/48；下一
  action 为 `t4/e00085 recon`，本 action 未启动。

## r004/t4/s01 两项候选均由 fixture 误报阻断（2026-08-24，action A0095）

- e00095/e00096 均为 `ctest_fail`（16/17），未进入生产 emit、difftest 或 Host
  计时，故 commit scratch 后延与 host predicate run 在 t4 轨迹均是**未测**，不得
  记为性能证伪。c1 生成物已有门内 `wrChgblk` reset，但 fixture 错要不存在的
  `detGrpblk`；c2 的 stock/outline/run 输出逐字节相同（1 boot/15 data），fixture
  错把 data 数写死为 9。
- evaluator 的请求表型现于任何 build/ctest 早退前写入 `result.json`，使失败候选也能
  通过 `tes-candidate.json` 表型审计并登记；构建、功能门和计时协议未改变。

## r004/t5/s00 动态热点画像（2026-08-24，action A0096）

- e00085 的 t5 独立 runtime-profile 通过 `73580/49996` 金标；compute/commit 为
  **73.1234%/26.8525%**，top-50 占总块 cycles **39.978%**。b93159/b93141 commit
  双峰合计 **8.421%**，b90656/b90657 system-task compute 双峰合计 **4.693%**，
  b83835/b93085 合计 **2.325%**。
- commit block 仅占执行次数约 2.57%，阶段墙钟却占 26.85%，平均单次约为 compute
  block 的 13.92x；scratch 生命周期后延与共享 fire 谓词 run 是下一步两个机制互异、
  可按池级 cycles 降幅证伪的方向。top-50 外仍有 60.022% 长尾，静态命中数不得替代
  动态 engagement。

## r004 第 1 轮中段重锚与跨轨迹结论（2026-08-24，action A0098）

- round 1 结束后复用既有 emu 串行 retime：AM/e00085 从冻结 **193.403s** 变为
  **194.922s**（+0.79%，CV 0.86%，unimodal），gsim/e00086 从 **22.720s** 变为
  **23.780s**（+4.67%，CV 2.45%，unimodal）。gsim 快带漂移超过 3% 协议阈值；
  r004 的 ledger/manifest 仍冻结原值，后续同时报告冻结裁决口径和重锚诊断口径，
  不把 target 单侧变慢归因于 AM 候选收益。
- 冻结口径下 e00093/gsim = **7.594x**；重锚诊断口径为 **7.255x**。第一轮唯一
  明确越过 3% 确认带的是 e00093 幂次 memory-read 索引专化（-10.79% vs e00085）；
  下次优先做 post-change recon，不能用旧画像的 3.140% 池权重直接外推收益来源。
- host-call 谓词共享与 commit scratch 后延在多轨迹重复给出 1.18%-2.45% 弱正信号，
  但均缺 post-change 池级证据；round 2 先按各轨迹独立 recon 验证，不直接跨轨迹迁移。
  Concat 位置装配仍未决：一个实现弱正、另一个因位序错误功能失败，重开须先补非对称
  多 operand 位序测试。

## r004/t3/s02 幂次索引与宽 mux 链组合（2026-08-24，action A0102）

- **同轨迹正交机制可加确认（e00106）**：在 e00093 幂次 memory-read 索引基座上组合
  e00094 的 4 条/92-step 宽 broadcast-to-mux 链融合，Host **166.947s**，较父节点
  **-3.24%**（CV 1.12%、单簇、非 noisy），越过 r004 3% 裁决带；17/17 ctest 与
  三次 `73580/49996` difftest 全过。宽链池在 e00085 recon 中占 **1.567%**，组合
  增量大于旧插桩权重，再次说明 recon 权重用于定位而非严格 Amdahl 上界；池级 70%
  降幅仍须 post-change recon 验证。
- **pack gather 性能未测（e00105）**：六个 512-read 块的 512 scalar -> 1024-bit
  Concat 融合候选因新 fixture 把 MemoryRead 放入 EntryBlock，语义 validator 在 ctest
  以 16/17 拒绝，生产 emit/difftest/Host 均未到达。重开前必须修正 fixture 并证明
  生产命中；不得把本次 `ctest_fail` 当作机制性能证伪。
- 新 best_overall=e00106 **166.947s**，相对 r004 AM y0 改善 **13.68%**，冻结
  AM/gsim = **7.348x**；预算 22/48。

## r004/t4/s02 修正 fixture 后完成双机制测量（2026-08-24，action A0103）

- **s01 回归误报关闭**：e00107/e00108 分别删除不存在 detector-group 的错误断言、
  将 byte-identical 三模型的 data 行数期望从 9 修正为 15；两项均通过 17/17 ctest、
  三次 `73580/49996` difftest 和编译门，证明 s01 失败来自 fixture 而非生成语义。
- commit scratch 事件门后清零 e00107 = **189.851s**（较 e00085 -1.84%，CV 0.86%）；
  outlined fwrite 同谓词分支合并 e00108 = **189.263s**（-2.14%，CV 1.47%）。两项都
  达到预注册 1% Host 下限但未越 3% 确认带，只记弱正，不能宣称确认。
- e00108 仅比 e00107 快 **0.31%**，raw winner 不代表机制优劣；commit 双峰 8.646%
  与 system-task 双峰 4.923% 的预注册池级降幅尚待 post-change recon。e00108 以
  outcome=`initial` 入 t4/main；全局 best 仍为 e00106 **166.947s**，预算 24/48。

## r004/t5/s02 Concat 位序修正与幂次索引迁移（2026-08-24，action A0104）

- e00109 将本轨迹 e00098 的 scalar Concat 直接装配从错误的低位累计改为按剩余总宽
  高位到低位放置，并新增 8/16/32-bit 非对称生成模型运行测试；17/17 ctest 与三次
  difftest 恢复，Host **189.753s**，较 e00097 改善 **0.71%**。功能修正确认，性能
  只达 0.5% 下限且未越 3% 带，不能宣称机制收益确认。
- e00110 以本 step 唯一迁移席把 e00093 幂次 memory-read 索引专化叠加到 e00097 的
  commit scratch 后延父节点，Host **173.058s**，较父改善 **9.45%**，CV 0.54%、
  单簇非 noisy；`migration_source=e00093`、outcome=`win`。这是继 t0/t1/t2 后又一条
  跨轨迹一阶复现，确认幂次索引是当前最稳定的可迁移机制。
- t5 best 的冻结 gsim 口径为 **7.617x**，仍比全局 best e00106 慢 **3.66%**；差异与
  e00106 额外组合宽 mux 链一致，但尚无 t5 post-change recon，不从整体 Host 反推池级
  降幅。预算 26/48；下一 action 为第 2 轮 round-summary。
