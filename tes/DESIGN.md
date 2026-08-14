# TES 设计：SimpleTES 到 grhsim-am 性能调优的映射

本文是 tes/ 实验系统的设计依据。方法来源：arXiv:2604.19341v2《Structured Scaling of AI
Discovery Across Diverse Scientific Domains》（SimpleTES 框架，本地副本 `ptmp/2604.19341.pdf`）。

## 1. 论文要点（与本系统相关的部分）

SimpleTES 把「评估驱动的发现循环」组织为设计元组 **(C, L, K, Φ)**：

- **C**：全局宽度——C 条相互独立的搜索轨迹并行推进，对抗早期方向锁定（Matthew 效应）。
- **L**：每条轨迹的精修深度——反馈在同一条轨迹内逐步累积。
- **K**：局部采样数——每步从同一 proposal 采 K 个候选，只把最高分的提交进轨迹历史，
  防止弱候选污染后续精修（局部承诺风险）。
- **Φ**：proposal 构造器——从轨迹历史 S 中选出哪些节点进入下一次 prompt。
  论文默认实现是 RPUCG（图版 PUCT）：节点维护传播值
  `U_i = max(r_i, γ·max_{j∈Ch(i)} U_j)`，按 `RPUCG(i) = U_i + λ·ρ_i·√(1+|S|)/(1+n_i)`
  贪心选择并排除一跳邻居；同时把反复出现的失败模式摘要折入 prompt。
- 预算 `N = C×L×K` 次评估查询；论文默认 32/100/16。
- 分配经验：依赖「质性不同方法」的问题宜大 C；增量工程精修主导的问题（如 GPU kernel
  优化）宜大 L；K 保持适中。
- **best-solution restart**：整轮跑完后用最佳解作为下一轮的 y0（论文观察到第 2、3 次
  restart 后饱和，主实验只多做一轮 restart）。

## 2. 问题映射

| SimpleTES 概念 | 本系统实例 |
|---|---|
| 解 y | wolvrix 仓库的一个 commit（tes 候选分支）+ 可选 emit 参数覆盖 |
| 评估器 V | `tes/grhsim-am-coremark/evaluator.py`：wolvrix 构建 → ctest 回归门 → 固定 exec-GRH emit → difftest emu 构建 → 绑核 3-rep 计时；返回 (score, 反馈) |
| 分数 r | `-median_host_ms`（越高越好）；辅助列：emu 构建耗时、noisy 标记 |
| 反馈 m | 逐 rep host_ms / difftest 计数 / 负载；失败时的阶段（build/emit/ctest/timeout）与日志指针 |
| 指令 x0 | `tes/grhsim-am-coremark/brief.md`（目标、硬约束、已知机制背景），run 期间冻结 |
| 目标 | `ratio = am_median / gsim_median ≤ 1.0`（基线于 run-init 同协议实测冻结） |
| LLM G | 推进 tes 的 goal 会话本身（按 proposal 设计 K 个候选并实施） |
| 初始解 y0 | run 起点 commit（r001 = `grh/dev-grhsim-topo-partition` tip，即 NO0018 收口态） |

候选生成时「K 个候选互不相同」指**机制层面不同**（不同的病灶假设/不同的变换手段/
代码修改 vs 纯 emit 旋钮组合均可），不是同一修改的参数微调——这才对应论文里 K 抵抗
生成噪声的本意。

## 3. 串行等价论证（为什么串行不损失论文语义）

本机实验相互干扰（计时污染有前科：supernode-align NO0017），不能并行跑评估。SimpleTES
的 C 条轨迹**按设计就是相互独立的**：轨迹各自维护 S，run 内无跨轨迹信息流（跨轨迹学习
只通过 run 之间的 restart 发生）。因此把 C 条轨迹的并行推进替换为**逐轮 round-robin 串行
推进**（每条轨迹各走一步为一轮），只要满足两点即与原语义等价：

1. 每条轨迹的 proposal 只看自己的历史（`phi.cross_trajectory=false`，默认）；
2. 评估结果不被机器状态污染（由测量纪律保证，见 RULES.md，由任务 evaluator.py 的
   flock + 干扰守卫 + 绑核 + CV 检查硬执行）。

串行反而带来两个实务收益：任何时刻只有一个构建/测量负载（可复现）；goal 粒度天然
对齐 action 粒度（无状态工作流）。

## 4. 无状态工作流与 action 模型

系统本身不持有内存：全部状态在任务目录下——`tes/<task>/state/run.json` +
`tes/<task>/state/ledger.jsonl`（append-only）+ `tes/<task>/runs/<run>/manifest.json`。
每次推进由 `/goal tes/goal.md` 驱动：goal 会话执行 `tesctl.py next` 算出的**恰好一个**
action（流程见 `tes/playbook.md`）后停止。

**多任务**：`tes/` 下每个含 `config.json` 的一级子目录是一个独立任务，自带
brief/config/evaluator.py/state/actions/proposals/runs。任务间共享：调度器
（tesctl.py --task）、Φ（phi.py --task）、全局串行锁 `build/tes/LOCK`（测量干扰是
机器级的）与 ccache `build/tes/ccache/`。任何时刻全机器只允许一个评估在跑，与任务数无关。

Action 类型（括号内为评估查询开销）：

| action | 内容 | 开销 |
|---|---|---|
| `run-init` | 冻结配置、pin 三仓库 commit、建分支、快照输入指纹、测 AM y0 与 gsim target 双基线 | 2 + ~1h |
| `step` | Φ 出 proposal → 设计并实施 K 个候选 → 串行评估 → winner 合入轨迹主线 → 分析 | K（~40min/候选）|
| `round-summary` | 一轮齐平后跨轨迹对比、追加 insights.md | 0 |
| `run-summary` | L 步跑完后的总结与 restart 裁决建议 | 0 |
| `restart` | 以上一 run 最佳解为 y0 开新 run（受 restart.max/auto 约束） | 新 run |

中断恢复：step 内每个候选评估完成即落 ledger；goal 中断后下一个 goal 以
`step-resume` 续跑剩余候选，不重跑已完成者。

## 5. 分支模型（任务目标仓库；playground 不开分支）

分支建在任务的目标仓库（config `repos.target`，当前任务为 `wolvrix`）。
命名规范（全部带 `tes/` 前缀，避免与开发分支混淆）：

- `tes/<run>/base` —— run 起点快照，run 期间不移动。例：`tes/r001/base`
- `tes/<run>/t<i>/main` —— 轨迹主线（i = 0..C-1）。每个被提交的 step = 其 winner 候选的
  tip，用 `git branch -f` 快移指针（主线从不被 checkout）。例：`tes/r001/t0/main`
  （主线带 `main` 叶是因为 git ref 不能同时作文件与目录：`tes/r001/t0` 与
  `tes/r001/t0/s01-c1` 无法共存。）
- `tes/<run>/t<i>/s<NN>-c<k>` —— 候选分支，从主线 tip 切出。例：`tes/r001/t0/s01-c2`

提交信息：`tes(r001/t0/s01): c1 <一句话假设>`；winner 合入后主线 tip 即该 commit。

保留策略：败者分支 run 期间一律保留（可复现）；run 收口时可 `format-patch` 归档进
`tes/<task>/runs/<run>/archive/` 后删分支（删分支属破坏性操作，需用户确认）。worktree
放在 `build/tes/<task>/src/`（playground 已 gitignore build/），评估产物在
`build/tes/<task>/evals/e*`。

playground 仓库：不开分支，tes/ 的每次状态推进在当期分支（`grh/tes-grhsim-am`）提交，
信息前缀 `tes(<task>/<run>): ...`。wolvrix  submodule 指针在 playground 侧保持指向开发
分支的正式 commit，不随 tes 实验分支移动；实验现场由 ledger 里的 commit sha + 分支名
锚定。tes 分支均为本地分支，推送与否由用户另行决定。
（分支名不含任务名：分支空间属于 wolvrix 仓库，run_id 已与任务绑定——若未来多个任务
共用 wolvrix 且 run_id 冲突，再引入 `tes/<task>/<run>/...` 前缀。）

## 6. Φ 的本系统实例化

- S = 本轨迹的 root（am 基线）+ 各 step 的 winner（ledger 里 commit-marker 标记）。
- 分数先做 min-max 归一化再算 U 传播（论文公式里 U 与探索项量纲需一致；归一化是
  本系统的落地选择）。ρ = 分数名次分位；n_i = 被选中次数（run.json 持久化）。
- 贪心选 max_nodes=4 个节点并排除一跳邻居；**轨迹主线 tip 强制纳入**（工程精修
  连续性要求，是对论文 Φ 的唯一增补）。
- proposal 另含：已否决变体清单（本轨迹评估成功但未中选者，避免原样重试）、失败模式
  摘要（build/emit/difftest/timeout 各自的假设与日志指针）、评估协议与 emit 旋钮基线。
- proposal 快照存 `tes/<task>/proposals/`，候选分支与 proposal 的父子边记进 ledger
  （`proposal_nodes`），供 RPUCG 的 Ch(i) 传播使用。

## 7. 默认参数与预算

C=3, L=8, K=2 → N=48 次评估，串行约 32 机时。理由：本问题为增量工程精修主导
（论文建议 L 重），单次评估 ~35-50min 决定了 K 必须小；C=3 提供方向多样性下限。
参数在 `tes/<task>/config.json` 改，run-init 冻结进 manifest，run 期间不可变（改动即新 run）。
（预算口径：N 只计搜索评估；run-init 的基线测量额外计入 evals 计数。）

## 8. 与既有纪律的关系

tes/ 不取代 pdocs/ 笔记体系：pdocs/grh-notepad/emit-cost 是面向机制的归因记录，
tes/ 是面向搜索的执行系统。action 笔记引用 pdocs 结论用相对路径；重大机制发现应同时
按 pdocs 规则另立 NO 记录（在 action 笔记里互相链接）。
