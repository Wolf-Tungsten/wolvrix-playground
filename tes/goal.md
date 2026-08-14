# TES 推进 goal

> 用法：`/goal tes/goal.md`。每个 goal 把 tes/ 实验系统推进**恰好一个 action**，完成后停止。
> 系统设计：`tes/DESIGN.md`；纪律：`tes/RULES.md`；各 action 的操作步骤：`tes/playbook.md`。

## 目标

推进 tes/ 的结构化性能搜索：读取当前状态，执行 `tesctl.py next` 给出的唯一 action
（step / step-resume / finish-step / baseline / round-summary / run-summary / run-init 之一），
把结果与分析落到 tes/，提交 playground，然后停止。**不得自发开始下一个 action。**

## 固定流程

1. 读状态：
   - `python3 tes/tools/tesctl.py status`
   - `python3 tes/tools/tesctl.py next --json`
   - 若报多任务歧义：用 `--task` 指定用户在本 goal 上下文中指明的任务；未指明则询问用户。
2. 按 action 类型执行 `tes/playbook.md` 中对应那一节（也只那一节）。
   `step-resume` 复用 step 一节，只补做 pending 候选。
3. 写 action 笔记 `tes/<task>/actions/Axxxx_<类型>_<主题>_<YYYYMMDD>.md`
   （编号取该任务 actions/ 现有最大值 +1）：做了什么、各候选/评估的量化结果、裁决、
   机制分析、对下一步的建议。
4. 更新 `tes/<task>/README.md` 的「当前状态速览」与 `tes/README.md` 的任务索引行。
5. 登记：`python3 tes/tools/tesctl.py action-done --type <类型> --note tes/<task>/actions/Axxxx_....md`。
6. 提交 playground 当前分支（不 bump 任何 submodule 指针）：
   `git add tes/ && git commit -m "tes(<task>/<run>): <一句话>"`。
7. 向用户汇报本 action 结果与下一个 action 预告，停止。

## 完成判据

上述 1-7 全部完成，即 goal 达成。任一环节失败且 playbook 无恢复路径时，
把现场与失败原因写进 action 笔记并提交，然后报告阻塞——不许绕过状态机手工修补
`run.json`（唯一例外：run-init 里回填 `pins.inputs[].sha256`，见 playbook）。

## 绝对纪律（违反即破坏实验有效性）

- 评估严格串行：只走任务自带的 `tes/<task>/evaluator.py`（内置 flock + 干扰守卫 +
  绑核 + 任务功能门）。不得手工跑计时，不得在评估计时阶段并发任何构建/仿真负载。
- 功能门一票否决：未过任务功能门（见任务 brief/protocol，evaluator 硬执行）的候选
  无论分数多好都判失败。
- run 内轨迹独立：proposal 不引用其他轨迹的结果；跨轨迹学习只发生在 restart。
- 任务目标仓库（config `repos.target`）的主 checkout 是用户开发现场，tes 一律在
  `build/tes/<task>/src/` 的 worktree 里动代码。
- 不 push、不删分支/worktree、不改 manifest 里 pin 的只读仓库，除非用户当场确认。
- ledger.jsonl 只追加；action 笔记只追加；manifest/proposal 不修改。
- 一个 goal 只推进一个 action。
