# TES 运行规则

约束 tes/ 目录的记录方式与实验执行纪律。范式沿用 `pdocs/grh-notepad/RULES.md` 的
append-only 精神，差异：tes/ 是机器可读的执行状态 + 人读的分析记录的混合系统。

## 1. 测量纪律（硬约束，由 evaluate.py 强制执行的部分不赘述）

- 评估严格串行：`build/tes/LOCK` 全局 flock（跨任务也只允许一个评估）；计时阶段前
  检查无其他 `emu` 进程，有则中止。
- 计时 reps：`taskset -c <core>` 绑核，默认 3 次取中位，CV>5% 自动加测至 5 次，
  仍超则标 `noisy`（分数可用但必须在分析中注明）。
- 计数与计时分离：正式计时 reps 不开 `EMU_RUNTIME_PROFILE`/`EMU_AM_BLOCK_EXECS` 等
  插桩；profiling 如需做，另开不计时的分析 pass。
- 构建负载与计时严格分离：评估内任何并行构建完成后才进入计时阶段；goal 会话不得
  在评估计时阶段发起任何其他编译/仿真任务。
- 功能门不可协商：每 rep 退出码 0 且计数等于任务 config 的 golden（本任务
  instrCnt=73,580 / cycleCnt=49,996），否则候选判 `difftest_fail`，无论多快都不得入选。
- 回归门：`ctest -R grhsim` 全绿。既有失败项（transform-comb-lane-pack / repcut）
  与 grhsim 无关，不在门内；新增失败即 `ctest_fail`。

## 2. 状态与记录规则

- `tes/<task>/state/ledger.jsonl` **只追加**：评估结果、commit-marker 一经写入不得
  修改；修正以新条目 + 勘误说明形式追加。
- `tes/<task>/state/run.json` 只能由 tesctl.py 或 phi.py 写；人/agent 不手改
  （唯一例外：run-init 时补写 `pins.exec_json_sha256`，见 playbook）。
- action 笔记：`tes/<task>/actions/Axxxx_<类型>_<主题>_<YYYYMMDD>.md`，Axxxx 按任务
  递增、不复用；内容 = 本 action 做了什么、各候选结果、裁决、机制分析、对下一 step 的
  建议。追加不覆盖，同 pdocs 惯例。
- proposal、manifest 生成后不修改（快照语义）。
- 每个 action 结束时：更新 `tes/<task>/README.md` 状态速览与 `tes/README.md` 任务索引
  → `action-done` 登记 → 在 playground 当前分支提交 tes/（前缀 `tes(<task>/<run>):`）。
- 链接一律相对路径；命令示例里的绝对路径保持文本形式（同 pdocs 规则）。

## 3. git 纪律

- wolvrix 分支只按 DESIGN.md §5 的命名模型创建；轨迹主线只用 `branch -f` 移动，
  永不 checkout 到任何 worktree（候选分支才允许 checkout）。worktree 一律在
  `build/tes/<task>/src/` 下。
- 不在 tes 流程里改动 wolvrix 主工作目录（`wolvrix/` 的 checkout 属于用户开发现场）。
- 不 push、不删分支、不删 worktree，除非用户当场确认。
- reference/gsim 与 testcase/xiangshan 只读引用（pin commit 记录进 manifest），不在
  tes 流程里修改它们；若必须改 gsim（如加插桩），走 pdocs 既有人工流程。
- playground 不开分支；tes/ 的提交不 bump wolvrix submodule 指针。

## 4. 忠实性规则（对 SimpleTES 语义的守护）

- run 内轨迹独立：proposal 不得引用其他轨迹的评估结果（round-summary 是给人看的，
  不回流进 proposal）。跨轨迹学习只发生在 restart。
- K 个候选必须机制互异；若实在想不出第二个机制，候选可以是「emit 旋钮组合」或
  「同一机制的不同实现策略」，但必须在 action 笔记里说明多样性妥协。
- 预算用尽（evals = N）或 L 步跑完即 run-summary；不得在 run 中途改 C/L/K。
- 失败候选同样是信息：必须登记 ledger 并在失败摘要中可见，不许悄悄丢弃。
