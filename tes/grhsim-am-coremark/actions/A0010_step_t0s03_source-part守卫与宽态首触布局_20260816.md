# A0010 - step r001/t0/s03：source-part 守卫与宽态首触布局

日期：2026-08-16。action 类型：step（trajectory t0, step 3, K=2）。
proposal：`tes/grhsim-am-coremark/proposals/r001-t0-s03.md`（Phi 仅从 t0 选中
e00004、e00010；候选设计与裁决未使用其他轨迹结果）。两候选均继承 t0 主线的
`--branchy-mux --resize-elision`，并叠加已在 t0/s02 证明运行时中性的
`--init-zero-elision`，以解除布局类候选的编译预算风险。

## 候选设计与可证伪假设

### c1 `--source-part-activity-guard` - 静默 source-part 快速跳过（emit 规则面）

- 分支 `tes/r001/t0/s03-c1`（tip commit `96b8df2`；init-zero 前置 commit
  `af3f1f6`），worktree `build/tes/grhsim-am-coremark/src/e00015-t0-s03c1`，
  eval e00015。
- emit-args：`--block-chunk-instructions 3000 --branchy-mux --resize-elision
  --init-zero-elision --source-part-activity-guard`。
- 机制：每个静态 `eval_scan_*` / `eval_commit_*` part 调用前，按该 part 的精确
  Block 区间聚合检查 `activeWords_`；区间全静默时跳过函数调用和内部逐 byte
  activity 扫描。首尾 64-bit word 使用区间 mask，避免读入相邻 part 或另一相位
  的活动位；前序 part 的同轮 `act.f` 已在后序 guard 前写入活动字，因此前向传播、
  `act.b` 和收敛轮次语义不变。完整模型生成 **334 个守卫调用点**（compute 248，
  commit 86）。
- **假设**：精确 64-bit source-part activity 区间守卫可跳过静默 part 的函数调用
  与逐 byte 扫描，使 Host 中位相对 e00010 降低至少 3%，且 difftest/ctest 全过。
- 变更默认 off，关闭时调用序列保持原样；CLI、文档、单元测试和生成模型语义测试
  随候选提交。GRH IR 与 AM IR 均未改变。

### c2 `--wide-storage-first-touch` - 宽状态按调度首触顺序打包（emit 布局规则面）

- 分支 `tes/r001/t0/s03-c2`（tip commit `847e020`；init-zero 前置 commit
  `631f136`），worktree `build/tes/grhsim-am-coremark/src/e00016-t0-s03c2`，
  eval e00016。
- emit-args：`--block-chunk-instructions 3000 --branchy-mux --resize-elision
  --init-zero-elision --wide-storage-first-touch`。
- 机制：仅重排 `wideValues_` 中宽 BitVector/Array 的连续槽；按 scheduled Block
  顺序扫描，每条指令先 operand 后 result，变量第一次出现即固定布局。未被任何
  Block 触及的变量按 VariableId 追加；变量内部 word/element 顺序及窄值、real、
  string 池不变。默认 off 时仍使用原 VariableId 布局。
- **假设**：首触布局通过收缩活跃状态跨度和页足迹，使 Host 中位相对 e00010 至少
  改善 3%，同时保持全部功能门；若不成立则关闭布局轴。
- CLI、文档、model counters、单元测试和生成模型语义测试随候选提交；未改变 GRH
  IR 或 AM 指令语义。

### 机制互异性

c1 减少每轮调度适配器对静默 source-part 的动态调用/扫描；c2 不改变执行次数，
只改善被执行代码访问宽状态时的物理局部性。前者作用于活动调度控制流，后者作用于
状态数据布局，机制和主要微架构成本均不同。

## 正式评估前证据

c2 在冻结的 XiangShan exec-GRH 上给出以下静态模型；这些计数只描述 footprint，
不冒充动态 cache/TLB miss：

| 指标 | VariableId 布局 | first-touch 布局 | 变化 |
|---|---:|---:|---:|
| Block 去重后的宽变量首 cache-line 总数（8 种基址余量平均） | 161,680 | 151,616 | **-6.22%** |
| Block-touched 变量覆盖跨度（word） | 24,304,307 | 8,347,000 | **-65.66%** |
| Block-touched 变量覆盖 4 KiB page | 17,661 | 16,303 | **-7.69%** |

419,243 个宽变量中 191,955 个被 scheduled Block 触及（45.79%）；其余按 ID 稳定
追加。该模型超过本轮 3% 正式评估门槛，故执行 e00016。实施期 focused
`grhsim-am-cpp-emitter` 测试通过；两候选 worktree 评估前均 clean 且已提交。

## 正式结果

共同对照 e00010 = 273.258s（t0/s02 tip，branchy-mux + resize-elision）。

| eval | 候选 | status / gates | compile_s | Host reps（ms） | 中位 / CV | 相对 e00010 |
|---|---|---|---:|---|---|---:|
| e00015 | c1 source-part activity guard | ok；ctest 17/17；3 rep difftest 全过 | 603.7s | 247051 / 247458 / 250751 | **247.458s / 0.82%** | **-9.44%** |
| e00016 | c2 wide-storage first-touch | ok；ctest 17/17；3 rep difftest 全过 | 590.9s | 260783 / 254867 / 257443 | **257.443s / 1.15%** | **-5.79%** |

所有 rep 均为 `instrCnt=73,580`、`cycleCnt=49,996`、进程 rc=0 且 nemu 在线
difftest 无 mismatch。两候选 compile_s 均远低于 2400s 门：init-zero-elision
继续把 e00010 的 1741.9s 编译路径压回约 10min，使本 step 的运行时问题不再被
init() 单 TU 编译成本遮蔽。

e00016 首次 configure 因受限网络无法 FetchContent；正式评估前只从同 run 的
e00010 CMake cache 复制 WHFC/parlay 这两个已 pin 的依赖源，并以
`FETCHCONTENT_FULLY_DISCONNECTED=ON` 完成配置。正式 evaluator 仍独占全局 lock，
未与其他构建/仿真并发，测量输入、编译参数和功能门均未改变。

## 机制分析

### c1：确认，首次收回一阶 source-part 扫描成本

- 9.44% 改善远高于本机约 2% 的谨慎裁决带，且 CV 仅 0.82%；这不是此前亚 1%
  emit 微调的布局彩票。它也是 r001 首个干净达到至少 5% 的候选。
- 334 个静态 part 调用原本即使整段无活动 Block，也要进入函数并逐 activity byte
  扫描。64-bit 区间预检把这部分成本降为少量活动字 load；静默段直接返回，活跃段
  仍走原消费/clear/relay 路径。收益说明残余的“2.87x instr/atom 适配胶”中，
  source-part 调用与空扫描是实质组成，而不只是纸面固定开销。
- 精确首尾 mask 与同轮传播测试守住了跨 part、跨 compute/commit 相位边界；正式
  difftest 再覆盖完整 50k 周期窗。假设完整成立。

### c2：确认，宽状态物理局部性是有效轴

- first-touch 将 Block-touched 宽状态的地址跨度收缩 65.66%、page 并集缩小
  7.69%，最终取得 5.79% 干净运行时改善。此前亲和布局两次只有
  compile_timeout，未产生运行时证据；e00016 是本 run 首次证明状态 gather/locality
  可以达到一阶收益。
- 首 cache-line 计数只降 6.22%，而 Host 降 5.79%，量级相符但不能据此宣称单一
  cache miss 因果；跨度/page 收缩也可能同时改善 TLB、预取和相邻块工作集复用。
  需要硬件计数器或离线采样才能继续拆分。
- 该轴未被关闭：假设门已通过。它未成为 winner 只因 c1 收益更大，不代表布局
  机制无效。

### c1 与 c2 对比

两候选共享 branchy-mux、resize-elision、init-zero-elision，正式 compile_s 也只差
2.1%，因此 9.985s 的中位差主要对应 guard 与 first-touch 两个新增机制。c1 比 c2
快 **3.88%**（反向看 c2 比 c1 慢 4.03%）：当前负载上，避免静默 part 的重复控制
流开销比只改善宽状态访问局部性更有杠杆。两者同时为正，不能从本 step 推断组合
是否可加。

## 裁决与 run 影响

winner = **e00015**（score `-247458`），机械裁决与机制裁决一致；已 fast-forward
到 `tes/r001/t0/main`（commit `96b8df2`），同时成为新的 t0 best 和 run
best_overall。相对 AM y0 273.103s 改善 **9.39%**；相对 gsim 24.688s 仍为
**10.02x**，AM/gsim 绝对差距关闭 **10.32%**。t0 完成 3/8 step，run 已用
16/48 eval。

## 对 Phi 下一步的建议

1. 当搜索再次回到 t0 时，优先检验 c1 guard 与 c2 first-touch 的组合。两者在同一
   轨迹内均越过 3% 门且机制正交，但必须写成新的可证伪假设，不能预设 9.44% 与
   5.79% 可加。
2. source-part 方向若继续细化，应先离线统计各 part 的动态 guard 命中率、活动字
   扫描长度与累计跳过次数，再决定是否调整 part 边界；不凭静态 334 个调用点盲调
   `blocks-per-source`。
3. 布局轴保留给“与 winner 组合”或有动态 locality 证据的定向变体；first-touch
   已完成一次广覆盖重排，不再为另一种无计数支撑的通用排列消耗正式 eval。
4. 状态机下一 action 是 `r001/t1/s03`。上述结论只供未来 t0 或 restart 使用；
   `cross_trajectory=false` 下不得把它们注入下一条 t1 proposal 的候选决策。
