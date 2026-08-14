---
name: tes
description: 推进 grhsim-am 性能调优的 SimpleTES 式结构化搜索——每次调用从 tes/ 读取状态，执行恰好一个 action（step/round-summary/run-init 等），记录结果后停止
type: prompt
whenToUse: 用户要求推进 tes 实验、执行 tes 的下一个 action、继续 grhsim-am 性能搜索时；或 goal 目标指向 tes/ 目录的实验进展时
---

# TES 无状态工作流

本 skill 是 tes/ 实验系统（`tes/DESIGN.md` + `tes/RULES.md`）的执行入口。**一个 goal 只推进
一个 action**，做完即停；不要自发开始下一个 action。系统无状态：所有进度都在
`tes/state/`、`tes/runs/` 的文件里，工具幂等可重入。

## 固定流程

1. 读状态：`python3 tes/tools/tesctl.py status` 与 `python3 tes/tools/tesctl.py next --json`。
2. 按 `next` 输出的 action 类型，执行 `${KIMI_SKILL_DIR}/references/playbook.md` 中对应的
   那一节（也只有那一节）。若 next 是 `step-resume`，执行 playbook 的 step 节但只补做
   pending 候选。
3. 写 action 笔记 `tes/actions/Axxxx_<类型>_<主题>_<YYYYMMDD>.md`（编号取 actions/
   现有最大值 +1），包含：做了什么、各候选/评估的量化结果、裁决、机制分析、下一步建议。
4. 更新 `tes/README.md` 的「当前状态速览」。
5. 登记：`python3 tes/tools/tesctl.py action-done --type <类型> --note tes/actions/Axxxx_....md`。
6. 提交 playground 当前分支（不 bump wolvrix submodule 指针）：
   `git add tes/ .agents/skills/tes/ && git commit -m "tes(<run>): <一句话>"`。
7. 向用户汇报本 action 结果与下一个 action 预告，然后停止。

## 绝对纪律（违反即破坏实验有效性）

- 评估严格串行：`tes/tools/evaluate.py` 自带 flock；不得绕过它手工跑计时，不得在
  评估计时阶段并发任何构建/仿真负载。
- 功能门一票否决：difftest 计数不符的候选无论多快都判失败。
- run 内轨迹独立：proposal 不引用其他轨迹的结果；跨轨迹学习只发生在 restart。
- wolvrix 主工作目录（`wolvrix/` checkout）是用户开发现场，tes 一律在
  `build/tes/src/` 的 worktree 里动代码。
- 不 push、不删分支/worktree、不改 `reference/gsim` 与 `testcase/xiangshan`，除非用户当场确认。
- ledger.jsonl 只追加；action 笔记只追加；manifest/proposal 不修改。
