# run r003 总结（grhsim-am-coremark）

收口日期：2026-08-23。C=2, L=8, K=2，16/16 步全部走满；候选 evals 32/32
耗尽（另含基线 e00051/e00052，总计 34 eval）。base/y0 = r002/e00007 完整解
`ecb4c3f3c6b2`（10 个冻结 emit 开关，分支 `tes/r003/base`）。输入继续使用
wolvrix 自解析 post-stats JSON（sha256 `cbd78c0b...3246`）。

## 结果总览

- 同协议基线：AM y0 = **363.995s**（e00051），gsim target = **45.864s**
  （e00052），起跑差距 **7.936x**。
- ledger best_overall = t0/e00057 **229.429s**，commit
  `1563c3d837fcfe9db28fc36901531a70b59fd790`；相对 AM 基线名义改善
  **36.97%**，但仍为 gsim 的 **5.002x**，剩余绝对差距 183.565s，目标未达成。
  t1 best = e00056 **241.956s**（5.276x gsim）。
- 健康度：32 个候选中 29 个 `ok`、3 个 `ctest_fail`（e00069/e00070/e00081）；
  全部 `ok` 候选通过 17/17 ctest、3 rep nemu difftest 和编译预算门。e00063/e00066
  为 noisy；e00073/e00074 与 e00075/e00076 虽为 `ok`，但候选开关/硬依赖漏传，
  已用 append-only correction 判为无效机制测量。
- 搜索收益集中在前两轮：t0/e00054 task body outline 与 e00057 scan hints、t1/e00056
  wide-mux chain fuse 建立两个轨迹 best；第 3 至第 8 轮均未刷新任一轨迹历史 best。

## 轨迹分数曲线（step raw winner 中位，秒）

| step | t0 | t1 |
|---|---|---|
| y0 | 363.995 (e00051) | 363.995 (e00051) |
| s01 | 247.560 (e00054) | **241.956 (e00056，t1 best)** |
| s02 | **229.429 (e00057，global best)** | 257.235 (e00059) |
| s03 | 251.746 (e00061) | 409.731 (e00064) |
| s04 | 409.869 (e00065) | 382.171 (e00067) |
| s05 | 无 winner（e00069/e00070 `ctest_fail`） | 339.910 (e00071) |
| s06 | 346.687 (e00074，表型无效) | 354.543 (e00076，表型无效) |
| s07 | 299.715 (e00078) | 345.215 (e00080) |
| s08 | 327.672 (e00082；e00081 `ctest_fail`) | 378.064 (e00084) |

表中是状态机 raw-score winner，不是跨窗因果排名。e00074/e00076 的 commit-marker
只表示机械合入，不能作为候选机制证据；t0/s05 全失败后主线不移动。跨评估窗口存在
约 1.3-1.4x 进程快慢态和持续 loadavg 差异，即使批内 CV=0 也不能直接相减。

## 机制族裁决

**保留的有效解材料**：

1. **task body outline + scan branch hints（t0）**：e00054 将 7,235 个非 final
   system-task 冷体抽为 noinline，e00057 再恢复已在 r002 同窗确认的扫描冷分支提示。
   e00057 较 e00054 名义再降 7.32%，两项组成 r003 最佳表型；r003 的 -31.99% 基线
   幅度受进程态混杂，不升级为机制净收益。
2. **wide-mux-chain-fuse（t1）**：e00056 融合 22528-bit broadcast-to-mux 相邻链，
   消除 352-word 中间数组并成为 t1 best。其正向性有 r002 同窗 -2.19%/-1.17%
   互证；r003 相对基线 -33.53% 同样不能当作纯机制幅度。
3. **局部 active-tile + nonzero-level 稀疏（方向性证据）**：e00067/e00071 在
   wide-mux 邻域依次保留连续 base 流、只重访实际非零 level；e00071 为 339.910s，
   紧邻 e00072 快 4.73%。它没有刷新 t1 best，跨 loadavg 幅度只记正向线索。

**关闭或要求新动态证据后才能重开**：

- scanner 的 ctz/switch、direct tree、nibble guard、prefix skip 与 byte hint 拆层均无
  新正向证据；保留 e00057 的 hinted 顺序扫描。重开须先量化 active word 内非零
  byte、首活跃 bit 和实际跳过测试数。
- task cold/compact/fire-hint 精修没有超过 outline 主机制；lazy member args 又败于
  ctest 契约。重开须先量化 fwrite fire 与参数准备动态权重，并用结构化 fixture
  固化局部/持久参数分类。
- wide-mux 的 priority resolve、全局 sparse overlay、固定层专化、selector summary
  reuse、幂等 store suppression 与 mask/value 栈缓存均未兑现；静态链数、selector
  共享度和 99.57% base-lane 比例都不是收益代理。重开须先取得 helper 动态 Host
  权重、active-tile 非零层分布或 target 词实际变化率。
- e00073-e00076 的表型漏传说明 `result.json.emit_args` 审计是候选有效性的硬前置；
  代码中存在 default-off 实现不等于生产表型启用。

## 测量与预算裁决

- r003 重测基线确认 r002/e00007 的 261.543s 是历史快态：同一完整解 e00051
  363.995s 与 r002 慢态锚 363.444s 仅差 0.15%。进程态问题贯穿本 run；e00063/e00066
  在固定 3 rep 内 noisy，更多候选则表现为批内 CV=0、跨批 loadavg/绝对时间大幅漂移。
- 因而 229.429s、5.002x 是 ledger/看板口径，不足以宣称累计机制加速 36.97%；可靠
  结论优先来自 r002 同窗互证和 r003 紧邻窗口的方向性比较。
- 29 个 ok、3 个 ctest_fail、4 个表型无效测量表明功能门稳定，但候选前置审计仍需
  加强。后六轮无新 best，继续按 L=8 深挖当前静态微结构邻域的边际收益已经衰减。

## restart 建议

**不建议立即 restart。** r003 未达目标，但 config `restart.max=2` 已被 r001->r002
与 r002->r003 两次 restart 耗尽，`auto=false`；更关键的是第 3-8 轮没有刷新轨迹 best，
wide-mux/scanner/task 三个邻域已收敛为“先补动态权重”，而进程快慢态仍使跨窗百分比
不可裁。run 收口后应停在无活跃 run，等待用户决定是结束该搜索，还是另行批准协议修复
和新预算。

若用户之后明确放宽 restart 预算，预备 y0 为 **r003/e00057**：commit
`1563c3d837fcfe9db28fc36901531a70b59fd790`，完整表型 = 冻结 10 开关 +
`--sys-task-body-outline --scan-branch-hints`。建议新 **C=2, L=4, K=2（N=16）**：
保留两条机制轨迹与每步两个实质候选，但按本 run 收益集中于前两轮的事实缩短深度。
启动前必须先解决 rep 级进程态分簇/同窗锚定，并用非计时 profiling 为 compute 长尾或
wide-mux 动态热点提供候选依据；届时由新的 goal 执行
`init-run --base-eval r003/e00057 --C 2 --L 4 --K 2`，本 action 不启动它。
