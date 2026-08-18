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
