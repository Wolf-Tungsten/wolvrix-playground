# 任务 grhsim-am-coremark

**目标**：grhsim-am emu 仿真 xiangshan coremark 50k（`-C 50000`）的 Host wall time
（初始 3 rep、双峰时自适应至 9 rep、快簇中位、绑核、评估间串行）≤ gsim 同等负载同协议测量值。任务指令见 [brief.md](brief.md)
（x0，run 期间冻结），参数见 [config.json](config.json)。

## 当前状态速览

- **r004 已启动，e00057 起点与双基线重锚完成**（2026-08-23，
  [A0084](actions/A0084_run-init_r004起点与聚簇基线_20260823.md)）：y0 = r003/e00057
  `1563c3d`，完整 12 开关表型；该 commit 已 fast-forward 合入 wolvrix
  `grh/tes-grhsim-am`，r004 base 与 t0..t5/main 均从同一点出发。C=6/L=4/K=2，
  N=48；AM e00085 = **348.716s**（unimodal，CV 0.89%，17/17 ctest + 3 rep
  difftest 全过），gsim e00086 = **50.275s**（unimodal，CV 0.47%，3 rep difftest
  全过），起跑差距 **6.936x**。下一 action = t0/e00085 `recon`，本 action 未启动它。

- **r003 已收口，当前不建议 restart**（2026-08-23，[A0083](actions/A0083_run-summary_r003收口与停止restart_20260823.md)，
  详见 [runs/r003/summary.md](runs/r003/summary.md)）：C=2/L=8/K=2，16/16 步、候选
  32/32 走满（29 ok、3 ctest_fail；另 4 个 ok 经勘误为表型无效）。best_overall =
  t0/e00057 **229.429s**（commit `1563c3d`），较 AM y0 363.995s 名义 -36.97%，
  但仍为 gsim 45.864s 的 **5.002x**，目标未达成；t1 best e00056 = 241.956s。
  两个 best 都在前两轮产生，后六轮没有刷新。`restart.max=2` 已耗尽，且进程快慢态
  尚未解决；若用户另行扩预算并先修测量协议，预备 y0=r003/e00057，建议 C/L/K=2/4/2。

- **r003/t1/s08 已完成，mask 缓存无正向证据，direct 写回机械胜出**
  （2026-08-23，[A0082](actions/A0082_step_t1s08_mask缓存与direct写回_20260823.md)）：
  e00083 紧凑缓存 active-tile mask/value = **419.534s**（CV 0，compile_s 2063.6s，
  loadavg 50.53）；e00084 移除幂等 target compare、恢复连续 copy/fill 与直接 sparse
  store = **378.064s**（CV 0，compile_s 2164.5s，loadavg 11.58）。两项均用完整 13
  开关表型通过 17/17 ctest 与 3 rep difftest，c2 raw-score winner 入 t1/main；因机器态
  不同且 c2 仍较低负载 e00080 名义慢 9.52%，不确认父节点收益。t0/t1 均 8/8，历史
  best 仍为 e00057 **229.429s**；下一 action = `run-summary`，本 action 未启动它。

- **r003/t0/s08 已完成，task 延迟取参败于回归门，byte 中性提示无正向证据**
  （2026-08-23，[A0081](actions/A0081_step_t0s08_task延迟取参与byte中性提示_20260823.md)）：
  e00081 `sys-task-lazy-member-args` 为 `ctest_fail`（16/17，compile_s 383.7s），
  因候选局部性 scaffolding 断言错误而未进入计时；e00082
  `scan-byte-neutral-hints` = **327.672s**（CV 0，compile_s 1220.3s），完整 14
  开关表型通过 17/17 ctest 与 3 rep difftest，但较 e00078 名义回退 9.33%，且
  loadavg 50.77 存在跨窗混杂，仅可判无正向证据。e00082 作为唯一 ok 机械入
  t0/main；t0 8/8、t1 7/8，历史 best 仍为 e00057 **229.429s**。下一 action =
  `r003/t1/s08 step`（K=2），本 action 未启动它。

- **r003 第 7 轮 round-summary 已完成**（2026-08-23，[A0080](actions/A0080_round-summary_第7轮跨轨迹小结_20260823.md)）：
  本轮四个候选均用完整表型通过 17/17 ctest、3 rep difftest 与编译门，但无新增
  正向性能证据。t0/e00077-e00078 均错过预注册收益门；t1/e00079-e00080
  分别较有效父节点 e00071 回退 5.87%/1.56%。控制流和 wide-mux 精修重开前均须
  先补动态权重，不再用静态站点/共享度作收益代理；另以 correction 明确 e00075/
  e00076 实际未启用候选机制。当前 t0/t1 各 7/8、evals 30/32，历史 best 仍为
  e00057 **229.429s**；下一 action = `r003/t0/s08 step`（K=2），本 action 未启动它。

- **r003/t1/s07 已完成，selector 摘要复用与幂等写抑制均证伪**（2026-08-23，[A0079](actions/A0079_step_t1s07_selector摘要复用与幂等写抑制_20260823.md)）：
  e00079 round-local selector summary reuse = **359.866s**（CV 0，compile_s
  1990.6s），e00080 idempotent store suppression = **345.215s**（CV 0，compile_s
  1983.1s）；两项均使用完整 13 开关父表型并通过 17/17 ctest、3 rep difftest，
  相对有效父节点 e00071 分别回退 5.87%/1.56%。c2 同窗快 4.07% 并机械入 t1/main，
  但两机制均无正收益。另勘误 e00075/e00076 缺少 `--wide-mux-chain-fuse`，实际未启用
  active-tile 候选，原性能结论作废。当前 t0/t1 各 7/8、evals 30/32，历史 best
  仍为 e00057 **229.429s**；下一 action = 第 7 轮 `round-summary`，本 action 未启动它。

- **r003/t0/s07 已完成，纠正表型后两项机制仍无正向证据**（2026-08-23，[A0078](actions/A0078_step_t0s07_前缀跳过与task触发提示实测_20260823.md)）：
  e00077 `scan-active-byte-prefix` = **312.027s**（CV 0，compile_s 1063.3s），
  e00078 `sys-task-fire-hints` = **299.715s**（CV 0，compile_s 1069.3s）；两项均以
  e00057 完整 12 开关父表型加候选开关评估，通过 17/17 ctest 与 3 rep difftest。
  c2 同 step 快 3.95% 并机械入 t0/main，但两者相对 e00057 名义慢 36.00%/30.63%，
  且比值落已知 1.3-1.4x 快慢态带，不能作纯机制幅度；两个预注册收益门均未达到。
  当前 t0 7/8、t1 6/8、evals 28/32，历史 best 仍为 e00057 **229.429s**；下一
  action = `r003/t1/s07 step`，本 action 未启动它。

- **r003 第 6 轮 round-summary 已完成**（2026-08-23，[A0077](actions/A0077_round-summary_第6轮跨轨迹小结_20260823.md)）：
  t0/s06 的 e00073/e00074 因候选 `emit_args` 漏传而是同一基础表型的重复计时，
  370.611s/346.687s 不得用于机制裁决；t1/s06 的 mask/value 栈缓存
  e00075 **363.823s** 与 single-level direct e00076 **354.543s** 分别较父节点
  e00071 回退 7.03%/4.31%，均证伪。本轮无新有效正向证据；候选表型审计升级
  为评估前/登记前硬检查，wide-mux 微结构重开须先有动态权重。当前
  t0/t1 各 6/8、evals 26/32，历史 best 仍为 e00057 **229.429s**；下一 action
  = `r003/t0/s07 step`，本 action 未启动它。

- **r003/t1/s06 已完成，两项 helper 微结构精修均慢于父节点**（2026-08-23，[A0076](actions/A0076_step_t1s06_mask缓存与单级direct_20260823.md)）：
  c1 e00075 紧凑缓存 active-tile 非零 mask/tval，Host **363.823s**（CV 0，
  compile_s 1982.6s），较 e00071 回退 7.03%；c2 e00076 为 151 条单级链使用 direct
  helper，Host **354.543s**（CV 0，compile_s 1995.9s），较 e00071 回退 4.31%。
  两项均通过 17/17 ctest、3 rep difftest，完整 11 开关表型已审计；c2 机械胜出并入
  t1/main，但两种机制均证伪。当前 t0/t1 各 6/8、evals 26/32，历史 best 仍为
  e00057 **229.429s**；下一 action = 第 6 轮 `round-summary`，本 action 不启动它。

- **r003/t0/s06 已消耗，但两候选因 emit_args 漏传判为无效测量**（2026-08-23，[A0075](actions/A0075_step_t0s06_候选表型漏传与无效测量_20260823.md)）：
  e00073/e00074 均过 17/17 ctest、3 rep difftest 与编译门，原始 Host 为
  **370.611s / 346.687s**；收口审计发现两份 result 都只有基础 10 开关，未启用
  `scan-active-byte-prefix` 或 `sys-task-fire-hints`，故分数不得作为机制证据。状态机已
  按 raw score 将默认-off 的 e00074 提交机械入 t0/main，t0 计为 6/8、evals 24/32，
  但历史 best 仍为 e00057 **229.429s**。ledger 已追加 correction；下一 action =
  `r003/t1/s06`，本 action 不启动它。

- **r003 第 5 轮 round-summary 已完成**（2026-08-23，[A0074](actions/A0074_round-summary_第5轮跨轨迹小结_20260823.md)）：
  t0/s05 的 `scan-active-byte-prefix` 与 `sys-task-fire-hints` 均因
  `grhsim-am-cpp-emitter` 回归断言失败（16/17 grhsim tests）被功能门否决，未产生
  性能分数；t1/s05 的 nonzero-level bitmap e00071 **339.910s** 胜 priority
  lane resolve e00072 **356.780s**，紧邻低负载窗口 c1 快 4.73%，已入 t1/main，
  但跨窗幅度仅记正向证据。当前 t0/t1 各 5/8、evals 22/32，历史 best 仍为 e00057
  **229.429s**；下一 action 由 `tesctl` 状态机给出。

- **r003/t1/s05 已完成，非零 level 压缩胜出**（2026-08-22，[A0073](actions/A0073_step_t1s05_非零level压缩与优先级去重_20260822.md)）：
  c1 e00071 在 active-tile union 时形成 <=64 层 nonzero bitmap，只重访实际非零层，
  Host **339.910s**（CV 0.02%，compile_s 1876.0s）；c2 e00072 逆序 priority resolve
  去除重叠 lane 写，Host **356.780s**（CV 0，compile_s 1870.1s）。二者均通过
  17/17 ctest、3 rep difftest 和编译门，较 e00067 名义 -11.06%/-6.64%；e00067
  与本轮起跑 loadavg 不同，跨窗幅度仅记正向。紧邻低负载窗口 c1 比 c2 快 4.73%，
  winner `2ac108f` 已入 t1/main。当前 t0/t1 各 5/8、evals 22/32，历史 best 仍为
  e00057 **229.429s**；下一 action = 第 5 轮 `round-summary`，本 action 不启动它。

- **r003/t0/s05 已完成但两候选均败于回归门**（2026-08-22，[A0072](actions/A0072_step_t0s05_前缀跳过与task触发提示回归门失败_20260822.md)）：
  c1 `scan-active-byte-prefix` e00069 与 c2 `sys-task-fire-hints` e00070 均为
  `ctest_fail`，各 16/17 grhsim tests 通过，分别因新增 prefix 文本断言和既有
  sys-task scaffolding 文本断言不匹配而失败；`compile_s=316.3/309.5s`，均未进入
  emit/emu/计时。两机制归类为“回归契约失败、未测”，不是性能证伪；无 winner，
  t0 主线不移动。当前 t0 5/8、t1 4/8、evals 20/32，历史 best 仍为 e00057
  **229.429s**；下一 action = `r003/t1/s05`，本 action 不启动它。

- **r003 第 4 轮 round-summary 已完成**（2026-08-22，[A0071](actions/A0071_round-summary_第4轮跨轨迹小结_20260822.md)）：
  t0/s04 机械 winner e00065 `--scan-active-byte-tree` = **409.869s**（CV 0，
  loadavg≈50 慢窗），相对 e00061 无正收益证据；e00066 nibble = **412.826s** 且
  CV 14% noisy，两种 active-byte 控制精修均关闭。t1/s04 winner e00067
  `--wide-mux-chain-active-tile-sparse` = **382.171s**（CV 0，compile_s 2136.2s），
  较 e00064 名义 -6.73% 并越 3% 门，但 loadavg 12.30 vs 50.18，暂定正向；e00068
  static-levels = **427.066s**，在相近高负载窗回退 4.23%，关闭。两轨迹各 4/8，
  evals 18/32，`best_overall` 仍为 e00057 **229.429s**；下一 action = `r003/t0/s05`，
  本小结不启动它。

- **r003/t1/s04 已完成**（2026-08-22，[A0070](actions/A0070_step_t1s04_活跃tile稀疏与固定层专化_20260822.md)）：
  c1 `--wide-mux-chain-active-tile-sparse` e00067 = **382.171s**（CV 0，compile_s
  2136.2s），较 e00064 名义 -6.73% 并越 3% 门，但起跑 loadavg 12.30 vs 50.18，
  仅记暂定正向；c2 `--wide-mux-chain-static-levels` e00068 = **427.066s**（CV 0，
  compile_s 2049.4s），在相近高负载起点下较 e00064 回退 4.23%，且 L4/L23 helper
  机器码展开 10.3x，原样方向关闭。两项均通过 17/17 ctest、3 rep difftest 与编译门；
  机械 winner e00067 已入 t1/main，t1/global best 仍为 e00056 **241.956s** / e00057
  **229.429s**。当前 t0/t1 各 4/8、evals 18/32；下一 action = 第 4 轮
  `round-summary`，本 action 不启动它。

- **r003/t0/s04 已完成**（2026-08-22，[A0069](actions/A0069_step_t0s04_ctz直接树与nibble分层守卫_20260822.md)）：
  c1 `--scan-active-byte-tree` e00065 = **409.869s**（CV 0），c2
  `--scan-active-byte-nibble` e00066 = **412.826s**（CV 14% noisy，第三 rep
  521.718s）；两项均通过 17/17 ctest、3 rep difftest 与编译门。两候选起跑
  loadavg≈50，均落约 410s 慢窗，相对低负载 e00061 的 63% 名义回退不可作纯机制
  幅度；c1/c2 仅差 0.72%，机械 winner e00065 已入 t0/main，但因果排名不可裁。
  direct-tree 去掉 jump-table rodata 却增加 text；nibble 守卫缩小 text 仍无正收益
  证据。t0/global best 保持 e00057 **229.429s**，当前 t0 4/8、t1 3/8、evals
  16/32；下一 action = `r003/t1/s04`，本 action 不启动它。

- **r003 第 3 轮 round-summary 已完成**（2026-08-22，[A0068](actions/A0068_round-summary_第3轮跨轨迹小结_20260822.md)）：
  t0/s03 winner e00061 `--scan-active-byte-ctz` = **251.746s**（较 e00057 名义
  +9.73%，机械入主线但机制证伪）；t1/s03 winner e00064
  `--wide-mux-chain-zero-tile-bypass` = **409.731s**（高负载窗较 noisy e00063
  快 17.31%，机械入主线但绝对收益未确认）。全局枚举/散写与 task 冷体纯布局
  精修关闭，只保留“局部 tile 门控 + 连续 base 流”作待动态计数量化方向。t0/t1
  历史 best 仍为 e00057 **229.429s** / e00056 **241.956s**，evals 14/32，
  best/gsim 看板比 **5.002x**；下一 action = `r003/t0/s04`，本小结不启动它。

- **r003/t1/s03 已完成**（2026-08-22，[A0067](actions/A0067_step_t1s03_mux稀疏覆盖与零tile旁路_20260822.md)）：
  recon 定量 23-level 链 selector 机会密度仅 **0.0188%**、99.57% lane 取 base。
  c1 sparse-overlay e00063 = **495.496s**（CV 8.73% noisy、loadavg 49.50），c2
  zero-tile-bypass e00064 = **409.731s**（CV 0、loadavg 50.18）；两项均通过
  17/17 ctest、3 rep difftest 与编译门，c2 同高负载窗口快 17.31% 成为机械 winner
  并入 t1/main。绝对值受高负载慢窗混杂，t1 best 仍为 e00056 241.956s，全局 best
  仍为 e00057 229.429s。当前 t0/t1 各 3/8、evals 14/32；下一 action = 第 3 轮
  `round-summary`，本 action 不启动它。

- **r003/t0/s03 已完成**（2026-08-22，[A0066](actions/A0066_step_t0s03_ctz稀疏派发与task冷段布局_20260822.md)）：
  c1 `--scan-active-byte-ctz` e00061 = **251.746s**（较 e00057 名义 +9.73%，
  ELF `.text` +2.48% / `.rodata` +7.67%），c2 `--sys-task-body-cold` e00062 =
  **300.215s**（名义 +30.85%；7,235 个 cold helper 落地、ELF `.text` -2.66%，
  但 e00062/e00057=1.308x 接近已知快慢态带）。两项均通过 17/17 ctest、3 rep
  difftest 与编译门，均未给出正收益；机械 winner e00061 已入 t0/main，但 t0/
  全局 best 仍为 e00057 229.429s。当前 t0 3/8、t1 2/8、evals 12/32；下一
  action = `r003/t1/s03`，本 action 不启动它。

- **r003 第 2 轮 round-summary 已完成**（2026-08-22，[A0065](actions/A0065_round-summary_第2轮跨轨迹小结_20260822.md)）：
  t0/s02 winner e00057 `--scan-branch-hints` = **229.429s**（较 e00054 名义
  -7.32%，刷新全局 best）；t1/s02 winner e00059
  `--wide-mux-chain-priority-resolve` = **257.235s**（较 e00056 名义 +6.32%，
  机械入主线但 t1 best 仍为 e00056 241.956s）。scan hints 结合 r002 同窗证据
  继续收敛为正向前端流机制；task-body compact 与两种 wide-mux helper 精修均无
  新正收益，后者须先补动态权重/二进制证据再重开。当前 t0/t1 各 2/8、evals
  10/32，best/gsim 看板比 **5.002x**；下一 action = `r003/t0/s03`，本小结不启动它。

- **r003/t1/s02 已完成**（2026-08-22，[A0064](actions/A0064_step_t1s02_宽mux链优先解析与单层tile快路_20260822.md)）：
  c1 多级链 priority-mask e00059 = **257.235s**，c2 单级链 tile/scatter e00060 =
  **358.271s**；两项均通过 17/17 ctest、3 rep difftest 与 2400s 编译门。生产形态
  为 151x1、1x4、4x23 条链，c2 精确命中 151 个单级调用。`e00060/e00059=1.393x`
  落已知快慢态带，故 c2 raw score 机械落败但纯机制幅度不可裁；c1 较 Φ 节点 e00056
  名义 +6.32%，也未产生正收益证据。机械 winner `d28a44f` 已入 t1/main，但 t1 best
  仍为 e00056 241.956s，全局 best 仍为 e00057 229.429s。当前 t0 2/8、t1 2/8、
  TES eval 计数 10/32；下一 action = 第 2 轮 `round-summary`。

- **r003/t0/s02 已完成**（2026-08-22，[A0063](actions/A0063_step_t0s02_扫描提示与task体压缩_20260822.md)）：
  c1 `--scan-branch-hints` e00057 = **229.429s**，c2
  `--sys-task-body-compact` e00058 = **252.374s**；两项均通过 17/17 ctest 与
  3 rep difftest，机械 winner `1563c3d` 已入 `t0/main`。相对 Φ 基座 e00054，c1
  名义 -7.32%，c2 +1.94%（c2 比 c1 慢 10.00%）；跨评估机器态仍要求保守归因，
  task-body-compact 压缩方向暂关闭。当前 t0 2/8、t1 1/8、TES eval 计数 8/32，
  `best_overall` = e00057，AM/gsim ledger 比约 **5.004x**；下一 action = `r003/t1/s02`。

- **r003 第 1 轮 round-summary 已完成**（2026-08-22，[A0062](actions/A0062_round-summary_第1轮跨轨迹小结_20260822.md)）：
  t0/s01 winner e00054 `--sys-task-body-outline` = **247.560s**，t1/s01 winner
  e00056 `--wide-mux-chain-fuse` = **241.956s**；四个候选均通过 17/17 ctest 与
  3 rep difftest。两条轨迹的机械 winner 均有效，但候选跨窗口，1.348x/1.352x
  落入已知快慢态带，名义 -31.99%/-33.53% 不作纯机制幅度；r002 同窗证据仍是
  task-outline 约 -5.91%、wide-mux 约 -2.19%/-1.17% 的因果口径。当前
  当时 `best_overall` = e00056，AM/gsim ledger 比 **5.276x**；该 round-summary
  不启动下一步。

- **r003/t1/s01 已完成**（2026-08-22，[A0061](actions/A0061_step_t1s01_活动摘要与宽mux链融合_20260822.md)）：
  两个实质候选均全门通过。c1 `--activity-summary-scan` e00055 = **270.003s**
  （CV=0，名义 -25.82%，生产模型 `activitySummary_` 静态引用 512,153 处）；c2
  `--wide-mux-chain-fuse` e00056 = **241.956s**（CV=0.41%，名义 -33.53%，
  engagement 156 chains/247 levels/74 blocks），机械 winner `014c3ae` 已入
  t1/main，当前 AM/gsim ledger 比为 **5.276x**。但 e00051/e00055=1.348x 落历史
  快慢态带，c2/c1 的 -10.39% 也跨窗口且大于 r002 同窗机制量级；分数与 winner
  有效，纯因果幅度保留。当前 t0 1/8、t1 1/8、TES eval 计数 6/32（含双基线）；
  next = 第 1 轮 `round-summary`。
- **r003/t0/s01 已完成**（2026-08-22，[A0060](actions/A0060_step_t0s01_scan提示与冷体outline_20260822.md)）：
  两个实质候选均全门通过。c1 `--scan-branch-hints` e00053 = **334.687s**
  （CV=0，较 e00051 名义 -8.05%）；c2 `--sys-task-body-outline` e00054 =
  **247.560s**（CV=0，名义 -31.99%），机械 winner `b1f2c8d` 已入 t0/main，
  当前 AM/gsim ledger 比为 **5.398x**。但 c1/c2 = **1.352x**，落在 r002 已检出的
  per-process 快慢态 1.3-1.4x 带内，且两候选跨窗口；因此不能把 c2 的 31.99%
  全归因于 outline，也不能据此可靠比较两机制真实强弱。两项均有 r002 同输入同窗
  正向先验并完成代码/功能迁移。当前 t0 1/8、t1 0/8、TES eval 计数 4/32（含双基线）；
  next = `r003/t1/s01`，保持轨迹独立。
- **r002 已收口**（2026-08-21，[A0058](actions/A0058_run-summary_r002收口与restart建议_20260821.md)，
  详见 [runs/r002/summary.md](runs/r002/summary.md)）：C=2/L=8/K=2，16/16 步走满，
  候选 32/32 恰好耗尽、全 ok。真值 best：t0 tip **295.042s**（快态簇锚）/
  301.081s（e00027 同窗确认 -11.41%）；t1 **322.762s**（e00029）；对 gsim
  ≈6.3-6.4x，目标未达成。ledger best e00007（261.543s）已 overturn（双态
  快态抽签）。确认机制族：scan-branch-hints × task body outline 族 ×
  gsim-aligned 调度点 × wide-mux-chain-fuse × concat-insert-inline 迁移
  （跨轨迹迁移三连中，捕获率 ~46% 双侧一致）；commit 相省指令/省往返/门控类
  整体关闭；残余开放池 = compute 长尾 ~52% + commit 数据侧。**裁决：建议
  restart**（y0 = t0 tip `79719b2d`，C/L/K 维持 2/8/2；restart.max=1 已消耗，
  r003 需用户放宽预算并先定基线重锚与 rep 级簇分组裁决）
- t1/s08（2026-08-21，[A0057](actions/A0057_step_t1s08_concat插入内联跨轨迹迁移与安慰剂锚点_20260821.md)）：
  **c1 concat-insert-inline 跨轨迹迁移确认 -6.26%**（t0 链 r001 起携带、首次迁入
  t1：单字退化 splice 从 outlined insert_words 动态循环改内联单语句；338.367s vs
  同窗安慰剂 361.025s，越 4% 假设门；engagement 站点 276,059→15,326，.o -8.4%，
  emu_build 无膨胀）；**recon-t1s07 刷新 t1 池地图**（hinted emu perf 45,319 样本：
  helper 首位易主 insert_words 11.61%；eval_scan annotate 证实跳过链 ~0%，dispatch
  骨架轴 t1 侧直接证据关闭）；跨轨迹迁移三连中。**t1 走完 8/8，r002 两轨迹收官**，
  evals 候选口径 32/32 用完；t1 真值口径 = 本窗 338.367s（锚 361.025s）。下一
  action = 第 8 轮 round-summary → run-summary
- t0/s08（2026-08-21，[A0056](actions/A0056_step_t0s08_MemoryFill使能门控与批内双态检出_20260821.md)）：
  **c1 memory-fill-enable-gate 证伪**（mem.fill 折入 cond 门控逐元素 detect 扫描，
  engagement 191 站/41,748 元素，off 逐字节等价实证；321.922s vs 同窗安慰剂快态簇
  295.042s = **+9.1% 回退**，commit 相「条件门控省流量」首试即败、不携带）；
  **测量学突破：批内首次直接检出 per-process 双态抽签**（安慰剂同批 3 rep
  295.0/389.2/295.0s，CV 12.35% 触发 5 rep，混合 median 343.664s 为 artifact 且
  反转了机械 winner——finish-step 按记分板合入 c1，内容无害：旋钮默认 off 逐字节
  等价）；**dispatch 骨架轴以 annotate 直接证据关闭**（recon-t0s07 hinted emu perf：
  eval_scan_* 46.61% 自时间全为内联块体、跳过链 ~0%）。t0 tip 真值口径 = 快态锚
  **295.042s**（历史最快）；t0 走完 8/8。evals 32/32（候选口径 30/32，余 2 =
  t1/s08）；下一 action = t1/s08（A0055 裁定，recon 先行）。协议升级提请：rep 级
  按快/慢簇分组裁决，弃用跨簇 median
- r002 第 7 轮 round-summary（2026-08-21，[A0055](actions/A0055_round-summary_第7轮跨轨迹小结_20260821.md)）：
  两轨迹各完成 s07，**scan-branch-hints 双双同窗确认——t0 -11.41%**（301.081s
  vs 安慰剂 339.849s，捕获 ≈ 骨架池 75-80s 的 ~50%，r002 单步最大确认收益）
  **× t1 迁移 -5.69%**（322.762s vs 安慰剂 342.230s，捕获 ~23%，落 5-7% 外推
  区间；提示数 105,479×105,485 逐数互证），双双历史最低、均已入主线。收敛：
  **dispatch 骨架跳过链亚池两轨迹兑现约半、骨架轴接近关闭**；**跨轨迹迁移二连
  中**（宽链融合 × scan-branch-hints，均为「不省指令、改数据/取指流形态」类）；
  **「前端流式主导、省指令无效」判据正向逆用第二次成立**；残余开放池归拢 =
  compute 长尾本体（~52% 双侧）+ commit 相纯数据侧。测量学：锚点席位连续第六轮
  2/4，跨窗漂移样本七点且本轮双窗反向（t0 +3.7% × t1 -6.1%）。真值口径：t0 tip
  301.081s / t1 tip 322.762s（均同窗锚点口径）。**s08 归属裁定：余 2 evals 给
  t1**（池地图最陈旧 + compute 长尾 ≈169s 最大残余池；recon-t1s07 先行），t0/s08
  空转。evals 30/32
- t1/s07（2026-08-21，[A0054](actions/A0054_step_t1s07_scan分支提示跨轨迹迁移与安慰剂锚点_20260821.md)）：
  **winner e00029 = 322.762s（`--scan-branch-hints` 跨轨迹迁移，t1 历史最低）**——
  t0 A0053 同态 -11.41% 机制 cherry-pick 到 t1 链（74b6d1e，2 处冲突手工解决、
  剔除 t0 独有 sysTaskOutline 伴生代码，diff 与原 patch 同形 +261/-19）；同窗
  安慰剂 e00030（t1 tip 原样 + 6 旋钮）**342.230s** → **-5.69% 确认**（越 4%
  假设门，落 5-7% 外推区间；提示 105,485 处与 t0 105,479 逐数互证扫描链同构）。
  捕获 ~23%（t1 池含 activity-summary-scan 已压部分，较 t0 ~50% 薄）。跨轨迹
  迁移二连中，「前端流式主导、省指令无效」判据正向逆用第二次成立。t1 有效
  emit_args = CLI 默认调度点 + 5 旋钮 + wide-mux-chain-fuse + scan-branch-hints；
  真值口径 = 本窗锚点 342.230s、含 hints tip 本窗 322.762s。测量学：跨窗漂移
  样本第七点（t1 tip 原样 364.464→342.230s，-6.1% 快向）。evals 30/32（余 2 =
  恰好一条轨迹的完整 s08）；下一 action = 第 7 轮 round-summary，裁定 s08 归属
- t0/s07（2026-08-21，[A0053](actions/A0053_step_t0s07_scan分支提示与安慰剂锚点_20260821.md)）：
  **winner e00027 = 301.081s（`--scan-branch-hints`，r002 单步最大确认收益）**——
  先按 A0052 纪律做归因 recon（recon-t0s06，生产 emu perf 32k 样本）：dispatch
  骨架无名池 = **eval_scan_* 内跳过链 ≈75-80s/Host 22-24%**（eval() 自身 ≈0、
  激活簿记在块 tick 窗内、commit 骨架 ≈1s，三嫌疑两清），病因 = 每块位测试与
  ~945B 块体交错的大步长取指流。c1 给 byte 序言与逐块位测试加
  `__builtin_expect(..., 0)`（b9a671a，off 260 文件 cmp 全等 + 剥壳归一化 +
  harness oracle，objdump 实证 fall-through ~13B/站紧凑链 + 冷区分层外置，.o
  text -0.15% 持平）；同窗安慰剂 e00028（t0 tip 原样 + 12 旋钮）**339.849s** →
  **-11.41% 确认**（越 4% 门近 3 倍，c1 低于 t0 全部历史读数，双态/漂移无法
  吸收；捕获 ≈ 池的 50%）。「前端流式主导、省指令无效」判据的正向逆用例证。
  t0 有效 emit_args = 12 旋钮 + scan-branch-hints；真值口径 = 本窗锚点
  339.849s、含 hints tip 本窗 301.081s。evals 28/32（余 4）；**t1/s07 首选
  scan-branch-hints 跨轨迹迁移（t1 骨架池 ~104s × ~50% ≈ 5-7% 外推）**
- r002 第 6 轮 round-summary（2026-08-21，[A0052](actions/A0052_round-summary_第6轮跨轨迹小结_20260821.md)）：
  两轨迹各完成 s06。**t0 c1 `--commit-row-merge` 同窗 +3.25% 决定性证伪**（静态
  确切成立但串行 `cur` 链替换可流水 STLF 行往返；winner = 安慰剂锚点 e00024
  **327.602s** = t0 历史最快、快窗）；**t1 c1 wide-mux-chain-fuse 跨轨迹迁移
  同窗 -1.17% 确认**（越 1.0% 门，已入 t1/main）。收敛：**宽链融合 = 首个可
  定量跨轨迹迁移机制族（收益/池比 ~46% 两轨迹一致，链轴双侧关闭）**；**commit
  相省指令/省往返类三次证伪整体关闭**；**两轨迹下一阶开放池同向 = dispatch 骨架
  无名池（t0 ~95s/26% × t1 ~104s/26%，全 run 最大单池，先归因 recon 再候选）**。
  测量学：锚点席位连续第四轮 2/4，同代码跨窗漂移样本累计五点。**末段座位裁决：
  余 6 evals vs 8 席缺 2——s07 两轨迹保持机制+锚点，s08 只剩一条轨迹的完整
  step（归属 s07 收口时裁定），锚点不砍**。真值口径：t0 tip 327.602s / t1 含
  fuse tip 364.464s（均同窗锚点口径）；基线重锚仍待用户。evals 26/32
- t1/s06（2026-08-21，[A0051](actions/A0051_step_t1s06_宽链融合跨轨迹迁移与安慰剂锚点_20260821.md)）：
  **winner e00025 = 364.464s**（`--wide-mux-chain-fuse` 跨轨迹迁移：t0 A0047
  同态 -2.19% 机制 cherry-pick 到 t1 链，4471846，冲突解决后 diff 与原 patch
  同形 +854/-4，已入 t1/main）；同窗安慰剂 e00026（t1 tip 原样 + 5 旋钮）
  **368.763s** → **-1.17% 确认**（越 1.0% 假设门，量级 = 池 2.25% × t0 捕获率
  ~46% 外推精确命中）。engagement chains=156/levels=247/blocks=74 与 t0 逐数
  一致，emit 源持平（-2.2KB）= 纯访存流收益。**首个可定量跨轨迹迁移机制族**
  （收益/池比 ~46% 两轨迹一致）；b69159 族链轴 t1 侧关闭。测量学：同代码跨窗
  漂移 +2.6% 反转样本（359.269→368.763s）。t1 有效 emit_args = CLI 默认调度点
  + 5 旋钮 + wide-mux-chain-fuse。evals 26/32（余 6 vs 剩余 10 席）
- t0/s06（2026-08-21，[A0050](actions/A0050_step_t0s06_commit行RMW合并与安慰剂锚点_20260821.md)）：
  **c1 `--commit-row-merge` 证伪**（96429a6：commit Block 同 key 严格相邻
  MemoryWrite(Cond)Mask run 融合为单次索引+单 load+单 store，runs=120/
  events=3084/blocks=35，off 260 文件 cmp 全等 + oracle 等价单测）——
  e00023 = 338.247s，同窗安慰剂 e00024（t0 tip 原样 + 12 旋钮）**327.602s**
  → **+3.25% 回退**（`cur` 串行链替换可流水 STLF 行往返，关键路径变长）。
  **commit 相省往返/省指令类连续两次静态成立动态为负，行合并类并入关闭
  清单**。winner = e00024（安慰剂空 commit ab20b29，t0/main 内容不变）。
  recon-t0s05：总 tick -2.20%（与 e00019 -2.19% 互证），**b69159 族
  15.4G→2.5G（-84%）链轴关闭**；t0 侧首次定量 dispatch 骨架无名池
  ~95s/26%（compute 墙钟 269.3s vs tick 折时 174.5s，与 t1 同族）。
  真值口径：t0 tip 本窗 **327.602s**（t0 历史最快、快窗）。evals 24/32
  （余 8 vs 剩余 10 席，末段需单候选）
- r002 第 5 轮 round-summary（2026-08-21，[A0049](actions/A0049_round-summary_第5轮跨轨迹小结_20260821.md)）：
  两轨迹各完成 s05。**t0 winner e00019 wide-mux-chain-fuse 同窗 -2.19%**（335.129s
  vs 安慰剂 342.632s，方向确认、量级落中间带，宽数组流扫族在 r002 首个正收益，
  已入 t0/main）；**t1 c1 commit-write-branchless 同窗 +1.71% 证伪**（静态形态
  成立但恒写 dirty 流量为负，误预测非 b93159 族主导），winner = 安慰剂锚点
  e00022（t1/main 内容不变）。收敛：**commit 相省指令/分支结构类跨轨迹整体关闭**
  （与 t0 A0041 数据侧 miss 主导互证），残余开放方向 = 数据侧机制 + compute 相
  本体 + t1 新发现的最大无名池（compute 墙钟/tick 缺口 ~104s/26%）。测量学：
  同代码跨窗漂移升格 ±5% 级连续分量，任意跨窗读数一律不裁。真值口径：t0 tip
  本窗 335.129s、t1 tip 本窗 359.269s；vs 基线 ratio 仍不可裁。evals 22/32
  （余 10 vs 剩余 12 候选席，末段或需单候选）
- t1/s05（2026-08-21，[A0048](actions/A0048_step_t1s05_commit写点无分支化证伪与安慰剂锚点_20260821.md)）：
  **c1 `--commit-write-branchless` 证伪**（01078eb：ST00013 写点检测内层分支改
  条件移动 + flag OR 累积，off 259 文件 cmp 全等，on 全量转换 141,169 站、
  反汇编证实分支消除+SSE 向量化成立）——e00021 = 365.427s，同窗安慰剂 e00022
  （t1 tip 原样 + 5 旋钮）**359.269s** → **+1.71% 回退**（分支消除带来恒写
  dirty 流量，误预测非该族主导成本）。**commit 写点分支结构轴关闭**，与 t0
  A0041 互证 commit 相数据侧 miss 主导。winner = e00022（安慰剂空 commit
  f167ae7，t1/main 内容不变）。recon-t1s05（新调度点首池地图）：总 702.1G
  tick，commit 31.8%（b93159 族 43 块 31.1%、b93159 45cyc/atom）/ compute
  68.2%，**compute 墙钟/tick 缺口 ~104s（26%）为最大无名池**。t1 tip 真值
  本窗 359.269s。evals 22/32
- t0/s05（2026-08-21，[A0047](actions/A0047_step_t0s05_宽广播mux链融合与安慰剂锚点_20260821.md)）：
  **winner e00019 = 335.129s**（`--wide-mux-chain-fuse`：broadcast(64 位源)→
  mux(elemWidth==64) 跨 atom 严格相邻链融合为单 pass helper，基座折叠、中间
  352-word 数组不物化，61b5fd6，off 逐字节等价，已入 t0/main）；同窗安慰剂
  e00020（t0 tip 原样）342.632s → **同态 -2.19%**（方向确认，未越 3% 假设门、
  过 1.5% 证伪线）。静态实证：engagement chains=156 levels=247 blocks=74，
  22528 宽链全融合（bcast 106→3、mux 117→18），.o 总字节持平（纯访存流收益）。
  **测量学新证据：同代码跨窗漂移 ±5% 级（342.632 vs 上窗同代码 361.053/
  339.654），超出双态 ×1.39 框架，机器态含连续漂移分量**。recon-t0s04（outline
  后池地图）：总 tick -6.9%，守卫池 9.28%→5.84%（outline 插桩侧确认），commit
  33.8% / compute 长尾 52.8%。本窗锚点 342.632s，t0 tip 本窗 335.129s。
  t0 有效 emit_args = 11 旋钮 + wide-mux-chain-fuse。evals 20/32
- r002 第 4 轮 round-summary（2026-08-21，[A0046](actions/A0046_round-summary_第4轮跨轨迹小结_20260821.md)）：
  两轨迹各完成 s04，双双同窗确认越门：**t0 e00015 sys-task-body-outline 同态
  -5.91%**（339.654s vs 安慰剂 361.053s）、**t1 e00017 gsim-aligned 调度点迁移
  -8.44%**（368.963s vs 安慰剂 402.978s）。收敛：守卫池瘦身路线跨形态闭环
  （t0 整块守卫 × t1 内嵌 task atom 同族确认，该轴兑现完毕关闭）、调度点一阶
  效应跨轨迹互证（t0 -16.4% × t1 -8.44%，两轨迹同调度点基后该轴关闭）、
  安慰剂锚点连续两轮 2/4 席产出全部裁决基准。真值口径：t0 tip ≈339.7s
  （常态窗）、t1 tip ≈369.0s；vs 基线 ratio 仍不可裁。evals 18/32，行程过半；
  下一步 t0/s05 与 t1/s05 均需先跑新 recon 再触 compute 相/commit 相数据侧。
- t1/s04（2026-08-21，[A0045](actions/A0045_step_t1s04_gsim-aligned调度点迁移与安慰剂锚点_20260821.md)）：
  **winner e00017 = 368.963s**（调度点单变量：回落 CLI 默认 gsim-aligned 点，
  t1 旋钮链不变，520b017 旋钮类空 commit，已入 t1/main）；同窗安慰剂 e00018
  （t1 tip 原样 + config 调度点）402.978s → **同态 -8.44% 确认**（越 6% 假设门）。
  静态实证：blocks .o text -4.3%。调度点一阶效应跨轨迹收敛（t0 -16.4% × t1
  -8.44%），两轨迹自此同调度点基。**t1 有效 emit_args = CLI 默认调度点 + 5 旋钮**
  （resize-elision/inline-scalar-helpers/inline-scalar-constants/
  activity-summary-scan/task-body-outline）；t1 tip 真值 ≈369s（本窗）。
  evals 18/32，t0/t1 各 4/8 齐平，下一步 = 第 4 轮 round-summary。
- t0/s04（2026-08-21，[A0044](actions/A0044_step_t0s04_sys-task-body-outline与安慰剂锚点_20260821.md)）：
  **winner e00015 = 339.654s**（`--sys-task-body-outline`：全部 7,235 个非 final
  fwrite 站体重活抽为 noinline 成员函数，e43ff4d，off 逐字节等价，已入 t0/main）；
  同窗安慰剂 e00016（t0 tip 原样）361.053s 锚定本窗=常态 → **同态 -5.91% 确认**
  （越 4% 假设门，双态 ×1.39 无法吸收）。静态实证：TaskFormatter 内联站
  7,235→0，b90656/90657 所在 TU .o text -50.3%/-47.7%，全模型 blocks text -7.9%。
  守卫池瘦身路线在 t0 整块守卫上闭环（A0041 预言路径确认）。**t0 tip 真值（常态窗）
  363.4s → 339.7s**。t0 有效 emit_args = 10 旋钮 + sys-task-body-outline。
  evals 16/32
- r002 第 3 轮 round-summary（2026-08-21，[A0043](actions/A0043_round-summary_第3轮跨轨迹小结_20260821.md)）：
  两轨迹各完成 s03。本轮最重要裁决：**ledger best e00007（261.543s）被三重证据
  overturn 为双态快态抽签**（安慰剂回读 363.444s = 261.543×1.389 精确落带），
  t0 tip 真值 ≈363s；**t1 winner e00013 task-body-outline 同态 -10.91% 确认**
  （375.670s vs 安慰剂 421.673s，b116236 TU text -75%）。收敛：同窗安慰剂席位
  常态化（本轮 2/4 席、产出两个最重要裁决）、守卫池机制轴收敛为代码瘦身单轴
  （t0 门控证伪 → t1 瘦身确认闭环）。关闭清单扩大：守卫门控（整块/run 级）与
  commit 省指令类关闭，候选空间向 compute 相（67% tick 未触探）集中。
  基线重锚仍待用户裁决。evals 14/32
- t1/s03（2026-08-21，[A0042](actions/A0042_step_t1s03_task体outline与安慰剂锚定_20260821.md)）：
  **winner e00013 = 375.670s**（`--task-body-outline`：无参 fwrite 冷体共享
  outline + DPI String 免 per-site 拷贝，b9a888c，off 逐字节等价，已入 t1/main）；
  同窗安慰剂 e00014（t1 tip 原样）421.673s 锚定本窗=快态 → **同态 -10.91% 确认**
  （越 5% 假设门，双态 ×1.3-1.4 方向相反无法吸收）。静态实证：b116236 TU .o
  text 3.56MB→0.89MB（-75%），task_write_const 5,937 站，DPI String 拷贝
  6,412→0。**t1 tip 快态带锚定 414.867/421.673s**（e00009 量级维持不可裁）。
  t1 有效 emit_args 追加 task-body-outline。evals 14/32
- 当前 run：**r002 已收口**（2026-08-21，A0058；C=2, L=8, K=2，N=32；base/y0 = r001 best
  `9c0a89db`；总结见 [runs/r002/summary.md](runs/r002/summary.md)）。无活跃 run，
  r003 已完成启动前准备但按用户要求尚未启动
- 基线（2026-08-20，新机器 + clang 21.1.8 + rep 绑核并行协议，3-rep 中位）：
  AM y0 = **619.0s**（e00001，CV ~0.0%）；gsim target = **46.8s**（e00002，
  CV ~0.0%）；**起跑差距 13.23x**。**⚠ 基线完整性红旗（A0035）**：e00001/e00002
  测于晨间慢机器态，同配置下午参照 452.8s（差 27%），vs 基线/gsim 的 ratio
  暂不可裁，待重锚
- t0/s03（2026-08-21，[A0041](actions/A0041_step_t0s03_守卫run门控与安慰剂锚点_20260821.md)）：
  **e00007 归因 overturn**——recon-t0s03（t0 tip + 10 旋钮插桩）块 tick/插桩 Host
  与 e00003 等价物双持平，安慰剂 e00012 同窗回读 **363.444s = 261.543×1.389**
  精确落双态带：`wide-detect-fast-path` 机制亚分辨中性，ledger best 261.543s 为
  快态抽签，**t0 tip 真值 ≈363s（常态窗）**；c1 `--guard-run-event-gating`
  （723c94e，run 级守卫门控，engagement 命中 b90656/90657 ~8953 atoms）
  370.498s = 同窗 +1.94% **证伪**（守卫块激活与门开 round 重合，无空闲重估可跳；
  守卫门控轴关闭，commit 省指令轴关闭——b93159 族为数据侧 miss 主导）。
  winner = e00012（安慰剂空 commit，t0/main 内容不变）。evals 12/32
- r002 第 2 轮 round-summary（2026-08-21，[A0040](actions/A0040_round-summary_第2轮跨轨迹小结_20260821.md)）：
  两轨迹各完成 s02，round best = e00007 **261.543s**（t0/main；vs 基线/gsim ratio
  因基线慢态污染维持不可裁）。收敛：**recon 驱动成标准前置**（两 recon 互证
  rounds 恒定 2.00/eval、commit 巨块池 ~30%）；**r001 两大机制族在新图各获首个
  一阶量级候选**（t0 宽站 detect 快速路径机制确认、t1 二级摘要扫描方向为正量级
  不可裁）；守卫池布局路线关闭（e00008）。evals 10/32。**勘误（A0041）**：t0
  e00007 机制经 recon+安慰剂三重证据 overturn 为快态抽签，tip 真值 ≈363s
- t1/s02（2026-08-21，[A0039](actions/A0039_step_t1s02_二级活动摘要扫描与同窗安慰剂_20260821.md)）：
  recon 驱动（recon-t1s02：commit 29.7%、43 commit 巨块独占 29.0%、b116236
  单块 12.63% 前端绑定、扫描骨架墙钟缺口 ~50%）；**winner e00009 = 414.867s**
  （`--activity-summary-scan` 二级活动摘要扫描，2,076 探针 + 576,615 镜像站点，
  off 逐字节等价，已入 t1/main；t1 有效 emit_args = config 调度 + 3 旋钮 +
  activity-summary-scan）；**机制量级不可裁**：同窗安慰剂 e00010（t1 tip 原样）
  574.637s 锚定本窗=慢态，c1 同窗名义 -27.8% 但双态翻转可吸收，c1 读数低于
  快态带下沿提示机制方向为正（2%~28% 不可裁），t1/s03 需同态锚定。evals 10/32
- t0/s02（2026-08-20 晚，[A0038](actions/A0038_step_t0s02_宽站detect快速路径与守卫变量聚簇_20260820.md)）：
  recon 驱动（recon-t0s02：commit 相 32.4% 集中、43 宽站巨块独占 31.7%、守卫
  双块 9.2%、rounds 恒定 2.00/eval）；**winner e00007 = 261.543s**
  （`--wide-detect-fast-path`，commit 宽站 memcmp/memcpy 快速路径，名义
  -27.9%，同窗逻辑控制排除机器态抽签，已入 t0/main；t0 有效 emit_args =
  默认调度 + 9 旋钮 + wide-detect-fast-path）；c2 守卫变量聚簇 358.456s
  亚分辨证伪（9.2% 池非散射 miss 主导，守卫布局路线关闭）。evals 8/32
- r002 第 1 轮 round-summary（2026-08-20，[A0037](actions/A0037_round-summary_第1轮跨轨迹小结_20260820.md)）：
  两轨迹各完成 s01，round best = e00003 **362.869s**（对同窗 config 参照 452.803s
  **-19.86%**；vs 基线 ratio 因基线慢态污染不可裁）。收敛：**常量/状态瘦身族在新
  输入图整体关闭**（t0 死宽池 0.46% 证伪 × t1 常量内连同频中性互证）；发散：
  **调度点一阶（gsim-aligned 单变量 -16.4%），分区/调度轴重开**（旧图 NO0002
  不适用新输入）。现协议只可分辨 ≥30% 效应，协议升级（机器态记录/跨窗口批次/
  基线重锚）待用户裁决
- t1/s01（2026-08-20，[A0036](actions/A0036_step_t1s01_t1链迁移与常量内联重实现_20260820.md)）：
  winner e00006 = 443.899s（**快窗口抽签，非机制收益**；`--inline-scalar-constants`
  重实现：12,795 只读窄常量/711,978 读取点字面量化，off 逐字节等价，已入 t1/main；
  验证同频 3.7GHz 下与 c1 差 -1.6%/-6.1% = 机制中性）。**刻画 ×1.3-1.4 双态环境
  混杂**（快簇 ~430s/慢簇 ~590s，20-40min 翻转；频率轨迹证伪 CPU 频率，嫌疑
  THP/NUMA 页放置）：现协议只能分辨 ≥30% 效应；t1 常量/状态瘦身族在新图关闭；
  测量协议升级（rep 期机器态记录/跨窗口批次/基线重锚）提请用户裁决
- t0/s01（2026-08-20，[A0035](actions/A0035_step_t0s01_机制链迁移与死宽态消除_20260820.md)）：
  winner e00003 = **362.869s**（gsim-aligned 默认调度点 + r001 t0 winner 9 旋钮链，
  已入 t0/main；t0 有效 emit_args = CLI 默认调度 + 9 旋钮）。因子分解：调度点
  一阶（gsim-aligned 比 config 点快 16.4%，分区轴在 r002 重开）、旋钮链在
  config 点上 -14.1%；死态瘦身族证伪（新图死宽池仅 0.46%）。测量教训：
  evaluator `--emit-args` 为整体替换，候选须显式携带调度点全参数
- r002 环境刻度：AMD EPYC 9654（384 线程）；输入切换为 wolvrix 自解析
  post-stats JSON（sha256 cbd78c0b…3246，取代 gsim 导出 exec-GRH）；rep 批内
  并行绑独立物理核（12/13/14），并行批均匀抬升 ~15-18%（AM +14.8%、gsim
  +18.1%，两侧同协议可比）；r001 绝对读数自此仅作历史
- r001 已收口（2026-08-20，A0033）：best **194.2s**（e00045 `9c0a89db`，旧机
  较 AM y0 -28.89%、gsim 7.87x、差距关闭 31.75%）；轨迹 best t0 194.2 /
  t1 219.0 / t2 254.5；候选 48/48 走满（ok 44 / compile_timeout 3 /
  difftest_fail 1）。机制族裁决与 restart 建议（已采纳为 r002 y0 与 C/L/K）见
  [runs/r001/summary.md](runs/r001/summary.md)
- r001 各 step/round 笔记见 [actions/](actions/)（A0001–A0033，append-only）

## 本任务构成

- `brief.md` — 常驻任务指令（目标、硬约束、已知机制背景）
- `protocol.md` — 评估协议（Φ 会原样内联进每个 proposal）
- `playbook.md` — 任务专属操作细节（基线流程、候选评估命令、结果解读）
- `config.json` — 默认参数与路径（run-init 冻结）
- `evaluator.py` — 评估器 V：`run`（候选/基线全流水线）与 `gsim`（现存 emu 协议化计时）两模式
- 评估构建规则见 [`playbook.md`](playbook.md)「构建与依赖复用」：候选 `wbuild`/
  `emu_build` 按 eval 隔离，FetchContent 依赖与 `build/tes/ccache` 复用，正式评估
  不联网；不要把新 build 目录误解为重新下载依赖
- `state/` — `run.json`、`ledger.jsonl`（append-only）、`insights.md`
- `actions/` `proposals/` `runs/` — action 笔记、Φ 快照、run 清单/总结
- 评估输入：wolvrix 自解析 XiangShan SV 的归一化 GRH（post-stats JSON，路径见 config `inputs`，run-init 记 sha256；r002 起取代 gsim 导出的 exec-GRH）

## 快速命令

评估前先遵守上面的“构建与依赖复用”规则：候选 build 目录隔离，FetchContent
依赖和 ccache 复用，不联网、不手工重建依赖。

```bash
python3 tes/tools/tesctl.py status            # 状态
python3 tes/tools/tesctl.py next              # 下一个 action
python3 tes/grhsim-am-coremark/evaluator.py run --worktree <wt> --eval-id eNNNNN
python3 tes/grhsim-am-coremark/evaluator.py gsim --eval-id eNNNNN
```
