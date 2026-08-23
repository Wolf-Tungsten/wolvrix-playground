# TES 运行规则

约束 tes/ 目录的记录方式与实验执行纪律（方法层，任务无关；各任务自己的门定义与
操作细节在 `tes/<task>/` 内）。范式沿用 `pdocs/grh-notepad/RULES.md` 的
append-only 精神，差异：tes/ 是机器可读的执行状态 + 人读的分析记录的混合系统。

## 1. 测量纪律（硬约束，由 evaluate.py 强制执行的部分不赘述）

- 评估严格串行：`build/tes/LOCK` 全局 flock（跨任务也只允许一个评估）；每个计时
  批次起跑前检查无其他 `emu` 进程，有则中止（批内并行 rep 是本评估自身负载）。
- 计时 reps（r004 起为簇结构自适应）：`taskset` 绑核（每 rep 一个独立物理核、批内
  并行，核清单由任务 config 指定）；初始 rep 数在 run-init 时冻结（`eval.reps`），
  检出双峰（`eval.cluster_ratio` 倍率缝隙）才自动加跑至 ≤ `eval.reps_max`；
  **score = 快簇中位**，弃用跨簇 median（r002 双态教训：跨簇 median 是 artifact
  且可反转 winner）。超过任务噪声阈值（CV 超标或 degraded）则标 `noisy`（分数可用
  但必须在分析中注明）。整批慢态嫌疑用任务 evaluator 的 `retime` 子命令补测
  （不重建、不占预算、保留历史）。
- 协变量采样：每 rep 1Hz 只读采样 smaps_rollup/numa_maps（r002 已验证只读监视与
  计时纪律兼容），用于簇根因分析；这不是 emu 插桩。
- 计数与计时分离：正式计时 reps 不开 `EMU_RUNTIME_PROFILE`/`EMU_AM_BLOCK_EXECS` 等
  插桩；profiling 如需做，走 recon action（不计时的分析 pass，见 §4）。
- 构建负载与计时严格分离：评估内任何并行构建完成后才进入计时阶段；goal 会话不得
  在评估计时阶段发起任何其他编译/仿真任务。
- 门不可协商：各任务的功能门/回归门/预算门定义在任务层（brief.md + protocol.md +
  config.json），由任务 evaluator 硬执行；未过门的候选无论分数多好都判失败。
  门的豁免条款（若有）只能写在任务 playbook 里并同步记录到 insights.md。

## 2. 状态与记录规则

- `tes/<task>/state/ledger.jsonl` **只追加**：评估结果、commit-marker 一经写入不得
  修改；修正以新条目 + 勘误说明形式追加。
- `tes/<task>/state/run.json` 只能由 tesctl.py 或 phi.py 写；人/agent 不手改
  （唯一例外：run-init 时回填 `pins.inputs[].sha256`，见 playbook）。
- action 笔记：`tes/<task>/actions/Axxxx_<类型>_<主题>_<YYYYMMDD>.md`，Axxxx 按任务
  递增、不复用；内容 = 本 action 做了什么、各候选结果、裁决、机制分析、对下一 step 的
  建议。追加不覆盖，同 pdocs 惯例。
- proposal、manifest 生成后不修改（快照语义）。
- 每个 action 结束时：更新 `tes/<task>/README.md` 状态速览与 `tes/README.md` 任务索引
  → `action-done` 登记 → 在 playground 当前分支提交 tes/（前缀 `tes(<task>/<run>):`）。
- 链接一律相对路径；命令示例里的绝对路径保持文本形式（同 pdocs 规则）。

## 3. git 纪律

- 目标仓库的 tes 分支只按 DESIGN.md §5 的命名模型创建；轨迹主线只用 `branch -f` 移动，
  永不 checkout 到任何 worktree（候选分支才允许 checkout）。worktree 一律在
  `build/tes/<task>/src/` 下。
- 不在 tes 流程里改动目标仓库的主 checkout（属于用户开发现场）。
- 不 push、不删分支、不删 worktree，除非用户当场确认。
- manifest `pins.repos` 里的仓库只读引用，不在 tes 流程里修改；若必须改，走 tes 之外
  的既有人工流程并在任务 insights.md 记录。
- playground 不开分支；tes/ 的提交不 bump 任何 submodule 指针。

## 4. 忠实性规则（对 SimpleTES 语义的守护）

- run 内轨迹独立（限 round 1 与 Φ proposal 构造）：Φ 的 proposal 只含本轨迹节点；
  round-summary 不回流进 proposal。**迁移席位例外（r004 起）**：step ≥ 2 的 K 席中
  至多 1 席可引用其他轨迹的**已确认机制**（假设写明来源 eval，登记
  `record-eval --migration-source`，ledger 存 `migration_source`）。r002 实践证明
  迁移是最高产通道之一；显式化使该信息通道可审计，而非假装不存在。
- recon 是正式协议 action（不占 eval 预算）：轨迹距上次 recon ≥ 2 步（或无 recon）
  时状态机先出 recon 再出 step；候选的病灶证据必须引用 recon 动态权重，静态计数
  只作辅证。
- K 个候选必须机制互异；若实在想不出第二个机制，候选可以是「任务暴露的调参旋钮组合」或
  「同一机制的不同实现策略」，但必须在 action 笔记里说明多样性妥协。
- K 是 Φ 所选历史节点邻域内的局部采样。每个候选必须给出“来源节点 → 已观测反馈/病灶 →
  本次改动 → 可证伪预期”的连续证据链；无证据的大跨度换向不得占用当前 step。
- 每个 K 席位都必须是有性能假设的实质候选。原样重测、空提交安慰剂和固定对照组不得占用
  搜索席位；测量校准（如基线中段重锚 retime）作为明确批准的协议动作处理。
- 表型声明硬前置：每个候选 commit 必须随附 `tes-candidate.json`（声明 emit_args 增删）；
  record-eval 审计声明与实际表型的一致性，不符拒绝登记（r003 表型漏传教训）。
- rejected / failed 只来自 TES ledger 中实际评估的候选。TES 外文档的失败记录只是先验，
  不得直接标为负方向或据此关闭搜索；先前实现不充分、输入变化或新机制均可触发 TES 内复验。
- 预算用尽（evals = N）或 L 步跑完即 run-summary；不得在 run 中途改 C/L/K。
- 失败候选同样是信息：必须登记 ledger 并在失败摘要中可见，不许悄悄丢弃。
